"""Deterministic alert rules.

A rule is a function of numbers, not of a model's opinion: the same stored
scores and baselines produce the same finding, which is what makes an alert
explainable in a meeting a week later.

Four constraints shape the rules:

* **Compare a child with themselves.** The baseline is the child's own recent
  mean and standard deviation, never a class average. A child whose normal is
  low should not be flagged for being consistently themselves; a child whose
  normal is high should be flagged when they fall.
* **Confidence gates severity.** A one-day blip cannot become an urgent alert.
  Score rules require at least `moderate` confidence, and baseline rules require
  a minimum number of observed days.
* **Gaps are not declines.** A missing week breaks a "consecutive" rule instead
  of being read as a low value.
* **At most one overall-score alert per child per evaluation.** A child in
  serious difficulty can otherwise produce four differently-worded overall
  alerts, which makes the queue look worse without telling the mentor more.
  Domain-level findings and the guardian pulse remain separate, because they
  answer different questions.

The rules return `Finding` objects. Persisting them, assigning an owner and
de-duplicating across runs is `alerts.engine`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils import timezone

from analytics import scoring
from analytics.models import DomainScore
from feedback.models import PulseResponse

#: A baseline needs this many observed days before it may be used to call
#: something a deviation. Below this, the "baseline" is noise with a mean.
MIN_BASELINE_SAMPLE = 8
#: Ignore tiny spreads: with SD 2 a three-point move is statistically alarming
#: and practically meaningless.
MIN_BASELINE_SD = 5.0
DROP_SIGMA = 1.5
DECLINE_POINTS = 10.0
SUSTAINED_LOW = 45.0
TWO_DOMAIN_LOW = 50.0
URGENT_OVERALL_LOW = 35.0
PULSE_LOW = 2
PULSE_LOOKBACK_DAYS = 21

TIER_ORDER = {"watch": 1, "concern": 2, "urgent": 3}

#: Human-readable labels for the cohort page and the queue.
RULE_LABELS = {
    "overall_very_low": "Overall wellness very low",
    "overall_below_baseline": "Overall below usual range",
    "sustained_low": "Sustained low overall wellness",
    "declining_trend": "Declining over several weeks",
    "multiple_domains_low": "Several domains low at once",
    "no_recent_data": "No recent entries",
    "guardian_pulse_low": "Guardian reports difficult weeks",
    "safeguarding_signal": "Safeguarding signal in a note",
}


@dataclass(frozen=True)
class Finding:
    rule_key: str
    tier: str
    domain: str
    title: str
    summary: str
    evidence: dict


def _value(point) -> float | None:
    return point["value"] if point else None


def _confident(point, allowed=("moderate", "good")) -> bool:
    return point is not None and point.get("confidence") in allowed


def _latest(series):
    return next(
        (point for point in reversed(series) if point["value"] is not None), None
    )


def _overall_findings(child, as_of: date) -> list[Finding]:
    series = scoring.stored_series(child, scoring.OVERALL, as_of)
    latest = _latest(series)
    if latest is None:
        return []

    findings: list[Finding] = []
    baseline = scoring.baseline_for(child, scoring.OVERALL, as_of)
    usable_baseline = (
        baseline is not None
        and baseline.get("stddev") is not None
        and baseline["stddev"] >= MIN_BASELINE_SD
        and baseline["sample_size"] >= MIN_BASELINE_SAMPLE
    )

    # Urgent: two consecutive, reasonably-covered weeks at a very low level.
    last_two = series[-2:]
    if len(series) >= 2 and all(
        point["value"] is not None
        and point["value"] <= URGENT_OVERALL_LOW
        and _confident(point)
        for point in last_two
    ):
        findings.append(
            Finding(
                rule_key="overall_very_low",
                tier="urgent",
                domain=scoring.OVERALL,
                title="Overall wellness is very low in consecutive weeks",
                summary=(
                    f"Overall wellness was {last_two[0]['value']:.1f} and then "
                    f"{last_two[1]['value']:.1f} out of 100 in the last two "
                    "seven-day windows, with enough data to be reliable. "
                    "This needs a named person to review it today."
                ),
                evidence={
                    "values": [last_two[0]["value"], last_two[1]["value"]],
                    "periods": [
                        str(last_two[0]["period_end"]),
                        str(last_two[1]["period_end"]),
                    ],
                    "threshold": URGENT_OVERALL_LOW,
                },
            )
        )

    if usable_baseline:
        threshold = baseline["mean"] - DROP_SIGMA * baseline["stddev"]
        if latest["value"] <= threshold and _confident(latest):
            findings.append(
                Finding(
                    rule_key="overall_below_baseline",
                    tier="concern",
                    domain=scoring.OVERALL,
                    title="Overall wellness is below this child's usual range",
                    summary=(
                        f"The latest overall score is {latest['value']:.1f}, "
                        f"against a recent usual range of {baseline['mean']:.1f} "
                        f"± {baseline['stddev']:.1f}. That is more than "
                        f"{DROP_SIGMA:g} standard deviations below their own baseline."
                    ),
                    evidence={
                        "latest": latest["value"],
                        "baseline_mean": baseline["mean"],
                        "baseline_stddev": baseline["stddev"],
                        "baseline_sample": baseline["sample_size"],
                        "threshold": round(threshold, 2),
                        "confidence": latest["confidence"],
                    },
                )
            )

    if len(series) >= 3 and all(
        point["value"] is not None
        and point["value"] <= SUSTAINED_LOW
        and _confident(point)
        for point in series[-3:]
    ):
        findings.append(
            Finding(
                rule_key="sustained_low",
                tier="concern",
                domain=scoring.OVERALL,
                title="Overall wellness has been low for three weeks",
                summary=(
                    "The overall score has stayed at or below "
                    f"{SUSTAINED_LOW:.0f} out of 100 for three consecutive "
                    "seven-day windows. A single low week can be an ordinary "
                    "bad week; three is a pattern."
                ),
                evidence={
                    "values": [point["value"] for point in series[-3:]],
                    "periods": [str(point["period_end"]) for point in series[-3:]],
                    "threshold": SUSTAINED_LOW,
                },
            )
        )

    # Compare with three windows earlier: week-to-week noise is large, and a
    # four-week comparison is the shortest one that is still a trend.
    latest_index = next(
        index for index, point in enumerate(series) if point is latest
    )
    if latest_index >= 3:
        earlier = series[latest_index - 3]
        if (
            earlier["value"] is not None
            and _confident(earlier)
            and _confident(latest)
            and latest["value"] - earlier["value"] <= -DECLINE_POINTS
        ):
            findings.append(
                Finding(
                    rule_key="declining_trend",
                    tier="watch",
                    domain=scoring.OVERALL,
                    title="Overall wellness has declined over four weeks",
                    summary=(
                        f"The latest score ({latest['value']:.1f}) is "
                        f"{abs(latest['value'] - earlier['value']):.1f} points "
                        f"below the score four weeks earlier "
                        f"({earlier['value']:.1f})."
                    ),
                    evidence={
                        "latest": latest["value"],
                        "earlier": earlier["value"],
                        "change": round(latest["value"] - earlier["value"], 2),
                        "earlier_period": str(earlier["period_end"]),
                        "threshold": -DECLINE_POINTS,
                    },
                )
            )

    # Prefer the most severe overall finding only. Multiple overall alerts for
    # one child in one run add noise, not information.
    if not findings:
        return []
    return [max(findings, key=lambda finding: TIER_ORDER[finding.tier])]


def _domain_findings(child, as_of: date) -> list[Finding]:
    findings: list[Finding] = []
    low_domains = []

    for domain in scoring.DOMAINS:
        series = scoring.stored_series(child, domain, as_of)
        latest = _latest(series)
        if latest is None:
            continue

        label = scoring.DOMAIN_LABELS[domain]
        if latest["value"] <= TWO_DOMAIN_LOW and _confident(latest):
            low_domains.append(
                {"domain": domain, "label": label, "value": latest["value"]}
            )

        baseline = scoring.baseline_for(child, domain, as_of)
        if (
            baseline is None
            or baseline.get("stddev") is None
            or baseline["stddev"] < MIN_BASELINE_SD
            or baseline["sample_size"] < MIN_BASELINE_SAMPLE
            or not _confident(latest)
        ):
            continue

        threshold = baseline["mean"] - DROP_SIGMA * baseline["stddev"]
        if latest["value"] <= threshold:
            findings.append(
                Finding(
                    rule_key=f"domain_below_baseline:{domain}",
                    tier="watch",
                    domain=domain,
                    title=f"{label} is below this child's usual range",
                    summary=(
                        f"The latest {label.lower()} score is "
                        f"{latest['value']:.1f}, against a recent usual range of "
                        f"{baseline['mean']:.1f} ± {baseline['stddev']:.1f}."
                    ),
                    evidence={
                        "domain": domain,
                        "latest": latest["value"],
                        "baseline_mean": baseline["mean"],
                        "baseline_stddev": baseline["stddev"],
                        "baseline_sample": baseline["sample_size"],
                        "threshold": round(threshold, 2),
                    },
                )
            )

    if len(low_domains) >= 2:
        findings.append(
            Finding(
                rule_key="multiple_domains_low",
                tier="concern",
                domain="",
                title="Several wellness domains are low at the same time",
                summary=(
                    "These domains all scored at or below "
                    f"{TWO_DOMAIN_LOW:.0f} out of 100 in the latest window: "
                    + ", ".join(
                        f"{row['label'].lower()} ({row['value']:.1f})"
                        for row in low_domains
                    )
                    + ". Difficulty in several areas at once is worth a "
                    "coordinated look rather than four separate ones."
                ),
                evidence={"domains": low_domains, "threshold": TWO_DOMAIN_LOW},
            )
        )

    return findings


def _no_data_finding(child, as_of: date) -> Finding | None:
    has_current = DomainScore.objects.filter(
        child=child, period_end=as_of
    ).exists()
    if has_current:
        return None
    has_history = DomainScore.objects.filter(
        child=child, period_end__gte=as_of - timedelta(days=scoring.WINDOW_DAYS)
    ).exists()
    if not has_history:
        # Never measured. That is a data-quality problem for the school, not a
        # wellness signal about the child.
        return None
    return Finding(
        rule_key="no_recent_data",
        tier="watch",
        domain="",
        title="No wellness entries in the latest week",
        summary=(
            "This child has entries earlier in the eight-week window but none "
            "in the latest seven days. Missing data is not a low score; it "
            "means the picture is out of date, so someone should check whether "
            "the child has stopped engaging or the recording has lapsed."
        ),
        evidence={"latest_window": str(as_of), "weeks": 8},
    )


def _pulse_finding(child, as_of: date) -> Finding | None:
    responses = list(
        PulseResponse.objects.filter(
            child=child,
            week_start__gte=as_of - timedelta(days=PULSE_LOOKBACK_DAYS + 7),
            week_start__lte=as_of,
        ).order_by("-week_start")[:2]
    )
    if len(responses) < 2:
        return None
    if any(response.wellbeing > PULSE_LOW for response in responses):
        return None
    if responses[0].week_start - responses[1].week_start > timedelta(days=14):
        # Non-consecutive reports are two difficult moments, not a run.
        return None
    return Finding(
        rule_key="guardian_pulse_low",
        tier="concern",
        domain="",
        title="Guardian has reported two difficult weeks in a row",
        summary=(
            "A guardian rated their child's week as difficult or very "
            "difficult in each of the last two weekly pulse responses. The "
            "guardian is describing what they see at home; that view should be "
            "part of the next conversation about this child."
        ),
        evidence={
            "weeks": [str(response.week_start) for response in responses],
            "wellbeing": [response.wellbeing for response in responses],
            "support": [response.support for response in responses],
        },
    )


def evaluate(child, as_of: date | None = None) -> list[Finding]:
    """Every finding for one child as of `as_of`, in no particular order."""
    as_of = as_of or timezone.localdate()
    if not child.has_consent:
        return []

    findings: list[Finding] = []
    findings.extend(_overall_findings(child, as_of))
    findings.extend(_domain_findings(child, as_of))

    no_data = _no_data_finding(child, as_of)
    if no_data is not None and not findings:
        # "Not enough data" and "looks unwell" are different messages. If a
        # score rule already fired there is something to act on, so the
        # missing-data notice would only dilute it.
        findings.append(no_data)

    pulse = _pulse_finding(child, as_of)
    if pulse is not None:
        findings.append(pulse)

    return findings

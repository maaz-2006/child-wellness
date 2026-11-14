"""Turn raw entries into versioned wellness scores.

Why a score exists at all: a mentor looking at forty rows of ratings cannot see
a trend, and a guardian cannot compare this month with last. A single number per
domain per week is a summary, and summaries are how people notice change.

What this score is *not*: a diagnosis, a prediction, or a judgement about a
child. It is a reproducible interpretation of structured ratings, stamped with
`METHOD_VERSION` and a confidence label so that a reader can tell the difference
between "four weeks of daily data say this" and "one observation says this".

Four decisions worth defending:

* **Only structured ratings are used, never free text.** The note on a check-in
  is the highest-risk field on the platform; a numeric score must not become a
  side channel that leaks it. Numeric mood, energy, marks, ratings and habit
  measurements are already governed by their domain's access rule.
* **Each domain is normalised to 0-1 before it is combined.** Otherwise minutes
  of activity and marks out of twenty would be added together as if they were
  the same kind of quantity.
* **The overall score renormalises by the weights of the domains that are
  actually present that day, and requires at least two.** A child with only
  emotional check-ins is not assigned 60% of a score; they get no overall score,
  and the page says why. Averaging missing domains as zero is how a monitoring
  system quietly labels an unmeasured child as unwell.
* **A rolling 7-day window, not a calendar week.** The latest point always ends
  today, so a new entry is visible immediately rather than waiting for Monday.

Per-child baselines are stored separately in `BaselineStat` so D5's alert engine
can compare a child against *their own* recent normal rather than against a
population average - the population includes children whose normal is already a
concern.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, pstdev

from django.db.models import Avg, Count, Max
from django.utils import timezone

from domains.models import (
    AcademicRecord,
    EmotionalCheckin,
    HabitLog,
    SocialObservation,
)

#: Bumped whenever the arithmetic changes. Stored on every row so a historical
#: score can be explained by the method that produced it.
METHOD_VERSION = "1.0"

#: The pseudo-domain that holds the combined score. `DomainScore.domain` is a
#: short string, and storing the overall score beside the real domains means one
#: table, one uniqueness rule and one query shape for both.
OVERALL = "overall"

PERIOD_DAYS = 7
TREND_PERIODS = 8
WINDOW_DAYS = PERIOD_DAYS * TREND_PERIODS
BASELINE_DAYS = 28

#: Two domains is the floor. With one domain the "overall" score would just be
#: that domain wearing a different hat, which invites over-reading it.
MIN_DOMAINS_FOR_OVERALL = 2

DOMAINS = ("emotional", "academic", "habits", "social")

DOMAIN_WEIGHTS = {
    "emotional": 0.40,
    "academic": 0.25,
    "habits": 0.20,
    "social": 0.15,
}

DOMAIN_LABELS = {
    OVERALL: "Overall wellness",
    "emotional": "Emotional wellness",
    "academic": "Academic progress",
    "habits": "Healthy habits",
    "social": "Social development",
}

CONFIDENCE_LABELS = {
    "none": "No data",
    "thin": "Thin",
    "moderate": "Moderate",
    "good": "Good",
}

#: How many days of data a 7-day window needs before it is called "good".
#: Academic and social entries are naturally less frequent than a daily
#: check-in, so holding them to the daily threshold would mark every child's
#: academic score "thin" forever. The threshold is per cadence, not optimism.
GOOD_POINTS = {
    OVERALL: 5,
    "emotional": 5,
    "academic": 3,
    "social": 3,
    "habits": 5,
}

#: Age-appropriate sleep ranges, in hours. Deliberately broad: the point is to
#: distinguish "nine hours" from "five hours", not to grade a child's bedtime
#: against a single number.
SLEEP_GUIDELINES = {
    "early": (10.0, 13.0),
    "primary": (9.0, 12.0),
    "early_secondary": (8.0, 10.0),
    "secondary": (8.0, 10.0),
    "unknown": (9.0, 12.0),
}


# ---------------------------------------------------------------------------
# Small maths helpers
# ---------------------------------------------------------------------------
def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _scale(value) -> float:
    """A 1-5 rubric rating as 0-1."""
    return _clamp01((float(value) - 1.0) / 4.0)


def _sleep_score(hours: float, age_band: str) -> float:
    low, high = SLEEP_GUIDELINES.get(age_band, SLEEP_GUIDELINES["unknown"])
    if low <= hours <= high:
        return 1.0
    if hours < low:
        # Three hours short of the lower bound scores zero. A graded ramp is
        # kinder than a cliff, and still distinguishes 8.5 h from 5 h.
        return _clamp01((hours - (low - 3.0)) / 3.0)
    return _clamp01(1.0 - (hours - high) / 3.0)


def _activity_score(minutes: float) -> float:
    """The guideline is about an hour of active play a day."""
    return _clamp01(minutes / 60.0)


def _screen_score(minutes: float) -> float:
    """Recreational screen time: an hour is neutral, four hours scores zero."""
    if minutes <= 60.0:
        return 1.0
    return _clamp01(1.0 - (minutes - 60.0) / 180.0)


def confidence_for(domain: str, data_points: int) -> str:
    if data_points <= 0:
        return "none"
    good = GOOD_POINTS.get(domain, 5)
    if data_points >= good:
        return "good"
    if data_points >= max(2, good - 2):
        return "moderate"
    return "thin"


@dataclass(frozen=True)
class Window:
    """One rolling period. `end` is inclusive."""

    start: date
    end: date

    @property
    def label(self) -> str:
        # Windows on this platform are dates, not localised month names. Using
        # the day plus a short month keeps the axis readable in a narrow chart.
        return f"{self.end.day} {self.end.strftime('%b')}"


def periods(as_of: date, count: int = TREND_PERIODS) -> list[Window]:
    """Consecutive 7-day windows ending on `as_of`, oldest first."""
    windows = []
    for offset in reversed(range(count)):
        end = as_of - timedelta(days=PERIOD_DAYS * offset)
        windows.append(Window(end - timedelta(days=PERIOD_DAYS - 1), end))
    return windows


# ---------------------------------------------------------------------------
# Daily normalised values
# ---------------------------------------------------------------------------
def _merge_days(per_day: dict[date, list[float]]) -> dict[date, float]:
    return {
        day: mean(values)
        for day, values in per_day.items()
        if values
    }


def _emotional_values(child, start: date, end: date) -> dict[date, float]:
    rows = EmotionalCheckin.objects.filter(
        child=child, occurred_on__gte=start, occurred_on__lte=end
    ).values("occurred_on", "mood", "energy", "sleep_quality", "felt_connected")

    per_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        parts = [_scale(row["mood"]), _scale(row["energy"])]
        if row["sleep_quality"] is not None:
            parts.append(_scale(row["sleep_quality"]))
        if row["felt_connected"] is not None:
            parts.append(_scale(row["felt_connected"]))
        per_day[row["occurred_on"]].append(mean(parts))
    return _merge_days(per_day)


def _academic_values(child, start: date, end: date) -> dict[date, float]:
    rows = AcademicRecord.objects.filter(
        child=child, occurred_on__gte=start, occurred_on__lte=end
    ).values("occurred_on", "score", "max_score")

    per_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        if not row["max_score"]:
            continue
        per_day[row["occurred_on"]].append(
            _clamp01(float(row["score"]) / float(row["max_score"]))
        )
    return _merge_days(per_day)


def _social_values(child, start: date, end: date) -> dict[date, float]:
    rows = SocialObservation.objects.filter(
        child=child, occurred_on__gte=start, occurred_on__lte=end
    ).values("occurred_on", "rating")

    per_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        per_day[row["occurred_on"]].append(_scale(row["rating"]))
    return _merge_days(per_day)


def _habit_values(child, start: date, end: date) -> dict[date, float]:
    age_band = child.age_band if child is not None else "unknown"
    rows = HabitLog.objects.filter(
        child=child, occurred_on__gte=start, occurred_on__lte=end
    ).values(
        "occurred_on",
        "sleep_hours",
        "activity_minutes",
        "screen_minutes",
        "nutrition_quality",
        "ate_breakfast",
    )

    per_day: dict[date, list[float]] = defaultdict(list)
    for row in rows:
        parts: list[float] = []
        if row["sleep_hours"] is not None:
            parts.append(_sleep_score(float(row["sleep_hours"]), age_band))
        if row["activity_minutes"] is not None:
            parts.append(_activity_score(float(row["activity_minutes"])))
        if row["screen_minutes"] is not None:
            parts.append(_screen_score(float(row["screen_minutes"])))
        if row["nutrition_quality"] is not None:
            parts.append(_scale(row["nutrition_quality"]))
        if row["ate_breakfast"] is not None:
            parts.append(1.0 if row["ate_breakfast"] else 0.0)
        if parts:
            per_day[row["occurred_on"]].append(mean(parts))
    return _merge_days(per_day)


def daily_values(child, domain: str, start: date, end: date) -> dict[date, float]:
    """Normalised 0-1 values, one per day that has data, for one domain."""
    if domain == "emotional":
        return _emotional_values(child, start, end)
    if domain == "academic":
        return _academic_values(child, start, end)
    if domain == "social":
        return _social_values(child, start, end)
    if domain == "habits":
        return _habit_values(child, start, end)
    raise ValueError(f"Unknown domain: {domain}")


def _overall_values(per_domain: dict[str, dict[date, float]]) -> dict[date, float]:
    """Weighted per-day combination of whichever domains have data that day."""
    days: set[date] = set()
    for values in per_domain.values():
        days.update(values)

    combined: dict[date, float] = {}
    for day in days:
        present = [
            (DOMAIN_WEIGHTS[domain], values[day])
            for domain, values in per_domain.items()
            if day in values
        ]
        if len(present) < MIN_DOMAINS_FOR_OVERALL:
            continue
        total_weight = sum(weight for weight, _value in present)
        combined[day] = sum(weight * value for weight, value in present) / total_weight
    return combined


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _score_rows(child, as_of: date, per_domain: dict[str, dict[date, float]]) -> list:
    """Build (not save) the DomainScore rows for one child.

    `per_domain` is passed in rather than queried again: recompute needs the same
    daily values for the baselines, and computing them twice would double the
    query count for no benefit.
    """
    from .models import DomainScore

    windows = periods(as_of, TREND_PERIODS)
    rows = []
    for domain, values in per_domain.items():
        for window in windows:
            sample = [
                value for day, value in values.items()
                if window.start <= day <= window.end
            ]
            if not sample:
                # No row at all is more honest than a row that says "zero".
                # The chart draws a gap; the table says "no data".
                continue
            rows.append(
                DomainScore(
                    child=child,
                    domain=domain,
                    period_start=window.start,
                    period_end=window.end,
                    score=round(mean(sample) * 100.0, 2),
                    data_points=len(sample),
                    confidence=confidence_for(domain, len(sample)),
                    method_version=METHOD_VERSION,
                )
            )
    return rows


def _baseline_row(child, domain: str, values: dict[date, float], as_of: date):
    from .models import BaselineStat

    start = as_of - timedelta(days=BASELINE_DAYS - 1)
    sample = [value for day, value in values.items() if start <= day <= as_of]
    if not sample:
        return None
    return BaselineStat(
        child=child,
        domain=domain,
        as_of=as_of,
        window_days=BASELINE_DAYS,
        mean=round(mean(sample) * 100.0, 2),
        stddev=round(pstdev(sample) * 100.0, 2) if len(sample) > 1 else None,
        sample_size=len(sample),
    )


def recompute_child(child, as_of: date | None = None) -> dict:
    """Recompute and store every score and baseline for one child.

    Idempotent by construction: the stored window is deleted and rebuilt, so
    running it twice produces byte-identical rows (apart from `computed_at`).
    The table is a cache of a calculation, not a ledger of events.
    """
    from .models import BaselineStat, DomainScore

    as_of = as_of or timezone.localdate()
    start = as_of - timedelta(days=WINDOW_DAYS - 1)

    per_domain = {
        domain: daily_values(child, domain, start, as_of) for domain in DOMAINS
    }
    per_domain[OVERALL] = _overall_values(
        {domain: value for domain, value in per_domain.items()}
    )

    rows = _score_rows(child, as_of, per_domain)
    DomainScore.objects.filter(child=child).delete()
    DomainScore.objects.bulk_create(rows)

    BaselineStat.objects.filter(
        child=child, as_of=as_of, window_days=BASELINE_DAYS
    ).delete()
    baselines = [
        row
        for domain, values in per_domain.items()
        if (row := _baseline_row(child, domain, values, as_of)) is not None
    ]
    BaselineStat.objects.bulk_create(baselines)

    return {
        "child": child,
        "as_of": as_of,
        "scores": len(rows),
        "baselines": len(baselines),
    }


def recompute_all(as_of: date | None = None) -> dict:
    """Recompute every active child. Used by `recompute_wellness` and seeding."""
    from children.models import Child

    as_of = as_of or timezone.localdate()
    children = list(Child.objects.filter(is_active=True))
    total_scores = 0
    for child in children:
        total_scores += recompute_child(child, as_of)["scores"]
    return {"as_of": as_of, "children": len(children), "scores": total_scores}


# ---------------------------------------------------------------------------
# Reading what was stored
# ---------------------------------------------------------------------------
def stored_series(
    child, domain: str, as_of: date | None = None, count: int = TREND_PERIODS
) -> list[dict]:
    """One point per window, with `value=None` where there was no data."""
    from .models import DomainScore

    as_of = as_of or timezone.localdate()
    windows = periods(as_of, count)
    rows = {
        row.period_end: row
        for row in DomainScore.objects.filter(
            child=child,
            domain=domain,
            period_end__in=[window.end for window in windows],
        )
    }

    series = []
    for window in windows:
        row = rows.get(window.end)
        series.append(
            {
                "period_start": window.start,
                "period_end": window.end,
                "label": window.label,
                "value": round(float(row.score), 1) if row else None,
                "data_points": row.data_points if row else 0,
                "confidence": row.confidence if row else "none",
            }
        )
    return series


def baseline_for(child, domain: str, as_of: date | None = None) -> dict | None:
    """The stored 28-day baseline as a chart-ready dict, or None."""
    from .models import BaselineStat

    as_of = as_of or timezone.localdate()
    row = BaselineStat.objects.filter(
        child=child, domain=domain, as_of=as_of, window_days=BASELINE_DAYS
    ).first()
    if row is None or row.mean is None:
        return None
    return {
        "mean": float(row.mean),
        "stddev": float(row.stddev) if row.stddev is not None else None,
        "sample_size": row.sample_size,
    }


def _latest_entry_at(child):
    stamps = [
        EmotionalCheckin.objects.filter(child=child).aggregate(at=Max("updated_at"))["at"],
        AcademicRecord.objects.filter(child=child).aggregate(at=Max("updated_at"))["at"],
        SocialObservation.objects.filter(child=child).aggregate(at=Max("updated_at"))["at"],
        HabitLog.objects.filter(child=child).aggregate(at=Max("updated_at"))["at"],
    ]
    present = [stamp for stamp in stamps if stamp is not None]
    return max(present) if present else None


def ensure_child_current(child, as_of: date | None = None) -> bool:
    """Recompute this child only if the stored scores are missing or stale.

    Staleness is `max(entry.updated_at) > max(score.computed_at)` or a missing
    current window. That makes a newly entered observation visible on the next
    page load without recomputing on every request.
    """
    from .models import DomainScore

    as_of = as_of or timezone.localdate()
    latest_score = DomainScore.objects.filter(child=child).aggregate(
        at=Max("computed_at")
    )["at"]
    has_current_period = DomainScore.objects.filter(
        child=child, period_end=as_of
    ).exists()

    if latest_score is not None and has_current_period:
        latest_entry = _latest_entry_at(child)
        if latest_entry is None or latest_entry <= latest_score:
            return False

    recompute_child(child, as_of)
    return True


def ensure_cohort_current(as_of: date | None = None) -> bool:
    """Recompute the whole cohort when no score exists for the current window.

    This is the coarse fallback for the aggregate page. Individual staleness is
    handled by `ensure_child_current` on the child page; a scheduled
    `recompute_wellness` is the reliable path for a production cohort.
    """
    from .models import DomainScore

    as_of = as_of or timezone.localdate()
    if DomainScore.objects.filter(period_end=as_of).exists():
        return False
    recompute_all(as_of)
    return True


def cohort_snapshot(as_of: date | None = None) -> dict:
    """Aggregate-only view of the cohort. Contains no child identifiers.

    The administrator has AGGREGATE on scores, not READ: this function is the
    shape that grant implies. If a name ever needs to appear here, the permission
    model has been violated, not merely stretched.
    """
    from children.models import Child
    from .models import DomainScore

    as_of = as_of or timezone.localdate()
    overall_rows = list(
        DomainScore.objects.filter(period_end=as_of, domain=OVERALL).values(
            "score", "confidence", "data_points"
        )
    )
    scored = len(overall_rows)
    average = (
        round(mean(float(row["score"]) for row in overall_rows), 1) if scored else None
    )

    buckets = [
        {"label": "85-100", "count": 0, "share": 0},
        {"label": "70-84", "count": 0, "share": 0},
        {"label": "50-69", "count": 0, "share": 0},
        {"label": "Below 50", "count": 0, "share": 0},
    ]
    for row in overall_rows:
        value = float(row["score"])
        if value >= 85:
            buckets[0]["count"] += 1
        elif value >= 70:
            buckets[1]["count"] += 1
        elif value >= 50:
            buckets[2]["count"] += 1
        else:
            buckets[3]["count"] += 1
    for bucket in buckets:
        bucket["share"] = (
            round(bucket["count"] / scored * 100) if scored else 0
        )

    confidence_counts = {key: 0 for key in CONFIDENCE_LABELS}
    for row in overall_rows:
        confidence_counts[row["confidence"]] = (
            confidence_counts.get(row["confidence"], 0) + 1
        )

    domain_rows = []
    for domain in DOMAINS:
        aggregate = DomainScore.objects.filter(
            period_end=as_of, domain=domain
        ).aggregate(average=Avg("score"), n=Count("id"))
        domain_rows.append(
            {
                "key": domain,
                "label": DOMAIN_LABELS[domain],
                "average": (
                    round(float(aggregate["average"]), 1)
                    if aggregate["average"] is not None
                    else None
                ),
                "children": aggregate["n"],
            }
        )

    windows = periods(as_of, TREND_PERIODS)
    trend_rows = (
        DomainScore.objects.filter(
            domain=OVERALL, period_end__in=[window.end for window in windows]
        )
        .values("period_end")
        .annotate(average=Avg("score"), n=Count("id"))
    )
    by_end = {row["period_end"]: row for row in trend_rows}
    trend = []
    for window in windows:
        row = by_end.get(window.end)
        trend.append(
            {
                "label": window.label,
                "value": (
                    round(float(row["average"]), 1)
                    if row and row["average"] is not None
                    else None
                ),
                "data_points": row["n"] if row else 0,
            }
        )

    return {
        "as_of": as_of,
        "children_total": Child.objects.filter(is_active=True).count(),
        "children_scored": scored,
        "average": average,
        "buckets": buckets,
        "confidence": [
            {
                "key": key,
                "label": CONFIDENCE_LABELS[key],
                "count": confidence_counts.get(key, 0),
            }
            for key in ("good", "moderate", "thin", "none")
        ],
        "domains": domain_rows,
        "trend": trend,
    }

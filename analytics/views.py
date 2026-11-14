"""Analytics screens.

Two audiences, two shapes, one permission gate:

* A mentor or guardian sees one child's trend, because they have READ on the
  score (which is a derived summary, not the raw records).
* An administrator sees the cohort distribution and trend and no names, because
  that is what AGGREGATE means. The aggregate page is not a redacted version of
  the child page; it never has the child identifiers to redact.

A child is denied both: `SCORE` is deliberately NONE for `(CHILD, SELF)`. A
platform that shows a nine-year-old a risk score about themselves has turned a
care tool into a label.
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from core import permissions
from core.audit import record_request
from core.mixins import ChildScopedMixin
from core.models import AuditLog
from core.permissions import Access, Resource

from . import charts, scoring


#: Overall first, then the weighted domains in descending weight so the page
#: reads in the same order as the method explanation.
CARD_ORDER = (
    scoring.OVERALL,
    "emotional",
    "academic",
    "habits",
    "social",
)


def _change(series: list[dict], weeks: int = 4) -> dict | None:
    """Change against the point `weeks` windows earlier, when both exist."""
    present = [
        (index, point) for index, point in enumerate(series)
        if point["value"] is not None
    ]
    if len(present) < 2:
        return None
    latest_index, latest = present[-1]
    target_index = latest_index - weeks
    if target_index < 0 or series[target_index]["value"] is None:
        return None

    delta = latest["value"] - series[target_index]["value"]
    if delta > 0.05:
        direction = "up"
    elif delta < -0.05:
        direction = "down"
    else:
        direction = "flat"
    return {"value": round(delta, 1), "direction": direction, "weeks": weeks}


def _card(child, domain: str, as_of) -> dict:
    series = scoring.stored_series(child, domain, as_of)
    baseline = scoring.baseline_for(child, domain, as_of)
    chart = charts.line_chart(
        series,
        chart_id=domain,
        title=f"{scoring.DOMAIN_LABELS[domain]}, last {scoring.TREND_PERIODS} weeks",
        band=baseline,
    )
    latest = next(
        (point for point in reversed(series) if point["value"] is not None), None
    )
    return {
        "key": domain,
        "label": scoring.DOMAIN_LABELS[domain],
        "chart": chart,
        "series": series,
        "latest": latest,
        "confidence_label": (
            scoring.CONFIDENCE_LABELS[latest["confidence"]] if latest else "No data"
        ),
        "change": _change(series),
        "baseline": baseline,
        "weight_pct": round(scoring.DOMAIN_WEIGHTS.get(domain, 0) * 100),
    }


class ChildWellnessView(ChildScopedMixin, TemplateView):
    """One child's trend. Requires READ on the score resource."""

    template_name = "analytics/child_wellness.html"
    resource = Resource.SCORE
    required_access = Access.READ

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        as_of = timezone.localdate()
        scoring.ensure_child_current(self.child, as_of)

        cards = [_card(self.child, domain, as_of) for domain in CARD_ORDER]

        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.SCORE,
            child=self.child,
            metadata={"method": scoring.METHOD_VERSION},
        )

        context.update(
            {
                "as_of": as_of,
                "overall_card": cards[0],
                "domain_cards": cards[1:],
                "has_any_data": any(card["latest"] is not None for card in cards),
                "method_version": scoring.METHOD_VERSION,
                "period_days": scoring.PERIOD_DAYS,
                "trend_periods": scoring.TREND_PERIODS,
                "baseline_days": scoring.BASELINE_DAYS,
                "weights": [
                    {
                        "label": scoring.DOMAIN_LABELS[domain],
                        "percent": round(scoring.DOMAIN_WEIGHTS[domain] * 100),
                    }
                    for domain in ("emotional", "academic", "habits", "social")
                ],
                "back_url": reverse("children:detail", args=[self.child.pk]),
            }
        )
        return context


class CohortWellnessView(LoginRequiredMixin, TemplateView):
    """Aggregate-only cohort overview.

    The gate is `access_for_institution`, not a role check, so the rule stays in
    the matrix. A mentor with READ on an individual child still has no
    institution-wide grant, and a future role can gain or lose this without the
    view changing.
    """

    template_name = "analytics/cohort_wellness.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            granted = permissions.access_for_institution(request.user, Resource.SCORE)
            if granted < Access.AGGREGATE:
                record_request(
                    request,
                    action=AuditLog.Action.DENY,
                    resource_type=Resource.SCORE,
                    metadata={
                        "required": Access.AGGREGATE.name,
                        "granted": Access(granted).name,
                        "scope": "institution",
                    },
                )
                raise PermissionDenied(
                    "Aggregate wellness data is not available to your account."
                )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        as_of = timezone.localdate()
        scoring.ensure_cohort_current(as_of)
        snapshot = scoring.cohort_snapshot(as_of)

        snapshot["chart"] = charts.line_chart(
            snapshot["trend"],
            chart_id="cohort",
            title=f"Cohort average overall score, last {scoring.TREND_PERIODS} weeks",
            description=(
                "Line chart of the cohort's average overall wellness score. "
                "Each point is a seven-day window ending on the date shown."
            ),
        )

        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.SCORE,
            metadata={"method": scoring.METHOD_VERSION, "scope": "institution"},
        )

        context.update(
            {
                "snapshot": snapshot,
                "as_of": as_of,
                "method_version": scoring.METHOD_VERSION,
                "trend_periods": scoring.TREND_PERIODS,
                "period_days": scoring.PERIOD_DAYS,
            }
        )
        return context

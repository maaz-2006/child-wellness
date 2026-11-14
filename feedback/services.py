"""Pulse queries and aggregates.

The aggregate is deliberately count-first: how many *children* were heard from,
not how many forms were submitted. A household with two guardians and one child
is one child reached, and averaging it twice would quietly overweight that
family.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count
from django.utils import timezone

from .models import PulseResponse, current_week_start


def pulse_for(guardian, child, week_start=None):
    return PulseResponse.objects.filter(
        guardian=guardian,
        child=child,
        week_start=week_start or current_week_start(),
    ).first()


def children_due_for(guardian):
    """Visible children with no pulse response for the current week."""
    from core import permissions

    children = permissions.visible_children(guardian)
    answered = set(
        PulseResponse.objects.filter(
            guardian=guardian, week_start=current_week_start()
        ).values_list("child_id", flat=True)
    )
    return [child for child in children if child.pk not in answered]


def history_for(child, limit=12):
    return (
        PulseResponse.objects.filter(child=child)
        .select_related("guardian")
        .order_by("-week_start", "-pk")[:limit]
    )


def cohort_snapshot(weeks: int = 4) -> dict:
    """Aggregate-only weekly pulse figures. No names and no comments."""
    from children.models import Child

    this_week = current_week_start()
    week_starts = [this_week - timedelta(days=7 * offset) for offset in reversed(range(weeks))]

    trend = []
    for start in week_starts:
        responses = PulseResponse.objects.filter(week_start=start)
        aggregate = responses.aggregate(average=Avg("wellbeing"), n=Count("id"))
        trend.append(
            {
                "week_start": start,
                "label": f"{start.day} {start.strftime('%b')}",
                "responses": aggregate["n"],
                "children": responses.values("child_id").distinct().count(),
                "average": (
                    round(float(aggregate["average"]), 1)
                    if aggregate["average"] is not None
                    else None
                ),
            }
        )

    current = list(PulseResponse.objects.filter(week_start=this_week).values("wellbeing"))
    distribution = []
    for value in range(1, 6):
        count = sum(1 for row in current if row["wellbeing"] == value)
        distribution.append(
            {
                "value": value,
                "label": PulseResponse.Wellbeing(value).label,
                "count": count,
                "share": round(count / len(current) * 100) if current else 0,
            }
        )

    support = PulseResponse.objects.filter(
        week_start=this_week, support__isnull=False
    ).aggregate(average=Avg("support"))["average"]

    active_children = Child.objects.filter(is_active=True).count()
    reached = (
        PulseResponse.objects.filter(week_start=this_week)
        .values("child_id")
        .distinct()
        .count()
    )

    return {
        "week_start": this_week,
        "responses": len(current),
        "children_reached": reached,
        "children_total": active_children,
        "reach_share": round(reached / active_children * 100) if active_children else 0,
        "average_wellbeing": (
            round(float(sum(row["wellbeing"] for row in current) / len(current)), 1)
            if current
            else None
        ),
        "average_support": round(float(support), 1) if support is not None else None,
        "distribution": distribution,
        "trend": trend,
    }

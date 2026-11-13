"""Row-level access to domain entries.

`core.permissions` answers "may this person open the emotional wellness page for
this child". It cannot answer "may they see *this row*", because the answer
depends on the row: a mentor has SUMMARY on emotional wellness, which means the
child's shared check-ins and the professional observations - never the child's
private notes.

Keeping that rule here, in one function, is what stops each view from inventing
its own slightly-different filter. Every list view calls `entries_for`; nothing
else is allowed to do `Model.objects.filter(child=child)` for display.

The rules, in full:

    READ and above      -> every row for that child. Child accounts are the
                           exception: they only ever see their own self-reports,
                           never an adult's observation about them.
    SUMMARY (mentor,
    emotional only)     -> adult observations, plus self-reports the child chose
                           to share (note_visibility MENTOR or ALL).
    Anything else       -> no rows. AGGREGATE gets counts, not records.

Free text is filtered *again* per row by `DomainEntry.note_visible_to`, so a
visible rating does not imply a visible note.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField, Q
from django.utils import timezone

from core import permissions
from core.models import Role
from core.permissions import Access

from .models import NoteVisibility, Source


def entries_for(user, child, module):
    """Return the queryset of `module` rows this user may see for this child."""
    queryset = module.model.objects.filter(child=child).select_related("recorded_by")

    access = permissions.access_for(user, child, module.resource)
    if access < Access.SUMMARY:
        return queryset.none()

    if access >= Access.READ:
        # A child has WRITE on their own emotional data, but the platform must
        # never show them an adult's observation about them. Their view is
        # restricted to what they wrote themselves.
        if user.role == Role.CHILD:
            return queryset.filter(source=Source.CHILD)
        return queryset

    # SUMMARY. Only one such grant exists in the matrix, and it is the mentor's
    # on emotional wellness. Be explicit rather than clever about it.
    if module.key == "emotional" and user.role == Role.MENTOR:
        return queryset.filter(
            Q(source__in=[Source.MENTOR, Source.PARENT])
            | Q(
                source=Source.CHILD,
                note_visibility__in=[NoteVisibility.MENTOR, NoteVisibility.ALL],
            )
        )

    return queryset.none()


def mode_for(user, child, module) -> str:
    """Describe how much of a domain the user may see, for templates.

    One of: "full", "shared", "summary", "aggregate", "none".
    """
    access = permissions.access_for(user, child, module.resource)
    if access >= Access.READ:
        return "full"
    if access == Access.SUMMARY:
        if module.key == "emotional" and user.role == Role.MENTOR:
            return "shared"
        return "summary"
    if access == Access.AGGREGATE:
        return "aggregate"
    return "none"


MODE_LABELS = {
    "full": "Full records",
    "shared": "Shared with you",
    "summary": "Summary only",
    "aggregate": "Aggregate only",
    "none": "Not available",
}


def rows_for(user, entries):
    """Decorate entries with the per-row decisions templates may not compute.

    A template cannot call `entry.note_visible_to(user)` (it takes an argument),
    and putting the rule in template tags would split it from the model. So the
    view resolves it once and the template only renders what it is given.
    """
    rows = []
    for entry in entries:
        show_note = bool(entry.note) and entry.note_visible_to(user)
        rows.append(
            {
                "entry": entry,
                "show_note": show_note,
                "note": entry.note if show_note else "",
                "source_label": entry.get_source_display() if hasattr(entry, "get_source_display") else "",
                "author_label": _author_label(user, entry),
                "has_hidden_note": bool(entry.note) and not show_note,
            }
        )
    return rows


def _author_label(user, entry) -> str:
    """Who wrote it, without leaking a staff member's identity to a child."""
    if entry.recorded_by_id is None:
        return "Recorded by staff"
    if user.role == Role.CHILD:
        return "You"
    return entry.recorded_by.display_name


def summarise(entries, module, window_days: int = 30) -> list[dict]:
    """A handful of descriptive statistics for SUMMARY/AGGREGATE views.

    These are *descriptive*, not the versioned wellness score from
    `analytics.scoring`. The distinction matters: a mean of the last 30 days is
    a fact about the records, while the wellness score is an interpretation with
    a method version and a confidence label.
    """
    since = timezone.localdate() - timedelta(days=window_days)
    recent = entries.filter(occurred_on__gte=since)
    total = entries.count()

    stats = [{"label": "Records on file", "value": total}]

    if module.key == "emotional":
        agg = recent.aggregate(
            mood=Avg("mood"),
            energy=Avg("energy"),
            connected=Avg("felt_connected"),
            n=Count("id"),
        )
        if agg["n"]:
            stats.append({"label": "Check-ins (30 days)", "value": agg["n"]})
            stats.append({"label": "Average mood", "value": f"{agg['mood']:.1f} / 5"})
            stats.append({"label": "Average energy", "value": f"{agg['energy']:.1f} / 5"})

    elif module.key == "academic":
        agg = recent.aggregate(
            average=Avg(
                ExpressionWrapper(
                    F("score") / F("max_score") * 100, output_field=FloatField()
                )
            ),
            n=Count("id"),
        )
        if agg["n"]:
            stats.append({"label": "Assessments (30 days)", "value": agg["n"]})
            stats.append({"label": "Average mark", "value": f"{agg['average']:.0f}%"})

    elif module.key == "social":
        agg = recent.aggregate(rating=Avg("rating"), n=Count("id"))
        if agg["n"]:
            stats.append({"label": "Observations (30 days)", "value": agg["n"]})
            stats.append({"label": "Average rating", "value": f"{agg['rating']:.1f} / 5"})

    elif module.key == "habits":
        agg = recent.aggregate(
            sleep=Avg("sleep_hours"),
            activity=Avg("activity_minutes"),
            screen=Avg("screen_minutes"),
            n=Count("id"),
        )
        if agg["n"]:
            stats.append({"label": "Logs (30 days)", "value": agg["n"]})
            if agg["sleep"] is not None:
                stats.append({"label": "Average sleep", "value": f"{agg['sleep']:.1f} h"})
            if agg["activity"] is not None:
                stats.append(
                    {"label": "Average activity", "value": f"{agg['activity']:.0f} min"}
                )

    return stats

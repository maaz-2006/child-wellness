"""State transitions for alerts.

Every function here enforces a rule that the UI must not be trusted to enforce:

* you cannot acknowledge or resolve an alert that is already closed;
* you cannot add a case note to a closed alert;
* you cannot share an urgent alert with a guardian at all;
* you cannot share *anything* with a guardian who has no active consent.

The functions are deliberately small and free of HTTP concerns so that both the
views and the tests exercise the same transitions.
"""

from __future__ import annotations

from django.utils import timezone

from .models import Alert, AlertEvent


class AlertStateError(Exception):
    """The requested transition is not allowed for this alert."""


def _require_open(alert: Alert) -> None:
    if not alert.is_open:
        raise AlertStateError("This alert is already closed.")


def _clean_note(note: str, *, required: bool, label: str) -> str:
    note = (note or "").strip()
    if required and not note:
        raise AlertStateError(f"{label} is required.")
    if len(note) > 2000:
        raise AlertStateError(f"{label} must be 2000 characters or fewer.")
    return note


def acknowledge(alert: Alert, actor) -> Alert:
    _require_open(alert)
    alert.status = Alert.Status.ACKNOWLEDGED
    alert.acknowledged_by = actor
    alert.acknowledged_at = timezone.now()
    if alert.assigned_to_id is None:
        alert.assigned_to = actor
    alert.save()
    AlertEvent.objects.create(
        alert=alert,
        actor=actor,
        kind=AlertEvent.Kind.ACKNOWLEDGED,
        body="Alert acknowledged; someone has taken ownership.",
    )
    return alert


def add_note(alert: Alert, actor, body: str) -> AlertEvent:
    _require_open(alert)
    body = _clean_note(body, required=True, label="Case note")
    return AlertEvent.objects.create(
        alert=alert,
        actor=actor,
        kind=AlertEvent.Kind.NOTE,
        body=body,
    )


def resolve(alert: Alert, actor, note: str = "") -> Alert:
    _require_open(alert)
    note = _clean_note(note, required=True, label="Resolution note")
    alert.status = Alert.Status.RESOLVED
    alert.resolved_by = actor
    alert.resolved_at = timezone.now()
    alert.resolution_note = note
    alert.save()
    AlertEvent.objects.create(
        alert=alert,
        actor=actor,
        kind=AlertEvent.Kind.RESOLVED,
        body=note,
    )
    return alert


def dismiss(alert: Alert, actor, note: str = "") -> Alert:
    _require_open(alert)
    note = _clean_note(note, required=True, label="Reason for dismissal")
    alert.status = Alert.Status.DISMISSED
    alert.resolved_by = actor
    alert.resolved_at = timezone.now()
    alert.resolution_note = note
    alert.save()
    AlertEvent.objects.create(
        alert=alert,
        actor=actor,
        kind=AlertEvent.Kind.DISMISSED,
        body=note,
    )
    return alert


def share_with_guardian(alert: Alert, actor) -> Alert:
    """Make a non-urgent alert visible to the child's guardians.

    Urgent alerts are never shareable through this function. A safeguarding
    disclosure is handled by a person following the school's procedure, not by
    pressing a button that pushes a notification to a parent.
    """
    if alert.tier == Alert.Tier.URGENT:
        raise AlertStateError(
            "Urgent and safeguarding alerts are never shared automatically. "
            "Follow the safeguarding procedure and speak to the family directly."
        )
    if alert.status == Alert.Status.DISMISSED:
        raise AlertStateError("A dismissed alert cannot be shared with a guardian.")
    if alert.guardian_shared_at is not None:
        raise AlertStateError("This alert has already been shared.")

    child = alert.child
    if not child.has_consent:
        raise AlertStateError(
            "This child has no active guardian consent, so there is no guardian "
            "with access to share this with."
        )

    alert.guardian_shared_at = timezone.now()
    alert.guardian_shared_by = actor
    alert.save()
    AlertEvent.objects.create(
        alert=alert,
        actor=actor,
        kind=AlertEvent.Kind.SHARED,
        body=(
            "Shared with the child's guardian. Internal case notes remain "
            "private to the care team."
        ),
    )
    return alert

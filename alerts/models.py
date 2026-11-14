"""Alerts: the point where data becomes a decision that a person must make.

Three design commitments are encoded in these models, and each of them is a
deliberate limit on what the platform is allowed to do:

1. **An alert is assigned to a named person.** `assigned_to` is not decorative.
   An unowned alert is a notification nobody reads; the engine therefore
   resolves a mentor (or the safeguarding lead) at creation time.

2. **Nothing here notifies a guardian automatically.** `guardian_shared_at` is
   null until a mentor decides, in a separate deliberate action, to share it.
   Urgent-tier alerts are *never* shareable through this table - the service
   layer refuses, and the tests prove it. A software rule is not an appropriate
   response to a safeguarding disclosure.

3. **The timeline is append-only.** `AlertEvent` records who acknowledged, what
   they wrote, and when the alert was resolved. There is no edit or delete path,
   because the value of a case record is that it says what actually happened.

`Alert` deliberately holds no free-text note from a child. `summary` is generated
from numeric evidence, and the only free text is what an adult writes in a case
event.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone


class Alert(models.Model):
    """One rule firing about one child, tracked until a person resolves it."""

    class Tier(models.TextChoices):
        WATCH = "watch", "Watch"
        CONCERN = "concern", "Concern"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="alerts"
    )
    #: Stable identifier for the rule, e.g. "overall_below_baseline" or
    #: "domain_below_baseline:habits". Used for de-duplication across runs.
    rule_key = models.CharField(max_length=64, db_index=True)
    tier = models.CharField(max_length=12, choices=Tier.choices, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True
    )
    domain = models.CharField(max_length=16, blank=True)

    title = models.CharField(max_length=160)
    #: Generated sentence built from the numeric evidence. Never a quotation
    #: from a child's note.
    summary = models.TextField(max_length=1000)
    #: The numbers behind the decision, so the alert can be explained later
    #: without re-running the rules against data that may have changed.
    evidence = models.JSONField(default=dict, blank=True)

    period_end = models.DateField(db_index=True)
    opened_on = models.DateField(default=timezone.localdate)
    last_seen_on = models.DateField(default=timezone.localdate)
    occurrences = models.PositiveSmallIntegerField(default=1)

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts_assigned",
    )

    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts_acknowledged",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])

    #: Set only by `alerts.services.share_with_guardian`, never by the engine.
    guardian_shared_at = models.DateTimeField(null=True, blank=True)
    guardian_shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alerts_shared",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-opened_on", "-pk"]
        constraints = [
            # The same rule cannot open twice for the same window, which is what
            # makes a scheduled evaluation job safe to run more than once.
            models.UniqueConstraint(
                fields=["child", "rule_key", "period_end"],
                name="uniq_alert_child_rule_period",
            )
        ]
        indexes = [
            models.Index(fields=["status", "tier"]),
            models.Index(fields=["child", "-opened_on"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_tier_display()} · {self.title} · {self.child.short_name}"

    @property
    def is_open(self) -> bool:
        return self.status in {self.Status.OPEN, self.Status.ACKNOWLEDGED}

    @property
    def is_urgent(self) -> bool:
        return self.tier == self.Tier.URGENT

    @property
    def guardian_visible(self) -> bool:
        """Only a non-urgent alert that a mentor explicitly shared."""
        return (
            self.guardian_shared_at is not None
            and self.tier != self.Tier.URGENT
            and self.status != self.Status.DISMISSED
        )


class AlertEvent(models.Model):
    """Append-only case timeline.

    `body` is the only place free text enters the alert system, and it is
    written by an adult with `CASE_NOTE: WRITE` for that child. Guardians never
    see these events; administrators never see them either.
    """

    class Kind(models.TextChoices):
        OPENED = "opened", "Opened"
        NOTE = "note", "Case note"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        RESOLVED = "resolved", "Resolved"
        DISMISSED = "dismissed", "Dismissed"
        SHARED = "shared", "Shared with guardian"
        ROUTED = "routed", "Routed"

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="alert_events",
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    body = models.TextField(blank=True, validators=[MaxLengthValidator(2000)])
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} on alert {self.alert_id}"

    def save(self, *args, **kwargs):
        """Refuse updates: a case timeline that can be edited is not a record."""
        if self.pk is not None:
            raise ValueError("AlertEvent rows are append-only and cannot be edited.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AlertEvent rows are append-only and cannot be deleted.")

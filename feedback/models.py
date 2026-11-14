"""Guardian pulse feedback.

The pulse is deliberately small: two ratings and an optional sentence, once a
week. A long survey gets abandoned, and an abandoned survey tells the school
nothing. Two questions that are actually answered are worth more.

The data model keeps the guardian, the child and the week explicit so that:

* one guardian cannot submit twice for the same child in the same week,
* a second guardian in the same household can disagree, and both views survive,
* the aggregate can count *children* reached rather than forms submitted.

The comment is free text written by an adult about their own child. It is
visible to the child's mentor, never to the administrator, and never read by the
scoring or alert engine.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxLengthValidator, MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def current_week_start(day=None):
    """Monday of the week containing `day` (or today)."""
    day = day or timezone.localdate()
    return day - timezone.timedelta(days=day.weekday())


class PulseResponse(models.Model):
    """One guardian's weekly view of how their child is doing."""

    class Wellbeing(models.IntegerChoices):
        VERY_DIFFICULT = 1, "Very difficult"
        DIFFICULT = 2, "Difficult"
        MIXED = 3, "Mixed"
        GOOD = 4, "Good"
        VERY_GOOD = 5, "Very good"

    class Support(models.IntegerChoices):
        NOT_AT_ALL = 1, "Not at all"
        A_LITTLE = 2, "A little"
        SOMEWHAT = 3, "Somewhat"
        WELL = 4, "Well"
        VERY_WELL = 5, "Very well"

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="pulse_responses"
    )
    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pulse_responses",
        limit_choices_to={"role": "parent"},
    )
    week_start = models.DateField(default=current_week_start, db_index=True)

    wellbeing = models.PositiveSmallIntegerField(
        choices=Wellbeing.choices,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="How has your child seemed this week?",
    )
    support = models.PositiveSmallIntegerField(
        choices=Support.choices,
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="How supported do you feel by the school?",
    )
    comment = models.TextField(
        blank=True,
        validators=[MaxLengthValidator(600)],
        help_text="Anything you want the school to know. Optional.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-week_start", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "child", "week_start"],
                name="uniq_pulse_guardian_child_week",
            )
        ]
        indexes = [models.Index(fields=["child", "-week_start"])]

    def __str__(self) -> str:
        return (
            f"{self.guardian.display_name} on {self.child.short_name}, "
            f"week of {self.week_start}: {self.get_wellbeing_display()}"
        )

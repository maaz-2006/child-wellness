"""The four wellness domains.

Shared shape, different measurements. Every module inherits `DomainEntry`, which
carries the fields the platform reasons about uniformly:

    child          - who the record is about
    recorded_by    - who wrote it (child or adult)
    source         - self-report vs adult observation
    occurred_on    - the day the thing happened, not the day it was typed
    note           - free text, with its own visibility rule
    note_visibility- controls *who may read the free text*, never the numbers

That last distinction is deliberate. Structured ratings are what the scoring
engine and any future model consume; free text is the highest-risk data on the
platform, so it gets its own narrower access rule rather than inheriting the
domain-level grant.

Generating fake data for all four modules is intentionally easy because they
share this base - see analytics/management/commands/seed_demo.py.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class Source(models.TextChoices):
    CHILD = "child", "Child self-report"
    MENTOR = "mentor", "Mentor observation"
    PARENT = "parent", "Parent observation"


class NoteVisibility(models.TextChoices):
    PRIVATE = "private", "Private to author"
    MENTOR = "mentor", "Author and mentor"
    ALL = "all", "Author, mentor and guardian"


SCALE_VALIDATORS = [MinValueValidator(1), MaxValueValidator(5)]


class DomainEntry(models.Model):
    """Abstract base shared by every wellness module."""

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="%(class)ss"
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MENTOR
    )
    occurred_on = models.DateField(default=timezone.localdate, db_index=True)
    note = models.TextField(blank=True)
    note_visibility = models.CharField(
        max_length=16,
        choices=NoteVisibility.choices,
        default=NoteVisibility.MENTOR,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-occurred_on", "-id"]

    @property
    def is_self_report(self) -> bool:
        return self.source == Source.CHILD

    def note_visible_to(self, user) -> bool:
        """Free-text rule. Numbers are governed by the domain grant; this is
        strictly narrower and applies on top of it."""
        if not getattr(user, "is_authenticated", False):
            return False
        if self.recorded_by_id and self.recorded_by_id == user.pk:
            return True
        if self.note_visibility == NoteVisibility.ALL:
            return True
        if self.note_visibility == NoteVisibility.MENTOR:
            return user.role in {"mentor", "admin"}
        return False


# ---------------------------------------------------------------------------
# Emotional wellness
# ---------------------------------------------------------------------------
class EmotionalCheckin(DomainEntry):
    """A short, repeated check-in.

    Five-point scales rather than free text entry: they are comparable over time,
    quick enough that a nine-year-old will actually finish one, and they let us
    compute volatility - which matters more clinically than a single low day.
    """

    MOOD_CHOICES = [
        (1, "Struggling"),
        (2, "Low"),
        (3, "Okay"),
        (4, "Good"),
        (5, "Great"),
    ]
    ENERGY_CHOICES = [
        (1, "Exhausted"),
        (2, "Tired"),
        (3, "Fine"),
        (4, "Energetic"),
        (5, "Full of energy"),
    ]

    mood = models.PositiveSmallIntegerField(choices=MOOD_CHOICES, validators=SCALE_VALIDATORS)
    energy = models.PositiveSmallIntegerField(
        choices=ENERGY_CHOICES, validators=SCALE_VALIDATORS, default=3
    )
    sleep_quality = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=SCALE_VALIDATORS
    )
    felt_connected = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=SCALE_VALIDATORS,
        help_text="How connected the child felt to people around them.",
    )

    class Meta(DomainEntry.Meta):
        verbose_name = "emotional check-in"
        indexes = [
            models.Index(fields=["child", "-occurred_on"]),
            models.Index(fields=["child", "source", "-occurred_on"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["child", "occurred_on", "source"],
                name="uniq_checkin_child_day_source",
            )
        ]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.occurred_on}: {self.get_mood_display()}"


# ---------------------------------------------------------------------------
# Academic progress
# ---------------------------------------------------------------------------
class AcademicRecord(DomainEntry):
    """One assessment or piece of marked work."""

    class Kind(models.TextChoices):
        TEST = "test", "Test"
        ASSIGNMENT = "assignment", "Assignment"
        EXAM = "exam", "Examination"
        PROJECT = "project", "Project"
        READING = "reading", "Reading assessment"

    subject = models.CharField(max_length=60)
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.ASSIGNMENT)
    title = models.CharField(max_length=120, blank=True)
    score = models.DecimalField(max_digits=6, decimal_places=2)
    max_score = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    target = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Optional per-record target, as a percentage.",
    )

    class Meta(DomainEntry.Meta):
        verbose_name = "academic record"
        indexes = [models.Index(fields=["child", "subject", "-occurred_on"])]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.subject}: {self.percentage}%"

    @property
    def percentage(self) -> float:
        if not self.max_score:
            return 0.0
        return round(float(self.score) / float(self.max_score) * 100, 1)


class AttendanceRecord(models.Model):
    """Daily attendance. Separate from AcademicRecord because it happens daily
    and is a leading indicator of disengagement."""

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT_EXCUSED = "absent_excused", "Absent (excused)"
        ABSENT = "absent", "Absent"

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="attendance"
    )
    occurred_on = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PRESENT)

    class Meta:
        ordering = ["-occurred_on"]
        constraints = [
            models.UniqueConstraint(fields=["child", "occurred_on"], name="uniq_attendance_child_day")
        ]
        indexes = [models.Index(fields=["child", "-occurred_on"])]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.occurred_on}: {self.get_status_display()}"


# ---------------------------------------------------------------------------
# Social development
# ---------------------------------------------------------------------------
class SocialObservation(DomainEntry):
    """A structured rating of one social dimension, with context.

    Rubric ratings rather than a single "social score": disagreement between
    dimensions is itself information (a child who participates in class but is
    isolated at break time).
    """

    class Dimension(models.TextChoices):
        PEERS = "peers", "Peer relationships"
        PARTICIPATION = "participation", "Participation"
        COOPERATION = "cooperation", "Cooperation"
        CONFLICT = "conflict", "Conflict resolution"
        BELONGING = "belonging", "Sense of belonging"

    class Context(models.TextChoices):
        CLASSROOM = "classroom", "Classroom"
        PLAYGROUND = "playground", "Playground"
        GROUP_WORK = "group_work", "Group work"
        CLUB = "club", "Club or sport"
        HOME = "home", "Home"

    dimension = models.CharField(
        max_length=24, choices=Dimension.choices, default=Dimension.PEERS
    )
    rating = models.PositiveSmallIntegerField(validators=SCALE_VALIDATORS)
    context = models.CharField(
        max_length=24, choices=Context.choices, default=Context.CLASSROOM
    )

    class Meta(DomainEntry.Meta):
        verbose_name = "social observation"
        indexes = [models.Index(fields=["child", "dimension", "-occurred_on"])]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.get_dimension_display()}: {self.rating}/5"


# ---------------------------------------------------------------------------
# Healthy habits
# ---------------------------------------------------------------------------
class HabitLog(DomainEntry):
    """Daily lifestyle indicators, scored against age-appropriate guidelines.

    Values are stored raw and unscored. All judgement about whether 7 hours of
    sleep is poor lives in analytics/scoring.py, where it is versioned and
    auditable, rather than being baked into the data.
    """

    sleep_hours = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(24)],
    )
    activity_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(600)]
    )
    screen_minutes = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(1440)]
    )
    nutrition_quality = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=SCALE_VALIDATORS
    )
    ate_breakfast = models.BooleanField(null=True, blank=True)

    class Meta(DomainEntry.Meta):
        verbose_name = "habit log"
        indexes = [
            models.Index(fields=["child", "-occurred_on"]),
            models.Index(fields=["child", "source", "-occurred_on"]),
        ]
        # One log per child, per day, per *source*.
        #
        # Source has to be part of the key because habits are observed by more
        # than one person: the child reports their own screen time, a guardian
        # reports what happened at home, a mentor reports the school day. A
        # (child, day) key would make the second reporter collide with the
        # first - an IntegrityError in production, not a validation message.
        # Keeping them as separate rows also preserves who said what.
        constraints = [
            models.UniqueConstraint(
                fields=["child", "occurred_on", "source"],
                name="uniq_habit_child_day_source",
            )
        ]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.occurred_on}: habits"

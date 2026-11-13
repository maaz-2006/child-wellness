"""Child records and the relationships that grant access to them.

Two deliberate choices worth defending in the report:

1. Consent is a *gate on access*, not a checkbox in a settings page. A guardian
   link with no `consent_granted_at` grants nothing: the permission gate in
   core.permissions refuses it. See Guardianship below.
2. Relationships are never deleted, only deactivated. `is_active` plus date
   ranges preserve the historical record of who was responsible for a child and
   when, which an audit trail needs.
"""

from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone


class Child(models.Model):
    """A child in the programme.

    Data minimisation is explicit: no address, no national ID, no photograph.
    Identity is a display name, a year group and an emoji avatar. Birth date is
    kept (not full DOB exposure - age bands are what the scoring rules need).
    """

    AVATAR_CHOICES = [
        ("🦊", "Fox"),
        ("🐼", "Panda"),
        ("🦉", "Owl"),
        ("🐬", "Dolphin"),
        ("🦋", "Butterfly"),
        ("🌻", "Sunflower"),
        ("⭐", "Star"),
        ("🚀", "Rocket"),
    ]

    first_name = models.CharField(max_length=60)
    last_name = models.CharField(max_length=60, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    year_group = models.CharField(
        max_length=24,
        blank=True,
        help_text="Free text, e.g. 'Year 4' or 'Grade 3'.",
    )
    avatar = models.CharField(max_length=8, default="🦊", choices=AVATAR_CHOICES)
    school = models.ForeignKey(
        "core.School",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    # Optional link to a login account. Not every child needs one: a child can
    # be fully supported from adult observations alone.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="child_profile",
        limit_choices_to={"role": "child"},
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["first_name", "last_name"]
        verbose_name_plural = "children"
        indexes = [models.Index(fields=["is_active", "first_name"])]

    def __str__(self) -> str:
        return self.full_name

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def short_name(self) -> str:
        return self.first_name

    @property
    def age(self) -> int | None:
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        years = today.year - self.date_of_birth.year
        if (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        return years

    @property
    def age_band(self) -> str:
        """Age bands drive the habit guidelines, not the raw age."""
        age = self.age
        if age is None:
            return "unknown"
        if age < 6:
            return "early"
        if age < 11:
            return "primary"
        if age < 14:
            return "early_secondary"
        return "secondary"


class Guardianship(models.Model):
    """Parent/guardian link, and the consent that makes it effective."""

    class Label(models.TextChoices):
        MOTHER = "mother", "Mother"
        FATHER = "father", "Father"
        GUARDIAN = "guardian", "Guardian"
        OTHER = "other", "Other"

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="guardianships",
        limit_choices_to={"role": "parent"},
    )
    child = models.ForeignKey(
        Child, on_delete=models.CASCADE, related_name="guardianships"
    )
    label = models.CharField(max_length=16, choices=Label.choices, default=Label.GUARDIAN)
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Consent gate: access requires consent_granted_at to be set.
    consent_granted_at = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=16, blank=True)
    consent_revoked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parent", "child"], name="uniq_guardian_child"),
        ]
        ordering = ["-is_primary", "parent__first_name"]

    def __str__(self) -> str:
        return f"{self.parent.display_name} → {self.child.full_name}"

    @property
    def has_consent(self) -> bool:
        return self.consent_granted_at is not None and self.consent_revoked_at is None


class ConsentRecord(models.Model):
    """Immutable-ish history of consent events.

    Guardianship holds the *current* state for fast permission checks; this
    table holds the *story* - who agreed to what, when, and what evidence
    exists. Revocation is a new state on the existing row, never a deletion.
    """

    class Type(models.TextChoices):
        PARTICIPATION = "participation", "Programme participation"
        DATA_PROCESSING = "data_processing", "Wellness data processing"
        MEDIA = "media", "Photos and media"

    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name="consents")
    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="consent_records",
    )
    consent_type = models.CharField(
        max_length=24, choices=Type.choices, default=Type.PARTICIPATION
    )
    version = models.CharField(max_length=16, default="1.0")
    granted_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    evidence = models.CharField(
        max_length=120,
        blank=True,
        help_text="How consent was captured, e.g. 'signed form 2026-11-14'.",
    )
    notes = models.TextField(blank=True, validators=[MaxLengthValidator(1000)])

    class Meta:
        ordering = ["-granted_at"]
        indexes = [models.Index(fields=["child", "consent_type", "-granted_at"])]

    def __str__(self) -> str:
        state = "revoked" if self.revoked_at else "granted"
        return f"{self.get_consent_type_display()} {state} for {self.child.full_name}"


class Mentorship(models.Model):
    """A bounded, revocable assignment of a mentor to a child."""

    class Role(models.TextChoices):
        CLASS_TEACHER = "class_teacher", "Class teacher"
        SUBJECT_TEACHER = "subject_teacher", "Subject teacher"
        COUNSELLOR = "counsellor", "Counsellor"
        COACH = "coach", "Coach"
        MENTOR = "mentor", "Mentor"

    mentor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mentorships",
        limit_choices_to={"role": "mentor"},
    )
    child = models.ForeignKey(
        Child, on_delete=models.CASCADE, related_name="mentorships"
    )
    role = models.CharField(
        max_length=24, choices=Role.choices, default=Role.CLASS_TEACHER
    )
    subject = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    active_from = models.DateField(default=timezone.localdate)
    active_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["mentor", "child", "role"], name="uniq_mentor_child_role"
            ),
        ]
        ordering = ["child__first_name"]

    def __str__(self) -> str:
        return f"{self.mentor.display_name} → {self.child.full_name} ({self.get_role_display()})"

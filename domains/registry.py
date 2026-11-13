"""Module registry.

One list that describes the four wellness domains, so the dashboard, scoring
engine, charts and admin do not each hardcode their own copy. Adding a fifth
module means adding one entry here plus its model.
"""

from dataclasses import dataclass

from core.permissions import Resource

from .models import AcademicRecord, AttendanceRecord, EmotionalCheckin, HabitLog, SocialObservation


@dataclass(frozen=True)
class DomainModule:
    key: str
    label: str
    short_label: str
    icon: str
    model: type
    resource: str
    description: str
    #: True when a *higher* measurement is better (academic score, activity),
    #: False where a higher raw value is worse (screen time).
    higher_is_better: bool = True
    unit: str = ""
    #: Template fragment that renders one row of this domain's table. Kept in
    #: the registry so the generic list view does not need a branch per module.
    row_template: str = "domains/rows/_generic.html"
    #: What one record is called, for headings and buttons.
    entry_noun: str = "record"
    entry_noun_plural: str = "records"


DOMAINS: tuple[DomainModule, ...] = (
    DomainModule(
        key="emotional",
        label="Emotional wellness",
        short_label="Emotional",
        icon="💗",
        model=EmotionalCheckin,
        resource=Resource.EMOTIONAL,
        description="How the child says they feel, and what adults notice.",
        unit="/5",
        row_template="domains/rows/_emotional.html",
        entry_noun="check-in",
        entry_noun_plural="check-ins",
    ),
    DomainModule(
        key="academic",
        label="Academic progress",
        short_label="Academic",
        icon="📚",
        model=AcademicRecord,
        resource=Resource.ACADEMIC,
        description="Assessment outcomes, targets and attendance.",
        unit="%",
        row_template="domains/rows/_academic.html",
        entry_noun="assessment",
        entry_noun_plural="assessments",
    ),
    DomainModule(
        key="social",
        label="Social development",
        short_label="Social",
        icon="🤝",
        model=SocialObservation,
        resource=Resource.SOCIAL,
        description="Peer relationships, participation and belonging.",
        unit="/5",
        row_template="domains/rows/_social.html",
        entry_noun="observation",
        entry_noun_plural="observations",
    ),
    DomainModule(
        key="habits",
        label="Healthy habits",
        short_label="Habits",
        icon="🌙",
        model=HabitLog,
        resource=Resource.HABITS,
        description="Sleep, activity, screen time and nutrition.",
        unit="",
        row_template="domains/rows/_habits.html",
        entry_noun="daily log",
        entry_noun_plural="daily logs",
    ),
)

DOMAINS_BY_KEY = {module.key: module for module in DOMAINS}

ATTENDANCE_MODEL = AttendanceRecord

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
    ),
)

DOMAINS_BY_KEY = {module.key: module for module in DOMAINS}

ATTENDANCE_MODEL = AttendanceRecord

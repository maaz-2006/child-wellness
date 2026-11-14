"""Generate a synthetic cohort for demonstration, development and evaluation.

Why this exists, in one paragraph: the platform handles the most sensitive
category of personal data there is, so it must never contain a real child's
records during development or marking. Everything below is fabricated. The
generator is also the *evaluation instrument* - because the archetype and the
simulated onset date of each child are recorded as ground truth, the alert engine
and the anomaly detector can later be measured against a known answer instead of
being eyeballed.

The model of behaviour is deliberately simple and honest: one latent quality
score `q` in [0, 1] per child per day, from which every domain is derived with
noise. That produces the cross-domain correlation the alert engine relies on
(a child who stops sleeping also stops attending), without pretending to be a
clinical simulation.

Usage:
    python manage.py seed_demo                 # 24 children, 84 days
    python manage.py seed_demo --reset         # remove previous demo data first
    python manage.py seed_demo --children 60 --days 120 --seed 7
"""

from __future__ import annotations

import math
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from analytics.models import ScenarioLabel
from children.models import Child, ConsentRecord, Guardianship, Mentorship
from core.models import Role, School, User
from domains.models import (
    AcademicRecord,
    AttendanceRecord,
    EmotionalCheckin,
    HabitLog,
    NoteVisibility,
    SocialObservation,
    Source,
)
from feedback.models import PulseResponse, current_week_start

DEMO_PASSWORD = "kito-demo-2026"
DEMO_EMAIL_DOMAIN = "demo.kito.local"

FIRST_NAMES = [
    "Amara", "Tunde", "Zuri", "Kofi", "Nia", "Juma", "Sanaa", "Baraka", "Imani", "Neema",
    "Faraja", "Amani", "Thabo", "Lerato", "Sipho", "Naledi", "Kwame", "Adaeze", "Chidi", "Esi",
    "Halima", "Yusuf", "Maya", "Rafiki", "Tumaini", "Zawadi", "Jabari", "Kito", "Lulu", "Mosi",
]
LAST_NAMES = [
    "Otieno", "Mwangi", "Achieng", "Kamau", "Njoroge", "Wanjiku", "Odhiambo", "Chebet",
    "Mutiso", "Nyambura", "Omondi", "Karanja",
]
SUBJECTS = ["Mathematics", "English", "Science", "Social Studies", "Art"]
SUBJECT_WEIGHTS = [0.28, 0.26, 0.22, 0.14, 0.10]
SOCIAL_DIMENSIONS = [
    ("peers", 0.3),
    ("participation", 0.25),
    ("cooperation", 0.2),
    ("conflict", 0.1),
    ("belonging", 0.15),
]
CONTEXTS = ["classroom", "classroom", "group_work", "playground", "club"]

#: Distribution of archetypes. Healthy dominates, as it would in a real cohort;
#: roughly one child in eight is in trouble at any time.
ARCHETYPE_MIX = [
    (ScenarioLabel.Archetype.HEALTHY, 0.50),
    (ScenarioLabel.Archetype.GRADUAL_DECLINE, 0.18),
    (ScenarioLabel.Archetype.SUDDEN_EVENT, 0.10),
    (ScenarioLabel.Archetype.RECOVERING, 0.12),
    (ScenarioLabel.Archetype.SPARSE, 0.10),
]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class Command(BaseCommand):
    help = "Create a synthetic school cohort with known wellness trajectories."

    def add_arguments(self, parser):
        parser.add_argument("--children", type=int, default=24)
        parser.add_argument("--days", type=int, default=84, help="History length in days.")
        parser.add_argument("--seed", type=int, default=42, help="RNG seed; same seed, same cohort.")
        parser.add_argument("--reset", action="store_true", help="Delete previous demo data first.")
        parser.add_argument(
            "--append",
            action="store_true",
            help="Add another cohort alongside existing demo data instead of refusing.",
        )
        parser.add_argument(
            "--no-consent-ratio",
            type=float,
            default=0.1,
            help="Fraction of guardianships left without recorded consent, to exercise the gate.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        self.rng = random.Random(options["seed"])
        self.children_count = options["children"]
        self.days = options["days"]
        self.no_consent_ratio = options["no_consent_ratio"]
        self.end = timezone.localdate()
        self.start = self.end - timedelta(days=self.days - 1)

        # Seeding twice without --reset silently doubles the cohort, which then
        # looks like "the dashboard is showing everyone twice". Refuse instead.
        existing = Child.objects.filter(scenario_label__isnull=False).count()
        if existing and not options["reset"] and not options["append"]:
            raise CommandError(
                f"{existing} demo children already exist. "
                "Use --reset to rebuild the cohort, or --append to add another group."
            )

        with transaction.atomic():
            if options["reset"]:
                self._reset()
            school = self._school()
            mentors = self._mentors(school)
            children = self._children(school, mentors)
            self._generate(children)

        # The designated safeguarding lead must exist before the engine runs,
        # because urgent and safeguarding alerts are assigned to that named
        # person at creation time.
        if school.safeguarding_lead_id is None and mentors:
            school.safeguarding_lead = mentors[2] if len(mentors) > 2 else mentors[0]
            school.save(update_fields=["safeguarding_lead"])

        # Scores are derived data, so they are computed after the raw rows are
        # committed. Seeding a demo without this step would leave every trend
        # chart empty and make the platform look broken rather than uncomputed.
        from analytics import scoring

        self.scores = scoring.recompute_all(as_of=self.end)
        self._pulse(children)

        from alerts import engine

        self.alerts = engine.evaluate_all(as_of=self.end)
        self._report(school, children)

    def _pulse(self, children: list[Child]) -> None:
        """Create a few weeks of guardian pulse responses for the demo.

        The pulse is correlated with the synthetic archetype so that a declining
        child's guardian also reports difficult weeks. That makes the
        guardian-pulse rule demonstrable without inventing a second, unrelated
        dataset.
        """
        this_week = current_week_start(self.end)
        created = 0
        for child in children:
            if not child.has_consent:
                continue
            label = child.scenario_label
            guardian_link = (
                child.guardianships.filter(is_primary=True).first()
                or child.guardianships.first()
            )
            if guardian_link is None:
                continue

            for offset in range(4):
                week_start = this_week - timedelta(days=7 * offset)
                if label.archetype == ScenarioLabel.Archetype.SPARSE and offset % 2:
                    continue

                if label.archetype in (
                    ScenarioLabel.Archetype.GRADUAL_DECLINE,
                    ScenarioLabel.Archetype.SUDDEN_EVENT,
                ) and label.onset_date and week_start >= label.onset_date - timedelta(days=7):
                    wellbeing = 2
                    support = 2
                elif (
                    label.archetype == ScenarioLabel.Archetype.RECOVERING
                    and label.onset_date
                    and week_start < label.onset_date
                ):
                    wellbeing = 2
                    support = 3
                elif label.archetype == ScenarioLabel.Archetype.HEALTHY:
                    wellbeing = 5 if self.rng.random() < 0.6 else 4
                    support = 4
                else:
                    wellbeing = 3
                    support = 3

                PulseResponse.objects.create(
                    child=child,
                    guardian=guardian_link.parent,
                    week_start=week_start,
                    wellbeing=wellbeing,
                    support=support,
                    comment="",
                )
                created += 1

        self.counts["pulse responses"] = created

    # ------------------------------------------------------------------
    def _reset(self) -> None:
        demo_children = Child.objects.filter(scenario_label__isnull=False)
        count = demo_children.count()
        demo_children.delete()
        users = User.objects.filter(email__endswith=f"@{DEMO_EMAIL_DOMAIN}").exclude(pk=1)
        user_count = users.count()
        users.delete()
        self.stdout.write(f"  reset: removed {count} demo children, {user_count} demo users")

    def _school(self) -> School:
        school, _ = School.objects.get_or_create(
            name="Riverside Primary School",
            defaults={"short_name": "Riverside", "timezone": "Africa/Nairobi"},
        )
        return school

    def _unique_username(self, base: str) -> str:
        candidate = base.lower().replace(" ", ".")
        suffix = 2
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base.lower().replace(' ', '.')}{suffix}"
            suffix += 1
        return candidate

    def _make_user(self, username_base: str, first: str, last: str, role: str) -> User:
        username = self._unique_username(username_base)
        return User.objects.create_user(
            username=username,
            email=f"{username}@{DEMO_EMAIL_DOMAIN}",
            password=DEMO_PASSWORD,
            first_name=first,
            last_name=last,
            role=role,
        )

    def _mentors(self, school: School) -> list[User]:
        people = [
            ("ruth", "Ruth", "Achieng", Mentorship.Role.CLASS_TEACHER),
            ("daniel", "Daniel", "Mutiso", Mentorship.Role.SUBJECT_TEACHER),
            ("grace", "Grace", "Nyambura", Mentorship.Role.COUNSELLOR),
            ("peter", "Peter", "Omondi", Mentorship.Role.COACH),
        ]
        mentors = []
        for base, first, last, _role in people:
            existing = User.objects.filter(
                username=base, email__endswith=f"@{DEMO_EMAIL_DOMAIN}"
            ).first()
            mentors.append(existing or self._make_user(base, first, last, Role.MENTOR))
        self._mentor_roles = {m.username: role for m, (_b, _f, _l, role) in zip(mentors, people)}
        return mentors

    def _archetype_for(self, index: int) -> str:
        """Deterministic distribution, not independent sampling, so that every
        cohort of any size contains each archetype."""
        slot = (index * 0.61803398875) % 1.0  # low-discrepancy sequence
        cumulative = 0.0
        for archetype, weight in ARCHETYPE_MIX:
            cumulative += weight
            if slot <= cumulative:
                return archetype
        return ScenarioLabel.Archetype.HEALTHY

    def _children(self, school: School, mentors: list[User]) -> list[Child]:
        children: list[Child] = []
        used_names: set[str] = set()

        for index in range(self.children_count):
            for _attempt in range(50):
                first = self.rng.choice(FIRST_NAMES)
                last = self.rng.choice(LAST_NAMES)
                if f"{first} {last}" not in used_names:
                    break
            used_names.add(f"{first} {last}")

            archetype = self._archetype_for(index)
            year = self.rng.choice(["Year 3", "Year 4", "Year 5", "Year 6"])
            age = {"Year 3": 8, "Year 4": 9, "Year 5": 10, "Year 6": 11}[year]
            dob = self.end - timedelta(days=age * 365 + self.rng.randint(-140, 140))

            child = Child.objects.create(
                first_name=first,
                last_name=last,
                date_of_birth=dob,
                year_group=year,
                avatar=self.rng.choice(Child.AVATAR_CHOICES)[0],
                school=school,
            )

            onset = None
            if archetype in (
                ScenarioLabel.Archetype.GRADUAL_DECLINE,
                ScenarioLabel.Archetype.SUDDEN_EVENT,
            ):
                onset = self.start + timedelta(days=int(self.days * 0.5) + self.rng.randint(0, 8))
            elif archetype == ScenarioLabel.Archetype.RECOVERING:
                onset = self.start + timedelta(days=int(self.days * 0.35) + self.rng.randint(0, 6))

            ScenarioLabel.objects.create(
                child=child,
                archetype=archetype,
                onset_date=onset,
                severity=self.rng.choice(["low", "moderate", "moderate", "high"]),
                notes="Synthetic cohort label. Never read by the alert engine.",
            )

            # --- guardian(s) -------------------------------------------------
            primary = self._make_user(
                f"parent.{first}", f"Guardian of {first}", last, Role.PARENT
            )
            has_consent = self.rng.random() > self.no_consent_ratio
            Guardianship.objects.create(
                parent=primary,
                child=child,
                label=Guardianship.Label.GUARDIAN,
                is_primary=True,
                consent_granted_at=(timezone.now() - timedelta(days=30)) if has_consent else None,
                consent_version="1.0" if has_consent else "",
            )
            if has_consent:
                ConsentRecord.objects.create(
                    child=child,
                    guardian=primary,
                    consent_type=ConsentRecord.Type.DATA_PROCESSING,
                    version="1.0",
                    granted_at=timezone.now() - timedelta(days=30),
                    evidence="Synthetic consent for demonstration",
                )

            # ~30% of children have a second guardian
            if self.rng.random() < 0.3:
                secondary = self._make_user(
                    f"parent2.{first}", f"Second guardian of {first}", last, Role.PARENT
                )
                Guardianship.objects.create(
                    parent=secondary,
                    child=child,
                    label=Guardianship.Label.OTHER,
                    is_primary=False,
                    consent_granted_at=(timezone.now() - timedelta(days=25)) if has_consent else None,
                    consent_version="1.0" if has_consent else "",
                )

            # --- mentor assignment ------------------------------------------
            mentor = mentors[index % len(mentors)]
            Mentorship.objects.create(
                mentor=mentor,
                child=child,
                role=self._mentor_roles.get(mentor.username, Mentorship.Role.CLASS_TEACHER),
                is_active=True,
                active_from=self.start - timedelta(days=60),
            )
            if index % 7 == 0:
                counsellor = mentors[2]
                if counsellor != mentor:
                    Mentorship.objects.get_or_create(
                        mentor=counsellor,
                        child=child,
                        role=Mentorship.Role.COUNSELLOR,
                        defaults={"is_active": True, "active_from": self.start - timedelta(days=20)},
                    )

            # --- optional child login ----------------------------------------
            if index % 3 == 0:
                child_user = self._make_user(f"child.{first}", first, last, Role.CHILD)
                child.user = child_user
                child.save(update_fields=["user"])

            children.append(child)

        return children

    # ------------------------------------------------------------------
    def _quality(self, archetype: str, day: int, onset_index: int | None) -> float:
        """Latent wellbeing in [0, 1] for one child on one day."""
        noise = self.rng.gauss(0, 0.045)
        weekly = 0.03 * math.sin(day / 7.0 * math.tau)
        base = 0.78 + noise + weekly

        if archetype == ScenarioLabel.Archetype.HEALTHY:
            return clamp(base, 0.55, 0.97)

        if archetype == ScenarioLabel.Archetype.SPARSE:
            return clamp(0.62 + noise, 0.35, 0.85)

        if archetype == ScenarioLabel.Archetype.GRADUAL_DECLINE:
            if onset_index is None or day < onset_index:
                return clamp(base, 0.55, 0.95)
            progress = clamp((day - onset_index) / 28.0)
            return clamp(0.78 * (1 - progress) + 0.22 * progress + noise, 0.12, 0.9)

        if archetype == ScenarioLabel.Archetype.SUDDEN_EVENT:
            if onset_index is None or day < onset_index:
                return clamp(base, 0.55, 0.95)
            elapsed = day - onset_index
            if elapsed < 12:
                return clamp(0.28 + noise, 0.1, 0.45)
            return clamp(0.28 + min(0.25, (elapsed - 12) * 0.012) + noise, 0.15, 0.65)

        if archetype == ScenarioLabel.Archetype.RECOVERING:
            if onset_index is None or day < onset_index:
                return clamp(0.3 + noise, 0.12, 0.5)
            progress = clamp((day - onset_index) / 35.0)
            return clamp(0.3 + 0.52 * progress + noise, 0.2, 0.92)

        return clamp(base, 0.4, 0.9)

    def _generate(self, children: list[Child]) -> None:
        checkins: list[EmotionalCheckin] = []
        habits: list[HabitLog] = []
        academics: list[AcademicRecord] = []
        attendance: list[AttendanceRecord] = []
        social: list[SocialObservation] = []

        for child in children:
            label = child.scenario_label
            onset_index = None
            if label.onset_date:
                onset_index = (label.onset_date - self.start).days

            for day in range(self.days):
                date = self.start + timedelta(days=day)
                weekend = date.weekday() >= 5
                q = self._quality(label.archetype, day, onset_index)

                # Sparse archetype leaves gaps on purpose: thin data must not
                # silently look like good or bad data.
                present = label.archetype != ScenarioLabel.Archetype.SPARSE or self.rng.random() < 0.28
                if present and not weekend and self.rng.random() < 0.78:
                    checkins.append(
                        self._checkin(child, date, q, Source.CHILD, child.user)
                    )
                if present and not weekend and self.rng.random() < 0.16:
                    checkins.append(
                        self._checkin(child, date, q, Source.MENTOR, None)
                    )
                if present and (not weekend or self.rng.random() < 0.3) and self.rng.random() < 0.8:
                    habits.append(self._habit(child, date, q, weekend))

                if not weekend:
                    if self.rng.random() < 0.92:
                        attendance.append(self._attendance(child, date, q))
                    if self.rng.random() < 0.42:
                        academics.append(self._academic(child, date, q))
                    if self.rng.random() < 0.28:
                        social.append(self._social(child, date, q))

        EmotionalCheckin.objects.bulk_create(checkins, batch_size=1000)
        HabitLog.objects.bulk_create(habits, batch_size=1000)
        AcademicRecord.objects.bulk_create(academics, batch_size=1000)
        AttendanceRecord.objects.bulk_create(attendance, batch_size=1000)
        SocialObservation.objects.bulk_create(social, batch_size=1000)

        self.counts = {
            "check-ins": len(checkins),
            "habit logs": len(habits),
            "academic records": len(academics),
            "attendance days": len(attendance),
            "social observations": len(social),
        }

    # ------------------------------------------------------------------
    def _checkin(self, child, date, q, source, author) -> EmotionalCheckin:
        mood = int(clamp(round(1 + 4 * q + self.rng.gauss(0, 0.45)), 1, 5))
        energy = int(clamp(round(1 + 4 * q + self.rng.gauss(0, 0.55)), 1, 5))
        return EmotionalCheckin(
            child=child,
            recorded_by=author,
            source=source,
            occurred_on=date,
            mood=mood,
            energy=energy,
            sleep_quality=int(clamp(round(1 + 4 * q + self.rng.gauss(0, 0.5)), 1, 5)),
            felt_connected=int(clamp(round(1 + 4 * q + self.rng.gauss(0, 0.6)), 1, 5)),
            note="",
            note_visibility=NoteVisibility.PRIVATE
            if source == Source.CHILD
            else NoteVisibility.MENTOR,
        )

    def _habit(self, child, date, q, weekend) -> HabitLog:
        sleep = clamp(6.4 + 3.3 * q + self.rng.gauss(0, 0.45), 4.0, 11.5)
        activity = int(clamp(15 + 60 * q + self.rng.gauss(0, 14), 0, 180))
        screen = int(clamp(230 - 130 * q + self.rng.gauss(0, 30), 20, 420))
        if weekend:
            activity += 12
            screen += 35
        return HabitLog(
            child=child,
            occurred_on=date,
            source=Source.CHILD,
            sleep_hours=Decimal(str(round(sleep, 1))),
            activity_minutes=activity,
            screen_minutes=screen,
            nutrition_quality=int(clamp(round(1 + 4 * q + self.rng.gauss(0, 0.6)), 1, 5)),
            ate_breakfast=self.rng.random() < (0.55 + 0.35 * q),
            note_visibility=NoteVisibility.PRIVATE,
        )

    def _attendance(self, child, date, q) -> AttendanceRecord:
        roll = self.rng.random()
        absent_chance = clamp(0.16 - 0.14 * q, 0.005, 0.2)
        if roll < absent_chance * 0.35:
            status = AttendanceRecord.Status.ABSENT
        elif roll < absent_chance * 0.6:
            status = AttendanceRecord.Status.ABSENT_EXCUSED
        elif roll < absent_chance:
            status = AttendanceRecord.Status.LATE
        else:
            status = AttendanceRecord.Status.PRESENT
        return AttendanceRecord(child=child, occurred_on=date, status=status)

    def _academic(self, child, date, q) -> AcademicRecord:
        subject = self.rng.choices(SUBJECTS, weights=SUBJECT_WEIGHTS, k=1)[0]
        pct = clamp(40 + 52 * q + self.rng.gauss(0, 5.5), 20, 99)
        return AcademicRecord(
            child=child,
            occurred_on=date,
            source=Source.MENTOR,
            subject=subject,
            kind=self.rng.choice(
                [
                    AcademicRecord.Kind.ASSIGNMENT,
                    AcademicRecord.Kind.TEST,
                    AcademicRecord.Kind.PROJECT,
                    AcademicRecord.Kind.READING,
                ]
            ),
            title=f"{subject} {self.rng.choice(['classwork', 'unit check', 'homework', 'practical'])}",
            score=Decimal(str(round(pct, 1))),
            max_score=Decimal("100"),
            note_visibility=NoteVisibility.MENTOR,
        )

    def _social(self, child, date, q) -> SocialObservation:
        dimension = self.rng.choices(
            [d for d, _w in SOCIAL_DIMENSIONS], weights=[w for _d, w in SOCIAL_DIMENSIONS], k=1
        )[0]
        rating = int(clamp(round(1 + 4 * q + self.rng.gauss(0, 0.5)), 1, 5))
        return SocialObservation(
            child=child,
            occurred_on=date,
            source=Source.MENTOR,
            dimension=dimension,
            rating=rating,
            context=self.rng.choice(CONTEXTS),
            note_visibility=NoteVisibility.MENTOR,
        )

    # ------------------------------------------------------------------
    def _report(self, school, children: list[Child]) -> None:
        from collections import Counter

        # A Django superuser who signed up through `createsuperuser` gets the
        # default role (parent), which would leave them unable to reach the
        # admin views. Superuser implies administrator, so reconcile it here
        # rather than making it a manual step that gets forgotten on deploy.
        promoted = User.objects.filter(is_superuser=True).exclude(role=Role.ADMIN).update(
            role=Role.ADMIN
        )
        if promoted:
            self.stdout.write(f"  promoted {promoted} superuser(s) to the admin role")

        archetypes = Counter(c.scenario_label.archetype for c in children)
        style = self.style.SUCCESS

        self.stdout.write("")
        self.stdout.write(style("Synthetic cohort created"))
        self.stdout.write(f"  school      {school.name}")
        self.stdout.write(f"  period      {self.start} to {self.end} ({self.days} days)")
        self.stdout.write(f"  children    {len(children)}")
        for name, count in self.counts.items():
            self.stdout.write(f"  {name:<20}{count}")
        scores = getattr(self, "scores", None)
        if scores:
            self.stdout.write(f"  {'wellness scores':<20}{scores['scores']}")
        alerts = getattr(self, "alerts", None)
        if alerts:
            self.stdout.write(
                f"  {'alerts opened/seen':<20}{alerts['alerts']} "
                f"(urgent {alerts['by_tier'].get('urgent', 0)}, "
                f"concern {alerts['by_tier'].get('concern', 0)}, "
                f"watch {alerts['by_tier'].get('watch', 0)})"
            )
        self.stdout.write("")
        self.stdout.write("  archetypes")
        for archetype, count in sorted(archetypes.items()):
            self.stdout.write(f"    {archetype:<18}{count}")
        self.stdout.write("")
        self.stdout.write(style(f"  All demo accounts use the password: {DEMO_PASSWORD}"))
        self.stdout.write("  Examples:")
        sample = children[0]
        guardian = sample.guardianships.filter(is_primary=True).first()
        if guardian:
            self.stdout.write(f"    parent  {guardian.parent.username}")
        mentor = sample.mentorships.filter(is_active=True).first()
        if mentor:
            self.stdout.write(f"    mentor  {mentor.mentor.username}")
        if sample.user:
            self.stdout.write(f"    child   {sample.user.username}")
        admin = User.objects.filter(role=Role.ADMIN).first()
        if admin:
            self.stdout.write(f"    admin   {admin.username}")
        self.stdout.write("")

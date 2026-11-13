"""Tests for the synthetic cohort generator.

These matter more than they look: every later evaluation claim (alert precision,
detection lead time) is only as meaningful as the ground truth this command
produces.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from analytics.models import ScenarioLabel
from children.models import Child, Guardianship
from core.models import User
from domains.models import EmotionalCheckin, HabitLog


class SeedDemoTests(TestCase):
    def _seed(self, **kwargs):
        call_command("seed_demo", stdout=StringIO(), **kwargs)

    def test_creates_labelled_cohort_with_data(self):
        self._seed(children=6, days=30)

        self.assertEqual(Child.objects.count(), 6)
        self.assertEqual(ScenarioLabel.objects.count(), 6)
        self.assertGreater(EmotionalCheckin.objects.count(), 0)
        self.assertGreater(HabitLog.objects.count(), 0)

    def test_every_child_has_mentor_and_guardian(self):
        self._seed(children=4, days=21)

        for child in Child.objects.all():
            self.assertTrue(child.mentorships.filter(is_active=True).exists())
            self.assertTrue(child.guardianships.exists())

    def test_some_guardianships_lack_consent_to_exercise_the_gate(self):
        self._seed(children=20, days=21, no_consent_ratio=0.5)

        without_consent = Guardianship.objects.filter(consent_granted_at__isnull=True)
        self.assertGreater(without_consent.count(), 0)

    def test_refuses_to_double_seed_without_reset(self):
        self._seed(children=3, days=14)
        with self.assertRaises(CommandError):
            self._seed(children=3, days=14)

    def test_reset_replaces_rather_than_duplicates(self):
        self._seed(children=3, days=14)
        self._seed(children=5, days=14, reset=True)

        self.assertEqual(Child.objects.count(), 5)

    def test_declining_archetypes_have_an_onset_date(self):
        self._seed(children=20, days=60)

        declining = ScenarioLabel.objects.filter(
            archetype__in=[
                ScenarioLabel.Archetype.GRADUAL_DECLINE,
                ScenarioLabel.Archetype.SUDDEN_EVENT,
            ]
        )
        self.assertGreater(declining.count(), 0)
        for label in declining:
            self.assertIsNotNone(label.onset_date)

    def test_superusers_are_promoted_to_admin_role(self):
        User.objects.create_superuser("boss", "boss@example.com", "pw-test-1234")
        self._seed(children=2, days=14)

        boss = User.objects.get(username="boss")
        self.assertEqual(boss.role, "admin")

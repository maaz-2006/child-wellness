"""Tests for row-level access and the entry flows.

The permission matrix tests in core/ prove the *page* gate. These prove the
harder half: that a granted page does not imply every row on it, and that the
two write paths (child self-report, adult observation) cannot be used to widen
access.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from children.models import Child, Guardianship, Mentorship
from core.models import Role, School, User
from core.permissions import Access

from . import access
from .models import EmotionalCheckin, NoteVisibility, Source
from .registry import DOMAINS_BY_KEY


class DomainFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Riverside Primary")
        cls.child = Child.objects.create(
            first_name="Amara", year_group="Year 4", school=cls.school
        )
        cls.other_child = Child.objects.create(
            first_name="Tunde", year_group="Year 5", school=cls.school
        )

        cls.parent = User.objects.create_user(
            username="parent1", password="pw-test-1234", role=Role.PARENT
        )
        cls.other_parent = User.objects.create_user(
            username="parent2", password="pw-test-1234", role=Role.PARENT
        )
        cls.mentor = User.objects.create_user(
            username="mentor1", password="pw-test-1234", role=Role.MENTOR
        )
        cls.other_mentor = User.objects.create_user(
            username="mentor2", password="pw-test-1234", role=Role.MENTOR
        )
        cls.admin = User.objects.create_user(
            username="admin1", password="pw-test-1234", role=Role.ADMIN
        )
        cls.child_user = User.objects.create_user(
            username="child1", password="pw-test-1234", role=Role.CHILD
        )

        cls.child.user = cls.child_user
        cls.child.save(update_fields=["user"])

        cls.guardianship = Guardianship.objects.create(
            parent=cls.parent,
            child=cls.child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
            is_primary=True,
        )
        cls.mentorship = Mentorship.objects.create(mentor=cls.mentor, child=cls.child)

        cls.today = timezone.localdate()
        cls.private = EmotionalCheckin.objects.create(
            child=cls.child,
            recorded_by=cls.child_user,
            source=Source.CHILD,
            occurred_on=cls.today - timedelta(days=2),
            mood=2,
            energy=2,
            note="private text",
            note_visibility=NoteVisibility.PRIVATE,
        )
        cls.shared = EmotionalCheckin.objects.create(
            child=cls.child,
            recorded_by=cls.child_user,
            source=Source.CHILD,
            occurred_on=cls.today - timedelta(days=1),
            mood=4,
            energy=4,
            note="shared text",
            note_visibility=NoteVisibility.MENTOR,
        )
        cls.observation = EmotionalCheckin.objects.create(
            child=cls.child,
            recorded_by=cls.mentor,
            source=Source.MENTOR,
            occurred_on=cls.today - timedelta(days=1),
            mood=2,
            energy=2,
            note="obs text",
            note_visibility=NoteVisibility.MENTOR,
        )
        cls.unrelated_observation = EmotionalCheckin.objects.create(
            child=cls.other_child,
            recorded_by=cls.mentor,
            source=Source.MENTOR,
            occurred_on=cls.today,
            mood=3,
            energy=3,
            note="unrelated text",
        )

    def emotional_url(self, child=None, name="emotional"):
        return reverse("domains:list", args=[(child or self.child).pk, name])

    def detail_url(self, child=None):
        return reverse("children:detail", args=[(child or self.child).pk])


class EntriesForTests(DomainFixture):
    module = DOMAINS_BY_KEY["emotional"]

    def test_parent_reads_every_row_for_their_child_only(self):
        rows = access.entries_for(self.parent, self.child, self.module)
        self.assertEqual(rows.count(), 3)
        self.assertNotIn(self.unrelated_observation, rows)

    def test_parent_without_consent_gets_no_rows(self):
        self.guardianship.consent_granted_at = None
        self.guardianship.save(update_fields=["consent_granted_at"])
        self.assertEqual(
            access.entries_for(self.parent, self.child, self.module).count(), 0
        )

    def test_mentor_sees_observations_and_shared_checkins_only(self):
        rows = access.entries_for(self.mentor, self.child, self.module)
        self.assertIn(self.observation, rows)
        self.assertIn(self.shared, rows)
        self.assertNotIn(self.private, rows)
        self.assertNotIn(self.unrelated_observation, rows)

    def test_child_sees_own_self_reports_and_never_adult_observations(self):
        rows = access.entries_for(self.child_user, self.child, self.module)
        self.assertIn(self.private, rows)
        self.assertIn(self.shared, rows)
        self.assertNotIn(self.observation, rows)

    def test_admin_gets_no_individual_emotional_rows(self):
        self.assertEqual(
            access.entries_for(self.admin, self.child, self.module).count(), 0
        )

    def test_unrelated_mentor_gets_nothing(self):
        self.assertEqual(
            access.entries_for(self.other_mentor, self.child, self.module).count(), 0
        )

    def test_modes_match_the_matrix(self):
        self.assertEqual(access.mode_for(self.child_user, self.child, self.module), "full")
        self.assertEqual(access.mode_for(self.parent, self.child, self.module), "full")
        self.assertEqual(access.mode_for(self.mentor, self.child, self.module), "shared")
        self.assertEqual(access.mode_for(self.admin, self.child, self.module), "none")
        self.assertEqual(
            access.mode_for(self.other_mentor, self.child, self.module), "none"
        )


class DetailPageTests(DomainFixture):
    def test_assigned_mentor_can_open_detail(self):
        self.client.force_login(self.mentor)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amara")
        self.assertContains(response, "Care team")

    def test_unrelated_mentor_is_denied(self):
        self.client.force_login(self.other_mentor)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 403)

    def test_parent_without_consent_is_denied(self):
        self.guardianship.consent_granted_at = None
        self.guardianship.save(update_fields=["consent_granted_at"])
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 403)

    def test_admin_sees_identity_but_no_emotional_content(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amara")
        self.assertNotContains(response, "private text")
        self.assertNotContains(response, "obs text")

    def test_child_cannot_open_another_childs_page(self):
        self.client.force_login(self.child_user)
        self.assertEqual(self.client.get(self.detail_url(self.other_child)).status_code, 403)

    def test_child_account_is_not_shown_the_care_team(self):
        self.client.force_login(self.child_user)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Care team")

    def test_viewing_a_child_is_audited(self):
        from core.models import AuditLog

        self.client.force_login(self.mentor)
        self.client.get(self.detail_url())
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.VIEW, child_id=self.child.pk
            ).exists()
        )


class EmotionalListTests(DomainFixture):
    def test_mentor_sees_shared_note_but_not_private_note(self):
        self.client.force_login(self.mentor)
        response = self.client.get(self.emotional_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "shared text")
        self.assertContains(response, "obs text")
        self.assertNotContains(response, "private text")

    def test_parent_does_not_read_child_private_note(self):
        self.client.force_login(self.parent)
        response = self.client.get(self.emotional_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "private text")
        # The rating itself is visible even when the note is not.
        self.assertContains(response, "Low")

    def test_child_never_sees_an_adult_observation(self):
        self.client.force_login(self.child_user)
        response = self.client.get(self.emotional_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "obs text")

    def test_unrelated_mentor_is_denied(self):
        self.client.force_login(self.other_mentor)
        self.assertEqual(self.client.get(self.emotional_url()).status_code, 403)

    def test_admin_cannot_open_the_emotional_list(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.emotional_url()).status_code, 403)

    def test_child_gets_a_summary_for_academic_not_rows(self):
        self.client.force_login(self.child_user)
        response = self.client.get(self.emotional_url(self.child, "academic"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "summary view")
        self.assertNotContains(response, "<table", html=False)

    def test_unknown_domain_is_404(self):
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(self.emotional_url(self.child, "nonsense")).status_code, 404)


class ChildCheckinTests(DomainFixture):
    def test_child_can_submit_a_checkin(self):
        self.client.force_login(self.child_user)
        response = self.client.post(
            reverse("domains:checkin"),
            {
                "mood": 4,
                "energy": 4,
                "sleep_quality": 3,
                "felt_connected": 5,
                "note": "A good day.",
                "note_visibility": NoteVisibility.PRIVATE,
            },
        )
        self.assertRedirects(response, reverse("domains:checkin"))

        entry = EmotionalCheckin.objects.get(
            child=self.child, occurred_on=self.today, source=Source.CHILD
        )
        self.assertEqual(entry.recorded_by, self.child_user)
        self.assertEqual(entry.mood, 4)
        self.assertEqual(entry.note_visibility, NoteVisibility.PRIVATE)

    def test_submitting_twice_updates_rather_than_duplicates(self):
        self.client.force_login(self.child_user)
        url = reverse("domains:checkin")
        payload = {
            "mood": 2,
            "energy": 2,
            "note": "first",
            "note_visibility": NoteVisibility.PRIVATE,
        }
        self.client.post(url, payload)
        payload["mood"] = 5
        payload["note"] = "second"
        self.client.post(url, payload)

        entries = EmotionalCheckin.objects.filter(
            child=self.child, occurred_on=self.today, source=Source.CHILD
        )
        self.assertEqual(entries.count(), 1)
        self.assertEqual(entries.first().mood, 5)

    def test_checkin_is_blocked_without_guardian_consent(self):
        self.guardianship.consent_granted_at = None
        self.guardianship.save(update_fields=["consent_granted_at"])

        self.client.force_login(self.child_user)
        response = self.client.get(reverse("domains:checkin"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not switched on")

        self.client.post(
            reverse("domains:checkin"),
            {"mood": 5, "energy": 5, "note_visibility": NoteVisibility.PRIVATE},
        )
        self.assertFalse(
            EmotionalCheckin.objects.filter(
                child=self.child, occurred_on=self.today, source=Source.CHILD
            ).exists()
        )

    def test_checkin_form_renders_every_scale(self):
        """Regression: assigning field.choices without widget.choices rendered
        empty radio groups for the fields whose model has no choices."""
        self.client.force_login(self.child_user)
        html = self.client.get(reverse("domains:checkin")).content.decode()
        for name, expected in (
            ("mood", 5),
            ("energy", 5),
            ("sleep_quality", 5),
            ("felt_connected", 5),
            ("note_visibility", 3),
        ):
            self.assertEqual(
                html.count(f'name="{name}"'),
                expected,
                f"{name} did not render {expected} choices",
            )

    def test_adults_cannot_use_the_child_checkin_page(self):
        for user in (self.mentor, self.parent, self.admin):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("domains:checkin")).status_code, 403
            )

    def test_child_without_a_profile_is_denied(self):
        loner = User.objects.create_user(
            username="child2", password="pw-test-1234", role=Role.CHILD
        )
        self.client.force_login(loner)
        self.assertEqual(self.client.get(reverse("domains:checkin")).status_code, 403)


class ObservationTests(DomainFixture):
    def observe_url(self, child=None):
        return reverse("domains:emotional_observe", args=[(child or self.child).pk])

    def test_observe_form_renders_every_scale(self):
        self.client.force_login(self.mentor)
        html = self.client.get(self.observe_url()).content.decode()
        for name, expected in (
            ("occurred_on", 1),
            ("mood", 5),
            ("energy", 5),
            ("sleep_quality", 5),
            ("felt_connected", 5),
            ("note_visibility", 3),
        ):
            self.assertEqual(
                html.count(f'name="{name}"'),
                expected,
                f"{name} did not render {expected} choices",
            )

    def test_mentor_records_an_observation(self):
        self.client.force_login(self.other_mentor)
        # other_mentor is not assigned, so grant an assignment first.
        Mentorship.objects.create(mentor=self.other_mentor, child=self.child)

        response = self.client.post(
            self.observe_url(),
            {
                "occurred_on": self.today.isoformat(),
                "mood": 2,
                "energy": 2,
                "note": "Withdrawn at break.",
                "note_visibility": NoteVisibility.MENTOR,
            },
        )
        self.assertRedirects(response, self.emotional_url_for())

        entry = EmotionalCheckin.objects.get(
            child=self.child, occurred_on=self.today, source=Source.MENTOR
        )
        self.assertEqual(entry.recorded_by, self.other_mentor)
        self.assertEqual(entry.note, "Withdrawn at break.")

    def emotional_url_for(self):
        return reverse("domains:list", args=[self.child.pk, "emotional"])

    def test_guardian_records_an_observation_with_parent_source(self):
        self.client.force_login(self.parent)
        response = self.client.post(
            self.observe_url(),
            {
                "occurred_on": self.today.isoformat(),
                "mood": 3,
                "energy": 3,
                "note": "Quieter than usual at home.",
                "note_visibility": NoteVisibility.MENTOR,
            },
        )
        self.assertRedirects(response, self.emotional_url_for())
        entry = EmotionalCheckin.objects.get(
            child=self.child, occurred_on=self.today, source=Source.PARENT
        )
        self.assertEqual(entry.recorded_by, self.parent)

    def test_unassigned_mentor_cannot_observe(self):
        self.client.force_login(self.other_mentor)
        self.assertEqual(self.client.get(self.observe_url()).status_code, 403)

    def test_child_cannot_record_an_observation_about_themselves(self):
        self.client.force_login(self.child_user)
        self.assertEqual(self.client.get(self.observe_url()).status_code, 403)

    def test_second_mentor_is_told_the_day_is_already_covered(self):
        mentor_two = User.objects.create_user(
            username="mentor3", password="pw-test-1234", role=Role.MENTOR
        )
        Mentorship.objects.create(mentor=mentor_two, child=self.child)
        EmotionalCheckin.objects.create(
            child=self.child,
            recorded_by=self.mentor,
            source=Source.MENTOR,
            occurred_on=self.today,
            mood=3,
            energy=3,
        )

        self.client.force_login(mentor_two)
        response = self.client.post(
            self.observe_url(),
            {
                "occurred_on": self.today.isoformat(),
                "mood": 1,
                "energy": 1,
                "note": "Should not be saved.",
                "note_visibility": NoteVisibility.MENTOR,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already recorded an observation")
        self.assertFalse(
            EmotionalCheckin.objects.filter(
                child=self.child,
                occurred_on=self.today,
                source=Source.MENTOR,
                recorded_by=mentor_two,
            ).exists()
        )

    def test_future_dated_observation_is_rejected(self):
        self.client.force_login(self.mentor)
        response = self.client.post(
            self.observe_url(),
            {
                "occurred_on": (self.today + timedelta(days=1)).isoformat(),
                "mood": 3,
                "energy": 3,
                "note_visibility": NoteVisibility.MENTOR,
            },
        )
        self.assertContains(response, "cannot be dated in the future")


class MatrixExtensionTests(DomainFixture):
    def test_mentor_can_write_observations_but_not_read_emotional_content(self):
        from core import permissions
        from core.permissions import Resource

        self.assertTrue(
            permissions.has_access(
                self.mentor, self.child, Resource.EMOTIONAL_OBSERVATION, Access.WRITE
            )
        )
        self.assertFalse(
            permissions.has_access(
                self.mentor, self.child, Resource.EMOTIONAL, Access.READ
            )
        )

    def test_child_and_admin_cannot_write_observations(self):
        from core import permissions
        from core.permissions import Resource

        for user in (self.child_user, self.admin):
            self.assertFalse(
                permissions.has_access(
                    user, self.child, Resource.EMOTIONAL_OBSERVATION, Access.WRITE
                )
            )

"""Tests for the guardian pulse.

The pulse is a small feature with a large privacy surface: it is the only place a
guardian writes free text about their own child. These tests therefore check not
only that submission works, but that the comment does not leak to the
administrator and is not read by the alert rules.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from alerts import rules
from children.models import Child, Guardianship, Mentorship
from core.models import AuditLog, Role, School, User

from .models import PulseResponse, current_week_start


class PulseFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.week_start = current_week_start(cls.today)
        cls.school = School.objects.create(name="Riverside")
        cls.child = Child.objects.create(
            first_name="Amara", last_name="Otieno", year_group="Year 4", school=cls.school
        )
        cls.parent = User.objects.create_user(
            username="parent", password="pw-test-1234", role=Role.PARENT
        )
        cls.other_parent = User.objects.create_user(
            username="other", password="pw-test-1234", role=Role.PARENT
        )
        cls.mentor = User.objects.create_user(
            username="mentor", password="pw-test-1234", role=Role.MENTOR
        )
        cls.admin = User.objects.create_user(
            username="admin", password="pw-test-1234", role=Role.ADMIN
        )
        cls.child_user = User.objects.create_user(
            username="child", password="pw-test-1234", role=Role.CHILD
        )
        cls.child.user = cls.child_user
        cls.child.save(update_fields=["user"])

        Guardianship.objects.create(
            parent=cls.parent,
            child=cls.child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
            is_primary=True,
        )
        Mentorship.objects.create(mentor=cls.mentor, child=cls.child)

    def pulse_url(self):
        return reverse("feedback:pulse", args=[self.child.pk])

    def history_url(self):
        return reverse("feedback:pulse_history", args=[self.child.pk])

    def submit(self, **overrides):
        data = {
            "wellbeing": 4,
            "support": 3,
            "comment": "A better week.",
        }
        data.update(overrides)
        return self.client.post(self.pulse_url(), data)


class PulseSubmissionTests(PulseFixture):
    def test_parent_can_submit_a_pulse(self):
        self.client.force_login(self.parent)

        response = self.submit()

        self.assertEqual(response.status_code, 302)
        pulse = PulseResponse.objects.get()
        self.assertEqual(pulse.guardian, self.parent)
        self.assertEqual(pulse.child, self.child)
        self.assertEqual(pulse.week_start, self.week_start)
        self.assertEqual(pulse.wellbeing, 4)

    def test_second_submission_updates_the_same_week(self):
        self.client.force_login(self.parent)
        self.submit()

        response = self.submit(wellbeing=2)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(PulseResponse.objects.count(), 1)
        pulse = PulseResponse.objects.get()
        self.assertEqual(pulse.wellbeing, 2)

    def test_submission_is_audited(self):
        self.client.force_login(self.parent)
        self.submit()

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CREATE,
                resource_type="feedback",
                child_id=self.child.pk,
            ).exists()
        )

    def test_unrelated_parent_is_refused(self):
        self.client.force_login(self.other_parent)
        self.assertEqual(self.client.get(self.pulse_url()).status_code, 403)

    def test_child_account_is_refused(self):
        self.client.force_login(self.child_user)
        self.assertEqual(self.client.get(self.pulse_url()).status_code, 403)

    def test_mentor_account_is_refused_creating_a_pulse(self):
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(self.pulse_url()).status_code, 403)

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(self.pulse_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("core:login"), response["Location"])


class PulseVisibilityTests(PulseFixture):
    def test_mentor_can_read_the_history_for_an_assigned_child(self):
        PulseResponse.objects.create(
            child=self.child,
            guardian=self.parent,
            week_start=self.week_start,
            wellbeing=3,
            support=4,
            comment="Sleep has been difficult.",
        )
        self.client.force_login(self.mentor)

        response = self.client.get(self.history_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sleep has been difficult.")
        self.assertContains(response, "Guardian voice")

    def test_parent_can_read_their_own_child_history(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(self.history_url()).status_code, 200)

    def test_admin_is_refused_one_child_history(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.history_url()).status_code, 403)

    def test_child_is_refused_the_guardian_history(self):
        self.client.force_login(self.child_user)
        self.assertEqual(self.client.get(self.history_url()).status_code, 403)

    def test_family_page_shows_a_due_child_and_then_stops(self):
        self.client.force_login(self.parent)
        response = self.client.get(reverse("alerts:family"))
        self.assertContains(response, self.child.full_name)

        self.submit(comment="")
        response = self.client.get(reverse("alerts:family"))
        self.assertNotContains(response, "still to hear about this week")

    def test_cohort_page_is_aggregate_only(self):
        PulseResponse.objects.create(
            child=self.child,
            guardian=self.parent,
            week_start=self.week_start,
            wellbeing=2,
            support=3,
            comment="A private comment from the family.",
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse("feedback:cohort_pulse"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Guardian pulse")
        self.assertNotContains(response, self.child.full_name)
        self.assertNotContains(response, self.child.first_name)
        self.assertNotContains(response, "A private comment from the family.")

    def test_mentor_is_refused_the_cohort_pulse_page(self):
        self.client.force_login(self.mentor)
        self.assertEqual(
            self.client.get(reverse("feedback:cohort_pulse")).status_code, 403
        )


class PulseRuleTests(PulseFixture):
    def test_two_low_weeks_raise_a_concern(self):
        for offset in range(2):
            PulseResponse.objects.create(
                child=self.child,
                guardian=self.parent,
                week_start=self.week_start - timedelta(days=7 * offset),
                wellbeing=2,
                support=2,
                comment="Do not put this in an alert.",
            )

        findings = rules.evaluate(self.child, self.today)

        pulse = [f for f in findings if f.rule_key == "guardian_pulse_low"]
        self.assertEqual(len(pulse), 1)
        self.assertEqual(pulse[0].tier, "concern")
        self.assertNotIn("Do not put this in an alert.", pulse[0].summary)
        self.assertNotIn("Do not put this in an alert.", str(pulse[0].evidence))

    def test_one_low_week_is_not_a_concern(self):
        PulseResponse.objects.create(
            child=self.child,
            guardian=self.parent,
            week_start=self.week_start,
            wellbeing=2,
            support=2,
        )

        findings = rules.evaluate(self.child, self.today)

        self.assertNotIn(
            "guardian_pulse_low", [finding.rule_key for finding in findings]
        )

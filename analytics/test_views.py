"""Tests for the analytics screens.

The interesting assertions are not the 200s. They are:

* a child is refused their own score,
* an administrator is refused the individual page but allowed the aggregate,
* the aggregate page contains no child names,
* the individual page is audited, because it is a view of derived sensitive data.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from children.models import Child, Guardianship, Mentorship
from core.models import AuditLog, Role, School, User
from domains.models import EmotionalCheckin, Source


class WellnessViewFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.school = School.objects.create(name="Riverside Primary")
        cls.child = Child.objects.create(
            first_name="Amara",
            year_group="Year 4",
            school=cls.school,
            date_of_birth=cls.today - timedelta(days=8 * 365 + 40),
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

        Guardianship.objects.create(
            parent=cls.parent,
            child=cls.child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
            is_primary=True,
        )
        Mentorship.objects.create(mentor=cls.mentor, child=cls.child)

    def wellness_url(self, child=None):
        return reverse(
            "children:wellness", args=[(child or self.child).pk]
        )

    def add_good_week(self, child=None, days=5):
        child = child or self.child
        for offset in range(days):
            EmotionalCheckin.objects.create(
                child=child,
                source=Source.CHILD,
                occurred_on=self.today - timedelta(days=offset),
                mood=5,
                energy=5,
                sleep_quality=5,
                felt_connected=5,
            )


class ChildWellnessAccessTests(WellnessViewFixture):
    def test_mentor_can_open_an_assigned_child_trend(self):
        self.add_good_week()
        self.client.force_login(self.mentor)

        response = self.client.get(self.wellness_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Wellness trend")
        self.assertContains(response, "100.0")
        self.assertContains(response, "method 1.0")
        self.assertContains(response, "How this score is calculated")

    def test_parent_can_open_their_child_trend(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(self.wellness_url()).status_code, 200)

    def test_child_is_refused_their_own_score(self):
        self.client.force_login(self.child_user)
        self.assertEqual(self.client.get(self.wellness_url()).status_code, 403)

    def test_unrelated_parent_is_refused(self):
        self.client.force_login(self.other_parent)
        self.assertEqual(self.client.get(self.wellness_url()).status_code, 403)

    def test_unrelated_mentor_is_refused(self):
        self.client.force_login(self.other_mentor)
        self.assertEqual(self.client.get(self.wellness_url()).status_code, 403)

    def test_admin_is_refused_the_individual_page(self):
        """AGGREGATE is below READ, on purpose. The admin page is the cohort."""
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.wellness_url()).status_code, 403)

    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(self.wellness_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("core:login"), response["Location"])

    def test_viewing_a_trend_is_audited(self):
        self.client.force_login(self.mentor)
        self.client.get(self.wellness_url())

        entry = AuditLog.objects.filter(
            action=AuditLog.Action.VIEW,
            resource_type="score",
            child_id=self.child.pk,
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.metadata["method"], "1.0")

    def test_no_data_renders_an_empty_state_rather_than_zero_scores(self):
        Mentorship.objects.create(mentor=self.other_mentor, child=self.other_child)
        self.client.force_login(self.other_mentor)

        response = self.client.get(self.wellness_url(self.other_child))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No scores yet")
        self.assertNotContains(response, "0.0/100")

    def test_new_data_is_reflected_on_the_next_view(self):
        self.add_good_week()
        self.client.force_login(self.mentor)
        self.assertContains(self.client.get(self.wellness_url()), "100.0")

        EmotionalCheckin.objects.create(
            child=self.child,
            source=Source.CHILD,
            occurred_on=self.today - timedelta(days=6),
            mood=1,
            energy=1,
            sleep_quality=1,
            felt_connected=1,
        )

        response = self.client.get(self.wellness_url())
        self.assertContains(response, "83.3")


class CohortWellnessAccessTests(WellnessViewFixture):
    def cohort_url(self):
        return reverse("analytics:cohort_wellness")

    def test_admin_can_open_the_aggregate_page(self):
        self.add_good_week()
        self.client.force_login(self.admin)

        response = self.client.get(self.cohort_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cohort wellness")
        self.assertContains(response, "Average overall")
        self.assertContains(response, "100.0")

    def test_aggregate_page_never_names_a_child(self):
        self.add_good_week()
        self.client.force_login(self.admin)

        response = self.client.get(self.cohort_url())

        self.assertNotContains(response, self.child.full_name)
        self.assertNotContains(response, self.child.first_name)

    def test_mentor_is_refused_the_cohort_page(self):
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(self.cohort_url()).status_code, 403)

    def test_parent_is_refused_the_cohort_page(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(self.cohort_url()).status_code, 403)

    def test_child_is_refused_the_cohort_page(self):
        self.client.force_login(self.child_user)
        self.assertEqual(self.client.get(self.cohort_url()).status_code, 403)

    def test_refusal_of_the_cohort_page_is_audited(self):
        self.client.force_login(self.mentor)
        self.client.get(self.cohort_url())

        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.DENY, resource_type="score"
            ).exists()
        )


class DetailPageLinkTests(WellnessViewFixture):
    def detail_url(self):
        return reverse("children:detail", args=[self.child.pk])

    def test_mentor_is_offered_the_trend_link(self):
        self.client.force_login(self.mentor)
        response = self.client.get(self.detail_url())

        self.assertContains(response, "Wellness trend")
        self.assertContains(response, self.wellness_url())

    def test_parent_is_offered_the_trend_link(self):
        self.client.force_login(self.parent)
        self.assertContains(self.client.get(self.detail_url()), "Wellness trend")

    def test_child_is_not_offered_the_trend_link(self):
        self.client.force_login(self.child_user)
        self.assertNotContains(self.client.get(self.detail_url()), "Wellness trend")

    def test_admin_is_not_offered_the_trend_link(self):
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(self.detail_url()), "Wellness trend")

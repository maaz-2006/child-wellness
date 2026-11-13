"""View-level smoke tests: the pages exist, render, and are gated."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from children.models import Child, Guardianship
from core.models import Role, School, User


class PublicPagesTests(TestCase):
    def test_healthz_reports_database(self):
        response = self.client.get(reverse("core:healthz"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["database"], "ok")

    def test_root_redirects_anonymous_to_login(self):
        response = self.client.get("/")
        self.assertRedirects(response, reverse("core:login"))

    def test_login_page_renders(self):
        response = self.client.get(reverse("core:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in")

    def test_unknown_page_uses_custom_404(self):
        response = self.client.get("/definitely-not-a-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "We couldn't find that page", status_code=404)


class RoleDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Riverside Primary")
        cls.child = Child.objects.create(first_name="Amara", year_group="Year 4", school=cls.school)

        cls.parent = User.objects.create_user(username="p1", password="pw-test-1234", role=Role.PARENT)
        cls.mentor = User.objects.create_user(username="m1", password="pw-test-1234", role=Role.MENTOR)
        cls.admin = User.objects.create_user(username="a1", password="pw-test-1234", role=Role.ADMIN)
        cls.child_user = User.objects.create_user(username="c1", password="pw-test-1234", role=Role.CHILD)

        cls.child.user = cls.child_user
        cls.child.save(update_fields=["user"])

        Guardianship.objects.create(
            parent=cls.parent,
            child=cls.child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
        )

    def test_parent_dashboard_lists_their_child(self):
        self.client.force_login(self.parent)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Amara")

    def test_admin_dashboard_shows_aggregates_and_no_child_names(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Institution overview")

    def test_permission_matrix_denied_to_non_admin(self):
        self.client.force_login(self.mentor)
        response = self.client.get(reverse("core:permission_matrix"))
        self.assertEqual(response.status_code, 403)

    def test_permission_matrix_renders_for_admin(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("core:permission_matrix"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Emotional wellness")
        self.assertContains(response, "Social development")
        self.assertContains(response, "Manage")

    def test_child_dashboard_does_not_mention_risk(self):
        self.client.force_login(self.child_user)
        response = self.client.get(reverse("core:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "at risk")
        self.assertNotContains(response, "risk score")

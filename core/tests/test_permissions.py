"""Tests for the permission gate.

These are the tests that matter most: every privacy claim in the report should
have a corresponding assertion here. If one of these fails, the platform is
leaking a child's data.
"""

from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.utils import timezone

from children.models import Child, Guardianship, Mentorship
from core import permissions
from core.audit import record_request
from core.models import AuditLog, Role, School, User
from core.permissions import Access, Relation, Resource


class GateFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name="Riverside Primary")
        cls.child = Child.objects.create(first_name="Amara", year_group="Year 4", school=cls.school)
        cls.other_child = Child.objects.create(first_name="Tunde", year_group="Year 5", school=cls.school)

        cls.parent = User.objects.create_user(username="parent1", password="pw-test-1234", role=Role.PARENT)
        cls.other_parent = User.objects.create_user(username="parent2", password="pw-test-1234", role=Role.PARENT)
        cls.mentor = User.objects.create_user(username="mentor1", password="pw-test-1234", role=Role.MENTOR)
        cls.admin = User.objects.create_user(username="admin1", password="pw-test-1234", role=Role.ADMIN)
        cls.child_user = User.objects.create_user(username="child1", password="pw-test-1234", role=Role.CHILD)

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


class RelationshipTests(GateFixture):
    def test_parent_with_consent_is_own_relation(self):
        self.assertEqual(permissions.resolve_relation(self.parent, self.child), Relation.OWN)

    def test_parent_without_consent_has_no_relation(self):
        self.guardianship.consent_granted_at = None
        self.guardianship.save(update_fields=["consent_granted_at"])
        self.assertEqual(permissions.resolve_relation(self.parent, self.child), Relation.NONE)

    def test_revoked_consent_removes_access(self):
        # Granted in the past, revoked now. Access must follow the current
        # state; a revocation that leaves the gate open is not a revocation.
        self.guardianship.consent_revoked_at = timezone.now()
        self.guardianship.save(update_fields=["consent_revoked_at"])
        self.assertEqual(permissions.resolve_relation(self.parent, self.child), Relation.NONE)
        self.assertFalse(
            permissions.has_access(self.parent, self.child, Resource.PROFILE)
        )

    def test_inactive_guardianship_has_no_relation(self):
        self.guardianship.is_active = False
        self.guardianship.save(update_fields=["is_active"])
        self.assertEqual(permissions.resolve_relation(self.parent, self.child), Relation.NONE)

    def test_unrelated_parent_sees_nothing(self):
        self.assertEqual(permissions.resolve_relation(self.other_parent, self.child), Relation.NONE)
        self.assertFalse(permissions.has_access(self.other_parent, self.child, Resource.EMOTIONAL))

    def test_deactivated_mentorship_removes_access(self):
        self.mentorship.is_active = False
        self.mentorship.save(update_fields=["is_active"])
        self.assertFalse(permissions.has_access(self.mentor, self.child, Resource.ACADEMIC))

    def test_child_is_self_only(self):
        self.assertEqual(permissions.resolve_relation(self.child_user, self.child), Relation.SELF)
        self.assertEqual(permissions.resolve_relation(self.child_user, self.other_child), Relation.NONE)


class MatrixTests(GateFixture):
    def test_parent_can_read_own_childs_emotional_records(self):
        self.assertTrue(permissions.has_access(self.parent, self.child, Resource.EMOTIONAL, Access.READ))

    def test_parent_sees_alert_summary_but_not_case_notes(self):
        self.assertEqual(permissions.access_for(self.parent, self.child, Resource.ALERT), Access.SUMMARY)
        self.assertEqual(permissions.access_for(self.parent, self.child, Resource.CASE_NOTE), Access.NONE)

    def test_child_never_sees_own_score_or_alert(self):
        """The central ethical rule: no risk label in the child's own interface."""
        self.assertEqual(permissions.access_for(self.child_user, self.child, Resource.SCORE), Access.NONE)
        self.assertEqual(permissions.access_for(self.child_user, self.child, Resource.ALERT), Access.NONE)

    def test_child_can_write_own_checkins(self):
        self.assertEqual(permissions.access_for(self.child_user, self.child, Resource.EMOTIONAL), Access.WRITE)

    def test_mentor_gets_summary_not_raw_emotional_text(self):
        self.assertTrue(
            permissions.has_access(self.mentor, self.child, Resource.EMOTIONAL, Access.SUMMARY)
        )
        self.assertFalse(
            permissions.has_access(self.mentor, self.child, Resource.EMOTIONAL, Access.READ)
        )

    def test_mentor_can_write_observations(self):
        self.assertTrue(permissions.has_access(self.mentor, self.child, Resource.ACADEMIC, Access.WRITE))
        self.assertTrue(permissions.has_access(self.mentor, self.child, Resource.SOCIAL, Access.WRITE))

    def test_admin_cannot_read_emotional_content(self):
        self.assertEqual(permissions.access_for(self.admin, self.child, Resource.EMOTIONAL), Access.NONE)
        self.assertEqual(permissions.access_for(self.admin, self.child, Resource.CASE_NOTE), Access.NONE)

    def test_admin_has_aggregate_scores_and_config(self):
        self.assertEqual(permissions.access_for(self.admin, self.child, Resource.SCORE), Access.AGGREGATE)
        self.assertEqual(permissions.access_for(self.admin, self.child, Resource.CONFIG), Access.MANAGE)

    def test_anonymous_gets_nothing(self):
        from django.contrib.auth.models import AnonymousUser

        anon = AnonymousUser()
        for resource in (Resource.PROFILE, Resource.EMOTIONAL, Resource.SCORE):
            self.assertEqual(permissions.access_for(anon, self.child, resource), Access.NONE)

    def test_every_role_and_relation_has_a_row(self):
        covered = {(role, relation) for role, relation in permissions.MATRIX}
        self.assertIn((Role.PARENT, Relation.OWN), covered)
        self.assertIn((Role.MENTOR, Relation.ASSIGNED), covered)
        self.assertIn((Role.CHILD, Relation.SELF), covered)
        self.assertIn((Role.ADMIN, Relation.INSTITUTION), covered)

    def test_no_grants_exist_for_unlisted_relations(self):
        """A role/relation pair with no row must fall back to deny, not to a default grant."""
        self.assertEqual(
            permissions.MATRIX.get((Role.PARENT, Relation.SELF), {}).get(Resource.PROFILE),
            None,
        )


class InstitutionAccessTests(GateFixture):
    """Aggregate access is resolved without a child, from the INSTITUTION row."""

    def test_admin_has_aggregate_on_scores_but_not_read(self):
        self.assertEqual(
            permissions.access_for_institution(self.admin, Resource.SCORE),
            Access.AGGREGATE,
        )
        self.assertLess(
            permissions.access_for_institution(self.admin, Resource.SCORE),
            Access.READ,
        )

    def test_no_one_else_has_institution_access(self):
        for user in (self.parent, self.mentor, self.child_user):
            self.assertEqual(
                permissions.access_for_institution(user, Resource.SCORE),
                Access.NONE,
                user.username,
            )

    def test_anonymous_user_has_no_institution_access(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertEqual(
            permissions.access_for_institution(AnonymousUser(), Resource.SCORE),
            Access.NONE,
        )


class VisibleChildrenTests(GateFixture):
    def test_parent_sees_only_their_child(self):
        self.assertEqual(list(permissions.visible_children(self.parent)), [self.child])

    def test_unrelated_parent_sees_nothing(self):
        self.assertEqual(list(permissions.visible_children(self.other_parent)), [])

    def test_mentor_sees_assigned_child(self):
        self.assertEqual(list(permissions.visible_children(self.mentor)), [self.child])

    def test_child_sees_only_themselves(self):
        self.assertEqual(list(permissions.visible_children(self.child_user)), [self.child])

    def test_admin_sees_all(self):
        self.assertEqual(permissions.visible_children(self.admin).count(), 2)


class EnforcementTests(GateFixture):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def test_require_access_raises_and_audits_for_denied_sensitive_read(self):
        request = self._request(self.other_parent)
        with self.assertRaises(PermissionDenied):
            permissions.require_access(request, self.child, Resource.EMOTIONAL, Access.READ)

        entry = AuditLog.objects.filter(action=AuditLog.Action.DENY).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.child_id, self.child.pk)
        self.assertEqual(entry.resource_type, Resource.EMOTIONAL)
        self.assertEqual(entry.metadata["granted"], "NONE")

    def test_require_access_allows_permitted_read_without_deny_row(self):
        request = self._request(self.parent)
        permissions.require_access(request, self.child, Resource.EMOTIONAL, Access.READ)
        self.assertFalse(AuditLog.objects.filter(action=AuditLog.Action.DENY).exists())

    def test_require_role_rejects_wrong_role(self):
        request = self._request(self.parent)
        with self.assertRaises(PermissionDenied):
            permissions.require_role(request, Role.ADMIN)


class AuditTests(GateFixture):
    def test_record_request_captures_forwarded_ip(self):
        factory = RequestFactory()
        request = factory.get("/", HTTP_X_FORWARDED_FOR="41.90.1.2, 10.0.0.1")
        request.user = self.mentor

        entry = record_request(request, action=AuditLog.Action.VIEW, resource_type="emotional", child=self.child)

        self.assertIsNotNone(entry)
        self.assertEqual(entry.ip_address, "41.90.1.2")
        self.assertEqual(entry.actor_role, Role.MENTOR)
        self.assertEqual(entry.child_id, self.child.pk)

    def test_audit_entry_survives_actor_deletion(self):
        record_request(
            self._request_with_user(self.mentor),
            action=AuditLog.Action.VIEW,
            resource_type="profile",
            child=self.child,
        )
        self.mentor.delete()
        self.assertTrue(AuditLog.objects.filter(resource_type="profile").exists())

    def _request_with_user(self, user):
        request = RequestFactory().get("/")
        request.user = user
        return request

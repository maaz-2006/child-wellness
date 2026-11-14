"""Tests for adult-to-adult messaging.

The feature is small, but it is the one place where one adult's private
correspondence about a child is stored, so most of these tests are about who
cannot see it:

* the child cannot read or write a thread, even about themselves;
* the administrator cannot read it, in the application or in Django admin;
* an unrelated parent or an unassigned mentor cannot reach a thread by guessing
  its id, and the denial is audited;
* revoking consent or ending a mentorship removes access without deleting the
  record;
* messages are append-only and a closed thread accepts no new replies.

The remaining tests check that the ordinary workflow actually works, because a
privacy boundary that makes the feature unusable is not a solution either.
"""

from __future__ import annotations

from django.contrib import admin as django_admin
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from children.models import Child, Guardianship, Mentorship
from core.models import AuditLog, Role, User
from core.permissions import Access, Resource
from core import permissions

from . import services
from .models import Message, Thread, ThreadRead


class MessagingFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.mentor = User.objects.create_user(
            username="mentor", password="pw-test-1234", role=Role.MENTOR,
            first_name="Ruth",
        )
        cls.other_mentor = User.objects.create_user(
            username="othermentor", password="pw-test-1234", role=Role.MENTOR
        )
        cls.parent = User.objects.create_user(
            username="parent", password="pw-test-1234", role=Role.PARENT,
            first_name="Halima",
        )
        cls.other_parent = User.objects.create_user(
            username="otherparent", password="pw-test-1234", role=Role.PARENT
        )
        cls.admin = User.objects.create_user(
            username="admin", password="pw-test-1234", role=Role.ADMIN
        )

        cls.child = Child.objects.create(
            first_name="Amara", last_name="Otieno", year_group="Year 4"
        )
        cls.other_child = Child.objects.create(
            first_name="Tunde", last_name="Mwangi", year_group="Year 5"
        )
        cls.child_user = User.objects.create_user(
            username="child", password="pw-test-1234", role=Role.CHILD
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
        Guardianship.objects.create(
            parent=cls.other_parent,
            child=cls.other_child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
            is_primary=True,
        )
        cls.mentorship = Mentorship.objects.create(
            mentor=cls.mentor, child=cls.child
        )
        Mentorship.objects.create(mentor=cls.other_mentor, child=cls.other_child)

        cls.thread = Thread.objects.create(
            child=cls.child, subject="Settling in", created_by=cls.mentor
        )
        cls.first = Message.objects.create(
            thread=cls.thread, author=cls.mentor, body="A short opening message."
        )
        cls.thread.last_message_at = cls.first.created_at
        cls.thread.save(update_fields=["last_message_at"])

    def login(self, user):
        self.client.force_login(user)


class PermissionMatrixTests(MessagingFixture):
    def test_only_the_two_adult_roles_can_message(self):
        self.assertEqual(
            permissions.access_for(self.parent, self.child, Resource.MESSAGE),
            Access.WRITE,
        )
        self.assertEqual(
            permissions.access_for(self.mentor, self.child, Resource.MESSAGE),
            Access.WRITE,
        )
        self.assertEqual(
            permissions.access_for(self.child_user, self.child, Resource.MESSAGE),
            Access.NONE,
        )
        self.assertEqual(
            permissions.access_for(self.admin, self.child, Resource.MESSAGE),
            Access.NONE,
        )

    def test_message_is_in_the_audited_resources(self):
        self.assertIn(Resource.MESSAGE, permissions.AUDITED_RESOURCES)

    def test_unrelated_mentor_has_no_message_access(self):
        self.assertEqual(
            permissions.access_for(self.other_mentor, self.child, Resource.MESSAGE),
            Access.NONE,
        )

    def test_revoking_consent_removes_the_guardian_channel(self):
        self.guardianship.consent_revoked_at = timezone.now()
        self.guardianship.save(update_fields=["consent_revoked_at"])

        self.assertEqual(
            permissions.access_for(self.parent, self.child, Resource.MESSAGE),
            Access.NONE,
        )

    def test_ending_a_mentorship_removes_the_mentor_channel(self):
        self.mentorship.is_active = False
        self.mentorship.save(update_fields=["is_active"])

        self.assertEqual(
            permissions.access_for(self.mentor, self.child, Resource.MESSAGE),
            Access.NONE,
        )


class InboxTests(MessagingFixture):
    def test_anonymous_is_redirected_to_sign_in(self):
        response = self.client.get(reverse("messaging:inbox"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_child_and_admin_are_refused_the_inbox(self):
        for user in (self.child_user, self.admin):
            self.login(user)
            self.assertEqual(
                self.client.get(reverse("messaging:inbox")).status_code, 403, user.username
            )

    def test_mentor_sees_only_threads_about_assigned_children(self):
        other = Thread.objects.create(
            child=self.other_child, subject="Not mine", created_by=self.other_mentor
        )
        Message.objects.create(thread=other, author=self.other_mentor, body="Hidden.")

        self.login(self.mentor)
        response = self.client.get(reverse("messaging:inbox"))

        self.assertEqual(response.status_code, 200)
        subjects = [row["thread"].subject for row in response.context["rows"]]
        self.assertEqual(subjects, ["Settling in"])
        self.assertNotContains(response, "Not mine")

    def test_guardian_sees_only_their_own_child(self):
        other = Thread.objects.create(
            child=self.other_child, subject="Another family", created_by=self.other_mentor
        )
        Message.objects.create(thread=other, author=self.other_mentor, body="Hidden.")

        self.login(self.parent)
        response = self.client.get(reverse("messaging:inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Settling in")
        self.assertNotContains(response, "Another family")

    def test_inbox_view_is_audited(self):
        self.login(self.parent)
        self.client.get(reverse("messaging:inbox"))

        entry = AuditLog.objects.filter(
            action=AuditLog.Action.VIEW, resource_type=Resource.MESSAGE
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor, self.parent)
        self.assertEqual(entry.metadata.get("scope"), "inbox")

    def test_unread_count_excludes_the_adults_own_messages(self):
        services.mark_read(self.thread, self.parent)
        Message.objects.create(
            thread=self.thread, author=self.mentor, body="A new message."
        )

        self.assertEqual(services.unread_count(self.parent, self.thread), 1)
        self.assertEqual(services.unread_count(self.mentor, self.thread), 0)

    def test_opening_a_thread_clears_the_unread_count(self):
        Message.objects.create(
            thread=self.thread, author=self.mentor, body="Another message."
        )

        self.login(self.parent)
        self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(services.unread_count(self.parent, self.thread), 0)
        self.assertTrue(
            ThreadRead.objects.filter(thread=self.thread, user=self.parent).exists()
        )


class ThreadAccessTests(MessagingFixture):
    def test_guardian_can_read_a_thread_about_their_child(self):
        self.login(self.parent)
        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A short opening message.")

    def test_mentor_can_read_a_thread_about_an_assigned_child(self):
        self.login(self.mentor)
        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 200)

    def test_child_cannot_read_a_thread_about_themselves(self):
        self.login(self.child_user)
        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_read_a_thread(self):
        self.login(self.admin)
        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 403)

    def test_unrelated_parent_denial_is_audited(self):
        self.login(self.other_parent)
        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 403)
        entry = AuditLog.objects.filter(action=AuditLog.Action.DENY).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor, self.other_parent)
        self.assertEqual(entry.resource_type, Resource.MESSAGE)
        self.assertEqual(entry.metadata.get("required"), "READ")

    def test_mentor_loses_access_when_assignment_ends(self):
        self.mentorship.is_active = False
        self.mentorship.save(update_fields=["is_active"])

        self.login(self.mentor)
        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 403)

    def test_missing_thread_is_a_404_not_a_500(self):
        self.login(self.mentor)
        response = self.client.get(reverse("messaging:thread", args=[999999]))
        self.assertEqual(response.status_code, 404)


class AppendOnlyTests(MessagingFixture):
    def test_reply_appends_a_message_and_updates_activity(self):
        before = self.thread.last_message_at
        self.login(self.parent)

        response = self.client.post(
            reverse("messaging:thread", args=[self.thread.pk]),
            {"action": "reply", "body": "Thank you for the update."},
        )

        self.assertEqual(response.status_code, 302)
        self.thread.refresh_from_db()
        self.assertEqual(self.thread.messages.count(), 2)
        self.assertEqual(
            self.thread.messages.last().body, "Thank you for the update."
        )
        self.assertGreaterEqual(self.thread.last_message_at, before)

    def test_reply_is_audited(self):
        self.login(self.parent)
        self.client.post(
            reverse("messaging:thread", args=[self.thread.pk]),
            {"action": "reply", "body": "One more thing."},
        )

        entry = AuditLog.objects.filter(
            action=AuditLog.Action.CREATE, resource_type=Resource.MESSAGE
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.child_id, self.child.pk)

    def test_empty_reply_is_rejected(self):
        self.login(self.parent)
        response = self.client.post(
            reverse("messaging:thread", args=[self.thread.pk]),
            {"action": "reply", "body": "   "},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_message_rows_cannot_be_edited(self):
        self.first.body = "Rewritten history."
        with self.assertRaises(ValueError):
            self.first.save()

    def test_message_rows_cannot_be_deleted(self):
        with self.assertRaises(ValueError):
            self.first.delete()

    def test_service_refuses_a_body_over_the_limit(self):
        with self.assertRaises(services.MessageError):
            services.post_message(self.thread, self.mentor, "x" * 4001)

    def test_services_refuse_a_write_without_access(self):
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            services.post_message(self.thread, self.admin, "Should not be stored.")
        with self.assertRaises(PermissionDenied):
            services.start_thread(
                self.child, self.other_mentor, "Subject", "Body"
            )


class ClosedThreadTests(MessagingFixture):
    def test_mentor_can_close_a_thread(self):
        self.login(self.mentor)
        response = self.client.post(
            reverse("messaging:thread", args=[self.thread.pk]),
            {"action": "close"},
        )

        self.assertEqual(response.status_code, 302)
        self.thread.refresh_from_db()
        self.assertTrue(self.thread.is_closed)

    def test_closed_thread_stays_readable(self):
        services.close_thread(self.thread, self.mentor)
        self.login(self.parent)

        response = self.client.get(reverse("messaging:thread", args=[self.thread.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A short opening message.")

    def test_closed_thread_rejects_a_reply(self):
        services.close_thread(self.thread, self.mentor)
        self.login(self.parent)

        response = self.client.post(
            reverse("messaging:thread", args=[self.thread.pk]),
            {"action": "reply", "body": "Too late."},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.thread.messages.count(), 1)

    def test_only_a_mentor_can_close(self):
        self.login(self.parent)

        response = self.client.post(
            reverse("messaging:thread", args=[self.thread.pk]),
            {"action": "close"},
        )

        self.assertEqual(response.status_code, 403)
        self.thread.refresh_from_db()
        self.assertFalse(self.thread.is_closed)

    def test_service_refuses_a_reply_to_a_closed_thread(self):
        services.close_thread(self.thread, self.mentor)

        with self.assertRaises(services.MessageError):
            services.post_message(self.thread, self.mentor, "Still writing.")


class StartThreadTests(MessagingFixture):
    def test_permitted_adult_can_start_a_conversation(self):
        self.login(self.parent)
        response = self.client.post(
            reverse("messaging:new_thread", args=[self.child.pk]),
            {"subject": "Reading at home", "body": "A question about reading."},
        )

        self.assertEqual(response.status_code, 302)
        thread = Thread.objects.get(subject="Reading at home")
        self.assertEqual(thread.child, self.child)
        self.assertEqual(thread.created_by, self.parent)
        self.assertEqual(thread.messages.count(), 1)
        self.assertTrue(
            ThreadRead.objects.filter(thread=thread, user=self.parent).exists()
        )

    def test_starting_a_thread_is_audited(self):
        self.login(self.mentor)
        self.client.post(
            reverse("messaging:new_thread", args=[self.child.pk]),
            {"subject": "Reading at home", "body": "A note."},
        )

        entry = AuditLog.objects.filter(
            action=AuditLog.Action.CREATE, resource_type=Resource.MESSAGE
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.child_id, self.child.pk)

    def test_subject_is_required(self):
        self.login(self.parent)
        response = self.client.post(
            reverse("messaging:new_thread", args=[self.child.pk]),
            {"subject": "  ", "body": "Body without a subject."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Thread.objects.count(), 1)

    def test_child_and_admin_cannot_start_a_thread(self):
        for user in (self.child_user, self.admin):
            self.login(user)
            self.assertEqual(
                self.client.get(
                    reverse("messaging:new_thread", args=[self.child.pk])
                ).status_code,
                403,
                user.username,
            )

    def test_unassigned_mentor_cannot_start_a_thread(self):
        self.login(self.other_mentor)
        self.assertEqual(
            self.client.get(
                reverse("messaging:new_thread", args=[self.child.pk])
            ).status_code,
            403,
        )

    def test_guardian_without_consent_cannot_start_a_thread(self):
        self.guardianship.consent_revoked_at = timezone.now()
        self.guardianship.save(update_fields=["consent_revoked_at"])
        self.login(self.parent)

        self.assertEqual(
            self.client.get(
                reverse("messaging:new_thread", args=[self.child.pk])
            ).status_code,
            403,
        )


class AdminRegistrationTests(TestCase):
    def test_messaging_models_are_not_registered_in_django_admin(self):
        registered = set(django_admin.site._registry)

        for model in (Thread, Message, ThreadRead):
            self.assertNotIn(model, registered)

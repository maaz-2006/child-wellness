"""Tests for the D5 alert engine, safeguarding screen and alert screens.

The assertions that matter here are behavioural, not cosmetic:

* one low week is not urgent,
* an alert is owned by a person,
* re-running the engine updates rather than duplicates,
* safeguarding text is never copied into the alert or the audit log,
* an urgent alert cannot be shared with a guardian,
* an administrator can see counts but never a child's name,
* a guardian sees only deliberately shared, non-urgent alerts.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analytics import scoring
from analytics.models import DomainScore
from children.models import Child, Guardianship, Mentorship
from core.models import AuditLog, Role, School, User
from domains.models import EmotionalCheckin, Source

from . import engine, rules, safeguarding, services
from .models import Alert, AlertEvent
from .rules import Finding


class AlertFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.child = Child.objects.create(
            first_name="Amara", last_name="Otieno", year_group="Year 4"
        )
        cls.other_child = Child.objects.create(
            first_name="Tunde", last_name="Mwangi", year_group="Year 5"
        )
        cls.mentor = User.objects.create_user(
            username="mentor", password="pw-test-1234", role=Role.MENTOR
        )
        cls.lead = User.objects.create_user(
            username="lead", password="pw-test-1234", role=Role.MENTOR
        )
        cls.parent = User.objects.create_user(
            username="parent", password="pw-test-1234", role=Role.PARENT
        )
        cls.child_user = User.objects.create_user(
            username="child", password="pw-test-1234", role=Role.CHILD
        )
        cls.admin = User.objects.create_user(
            username="admin", password="pw-test-1234", role=Role.ADMIN
        )
        cls.school = School.objects.create(
            name="Riverside", safeguarding_lead=cls.lead
        )
        cls.child.school = cls.school
        cls.child.user = cls.child_user
        cls.child.save(update_fields=["school", "user"])

        Guardianship.objects.create(
            parent=cls.parent,
            child=cls.child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
            is_primary=True,
        )
        Mentorship.objects.create(mentor=cls.mentor, child=cls.child)

    def set_overall_scores(self, values, child=None):
        """Create stored overall scores for the last N windows."""
        child = child or self.child
        as_of = self.today
        windows = scoring.periods(as_of, scoring.TREND_PERIODS)
        chosen = windows[-len(values):]
        for window, value in zip(chosen, values):
            DomainScore.objects.update_or_create(
                child=child,
                domain=scoring.OVERALL,
                period_end=window.end,
                defaults={
                    "period_start": window.start,
                    "score": value,
                    "data_points": 6,
                    "confidence": "good",
                    "method_version": scoring.METHOD_VERSION,
                },
            )
        return as_of

    def make_alert(self, **overrides):
        defaults = {
            "child": self.child,
            "rule_key": "declining_trend",
            "tier": Alert.Tier.WATCH,
            "title": "Overall wellness has declined over four weeks",
            "summary": "Generated summary.",
            "evidence": {"change": -12},
            "period_end": self.today,
            "opened_on": self.today,
            "last_seen_on": self.today,
            "assigned_to": self.mentor,
        }
        defaults.update(overrides)
        alert = Alert.objects.create(**defaults)
        AlertEvent.objects.create(
            alert=alert,
            actor=None,
            kind=AlertEvent.Kind.OPENED,
            body="Alert opened by the screening engine.",
        )
        return alert


class RuleTests(AlertFixture):
    def test_one_very_low_week_is_not_urgent(self):
        self.set_overall_scores([30])

        findings = rules.evaluate(self.child, self.today)

        self.assertNotIn("overall_very_low", [finding.rule_key for finding in findings])

    def test_two_confident_very_low_weeks_are_urgent(self):
        self.set_overall_scores([30, 28])

        findings = rules.evaluate(self.child, self.today)

        urgent = [finding for finding in findings if finding.tier == "urgent"]
        self.assertEqual(len(urgent), 1)
        self.assertEqual(urgent[0].rule_key, "overall_very_low")

    def test_three_low_weeks_are_a_concern(self):
        self.set_overall_scores([44, 42, 40])

        findings = rules.evaluate(self.child, self.today)

        self.assertIn("sustained_low", [finding.rule_key for finding in findings])

    def test_child_without_consent_is_not_evaluated(self):
        self.set_overall_scores([30, 28])
        Guardianship.objects.filter(child=self.child).update(consent_granted_at=None)

        self.assertEqual(rules.evaluate(self.child, self.today), [])

    def test_a_gap_is_not_read_as_zero(self):
        # Only the oldest window has data; the latest windows are missing. The
        # sustained-low rule must not treat absent rows as zeros.
        self.set_overall_scores([100, 100, 100, 100, 100, 100])
        DomainScore.objects.filter(
            child=self.child, period_end__gte=self.today - timedelta(days=14)
        ).delete()

        findings = rules.evaluate(self.child, self.today)

        self.assertNotIn("sustained_low", [finding.rule_key for finding in findings])


class EngineTests(AlertFixture):
    def test_engine_creates_one_alert_owned_by_the_class_teacher(self):
        finding = Finding(
            rule_key="declining_trend",
            tier="watch",
            domain="overall",
            title="Decline",
            summary="Summary.",
            evidence={"change": -10},
        )

        alert = engine.persist_finding(self.child, finding, self.today)

        self.assertEqual(alert.assigned_to, self.mentor)
        self.assertEqual(alert.status, Alert.Status.OPEN)
        self.assertEqual(alert.events.count(), 1)
        self.assertEqual(alert.events.first().kind, AlertEvent.Kind.OPENED)

    def test_rerunning_on_the_same_day_does_not_duplicate_or_inflate(self):
        finding = Finding(
            rule_key="declining_trend",
            tier="watch",
            domain="overall",
            title="Decline",
            summary="Summary.",
            evidence={"change": -10},
        )

        first = engine.persist_finding(self.child, finding, self.today)
        second = engine.persist_finding(self.child, finding, self.today)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(second.occurrences, 1)

    def test_rerunning_on_a_later_day_increments_occurrences(self):
        finding = Finding(
            rule_key="declining_trend",
            tier="watch",
            domain="overall",
            title="Decline",
            summary="Summary.",
            evidence={},
        )
        engine.persist_finding(self.child, finding, self.today)
        alert = engine.persist_finding(
            self.child, finding, self.today + timedelta(days=1)
        )

        self.assertEqual(Alert.objects.count(), 1)
        self.assertEqual(alert.occurrences, 2)

    def test_an_open_alert_escalates_and_does_not_downgrade(self):
        watch = Finding(
            rule_key="declining_trend",
            tier="watch",
            domain="overall",
            title="Decline",
            summary="Summary.",
            evidence={},
        )
        concern = Finding(
            rule_key="declining_trend",
            tier="urgent",
            domain="overall",
            title="Urgent",
            summary="Urgent summary.",
            evidence={},
        )
        engine.persist_finding(self.child, watch, self.today)
        escalated = engine.persist_finding(
            self.child, concern, self.today + timedelta(days=1)
        )
        downgraded = engine.persist_finding(
            self.child, watch, self.today + timedelta(days=2)
        )

        self.assertEqual(escalated.tier, Alert.Tier.URGENT)
        self.assertEqual(downgraded.tier, Alert.Tier.URGENT)

    def test_urgent_alert_goes_to_the_safeguarding_lead(self):
        alert = self.make_alert(tier=Alert.Tier.URGENT)
        alert.assigned_to = None
        alert.save()

        refreshed = engine.persist_finding(
            self.child,
            Finding(
                rule_key="overall_very_low",
                tier="urgent",
                domain="overall",
                title="Very low",
                summary="Summary.",
                evidence={},
            ),
            self.today,
        )

        self.assertEqual(refreshed.assigned_to, self.lead)


class SafeguardingTests(AlertFixture):
    def test_benign_text_does_not_match(self):
        self.assertEqual(safeguarding.categories_for("Had a good day at school."), [])

    def test_self_harm_language_creates_an_urgent_alert(self):
        alerts = safeguarding.screen_and_alert(
            self.child,
            "I want to die",
            actor=self.mentor,
            source_resource="emotional",
            entry_id=99,
        )

        self.assertEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.tier, Alert.Tier.URGENT)
        self.assertEqual(alert.assigned_to, self.lead)
        self.assertFalse(alert.evidence["text_stored"])
        self.assertNotIn("I want to die", alert.summary)
        self.assertNotIn("I want to die", str(alert.evidence))

    def test_screening_does_not_store_the_text_on_the_alert(self):
        safeguarding.screen_and_alert(self.child, "someone is hurting me")

        alert = Alert.objects.get()
        self.assertNotIn("hurting", alert.summary.lower())
        self.assertNotIn("someone is hurting me", str(alert.evidence).lower())

    def test_child_checkin_with_disclosure_routes_an_urgent_alert(self):
        self.client.force_login(self.child_user)
        response = self.client.post(
            reverse("domains:checkin"),
            {
                "mood": 2,
                "energy": 2,
                "sleep_quality": 2,
                "felt_connected": 2,
                "note": "I want to die",
                "note_visibility": "private",
            },
        )

        self.assertEqual(response.status_code, 302)
        alert = Alert.objects.get(child=self.child)
        self.assertEqual(alert.tier, Alert.Tier.URGENT)
        self.assertEqual(alert.assigned_to, self.lead)
        self.assertFalse(alert.evidence["text_stored"])
        self.assertNotIn("I want to die", alert.summary)

        audit = AuditLog.objects.get(action="safeguarding")
        self.assertIn("self_harm", audit.metadata["categories"])
        self.assertNotIn("I want to die", str(audit.metadata))


class ServiceTests(AlertFixture):
    def test_acknowledge_then_resolve_records_a_timeline(self):
        alert = self.make_alert()

        services.acknowledge(alert, self.mentor)
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.Status.ACKNOWLEDGED)

        services.resolve(alert, self.mentor, "Spoke to the child and guardian.")
        alert.refresh_from_db()
        self.assertEqual(alert.status, Alert.Status.RESOLVED)
        self.assertEqual(alert.resolution_note, "Spoke to the child and guardian.")
        self.assertEqual(
            list(alert.events.values_list("kind", flat=True)),
            ["opened", "acknowledged", "resolved"],
        )

    def test_resolution_requires_a_note(self):
        alert = self.make_alert()
        with self.assertRaises(services.AlertStateError):
            services.resolve(alert, self.mentor, "")

    def test_closed_alert_cannot_be_acknowledged_again(self):
        alert = self.make_alert(status=Alert.Status.RESOLVED)
        with self.assertRaises(services.AlertStateError):
            services.acknowledge(alert, self.mentor)

    def test_urgent_alert_is_never_shareable(self):
        alert = self.make_alert(tier=Alert.Tier.URGENT)

        with self.assertRaises(services.AlertStateError):
            services.share_with_guardian(alert, self.mentor)

        alert.refresh_from_db()
        self.assertIsNone(alert.guardian_shared_at)

    def test_non_urgent_alert_can_be_shared_when_consent_exists(self):
        alert = self.make_alert(tier=Alert.Tier.CONCERN)

        services.share_with_guardian(alert, self.mentor)

        alert.refresh_from_db()
        self.assertIsNotNone(alert.guardian_shared_at)
        self.assertEqual(alert.guardian_shared_by, self.mentor)

    def test_share_refused_when_no_guardian_consent(self):
        alert = self.make_alert(tier=Alert.Tier.CONCERN)
        Guardianship.objects.filter(child=self.child).update(consent_granted_at=None)

        with self.assertRaises(services.AlertStateError):
            services.share_with_guardian(alert, self.mentor)

    def test_alert_events_are_append_only(self):
        alert = self.make_alert()
        event = alert.events.first()

        event.body = "rewritten"
        with self.assertRaises(ValueError):
            event.save()
        with self.assertRaises(ValueError):
            event.delete()


class AlertViewTests(AlertFixture):
    def test_mentor_sees_the_queue_for_an_assigned_child(self):
        self.make_alert()
        self.client.force_login(self.mentor)

        response = self.client.get(reverse("alerts:queue"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alert queue")
        self.assertContains(response, self.child.full_name)

    def test_parent_and_admin_cannot_open_the_mentor_queue(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(reverse("alerts:queue")).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("alerts:queue")).status_code, 403)

    def test_mentor_can_open_an_alert_case(self):
        alert = self.make_alert()
        self.client.force_login(self.mentor)

        response = self.client.get(reverse("alerts:detail", args=[alert.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, alert.title)
        self.assertContains(response, "Case timeline")

    def test_parent_and_admin_cannot_open_a_case_file(self):
        alert = self.make_alert()
        for user in (self.parent, self.admin):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("alerts:detail", args=[alert.pk])).status_code,
                403,
            )

    def test_guardian_sees_shared_non_urgent_alert_but_not_urgent(self):
        shared = self.make_alert(
            title="Shared concern", tier=Alert.Tier.CONCERN,
            guardian_shared_at=timezone.now(),
        )
        urgent = self.make_alert(
            title="Urgent secret", tier=Alert.Tier.URGENT,
            rule_key="overall_very_low", guardian_shared_at=timezone.now(),
        )
        self.client.force_login(self.parent)

        response = self.client.get(reverse("alerts:family"))

        self.assertContains(response, "Shared concern")
        self.assertNotContains(response, urgent.title)

    def test_guardian_never_sees_case_notes_on_the_family_page(self):
        alert = self.make_alert(
            title="Shared concern",
            tier=Alert.Tier.CONCERN,
            guardian_shared_at=timezone.now(),
        )
        services.add_note(alert, self.mentor, "Internal case note text.")
        self.client.force_login(self.parent)

        response = self.client.get(reverse("alerts:family"))

        self.assertNotContains(response, "Internal case note text.")

    def test_cohort_page_is_aggregate_only(self):
        self.make_alert(tier=Alert.Tier.URGENT)
        self.client.force_login(self.admin)

        response = self.client.get(reverse("alerts:cohort"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Early-warning alerts")
        self.assertNotContains(response, self.child.full_name)
        self.assertNotContains(response, self.child.first_name)

    def test_mentor_cannot_open_the_cohort_alert_page(self):
        self.client.force_login(self.mentor)
        self.assertEqual(self.client.get(reverse("alerts:cohort")).status_code, 403)

    def test_sharing_through_the_view_is_audited(self):
        alert = self.make_alert(tier=Alert.Tier.CONCERN)
        self.client.force_login(self.mentor)

        response = self.client.post(
            reverse("alerts:detail", args=[alert.pk]), {"action": "share"}
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.ALERT_SHARE).exists()
        )
        alert.refresh_from_db()
        self.assertIsNotNone(alert.guardian_shared_at)

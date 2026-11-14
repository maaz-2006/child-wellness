"""Tests for the offline classifier benchmark.

The benchmark is not part of the care path, so these tests are not about
accuracy claims. They check the properties that make the number honest and the
artefact safe:

* labels come from the synthetic archetype, not from the outcome we are hoping
  to see;
* a snapshot with no overall score is dropped rather than counted as stable, and
  sparse children are excluded entirely;
* validation is by child, not by row, so the same child cannot appear in both
  training and test;
* an insufficient cohort produces an explicit "insufficient data" report rather
  than a number on four examples;
* the stored report contains counts and coefficients only - no child ids, names
  or per-child predictions;
* only the administrator can read the methodology page.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from analytics import ml, scoring
from analytics.models import DomainScore, ModelReport, ScenarioLabel
from children.models import Child, Guardianship, Mentorship
from core.models import AuditLog, Role, School, User


class MLFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.school = School.objects.create(name="Riverside")
        cls.windows = scoring.periods(cls.today, scoring.TREND_PERIODS)

    # -- builders ---------------------------------------------------------
    def make_child(self, first_name, *, archetype, scores, onset_index=None):
        child = Child.objects.create(
            first_name=first_name, last_name="Demo", school=self.school
        )
        guardian = User.objects.create_user(
            username=f"p-{first_name.lower()}",
            password="pw-test-1234",
            role=Role.PARENT,
        )
        Guardianship.objects.create(
            parent=guardian,
            child=child,
            consent_granted_at=timezone.now(),
            consent_version="1.0",
            is_primary=True,
        )
        onset = (
            self.windows[onset_index].end
            if onset_index is not None
            else None
        )
        ScenarioLabel.objects.create(
            child=child, archetype=archetype, onset_date=onset
        )
        for window, value in zip(self.windows, scores):
            for domain in scoring.DOMAINS + (scoring.OVERALL,):
                DomainScore.objects.create(
                    child=child,
                    domain=domain,
                    period_start=window.start,
                    period_end=window.end,
                    score=value,
                    data_points=6,
                    confidence="good",
                    method_version=scoring.METHOD_VERSION,
                )
        return child

    def make_cohort(self):
        """Enough children of both classes for a real leave-one-child-out run."""
        count = len(self.windows)
        for index in range(5):
            self.make_child(
                f"Stable{index}",
                archetype=ScenarioLabel.Archetype.HEALTHY,
                scores=[78.0 + index] * count,
            )
        for index in range(5):
            decline = [80.0 - 4.0 * step for step in range(count)]
            self.make_child(
                f"Decline{index}",
                archetype=ScenarioLabel.Archetype.GRADUAL_DECLINE,
                scores=decline,
                onset_index=count // 2,
            )


class LabelTests(MLFixture):
    def test_healthy_snapshot_is_always_negative(self):
        label = ScenarioLabel(archetype=ScenarioLabel.Archetype.HEALTHY)
        self.assertEqual(ml.label_for(label, self.today), 0)

    def test_declining_snapshot_is_positive_only_from_onset(self):
        onset = self.windows[4].end
        label = ScenarioLabel(
            archetype=ScenarioLabel.Archetype.GRADUAL_DECLINE, onset_date=onset
        )
        self.assertEqual(ml.label_for(label, onset - timedelta(days=1)), 0)
        self.assertEqual(ml.label_for(label, onset), 1)
        self.assertEqual(ml.label_for(label, onset + timedelta(days=14)), 1)

    def test_recovering_snapshot_is_positive_before_recovery(self):
        recovery = self.windows[4].end
        label = ScenarioLabel(
            archetype=ScenarioLabel.Archetype.RECOVERING, onset_date=recovery
        )
        self.assertEqual(ml.label_for(label, recovery - timedelta(days=1)), 1)
        self.assertEqual(ml.label_for(label, recovery), 0)

    def test_sparse_archetype_has_no_label(self):
        label = ScenarioLabel(archetype=ScenarioLabel.Archetype.SPARSE)
        self.assertIsNone(ml.label_for(label, self.today))


class FeatureTests(MLFixture):
    def test_feature_names_and_vector_agree(self):
        child = self.make_child(
            "Feature",
            archetype=ScenarioLabel.Archetype.HEALTHY,
            scores=[70.0] * len(self.windows),
        )
        rows = list(DomainScore.objects.filter(child=child))

        vector = ml.features_for(rows, [], self.windows[-1].end)

        self.assertIsNotNone(vector)
        self.assertEqual(len(vector), len(ml.FEATURE_NAMES))

    def test_no_overall_score_means_no_example(self):
        child = self.make_child(
            "Gap",
            archetype=ScenarioLabel.Archetype.HEALTHY,
            scores=[70.0] * len(self.windows),
        )
        DomainScore.objects.filter(child=child, domain=scoring.OVERALL).delete()
        rows = list(DomainScore.objects.filter(child=child))

        self.assertIsNone(ml.features_for(rows, [], self.windows[-1].end))

    def test_missing_pulse_is_flagged_rather_than_guessed(self):
        child = self.make_child(
            "NoPulse",
            archetype=ScenarioLabel.Archetype.HEALTHY,
            scores=[70.0] * len(self.windows),
        )
        rows = list(DomainScore.objects.filter(child=child))

        vector = ml.features_for(rows, [], self.windows[-1].end)
        index = ml.FEATURE_NAMES.index("pulse_missing")

        self.assertEqual(vector[index], 1.0)

    def test_recent_pulse_is_read_as_a_rating(self):
        child = self.make_child(
            "Pulse",
            archetype=ScenarioLabel.Archetype.HEALTHY,
            scores=[70.0] * len(self.windows),
        )
        rows = list(DomainScore.objects.filter(child=child))
        pulses = [(self.windows[-1].end, 4, 5)]

        vector = ml.features_for(rows, pulses, self.windows[-1].end)

        self.assertEqual(vector[ml.FEATURE_NAMES.index("pulse_missing")], 0.0)
        self.assertEqual(vector[ml.FEATURE_NAMES.index("pulse_wellbeing")], 0.75)
        self.assertEqual(vector[ml.FEATURE_NAMES.index("pulse_support")], 1.0)


class DatasetTests(MLFixture):
    def test_sparse_children_are_excluded(self):
        self.make_child(
            "Sparse",
            archetype=ScenarioLabel.Archetype.SPARSE,
            scores=[60.0] * len(self.windows),
        )
        dataset = ml.build_dataset(self.today)

        self.assertEqual(dataset.examples, [])
        self.assertEqual(dataset.skipped_sparse, 1)

    def test_child_without_consent_is_excluded(self):
        child = self.make_child(
            "NoConsent",
            archetype=ScenarioLabel.Archetype.HEALTHY,
            scores=[70.0] * len(self.windows),
        )
        child.guardianships.update(consent_revoked_at=timezone.now())

        dataset = ml.build_dataset(self.today)

        self.assertEqual(dataset.examples, [])
        self.assertEqual(dataset.skipped_no_consent, 1)

    def test_dataset_counts_match_the_examples(self):
        self.make_cohort()
        dataset = ml.build_dataset(self.today)

        self.assertEqual(len(dataset.examples), 10 * len(self.windows))
        self.assertEqual(dataset.positive + dataset.negative, len(dataset.examples))
        self.assertEqual(dataset.children, 10)
        self.assertGreater(dataset.positive, 0)
        self.assertGreater(dataset.negative, 0)


class TrainingTests(TestCase):
    def test_irls_learns_the_direction_of_a_separable_toy_problem(self):
        rows = [[-2.0], [-1.0], [1.0], [2.0]]
        labels = [0, 0, 1, 1]

        weights, bias = ml.train(rows, labels)

        self.assertGreater(weights[0], 0)
        low = ml._sigmoid(weights[0] * -1.0 + bias)
        high = ml._sigmoid(weights[0] * 1.0 + bias)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)

    def test_auc_is_one_for_a_perfect_ranking(self):
        self.assertEqual(ml._auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]), 1.0)

    def test_auc_is_none_with_one_class(self):
        self.assertIsNone(ml._auc([0, 0], [0.1, 0.2]))


class EvaluationTests(MLFixture):
    def test_loocv_holds_out_every_child(self):
        self.make_cohort()
        dataset = ml.build_dataset(self.today)

        result = ml.evaluate_loocv(dataset.examples)

        self.assertEqual(result["folds"], 10)
        self.assertEqual(result["predictions"], len(dataset.examples))
        self.assertEqual(
            sum(result["confusion"].values()), len(dataset.examples)
        )
        for value in result["metrics"].values():
            if value is not None:
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_evaluate_and_store_reports_insufficient_data(self):
        report = ml.evaluate_and_store(self.today)

        self.assertEqual(report.status, ModelReport.Status.INSUFFICIENT_DATA)
        self.assertFalse(report.has_metrics)
        self.assertEqual(report.coefficients, [])

    def test_evaluate_and_store_produces_an_aggregate_report(self):
        self.make_cohort()

        report = ml.evaluate_and_store(self.today)

        self.assertEqual(report.status, ModelReport.Status.OK)
        self.assertTrue(report.has_metrics)
        self.assertEqual(report.n_children, 10)
        self.assertEqual(report.feature_names, list(ml.FEATURE_NAMES))
        self.assertEqual(len(report.coefficients), len(ml.FEATURE_NAMES))
        self.assertEqual(
            report.n_positive + report.n_negative, report.n_examples
        )

    def test_report_holds_no_child_identifiers(self):
        self.make_cohort()

        report = ml.evaluate_and_store(self.today)
        blob = " ".join(
            [
                report.notes,
                report.task,
                str(report.metrics),
                str(report.confusion),
                str(report.coefficients),
            ]
        )

        for name in ("Stable0", "Decline0", "Demo"):
            self.assertNotIn(name, blob)

    def test_ml_report_command_stores_a_report(self):
        self.make_cohort()

        call_command("ml_report")

        self.assertEqual(ModelReport.objects.count(), 1)


class ModelReportViewTests(MLFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = User.objects.create_user(
            username="admin", password="pw-test-1234", role=Role.ADMIN
        )
        cls.mentor = User.objects.create_user(
            username="mentor", password="pw-test-1234", role=Role.MENTOR
        )
        cls.parent = User.objects.create_user(
            username="parent", password="pw-test-1234", role=Role.PARENT
        )
        cls.child_user = User.objects.create_user(
            username="child", password="pw-test-1234", role=Role.CHILD
        )

    def setUp(self):
        self.report = ModelReport.objects.create(
            as_of=self.today,
            status=ModelReport.Status.OK,
            n_children=10,
            n_examples=80,
            n_positive=20,
            n_negative=60,
            folds=10,
            metrics={"accuracy": 0.9, "auc": 0.88, "brier": 0.07},
            confusion={"tp": 15, "fp": 2, "tn": 58, "fn": 5},
            feature_names=list(ml.FEATURE_NAMES),
            coefficients=[
                {"name": "overall_latest", "label": "Latest overall score", "weight": -1.2}
            ],
            notes="Aggregate only.",
        )

    def url(self):
        return reverse("analytics:model_report")

    def test_anonymous_is_redirected(self):
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_non_admin_roles_are_refused(self):
        for user in (self.mentor, self.parent, self.child_user):
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(self.url()).status_code, 403, user.username
            )

    def test_admin_can_read_the_aggregate_report(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Offline model benchmark")
        self.assertContains(response, "Leave-one-child-out")
        self.assertContains(response, "not connected to any child")

    def test_page_contains_no_child_names(self):
        self.make_cohort()
        self.client.force_login(self.admin)
        response = self.client.get(self.url())

        for name in ("Stable0", "Decline0", "Demo"):
            self.assertNotContains(response, name)

    def test_viewing_the_report_is_audited(self):
        self.client.force_login(self.admin)
        self.client.get(self.url())

        entry = AuditLog.objects.filter(
            action=AuditLog.Action.VIEW, resource_type="score"
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.metadata.get("scope"), "model_report")

    def test_no_report_yet_still_renders(self):
        ModelReport.objects.all().delete()
        self.client.force_login(self.admin)

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No benchmark has been run")

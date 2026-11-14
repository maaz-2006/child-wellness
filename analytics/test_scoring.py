"""Tests for the wellness score.

The arithmetic is the product claim: if the score is wrong, the trend chart is a
confident lie. These tests pin down the interpretation as much as the numbers -
especially the two places where a naive implementation would be harmful:

* a missing domain must not be averaged in as zero, and
* a child with one domain must not receive an "overall" score.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from children.models import Child
from domains.models import (
    AcademicRecord,
    EmotionalCheckin,
    HabitLog,
    SocialObservation,
    Source,
)

from . import scoring
from .models import BaselineStat, DomainScore


class ScoringFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        today = timezone.localdate()
        cls.today = today
        # Age 8 keeps the child in the "primary" sleep-guideline band.
        cls.child = Child.objects.create(
            first_name="Amara",
            year_group="Year 4",
            date_of_birth=today - timedelta(days=8 * 365 + 40),
        )
        cls.other_child = Child.objects.create(
            first_name="Tunde",
            year_group="Year 5",
            date_of_birth=today - timedelta(days=10 * 365 + 40),
        )

    # -- builders --------------------------------------------------------
    def add_checkin(self, child=None, days_ago=0, rating=5, **overrides):
        values = {
            "mood": rating,
            "energy": rating,
            "sleep_quality": rating,
            "felt_connected": rating,
        }
        values.update(overrides)
        return EmotionalCheckin.objects.create(
            child=child or self.child,
            source=Source.CHILD,
            occurred_on=self.today - timedelta(days=days_ago),
            **values,
        )

    def add_academic(self, child=None, days_ago=0, percent=100):
        return AcademicRecord.objects.create(
            child=child or self.child,
            source=Source.MENTOR,
            occurred_on=self.today - timedelta(days=days_ago),
            subject="Maths",
            score=percent,
            max_score=100,
        )

    def add_social(self, child=None, days_ago=0, rating=5):
        return SocialObservation.objects.create(
            child=child or self.child,
            source=Source.MENTOR,
            occurred_on=self.today - timedelta(days=days_ago),
            dimension=SocialObservation.Dimension.PEERS,
            rating=rating,
        )

    def add_habit(self, child=None, days_ago=0, **overrides):
        values = {
            "sleep_hours": 10,
            "activity_minutes": 60,
            "screen_minutes": 30,
            "nutrition_quality": 5,
            "ate_breakfast": True,
        }
        values.update(overrides)
        return HabitLog.objects.create(
            child=child or self.child,
            source=Source.CHILD,
            occurred_on=self.today - timedelta(days=days_ago),
            **values,
        )


class DailyValueTests(ScoringFixture):
    def test_full_marks_emotional_day_is_one(self):
        self.add_checkin()
        values = scoring.daily_values(
            self.child, "emotional", self.today, self.today
        )
        self.assertEqual(values[self.today], 1.0)

    def test_lowest_emotional_day_is_zero(self):
        self.add_checkin(rating=1)
        values = scoring.daily_values(
            self.child, "emotional", self.today, self.today
        )
        self.assertEqual(values[self.today], 0.0)

    def test_academic_is_a_share_of_the_mark_not_the_raw_mark(self):
        self.add_academic(percent=17)  # 17 out of 100
        self.add_academic(percent=85)  # same day; averaged
        values = scoring.daily_values(
            self.child, "academic", self.today, self.today
        )
        self.assertAlmostEqual(values[self.today], (0.17 + 0.85) / 2, places=4)

    def test_all_good_habits_score_one(self):
        self.add_habit()
        values = scoring.daily_values(self.child, "habits", self.today, self.today)
        self.assertEqual(values[self.today], 1.0)

    def test_all_bad_habits_score_zero(self):
        self.add_habit(
            sleep_hours=5,
            activity_minutes=0,
            screen_minutes=240,
            nutrition_quality=1,
            ate_breakfast=False,
        )
        values = scoring.daily_values(self.child, "habits", self.today, self.today)
        self.assertEqual(values[self.today], 0.0)

    def test_partial_habit_day_uses_only_the_measurements_present(self):
        # Sleep alone: 10 h scores 1.0; the absent measures must not drag it down.
        self.add_habit(
            activity_minutes=None,
            screen_minutes=None,
            nutrition_quality=None,
            ate_breakfast=None,
        )
        values = scoring.daily_values(self.child, "habits", self.today, self.today)
        self.assertEqual(values[self.today], 1.0)

    def test_sleep_guideline_is_age_appropriate(self):
        # 8.5 h is adequate for a 13-year-old and short for an 8-year-old.
        self.assertLess(
            scoring._sleep_score(8.5, "primary"),
            1.0,
        )
        self.assertEqual(scoring._sleep_score(8.5, "early_secondary"), 1.0)

    def test_multiple_reporters_on_one_day_are_averaged(self):
        self.add_checkin(rating=1)
        EmotionalCheckin.objects.create(
            child=self.child,
            source=Source.MENTOR,
            occurred_on=self.today,
            mood=5,
            energy=5,
            sleep_quality=5,
            felt_connected=5,
        )
        values = scoring.daily_values(
            self.child, "emotional", self.today, self.today
        )
        self.assertEqual(values[self.today], 0.5)


class WeeklyScoreTests(ScoringFixture):
    def test_five_good_days_score_one_hundred_and_are_good_confidence(self):
        for offset in range(5):
            self.add_checkin(days_ago=offset)

        scoring.recompute_child(self.child, self.today)
        row = DomainScore.objects.get(
            child=self.child, domain="emotional", period_end=self.today
        )

        self.assertEqual(float(row.score), 100.0)
        self.assertEqual(row.data_points, 5)
        self.assertEqual(row.confidence, "good")
        self.assertEqual(row.method_version, scoring.METHOD_VERSION)
        self.assertEqual(
            row.period_start, self.today - timedelta(days=scoring.PERIOD_DAYS - 1)
        )

    def test_a_child_with_only_one_domain_gets_no_overall_score(self):
        self.add_checkin()
        scoring.recompute_child(self.child, self.today)

        self.assertFalse(
            DomainScore.objects.filter(
                child=self.child, domain=scoring.OVERALL, period_end=self.today
            ).exists()
        )

    def test_overall_score_renormalises_over_the_domains_present(self):
        # One day with emotional 1.0 and academic 0.5. The weights are 0.40 and
        # 0.25, so the score is (0.40 + 0.125) / 0.65, not (0.40 + 0.125) / 1.0.
        self.add_checkin(rating=5)
        self.add_academic(percent=50)

        scoring.recompute_child(self.child, self.today)
        overall = DomainScore.objects.get(
            child=self.child, domain=scoring.OVERALL, period_end=self.today
        )

        self.assertAlmostEqual(float(overall.score), 80.77, places=2)
        self.assertEqual(overall.data_points, 1)

    def test_days_with_one_domain_do_not_contribute_to_the_overall_score(self):
        self.add_checkin(days_ago=0)  # emotional + academic
        self.add_academic(days_ago=0, percent=100)
        self.add_checkin(days_ago=1)  # emotional only

        scoring.recompute_child(self.child, self.today)
        overall = DomainScore.objects.get(
            child=self.child, domain=scoring.OVERALL, period_end=self.today
        )

        self.assertEqual(overall.data_points, 1)

    def test_confidence_reflects_the_reporting_cadence(self):
        self.assertEqual(scoring.confidence_for("emotional", 0), "none")
        self.assertEqual(scoring.confidence_for("emotional", 1), "thin")
        self.assertEqual(scoring.confidence_for("emotional", 2), "thin")
        self.assertEqual(scoring.confidence_for("emotional", 3), "moderate")
        self.assertEqual(scoring.confidence_for("emotional", 5), "good")
        # Academic entries are less frequent by nature, so the bar is lower.
        self.assertEqual(scoring.confidence_for("academic", 1), "thin")
        self.assertEqual(scoring.confidence_for("academic", 2), "moderate")
        self.assertEqual(scoring.confidence_for("academic", 3), "good")

    def test_a_week_with_no_data_gets_no_row_not_a_zero(self):
        self.add_checkin(days_ago=0)
        scoring.recompute_child(self.child, self.today)

        older = DomainScore.objects.filter(
            child=self.child, domain="emotional", period_end=self.today - timedelta(days=7)
        )
        self.assertFalse(older.exists())

    def test_stored_series_reports_gaps_as_none(self):
        self.add_checkin(days_ago=0)
        scoring.recompute_child(self.child, self.today)

        series = scoring.stored_series(self.child, "emotional", self.today)

        self.assertEqual(len(series), scoring.TREND_PERIODS)
        self.assertEqual([point["value"] for point in series[:-1]], [None] * 7)
        self.assertEqual(series[-1]["value"], 100.0)
        self.assertEqual(series[-1]["confidence"], "thin")


class RecomputeTests(ScoringFixture):
    def test_recompute_is_idempotent(self):
        for offset in range(3):
            self.add_checkin(days_ago=offset)
        self.add_academic(percent=80)
        self.add_social(rating=4)
        self.add_habit()

        first = scoring.recompute_child(self.child, self.today)
        rows_first = list(
            DomainScore.objects.filter(child=self.child)
            .order_by("domain", "period_end")
            .values(
                "domain", "period_start", "period_end", "score",
                "data_points", "confidence", "method_version",
            )
        )

        second = scoring.recompute_child(self.child, self.today)
        rows_second = list(
            DomainScore.objects.filter(child=self.child)
            .order_by("domain", "period_end")
            .values(
                "domain", "period_start", "period_end", "score",
                "data_points", "confidence", "method_version",
            )
        )

        self.assertEqual(first["scores"], second["scores"])
        self.assertEqual(rows_first, rows_second)

    def test_recompute_picks_up_a_changed_entry(self):
        for offset in range(3):
            self.add_checkin(days_ago=offset, rating=5)
        scoring.recompute_child(self.child, self.today)
        before = DomainScore.objects.get(
            child=self.child, domain="emotional", period_end=self.today
        ).score

        entry = EmotionalCheckin.objects.get(child=self.child, occurred_on=self.today)
        entry.mood = 1
        entry.energy = 1
        entry.sleep_quality = 1
        entry.felt_connected = 1
        entry.save()
        scoring.recompute_child(self.child, self.today)
        after = DomainScore.objects.get(
            child=self.child, domain="emotional", period_end=self.today
        ).score

        self.assertLess(after, before)

    def test_baseline_stores_mean_and_spread(self):
        for offset, rating in enumerate((1, 3, 5)):
            self.add_checkin(days_ago=offset, rating=rating)

        scoring.recompute_child(self.child, self.today)
        baseline = BaselineStat.objects.get(
            child=self.child, domain="emotional", as_of=self.today
        )

        self.assertEqual(float(baseline.mean), 50.0)
        self.assertAlmostEqual(float(baseline.stddev), 40.82, places=2)
        self.assertEqual(baseline.sample_size, 3)
        self.assertEqual(baseline.window_days, scoring.BASELINE_DAYS)

    def test_baseline_advertised_to_the_chart_is_chart_ready(self):
        for offset in range(3):
            self.add_checkin(days_ago=offset, rating=5)
        scoring.recompute_child(self.child, self.today)

        baseline = scoring.baseline_for(self.child, "emotional", self.today)
        self.assertEqual(baseline["mean"], 100.0)
        self.assertEqual(baseline["stddev"], 0.0)
        self.assertEqual(baseline["sample_size"], 3)

    def test_ensure_child_current_skips_a_fresh_child(self):
        self.add_checkin()
        scoring.recompute_child(self.child, self.today)

        self.assertFalse(scoring.ensure_child_current(self.child, self.today))

    def test_ensure_child_current_recomputes_when_an_entry_is_newer(self):
        self.add_checkin()
        scoring.recompute_child(self.child, self.today)

        # Move the stored computation into the past, simulating an entry added
        # after the last recompute.
        DomainScore.objects.filter(child=self.child).update(
            computed_at=timezone.now() - timedelta(hours=1)
        )

        self.assertTrue(scoring.ensure_child_current(self.child, self.today))

    def test_an_empty_child_produces_no_rows(self):
        result = scoring.recompute_child(self.other_child, self.today)

        self.assertEqual(result["scores"], 0)
        self.assertEqual(result["baselines"], 0)
        self.assertFalse(DomainScore.objects.filter(child=self.other_child).exists())
        self.assertEqual(
            [point["value"] for point in scoring.stored_series(
                self.other_child, scoring.OVERALL, self.today
            )],
            [None] * scoring.TREND_PERIODS,
        )


class CohortSnapshotTests(ScoringFixture):
    def test_snapshot_averages_without_naming_children(self):
        # Child one: high in two domains. Child two: low in two domains.
        self.add_checkin(rating=5)
        self.add_academic(percent=100)
        self.add_checkin(child=self.other_child, rating=1)
        self.add_academic(child=self.other_child, percent=0)

        scoring.recompute_all(self.today)
        snapshot = scoring.cohort_snapshot(self.today)

        self.assertEqual(snapshot["children_scored"], 2)
        self.assertEqual(snapshot["average"], 50.0)
        self.assertEqual(snapshot["buckets"][0]["count"], 1)
        self.assertEqual(snapshot["buckets"][-1]["count"], 1)
        self.assertNotIn(self.child.full_name, str(snapshot))
        self.assertNotIn(self.other_child.full_name, str(snapshot))

    def test_snapshot_counts_domains_and_confidence(self):
        self.add_checkin()
        self.add_academic()
        scoring.recompute_all(self.today)

        snapshot = scoring.cohort_snapshot(self.today)
        by_key = {row["key"]: row for row in snapshot["domains"]}
        confidence = {item["key"]: item["count"] for item in snapshot["confidence"]}

        self.assertEqual(by_key["emotional"]["children"], 1)
        self.assertEqual(by_key["emotional"]["average"], 100.0)
        self.assertEqual(confidence["thin"], 1)

    def test_snapshot_trend_has_a_point_per_window(self):
        self.add_checkin()
        self.add_academic()
        scoring.recompute_all(self.today)

        snapshot = scoring.cohort_snapshot(self.today)
        self.assertEqual(len(snapshot["trend"]), scoring.TREND_PERIODS)
        self.assertEqual(snapshot["trend"][-1]["value"], 100.0)
        self.assertEqual(snapshot["trend"][-1]["data_points"], 1)

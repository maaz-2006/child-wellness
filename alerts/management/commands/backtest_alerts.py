"""Measure the alert rules against the synthetic cohort's known trajectories.

This is the command behind the report's precision/recall figures. It exists
because "the alerts look sensible" is not an evaluation.

How the labels are used:

* `gradual_decline` and `sudden_event` are positives. The label records the
  simulated onset date, so a detection *before* onset is a false positive and a
  detection after onset has a measurable lead time.
* `healthy` and `recovering` are negatives for the precision denominator.
  `recovering` is included because it starts from a real simulated dip, so it is
  a harder negative than a healthy child.
* `sparse` is excluded: its problem is missing data, and counting that as either
  a hit or a miss would flatter or punish the rules for a recording artefact.

The command never writes alerts, and it restores the current stored scores at
the end. Running it on a production database would be slow and pointless; it is
an evaluation tool for the synthetic cohort.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from alerts import rules
from analytics import scoring
from analytics.models import ScenarioLabel

POSITIVE = {
    ScenarioLabel.Archetype.GRADUAL_DECLINE,
    ScenarioLabel.Archetype.SUDDEN_EVENT,
}
NEGATIVE = {
    ScenarioLabel.Archetype.HEALTHY,
    ScenarioLabel.Archetype.RECOVERING,
}


def _signal_findings(findings) -> list:
    """Findings that represent a wellness signal, not merely a data gap."""
    return [finding for finding in findings if finding.rule_key != "no_recent_data"]


class Command(BaseCommand):
    help = "Backtest alert rules against the synthetic cohort's scenario labels."

    def add_arguments(self, parser):
        parser.add_argument(
            "--weeks", type=int, default=8, help="How many weekly evaluation points."
        )
        parser.add_argument(
            "--step", type=int, default=7, help="Days between evaluation points."
        )
        parser.add_argument(
            "--positive-only",
            action="store_true",
            help="Skip the negative cohort and report recall/lead time only.",
        )

    def handle(self, *args, **options):
        if options["weeks"] < 2:
            raise CommandError("--weeks must be at least 2.")
        if options["step"] < 1:
            raise CommandError("--step must be at least 1.")

        children = list(
            ScenarioLabel.objects.select_related("child").order_by("child_id")
        )
        if not children:
            raise CommandError("No scenario labels. Run seed_demo first.")

        today = timezone.localdate()
        evaluation_dates = [
            today - timedelta(days=options["step"] * offset)
            for offset in reversed(range(options["weeks"]))
        ]

        positives = [
            label for label in children if label.archetype in POSITIVE
        ]
        negatives = [
            label
            for label in children
            if label.archetype in NEGATIVE and not options["positive_only"]
        ]

        detections: list[dict] = []
        missed: list[str] = []
        false_positives: list[str] = []
        early_flags: list[str] = []

        for label in positives:
            child = label.child
            if not child.has_consent:
                continue
            onset = label.onset_date
            detected_at = None
            any_before_onset = False
            for as_of in evaluation_dates:
                scoring.recompute_child(child, as_of)
                findings = _signal_findings(rules.evaluate(child, as_of))
                if not findings:
                    continue
                if onset is None:
                    detected_at = detected_at or as_of
                elif as_of < onset:
                    any_before_onset = True
                elif detected_at is None:
                    detected_at = as_of
            if detected_at is not None and onset is not None:
                detections.append(
                    {
                        "child": child,
                        "onset": onset,
                        "detected": detected_at,
                        "lead_days": (detected_at - onset).days,
                    }
                )
            elif onset is not None:
                missed.append(child.full_name)
            if any_before_onset:
                early_flags.append(child.full_name)

        for label in negatives:
            child = label.child
            if not child.has_consent:
                continue
            for as_of in evaluation_dates:
                scoring.recompute_child(child, as_of)
                if _signal_findings(rules.evaluate(child, as_of)):
                    false_positives.append(child.full_name)
                    break

        # Restore the current stored scores, because the backtest overwrote them
        # one historical as-of at a time.
        scoring.recompute_all(as_of=today)

        self._report(
            positives=[label for label in positives if label.child.has_consent],
            negatives=[label for label in negatives if label.child.has_consent],
            detections=detections,
            missed=missed,
            false_positives=false_positives,
            early_flags=early_flags,
            dates=evaluation_dates,
        )

    def _report(
        self,
        *,
        positives,
        negatives,
        detections,
        missed,
        false_positives,
        early_flags,
        dates,
    ) -> None:
        style = self.style
        detected_names = {row["child"].pk for row in detections}
        true_positive_children = len(detected_names)
        false_positive_children = len(set(false_positives))

        self.stdout.write("")
        self.stdout.write(style.SUCCESS("Alert rule backtest"))
        self.stdout.write(
            f"  evaluation points   {dates[0]} to {dates[-1]} "
            f"({len(dates)} weekly points, non-persistent)"
        )
        self.stdout.write(f"  positive children   {len(positives)}")
        self.stdout.write(f"  negative children   {len(negatives)}")
        self.stdout.write(f"  detected            {true_positive_children}")
        self.stdout.write(f"  missed              {len(missed)}")
        self.stdout.write(f"  false positives     {false_positive_children}")

        denominator = true_positive_children + false_positive_children
        if denominator:
            self.stdout.write(
                f"  child-level precision {true_positive_children / denominator:.2f}"
            )
        if positives:
            self.stdout.write(
                f"  child-level recall    {true_positive_children / len(positives):.2f}"
            )
        if detections:
            lead = median(row["lead_days"] for row in detections)
            self.stdout.write(f"  median lead time      {lead:.0f} days after onset")

        if early_flags:
            self.stdout.write("")
            self.stdout.write(
                style.WARNING(
                    "  flagged before simulated onset (counted as early, not as a hit): "
                    + ", ".join(early_flags)
                )
            )
        if missed:
            self.stdout.write("")
            self.stdout.write(style.WARNING("  missed: " + ", ".join(missed)))
        if false_positives:
            self.stdout.write("")
            self.stdout.write(
                style.WARNING(
                    "  false positives: " + ", ".join(sorted(set(false_positives)))
                )
            )

        self.stdout.write("")
        self.stdout.write(
            "  Ground truth is synthetic. These figures measure the rules against "
            "the generator's labels, not against clinical outcomes."
        )

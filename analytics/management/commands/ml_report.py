"""Run the offline classifier benchmark and store the result.

This command does not change any score, alert or child record. It reads the
stored weekly scores and guardian ratings, fits a small logistic regression
leave-one-child-out, and writes a `ModelReport` for the methodology page and the
report appendix.

    python manage.py ml_report
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from analytics import ml


class Command(BaseCommand):
    help = "Evaluate the offline logistic-regression benchmark on the synthetic cohort."

    def handle(self, *args, **options):
        report = ml.evaluate_and_store()

        style = self.style
        self.stdout.write("")
        self.stdout.write(style.SUCCESS("Offline model benchmark"))
        self.stdout.write(f"  algorithm         {report.algorithm}")
        self.stdout.write(f"  as of             {report.as_of}")
        self.stdout.write(f"  task              {report.task}")
        self.stdout.write(
            f"  examples          {report.n_examples} "
            f"({report.n_positive} positive, {report.n_negative} negative)"
        )
        self.stdout.write(f"  children          {report.n_children}")
        self.stdout.write(f"  validation        leave-one-child-out, {report.folds} folds")

        if not report.has_metrics:
            self.stdout.write("")
            self.stdout.write(
                style.WARNING(
                    "  Insufficient usable examples for a benchmark. "
                    "Run seed_demo first, then try again."
                )
            )
            return

        metrics = report.metrics
        for key in (
            "accuracy",
            "precision",
            "recall",
            "f1",
            "specificity",
            "auc",
            "prevalence",
            "brier",
        ):
            value = metrics.get(key)
            label = ml.METRIC_LABELS.get(key, (key, ""))[0]
            if value is None:
                self.stdout.write(f"  {label:<17} n/a")
            else:
                self.stdout.write(f"  {label:<17} {value:.4f}")

        confusion = report.confusion
        self.stdout.write(
            "  confusion         "
            f"tp {confusion.get('tp', 0)}, fp {confusion.get('fp', 0)}, "
            f"tn {confusion.get('tn', 0)}, fn {confusion.get('fn', 0)}"
        )

        if report.coefficients:
            self.stdout.write("")
            self.stdout.write("  Largest standardised coefficients (full-cohort fit)")
            ordered = sorted(
                report.coefficients,
                key=lambda row: abs(row.get("weight", 0.0)),
                reverse=True,
            )[:6]
            for row in ordered:
                self.stdout.write(
                    f"    {row['label']:<45} {row['weight']:+.4f}"
                )

        self.stdout.write("")
        self.stdout.write(
            "  This is an offline benchmark, not a production classifier. "
            "No alert or score is produced by it."
        )
        self.stdout.write(
            "  Ground truth is synthetic, so the figures measure the method "
            "against the generator, not clinical outcomes."
        )
        self.stdout.write("")
        self.stdout.write(style.SUCCESS(f"  Model report #{report.pk} stored."))
        self.stdout.write("")

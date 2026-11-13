"""Derived analytics state.

Nothing in here is authored by a human. Every row is recomputable from raw domain
entries by `manage.py recompute_wellness`, which is what makes the scores
auditable: given the same input data and the same `method_version`, you get the
same numbers.

`ScenarioLabel` is not analytics output - it is the *ground truth* attached to
the synthetic cohort, and it is what lets the report quote real precision and
recall figures instead of claiming the alerts "seem reasonable".
"""

from django.db import models


class DomainScore(models.Model):
    """A 0-100 wellness score for one child, one domain, one period."""

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="domain_scores"
    )
    domain = models.CharField(max_length=16, db_index=True)
    period_start = models.DateField()
    period_end = models.DateField()
    score = models.DecimalField(max_digits=5, decimal_places=2)
    data_points = models.PositiveSmallIntegerField(default=0)
    confidence = models.CharField(
        max_length=12,
        choices=[
            ("none", "No data"),
            ("thin", "Thin"),
            ("moderate", "Moderate"),
            ("good", "Good"),
        ],
        default="none",
    )
    method_version = models.CharField(max_length=12, default="1.0")
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["child", "domain", "period_end"],
                name="uniq_score_child_domain_period",
            )
        ]
        indexes = [models.Index(fields=["domain", "-period_end"])]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.domain} {self.period_end}: {self.score}"


class BaselineStat(models.Model):
    """Per-child rolling baseline.

    Alerts compare a child against *their own* recent normal, not against a
    population average, because the population includes children whose normal is
    already a concern. Storing the baseline makes each alert reproducible.
    """

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="baselines"
    )
    domain = models.CharField(max_length=16)
    as_of = models.DateField()
    window_days = models.PositiveSmallIntegerField(default=28)
    mean = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    stddev = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    sample_size = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["-as_of"]
        constraints = [
            models.UniqueConstraint(
                fields=["child", "domain", "as_of", "window_days"],
                name="uniq_baseline_child_domain_date_window",
            )
        ]

    def __str__(self) -> str:
        return f"{self.child.short_name} {self.domain} baseline @ {self.as_of}: {self.mean}"


class ScenarioLabel(models.Model):
    """Ground truth for the synthetic cohort.

    Deliberately separate from the alert tables: the alert engine must never be
    able to read this. It exists so `manage.py backtest` can measure detection
    performance against a known onset date.
    """

    class Archetype(models.TextChoices):
        HEALTHY = "healthy", "Stable and healthy"
        GRADUAL_DECLINE = "gradual_decline", "Gradual decline"
        SUDDEN_EVENT = "sudden_event", "Sudden event"
        RECOVERING = "recovering", "Recovering from a low period"
        SPARSE = "sparse", "Sparse / disengaged data"

    child = models.OneToOneField(
        "children.Child", on_delete=models.CASCADE, related_name="scenario_label"
    )
    archetype = models.CharField(max_length=24, choices=Archetype.choices)
    onset_date = models.DateField(
        null=True,
        blank=True,
        help_text="For declining archetypes, the day the simulated change begins.",
    )
    severity = models.CharField(
        max_length=12,
        choices=[("low", "Low"), ("moderate", "Moderate"), ("high", "High")],
        default="moderate",
    )
    notes = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = "scenario label"

    def __str__(self) -> str:
        return f"{self.child.short_name}: {self.get_archetype_display()}"

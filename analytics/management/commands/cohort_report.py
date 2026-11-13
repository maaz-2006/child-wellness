"""Validate the synthetic cohort: do the labelled archetypes actually behave
differently in the data?

This is an instrument check, not a product feature. If a child labelled
"gradual decline" shows a flat mood series, then any later claim that the alert
engine detected declines is measuring noise. Printing the numbers makes that
failure visible immediately, and the output doubles as a table for the report.

    python manage.py cohort_report
"""

from __future__ import annotations

from statistics import mean

from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Q

from analytics.models import ScenarioLabel
from children.models import Child
from domains.models import AcademicRecord, AttendanceRecord, EmotionalCheckin, HabitLog


class Command(BaseCommand):
    help = "Compare early vs late period averages per labelled archetype."

    def handle(self, *args, **options):
        children = list(Child.objects.select_related("scenario_label").order_by("pk"))
        labelled = [c for c in children if hasattr(c, "scenario_label")]
        if not labelled:
            self.stderr.write("No labelled children. Run: manage.py seed_demo")
            return

        dates = sorted(
            EmotionalCheckin.objects.values_list("occurred_on", flat=True).distinct()
        )
        if len(dates) < 6:
            self.stderr.write("Not enough history to split into periods.")
            return
        split = dates[len(dates) // 3]
        split_late = dates[(len(dates) * 2) // 3]

        self.stdout.write("")
        self.stdout.write(f"Period thirds split at {split} and {split_late}")
        self.stdout.write("")
        header = f"{'archetype':<18}{'n':>3}  {'mood e->l':<13}{'sleep e->l':<14}{'acad e->l':<14}{'attend e->l':<13}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for archetype, _label in ScenarioLabel.Archetype.choices:
            group = [c for c in labelled if c.scenario_label.archetype == archetype]
            if not group:
                continue
            self.stdout.write(
                f"{archetype:<18}{len(group):>3}  "
                f"{self._pair(group, EmotionalCheckin, "mood", split, split_late):<13}"
                f"{self._pair(group, HabitLog, "sleep_hours", split, split_late):<14}"
                f"{self._pair(group, AcademicRecord, "pct", split, split_late):<14}"
                f"{self._attendance_pair(group, split, split_late):<13}"
            )

        self.stdout.write("")
        self.stdout.write(
            "Expected: healthy flat, gradual_decline and sudden_event falling,"
            " recovering rising. Flat rows mean the generator or the split is wrong."
        )
        self.stdout.write("")

    def _pair(self, group, model, field, split, split_late) -> str:
        early_values, late_values = [], []
        for child in group:
            rows = model.objects.filter(child=child)
            for row in rows:
                if row.occurred_on < split:
                    value = self._value(row, field)
                    if value is not None:
                        early_values.append(float(value))
                elif row.occurred_on > split_late:
                    value = self._value(row, field)
                    if value is not None:
                        late_values.append(float(value))
        if not early_values or not late_values:
            return "--"
        return f"{mean(early_values):.1f}->{mean(late_values):.1f}"

    def _value(self, row, field):
        if field == "pct":
            return row.percentage
        return getattr(row, field)

    def _attendance_pair(self, group, split, split_late) -> str:
        def rate(queryset):
            total = queryset.count()
            if not total:
                return None
            present = queryset.filter(
                status__in=[AttendanceRecord.Status.PRESENT, AttendanceRecord.Status.LATE]
            ).count()
            return present / total

        early = rate(
            AttendanceRecord.objects.filter(child__in=group, occurred_on__lt=split)
        )
        late = rate(
            AttendanceRecord.objects.filter(child__in=group, occurred_on__gt=split_late)
        )
        if early is None or late is None:
            return "--"
        return f"{early:.0%}->{late:.0%}"

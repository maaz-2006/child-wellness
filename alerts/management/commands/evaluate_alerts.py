"""Run the deterministic alert rules and persist the findings.

Typical use on the host after a score recompute:

    python manage.py evaluate_alerts
    python manage.py evaluate_alerts --as-of 2026-11-14
    python manage.py evaluate_alerts --child 12 --dry-run

The command recomputes scores first by default. Evaluating rules against stale
stored scores would produce alerts about last week's data wearing today's date,
which is worse than no alert.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from alerts import engine, rules
from analytics import scoring


class Command(BaseCommand):
    help = "Evaluate alert rules for the cohort and persist new findings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--as-of",
            help="Evaluation date as YYYY-MM-DD. Defaults to today.",
        )
        parser.add_argument(
            "--child",
            type=int,
            help="Evaluate one child by primary key instead of the cohort.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would fire without writing alerts.",
        )
        parser.add_argument(
            "--no-recompute",
            action="store_true",
            help="Use the scores already stored instead of recomputing first.",
        )

    def handle(self, *args, **options):
        as_of = None
        if options["as_of"]:
            try:
                as_of = date.fromisoformat(options["as_of"])
            except ValueError as exc:
                raise CommandError("--as-of must be a date in YYYY-MM-DD form.") from exc

        if options["child"]:
            from children.models import Child

            child = Child.objects.filter(pk=options["child"]).first()
            if child is None:
                raise CommandError(f"No child with primary key {options['child']}.")
            return self._one(child, as_of, options)

        if not options["no_recompute"]:
            scoring.recompute_all(as_of)

        if options["dry_run"]:
            from children.models import Child

            total = 0
            for child in Child.objects.filter(is_active=True):
                if not child.has_consent:
                    continue
                findings = rules.evaluate(child, as_of)
                total += len(findings)
                if findings:
                    self.stdout.write(
                        f"  {child.full_name}: "
                        + ", ".join(f"{f.rule_key} ({f.tier})" for f in findings)
                    )
            self.stdout.write(
                self.style.WARNING(f"Dry run: {total} findings not written.")
            )
            return

        result = engine.evaluate_all(as_of)
        self.stdout.write(
            self.style.SUCCESS(
                f"Evaluated {result['children']} children as of {result['as_of']}: "
                f"{result['findings']} findings, {result['alerts']} alerts "
                f"(urgent {result['by_tier'].get('urgent', 0)}, "
                f"concern {result['by_tier'].get('concern', 0)}, "
                f"watch {result['by_tier'].get('watch', 0)})."
            )
        )

    def _one(self, child, as_of, options) -> None:
        if not options["no_recompute"]:
            scoring.recompute_child(child, as_of)

        if options["dry_run"]:
            findings = rules.evaluate(child, as_of)
            if not findings:
                self.stdout.write(f"No findings for {child.full_name}.")
            for finding in findings:
                self.stdout.write(
                    f"  {finding.rule_key} [{finding.tier}] {finding.title}"
                )
            return

        result = engine.evaluate_child(child, as_of)
        self.stdout.write(
            self.style.SUCCESS(
                f"{child.full_name}: {result['findings']} findings, "
                f"{len(result['alerts'])} alerts."
            )
        )

"""Recompute stored wellness scores and baselines.

The tables this writes (`DomainScore`, `BaselineStat`) are a cache of a
calculation, not source data. Running this command is always safe: it deletes and
rebuilds the stored window for each child, so the result depends only on the raw
entries and `METHOD_VERSION`.

    python manage.py recompute_wellness
    python manage.py recompute_wellness --child 12
    python manage.py recompute_wellness --as-of 2026-11-01
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from analytics import scoring


class Command(BaseCommand):
    help = "Recompute wellness scores and per-child baselines from raw entries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--child",
            type=int,
            help="Recompute one child by primary key instead of the whole cohort.",
        )
        parser.add_argument(
            "--as-of",
            help="End date for the rolling windows, as YYYY-MM-DD. Defaults to today.",
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
            result = scoring.recompute_child(child, as_of)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Recomputed {result['scores']} scores and "
                    f"{result['baselines']} baselines for {child.full_name} "
                    f"(method {scoring.METHOD_VERSION}, as of {result['as_of']})."
                )
            )
            return

        result = scoring.recompute_all(as_of)
        self.stdout.write(
            self.style.SUCCESS(
                f"Recomputed {result['scores']} scores for {result['children']} "
                f"children (method {scoring.METHOD_VERSION}, as of {result['as_of']})."
            )
        )

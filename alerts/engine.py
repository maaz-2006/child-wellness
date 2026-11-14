"""Persist rule findings as alerts that a named person owns.

The rules decide *what* is true. This module decides what the school does about
it, and it is deliberately conservative:

* **One rolling alert per rule per child.** A rule that keeps firing updates the
  open alert instead of opening a new one every week. A queue that grows by one
  row per rule per week stops being a queue and becomes a log nobody reads.
* **De-duplication is safe to re-run.** `(child, rule_key, period_end)` is
  unique, and an evaluation run on the same day does not increment
  `occurrences`. A scheduled job can therefore run hourly without inflating the
  record.
* **Tiers only go up while an alert is open.** Re-running a rule cannot silently
  downgrade an urgent concern because a later score recovered; a person closes
  the alert, not a cron job.
* **Alerts are never auto-resolved.** Recovery is good news, but the decision
  that a case is finished belongs to the mentor who was working it.
* **Assignment is explicit.** Urgent and safeguarding alerts go to the
  designated safeguarding lead when one exists; otherwise to the child's class
  teacher. An unassigned alert is a notification nobody reads.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction
from django.utils import timezone

from core.models import Role, School
from children.models import Mentorship

from .models import Alert, AlertEvent
from .rules import TIER_ORDER, Finding, evaluate

#: Preferred order for choosing a default owner. The class teacher sees the
#: child every day; a subject teacher or coach may see them once a week.
ASSIGNMENT_PREFERENCE = (
    Mentorship.Role.CLASS_TEACHER,
    Mentorship.Role.MENTOR,
    Mentorship.Role.COUNSELLOR,
    Mentorship.Role.SUBJECT_TEACHER,
    Mentorship.Role.COACH,
)


def _school_for(child) -> School | None:
    return child.school or School.load()


def safeguarding_lead_for(child):
    school = _school_for(child)
    if school is not None and school.safeguarding_lead_id is not None:
        lead = school.safeguarding_lead
        if lead.is_active and lead.role in {Role.MENTOR, Role.ADMIN}:
            return lead
    return None


def default_assignee(child, tier: str, rule_key: str):
    """The named person who should see this alert first.

    Safeguarding signals and urgent tiers go to the designated lead when the
    school has named one. Otherwise they fall back to the child's class teacher,
    which is the best available answer - not a perfect one, but a person.
    """
    if rule_key.startswith("safeguarding_signal") or tier == Alert.Tier.URGENT:
        lead = safeguarding_lead_for(child)
        if lead is not None:
            return lead

    links = child.mentorships.filter(is_active=True).select_related("mentor")
    for role in ASSIGNMENT_PREFERENCE:
        for link in links:
            if link.role == role and link.mentor.is_active:
                return link.mentor
    for link in links:
        if link.mentor.is_active:
            return link.mentor
    return None


def _highest_tier(*tiers: str) -> str:
    return max(tiers, key=lambda tier: TIER_ORDER.get(tier, 0))


@transaction.atomic
def persist_finding(child, finding: Finding, as_of: date, actor=None) -> Alert:
    """Create or update the open alert for this rule, returning it."""
    existing = (
        Alert.objects.select_for_update()
        .filter(
            child=child,
            rule_key=finding.rule_key,
            status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED],
        )
        .order_by("-pk")
        .first()
    )

    if existing is None:
        # A closed alert for the same rule and same day means a person already
        # decided this. Do not reopen it from a cron run, and do not trip the
        # (child, rule_key, period_end) uniqueness constraint by trying to insert
        # a duplicate. The next evaluation day gets a fresh alert if the rule
        # still fires.
        closed_same_period = Alert.objects.filter(
            child=child, rule_key=finding.rule_key, period_end=as_of
        ).first()
        if closed_same_period is not None:
            return closed_same_period

        alert = Alert.objects.create(
            child=child,
            rule_key=finding.rule_key,
            tier=finding.tier,
            status=Alert.Status.OPEN,
            domain=finding.domain,
            title=finding.title,
            summary=finding.summary,
            evidence=finding.evidence,
            period_end=as_of,
            opened_on=as_of,
            last_seen_on=as_of,
            occurrences=1,
            assigned_to=default_assignee(child, finding.tier, finding.rule_key),
        )
        AlertEvent.objects.create(
            alert=alert,
            actor=actor,
            kind=AlertEvent.Kind.OPENED,
            body=(
                "Alert opened by the screening engine. "
                "Evidence is recorded on the alert; no child free text is stored here."
            ),
        )
        return alert

    if existing.last_seen_on != as_of:
        existing.occurrences += 1
        existing.last_seen_on = as_of

    existing.tier = _highest_tier(existing.tier, finding.tier)
    existing.domain = finding.domain
    existing.title = finding.title
    existing.summary = finding.summary
    existing.evidence = finding.evidence
    if existing.assigned_to_id is None:
        existing.assigned_to = default_assignee(
            child, existing.tier, existing.rule_key
        )
    existing.save()
    return existing


def evaluate_child(child, as_of: date | None = None, actor=None) -> dict:
    """Evaluate one child and persist the findings. Returns a small summary."""
    as_of = as_of or timezone.localdate()
    findings = evaluate(child, as_of)
    alerts = [persist_finding(child, finding, as_of, actor=actor) for finding in findings]
    return {
        "child": child,
        "as_of": as_of,
        "findings": len(findings),
        "alerts": alerts,
    }


def evaluate_all(as_of: date | None = None, actor=None) -> dict:
    """Evaluate every active child with recorded consent.

    Children without consent are skipped, not evaluated-and-suppressed: running
    a screening algorithm over their data would be processing it without a
    lawful basis.
    """
    from children.models import Child

    as_of = as_of or timezone.localdate()
    eligible = [
        child
        for child in Child.objects.filter(is_active=True).select_related("school")
        if child.has_consent
    ]

    counts = {
        "children": len(eligible),
        "findings": 0,
        "alerts": 0,
        "by_tier": {tier: 0 for tier in TIER_ORDER},
    }
    for child in eligible:
        result = evaluate_child(child, as_of, actor=actor)
        counts["findings"] += result["findings"]
        counts["alerts"] += len(result["alerts"])
        for alert in result["alerts"]:
            counts["by_tier"][alert.tier] = counts["by_tier"].get(alert.tier, 0) + 1
    counts["as_of"] = as_of
    return counts


def open_alerts_for(child):
    return Alert.objects.filter(
        child=child, status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED]
    )

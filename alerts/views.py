"""Alert screens.

Four audiences, four shapes:

* **Mentor** - the operational queue and the case file, for children they are
  assigned to. This is where acknowledging, noting, resolving and sharing happen.
* **Guardian** - only alerts a mentor explicitly shared, with no tier, no case
  notes and no internal evidence. Urgent alerts never appear.
* **Administrator** - counts only. The matrix grants AGGREGATE on alerts, so the
  institution page cannot name a child even if a template tried to.
* **Child** - nothing. `(CHILD, SELF)` has NONE on alerts by design.

State changes go through `alerts.services`, never through `Alert.save()` in a
view, so the safety rules are enforced in one place.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from core import permissions
from core.audit import record_request
from core.mixins import RoleRequiredMixin
from core.models import AuditLog, Role
from core.permissions import Access, Resource
from feedback.models import PulseResponse, current_week_start
from feedback.services import children_due_for

from . import services
from .models import Alert
from .rules import RULE_LABELS, TIER_ORDER

STATUS_FILTERS = {
    "open": [Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED],
    "resolved": [Alert.Status.RESOLVED],
    "dismissed": [Alert.Status.DISMISSED],
    "all": [choice for choice, _label in Alert.Status.choices],
}


def _label_for_rule(rule_key: str) -> str:
    base = rule_key.split(":", 1)[0]
    return RULE_LABELS.get(base, base.replace("_", " ").title())


def _evidence_items(evidence: dict) -> list[dict]:
    """Flatten JSON evidence into readable rows without exposing free text."""
    items = []
    for key, value in (evidence or {}).items():
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str)
        elif isinstance(value, bool):
            value = "yes" if value else "no"
        items.append(
            {
                "label": key.replace("_", " ").capitalize(),
                "value": value,
            }
        )
    return items


class AlertQueueView(RoleRequiredMixin, TemplateView):
    """The mentor's working queue for the children assigned to them."""

    template_name = "alerts/queue.html"
    allowed_roles = (Role.MENTOR,)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        status_key = self.request.GET.get("status", "open")
        tier_key = self.request.GET.get("tier", "")
        if status_key not in STATUS_FILTERS:
            status_key = "open"
        if tier_key not in TIER_ORDER:
            tier_key = ""

        visible = permissions.visible_children(user)
        base = Alert.objects.filter(child__in=visible).select_related(
            "child", "assigned_to"
        )
        queryset = base.filter(status__in=STATUS_FILTERS[status_key])
        if tier_key:
            queryset = queryset.filter(tier=tier_key)

        counts = {
            row["tier"]: row["n"]
            for row in base.filter(
                status__in=STATUS_FILTERS["open"]
            )
            .values("tier")
            .annotate(n=Count("id"))
        }
        context.update(
            {
                "alerts": queryset.order_by("tier", "-opened_on", "-pk"),
                "counts": {
                    "watch": counts.get(Alert.Tier.WATCH, 0),
                    "concern": counts.get(Alert.Tier.CONCERN, 0),
                    "urgent": counts.get(Alert.Tier.URGENT, 0),
                    "total": sum(counts.values()),
                },
                "status_key": status_key,
                "tier_key": tier_key,
                "status_filters": [
                    ("open", "Open"),
                    ("resolved", "Resolved"),
                    ("dismissed", "Dismissed"),
                    ("all", "All"),
                ],
                "tier_filters": [
                    ("", "All tiers"),
                    (Alert.Tier.URGENT, "Urgent"),
                    (Alert.Tier.CONCERN, "Concern"),
                    (Alert.Tier.WATCH, "Watch"),
                ],
                "as_of": timezone.localdate(),
            }
        )
        return context


class AlertDetailView(LoginRequiredMixin, View):
    """One alert and its append-only case timeline.

    The page is only for a person with READ on the alert *and* a relationship to
    the child. A guardian (SUMMARY) and an administrator (AGGREGATE) are both
    below READ, so neither can reach it.
    """

    template_name = "alerts/detail.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.alert = get_object_or_404(
            Alert.objects.select_related("child", "assigned_to"), pk=kwargs["pk"]
        )
        permissions.require_access(
            request, self.alert.child, Resource.ALERT, Access.READ
        )
        self.can_manage = permissions.has_access(
            request.user, self.alert.child, Resource.ALERT, Access.WRITE
        )
        self.can_note = permissions.has_access(
            request.user, self.alert.child, Resource.CASE_NOTE, Access.READ
        )
        return super().dispatch(request, *args, **kwargs)

    def _context(self):
        return {
            "alert": self.alert,
            "events": self.alert.events.select_related("actor"),
            "evidence_items": _evidence_items(self.alert.evidence),
            "rule_label": _label_for_rule(self.alert.rule_key),
            "can_manage": self.can_manage,
            "can_note": self.can_note,
            "queue_url": reverse("alerts:queue"),
            "child_url": reverse("children:detail", args=[self.alert.child_id]),
            "history_url": reverse(
                "feedback:pulse_history", args=[self.alert.child_id]
            ),
            "is_urgent": self.alert.is_urgent,
            "can_share": (
                self.can_manage
                and not self.alert.is_urgent
                and self.alert.status != Alert.Status.DISMISSED
                and self.alert.guardian_shared_at is None
            ),
        }

    def get(self, request, *args, **kwargs):
        record_request(
            request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.ALERT,
            child=self.alert.child,
            resource_id=str(self.alert.pk),
            metadata={"tier": self.alert.tier, "status": self.alert.status},
        )
        return render(request, self.template_name, self._context())

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "")
        alert = self.alert

        try:
            if action == "acknowledge":
                permissions.require_access(
                    request, alert.child, Resource.ALERT, Access.WRITE
                )
                services.acknowledge(alert, request.user)
                audit_action = AuditLog.Action.ALERT_ACK
                message = "Alert acknowledged."
            elif action == "note":
                permissions.require_access(
                    request, alert.child, Resource.CASE_NOTE, Access.WRITE
                )
                services.add_note(alert, request.user, request.POST.get("body", ""))
                audit_action = AuditLog.Action.ALERT_NOTE
                message = "Case note added."
            elif action == "resolve":
                permissions.require_access(
                    request, alert.child, Resource.ALERT, Access.WRITE
                )
                services.resolve(alert, request.user, request.POST.get("body", ""))
                audit_action = AuditLog.Action.ALERT_RESOLVE
                message = "Alert resolved."
            elif action == "dismiss":
                permissions.require_access(
                    request, alert.child, Resource.ALERT, Access.WRITE
                )
                services.dismiss(alert, request.user, request.POST.get("body", ""))
                audit_action = AuditLog.Action.ALERT_DISMISS
                message = "Alert dismissed with a recorded reason."
            elif action == "share":
                permissions.require_access(
                    request, alert.child, Resource.ALERT, Access.WRITE
                )
                services.share_with_guardian(alert, request.user)
                audit_action = AuditLog.Action.ALERT_SHARE
                message = "Alert shared with the child's guardian."
            else:
                messages.error(request, "Unknown action.")
                return redirect("alerts:detail", pk=alert.pk)
        except services.AlertStateError as exc:
            messages.error(request, str(exc))
            return redirect("alerts:detail", pk=alert.pk)

        record_request(
            request,
            action=audit_action,
            resource_type=Resource.ALERT,
            child=alert.child,
            resource_id=str(alert.pk),
            metadata={"tier": alert.tier},
        )
        messages.success(request, message)
        return redirect("alerts:detail", pk=alert.pk)


class GuardianAlertListView(LoginRequiredMixin, TemplateView):
    """What a guardian is allowed to know: shared, non-urgent alerts only."""

    template_name = "alerts/family.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role != Role.PARENT:
            raise PermissionDenied("Family updates are for guardian accounts.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        children = permissions.visible_children(user)

        shared = (
            Alert.objects.filter(
                child__in=children,
                guardian_shared_at__isnull=False,
                tier__in=[Alert.Tier.WATCH, Alert.Tier.CONCERN],
            )
            .exclude(status=Alert.Status.DISMISSED)
            .select_related("child")
            .order_by("-guardian_shared_at")
        )

        due = children_due_for(user) if user.is_authenticated else []
        answered = PulseResponse.objects.filter(
            guardian=user, week_start=current_week_start(), child__in=children
        ).count()

        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.ALERT,
            metadata={"shared_alerts": shared.count(), "scope": "family"},
        )
        context.update(
            {
                "alerts": shared,
                "children_due": due,
                "pulse_answered": answered,
                "week_start": current_week_start(),
                "as_of": timezone.localdate(),
            }
        )
        return context


class CohortAlertView(LoginRequiredMixin, TemplateView):
    """Institution-wide alert counts. No child names, no case notes."""

    template_name = "alerts/cohort.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            granted = permissions.access_for_institution(
                request.user, Resource.ALERT
            )
            if granted < Access.AGGREGATE:
                record_request(
                    request,
                    action=AuditLog.Action.DENY,
                    resource_type=Resource.ALERT,
                    metadata={
                        "required": Access.AGGREGATE.name,
                        "granted": Access(granted).name,
                        "scope": "institution",
                    },
                )
                raise PermissionDenied(
                    "Aggregate alert data is not available to your account."
                )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        open_alerts = Alert.objects.filter(
            status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED]
        )
        by_tier = {
            row["tier"]: row["n"]
            for row in open_alerts.values("tier").annotate(n=Count("id"))
        }
        since = today - timedelta(days=28)
        recent = Alert.objects.filter(opened_on__gte=since)

        context.update(
            {
                "by_tier": {
                    "watch": by_tier.get(Alert.Tier.WATCH, 0),
                    "concern": by_tier.get(Alert.Tier.CONCERN, 0),
                    "urgent": by_tier.get(Alert.Tier.URGENT, 0),
                    "total": sum(by_tier.values()),
                },
                "opened_recent": recent.count(),
                "resolved_recent": recent.filter(
                    status=Alert.Status.RESOLVED
                ).count(),
                "dismissed_recent": recent.filter(
                    status=Alert.Status.DISMISSED
                ).count(),
                "unassigned": open_alerts.filter(assigned_to__isnull=True).count(),
                "safeguarding_open": open_alerts.filter(
                    rule_key__startswith="safeguarding_signal"
                ).count(),
                "shared_total": Alert.objects.filter(
                    guardian_shared_at__isnull=False
                ).count(),
                "as_of": today,
                "window_days": 28,
            }
        )
        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.ALERT,
            metadata={"scope": "institution"},
        )
        return context

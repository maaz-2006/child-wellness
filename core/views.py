"""Core views: routing by role, the dashboard shell, health check, and the
generated permission matrix."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib.auth.forms import AuthenticationForm
from django.db import connection
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from . import permissions
from .audit import record_request
from .mixins import RoleRequiredMixin
from .models import AuditLog, Role, School, User
from .permissions import Access, RELATION_LABELS, RESOURCE_LABELS


class AuditedLoginView(auth_views.LoginView):
    """Standard login, plus an audit row for both success and failure.

    Failed sign-ins matter here: repeated failures against a child account are
    worth seeing.
    """

    template_name = "core/login.html"
    redirect_authenticated_user = True
    authentication_form = AuthenticationForm

    def form_valid(self, form):
        response = super().form_valid(form)
        record_request(
            self.request,
            action=AuditLog.Action.LOGIN,
            resource_type="session",
            metadata={"role": self.request.user.role},
        )
        return response

    def form_invalid(self, form):
        record_request(
            self.request,
            action=AuditLog.Action.LOGIN_FAILED,
            resource_type="session",
            metadata={"username": form.data.get("username", "")[:64]},
        )
        return super().form_invalid(form)


class AuditedLogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("core:login")


def home(request):
    """Entry point: send people where they belong."""
    if not request.user.is_authenticated:
        return redirect("core:login")
    return redirect("core:dashboard")


class DashboardView(TemplateView):
    """One route, four shapes.

    The template branches per role rather than us maintaining four URLs, but the
    data each role receives is filtered by the permission gate, not by template
    conditionals.
    """

    template_name = "core/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("core:login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context["children_visible"] = permissions.visible_children(user)
        context["school"] = School.load()

        if user.role == Role.ADMIN:
            context["stats"] = {
                "children": context["children_visible"].count(),
                "mentors": User.objects.filter(role=Role.MENTOR, is_active=True).count(),
                "parents": User.objects.filter(role=Role.PARENT, is_active=True).count(),
            }
            context["alert_counts"] = _cohort_alert_counts()
        elif user.role == Role.MENTOR:
            from alerts.models import Alert

            visible = context["children_visible"]
            open_alerts = Alert.objects.filter(
                child__in=visible,
                status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED],
            )
            by_tier = {
                row["tier"]: row["n"]
                for row in open_alerts.values("tier").annotate(n=Count("id"))
            }
            context["alert_counts"] = {
                "total": sum(by_tier.values()),
                "urgent": by_tier.get(Alert.Tier.URGENT, 0),
                "concern": by_tier.get(Alert.Tier.CONCERN, 0),
                "watch": by_tier.get(Alert.Tier.WATCH, 0),
            }
            context["message_counts"] = _message_counts(user)
        elif user.role == Role.PARENT:
            from alerts.models import Alert
            from feedback.services import children_due_for

            shared = Alert.objects.filter(
                child__in=context["children_visible"],
                guardian_shared_at__isnull=False,
            ).exclude(status=Alert.Status.DISMISSED)
            context["alert_counts"] = {"shared": shared.count()}
            context["pulse_due"] = children_due_for(user)
            context["message_counts"] = _message_counts(user)
        return context


def _message_counts(user) -> dict:
    """Conversation and unread counts for the two adult roles that can message."""
    from messaging import services

    threads = list(services.threads_for(user))
    return {
        "threads": len(threads),
        "unread": sum(services.unread_count(user, thread) for thread in threads),
    }


def _cohort_alert_counts() -> dict:
    """Small aggregate helper for the administrator dashboard."""
    from alerts.models import Alert

    open_alerts = Alert.objects.filter(
        status__in=[Alert.Status.OPEN, Alert.Status.ACKNOWLEDGED]
    )
    by_tier = {
        row["tier"]: row["n"]
        for row in open_alerts.values("tier").annotate(n=Count("id"))
    }
    return {
        "total": sum(by_tier.values()),
        "urgent": by_tier.get(Alert.Tier.URGENT, 0),
        "concern": by_tier.get(Alert.Tier.CONCERN, 0),
        "watch": by_tier.get(Alert.Tier.WATCH, 0),
    }


class PermissionMatrixView(RoleRequiredMixin, TemplateView):
    """Renders the matrix from core.permissions.MATRIX.

    This page exists so the documentation cannot lie: what you see is the data
    structure the gate actually enforces.
    """

    template_name = "core/permission_matrix.html"
    allowed_roles = (Role.ADMIN,)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        resource_keys = sorted(RESOURCE_LABELS)
        table = []
        for (role, relation), grants in permissions.MATRIX.items():
            table.append(
                {
                    "role": str(Role(role).label),
                    "relation": RELATION_LABELS.get(relation, relation),
                    "cells": [
                        {
                            "resource": key,
                            "access": Access(grants.get(key, Access.NONE)).name.lower(),
                        }
                        for key in resource_keys
                    ],
                }
            )

        context["matrix_table"] = table
        context["resource_headers"] = [
            {"key": key, "label": RESOURCE_LABELS[key]} for key in resource_keys
        ]
        context["access_levels"] = [a.name for a in Access]
        context["row_count"] = sum(len(row["cells"]) for row in table)
        return context


def healthz(request):
    """Liveness probe. Used by an uptime pinger so the free-tier app stays warm."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_ok = True
    except Exception:  # pragma: no cover
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse(
        {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "unavailable",
            "debug": settings.DEBUG,
        },
        status=status,
    )


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)

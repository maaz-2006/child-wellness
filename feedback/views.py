"""Guardian pulse screens.

The pulse is a guardian's own channel, not a staff form. The view therefore
resolves the child from the URL and then asks the permission gate whether *this*
guardian may give feedback about *this* child; it never branches on role alone.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from children.models import Child
from core import permissions
from core.audit import record_request
from core.mixins import ChildScopedMixin
from core.models import AuditLog, Role
from core.permissions import Access, Resource

from . import services
from .forms import PulseForm
from .models import PulseResponse, current_week_start


class PulseCreateView(LoginRequiredMixin, View):
    """One guardian's weekly view of one child."""

    template_name = "feedback/pulse_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if request.user.role != Role.PARENT:
            raise PermissionDenied("The weekly pulse is for guardian accounts.")
        self.child = get_object_or_404(Child, pk=kwargs.get("child_id"))
        permissions.require_access(
            request, self.child, Resource.FEEDBACK, Access.WRITE
        )
        self.week_start = current_week_start()
        self.existing = services.pulse_for(
            request.user, self.child, self.week_start
        )
        return super().dispatch(request, *args, **kwargs)

    def _context(self, form):
        return {
            "form": form,
            "child": self.child,
            "week_start": self.week_start,
            "editing": self.existing is not None,
            "history_url": reverse(
                "feedback:pulse_history", args=[self.child.pk]
            ),
            "back_url": reverse("core:dashboard"),
        }

    def get(self, request, *args, **kwargs):
        form = PulseForm(instance=self.existing)
        return render(request, self.template_name, self._context(form))

    def post(self, request, *args, **kwargs):
        form = PulseForm(request.POST, instance=self.existing)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        response = form.save(commit=False)
        response.child = self.child
        response.guardian = request.user
        response.week_start = self.week_start
        action = (
            AuditLog.Action.UPDATE
            if self.existing is not None
            else AuditLog.Action.CREATE
        )
        response.save()

        record_request(
            request,
            action=action,
            resource_type=Resource.FEEDBACK,
            child=self.child,
            resource_id=str(response.pk),
            metadata={"week_start": str(self.week_start)},
        )
        messages.success(
            request,
            "Thank you. Your weekly pulse is saved, and your child's mentor can "
            "see it.",
        )
        return redirect("core:dashboard")


class PulseHistoryView(ChildScopedMixin, TemplateView):
    """The last few pulse responses for one child.

    A mentor sees this because it is the guardian's account of what is happening
    at home, which is exactly the context a school-based observation lacks. The
    administrator does not: the matrix grants AGGREGATE on feedback, and this page
    is one named child.
    """

    template_name = "feedback/pulse_history.html"
    resource = Resource.FEEDBACK
    required_access = Access.READ

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rows = services.history_for(self.child)
        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.FEEDBACK,
            child=self.child,
            metadata={"rows": len(rows)},
        )
        context.update(
            {
                "rows": rows,
                "this_week": current_week_start(),
                "back_url": reverse("children:detail", args=[self.child.pk]),
                "can_submit": (
                    self.request.user.role == Role.PARENT
                    and permissions.has_access(
                        self.request.user,
                        self.child,
                        Resource.FEEDBACK,
                        Access.WRITE,
                    )
                ),
            }
        )
        return context


class PulseCohortView(LoginRequiredMixin, TemplateView):
    """Aggregate pulse participation for the institution. No names, no comments."""

    template_name = "feedback/cohort.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            granted = permissions.access_for_institution(
                request.user, Resource.FEEDBACK
            )
            if granted < Access.AGGREGATE:
                record_request(
                    request,
                    action=AuditLog.Action.DENY,
                    resource_type=Resource.FEEDBACK,
                    metadata={
                        "required": Access.AGGREGATE.name,
                        "granted": Access(granted).name,
                        "scope": "institution",
                    },
                )
                raise PermissionDenied(
                    "Aggregate pulse data is not available to your account."
                )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        snapshot = services.cohort_snapshot()
        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.FEEDBACK,
            metadata={"scope": "institution"},
        )
        context.update({"snapshot": snapshot, "as_of": timezone.localdate()})
        return context

"""Reusable view mixins that enforce the permission gate."""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from . import permissions
from .permissions import Access


class RoleRequiredMixin(LoginRequiredMixin):
    """Restrict a view to one or more roles. Denies, never redirects, because a
    redirect would leak the existence of the page."""

    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if self.allowed_roles and request.user.role not in self.allowed_roles:
            raise PermissionDenied("This area is not available to your account.")
        return super().dispatch(request, *args, **kwargs)


class ChildScopedMixin(LoginRequiredMixin):
    """Resolve `child` from the URL and enforce access before the view body runs.

    Subclasses declare `resource` and `required_access`. The check happens in
    dispatch, so no view body can accidentally query before authorisation.
    """

    resource: str = permissions.Resource.PROFILE
    required_access: Access = Access.READ
    child_kwarg: str = "child_id"

    child = None

    def dispatch(self, request, *args, **kwargs):
        from children.models import Child

        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        self.child = get_object_or_404(Child, pk=kwargs.get(self.child_kwarg))
        permissions.require_access(request, self.child, self.resource, self.required_access)
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("child", self.child)
        return context

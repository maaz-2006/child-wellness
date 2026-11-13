"""Child detail page: the single place that answers "how is this child doing?".

The page is assembled from the permission gate, not from role conditionals in
the template. For each module the view asks two questions:

    mode_for()    - how much of this domain may this person see?
    stats_for()   - what descriptive figures are appropriate at that level?

so an administrator lands on the same URL as a mentor and gets a structurally
different page: identity and counts, no emotional content, no case notes.
"""

from __future__ import annotations

from django.urls import reverse
from django.views.generic import TemplateView

from core import permissions
from core.audit import record_request
from core.mixins import ChildScopedMixin
from core.models import AuditLog, Role
from core.permissions import Access, Resource
from domains import access
from domains.registry import DOMAINS

from .models import Guardianship, Mentorship


class ChildDetailView(ChildScopedMixin, TemplateView):
    template_name = "children/detail.html"
    resource = Resource.PROFILE
    required_access = Access.READ

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        child = self.child

        sections = []
        for module in DOMAINS:
            mode = access.mode_for(user, child, module)
            can_open = mode in {"full", "shared", "summary"}
            sections.append(
                {
                    "module": module,
                    "mode": mode,
                    "mode_label": access.MODE_LABELS[mode],
                    "can_open": can_open,
                    "can_add": module.form_class is not None
                    and permissions.has_access(
                        user, child, module.resource, Access.WRITE
                    ),
                    "url": reverse("domains:list", args=[child.pk, module.key]),
                    "add_url": reverse(
                        "domains:entry_create", args=[child.pk, module.key]
                    ),
                    "stats": (
                        access.summarise(
                            module.model.objects.filter(child=child), module
                        )
                        if can_open
                        else []
                    ),
                    "count": module.model.objects.filter(child=child).count(),
                }
            )

        can_observe = permissions.has_access(
            user, child, Resource.EMOTIONAL_OBSERVATION, Access.WRITE
        )
        is_self = user.role == Role.CHILD and getattr(user, "child_profile", None) == child

        # Guardians and mentors are shown to staff as part of the care picture.
        # A child sees neither: who is assigned to them is an administrative
        # fact, not something to surface in a child's own space.
        staff_view = user.role in {Role.MENTOR, Role.ADMIN}
        guardianships = (
            child.active_guardianships if staff_view else Guardianship.objects.none()
        )
        mentorships = (
            child.active_mentorships if staff_view else Mentorship.objects.none()
        )

        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.PROFILE,
            child=child,
        )

        context.update(
            {
                "sections": sections,
                "can_observe": can_observe,
                "is_self": is_self,
                "has_consent": child.has_consent,
                "show_care_team": staff_view,
                "guardianships": guardianships,
                "mentorships": mentorships,
                "observe_url": reverse("domains:emotional_observe", args=[child.pk]),
                "checkin_url": reverse("domains:checkin"),
                "can_checkin": is_self and child.has_consent,
            }
        )
        return context

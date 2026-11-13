"""Views for the four wellness modules.

Two rules govern everything below:

1. The page-level check is `ChildScopedMixin` (does this user have any access to
   this resource for this child). It runs in `dispatch`, before any query.
2. The row-level check is `domains.access.entries_for` (which *rows* may they
   see). Views never query the models directly for display.

The child's check-in page is the one view that is not child-scoped by URL: the
child is resolved from their own session, so there is no id to tamper with.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView, View

from core import permissions
from core.audit import record_request
from core.mixins import ChildScopedMixin
from core.models import AuditLog, Role
from core.permissions import Access, Resource

from . import access
from .forms import EmotionalCheckinForm, EmotionalObservationForm
from .models import EmotionalCheckin, Source
from .registry import DOMAINS, DOMAINS_BY_KEY

#: Which kind of person made this entry. Derived from the role, never chosen by
#: the user: a mentor must not be able to file a record as a parent's observation.
SOURCE_BY_ROLE = {
    Role.CHILD: Source.CHILD,
    Role.PARENT: Source.PARENT,
    Role.MENTOR: Source.MENTOR,
}


def _module_or_404(key: str):
    module = DOMAINS_BY_KEY.get(key)
    if module is None:
        raise Http404("Unknown wellness domain.")
    return module


def _stats_for(user, child, module, mode) -> list[dict]:
    """Descriptive figures for a domain card.

    AGGREGATE deliberately gets a count only. An average mark for one named
    child is not an aggregate, and treating it as one is how "admins can't see
    individual wellness" quietly stops being true.
    """
    if mode in {"summary", "shared", "full"}:
        return access.summarise(module.model.objects.filter(child=child), module)
    if mode == "aggregate":
        return [
            {
                "label": f"{module.entry_noun_plural.title()} on file",
                "value": module.model.objects.filter(child=child).count(),
            }
        ]
    return []


class DomainListView(ChildScopedMixin, TemplateView):
    """One view for all four modules, driven by `domains.registry`.

    Adding a fifth domain means adding a registry entry and a row template.
    """

    template_name = "domains/domain_list.html"
    required_access = Access.SUMMARY
    paginate_by = 25

    module = None

    def dispatch(self, request, *args, **kwargs):
        self.module = _module_or_404(kwargs.get("domain_key"))
        # ChildScopedMixin reads self.resource in its dispatch, which runs next.
        self.resource = self.module.resource
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        mode = access.mode_for(user, self.child, self.module)
        queryset = access.entries_for(user, self.child, self.module)

        paginator = Paginator(queryset, self.paginate_by)
        page = paginator.get_page(self.request.GET.get("page"))
        rows = access.rows_for(user, page.object_list)

        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=self.module.resource,
            child=self.child,
            metadata={"mode": mode, "rows": len(rows)},
        )

        context.update(
            {
                "module": self.module,
                "modules": DOMAINS,
                "mode": mode,
                "mode_label": access.MODE_LABELS[mode],
                "rows": rows,
                "page_obj": page,
                "total": queryset.count(),
                "can_observe": permissions.has_access(
                    user, self.child, Resource.EMOTIONAL_OBSERVATION, Access.WRITE
                ),
                "can_checkin": (
                    user.role == Role.CHILD and self.module.key == "emotional"
                ),
                "can_add": self.module.form_class is not None
                and permissions.has_access(
                    user, self.child, self.module.resource, Access.WRITE
                ),
                "add_url": reverse(
                    "domains:entry_create", args=[self.child.pk, self.module.key]
                ),
                "observe_url": reverse(
                    "domains:emotional_observe", args=[self.child.pk]
                ),
                "back_url": reverse("children:detail", args=[self.child.pk]),
                "stats": _stats_for(user, self.child, self.module, mode),
            }
        )
        return context


class DomainEntryCreateView(ChildScopedMixin, View):
    """Add a record to academic, social or habits.

    One view for three domains, driven by the registry's `form_class`. Adding a
    fourth measurable domain means adding a model, a form and a registry entry;
    it does not mean another view with its own copy of the permission check.

    Two safeguards live here rather than in the forms:

    * `source` comes from the role, never from the submitted data.
    * For one-per-day domains, re-submitting updates *your own* row for that
      day. If someone else already logged it, you are told so and nothing is
      overwritten - otherwise a guardian could silently replace a mentor's
      record of the school day.
    """

    template_name = "domains/entry_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.module = _module_or_404(kwargs.get("domain_key"))
        if self.module.form_class is None:
            raise Http404("This domain has its own entry page.")
        self.resource = self.module.resource
        self.required_access = Access.WRITE
        return super().dispatch(request, *args, **kwargs)

    # -- helpers ---------------------------------------------------------
    def _source(self) -> str:
        return SOURCE_BY_ROLE[self.request.user.role]

    def _audience(self) -> str:
        return "child" if self.request.user.role == Role.CHILD else "adult"

    def _form(self, data=None, instance=None):
        return self.module.form_class(
            data, instance=instance, audience=self._audience()
        )

    def _own_row_for_today(self):
        if not self.module.one_per_day:
            return None
        return self.module.model.objects.filter(
            child=self.child,
            occurred_on=timezone.localdate(),
            source=self._source(),
            recorded_by=self.request.user,
        ).first()

    def _context(self, form):
        return {
            "form": form,
            "module": self.module,
            "child": self.child,
            "back_url": reverse(
                "domains:list", args=[self.child.pk, self.module.key]
            ),
        }

    # -- http ------------------------------------------------------------
    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            self._context(self._form(instance=self._own_row_for_today())),
        )

    def post(self, request, *args, **kwargs):
        form = self._form(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        entry = form.save(commit=False)
        entry.child = self.child
        entry.source = self._source()
        entry.recorded_by = request.user
        action = AuditLog.Action.CREATE

        if self.module.one_per_day:
            existing = self.module.model.objects.filter(
                child=self.child,
                occurred_on=entry.occurred_on,
                source=entry.source,
            ).first()
            if existing is not None:
                if existing.recorded_by_id != request.user.pk:
                    who = (
                        existing.recorded_by.display_name
                        if existing.recorded_by_id
                        else "Someone else"
                    )
                    form.add_error(
                        None,
                        f"{who} already logged this day. Add your own note on "
                        "another day, or ask them to update the entry.",
                    )
                    return render(request, self.template_name, self._context(form))
                # Re-bind the form to the stored row rather than assigning a pk
                # to a fresh instance: the second carries no created_at, and an
                # UPDATE would try to write NULL into it.
                form = self._form(request.POST, instance=existing)
                if not form.is_valid():
                    return render(request, self.template_name, self._context(form))
                entry = form.save(commit=False)
                entry.child = self.child
                entry.source = self._source()
                entry.recorded_by = request.user
                action = AuditLog.Action.UPDATE

        entry.save()

        record_request(
            request,
            action=action,
            resource_type=self.module.resource,
            child=self.child,
            resource_id=str(entry.pk),
        )
        messages.success(request, f"{self.module.entry_noun.capitalize()} saved.")
        return redirect("domains:list", self.child.pk, self.module.key)


class EmotionalObservationCreateView(ChildScopedMixin, View):
    """An adult records what they observed.

    Mentors and guardians both land here; `source` is derived from the role so
    the data always records what kind of person made the observation, not just
    who.
    """

    resource = Resource.EMOTIONAL_OBSERVATION
    required_access = Access.WRITE

    template_name = "domains/observe.html"

    def _source(self) -> str:
        return (
            Source.PARENT if self.request.user.role == Role.PARENT else Source.MENTOR
        )

    def _form(self, data=None):
        return EmotionalObservationForm(
            data,
            child=self.child,
            author=self.request.user,
            source=self._source(),
        )

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {
                "form": self._form(),
                "child": self.child,
                "back_url": reverse("domains:list", args=[self.child.pk, "emotional"]),
            },
        )

    def post(self, request, *args, **kwargs):
        form = self._form(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "child": self.child,
                    "back_url": reverse(
                        "domains:list", args=[self.child.pk, "emotional"]
                    ),
                },
            )

        entry = form.save(commit=False)
        existing = EmotionalCheckin.objects.filter(
            child=self.child,
            occurred_on=entry.occurred_on,
            source=self._source(),
            recorded_by=request.user,
        ).first()

        entry.child = self.child
        entry.source = self._source()
        entry.recorded_by = request.user
        if existing is not None:
            # Editing your own observation for the same day, not creating a
            # second one. The unique constraint would reject the latter anyway.
            entry.pk = existing.pk
            action = AuditLog.Action.UPDATE
            note = "Observation updated."
        else:
            action = AuditLog.Action.CREATE
            note = "Observation recorded."

        entry.save()

        record_request(
            request,
            action=action,
            resource_type=Resource.EMOTIONAL_OBSERVATION,
            child=self.child,
            resource_id=str(entry.pk),
        )
        messages.success(request, note)
        return redirect("domains:list", self.child.pk, "emotional")


class ChildCheckinView(LoginRequiredMixin, View):
    """The child's own daily check-in.

    The date is always today: a child should not be able to back-date a mood,
    and the unique constraint means a second submission edits today's entry
    rather than creating a contradictory one.
    """

    template_name = "domains/checkin.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        if request.user.role != Role.CHILD:
            raise PermissionDenied("This page is for child accounts.")

        child = getattr(request.user, "child_profile", None)
        if child is None:
            raise PermissionDenied("This account is not linked to a child profile.")

        permissions.require_access(
            request, child, Resource.EMOTIONAL, Access.WRITE
        )
        self.child = child
        return super().dispatch(request, *args, **kwargs)

    def _today_entry(self):
        return EmotionalCheckin.objects.filter(
            child=self.child,
            occurred_on=timezone.localdate(),
            source=Source.CHILD,
        ).first()

    def _context(self, form, *, blocked=False):
        return {
            "form": form,
            "child": self.child,
            "blocked": blocked,
            "today": timezone.localdate(),
            "editing": form.instance.pk is not None,
            "dashboard_url": reverse("core:dashboard"),
            "emotional_url": reverse("domains:list", args=[self.child.pk, "emotional"]),
        }

    def get(self, request, *args, **kwargs):
        # No guardian consent means the platform should not be inviting this
        # child to confide in it. That is a gate, not a nag screen.
        if not self.child.has_consent:
            return render(
                request, self.template_name, self._context(EmotionalCheckinForm(), blocked=True)
            )
        form = EmotionalCheckinForm(instance=self._today_entry())
        return render(request, self.template_name, self._context(form))

    def post(self, request, *args, **kwargs):
        if not self.child.has_consent:
            return render(
                request, self.template_name, self._context(EmotionalCheckinForm(), blocked=True)
            )

        form = EmotionalCheckinForm(request.POST, instance=self._today_entry())
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        entry = form.save(commit=False)
        entry.child = self.child
        entry.recorded_by = request.user
        entry.source = Source.CHILD
        entry.occurred_on = timezone.localdate()
        action = (
            AuditLog.Action.UPDATE if entry.pk is not None else AuditLog.Action.CREATE
        )
        entry.save()

        record_request(
            request,
            action=action,
            resource_type=Resource.EMOTIONAL,
            child=self.child,
            resource_id=str(entry.pk),
        )
        messages.success(
            request,
            "Thanks for checking in. You can change today's answers any time.",
        )
        return redirect("domains:checkin")

"""Messaging screens for the adults around a child.

Two roles, one shared inbox shape:

* a **mentor** sees conversations about the children currently assigned to them;
* a **guardian** sees conversations about their own children, and only while
  consent is on file.

Both are row-filtered through `messaging.services`, which asks the permission
gate per child. The child and the administrator are refused before any thread is
loaded: `Resource.MESSAGE` is NONE for both in the matrix.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import TemplateView, View

from children.models import Child
from core import permissions
from core.audit import record_request
from core.mixins import RoleRequiredMixin
from core.models import AuditLog, Role
from core.permissions import Access, Resource

from . import services
from .forms import MessageForm, ThreadForm
from .models import Message, Thread


class ThreadListView(RoleRequiredMixin, TemplateView):
    """The adult's inbox: one row per conversation, with unread count."""

    template_name = "messaging/thread_list.html"
    allowed_roles = (Role.PARENT, Role.MENTOR)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        threads = services.threads_for(user).prefetch_related(
            Prefetch(
                "messages",
                queryset=Message.objects.select_related("author").order_by(
                    "-created_at", "-pk"
                ),
                to_attr="recent_messages",
            )
        )

        rows = []
        for thread in threads:
            last = thread.recent_messages[0] if thread.recent_messages else None
            rows.append(
                {
                    "thread": thread,
                    "last": last,
                    "unread": services.unread_count(user, thread),
                }
            )

        children = services.permitted_children(user)
        record_request(
            self.request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.MESSAGE,
            metadata={"scope": "inbox", "threads": len(rows)},
        )
        context.update(
            {
                "rows": rows,
                "children": children,
                "unread_total": sum(row["unread"] for row in rows),
                "new_thread_urls": [
                    {
                        "child": child,
                        "url": reverse(
                            "messaging:new_thread", args=[child.pk]
                        ),
                    }
                    for child in children
                ],
            }
        )
        return context


class ThreadCreateView(LoginRequiredMixin, View):
    """Start a conversation about one child."""

    template_name = "messaging/thread_form.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.child = get_object_or_404(Child, pk=kwargs.get("child_id"))
        permissions.require_access(
            request, self.child, Resource.MESSAGE, Access.WRITE
        )
        return super().dispatch(request, *args, **kwargs)

    def _context(self, form):
        return {
            "form": form,
            "child": self.child,
            "inbox_url": reverse("messaging:inbox"),
            "child_url": reverse("children:detail", args=[self.child.pk]),
        }

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self._context(ThreadForm()))

    def post(self, request, *args, **kwargs):
        form = ThreadForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        try:
            thread = services.start_thread(
                self.child,
                request.user,
                form.cleaned_data["subject"],
                form.cleaned_data["body"],
            )
        except services.MessageError as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name, self._context(form))

        record_request(
            request,
            action=AuditLog.Action.CREATE,
            resource_type=Resource.MESSAGE,
            child=self.child,
            resource_id=str(thread.pk),
            metadata={"subject": thread.subject},
        )
        messages.success(request, "Conversation started.")
        return redirect("messaging:thread", pk=thread.pk)


class ThreadDetailView(LoginRequiredMixin, View):
    """Read one conversation and append a reply.

    The thread is loaded by primary key, but the gate is the *child*: a thread
    id guessed by an unrelated adult resolves to a 403, and the denial is
    audited because `MESSAGE` is in `AUDITED_RESOURCES`.
    """

    template_name = "messaging/thread_detail.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.thread = get_object_or_404(
            Thread.objects.select_related("child", "created_by"), pk=kwargs["pk"]
        )
        permissions.require_access(
            request, self.thread.child, Resource.MESSAGE, Access.READ
        )
        self.can_write = (
            not self.thread.is_closed
            and permissions.has_access(
                request.user, self.thread.child, Resource.MESSAGE, Access.WRITE
            )
        )
        self.can_close = (
            request.user.role == Role.MENTOR
            and permissions.has_access(
                request.user, self.thread.child, Resource.MESSAGE, Access.WRITE
            )
        )
        return super().dispatch(request, *args, **kwargs)

    def _context(self, form):
        return {
            "thread": self.thread,
            "child": self.thread.child,
            "messages_list": self.thread.messages.select_related("author"),
            "form": form,
            "can_write": self.can_write,
            "can_close": self.can_close,
            "inbox_url": reverse("messaging:inbox"),
            "child_url": reverse("children:detail", args=[self.thread.child_id]),
        }

    def get(self, request, *args, **kwargs):
        services.mark_read(self.thread, request.user)
        record_request(
            request,
            action=AuditLog.Action.VIEW,
            resource_type=Resource.MESSAGE,
            child=self.thread.child,
            resource_id=str(self.thread.pk),
        )
        return render(
            request, self.template_name, self._context(MessageForm())
        )

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action", "reply")

        if action == "close":
            if not self.can_close:
                raise PermissionDenied("Only a mentor can close this conversation.")
            services.close_thread(self.thread, request.user)
            record_request(
                request,
                action=AuditLog.Action.UPDATE,
                resource_type=Resource.MESSAGE,
                child=self.thread.child,
                resource_id=str(self.thread.pk),
                metadata={"closed": True},
            )
            messages.success(request, "Conversation closed. Its history is kept.")
            return redirect("messaging:thread", pk=self.thread.pk)

        if not self.can_write:
            raise PermissionDenied("This conversation is closed.")

        form = MessageForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))

        try:
            message = services.post_message(
                self.thread, request.user, form.cleaned_data["body"]
            )
        except services.MessageError as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name, self._context(form))

        record_request(
            request,
            action=AuditLog.Action.CREATE,
            resource_type=Resource.MESSAGE,
            child=self.thread.child,
            resource_id=str(self.thread.pk),
            metadata={"message": str(message.pk)},
        )
        return redirect("messaging:thread", pk=self.thread.pk)

"""Messaging rules.

Views call these functions; they do not create `Message` rows themselves. That
keeps three invariants in one place:

* a message can only be written by an adult who currently has WRITE on the
  child - revoking consent or ending a mentorship closes the channel
  immediately, without deleting the history;
* a message is never empty and never over the length limit;
* a closed thread is readable but not writable.

Read markers are not authorization. They only decide whether the interface says
"1 new message"; the permission gate decides whether the thread exists for this
person at all.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.utils import timezone

from core import permissions
from core.models import Role
from core.permissions import Access, Resource

from .models import Message, Thread, ThreadRead

MAX_BODY = 4000


class MessageError(Exception):
    """The requested message operation is not valid."""


def _clean_body(body: str) -> str:
    body = (body or "").strip()
    if not body:
        raise MessageError("Write a message before sending it.")
    if len(body) > MAX_BODY:
        raise MessageError(f"A message must be {MAX_BODY} characters or fewer.")
    return body


def _require_write(actor, child) -> None:
    if not permissions.has_access(actor, child, Resource.MESSAGE, Access.WRITE):
        raise PermissionDenied("You cannot message about this child.")


def permitted_children(user):
    """Children whose message threads this adult may see.

    The matrix grants MESSAGE to parents and mentors only, but the check is
    still made per child: a mentor is assigned to some children, not all of
    them, and a guardian's consent can be withdrawn.
    """
    if not permissions.is_authenticated(user):
        return []
    if user.role not in {Role.PARENT, Role.MENTOR}:
        return []
    return [
        child
        for child in permissions.visible_children(user).select_related("school")
        if permissions.has_access(user, child, Resource.MESSAGE, Access.READ)
    ]


def threads_for(user):
    """Threads visible to this adult, newest activity first."""
    child_ids = [child.pk for child in permitted_children(user)]
    if not child_ids:
        return Thread.objects.none()
    return (
        Thread.objects.filter(child_id__in=child_ids)
        .select_related("child", "created_by")
        .order_by("-last_message_at", "-pk")
    )


def threads_for_child(child):
    """All threads about one child. The view must authorise the child first."""
    return (
        Thread.objects.filter(child=child)
        .select_related("created_by")
        .order_by("-last_message_at", "-pk")
    )


def unread_count(user, thread) -> int:
    """Messages not written by this adult since they last opened the thread."""
    rows = thread.messages.exclude(author=user)
    marker = ThreadRead.objects.filter(thread=thread, user=user).first()
    if marker is not None:
        rows = rows.filter(created_at__gt=marker.last_read_at)
    return rows.count()


def mark_read(thread, user) -> ThreadRead:
    marker, _created = ThreadRead.objects.update_or_create(
        thread=thread,
        user=user,
        defaults={"last_read_at": timezone.now()},
    )
    return marker


def start_thread(child, actor, subject: str, body: str) -> Thread:
    """Open a conversation and write the first message atomically enough for one user."""
    _require_write(actor, child)
    subject = (subject or "").strip()
    if not subject:
        raise MessageError("Give the conversation a subject.")
    if len(subject) > 160:
        raise MessageError("The subject must be 160 characters or fewer.")
    body = _clean_body(body)

    thread = Thread.objects.create(
        child=child,
        subject=subject,
        created_by=actor,
        last_message_at=timezone.now(),
    )
    Message.objects.create(thread=thread, author=actor, body=body)
    mark_read(thread, actor)
    return thread


def post_message(thread, actor, body: str) -> Message:
    """Append a message. Refuses closed threads and adults without access."""
    _require_write(actor, thread.child)
    if thread.is_closed:
        raise MessageError("This conversation is closed.")
    body = _clean_body(body)

    message = Message.objects.create(thread=thread, author=actor, body=body)
    thread.last_message_at = message.created_at
    thread.save(update_fields=["last_message_at"])
    mark_read(thread, actor)
    return message


def close_thread(thread, actor, is_closed: bool = True) -> Thread:
    """A mentor can close a conversation without deleting its history."""
    _require_write(actor, thread.child)
    if actor.role != Role.MENTOR:
        raise PermissionDenied("Only a mentor can close a conversation.")
    thread.is_closed = is_closed
    thread.save(update_fields=["is_closed"])
    return thread

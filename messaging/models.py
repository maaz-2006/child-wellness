"""Adult-to-adult messages about a child.

The boundary is the feature. This is a place for the adults who already share
responsibility for a child - a mentor and a guardian - to write to each other
without turning the platform into a social network. It is deliberately not a
channel between an adult and the child:

* `(CHILD, SELF)` has no access to `Resource.MESSAGE`; a child's conversations
  belong in the check-in and with people they can see, not in a private inbox
  managed by the school.
* The administrator has no access either. Messages about a family are not
  configuration data, and "the admin can read everything" is the privacy
  anti-pattern this project keeps rejecting.

Messages are append-only. A thread is a record of what two adults said to each
other; editing it after the fact would make it useless as a record. Deletion is
not offered in the application at all.

Read state is per adult (`ThreadRead`) rather than a boolean on the message,
because the same message can be unread for the guardian and already read by the
mentor. It is a convenience marker, never an access control.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone


class Thread(models.Model):
    """One conversation about one child, between the adults around them."""

    child = models.ForeignKey(
        "children.Child", on_delete=models.CASCADE, related_name="message_threads"
    )
    subject = models.CharField(max_length=160)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="message_threads_started",
    )
    is_closed = models.BooleanField(
        default=False,
        help_text="Closed threads stay readable but accept no new messages.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-last_message_at", "-pk"]
        indexes = [
            models.Index(fields=["child", "-last_message_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject} · {self.child.short_name}"


class Message(models.Model):
    """One message. Append-only, like a case timeline."""

    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE, related_name="messages"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="messages_written",
    )
    body = models.TextField(validators=[MaxLengthValidator(4000)])
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        who = self.author.display_name if self.author else "unknown author"
        return f"{who} on {self.thread_id}"

    def save(self, *args, **kwargs):
        """Refuse updates: a message that can be edited is not a record."""
        if self.pk is not None:
            raise ValueError("Message rows are append-only and cannot be edited.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Message rows are append-only and cannot be deleted.")


class ThreadRead(models.Model):
    """When this adult last looked at this thread."""

    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE, related_name="reads"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="thread_reads",
    )
    last_read_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["thread", "user"], name="uniq_thread_read_user"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user.display_name} read {self.thread_id} at {self.last_read_at:%Y-%m-%d %H:%M}"

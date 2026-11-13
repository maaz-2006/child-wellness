"""
Core identity, institution and audit models.

Design note on AuditLog: it deliberately does *not* hold a foreign key to
children.Child. A core -> children FK plus children -> core (User, School) would
create a circular migration dependency. We denormalise `child_id` instead and
accept the weaker referential guarantee, because an audit row must survive the
deletion of the thing it describes anyway.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    PARENT = "parent", "Parent / Guardian"
    MENTOR = "mentor", "Mentor / Teacher"
    CHILD = "child", "Child"
    ADMIN = "admin", "Administrator"


class User(AbstractUser):
    """Single user table for every role.

    A separate profile table per role was rejected: the permission gate needs to
    resolve role -> relationship -> access in one query, and scattered profiles
    make that both slower and easier to get wrong.
    """

    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.PARENT,
        db_index=True,
    )
    must_change_password = models.BooleanField(
        default=False,
        help_text="Set for generated accounts (e.g. child PIN accounts) on first login.",
    )

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username

    @property
    def is_admin_role(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_mentor(self) -> bool:
        return self.role == Role.MENTOR

    @property
    def is_parent(self) -> bool:
        return self.role == Role.PARENT

    @property
    def is_child(self) -> bool:
        return self.role == Role.CHILD


class School(models.Model):
    """The single institution this deployment serves.

    Present as a model rather than as settings values so that a second school is
    a data change rather than a fork of the codebase.
    """

    name = models.CharField(max_length=160)
    short_name = models.CharField(max_length=40, blank=True)
    timezone = models.CharField(max_length=64, default="Africa/Nairobi")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "school"
        verbose_name_plural = "school"

    def __str__(self) -> str:
        return self.name

    @classmethod
    def load(cls) -> "School | None":
        return cls.objects.order_by("pk").first()


class AuditLog(models.Model):
    """Append-only record of who did what to whose data.

    Written for every privileged read of sensitive wellness data, every
    permission denial, and every mutation of a child record. This is the
    evidence trail behind the privacy section of the report.
    """

    class Action(models.TextChoices):
        VIEW = "view", "Viewed"
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        DELETE = "delete", "Deleted"
        DENY = "deny", "Access denied"
        LOGIN = "login", "Signed in"
        LOGIN_FAILED = "login_failed", "Sign-in failed"
        EXPORT = "export", "Exported"
        ALERT_ACK = "alert_ack", "Acknowledged alert"
        ALERT_DISMISS = "alert_dismiss", "Dismissed alert"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    actor_role = models.CharField(max_length=16, blank=True)
    action = models.CharField(max_length=24, choices=Action.choices, db_index=True)
    resource_type = models.CharField(max_length=64, blank=True, db_index=True)
    resource_id = models.CharField(max_length=64, blank=True)
    child_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor", "-created_at"]),
            models.Index(fields=["child_id", "-created_at"]),
        ]
        verbose_name = "audit log entry"

    def __str__(self) -> str:
        who = self.actor.display_name if self.actor else "anonymous"
        return f"{who} {self.get_action_display().lower()} {self.resource_type} @ {self.created_at:%Y-%m-%d %H:%M}"

"""Audit trail helpers.

Kept separate from models so views can call one function and never touch the
model directly. `record_request` never raises: an audit failure must not take
down a page, but it is logged loudly because a silent audit gap is worse than a
loud one.
"""

from __future__ import annotations

import logging

from .models import AuditLog

logger = logging.getLogger("wellness.audit")


def _client_ip(request) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def record_request(
    request,
    action: str,
    resource_type: str = "",
    resource_id: str | int = "",
    child=None,
    metadata: dict | None = None,
) -> AuditLog | None:
    """Append an audit row for the current request. Always safe to call."""
    try:
        user = getattr(request, "user", None)
        actor = user if getattr(user, "is_authenticated", False) else None
        return AuditLog.objects.create(
            actor=actor,
            actor_role=getattr(actor, "role", "") or "",
            action=action,
            resource_type=resource_type or "",
            resource_id=str(resource_id or ""),
            child_id=getattr(child, "pk", None),
            ip_address=_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:255],
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit entry for action=%s", action)
        return None


def record(
    action: str,
    actor=None,
    resource_type: str = "",
    resource_id: str | int = "",
    child=None,
    metadata: dict | None = None,
) -> AuditLog | None:
    """Audit without a request object (management commands, seeders)."""
    try:
        return AuditLog.objects.create(
            actor=actor,
            actor_role=getattr(actor, "role", "") or "",
            action=action,
            resource_type=resource_type or "",
            resource_id=str(resource_id or ""),
            child_id=getattr(child, "pk", None),
            metadata=metadata or {},
        )
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit entry for action=%s", action)
        return None

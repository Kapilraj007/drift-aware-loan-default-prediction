"""Small, deliberately allow-listed audit-event writer."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from ..models.db_models import AuditEvent, User

_SENSITIVE_KEYS = frozenset(
    {"password", "current_password", "new_password", "temporary_password", "token", "features"}
)


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in (metadata or {}).items()
        if key.casefold() not in _SENSITIVE_KEYS
    }


def request_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host[:64]


def record_audit_event(
    session: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_user_id: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditEvent:
    """Append an event without accepting secrets or application feature payloads."""

    event = AuditEvent(
        actor_user_id=actor.id if actor is not None else actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        event_metadata=_safe_metadata(metadata),
        ip=request_ip(request),
    )
    session.add(event)
    session.flush()
    return event


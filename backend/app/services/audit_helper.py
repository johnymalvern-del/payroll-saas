
"""Write append-only audit entries for auth events.

Never write passwords, tokens, or token hashes. The redaction list below is
enforced here so any caller that passes them by mistake is caught before it
reaches the database.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.tenant.models.platform import AuditLog

_REDACTED_KEYS = {
    "password",
    "password_hash",
    "current_password",
    "new_password",
    "token",
    "access_token",
    "refresh_token",
    "jti",
    "jti_hash",
}


def _redact(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    out: dict[str, Any] = {}
    for k, v in value.items():
        if k in _REDACTED_KEYS:
            out[k] = "***"
        else:
            out[k] = v
    return out


def write_auth_audit(
    session: Session,
    *,
    action: str,
    entity_type: str = "user",
    entity_id: str | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    reason: str | None = None,
    ip_address: str | None = None,
    request_id: str | None = None,
) -> None:
    import uuid as _uuid

    session.add(
        AuditLog(
            id=_uuid.uuid4(),
            actor_user_id=_uuid.UUID(actor_user_id) if actor_user_id else None,
            actor_role=actor_role,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            old_value=_redact(old_value),
            new_value=_redact(new_value),
            reason=reason,
            ip_address=ip_address,
            request_id=request_id,
        )
    )

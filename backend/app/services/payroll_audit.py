"""Defensive audit writer for payroll endpoints (Chapter 4).

The control audit table's exact column set is not fully probed yet; this
helper filters kwargs by column name so it works regardless. If a shared
audit helper exists later, wire it in here in one place.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session


def write_audit(
    db: Session,
    user: Any,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    reason: str | None = None,
    actor_system: bool = False,
) -> "AuditLog":
    """Append an audit row.

    If actor_system=True, actor_role is set to 'system' and actor_user_id is
    None. That satisfies Phase 1A's "service identity distinguishable from
    humans" requirement without a schema change (Phase 1E may add an
    explicit actor_system column). The created AuditLog row is returned so
    callers can link downstream records (e.g. intelligence_mode_change_log).
    """
    from app.db.tenant.models.platform import AuditLog

    cols = {c.name for c in AuditLog.__table__.columns}
    kwargs: dict[str, Any] = {}
    for k, v in (
        ("actor_user_id", None if actor_system else getattr(user, "id", None)),
        ("actor_role", "system" if actor_system else getattr(user, "role", None)),
        ("entity_type", entity_type),
        ("entity_id", entity_id),
        ("action", action),
        ("old_value", old_value),
        ("new_value", new_value),
        ("reason", reason),
        ("occurred_at", datetime.now(timezone.utc)),
    ):
        if k in cols:
            kwargs[k] = v
    row = AuditLog(**kwargs)
    db.add(row)
    return row

# END OF FILE

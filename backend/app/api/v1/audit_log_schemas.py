"""Audit-log read API schemas (1C.12)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_user_id: uuid.UUID | None = None
    actor_role: str | None = None
    entity_type: str
    entity_id: str | None = None
    action: str
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None
    reason: str | None = None
    ip_address: str | None = None
    request_id: str | None = None


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    next_cursor: str | None = None
    total: int | None = None
    occurred_from_applied: datetime
    occurred_to_applied: datetime

# END OF FILE
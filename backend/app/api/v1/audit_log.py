"""Audit-log read API (1C.12).

Two endpoints:
  GET /api/v1/audit-log          list, cursor, filters
  GET /api/v1/audit-log/{id}     single-row drill-down

Permission: AUDIT_VIEW (payroll_admin, auditor). No new matrix rows.

D6A (read-auditing), scoped tightly:
  - One audit_log.read row per REQUEST, not per returned row.
  - The row records the filters used (list) or the entry id (single read)
    in new_value, and never copies old_value or new_value from the rows
    being read.
  - The write is in the same transaction as the read. A failed write fails
    the request (fail closed). No unlogged audit reads.

D3 override: occurred_from is OPTIONAL. If omitted, the effective range is
the last 30 days. If occurred_to is supplied and lies more than 30 days in
the past, occurred_from defaults to occurred_to - 30 days so that a
plausible range is returned. The effective range is echoed in the response
as occurred_from_applied and occurred_to_applied. If the resulting
effective_from > effective_to, the request fails with 400 invalid_range.

D4: newest first (occurred_at DESC, id DESC). id is a random UUID and is
used only as a deterministic pagination tiebreaker; it is not insertion
order.

D7: old_value and new_value are returned exactly as stored. They were
redacted at write time by app.services.audit_redact.redact_for_audit.

Error codes:
  invalid_range            - effective_from > effective_to
  invalid_cursor           - cursor is malformed
  audit_entry_not_found    - single-row read, id not present
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import and_, func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.audit_log_schemas import AuditLogListOut, AuditLogOut
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/audit-log", tags=["audit-log"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_DEFAULT_WINDOW = timedelta(days=30)


def _encode_cursor(occurred_at: datetime, entry_id: uuid.UUID) -> str:
    payload = {"t": occurred_at.isoformat(), "i": str(entry_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        ts = datetime.fromisoformat(payload["t"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, uuid.UUID(payload["i"])
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _as_utc(dt: datetime | None) -> datetime | None:
    """Normalise a naive datetime to UTC; pass through aware ones."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _to_out(row: AuditLog) -> AuditLogOut:
    return AuditLogOut(
        id=row.id,
        occurred_at=row.occurred_at,
        actor_user_id=row.actor_user_id,
        actor_role=row.actor_role,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        action=row.action,
        old_value=row.old_value,
        new_value=row.new_value,
        reason=row.reason,
        ip_address=row.ip_address,
        request_id=row.request_id,
    )


def _write_read_audit(
    db: Any,
    request: Request,
    user: Any,
    *,
    new_value: dict[str, Any],
    entity_id: str | None = None,
) -> None:
    """Write one audit_log.read row. Caller is responsible for the commit."""
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="audit_log",
            entity_id=entity_id,
            action="audit_log.read",
            old_value=None,
            new_value=redact_for_audit(new_value),
            request_id=getattr(request.state, "request_id", None),
            ip_address=(request.client.host if request.client else None),
        )
    )


@router.get("", response_model=AuditLogListOut)
def list_audit_log(
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.AUDIT_VIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_total: bool = Query(False),
    occurred_from: datetime | None = Query(None),
    occurred_to: datetime | None = Query(None),
    actor_user_id: uuid.UUID | None = Query(None),
    actor_role: str | None = Query(None),
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
    action: str | None = Query(None),
    request_id: str | None = Query(None),
    reason: str | None = Query(None),
) -> AuditLogListOut:
    occurred_from = _as_utc(occurred_from)
    occurred_to = _as_utc(occurred_to)
    now = datetime.now(timezone.utc)
    if occurred_from is None:
        if occurred_to is not None and occurred_to < now - _DEFAULT_WINDOW:
            effective_from = occurred_to - _DEFAULT_WINDOW
        else:
            effective_from = now - _DEFAULT_WINDOW
    else:
        effective_from = occurred_from
    effective_to = occurred_to or now

    if effective_from > effective_to:
        raise AppError(
            "invalid_range",
            "occurred_from must not be after occurred_to",
            status.HTTP_400_BAD_REQUEST,
        )

    base_clauses = [
        AuditLog.occurred_at >= effective_from,
        AuditLog.occurred_at <= effective_to,
    ]
    if actor_user_id is not None:
        base_clauses.append(AuditLog.actor_user_id == actor_user_id)
    if actor_role is not None:
        base_clauses.append(AuditLog.actor_role == actor_role)
    if entity_type is not None:
        base_clauses.append(AuditLog.entity_type == entity_type)
    if entity_id is not None:
        base_clauses.append(AuditLog.entity_id == entity_id)
    if action is not None:
        base_clauses.append(AuditLog.action == action)
    if request_id is not None:
        base_clauses.append(AuditLog.request_id == request_id)
    if reason is not None:
        base_clauses.append(AuditLog.reason == reason)

    q = select(AuditLog).where(*base_clauses)
    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(
            or_(
                AuditLog.occurred_at < ts,
                and_(AuditLog.occurred_at == ts, AuditLog.id < cid),
            )
        )
    q = q.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.occurred_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(AuditLog).where(*base_clauses)
        total = int(db.scalar(tq) or 0)

    filters_used = {
        "occurred_from": effective_from.isoformat(),
        "occurred_to": effective_to.isoformat(),
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "actor_role": actor_role,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "request_id": request_id,
        "reason": reason,
        "cursor": cursor is not None,
        "limit": limit,
        "include_total": include_total,
    }
    _write_read_audit(db, request, user, new_value={"filters": filters_used})
    db.commit()

    return AuditLogListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
        occurred_from_applied=effective_from,
        occurred_to_applied=effective_to,
    )


@router.get("/{entry_id}", response_model=AuditLogOut)
def get_audit_log_entry(
    entry_id: uuid.UUID,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.AUDIT_VIEW))],
) -> AuditLogOut:
    row = db.get(AuditLog, entry_id)
    if row is None:
        raise AppError(
            "audit_entry_not_found",
            "Audit log entry not found",
            status.HTTP_404_NOT_FOUND,
        )
    _write_read_audit(
        db,
        request,
        user,
        new_value={"entry_id": str(entry_id)},
        entity_id=str(entry_id),
    )
    db.commit()
    return _to_out(row)

# END OF FILE
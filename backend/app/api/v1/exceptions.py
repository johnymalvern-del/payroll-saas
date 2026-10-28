"""Exceptions queue endpoints (Chapter 2C).

Four endpoints:
  GET  /attendance/exceptions                   cursor list, filters
  GET  /attendance/exceptions/{id}              single
  POST /attendance/exceptions/{id}/resolve      apply_suggestion / custom / dismiss
  POST /attendance/exceptions/bulk_resolve      dry-run + token (C1)

Permissions:
  list, get     ATTENDANCE_VIEW
  resolve, bulk ATTENDANCE_ADJUST

Scope:
  list uses apply_scope(model=ExceptionItem)
  single uses assert_in_scope on employee_id; out-of-scope returns 404

Self-adjustment (C8) and locked-day (C3) guards live in the resolve and
bulk_resolve endpoints, added in 2C-3b-ii.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.exceptions_schemas import ExceptionListOut, ExceptionOut
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.attendance import ExceptionItem
from app.db.tenant.models.people import Employee

router = APIRouter(prefix="/attendance/exceptions", tags=["attendance-exceptions"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(e: ExceptionItem) -> ExceptionOut:
    return ExceptionOut(
        id=e.id,
        employee_id=e.employee_id,
        work_date=e.work_date,
        type=e.type,
        source_ref=dict(e.source_ref or {}),
        suggested_fix=dict(e.suggested_fix or {}),
        status=e.status,
        assigned_to=e.assigned_to,
        resolved_by=e.resolved_by,
        resolved_at=e.resolved_at,
        resolution=dict(e.resolution) if e.resolution else None,
        created_at=e.created_at,
        updated_at=e.updated_at,
    )


def _encode_cursor(work_date: date, exc_id: uuid.UUID) -> str:
    raw = json.dumps({"d": work_date.isoformat(), "i": str(exc_id)},
                     separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        return date.fromisoformat(payload["d"]), uuid.UUID(payload["i"])
    except Exception:
        raise AppError(
            "invalid_cursor", "The pagination cursor is malformed", 400
        ) from None


@router.get("", response_model=ExceptionListOut)
def list_exceptions(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_total: bool = Query(False),
    employee_id: uuid.UUID | None = Query(None),
    site_id: uuid.UUID | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    type_filter: str | None = Query(None, alias="type"),
    status_filter: str | None = Query(None, alias="status"),
) -> ExceptionListOut:
    q = select(ExceptionItem)
    if status_filter is None:
        q = q.where(ExceptionItem.status == "open")
    else:
        q = q.where(ExceptionItem.status == status_filter)
    if employee_id is not None:
        q = q.where(ExceptionItem.employee_id == employee_id)
    if site_id is not None:
        q = q.where(ExceptionItem.employee_id.in_(
            select(Employee.id).where(Employee.site_id == site_id)))
    if department_id is not None:
        q = q.where(ExceptionItem.employee_id.in_(
            select(Employee.id).where(Employee.department_id == department_id)))
    if from_date is not None:
        q = q.where(ExceptionItem.work_date >= from_date)
    if to_date is not None:
        q = q.where(ExceptionItem.work_date <= to_date)
    if type_filter is not None:
        q = q.where(ExceptionItem.type == type_filter)

    q = apply_scope(q, user, db, model=ExceptionItem)

    if cursor is not None:
        wd, cid = _decode_cursor(cursor)
        q = q.where(or_(
            ExceptionItem.work_date < wd,
            (ExceptionItem.work_date == wd) & (ExceptionItem.id < cid),
        ))

    q = q.order_by(ExceptionItem.work_date.desc(), ExceptionItem.id.desc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.work_date, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(ExceptionItem)
        if status_filter is None:
            tq = tq.where(ExceptionItem.status == "open")
        else:
            tq = tq.where(ExceptionItem.status == status_filter)
        if employee_id is not None:
            tq = tq.where(ExceptionItem.employee_id == employee_id)
        if site_id is not None:
            tq = tq.where(ExceptionItem.employee_id.in_(
                select(Employee.id).where(Employee.site_id == site_id)))
        if department_id is not None:
            tq = tq.where(ExceptionItem.employee_id.in_(
                select(Employee.id).where(Employee.department_id == department_id)))
        if from_date is not None:
            tq = tq.where(ExceptionItem.work_date >= from_date)
        if to_date is not None:
            tq = tq.where(ExceptionItem.work_date <= to_date)
        if type_filter is not None:
            tq = tq.where(ExceptionItem.type == type_filter)
        tq = apply_scope(tq, user, db, model=ExceptionItem)
        total = int(db.scalar(tq) or 0)

    return ExceptionListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/{exception_id}", response_model=ExceptionOut)
def get_exception(
    exception_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
) -> ExceptionOut:
    exc = db.get(ExceptionItem, exception_id)
    if exc is None:
        raise AppError("record_not_found", "Exception not found", 404)
    try:
        assert_in_scope(user, exc.employee_id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Exception not found", 404) from None
    return _to_out(exc)

# END OF FILE
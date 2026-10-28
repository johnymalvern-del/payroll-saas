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
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.exceptions_schemas import (
    CustomAdjustmentIn, ExceptionListOut, ExceptionOut,
    ResolveIn, ResolveOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.attendance import (
    Adjustment, AttendanceDay, AttendanceSegment, ExceptionItem, Shift,
)
from app.db.tenant.models.organisation import Company, Site
from app.db.tenant.models.platform import AuditLog
from app.api.v1.attendance_engine import (
    _day_snapshot, _persist_adjustment, _sync_exceptions, recompute_day,
)
from zoneinfo import ZoneInfo
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


_DEFAULT_REASON_CODES = (
    "device_down",
    "forgot_clock",
    "approved_site_work",
    "system_correction",
    "other",
)


def _current_reason_codes(db) -> tuple:
    company = db.scalar(select(Company))
    if company is None:
        return _DEFAULT_REASON_CODES
    settings = company.settings or {}
    att = settings.get("attendance") or {}
    codes = att.get("reason_codes")
    if isinstance(codes, list) and codes and all(isinstance(c, str) for c in codes):
        return tuple(codes)
    return _DEFAULT_REASON_CODES


def _validate_reason(db, reason_code: str, note: str | None) -> None:
    allowed = _current_reason_codes(db)
    if reason_code not in allowed:
        raise AppError(
            "invalid_reason_code",
            f"reason_code must be one of {allowed}",
            status.HTTP_400_BAD_REQUEST,
            {"reason_code": reason_code},
        )
    if reason_code == "other":
        if note is None or len(note.strip()) < 10:
            raise AppError(
                "note_required",
                "reason_code 'other' requires a note of at least 10 characters",
                status.HTTP_400_BAD_REQUEST,
            )


def _site_tz_for_employee(db, employee) -> ZoneInfo:
    if employee.site_id is not None:
        site = db.get(Site, employee.site_id)
        if site is not None and site.timezone:
            return ZoneInfo(site.timezone)
    company = db.scalar(select(Company))
    if company is None:
        raise AppError("company_missing", "Company row not found", 500)
    return ZoneInfo(company.default_timezone)


def _day_for(db, employee_id, work_date):
    return db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == employee_id,
        AttendanceDay.work_date == work_date,
    ))


def _approve_pending_segments(db, day) -> int:
    segs = db.scalars(select(AttendanceSegment).where(
        AttendanceSegment.attendance_day_id == day.id,
        AttendanceSegment.overtime_status == "pending",
    )).all()
    for s in segs:
        s.overtime_status = "approved"
    db.flush()
    return len(segs)


def _serialize_adj(adj) -> dict:
    return {
        "id": str(adj.id),
        "employee_id": str(adj.employee_id),
        "work_date": adj.work_date.isoformat(),
        "outcome": adj.outcome,
        "time_in": adj.time_in.isoformat() if adj.time_in else None,
        "time_out": adj.time_out.isoformat() if adj.time_out else None,
        "minutes": adj.minutes,
        "reason_code": adj.reason_code,
        "note": adj.note,
        "batch_id": str(adj.batch_id) if adj.batch_id else None,
        "created_by": str(adj.created_by) if adj.created_by else None,
    }


def _apply_adjustment(db, user, employee_id, work_date, custom,
                      *, batch_id=None, request_id=None):
    day_before = _day_for(db, employee_id, work_date)
    if day_before is not None and day_before.locked:
        raise AppError(
            "day_locked",
            "The payroll period containing this day is closed; corrections after close come with the payroll period feature",
            status.HTTP_409_CONFLICT,
        )
    adj = _persist_adjustment(
        db,
        employee_id=employee_id,
        work_date=work_date,
        outcome=custom.outcome,
        time_in=custom.time_in,
        time_out=custom.time_out,
        reason_code=custom.reason_code,
        note=custom.note,
        created_by=getattr(user, "id", None),
        batch_id=batch_id,
    )
    recompute_day(db, employee_id, work_date)
    day_after = _day_for(db, employee_id, work_date)
    adj.new_value = _day_snapshot(day_after)
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="adjustment",
        entity_id=str(adj.id),
        action="attendance.adjustment.create",
        old_value=adj.old_value,
        new_value={"adjustment": _serialize_adj(adj)},
        request_id=request_id,
    ))
    db.commit()
    return adj.id, (day_after.status if day_after else None)


def _suggested_adjustment_for(db, exc, day, employee):
    """Return a CustomAdjustmentIn or None (acceptance-only), or raise."""
    t = exc.type
    if t == "missing_out":
        if day is None or day.shift_id is None or day.first_in is None:
            raise AppError(
                "suggestion_requires_params",
                "missing_out with no shift cannot be auto-applied; use custom",
                status.HTTP_400_BAD_REQUEST,
            )
        shift = db.get(Shift, day.shift_id)
        if shift is None:
            raise AppError("suggestion_requires_params", "shift not found", status.HTTP_400_BAD_REQUEST)
        tz = _site_tz_for_employee(db, employee)
        end_local = datetime.combine(day.work_date, shift.start_time, tzinfo=tz) + timedelta(minutes=shift.length_minutes)
        return CustomAdjustmentIn(
            outcome="worked",
            time_in=day.first_in,
            time_out=end_local.astimezone(timezone.utc),
            reason_code="forgot_clock",
            note="Auto: apply shift end time",
        )
    if t == "too_long":
        if day is None or day.shift_id is None or day.first_in is None:
            raise AppError("suggestion_requires_params", "too_long with no shift", status.HTTP_400_BAD_REQUEST)
        shift = db.get(Shift, day.shift_id)
        if shift is None:
            raise AppError("suggestion_requires_params", "shift not found", status.HTTP_400_BAD_REQUEST)
        return CustomAdjustmentIn(
            outcome="worked",
            time_in=day.first_in,
            time_out=day.first_in + timedelta(minutes=shift.max_shift_minutes),
            reason_code="system_correction",
            note="Auto: truncate to max shift",
        )
    if t == "absent_expected":
        return CustomAdjustmentIn(
            outcome="day_off",
            reason_code="system_correction",
            note="Auto: mark as day off",
        )
    if t == "no_shift_match":
        raise AppError(
            "suggestion_requires_params",
            "no_shift_match requires choosing a shift via 'custom'",
            status.HTTP_400_BAD_REQUEST,
        )
    if t in ("low_confidence", "overtime_unapproved", "device_clock_gap", "duplicate", "employee_query"):
        return None
    raise AppError(
        "unknown_suggestion",
        f"No suggestion for exception type {t}",
        status.HTTP_400_BAD_REQUEST,
    )


@router.post("/{exception_id}/resolve", response_model=ResolveOut)
def resolve_exception(
    exception_id: uuid.UUID,
    payload: ResolveIn,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_ADJUST))],
) -> ResolveOut:
    exc = db.get(ExceptionItem, exception_id)
    if exc is None:
        raise AppError("record_not_found", "Exception not found", 404)
    try:
        assert_in_scope(user, exc.employee_id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Exception not found", 404) from None
    if exc.status != "open":
        raise AppError(
            "exception_not_open",
            f"Exception is already {exc.status}",
            status.HTTP_409_CONFLICT,
        )
    if getattr(user, "employee_id", None) is not None and user.employee_id == exc.employee_id:
        raise AppError(
            "cannot_adjust_own",
            "A user cannot adjust their own attendance",
            status.HTTP_403_FORBIDDEN,
        )
    employee = db.get(Employee, exc.employee_id)
    if employee is None:
        raise AppError("record_not_found", "Employee not found", 404)
    day = _day_for(db, exc.employee_id, exc.work_date)
    request_id = getattr(request.state, "request_id", None)
    adjustment_id: uuid.UUID | None = None
    day_status = day.status if day is not None else None

    try:
        if payload.action == "dismiss":
            pass
        elif payload.action == "custom":
            ca = payload.custom_adjustment
            _validate_reason(db, ca.reason_code, ca.note)
            adjustment_id, day_status = _apply_adjustment(
                db, user, exc.employee_id, exc.work_date, ca, request_id=request_id
            )
        else:
            ca = _suggested_adjustment_for(db, exc, day, employee)
            if ca is not None:
                _validate_reason(db, ca.reason_code, ca.note)
                adjustment_id, day_status = _apply_adjustment(
                    db, user, exc.employee_id, exc.work_date, ca, request_id=request_id
                )
            elif exc.type == "overtime_unapproved" and day is not None:
                _approve_pending_segments(db, day)
                recompute_day(db, exc.employee_id, exc.work_date)
                db.commit()
                refreshed = _day_for(db, exc.employee_id, exc.work_date)
                day_status = refreshed.status if refreshed is not None else None
    except AppError:
        db.rollback()
        raise

    exc = db.get(ExceptionItem, exception_id)
    exc.status = "resolved"
    exc.resolved_by = getattr(user, "id", None)
    exc.resolved_at = datetime.now(timezone.utc)
    exc.resolution = {
        "action": payload.action,
        "adjustment_id": str(adjustment_id) if adjustment_id else None,
        "note": payload.note,
    }
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="exception_item",
        entity_id=str(exc.id),
        action="attendance.exception.resolve",
        old_value={"status": "open"},
        new_value={
            "status": "resolved",
            "action": payload.action,
            "adjustment_id": str(adjustment_id) if adjustment_id else None,
        },
        request_id=request_id,
    ))
    db.commit()
    db.refresh(exc)
    return ResolveOut(
        exception=_to_out(exc),
        adjustment_id=adjustment_id,
        day_status=day_status,
    )

# END OF FILE

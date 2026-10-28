"""Attendance read and recompute endpoints (Chapter 2B).

Three endpoints:
  GET  /api/v1/attendance/day                     cursor list, filters
  GET  /api/v1/attendance/day/{employee_id}/{work_date}   single day with segments
  POST /api/v1/attendance/recompute              sweep + recompute for a target

Permissions:
  day list and day detail   ATTENDANCE_VIEW  (employee, manager, hr, payroll_admin;
                                              auditor is NOT granted, per section 6)
  recompute                 ATTENDANCE_ADJUST (manager, hr, payroll_admin)

Scope:
  list uses apply_scope(model=AttendanceDay) — filters by employee_id set
  detail uses assert_in_scope — out-of-scope returns 404 record_not_found
  recompute applies apply_scope(model=Employee) to the target employee set
  before iterating. A manager cannot recompute outside their scope (B12).

B12 for recompute: run ensure_days first (creates rows for dates with no
punches: absent / missing_punch / public_holiday_unworked / clocks=false
synthetic), then recompute_day for each (employee, date). Locked days are
skipped and reported in skipped_locked.

B2: work_date is the local date the shift STARTS. Segments carry local_date
(the real calendar date of the segment) which may differ on a night shift.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.attendance_engine import ensure_days, recompute_day
from app.api.v1.attendance_schemas import (
    DayDetailOut,
    DayListOut,
    DayOut,
    RecomputeIn,
    RecomputeOut,
    SegmentOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.attendance import AttendanceDay, AttendanceSegment
from app.db.tenant.models.people import Employee

router = APIRouter(prefix="/attendance", tags=["attendance"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _to_out(d: AttendanceDay) -> DayOut:
    return DayOut(
        id=d.id,
        employee_id=d.employee_id,
        work_date=d.work_date,
        status=d.status,
        first_in=d.first_in,
        last_out=d.last_out,
        worked_minutes=d.worked_minutes,
        normal_minutes=d.normal_minutes,
        overtime_minutes=d.overtime_minutes,
        raw_minutes=d.raw_minutes,
        shift_id=d.shift_id,
        flags=list(d.flags or []),
        source_version=d.source_version,
        locked=d.locked,
        row_version=d.row_version,
        computed_at=d.computed_at,
    )


def _seg_to_out(s: AttendanceSegment) -> SegmentOut:
    return SegmentOut(
        id=s.id,
        attendance_day_id=s.attendance_day_id,
        local_date=s.local_date,
        day_type=s.day_type,
        kind=s.kind,
        tier=s.tier,
        minutes=s.minutes,
        rate_method=s.rate_method,
        rate_value=s.rate_value,
        overtime_status=s.overtime_status,
        source_refs=list(s.source_refs or []),
    )


def _encode_cursor(work_date: date, day_id: uuid.UUID) -> str:
    payload = {"d": work_date.isoformat(), "i": str(day_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
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


@router.get("/day", response_model=DayListOut)
def list_days(
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
    status_filter: str | None = Query(None, alias="status"),
    employee_code: str | None = Query(None),
) -> DayListOut:
    q = select(AttendanceDay)
    if employee_id is not None:
        q = q.where(AttendanceDay.employee_id == employee_id)
    if site_id is not None:
        q = q.where(
            AttendanceDay.employee_id.in_(
                select(Employee.id).where(Employee.site_id == site_id)
            )
        )
    if department_id is not None:
        q = q.where(
            AttendanceDay.employee_id.in_(
                select(Employee.id).where(Employee.department_id == department_id)
            )
        )
    if employee_code is not None:
        q = q.where(
            AttendanceDay.employee_id.in_(
                select(Employee.id).where(
                    func.lower(Employee.employee_code) == employee_code.strip().lower()
                )
            )
        )
    if from_date is not None:
        q = q.where(AttendanceDay.work_date >= from_date)
    if to_date is not None:
        q = q.where(AttendanceDay.work_date <= to_date)
    if status_filter is not None:
        q = q.where(AttendanceDay.status == status_filter)

    q = apply_scope(q, user, db, model=AttendanceDay)

    if cursor is not None:
        wd, cid = _decode_cursor(cursor)
        q = q.where(
            or_(
                AttendanceDay.work_date < wd,
                (AttendanceDay.work_date == wd) & (AttendanceDay.id < cid),
            )
        )

    q = q.order_by(AttendanceDay.work_date.desc(), AttendanceDay.id.desc()).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.work_date, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(AttendanceDay)
        if employee_id is not None:
            tq = tq.where(AttendanceDay.employee_id == employee_id)
        if site_id is not None:
            tq = tq.where(
                AttendanceDay.employee_id.in_(
                    select(Employee.id).where(Employee.site_id == site_id)
                )
            )
        if department_id is not None:
            tq = tq.where(
                AttendanceDay.employee_id.in_(
                    select(Employee.id).where(Employee.department_id == department_id)
                )
            )
        if employee_code is not None:
            tq = tq.where(
                AttendanceDay.employee_id.in_(
                    select(Employee.id).where(
                        func.lower(Employee.employee_code) == employee_code.strip().lower()
                    )
                )
            )
        if from_date is not None:
            tq = tq.where(AttendanceDay.work_date >= from_date)
        if to_date is not None:
            tq = tq.where(AttendanceDay.work_date <= to_date)
        if status_filter is not None:
            tq = tq.where(AttendanceDay.status == status_filter)
        tq = apply_scope(tq, user, db, model=AttendanceDay)
        total = int(db.scalar(tq) or 0)

    return DayListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.get("/day/{employee_id}/{work_date}", response_model=DayDetailOut)
def get_day(
    employee_id: uuid.UUID,
    work_date: date,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
) -> DayDetailOut:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError(
            "record_not_found", "Attendance day not found", 404
        ) from None
    day = db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.work_date == work_date,
        )
    )
    if day is None:
        raise AppError("record_not_found", "Attendance day not found", 404)
    segs = db.scalars(
        select(AttendanceSegment)
        .where(AttendanceSegment.attendance_day_id == day.id)
        .order_by(
            AttendanceSegment.local_date,
            AttendanceSegment.kind,
            AttendanceSegment.tier,
        )
    ).all()
    base = _to_out(day)
    return DayDetailOut(
        **base.model_dump(),
        segments=[_seg_to_out(s) for s in segs],
    )


@router.post("/recompute", response_model=RecomputeOut)
def recompute(
    payload: RecomputeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_ADJUST))],
) -> RecomputeOut:
    if payload.employee_id is not None:
        q = select(Employee).where(Employee.id == payload.employee_id)
    elif payload.site_id is not None:
        q = select(Employee).where(Employee.site_id == payload.site_id)
    else:
        q = select(Employee).where(Employee.department_id == payload.department_id)
    q = apply_scope(q, user, db, model=Employee)
    targets = list(db.scalars(q).all())

    if not targets:
        return RecomputeOut(
            recomputed=0,
            skipped_locked=0,
            employee_count=0,
            from_date=payload.from_date,
            to_date=payload.to_date,
        )

    target_ids = [e.id for e in targets]

    ensure_days(db, target_ids, payload.from_date, payload.to_date)

    locked_keys: set[tuple[uuid.UUID, date]] = set()
    for row in db.execute(
        select(AttendanceDay.employee_id, AttendanceDay.work_date).where(
            AttendanceDay.employee_id.in_(target_ids),
            AttendanceDay.work_date >= payload.from_date,
            AttendanceDay.work_date <= payload.to_date,
            AttendanceDay.locked.is_(True),
        )
    ):
        locked_keys.add((row.employee_id, row.work_date))

    recomputed = 0
    skipped_locked = 0
    cur = payload.from_date
    while cur <= payload.to_date:
        for emp in targets:
            if (emp.id, cur) in locked_keys:
                skipped_locked += 1
                continue
            recompute_day(db, emp.id, cur)
            recomputed += 1
        cur += timedelta(days=1)

    return RecomputeOut(
        recomputed=recomputed,
        skipped_locked=skipped_locked,
        employee_count=len(targets),
        from_date=payload.from_date,
        to_date=payload.to_date,
    )

# END OF FILE
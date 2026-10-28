"""Attendance sheet endpoints (Chapter 2C).

Three endpoints (this file part 1: sheet; part 2: daily, mark_reviewed):
  GET  /attendance/sheet               monthly grid, cursor on employee_id
  GET  /attendance/daily               daily list for one date
  POST /attendance/mark_reviewed       clean-days marker (C3)

C2 compliance: no field in any response identifies a day as adjusted.
Adjustments are visible only through the audit log.

C9 limits: sheet page size default 50, max 200; date range max 31 days.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.api.deps import TenantDbDep
from app.api.v1.sheet_schemas import (
    DailyOut,
    DailyRowOut,
    MarkReviewedIn,
    MarkReviewedOut,
    MarkReviewedRefusedOut,
    SheetCellOut,
    SheetEmployeeOut,
    SheetOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import apply_scope
from app.db.tenant.models.attendance import AttendanceDay, ExceptionItem
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog

router = APIRouter(prefix="/attendance", tags=["attendance-sheet"])

_DEFAULT_SHEET_LIMIT = 50
_MAX_SHEET_LIMIT = 200
_MAX_RANGE_DAYS = 31


def _validate_range(from_date: date, to_date: date) -> None:
    if to_date < from_date:
        raise AppError("invalid_range", "to_date must be on or after from_date", 400)
    if (to_date - from_date).days > _MAX_RANGE_DAYS:
        raise AppError(
            "range_too_wide",
            f"date range must be {_MAX_RANGE_DAYS} days or fewer",
            400,
        )


def _employee_name(e: Employee) -> str:
    return f"{e.first_name} {e.last_name}".strip()


def _encode_emp_cursor(employee_id: uuid.UUID) -> str:
    raw = json.dumps({"i": str(employee_id)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_emp_cursor(cursor: str) -> uuid.UUID:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        return uuid.UUID(payload["i"])
    except Exception:
        raise AppError("invalid_cursor", "The pagination cursor is malformed", 400) from None


def _employee_filter_query(
    db, user,
    *, site_id, branch_id, department_id, include_terminated: bool,
):
    q = select(Employee)
    if not include_terminated:
        q = q.where(Employee.status != "terminated")
    if site_id is not None:
        q = q.where(Employee.site_id == site_id)
    if branch_id is not None:
        q = q.where(Employee.branch_id == branch_id)
    if department_id is not None:
        q = q.where(Employee.department_id == department_id)
    q = apply_scope(q, user, db, model=Employee)
    return q


def _open_exception_counts(db, employee_ids, from_date, to_date) -> dict:
    if not employee_ids:
        return {}
    rows = db.execute(
        select(
            ExceptionItem.employee_id,
            ExceptionItem.work_date,
            func.count(),
        ).where(
            ExceptionItem.employee_id.in_(employee_ids),
            ExceptionItem.work_date >= from_date,
            ExceptionItem.work_date <= to_date,
            ExceptionItem.status == "open",
        ).group_by(ExceptionItem.employee_id, ExceptionItem.work_date)
    ).all()
    return {(r[0], r[1]): int(r[2]) for r in rows}


def _days_by_emp(db, employee_ids, from_date, to_date) -> dict:
    if not employee_ids:
        return {}
    rows = db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.employee_id.in_(employee_ids),
            AttendanceDay.work_date >= from_date,
            AttendanceDay.work_date <= to_date,
        )
    ).all()
    return {(d.employee_id, d.work_date): d for d in rows}


@router.get("/sheet", response_model=SheetOut)
def get_sheet(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
    from_date: date,
    to_date: date,
    site_id: uuid.UUID | None = Query(None),
    branch_id: uuid.UUID | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    include_terminated: bool = Query(False),
    include_total: bool = Query(False),
    limit: int = Query(_DEFAULT_SHEET_LIMIT, ge=1, le=_MAX_SHEET_LIMIT),
    cursor: str | None = Query(None),
) -> SheetOut:
    _validate_range(from_date, to_date)
    q = _employee_filter_query(
        db, user,
        site_id=site_id, branch_id=branch_id, department_id=department_id,
        include_terminated=include_terminated,
    )
    if cursor is not None:
        cid = _decode_emp_cursor(cursor)
        q = q.where(Employee.id > cid)
    q = q.order_by(Employee.id.asc()).limit(limit + 1)
    emps = list(db.scalars(q).all())
    next_cursor = None
    if len(emps) > limit:
        emps = emps[:limit]
        next_cursor = _encode_emp_cursor(emps[-1].id)

    emp_ids = [e.id for e in emps]
    days_map = _days_by_emp(db, emp_ids, from_date, to_date)
    exc_map = _open_exception_counts(db, emp_ids, from_date, to_date)

    items = []
    num_days = (to_date - from_date).days + 1
    for emp in emps:
        cells = []
        for offset in range(num_days):
            d = from_date + timedelta(days=offset)
            day = days_map.get((emp.id, d))
            cells.append(SheetCellOut(
                work_date=d,
                status=day.status if day is not None else None,
                worked_minutes=day.worked_minutes if day is not None else None,
                normal_minutes=day.normal_minutes if day is not None else None,
                overtime_minutes=day.overtime_minutes if day is not None else None,
                flags=list(day.flags or []) if day is not None else [],
                open_exception_count=exc_map.get((emp.id, d), 0),
                locked=day.locked if day is not None else False,
                reviewed=(day.reviewed_at is not None) if day is not None else False,
            ))
        items.append(SheetEmployeeOut(
            employee_id=emp.id,
            employee_code=emp.employee_code,
            employee_name=_employee_name(emp),
            site_id=emp.site_id,
            department_id=emp.department_id,
            days=cells,
        ))

    total: int | None = None
    if include_total:
        tq = _employee_filter_query(
            db, user,
            site_id=site_id, branch_id=branch_id, department_id=department_id,
            include_terminated=include_terminated,
        )
        count_q = select(func.count()).select_from(tq.subquery())
        total = int(db.scalar(count_q) or 0)

    return SheetOut(items=items, next_cursor=next_cursor, total=total)


@router.get("/daily", response_model=DailyOut)
def get_daily(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
    target_date: date = Query(..., alias="date"),
    site_id: uuid.UUID | None = Query(None),
    branch_id: uuid.UUID | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    include_terminated: bool = Query(False),
    include_total: bool = Query(False),
    limit: int = Query(_DEFAULT_SHEET_LIMIT, ge=1, le=_MAX_SHEET_LIMIT),
    cursor: str | None = Query(None),
) -> DailyOut:
    q = _employee_filter_query(
        db, user,
        site_id=site_id, branch_id=branch_id, department_id=department_id,
        include_terminated=include_terminated,
    )
    if cursor is not None:
        cid = _decode_emp_cursor(cursor)
        q = q.where(Employee.id > cid)
    q = q.order_by(Employee.id.asc()).limit(limit + 1)
    emps = list(db.scalars(q).all())
    next_cursor = None
    if len(emps) > limit:
        emps = emps[:limit]
        next_cursor = _encode_emp_cursor(emps[-1].id)

    emp_ids = [e.id for e in emps]
    days_map = _days_by_emp(db, emp_ids, target_date, target_date)
    exc_map = _open_exception_counts(db, emp_ids, target_date, target_date)

    items = []
    for emp in emps:
        day = days_map.get((emp.id, target_date))
        items.append(DailyRowOut(
            employee_id=emp.id,
            employee_code=emp.employee_code,
            employee_name=_employee_name(emp),
            site_id=emp.site_id,
            department_id=emp.department_id,
            work_date=target_date,
            status=day.status if day is not None else None,
            first_in=day.first_in if day is not None else None,
            last_out=day.last_out if day is not None else None,
            shift_id=day.shift_id if day is not None else None,
            worked_minutes=day.worked_minutes if day is not None else None,
            normal_minutes=day.normal_minutes if day is not None else None,
            overtime_minutes=day.overtime_minutes if day is not None else None,
            flags=list(day.flags or []) if day is not None else [],
            open_exception_count=exc_map.get((emp.id, target_date), 0),
            locked=day.locked if day is not None else False,
            reviewed=(day.reviewed_at is not None) if day is not None else False,
        ))

    total: int | None = None
    if include_total:
        tq = _employee_filter_query(
            db, user,
            site_id=site_id, branch_id=branch_id, department_id=department_id,
            include_terminated=include_terminated,
        )
        count_q = select(func.count()).select_from(tq.subquery())
        total = int(db.scalar(count_q) or 0)

    return DailyOut(items=items, next_cursor=next_cursor, total=total)


@router.post("/mark_reviewed", response_model=MarkReviewedOut)
def mark_reviewed(
    payload: MarkReviewedIn,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_ADJUST))],
) -> MarkReviewedOut:
    _validate_range(payload.from_date, payload.to_date)

    if payload.employee_ids is not None:
        q = select(Employee).where(Employee.id.in_(payload.employee_ids))
    elif payload.site_id is not None:
        q = select(Employee).where(Employee.site_id == payload.site_id)
    else:
        q = select(Employee).where(Employee.department_id == payload.department_id)
    q = apply_scope(q, user, db, model=Employee)
    target_ids = [e.id for e in db.scalars(q).all()]

    if not target_ids:
        return MarkReviewedOut(marked=0, refused=0, refused_days=[])

    open_exc_rows = db.execute(
        select(ExceptionItem.employee_id, ExceptionItem.work_date).where(
            ExceptionItem.employee_id.in_(target_ids),
            ExceptionItem.work_date >= payload.from_date,
            ExceptionItem.work_date <= payload.to_date,
            ExceptionItem.status == "open",
        )
    ).all()
    refused_set = {(r[0], r[1]) for r in open_exc_rows}

    candidate_rows = list(db.scalars(
        select(AttendanceDay).where(
            AttendanceDay.employee_id.in_(target_ids),
            AttendanceDay.work_date >= payload.from_date,
            AttendanceDay.work_date <= payload.to_date,
            AttendanceDay.reviewed_at.is_(None),
        )
    ).all())

    now = datetime.now(timezone.utc)
    uid = getattr(user, "id", None)
    marked = 0
    refused_days: list[MarkReviewedRefusedOut] = []
    for row in candidate_rows:
        if (row.employee_id, row.work_date) in refused_set:
            refused_days.append(MarkReviewedRefusedOut(
                employee_id=row.employee_id,
                work_date=row.work_date,
                reason="open_exceptions",
            ))
            continue
        row.reviewed_at = now
        row.reviewed_by = uid
        marked += 1

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=uid,
        actor_role=getattr(user, "role", None),
        entity_type="attendance_day",
        entity_id=str(uuid.uuid4()),
        action="attendance.mark_reviewed",
        old_value=None,
        new_value={
            "marked": marked,
            "refused": len(refused_days),
            "from_date": payload.from_date.isoformat(),
            "to_date": payload.to_date.isoformat(),
            "target_count": len(target_ids),
            "refused_sample": [
                {"employee_id": str(rd.employee_id), "work_date": rd.work_date.isoformat()}
                for rd in refused_days[:20]
            ],
        },
        request_id=getattr(request.state, "request_id", None),
    ))
    db.commit()

    return MarkReviewedOut(
        marked=marked,
        refused=len(refused_days),
        refused_days=refused_days,
    )

# END OF FILE

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
from datetime import date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import TenantDbDep
from app.api.v1.sheet_schemas import (
    SheetCellOut,
    SheetEmployeeOut,
    SheetOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import apply_scope
from app.db.tenant.models.attendance import AttendanceDay, ExceptionItem
from app.db.tenant.models.people import Employee

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

# END OF FILE
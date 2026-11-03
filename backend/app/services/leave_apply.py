"""Leave attendance integration (Chapter 3, 3C, amendment 2).

On final approval of a leave request, one system adjustment is created
per LeaveRequestDay with outcome "leave" (or "sick" when the leave type
code is in PayrollSettings.sick_leave_codes), reason_code
"approved_leave", system_generated=True, leave_request_id=<req.id>.

Cancellation of an approved request creates a matching "revert"
adjustment per original day and reduces the balance.

Amendment 2: "Days in locked/closed periods: refuse with 409 day_locked
listing the dates." Applied on submit (before reservation) and on decide
(before adjustment creation). Applied atomically: if any day is locked,
NO adjustments are created and no balance is touched.

Amendment 6: `approved_leave` is a system-only reason code — it is NOT in
the user-facing reason-code whitelist and NOT surfaced by
GET /attendance/reason-codes. It exists only on system_generated=True
adjustments created by this module.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.attendance import Adjustment, AttendanceDay
from app.db.tenant.models.leave import LeaveRequest, LeaveType
from app.db.tenant.models.payroll_settings import PayrollSettings


def _sick_codes(db: Session) -> set[str]:
    s = db.scalar(select(PayrollSettings).limit(1))
    if s is None or not s.sick_leave_codes:
        return set()
    return set(s.sick_leave_codes)


def check_days_not_locked(
    db: Session, employee_id: uuid.UUID, work_dates: list[date],
) -> None:
    if not work_dates:
        return
    rows = db.execute(
        select(AttendanceDay.work_date).where(
            AttendanceDay.employee_id == employee_id,
            AttendanceDay.work_date.in_(work_dates),
            AttendanceDay.locked.is_(True),
        )
    ).all()
    locked = sorted(r[0] for r in rows)
    if locked:
        raise AppError(
            "day_locked",
            f"{len(locked)} day(s) are in a closed pay period: "
            + ", ".join(d.isoformat() for d in locked),
            409,
            {"dates": [d.isoformat() for d in locked]},
        )


def apply_leave_to_attendance(
    db: Session,
    *,
    user,
    request: LeaveRequest,
    leave_type: LeaveType,
    work_dates: list[date],
) -> list[uuid.UUID]:
    """Create one system adjustment per work_date. Caller commits.

    All-or-nothing: if any day is locked, raises day_locked before
    creating any adjustment.
    """
    check_days_not_locked(db, request.employee_id, work_dates)

    from app.api.v1.attendance_engine import _persist_adjustment, recompute_day

    sick = leave_type.code in _sick_codes(db)
    outcome = "sick" if sick else "leave"
    adj_ids: list[uuid.UUID] = []
    for wd in work_dates:
        adj = _persist_adjustment(
            db,
            employee_id=request.employee_id,
            work_date=wd,
            outcome=outcome,
            time_in=None,
            time_out=None,
            reason_code="approved_leave",
            note=f"Approved leave: request {request.id}",
            created_by=getattr(user, "id", None),
            batch_id=None,
        )
        adj.leave_request_id = request.id
        adj.system_generated = True
        db.add(adj)
        db.flush()
        recompute_day(db, request.employee_id, wd)
        adj_ids.append(adj.id)
    return adj_ids


def revert_leave_from_attendance(
    db: Session,
    *,
    user,
    request: LeaveRequest,
) -> list[uuid.UUID]:
    """Create revert adjustments for every non-reverted system adjustment
    linked to this leave request. Caller commits.
    """
    from app.api.v1.attendance_engine import _persist_adjustment, recompute_day

    prior = list(db.scalars(
        select(Adjustment).where(
            Adjustment.leave_request_id == request.id,
            Adjustment.system_generated.is_(True),
            Adjustment.outcome != "revert",
        ).order_by(Adjustment.work_date)
    ).all())
    if not prior:
        return []

    adj_ids: list[uuid.UUID] = []
    for a in prior:
        adj = _persist_adjustment(
            db,
            employee_id=a.employee_id,
            work_date=a.work_date,
            outcome="revert",
            time_in=None,
            time_out=None,
            reason_code="system_correction",
            note=f"Revert of leave request {request.id}",
            created_by=getattr(user, "id", None),
            batch_id=None,
        )
        adj.leave_request_id = request.id
        adj.system_generated = True
        db.add(adj)
        db.flush()
        recompute_day(db, a.employee_id, a.work_date)
        adj_ids.append(adj.id)
    return adj_ids
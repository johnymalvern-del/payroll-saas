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

Stage A period protection
-------------------------
check_days_not_locked now also calls payroll_period_guard's
assert_dates_not_locked, which locks every overlapping PayPeriod row
(open or locked) FOR UPDATE in deterministic id order and raises
day_locked if any is locked. This catches dates whose AttendanceDay.locked
is False or absent (rest days, non-working holidays, un-materialised
dates) that would otherwise slip past the day-level check.

revert_leave_from_attendance also calls check_days_not_locked (defensive
redundant call) so direct callers that do not pre-guard are protected
too. Under the same transaction the second call re-locks the same
PayPeriod rows — a no-op — so no deadlock.

Both loops set db.info["bulk_no_commit"] = True for their duration and
restore the exact previous state in `finally` (present + value, or
absent). This forces _persist_day in attendance_engine to flush rather
than commit per iteration, so the guard's PayPeriod FOR UPDATE lock is
held until the caller's single commit. Without this, the mid-loop commit
in recompute_day would release the lock after the first date and later
dates would be unprotected.
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
from app.services.payroll_period_guard import assert_dates_not_locked


def _sick_codes(db: Session) -> set[str]:
    s = db.scalar(select(PayrollSettings).limit(1))
    if s is None or not s.sick_leave_codes:
        return set()
    return set(s.sick_leave_codes)


def check_days_not_locked(
    db: Session, employee_id: uuid.UUID, work_dates: list[date],
) -> None:
    """Reject if any of work_dates is inside a locked pay period.

    Two checks, both required:
      1. AttendanceDay.locked — the pre-existing day-level flag.
      2. PayPeriod.status == "locked" — the primary protection, which
         works even when no AttendanceDay row exists for a date.
    """
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
    # Period-level guard. Never commits; caller's transaction holds the
    # PayPeriod row locks until it commits or rolls back.
    assert_dates_not_locked(
        db,
        employee_id=employee_id,
        dates=work_dates,
    )


def _set_bulk_no_commit(db: Session) -> tuple[bool, object]:
    """Set db.info['bulk_no_commit'] = True, returning the prior state.

    The returned tuple lets the caller restore the exact prior state in a
    `finally` block, whether the key existed before (then value) or not.
    """
    existed = "bulk_no_commit" in db.info
    prior = db.info.get("bulk_no_commit")
    db.info["bulk_no_commit"] = True
    return existed, prior


def _restore_bulk_no_commit(db: Session, existed: bool, prior: object) -> None:
    if existed:
        db.info["bulk_no_commit"] = prior
    else:
        db.info.pop("bulk_no_commit", None)


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

    bulk_no_commit is set for the loop and restored exactly in finally,
    so recompute_day's internal _persist_day flushes rather than commits,
    and the guard's PayPeriod FOR UPDATE lock is held until the caller's
    commit.
    """
    check_days_not_locked(db, request.employee_id, work_dates)

    from app.api.v1.attendance_engine import _persist_adjustment, recompute_day

    sick = leave_type.code in _sick_codes(db)
    outcome = "sick" if sick else "leave"

    existed, prior = _set_bulk_no_commit(db)
    adj_ids: list[uuid.UUID] = []
    try:
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
    finally:
        _restore_bulk_no_commit(db, existed, prior)
    return adj_ids


def revert_leave_from_attendance(
    db: Session,
    *,
    user,
    request: LeaveRequest,
) -> list[uuid.UUID]:
    """Create revert adjustments for every non-reverted system adjustment
    linked to this leave request. Caller commits.

    Stage A: check_days_not_locked is called at the top (after the prior
    query, before any write) as a defensive redundant guard. The caller
    `cancel_leave_request` already calls check_days_not_locked before the
    first balance mutation, so under the same transaction this re-lock is
    a no-op. It exists so future callers that do not pre-guard are still
    protected.

    bulk_no_commit is set for the loop and restored exactly in finally,
    matching apply_leave_to_attendance.
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

    # Defensive guard. Must run before any write, including before the
    # loop below. Under the current only caller (cancel_leave_request),
    # the same (employee, dates) guard has already been run in the same
    # transaction; this re-lock is a no-op.
    check_days_not_locked(
        db,
        request.employee_id,
        [a.work_date for a in prior],
    )

    existed, prior_bulk = _set_bulk_no_commit(db)
    adj_ids: list[uuid.UUID] = []
    try:
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
    finally:
        _restore_bulk_no_commit(db, existed, prior_bulk)
    return adj_ids
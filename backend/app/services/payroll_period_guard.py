"""Payroll-period lock guard for attendance-related writes.

Purpose
-------
Refuse any attendance-related write whose requested dates overlap a
PayPeriod whose status is "locked". Finalisation sets PayPeriod.status =
"locked"; reopening sets it back to "open". Every attendance write path
must call this guard before writing anything.

Why a dedicated module
----------------------
Callers live across api/v1/adjustments.py, api/v1/exceptions.py,
services/leave_apply.py and api/v1/attendance.py. Putting the guard in
leave_apply would invert the dependency; putting it in payroll_runner
would import a payroll service into attendance endpoints. A small
dedicated module is the smallest safe footprint.

Lock discipline
---------------
The guard takes SELECT ... FOR UPDATE on every PayPeriod row whose
[start_date, end_date] overlaps the requested date range, INCLUDING open
periods. Locking open rows is required: if only locked rows were locked,
a concurrent finalise() could flip an open row to "locked" between the
guard's read and the attendance write, and the write would slip through.
Locking all overlapping rows serialises the guard with finalise()/reopen()
on the same row.

Rows are locked in PayPeriod.id ASC order so the acquisition order is
deterministic. _lock_period() (used by finalise/reopen) locks exactly one
row and never holds one while waiting for another, so guard-vs-finalise
deadlock is not possible. Guard-vs-guard deadlock is prevented by the
ORDER BY. Any future multi-row locker on PayPeriod MUST use the same
ORDER BY PayPeriod.id ASC FOR UPDATE discipline.

The guard never commits. The caller's transaction holds the locks until
its own db.commit() or db.rollback().

Known limitation: concurrent PayPeriod creation
-----------------------------------------------
A PayPeriod insert that covers a date which previously had no period
cannot be prevented by row-locking (there is no row to lock). This race
is documented and deferred to a follow-up DB-level exclusion constraint
(EXCLUDE USING gist on daterange(start_date, end_date, '[]') WITH &&).

PayPeriod is not employee-specific
----------------------------------
employee_id is retained on the signature for interface consistency with
leave_apply.check_days_not_locked, but is NOT used in the query. A
PayPeriod spans all employees. If any locked period covers a requested
date, the write is blocked for every employee on that date.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.pay import PayPeriod


def assert_dates_not_locked(
    db: Session,
    *,
    employee_id: uuid.UUID | None,
    dates: Iterable[date],
) -> None:
    dates_sorted = sorted(set(dates))
    if not dates_sorted:
        return

    min_d = dates_sorted[0]
    max_d = dates_sorted[-1]

    rows = db.execute(
        select(PayPeriod)
        .where(PayPeriod.start_date <= max_d)
        .where(PayPeriod.end_date >= min_d)
        .order_by(PayPeriod.id.asc())
        .with_for_update()
    ).scalars().all()

    locked_dates: set[date] = set()
    for period in rows:
        if period.status != "locked":
            continue
        for d in dates_sorted:
            if period.start_date <= d <= period.end_date:
                locked_dates.add(d)

    if locked_dates:
        ordered = sorted(locked_dates)
        raise AppError(
            "day_locked",
            f"{len(ordered)} day(s) are in a closed pay period: "
            + ", ".join(d.isoformat() for d in ordered),
            409,
            {"dates": [d.isoformat() for d in ordered]},
        )
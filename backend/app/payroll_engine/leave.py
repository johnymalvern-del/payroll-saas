"""Leave engine helpers (Chapter 3, 3B).

compute_cycle_bounds: returns (cycle_start, cycle_end) for an employee
given a leave type and an as-of date.

available_balance: net available for a balance row. `entitled` is the
full grant tracked as informational only; the amount actually reachable
in the current cycle is accrued + carried_in + adjusted - taken -
pending. This avoids the entitled/accrued double-count flagged in
amendment 4.

Accrual service (accrue_all_employees, carry-over) lands in L1d.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.errors import AppError
from app.db.tenant.models.leave import LeaveBalance, LeaveType
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee


_ZERO = Decimal("0")


def _d(x: Decimal | None) -> Decimal:
    return x if x is not None else _ZERO


@dataclass(frozen=True)
class CycleBounds:
    start: date
    end: date


def _calendar_bounds(as_of_date: date) -> CycleBounds:
    return CycleBounds(
        start=date(as_of_date.year, 1, 1),
        end=date(as_of_date.year, 12, 31),
    )


def _anniversary_bounds(hire_date: date, as_of_date: date) -> CycleBounds:
    month = hire_date.month
    day = hire_date.day
    try:
        this_year_anchor = date(as_of_date.year, month, day)
    except ValueError:
        this_year_anchor = date(as_of_date.year, month, 28)
    if this_year_anchor <= as_of_date:
        start = this_year_anchor
    else:
        try:
            start = date(as_of_date.year - 1, month, day)
        except ValueError:
            start = date(as_of_date.year - 1, month, 28)
    try:
        next_anchor = date(start.year + 1, start.month, start.day)
    except ValueError:
        next_anchor = date(start.year + 1, start.month, 28)
    return CycleBounds(start=start, end=next_anchor - timedelta(days=1))


def _fixed_bounds(anchor: date, as_of_date: date) -> CycleBounds:
    start = anchor
    while start <= as_of_date:
        try:
            next_start = date(start.year + 1, start.month, start.day)
        except ValueError:
            next_start = date(start.year + 1, start.month, 28)
        end = next_start - timedelta(days=1)
        if start <= as_of_date <= end:
            return CycleBounds(start=start, end=end)
        start = next_start
    raise AppError(
        "leave_cycle_out_of_range",
        "as_of_date is before the configured fixed cycle anchor",
        422,
    )


def compute_cycle_bounds(
    employee: Employee,
    leave_type: LeaveType,
    settings: PayrollSettings | None,
    as_of_date: date,
) -> CycleBounds:
    cycle = leave_type.cycle
    if cycle == "calendar":
        return _calendar_bounds(as_of_date)
    if cycle == "anniversary":
        return _anniversary_bounds(employee.hire_date, as_of_date)
    if cycle == "fixed":
        anchor = settings.leave_cycle_fixed_anchor if settings else None
        if anchor is None:
            raise AppError(
                "leave_cycle_anchor_not_configured",
                "leave_cycle_fixed_anchor is unset; cycle='fixed' requires it",
                409,
            )
        return _fixed_bounds(anchor, as_of_date)
    raise AppError("invalid_cycle", f"Unknown cycle {cycle!r}", 500)


def available_balance(balance: LeaveBalance) -> Decimal:
    return (
        _d(balance.accrued)
        + _d(balance.carried_in)
        + _d(balance.adjusted)
        - _d(balance.taken)
        - _d(balance.pending)
    )
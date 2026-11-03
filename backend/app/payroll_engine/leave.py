"""Leave engine helpers (Chapter 3, 3B + 3C).

Cycle bounds, availability, balance reservation helpers, approval chain
construction, and per-day computation for requests.

Amendment 1: approval chain resolves role → concrete approver. Self-
approval is never allowed; if all chain roles resolve to the submitter
or are unavailable, escalate to payroll_admin (only if the leave type
sets requires_payroll_admin_final) or raise no_eligible_approver.

Amendment 4: available_balance excludes `entitled` (informational only).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.leave import LeaveBalance, LeaveType
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User


_ZERO = Decimal("0")
_QUANT = Decimal("0.0001")


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


# ---------------------------------------------------------------------------
# Balance reservation (Chapter 3, 3C)
# ---------------------------------------------------------------------------

def reserve_pending(
    db: Session, balance: LeaveBalance, days: Decimal,
) -> None:
    balance.pending = _d(balance.pending) + days
    balance.row_version = balance.row_version + 1
    db.flush()


def release_pending(
    db: Session, balance: LeaveBalance, days: Decimal,
) -> None:
    balance.pending = max(_ZERO, _d(balance.pending) - days)
    balance.row_version = balance.row_version + 1
    db.flush()


def convert_pending_to_taken(
    db: Session, balance: LeaveBalance, days: Decimal,
) -> None:
    balance.pending = max(_ZERO, _d(balance.pending) - days)
    balance.taken = _d(balance.taken) + days
    balance.row_version = balance.row_version + 1
    db.flush()


# ---------------------------------------------------------------------------
# Request day computation
# ---------------------------------------------------------------------------

def compute_request_days(
    db: Session,
    employee: Employee,
    from_date: date,
    to_date: date,
) -> list[tuple[date, Decimal]]:
    from app.api.v1.attendance_engine import _employee_expected

    out: list[tuple[date, Decimal]] = []
    cur = from_date
    while cur <= to_date:
        if _employee_expected(db, employee, cur):
            out.append((cur, Decimal("1")))
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Approval chain (Chapter 3, 3C, amendment 1)
# ---------------------------------------------------------------------------

def resolve_approver_for_role(
    db: Session, employee: Employee, role: str,
) -> User | None:
    if role == "manager":
        if employee.manager_id is None:
            return None
        return db.scalar(
            select(User).where(
                User.employee_id == employee.manager_id,
                User.is_active.is_(True),
            )
        )
    if role == "hr":
        return db.scalar(
            select(User)
            .where(User.role == "hr", User.is_active.is_(True))
            .limit(1)
        )
    if role == "payroll_admin":
        return db.scalar(
            select(User)
            .where(User.role == "payroll_admin", User.is_active.is_(True))
            .limit(1)
        )
    return None


def build_approval_chain(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    submitter: User,
) -> list[str]:
    """Ordered list of approver roles for the request.

    Returns [] when leave_type.requires_approval is False (caller auto-
    approves). Otherwise excludes self-approvers; if every role resolves
    to self or is unavailable, either escalates to payroll_admin (when
    requires_payroll_admin_final) or raises no_eligible_approver.
    """
    if not leave_type.requires_approval:
        return []

    chain = list(leave_type.approval_chain or [])
    eligible: list[str] = []
    for role in chain:
        approver = resolve_approver_for_role(db, employee, role)
        if approver is None:
            continue
        if approver.id == submitter.id:
            continue
        eligible.append(role)

    if not eligible:
        if leave_type.requires_payroll_admin_final:
            eligible = ["payroll_admin"]
        else:
            raise AppError(
                "no_eligible_approver",
                "No eligible approvers for this request after excluding "
                "self-approval. Set requires_payroll_admin_final or adjust "
                "the leave type's approval_chain.",
                409,
            )
    elif (
        leave_type.requires_payroll_admin_final
        and "payroll_admin" not in eligible
    ):
        eligible.append("payroll_admin")

    return eligible
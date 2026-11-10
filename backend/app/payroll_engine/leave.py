"""Leave engine helpers (Chapter 3, 3B + 3C).

Cycle bounds, availability, balance reservation helpers, approval chain
construction, per-day computation for requests, and the accrual service.

Amendment 1: approval chain resolves role -> concrete approver. Self-
approval is never allowed; if every role resolves to self or unavailable,
escalate to payroll_admin (only if the leave type sets
requires_payroll_admin_final) or raise no_eligible_approver.

Amendment 4: available_balance excludes `entitled` (informational only).

B-L5a: accrue_all_employees takes a transaction-scoped advisory lock at the
top (per tenant). Serialises concurrent accrual runs and prevents the
"read existing period keys, then write missing rows" race that could
otherwise double-write a period under concurrent execution. Lock is
released by the existing db.commit() at the end of the function (or any
rollback).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.leave import LeaveBalance, LeaveBalanceLedger, LeaveType
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
# Accrual (3B.3, amendment 3)
# ---------------------------------------------------------------------------

def _period_keys_for(
    leave_type: LeaveType,
    bounds: CycleBounds,
    as_of_date: date,
) -> list[str]:
    if leave_type.accrual_method == "fixed":
        return [f"fixed:{bounds.start.isoformat()}"]
    keys: list[str] = []
    cur = date(bounds.start.year, bounds.start.month, 1)
    stop = date(bounds.end.year, bounds.end.month, 1)
    as_of_month = date(as_of_date.year, as_of_date.month, 1)
    if as_of_month < stop:
        stop = as_of_month
    while cur <= stop:
        keys.append(f"{cur.year}-{cur.month:02d}")
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return keys


def _accrual_amount_for(leave_type: LeaveType) -> Decimal:
    if leave_type.accrual_amount is None:
        return _ZERO
    if leave_type.accrual_method == "annual":
        return (_d(leave_type.accrual_amount) / Decimal(12)).quantize(_QUANT)
    if leave_type.accrual_method == "monthly":
        return _d(leave_type.accrual_amount)
    if leave_type.accrual_method == "fixed":
        return _d(leave_type.accrual_amount)
    return _ZERO


def _carry_in_for_prior_cycle(
    db: Session,
    employee: Employee,
    leave_type: LeaveType,
    bounds: CycleBounds,
) -> Decimal:
    prior = db.scalar(
        select(LeaveBalance)
        .where(
            LeaveBalance.employee_id == employee.id,
            LeaveBalance.leave_type_id == leave_type.id,
            LeaveBalance.cycle_end == bounds.start - timedelta(days=1),
        )
        .order_by(LeaveBalance.cycle_start.desc())
        .limit(1)
    )
    if prior is None:
        return _ZERO
    prior_avail = available_balance(prior)
    if prior_avail <= _ZERO:
        return _ZERO
    if leave_type.max_carryover is None:
        return prior_avail
    return min(prior_avail, leave_type.max_carryover)


def accrue_all_employees(db: Session, as_of_date: date) -> dict:
    """Materialise accruals. Idempotent per (employee, type, cycle, period_key)
    via LeaveBalanceLedger.reason = "accrual:<period_key>"."""
    # B-L5a: transaction-scoped advisory lock, tenant-wide. Serialises
    # concurrent accrual runs. Held until the existing db.commit() at the
    # end of this function (or any rollback). Prevents the race between the
    # "read existing accrual:* keys" step and the "write missing rows" step
    # that could otherwise double-write a period under concurrent execution.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": "leave_accrual_run"},
    )
    settings = db.scalar(select(PayrollSettings).limit(1))
    employees = list(
        db.scalars(
            select(Employee).where(Employee.status != "terminated")
        ).all()
    )
    types = list(
        db.scalars(
            select(LeaveType).where(LeaveType.is_active.is_(True))
        ).all()
    )

    rows_written = 0
    employees_touched = 0

    for emp in employees:
        wrote_for_emp = False
        for t in types:
            if t.accrual_method == "none":
                continue
            try:
                bounds = compute_cycle_bounds(emp, t, settings, as_of_date)
            except AppError:
                continue

            balance = db.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == emp.id,
                    LeaveBalance.leave_type_id == t.id,
                    LeaveBalance.cycle_start == bounds.start,
                )
            )
            if balance is None:
                carry = _carry_in_for_prior_cycle(db, emp, t, bounds)
                entitled = (
                    _d(t.accrual_amount)
                    if t.accrual_method in ("annual", "fixed")
                    else _ZERO
                )
                balance = LeaveBalance(
                    employee_id=emp.id,
                    leave_type_id=t.id,
                    cycle_start=bounds.start,
                    cycle_end=bounds.end,
                    entitled=entitled,
                    accrued=_ZERO,
                    taken=_ZERO,
                    pending=_ZERO,
                    carried_in=carry,
                    adjusted=_ZERO,
                    row_version=1,
                )
                db.add(balance)
                db.flush()

            needed = _period_keys_for(t, bounds, as_of_date)
            if not needed:
                continue

            existing = set(
                db.scalars(
                    select(LeaveBalanceLedger.reason).where(
                        LeaveBalanceLedger.employee_id == emp.id,
                        LeaveBalanceLedger.leave_type_id == t.id,
                        LeaveBalanceLedger.reason.like("accrual:%"),
                    )
                ).all()
            )

            amount = _accrual_amount_for(t)
            if amount <= _ZERO:
                continue

            for pk in needed:
                reason_key = f"accrual:{pk}"
                if reason_key in existing:
                    continue
                db.add(
                    LeaveBalanceLedger(
                        employee_id=emp.id,
                        leave_type_id=t.id,
                        delta=amount,
                        reason=reason_key,
                        reference_id=None,
                        created_by_user_id=None,
                    )
                )
                balance.accrued = (balance.accrued or _ZERO) + amount
                balance.row_version = balance.row_version + 1
                rows_written += 1
                wrote_for_emp = True

        if wrote_for_emp:
            employees_touched += 1

    if settings is not None:
        settings.last_accrual_run_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "employees_touched": employees_touched,
        "rows_written": rows_written,
        "as_of": as_of_date,
    }


# ---------------------------------------------------------------------------
# Balance reservation (3C)
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
# Request day computation (3C)
# ---------------------------------------------------------------------------

def compute_request_days(
    db: Session,
    employee: Employee,
    from_date: date,
    to_date: date,
) -> list[tuple[date, Decimal]]:
    from app.api.v1.attendance_engine import _employee_expected
    from app.db.tenant.models.attendance import EmployeeWorkPattern

    has_wp = getattr(employee, "work_pattern_id", None) is not None
    if not has_wp:
        ewp_id = db.scalar(
            select(EmployeeWorkPattern.id)
            .where(EmployeeWorkPattern.employee_id == employee.id)
            .limit(1)
        )
        has_wp = ewp_id is not None
    if not has_wp:
        return []

    out: list[tuple[date, Decimal]] = []
    cur = from_date
    while cur <= to_date:
        if _employee_expected(db, employee, cur)[0]:
            out.append((cur, Decimal("1")))
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Approval chain (3C, amendment 1)
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
    if not leave_type.requires_approval:
        return []

    chain = list(leave_type.approval_chain or [])
    eligible: list[str] = []
    for role in chain:
        approver = resolve_approver_for_role(db, employee, role)
        if approver is None:
            continue
        if approver.employee_id == employee.id:
            continue
        eligible.append(role)

    if not eligible:
        if leave_type.requires_payroll_admin_final:
            eligible = ["payroll_admin"]
        else:
            raise AppError(
                "no_eligible_approver",
                "No eligible approvers after excluding self-approval. Set "
                "requires_payroll_admin_final or adjust the leave type's "
                "approval_chain.",
                409,
            )
    elif (
        leave_type.requires_payroll_admin_final
        and "payroll_admin" not in eligible
    ):
        eligible.append("payroll_admin")

    return eligible
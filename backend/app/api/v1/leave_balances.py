"""Leave balance read + admin adjustment (Chapter 3, 3B.2).

B-L5a: adjust_leave_balance takes a transaction-scoped PostgreSQL advisory
lock keyed to the exact (employee_id, leave_type_id, cycle_start) triple
before the balance lookup, so concurrent first-time adjustments for the
same scope serialise and cannot create duplicate rows or lose deltas. The
existing-row path additionally uses SELECT ... FOR UPDATE. The lock is
released automatically when the surrounding transaction commits or rolls
back (existing db.commit() at the end of the handler).
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import or_, select, text

from app.api.deps import TenantDbDep
from app.api.v1.leave_balances_schemas import (
    BalanceAdjustIn,
    BalanceAdjustOut,
    LeaveBalanceListOut,
    LeaveBalanceOut,
)
from app.core.auth_deps import get_current_user
from app.core.errors import AppError
from app.core.permissions import Permission, check_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.leave import (
    LeaveBalance,
    LeaveBalanceLedger,
    LeaveType,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.payroll_engine.leave import available_balance, compute_cycle_bounds
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/leave/balances", tags=["leave-balances"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_ZERO = Decimal("0")


def _not_found() -> AppError:
    return AppError("not_found", "Leave balance not found", 404)


def _to_out(row: LeaveBalance) -> LeaveBalanceOut:
    out = LeaveBalanceOut.model_validate(row)
    out.available = available_balance(row)
    return out


def _encode_cursor(created_at: datetime, bid: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(bid)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        ts = datetime.fromisoformat(payload["c"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, uuid.UUID(payload["i"])
    except Exception:
        raise AppError(
            "invalid_cursor", "The pagination cursor is malformed", 400
        ) from None


def _require_any_view(user: Any) -> None:
    if check_permission(user, Permission.LEAVE_APPROVE):
        return
    if check_permission(user, Permission.SELF_VIEW):
        return
    raise AppError(
        "forbidden", "Not permitted to view leave balances", 403
    )


def _is_self_only(user: Any) -> bool:
    return (
        check_permission(user, Permission.SELF_VIEW)
        and not check_permission(user, Permission.LEAVE_APPROVE)
    )


@router.get("", response_model=LeaveBalanceListOut)
def list_leave_balances(
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
    employee_id: uuid.UUID | None = Query(None),
    leave_type_id: uuid.UUID | None = Query(None),
    cycle_start_gte: date | None = Query(None),
    cycle_start_lte: date | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> LeaveBalanceListOut:
    _require_any_view(user)

    settings_for_run = db.scalar(select(PayrollSettings).limit(1))
    last_run = settings_for_run.last_accrual_run_at if settings_for_run else None
    if last_run is not None and last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    stale = last_run is None or (datetime.now(timezone.utc) - last_run) > timedelta(days=1)

    q = select(LeaveBalance)

    if _is_self_only(user):
        own = getattr(user, "employee_id", None)
        if own is None:
            raise AppError(
                "no_employee_record",
                "User has no employee record",
                404,
            )
        q = q.where(LeaveBalance.employee_id == own)
    else:
        if employee_id is not None:
            q = q.where(LeaveBalance.employee_id == employee_id)
        q = apply_scope(q, user, db, model=LeaveBalance)

    if leave_type_id is not None:
        q = q.where(LeaveBalance.leave_type_id == leave_type_id)
    if cycle_start_gte is not None:
        q = q.where(LeaveBalance.cycle_start >= cycle_start_gte)
    if cycle_start_lte is not None:
        q = q.where(LeaveBalance.cycle_start <= cycle_start_lte)

    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(
            or_(
                LeaveBalance.created_at > ts,
                (LeaveBalance.created_at == ts) & (LeaveBalance.id > cid),
            )
        )

    q = q.order_by(
        LeaveBalance.created_at.asc(), LeaveBalance.id.asc()
    ).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return LeaveBalanceListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        accrued_as_of=last_run,
        accrual_stale=stale,
    )


@router.get("/{balance_id}", response_model=LeaveBalanceOut)
def get_leave_balance(
    balance_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveBalanceOut:
    _require_any_view(user)
    row = db.get(LeaveBalance, balance_id)
    if row is None:
        raise _not_found()
    if _is_self_only(user):
        own = getattr(user, "employee_id", None)
        if own is None or row.employee_id != own:
            raise _not_found()
    else:
        try:
            assert_in_scope(user, row.employee_id, db)
        except ScopeViolation:
            raise _not_found() from None
    return _to_out(row)


@router.post("/adjust", response_model=BalanceAdjustOut)
def adjust_leave_balance(
    payload: BalanceAdjustIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> BalanceAdjustOut:
    can_approve = check_permission(user, Permission.LEAVE_APPROVE)
    can_finalise = check_permission(user, Permission.PAYROLL_FINALISE)
    if not (can_approve or can_finalise):
        raise AppError(
            "forbidden",
            "Not permitted to adjust leave balances",
            status.HTTP_403_FORBIDDEN,
        )

    employee = db.get(Employee, payload.employee_id)
    if employee is None:
        raise AppError("not_found", "Employee not found", 404)
    try:
        assert_in_scope(user, employee.id, db)
    except ScopeViolation:
        raise AppError("not_found", "Employee not found", 404) from None

    leave_type = db.get(LeaveType, payload.leave_type_id)
    if leave_type is None:
        raise AppError("not_found", "Leave type not found", 404)

    settings = db.scalar(select(PayrollSettings).limit(1))

    # B-L5a: determine target cycle_start BEFORE taking the lock, so the lock
    # key fully identifies the row we will read or create. Preserves existing
    # behaviour: caller-supplied cycle_start must already exist (404 if not);
    # the implicit-current-cycle path creates the row if missing.
    if payload.cycle_start is not None:
        target_cycle_start = payload.cycle_start
        target_cycle_end: date | None = None
        create_if_missing = False
    else:
        bounds = compute_cycle_bounds(
            employee, leave_type, settings, date.today()
        )
        target_cycle_start = bounds.start
        target_cycle_end = bounds.end
        create_if_missing = True

    # B-L5a: transaction-scoped advisory lock keyed to the exact
    # (employee, leave_type, cycle_start) triple. Serialises concurrent
    # adjustments for the same scope, including the first-time case where
    # no LeaveBalance row exists yet (FOR UPDATE alone cannot cover that).
    # Released automatically when this transaction commits or rolls back.
    lock_key = (
        f"leave_balance:{employee.id}:{leave_type.id}:"
        f"{target_cycle_start.isoformat()}"
    )
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": lock_key},
    )

    # Existing-row path: also take a row-level FOR UPDATE. Defense in depth —
    # any future code path that reaches this row without going through the
    # advisory lock still sees a consistent view.
    balance = db.scalar(
        select(LeaveBalance)
        .where(
            LeaveBalance.employee_id == employee.id,
            LeaveBalance.leave_type_id == leave_type.id,
            LeaveBalance.cycle_start == target_cycle_start,
        )
        .with_for_update()
    )

    if balance is None:
        if not create_if_missing:
            raise AppError(
                "not_found",
                "Leave balance not found for the requested cycle",
                404,
            )
        balance = LeaveBalance(
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            cycle_start=target_cycle_start,
            cycle_end=target_cycle_end,
            entitled=_ZERO,
            accrued=_ZERO,
            taken=_ZERO,
            pending=_ZERO,
            carried_in=_ZERO,
            adjusted=_ZERO,
            row_version=1,
        )
        db.add(balance)
        db.flush()

    closed = balance.cycle_end < date.today()
    if closed and not can_finalise:
        raise AppError(
            "forbidden",
            "Adjusting a closed cycle requires PAYROLL_FINALISE",
            status.HTTP_403_FORBIDDEN,
            {"cycle_end": balance.cycle_end.isoformat()},
        )

    old_snapshot = _to_out(balance).model_dump(mode="json")
    balance.adjusted = (balance.adjusted or _ZERO) + payload.delta
    balance.row_version = balance.row_version + 1
    db.flush()

    if not leave_type.allow_negative:
        avail = available_balance(balance)
        if avail < _ZERO:
            db.rollback()
            raise AppError(
                "insufficient_balance",
                f"Resulting available balance would be {avail} (negative "
                f"not allowed for this leave type)",
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                {"available": str(avail)},
            )

    ledger = LeaveBalanceLedger(
        employee_id=employee.id,
        leave_type_id=leave_type.id,
        delta=payload.delta,
        reason="adjustment",
        reference_id=None,
        created_by_user_id=getattr(user, "id", None),
    )
    db.add(ledger)
    db.flush()

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_balance",
        entity_id=str(balance.id),
        action="leave_balance.adjust",
        old_value=redact_for_audit(old_snapshot),
        new_value=redact_for_audit({
            "delta": str(payload.delta),
            "reason": payload.reason,
            "ledger_entry_id": str(ledger.id),
            "balance": _to_out(balance).model_dump(mode="json"),
        }),
    ))
    db.commit()
    db.refresh(balance)
    return BalanceAdjustOut(
        balance=_to_out(balance),
        ledger_entry_id=ledger.id,
    )
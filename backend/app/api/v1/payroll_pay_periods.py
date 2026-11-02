"""Pay period endpoints (Chapter 4 Bundle 004b-a + Chapter 4H B-4d + B-3).

B-3 adds:
  GET /payroll/pay-periods/{period_id}/preview/{employee_id}
    Read-only single-employee preview from the latest persisted run.
"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_pay_periods_schemas import (
    FinaliseIn,
    PayPeriodIn,
    PayPeriodListOut,
    PayPeriodOut,
    PayrollRunOut,
    PreviewEmployeeDeductionOut,
    PreviewEmployeeLineOut,
    PreviewEmployeeOut,
    PreviewOut,
    PreviewSummaryRow,
    ReopenIn,
    ReopenLogOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.pay import (
    PayPeriod, PayrollRun, Payslip, PayslipLine, PeriodReopenLog,
)
from app.db.tenant.models.people import Employee
from app.services.payroll_runner import finalise, reopen, run_preview

router = APIRouter(prefix="/payroll/pay-periods", tags=["payroll-pay-periods"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _encode_cursor(uid: uuid.UUID) -> str:
    raw = json.dumps({"i": str(uid)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> uuid.UUID:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return uuid.UUID(json.loads(raw)["i"])
    except Exception:
        raise AppError("invalid_cursor", "The pagination cursor is malformed", 400) from None


def _preview_row_from_payslip(payslip: Payslip, employee: Employee) -> PreviewSummaryRow:
    ctx = payslip.calculation_context or {}
    warns = ctx.get("attendance_warnings") or []
    if not isinstance(warns, list):
        warns = []
    return PreviewSummaryRow(
        employee_id=employee.id,
        employee_code=employee.employee_code,
        employee_name=f"{employee.first_name} {employee.last_name}".strip(),
        gross=payslip.gross,
        paye=payslip.paye,
        net=payslip.net,
        warnings=[str(w) for w in warns],
    )


@router.post("", response_model=PayPeriodOut, status_code=201)
def create_pay_period(
    body: PayPeriodIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> PayPeriodOut:
    dup = db.scalar(select(PayPeriod).where(PayPeriod.period_key == body.period_key))
    if dup is not None:
        raise AppError("period_key_taken", f"period_key {body.period_key!r} already exists", 409)
    if body.end_date < body.start_date:
        raise AppError("invalid_range", "end_date must be on or after start_date", 422)
    if body.pay_date < body.end_date:
        raise AppError("invalid_pay_date", "pay_date must be on or after end_date", 422)
    period = PayPeriod(
        id=uuid.uuid4(),
        period_key=body.period_key,
        start_date=body.start_date,
        end_date=body.end_date,
        pay_date=body.pay_date,
        status="open",
        cutoff_at=body.cutoff_at,
    )
    db.add(period)
    db.commit()
    return PayPeriodOut.model_validate(period)


@router.get("", response_model=PayPeriodListOut)
def list_pay_periods(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    status: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> PayPeriodListOut:
    q = select(PayPeriod)
    if status is not None:
        q = q.where(PayPeriod.status == status)
    if cursor is not None:
        q = q.where(PayPeriod.id > _decode_cursor(cursor))
    q = q.order_by(PayPeriod.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return PayPeriodListOut(
        items=[PayPeriodOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/{period_id}", response_model=PayPeriodOut)
def get_pay_period(
    period_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> PayPeriodOut:
    row = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if row is None:
        raise AppError("not_found", "Pay period not found", 404)
    return PayPeriodOut.model_validate(row)


@router.post("/{period_id}/preview", response_model=PreviewOut)
def preview_pay_period(
    period_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> PreviewOut:
    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)

    run = run_preview(db, user, period)
    db.commit()

    q = (
        select(Payslip, Employee)
        .join(Employee, Employee.id == Payslip.employee_id)
        .where(Payslip.payroll_run_id == run.id)
        .order_by(Payslip.id.asc())
    )
    if cursor is not None:
        q = q.where(Payslip.id > _decode_cursor(cursor))
    q = q.limit(limit + 1)
    pairs = list(db.execute(q).all())
    next_cursor = None
    if len(pairs) > limit:
        pairs = pairs[:limit]
        next_cursor = _encode_cursor(pairs[-1][0].id)

    items = [_preview_row_from_payslip(p, e) for p, e in pairs]

    return PreviewOut(
        run_id=run.id,
        revision=run.revision,
        status=run.status,
        unacknowledged_formulas=run.rules_snapshot.get("unacknowledged_formulas", []),
        items=items,
        next_cursor=next_cursor,
    )


@router.get("/{period_id}/preview/{employee_id}", response_model=PreviewEmployeeOut)
def preview_employee(
    period_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> PreviewEmployeeOut:
    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)

    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Employee not found", 404)

    employee = db.scalar(select(Employee).where(Employee.id == employee_id))
    if employee is None:
        raise AppError("not_found", "Employee not found", 404)

    run = db.scalar(
        select(PayrollRun)
        .where(PayrollRun.pay_period_id == period.id)
        .order_by(PayrollRun.revision.desc(), PayrollRun.started_at.desc())
        .limit(1)
    )
    if run is None:
        raise AppError(
            "no_preview_run",
            "No payroll run exists for this period; call POST /preview first",
            409,
        )

    ps = db.scalar(
        select(Payslip).where(
            Payslip.payroll_run_id == run.id,
            Payslip.employee_id == employee_id,
        )
    )
    if ps is None:
        raise AppError(
            "not_found",
            "No payslip for this employee in the current run",
            404,
        )

    lines_records = list(db.scalars(
        select(PayslipLine)
        .where(PayslipLine.payslip_id == ps.id)
        .order_by(PayslipLine.sort_order.asc())
    ).all())

    earning_lines = [
        PreviewEmployeeLineOut(
            earning_type_code=(l.source_ref or {}).get("earning_type_code", ""),
            earning_type_name=l.label,
            rate_source=(l.source_ref or {}).get("rate_source"),
            amount=l.amount,
            minutes=(l.source_ref or {}).get("minutes"),
        )
        for l in lines_records if l.line_type == "earning"
    ]
    deduction_lines = [
        PreviewEmployeeDeductionOut(
            deduction_type_code=(l.source_ref or {}).get("deduction_type_code", ""),
            deduction_type_name=l.label,
            amount=l.amount,
        )
        for l in lines_records
        if l.line_type == "deduction" and not (l.source_ref or {}).get("deferred")
    ]

    ctx = ps.calculation_context or {}
    warns = ctx.get("attendance_warnings") or []
    if not isinstance(warns, list):
        warns = []

    return PreviewEmployeeOut(
        employee_id=employee.id,
        employee_code=employee.employee_code,
        employee_name=f"{employee.first_name} {employee.last_name}".strip(),
        pay_period_id=period.id,
        revision=run.revision,
        status=run.status,
        gross=ps.gross,
        paye=ps.paye,
        net=ps.net,
        warnings=[str(w) for w in warns],
        lines=earning_lines,
        deductions=deduction_lines,
    )


@router.post("/{period_id}/finalise", response_model=PayrollRunOut)
def finalise_pay_period(
    period_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
    body: FinaliseIn | None = None,
) -> PayrollRunOut:
    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)
    ack = body.ack_open_exceptions_reason if body is not None else None
    run = finalise(db, user, period, ack_open_exceptions_reason=ack)
    db.commit()
    return PayrollRunOut.model_validate(run)


@router.post("/{period_id}/reopen", response_model=ReopenLogOut)
def reopen_pay_period(
    period_id: uuid.UUID,
    body: ReopenIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_REOPEN))],
) -> ReopenLogOut:
    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)
    log = reopen(db, user, period, body.reason)
    db.commit()
    return ReopenLogOut.model_validate(log)


@router.get("/{period_id}/reopen-log", response_model=list[ReopenLogOut])
def get_reopen_log(
    period_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> list[ReopenLogOut]:
    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)
    rows = list(db.scalars(
        select(PeriodReopenLog).where(PeriodReopenLog.pay_period_id == period_id)
        .order_by(PeriodReopenLog.occurred_at.asc())
    ).all())
    return [ReopenLogOut.model_validate(r) for r in rows]

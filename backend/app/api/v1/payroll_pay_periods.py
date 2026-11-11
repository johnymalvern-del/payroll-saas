"""Pay period endpoints (Chapter 4 Bundle 004b-a + Chapter 4H B-4d + B-3).

B-3 adds:
  GET /payroll/pay-periods/{period_id}/preview/{employee_id}
    Read-only single-employee preview from the latest persisted run.

M5 adds:
  GET /payroll/pay-periods/{period_id}/salary-sheet
    Company-wide read-only salary sheet for a period, backed by persisted
    Payslip rows. Preview figures when the period is open, finalised
    figures when the period is locked. Basic vs Additional earnings are
    derived only by summing already-persisted PayslipLine rows.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select

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
from app.api.v1.payroll_salary_sheet_schemas import SalarySheetOut, SalarySheetRow
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.pay import (
    PayPeriod, PayrollRun, Payslip, PayslipLine, PeriodReopenLog,
)
from app.db.tenant.models.people import Employee
from app.services.payroll_runner import (
    finalise,
    reopen,
    run_preview,
    run_preview_for_employee_as_of,
)

router = APIRouter(prefix="/payroll/pay-periods", tags=["payroll-pay-periods"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_ZERO = Decimal("0")


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


def _encode_sheet_cursor(employee_code: str, ps_id: uuid.UUID) -> str:
    """Composite cursor for the salary sheet's (employee_code, payslip_id) order."""
    raw = json.dumps(
        {"c": employee_code, "i": str(ps_id)}, separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_sheet_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        return payload["c"], uuid.UUID(payload["i"])
    except Exception:
        raise AppError(
            "invalid_cursor", "The pagination cursor is malformed", 400,
        ) from None


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


def _preview_as_of(
    db,
    user,
    period_id: uuid.UUID,
    employee_id: uuid.UUID,
    as_of: date | None = None,
) -> PreviewEmployeeOut:
    """Read-only payslip-so-far for one employee, as of `as_of`.

    Used by GET .../preview/{employee_id}?as_of=YYYY-MM-DD. Does not
    persist anything (no PayrollRun, no Payslip, no audit). Delegates to
    payroll_runner.run_preview_for_employee_as_of.
    """
    pay_period = db.get(PayPeriod, period_id)
    if pay_period is None:
        raise AppError("record_not_found", "Pay period not found", 404)
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError("record_not_found", "Employee not found", 404)
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Employee not found", 404) from None
    data = run_preview_for_employee_as_of(
        db, user, pay_period, employee, as_of,
    )
    return PreviewEmployeeOut(**data)


@router.get("/{period_id}/preview/{employee_id}", response_model=PreviewEmployeeOut)
def preview_employee(
    period_id: uuid.UUID,
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    as_of: date | None = None,
) -> PreviewEmployeeOut:
    if as_of is not None:
        return _preview_as_of(db, user, period_id, employee_id, as_of)
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


@router.get("/{period_id}/salary-sheet", response_model=SalarySheetOut)
def get_salary_sheet(
    period_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    q: str | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> SalarySheetOut:
    """M5 — read-only monthly salary sheet.

    Reads persisted Payslip rows for the period; never calls the pipeline.
    Preview payslips for an open period, current payslips for a locked one.
    basic_earnings and additional_earnings are sums of PayslipLine amounts
    split on source_ref.earning_type_code == 'BASE_MONTHLY'. Every other
    figure is copied from Payslip, so it matches the payslip PDF exactly.

    Ordering is (Employee.employee_code ASC, Payslip.id ASC). The cursor
    encodes both fields and the filter is a compound predicate matching
    that order — Payslip.id alone is insufficient because it is a random
    UUID and does not track the employee_code-sorted position.
    """
    # Normalise FastAPI Query defaults. When this handler is called through
    # HTTP, FastAPI has already resolved these to plain str/int/None. When
    # unit tests call the function directly, the parameter defaults are
    # fastapi.params.Query objects rather than their resolved values; the
    # isinstance checks below restore the intended defaults so the body of
    # the function sees exactly what it would see over HTTP.
    q = q if isinstance(q, str) else None
    cursor = cursor if isinstance(cursor, str) else None
    limit = limit if isinstance(limit, int) else _DEFAULT_LIMIT

    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)

    if period.status == "locked":
        payslip_status = "current"
        figures_state = "finalised"
    else:
        payslip_status = "preview"
        figures_state = "preview"

    base = (
        select(Payslip, Employee)
        .join(Employee, Employee.id == Payslip.employee_id)
        .where(
            Payslip.pay_period_id == period.id,
            Payslip.status == payslip_status,
        )
    )
    base = apply_scope(base, user, db, model=Payslip)

    if q:
        needle = f"%{q.strip()}%"
        base = base.where(
            or_(
                Employee.employee_code.ilike(needle),
                Employee.first_name.ilike(needle),
                Employee.last_name.ilike(needle),
            )
        )

    if cursor is not None:
        c_code, c_id = _decode_sheet_cursor(cursor)
        base = base.where(
            or_(
                Employee.employee_code > c_code,
                (Employee.employee_code == c_code) & (Payslip.id > c_id),
            )
        )

    base = base.order_by(Employee.employee_code.asc(), Payslip.id.asc()).limit(limit + 1)
    pairs = list(db.execute(base).all())
    next_cursor = None
    if len(pairs) > limit:
        pairs = pairs[:limit]
        last_ps, last_emp = pairs[-1]
        next_cursor = _encode_sheet_cursor(last_emp.employee_code, last_ps.id)

    # Sum PayslipLine rows for Basic vs Additional. One batched query.
    payslip_ids = [p.id for p, _e in pairs]
    split_by_ps: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    if payslip_ids:
        line_rows = db.execute(
            select(
                PayslipLine.payslip_id,
                PayslipLine.source_ref,
                PayslipLine.amount,
            ).where(
                PayslipLine.payslip_id.in_(payslip_ids),
                PayslipLine.line_type == "earning",
            )
        ).all()
        for ps_id, source_ref, amount in line_rows:
            code = (source_ref or {}).get("earning_type_code")
            basic, additional = split_by_ps.get(ps_id, (_ZERO, _ZERO))
            if code == "BASE_MONTHLY":
                basic = basic + Decimal(amount)
            else:
                additional = additional + Decimal(amount)
            split_by_ps[ps_id] = (basic, additional)

    items: list[SalarySheetRow] = []
    run_id: uuid.UUID | None = None
    revision: int | None = None
    for p, e in pairs:
        if run_id is None:
            run_id = p.payroll_run_id
            revision = p.revision
        basic, additional = split_by_ps.get(p.id, (_ZERO, _ZERO))
        items.append(SalarySheetRow(
            employee_id=e.id,
            employee_code=e.employee_code,
            employee_name=f"{e.first_name} {e.last_name}".strip(),
            payslip_id=p.id,
            payslip_status=p.status,
            revision=p.revision,
            basic_earnings=basic,
            additional_earnings=additional,
            gross=p.gross,
            pre_tax_deductions=p.pre_tax_deductions,
            taxable_income=p.taxable_income,
            paye=p.paye,
            uif_employee=p.uif_employee,
            uif_employer=p.uif_employer,
            sdl=p.sdl,
            other_deductions=p.other_deductions,
            reimbursements=p.reimbursements,
            net=p.net,
        ))

    if figures_state == "preview" and not items and not next_cursor:
        figures_state = "no_preview"

    return SalarySheetOut(
        pay_period_id=period.id,
        pay_period_key=period.period_key,
        pay_period_status=period.status,
        figures_state=figures_state,
        run_id=run_id,
        revision=revision,
        items=items,
        next_cursor=next_cursor,
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
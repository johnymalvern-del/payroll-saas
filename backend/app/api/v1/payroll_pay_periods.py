"""Pay period endpoints (Chapter 4, Bundle 004b-a).

6 endpoints:
  POST   /payroll/pay-periods                          PAYROLL_FINALISE
  GET    /payroll/pay-periods                          PAYROLL_PREVIEW
  GET    /payroll/pay-periods/{id}                     PAYROLL_PREVIEW
  POST   /payroll/pay-periods/{id}/preview             PAYROLL_PREVIEW  (persisted per F4)
  POST   /payroll/pay-periods/{id}/finalise            PAYROLL_FINALISE
  POST   /payroll/pay-periods/{id}/reopen              PAYROLL_REOPEN
  GET    /payroll/pay-periods/{id}/reopen-log          PAYROLL_PREVIEW
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
    PayPeriodIn,
    PayPeriodListOut,
    PayPeriodOut,
    PayrollRunOut,
    PreviewOut,
    PreviewSummaryRow,
    ReopenIn,
    ReopenLogOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.pay import PayPeriod, PayrollRun, Payslip, PeriodReopenLog
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

    items = [
        PreviewSummaryRow(
            employee_id=e.id,
            employee_code=e.employee_code,
            employee_name=f"{e.first_name} {e.last_name}".strip(),
            gross=p.gross, paye=p.paye, net=p.net, warnings=[],
        )
        for p, e in pairs
    ]

    return PreviewOut(
        run_id=run.id,
        revision=run.revision,
        status=run.status,
        unacknowledged_formulas=run.rules_snapshot.get("unacknowledged_formulas", []),
        items=items,
        next_cursor=next_cursor,
    )


@router.post("/{period_id}/finalise", response_model=PayrollRunOut)
def finalise_pay_period(
    period_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_FINALISE))],
) -> PayrollRunOut:
    period = db.scalar(select(PayPeriod).where(PayPeriod.id == period_id))
    if period is None:
        raise AppError("not_found", "Pay period not found", 404)
    run = finalise(db, user, period)
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

# END OF FILE

"""Payslip read endpoints (Chapter 4, Bundle 004b-b).

Four endpoints:
  GET /payroll/payslips                      list (excludes preview rows)
  GET /payroll/payslips/{id}                 get one (scope applied)
  GET /payroll/payslips/{id}/explain         header + lines + snapshot
  GET /payroll/payslips/{id}/pdf             bytes on demand

Permission gates on PAYSLIP_VIEW (granted to all five roles per the current
matrix). Scope enforcement via apply_scope / assert_in_scope decides which
rows a manager or auditor may see; per-F14 role refinements are a follow-up.

Storage is not used: PDF is rendered on demand and returned as bytes.

Query parameters on list_payslips use the Annotated[..., Query()] = <default>
form so the function is callable from both FastAPI (query strings) and plain
Python (unit tests) without leaking Query marker objects into arithmetic.
"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_payslips_schemas import (
    PayslipExplainOut,
    PayslipLineOut,
    PayslipListOut,
    PayslipOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.pay import PayPeriod, Payslip, PayslipLine, PayrollRun
from app.db.tenant.models.people import Employee
from app.services.payroll_pdf import render_payslip_pdf

router = APIRouter(prefix="/payroll/payslips", tags=["payroll-payslips"])

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


def _load_payslip_scoped(db, user, payslip_id: uuid.UUID) -> Payslip:
    row = db.scalar(select(Payslip).where(Payslip.id == payslip_id))
    if row is None or row.status == "preview":
        raise AppError("not_found", "Payslip not found", 404)
    try:
        assert_in_scope(user, row.employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Payslip not found", 404)
    return row


@router.get("", response_model=PayslipListOut)
def list_payslips(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYSLIP_VIEW))],
    employee_id: Annotated[uuid.UUID | None, Query()] = None,
    pay_period_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = "current",
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> PayslipListOut:
    q = select(Payslip)
    if status is not None:
        q = q.where(Payslip.status == status)
    q = q.where(Payslip.status != "preview")
    if employee_id is not None:
        q = q.where(Payslip.employee_id == employee_id)
    if pay_period_id is not None:
        q = q.where(Payslip.pay_period_id == pay_period_id)
    q = apply_scope(q, user, db, model=Payslip)
    if cursor is not None:
        q = q.where(Payslip.id > _decode_cursor(cursor))
    q = q.order_by(Payslip.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].id)
    return PayslipListOut(
        items=[PayslipOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/{payslip_id}", response_model=PayslipOut)
def get_payslip(
    payslip_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYSLIP_VIEW))],
) -> PayslipOut:
    row = _load_payslip_scoped(db, user, payslip_id)
    return PayslipOut.model_validate(row)


@router.get("/{payslip_id}/explain", response_model=PayslipExplainOut)
def explain_payslip(
    payslip_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYSLIP_VIEW))],
) -> PayslipExplainOut:
    row = _load_payslip_scoped(db, user, payslip_id)
    lines = list(db.scalars(
        select(PayslipLine).where(PayslipLine.payslip_id == row.id)
        .order_by(PayslipLine.sort_order.asc())
    ).all())
    return PayslipExplainOut(
        payslip=PayslipOut.model_validate(row),
        lines=[PayslipLineOut.model_validate(l) for l in lines],
        snapshot=row.snapshot or {},
        calculation_context=row.calculation_context or {},
    )


@router.get("/{payslip_id}/pdf")
def get_payslip_pdf(
    payslip_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYSLIP_VIEW))],
) -> Response:
    row = _load_payslip_scoped(db, user, payslip_id)
    employee = db.scalar(select(Employee).where(Employee.id == row.employee_id))
    pay_period = db.scalar(select(PayPeriod).where(PayPeriod.id == row.pay_period_id))
    if employee is None or pay_period is None:
        raise AppError("not_found", "Payslip references missing employee or period", 500)
    pdf_bytes = render_payslip_pdf(row, employee, pay_period)
    filename = f"payslip-{employee.employee_code}-{pay_period.period_key}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# END OF FILE

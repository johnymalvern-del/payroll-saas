"""Payslip read endpoints (Chapter 4 Bundle 004b-b + Chapter 4H B-3).

Chapter 4H B-3 additions (round-2 amendments §12–§14):
  - `/me`, `/me/{id}`, `/me/{id}/pdf` — SELF_VIEW routes for own payslips.
    Registered BEFORE `/{payslip_id}` so FastAPI does not try to parse
    "me" as a UUID.
  - `/me` returns FINALISED payslips only (`status != "preview"`).
  - Auditor role is refused with 403 on the /me endpoints (master brief §6).
  - PDF responses add `Cache-Control: no-store` and a generic
    `filename="payslip.pdf"`.
  - The generic `/{payslip_id}/pdf` writes an audit entry when the caller
    is not the payslip's employee.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_payslips_schemas import (
    PayslipExplainOut,
    PayslipLineOut,
    PayslipListOut,
    PayslipMeListOut,
    PayslipMeRow,
    PayslipOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.pay import PayPeriod, Payslip, PayslipLine, PayrollRun
from app.db.tenant.models.people import Employee
from app.services.payroll_audit import write_audit
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


def _encode_me_cursor(pay_date: date, payslip_id: uuid.UUID) -> str:
    raw = json.dumps(
        {"d": pay_date.isoformat(), "i": str(payslip_id)},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_me_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        return date.fromisoformat(payload["d"]), uuid.UUID(payload["i"])
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


def _require_non_auditor(user: Any) -> None:
    """Master brief section 6: auditors must not access the self-service
    payslip routes (they see every payslip via their day-to-day role).
    """
    if getattr(user, "role", None) == "auditor":
        raise AppError(
            "forbidden",
            "Auditors cannot access the self-service payslip endpoints",
            403,
            {"role": "auditor"},
        )


def _me_employee_id(user: Any) -> uuid.UUID:
    employee_id = getattr(user, "employee_id", None)
    if employee_id is None:
        raise AppError(
            "no_employee_record",
            "User has no employee record",
            404,
        )
    return employee_id


def _load_my_payslip(
    db, user, payslip_id: uuid.UUID,
) -> Payslip:
    employee_id = _me_employee_id(user)
    row = db.scalar(
        select(Payslip).where(
            Payslip.id == payslip_id,
            Payslip.employee_id == employee_id,
            Payslip.status != "preview",
        )
    )
    if row is None:
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


# ---- /me routes — MUST come before /{payslip_id} (FastAPI path order) ----


@router.get("/me", response_model=PayslipMeListOut)
def list_my_payslips(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SELF_VIEW))],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> PayslipMeListOut:
    _require_non_auditor(user)
    employee_id = _me_employee_id(user)

    q = (
        select(Payslip, PayPeriod)
        .join(PayPeriod, PayPeriod.id == Payslip.pay_period_id)
        .where(
            Payslip.employee_id == employee_id,
            Payslip.status != "preview",
        )
    )
    if cursor is not None:
        d, i = _decode_me_cursor(cursor)
        q = q.where(
            or_(
                PayPeriod.pay_date < d,
                (PayPeriod.pay_date == d) & (Payslip.id < i),
            )
        )
    q = q.order_by(PayPeriod.pay_date.desc(), Payslip.id.desc()).limit(limit + 1)
    rows = list(db.execute(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last_ps, last_pp = rows[-1]
        next_cursor = _encode_me_cursor(last_pp.pay_date, last_ps.id)

    items = [
        PayslipMeRow(
            id=ps.id,
            pay_period_id=ps.pay_period_id,
            period_key=pp.period_key,
            pay_date=pp.pay_date,
            status=ps.status,
            gross=ps.gross,
            net=ps.net,
            computed_at=ps.computed_at,
        )
        for ps, pp in rows
    ]
    return PayslipMeListOut(items=items, next_cursor=next_cursor)


@router.get("/me/{payslip_id}", response_model=PayslipOut)
def get_my_payslip(
    payslip_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SELF_VIEW))],
) -> PayslipOut:
    _require_non_auditor(user)
    row = _load_my_payslip(db, user, payslip_id)
    return PayslipOut.model_validate(row)


@router.get("/me/{payslip_id}/pdf")
def get_my_payslip_pdf(
    payslip_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.SELF_VIEW))],
) -> Response:
    _require_non_auditor(user)
    row = _load_my_payslip(db, user, payslip_id)
    employee = db.scalar(select(Employee).where(Employee.id == row.employee_id))
    pay_period = db.scalar(select(PayPeriod).where(PayPeriod.id == row.pay_period_id))
    if employee is None or pay_period is None:
        raise AppError("not_found", "Payslip references missing employee or period", 500)
    pdf_bytes = render_payslip_pdf(row, employee, pay_period)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="payslip.pdf"',
            "Cache-Control": "no-store",
        },
    )


# ---- generic routes ----


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

    # Round-2 amendment §14: audit when a non-owner downloads.
    if getattr(user, "employee_id", None) != row.employee_id:
        write_audit(
            db, user,
            entity_type="payslip",
            entity_id=row.id,
            action="payslip.pdf_download_by_other",
            new_value={
                "downloaded_by_user_id": str(getattr(user, "id", "")),
                "employee_id": str(row.employee_id),
                "pay_period_id": str(row.pay_period_id),
            },
        )
        db.commit()

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="payslip.pdf"',
            "Cache-Control": "no-store",
        },
    )

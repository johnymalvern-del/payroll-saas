"""Per-employee earnings and deductions (Chapter 4, Bundle 003c).

Writes go through PAY_RATE_REQUEST (hr only) per F3: these rows change the
payslip amount, so they follow the same change-control flow as a pay-rate
request. Reads are PAYROLL_PREVIEW (hr + payroll_admin).

Every single-row operation calls assert_in_scope so a future scope narrowing
cannot accidentally allow cross-scope reads or writes; today the actual
callers (hr, payroll_admin) are company-wide so it is a no-op, but it fails
closed if scope is ever narrowed.
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_employees_schemas import (
    EmployeeDeductionIn,
    EmployeeDeductionListOut,
    EmployeeDeductionOut,
    EmployeeDeductionPatch,
    EmployeeEarningIn,
    EmployeeEarningListOut,
    EmployeeEarningOut,
    EmployeeEarningPatch,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.pay import EmployeeDeduction, EmployeeEarning
from app.db.tenant.models.people import Employee
from app.services.payroll_audit import write_audit

router = APIRouter(prefix="/payroll", tags=["payroll-employees"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _encode_uuid_cursor(uid: uuid.UUID) -> str:
    raw = json.dumps({"i": str(uid)}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_uuid_cursor(cursor: str) -> uuid.UUID:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        return uuid.UUID(json.loads(raw)["i"])
    except Exception:
        raise AppError("invalid_cursor", "The pagination cursor is malformed", 400) from None


def _resolve_employee_or_404(db, user, employee_id: uuid.UUID) -> Employee:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Employee not found", 404)
    emp = db.scalar(select(Employee).where(Employee.id == employee_id))
    if emp is None:
        raise AppError("not_found", "Employee not found", 404)
    return emp


def _validate_amount_or_rate(amount, rate) -> None:
    if amount is None and rate is None:
        raise AppError(
            "amount_or_rate_required",
            "Provide amount or rate",
            422,
        )
    if amount is not None and rate is not None:
        raise AppError(
            "amount_xor_rate",
            "Provide amount or rate, not both",
            422,
        )


def _validate_effective_window(effective_from: date, effective_to: date | None) -> None:
    if effective_to is not None and effective_to < effective_from:
        raise AppError(
            "invalid_effective_window",
            "effective_to must be on or after effective_from",
            422,
        )


# ---------------------------------------------------------------------------
# Employee earnings
# ---------------------------------------------------------------------------

@router.get("/employees/{employee_id}/earnings", response_model=EmployeeEarningListOut)
def list_employee_earnings(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    active_only: bool = Query(True),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> EmployeeEarningListOut:
    _resolve_employee_or_404(db, user, employee_id)
    q = select(EmployeeEarning).where(EmployeeEarning.employee_id == employee_id)
    if active_only:
        q = q.where(EmployeeEarning.is_active.is_(True))
    if cursor is not None:
        q = q.where(EmployeeEarning.id > _decode_uuid_cursor(cursor))
    q = q.order_by(EmployeeEarning.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_uuid_cursor(rows[-1].id)
    return EmployeeEarningListOut(
        items=[EmployeeEarningOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/employees/{employee_id}/earnings/{item_id}", response_model=EmployeeEarningOut)
def get_employee_earning(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> EmployeeEarningOut:
    _resolve_employee_or_404(db, user, employee_id)
    row = db.scalar(
        select(EmployeeEarning).where(
            EmployeeEarning.id == item_id,
            EmployeeEarning.employee_id == employee_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Employee earning not found", 404)
    return EmployeeEarningOut.model_validate(row)


@router.post("/employees/{employee_id}/earnings", response_model=EmployeeEarningOut, status_code=201)
def create_employee_earning(
    employee_id: uuid.UUID,
    body: EmployeeEarningIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> EmployeeEarningOut:
    _resolve_employee_or_404(db, user, employee_id)
    _validate_amount_or_rate(body.amount, body.rate)
    _validate_effective_window(body.effective_from, body.effective_to)
    row = EmployeeEarning(
        id=uuid.uuid4(),
        employee_id=employee_id,
        earning_type_id=body.earning_type_id,
        amount=body.amount,
        rate=body.rate,
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        is_active=True,
    )
    db.add(row)
    db.flush()
    write_audit(
        db, user,
        entity_type="employee_earning", entity_id=row.id, action="create",
        new_value={
            "employee_id": str(employee_id),
            "earning_type_id": str(row.earning_type_id),
            "amount": str(row.amount) if row.amount is not None else None,
            "rate": str(row.rate) if row.rate is not None else None,
            "effective_from": str(row.effective_from),
            "effective_to": str(row.effective_to) if row.effective_to else None,
        },
    )
    db.commit()
    return EmployeeEarningOut.model_validate(row)


@router.patch("/employees/{employee_id}/earnings/{item_id}", response_model=EmployeeEarningOut)
def patch_employee_earning(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    body: EmployeeEarningPatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> EmployeeEarningOut:
    _resolve_employee_or_404(db, user, employee_id)
    row = db.scalar(
        select(EmployeeEarning).where(
            EmployeeEarning.id == item_id,
            EmployeeEarning.employee_id == employee_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Employee earning not found", 404)
    if body.row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {body.row_version}, current {row.row_version}",
            409,
        )
    new_amount = body.amount if "amount" in body.model_fields_set else row.amount
    new_rate = body.rate if "rate" in body.model_fields_set else row.rate
    _validate_amount_or_rate(new_amount, new_rate)
    new_from = body.effective_from if "effective_from" in body.model_fields_set and body.effective_from is not None else row.effective_from
    new_to = body.effective_to if "effective_to" in body.model_fields_set else row.effective_to
    _validate_effective_window(new_from, new_to)

    old_snapshot = {
        "amount": str(row.amount) if row.amount is not None else None,
        "rate": str(row.rate) if row.rate is not None else None,
        "effective_from": str(row.effective_from),
        "effective_to": str(row.effective_to) if row.effective_to else None,
        "is_active": row.is_active,
        "row_version": row.row_version,
    }
    if "amount" in body.model_fields_set:
        row.amount = body.amount
    if "rate" in body.model_fields_set:
        row.rate = body.rate
    if "effective_from" in body.model_fields_set and body.effective_from is not None:
        row.effective_from = body.effective_from
    if "effective_to" in body.model_fields_set:
        row.effective_to = body.effective_to
    if "is_active" in body.model_fields_set and body.is_active is not None:
        row.is_active = body.is_active
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="employee_earning", entity_id=row.id, action="update",
        old_value=old_snapshot,
        new_value={
            "amount": str(row.amount) if row.amount is not None else None,
            "rate": str(row.rate) if row.rate is not None else None,
            "effective_from": str(row.effective_from),
            "effective_to": str(row.effective_to) if row.effective_to else None,
            "is_active": row.is_active,
            "row_version": row.row_version,
        },
    )
    db.commit()
    return EmployeeEarningOut.model_validate(row)


@router.post("/employees/{employee_id}/earnings/{item_id}/deactivate", response_model=EmployeeEarningOut)
def deactivate_employee_earning(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
    row_version: int = Query(...),
) -> EmployeeEarningOut:
    _resolve_employee_or_404(db, user, employee_id)
    row = db.scalar(
        select(EmployeeEarning).where(
            EmployeeEarning.id == item_id,
            EmployeeEarning.employee_id == employee_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Employee earning not found", 404)
    if row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {row_version}, current {row.row_version}",
            409,
        )
    row.is_active = False
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="employee_earning", entity_id=row.id, action="deactivate",
        old_value={"is_active": True}, new_value={"is_active": False},
    )
    db.commit()
    return EmployeeEarningOut.model_validate(row)


# ---------------------------------------------------------------------------
# Employee deductions
# ---------------------------------------------------------------------------

@router.get("/employees/{employee_id}/deductions", response_model=EmployeeDeductionListOut)
def list_employee_deductions(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
    active_only: bool = Query(True),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> EmployeeDeductionListOut:
    _resolve_employee_or_404(db, user, employee_id)
    q = select(EmployeeDeduction).where(EmployeeDeduction.employee_id == employee_id)
    if active_only:
        q = q.where(EmployeeDeduction.is_active.is_(True))
    if cursor is not None:
        q = q.where(EmployeeDeduction.id > _decode_uuid_cursor(cursor))
    q = q.order_by(EmployeeDeduction.id.asc()).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        next_cursor = _encode_uuid_cursor(rows[-1].id)
    return EmployeeDeductionListOut(
        items=[EmployeeDeductionOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/employees/{employee_id}/deductions/{item_id}", response_model=EmployeeDeductionOut)
def get_employee_deduction(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> EmployeeDeductionOut:
    _resolve_employee_or_404(db, user, employee_id)
    row = db.scalar(
        select(EmployeeDeduction).where(
            EmployeeDeduction.id == item_id,
            EmployeeDeduction.employee_id == employee_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Employee deduction not found", 404)
    return EmployeeDeductionOut.model_validate(row)


@router.post("/employees/{employee_id}/deductions", response_model=EmployeeDeductionOut, status_code=201)
def create_employee_deduction(
    employee_id: uuid.UUID,
    body: EmployeeDeductionIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> EmployeeDeductionOut:
    _resolve_employee_or_404(db, user, employee_id)
    _validate_effective_window(body.effective_from, body.effective_to)
    row = EmployeeDeduction(
        id=uuid.uuid4(),
        employee_id=employee_id,
        deduction_type_id=body.deduction_type_id,
        amount=body.amount,
        balance=Decimal("0.00"),
        effective_from=body.effective_from,
        effective_to=body.effective_to,
        is_active=True,
    )
    db.add(row)
    db.flush()
    write_audit(
        db, user,
        entity_type="employee_deduction", entity_id=row.id, action="create",
        new_value={
            "employee_id": str(employee_id),
            "deduction_type_id": str(row.deduction_type_id),
            "amount": str(row.amount),
            "effective_from": str(row.effective_from),
            "effective_to": str(row.effective_to) if row.effective_to else None,
        },
    )
    db.commit()
    return EmployeeDeductionOut.model_validate(row)


@router.patch("/employees/{employee_id}/deductions/{item_id}", response_model=EmployeeDeductionOut)
def patch_employee_deduction(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    body: EmployeeDeductionPatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> EmployeeDeductionOut:
    _resolve_employee_or_404(db, user, employee_id)
    row = db.scalar(
        select(EmployeeDeduction).where(
            EmployeeDeduction.id == item_id,
            EmployeeDeduction.employee_id == employee_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Employee deduction not found", 404)
    if body.row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {body.row_version}, current {row.row_version}",
            409,
        )
    new_from = body.effective_from if "effective_from" in body.model_fields_set and body.effective_from is not None else row.effective_from
    new_to = body.effective_to if "effective_to" in body.model_fields_set else row.effective_to
    _validate_effective_window(new_from, new_to)

    old_snapshot = {
        "amount": str(row.amount),
        "effective_from": str(row.effective_from),
        "effective_to": str(row.effective_to) if row.effective_to else None,
        "is_active": row.is_active,
        "row_version": row.row_version,
    }
    if "amount" in body.model_fields_set and body.amount is not None:
        row.amount = body.amount
    if "effective_from" in body.model_fields_set and body.effective_from is not None:
        row.effective_from = body.effective_from
    if "effective_to" in body.model_fields_set:
        row.effective_to = body.effective_to
    if "is_active" in body.model_fields_set and body.is_active is not None:
        row.is_active = body.is_active
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="employee_deduction", entity_id=row.id, action="update",
        old_value=old_snapshot,
        new_value={
            "amount": str(row.amount),
            "effective_from": str(row.effective_from),
            "effective_to": str(row.effective_to) if row.effective_to else None,
            "is_active": row.is_active,
            "row_version": row.row_version,
        },
    )
    db.commit()
    return EmployeeDeductionOut.model_validate(row)


@router.post("/employees/{employee_id}/deductions/{item_id}/deactivate", response_model=EmployeeDeductionOut)
def deactivate_employee_deduction(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
    row_version: int = Query(...),
) -> EmployeeDeductionOut:
    _resolve_employee_or_404(db, user, employee_id)
    row = db.scalar(
        select(EmployeeDeduction).where(
            EmployeeDeduction.id == item_id,
            EmployeeDeduction.employee_id == employee_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Employee deduction not found", 404)
    if row_version != row.row_version:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {row_version}, current {row.row_version}",
            409,
        )
    row.is_active = False
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="employee_deduction", entity_id=row.id, action="deactivate",
        old_value={"is_active": True}, new_value={"is_active": False},
    )
    db.commit()
    return EmployeeDeductionOut.model_validate(row)

# END OF FILE

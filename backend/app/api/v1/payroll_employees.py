"""Per-employee earnings and deductions (Chapter 4).

Writes route through the F3 change-request mechanism (Bundle 004a-iv-a):
HR submits a pending change request via these endpoints, payroll_admin
approves via /payroll/change-requests/{id}/approve. Pending requests have
zero effect on employee_earning / employee_deduction until approved.

Reads are direct (PAYROLL_PREVIEW); the writes return 202 with the pending
change request envelope, not the would-be row.

F3 default: submission endpoint = existing 003c URL. The change-request
create/approve endpoints exist separately under /payroll/change-requests.
"""
from __future__ import annotations

import base64
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_change_requests_schemas import ChangeRequestOut
from app.api.v1.payroll_employees_schemas import (
    EmployeeDeductionListOut,
    EmployeeDeductionOut,
    EmployeeDeductionPatch,
    EmployeeEarningIn,
    EmployeeEarningListOut,
    EmployeeEarningOut,
    EmployeeEarningPatch,
    EmployeeDeductionIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.pay import EmployeeDeduction, EmployeeEarning
from app.db.tenant.models.people import Employee
from app.services.payroll_change_request import submit_change_request

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


# ---------------------------------------------------------------------------
# Employee earnings — READ
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


# ---------------------------------------------------------------------------
# Employee earnings — WRITE (change-request submission)
# ---------------------------------------------------------------------------

@router.post("/employees/{employee_id}/earnings", response_model=ChangeRequestOut, status_code=202)
def create_employee_earning_request(
    employee_id: uuid.UUID,
    body: EmployeeEarningIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    request = submit_change_request(
        db, user,
        kind="employee_earning_create",
        employee_id=employee_id,
        payload=body.model_dump(mode="json"),
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.patch("/employees/{employee_id}/earnings/{item_id}", response_model=ChangeRequestOut, status_code=202)
def patch_employee_earning_request(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    body: EmployeeEarningPatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    payload = body.model_dump(mode="json", exclude_unset=True)
    payload["target_id"] = str(item_id)
    request = submit_change_request(
        db, user,
        kind="employee_earning_update",
        employee_id=employee_id,
        payload=payload,
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.post("/employees/{employee_id}/earnings/{item_id}/deactivate", response_model=ChangeRequestOut, status_code=202)
def deactivate_employee_earning_request(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
    row_version: int = Query(...),
) -> ChangeRequestOut:
    request = submit_change_request(
        db, user,
        kind="employee_earning_deactivate",
        employee_id=employee_id,
        payload={"target_id": str(item_id), "row_version": row_version},
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)


# ---------------------------------------------------------------------------
# Employee deductions — READ
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


# ---------------------------------------------------------------------------
# Employee deductions — WRITE (change-request submission)
# ---------------------------------------------------------------------------

@router.post("/employees/{employee_id}/deductions", response_model=ChangeRequestOut, status_code=202)
def create_employee_deduction_request(
    employee_id: uuid.UUID,
    body: EmployeeDeductionIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    request = submit_change_request(
        db, user,
        kind="employee_deduction_create",
        employee_id=employee_id,
        payload=body.model_dump(mode="json"),
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.patch("/employees/{employee_id}/deductions/{item_id}", response_model=ChangeRequestOut, status_code=202)
def patch_employee_deduction_request(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    body: EmployeeDeductionPatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    payload = body.model_dump(mode="json", exclude_unset=True)
    payload["target_id"] = str(item_id)
    request = submit_change_request(
        db, user,
        kind="employee_deduction_update",
        employee_id=employee_id,
        payload=payload,
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)


@router.post("/employees/{employee_id}/deductions/{item_id}/deactivate", response_model=ChangeRequestOut, status_code=202)
def deactivate_employee_deduction_request(
    employee_id: uuid.UUID,
    item_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
    row_version: int = Query(...),
) -> ChangeRequestOut:
    request = submit_change_request(
        db, user,
        kind="employee_deduction_deactivate",
        employee_id=employee_id,
        payload={"target_id": str(item_id), "row_version": row_version},
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)

# END OF FILE

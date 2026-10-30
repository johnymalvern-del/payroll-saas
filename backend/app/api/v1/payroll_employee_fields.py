"""Employee payroll field endpoints (Chapter 4, Bundle 004a-iv-b).

The three fields exposed here (contracted_weekly_hours, medical_scheme_members,
uif_exempt) drive hourly-rate derivation, medical tax credits, and UIF cost.
Reads are direct via PAYROLL_PREVIEW; writes route through F3 change requests
(HR submits via PAY_RATE_REQUEST, payroll_admin approves via PAY_RATE_APPROVE).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.payroll_change_requests_schemas import ChangeRequestOut
from app.api.v1.payroll_employee_fields_schemas import (
    EmployeeFieldsChangeIn,
    EmployeeFieldsOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.people import Employee
from app.services.payroll_change_request import submit_change_request

router = APIRouter(prefix="/payroll", tags=["payroll-employee-fields"])


def _resolve_employee_or_404(db, user, employee_id: uuid.UUID) -> Employee:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Employee not found", 404)
    emp = db.scalar(select(Employee).where(Employee.id == employee_id))
    if emp is None:
        raise AppError("not_found", "Employee not found", 404)
    return emp


@router.get("/employees/{employee_id}/fields", response_model=EmployeeFieldsOut)
def get_employee_fields(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAYROLL_PREVIEW))],
) -> EmployeeFieldsOut:
    emp = _resolve_employee_or_404(db, user, employee_id)
    return EmployeeFieldsOut(
        employee_id=emp.id,
        contracted_weekly_hours=(
            float(emp.contracted_weekly_hours)
            if emp.contracted_weekly_hours is not None
            else None
        ),
        medical_scheme_members=emp.medical_scheme_members,
        uif_exempt=emp.uif_exempt,
        row_version=emp.row_version,
    )


@router.post(
    "/employees/{employee_id}/fields",
    response_model=ChangeRequestOut,
    status_code=202,
)
def submit_employee_fields_change(
    employee_id: uuid.UUID,
    body: EmployeeFieldsChangeIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> ChangeRequestOut:
    request = submit_change_request(
        db, user,
        kind="employee_field_update",
        employee_id=employee_id,
        payload=body.model_dump(mode="json"),
    )
    db.commit()
    return ChangeRequestOut.model_validate(request)

# END OF FILE

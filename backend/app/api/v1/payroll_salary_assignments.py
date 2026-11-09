"""Salary structure assignment endpoints (Stage C of Milestone 3).

Submit / reject / cancel / read / attempts / employee history /
collision pre-check. Approve (with batch inserts, closures, attempt
rows) is Stage D and lives in a separate module.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import TenantDbDep
from app.api.v1.payroll_salary_assignments_schemas import (
    AssignmentDetailOut,
    AssignmentListOut,
    AssignmentOut,
    AssignmentRejectIn,
    AssignmentSubmitIn,
    AttemptListOut,
    AttemptOut,
    ChangeRequestChildOut,
    CheckCollisionsIn,
    CheckCollisionsOut,
    ManualOverlapOut,
    StructureOwnedOverlapOut,
)
from app.core.permissions import Permission, require_permission
from app.services import salary_assignment_service as svc

router = APIRouter(
    prefix="/payroll/employee-salary-assignments",
    tags=["payroll-salary-assignments"],
)


@router.post("", response_model=AssignmentOut, status_code=201)
def submit(
    body: AssignmentSubmitIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> AssignmentOut:
    a = svc.submit_assignment(
        db, user,
        employee_id=body.employee_id,
        structure_id=body.structure_id,
        effective_from=body.effective_from,
        idempotency_key=body.idempotency_key,
        override_manual_ids=[i.model_dump() for i in body.override_manual_ids],
    )
    db.commit()
    return AssignmentOut.model_validate(a)


@router.post("/check-collisions", response_model=CheckCollisionsOut)
def check_collisions(
    body: CheckCollisionsIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> CheckCollisionsOut:
    result = svc.check_collisions(
        db, user,
        employee_id=body.employee_id,
        structure_id=body.structure_id,
        effective_from=body.effective_from,
        override_manual_ids=[i.model_dump() for i in body.override_manual_ids],
    )
    return CheckCollisionsOut(
        employee_id=body.employee_id,
        structure_id=body.structure_id,
        effective_from=body.effective_from,
        manual=[ManualOverlapOut(**r) for r in result["manual"]],
        structure_owned=[StructureOwnedOverlapOut(**r) for r in result["structure_owned"]],
    )


@router.get("/{assignment_id}", response_model=AssignmentDetailOut)
def get_one(
    assignment_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> AssignmentDetailOut:
    a = svc.get_assignment(db, user, assignment_id)
    children = svc.list_children(db, a.id)
    base = AssignmentOut.model_validate(a).model_dump()
    return AssignmentDetailOut(
        **base,
        children=[ChangeRequestChildOut.model_validate(c) for c in children],
    )


@router.get("/{assignment_id}/attempts", response_model=AttemptListOut)
def get_attempts(
    assignment_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> AttemptListOut:
    rows = svc.list_attempts(db, user, assignment_id)
    return AttemptListOut(items=[AttemptOut.model_validate(r) for r in rows])


@router.post("/{assignment_id}/reject", response_model=AssignmentOut)
def reject(
    assignment_id: uuid.UUID,
    body: AssignmentRejectIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_APPROVE))],
) -> AssignmentOut:
    a = svc.reject_assignment(db, user, assignment_id, body.note)
    db.commit()
    return AssignmentOut.model_validate(a)


@router.post("/{assignment_id}/cancel", response_model=AssignmentOut)
def cancel(
    assignment_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> AssignmentOut:
    a = svc.cancel_assignment(db, user, assignment_id)
    db.commit()
    return AssignmentOut.model_validate(a)


# Employee history endpoint uses a different prefix, mounted separately.
employee_history_router = APIRouter(
    prefix="/payroll/employees",
    tags=["payroll-salary-assignments"],
)


@employee_history_router.get(
    "/{employee_id}/salary-assignments",
    response_model=AssignmentListOut,
)
def list_for_employee(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_VIEW))],
) -> AssignmentListOut:
    rows = svc.list_for_employee(db, user, employee_id)
    return AssignmentListOut(items=[AssignmentOut.model_validate(r) for r in rows])

# END OF FILE
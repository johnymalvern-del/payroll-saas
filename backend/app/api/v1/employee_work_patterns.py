'''Employee work-pattern assignment endpoints (Chapter 2A).'''
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.employee_work_pattern_schemas import (
    AssignmentCreateIn,
    AssignmentListOut,
    AssignmentOut,
    AssignmentPatchIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.attendance import EmployeeWorkPattern, WorkPattern
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix='/employees/{employee_id}/work-patterns', tags=['employee-work-patterns'])


def _to_out(a: EmployeeWorkPattern) -> AssignmentOut:
    return AssignmentOut(id=a.id, employee_id=a.employee_id, work_pattern_id=a.work_pattern_id, effective_from=a.effective_from, effective_to=a.effective_to, created_at=a.created_at)


def _employee_or_404(db: Any, employee_id: uuid.UUID, user: Any) -> Employee:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError('record_not_found', 'Employee not found', 404) from None
    e = db.get(Employee, employee_id)
    if e is None:
        raise AppError('record_not_found', 'Employee not found', 404)
    return e


def _check_overlap(db: Any, employee_id: uuid.UUID, eff_from: date, eff_to: date | None, exclude_id: uuid.UUID | None = None) -> None:
    stmt = select(EmployeeWorkPattern).where(EmployeeWorkPattern.employee_id == employee_id)
    if exclude_id is not None:
        stmt = stmt.where(EmployeeWorkPattern.id != exclude_id)
    for existing in db.scalars(stmt).all():
        if (eff_to is None or existing.effective_from <= eff_to) and (existing.effective_to is None or eff_from <= existing.effective_to):
            raise AppError('overlapping_period', 'Assignment period overlaps an existing one', 409, {'existing_id': str(existing.id)})


@router.get('', response_model=AssignmentListOut)
def list_assignments(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> AssignmentListOut:
    _employee_or_404(db, employee_id, user)
    rows = list(db.scalars(select(EmployeeWorkPattern).where(EmployeeWorkPattern.employee_id == employee_id).order_by(EmployeeWorkPattern.effective_from)).all())
    return AssignmentListOut(items=[_to_out(r) for r in rows])


@router.post('', response_model=AssignmentOut, status_code=status.HTTP_201_CREATED)
def create_assignment(
    employee_id: uuid.UUID,
    payload: AssignmentCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> AssignmentOut:
    _employee_or_404(db, employee_id, user)
    if db.get(WorkPattern, payload.work_pattern_id) is None:
        raise AppError('invalid_work_pattern', 'work_pattern_id does not exist', 400)
    _check_overlap(db, employee_id, payload.effective_from, payload.effective_to)
    a = EmployeeWorkPattern(employee_id=employee_id, work_pattern_id=payload.work_pattern_id, effective_from=payload.effective_from, effective_to=payload.effective_to)
    db.add(a)
    db.flush()
    snap = _to_out(a).model_dump(mode='json')
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='employee_work_pattern', entity_id=str(a.id), action='employee_work_pattern.create', old_value=None, new_value=redact_for_audit(snap)))
    db.commit()
    db.refresh(a)
    return _to_out(a)


@router.patch('/{assignment_id}', response_model=AssignmentOut)
def end_assignment(
    employee_id: uuid.UUID,
    assignment_id: uuid.UUID,
    payload: AssignmentPatchIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> AssignmentOut:
    _employee_or_404(db, employee_id, user)
    a = db.get(EmployeeWorkPattern, assignment_id)
    if a is None or a.employee_id != employee_id:
        raise AppError('record_not_found', 'Assignment not found', 404)
    if payload.effective_to <= a.effective_from:
        raise AppError('invalid_effective_to', 'effective_to must be after effective_from', 400)
    _check_overlap(db, employee_id, a.effective_from, payload.effective_to, exclude_id=a.id)
    old_snap = _to_out(a).model_dump(mode='json')
    a.effective_to = payload.effective_to
    db.flush()
    new_snap = _to_out(a).model_dump(mode='json')
    db.add(AuditLog(id=uuid.uuid4(), actor_user_id=getattr(user, 'id', None), actor_role=getattr(user, 'role', None), entity_type='employee_work_pattern', entity_id=str(a.id), action='employee_work_pattern.end', old_value=redact_for_audit(old_snap), new_value=redact_for_audit(new_snap)))
    db.commit()
    db.refresh(a)
    return _to_out(a)

# END OF FILE

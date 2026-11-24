"""Attendance PIN endpoints -- the non-biometric fallback (policy s4).

Section 4 requires a non-biometric alternative that every employee can use
without detriment. This module manages the credential for it.

Deliberately gated on EMPLOYEE_CRUD, not BIOMETRIC_ENROL. A fallback credential
is employee administration, and putting it behind the biometric permission would
make the alternative unavailable to exactly the employees whose circumstances
require it -- a biometric permission held only by HR and payroll_admin.

HR sets and resets PINs. Self-service PIN change is not implemented; when it is,
it belongs on a different permission and should require the employee's existing
credential. Noted rather than half-built.

The PIN is hashed with the same argon2 configuration as user passwords and is
never returned by any endpoint. A forgotten PIN is reset, never recovered.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.employee_pin_schemas import PinSetIn, PinStatusOut
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.core.security import hash_password
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog

router = APIRouter(prefix="/employees", tags=["employee-pin"])


def _get_employee(db: Any, employee_id: uuid.UUID, user: Any) -> Employee:
    """Fetch an employee, honouring the caller's scope.

    Scoped-out produces 404 rather than 403, matching the rest of the codebase:
    confirming that an employee exists outside the caller's scope leaks the org
    chart.
    """
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError("record_not_found", "Employee not found", 404)
    try:
        assert_in_scope(user, employee.id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Employee not found", 404) from None
    return employee


def _audit(db: Any, *, action: str, employee_id: uuid.UUID, new_value: dict) -> None:
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=None,
            actor_role=None,
            entity_type="employee_pin",
            entity_id=str(employee_id),
            action=action,
            old_value=None,
            new_value={"employee_id": str(employee_id), **new_value},
            request_id=None,
        )
    )


@router.get("/{employee_id}/attendance-pin", response_model=PinStatusOut)
def get_pin_status(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> PinStatusOut:
    employee = _get_employee(db, employee_id, user)
    now = datetime.now(timezone.utc)
    locked = (
        employee.pin_locked_until is not None
        and employee.pin_locked_until > now
    )
    return PinStatusOut(
        employee_id=employee.id,
        pin_set=employee.pin_hash is not None,
        pin_set_at=employee.pin_set_at,
        locked=locked,
        locked_until=employee.pin_locked_until if locked else None,
        failed_attempts=employee.pin_failed_attempts or 0,
    )


@router.put("/{employee_id}/attendance-pin", response_model=PinStatusOut)
def set_pin(
    employee_id: uuid.UUID,
    payload: PinSetIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> PinStatusOut:
    """Set or reset the attendance PIN.

    Resetting also clears any lockout: HR issuing a new PIN is the documented
    recovery path for a locked employee, and leaving the lock in place would
    make the new PIN unusable.
    """
    employee = _get_employee(db, employee_id, user)

    employee.pin_hash = hash_password(payload.pin.get_secret_value())
    employee.pin_set_at = datetime.now(timezone.utc)
    employee.pin_failed_attempts = 0
    employee.pin_locked_until = None

    _audit(
        db,
        action="employee_pin.set",
        employee_id=employee.id,
        new_value={"reset": True},
    )
    db.commit()
    db.refresh(employee)

    return PinStatusOut(
        employee_id=employee.id,
        pin_set=True,
        pin_set_at=employee.pin_set_at,
        locked=False,
        locked_until=None,
        failed_attempts=0,
    )


@router.delete("/{employee_id}/attendance-pin", status_code=status.HTTP_204_NO_CONTENT)
def clear_pin(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> Response:
    """Remove the PIN entirely.

    An employee with no PIN simply cannot use the fallback and must ask HR for
    one. That is the correct outcome when an employee leaves or when a PIN is
    believed compromised.
    """
    employee = _get_employee(db, employee_id, user)

    if employee.pin_hash is None:
        raise AppError(
            "pin_not_set",
            "This employee has no attendance PIN to clear.",
            409,
        )

    employee.pin_hash = None
    employee.pin_set_at = None
    employee.pin_failed_attempts = 0
    employee.pin_locked_until = None

    _audit(db, action="employee_pin.cleared", employee_id=employee.id, new_value={})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{employee_id}/attendance-pin/unlock", response_model=PinStatusOut)
def unlock_pin(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.EMPLOYEE_CRUD))],
) -> PinStatusOut:
    """Clear a lockout without changing the PIN.

    Separate from set_pin because an employee who forgot their PIN needs a
    reset, while one who mistyped it five times needs only an unlock -- and
    resetting would leave them without their chosen PIN.
    """
    employee = _get_employee(db, employee_id, user)

    if employee.pin_hash is None:
        raise AppError(
            "pin_not_set",
            "This employee has no attendance PIN.",
            409,
        )

    employee.pin_failed_attempts = 0
    employee.pin_locked_until = None

    _audit(db, action="employee_pin.unlocked", employee_id=employee.id, new_value={})
    db.commit()
    db.refresh(employee)

    return PinStatusOut(
        employee_id=employee.id,
        pin_set=True,
        pin_set_at=employee.pin_set_at,
        locked=False,
        locked_until=None,
        failed_attempts=0,
    )

# END OF FILE
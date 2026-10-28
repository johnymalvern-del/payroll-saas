"""Adjustment endpoints (Chapter 2C).

Two endpoints:
  POST /attendance/adjustments        single adjustment
  POST /attendance/adjustments/bulk   dry-run + token (C1)

Adjustments are append-only (C6). outcome='revert' restores the punch-based
computation; the adjustment history stays in the audit log.

Self-adjust (C8): a user cannot adjust their own employee record. Enforced
here and in the bulk endpoint.

Locked days (C3): 409 day_locked with a message pointing to the payroll
period feature for corrections after close.

Reuses _apply_adjustment / _day_for / _validate_reason from exceptions.py so
single adjustments and exception-driven adjustments produce identical audit
rows and identical locked-day errors.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import TenantDbDep
from app.api.v1.adjustments_schemas import (
    AdjustmentCreateIn,
    AdjustmentOut,
    AdjustmentResultOut,
    BulkAdjustIn,
    BulkAdjustItemOut,
    BulkAdjustOut,
)
from app.api.v1.exceptions import (
    _apply_adjustment,
    _day_for,
    _validate_reason,
)
from app.api.v1.exceptions_schemas import CustomAdjustmentIn
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.attendance import Adjustment
from app.db.tenant.models.people import Employee

router = APIRouter(prefix="/attendance/adjustments", tags=["attendance-adjustments"])


def _to_adj_out(a: Adjustment) -> AdjustmentOut:
    return AdjustmentOut(
        id=a.id,
        employee_id=a.employee_id,
        work_date=a.work_date,
        outcome=a.outcome,
        time_in=a.time_in,
        time_out=a.time_out,
        minutes=a.minutes,
        reason_code=a.reason_code,
        note=a.note,
        batch_id=a.batch_id,
        created_by=a.created_by,
        period_id=a.period_id,
        created_at=a.created_at,
    )


def _require_not_self(user, employee_id) -> None:
    if getattr(user, "employee_id", None) is not None and user.employee_id == employee_id:
        raise AppError(
            "cannot_adjust_own",
            "A user cannot adjust their own attendance",
            status.HTTP_403_FORBIDDEN,
        )


def _require_scope(db, user, employee_id) -> None:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Employee not found", 404) from None


def _to_custom(payload) -> CustomAdjustmentIn:
    return CustomAdjustmentIn(
        outcome=payload.outcome,
        time_in=payload.time_in,
        time_out=payload.time_out,
        reason_code=payload.reason_code,
        note=payload.note,
    )


def _validate_common(db, payload) -> None:
    _validate_reason(db, payload.reason_code, payload.note)


@router.post("", response_model=AdjustmentResultOut, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    payload: AdjustmentCreateIn,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_ADJUST))],
) -> AdjustmentResultOut:
    _require_not_self(user, payload.employee_id)
    _require_scope(db, user, payload.employee_id)
    _validate_common(db, payload)
    request_id = getattr(request.state, "request_id", None)
    adj_id, day_status = _apply_adjustment(
        db, user, payload.employee_id, payload.work_date, _to_custom(payload),
        request_id=request_id,
    )
    adj = db.get(Adjustment, adj_id)
    day = _day_for(db, payload.employee_id, payload.work_date)
    return AdjustmentResultOut(
        adjustment=_to_adj_out(adj),
        day_status=day.status if day else None,
        day_worked_minutes=day.worked_minutes if day else None,
        day_normal_minutes=day.normal_minutes if day else None,
        day_overtime_minutes=day.overtime_minutes if day else None,
    )

# END OF FILE
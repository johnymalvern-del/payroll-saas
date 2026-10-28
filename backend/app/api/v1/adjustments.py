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
    _ERROR_MESSAGES,
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


_BULK_REASON_ERRORS = {
    "invalid_reason_code": "reason_code not in the current list",
    "note_required": "reason_code 'other' requires a note of at least 10 characters",
}


def _compute_adjust_bulk_token(items) -> str:
    payload = [item.model_dump(mode="json") for item in items]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _pre_validate_adjust_item(db, user, item):
    """Read-only validation. Returns an error code or None."""
    if getattr(user, "employee_id", None) is not None and user.employee_id == item.employee_id:
        return "cannot_adjust_own"
    try:
        assert_in_scope(user, item.employee_id, db)
    except ScopeViolation:
        return "record_not_found"
    day = _day_for(db, item.employee_id, item.work_date)
    if day is not None and day.locked:
        return "day_locked"
    try:
        _validate_reason(db, item.reason_code, item.note)
    except AppError as e:
        return e.code
    return None


def _adjust_result_message(code: str) -> str:
    if code in _BULK_REASON_ERRORS:
        return _BULK_REASON_ERRORS[code]
    return _ERROR_MESSAGES.get(code, code)


@router.post("/bulk", response_model=BulkAdjustOut)
def bulk_adjust(
    payload: BulkAdjustIn,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_ADJUST))],
) -> BulkAdjustOut:
    computed = _compute_adjust_bulk_token(payload.items)
    if payload.token is not None and payload.token != computed:
        raise AppError(
            "token_mismatch",
            "Payload does not match the dry-run token; re-run dry-run with the same items",
            status.HTTP_409_CONFLICT,
        )
    is_dry_run = payload.token is None
    request_id = getattr(request.state, "request_id", None)

    pre_errors: dict[int, str] = {}
    for idx, item in enumerate(payload.items):
        code = _pre_validate_adjust_item(db, user, item)
        if code is not None:
            pre_errors[idx] = code

    def _emit_results(ok_adj_ids: dict[int, uuid.UUID] | None = None):
        out = []
        for idx, item in enumerate(payload.items):
            if idx in pre_errors:
                code = pre_errors[idx]
                out.append(BulkAdjustItemOut(
                    index=idx, employee_id=item.employee_id, work_date=item.work_date,
                    ok=False, error_code=code, error_message=_adjust_result_message(code),
                ))
            else:
                adj_id = ok_adj_ids.get(idx) if ok_adj_ids else None
                out.append(BulkAdjustItemOut(
                    index=idx, employee_id=item.employee_id, work_date=item.work_date,
                    ok=True, adjustment_id=adj_id,
                ))
        return out

    if is_dry_run:
        return BulkAdjustOut(
            results=_emit_results(),
            applied=0,
            dry_run=True,
            token=computed,
        )

    if pre_errors:
        raise AppError(
            "bulk_validation_failed",
            "One or more items failed validation; nothing was applied. Use the dry-run results to fix the batch.",
            status.HTTP_400_BAD_REQUEST,
            {"results": [r.model_dump(mode="json") for r in _emit_results()]},
        )

    db.info["bulk_no_commit"] = True
    applied_ids: dict[int, uuid.UUID] = {}
    batch_id = uuid.uuid4()
    try:
        for idx, item in enumerate(payload.items):
            try:
                adj_id, _ = _apply_adjustment(
                    db, user, item.employee_id, item.work_date, _to_custom(item),
                    batch_id=batch_id, request_id=request_id,
                )
                applied_ids[idx] = adj_id
            except AppError as e:
                db.rollback()
                raise AppError(
                    "batch_failed",
                    f"Batch aborted at item {idx}: {e.message}. Nothing was applied.",
                    status.HTTP_409_CONFLICT,
                    {"failed_index": idx, "code": e.code},
                ) from None
        from app.db.tenant.models.platform import AuditLog
        db.add(AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="adjustment",
            entity_id=str(batch_id),
            action="attendance.adjustment.bulk",
            old_value=None,
            new_value={
                "batch_id": str(batch_id),
                "count": len(applied_ids),
                "from_date": min(i.work_date for i in payload.items).isoformat(),
                "to_date": max(i.work_date for i in payload.items).isoformat(),
            },
            request_id=request_id,
        ))
        db.commit()
    finally:
        db.info.pop("bulk_no_commit", None)

    return BulkAdjustOut(
        results=_emit_results(applied_ids),
        applied=len(applied_ids),
        dry_run=False,
        token=computed,
    )

# END OF FILE

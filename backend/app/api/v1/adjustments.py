"""Adjustment endpoints (Chapter 2C).

Three endpoints:
  POST /attendance/adjustments        single adjustment
  POST /attendance/adjustments/bulk   dry-run + token (C1)
  GET  /attendance/adjustments/history per-day correction history (Batch B)

Adjustments are append-only (C6). outcome='revert' restores the punch-based
computation; the adjustment history stays in the audit log.

Self-adjust (C8): a user cannot adjust their own employee record. Enforced
here and in the bulk endpoint. A3: the guard is scoped by the
ATTENDANCE_ADJUST_SELF permission — roles that hold it (hr, payroll_admin)
may adjust their own attendance; every other role remains blocked and sees
the same "cannot_adjust_own" 403 as before. The permission never bypasses
_require_scope or assert_dates_not_locked; those run in the same order.

Locked days (C3): 409 day_locked with a message pointing to the payroll
period feature for corrections after close.

Stage A period protection: both the single endpoint and the bulk
pre-validator call payroll_period_guard.assert_dates_not_locked, which
locks every overlapping PayPeriod row (open or locked) FOR UPDATE in
deterministic id order and raises day_locked if any is locked. This
catches dates whose AttendanceDay.locked is False or absent (rest days,
non-working holidays, un-materialised dates) that would otherwise slip
past the day-level check.

Reuses _apply_adjustment / _day_for / _validate_reason from exceptions.py so
single adjustments and exception-driven adjustments produce identical audit
rows and identical locked-day errors.

Stage B Batch B — history endpoint:
  GET /attendance/adjustments/history?employee_id=<uuid>&work_date=YYYY-MM-DD
  returns the append-only Adjustment rows for that (employee, date) newest
  first, with the creator's display name resolved from User. Permissioned
  to ATTENDANCE_VIEW, and scope-checked via assert_in_scope — HR sees only
  history for employees they are already authorised to view. Tenant
  isolation is the TenantDbDep session. old_value/new_value snapshots are
  returned intact; no AuditLog read, no AUDIT_VIEW needed.

Stage B Batch C — shift override:
  create_adjustment resolves payload.shift_id (if set) to a Shift row and
  passes both shift_id and shift_name into _apply_adjustment, which stores
  shift_id on the Adjustment row and shift_name inside new_value.shift_name.
  This lets HR record "the shift should have been X" as part of a correction
  and lets the day panel display the HR-selected shift even if the Shift row
  is later hard-deleted (FK ON DELETE SET NULL). Resolution is done here,
  not in the engine, so the engine stays free of Shift-name lookup concerns.
  History rows expose shift_id and shift_name (shift_name prefers the
  snapshot's value, falling back to a live Shift lookup).

  Bulk adjustments do NOT carry a shift override in this batch. Bulk items
  go through _to_custom, which drops shift_id; the bulk path continues to
  behave exactly as before. Bulk shift override is a separate follow-up.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.adjustments_schemas import (
    AdjustmentCreateIn,
    AdjustmentHistoryListOut,
    AdjustmentHistoryRowOut,
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
from app.core.permissions import Permission, check_permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.attendance import Adjustment, Shift
from app.db.tenant.models.people import Employee, User
from app.services.payroll_period_guard import assert_dates_not_locked

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
        shift_id=a.shift_id,
        created_at=a.created_at,
    )


def _require_not_self(user, employee_id) -> None:
    """A3: the self-adjust restriction is scoped by ATTENDANCE_ADJUST_SELF.

    Callers that hold the permission may proceed to adjust their own
    employee record; every other caller sees the existing 403. The
    permission does not bypass _require_scope or assert_dates_not_locked,
    which run after this function.
    """
    if getattr(user, "employee_id", None) is not None and user.employee_id == employee_id:
        if check_permission(user, Permission.ATTENDANCE_ADJUST_SELF):
            return
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


def _resolve_creator_name(user: User | None) -> str | None:
    """Best-effort display name for an Adjustment's created_by user.

    Returns None if the user has been deleted (created_by is FK ON DELETE
    SET NULL, so the User row may not exist). If the user row exists but
    lacks first/last name, falls back to username. If even username is
    missing, returns None so the frontend renders its own fallback.
    """
    if user is None:
        return None
    first = getattr(user, "first_name", None) or ""
    last = getattr(user, "last_name", None) or ""
    label = f"{first} {last}".strip()
    if label:
        return label
    return getattr(user, "username", None) or None


def _resolve_shift_name_for_history(db, adj: Adjustment) -> str | None:
    """Resolve the display name for an adjustment's shift override.

    Stage B Batch C: prefer the name captured at write time inside
    new_value.shift_name (survives a later hard-delete of the Shift row).
    Fall back to a live Shift lookup when the snapshot lacks it (older
    rows written before Batch C, or rows where the caller did not pass a
    name). Return None when there is no shift override.

    Ordering matters: the snapshot is checked FIRST, before the
    adj.shift_id is None guard. A hard-deleted Shift row nulls
    Adjustment.shift_id via FK ON DELETE SET NULL, but the captured name
    in new_value.shift_name must still be returned — that is the whole
    point of storing it in the snapshot.
    """
    snap = adj.new_value or {}
    if isinstance(snap, dict):
        name = snap.get("shift_name")
        if isinstance(name, str) and name:
            return name
    if adj.shift_id is None:
        return None
    shift = db.get(Shift, adj.shift_id)
    return shift.name if shift is not None else None


@router.get("/history", response_model=AdjustmentHistoryListOut)
def get_adjustment_history(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_VIEW))],
    employee_id: uuid.UUID = Query(...),
    work_date: date = Query(...),
) -> AdjustmentHistoryListOut:
    """Append-only history of adjustments for (employee_id, work_date).

    Newest first by (created_at DESC, id DESC). The Adjustment table is the
    authoritative log: every correction creates exactly one row, and rows
    are never edited or deleted. old_value / new_value are the snapshots
    captured by _apply_adjustment.

    Scope and tenant isolation:
      - apply_scope / assert_in_scope prevents HR from reading history
        for an employee outside their authorised scope (404 not 403, to
        avoid confirming existence).
      - TenantDbDep binds the session to the active tenant, so no
        cross-tenant rows can be reached.
    """
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Employee not found", 404) from None

    rows = db.execute(
        select(Adjustment, User)
        .outerjoin(User, User.id == Adjustment.created_by)
        .where(
            Adjustment.employee_id == employee_id,
            Adjustment.work_date == work_date,
        )
        .order_by(Adjustment.created_at.desc(), Adjustment.id.desc())
    ).all()

    items = [
        AdjustmentHistoryRowOut(
            id=adj.id,
            employee_id=adj.employee_id,
            work_date=adj.work_date,
            outcome=adj.outcome,
            time_in=adj.time_in,
            time_out=adj.time_out,
            minutes=adj.minutes,
            reason_code=adj.reason_code,
            note=adj.note,
            batch_id=adj.batch_id,
            created_by=adj.created_by,
            created_by_name=_resolve_creator_name(usr),
            shift_id=adj.shift_id,
            shift_name=_resolve_shift_name_for_history(db, adj),
            created_at=adj.created_at,
            old_value=adj.old_value,
            new_value=adj.new_value,
        )
        for adj, usr in rows
    ]
    return AdjustmentHistoryListOut(items=items)


@router.post("", response_model=AdjustmentResultOut, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    payload: AdjustmentCreateIn,
    request: Request,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.ATTENDANCE_ADJUST))],
) -> AdjustmentResultOut:
    _require_not_self(user, payload.employee_id)
    _require_scope(db, user, payload.employee_id)
    # Stage A: reject before any write if the date is inside a locked
    # payroll period. Works even when AttendanceDay does not exist for
    # this (employee, date). Holds a FOR UPDATE lock on the PayPeriod
    # row(s) until this request's transaction commits or rolls back.
    assert_dates_not_locked(
        db,
        employee_id=payload.employee_id,
        dates=[payload.work_date],
    )
    _validate_common(db, payload)
    request_id = getattr(request.state, "request_id", None)

    # Stage B Batch C: resolve the HR-selected shift override, if any.
    # The name is captured now and stored inside new_value.shift_name by
    # _apply_adjustment, so a later hard-delete of the Shift row does not
    # erase the label. An unknown shift_id is rejected before any write
    # rather than being silently dropped — the correction would otherwise
    # record "no override" while the user believed they had chosen one.
    shift_id = payload.shift_id
    shift_name: str | None = None
    if shift_id is not None:
        shift = db.get(Shift, shift_id)
        if shift is None:
            raise AppError(
                "invalid_shift",
                "shift_id does not refer to an existing shift",
                status.HTTP_400_BAD_REQUEST,
                {"shift_id": str(shift_id)},
            )
        shift_name = shift.name

    adj_id, day_status = _apply_adjustment(
        db, user, payload.employee_id, payload.work_date, _to_custom(payload),
        request_id=request_id,
        shift_id=shift_id,
        shift_name=shift_name,
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
    """Read-only validation. Returns an error code or None.

    A3: the self-adjust restriction is scoped by ATTENDANCE_ADJUST_SELF.
    Callers that hold the permission pass this check for their own record;
    every other caller still sees "cannot_adjust_own".
    """
    if (
        getattr(user, "employee_id", None) is not None
        and user.employee_id == item.employee_id
        and not check_permission(user, Permission.ATTENDANCE_ADJUST_SELF)
    ):
        return "cannot_adjust_own"
    try:
        assert_in_scope(user, item.employee_id, db)
    except ScopeViolation:
        return "record_not_found"
    day = _day_for(db, item.employee_id, item.work_date)
    if day is not None and day.locked:
        return "day_locked"
    # Stage A: period-level protection. The day-level check above only
    # catches dates whose AttendanceDay exists and has locked=True.
    # Finalisation does not set AttendanceDay.locked; and rest days /
    # non-working holidays have no AttendanceDay row at all. This call
    # covers both cases by locking and inspecting the PayPeriod rows
    # that cover the requested date.
    try:
        assert_dates_not_locked(
            db,
            employee_id=item.employee_id,
            dates=[item.work_date],
        )
    except AppError as e:
        return e.code
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
"""Pay-rate-change endpoints (1C.10).

Surface (all nested under /employees):
  GET    /{employee_id}/pay-rate-changes                     list
  POST   /{employee_id}/pay-rate-changes                     request (HR)
  POST   /{employee_id}/pay-rate-changes/{id}/approve        approve (payroll_admin)
  POST   /{employee_id}/pay-rate-changes/{id}/reject         reject (payroll_admin)

Permissions:
  - Request: PAY_RATE_REQUEST (hr only).
  - Approve / reject: PAY_RATE_APPROVE (payroll_admin only).
  - View: PAY_RATE_VIEW (hr, payroll_admin, auditor) OR the data subject
    on their own record. Enforced inline because it is an "A OR B" check
    that require_permission (single permission) cannot express. The list
    endpoint therefore has no permission dependency of its own; it uses
    get_current_user and enforces the "A OR B" rule inline.

Scope:
  - Every endpoint calls assert_in_scope(user, employee_id, db). Out of
    scope returns 404 record_not_found, indistinguishable from a missing
    employee (IDOR mitigation, matching 1C.8).

Status and decision:
  - New rows start as status="pending" with changed_by = user.id.
  - approve sets status="approved", approved_by=decided_by=user.id,
    decided_at=now(). If the row is the currently-effective rate (the
    newest approved row whose effective_from <= today), it also updates
    Employee.base_rate and bumps Employee.row_version. A future-dated
    approval therefore becomes live only when the date arrives and a
    subsequent approval or a future scheduler applies it; 1C.10 does not
    apply it.
  - reject sets status="rejected", decided_by=user.id, decided_at=now(),
    decision_reason=<body.reason>. Employee.base_rate is not touched.
  - A pending row cannot be re-decided: an approve or reject against a
    non-pending row returns 409 not_pending.
  - A pending row is protected from a duplicate submission by the partial
    unique index uq_pay_history_emp_effective_live; the endpoint pre-checks
    and returns 409 overlapping_effective_date.

Errors:
  overlapping_effective_date - a pending or approved row already has this
                               (employee_id, effective_from)
  invalid_effective_date     - effective_from < employee.hire_date
  not_pending                - approve/reject on a non-pending row
  forbidden                  - viewer lacks PAY_RATE_VIEW and is not the subject
  record_not_found           - employee or pay-history row not found,
                               or employee out of scope
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.pay_history_schemas import (
    ALLOWED_STATUSES,
    PayHistoryCreateIn,
    PayHistoryListOut,
    PayHistoryOut,
    PayHistoryRejectIn,
)
from app.core.auth_deps import get_current_user
from app.core.errors import AppError
from app.core.permissions import (
    Permission,
    check_permission,
    require_permission,
)
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.people import Employee, EmployeePayHistory
from app.db.tenant.models.platform import AuditLog
from app.services.audit_redact import redact_for_audit

router = APIRouter(prefix="/employees", tags=["pay-history"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500


def _not_found() -> AppError:
    return AppError(
        "record_not_found", "Pay-rate change not found", status.HTTP_404_NOT_FOUND
    )


def _employee_not_found() -> AppError:
    return AppError(
        "record_not_found", "Employee not found", status.HTTP_404_NOT_FOUND
    )


def _to_out(ph: EmployeePayHistory) -> PayHistoryOut:
    return PayHistoryOut(
        id=ph.id,
        employee_id=ph.employee_id,
        base_rate=ph.base_rate,
        effective_from=ph.effective_from,
        changed_by=ph.changed_by,
        approved_by=ph.approved_by,
        decided_by=ph.decided_by,
        decided_at=ph.decided_at,
        decision_reason=ph.decision_reason,
        note=ph.note,
        status=ph.status,
        created_at=ph.created_at,
        updated_at=ph.updated_at,
    )


def _encode_cursor(created_at: datetime, ph_id: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(ph_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        created_at = datetime.fromisoformat(payload["c"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        ph_id = uuid.UUID(payload["i"])
        return created_at, ph_id
    except Exception:
        raise AppError(
            "invalid_cursor",
            "The pagination cursor is malformed",
            status.HTTP_400_BAD_REQUEST,
        ) from None


def _fetch_employee(db: Any, employee_id: uuid.UUID) -> Employee:
    emp = db.get(Employee, employee_id)
    if emp is None:
        raise _employee_not_found()
    return emp


def _fetch_pay_history(
    db: Any, employee_id: uuid.UUID, change_id: uuid.UUID
) -> EmployeePayHistory:
    row = db.get(EmployeePayHistory, change_id)
    if row is None or row.employee_id != employee_id:
        raise _not_found()
    return row


def _require_view_or_self(user: Any, employee_id: uuid.UUID) -> None:
    if check_permission(user, Permission.PAY_RATE_VIEW):
        return
    if getattr(user, "employee_id", None) == employee_id:
        return
    raise AppError(
        "forbidden",
        "Not permitted to view this employee's pay history",
        status.HTTP_403_FORBIDDEN,
    )


def _overlap_exists(
    db: Any, employee_id: uuid.UUID, effective_from: date
) -> bool:
    row = db.scalar(
        select(EmployeePayHistory.id).where(
            EmployeePayHistory.employee_id == employee_id,
            EmployeePayHistory.effective_from == effective_from,
            EmployeePayHistory.status.in_(("pending", "approved")),
        )
    )
    return row is not None


@router.get("/{employee_id}/pay-rate-changes", response_model=PayHistoryListOut)
def list_pay_rate_changes(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
    include_total: bool = Query(False),
    status_filter: str | None = Query(None, alias="status"),
    effective_from_gte: date | None = Query(None),
    effective_from_lte: date | None = Query(None),
) -> PayHistoryListOut:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise _employee_not_found() from None
    _require_view_or_self(user, employee_id)
    _fetch_employee(db, employee_id)

    if status_filter is not None and status_filter not in ALLOWED_STATUSES:
        raise AppError(
            "invalid_status_filter",
            f"status must be one of {ALLOWED_STATUSES}",
            status.HTTP_400_BAD_REQUEST,
            {"status": status_filter},
        )

    q = select(EmployeePayHistory).where(
        EmployeePayHistory.employee_id == employee_id
    )
    if status_filter is not None:
        q = q.where(EmployeePayHistory.status == status_filter)
    if effective_from_gte is not None:
        q = q.where(EmployeePayHistory.effective_from >= effective_from_gte)
    if effective_from_lte is not None:
        q = q.where(EmployeePayHistory.effective_from <= effective_from_lte)

    if cursor is not None:
        cursor_ts, cursor_id = _decode_cursor(cursor)
        q = q.where(
            or_(
                EmployeePayHistory.created_at > cursor_ts,
                (EmployeePayHistory.created_at == cursor_ts)
                & (EmployeePayHistory.id > cursor_id),
            )
        )

    q = q.order_by(
        EmployeePayHistory.created_at.asc(), EmployeePayHistory.id.asc()
    ).limit(limit + 1)
    rows = list(db.scalars(q).all())

    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    total: int | None = None
    if include_total:
        tq = select(func.count()).select_from(EmployeePayHistory).where(
            EmployeePayHistory.employee_id == employee_id
        )
        if status_filter is not None:
            tq = tq.where(EmployeePayHistory.status == status_filter)
        if effective_from_gte is not None:
            tq = tq.where(EmployeePayHistory.effective_from >= effective_from_gte)
        if effective_from_lte is not None:
            tq = tq.where(EmployeePayHistory.effective_from <= effective_from_lte)
        total = int(db.scalar(tq) or 0)

    return PayHistoryListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
        total=total,
    )


@router.post(
    "/{employee_id}/pay-rate-changes",
    response_model=PayHistoryOut,
    status_code=status.HTTP_201_CREATED,
)
def create_pay_rate_change(
    employee_id: uuid.UUID,
    payload: PayHistoryCreateIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_REQUEST))],
) -> PayHistoryOut:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise _employee_not_found() from None
    employee = _fetch_employee(db, employee_id)

    if payload.effective_from < employee.hire_date:
        raise AppError(
            "invalid_effective_date",
            f"effective_from {payload.effective_from} is before hire_date "
            f"{employee.hire_date}",
            status.HTTP_400_BAD_REQUEST,
        )

    if _overlap_exists(db, employee_id, payload.effective_from):
        raise AppError(
            "overlapping_effective_date",
            f"A pending or approved rate already exists for "
            f"{payload.effective_from}",
            status.HTTP_409_CONFLICT,
            {"effective_from": payload.effective_from.isoformat()},
        )

    row = EmployeePayHistory(
        employee_id=employee_id,
        base_rate=payload.base_rate,
        effective_from=payload.effective_from,
        changed_by=getattr(user, "id", None),
        status="pending",
        note=payload.note,
    )
    db.add(row)
    db.flush()

    snapshot = _to_out(row).model_dump(mode="json")
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="employee_pay_history",
            entity_id=str(row.id),
            action="pay_history.request",
            old_value=None,
            new_value=redact_for_audit(snapshot),
        )
    )
    db.commit()
    db.refresh(row)
    return _to_out(row)


def _currently_effective_rate(
    db: Any, employee_id: uuid.UUID, as_of: date
) -> EmployeePayHistory | None:
    """Return the newest approved row with effective_from <= as_of.

    Ordering: effective_from DESC, then created_at DESC, then id DESC as a
    deterministic tiebreak (the partial unique index makes date ties
    impossible for approved rows, but defensive ordering costs nothing).
    """
    return db.scalar(
        select(EmployeePayHistory)
        .where(
            EmployeePayHistory.employee_id == employee_id,
            EmployeePayHistory.status == "approved",
            EmployeePayHistory.effective_from <= as_of,
        )
        .order_by(
            EmployeePayHistory.effective_from.desc(),
            EmployeePayHistory.created_at.desc(),
            EmployeePayHistory.id.desc(),
        )
        .limit(1)
    )


@router.post(
    "/{employee_id}/pay-rate-changes/{change_id}/approve",
    response_model=PayHistoryOut,
)
def approve_pay_rate_change(
    employee_id: uuid.UUID,
    change_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_APPROVE))],
) -> PayHistoryOut:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise _employee_not_found() from None
    employee = _fetch_employee(db, employee_id)
    row = _fetch_pay_history(db, employee_id, change_id)

    if row.status != "pending":
        raise AppError(
            "not_pending",
            f"Cannot approve a request in status '{row.status}'",
            status.HTTP_409_CONFLICT,
            {"current_status": row.status},
        )

    old_snapshot = _to_out(row).model_dump(mode="json")
    now = datetime.now(timezone.utc)
    row.status = "approved"
    row.approved_by = getattr(user, "id", None)
    row.decided_by = getattr(user, "id", None)
    row.decided_at = now
    db.flush()

    # Recompute the currently-effective rate for the employee. Apply it to
    # Employee.base_rate only if this row is the newest approved row with
    # effective_from <= today. A future-dated approval is recorded but not
    # applied; it will become effective when a later approval on an earlier
    # date lands, or a future scheduler applies it (out of scope for 1C.10).
    effective = _currently_effective_rate(db, employee_id, now.date())
    employee_applied = False
    if effective is not None and effective.id == row.id:
        if employee.base_rate != effective.base_rate:
            employee.base_rate = effective.base_rate
            employee.row_version = employee.row_version + 1
            employee_applied = True

    db.flush()
    new_snapshot = _to_out(row).model_dump(mode="json")
    audit_new = dict(new_snapshot)
    audit_new["employee_base_rate_applied"] = employee_applied

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="employee_pay_history",
            entity_id=str(row.id),
            action="pay_history.approve",
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(audit_new),
        )
    )
    db.commit()
    db.refresh(row)
    return _to_out(row)


@router.post(
    "/{employee_id}/pay-rate-changes/{change_id}/reject",
    response_model=PayHistoryOut,
)
def reject_pay_rate_change(
    employee_id: uuid.UUID,
    change_id: uuid.UUID,
    payload: PayHistoryRejectIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.PAY_RATE_APPROVE))],
) -> PayHistoryOut:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise _employee_not_found() from None
    _fetch_employee(db, employee_id)
    row = _fetch_pay_history(db, employee_id, change_id)

    if row.status != "pending":
        raise AppError(
            "not_pending",
            f"Cannot reject a request in status '{row.status}'",
            status.HTTP_409_CONFLICT,
            {"current_status": row.status},
        )

    old_snapshot = _to_out(row).model_dump(mode="json")
    row.status = "rejected"
    row.decided_by = getattr(user, "id", None)
    row.decided_at = datetime.now(timezone.utc)
    row.decision_reason = payload.reason
    db.flush()
    new_snapshot = _to_out(row).model_dump(mode="json")

    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="employee_pay_history",
            entity_id=str(row.id),
            action="pay_history.reject",
            old_value=redact_for_audit(old_snapshot),
            new_value=redact_for_audit(new_snapshot),
        )
    )
    db.commit()
    db.refresh(row)
    return _to_out(row)

# END OF FILE
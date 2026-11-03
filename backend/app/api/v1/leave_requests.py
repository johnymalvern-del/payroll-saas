"""Leave requests + approval chain (Chapter 3, 3C, amendments 1/2/8).

Permissions:
  GET*        : SELF_VIEW (own only) OR LEAVE_APPROVE (in scope)
  POST (create) : SELF_SUBMIT (own) OR LEAVE_APPROVE (capture-on-behalf,
                  employee_id required in body; captured_by_user_id set)
  PATCH / submit / cancel : same as create, and request must belong to the
                  caller (self) or be capturable (LEAVE_APPROVE)
  POST decide / steps/{id}/decide : LEAVE_APPROVE
  POST advance : USER_MANAGE

Amendment 1: approval chain resolved per leave type; self-approval never
allowed (user.employee_id == request.employee_id → 403). If chain empties
without requires_payroll_admin_final → 409 no_eligible_approver.

Amendment 2: on final approval, one system adjustment is created per
LeaveRequestDay via services/leave_apply.apply_leave_to_attendance.
Cancel-after-approval reverts them. Locked days raise 409 day_locked
listing dates before any write happens.

Amendment 4: hour-unit leave types refused 422 unit_not_supported_yet.

Amendment 8: HR can capture-on-behalf (LEAVE_APPROVE + employee_id in body).
The employee stays the subject; approval chain applies normally; the
capturing user MAY approve their own capture but MUST provide a note
(audited); the employee (subject) can never approve their own request.

Errors:
  not_found                    - request/type/step missing or out of scope
  no_employee_record           - capture-on-behalf body missing employee_id
  unit_not_supported_yet       - leave_type.unit == 'hour'
  no_working_days_in_range     - range contains zero expected-working days
  insufficient_balance         - submitted days exceed available and
                                 allow_negative=False
  day_locked                   - one or more days already in a closed period
  self_approval_forbidden      - user is the subject of the leave
  step_already_decided         - deciding a non-pending step
  wrong_step                   - decision on a step that is not the current
                                 pending step (out of order)
  wrong_approver               - user does not hold the step's role / is not
                                 the assigned approver
  no_eligible_approver         - chain empty after self-approval exclusion
  capture_requires_note        - capturing HR approving own capture without
                                 a note
  cannot_cancel_after_days_taken - cancel on approved request with taken day
  record_changed               - row_version mismatch on PATCH
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select

from app.api.deps import TenantDbDep
from app.api.v1.leave_requests_schemas import (
    DecideIn,
    LeaveApprovalStepOut,
    LeaveRequestDayOut,
    LeaveRequestIn,
    LeaveRequestListOut,
    LeaveRequestOut,
    LeaveRequestPatch,
    StepDecideIn,
)
from app.core.auth_deps import get_current_user
from app.core.errors import AppError
from app.core.permissions import Permission, check_permission
from app.core.scope import ScopeViolation, apply_scope, assert_in_scope
from app.db.tenant.models.leave import (
    LeaveApprovalStep,
    LeaveBalance,
    LeaveRequest,
    LeaveRequestDay,
    LeaveType,
)
from app.db.tenant.models.people import Employee
from app.db.tenant.models.platform import AuditLog
from app.payroll_engine.leave import (
    available_balance,
    build_approval_chain,
    compute_cycle_bounds,
    compute_request_days,
    convert_pending_to_taken,
    release_pending,
    reserve_pending,
    resolve_approver_for_role,
)
from app.services.audit_redact import redact_for_audit
from app.services.leave_apply import (
    apply_leave_to_attendance,
    check_days_not_locked,
    revert_leave_from_attendance,
)

router = APIRouter(prefix="/leave/requests", tags=["leave-requests"])

_DEFAULT_LIMIT = 100
_MAX_LIMIT = 500
_ZERO = Decimal("0")


def _not_found() -> AppError:
    return AppError("not_found", "Leave request not found", 404)


def _zero() -> Decimal:
    return _ZERO


def _to_out(row: LeaveRequest) -> LeaveRequestOut:
    out = LeaveRequestOut.model_validate(row)
    out.days = [LeaveRequestDayOut.model_validate(d) for d in (row.days or [])]
    out.steps = [
        LeaveApprovalStepOut.model_validate(s)
        for s in sorted(row.steps or [], key=lambda s: s.step_no)
    ]
    return out


def _encode_cursor(created_at: datetime, rid: uuid.UUID) -> str:
    payload = {"c": created_at.isoformat(), "i": str(rid)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        ts = datetime.fromisoformat(payload["c"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts, uuid.UUID(payload["i"])
    except Exception:
        raise AppError(
            "invalid_cursor", "The pagination cursor is malformed", 400
        ) from None


def _is_self_only(user: Any) -> bool:
    return (
        check_permission(user, Permission.SELF_VIEW)
        and not check_permission(user, Permission.LEAVE_APPROVE)
    )


def _require_any_read(user: Any) -> None:
    if check_permission(user, Permission.LEAVE_APPROVE):
        return
    if check_permission(user, Permission.SELF_VIEW):
        return
    raise AppError(
        "forbidden", "Not permitted to view leave requests", 403
    )


def _is_capture(user: Any) -> bool:
    return check_permission(user, Permission.LEAVE_APPROVE)


def _require_submit_capability(user: Any, employee_id: uuid.UUID) -> bool:
    """True if caller is the employee (self); False if caller is an approver
    acting on behalf (capture). Raises forbidden otherwise."""
    if getattr(user, "employee_id", None) == employee_id:
        if check_permission(user, Permission.SELF_SUBMIT):
            return True
        raise AppError(
            "forbidden",
            "Not permitted to submit leave",
            status.HTTP_403_FORBIDDEN,
        )
    if _is_capture(user):
        return False
    raise AppError(
        "forbidden",
        "Not permitted to submit leave for this employee",
        status.HTTP_403_FORBIDDEN,
    )


def _load_leave_type(db: Any, leave_type_id: uuid.UUID) -> LeaveType:
    lt = db.get(LeaveType, leave_type_id)
    if lt is None or not lt.is_active:
        raise AppError("not_found", "Leave type not found", 404)
    if lt.unit == "hour":
        raise AppError(
            "unit_not_supported_yet",
            "Hour-unit leave types are not yet supported; use a day-unit type",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )
    return lt


def _load_employee(db: Any, user: Any, employee_id: uuid.UUID) -> Employee:
    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Employee not found", 404) from None
    emp = db.get(Employee, employee_id)
    if emp is None or emp.status == "terminated":
        raise AppError("not_found", "Employee not found", 404)
    return emp


def _load_request(
    db: Any, request_id: uuid.UUID, user: Any,
) -> LeaveRequest:
    row = db.get(LeaveRequest, request_id)
    if row is None:
        raise _not_found()
    if _is_self_only(user):
        if getattr(user, "employee_id", None) != row.employee_id:
            raise _not_found()
    else:
        try:
            assert_in_scope(user, row.employee_id, db)
        except ScopeViolation:
            raise _not_found() from None
    return row


def _ensure_no_hour_type(db: Any, request: LeaveRequest) -> LeaveType:
    lt = db.get(LeaveType, request.leave_type_id)
    if lt is None:
        raise AppError("not_found", "Leave type not found", 404)
    if lt.unit == "hour":
        raise AppError(
            "unit_not_supported_yet",
            "Hour-unit leave types are not yet supported",
            422,
        )
    return lt


def _current_step(
    db: Any, request: LeaveRequest,
) -> LeaveApprovalStep | None:
    for s in sorted(request.steps or [], key=lambda x: x.step_no):
        if s.status == "pending":
            return s
    return None


def _ensure_current_approver(db: Any, request: LeaveRequest, user: Any) -> LeaveApprovalStep:
    step = _current_step(db, request)
    if step is None:
        raise AppError(
            "step_already_decided",
            "No pending step for this request",
            status.HTTP_409_CONFLICT,
        )
    if (
        getattr(user, "employee_id", None) is not None
        and user.employee_id == request.employee_id
    ):
        raise AppError(
            "self_approval_forbidden",
            "The subject of a leave request cannot approve it",
            status.HTTP_403_FORBIDDEN,
        )
    if not check_permission(user, Permission.USER_MANAGE):
        matched = False
        if step.approver_user_id is not None and step.approver_user_id == getattr(user, "id", None):
            matched = True
        elif step.approver_role is not None:
            emp = db.get(Employee, request.employee_id)
            approver = (
                resolve_approver_for_role(db, emp, step.approver_role) if emp else None
            )
            if approver is not None and approver.id == getattr(user, "id", None):
                matched = True
        if not matched:
            raise AppError(
                "wrong_approver",
                "You are not the assigned approver for this step",
                status.HTTP_403_FORBIDDEN,
            )
    return step


def _ensure_balance(
    db: Any, request: LeaveRequest, leave_type: LeaveType,
) -> LeaveBalance:
    employee = db.get(Employee, request.employee_id)
    if employee is None:
        raise AppError("not_found", "Employee not found", 404)
    settings = None
    from app.db.tenant.models.payroll_settings import PayrollSettings
    settings = db.scalar(select(PayrollSettings).limit(1))
    bounds = compute_cycle_bounds(employee, leave_type, settings, request.from_date)
    balance = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == request.employee_id,
            LeaveBalance.leave_type_id == leave_type.id,
            LeaveBalance.cycle_start == bounds.start,
        )
    )
    if balance is None:
        balance = LeaveBalance(
            employee_id=request.employee_id,
            leave_type_id=leave_type.id,
            cycle_start=bounds.start,
            cycle_end=bounds.end,
            entitled=_zero(),
            accrued=_zero(),
            taken=_zero(),
            pending=_zero(),
            carried_in=_zero(),
            adjusted=_zero(),
            row_version=1,
        )
        db.add(balance)
        db.flush()
    return balance


def _rebuild_days(
    db: Any, request: LeaveRequest,
) -> list[LeaveRequestDay]:
    employee = db.get(Employee, request.employee_id)
    if employee is None:
        raise AppError("not_found", "Employee not found", 404)
    for old in list(request.days or []):
        db.delete(old)
    db.flush()
    computed = compute_request_days(
        db, employee, request.from_date, request.to_date
    )
    if not computed:
        raise AppError(
            "no_working_days_in_range",
            "The selected range contains no expected-working days",
            422,
        )
    new_rows: list[LeaveRequestDay] = []
    for wd, days in computed:
        row = LeaveRequestDay(
            leave_request_id=request.id,
            work_date=wd,
            days=days,
        )
        db.add(row)
        new_rows.append(row)
    request.days_requested = sum((d for _, d in computed), _zero())
    db.flush()
    return new_rows


def _apply_chain(
    db: Any, request: LeaveRequest, user: Any,
) -> None:
    employee = db.get(Employee, request.employee_id)
    if employee is None:
        raise AppError("not_found", "Employee not found", 404)
    lt = db.get(LeaveType, request.leave_type_id)
    if lt is None:
        raise AppError("not_found", "Leave type not found", 404)
    chain = build_approval_chain(db, employee, lt, user)
    for old in list(request.steps or []):
        db.delete(old)
    db.flush()
    if not chain:
        # Auto-approval: no approval chain (requires_approval=False)
        request.status = "approved"
        request.submitted_at = datetime.now(timezone.utc)
        request.decided_at = datetime.now(timezone.utc)
        request.decided_by_user_id = getattr(user, "id", None)
        request.decision_note = "Auto-approved (type does not require approval)"
        db.flush()
        _final_approval_side_effects(db, request, user)
        return
    for idx, role in enumerate(chain, start=1):
        approver = resolve_approver_for_role(db, employee, role)
        step = LeaveApprovalStep(
            leave_request_id=request.id,
            step_no=idx,
            approver_user_id=approver.id if approver is not None else None,
            approver_role=role,
            status="pending",
        )
        db.add(step)
    db.flush()


def _final_approval_side_effects(
    db: Any, request: LeaveRequest, user: Any,
) -> None:
    lt = db.get(LeaveType, request.leave_type_id)
    if lt is None:
        raise AppError("not_found", "Leave type not found", 404)
    balance = _ensure_balance(db, request, lt)
    convert_pending_to_taken(db, balance, request.days_requested)
    work_dates = [d.work_date for d in (request.days or [])]
    apply_leave_to_attendance(
        db, user=user, request=request, leave_type=lt, work_dates=work_dates
    )
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_request",
        entity_id=str(request.id),
        action="leave_request.approved",
        old_value={"status": "submitted"},
        new_value={
            "status": "approved",
            "days_requested": str(request.days_requested),
            "employee_id": str(request.employee_id),
        },
    ))
    db.flush()


def _after_step_decided(
    db: Any, request: LeaveRequest, user: Any,
) -> None:
    remaining = list(
        db.scalars(
            select(LeaveApprovalStep).where(
                LeaveApprovalStep.leave_request_id == request.id,
                LeaveApprovalStep.status == "pending",
            )
        ).all()
    )
    if remaining:
        return
    request.status = "approved"
    request.decided_at = datetime.now(timezone.utc)
    request.decided_by_user_id = getattr(user, "id", None)
    db.flush()
    _final_approval_side_effects(db, request, user)


def _capture_note_if_needed(user: Any, request: LeaveRequest, note: str | None) -> str | None:
    is_capture_self_approve = (
        request.captured_by_user_id is not None
        and request.captured_by_user_id == getattr(user, "id", None)
        and getattr(user, "employee_id", None) != request.employee_id
    )
    if is_capture_self_approve:
        if note is None or not note.strip():
            raise AppError(
                "capture_requires_note",
                "Capturing user approving own capture requires a note",
                422,
            )
        return note.strip()
    return note


@router.get("", response_model=LeaveRequestListOut)
def list_leave_requests(
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
    employee_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    from_date_gte: date | None = Query(None),
    to_date_lte: date | None = Query(None),
    limit: int = Query(_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    cursor: str | None = Query(None),
) -> LeaveRequestListOut:
    _require_any_read(user)

    q = select(LeaveRequest)
    if _is_self_only(user):
        own = getattr(user, "employee_id", None)
        if own is None:
            raise AppError(
                "no_employee_record",
                "User has no employee record",
                404,
            )
        q = q.where(LeaveRequest.employee_id == own)
    else:
        if employee_id is not None:
            q = q.where(LeaveRequest.employee_id == employee_id)
        q = apply_scope(q, user, db, model=LeaveRequest)

    if status_filter is not None:
        q = q.where(LeaveRequest.status == status_filter)
    if from_date_gte is not None:
        q = q.where(LeaveRequest.from_date >= from_date_gte)
    if to_date_lte is not None:
        q = q.where(LeaveRequest.to_date <= to_date_lte)

    if cursor is not None:
        ts, cid = _decode_cursor(cursor)
        q = q.where(
            or_(
                LeaveRequest.created_at > ts,
                (LeaveRequest.created_at == ts) & (LeaveRequest.id > cid),
            )
        )

    q = q.order_by(
        LeaveRequest.created_at.asc(), LeaveRequest.id.asc()
    ).limit(limit + 1)
    rows = list(db.scalars(q).all())
    next_cursor = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.created_at, last.id)

    return LeaveRequestListOut(
        items=[_to_out(r) for r in rows],
        next_cursor=next_cursor,
    )


@router.get("/{request_id}", response_model=LeaveRequestOut)
def get_leave_request(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    _require_any_read(user)
    return _to_out(_load_request(db, request_id, user))


@router.post(
    "", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED
)
def create_leave_request(
    body: LeaveRequestIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    employee_id = body.employee_id or getattr(user, "employee_id", None)
    if employee_id is None:
        raise AppError(
            "no_employee_record",
            "Provide employee_id (capture-on-behalf) or use a user with an "
            "employee record",
            422,
        )
    _require_submit_capability(user, employee_id)

    employee = _load_employee(db, user, employee_id)
    lt = _load_leave_type(db, body.leave_type_id)

    request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=lt.id,
        from_date=body.from_date,
        to_date=body.to_date,
        days_requested=_zero(),
        reason=body.reason,
        status="draft",
        captured_by_user_id=getattr(user, "id", None),
        row_version=1,
    )
    db.add(request)
    db.flush()

    _rebuild_days(db, request)

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_request",
        entity_id=str(request.id),
        action="leave_request.create",
        old_value=None,
        new_value=redact_for_audit({
            "employee_id": str(employee.id),
            "leave_type_id": str(lt.id),
            "from_date": body.from_date.isoformat(),
            "to_date": body.to_date.isoformat(),
            "days_requested": str(request.days_requested),
        }),
    ))
    db.commit()
    db.refresh(request)
    return _to_out(request)


@router.patch("/{request_id}", response_model=LeaveRequestOut)
def patch_leave_request(
    request_id: uuid.UUID,
    body: LeaveRequestPatch,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    request = _load_request(db, request_id, user)
    _require_submit_capability(user, request.employee_id)
    if request.status != "draft":
        raise AppError(
            "not_draft",
            f"Leave request is {request.status}; only draft can be edited",
            409,
        )
    if request.row_version != body.row_version:
        raise AppError(
            "record_changed",
            f"Leave request has changed (current {request.row_version})",
            409,
            {"current_row_version": request.row_version},
        )

    old = _to_out(request).model_dump(mode="json")
    if body.from_date is not None:
        request.from_date = body.from_date
    if body.to_date is not None:
        request.to_date = body.to_date
    if body.reason is not None:
        request.reason = body.reason
    if request.to_date < request.from_date:
        raise AppError(
            "invalid_range",
            "to_date must be on or after from_date",
            422,
        )
    _rebuild_days(db, request)
    request.row_version = request.row_version + 1
    db.flush()

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_request",
        entity_id=str(request.id),
        action="leave_request.update",
        old_value=redact_for_audit(old),
        new_value=redact_for_audit(_to_out(request).model_dump(mode="json")),
    ))
    db.commit()
    db.refresh(request)
    return _to_out(request)


@router.post("/{request_id}/submit", response_model=LeaveRequestOut)
def submit_leave_request(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    request = _load_request(db, request_id, user)
    _require_submit_capability(user, request.employee_id)
    if request.status != "draft":
        raise AppError(
            "not_draft",
            f"Leave request is {request.status}; only draft can be submitted",
            409,
        )

    lt = _ensure_no_hour_type(db, request)
    days = list(request.days or [])
    work_dates = [d.work_date for d in days]
    check_days_not_locked(db, request.employee_id, work_dates)

    balance = _ensure_balance(db, request, lt)
    available = available_balance(balance)
    if available - request.days_requested < _zero() and not lt.allow_negative:
        raise AppError(
            "insufficient_balance",
            f"Available {available}, requested {request.days_requested} "
            f"(negative not allowed)",
            422,
            {
                "available": str(available),
                "requested": str(request.days_requested),
            },
        )

    reserve_pending(db, balance, request.days_requested)
    request.submitted_at = datetime.now(timezone.utc)
    request.row_version = request.row_version + 1
    db.flush()

    _apply_chain(db, request, user)
    if request.status == "submitted":
        db.add(AuditLog(
            id=uuid.uuid4(),
            actor_user_id=getattr(user, "id", None),
            actor_role=getattr(user, "role", None),
            entity_type="leave_request",
            entity_id=str(request.id),
            action="leave_request.submit",
            old_value={"status": "draft"},
            new_value={"status": "submitted"},
        ))
    db.commit()
    db.refresh(request)
    return _to_out(request)


@router.post("/{request_id}/cancel", response_model=LeaveRequestOut)
def cancel_leave_request(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    request = _load_request(db, request_id, user)
    _require_submit_capability(user, request.employee_id)

    if request.status == "draft":
        request.status = "cancelled"
        request.row_version = request.row_version + 1
        db.flush()
    elif request.status == "submitted":
        lt = _ensure_no_hour_type(db, request)
        balance = _ensure_balance(db, request, lt)
        release_pending(db, balance, request.days_requested)
        request.status = "cancelled"
        request.row_version = request.row_version + 1
        db.flush()
    elif request.status == "approved":
        taken_future = [
            d.work_date
            for d in (request.days or [])
            if d.work_date <= date.today()
        ]
        if taken_future:
            raise AppError(
                "cannot_cancel_after_days_taken",
                "Cannot cancel an approved leave with days already started",
                409,
                {"started_days": [d.isoformat() for d in taken_future]},
            )
        lt = _ensure_no_hour_type(db, request)
        balance = _ensure_balance(db, request, lt)
        balance.taken = max(_zero(), balance.taken - request.days_requested)
        balance.row_version = balance.row_version + 1
        db.flush()
        revert_leave_from_attendance(db, user=user, request=request)
        request.status = "cancelled"
        request.row_version = request.row_version + 1
        db.flush()
    else:
        raise AppError(
            "cannot_cancel",
            f"Cannot cancel a leave request in status '{request.status}'",
            409,
        )

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_request",
        entity_id=str(request.id),
        action="leave_request.cancel",
        old_value={"status": "prior"},
        new_value={"status": "cancelled"},
    ))
    db.commit()
    db.refresh(request)
    return _to_out(request)


@router.get("/{request_id}/steps", response_model=list[LeaveApprovalStepOut])
def get_leave_steps(
    request_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> list[LeaveApprovalStepOut]:
    _require_any_read(user)
    request = _load_request(db, request_id, user)
    steps = sorted(request.steps or [], key=lambda s: s.step_no)
    return [LeaveApprovalStepOut.model_validate(s) for s in steps]


@router.post(
    "/{request_id}/steps/{step_id}/decide", response_model=LeaveRequestOut
)
def decide_step(
    request_id: uuid.UUID,
    step_id: uuid.UUID,
    body: StepDecideIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    if not check_permission(user, Permission.LEAVE_APPROVE):
        raise AppError("forbidden", "LEAVE_APPROVE required", 403)
    request = _load_request(db, request_id, user)
    step = db.get(LeaveApprovalStep, step_id)
    if step is None or step.leave_request_id != request.id:
        raise AppError("not_found", "Approval step not found", 404)
    if step.status != "pending":
        raise AppError(
            "step_already_decided",
            f"Step is already {step.status}",
            409,
        )
    current = _current_step(db, request)
    if current is None or current.id != step.id:
        raise AppError(
            "wrong_step",
            "Decisions must be applied to the current pending step",
            409,
        )
    _ensure_current_approver(db, request, user)

    note = _capture_note_if_needed(user, request, body.note)

    if body.approve:
        step.status = "approved"
        step.decided_at = datetime.now(timezone.utc)
        step.note = note
        db.flush()
        _after_step_decided(db, request, user)
    else:
        step.status = "rejected"
        step.decided_at = datetime.now(timezone.utc)
        step.note = note
        lt = _ensure_no_hour_type(db, request)
        balance = _ensure_balance(db, request, lt)
        release_pending(db, balance, request.days_requested)
        request.status = "rejected"
        request.decided_at = datetime.now(timezone.utc)
        request.decided_by_user_id = getattr(user, "id", None)
        request.decision_note = note
        request.row_version = request.row_version + 1
        db.flush()

    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_request",
        entity_id=str(request.id),
        action="leave_request.decide",
        old_value={"status": "submitted"},
        new_value={
            "status": request.status,
            "step_no": step.step_no,
            "approve": body.approve,
        },
    ))
    db.commit()
    db.refresh(request)
    return _to_out(request)


@router.post("/{request_id}/decide", response_model=LeaveRequestOut)
def decide_shortcut(
    request_id: uuid.UUID,
    body: DecideIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    if not check_permission(user, Permission.LEAVE_APPROVE):
        raise AppError("forbidden", "LEAVE_APPROVE required", 403)
    request = _load_request(db, request_id, user)
    if request.status == "draft":
        # auto-submit first
        _require_submit_capability(user, request.employee_id)
        lt = _ensure_no_hour_type(db, request)
        balance = _ensure_balance(db, request, lt)
        check_days_not_locked(
            db, request.employee_id, [d.work_date for d in (request.days or [])]
        )
        available = available_balance(balance)
        if available - request.days_requested < _zero() and not lt.allow_negative:
            raise AppError(
                "insufficient_balance",
                f"Available {available}, requested {request.days_requested}",
                422,
            )
        reserve_pending(db, balance, request.days_requested)
        request.submitted_at = datetime.now(timezone.utc)
        _apply_chain(db, request, user)
        db.flush()
        if request.status == "approved":
            db.commit()
            db.refresh(request)
            return _to_out(request)

    step = _current_step(db, request)
    if step is None:
        raise AppError(
            "step_already_decided",
            "No pending step to decide",
            409,
        )
    _ensure_current_approver(db, request, user)
    note = _capture_note_if_needed(user, request, body.note)

    if body.approve:
        step.status = "approved"
        step.decided_at = datetime.now(timezone.utc)
        step.note = note
        db.flush()
        _after_step_decided(db, request, user)
    else:
        step.status = "rejected"
        step.decided_at = datetime.now(timezone.utc)
        step.note = note
        lt = _ensure_no_hour_type(db, request)
        balance = _ensure_balance(db, request, lt)
        release_pending(db, balance, request.days_requested)
        request.status = "rejected"
        request.decided_at = datetime.now(timezone.utc)
        request.decided_by_user_id = getattr(user, "id", None)
        request.decision_note = note
        request.row_version = request.row_version + 1
        db.flush()

    db.commit()
    db.refresh(request)
    return _to_out(request)


@router.post("/{request_id}/advance", response_model=LeaveRequestOut)
def advance_request(
    request_id: uuid.UUID,
    body: DecideIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(get_current_user)],
) -> LeaveRequestOut:
    if not check_permission(user, Permission.USER_MANAGE):
        raise AppError("forbidden", "USER_MANAGE required", 403)
    request = _load_request(db, request_id, user)
    step = _current_step(db, request)
    if step is None:
        raise AppError(
            "step_already_decided",
            "No pending step to advance",
            409,
        )
    step.status = "approved"
    step.decided_at = datetime.now(timezone.utc)
    step.note = (body.note or "") + f" [advanced by user {getattr(user, 'id', None)}]"
    db.flush()
    _after_step_decided(db, request, user)
    db.add(AuditLog(
        id=uuid.uuid4(),
        actor_user_id=getattr(user, "id", None),
        actor_role=getattr(user, "role", None),
        entity_type="leave_request",
        entity_id=str(request.id),
        action="leave_request.advance",
        old_value=None,
        new_value={"step_no": step.step_no, "new_status": request.status},
    ))
    db.commit()
    db.refresh(request)
    return _to_out(request)
"""Payroll change request service (Chapter 4, Bundle 004a-iv-a + iv-b + M6 Stage A + M6 Part 2 Stage 2).

F3: HR submits, payroll_admin approves, approver != requester. Pending
requests never touch employee_earning / employee_deduction / employee fields.
Approval writes through in the same transaction as the status flip.

004a-iv-b hardening for employee_field_update:
  - payload requires row_version + at least one mutable field
  - _apply checks row_version at approval time (stale request -> record_changed)
  - _apply refuses if no field was actually written (defence in depth)

M3 Stage C: individual approve / reject / cancel refuse to act on any
change request whose assignment_id IS NOT NULL. These children are audit
envelopes controlled exclusively by the salary-assignment service.

M6 Stage A: approve / reject / cancel now enforce employee scope via
_load_scoped_request. Order matters — scope is checked FIRST, before the
assignment-child 409 and before the not-pending 409, so an out-of-scope
request returns an indistinguishable 404 instead of leaking existence
or status.

M6 Part 2 Stage 2: _apply refuses with 409 locked_period_affects if
approving the CR would alter a locked period. Effective-window overlap is
used; the existing row's window is included for update/deactivate kinds
because a shorten removes from the period and an extend adds to it.
`employee_field_update` blocks if the employee has a payslip in any locked
period. Malformed payloads fail closed.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.change_request import KINDS, PayrollChangeRequest
from app.db.tenant.models.pay import (
    DeductionType, EarningType, EmployeeDeduction, EmployeeEarning,
)
from app.db.tenant.models.people import Employee
from app.services.payroll_audit import write_audit


# ---------------------------------------------------------------------------
# Per-kind payload schemas (validated at submit time)
# ---------------------------------------------------------------------------

class _EarningCreatePayload(BaseModel):
    earning_type_id: uuid.UUID
    amount: Decimal | None = Field(None, ge=0)
    rate: Decimal | None = Field(None, ge=0)
    effective_from: date
    effective_to: date | None = None


class _EarningUpdatePayload(BaseModel):
    target_id: uuid.UUID
    row_version: int
    amount: Decimal | None = Field(None, ge=0)
    rate: Decimal | None = Field(None, ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool | None = None


class _EarningDeactivatePayload(BaseModel):
    target_id: uuid.UUID
    row_version: int


class _DeductionCreatePayload(BaseModel):
    deduction_type_id: uuid.UUID
    amount: Decimal = Field(..., ge=0)
    effective_from: date
    effective_to: date | None = None


class _DeductionUpdatePayload(BaseModel):
    target_id: uuid.UUID
    row_version: int
    amount: Decimal | None = Field(None, ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool | None = None


class _DeductionDeactivatePayload(BaseModel):
    target_id: uuid.UUID
    row_version: int


class _EmployeeFieldUpdatePayload(BaseModel):
    row_version: int
    contracted_weekly_hours: float | None = Field(None, ge=0)
    medical_scheme_members: int | None = Field(None, ge=0)
    uif_exempt: bool | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> "_EmployeeFieldUpdatePayload":
        if all(
            getattr(self, name) is None
            for name in ("contracted_weekly_hours", "medical_scheme_members", "uif_exempt")
        ):
            raise ValueError(
                "at least one of contracted_weekly_hours, medical_scheme_members, "
                "uif_exempt must be provided"
            )
        return self


SUBMIT_SCHEMAS: dict[str, type[BaseModel]] = {
    "employee_earning_create": _EarningCreatePayload,
    "employee_earning_update": _EarningUpdatePayload,
    "employee_earning_deactivate": _EarningDeactivatePayload,
    "employee_deduction_create": _DeductionCreatePayload,
    "employee_deduction_update": _DeductionUpdatePayload,
    "employee_deduction_deactivate": _DeductionDeactivatePayload,
    "employee_field_update": _EmployeeFieldUpdatePayload,
}


# ---------------------------------------------------------------------------
# Assignment-child guard (design §5.11 Rule 1) + M6 Stage A scope guard
# ---------------------------------------------------------------------------

_ASSIGNMENT_CHILD_GUARD: dict[str, str] = {
    "approve": "assignment_requires_batch_approve",
    "reject": "assignment_requires_batch_reject",
    "cancel": "assignment_requires_batch_cancel",
}


def _load_scoped_request(
    db: Session, user: Any, request_id: uuid.UUID,
) -> PayrollChangeRequest:
    """Load the request; 404 if missing or outside the caller's employee scope.

    Scope is checked FIRST — before any status or assignment-child guard —
    so an out-of-scope request cannot leak its existence or status by
    responding differently from a nonexistent one.
    """
    row = db.scalar(
        select(PayrollChangeRequest).where(
            PayrollChangeRequest.id == request_id,
        )
    )
    if row is None:
        raise AppError("not_found", "Change request not found", 404)
    try:
        assert_in_scope(user, row.employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Change request not found", 404) from None
    return row


def _guard_assignment_child(row: PayrollChangeRequest, action: str) -> None:
    """Refuse if the target change request is controlled by an assignment.

    Called after _load_scoped_request so an out-of-scope assignment-linked
    request has already responded 404 (existence not leaked).
    """
    if row.assignment_id is not None:
        raise AppError(
            _ASSIGNMENT_CHILD_GUARD[action],
            f"This change request is controlled by salary assignment "
            f"{row.assignment_id}; use the assignment {action} endpoint",
            409,
        )


def _guard_pending(row: PayrollChangeRequest) -> None:
    if row.status != "pending":
        raise AppError(
            "not_pending",
            f"Change request is {row.status}, cannot transition",
            409,
        )


# ---------------------------------------------------------------------------
# Submit / approve / reject / cancel
# ---------------------------------------------------------------------------

def submit_change_request(
    db: Session,
    user: Any,
    *,
    kind: str,
    employee_id: uuid.UUID,
    payload: dict,
    note: str | None = None,
) -> PayrollChangeRequest:
    if kind not in KINDS:
        raise AppError(
            "unknown_kind", f"change request kind {kind!r} is not supported", 422,
        )
    schema = SUBMIT_SCHEMAS[kind]
    try:
        validated = schema(**payload)
    except ValidationError as exc:
        raise AppError(
            "invalid_payload",
            f"payload does not match {kind} schema: {exc.errors()}",
            422,
        ) from None

    try:
        assert_in_scope(user, employee_id, db)
    except ScopeViolation:
        raise AppError("not_found", "Employee not found", 404)

    emp = db.scalar(select(Employee).where(Employee.id == employee_id))
    if emp is None:
        raise AppError("not_found", "Employee not found", 404)

    request = PayrollChangeRequest(
        id=uuid.uuid4(),
        kind=kind,
        employee_id=employee_id,
        payload=validated.model_dump(mode="json"),
        status="pending",
        requested_by_user_id=getattr(user, "id", None),
        decision_note=note,
    )
    db.add(request)
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=request.id, action="submit",
        new_value={
            "kind": kind,
            "employee_id": str(employee_id),
            "payload": validated.model_dump(mode="json"),
        },
    )
    return request


def approve_change_request(
    db: Session, user: Any, request_id: uuid.UUID,
) -> tuple[PayrollChangeRequest, uuid.UUID]:
    row = _load_scoped_request(db, user, request_id)  # 404 if missing or out-of-scope
    _guard_assignment_child(row, "approve")            # 409 if assignment-linked
    _guard_pending(row)                                 # 409 if not pending
    _reject_self_approval(row, user)                    # 409 if self-approval

    applied_id = _apply(db, row, approver_user=user)
    row.status = "approved"
    row.decided_by_user_id = getattr(user, "id", None)
    row.decided_at = datetime.utcnow()
    row.applied_entity_id = applied_id
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=row.id, action="approve",
        old_value={"status": "pending"},
        new_value={"status": "approved", "applied_entity_id": str(applied_id)},
    )
    return row, applied_id


def reject_change_request(
    db: Session, user: Any, request_id: uuid.UUID, note: str,
) -> PayrollChangeRequest:
    row = _load_scoped_request(db, user, request_id)  # 404 if missing or out-of-scope
    _guard_assignment_child(row, "reject")             # 409 if assignment-linked
    _guard_pending(row)                                 # 409 if not pending
    _reject_self_approval(row, user)                    # 409 if self-approval

    row.status = "rejected"
    row.decided_by_user_id = getattr(user, "id", None)
    row.decided_at = datetime.utcnow()
    row.decision_note = note
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=row.id, action="reject",
        old_value={"status": "pending"},
        new_value={"status": "rejected", "note": note},
    )
    return row


def cancel_change_request(
    db: Session, user: Any, request_id: uuid.UUID,
) -> PayrollChangeRequest:
    row = _load_scoped_request(db, user, request_id)  # 404 if missing or out-of-scope
    _guard_assignment_child(row, "cancel")             # 409 if assignment-linked
    _guard_pending(row)                                 # 409 if not pending

    if row.requested_by_user_id != getattr(user, "id", None):
        raise AppError(
            "not_requester", "Only the requester may cancel a pending change", 403,
        )
    row.status = "cancelled"
    row.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=row.id, action="cancel",
        old_value={"status": "pending"}, new_value={"status": "cancelled"},
    )
    return row


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _reject_self_approval(request: PayrollChangeRequest, user: Any) -> None:
    if request.requested_by_user_id == getattr(user, "id", None):
        raise AppError(
            "self_approval_forbidden",
            "Approver must differ from requester",
            409,
        )


def _apply(
    db: Session, request: PayrollChangeRequest, *, approver_user: Any,
) -> uuid.UUID:
    # M6 Part 2 Stage 2: refuse approval if the change would alter a locked
    # period. Guard runs before any write so a blocked CR leaves no residue.
    #
    # Residual concurrency note: this guard reads locked periods, but a
    # concurrent finalise() that is turning an OPEN period into LOCKED can
    # interleave with this read. Full closure of that race is Stage 4's job
    # (content-hash comparison at finalise). See payroll_runner.finalise
    # docstring.
    from app.services.payroll_runner import _cr_could_affect_locked_periods

    locked_period, reason = _cr_could_affect_locked_periods(db, request)
    if locked_period is not None:
        raise AppError(
            "locked_period_affects",
            f"approving this change request would alter locked period "
            f"{locked_period.period_key!r}; reopen the period first",
            409,
            {
                "period_id": str(locked_period.id),
                "period_key": locked_period.period_key,
                "cr_id": str(request.id),
                "cr_kind": request.kind,
            },
        )
    if reason is not None:
        raise AppError(
            "locked_period_affects",
            f"cannot determine whether approving this change request would "
            f"alter a locked period ({reason}); cancel or reject the request "
            f"instead",
            409,
            {
                "cr_id": str(request.id),
                "cr_kind": request.kind,
                "reason": reason,
            },
        )

    kind = request.kind
    p = request.payload

    if kind == "employee_earning_create":
        row = EmployeeEarning(
            id=uuid.uuid4(),
            employee_id=request.employee_id,
            earning_type_id=uuid.UUID(p["earning_type_id"]),
            amount=Decimal(p["amount"]) if p.get("amount") is not None else None,
            rate=Decimal(p["rate"]) if p.get("rate") is not None else None,
            effective_from=date.fromisoformat(p["effective_from"]),
            effective_to=date.fromisoformat(p["effective_to"]) if p.get("effective_to") else None,
            is_active=True,
        )
        _validate_amount_or_rate(row.amount, row.rate)
        db.add(row)
        db.flush()
        return row.id

    if kind == "employee_earning_update":
        row = _load_scoped(db, EmployeeEarning, request.employee_id, uuid.UUID(p["target_id"]))
        _check_row_version(row, p["row_version"])
        _apply_patch(row, p, {"amount", "rate", "effective_from", "effective_to", "is_active"})
        _validate_amount_or_rate(row.amount, row.rate)
        row.row_version += 1
        db.flush()
        return row.id

    if kind == "employee_earning_deactivate":
        row = _load_scoped(db, EmployeeEarning, request.employee_id, uuid.UUID(p["target_id"]))
        _check_row_version(row, p["row_version"])
        row.is_active = False
        row.row_version += 1
        db.flush()
        return row.id

    if kind == "employee_deduction_create":
        row = EmployeeDeduction(
            id=uuid.uuid4(),
            employee_id=request.employee_id,
            deduction_type_id=uuid.UUID(p["deduction_type_id"]),
            amount=Decimal(p["amount"]),
            balance=Decimal("0.00"),
            effective_from=date.fromisoformat(p["effective_from"]),
            effective_to=date.fromisoformat(p["effective_to"]) if p.get("effective_to") else None,
            is_active=True,
        )
        db.add(row)
        db.flush()
        return row.id

    if kind == "employee_deduction_update":
        row = _load_scoped(db, EmployeeDeduction, request.employee_id, uuid.UUID(p["target_id"]))
        _check_row_version(row, p["row_version"])
        _apply_patch(row, p, {"amount", "effective_from", "effective_to", "is_active"})
        row.row_version += 1
        db.flush()
        return row.id

    if kind == "employee_deduction_deactivate":
        row = _load_scoped(db, EmployeeDeduction, request.employee_id, uuid.UUID(p["target_id"]))
        _check_row_version(row, p["row_version"])
        row.is_active = False
        row.row_version += 1
        db.flush()
        return row.id

    if kind == "employee_field_update":
        emp = db.scalar(select(Employee).where(Employee.id == request.employee_id))
        if emp is None:
            raise AppError("not_found", "Employee not found", 404)
        expected_rv = p.get("row_version")
        if expected_rv is not None and emp.row_version != expected_rv:
            raise AppError(
                "record_changed",
                f"row_version mismatch: sent {expected_rv}, current {emp.row_version}",
                409,
            )
        applied_any = False
        for field_name in ("contracted_weekly_hours", "medical_scheme_members", "uif_exempt"):
            if field_name in p and p[field_name] is not None:
                setattr(emp, field_name, p[field_name])
                applied_any = True
        if not applied_any:
            raise AppError(
                "empty_update",
                "no recognised fields to update on employee",
                422,
            )
        emp.row_version += 1
        db.flush()
        return emp.id

    raise AppError("unknown_kind", f"no handler for kind {kind!r}", 500)


def _load_scoped(db: Session, model: Any, employee_id: uuid.UUID, target_id: uuid.UUID) -> Any:
    row = db.scalar(
        select(model).where(model.id == target_id, model.employee_id == employee_id)
    )
    if row is None:
        raise AppError("not_found", "Target row not found for this employee", 404)
    return row


def _check_row_version(row: Any, expected: int) -> None:
    if row.row_version != expected:
        raise AppError(
            "record_changed",
            f"row_version mismatch: sent {expected}, current {row.row_version}",
            409,
        )


def _apply_patch(row: Any, payload: dict, allowed: set[str]) -> None:
    for field_name in allowed:
        if field_name in payload and payload[field_name] is not None:
            value = payload[field_name]
            if field_name in ("effective_from", "effective_to") and value is not None:
                value = date.fromisoformat(value)
            setattr(row, field_name, value)


def _validate_amount_or_rate(amount: Decimal | None, rate: Decimal | None) -> None:
    if amount is None and rate is None:
        raise AppError("amount_or_rate_required", "Provide amount or rate", 422)
    if amount is not None and rate is not None:
        raise AppError("amount_xor_rate", "Provide amount or rate, not both", 422)

# END OF FILE
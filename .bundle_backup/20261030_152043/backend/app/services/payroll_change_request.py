"""Payroll change request service (Chapter 4, Bundle 004a-iv-a).

F3: HR submits, payroll_admin approves, approver != requester. Pending
requests never touch employee_earning / employee_deduction / employee fields.
Approval writes through in the same transaction as the status flip.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError
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
# Per-kind payload schemas (internal — validated at submit time)
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
    contracted_weekly_hours: float | None = None
    medical_scheme_members: int | None = None
    uif_exempt: bool | None = None


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
    request = _load_pending(db, request_id)
    _reject_self_approval(request, user)

    applied_id = _apply(db, request, approver_user=user)
    request.status = "approved"
    request.decided_by_user_id = getattr(user, "id", None)
    request.decided_at = datetime.utcnow()
    request.applied_entity_id = applied_id
    request.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=request.id, action="approve",
        old_value={"status": "pending"},
        new_value={"status": "approved", "applied_entity_id": str(applied_id)},
    )
    return request, applied_id


def reject_change_request(
    db: Session, user: Any, request_id: uuid.UUID, note: str,
) -> PayrollChangeRequest:
    request = _load_pending(db, request_id)
    _reject_self_approval(request, user)
    request.status = "rejected"
    request.decided_by_user_id = getattr(user, "id", None)
    request.decided_at = datetime.utcnow()
    request.decision_note = note
    request.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=request.id, action="reject",
        old_value={"status": "pending"},
        new_value={"status": "rejected", "note": note},
    )
    return request


def cancel_change_request(
    db: Session, user: Any, request_id: uuid.UUID,
) -> PayrollChangeRequest:
    request = _load_pending(db, request_id)
    if request.requested_by_user_id != getattr(user, "id", None):
        raise AppError(
            "not_requester", "Only the requester may cancel a pending change", 403,
        )
    request.status = "cancelled"
    request.row_version += 1
    db.flush()
    write_audit(
        db, user,
        entity_type="payroll_change_request", entity_id=request.id, action="cancel",
        old_value={"status": "pending"}, new_value={"status": "cancelled"},
    )
    return request


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _load_pending(db: Session, request_id: uuid.UUID) -> PayrollChangeRequest:
    request = db.scalar(
        select(PayrollChangeRequest).where(PayrollChangeRequest.id == request_id)
    )
    if request is None:
        raise AppError("not_found", "Change request not found", 404)
    if request.status != "pending":
        raise AppError(
            "not_pending",
            f"Change request is {request.status}, cannot transition",
            409,
        )
    return request


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
        for field_name in ("contracted_weekly_hours", "medical_scheme_members", "uif_exempt"):
            if field_name in p and p[field_name] is not None:
                setattr(emp, field_name, p[field_name])
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

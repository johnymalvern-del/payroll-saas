"""Biometric consent endpoints.

Three things live here and only one of them is implemented:

  * recording consent            -- implemented
  * withdrawing consent          -- implemented
  * creating a biometric enrolment -- REFUSED, always

The third endpoint exists deliberately. Phase 6 is blocked by section 8 of
BIOMETRIC_PRIVACY_AND_RETENTION_POLICY.md, which requires a signed POPIA
approval record before any enrolment capability is built. Rather than leave a
comment nobody reads, the gate is enforced by a real endpoint that returns 403
with a specific code. When approval lands, this is the single place that
changes, and until then a client that tries gets a clear answer instead of a
404 that looks like a routing bug.

Note that the database enforces the same gate independently:
biometric_enrolment.template_encrypted is NOT NULL, so no enrolment row can
exist without an actual template. There is no code path that could write one.

Consent rows are never deleted. Withdrawal sets withdrawn_at, because policy
section 2 requires revocation to be auditable and a deleted row cannot record
that consent was ever given.

Withdrawal is never blocked by a payroll lock. Locking a period preserves the
pay figures; it does not suspend a data subject's rights.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.biometric_consent_schemas import (
    BiometricNotApprovedOut,
    ConsentGrantIn,
    ConsentRecordOut,
    ConsentStatusOut,
    EnrolmentOut,
    WithdrawIn,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.core.scope import ScopeViolation, assert_in_scope
from app.db.tenant.models.people import BiometricConsent, BiometricEnrolment, Employee
from app.db.tenant.models.platform import AuditLog

router = APIRouter(prefix="/employees", tags=["biometric-consent"])


def _get_employee(db: Any, employee_id: uuid.UUID, user: Any) -> Employee:
    """Fetch an employee, honouring the caller's scope.

    A scoped-out employee returns 404 rather than 403: telling a branch
    manager that an employee exists elsewhere in the tenant leaks the
    org chart, and the scope system is used elsewhere in this codebase for
    exactly that reason.
    """
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError("record_not_found", "Employee not found", 404)
    try:
        assert_in_scope(user, employee.id, db)
    except ScopeViolation:
        raise AppError("record_not_found", "Employee not found", 404) from None
    return employee


def _active_consent(db: Any, employee_id: uuid.UUID) -> BiometricConsent | None:
    return db.scalar(
        select(BiometricConsent)
        .where(
            BiometricConsent.employee_id == employee_id,
            BiometricConsent.withdrawn_at.is_(None),
        )
        .order_by(BiometricConsent.accepted_at.desc())
        .limit(1)
    )


def _live_enrolment(db: Any, employee_id: uuid.UUID) -> BiometricEnrolment | None:
    return db.scalar(
        select(BiometricEnrolment)
        .where(
            BiometricEnrolment.employee_id == employee_id,
            BiometricEnrolment.revoked_at.is_(None),
        )
        .order_by(BiometricEnrolment.enrolled_at.desc())
        .limit(1)
    )


def _audit(
    db: Any,
    *,
    action: str,
    employee_id: uuid.UUID,
    entity_id: str,
    new_value: dict,
) -> None:
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            actor_user_id=None,
            actor_role=None,
            entity_type="biometric_consent",
            entity_id=entity_id,
            action=action,
            old_value=None,
            new_value={"employee_id": str(employee_id), **new_value},
            request_id=None,
        )
    )


@router.get("/{employee_id}/biometric-consent", response_model=ConsentStatusOut)
def get_consent_status(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.BIOMETRIC_ENROL))],
) -> ConsentStatusOut:
    """Current biometric state. Reads never require anything beyond the scope."""
    _get_employee(db, employee_id, user)

    consent = _active_consent(db, employee_id)
    enrolment = _live_enrolment(db, employee_id)

    if consent is None:
        reason = "no_consent"
    elif enrolment is None:
        reason = "no_enrolment"
    elif enrolment.consent_id != consent.id:
        # An enrolment tied to an older consent is not covered by the current
        # one. Withdrawal revokes the enrolment, so this should be unreachable
        # -- reporting it rather than pretending it is fine.
        reason = "enrolment_not_covered_by_current_consent"
    else:
        reason = None

    return ConsentStatusOut(
        employee_id=employee_id,
        has_consent=consent is not None,
        consent=ConsentRecordOut.model_validate(consent) if consent else None,
        enrolment=EnrolmentOut.model_validate(enrolment) if enrolment else None,
        biometric_active=(consent is not None and enrolment is not None and reason is None),
        unavailable_reason=reason,
    )


@router.post(
    "/{employee_id}/biometric-consent",
    response_model=ConsentRecordOut,
    status_code=status.HTTP_201_CREATED,
)
def grant_consent(
    employee_id: uuid.UUID,
    payload: ConsentGrantIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.BIOMETRIC_ENROL))],
) -> ConsentRecordOut:
    """Record that an employee has consented.

    This records consent; it does not enrol anyone. No biometric data is
    captured here, which is why this endpoint is permitted while the approval
    gate is closed.
    """
    _get_employee(db, employee_id, user)

    if _active_consent(db, employee_id) is not None:
        raise AppError(
            "consent_already_active",
            "This employee already has an active biometric consent. "
            "Withdraw it before recording a new one.",
            409,
        )

    consent = BiometricConsent(
        employee_id=employee_id,
        consent_text_version=payload.consent_text_version,
        captured_by=getattr(user, "id", None),
        method=payload.method,
    )
    db.add(consent)
    db.flush()

    _audit(
        db,
        action="biometric_consent.granted",
        employee_id=employee_id,
        entity_id=str(consent.id),
        new_value={
            "consent_text_version": payload.consent_text_version,
            "method": payload.method,
        },
    )
    db.commit()
    db.refresh(consent)
    return ConsentRecordOut.model_validate(consent)


@router.post(
    "/{employee_id}/biometric-consent/withdraw",
    response_model=ConsentRecordOut,
)
def withdraw_consent(
    employee_id: uuid.UUID,
    payload: WithdrawIn,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.BIOMETRIC_ENROL))],
) -> ConsentRecordOut:
    """Withdraw consent and revoke any enrolment that depended on it.

    Never blocked by a payroll lock or an open period: withdrawal is a data
    subject right and suppressing it to protect a pay run would be indefensible.

    The consent row is retained with withdrawn_at set. Deleting it would erase
    the evidence that consent was given and that it was later withdrawn.
    """
    _get_employee(db, employee_id, user)

    consent = _active_consent(db, employee_id)
    if consent is None:
        raise AppError(
            "no_active_consent",
            "This employee has no active biometric consent to withdraw.",
            409,
        )

    now = datetime.now(timezone.utc)
    consent.withdrawn_at = now
    consent.withdrawn_by = getattr(user, "id", None)

    # Revoke any enrolment that depended on this consent. The template is not
    # deleted here: policy section 2 requires the revocation and deletion to be
    # auditable, and there is no template to delete today anyway since the
    # enrolment endpoint refuses. Setting revoked_at is what makes the
    # enrolment unusable.
    enrolment = _live_enrolment(db, employee_id)
    if enrolment is not None:
        enrolment.revoked_at = now

    _audit(
        db,
        action="biometric_consent.withdrawn",
        employee_id=employee_id,
        entity_id=str(consent.id),
        new_value={
            "reason": payload.reason,
            "enrolment_revoked": enrolment is not None,
            "enrolment_id": str(enrolment.id) if enrolment else None,
        },
    )
    db.commit()
    db.refresh(consent)
    return ConsentRecordOut.model_validate(consent)


@router.post(
    "/{employee_id}/biometric-enrolment",
    response_model=BiometricNotApprovedOut,
    status_code=status.HTTP_403_FORBIDDEN,
    responses={403: {"model": BiometricNotApprovedOut}},
)
def create_enrolment(
    employee_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.BIOMETRIC_ENROL))],
) -> BiometricNotApprovedOut:
    """Refuse to enrol. Always.

    Section 8 of the privacy policy prohibits any biometric enrolment until a
    signed POPIA approval record exists. This endpoint is the enforcement point
    in code; the NOT NULL template_encrypted column is the second, independent
    gate in the database.

    When the approval record is signed, replace this body. Nothing else in the
    codebase needs to change, and until then a caller gets a specific error
    code rather than a 404 that looks like a typo in the URL.
    """
    _get_employee(db, employee_id, user)
    raise AppError(
        "biometric_not_approved",
        "Biometric enrolment is not available. Section 8 of the biometric "
        "privacy policy requires a signed POPIA approval record before any "
        "enrolment capability may be enabled.",
        403,
    )

# END OF FILE
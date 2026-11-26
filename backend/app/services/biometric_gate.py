"""The section 8 gate: may this tenant collect biometric data at all?

Five refusals, each with its own code, because "enrolment failed" tells an HR
user nothing. Every one fails CLOSED: there is no input, missing row, unreadable
file or ambiguous scope that results in a stored template.

    biometric_not_approved       no approval row, or status is not 'approved'
    biometric_approval_tampered  the signed document no longer matches its hash
    biometric_approval_expired   today is outside the effective dates
    biometric_approval_scope     the employee, site or biometric type is excluded
    biometric_consent_missing    no active, unwithdrawn consent for this employee
    biometric_not_configured     no provider SDK, or no key to encrypt with

Three of those are 403 and describe a policy decision. Three are 503 and
describe a system fault. The distinction matters: a 403 means "ask your
administrator to change the approval", a 503 means "this deployment is
misconfigured and no amount of asking will help". Collapsing them into one code
sends people to the wrong place.

Why the document hash is checked rather than trusted:

    A row saying status='approved' is a claim. The hash is what makes the claim
    verifiable against the thing that was actually signed. Without it the table
    is no stronger than the file it replaced -- a single UPDATE opens the gate.

Why the gate raises rather than returning a bool:

    A caller that ignores a False return stores a template. A raise cannot be
    ignored by accident.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from app.core.errors import AppError
from app.db.control.models import BiometricApproval
from app.db.control.session import control_session

# Overridable so tests and deployments can point at the real signed record
# without the code needing to know where operations put it.
_DOCUMENT_ENV = "BIOMETRIC_APPROVAL_DOCUMENT"
_DEFAULT_DOCUMENT = "docs/BIOMETRIC_APPROVAL_RECORD.md"

VALID_TYPES = frozenset({"fingerprint", "face"})
_APPROVAL_CACHE: dict[tuple[uuid.UUID, str], BiometricApproval] = {}


def document_path() -> Path:
    raw = os.environ.get(_DOCUMENT_ENV)
    return Path(raw) if raw else Path(_DEFAULT_DOCUMENT)


def sha256_file(path: Path) -> str:
    """SHA-256 of a file's bytes, hex encoded."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_approval(subscriber_id: uuid.UUID, biometric_type: str) -> BiometricApproval | None:
    """The approval covering this tenant and type, or None.

    'both' is checked after the specific type: an approval for fingerprint
    alone must not authorise face. An approval recorded as 'both' covers
    either.
    """
    with control_session() as session:
        for candidate in (biometric_type, "both"):
            row = (
                session.query(BiometricApproval)
                .filter(
                    BiometricApproval.subscriber_id == subscriber_id,
                    BiometricApproval.biometric_type == candidate,
                )
                .one_or_none()
            )
            if row is not None:
                # Detach from the session: callers keep the object after the
                # context closes.
                session.expunge(row)
                return row
    return None


def _scope_excludes(values: list[Any] | None, target: uuid.UUID) -> bool:
    """True when a scope list is present and does not contain target.

    NULL and empty both mean unrestricted. A scope that restricts to nobody
    would be indistinguishable from revoked, so it is read as "no restriction"
    and the status field carries revocation instead.
    """
    if not values:
        return False
    return str(target) not in {str(v) for v in values}


def require_approval(
    *,
    subscriber_id: uuid.UUID,
    employee_id: uuid.UUID,
    site_id: uuid.UUID | None,
    biometric_type: str,
    today: date | None = None,
    document: Path | None = None,
) -> BiometricApproval:
    """Raise unless a valid, in-date, in-scope approval exists.

    The checks run in the order a person would answer them:

      1. is there an approval at all?
      2. does the signed document still match what was approved?
      3. is it still in force?
      4. does it cover this person, place and biometric?
    """
    if biometric_type not in VALID_TYPES:
        raise AppError(
            "biometric_type_invalid",
            f"biometric_type must be one of {sorted(VALID_TYPES)}",
            400,
        )

    approval = _load_approval(subscriber_id, biometric_type)

    if approval is None or approval.status != "approved":
        raise AppError(
            "biometric_not_approved",
            "Biometric collection is not approved for this company. A signed "
            "approval record is required before any employee can enrol.",
            403,
        )

    if not approval.approved_by_company or not approval.approved_by_counsel:
        # An 'approved' row without two named signatories is incomplete. Treated
        # as not approved rather than as a warning: the whole point of the gate
        # is that approval is a documented act by two parties.
        raise AppError(
            "biometric_not_approved",
            "The approval record is missing a required signature.",
            403,
        )

    path = document or document_path()
    try:
        actual = sha256_file(path)
    except OSError:
        raise AppError(
            "biometric_not_configured",
            "The signed approval document could not be read. Biometric "
            "enrolment is unavailable until the document is restored.",
            503,
        ) from None

    if actual != approval.record_sha256:
        raise AppError(
            "biometric_approval_tampered",
            "The approval document does not match the approval on record. "
            "Enrolment is blocked until this is investigated.",
            503,
        )

    today = today or date.today()
    if today < approval.effective_from:
        raise AppError(
            "biometric_approval_expired",
            "The biometric approval is not yet in force.",
            403,
        )
    if approval.effective_to is not None and today > approval.effective_to:
        raise AppError(
            "biometric_approval_expired",
            "The biometric approval has expired and must be renewed.",
            403,
        )

    approval_type = approval.biometric_type
    if approval_type not in ("both", biometric_type):
        raise AppError(
            "biometric_approval_scope",
            f"The approval does not cover {biometric_type}.",
            403,
        )

    if _scope_excludes(approval.scope_employee_ids, employee_id):
        raise AppError(
            "biometric_approval_scope",
            "This employee is not covered by the biometric approval.",
            403,
        )
    if site_id is not None and _scope_excludes(approval.scope_site_ids, site_id):
        raise AppError(
            "biometric_approval_scope",
            "This site is not covered by the biometric approval.",
            403,
        )

    return approval


def require_consent(db: Any, employee_id: uuid.UUID) -> Any:
    """Raise unless the employee has active, unwithdrawn consent."""
    from app.db.tenant.models.people import BiometricConsent

    consent = db.query(BiometricConsent).filter(
        BiometricConsent.employee_id == employee_id,
        BiometricConsent.withdrawn_at.is_(None),
    ).first()
    if consent is None:
        raise AppError(
            "biometric_consent_missing",
            "This employee has not consented to biometric processing, or has "
            "withdrawn consent. Use the PIN alternative instead.",
            403,
        )
    return consent


def require_provider() -> Any:
    """Raise unless a real provider is installed.

    NullProvider raises ProviderNotConfigured from both of its methods, so the
    check is simply whether the installed provider is the null one. Done by
    name rather than isinstance so a vendor adapter that subclasses nothing
    still plugs in.
    """
    from app.services.biometric_provider import get_provider

    provider = get_provider()
    if getattr(provider, "name", "null") == "null":
        raise AppError(
            "biometric_not_configured",
            "No biometric reader SDK is configured on this server. Enrolment "
            "is unavailable; employees can use the PIN alternative.",
            503,
        )
    return provider


def assert_enrolment_permitted(
    db: Any,
    *,
    subscriber_id: uuid.UUID,
    employee_id: uuid.UUID,
    site_id: uuid.UUID | None,
    biometric_type: str,
    today: date | None = None,
    document: Path | None = None,
) -> Any:
    """All gate conditions, in order. Returns the installed provider.

    Provider last: if the deployment has no SDK, there is nothing to enrol with
    even when every policy condition is satisfied, and telling an operator
    "not approved" when the real problem is a missing SDK sends them to the
    wrong team.
    """
    require_approval(
        subscriber_id=subscriber_id,
        employee_id=employee_id,
        site_id=site_id,
        biometric_type=biometric_type,
        today=today,
        document=document,
    )
    require_consent(db, employee_id)
    return require_provider()
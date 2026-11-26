"""Biometric verification at punch time.

The device sends a probe template and a claim about who is clocking in. Nothing
it sends is trusted: a terminal that reports its own match_score has not been
verified by anything, so the score is computed here, server-side, from the
stored reference template.

The probe is never stored. It is decrypted-compared-discarded in the same
request, for the same reason policy section 1 discards photographs: retaining a
probe adds biometric data with no operational benefit.

Verdicts never reject a punch. A failed match produces low_confidence, which
already routes to the exception queue where HR decides. The alternative --
rejecting -- would mean a worn fingerprint costs someone a day's pay, and the
exception queue exists precisely so that a human decides rather than a
threshold.

Verdict NOT_ENROLLED is the one worth understanding. An employee with no
enrolment who submits a fingerprint punch is not committing fraud; they may
have been told to use the reader by a supervisor who never enrolled them. The
punch is accepted, flagged, and queued -- losing it would punish the employee
for an administrative omission.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, unique
from typing import Any

from app.api.v1.biometric_consent import KEY_VERSION as BIOMETRIC_KEY_VERSION
from app.core.template_crypto import TemplateCrypto, TemplateCryptoError
from app.db.tenant.models.people import BiometricConsent, BiometricEnrolment
from app.services.biometric_provider import (
    MATCH_THRESHOLD,
    ProviderNotConfigured,
    TemplateInvalid,
    VersionMismatch,
    get_provider,
)

# Base64 expansion plus a generous ceiling. An ISO 19794-2 template is well
# under 2 KB; 64 KB is far past any real template and stops a device from
# posting an image labelled as one.
_MAX_PROBE_BYTES = 64 * 1024


class ProbeInvalid(ValueError):
    """The probe is not usable as a template."""


@unique
class BiometricVerdict(str, Enum):
    MATCHED = "matched"
    BELOW_THRESHOLD = "below_threshold"
    NOT_ENROLLED = "not_enrolled"
    CONSENT_MISSING = "consent_missing"
    CONFIG_MISMATCH = "config_mismatch"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class BiometricResult:
    verdict: BiometricVerdict
    score: Decimal | None = None
    reason: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.verdict is BiometricVerdict.MATCHED


# Verdict to punch flag. The flags are mapped to exception types in
# attendance_engine, which is what puts them in front of HR.
_FLAG_FOR_VERDICT: dict[BiometricVerdict, str] = {
    BiometricVerdict.BELOW_THRESHOLD: "match_below_threshold",
    BiometricVerdict.NOT_ENROLLED: "biometric_not_enrolled",
    BiometricVerdict.CONSENT_MISSING: "biometric_consent_missing",
    BiometricVerdict.CONFIG_MISMATCH: "biometric_template_mismatch",
    BiometricVerdict.UNAVAILABLE: "biometric_verification_unavailable",
}


def decode_probe_template(encoded: str | None) -> bytes:
    """Base64 probe to bytes, with the same size floor encryption enforces."""
    if not encoded:
        raise ProbeInvalid("probe_template_base64 is required for a biometric punch")
    stripped = "".join(encoded.split())
    try:
        raw = base64.b64decode(stripped, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProbeInvalid("probe_template_base64 is not valid base64") from exc
    if len(raw) < 16:
        raise ProbeInvalid(
            f"probe is {len(raw)} bytes; a reader that returned nothing cannot "
            f"verify anyone"
        )
    if len(raw) > _MAX_PROBE_BYTES:
        raise ProbeInvalid(
            f"probe is {len(raw)} bytes, above the {_MAX_PROBE_BYTES}-byte limit"
        )
    return raw


def _live_enrolment(db: Any, employee_id: Any, biometric_type: str) -> BiometricEnrolment | None:
    return (
        db.query(BiometricEnrolment)
        .filter(
            BiometricEnrolment.employee_id == employee_id,
            BiometricEnrolment.revoked_at.is_(None),
            BiometricEnrolment.method == biometric_type,
        )
        .order_by(BiometricEnrolment.enrolled_at.desc())
        .first()
    )


def _consent_active(db: Any, employee_id: Any) -> bool:
    return (
        db.query(BiometricConsent)
        .filter(
            BiometricConsent.employee_id == employee_id,
            BiometricConsent.withdrawn_at.is_(None),
        )
        .first()
        is not None
    )


def verify_biometric_punch(
    db: Any,
    *,
    employee_id: Any,
    biometric_type: str,
    probe_raw: bytes,
    crypto: Any,
    key_version: str = BIOMETRIC_KEY_VERSION,
    threshold: float = MATCH_THRESHOLD,
) -> BiometricResult:
    """Compare a probe against the employee's live enrolment.

    Never raises for a failed match -- the punch still has to be recorded.
    Raises only for input that cannot be assessed at all, which the caller
    turns into a 400 before any punch row exists.
    """
    provider = get_provider()

    enrolment = _live_enrolment(db, employee_id, biometric_type)
    if enrolment is None:
        return BiometricResult(
            BiometricVerdict.NOT_ENROLLED,
            reason="no live enrolment for this employee and method",
            flags=[_FLAG_FOR_VERDICT[BiometricVerdict.NOT_ENROLLED]],
        )

    # Consent is re-checked at punch time, not just at enrolment. Withdrawal
    # revokes the enrolment row, but if the two have diverged -- a withdrawal
    # that failed halfway -- the template must not be used.
    if not _consent_active(db, employee_id):
        return BiometricResult(
            BiometricVerdict.CONSENT_MISSING,
            reason="consent withdrawn but an enrolment is still live",
            flags=[_FLAG_FOR_VERDICT[BiometricVerdict.CONSENT_MISSING]],
        )

    if enrolment.template_version != getattr(provider, "template_version", None):
        return BiometricResult(
            BiometricVerdict.CONFIG_MISMATCH,
            reason=(
                f"enrolment was created at template version "
                f"{enrolment.template_version}, provider produces "
                f"{getattr(provider, 'template_version', None)}"
            ),
            flags=[_FLAG_FOR_VERDICT[BiometricVerdict.CONFIG_MISMATCH]],
        )

    try:
        reference = TemplateCrypto(crypto, key_version=key_version).decrypt_template(
            enrolment.template_encrypted
        )
    except TemplateCryptoError as exc:
        # The stored template cannot be read. That is a system fault, not a
        # failed match, and it must not be reported as one.
        return BiometricResult(
            BiometricVerdict.UNAVAILABLE,
            reason=f"stored template unreadable: {exc}",
            flags=[_FLAG_FOR_VERDICT[BiometricVerdict.UNAVAILABLE]],
        )

    try:
        score = provider.match(probe_raw, reference)
    except (VersionMismatch, TemplateInvalid, ProviderNotConfigured) as exc:
        return BiometricResult(
            BiometricVerdict.UNAVAILABLE,
            reason=f"{type(exc).__name__}: {exc}",
            flags=[_FLAG_FOR_VERDICT[BiometricVerdict.UNAVAILABLE]],
        )

    # Quantised to two places to match punch.match_score NUMERIC(5,2). Rounding
    # here rather than at storage means the threshold comparison and the stored
    # value agree.
    quantised = Decimal(str(round(float(score), 2)))

    if quantised >= Decimal(str(threshold)):
        return BiometricResult(BiometricVerdict.MATCHED, score=quantised)

    return BiometricResult(
        BiometricVerdict.BELOW_THRESHOLD,
        score=quantised,
        reason=f"score {quantised} is below the threshold {threshold}",
        flags=[_FLAG_FOR_VERDICT[BiometricVerdict.BELOW_THRESHOLD]],
    )


def is_biometric_method(method: str) -> bool:
    return method in ("fingerprint", "face")
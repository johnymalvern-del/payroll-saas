"""Intelligence service — Phase 1A foundation.

Deterministic mode resolution and mode-change recording. No recommendation
generation, no decision execution, no business-rule interpretation of any
workflow.

Fails closed:
  - missing settings row -> Traditional
  - unknown workflow      -> AppError (422)
  - no override active    -> company default
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.tenant.models.intelligence import (
    MODES,
    WORKFLOWS,
    IntelligenceModeChangeLog,
    IntelligenceSettings,
    IntelligenceWorkflowMode,
)


def _validate_mode(mode: str) -> None:
    if mode not in MODES:
        raise AppError(
            "invalid_mode",
            f"mode must be one of {MODES}",
            422,
            {"mode": mode, "allowed": list(MODES)},
        )


def _validate_workflow(workflow: str) -> None:
    if workflow not in WORKFLOWS:
        raise AppError(
            "unknown_workflow",
            f"workflow {workflow!r} is not registered",
            422,
            {"workflow": workflow, "allowed": list(WORKFLOWS)},
        )


def _get_or_create_settings(db: Session) -> IntelligenceSettings:
    settings = db.scalar(select(IntelligenceSettings).limit(1))
    if settings is None:
        settings = IntelligenceSettings(
            id=uuid.uuid4(),
            default_mode="traditional",
            row_version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(settings)
        db.flush()
    return settings


def resolve_effective_mode(db: Session, workflow: str) -> str:
    """Deterministic mode resolution.

    1. Validate workflow (unknown -> 422).
    2. Read company default (missing -> 'traditional').
    3. Read active override whose effective_from <= now (if any).
    4. Return override mode, else company default.
    """
    _validate_workflow(workflow)
    settings = db.scalar(select(IntelligenceSettings).limit(1))
    company_default = settings.default_mode if settings else "traditional"
    now = datetime.now(timezone.utc)
    override = db.scalar(
        select(IntelligenceWorkflowMode).where(
            IntelligenceWorkflowMode.workflow == workflow,
            IntelligenceWorkflowMode.is_active.is_(True),
            IntelligenceWorkflowMode.effective_from <= now,
        )
    )
    return override.mode if override else company_default


def record_mode_change(
    db: Session,
    user: Any,
    *,
    workflow: str | None,
    previous_mode: str,
    new_mode: str,
    reason: str,
    effective_from: datetime,
    audit_id: uuid.UUID | None,
) -> IntelligenceModeChangeLog:
    if workflow is not None:
        _validate_workflow(workflow)
    _validate_mode(previous_mode)
    _validate_mode(new_mode)
    if not reason or not reason.strip():
        raise AppError(
            "reason_required", "A reason is required for mode changes", 422
        )
    log = IntelligenceModeChangeLog(
        id=uuid.uuid4(),
        changed_by_user_id=getattr(user, "id", None),
        changed_at=datetime.now(timezone.utc),
        workflow=workflow,
        previous_mode=previous_mode,
        new_mode=new_mode,
        reason=reason.strip(),
        effective_from=effective_from,
        audit_id=audit_id,
    )
    db.add(log)
    db.flush()
    return log


# ============================================================
# Phase 1B — decision record + snapshot creation
# ============================================================
import hashlib
import json as _json

from app.db.tenant.models.intelligence import (
    IntelligenceDecision,
    IntelligenceEvidenceSnapshot,
)
from app.services.payroll_audit import write_audit


FORBIDDEN_SNAPSHOT_KEY_PREFIXES = (
    "fingerprint", "template", "biometric", "photo_bytes",
    "face_embedding", "raw_biometric",
)
REDACTED_SNAPSHOT_KEY_PREFIXES = (
    "national_id", "bank_account_number", "password", "token", "secret",
)


def _canonical_serialise(payload: dict) -> str:
    return _json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str,
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sanitise_snapshot(payload: dict) -> dict:
    """Reject biometric-like keys; silently redact encrypted PII."""
    if not isinstance(payload, dict):
        raise AppError(
            "snapshot_invalid",
            "evidence_payload must be a JSON object",
            422,
        )

    def _walk(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if any(lk.startswith(p) for p in FORBIDDEN_SNAPSHOT_KEY_PREFIXES):
                    raise AppError(
                        "snapshot_forbidden_key",
                        f"Snapshot may not contain biometric key {k!r}",
                        422,
                        {"key": k},
                    )
                if any(lk.startswith(p) for p in REDACTED_SNAPSHOT_KEY_PREFIXES):
                    out[k] = "[REDACTED]"
                else:
                    out[k] = _walk(v)
            return out
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        return obj

    return _walk(payload)


def create_decision_record(
    db: Session,
    user: Any,
    *,
    workflow: str,
    employee_id: uuid.UUID,
    source_type: str,
    source_id: uuid.UUID | None = None,
    decision_type: str = "recommendation",
    initiator_type: str = "human",
    evidence_payload: dict,
    policy_version: str | None = None,
    statutory_version: str | None = None,
    idempotency_key: str | None = None,
    recommendation: dict | None = None,
    explanation: str | None = None,
) -> IntelligenceDecision:
    """Create a decision record + immutable snapshot in one transaction.

    - Captures company/effective/override modes at creation time (historical).
    - Sanitises evidence_payload (fail on biometric, redact PII).
    - Computes SHA-256 of canonical serialisation.
    - Idempotency: (workflow, idempotency_key) unique. Matching payload returns
      existing record; mismatched payload raises 409.
    - Writes audit; links audit_id + evidence_snapshot_id.
    - No execution. No state change outside these two tables + audit.
    """
    _validate_workflow(workflow)
    if decision_type not in ("recommendation", "autonomous_action", "escalation"):
        raise AppError("invalid_decision_type", "invalid decision_type", 422)
    if initiator_type not in ("human", "system"):
        raise AppError("invalid_initiator_type", "invalid initiator_type", 422)

    # Idempotency check
    if idempotency_key is not None:
        existing = db.scalar(
            select(IntelligenceDecision).where(
                IntelligenceDecision.workflow == workflow,
                IntelligenceDecision.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.evidence_snapshot_id is not None:
                snap = db.get(
                    IntelligenceEvidenceSnapshot,
                    existing.evidence_snapshot_id,
                )
                try:
                    candidate_hash = _sha256_hex(
                        _canonical_serialise(_sanitise_snapshot(evidence_payload))
                    )
                except AppError:
                    candidate_hash = None
                if snap is not None and candidate_hash == snap.sha256_hex:
                    return existing
            raise AppError(
                "idempotency_key_conflict",
                f"Idempotency key {idempotency_key!r} already used with different payload",
                409,
            )

    # Resolve modes at creation
    settings = _get_or_create_settings(db)
    company_default = settings.default_mode
    effective = resolve_effective_mode(db, workflow)
    override = db.scalar(
        select(IntelligenceWorkflowMode).where(
            IntelligenceWorkflowMode.workflow == workflow,
            IntelligenceWorkflowMode.is_active.is_(True),
        )
    )
    override_mode = override.mode if override else None

    # Sanitise + hash
    safe_payload = _sanitise_snapshot(evidence_payload)
    canonical = _canonical_serialise(safe_payload)
    sha = _sha256_hex(canonical)

    # Insert decision (evidence_snapshot_id NULL first)
    decision = IntelligenceDecision(
        id=uuid.uuid4(),
        employee_id=employee_id,
        workflow=workflow,
        source_type=source_type,
        source_id=source_id,
        evidence_snapshot={},
        mode_at_creation=effective,
        recommendation=recommendation,
        explanation=explanation,
        decision_type=decision_type,
        initiator_type=initiator_type,
        initiator_user_id=(
            getattr(user, "id", None) if initiator_type == "human" else None
        ),
        company_default_mode=company_default,
        effective_workflow_mode=effective,
        workflow_override_mode=override_mode,
        idempotency_key=idempotency_key,
        policy_version=policy_version,
        statutory_version=statutory_version,
        execution_status="pending",
        created_at=datetime.now(timezone.utc),
    )
    # Wrap the decision insert in a savepoint so a concurrent duplicate
    # (same workflow + idempotency_key) is caught and handled without
    # rolling back the caller's surrounding transaction.
    _sp = db.begin_nested()
    try:
        db.add(decision)
        db.flush()
        _sp.commit()
    except IntegrityError as exc:
        _sp.rollback()
        _msg = (
            str(exc.orig) if getattr(exc, "orig", None) else str(exc)
        ).lower()
        if idempotency_key is not None and (
            "uq_intelligence_decision_idempotency" in _msg
            or ("unique" in _msg and "idempotency" in _msg)
        ):
            _existing = db.scalar(
                select(IntelligenceDecision).where(
                    IntelligenceDecision.workflow == workflow,
                    IntelligenceDecision.idempotency_key == idempotency_key,
                )
            )
            if _existing is not None:
                if _existing.evidence_snapshot_id is not None:
                    _snap = db.get(
                        IntelligenceEvidenceSnapshot,
                        _existing.evidence_snapshot_id,
                    )
                    try:
                        _candidate_hash = _sha256_hex(
                            _canonical_serialise(
                                _sanitise_snapshot(evidence_payload)
                            )
                        )
                    except AppError:
                        _candidate_hash = None
                    if _snap is not None and _candidate_hash == _snap.sha256_hex:
                        return _existing
                raise AppError(
                    "idempotency_key_conflict",
                    f"Idempotency key {idempotency_key!r} already used "
                    f"with different payload",
                    409,
                )
        # Not an idempotency conflict — re-raise untouched
        raise

    # Insert snapshot
    snapshot = IntelligenceEvidenceSnapshot(
        id=uuid.uuid4(),
        decision_id=decision.id,
        schema_version=1,
        payload=safe_payload,
        sha256_hex=sha,
        created_at=datetime.now(timezone.utc),
    )
    db.add(snapshot)
    db.flush()

    # Link decision -> snapshot
    decision.evidence_snapshot_id = snapshot.id

    # Audit
    audit = write_audit(
        db, user,
        entity_type="intelligence_decision",
        entity_id=decision.id,
        action="intelligence.decision.create",
        old_value=None,
        new_value={
            "workflow": workflow,
            "employee_id": str(employee_id),
            "decision_type": decision_type,
            "initiator_type": initiator_type,
            "mode": effective,
            "sha256_hex": sha,
        },
        actor_system=(initiator_type == "system"),
    )
    db.flush()
    decision.audit_id = audit.id

    return decision


def verify_decision_snapshot(
    db: Session, decision_id: uuid.UUID,
) -> bool:
    """Recompute hash of the stored snapshot; compare to stored hash."""
    decision = db.get(IntelligenceDecision, decision_id)
    if decision is None:
        raise AppError("not_found", "Decision record not found", 404)
    if decision.evidence_snapshot_id is None:
        raise AppError("snapshot_missing", "Decision has no snapshot", 404)
    snap = db.get(IntelligenceEvidenceSnapshot, decision.evidence_snapshot_id)
    if snap is None:
        raise AppError("snapshot_missing", "Snapshot not found", 404)
    recomputed = _sha256_hex(_canonical_serialise(snap.payload))
    return recomputed == snap.sha256_hex


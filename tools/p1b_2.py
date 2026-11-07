"""Phase 1B: model extension + snapshot model + service additions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
SRC = BE / "app"

# ---------- 1. models/intelligence.py: add fields + new model ----------
mp = SRC / "db" / "tenant" / "models" / "intelligence.py"
s = mp.read_text(encoding="utf-8")

if "class IntelligenceEvidenceSnapshot" in s:
    print("models: snapshot already present")
else:
    # add new fields to IntelligenceDecision — insert before created_at
    anchor = (
        "    audit_id: Mapped[uuid.UUID | None] = mapped_column(\n"
        "        UUID(as_uuid=True), ForeignKey(\"audit_log.id\", ondelete=\"SET NULL\"),\n"
        "        nullable=True,\n"
        "    )\n"
        "    created_at: Mapped[datetime] = mapped_column(\n"
        "        DateTime(timezone=True), server_default=func.now(), nullable=False\n"
        "    )\n"
    )
    if anchor not in s:
        raise SystemExit("FATAL: IntelligenceDecision tail anchor not matched")

    new_tail = (
        "    audit_id: Mapped[uuid.UUID | None] = mapped_column(\n"
        "        UUID(as_uuid=True), ForeignKey(\"audit_log.id\", ondelete=\"SET NULL\"),\n"
        "        nullable=True,\n"
        "    )\n"
        # new Phase 1B fields
        "    decision_type: Mapped[str] = mapped_column(\n"
        "        String(20), nullable=False,\n"
        "        default=\"recommendation\",\n"
        "        server_default=text(\"'recommendation'\"),\n"
        "    )\n"
        "    initiator_type: Mapped[str] = mapped_column(\n"
        "        String(20), nullable=False,\n"
        "        default=\"human\", server_default=text(\"'human'\"),\n"
        "    )\n"
        "    initiator_user_id: Mapped[uuid.UUID | None] = mapped_column(\n"
        "        UUID(as_uuid=True), ForeignKey(\"user.id\", ondelete=\"SET NULL\"),\n"
        "        nullable=True,\n"
        "    )\n"
        "    company_default_mode: Mapped[str | None] = mapped_column(\n"
        "        String(20), nullable=True\n"
        "    )\n"
        "    effective_workflow_mode: Mapped[str | None] = mapped_column(\n"
        "        String(20), nullable=True\n"
        "    )\n"
        "    workflow_override_mode: Mapped[str | None] = mapped_column(\n"
        "        String(20), nullable=True\n"
        "    )\n"
        "    idempotency_key: Mapped[str | None] = mapped_column(\n"
        "        String(120), nullable=True\n"
        "    )\n"
        "    evidence_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(\n"
        "        UUID(as_uuid=True),\n"
        "        ForeignKey(\"intelligence_evidence_snapshot.id\",\n"
        "                   ondelete=\"SET NULL\"),\n"
        "        nullable=True,\n"
        "    )\n"
        "    created_at: Mapped[datetime] = mapped_column(\n"
        "        DateTime(timezone=True), server_default=func.now(), nullable=False\n"
        "    )\n"
    )
    s = s.replace(anchor, new_tail, 1)

    # append new model class
    snapshot_model = '''

class IntelligenceEvidenceSnapshot(Base):
    """Immutable snapshot of the evidence used to create a decision.

    Append-only at both app-role (REVOKE UPDATE, DELETE) and DB-trigger
    level (BEFORE UPDATE/DELETE raises). Same pattern as audit_log.
    """
    __tablename__ = "intelligence_evidence_snapshot"

    id: Mapped[uuid.UUID] = _pk()
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intelligence_decision.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
'''
    s = s.rstrip() + snapshot_model
    mp.write_text(s, encoding="utf-8")
    print("models: extended IntelligenceDecision + appended snapshot model")

# ---------- 2. service: add decision-record functions ----------
svc = SRC / "services" / "intelligence_service.py"
s = svc.read_text(encoding="utf-8")

if "def create_decision_record" in s:
    print("service: create_decision_record already present")
else:
    addition = '''


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
    source_id: uuid.UUID | None,
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
    db.add(decision)
    db.flush()

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
'''
    s = s.rstrip() + addition + "\n"
    svc.write_text(s, encoding="utf-8")
    print("service: appended create_decision_record + verify_decision_snapshot")
"""Phase 1B: schemas + router + registration."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
BE = ROOT / "backend"
API = BE / "app" / "api" / "v1"

(API / "intelligence_decisions_schemas.py").write_text('''"""Read-only schemas for intelligence decision records (Phase 1B)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SnapshotOut(BaseModel):
    id: uuid.UUID
    decision_id: uuid.UUID
    created_at: datetime
    schema_version: int
    payload: dict
    sha256_hex: str


class DecisionSummaryOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    workflow: str
    source_type: str
    source_id: uuid.UUID | None = None
    decision_type: str
    initiator_type: str
    initiator_user_id: uuid.UUID | None = None
    company_default_mode: str | None = None
    effective_workflow_mode: str | None = None
    workflow_override_mode: str | None = None
    execution_status: str
    created_at: datetime


class DecisionDetailOut(DecisionSummaryOut):
    policy_version: str | None = None
    statutory_version: str | None = None
    recommendation: dict | None = None
    explanation: str | None = None
    audit_id: uuid.UUID | None = None
    evidence_snapshot_id: uuid.UUID | None = None
    snapshot: SnapshotOut | None = None


class DecisionListOut(BaseModel):
    items: list[DecisionSummaryOut]
    next_cursor: str | None = None
    total: int | None = None
''', encoding="utf-8")
print("wrote intelligence_decisions_schemas.py")

(API / "intelligence_decisions.py").write_text('''"""Read-only decision-records API (Phase 1B).

No POST/PATCH/DELETE. Decision creation happens through the service
layer only (intelligence_service.create_decision_record) for future
workflows. Nothing in this router writes.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import TenantDbDep
from app.api.v1.intelligence_decisions_schemas import (
    DecisionDetailOut,
    DecisionListOut,
    DecisionSummaryOut,
    SnapshotOut,
)
from app.core.errors import AppError
from app.core.permissions import Permission, require_permission
from app.db.tenant.models.intelligence import (
    IntelligenceDecision,
    IntelligenceEvidenceSnapshot,
)
from app.services.intelligence_service import verify_decision_snapshot

router = APIRouter(prefix="/intelligence/decisions", tags=["intelligence"])


def _summary(d: IntelligenceDecision) -> DecisionSummaryOut:
    return DecisionSummaryOut(
        id=d.id, employee_id=d.employee_id, workflow=d.workflow,
        source_type=d.source_type, source_id=d.source_id,
        decision_type=d.decision_type, initiator_type=d.initiator_type,
        initiator_user_id=d.initiator_user_id,
        company_default_mode=d.company_default_mode,
        effective_workflow_mode=d.effective_workflow_mode,
        workflow_override_mode=d.workflow_override_mode,
        execution_status=d.execution_status, created_at=d.created_at,
    )


@router.get("", response_model=DecisionListOut)
def list_decisions(
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_VIEW))],
    workflow: str | None = Query(None),
    employee_id: uuid.UUID | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
) -> DecisionListOut:
    q = select(IntelligenceDecision).order_by(
        IntelligenceDecision.created_at.desc()
    )
    if workflow:
        q = q.where(IntelligenceDecision.workflow == workflow)
    if employee_id:
        q = q.where(IntelligenceDecision.employee_id == employee_id)
    if status_filter:
        q = q.where(IntelligenceDecision.execution_status == status_filter)
    rows = list(db.scalars(q.limit(limit)).all())
    return DecisionListOut(items=[_summary(r) for r in rows])


@router.get("/{decision_id}", response_model=DecisionDetailOut)
def get_decision(
    decision_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_VIEW))],
) -> DecisionDetailOut:
    d = db.get(IntelligenceDecision, decision_id)
    if d is None:
        raise AppError("not_found", "Decision record not found", 404)
    snapshot = None
    if d.evidence_snapshot_id is not None:
        snap = db.get(IntelligenceEvidenceSnapshot, d.evidence_snapshot_id)
        if snap is not None:
            snapshot = SnapshotOut(
                id=snap.id, decision_id=snap.decision_id,
                created_at=snap.created_at, schema_version=snap.schema_version,
                payload=snap.payload, sha256_hex=snap.sha256_hex,
            )
    base = _summary(d)
    return DecisionDetailOut(
        **base.model_dump(),
        policy_version=d.policy_version,
        statutory_version=d.statutory_version,
        recommendation=d.recommendation,
        explanation=d.explanation,
        audit_id=d.audit_id,
        evidence_snapshot_id=d.evidence_snapshot_id,
        snapshot=snapshot,
    )


@router.get("/{decision_id}/verify")
def verify_snapshot(
    decision_id: uuid.UUID,
    db: TenantDbDep,
    user: Annotated[Any, Depends(require_permission(Permission.INTELLIGENCE_VIEW))],
) -> dict:
    ok = verify_decision_snapshot(db, decision_id)
    return {"valid": ok, "decision_id": str(decision_id)}
''', encoding="utf-8")
print("wrote intelligence_decisions.py")

# register router
ini = API / "__init__.py"
s = ini.read_text(encoding="utf-8")
if "intelligence_decisions_router" in s:
    print("__init__.py: already registered")
else:
    s = s.replace(
        "from app.api.v1.intelligence_settings import router as intelligence_settings_router\n",
        "from app.api.v1.intelligence_settings import router as intelligence_settings_router\n"
        "from app.api.v1.intelligence_decisions import router as intelligence_decisions_router\n",
        1,
    )
    s = s.replace(
        "api_router.include_router(intelligence_settings_router)\n",
        "api_router.include_router(intelligence_settings_router)\n"
        "api_router.include_router(intelligence_decisions_router)\n",
        1,
    )
    ini.write_text(s, encoding="utf-8")
    print("__init__.py: decisions router registered")
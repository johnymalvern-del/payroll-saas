"""Read-only schemas for intelligence decision records (Phase 1B)."""
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

"""Pydantic schemas for intelligence settings (Phase 1A)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class IntelligenceSettingsOut(BaseModel):
    id: uuid.UUID
    default_mode: str
    acknowledged_at: datetime | None = None
    acknowledged_by_user_id: uuid.UUID | None = None
    row_version: int


class UpdateDefaultModeIn(BaseModel):
    default_mode: str = Field(..., description="traditional | assisted | autonomous")
    row_version: int = Field(..., ge=1)
    reason: str = Field(..., min_length=3, max_length=1000)
    effective_from: datetime | None = None
    acknowledged_autonomous: bool = False


class WorkflowModeOut(BaseModel):
    workflow: str
    company_default: str
    override_mode: str | None = None
    override_active: bool
    effective_mode: str
    row_version: int | None = None
    effective_from: datetime | None = None
    # Explicit: no workflow has autonomous capability yet in Phase 1A.
    autonomous_capability_implemented: bool = False


class WorkflowModeListOut(BaseModel):
    items: list[WorkflowModeOut]


class UpdateWorkflowModeIn(BaseModel):
    mode: str
    is_active: bool = True
    row_version: int | None = None
    reason: str = Field(..., min_length=3, max_length=1000)
    effective_from: datetime | None = None
    acknowledged_autonomous: bool = False


class ModeChangeLogOut(BaseModel):
    id: uuid.UUID
    changed_by_user_id: uuid.UUID | None = None
    changed_at: datetime
    workflow: str | None = None
    previous_mode: str
    new_mode: str
    reason: str
    effective_from: datetime
    audit_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class ModeChangeLogListOut(BaseModel):
    items: list[ModeChangeLogOut]

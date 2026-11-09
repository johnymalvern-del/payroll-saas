from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


AssignmentStatus = Literal["pending", "approved", "rejected", "cancelled"]
OverrideKind = Literal["employee_earning", "employee_deduction"]


class OverrideManualIdIn(BaseModel):
    kind: OverrideKind
    id: uuid.UUID


class AssignmentSubmitIn(BaseModel):
    employee_id: uuid.UUID
    structure_id: uuid.UUID
    effective_from: date
    idempotency_key: str | None = Field(None, max_length=64)
    override_manual_ids: list[OverrideManualIdIn] = Field(
        default_factory=list, max_length=100,
    )

    @field_validator("override_manual_ids")
    @classmethod
    def _no_dup(cls, v: list[OverrideManualIdIn]) -> list[OverrideManualIdIn]:
        seen: set[tuple[str, uuid.UUID]] = set()
        for item in v:
            key = (item.kind, item.id)
            if key in seen:
                raise ValueError("duplicate_override_manual_id")
            seen.add(key)
        return v


class AssignmentRejectIn(BaseModel):
    note: str = Field(..., min_length=1)


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    structure_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None
    status: str
    idempotency_key: str | None = None
    submitted_by_user_id: uuid.UUID | None = None
    submitted_at: datetime
    decided_by_user_id: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    failure_detail: str | None = None
    override_manual_ids: list = Field(default_factory=list)
    row_version: int
    created_at: datetime
    updated_at: datetime


class ChangeRequestChildOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    employee_id: uuid.UUID
    status: str
    applied_entity_id: uuid.UUID | None = None
    decision_note: str | None = None


class AssignmentDetailOut(AssignmentOut):
    children: list[ChangeRequestChildOut] = Field(default_factory=list)


class AttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assignment_id: uuid.UUID
    attempted_by_user_id: uuid.UUID | None = None
    attempted_at: datetime
    outcome: str
    failure_detail: str | None = None


class AttemptListOut(BaseModel):
    items: list[AttemptOut]


class AssignmentListOut(BaseModel):
    items: list[AssignmentOut]


class CheckCollisionsIn(BaseModel):
    employee_id: uuid.UUID
    structure_id: uuid.UUID
    effective_from: date
    override_manual_ids: list[OverrideManualIdIn] = Field(default_factory=list)


class ManualOverlapOut(BaseModel):
    kind: str
    id: uuid.UUID
    component_kind: str
    component_type_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None
    status: str


class StructureOwnedOverlapOut(BaseModel):
    kind: str
    id: uuid.UUID
    component_kind: str
    component_type_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None


class CheckCollisionsOut(BaseModel):
    employee_id: uuid.UUID
    structure_id: uuid.UUID
    effective_from: date
    manual: list[ManualOverlapOut]
    structure_owned: list[StructureOwnedOverlapOut]

# END OF FILE
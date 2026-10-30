from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ChangeKind = Literal[
    "employee_earning_create",
    "employee_earning_update",
    "employee_earning_deactivate",
    "employee_deduction_create",
    "employee_deduction_update",
    "employee_deduction_deactivate",
    "employee_field_update",
]


class ChangeRequestSubmitIn(BaseModel):
    kind: ChangeKind
    employee_id: uuid.UUID
    payload: dict[str, Any]
    note: str | None = None


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    employee_id: uuid.UUID
    status: str
    requested_by_user_id: uuid.UUID | None = None
    requested_at: datetime
    decided_by_user_id: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    applied_entity_id: uuid.UUID | None = None
    row_version: int


class ChangeRequestListOut(BaseModel):
    items: list[ChangeRequestOut]
    next_cursor: str | None = None


class RejectIn(BaseModel):
    note: str = Field(..., min_length=1)

# END OF FILE

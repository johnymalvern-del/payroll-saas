"""Leave request schemas (Chapter 3, 3C)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeaveRequestDayOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    leave_request_id: uuid.UUID
    work_date: date
    days: Decimal


class LeaveApprovalStepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    leave_request_id: uuid.UUID
    step_no: int
    approver_user_id: uuid.UUID | None = None
    approver_role: str | None = None
    status: str
    decided_at: datetime | None = None
    note: str | None = None
    created_at: datetime


class LeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type_id: uuid.UUID
    from_date: date
    to_date: date
    days_requested: Decimal
    reason: str | None = None
    status: str
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by_user_id: uuid.UUID | None = None
    decision_note: str | None = None
    row_version: int
    created_at: datetime
    updated_at: datetime
    captured_by_user_id: uuid.UUID | None = None
    days: list[LeaveRequestDayOut] = Field(default_factory=list)
    steps: list[LeaveApprovalStepOut] = Field(default_factory=list)


class LeaveRequestListOut(BaseModel):
    items: list[LeaveRequestOut]
    next_cursor: str | None = None


class LeaveRequestIn(BaseModel):
    employee_id: uuid.UUID | None = None
    leave_type_id: uuid.UUID
    from_date: date
    to_date: date
    reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _v_dates(self) -> "LeaveRequestIn":
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        return self


class LeaveRequestPatch(BaseModel):
    row_version: int = Field(..., ge=1)
    from_date: date | None = None
    to_date: date | None = None
    reason: str | None = Field(default=None, max_length=1000)


class StepDecideIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)


class DecideIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=1000)
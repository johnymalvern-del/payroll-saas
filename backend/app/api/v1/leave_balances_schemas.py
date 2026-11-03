"""Leave balance schemas (Chapter 3, 3B.2)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LeaveBalanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    leave_type_id: uuid.UUID
    cycle_start: date
    cycle_end: date
    entitled: Decimal
    accrued: Decimal
    taken: Decimal
    pending: Decimal
    carried_in: Decimal
    adjusted: Decimal
    available: Decimal = Decimal("0")
    row_version: int
    created_at: datetime
    updated_at: datetime


class LeaveBalanceListOut(BaseModel):
    items: list[LeaveBalanceOut]
    next_cursor: str | None = None


class BalanceAdjustIn(BaseModel):
    employee_id: uuid.UUID
    leave_type_id: uuid.UUID
    cycle_start: date | None = None
    delta: Decimal
    reason: str = Field(..., min_length=1, max_length=200)


class BalanceAdjustOut(BaseModel):
    balance: LeaveBalanceOut
    ledger_entry_id: uuid.UUID
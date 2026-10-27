"""Pay-rate-change schemas (1C.10).

PayHistoryOut is the read shape. It has no row_version because the model
has none: pay-history rows are append-only from the API's perspective
(create, approve, reject), and concurrency is enforced by the partial
unique index on live rows, not by row_version.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


_ALLOWED_STATUSES = ("pending", "approved", "rejected", "cancelled")


class PayHistoryOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    base_rate: Decimal
    effective_from: date
    changed_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    decided_by: uuid.UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    note: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class PayHistoryCreateIn(BaseModel):
    base_rate: Decimal = Field(..., ge=0)
    effective_from: date
    note: str | None = Field(default=None, max_length=2000)


class PayHistoryRejectIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class PayHistoryListOut(BaseModel):
    items: list[PayHistoryOut]
    next_cursor: str | None = None
    total: int | None = None


ALLOWED_STATUSES = _ALLOWED_STATUSES

# END OF FILE
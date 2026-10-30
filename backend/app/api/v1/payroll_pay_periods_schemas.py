from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PayPeriodIn(BaseModel):
    period_key: str = Field(..., max_length=40)
    start_date: date
    end_date: date
    pay_date: date
    cutoff_at: datetime


class PayPeriodOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    period_key: str
    start_date: date
    end_date: date
    pay_date: date
    status: str
    cutoff_at: datetime
    row_version: int


class PayPeriodListOut(BaseModel):
    items: list[PayPeriodOut]
    next_cursor: str | None = None


class PreviewSummaryRow(BaseModel):
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    gross: Decimal
    paye: Decimal
    net: Decimal
    warnings: list[str] = []


class PreviewOut(BaseModel):
    run_id: uuid.UUID
    revision: int
    status: str
    unacknowledged_formulas: list[str] = []
    items: list[PreviewSummaryRow]
    next_cursor: str | None = None


class PayrollRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pay_period_id: uuid.UUID
    kind: str
    revision: int
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None


class ReopenIn(BaseModel):
    reason: str = Field(..., min_length=1)


class ReopenLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    pay_period_id: uuid.UUID
    reopened_by_user_id: uuid.UUID | None = None
    reason: str
    prior_revision: int
    new_revision: int
    occurred_at: datetime

# END OF FILE

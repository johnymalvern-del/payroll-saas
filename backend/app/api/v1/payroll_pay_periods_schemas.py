"""Pay period schemas (Chapter 4 + Chapter 4H B-4d + B-3 + M6 Stage A + M6 Part 2).

B-3 adds PreviewEmployeeOut (single-employee preview detail).
M6 Stage A adds PreviewOut.raw_employee_count.
M6 Part 2 Stage 4 adds FinaliseIn.ack_stale_preview_reason.
"""
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
    gross: Decimal | None = None
    paye: Decimal | None = None
    net: Decimal | None = None
    warnings: list[str] = Field(default_factory=list)


class PreviewOut(BaseModel):
    run_id: uuid.UUID
    revision: int | None = None
    status: str
    unacknowledged_formulas: list[str] = Field(default_factory=list)
    items: list[PreviewSummaryRow]
    next_cursor: str | None = None
    raw_employee_count: int = 0


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


class FinaliseIn(BaseModel):
    ack_open_exceptions_reason: str | None = Field(default=None, max_length=500)
    ack_stale_preview_reason: str | None = Field(default=None, max_length=500)


class PreviewEmployeeLineOut(BaseModel):
    earning_type_code: str
    earning_type_name: str
    rate_source: str | None = None
    amount: Decimal
    minutes: int | None = None


class PreviewEmployeeDeductionOut(BaseModel):
    deduction_type_code: str
    deduction_type_name: str
    amount: Decimal


class PreviewEmployeeOut(BaseModel):
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    pay_period_id: uuid.UUID
    revision: int
    status: str
    gross: Decimal
    paye: Decimal
    net: Decimal
    warnings: list[str] = Field(default_factory=list)
    lines: list[PreviewEmployeeLineOut] = Field(default_factory=list)
    deductions: list[PreviewEmployeeDeductionOut] = Field(default_factory=list)
    available: bool = True
    reason_unavailable: str | None = None
    as_of: date | None = None
    unacknowledged_formulas: list[str] = Field(default_factory=list)
    demo_values: bool = False

# END OF FILE
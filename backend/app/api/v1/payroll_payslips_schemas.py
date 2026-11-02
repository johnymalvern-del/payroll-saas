"""Payslip schemas (Chapter 4 Bundle 004b-b + Chapter 4H B-3).

B-3 adds self-service list/detail shapes (PayslipMeRow, PayslipMeListOut).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PayslipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    payroll_run_id: uuid.UUID
    pay_period_id: uuid.UUID
    employee_id: uuid.UUID
    revision: int
    status: str
    gross: Decimal
    pre_tax_deductions: Decimal
    taxable_income: Decimal
    paye: Decimal
    uif_employee: Decimal
    uif_employer: Decimal
    sdl: Decimal
    other_deductions: Decimal
    reimbursements: Decimal
    net: Decimal
    pdf_object_key: str | None = None
    predecessor_payslip_id: uuid.UUID | None = None
    computed_at: datetime


class PayslipListOut(BaseModel):
    items: list[PayslipOut]
    next_cursor: str | None = None


class PayslipLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    line_type: str
    step: str
    sort_order: int
    label: str
    amount: Decimal
    source_ref: dict


class PayslipExplainOut(BaseModel):
    payslip: PayslipOut
    lines: list[PayslipLineOut]
    snapshot: dict
    calculation_context: dict


class PayslipMeRow(BaseModel):
    """Lean self-service row (B-3)."""
    id: uuid.UUID
    pay_period_id: uuid.UUID
    period_key: str
    pay_date: date
    status: str
    gross: Decimal
    net: Decimal
    computed_at: datetime


class PayslipMeListOut(BaseModel):
    items: list[PayslipMeRow]
    next_cursor: str | None = None

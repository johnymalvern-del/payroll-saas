"""Salary sheet schemas (M5).

Read-only projection over persisted Payslip rows. Every monetary field
here is copied verbatim from a Payslip (which is what the payslip PDF
also reads); basic_earnings and additional_earnings are sums of
PayslipLine rows filtered by source_ref.earning_type_code. No
calculation happens in the API layer.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel


class SalarySheetRow(BaseModel):
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    payslip_id: uuid.UUID
    payslip_status: str  # "current" (finalised) or "preview"
    revision: int
    basic_earnings: Decimal
    additional_earnings: Decimal
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


class SalarySheetOut(BaseModel):
    pay_period_id: uuid.UUID
    pay_period_key: str
    pay_period_status: str  # "open" | "locked"
    figures_state: str  # "preview" | "finalised" | "no_preview"
    run_id: uuid.UUID | None = None
    revision: int | None = None
    items: list[SalarySheetRow]
    next_cursor: str | None = None
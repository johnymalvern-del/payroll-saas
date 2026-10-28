"""Schemas for the employee import endpoint (1C.11).

Design notes:
  - The error report is row-by-row. `row` is the 1-based data row index
    (header excluded), so the first data row after the header is row 1.
    `column` is the CSV header name the error relates to, or null when
    the error applies to the row as a whole.
  - `message` is plain language; HR should not need to know error codes.
  - `token` is the sha256 hex of the file bytes. A real import must supply
    the token returned by a dry run of the same file (D3 override); this
    makes the review exactly what is imported.
  - `opening_rates` lists every rate that was (or, in dry run, would be)
    loaded as part of a create, so payroll admin can review them. The
    `opening_rates_require_payroll_admin_review` flag is true when the
    importing user does not have PAY_RATE_APPROVE, i.e. the opening rates
    were loaded by HR and payroll admin has not yet reviewed them.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ImportErrorOut(BaseModel):
    row: int
    column: str | None = None
    code: str
    message: str


class OpeningRateOut(BaseModel):
    employee_code: str
    base_rate: Decimal
    effective_from: date


class ImportResultOut(BaseModel):
    dry_run: bool
    token: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    created: int
    updated: int
    opening_rates_loaded: int
    opening_rates: list[OpeningRateOut]
    opening_rates_require_payroll_admin_review: bool
    errors: list[ImportErrorOut]
    errors_truncated: bool

# END OF FILE
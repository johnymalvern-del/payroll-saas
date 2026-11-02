"""Pydantic schema for golden payslip case files (Chapter 4H 4G-c).

Round-2 §16: `reviewed_by` and `reviewed_on` are required when
`accountant_reviewed` is true. Validated at load time so an unreviewed
file cannot be accidentally promoted without the audit fields.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class GoldenExpected(BaseModel):
    gross: str
    paye: str
    net: str
    lines: list[dict] = Field(default_factory=list)
    deductions: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class GoldenPayslipCase(BaseModel):
    case_id: str
    description: str
    accountant_reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_on: str | None = None
    company_settings: dict = Field(default_factory=dict)
    payroll_settings: dict = Field(default_factory=dict)
    employee: dict
    shift: dict | None = None
    shift_rate_rules: list[dict] = Field(default_factory=list)
    employee_earnings: list[dict] = Field(default_factory=list)
    employee_deductions: list[dict] = Field(default_factory=list)
    attendance_days: list[dict] = Field(default_factory=list)
    attendance_segments: list[dict] = Field(default_factory=list)
    pay_period: dict
    expected: GoldenExpected

    @model_validator(mode="after")
    def _require_reviewer_fields_if_reviewed(self) -> "GoldenPayslipCase":
        if self.accountant_reviewed:
            if not self.reviewed_by or not self.reviewed_by.strip():
                raise ValueError(
                    "reviewed_by required when accountant_reviewed=true"
                )
            if not self.reviewed_on or not self.reviewed_on.strip():
                raise ValueError(
                    "reviewed_on required when accountant_reviewed=true"
                )
        return self
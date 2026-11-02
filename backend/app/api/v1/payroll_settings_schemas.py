"""Payroll settings schemas (Chapter 4H B-4 foundation).

New fields are nullable and carry no defaults. Round-1 amendment 5.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.services.payroll_runner import AgeRef  # type: ignore[attr-defined]


class PayrollSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    age_reference_date: AgeRef | None = None
    sdl_applies: bool | None = None
    net_pay_floor: Decimal = Decimal("0.00")
    row_version: int = 0

    attendance_earning_map: dict[str, str] = Field(default_factory=dict)
    unpaid_day_behaviour: str | None = None
    unpaid_day_formula_code: str | None = None
    public_holiday_unworked_monthly: str | None = None
    public_holiday_paid: bool | None = None
    leave_authoritative_source: str | None = None
    monthly_hourly_derivation_formula_code: str | None = None
    leave_earning_for_monthly: bool | None = None
    demo_values: bool = False


class PayrollSettingsPatchIn(BaseModel):
    age_reference_date: AgeRef | None = None
    sdl_applies: bool | None = None
    net_pay_floor: Decimal | None = Field(None, ge=0)
    row_version: int

    attendance_earning_map: dict[str, str] | None = None
    unpaid_day_behaviour: str | None = None
    unpaid_day_formula_code: str | None = None
    public_holiday_unworked_monthly: str | None = None
    public_holiday_paid: bool | None = None
    leave_authoritative_source: str | None = None
    monthly_hourly_derivation_formula_code: str | None = None
    leave_earning_for_monthly: bool | None = None
    demo_values: bool | None = None

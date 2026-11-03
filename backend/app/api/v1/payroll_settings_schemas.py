"""Payroll settings schemas (Chapter 4H B-4 + Chapter 3 L1a).

New fields are nullable and carry no defaults. Chapter 3 L1a adds
leave_escalation_days, leave_cycle_fixed_anchor, advance_max_pct,
advance_hard_cap, sick_leave_codes, net_estimate_method. Money and law
values are all unset by default, in line with the no-invented-values
rule.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class PayrollSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    age_reference_date: str | None = None
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

    leave_escalation_days: int | None = None
    leave_cycle_fixed_anchor: date | None = None
    advance_max_pct: Decimal | None = None
    advance_hard_cap: Decimal | None = None
    sick_leave_codes: list[str] = Field(default_factory=list)
    net_estimate_method: str | None = None

    last_accrual_run_at: datetime | None = None
    demo_values: bool = False


class PayrollSettingsPatchIn(BaseModel):
    age_reference_date: str | None = None
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

    leave_escalation_days: int | None = None
    leave_cycle_fixed_anchor: date | None = None
    advance_max_pct: Decimal | None = None
    advance_hard_cap: Decimal | None = None
    sick_leave_codes: list[str] | None = None
    net_estimate_method: str | None = None

    demo_values: bool | None = None
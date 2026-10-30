from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

CalcMethod = Literal["fixed_amount", "per_hour", "per_day", "percent_of_gross", "percent_of_basic"]
Frequency = Literal["regular", "once_off", "irregular"]
ProrationRule = Literal["none", "by_calendar_days", "by_work_days", "by_hours"]
DeductionCategory = Literal["retirement", "garnishee", "loan", "advance", "other"]


class EarningTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    calc_method: CalcMethod
    frequency: Frequency
    is_taxable: bool
    counts_for_uif: bool
    counts_for_sdl: bool
    ledger_account: str | None = None
    proration_rule: ProrationRule
    eligibility_rule: dict | None = None
    is_system: bool
    is_active: bool
    row_version: int


class EarningTypeIn(BaseModel):
    name: str = Field(..., max_length=80)
    code: str = Field(..., max_length=40)
    calc_method: CalcMethod
    frequency: Frequency
    is_taxable: bool = True
    counts_for_uif: bool = True
    counts_for_sdl: bool = True
    ledger_account: str | None = Field(None, max_length=40)
    proration_rule: ProrationRule = "none"
    eligibility_rule: dict | None = None


class EarningTypePatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    calc_method: CalcMethod | None = None
    frequency: Frequency | None = None
    is_taxable: bool | None = None
    counts_for_uif: bool | None = None
    counts_for_sdl: bool | None = None
    ledger_account: str | None = Field(None, max_length=40)
    proration_rule: ProrationRule | None = None
    eligibility_rule: dict | None = None
    is_active: bool | None = None
    row_version: int


class EarningTypeListOut(BaseModel):
    items: list[EarningTypeOut]
    next_cursor: str | None = None


class DeductionTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    category: DeductionCategory
    priority: int
    is_pre_tax: bool
    is_system: bool
    is_active: bool
    row_version: int


class DeductionTypeIn(BaseModel):
    name: str = Field(..., max_length=80)
    code: str = Field(..., max_length=40)
    category: DeductionCategory
    priority: int = 100
    is_pre_tax: bool = False


class DeductionTypePatch(BaseModel):
    name: str | None = Field(None, max_length=80)
    category: DeductionCategory | None = None
    priority: int | None = None
    is_pre_tax: bool | None = None
    is_active: bool | None = None
    row_version: int


class DeductionTypeListOut(BaseModel):
    items: list[DeductionTypeOut]
    next_cursor: str | None = None

# END OF FILE

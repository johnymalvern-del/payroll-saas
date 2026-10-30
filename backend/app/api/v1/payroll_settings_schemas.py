from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgeRef = Literal["period_start", "period_end", "pay_date"]


class PayrollSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    age_reference_date: AgeRef | None = None
    sdl_applies: bool | None = None
    net_pay_floor: Decimal = Decimal("0.00")
    row_version: int = 0


class PayrollSettingsPatchIn(BaseModel):
    age_reference_date: AgeRef | None = None
    sdl_applies: bool | None = None
    net_pay_floor: Decimal | None = Field(None, ge=0)
    row_version: int

# END OF FILE

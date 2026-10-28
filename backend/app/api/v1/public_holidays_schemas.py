'''Public holiday tenant override schemas (Chapter 2A).'''
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field


class PublicHolidayOut(BaseModel):
    id: uuid.UUID
    holiday_date: date
    name: str
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    is_working_day_override: bool
    is_active: bool
    row_version: int


class PublicHolidayCreateIn(BaseModel):
    holiday_date: date
    name: str = Field(..., min_length=1, max_length=120)
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    is_working_day_override: bool = False


class PublicHolidayPatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    holiday_date: date | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    is_working_day_override: bool | None = None
    is_active: bool | None = None


class PublicHolidayListOut(BaseModel):
    items: list[PublicHolidayOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE

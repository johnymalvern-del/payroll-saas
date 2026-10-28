'''Work pattern schemas (Chapter 2A).'''
from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field, model_validator


class WorkPatternDayOut(BaseModel):
    id: uuid.UUID
    work_pattern_id: uuid.UUID
    day_index: int
    is_expected: bool
    expected_shift_id: uuid.UUID | None = None


class WorkPatternDayIn(BaseModel):
    day_index: int = Field(..., ge=0)
    is_expected: bool
    expected_shift_id: uuid.UUID | None = None


class WorkPatternOut(BaseModel):
    id: uuid.UUID
    name: str
    cycle_length_days: int
    anchor_date: date
    is_active: bool
    row_version: int


class WorkPatternDetailOut(WorkPatternOut):
    days: list[WorkPatternDayOut]


class WorkPatternListOut(BaseModel):
    items: list[WorkPatternOut]
    next_cursor: str | None = None
    total: int | None = None


class WorkPatternCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    cycle_length_days: int = Field(..., ge=1, le=365)
    anchor_date: date
    days: list[WorkPatternDayIn]

    @model_validator(mode='after')
    def _v_days(self):
        got = [d.day_index for d in self.days]
        if len(got) != len(set(got)):
            raise ValueError('days contains duplicate day_index values')
        if set(got) != set(range(self.cycle_length_days)):
            raise ValueError(f'days must cover 0..{self.cycle_length_days - 1} exactly once; got {sorted(got)}')
        return self


class WorkPatternPatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    cycle_length_days: int | None = Field(default=None, ge=1, le=365)
    anchor_date: date | None = None
    is_active: bool | None = None
    days: list[WorkPatternDayIn] | None = None

    @model_validator(mode='after')
    def _v_days(self):
        if self.days is None:
            return self
        if self.cycle_length_days is None:
            return self
        got = [d.day_index for d in self.days]
        if len(got) != len(set(got)):
            raise ValueError('days contains duplicate day_index values')
        if set(got) != set(range(self.cycle_length_days)):
            raise ValueError(f'days must cover 0..{self.cycle_length_days - 1} exactly once; got {sorted(got)}')
        return self

# END OF FILE

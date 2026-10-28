'''Shift schemas (Chapter 2A).'''
from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, Field, field_validator

_ROUNDING_MODES = ('nearest', 'up', 'down')
_SALARIED_PREMIUM_MODES = ('full', 'premium_only')


class ShiftOut(BaseModel):
    id: uuid.UUID
    name: str
    start_time: time
    length_minutes: int
    unpaid_break_minutes: int
    paid_break_minutes: int
    grace_late_minutes: int
    grace_early_minutes: int
    rounding_minutes: int
    rounding_mode: str
    min_overtime_minutes: int
    overtime_requires_approval: bool
    max_shift_minutes: int
    match_tolerance_minutes: int
    salaried_premium_mode: str
    is_active: bool
    row_version: int


class ShiftCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    start_time: time
    length_minutes: int = Field(..., gt=0)
    unpaid_break_minutes: int = Field(default=0, ge=0)
    paid_break_minutes: int = Field(default=0, ge=0)
    grace_late_minutes: int = Field(default=0, ge=0)
    grace_early_minutes: int = Field(default=0, ge=0)
    rounding_minutes: int = Field(default=0, ge=0)
    rounding_mode: str = Field(default='nearest')
    min_overtime_minutes: int = Field(default=0, ge=0)
    overtime_requires_approval: bool = True
    max_shift_minutes: int = Field(..., gt=0)
    match_tolerance_minutes: int = Field(default=60, ge=0)
    salaried_premium_mode: str = Field(default='full')

    @field_validator('rounding_mode')
    @classmethod
    def _v_rounding(cls, v: str) -> str:
        if v not in _ROUNDING_MODES:
            raise ValueError(f'rounding_mode must be one of {_ROUNDING_MODES}')
        return v

    @field_validator('salaried_premium_mode')
    @classmethod
    def _v_salaried(cls, v: str) -> str:
        if v not in _SALARIED_PREMIUM_MODES:
            raise ValueError(f'salaried_premium_mode must be one of {_SALARIED_PREMIUM_MODES}')
        return v


class ShiftPatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    start_time: time | None = None
    length_minutes: int | None = Field(default=None, gt=0)
    unpaid_break_minutes: int | None = Field(default=None, ge=0)
    paid_break_minutes: int | None = Field(default=None, ge=0)
    grace_late_minutes: int | None = Field(default=None, ge=0)
    grace_early_minutes: int | None = Field(default=None, ge=0)
    rounding_minutes: int | None = Field(default=None, ge=0)
    rounding_mode: str | None = None
    min_overtime_minutes: int | None = Field(default=None, ge=0)
    overtime_requires_approval: bool | None = None
    max_shift_minutes: int | None = Field(default=None, gt=0)
    match_tolerance_minutes: int | None = Field(default=None, ge=0)
    salaried_premium_mode: str | None = None
    is_active: bool | None = None


class ShiftListOut(BaseModel):
    items: list[ShiftOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE

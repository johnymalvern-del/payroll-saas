'''Shift rate rule schemas (Chapter 2A).

Per-field validation only. Cross-tier validation (contiguity from 1,
strictly increasing tier_up_to_minutes, exactly one open-ended top
tier) requires comparing sibling rows, so it lives in the router
(422 invalid_tier_structure) and in the pure helper
app/core/rate_lookup.py.

Per-key period overlap (409 overlapping_rate_rule) also lives in
the router, because it needs to query sibling rows.

No PATCH: rate rules are config, and their composite uniqueness is
(shift_id, day_type, kind, tier, effective_from). Changing any of
those means a different rule; changing only value/method/flat_unit
in place is a delete+create in the UI. This is recorded in
docs/STATE.md.
'''
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

_DAY_TYPES = ('weekday', 'saturday', 'sunday', 'public_holiday')
_KINDS = ('normal', 'overtime')
_METHODS = ('multiplier', 'flat_amount')
_FLAT_UNITS = ('per_hour', 'per_segment')


class ShiftRateRuleOut(BaseModel):
    id: uuid.UUID
    shift_id: uuid.UUID
    day_type: str
    kind: str
    tier: int
    tier_up_to_minutes: int | None = None
    method: str
    value: Decimal
    flat_unit: str | None = None
    effective_from: date
    effective_to: date | None = None


class ShiftRateRuleCreateIn(BaseModel):
    day_type: str
    kind: str
    tier: int = Field(..., ge=1)
    tier_up_to_minutes: int | None = Field(default=None, ge=1)
    method: str
    value: Decimal = Field(..., ge=0)
    flat_unit: str | None = None
    effective_from: date
    effective_to: date | None = None

    @field_validator('day_type')
    @classmethod
    def _v_day_type(cls, v: str) -> str:
        if v not in _DAY_TYPES:
            raise ValueError(f'day_type must be one of {_DAY_TYPES}')
        return v

    @field_validator('kind')
    @classmethod
    def _v_kind(cls, v: str) -> str:
        if v not in _KINDS:
            raise ValueError(f'kind must be one of {_KINDS}')
        return v

    @field_validator('method')
    @classmethod
    def _v_method(cls, v: str) -> str:
        if v not in _METHODS:
            raise ValueError(f'method must be one of {_METHODS}')
        return v

    @model_validator(mode='after')
    def _v_cross_field(self):
        if self.method == 'multiplier' and self.flat_unit is not None:
            raise ValueError('flat_unit must be null when method=multiplier')
        if self.method == 'flat_amount':
            if self.flat_unit not in _FLAT_UNITS:
                raise ValueError(f'flat_unit must be one of {_FLAT_UNITS} when method=flat_amount')
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError('effective_to must be after effective_from')
        return self


class ShiftRateRuleListOut(BaseModel):
    items: list[ShiftRateRuleOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE

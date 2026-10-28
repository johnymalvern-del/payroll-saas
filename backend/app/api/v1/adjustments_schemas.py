"""Adjustment endpoint schemas (Chapter 2C).

Single adjustment and bulk adjustment (with C1 dry-run/token). Revert is a
first-class outcome (C6). Self-adjust (C8) and locked-day (C3) guards live
in the router, not here.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


_OUTCOMES = ("worked", "leave", "sick", "absent", "day_off", "revert")


def _validate_common(outcome: str, time_in, time_out, reason_code: str, note: str | None) -> None:
    if outcome not in _OUTCOMES:
        raise ValueError(f"outcome must be one of {_OUTCOMES}")
    if outcome == "worked" and (time_in is None or time_out is None):
        raise ValueError("worked requires both time_in and time_out")
    if time_in is not None and time_out is not None and time_out <= time_in:
        raise ValueError("time_out must be after time_in")
    if reason_code == "other" and (note is None or len(note.strip()) < 10):
        raise ValueError("reason_code 'other' requires a note of at least 10 characters")


class AdjustmentOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    outcome: str
    time_in: datetime | None = None
    time_out: datetime | None = None
    minutes: int | None = None
    reason_code: str
    note: str | None = None
    batch_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    period_id: uuid.UUID | None = None
    created_at: datetime


class AdjustmentResultOut(BaseModel):
    adjustment: AdjustmentOut
    day_status: str | None = None
    day_worked_minutes: int | None = None
    day_normal_minutes: int | None = None
    day_overtime_minutes: int | None = None


class AdjustmentCreateIn(BaseModel):
    employee_id: uuid.UUID
    work_date: date
    outcome: str
    time_in: datetime | None = None
    time_out: datetime | None = None
    reason_code: str = Field(..., min_length=1, max_length=40)
    note: str | None = None

    @model_validator(mode="after")
    def _v(self):
        _validate_common(self.outcome, self.time_in, self.time_out, self.reason_code, self.note)
        return self


class BulkAdjustItemIn(BaseModel):
    employee_id: uuid.UUID
    work_date: date
    outcome: str
    time_in: datetime | None = None
    time_out: datetime | None = None
    reason_code: str = Field(..., min_length=1, max_length=40)
    note: str | None = None

    @model_validator(mode="after")
    def _v(self):
        _validate_common(self.outcome, self.time_in, self.time_out, self.reason_code, self.note)
        return self


class BulkAdjustIn(BaseModel):
    items: list[BulkAdjustItemIn] = Field(..., min_length=1, max_length=200)
    token: str | None = None


class BulkAdjustItemOut(BaseModel):
    index: int
    employee_id: uuid.UUID
    work_date: date
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    adjustment_id: uuid.UUID | None = None


class BulkAdjustOut(BaseModel):
    results: list[BulkAdjustItemOut]
    applied: int
    dry_run: bool
    token: str

# END OF FILE
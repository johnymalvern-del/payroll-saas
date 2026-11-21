
"""Adjustment endpoint schemas (Chapter 2C).

Single adjustment and bulk adjustment (with C1 dry-run/token). Revert is a
first-class outcome (C6). Self-adjust (C8) and locked-day (C3) guards live
in the router, not here.

Stage B Batch B: AdjustmentHistoryRowOut is the read shape for the
per-day correction history. It carries the old_value/new_value JSONB
snapshots from the Adjustment row plus the resolved created_by_name
(joined from User, or None if the user has been deleted). Read-only.

Stage B Batch C: shift override. AdjustmentCreateIn accepts an optional
shift_id (nullable — None means "no override, use the detected shift").
AdjustmentOut and AdjustmentHistoryRowOut carry it through so the created
adjustment and its history rows show the override. AdjustmentHistoryRowOut
also carries shift_name, resolved from new_value.shift_name (captured at
write time) so a deleted Shift row does not erase the identity of the
shift HR selected.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

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
    shift_id: uuid.UUID | None = None
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
    shift_id: uuid.UUID | None = None

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


class AdjustmentHistoryRowOut(BaseModel):
    """Read shape for one row of per-day correction history.

    Mirrors the Adjustment model's externally-relevant fields plus the
    resolved creator name. old_value and new_value are the raw JSONB
    snapshots captured by _apply_adjustment — no fields are dropped or
    simplified here; the frontend is responsible for whatever display
    subset it chooses.

    Stage B Batch C: shift_id is the shift override (None = no override).
    shift_name is resolved from new_value.shift_name, captured at write
    time, so it survives hard deletion of the underlying Shift row.
    """
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
    created_by_name: str | None = None
    shift_id: uuid.UUID | None = None
    shift_name: str | None = None
    created_at: datetime
    old_value: dict[str, Any] | None = None
    new_value: dict[str, Any] | None = None


class AdjustmentHistoryListOut(BaseModel):
    items: list[AdjustmentHistoryRowOut]

# END OF FILE
"""Exceptions queue schemas (Chapter 2C).

Single resolve and bulk resolve (C1) are shaped the same way as the
1C.11 import: a dry-run call (no token) validates and returns per-item
results plus a token; the real call (with token) recomputes the hash
and applies everything or nothing.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


_ALLOWED_ACTIONS = ("apply_suggestion", "custom", "dismiss")


class ExceptionOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    type: str
    source_ref: dict[str, Any] = Field(default_factory=dict)
    suggested_fix: dict[str, Any] = Field(default_factory=dict)
    status: str
    assigned_to: uuid.UUID | None = None
    resolved_by: uuid.UUID | None = None
    resolved_at: datetime | None = None
    resolution: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ExceptionListOut(BaseModel):
    items: list[ExceptionOut]
    next_cursor: str | None = None
    total: int | None = None


class CustomAdjustmentIn(BaseModel):
    outcome: str
    time_in: datetime | None = None
    time_out: datetime | None = None
    reason_code: str = Field(..., min_length=1, max_length=40)
    note: str | None = None

    @model_validator(mode="after")
    def _v(self):
        allowed = ("worked", "leave", "sick", "absent", "day_off", "revert")
        if self.outcome not in allowed:
            raise ValueError(f"outcome must be one of {allowed}")
        if self.outcome == "worked" and (self.time_in is None or self.time_out is None):
            raise ValueError("worked requires both time_in and time_out")
        if self.time_in is not None and self.time_out is not None and self.time_out <= self.time_in:
            raise ValueError("time_out must be after time_in")
        if self.reason_code == "other" and (self.note is None or len(self.note.strip()) < 10):
            raise ValueError("reason_code 'other' requires a note of at least 10 characters")
        return self


class ResolveIn(BaseModel):
    action: Literal["apply_suggestion", "custom", "dismiss"]
    custom_adjustment: CustomAdjustmentIn | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _v(self):
        if self.action == "custom" and self.custom_adjustment is None:
            raise ValueError("action='custom' requires custom_adjustment")
        if self.action == "dismiss" and (self.note is None or len(self.note.strip()) < 3):
            raise ValueError("action='dismiss' requires a note (at least 3 characters)")
        return self


class ResolveOut(BaseModel):
    exception: ExceptionOut
    adjustment_id: uuid.UUID | None = None
    day_status: str | None = None


class BulkResolveItemIn(BaseModel):
    exception_id: uuid.UUID
    action: Literal["apply_suggestion", "custom", "dismiss"]
    custom_adjustment: CustomAdjustmentIn | None = None
    note: str | None = None


class BulkResolveIn(BaseModel):
    items: list[BulkResolveItemIn] = Field(..., min_length=1, max_length=200)
    token: str | None = None

    @model_validator(mode="after")
    def _v(self):
        for item in self.items:
            if item.action == "custom" and item.custom_adjustment is None:
                raise ValueError("each custom item requires custom_adjustment")
            if item.action == "dismiss" and (item.note is None or len(item.note.strip()) < 3):
                raise ValueError("each dismiss item requires a note")
        return self


class BulkResolveItemOut(BaseModel):
    index: int
    exception_id: uuid.UUID
    ok: bool
    error_code: str | None = None
    error_message: str | None = None
    adjustment_id: uuid.UUID | None = None


class BulkResolveOut(BaseModel):
    results: list[BulkResolveItemOut]
    applied: int
    dry_run: bool
    token: str

# END OF FILE
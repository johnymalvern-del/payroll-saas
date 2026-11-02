"""Attendance read and recompute schemas (Chapter 2B).

B-5/B-11: DayOut carries `site_timezone` so the day list and day detail
both surface the employee's site timezone (falling back to the company
default). DayDetailOut inherits the field from DayOut.
"""
from __future__ import annotations
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator


class SegmentOut(BaseModel):
    id: uuid.UUID
    attendance_day_id: uuid.UUID
    local_date: date
    day_type: str
    kind: str
    tier: int
    minutes: int
    rate_method: str
    rate_value: Decimal
    overtime_status: str | None = None
    source_refs: list[Any] = Field(default_factory=list)


class DayOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    work_date: date
    status: str
    first_in: datetime | None = None
    last_out: datetime | None = None
    worked_minutes: int
    normal_minutes: int
    overtime_minutes: int
    raw_minutes: int
    shift_id: uuid.UUID | None = None
    flags: list[str] = Field(default_factory=list)
    source_version: int
    locked: bool
    row_version: int
    computed_at: datetime
    # B-5/B-11: employee's site timezone, falling back to company default.
    site_timezone: str | None = None


class DayDetailOut(DayOut):
    segments: list[SegmentOut] = Field(default_factory=list)


class DayListOut(BaseModel):
    items: list[DayOut]
    next_cursor: str | None = None
    total: int | None = None


class RecomputeIn(BaseModel):
    employee_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _v_one_target(self):
        targets = [self.employee_id, self.site_id, self.department_id]
        if sum(1 for t in targets if t is not None) != 1:
            raise ValueError("exactly one of employee_id, site_id, department_id must be provided")
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        if (self.to_date - self.from_date).days > 31:
            raise ValueError("date range must be 31 days or fewer")
        return self


class RecomputeOut(BaseModel):
    recomputed: int
    skipped_locked: int
    employee_count: int
    from_date: date
    to_date: date
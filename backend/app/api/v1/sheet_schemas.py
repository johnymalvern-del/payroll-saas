"""Sheet/daily response schemas (Chapter 2C).

B-5/B-11: SheetEmployeeOut and DailyRowOut carry `site_timezone` so the
frontend can render per-employee timestamps in the employee's site
timezone without a second lookup.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class SheetCellOut(BaseModel):
    work_date: date
    status: str | None = None
    worked_minutes: int | None = None
    normal_minutes: int | None = None
    overtime_minutes: int | None = None
    flags: list[str] = Field(default_factory=list)
    open_exception_count: int = 0
    locked: bool = False
    reviewed: bool = False


class SheetEmployeeOut(BaseModel):
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    days: list[SheetCellOut]
    # B-5/B-11: per-employee site timezone (falls back to company default).
    site_timezone: str | None = None


class SheetOut(BaseModel):
    items: list[SheetEmployeeOut]
    next_cursor: str | None = None
    total: int | None = None


class DailyRowOut(BaseModel):
    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    work_date: date
    status: str | None = None
    first_in: datetime | None = None
    last_out: datetime | None = None
    shift_id: uuid.UUID | None = None
    worked_minutes: int | None = None
    normal_minutes: int | None = None
    overtime_minutes: int | None = None
    flags: list[str] = Field(default_factory=list)
    open_exception_count: int = 0
    locked: bool = False
    reviewed: bool = False
    # B-5/B-11: per-employee site timezone (falls back to company default).
    site_timezone: str | None = None


class DailyOut(BaseModel):
    items: list[DailyRowOut]
    next_cursor: str | None = None
    total: int | None = None


class MarkReviewedIn(BaseModel):
    employee_ids: list[uuid.UUID] | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    from_date: date
    to_date: date

    @model_validator(mode="after")
    def _v(self):
        if (
            self.employee_ids is None
            and self.site_id is None
            and self.department_id is None
        ):
            raise ValueError(
                "one of employee_ids, site_id, department_id is required"
            )
        return self


class MarkReviewedRefusedOut(BaseModel):
    employee_id: uuid.UUID
    work_date: date
    reason: str


class MarkReviewedOut(BaseModel):
    marked: int
    refused: int
    refused_days: list[MarkReviewedRefusedOut]
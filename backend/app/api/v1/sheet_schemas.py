"""Sheet, daily list, and mark-reviewed schemas (Chapter 2C).

C2: no `adjusted`, `adjustment`, `adjustment_id`, or `reason_code` may appear
in any field of SheetCellOut, SheetEmployeeOut, or DailyRowOut. Adjusted
days look identical to clocked days in these responses; adjustments are
visible only through the audit log. A test in test_sheet.py asserts this
for every role.

C9: sheet limits 50 default, 200 max per page; date range 31 days max.

Sheet cells include one entry per date in [from_date, to_date]. If no
attendance_day exists for a date, the cell has status=None and null
minutes, so the UI renders an empty cell without aligning arrays.
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
        targets_present = sum(1 for t in (
            self.employee_ids is not None,
            self.site_id is not None,
            self.department_id is not None,
        ) if t)
        if targets_present != 1:
            raise ValueError(
                "exactly one of employee_ids, site_id, department_id must be provided"
            )
        if self.to_date < self.from_date:
            raise ValueError("to_date must be on or after from_date")
        if (self.to_date - self.from_date).days > 31:
            raise ValueError("date range must be 31 days or fewer")
        if self.employee_ids is not None and len(self.employee_ids) > 200:
            raise ValueError("employee_ids must be 200 or fewer")
        return self


class MarkReviewedRefusedOut(BaseModel):
    employee_id: uuid.UUID
    work_date: date
    reason: str


class MarkReviewedOut(BaseModel):
    marked: int
    refused: int
    refused_days: list[MarkReviewedRefusedOut]

# END OF FILE
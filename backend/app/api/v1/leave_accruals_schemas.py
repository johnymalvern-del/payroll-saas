"""Leave accrual schemas (Chapter 3, 3B.3)."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class AccrualRunIn(BaseModel):
    as_of_date: date | None = None


class AccrualRunOut(BaseModel):
    employees_touched: int
    rows_written: int
    as_of: date
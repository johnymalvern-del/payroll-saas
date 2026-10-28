'''Employee work-pattern assignment schemas (Chapter 2A).'''
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class AssignmentOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    work_pattern_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None
    created_at: datetime


class AssignmentCreateIn(BaseModel):
    work_pattern_id: uuid.UUID
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode='after')
    def _v_dates(self):
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError('effective_to must be after effective_from')
        return self


class AssignmentPatchIn(BaseModel):
    effective_to: date


class AssignmentListOut(BaseModel):
    items: list[AssignmentOut]

# END OF FILE

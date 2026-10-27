"""Department endpoint schemas.

Mirrors app/api/v1/sites_schemas.py:
  * DepartmentOut is the read shape (includes parent_id).
  * DepartmentCreateIn / DepartmentPatchIn are the write shapes.
  * PATCH requires row_version; stale values return 409 record_changed.
  * code is stripped on write so the API and the functional unique index
    on lower(btrim(code)) agree.
  * parent_id is optional in both create and patch. The endpoint enforces
    the cycle rule; the schema only carries the value.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


def _clean_code(v: str) -> str:
    if v is None:
        return v
    trimmed = v.strip()
    if not trimmed:
        raise ValueError("code must not be empty")
    return trimmed


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    parent_id: uuid.UUID | None = None
    is_active: bool
    row_version: int


class DepartmentCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=40)
    parent_id: uuid.UUID | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return _clean_code(v)


class DepartmentPatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _clean_code(v)


class DepartmentListOut(BaseModel):
    items: list[DepartmentOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE
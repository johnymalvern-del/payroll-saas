"""Branch endpoint schemas.

Mirrors the style of app/api/v1/company/schemas.py:
  * `BranchOut` is the read shape.
  * `BranchCreateIn` and `BranchPatchIn` are the write shapes.
  * `PATCH` requires `row_version`; stale values return 409 record_changed.
  * All fields are optional on PATCH except row_version.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


def _clean_code(v: str) -> str:
    """Trim the code and reject empties after trimming."""
    if v is None:
        return v
    trimmed = v.strip()
    if not trimmed:
        raise ValueError("code must not be empty")
    return trimmed


class BranchOut(BaseModel):
    id: uuid.UUID
    name: str
    code: str
    address: str | None = None
    is_active: bool
    row_version: int


class BranchCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=40)
    address: str | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return _clean_code(v)


class BranchPatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    address: str | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _clean_code(v)


class BranchListOut(BaseModel):
    items: list[BranchOut]
    next_cursor: str | None = None
    total: int | None = None
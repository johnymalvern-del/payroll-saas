"""Site endpoint schemas.

Mirrors app/api/v1/branches_schemas.py:
  * SiteOut is the read shape (includes branch_id and site_type).
  * SiteCreateIn / SitePatchIn are the write shapes.
  * PATCH requires row_version; stale values return 409 record_changed.
  * code is stripped on write so the API and the functional unique index
    on lower(btrim(code)) agree.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


_SITE_TYPES = ("site", "store", "office")


def _clean_code(v: str) -> str:
    if v is None:
        return v
    trimmed = v.strip()
    if not trimmed:
        raise ValueError("code must not be empty")
    return trimmed


class SiteOut(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    name: str
    code: str
    site_type: str
    address: str | None = None
    timezone: str
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_m: int | None = None
    is_active: bool
    row_version: int


class SiteCreateIn(BaseModel):
    branch_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=40)
    site_type: str = Field(default="site")
    address: str | None = None
    timezone: str = Field(default="Africa/Johannesburg", max_length=64)
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_m: int | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return _clean_code(v)

    @field_validator("site_type")
    @classmethod
    def _validate_site_type(cls, v: str) -> str:
        if v not in _SITE_TYPES:
            raise ValueError(f"site_type must be one of {_SITE_TYPES}")
        return v


class SitePatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    branch_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    site_type: str | None = None
    address: str | None = None
    timezone: str | None = Field(default=None, max_length=64)
    latitude: float | None = None
    longitude: float | None = None
    geofence_radius_m: int | None = None
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _validate_code(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _clean_code(v)

    @field_validator("site_type")
    @classmethod
    def _validate_site_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _SITE_TYPES:
            raise ValueError(f"site_type must be one of {_SITE_TYPES}")
        return v


class SiteListOut(BaseModel):
    items: list[SiteOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE
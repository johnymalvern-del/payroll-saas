'''Punch schemas (Chapter 2A).

PunchIn is what a device submits. The device is authenticated by
X-Device-Key (see device_auth.require_device); the payload carries no
auth. manual_import is not accepted by this endpoint - it is reserved
for a future historical-import feature.

A2: device_time and device_now_at_send must be timezone-aware. The
service computes effective_time and offset_ms from them.

A6: photo_base64 (JPEG/PNG), raw_payload (<=8KB, no biometric-shaped
keys) are validated by the service, not by the schema, because they
need byte-level inspection.
'''
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, field_validator

_DEVICE_METHODS = ('fingerprint', 'face', 'code')


class PunchIn(BaseModel):
    client_punch_id: uuid.UUID
    employee_id: uuid.UUID
    device_time: AwareDatetime
    device_now_at_send: AwareDatetime | None = None
    method: str
    match_score: Decimal | None = Field(default=None, ge=0, le=100)
    liveness_passed: bool | None = None
    photo_base64: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator('method')
    @classmethod
    def _v_method(cls, v: str) -> str:
        if v not in _DEVICE_METHODS:
            raise ValueError(f'method must be one of {_DEVICE_METHODS}')
        return v


class PunchBatchIn(BaseModel):
    punches: list[PunchIn] = Field(..., max_length=500)


class PunchOut(BaseModel):
    id: uuid.UUID
    client_punch_id: uuid.UUID
    employee_id: uuid.UUID
    device_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    server_received_at: datetime
    device_time: datetime
    device_now_at_send: datetime | None = None
    effective_time: datetime
    offset_ms: int
    method: str
    match_score: Decimal | None = None
    liveness_passed: bool | None = None
    photo_object_key: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    status: str
    flags: list[str]
    raw_payload: dict[str, Any]
    created_at: datetime


class PunchBatchItemOut(BaseModel):
    index: int
    ok: bool
    punch: PunchOut | None = None
    error: dict[str, Any] | None = None


class PunchBatchOut(BaseModel):
    results: list[PunchBatchItemOut]
    accepted: int
    rejected: int


class PunchListOut(BaseModel):
    items: list[PunchOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE

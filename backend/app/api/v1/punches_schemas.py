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

Phase 2: gps_accuracy_m carries the device's reported horizontal
accuracy alongside latitude/longitude. It is intentionally NOT part of
canonical_payload_hash -- see punches.py -- so a retry of an
already-accepted punch keeps the same payload_hash and is recognised as
a duplicate rather than a conflict.

Non-biometric fallback (policy section 4): method='pin' carries a PIN in
the `pin` field. SecretStr keeps it out of repr(), logs and any accidental
model_dump() in an error path; the value is read with get_secret_value()
at exactly one place in punches.py.

`pin` is likewise excluded from canonical_payload_hash, because that
function builds its field dict explicitly rather than dumping the model.
That is not incidental -- a failed PIN retry re-sent with the same
client_punch_id must be recognised as the same punch and must not be
re-verified. The original already verified.

Phase 5: PunchOut carries site_name so the clock-in screen can name the
branch the employee clocked at without a second round trip to /org/sites.

ten_0030/ten_0031 (privacy policy s5): PunchOut no longer carries flat
latitude, longitude, gps_accuracy_m or distance_m. The fix is a nested
location object, or null -- either because none was captured or because
retention has deleted it.
'''
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
)

_DEVICE_METHODS = ('fingerprint', 'face', 'code', 'pin')


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
    gps_accuracy_m: Decimal | None = None
    # Non-biometric fallback credential. Only read when method == 'pin'.
    # Never persisted, never logged, never returned.
    pin: SecretStr | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator('method')
    @classmethod
    def _v_method(cls, v: str) -> str:
        if v not in _DEVICE_METHODS:
            raise ValueError(f'method must be one of {_DEVICE_METHODS}')
        return v


class PunchBatchIn(BaseModel):
    punches: list[PunchIn] = Field(..., max_length=500)


class PunchLocationOut(BaseModel):
    """The raw GPS fix for one punch.

    Absent once retention deletes it. A null parent `location` means the
    fix is gone or was never captured.
    """

    model_config = ConfigDict(from_attributes=True)

    latitude: Decimal
    longitude: Decimal
    gps_accuracy_m: Decimal | None = None
    distance_m: Decimal | None = None
    captured_at: datetime


class PunchOut(BaseModel):
    id: uuid.UUID
    client_punch_id: uuid.UUID
    employee_id: uuid.UUID
    device_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    site_name: str | None = None
    server_received_at: datetime
    device_time: datetime
    device_now_at_send: datetime | None = None
    effective_time: datetime
    offset_ms: int
    method: str
    match_score: Decimal | None = None
    liveness_passed: bool | None = None
    photo_object_key: str | None = None
    geofence_result: str | None = None
    geofence_reason: str | None = None
    distance_band: str | None = None
    location: PunchLocationOut | None = None
    status: str
    flags: list[str]
    raw_payload: dict[str, Any]
    created_at: datetime
    warnings: list[str] = []


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
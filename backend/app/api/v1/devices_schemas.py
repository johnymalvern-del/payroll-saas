'''Device schemas (Chapter 2A).

DeviceOut never includes api_key_hash. DeviceCreateOut and
DeviceRotateKeyOut are the ONLY two shapes that carry the raw key,
and each is returned exactly once per create/rotate.'''
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

_DEVICE_TYPES = ('usb_fingerprint', 'web_camera', 'phone', 'kiosk')
_STATUSES = ('active', 'inactive', 'suspended', 'offline')


class DeviceOut(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    name: str
    device_type: str
    status: str
    last_seen_at: datetime | None = None
    last_sync_at: datetime | None = None
    pending_punch_count: int
    allows_code_only: bool
    require_photo_for_code: bool
    software_version: str | None = None
    row_version: int


class DeviceCreateOut(DeviceOut):
    api_key: str


class DeviceRotateKeyOut(BaseModel):
    id: uuid.UUID
    api_key: str


class DeviceCreateIn(BaseModel):
    site_id: uuid.UUID
    name: str = Field(..., min_length=1, max_length=120)
    device_type: str
    allows_code_only: bool = False
    require_photo_for_code: bool = True
    software_version: str | None = Field(default=None, max_length=60)


class DevicePatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    site_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = None
    allows_code_only: bool | None = None
    require_photo_for_code: bool | None = None
    software_version: str | None = Field(default=None, max_length=60)


class DeviceListOut(BaseModel):
    items: list[DeviceOut]
    next_cursor: str | None = None
    total: int | None = None

# END OF FILE

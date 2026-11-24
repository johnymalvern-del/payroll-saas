'''Attendance PIN schemas (non-biometric fallback, privacy policy section 4).

The PIN is a SecretStr in both directions. HR sets it and never sees it again;
the status endpoint reports only whether one exists, when it was last set, and
whether the account is locked.

There is deliberately no endpoint that reveals a PIN. A forgotten PIN is reset,
not recovered -- which is only possible because the stored value is a one-way
hash rather than a decryptable column.
'''
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, SecretStr, field_validator


class PinSetIn(BaseModel):
    """A PIN to set or reset. 6 digits exactly."""

    pin: SecretStr = Field(..., description="6 digits")

    @field_validator("pin")
    @classmethod
    def _v_pin(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if len(raw) != 6 or not raw.isdigit():
            raise ValueError("PIN must be exactly 6 digits")
        return v


class PinStatusOut(BaseModel):
    employee_id: uuid.UUID
    pin_set: bool
    pin_set_at: datetime | None = None
    locked: bool = False
    locked_until: datetime | None = None
    failed_attempts: int = 0

# END OF FILE
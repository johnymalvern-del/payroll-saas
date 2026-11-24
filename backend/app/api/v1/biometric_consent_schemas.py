'''Biometric consent schemas.

Consent is ordinary personal data, not biometric data. Recording it does not
touch the approval gate in section 8 of the privacy policy; the gate covers
capturing, storing and comparing biometric templates.

EnrolmentOut deliberately omits template_encrypted. The ciphertext is never
returned by any endpoint -- not because it is indecipherable to the holder of
the tenant key, but because an API that returns it invites a client to cache
it somewhere unencrypted. Nothing in this system needs to read a template back
out; enrolment is write-only from the application's point of view.

has_consent exists so a caller does not have to distinguish "no consent
recorded" from "consent withdrawn". Both mean biometrics may not be used, and
a frontend that renders them differently will eventually get it wrong.
'''
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConsentGrantIn(BaseModel):
    """A consent capture. The employee is identified by the path."""

    consent_text_version: str = Field(min_length=1, max_length=40)
    method: str = Field(default="digital", max_length=40)


class WithdrawIn(BaseModel):
    """Withdrawal. A reason is optional and never required.

    Making a reason mandatory would obstruct a data-subject right, which is
    the one thing a withdrawal flow must never do.
    """

    reason: str | None = Field(default=None, max_length=200)


class ConsentRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    consent_text_version: str
    accepted_at: datetime
    captured_by: uuid.UUID | None = None
    method: str
    withdrawn_at: datetime | None = None
    withdrawn_by: uuid.UUID | None = None


class EnrolmentOut(BaseModel):
    """An enrolment, without the template.

    template_encrypted is deliberately absent -- see the module docstring.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    method: str
    vendor: str
    template_version: str
    enrolled_at: datetime
    revoked_at: datetime | None = None


class ConsentStatusOut(BaseModel):
    """Current biometric state for one employee."""

    employee_id: uuid.UUID
    has_consent: bool
    consent: ConsentRecordOut | None = None
    enrolment: EnrolmentOut | None = None
    # True only when an active, non-withdrawn consent AND a live enrolment
    # both exist. Either alone authorises nothing.
    biometric_active: bool = False
    # Explanation shown to a caller that asked why biometrics are unavailable.
    unavailable_reason: str | None = None


class BiometricNotApprovedOut(BaseModel):
    """Returned by the enrolment endpoint while the approval gate is closed."""

    error: dict[str, Any]
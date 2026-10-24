
"""Company endpoint schemas."""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field


class CompanyOut(BaseModel):
    id: uuid.UUID
    legal_name: str
    trading_name: str | None = None
    registration_number: str | None = None
    tax_number: str | None = None
    paye_reference: str | None = None
    uif_reference: str | None = None
    sdl_reference: str | None = None
    coida_reference: str | None = None
    address: str | None = None
    country_code: str
    currency: str
    default_timezone: str
    settings: dict[str, Any]
    row_version: int


class CompanyPatchIn(BaseModel):
    """All fields optional except row_version, which is required for
    lost-update protection (rule 2).

    tax_number, paye_reference, uif_reference, sdl_reference and
    coida_reference are payroll_admin-only. If an HR user sends them, the
    endpoint rejects the request before applying any change.
    """
    row_version: int = Field(..., ge=1)

    legal_name: str | None = Field(default=None, max_length=200)
    trading_name: str | None = Field(default=None, max_length=200)
    registration_number: str | None = Field(default=None, max_length=60)
    address: str | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    default_timezone: str | None = Field(default=None, max_length=64)
    settings: dict[str, Any] | None = None

    # payroll_admin-only (enforced server-side in the router)
    tax_number: str | None = Field(default=None, max_length=60)
    paye_reference: str | None = Field(default=None, max_length=60)
    uif_reference: str | None = Field(default=None, max_length=60)
    sdl_reference: str | None = Field(default=None, max_length=60)
    coida_reference: str | None = Field(default=None, max_length=60)


# Fields that only payroll_admin may edit. The router enforces this.
PAYROLL_ADMIN_ONLY_FIELDS = frozenset({
    "tax_number",
    "paye_reference",
    "uif_reference",
    "sdl_reference",
    "coida_reference",
})

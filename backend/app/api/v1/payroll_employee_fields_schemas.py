from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmployeeFieldsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    employee_id: uuid.UUID
    contracted_weekly_hours: float | None = None
    medical_scheme_members: int
    uif_exempt: bool
    row_version: int


class EmployeeFieldsChangeIn(BaseModel):
    """Payload for POST /employees/{id}/fields (F3 field-update request).

    At least one of the three mutable fields must be provided; row_version is
    captured at submission time and re-checked at approval time so a change
    that was queued against an older snapshot is refused with record_changed.
    """

    row_version: int
    contracted_weekly_hours: float | None = Field(None, ge=0)
    medical_scheme_members: int | None = Field(None, ge=0)
    uif_exempt: bool | None = None

    @model_validator(mode="after")
    def _require_one_field(self) -> "EmployeeFieldsChangeIn":
        if all(
            getattr(self, name) is None
            for name in ("contracted_weekly_hours", "medical_scheme_members", "uif_exempt")
        ):
            raise ValueError(
                "at least one of contracted_weekly_hours, medical_scheme_members, "
                "uif_exempt must be provided"
            )
        return self

# END OF FILE

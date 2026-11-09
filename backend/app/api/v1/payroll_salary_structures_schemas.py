from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ComponentKind = Literal["earning", "deduction"]
PayBasis = Literal["hourly", "daily", "monthly"]


class StructureComponentIn(BaseModel):
    kind: ComponentKind
    earning_type_id: uuid.UUID | None = None
    deduction_type_id: uuid.UUID | None = None
    amount: Decimal | None = Field(None, ge=0)
    rate: Decimal | None = Field(None, ge=0)

    @model_validator(mode="after")
    def _check_fields(self) -> "StructureComponentIn":
        if self.kind == "earning":
            if self.earning_type_id is None:
                raise ValueError(
                    "earning_type_id is required for kind='earning'"
                )
            if self.deduction_type_id is not None:
                raise ValueError(
                    "deduction_type_id must be None for kind='earning'"
                )
            has_amt = self.amount is not None
            has_rate = self.rate is not None
            if has_amt == has_rate:
                raise ValueError(
                    "earning component requires exactly one of amount or rate"
                )
        else:
            if self.deduction_type_id is None:
                raise ValueError(
                    "deduction_type_id is required for kind='deduction'"
                )
            if self.earning_type_id is not None:
                raise ValueError(
                    "earning_type_id must be None for kind='deduction'"
                )
            if self.amount is None:
                raise ValueError("deduction component requires amount")
            if self.rate is not None:
                raise ValueError("deduction component must not set rate")
        return self


class StructureCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    pay_basis: PayBasis
    base_rate: Decimal = Field(..., ge=0)
    components: list[StructureComponentIn] = Field(default_factory=list)


class StructureEditIn(BaseModel):
    version_number: int = Field(..., ge=1)
    row_version: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    pay_basis: PayBasis | None = None
    base_rate: Decimal | None = Field(None, ge=0)
    components: list[StructureComponentIn] | None = None


class StructureComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    earning_type_id: uuid.UUID | None = None
    deduction_type_id: uuid.UUID | None = None
    amount: Decimal | None = None
    rate: Decimal | None = None


class StructureOut(BaseModel):
    id: uuid.UUID
    structure_group_id: uuid.UUID
    version_number: int
    is_current: bool
    name: str
    description: str | None = None
    pay_basis: str
    base_rate: Decimal
    is_active: bool
    row_version: int
    created_at: datetime
    updated_at: datetime
    components: list[StructureComponentOut] = Field(default_factory=list)


class StructureListOut(BaseModel):
    items: list[StructureOut]


class DeactivateOut(BaseModel):
    deactivated: bool = True
    structure_group_id: uuid.UUID

# END OF FILE
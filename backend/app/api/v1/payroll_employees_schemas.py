from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EmployeeEarningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    earning_type_id: uuid.UUID
    amount: Decimal | None = None
    rate: Decimal | None = None
    effective_from: date
    effective_to: date | None = None
    is_active: bool
    row_version: int


class EmployeeEarningIn(BaseModel):
    earning_type_id: uuid.UUID
    amount: Decimal | None = Field(None, ge=0)
    rate: Decimal | None = Field(None, ge=0)
    effective_from: date
    effective_to: date | None = None


class EmployeeEarningPatch(BaseModel):
    amount: Decimal | None = Field(None, ge=0)
    rate: Decimal | None = Field(None, ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool | None = None
    row_version: int


class EmployeeEarningListOut(BaseModel):
    items: list[EmployeeEarningOut]
    next_cursor: str | None = None


class EmployeeDeductionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    deduction_type_id: uuid.UUID
    amount: Decimal
    balance: Decimal
    effective_from: date
    effective_to: date | None = None
    is_active: bool
    row_version: int


class EmployeeDeductionIn(BaseModel):
    deduction_type_id: uuid.UUID
    amount: Decimal = Field(..., ge=0)
    effective_from: date
    effective_to: date | None = None


class EmployeeDeductionPatch(BaseModel):
    amount: Decimal | None = Field(None, ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    is_active: bool | None = None
    row_version: int


class EmployeeDeductionListOut(BaseModel):
    items: list[EmployeeDeductionOut]
    next_cursor: str | None = None

# END OF FILE

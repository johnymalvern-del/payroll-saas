"""Employee endpoint schemas (1C.8).

Read shape returns masked versions of the encrypted fields for callers with
EMPLOYEE_CRUD. The full values are returned only by GET /api/v1/employees/me
for the data subject themselves.

Write shape (create) accepts national_id and bank_account_number in plain
form; the router encrypts them via TenantCrypto. Neither field is accepted
on PATCH; changes to those go through the request/approve flow in a later
phase (per 1C.8 decisions 2A and the national_id parity rule).

PATCH requires row_version; stale values return 409 record_changed.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


_ALLOWED_STATUS = ("active", "on_leave", "suspended", "terminated")
_ALLOWED_EMPLOYEE_TYPE = ("hourly", "salaried", "casual", "contract")
_ALLOWED_PAY_BASIS = ("hourly", "daily", "monthly")
_ALLOWED_PAY_FREQUENCY = ("weekly", "fortnightly", "monthly")
_PATCH_FORBIDDEN_FIELDS = frozenset({"national_id", "bank_account_number"})


def _clean_code(v: str) -> str:
    if v is None:
        return v
    trimmed = v.strip()
    if not trimmed:
        raise ValueError("employee_code must not be empty")
    return trimmed


class EmployeeOut(BaseModel):
    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    national_id_masked: str | None = None
    email: str | None = None
    mobile: str | None = None
    date_of_birth: date | None = None
    hire_date: date
    termination_date: date | None = None
    status: str
    job_title: str | None = None
    branch_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    employee_type: str
    pay_basis: str
    pay_frequency: str
    base_rate: Decimal | None = None
    overtime_eligible: bool
    clocks: bool
    work_pattern_id: uuid.UUID | None = None
    default_shift_id: uuid.UUID | None = None
    bank_name: str | None = None
    bank_account_number_masked: str | None = None
    bank_branch_code: str | None = None
    account_type: str | None = None
    tax_number: str | None = None
    medical_aid_dependants: int
    retirement_fund_flags: str | None = None
    uif_exempt: bool
    notes: str | None = None
    row_version: int


class EmployeeMeOut(EmployeeOut):
    """Same shape as EmployeeOut, but the masked fields are decrypted."""

    national_id: str | None = None
    bank_account_number: str | None = None


class EmployeeCreateIn(BaseModel):
    employee_code: str = Field(..., min_length=1, max_length=40)
    first_name: str = Field(..., min_length=1, max_length=120)
    last_name: str = Field(..., min_length=1, max_length=120)
    national_id: str | None = None
    email: str | None = Field(default=None, max_length=255)
    mobile: str | None = Field(default=None, max_length=40)
    date_of_birth: date | None = None
    hire_date: date
    termination_date: date | None = None
    status: str = Field(default="active")
    job_title: str | None = Field(default=None, max_length=120)
    branch_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    employee_type: str = Field(default="hourly")
    pay_basis: str = Field(default="hourly")
    pay_frequency: str = Field(default="monthly")
    base_rate: Decimal | None = None
    overtime_eligible: bool = True
    clocks: bool = True
    work_pattern_id: uuid.UUID | None = None
    default_shift_id: uuid.UUID | None = None
    bank_name: str | None = Field(default=None, max_length=120)
    bank_account_number: str | None = None
    bank_branch_code: str | None = Field(default=None, max_length=20)
    account_type: str | None = Field(default=None, max_length=40)
    tax_number: str | None = Field(default=None, max_length=40)
    medical_aid_dependants: int = Field(default=0, ge=0)
    retirement_fund_flags: str | None = Field(default=None, max_length=120)
    uif_exempt: bool = False
    notes: str | None = None

    @field_validator("employee_code")
    @classmethod
    def _validate_code(cls, v: str) -> str:
        return _clean_code(v)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in _ALLOWED_STATUS:
            raise ValueError(f"status must be one of {_ALLOWED_STATUS}")
        return v

    @field_validator("employee_type")
    @classmethod
    def _validate_type(cls, v: str) -> str:
        if v not in _ALLOWED_EMPLOYEE_TYPE:
            raise ValueError(
                f"employee_type must be one of {_ALLOWED_EMPLOYEE_TYPE}"
            )
        return v

    @field_validator("pay_basis")
    @classmethod
    def _validate_basis(cls, v: str) -> str:
        if v not in _ALLOWED_PAY_BASIS:
            raise ValueError(f"pay_basis must be one of {_ALLOWED_PAY_BASIS}")
        return v

    @field_validator("pay_frequency")
    @classmethod
    def _validate_frequency(cls, v: str) -> str:
        if v not in _ALLOWED_PAY_FREQUENCY:
            raise ValueError(
                f"pay_frequency must be one of {_ALLOWED_PAY_FREQUENCY}"
            )
        return v


class EmployeePatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    employee_code: str | None = Field(default=None, min_length=1, max_length=40)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    mobile: str | None = Field(default=None, max_length=40)
    date_of_birth: date | None = None
    hire_date: date | None = None
    termination_date: date | None = None
    status: str | None = None
    job_title: str | None = Field(default=None, max_length=120)
    branch_id: uuid.UUID | None = None
    site_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    employee_type: str | None = None
    pay_basis: str | None = None
    pay_frequency: str | None = None
    base_rate: Decimal | None = None
    overtime_eligible: bool | None = None
    clocks: bool | None = None
    work_pattern_id: uuid.UUID | None = None
    default_shift_id: uuid.UUID | None = None
    bank_name: str | None = Field(default=None, max_length=120)
    bank_branch_code: str | None = Field(default=None, max_length=20)
    account_type: str | None = Field(default=None, max_length=40)
    tax_number: str | None = Field(default=None, max_length=40)
    medical_aid_dependants: int | None = Field(default=None, ge=0)
    retirement_fund_flags: str | None = Field(default=None, max_length=120)
    uif_exempt: bool | None = None
    notes: str | None = None

    @field_validator("employee_code")
    @classmethod
    def _validate_code(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _clean_code(v)

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ALLOWED_STATUS:
            raise ValueError(f"status must be one of {_ALLOWED_STATUS}")
        return v

    @field_validator("employee_type")
    @classmethod
    def _validate_type(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ALLOWED_EMPLOYEE_TYPE:
            raise ValueError(
                f"employee_type must be one of {_ALLOWED_EMPLOYEE_TYPE}"
            )
        return v

    @field_validator("pay_basis")
    @classmethod
    def _validate_basis(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ALLOWED_PAY_BASIS:
            raise ValueError(f"pay_basis must be one of {_ALLOWED_PAY_BASIS}")
        return v

    @field_validator("pay_frequency")
    @classmethod
    def _validate_frequency(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in _ALLOWED_PAY_FREQUENCY:
            raise ValueError(
                f"pay_frequency must be one of {_ALLOWED_PAY_FREQUENCY}"
            )
        return v


class EmployeeListOut(BaseModel):
    items: list[EmployeeOut]
    next_cursor: str | None = None
    total: int | None = None


PATCH_FORBIDDEN_FIELDS = _PATCH_FORBIDDEN_FIELDS

# END OF FILE
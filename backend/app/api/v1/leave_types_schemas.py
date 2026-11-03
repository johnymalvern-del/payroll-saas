"""Leave type schemas (Chapter 3, 3B.1)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ALLOWED_UNITS = ("hour", "day")
ALLOWED_ACCRUAL_METHODS = ("annual", "monthly", "none", "fixed")
ALLOWED_CYCLES = ("calendar", "anniversary", "fixed")
ALLOWED_APPROVER_ROLES = ("manager", "hr", "payroll_admin")

DEFAULT_APPROVAL_CHAIN = ["manager", "hr"]


def _clean_code(v: str) -> str:
    return v.strip().lower()


def _validate_unit(v: str) -> str:
    if v not in ALLOWED_UNITS:
        raise ValueError(f"unit must be one of {ALLOWED_UNITS}")
    return v


def _validate_method(v: str) -> str:
    if v not in ALLOWED_ACCRUAL_METHODS:
        raise ValueError(f"accrual_method must be one of {ALLOWED_ACCRUAL_METHODS}")
    return v


def _validate_cycle(v: str) -> str:
    if v not in ALLOWED_CYCLES:
        raise ValueError(f"cycle must be one of {ALLOWED_CYCLES}")
    return v


def _validate_chain(v: list[str]) -> list[str]:
    if not isinstance(v, list):
        raise ValueError("approval_chain must be a list of roles")
    seen: set[str] = set()
    for role in v:
        if role not in ALLOWED_APPROVER_ROLES:
            raise ValueError(
                f"approval_chain role {role!r} must be one of {ALLOWED_APPROVER_ROLES}"
            )
        if role in seen:
            raise ValueError(f"approval_chain contains duplicate role {role!r}")
        seen.add(role)
    return list(v)


class LeaveTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    unit: str
    paid: bool
    accrual_method: str
    accrual_amount: Decimal | None = None
    cycle: str
    requires_approval: bool
    requires_document_after_days: int | None = None
    allow_negative: bool
    max_carryover: Decimal | None = None
    is_active: bool
    row_version: int
    approval_chain: list[str]
    requires_payroll_admin_final: bool
    created_at: datetime
    updated_at: datetime


class LeaveTypeIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    code: str = Field(..., min_length=1, max_length=30)
    unit: str = "day"
    paid: bool = True
    accrual_method: str = "none"
    accrual_amount: Decimal | None = Field(None, ge=0)
    cycle: str = "calendar"
    requires_approval: bool = True
    requires_document_after_days: int | None = Field(None, ge=0)
    allow_negative: bool = False
    max_carryover: Decimal | None = Field(None, ge=0)
    approval_chain: list[str] = Field(default_factory=lambda: list(DEFAULT_APPROVAL_CHAIN))
    requires_payroll_admin_final: bool = False

    @field_validator("code")
    @classmethod
    def _v_code(cls, v: str) -> str:
        v = _clean_code(v)
        if not v:
            raise ValueError("code must not be blank")
        return v

    @field_validator("unit")
    @classmethod
    def _v_unit(cls, v: str) -> str:
        return _validate_unit(v)

    @field_validator("accrual_method")
    @classmethod
    def _v_method(cls, v: str) -> str:
        return _validate_method(v)

    @field_validator("cycle")
    @classmethod
    def _v_cycle(cls, v: str) -> str:
        return _validate_cycle(v)

    @field_validator("approval_chain")
    @classmethod
    def _v_chain(cls, v: list[str]) -> list[str]:
        return _validate_chain(v)


class LeaveTypePatch(BaseModel):
    row_version: int = Field(..., ge=1)
    name: str | None = Field(None, min_length=1, max_length=80)
    unit: str | None = None
    paid: bool | None = None
    accrual_method: str | None = None
    accrual_amount: Decimal | None = Field(None, ge=0)
    cycle: str | None = None
    requires_approval: bool | None = None
    requires_document_after_days: int | None = Field(None, ge=0)
    allow_negative: bool | None = None
    max_carryover: Decimal | None = Field(None, ge=0)
    approval_chain: list[str] | None = None
    requires_payroll_admin_final: bool | None = None
    is_active: bool | None = None

    @field_validator("unit")
    @classmethod
    def _v_unit(cls, v: str | None) -> str | None:
        return v if v is None else _validate_unit(v)

    @field_validator("accrual_method")
    @classmethod
    def _v_method(cls, v: str | None) -> str | None:
        return v if v is None else _validate_method(v)

    @field_validator("cycle")
    @classmethod
    def _v_cycle(cls, v: str | None) -> str | None:
        return v if v is None else _validate_cycle(v)

    @field_validator("approval_chain")
    @classmethod
    def _v_chain(cls, v: list[str] | None) -> list[str] | None:
        return v if v is None else _validate_chain(v)


class LeaveTypeListOut(BaseModel):
    items: list[LeaveTypeOut]
    next_cursor: str | None = None
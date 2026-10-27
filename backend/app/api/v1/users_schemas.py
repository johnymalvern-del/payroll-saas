"""User and user-scope schemas (1C.9).

PATCH accepts only is_active; username, password, role, employee_id,
password_hash and must_change_password are declared here solely so the
endpoint can refuse them with 400 field_not_patchable instead of silently
dropping them (Pydantic v2 drops undeclared fields by default).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

_ALLOWED_ROLES = ("employee", "manager", "hr", "payroll_admin", "auditor")
_ALLOWED_SCOPE_TYPES = ("site", "branch", "department")

_USER_PATCH_FORBIDDEN_FIELDS = frozenset({
    "username", "password", "role", "employee_id",
    "password_hash", "must_change_password",
})


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    employee_id: uuid.UUID | None = None
    role: str
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None = None
    row_version: int


class UserCreateIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=1, max_length=512)
    role: str
    employee_id: uuid.UUID | None = None
    is_active: bool = True


class UserPatchIn(BaseModel):
    row_version: int = Field(..., ge=1)
    is_active: bool | None = None
    # Declared only so the endpoint can refuse them with field_not_patchable.
    username: str | None = None
    password: str | None = None
    role: str | None = None
    employee_id: uuid.UUID | None = None
    password_hash: str | None = None
    must_change_password: bool | None = None


class UserListOut(BaseModel):
    items: list[UserOut]
    next_cursor: str | None = None
    total: int | None = None


class ScopeOut(BaseModel):
    id: uuid.UUID
    scope_type: str
    scope_id: uuid.UUID


class ScopeListOut(BaseModel):
    items: list[ScopeOut]


class ScopeItemIn(BaseModel):
    scope_type: str
    scope_id: uuid.UUID


class ScopeReplaceIn(BaseModel):
    items: list[ScopeItemIn]


USER_PATCH_FORBIDDEN_FIELDS = _USER_PATCH_FORBIDDEN_FIELDS
ALLOWED_ROLES = _ALLOWED_ROLES
ALLOWED_SCOPE_TYPES = _ALLOWED_SCOPE_TYPES

# END OF FILE
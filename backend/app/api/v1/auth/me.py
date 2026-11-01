"""Current-user endpoint (B-1).

GET /auth/me returns the authenticated user's id, username, role,
employee_id, and permissions from the live ROLE_PERMISSIONS matrix
(app/core/permissions.py), never a client-side hard-coded copy.

must_change_password is read from the User.must_change_password column
(explicit flag the app uses to gate the UI). Fallback: if a migration ever
drops that column, the endpoint falls back to `password_changed_at is None`.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.core.auth_deps import get_current_user
from app.core.permissions import ROLE_PERMISSIONS

router = APIRouter(prefix="/auth/me", tags=["auth"])


class UserMeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    role: str
    employee_id: uuid.UUID | None
    permissions: list[str]
    must_change_password: bool


def _must_change_password(user: Any) -> bool:
    if hasattr(user, "must_change_password"):
        return bool(user.must_change_password)
    # fallback only; the column exists today (ten_0002)
    if hasattr(user, "password_changed_at"):
        return user.password_changed_at is None
    return False


@router.get("", response_model=UserMeOut)
def get_me(
    user: Annotated[Any, Depends(get_current_user)],
) -> UserMeOut:
    role = getattr(user, "role", None) or "unknown"
    permissions = sorted(
        p.value for p in ROLE_PERMISSIONS.get(role, frozenset())
    )
    return UserMeOut(
        id=user.id,
        username=user.username,
        role=role,
        employee_id=getattr(user, "employee_id", None),
        permissions=permissions,
        must_change_password=_must_change_password(user),
    )

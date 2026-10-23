
"""Pydantic schemas for auth endpoints."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)
    company_code: str | None = Field(
        default=None,
        max_length=60,
        description="Required only when no tenant subdomain / header is present.",
    )


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshIn(BaseModel):
    # Optional because in production the refresh token is in the httpOnly
    # cookie and the body may be empty.
    refresh_token: str | None = Field(default=None, max_length=4096)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=12, max_length=200)


class MeOut(BaseModel):
    user_id: str
    username: str
    role: str
    email: EmailStr | None = None
    must_change_password: bool


__all__ = [
    "LoginIn",
    "TokenPairOut",
    "RefreshIn",
    "ChangePasswordIn",
    "MeOut",
]

"""JWT issuance and verification for the payroll SaaS.

Access tokens (15 min) and refresh tokens (30 days) are both signed with
SECRET_KEY using HS256. They differ in their `type` claim:

  access : sub, tenant, role, jti, iat, exp, type=access
  refresh: sub, tenant, jti, iat, exp, type=refresh
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
ALGORITHM = "HS256"


class TokenError(Exception):
    """Any reason a token is rejected."""


@dataclass(frozen=True)
class TokenClaims:
    user_id: str
    tenant: str
    role: str | None
    jti: str
    type: str
    issued_at: datetime
    expires_at: datetime


class JWTManager:
    def __init__(self, secret_key: str) -> None:
        self._secret = secret_key

    def issue_access(self, user_id: str, tenant: str, role: str) -> str:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": user_id,
            "tenant": tenant,
            "role": role,
            "jti": uuid.uuid4().hex,
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + ACCESS_TTL).timestamp()),
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def issue_refresh(self, user_id: str, tenant: str) -> str:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "sub": user_id,
            "tenant": tenant,
            "jti": uuid.uuid4().hex,
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int((now + REFRESH_TTL).timestamp()),
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def decode(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(token, self._secret, algorithms=[ALGORITHM])
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("token expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError("token invalid") from exc

        try:
            return TokenClaims(
                user_id=payload["sub"],
                tenant=payload["tenant"],
                role=payload.get("role"),
                jti=payload["jti"],
                type=payload["type"],
                issued_at=datetime.fromtimestamp(payload["iat"], tz=timezone.utc),
                expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
            )
        except KeyError as exc:
            raise TokenError(f"missing claim: {exc.args[0]}") from exc

    def is_access(self, claims: TokenClaims) -> bool:
        return claims.type == "access"

    def is_refresh(self, claims: TokenClaims) -> bool:
        return claims.type == "refresh"
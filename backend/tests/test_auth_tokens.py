"""Tests for JWTManager.

Four tests:
  1. Access token verifies and carries the exact claims we issued.
  2. Refresh token verifies and is distinguishable from access.
  3. Expired access token rejects with TokenError.
  4. Tampered token rejects with TokenError.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import jwt
import pytest

from app.core.auth_tokens import JWTManager, TokenError


def _mgr() -> JWTManager:
    return JWTManager(secret_key="z" * 40)


def test_access_token_verifies() -> None:
    m = _mgr()
    token = m.issue_access(user_id="user-42", tenant="demo", role="hr")
    claims = m.decode(token)
    assert claims.user_id == "user-42"
    assert claims.tenant == "demo"
    assert claims.role == "hr"
    assert claims.type == "access"
    assert len(claims.jti) == 32
    assert claims.expires_at > claims.issued_at
    assert m.is_access(claims) and not m.is_refresh(claims)


def test_refresh_token_verifies() -> None:
    m = _mgr()
    token = m.issue_refresh(user_id="user-42", tenant="demo")
    claims = m.decode(token)
    assert claims.user_id == "user-42"
    assert claims.tenant == "demo"
    assert claims.role is None
    assert claims.type == "refresh"
    assert m.is_refresh(claims) and not m.is_access(claims)


def test_expired_access_token_rejected() -> None:
    m = _mgr()
    token = m.issue_access(user_id="u", tenant="t", role="employee")
    # Force decode into the future by patching jwt.decode's notion of "now"
    # is awkward. Simpler: craft a token with an already-past exp.
    past = int(time.time()) - 120
    expired = jwt.encode(
        {
            "sub": "u",
            "tenant": "t",
            "role": "employee",
            "jti": "deadbeef",
            "type": "access",
            "iat": past - 60,
            "exp": past,
        },
        m._secret,  # type: ignore[attr-defined]
        algorithm="HS256",
    )
    with pytest.raises(TokenError, match="expired"):
        m.decode(expired)


def test_tampered_token_rejected() -> None:
    m = _mgr()
    token = m.issue_access(user_id="u", tenant="t", role="employee")
    tampered = token[:-4] + ("aaaa" if token[-4:] != "aaaa" else "bbbb")
    with pytest.raises(TokenError, match="invalid"):
        m.decode(tampered)
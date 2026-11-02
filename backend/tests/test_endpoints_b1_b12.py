"""HTTP-level tests for B-1 (/auth/me.default_timezone) and B-12
(/attendance/reason-codes).

Follows the provisioning pattern in test_auth_endpoints.py: a fresh
tenant per test, admin login via /auth/login, then direct endpoint calls
with the issued bearer token. Autouse rate-limiter reset mirrors the
existing file so login calls never trip the per-IP limiter.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limiter.factory import get_rate_limiter
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


_ADMIN_USERNAME = "admin"
_ADMIN_PASSWORD = "AdminPassword123!"


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    rl = get_rate_limiter()
    if hasattr(rl, "_events"):
        rl._events.clear()  # type: ignore[attr-defined]
    yield
    if hasattr(rl, "_events"):
        rl._events.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def tenant_with_admin(api_client: TestClient):
    slug = f"b1b12-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug,
        name="B1/B12 Co",
        admin_username=_ADMIN_USERNAME,
        admin_password_hash=hash_password(_ADMIN_PASSWORD),
    )
    db_name = _tenant_db_name(slug)
    try:
        first = api_client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": slug},
            json={"identifier": _ADMIN_USERNAME, "password": _ADMIN_PASSWORD},
        )
        assert first.status_code == 200, first.text
        yield slug, first.json()
    finally:
        _drop_tenant_database(db_name)
        with control_session() as session:
            row = (
                session.query(Subscriber)
                .filter(Subscriber.slug == slug)
                .one_or_none()
            )
            if row is not None:
                session.delete(row)


def _auth_headers(slug: str, token: str) -> dict[str, str]:
    return {
        "X-Tenant-Slug": slug,
        "Authorization": f"Bearer {token}",
    }


# ---------------------------------------------------------------------------
# B-1: /auth/me default_timezone
# ---------------------------------------------------------------------------


def test_me_returns_default_timezone(api_client, tenant_with_admin):
    slug, first = tenant_with_admin
    r = api_client.get(
        "/api/v1/auth/me",
        headers=_auth_headers(slug, first["access_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "default_timezone" in body
    assert body["default_timezone"] == "Africa/Johannesburg"
    # Sanity: existing fields still present.
    assert body["username"] == _ADMIN_USERNAME
    assert body["role"] == "payroll_admin"
    assert isinstance(body["permissions"], list)
    assert body["must_change_password"] is True


def test_me_requires_auth(api_client, tenant_with_admin):
    slug, _ = tenant_with_admin
    r = api_client.get(
        "/api/v1/auth/me",
        headers={"X-Tenant-Slug": slug},
    )
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# B-12: /attendance/reason-codes
# ---------------------------------------------------------------------------


def test_reason_codes_http_returns_default_set(api_client, tenant_with_admin):
    slug, first = tenant_with_admin
    r = api_client.get(
        "/api/v1/attendance/reason-codes",
        headers=_auth_headers(slug, first["access_token"]),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    codes = [i["code"] for i in items]
    assert codes == [
        "device_down",
        "forgot_clock",
        "approved_site_work",
        "system_correction",
        "other",
    ]
    other = next(i for i in items if i["code"] == "other")
    assert other["requires_note"] is True
    assert other["label"] == "Other"
    for i in items:
        if i["code"] != "other":
            assert i["requires_note"] is False


def test_reason_codes_requires_auth(api_client, tenant_with_admin):
    slug, _ = tenant_with_admin
    r = api_client.get(
        "/api/v1/attendance/reason-codes",
        headers={"X-Tenant-Slug": slug},
    )
    assert r.status_code == 401
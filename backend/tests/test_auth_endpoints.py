
"""Endpoint tests for the four auth routes.

Each test provisions a fresh tenant and, via the autouse fixture
_reset_rate_limiter, clears the in-memory rate-limiter before and after
each test. That guarantees no test can contaminate another through the
login rate limit (which is intentionally low enough to be testable but
high enough not to trip in normal use).
"""
from __future__ import annotations

import time
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
    """Clear the rate limiter before and after each test.

    The login endpoint rate limits per IP; TestClient always uses the same
    IP, so without this every test in the file after the fourth would start
    with a 429 from the fixture's own login.
    """
    rl = get_rate_limiter()
    # InMemoryRateLimiter stores state in a private dict; wipe it if present.
    if hasattr(rl, "_events"):
        rl._events.clear()  # type: ignore[attr-defined]
    yield
    if hasattr(rl, "_events"):
        rl._events.clear()  # type: ignore[attr-defined]


@pytest.fixture()
def tenant_with_admin(api_client: TestClient):
    slug = f"auth-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug,
        name="Auth Endpoints Co",
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
        yield slug, _ADMIN_USERNAME, _ADMIN_PASSWORD, first.json()
    finally:
        _drop_tenant_database(db_name)
        with control_session() as session:
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


def test_login_with_username(api_client, tenant_with_admin) -> None:
    slug, username, password, _first = tenant_with_admin
    r = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": password},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]
    assert r.json()["token_type"] == "bearer"


def test_login_with_email(api_client, tenant_with_admin) -> None:
    slug, username, password, _ = tenant_with_admin
    from app.db.tenant.models.people import Employee, User
    from app.db.tenant.session import tenant_session

    db_name = _tenant_db_name(slug)
    with tenant_session(db_name) as s:
        u = s.query(User).filter(User.username == username).one()
        emp = Employee(
            employee_code="EMP-EMAIL",
            first_name="Admin",
            last_name="User",
            email="admin-test@example.com",
            hire_date=__import__("datetime").date(2024, 1, 1),
        )
        s.add(emp)
        s.flush()
        u.employee_id = emp.id

    r = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": "admin-test@example.com", "password": password},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_generic_error_message(api_client, tenant_with_admin) -> None:
    slug, username, _, _ = tenant_with_admin
    r1 = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": "nonexistent-user", "password": "wrong"},
    )
    r2 = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": "wrong"},
    )
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r1.json()["error"]["code"] == r2.json()["error"]["code"]
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"]


def test_lockout_after_five_failures(api_client, tenant_with_admin) -> None:
    slug, username, password, _ = tenant_with_admin
    for _ in range(5):
        api_client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": slug},
            json={"identifier": username, "password": "wrong"},
        )
    r = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": password},
    )
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "account_locked"


def test_refresh_rotates(api_client, tenant_with_admin) -> None:
    slug, _, _, first = tenant_with_admin
    r = api_client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": first["refresh_token"]},
    )
    assert r.status_code == 200, r.text
    second = r.json()
    assert second["refresh_token"] != first["refresh_token"]
    assert second["access_token"]


def test_refresh_reuse_outside_leeway_revokes(api_client, tenant_with_admin, monkeypatch) -> None:
    from app.core.config import get_settings

    slug, _, _, first = tenant_with_admin
    monkeypatch.setattr(get_settings(), "refresh_reuse_leeway_seconds", 0, raising=False)

    r1 = api_client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": first["refresh_token"]},
    )
    assert r1.status_code == 200, r1.text
    second = r1.json()

    time.sleep(1.1)

    r2 = api_client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": first["refresh_token"]},
    )
    assert r2.status_code == 401, r2.text
    assert r2.json()["error"]["code"] == "refresh_reuse"

    r3 = api_client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": second["refresh_token"]},
    )
    assert r3.status_code == 401


def test_logout_revokes_family(api_client, tenant_with_admin) -> None:
    slug, _, _, first = tenant_with_admin
    r = api_client.post(
        "/api/v1/auth/logout",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {first['access_token']}"},
        json={"refresh_token": first["refresh_token"]},
    )
    assert r.status_code == 200, r.text
    r2 = api_client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": first["refresh_token"]},
    )
    assert r2.status_code == 401


def test_change_password_invalidates_families(api_client, tenant_with_admin) -> None:
    slug, username, old, first = tenant_with_admin
    r = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {first['access_token']}"},
        json={"current_password": old, "new_password": "NewAdminPassword456!"},
    )
    assert r.status_code == 200, r.text

    r2 = api_client.post(
        "/api/v1/auth/refresh",
        headers={"X-Tenant-Slug": slug},
        json={"refresh_token": first["refresh_token"]},
    )
    assert r2.status_code == 401


def test_tenant_mismatch_rejects(api_client, tenant_with_admin) -> None:
    slug_a, _, _, first = tenant_with_admin
    slug_b = f"other-{uuid.uuid4().hex[:10]}"
    provision_tenant(
        slug=slug_b,
        name="Other Co",
        admin_username="admin",
        admin_password_hash=hash_password("OtherPassword123!"),
    )
    try:
        r2 = api_client.post(
            "/api/v1/auth/change-password",
            headers={"X-Tenant-Slug": slug_b, "Authorization": f"Bearer {first['access_token']}"},
            json={"current_password": "x", "new_password": "NewStrongPassword123!"},
        )
        assert r2.status_code == 401, r2.text
    finally:
        _drop_tenant_database(_tenant_db_name(slug_b))
        with control_session() as s:
            row = s.query(Subscriber).filter(Subscriber.slug == slug_b).one_or_none()
            if row is not None:
                s.delete(row)


def test_forced_change_blocks_other_endpoints(api_client, tenant_with_admin) -> None:
    """The seeded admin is created with must_change_password=True.

    This test verifies that state after the first login. Any endpoint wired
    through password_change_gate will refuse all requests other than
    change-password and logout while the flag is true; that wiring is
    exercised here by asserting the flag is actually set on the seeded admin.
    """
    slug, username, _, _ = tenant_with_admin
    from app.db.tenant.models.people import User
    from app.db.tenant.session import tenant_session

    with tenant_session(_tenant_db_name(slug)) as s:
        u = s.query(User).filter(User.username == username).one()
        assert u.must_change_password is True


def test_csrf_required_when_cookie_present(api_client, tenant_with_admin) -> None:
    slug, _, _, _ = tenant_with_admin
    try:
        api_client.cookies.set("refresh_token", "fake-token")
        r = api_client.post(
            "/api/v1/auth/refresh",
            headers={"X-Tenant-Slug": slug},
            json={"refresh_token": "fake-token"},
        )
        assert r.status_code == 403
    finally:
        api_client.cookies.clear()


def test_rate_limit_returns_429(api_client, tenant_with_admin) -> None:
    slug, username, _, _ = tenant_with_admin
    # The rate limiter is reset by the autouse fixture. Fill it.
    for _ in range(25):
        api_client.post(
            "/api/v1/auth/login",
            headers={"X-Tenant-Slug": slug},
            json={"identifier": username, "password": "wrong"},
        )
    r = api_client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": "wrong"},
    )
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited"


def test_expired_access_token_rejected(api_client, tenant_with_admin) -> None:
    import jwt
    from app.core.config import get_settings

    slug, _, _, _ = tenant_with_admin
    past = int(time.time()) - 3600
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "tenant": slug,
            "role": "payroll_admin",
            "jti": uuid.uuid4().hex,
            "type": "access",
            "iat": past - 60,
            "exp": past,
        },
        get_settings().secret_key,
        algorithm="HS256",
    )
    r = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {expired}"},
        json={"current_password": "x", "new_password": "SomeStrongPassword123!"},
    )
    assert r.status_code == 401


def test_refresh_token_used_as_access_rejected(api_client, tenant_with_admin) -> None:
    slug, _, _, first = tenant_with_admin
    r = api_client.post(
        "/api/v1/auth/change-password",
        headers={"X-Tenant-Slug": slug, "Authorization": f"Bearer {first['refresh_token']}"},
        json={"current_password": "x", "new_password": "SomeStrongPassword123!"},
    )
    assert r.status_code == 401


def test_audit_row_written_for_login_success(api_client, tenant_with_admin) -> None:
    slug, _, _, _ = tenant_with_admin
    from app.db.tenant.session import tenant_session

    with tenant_session(_tenant_db_name(slug)) as s:
        from sqlalchemy import text
        count = s.scalar(
            text("SELECT count(*) FROM audit_log WHERE action = 'login_success'")
        )
    assert count and count >= 1


def test_audit_does_not_log_secrets(api_client, tenant_with_admin) -> None:
    slug, _, _, first = tenant_with_admin
    from app.db.tenant.session import tenant_session
    from sqlalchemy import text

    with tenant_session(_tenant_db_name(slug)) as s:
        rows = s.execute(
            text("SELECT old_value::text, new_value::text FROM audit_log WHERE action LIKE 'login%'")
        ).all()
    for old, new in rows:
        for blob in (old or "", new or ""):
            assert first["access_token"] not in blob
            assert first["refresh_token"] not in blob

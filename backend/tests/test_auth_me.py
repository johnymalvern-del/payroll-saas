"""B-1: GET /auth/me tests.

Root cause fixed here: normalise_username("pa-1") collapses to "pa1" because
the rule treats (digit + separator) as a mobile number. _mk_user must store
whatever authenticate() will later look up, so it applies normalise_username
to the input. Callers still pass "pa-1" to _login; authenticate normalises it
to "pa1" and finds the row.

must_change_password is read from the real User.must_change_password column.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import hash_password
from app.core.usernames import normalise_username
from app.db.tenant.models.people import User
from app.db.tenant.session import get_tenant_engine


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session
    from app.services.provisioning import (
        _drop_tenant_database,
        _tenant_db_name,
        provision_tenant,
    )
    slug = f"auth-me-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Auth Me Test",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        try:
            _drop_tenant_database(db_name)
        except Exception:
            pass
        with control_session() as session:
            row = (
                session.query(Subscriber)
                .filter(Subscriber.slug == slug)
                .one_or_none()
            )
            if row is not None:
                session.delete(row)


@pytest.fixture()
def tenant_session(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    session = Session(engine)
    try:
        yield session, engine
    finally:
        session.close()
        engine.dispose()


def _mk_user(
    session,
    *,
    username,
    role,
    password,
    employee_id=None,
    must_change_password=False,
    password_changed_at="set",
):
    if password_changed_at == "set":
        password_changed_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    stored_username = normalise_username(username)
    u = User(
        id=uuid.uuid4(),
        username=stored_username,
        password_hash=hash_password(password),
        role=role,
        employee_id=employee_id,
        is_active=True,
        must_change_password=must_change_password,
        failed_attempts=0,
        locked_until=None,
        password_changed_at=password_changed_at,
    )
    session.add(u)
    session.commit()
    return u


def _client() -> TestClient:
    from app.main import app
    return TestClient(app)


def _login(client, slug, username, password):
    r = client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": password},
    )
    assert r.status_code == 200, (
        f"login failed: status={r.status_code} body={r.text} "
        f"username={username!r} slug={slug!r}"
    )
    body = r.json()
    token = body.get("access_token") or body.get("access")
    assert isinstance(token, str) and token, (
        f"login 200 but no access token in body: keys={sorted(body.keys())}"
    )
    return token


# ---------------------------------------------------------------------------
# Auth required
# ---------------------------------------------------------------------------

def test_auth_me_requires_auth(disposable_tenant):
    client = _client()
    r = client.get(
        "/api/v1/auth/me",
        headers={"X-Tenant-Slug": disposable_tenant.slug},
    )
    assert r.status_code == 401, r.text


# ---------------------------------------------------------------------------
# Role + permissions from the live matrix
# ---------------------------------------------------------------------------

def test_auth_me_returns_payroll_admin_role_and_permissions(
    disposable_tenant, tenant_session,
):
    session, _ = tenant_session
    _mk_user(session, username="paone", role="payroll_admin", password="PaPass123!")
    client = _client()
    token = _login(client, disposable_tenant.slug, "paone", "PaPass123!")
    r = client.get(
        "/api/v1/auth/me",
        headers={
            "X-Tenant-Slug": disposable_tenant.slug,
            "Authorization": f"Bearer {token}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "payroll_admin"
    assert body["username"] == "paone"
    expected = sorted(p.value for p in ROLE_PERMISSIONS["payroll_admin"])
    assert sorted(body["permissions"]) == expected
    assert body["must_change_password"] is False


def test_auth_me_returns_employee_role_and_permissions(
    disposable_tenant, tenant_session,
):
    session, _ = tenant_session
    _mk_user(session, username="empone", role="employee", password="EmpPass123!")
    client = _client()
    token = _login(client, disposable_tenant.slug, "empone", "EmpPass123!")
    r = client.get(
        "/api/v1/auth/me",
        headers={
            "X-Tenant-Slug": disposable_tenant.slug,
            "Authorization": f"Bearer {token}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "employee"
    expected = sorted(p.value for p in ROLE_PERMISSIONS["employee"])
    assert sorted(body["permissions"]) == expected


# ---------------------------------------------------------------------------
# must_change_password reflects the column
# ---------------------------------------------------------------------------

def test_auth_me_must_change_password_true_when_flag_set(
    disposable_tenant, tenant_session,
):
    session, _ = tenant_session
    _mk_user(
        session,
        username="pamcfirst",
        role="payroll_admin",
        password="PaPass123!",
        must_change_password=True,
        password_changed_at=None,
    )
    client = _client()
    token = _login(client, disposable_tenant.slug, "pamcfirst", "PaPass123!")
    r = client.get(
        "/api/v1/auth/me",
        headers={
            "X-Tenant-Slug": disposable_tenant.slug,
            "Authorization": f"Bearer {token}",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is True


def test_auth_me_must_change_password_false_when_flag_clear(
    disposable_tenant, tenant_session,
):
    session, _ = tenant_session
    _mk_user(
        session,
        username="pamcsecond",
        role="payroll_admin",
        password="PaPass123!",
        must_change_password=False,
        password_changed_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    client = _client()
    token = _login(client, disposable_tenant.slug, "pamcsecond", "PaPass123!")
    r = client.get(
        "/api/v1/auth/me",
        headers={
            "X-Tenant-Slug": disposable_tenant.slug,
            "Authorization": f"Bearer {token}",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["must_change_password"] is False


# ---------------------------------------------------------------------------
# Guard: normalise_username is what the login path uses
# ---------------------------------------------------------------------------

def test_normalise_username_would_collapse_pa_1():
    # documents the rule that caused the earlier failure; both must agree
    assert normalise_username("pa-1") == "pa1"
    assert normalise_username("pamcfirst") == "pamcfirst"

"""Branch endpoint tests (1C.5).

Because tests/tenancy/conftest.py is a sibling directory and pytest only
injects fixtures from ancestor conftest files, this module declares its own
`disposable_tenant` fixture (mirroring tests/test_permissions.py) and uses
the `api_client` fixture that tests/conftest.py provides.

Every test provisions its own tenant and drops it in a finally block, so no
stale tenant databases are left behind even on failure.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.organisation import Branch
from app.db.tenant.models.people import User
from app.db.tenant.models.platform import AuditLog
from app.db.tenant.session import get_tenant_engine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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

    slug = f"brnch-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Branch Endpoint Co",
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
def api(api_client: TestClient, disposable_tenant: _DisposableTenant):
    """Return (client, tenant) so tests can log in and drop the tenant."""
    return api_client, disposable_tenant


@pytest.fixture()
def db(disposable_tenant: _DisposableTenant) -> Iterator[Session]:
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _login(client: TestClient, slug: str, username: str, password: str) -> str:
    r = client.post(
        "/api/v1/auth/login",
        headers={"X-Tenant-Slug": slug},
        json={"identifier": username, "password": password},
    )
    assert r.status_code == 200, r.text
    token = r.json().get("access_token")
    assert token, r.text
    return token


def _auth(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Tenant-Slug": slug}


def _admin_token(client: TestClient, slug: str) -> str:
    """Log in the provisioned admin and rotate past must_change_password.

    The first admin has must_change_password=true and password_changed_at
    null. Change the password once, then log in again with the new one.
    """
    token = _login(client, slug, "admin", "TestPassword123!")
    r = client.post(
        "/api/v1/auth/change-password",
        headers={**_auth(token, slug), "Content-Type": "application/json"},
        json={
            "current_password": "TestPassword123!",
            "new_password": "PostChange123!",
        },
    )
    assert r.status_code in (200, 204), r.text
    return _login(client, slug, "admin", "PostChange123!")


def _mk_user(
    session: Session,
    *,
    username: str,
    role: str,
    password: str,
    employee_id: uuid.UUID | None = None,
) -> User:
    u = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=employee_id,
    )
    session.add(u)
    session.commit()
    return u


def _mk_branch(
    session: Session,
    *,
    name: str,
    code: str,
    is_active: bool = True,
) -> Branch:
    b = Branch(name=name, code=code, is_active=is_active, row_version=1)
    session.add(b)
    session.commit()
    return b


def _seed_admin(session: Session, code: str) -> Branch:
    return _mk_branch(session, name=f"Admin {code}", code=code)


# ---------------------------------------------------------------------------
# List and permission tests
# ---------------------------------------------------------------------------


def test_list_branches_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/branches", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_branches_payroll_admin_succeeds(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get("/api/v1/branches", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "next_cursor" in body


def test_list_branches_auditor_succeeds(api, db):
    client, tenant = api
    _mk_user(db, username="aud1", role="auditor", password="Auditor123!")
    token = _login(client, tenant.slug, "aud1", "Auditor123!")
    r = client.get("/api/v1/branches", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text


def test_create_branch_auditor_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="aud2", role="auditor", password="Auditor123!")
    token = _login(client, tenant.slug, "aud2", "Auditor123!")
    r = client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "X", "code": "X1"},
    )
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_branch_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "Head Office", "code": "HQ", "address": "1 Main St"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Head Office"
    assert body["code"] == "HQ"
    assert body["is_active"] is True
    assert body["row_version"] == 1


def test_create_branch_duplicate_code_rejected(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "HQ"},
    )
    r = client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "B", "code": "HQ"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_code"


def test_create_branch_duplicate_code_case_insensitive(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "HQ"},
    )
    r = client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "B", "code": "hq"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_code"


def test_create_branch_trims_code(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "  HQ  "},
    )
    assert r.status_code == 201, r.text
    assert r.json()["code"] == "HQ"


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_branch_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/branches",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "HQ"},
    ).json()
    r = client.get(
        f"/api/v1/branches/{created['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created["id"]


def test_get_branch_unknown_returns_404(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/branches/{uuid.uuid4()}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "record_not_found"

# END OF FILE
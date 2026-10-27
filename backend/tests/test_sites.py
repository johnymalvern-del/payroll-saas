"""Site endpoint tests (1C.6).

Declares its own `disposable_tenant` (tests/tenancy/conftest.py is a sibling
directory, not an ancestor) and uses `api_client` from tests/conftest.py.
Mirrors tests/test_branches.py, with site-specific cases:
  - branch_id must exist and be active at create and at PATCH-branch-change;
  - reactivating a site whose branch is inactive returns 409 branch_inactive;
  - DELETE with employees pointing at the site returns 409 site_in_use;
  - list filters branch_id, site_type, is_active.
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
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee, User
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

    slug = f"siteapi-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Site API Co",
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
    return api_client, disposable_tenant


@pytest.fixture()
def db(disposable_tenant: _DisposableTenant) -> Iterator[Session]:
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.close()


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


def _mk_branch(session: Session, *, name: str, code: str, is_active: bool = True) -> Branch:
    b = Branch(name=name, code=code, is_active=is_active, row_version=1)
    session.add(b)
    session.commit()
    return b


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


def _mk_employee(
    session: Session,
    code: str,
    *,
    site_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        site_id=site_id,
        branch_id=branch_id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
    )
    session.add(e)
    session.commit()
    return e


def test_list_sites_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/sites", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_sites_payroll_admin_succeeds(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get("/api/v1/sites", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    assert "items" in r.json() and "next_cursor" in r.json()


def test_list_sites_auditor_succeeds(api, db):
    client, tenant = api
    _mk_user(db, username="aud1", role="auditor", password="Auditor123!")
    token = _login(client, tenant.slug, "aud1", "Auditor123!")
    r = client.get("/api/v1/sites", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text


def test_create_site_auditor_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="aud2", role="auditor", password="Auditor123!")
    token = _login(client, tenant.slug, "aud2", "Auditor123!")
    r = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={
            "branch_id": str(uuid.uuid4()),
            "name": "X",
            "code": "X1",
        },
    )
    assert r.status_code == 403, r.text


def test_create_site_ok(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b = _mk_branch(db, name="HQ", code="HQ")
    r = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={
            "branch_id": str(b.id),
            "name": "Main",
            "code": "MAIN",
            "site_type": "site",
            "timezone": "Africa/Johannesburg",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["branch_id"] == str(b.id)
    assert body["code"] == "MAIN"
    assert body["is_active"] is True
    assert body["row_version"] == 1


def test_create_site_invalid_branch_missing(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={
            "branch_id": str(uuid.uuid4()),
            "name": "X",
            "code": "X1",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_branch"


def test_create_site_invalid_branch_inactive(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b = _mk_branch(db, name="Old", code="OLD", is_active=False)
    r = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={
            "branch_id": str(b.id),
            "name": "X",
            "code": "X1",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_branch"


def test_create_site_duplicate_code_case_insensitive(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b = _mk_branch(db, name="HQ", code="HQ")
    client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b.id), "name": "A", "code": "MAIN"},
    )
    r = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b.id), "name": "B", "code": "main"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_code"


def test_get_site_unknown_returns_404(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/sites/{uuid.uuid4()}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "record_not_found"


def test_patch_site_stale_row_version(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b = _mk_branch(db, name="HQ", code="HQ")
    created = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b.id), "name": "A", "code": "MAIN"},
    ).json()
    r = client.patch(
        f"/api/v1/sites/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": 99, "name": "B"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "record_changed"


def test_reactivate_site_with_inactive_branch_returns_409(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b = _mk_branch(db, name="HQ", code="HQ", is_active=True)
    created = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b.id), "name": "A", "code": "MAIN"},
    ).json()
    # Deactivate site
    r1 = client.patch(
        f"/api/v1/sites/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": created["row_version"], "is_active": False},
    )
    assert r1.status_code == 200, r1.text
    # Deactivate branch directly via DB (branch PATCH has its own guard)
    b2 = db.get(Branch, b.id)
    assert b2 is not None
    b2.is_active = False
    db.commit()
    # Try to reactivate the site
    r2 = client.patch(
        f"/api/v1/sites/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": r1.json()["row_version"], "is_active": True},
    )
    assert r2.status_code == 409, r2.text
    assert r2.json()["error"]["code"] == "branch_inactive"


def test_delete_site_with_employees_returns_409(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b = _mk_branch(db, name="HQ", code="HQ")
    created = client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b.id), "name": "A", "code": "MAIN"},
    ).json()
    _mk_employee(db, "E1", site_id=uuid.UUID(created["id"]), branch_id=b.id)
    r = client.delete(
        f"/api/v1/sites/{created['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "site_in_use"


def test_list_sites_filter_by_branch_and_site_type(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b1 = _mk_branch(db, name="B1", code="B1")
    b2 = _mk_branch(db, name="B2", code="B2")
    client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b1.id), "name": "A", "code": "S-A", "site_type": "store"},
    )
    client.post(
        "/api/v1/sites",
        headers=_auth(token, tenant.slug),
        json={"branch_id": str(b2.id), "name": "B", "code": "S-B", "site_type": "office"},
    )
    r = client.get(
        f"/api/v1/sites?branch_id={b1.id}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["branch_id"] == str(b1.id)

    r2 = client.get(
        "/api/v1/sites?site_type=office",
        headers=_auth(token, tenant.slug),
    )
    assert r2.status_code == 200, r2.text
    assert len(r2.json()["items"]) == 1
    assert r2.json()["items"][0]["site_type"] == "office"

# END OF FILE
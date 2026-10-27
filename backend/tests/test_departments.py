"""Department endpoint tests (1C.7).

Declares its own `disposable_tenant` (tests/tenancy/conftest.py is a sibling
directory, not an ancestor) and uses `api_client` from tests/conftest.py.
Mirrors tests/test_sites.py with the department-specific cases:
  - parent_id validation on create and on patch;
  - cycles: parent cannot be self, cannot be an ancestor;
  - deactivate refused with active children (department_has_active_children);
  - delete refused with children (department_has_children);
  - delete refused with employees (department_in_use);
  - list filters parent_id and is_active.
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
from app.db.tenant.models.organisation import Department
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

    slug = f"deptapi-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Dept API Co",
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


def _mk_user(
    session: Session,
    *,
    username: str,
    role: str,
    password: str,
) -> User:
    u = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=None,
    )
    session.add(u)
    session.commit()
    return u


def _mk_employee(
    session: Session,
    code: str,
    *,
    department_id: uuid.UUID | None = None,
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        department_id=department_id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
    )
    session.add(e)
    session.commit()
    return e


def test_list_departments_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/departments", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_departments_payroll_admin_succeeds(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get("/api/v1/departments", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    assert "items" in r.json() and "next_cursor" in r.json()


def test_create_department_auditor_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="aud2", role="auditor", password="Auditor123!")
    token = _login(client, tenant.slug, "aud2", "Auditor123!")
    r = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "X", "code": "X1"},
    )
    assert r.status_code == 403, r.text


def test_create_department_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Engineering", "code": "ENG"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Engineering"
    assert body["code"] == "ENG"
    assert body["parent_id"] is None
    assert body["is_active"] is True
    assert body["row_version"] == 1


def test_create_department_duplicate_code_case_insensitive(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "ENG"},
    )
    r = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "B", "code": "eng"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_code"


def test_create_department_invalid_parent_missing(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "ENG", "parent_id": str(uuid.uuid4())},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_parent"


def test_create_department_with_parent_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    parent = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Engineering", "code": "ENG"},
    ).json()
    r = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Backend", "code": "ENG-BE", "parent_id": parent["id"]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["parent_id"] == parent["id"]


def test_get_department_unknown_returns_404(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/departments/{uuid.uuid4()}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "record_not_found"


def test_patch_department_stale_row_version(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "ENG"},
    ).json()
    r = client.patch(
        f"/api/v1/departments/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": 99, "name": "B"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "record_changed"


def test_patch_department_parent_self_returns_400(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "ENG"},
    ).json()
    r = client.patch(
        f"/api/v1/departments/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": created["row_version"], "parent_id": created["id"]},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_parent"


def test_patch_department_parent_cycle_returns_400(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    a = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "A"},
    ).json()
    b = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "B", "code": "B", "parent_id": a["id"]},
    ).json()
    # Now make A a child of B: would create A -> B -> A.
    r = client.patch(
        f"/api/v1/departments/{a['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": a["row_version"], "parent_id": b["id"]},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_parent"


def test_deactivate_department_with_active_children_returns_409(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    parent = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Engineering", "code": "ENG"},
    ).json()
    client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Backend", "code": "ENG-BE", "parent_id": parent["id"]},
    )
    r = client.patch(
        f"/api/v1/departments/{parent['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": parent["row_version"], "is_active": False},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "department_has_active_children"


def test_delete_department_with_children_returns_409(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    parent = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Engineering", "code": "ENG"},
    ).json()
    client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "Backend", "code": "ENG-BE", "parent_id": parent["id"]},
    )
    r = client.delete(
        f"/api/v1/departments/{parent['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "department_has_children"


def test_delete_department_with_employees_returns_409(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "ENG"},
    ).json()
    _mk_employee(db, "E1", department_id=uuid.UUID(created["id"]))
    r = client.delete(
        f"/api/v1/departments/{created['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "department_in_use"


def test_list_departments_filter_by_parent(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    a = client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "A", "code": "A"},
    ).json()
    client.post(
        "/api/v1/departments",
        headers=_auth(token, tenant.slug),
        json={"name": "B", "code": "B", "parent_id": a["id"]},
    )
    r = client.get(
        f"/api/v1/departments?parent_id={a['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["parent_id"] == a["id"]

# END OF FILE
"""User endpoint tests (1C.9), part 1 of 2: list and create.

Declares its own `disposable_tenant` (tests/tenancy/conftest.py is a sibling
directory, not an ancestor) and uses `api_client` from tests/conftest.py.
The module is not in _REAL_LIMITER_MODULES, so the 1C.6.2 bypass applies and
repeated logins do not trip the per-IP rate limit.

Only payroll_admin has USER_MANAGE. Every endpoint in this module therefore
must be exercised by payroll_admin, and the "non-user_manage returns 403"
tests below confirm the permission gate.
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
from app.core.usernames import normalise_username
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

    slug = f"userapi-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="User API Co",
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
    employee_id: uuid.UUID | None = None,
) -> User:
    u = User(
        username=normalise_username(username),
        password_hash=hash_password(password),
        role=role,
        is_active=True,
        must_change_password=False,
        employee_id=employee_id,
        row_version=1,
    )
    session.add(u)
    session.commit()
    return u


def _mk_employee(session: Session, code: str) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(e)
    session.commit()
    return e


# ---------------------------------------------------------------------------
# List: auth and permission surface
# ---------------------------------------------------------------------------


def test_list_users_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/users", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_users_hr_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="hr-1", role="hr", password="HrUser12345!")
    token = _login(client, tenant.slug, "hr-1", "HrUser12345!")
    r = client.get("/api/v1/users", headers=_auth(token, tenant.slug))
    assert r.status_code == 403, r.text


def test_list_users_payroll_admin_succeeds(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get("/api/v1/users", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "next_cursor" in body
    assert body["total"] is None


def test_list_users_include_total(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get(
        "/api/v1/users?include_total=true",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] >= 1


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_user_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "EmployeeOne",
            "password": "EmployeePassword123!",
            "role": "employee",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "employeeone"  # normalised to lowercase
    assert body["role"] == "employee"
    assert body["is_active"] is True
    assert body["must_change_password"] is True
    assert body["row_version"] == 1


def test_create_user_duplicate_username(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "dupe", "password": "DupePassword123!", "role": "employee"},
    )
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "dupe", "password": "DupePassword123!", "role": "employee"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_username"


def test_create_user_duplicate_username_case_insensitive(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "Dupe", "password": "DupePassword123!", "role": "employee"},
    )
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "dupe", "password": "DupePassword123!", "role": "employee"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_username"


def test_create_user_invalid_role(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "nope", "password": "SomePassword123!", "role": "god"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_role"


def test_create_user_weak_password(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "weak", "password": "short", "role": "employee"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_password"


def test_create_user_with_employee_ok(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, "E-USR-1")
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "emp-user",
            "password": "EmployeePassword123!",
            "role": "employee",
            "employee_id": str(emp.id),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["employee_id"] == str(emp.id)


def test_create_user_duplicate_employee_active_user(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, "E-USR-2")
    client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "emp-user-a",
            "password": "EmployeePassword123!",
            "role": "employee",
            "employee_id": str(emp.id),
        },
    )
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "emp-user-b",
            "password": "EmployeePassword123!",
            "role": "employee",
            "employee_id": str(emp.id),
        },
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_employee_user"


def test_create_user_invalid_employee(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "emp-user-x",
            "password": "EmployeePassword123!",
            "role": "employee",
            "employee_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_employee"


# ---------------------------------------------------------------------------
# Patch: row_version, field_not_patchable, deactivation + family revocation
# ---------------------------------------------------------------------------


def test_patch_user_deactivate_revokes_families(api, db):
    from sqlalchemy import select as _select
    from app.models_auth_orm import RefreshTokenFamily

    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "deact", "password": "DeactPassword123!", "role": "employee"},
    ).json()

    # Log in as the new user - this creates a RefreshTokenFamily.
    _login(client, tenant.slug, "deact", "DeactPassword123!")

    r = client.patch(
        f"/api/v1/users/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": created["row_version"], "is_active": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False
    assert r.json()["row_version"] == created["row_version"] + 1

    families = list(
        db.scalars(
            _select(RefreshTokenFamily).where(
                RefreshTokenFamily.user_id == uuid.UUID(created["id"])
            )
        ).all()
    )
    assert len(families) >= 1
    for f in families:
        assert f.revoked_at is not None
        assert f.revoked_reason == "user_deactivated"


def test_patch_user_stale_row_version(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "stale", "password": "StalePassword123!", "role": "employee"},
    ).json()
    r = client.patch(
        f"/api/v1/users/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": 99, "is_active": False},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "record_changed"


def test_patch_user_field_not_patchable(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "fpatch", "password": "FpatchPassword123!", "role": "employee"},
    ).json()
    r = client.patch(
        f"/api/v1/users/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": created["row_version"], "role": "hr"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "field_not_patchable"


def test_patch_user_reactivate_conflict_with_other_active_user(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    emp = _mk_employee(db, "E-REACT")

    # Active user A for the employee.
    client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "react-a",
            "password": "ReactAPassword123!",
            "role": "employee",
            "employee_id": str(emp.id),
        },
    )
    # Inactive user B for the same employee (create allows is_active=False).
    user_b = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={
            "username": "react-b",
            "password": "ReactBPassword123!",
            "role": "employee",
            "employee_id": str(emp.id),
            "is_active": False,
        },
    ).json()

    r = client.patch(
        f"/api/v1/users/{user_b['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": user_b["row_version"], "is_active": True},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_employee_user"


def test_delete_user_returns_405(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "tod", "password": "TodPassword1234!", "role": "employee"},
    ).json()
    r = client.delete(
        f"/api/v1/users/{created['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 405, r.text
    assert r.json()["error"]["code"] == "method_not_allowed"


# ---------------------------------------------------------------------------
# User scopes (PUT replace-all, D3A)
# ---------------------------------------------------------------------------


def test_get_user_scopes_empty(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "noscopes", "password": "NoScopes12345678!", "role": "manager"},
    ).json()
    r = client.get(
        f"/api/v1/users/{created['id']}/scopes",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


def test_put_user_scopes_replaces(api, db):
    from app.db.tenant.models.organisation import Branch

    client, tenant = api
    token = _admin_token(client, tenant.slug)
    branch = Branch(name="ScopeB", code="B-SCOPE", is_active=True, row_version=1)
    db.add(branch)
    db.commit()

    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "scoped", "password": "ScopedPassword123!", "role": "manager"},
    ).json()

    payload = {"items": [{"scope_type": "branch", "scope_id": str(branch.id)}]}
    r = client.put(
        f"/api/v1/users/{created['id']}/scopes",
        headers=_auth(token, tenant.slug),
        json=payload,
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["scope_type"] == "branch"
    assert items[0]["scope_id"] == str(branch.id)

    # Replace with empty - old rows removed.
    r2 = client.put(
        f"/api/v1/users/{created['id']}/scopes",
        headers=_auth(token, tenant.slug),
        json={"items": []},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["items"] == []


def test_put_user_scopes_invalid_scope_type(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "badtype", "password": "BadTypePassword12!", "role": "manager"},
    ).json()
    r = client.put(
        f"/api/v1/users/{created['id']}/scopes",
        headers=_auth(token, tenant.slug),
        json={"items": [{"scope_type": "planet", "scope_id": str(uuid.uuid4())}]},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_scope"


def test_put_user_scopes_unknown_scope_id(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/users",
        headers=_auth(token, tenant.slug),
        json={"username": "badid", "password": "BadIdPassword1234!", "role": "manager"},
    ).json()
    r = client.put(
        f"/api/v1/users/{created['id']}/scopes",
        headers=_auth(token, tenant.slug),
        json={"items": [{"scope_type": "branch", "scope_id": str(uuid.uuid4())}]},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_scope"

# END OF FILE
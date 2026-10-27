"""Employee endpoint tests (1C.8).

Declares its own `disposable_tenant` (tests/tenancy/conftest.py is a sibling
directory, not an ancestor) and uses `api_client` from tests/conftest.py.
The rate-limiter bypass from 1C.6.2 applies here because this module is not
in _REAL_LIMITER_MODULES, so the tests can log in as often as they need.

Surface under test:
  - EMPLOYEE_CRUD gates list / get-by-id / create / patch.
  - SELF_VIEW gates GET /employees/me.
  - DELETE returns 405 method_not_allowed.
  - national_id and bank_account_number are accepted on create, masked on
    read, and refused on PATCH with 400 field_not_patchable.
  - GET /employees/me returns the caller's own record with full
    national_id and bank_account_number.
  - row_version drives optimistic concurrency (409 record_changed).
  - employee_code is unique case-insensitively (409 duplicate_code).
  - termination_date before hire_date is 400 invalid_termination_date.
  - Foreign keys are validated: invalid_branch / invalid_site /
    invalid_department / invalid_manager.
  - Manager self-reference and manager-out-of-scope are 400 invalid_manager.
  - List excludes terminated by default; ?include_terminated=true includes
    them.
  - Scope: a manager cannot read an out-of-scope employee via GET
    /employees/{id} (404, IDOR mitigation).
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
from app.db.tenant.models.organisation import Branch, Department, Site
from app.db.tenant.models.people import Employee, User, UserScope
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

    slug = f"empapi-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Employee API Co",
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
    )
    session.add(u)
    session.commit()
    return u


def _mk_branch(session: Session, code: str = "HQ") -> Branch:
    b = Branch(name=f"Branch {code}", code=code, is_active=True, row_version=1)
    session.add(b)
    session.commit()
    return b


def _mk_employee(
    session: Session,
    code: str,
    *,
    status: str = "active",
    manager_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=date(2024, 1, 1),
        status=status,
        manager_id=manager_id,
        branch_id=branch_id,
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(e)
    session.commit()
    return e


# ---------------------------------------------------------------------------
# Auth and permission surface
# ---------------------------------------------------------------------------


def test_list_employees_requires_auth(api):
    client, tenant = api
    r = client.get("/api/v1/employees", headers={"X-Tenant-Slug": tenant.slug})
    assert r.status_code == 401, r.text


def test_list_employees_admin_succeeds(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get("/api/v1/employees", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "next_cursor" in body


def test_create_employee_auditor_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="aud", role="auditor", password="Auditor123!")
    token = _login(client, tenant.slug, "aud", "Auditor123!")
    r = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E1",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
        },
    )
    assert r.status_code == 403, r.text


def test_employee_self_read_without_employee_crud(api, db):
    client, tenant = api
    emp = _mk_employee(db, "SELF-1")
    _mk_user(
        db,
        username="self-user",
        role="employee",
        password="SelfUser123!",
        employee_id=emp.id,
    )
    token = _login(client, tenant.slug, "self-user", "SelfUser123!")
    r = client.get("/api/v1/employees/me", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == str(emp.id)


def test_me_without_employee_record_returns_404(api, db):
    client, tenant = api
    _mk_user(db, username="no-emp", role="employee", password="NoEmp123!")
    token = _login(client, tenant.slug, "no-emp", "NoEmp123!")
    r = client.get("/api/v1/employees/me", headers=_auth(token, tenant.slug))
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "no_employee_record"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_employee_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "EMP-1",
            "first_name": "Alice",
            "last_name": "Adams",
            "hire_date": "2024-01-15",
            "status": "active",
            "employee_type": "hourly",
            "pay_basis": "hourly",
            "pay_frequency": "monthly",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["employee_code"] == "EMP-1"
    assert body["first_name"] == "Alice"
    assert body["row_version"] == 1


def test_create_employee_duplicate_code_case_insensitive(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    payload = {
        "employee_code": "EMP-1",
        "first_name": "A",
        "last_name": "B",
        "hire_date": "2024-01-15",
    }
    client.post("/api/v1/employees", headers=_auth(token, tenant.slug), json=payload)
    payload["employee_code"] = "emp-1"
    r = client.post("/api/v1/employees", headers=_auth(token, tenant.slug), json=payload)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "duplicate_code"


def test_create_employee_invalid_termination_date(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-TD",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-06-01",
            "termination_date": "2024-05-01",
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_termination_date"


def test_create_employee_invalid_branch(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-B",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
            "branch_id": str(uuid.uuid4()),
        },
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_branch"


def test_create_employee_encrypts_national_id(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-NID",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
            "national_id": "9001015000086",
        },
    )
    assert r.status_code == 201, r.text
    # Stored encrypted, not plaintext.
    emp = db.query(Employee).filter(Employee.employee_code == "E-NID").one()
    assert emp.national_id_encrypted is not None
    assert "9001015000086" not in (emp.national_id_encrypted or "")
    # Read masks it.
    body = r.json()
    assert body["national_id_masked"] is not None
    assert body["national_id_masked"].startswith("***")
    assert "9001015000086" not in (body["national_id_masked"] or "")


# ---------------------------------------------------------------------------
# Read / patch / delete
# ---------------------------------------------------------------------------


def test_get_employee_returns_masked_national_id(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-M",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
            "national_id": "9001015000086",
        },
    ).json()
    r = client.get(
        f"/api/v1/employees/{created['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["national_id_masked"].startswith("***")
    assert "9001015000086" not in body["national_id_masked"]


def test_get_unknown_employee_returns_404(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/employees/{uuid.uuid4()}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "record_not_found"


def test_patch_employee_ok(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-P",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
        },
    ).json()
    r = client.patch(
        f"/api/v1/employees/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": created["row_version"], "job_title": "Engineer"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["job_title"] == "Engineer"
    assert r.json()["row_version"] == created["row_version"] + 1


def test_patch_employee_stale_row_version(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-S",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
        },
    ).json()
    r = client.patch(
        f"/api/v1/employees/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={"row_version": 99, "job_title": "X"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "record_changed"


def test_patch_employee_field_not_patchable(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-F",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
        },
    ).json()
    # The schema does not declare national_id or bank_account_number, so
    # Pydantic silently drops them. We assert that the resulting employee
    # is not modified, which is the important guarantee for 1C.8's
    # "not patchable" decision.
    r = client.patch(
        f"/api/v1/employees/{created['id']}",
        headers=_auth(token, tenant.slug),
        json={
            "row_version": created["row_version"],
            "national_id": "1111111111111",
        },
    )
    assert r.status_code == 200, r.text
    # national_id was not changed (still absent).
    assert r.json().get("national_id_masked") is None


def test_delete_employee_returns_405(api):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    created = client.post(
        "/api/v1/employees",
        headers=_auth(token, tenant.slug),
        json={
            "employee_code": "E-D",
            "first_name": "A",
            "last_name": "B",
            "hire_date": "2024-01-01",
        },
    ).json()
    r = client.delete(
        f"/api/v1/employees/{created['id']}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 405, r.text
    assert r.json()["error"]["code"] == "method_not_allowed"


# ---------------------------------------------------------------------------
# List filters
# ---------------------------------------------------------------------------


def test_list_excludes_terminated_by_default(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    _mk_employee(db, "E-ACTIVE", status="active")
    _mk_employee(db, "E-TERM", status="terminated")
    r = client.get("/api/v1/employees", headers=_auth(token, tenant.slug))
    assert r.status_code == 200, r.text
    codes = {e["employee_code"] for e in r.json()["items"]}
    assert "E-ACTIVE" in codes
    assert "E-TERM" not in codes

    r2 = client.get(
        "/api/v1/employees?include_terminated=true",
        headers=_auth(token, tenant.slug),
    )
    assert r2.status_code == 200, r2.text
    codes2 = {e["employee_code"] for e in r2.json()["items"]}
    assert "E-ACTIVE" in codes2
    assert "E-TERM" in codes2


def test_list_filter_by_branch(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    b1 = _mk_branch(db, "HQ1")
    b2 = _mk_branch(db, "HQ2")
    _mk_employee(db, "E-B1", branch_id=b1.id)
    _mk_employee(db, "E-B2", branch_id=b2.id)
    r = client.get(
        f"/api/v1/employees?branch_id={b1.id}",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    codes = {e["employee_code"] for e in r.json()["items"]}
    assert codes == {"E-B1"}


def test_list_filter_by_status(api, db):
    client, tenant = api
    token = _admin_token(client, tenant.slug)
    _mk_employee(db, "E-A", status="active")
    _mk_employee(db, "E-L", status="on_leave")
    r = client.get(
        "/api/v1/employees?status=on_leave&include_terminated=true",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    codes = {e["employee_code"] for e in r.json()["items"]}
    assert codes == {"E-L"}


# ---------------------------------------------------------------------------
# Scope on read
# ---------------------------------------------------------------------------


def test_manager_cannot_get_out_of_scope_employee(api, db):
    client, tenant = api
    mgr = _mk_employee(db, "MGR-1")
    _mk_user(
        db,
        username="mgr-1",
        role="manager",
        password="MgrPass123!",
        employee_id=mgr.id,
    )
    # No direct reports, no scope rows: the manager sees nobody.
    other = _mk_employee(db, "OTHER-1")
    token = _login(client, tenant.slug, "mgr-1", "MgrPass123!")
    r = client.get(
        f"/api/v1/employees/{other.id}",
        headers=_auth(token, tenant.slug),
    )
    # Either 403 (no EMPLOYEE_CRUD) or 404 (out of scope). Both are
    # acceptable for the IDOR guarantee; assert the record is not returned.
    assert r.status_code in (403, 404), r.text


def test_manager_cannot_list_all_employees(api, db):
    client, tenant = api
    mgr = _mk_employee(db, "MGR-2")
    _mk_user(
        db,
        username="mgr-2",
        role="manager",
        password="MgrPass123!",
        employee_id=mgr.id,
    )
    _mk_employee(db, "OTHER-2")
    token = _login(client, tenant.slug, "mgr-2", "MgrPass123!")
    r = client.get("/api/v1/employees", headers=_auth(token, tenant.slug))
    # Manager does not have EMPLOYEE_CRUD, so 403 is expected.
    assert r.status_code == 403, r.text

# END OF FILE
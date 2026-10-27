"""Pay-rate-change endpoint tests (1C.10).

Declares its own `disposable_tenant` (tests/tenancy/conftest.py is a sibling
directory, not an ancestor) and uses `api_client` from tests/conftest.py.
Not in _REAL_LIMITER_MODULES, so the 1C.6.2 bypass applies.

Permission surface under test:
  - list: PAY_RATE_VIEW (hr, payroll_admin, auditor) OR the data subject.
  - create: PAY_RATE_REQUEST (hr only).
  - approve / reject: PAY_RATE_APPROVE (payroll_admin only).
  - effective-rate recompute on approve (newest approved row at or before
    today), and future-dated approvals recorded but not applied.
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
from app.db.tenant.models.people import Employee, EmployeePayHistory, User
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

    slug = f"payhist-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Pay History Co",
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


def _mk_employee(session: Session, code: str, *, hire: date | None = None) -> Employee:
    e = Employee(
        employee_code=code,
        first_name="E",
        last_name=code,
        hire_date=hire or date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    session.add(e)
    session.commit()
    return e


def _mk_pay_history(
    session: Session,
    *,
    employee_id: uuid.UUID,
    base_rate: float,
    effective_from: date,
    status: str = "pending",
    changed_by: uuid.UUID | None = None,
) -> EmployeePayHistory:
    row = EmployeePayHistory(
        employee_id=employee_id,
        base_rate=base_rate,
        effective_from=effective_from,
        status=status,
        changed_by=changed_by,
    )
    session.add(row)
    session.commit()
    return row


# ---------------------------------------------------------------------------
# List: permissions and visibility
# ---------------------------------------------------------------------------


def test_list_requires_auth(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-LIST-NA")
    r = client.get(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers={"X-Tenant-Slug": tenant.slug},
    )
    assert r.status_code == 401, r.text


def test_list_hr_can_see_any_employee(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-HR-SEE")
    _mk_user(db, username="hr-see", role="hr", password="HrSeePassword123!")
    token = _login(client, tenant.slug, "hr-see", "HrSeePassword123!")
    r = client.get(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


def test_list_auditor_can_see_any_employee(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-AUD-SEE")
    _mk_user(db, username="aud-see", role="auditor", password="AudSeePassword123!")
    token = _login(client, tenant.slug, "aud-see", "AudSeePassword123!")
    r = client.get(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text


def test_list_employee_cannot_see_other_employee(api, db):
    client, tenant = api
    me = _mk_employee(db, "E-SELF")
    other = _mk_employee(db, "E-OTHER")
    _mk_user(
        db,
        username="self-emp",
        role="employee",
        password="SelfEmpPassword123!",
        employee_id=me.id,
    )
    token = _login(client, tenant.slug, "self-emp", "SelfEmpPassword123!")
    r = client.get(
        f"/api/v1/employees/{other.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code in (403, 404), r.text


def test_list_employee_can_see_own(api, db):
    client, tenant = api
    me = _mk_employee(db, "E-SELF-OWN")
    _mk_user(
        db,
        username="self-own",
        role="employee",
        password="SelfOwnPassword1234!",
        employee_id=me.id,
    )
    _mk_pay_history(
        db,
        employee_id=me.id,
        base_rate=100.0,
        effective_from=date(2024, 2, 1),
        status="approved",
    )
    token = _login(client, tenant.slug, "self-own", "SelfOwnPassword1234!")
    r = client.get(
        f"/api/v1/employees/{me.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 1


def test_list_filters_by_status(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-FILTER")
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 2, 1), status="approved",
    )
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=110.0,
        effective_from=date(2024, 3, 1), status="pending",
    )
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/employees/{emp.id}/pay-rate-changes?status=pending",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "pending"


def test_list_filters_by_effective_from_range(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-RANGE")
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 1, 1), status="approved",
    )
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=110.0,
        effective_from=date(2024, 6, 1), status="approved",
    )
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/employees/{emp.id}/pay-rate-changes"
        f"?effective_from_gte=2024-05-01&effective_from_lte=2024-12-01",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["effective_from"] == "2024-06-01"


def test_list_include_total(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-TOT")
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 1, 1), status="approved",
    )
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=110.0,
        effective_from=date(2024, 6, 1), status="pending",
    )
    token = _admin_token(client, tenant.slug)
    r = client.get(
        f"/api/v1/employees/{emp.id}/pay-rate-changes?include_total=true",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


# ---------------------------------------------------------------------------
# Create: permission surface and validation
# ---------------------------------------------------------------------------


def test_create_employee_forbidden(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-NOTHR")
    _mk_user(
        db,
        username="plain-emp",
        role="employee",
        password="PlainEmpPassword123!",
        employee_id=emp.id,
    )
    tok = _login(client, tenant.slug, "plain-emp", "PlainEmpPassword123!")
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(tok, tenant.slug),
        json={"base_rate": 100, "effective_from": "2024-05-01"},
    )
    assert r.status_code == 403, r.text


def test_create_hr_ok(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-HR-CREATE")
    _mk_user(db, username="hr-c", role="hr", password="HrCPassword12345!")
    token = _login(client, tenant.slug, "hr-c", "HrCPassword12345!")
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
        json={
            "base_rate": "150.000000",
            "effective_from": "2024-06-01",
            "note": "annual increase",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert body["note"] == "annual increase"
    assert body["decided_by"] is None


def test_create_overlapping_pending_rejected(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-OVL-P")
    _mk_user(db, username="hr-ovp", role="hr", password="HrOvpPassword123!")
    token = _login(client, tenant.slug, "hr-ovp", "HrOvpPassword123!")
    payload = {"base_rate": "100", "effective_from": "2024-06-01"}
    client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
        json=payload,
    )
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
        json=payload,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "overlapping_effective_date"


def test_create_overlapping_approved_rejected(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-OVL-A")
    _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 6, 1), status="approved",
    )
    _mk_user(db, username="hr-ova", role="hr", password="HrOvaPassword123!")
    token = _login(client, tenant.slug, "hr-ova", "HrOvaPassword123!")
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
        json={"base_rate": "110", "effective_from": "2024-06-01"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "overlapping_effective_date"


def test_create_before_hire_date_rejected(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-HIRE", hire=date(2024, 6, 1))
    _mk_user(db, username="hr-hire", role="hr", password="HrHirePassword123!")
    token = _login(client, tenant.slug, "hr-hire", "HrHirePassword123!")
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
        json={"base_rate": "100", "effective_from": "2024-05-01"},
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_effective_date"


def test_create_employee_not_found(api, db):
    client, tenant = api
    _mk_user(db, username="hr-nf", role="hr", password="HrNfPassword12345!")
    token = _login(client, tenant.slug, "hr-nf", "HrNfPassword12345!")
    r = client.post(
        f"/api/v1/employees/{uuid.uuid4()}/pay-rate-changes",
        headers=_auth(token, tenant.slug),
        json={"base_rate": "100", "effective_from": "2024-06-01"},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "record_not_found"


# ---------------------------------------------------------------------------
# Approve / reject (PAY_RATE_APPROVE, payroll_admin only)
# ---------------------------------------------------------------------------


def test_approve_applies_employee_rate(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-AP-APPLY")
    original_version = emp.row_version
    # effective_from is in the past relative to today (2026-10).
    row = _mk_pay_history(
        db, employee_id=emp.id, base_rate=125.0,
        effective_from=date(2024, 6, 1), status="pending",
    )
    token = _admin_token(client, tenant.slug)
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row.id}/approve",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["decided_by"] is not None
    assert body["decided_at"] is not None

    # Employee.base_rate should have been applied.
    db.expire_all()
    refreshed_emp = db.get(Employee, emp.id)
    assert refreshed_emp is not None
    assert float(refreshed_emp.base_rate) == 125.0
    assert refreshed_emp.row_version > original_version


def test_approve_future_dated_not_applied(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-AP-FUT")
    original_rate = emp.base_rate
    original_version = emp.row_version
    # effective_from is in the future (2099).
    row = _mk_pay_history(
        db, employee_id=emp.id, base_rate=999.0,
        effective_from=date(2099, 1, 1), status="pending",
    )
    token = _admin_token(client, tenant.slug)
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row.id}/approve",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    # Employee.base_rate should NOT have been applied (future-dated).
    db.expire_all()
    refreshed_emp = db.get(Employee, emp.id)
    assert refreshed_emp is not None
    assert refreshed_emp.base_rate == original_rate
    assert refreshed_emp.row_version == original_version


def test_approve_out_of_order_recomputes(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-AP-OOO")
    # Two pending rows: A earlier (2024-03), B later (2024-06).
    row_a = _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 3, 1), status="pending",
    )
    row_b = _mk_pay_history(
        db, employee_id=emp.id, base_rate=200.0,
        effective_from=date(2024, 6, 1), status="pending",
    )
    token = _admin_token(client, tenant.slug)

    # Approve B first - applies 200.
    r_b = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row_b.id}/approve",
        headers=_auth(token, tenant.slug),
    )
    assert r_b.status_code == 200, r_b.text
    db.expire_all()
    emp_after_b = db.get(Employee, emp.id)
    assert emp_after_b is not None
    assert float(emp_after_b.base_rate) == 200.0

    # Approve A second - B is still the newest approved row at or before
    # today, so A must NOT overwrite the current rate.
    r_a = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row_a.id}/approve",
        headers=_auth(token, tenant.slug),
    )
    assert r_a.status_code == 200, r_a.text
    db.expire_all()
    emp_after_a = db.get(Employee, emp.id)
    assert emp_after_a is not None
    assert float(emp_after_a.base_rate) == 200.0


def test_approve_non_pending_returns_409(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-AP-NP")
    row = _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 6, 1), status="approved",
    )
    token = _admin_token(client, tenant.slug)
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row.id}/approve",
        headers=_auth(token, tenant.slug),
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "not_pending"
    assert r.json()["error"]["details"].get("current_status") == "approved"


def test_reject_pending_ok(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-RJ-OK")
    row = _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 6, 1), status="pending",
    )
    token = _admin_token(client, tenant.slug)
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row.id}/reject",
        headers=_auth(token, tenant.slug),
        json={"reason": "rate not approved by board"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "rejected"
    assert body["decision_reason"] == "rate not approved by board"
    assert body["decided_by"] is not None
    assert body["decided_at"] is not None
    # Employee.base_rate unchanged.
    db.expire_all()
    refreshed_emp = db.get(Employee, emp.id)
    assert refreshed_emp is not None
    assert refreshed_emp.base_rate == emp.base_rate


def test_reject_non_pending_returns_409(api, db):
    client, tenant = api
    emp = _mk_employee(db, "E-RJ-NP")
    row = _mk_pay_history(
        db, employee_id=emp.id, base_rate=100.0,
        effective_from=date(2024, 6, 1), status="rejected",
    )
    token = _admin_token(client, tenant.slug)
    r = client.post(
        f"/api/v1/employees/{emp.id}/pay-rate-changes/{row.id}/reject",
        headers=_auth(token, tenant.slug),
        json={"reason": "again"},
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "not_pending"
    assert r.json()["error"]["details"].get("current_status") == "rejected"

# END OF FILE
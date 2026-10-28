"""Employee import endpoint tests (1C.11).

Split across six scripts:
  5-i    - fixtures and login helpers
  5-ii   - data helpers and header/parse tests
  5-iii  - dry-run and token tests
  5-iv   - create path tests
  5-v    - update path tests
  6      - all-or-nothing, audit, scope, focused pytest

Declares its own `disposable_tenant` (tests/tenancy/conftest.py is a sibling
directory, not an ancestor) and uses `api_client` from tests/conftest.py.
Not in _REAL_LIMITER_MODULES, so the 1C.6.2 rate-limiter bypass applies.
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
from app.db.tenant.models.organisation import Branch
from app.db.tenant.models.people import (
    Employee,
    EmployeePayHistory,
    User,
    UserScope,
)
from app.db.tenant.models.platform import AuditLog
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

    slug = f"impt-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Import Test Co",
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


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _csv_bytes(header: list[str], rows: list[list[str]]) -> bytes:
    """Build a CSV file body for the import endpoint.

    Manual assembly (no csv module) so the tests can deliberately produce
    malformed shapes (wrong cell counts) and BOMs when needed.
    """
    import csv as _csv
    import io as _io

    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue().encode("utf-8")


def _post_import(
    client: TestClient,
    slug: str,
    token: str,
    body: bytes,
    *,
    filename: str = "employees.csv",
    dry_run_token: str | None = None,
):
    """Submit the multipart request.

    `token` is the bearer token. `dry_run_token` is the file-hash token from
    a prior dry run (None means this is the dry run).
    """
    data = {}
    if dry_run_token is not None:
        data["token"] = dry_run_token
    return client.post(
        "/api/v1/employees/import",
        headers=_auth(token, slug),
        files={"file": (filename, body, "text/csv")},
        data=data,
    )


def _hr_token(client: TestClient, db: Session, tenant: _DisposableTenant) -> str:
    _mk_user(db, username="hr-imp", role="hr", password="HrImpPassword123!")
    return _login(client, tenant.slug, "hr-imp", "HrImpPassword123!")


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


# ---------------------------------------------------------------------------
# Header / parse tests (400-level errors)
# ---------------------------------------------------------------------------


def test_import_requires_auth(api):
    client, tenant = api
    r = client.post(
        "/api/v1/employees/import",
        headers={"X-Tenant-Slug": tenant.slug},
        files={"file": ("x.csv", b"employee_code\n", "text/csv")},
    )
    assert r.status_code == 401, r.text


def test_import_employee_role_forbidden(api, db):
    client, tenant = api
    _mk_user(db, username="plain-imp", role="employee", password="PlainImpPassword123!")
    tok = _login(client, tenant.slug, "plain-imp", "PlainImpPassword123!")
    body = _csv_bytes(["employee_code"], [["X"]])
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 403, r.text


def test_import_empty_file(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = _post_import(client, tenant.slug, tok, b"")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "empty_file"


def test_import_binary_content_rejected(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    r = _post_import(client, tenant.slug, tok, b"\x00\x01\x02PK\x03\x04binary")
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_file_type"


def test_import_invalid_encoding(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    bad = b"employee_code\n" + b"\xff\xfe"
    r = _post_import(client, tenant.slug, tok, bad)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "invalid_encoding"


def test_import_unknown_column(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(["employee_code", "mystery_col"], [["X", "Y"]])
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "unknown_column"


def test_import_duplicate_column(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "first_name"],
        [["X", "A", "B"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "duplicate_column"


def test_import_bom_is_tolerated(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = b"\xef\xbb\xbf" + _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["BOM-1", "A", "B", "2024-01-01"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    assert r.json()["valid_rows"] == 1
    assert r.json()["invalid_rows"] == 0


def test_import_empty_body_with_header_only(api):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = b"employee_code,first_name,last_name,hire_date\n"
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    body_json = r.json()
    assert body_json["total_rows"] == 0
    assert body_json["valid_rows"] == 0
    assert body_json["created"] == 0


# ---------------------------------------------------------------------------
# Dry run and token (D3 override)
# ---------------------------------------------------------------------------


def test_dry_run_writes_nothing(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["DR-1", "A", "B", "2024-01-01"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["dry_run"] is True
    assert payload["created"] == 1
    assert payload["token"]
    assert len(payload["token"]) == 64  # sha256 hex

    # No employees committed.
    assert db.query(Employee).filter(Employee.employee_code == "DR-1").first() is None


def test_apply_without_token_is_a_dry_run(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["DR-2", "A", "B", "2024-01-01"]],
    )
    # No token form field.
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"] is True
    assert db.query(Employee).filter(Employee.employee_code == "DR-2").first() is None


def test_apply_with_correct_token_commits(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["T-1", "A", "B", "2024-01-01"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    file_token = dry.json()["token"]

    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=file_token
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["dry_run"] is False
    assert payload["created"] == 1
    assert db.query(Employee).filter(Employee.employee_code == "T-1").first() is not None


def test_apply_with_wrong_token_is_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["W-1", "A", "B", "2024-01-01"]],
    )
    r = _post_import(
        client, tenant.slug, tok, body,
        dry_run_token="0" * 64,
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "file_changed_since_dry_run"
    assert db.query(Employee).filter(Employee.employee_code == "W-1").first() is None


def test_apply_with_token_from_different_file_is_409(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    file_a = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["A-1", "A", "B", "2024-01-01"]],
    )
    file_b = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["B-1", "A", "B", "2024-01-01"]],
    )
    dry = _post_import(client, tenant.slug, tok, file_a)
    assert dry.status_code == 200, dry.text
    token_a = dry.json()["token"]

    applied = _post_import(
        client, tenant.slug, tok, file_b, dry_run_token=token_a
    )
    assert applied.status_code == 409, applied.text
    assert applied.json()["error"]["code"] == "file_changed_since_dry_run"
    assert db.query(Employee).filter(Employee.employee_code == "B-1").first() is None
    assert db.query(Employee).filter(Employee.employee_code == "A-1").first() is None


# ---------------------------------------------------------------------------
# Create path: opening rate, HR review flag, base_rate rules (D7 override)
# ---------------------------------------------------------------------------


def _mk_existing_employee(
    db: Session,
    code: str,
    *,
    base_rate: float | None = None,
    first_name: str = "Old",
    hire: date = date(2024, 1, 1),
) -> Employee:
    e = Employee(
        employee_code=code,
        first_name=first_name,
        last_name="Existing",
        hire_date=hire,
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        base_rate=base_rate,
        row_version=1,
    )
    db.add(e)
    db.commit()
    return e


def test_import_creates_opening_rate_hr(api, db):
    client, tenant = api
    _mk_user(db, username="hr-or", role="hr", password="HrOrPassword123!")
    tok = _login(client, tenant.slug, "hr-or", "HrOrPassword123!")
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date", "base_rate", "effective_from"],
        [["OR-1", "A", "B", "2024-01-01", "150.00", "2024-01-15"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    file_token = dry.json()["token"]

    applied = _post_import(client, tenant.slug, tok, body, dry_run_token=file_token)
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["created"] == 1
    assert payload["opening_rates_loaded"] == 1
    assert payload["opening_rates_require_payroll_admin_review"] is True
    assert len(payload["opening_rates"]) == 1
    assert float(payload["opening_rates"][0]["base_rate"]) == 150.0
    assert payload["opening_rates"][0]["effective_from"] == "2024-01-15"

    emp = db.query(Employee).filter(Employee.employee_code == "OR-1").first()
    assert emp is not None
    assert float(emp.base_rate) == 150.0
    rows = db.query(EmployeePayHistory).filter(
        EmployeePayHistory.employee_id == emp.id
    ).all()
    assert len(rows) == 1
    assert rows[0].source == "import"
    assert rows[0].status == "approved"
    assert rows[0].decided_by is not None
    assert rows[0].approved_by is not None
    assert rows[0].changed_by is not None
    assert rows[0].decided_at is not None
    assert rows[0].effective_from == date(2024, 1, 15)


def test_import_creates_opening_rate_payroll_admin(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date", "base_rate", "effective_from"],
        [["OR-2", "A", "B", "2024-01-01", "150.00", "2024-01-15"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["created"] == 1
    assert payload["opening_rates_loaded"] == 1
    assert payload["opening_rates_require_payroll_admin_review"] is False


def test_import_base_rate_without_effective_from(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date", "base_rate"],
        [["NE-1", "A", "B", "2024-01-01", "100.00"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    assert any(
        e["code"] == "opening_rate_effective_from_required"
        for e in payload["errors"]
    )
    assert db.query(Employee).filter(Employee.employee_code == "NE-1").first() is None


def test_import_same_rate_on_update_is_noop(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "SR-1", base_rate=100.0)
    body = _csv_bytes(
        ["employee_code", "base_rate"],
        [["SR-1", "100.0"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    payload = dry.json()
    assert payload["valid_rows"] == 1
    assert payload["invalid_rows"] == 0

    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    applied_payload = applied.json()
    assert applied_payload["valid_rows"] == 1
    assert applied_payload["created"] == 0
    assert applied_payload["updated"] == 0  # nothing to change

    emp = db.query(Employee).filter(Employee.employee_code == "SR-1").first()
    assert float(emp.base_rate) == 100.0
    rows = db.query(EmployeePayHistory).filter(
        EmployeePayHistory.employee_id == emp.id
    ).all()
    assert len(rows) == 0


def test_import_different_rate_on_update_rejected(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "DR-1", base_rate=100.0)
    body = _csv_bytes(
        ["employee_code", "base_rate"],
        [["DR-1", "150.0"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    assert any(
        e["code"] == "rate_change_requires_approval" for e in payload["errors"]
    )
    assert payload["errors"][0]["column"] == "base_rate"

    # Nothing changed.
    emp = db.query(Employee).filter(Employee.employee_code == "DR-1").first()
    assert float(emp.base_rate) == 100.0
    rows = db.query(EmployeePayHistory).filter(
        EmployeePayHistory.employee_id == emp.id
    ).all()
    assert len(rows) == 0


# ---------------------------------------------------------------------------
# Create path (basic): no base_rate, multiple rows, invalid field
# ---------------------------------------------------------------------------


def test_import_creates_simple_employee(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date", "job_title"],
        [["SC-1", "Alice", "Adams", "2024-02-01", "Engineer"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["created"] == 1
    assert payload["updated"] == 0
    assert payload["opening_rates_loaded"] == 0
    assert payload["opening_rates"] == []

    emp = db.query(Employee).filter(Employee.employee_code == "SC-1").first()
    assert emp is not None
    assert emp.first_name == "Alice"
    assert emp.job_title == "Engineer"
    assert emp.base_rate is None
    rows = db.query(EmployeePayHistory).filter(
        EmployeePayHistory.employee_id == emp.id
    ).all()
    assert rows == []


def test_import_creates_multiple_employees(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [
            ["MC-1", "A", "A", "2024-01-01"],
            ["MC-2", "B", "B", "2024-01-02"],
            ["MC-3", "C", "C", "2024-01-03"],
        ],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created"] == 3
    assert db.query(Employee).filter(Employee.employee_code == "MC-1").first() is not None
    assert db.query(Employee).filter(Employee.employee_code == "MC-2").first() is not None
    assert db.query(Employee).filter(Employee.employee_code == "MC-3").first() is not None


def test_import_invalid_field_value_rejected(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["BAD-1", "A", "B", "not-a-date"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    assert any(e["code"] == "invalid_field_value" for e in payload["errors"])
    assert db.query(Employee).filter(Employee.employee_code == "BAD-1").first() is None


def test_import_unknown_code_with_all_create_fields_becomes_create(api, db):
    """An update-shaped row whose employee_code is not in the database
    becomes a create, provided all the create-required fields are present.
    The import is upsert-by-code (D2A)."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["UPS-1", "Fresh", "Hire", "2024-01-01"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["created"] == 1
    assert db.query(Employee).filter(Employee.employee_code == "UPS-1").first() is not None


# ---------------------------------------------------------------------------
# Update path
# ---------------------------------------------------------------------------


def test_import_updates_existing_employee_fields(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "UP-1", first_name="Old")
    body = _csv_bytes(
        ["employee_code", "first_name", "job_title"],
        [["UP-1", "New", "Manager"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    payload = applied.json()
    assert payload["created"] == 0
    assert payload["updated"] == 1
    emp = db.query(Employee).filter(Employee.employee_code == "UP-1").first()
    assert emp is not None
    assert emp.first_name == "New"
    assert emp.job_title == "Manager"


def test_import_update_with_no_fields_is_noop(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "NO-1", first_name="Same")
    body = _csv_bytes(["employee_code"], [["NO-1"]])
    dry = _post_import(client, tenant.slug, tok, body)
    assert dry.status_code == 200, dry.text
    payload = dry.json()
    assert payload["valid_rows"] == 1
    assert payload["invalid_rows"] == 0

    applied = _post_import(
        client, tenant.slug, tok, body, dry_run_token=dry.json()["token"]
    )
    assert applied.status_code == 200, applied.text
    p2 = applied.json()
    assert p2["valid_rows"] == 1
    assert p2["created"] == 0
    assert p2["updated"] == 0


def test_import_update_with_national_id_forbidden(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "NI-1", first_name="Same")
    body = _csv_bytes(
        ["employee_code", "national_id"],
        [["NI-1", "9001015000086"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    assert any(
        e["code"] == "field_not_updatable_via_import" for e in payload["errors"]
    )
    emp = db.query(Employee).filter(Employee.employee_code == "NI-1").first()
    assert emp.national_id_encrypted is None


def test_import_update_missing_required_field_when_new(api, db):
    """A row that is neither a valid create (missing required create fields)
    nor a valid update (no such employee_code) must be rejected with the
    missing fields named."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name"],
        [["MISS-1", "OnlyFirst"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    codes = {e["code"] for e in payload["errors"]}
    assert "missing_last_name" in codes
    assert "missing_hire_date" in codes
    assert db.query(Employee).filter(Employee.employee_code == "MISS-1").first() is None


# ---------------------------------------------------------------------------
# All-or-nothing (D4A)
# ---------------------------------------------------------------------------


def test_import_all_or_nothing(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [
            ["AON-OK", "Valid", "Row", "2024-01-01"],
            ["AON-BAD", "Bad", "Row", "not-a-date"],
        ],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["total_rows"] == 2
    assert payload["valid_rows"] == 1
    assert payload["invalid_rows"] == 1
    assert payload["created"] == 0
    assert payload["updated"] == 0
    # Neither row was applied.
    assert db.query(Employee).filter(Employee.employee_code == "AON-OK").first() is None
    assert db.query(Employee).filter(Employee.employee_code == "AON-BAD").first() is None


def test_import_apply_rollback_keeps_existing_employees(api, db):
    """A failed import must not modify existing employees either."""
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "EXIST-1", first_name="Before")
    body = _csv_bytes(
        ["employee_code", "first_name", "hire_date"],
        [
            ["EXIST-1", "After", "2024-01-01"],  # update, valid
            ["NEW-BAD", "", "not-a-date"],       # create, invalid
        ],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    emp = db.query(Employee).filter(Employee.employee_code == "EXIST-1").first()
    assert emp is not None
    assert emp.first_name == "Before"


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


_IMPORT_ACTIONS = (
    "employee.import",
    "employee.import_update",
    "pay_history.import",
    "employee_import.apply",
)


def _import_audit_rows(db: Session) -> list[AuditLog]:
    return (
        db.query(AuditLog)
        .filter(AuditLog.action.in_(_IMPORT_ACTIONS))
        .order_by(AuditLog.occurred_at.asc())
        .all()
    )


def test_import_audit_per_create(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [
            ["AU-1", "A", "A", "2024-01-01"],
            ["AU-2", "B", "B", "2024-01-02"],
        ],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    _post_import(client, tenant.slug, tok, body, dry_run_token=dry.json()["token"])

    rows = _import_audit_rows(db)
    actions = [r.action for r in rows]
    assert actions.count("employee.import") == 2
    assert actions.count("employee_import.apply") == 1
    # The batch row is last and carries the sha256.
    batch = [r for r in rows if r.action == "employee_import.apply"][0]
    assert batch.new_value is not None
    assert len(batch.new_value["sha256"]) == 64
    assert batch.new_value["filename"] == "employees.csv"
    assert batch.new_value["created"] == 2
    assert batch.new_value["updated"] == 0


def test_import_audit_opening_rate(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date", "base_rate", "effective_from"],
        [["AU-R", "A", "B", "2024-01-01", "100.0", "2024-01-15"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    _post_import(client, tenant.slug, tok, body, dry_run_token=dry.json()["token"])

    rows = _import_audit_rows(db)
    actions = [r.action for r in rows]
    assert actions.count("pay_history.import") == 1
    assert actions.count("employee.import") == 1
    ph = [r for r in rows if r.action == "pay_history.import"][0]
    assert ph.new_value is not None
    assert ph.new_value["source"] == "import"
    assert ph.new_value["effective_from"] == "2024-01-15"


def test_import_audit_update(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    _mk_existing_employee(db, "AU-U", first_name="Old")
    body = _csv_bytes(
        ["employee_code", "first_name"],
        [["AU-U", "New"]],
    )
    dry = _post_import(client, tenant.slug, tok, body)
    _post_import(client, tenant.slug, tok, body, dry_run_token=dry.json()["token"])

    rows = _import_audit_rows(db)
    actions = [r.action for r in rows]
    assert actions.count("employee.import_update") == 1
    upd = [r for r in rows if r.action == "employee.import_update"][0]
    assert upd.old_value is not None
    assert upd.old_value["first_name"] == "Old"
    assert upd.new_value["first_name"] == "New"


def test_import_dry_run_writes_no_audit(api, db):
    client, tenant = api
    tok = _admin_token(client, tenant.slug)
    before = len(_import_audit_rows(db))
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date"],
        [["DR-A", "A", "B", "2024-01-01"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    assert r.status_code == 200, r.text
    assert r.json()["dry_run"] is True
    after = len(_import_audit_rows(db))
    assert after == before


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _mk_branch(db: Session, code: str) -> Branch:
    b = Branch(name=f"Branch {code}", code=code, is_active=True, row_version=1)
    db.add(b)
    db.commit()
    return b


def test_import_create_out_of_scope_is_409(api, db):
    client, tenant = api
    # Two branches; HR has scope for one only.
    b_in = _mk_branch(db, "IN-1")
    b_out = _mk_branch(db, "OUT-1")
    hr_user = _mk_user(
        db, username="hr-scope", role="hr", password="HrScopePassword123!"
    )
    db.add(UserScope(user_id=hr_user.id, scope_type="branch", scope_id=b_in.id))
    db.commit()

    tok = _login(client, tenant.slug, "hr-scope", "HrScopePassword123!")
    body = _csv_bytes(
        ["employee_code", "first_name", "last_name", "hire_date", "branch_id"],
        [["OOS-1", "A", "B", "2024-01-01", str(b_out.id)]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    # Create-path scope check fires at apply time -> 409 batch failure.
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "out_of_scope"
    assert db.query(Employee).filter(Employee.employee_code == "OOS-1").first() is None


def test_import_update_out_of_scope_reported_as_row_error(api, db):
    client, tenant = api
    b_in = _mk_branch(db, "IN-2")
    b_out = _mk_branch(db, "OUT-2")
    hr_user = _mk_user(
        db, username="hr-scope2", role="hr", password="HrScopePassword234!"
    )
    db.add(UserScope(user_id=hr_user.id, scope_type="branch", scope_id=b_in.id))
    db.commit()

    # Existing employee in the out-of-scope branch.
    victim = _mk_existing_employee(db, "OOU-1", first_name="Old")
    victim.branch_id = b_out.id
    db.commit()

    tok = _login(client, tenant.slug, "hr-scope2", "HrScopePassword234!")
    body = _csv_bytes(
        ["employee_code", "first_name"],
        [["OOU-1", "New"]],
    )
    r = _post_import(client, tenant.slug, tok, body)
    # Update-path scope check runs in _validate_row -> row error.
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["invalid_rows"] == 1
    assert any(e["code"] == "out_of_scope" for e in payload["errors"])
    emp = db.query(Employee).filter(Employee.employee_code == "OOU-1").first()
    assert emp.first_name == "Old"

# END OF FILE
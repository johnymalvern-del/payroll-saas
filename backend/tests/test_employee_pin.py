"""Attendance PIN tests (non-biometric fallback, policy section 4).

Two halves:

  * endpoint tests, called directly -- they exercise the credential lifecycle
    (set, clear, unlock) without an HTTP client, because the behaviour under
    test is state transitions, not routing
  * punch tests over HTTP -- the PIN path is only meaningful end to end, and
    the lockout counter, idempotent replay and punch rejection all involve the
    real request pipeline

client_punch_id must differ between two punch attempts in the same test.
_handle_idempotent runs before PIN verification, so reusing an id would return
the first result and skip verification -- exactly what it should do for a real
retry, and exactly wrong for a test that wants to attempt a second guess.

The wrong-PIN counter tests share one employee deliberately: the counter lives
on the employee row, so separate employees would each start at zero and prove
nothing about lockout.
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.device_auth import hash_device_key
from app.api.v1.employee_pin import clear_pin, get_pin_status, set_pin, unlock_pin
from app.api.v1.employee_pin_schemas import PinSetIn
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Branch, Site
from app.db.tenant.models.people import Employee, User
from app.db.tenant.session import get_tenant_engine

PIN = "481920"
WRONG_PIN = "000000"


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

    slug = f"pin-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Pin Test Co",
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
            row = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if row is not None:
                session.delete(row)


@pytest.fixture()
def db(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    s = Session(engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def user(db):
    """A real User row -- assert_in_scope and the audit action both need one."""
    u = User(
        username=f"hr-{uuid.uuid4().hex[:8]}",
        password_hash="x",
        role="hr",
        is_active=True,
        must_change_password=False,
    )
    db.add(u)
    db.commit()
    return u


def _mk_employee(db, code=None):
    emp = Employee(
        employee_code=code or f"E-{uuid.uuid4().hex[:6]}",
        first_name="A",
        last_name="L",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        row_version=1,
    )
    db.add(emp)
    db.commit()
    return emp


def _set_pin(db, employee, user, pin=PIN):
    return set_pin(
        employee_id=employee.id, payload=PinSetIn(pin=pin), db=db, user=user
    )


# ---------------------------------------------------------------------------
# Credential lifecycle
# ---------------------------------------------------------------------------


def test_set_pin_stores_a_hash_not_the_pin(db, user):
    employee = _mk_employee(db)
    _set_pin(db, employee, user)

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_hash is not None
    assert PIN not in row.pin_hash, "the PIN must not be recoverable from storage"
    assert row.pin_hash.startswith("$argon2"), "expected an argon2 hash"
    assert row.pin_set_at is not None


def test_set_pin_rejects_four_digits(user):
    with pytest.raises(Exception):
        PinSetIn(pin="1234")


def test_set_pin_rejects_non_digits(user):
    with pytest.raises(Exception):
        PinSetIn(pin="12a456")


def test_set_pin_accepts_exactly_six_digits(user):
    payload = PinSetIn(pin="481920")
    assert payload.pin.get_secret_value() == "481920"


def test_set_pin_twice_replaces_and_clears_lockout(db, user):
    employee = _mk_employee(db)
    _set_pin(db, employee, user)

    # Simulate a lockout, then reset.
    db.expire_all()
    row = db.get(Employee, employee.id)
    row.pin_failed_attempts = 5
    row.pin_locked_until = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.commit()

    out = _set_pin(db, employee, user, pin="999999")

    assert out.locked is False
    assert out.failed_attempts == 0

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_failed_attempts == 0
    assert row.pin_locked_until is None


def test_clear_pin_removes_it(db, user):
    employee = _mk_employee(db)
    _set_pin(db, employee, user)

    clear_pin(employee_id=employee.id, db=db, user=user)

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_hash is None
    assert row.pin_set_at is None


def test_clear_pin_without_one_is_409(db, user):
    employee = _mk_employee(db)
    with pytest.raises(AppError) as exc:
        clear_pin(employee_id=employee.id, db=db, user=user)
    assert exc.value.status_code == 409


def test_unlock_clears_lockout_but_keeps_the_pin(db, user):
    employee = _mk_employee(db)
    _set_pin(db, employee, user)

    db.expire_all()
    row = db.get(Employee, employee.id)
    original_hash = row.pin_hash
    row.pin_failed_attempts = 5
    row.pin_locked_until = datetime(2099, 1, 1, tzinfo=timezone.utc)
    db.commit()

    out = unlock_pin(employee_id=employee.id, db=db, user=user)

    assert out.locked is False
    assert out.failed_attempts == 0
    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_hash == original_hash, "unlock must not change the credential"
    assert row.pin_locked_until is None


def test_status_reports_set_without_revealing_anything(db, user):
    employee = _mk_employee(db)
    _set_pin(db, employee, user)

    out = get_pin_status(employee_id=employee.id, db=db, user=user)

    assert out.pin_set is True
    assert out.pin_set_at is not None
    assert out.locked is False
    assert not hasattr(out, "pin_hash"), "status must not expose the hash"


# ---------------------------------------------------------------------------
# Punch verification (HTTP)
# ---------------------------------------------------------------------------


def _mk_site(db, name="S"):
    branch = Branch(
        name=f"B-{uuid.uuid4().hex[:6]}",
        code=f"B-{uuid.uuid4().hex[:6]}",
        is_active=True,
        row_version=1,
    )
    db.add(branch)
    db.commit()
    site = Site(
        branch_id=branch.id,
        name=name,
        code=f"S-{uuid.uuid4().hex[:6]}",
        site_type="site",
        timezone="Africa/Johannesburg",
        is_active=True,
        row_version=1,
    )
    db.add(site)
    db.commit()
    return site


def _mk_device(db, site_id):
    raw = secrets.token_hex(32)
    device = Device(
        site_id=site_id,
        name=f"Dev-{uuid.uuid4().hex[:6]}",
        device_type="usb_fingerprint",
        api_key_hash=hash_device_key(raw),
        status="active",
        # Deliberately False: a PIN punch must work even where code-only is
        # forbidden. The fallback cannot depend on a device flag.
        allows_code_only=False,
        require_photo_for_code=True,
        pending_punch_count=0,
        row_version=1,
    )
    db.add(device)
    db.commit()
    return device, raw


def _payload(employee_id, **overrides):
    now = datetime.now(timezone.utc)
    body = {
        "client_punch_id": str(uuid.uuid4()),
        "employee_id": str(employee_id),
        "device_time": now.isoformat(),
        "method": "pin",
        "raw_payload": {},
    }
    body.update(overrides)
    return body


def _post(client, slug, device_key, body):
    return client.post(
        "/api/v1/punches",
        headers={"X-Tenant-Slug": slug, "X-Device-Key": device_key},
        json=body,
    )


@pytest.fixture()
def punch_setup(api_client, db, disposable_tenant, user):
    site = _mk_site(db)
    _device, raw = _mk_device(db, site.id)
    employee = _mk_employee(db)
    _set_pin(db, employee, user)
    return api_client, disposable_tenant, raw, employee


def test_punch_with_correct_pin_is_accepted(punch_setup):
    client, tenant, raw, employee = punch_setup
    r = _post(client, tenant.slug, raw, _payload(employee.id, pin=PIN))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "accepted"
    assert body["method"] == "pin"


def test_punch_with_wrong_pin_is_rejected(punch_setup):
    client, tenant, raw, employee = punch_setup
    r = _post(client, tenant.slug, raw, _payload(employee.id, pin=WRONG_PIN))
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "pin_incorrect"


def test_wrong_pin_increments_the_counter(punch_setup, db):
    client, tenant, raw, employee = punch_setup
    _post(client, tenant.slug, raw, _payload(employee.id, pin=WRONG_PIN))

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_failed_attempts == 1


def test_pin_locks_after_five_failures(punch_setup, db):
    client, tenant, raw, employee = punch_setup
    for _ in range(5):
        _post(client, tenant.slug, raw, _payload(employee.id, pin=WRONG_PIN))

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_locked_until is not None, "lockout must engage at five"

    # A sixth attempt is refused as locked, not as incorrect.
    r = _post(client, tenant.slug, raw, _payload(employee.id, pin=PIN))
    assert r.status_code == 423, r.text
    assert r.json()["error"]["code"] == "pin_locked"


def test_successful_punch_resets_the_counter(punch_setup, db):
    client, tenant, raw, employee = punch_setup
    _post(client, tenant.slug, raw, _payload(employee.id, pin=WRONG_PIN))
    _post(client, tenant.slug, raw, _payload(employee.id, pin=PIN))

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_failed_attempts == 0


def test_missing_pin_field_is_400_not_a_counted_attempt(punch_setup, db):
    """A terminal that omits the field has not made a guess.

    Counting it would let one buggy client lock out every employee in the
    company.
    """
    client, tenant, raw, employee = punch_setup
    r = _post(client, tenant.slug, raw, _payload(employee.id))
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "pin_required"

    db.expire_all()
    row = db.get(Employee, employee.id)
    assert row.pin_failed_attempts == 0


def test_employee_without_a_pin_cannot_use_the_fallback(punch_setup, db):
    client, tenant, raw, employee = punch_setup
    other = _mk_employee(db)

    r = _post(client, tenant.slug, raw, _payload(other.id, pin=PIN))
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == "pin_not_set"


def test_pin_punch_is_not_flagged_as_an_exception(punch_setup):
    """The fallback is a right, not a suspicious event.

    If a PIN punch ever carries a flag that maps to an exception type, the
    employee who chose the non-biometric path gets queued for review -- the
    exact detriment section 4 forbids.
    """
    client, tenant, raw, employee = punch_setup
    r = _post(client, tenant.slug, raw, _payload(employee.id, pin=PIN))
    assert r.status_code == 201, r.text
    assert r.json()["flags"] == []

# END OF FILE
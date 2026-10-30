"""Import-field helpers (Chapter 4, Bundle 004a-iv-c)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine
from app.services.payroll_import_fields import (
    IMPORT_FIELDS,
    apply_import_row_fields,
    validate_import_row_fields,
)


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
        _drop_tenant_database, _tenant_db_name, provision_tenant,
    )
    slug = f"imp-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Import Test",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug, tenant_db_name=result.tenant_db_name,
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
def tenant_session(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    session = Session(engine)
    try:
        yield session, engine
    finally:
        session.close()
        engine.dispose()


def _mk_emp(session):
    code = f"I-{uuid.uuid4().hex[:6]}"
    emp = Employee(
        employee_code=code, first_name="A", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
        medical_scheme_members=0, uif_exempt=False,
    )
    session.add(emp)
    session.commit()
    return emp


def test_import_fields_names():
    assert set(IMPORT_FIELDS) == {
        "contracted_weekly_hours", "medical_scheme_members", "uif_exempt",
    }


def test_validate_clean_row():
    row = {
        "contracted_weekly_hours": 40,
        "medical_scheme_members": 2,
        "uif_exempt": False,
    }
    assert validate_import_row_fields(row) == []


def test_validate_rejects_bad_hours():
    errors = validate_import_row_fields({"contracted_weekly_hours": 200})
    assert errors and "out of range" in errors[0].lower()


def test_validate_rejects_negative_members():
    errors = validate_import_row_fields({"medical_scheme_members": -1})
    assert errors and "negative" in errors[0].lower()


def test_apply_writes_all_three(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    wrote = apply_import_row_fields(emp, {
        "contracted_weekly_hours": 40,
        "medical_scheme_members": 3,
        "uif_exempt": True,
    })
    session.commit()
    session.refresh(emp)
    assert wrote is True
    assert float(emp.contracted_weekly_hours) == 40.0
    assert emp.medical_scheme_members == 3
    assert emp.uif_exempt is True


def test_apply_partial_leaves_rest_untouched(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    wrote = apply_import_row_fields(emp, {"medical_scheme_members": 2})
    session.commit()
    session.refresh(emp)
    assert wrote is True
    assert emp.medical_scheme_members == 2
    assert emp.contracted_weekly_hours is None


def test_apply_empty_row_noop(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    wrote = apply_import_row_fields(emp, {})
    assert wrote is False


def test_apply_boolean_coercion(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    apply_import_row_fields(emp, {"uif_exempt": "true"})
    session.commit()
    session.refresh(emp)
    assert emp.uif_exempt is True

# END OF FILE

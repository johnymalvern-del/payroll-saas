"""Employee payroll field endpoints + change request hardening (004a-iv-b)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.api.v1.payroll_employee_fields import (
    get_employee_fields,
    submit_employee_fields_change,
)
from app.api.v1.payroll_employee_fields_schemas import EmployeeFieldsChangeIn
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.people import Employee, User
from app.db.tenant.session import get_tenant_engine
from app.services.payroll_change_request import (
    approve_change_request,
    submit_change_request,
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
    slug = f"fld-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Fields Test",
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


def _mk_emp(session, code=None):
    code = code or f"F-{uuid.uuid4().hex[:6]}"
    emp = Employee(
        employee_code=code, first_name="A", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
        medical_scheme_members=0, uif_exempt=False,
    )
    session.add(emp)
    session.commit()
    return emp


def _mk_user(session, *, username, role, employee_id=None):
    u = User(
        id=uuid.uuid4(),
        username=username,
        password_hash=hash_password("TestPass123!"),
        role=role,
        employee_id=employee_id,
    )
    session.add(u)
    session.commit()
    return u


@pytest.fixture()
def ctx(tenant_session):
    session, engine = tenant_session
    emp = _mk_emp(session)
    hr = _mk_user(session, username=f"hr-{uuid.uuid4().hex[:6]}", role="hr", employee_id=emp.id)
    admin = _mk_user(session, username=f"pa-{uuid.uuid4().hex[:6]}", role="payroll_admin", employee_id=None)
    return SimpleNamespace(session=session, engine=engine, emp=emp, hr=hr, admin=admin)


# ---------------------------------------------------------------------------
# GET /fields
# ---------------------------------------------------------------------------

def test_get_fields_defaults(ctx):
    out = get_employee_fields(employee_id=ctx.emp.id, db=ctx.session, user=ctx.hr)
    assert out.employee_id == ctx.emp.id
    assert out.contracted_weekly_hours is None
    assert out.medical_scheme_members == 0
    assert out.uif_exempt is False
    assert out.row_version >= 1


def test_get_fields_404_for_nonexistent(ctx):
    with pytest.raises(AppError) as exc_info:
        get_employee_fields(employee_id=uuid.uuid4(), db=ctx.session, user=ctx.hr)
    assert exc_info.value.code == "not_found"


# ---------------------------------------------------------------------------
# POST /fields — change request submission
# ---------------------------------------------------------------------------

def test_submit_fields_change_returns_pending(ctx):
    body = EmployeeFieldsChangeIn(row_version=ctx.emp.row_version, uif_exempt=True)
    out = submit_employee_fields_change(
        employee_id=ctx.emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    assert out.kind == "employee_field_update"
    assert out.status == "pending"
    # Employee unchanged
    ctx.session.refresh(ctx.emp)
    assert ctx.emp.uif_exempt is False


def test_submit_fields_change_empty_payload_422_via_service(ctx):
    with pytest.raises(AppError) as exc_info:
        submit_change_request(
            ctx.session, ctx.hr,
            kind="employee_field_update",
            employee_id=ctx.emp.id,
            payload={"row_version": ctx.emp.row_version},
        )
    assert exc_info.value.code == "invalid_payload"


def test_submit_fields_change_negative_members_422_via_service(ctx):
    with pytest.raises(AppError) as exc_info:
        submit_change_request(
            ctx.session, ctx.hr,
            kind="employee_field_update",
            employee_id=ctx.emp.id,
            payload={"row_version": ctx.emp.row_version, "medical_scheme_members": -3},
        )
    assert exc_info.value.code == "invalid_payload"


# ---------------------------------------------------------------------------
# Approve changes fields, bumps row_version
# ---------------------------------------------------------------------------

def test_approve_fields_change_updates_employee(ctx):
    body = EmployeeFieldsChangeIn(
        row_version=ctx.emp.row_version,
        contracted_weekly_hours=40.0,
        uif_exempt=True,
    )
    out = submit_employee_fields_change(
        employee_id=ctx.emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    old_rv = ctx.emp.row_version
    approve_change_request(ctx.session, ctx.admin, out.id)
    ctx.session.commit()
    ctx.session.refresh(ctx.emp)
    assert ctx.emp.contracted_weekly_hours == 40.0
    assert ctx.emp.uif_exempt is True
    assert ctx.emp.row_version == old_rv + 1


# ---------------------------------------------------------------------------
# Stale row_version at approval time
# ---------------------------------------------------------------------------

def test_approve_fields_change_refuses_stale_row_version(ctx):
    # Submit against a fake row_version
    body = EmployeeFieldsChangeIn(
        row_version=ctx.emp.row_version + 100, uif_exempt=True,
    )
    out = submit_employee_fields_change(
        employee_id=ctx.emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    with pytest.raises(AppError) as exc_info:
        approve_change_request(ctx.session, ctx.admin, out.id)
    assert exc_info.value.code == "record_changed"

# END OF FILE

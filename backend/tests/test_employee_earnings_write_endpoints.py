"""Employee earning/deduction write endpoints now submit change requests (F3).

Called as raw functions (not HTTP) - the Depends(require_permission) layer is
asserted separately by test_payroll_endpoint_permissions. These tests verify
the business behavior: writes create pending requests, approval writes through.

Scope note: HR has company-wide scope for PAY_RATE_REQUEST by design (that is
the role of HR), so HR can submit change requests for any employee. A true
scope-refusal test would need a role that has PAY_RATE_REQUEST but a limited
scope - none exists today. We instead test the 404 path for nonexistent
employee IDs, which is the actual defensive behaviour the endpoint enforces.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.api.v1.payroll_employees import (
    create_employee_deduction_request,
    create_employee_earning_request,
    deactivate_employee_earning_request,
    patch_employee_earning_request,
)
from app.api.v1.payroll_employees_schemas import (
    EmployeeDeductionIn,
    EmployeeEarningIn,
    EmployeeEarningPatch,
)
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.pay import DeductionType, EarningType, EmployeeEarning
from app.db.tenant.models.people import Employee, User
from app.db.tenant.session import get_tenant_engine
from app.services.payroll_change_request import approve_change_request


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
    slug = f"pew-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="PEW Test",
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
    code = code or f"PE-{uuid.uuid4().hex[:6]}"
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


def _mk_earning_type(session, code=None):
    code = code or f"e-{uuid.uuid4().hex[:6]}"
    et = EarningType(
        id=uuid.uuid4(), name="E", code=code,
        calc_method="fixed_amount", frequency="regular",
        is_system=False, is_active=True,
    )
    session.add(et)
    session.commit()
    return et


def _mk_deduction_type(session, code=None):
    code = code or f"d-{uuid.uuid4().hex[:6]}"
    dt = DeductionType(
        id=uuid.uuid4(), name="D", code=code,
        category="other", priority=100, is_pre_tax=False,
        is_system=False, is_active=True,
    )
    session.add(dt)
    session.commit()
    return dt


@pytest.fixture()
def ctx(tenant_session):
    session, engine = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    dt = _mk_deduction_type(session)
    hr = _mk_user(session, username=f"hr-{uuid.uuid4().hex[:6]}", role="hr", employee_id=emp.id)
    admin = _mk_user(session, username=f"pa-{uuid.uuid4().hex[:6]}", role="payroll_admin", employee_id=None)
    return SimpleNamespace(
        session=session, engine=engine, emp=emp, et=et, dt=dt, hr=hr, admin=admin,
    )


# ---------------------------------------------------------------------------
# Create earning
# ---------------------------------------------------------------------------

def test_create_earning_returns_change_request_not_row(ctx):
    body = EmployeeEarningIn(
        earning_type_id=ctx.et.id,
        amount=Decimal("1500.00"),
        rate=None,
        effective_from=date(2025, 1, 1),
        effective_to=None,
    )
    out = create_employee_earning_request(
        employee_id=ctx.emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    assert out.kind == "employee_earning_create"
    assert out.status == "pending"
    assert ctx.session.query(EmployeeEarning).count() == 0


def test_create_earning_then_approve_writes_row(ctx):
    body = EmployeeEarningIn(
        earning_type_id=ctx.et.id,
        amount=Decimal("1500.00"),
        rate=None,
        effective_from=date(2025, 1, 1),
        effective_to=None,
    )
    out = create_employee_earning_request(
        employee_id=ctx.emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    approve_change_request(ctx.session, ctx.admin, out.id)
    ctx.session.commit()
    row = ctx.session.query(EmployeeEarning).filter_by(employee_id=ctx.emp.id).one()
    assert row.amount == Decimal("1500.00")


# ---------------------------------------------------------------------------
# Patch earning
# ---------------------------------------------------------------------------

def test_patch_earning_returns_change_request(ctx):
    row = EmployeeEarning(
        id=uuid.uuid4(), employee_id=ctx.emp.id, earning_type_id=ctx.et.id,
        amount=Decimal("1000.00"), rate=None,
        effective_from=date(2025, 1, 1), is_active=True,
    )
    ctx.session.add(row)
    ctx.session.commit()

    body = EmployeeEarningPatch(row_version=row.row_version, amount=Decimal("1200.00"))
    out = patch_employee_earning_request(
        employee_id=ctx.emp.id, item_id=row.id, body=body,
        db=ctx.session, user=ctx.hr,
    )
    assert out.kind == "employee_earning_update"
    assert out.status == "pending"
    ctx.session.refresh(row)
    assert row.amount == Decimal("1000.00")


# ---------------------------------------------------------------------------
# Deactivate earning
# ---------------------------------------------------------------------------

def test_deactivate_earning_returns_change_request(ctx):
    row = EmployeeEarning(
        id=uuid.uuid4(), employee_id=ctx.emp.id, earning_type_id=ctx.et.id,
        amount=Decimal("1000.00"), rate=None,
        effective_from=date(2025, 1, 1), is_active=True,
    )
    ctx.session.add(row)
    ctx.session.commit()

    out = deactivate_employee_earning_request(
        employee_id=ctx.emp.id, item_id=row.id,
        row_version=row.row_version, db=ctx.session, user=ctx.hr,
    )
    assert out.kind == "employee_earning_deactivate"
    ctx.session.refresh(row)
    assert row.is_active is True


# ---------------------------------------------------------------------------
# Create deduction
# ---------------------------------------------------------------------------

def test_create_deduction_returns_change_request(ctx):
    body = EmployeeDeductionIn(
        deduction_type_id=ctx.dt.id,
        amount=Decimal("500.00"),
        effective_from=date(2025, 1, 1),
        effective_to=None,
    )
    out = create_employee_deduction_request(
        employee_id=ctx.emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    assert out.kind == "employee_deduction_create"
    assert out.status == "pending"


# ---------------------------------------------------------------------------
# HR company-wide scope: any valid employee is accepted
# ---------------------------------------------------------------------------

def test_hr_can_submit_for_any_employee_company_wide(ctx):
    """HR has company-wide scope for pay-rate change requests by design."""
    other_emp = _mk_emp(ctx.session, code=f"OTHER-{uuid.uuid4().hex[:6]}")
    body = EmployeeEarningIn(
        earning_type_id=ctx.et.id,
        amount=Decimal("100.00"),
        rate=None,
        effective_from=date(2025, 1, 1),
        effective_to=None,
    )
    out = create_employee_earning_request(
        employee_id=other_emp.id, body=body, db=ctx.session, user=ctx.hr,
    )
    assert out.kind == "employee_earning_create"
    assert out.status == "pending"
    assert out.employee_id == other_emp.id


# ---------------------------------------------------------------------------
# Defensive 404: nonexistent employee ID is rejected
# ---------------------------------------------------------------------------

def test_submit_for_nonexistent_employee_404s(ctx):
    """The existence check in submit_change_request rejects unknown employee IDs."""
    body = EmployeeEarningIn(
        earning_type_id=ctx.et.id,
        amount=Decimal("100.00"),
        rate=None,
        effective_from=date(2025, 1, 1),
        effective_to=None,
    )
    with pytest.raises(AppError) as exc_info:
        create_employee_earning_request(
            employee_id=uuid.uuid4(),  # random, nonexistent
            body=body, db=ctx.session, user=ctx.hr,
        )
    assert exc_info.value.code == "not_found"

# END OF FILE

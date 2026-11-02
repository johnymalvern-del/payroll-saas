"""Chapter 4H B-3: /payroll/payslips/me routes + role matrix."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.payroll_payslips import (
    get_my_payslip,
    get_my_payslip_pdf,
    list_my_payslips,
)
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.pay import PayPeriod, PayrollRun, Payslip
from app.db.tenant.models.people import Employee, User
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    slug = f"ownpay-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Own Payslips Co",
        admin_username="admin",
        admin_password_hash=hash_password("AdminPassword123!"),
    )
    try:
        yield _DisposableTenant(
            slug=slug,
            tenant_db_name=result.tenant_db_name,
            subscriber_id=result.subscriber_id,
        )
    finally:
        _drop_tenant_database(result.tenant_db_name)
        with control_session() as s:
            r = s.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
            if r is not None:
                s.delete(r)


@pytest.fixture()
def session(disposable_tenant) -> Iterator[Session]:
    url = (
        "postgresql+psycopg://payroll_app:payroll_app_dev_password"
        f"@localhost:5432/{disposable_tenant.tenant_db_name}"
    )
    engine = create_engine(url, future=True)
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        engine.dispose()


def _mk_employee(session) -> Employee:
    emp = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="Test",
        last_name="Emp",
        hire_date=date(2024, 1, 1),
        status="active",
        employee_type="hourly",
        pay_basis="hourly",
        pay_frequency="monthly",
        base_rate=Decimal("100.00"),
        row_version=1,
    )
    session.add(emp)
    session.flush()
    return emp


def _mk_user(session, *, role: str, employee_id: uuid.UUID | None) -> User:
    u = User(
        username=f"{role}-{uuid.uuid4().hex[:6]}",
        password_hash="x",
        employee_id=employee_id,
        role=role,
        is_active=True,
        must_change_password=False,
        failed_attempts=0,
        row_version=1,
    )
    session.add(u)
    session.flush()
    return u


def _mk_period(session, period_key="2026-01", pay_date=None) -> PayPeriod:
    p = PayPeriod(
        id=uuid.uuid4(),
        period_key=period_key,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        pay_date=pay_date or date(2026, 1, 31),
        status="locked",
        cutoff_at=datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc),
    )
    session.add(p)
    session.flush()
    return p


def _mk_run(session, period) -> PayrollRun:
    run = PayrollRun(
        id=uuid.uuid4(),
        pay_period_id=period.id,
        kind="final",
        revision=1,
        status="completed",
        rules_snapshot={},
    )
    session.add(run)
    session.flush()
    return run


def _mk_payslip(
    session, run, period, emp, *, status="current", net="890.00",
) -> Payslip:
    ps = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=period.id,
        employee_id=emp.id,
        revision=run.revision,
        status=status,
        gross=Decimal("1000.00"),
        pre_tax_deductions=Decimal("0"),
        taxable_income=Decimal("1000.00"),
        paye=Decimal("100.00"),
        uif_employee=Decimal("10.00"),
        uif_employer=Decimal("10.00"),
        sdl=Decimal("10.00"),
        other_deductions=Decimal("0"),
        reimbursements=Decimal("0"),
        net=Decimal(net),
        employer_costs={},
        snapshot={},
        calculation_context={},
    )
    session.add(ps)
    session.flush()
    return ps


def _ctx_one_own_payslip(session):
    emp = _mk_employee(session)
    user = _mk_user(session, role="employee", employee_id=emp.id)
    period = _mk_period(session)
    run = _mk_run(session, period)
    ps = _mk_payslip(session, run, period, emp)
    return emp, user, period, ps


def test_me_lists_only_own(session):
    emp1 = _mk_employee(session)
    emp2 = _mk_employee(session)
    user1 = _mk_user(session, role="employee", employee_id=emp1.id)

    p1 = _mk_period(session, period_key="2026-01", pay_date=date(2026, 1, 31))
    r1 = _mk_run(session, p1)
    ps1 = _mk_payslip(session, r1, p1, emp1)
    ps2 = _mk_payslip(session, r1, p1, emp2)

    out = list_my_payslips(session, user1, limit=100, cursor=None)
    ids = [it.id for it in out.items]
    assert ps1.id in ids
    assert ps2.id not in ids


def test_me_excludes_preview_status(session):
    emp = _mk_employee(session)
    user = _mk_user(session, role="employee", employee_id=emp.id)
    period = _mk_period(session)
    run = _mk_run(session, period)
    _mk_payslip(session, run, period, emp, status="preview")
    _mk_payslip(session, run, period, emp, status="current")

    out = list_my_payslips(session, user, limit=100, cursor=None)
    assert all(it.status != "preview" for it in out.items)


def test_me_404_when_no_employee_record(session):
    user = _mk_user(session, role="employee", employee_id=None)
    with pytest.raises(AppError) as exc:
        list_my_payslips(session, user, limit=100, cursor=None)
    assert exc.value.code == "no_employee_record"


def test_me_detail_404_for_other_employee_payslip(session):
    emp1 = _mk_employee(session)
    emp2 = _mk_employee(session)
    user1 = _mk_user(session, role="employee", employee_id=emp1.id)
    period = _mk_period(session)
    run = _mk_run(session, period)
    other_ps = _mk_payslip(session, run, period, emp2)

    with pytest.raises(AppError) as exc:
        get_my_payslip(other_ps.id, session, user1)
    assert exc.value.code == "not_found"


def test_me_pdf_404_for_other_employee_payslip(session):
    emp1 = _mk_employee(session)
    emp2 = _mk_employee(session)
    user1 = _mk_user(session, role="employee", employee_id=emp1.id)
    period = _mk_period(session)
    run = _mk_run(session, period)
    other_ps = _mk_payslip(session, run, period, emp2)

    with pytest.raises(AppError) as exc:
        get_my_payslip_pdf(other_ps.id, session, user1)
    assert exc.value.code == "not_found"


def test_me_pagination_cursor(session):
    emp = _mk_employee(session)
    user = _mk_user(session, role="employee", employee_id=emp.id)
    for i in range(3):
        p = _mk_period(
            session,
            period_key=f"2026-{i + 1:02d}",
            pay_date=date(2026, i + 1, 28),
        )
        r = _mk_run(session, p)
        _mk_payslip(session, r, p, emp)

    first = list_my_payslips(session, user, limit=2, cursor=None)
    assert len(first.items) == 2
    assert first.next_cursor is not None

    second = list_my_payslips(session, user, limit=2, cursor=first.next_cursor)
    assert len(second.items) >= 1
    # Different payslips between pages
    assert set(it.id for it in first.items) & set(it.id for it in second.items) == set()


def test_me_not_parsed_as_id_by_route(session):
    """Round-2 §12: 'me' must not be consumed by /{payslip_id}.

    FastAPI registration order guarantees /me is matched before
    /{payslip_id}. This test proves it in two ways: (a) the /me route
    exists on the router (import-time check), (b) calling list_my_payslips
    on the current user does not raise 'uuid parse' errors.
    """
    from app.api.v1.payroll_payslips import router as payslip_router

    paths = [r.path for r in payslip_router.routes]
    assert "/payroll/payslips/me" in paths
    idx_me = paths.index("/payroll/payslips/me")
    idx_id = paths.index("/payroll/payslips/{payslip_id}")
    assert idx_me < idx_id, "/me must be registered before /{payslip_id}"

    emp = _mk_employee(session)
    user = _mk_user(session, role="employee", employee_id=emp.id)
    out = list_my_payslips(session, user, limit=100, cursor=None)
    assert out is not None  # no UUID-parse crash


def test_me_employee_can_read_own(session):
    _emp, user, _period, _ps = _ctx_one_own_payslip(session)
    out = list_my_payslips(session, user, limit=100, cursor=None)
    assert out is not None


def test_me_manager_can_read_own(session):
    emp, _u, _p, _ps = _ctx_one_own_payslip(session)
    manager_user = _mk_user(session, role="manager", employee_id=emp.id)
    out = list_my_payslips(session, manager_user, limit=100, cursor=None)
    assert out is not None


def test_me_hr_can_read_own(session):
    emp, _u, _p, _ps = _ctx_one_own_payslip(session)
    hr_user = _mk_user(session, role="hr", employee_id=emp.id)
    out = list_my_payslips(session, hr_user, limit=100, cursor=None)
    assert out is not None


def test_me_payroll_admin_can_read_own(session):
    emp, _u, _p, _ps = _ctx_one_own_payslip(session)
    admin_user = _mk_user(session, role="payroll_admin", employee_id=emp.id)
    out = list_my_payslips(session, admin_user, limit=100, cursor=None)
    assert out is not None


def test_me_auditor_gets_403(session):
    emp = _mk_employee(session)
    auditor_user = _mk_user(session, role="auditor", employee_id=emp.id)
    with pytest.raises(AppError) as exc:
        list_my_payslips(session, auditor_user, limit=100, cursor=None)
    assert exc.value.code == "forbidden"
    assert (exc.value.details or {}).get("role") == "auditor"

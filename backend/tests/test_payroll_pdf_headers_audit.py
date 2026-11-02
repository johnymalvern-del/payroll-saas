"""Chapter 4H B-3 amendment §14: PDF Cache-Control, generic filename, audit."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.payroll_payslips import get_payslip_pdf
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.pay import PayPeriod, PayrollRun, Payslip
from app.db.tenant.models.people import Employee, User
from app.db.tenant.models.platform import AuditLog
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
    slug = f"pdfau-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="PDF Audit Co",
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
        first_name="Ada",
        last_name="Mokoena",
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


def _mk_payslip(session, emp) -> Payslip:
    period = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"P-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        pay_date=date(2026, 1, 31),
        status="locked",
        cutoff_at=datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc),
    )
    session.add(period)
    session.flush()
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
    ps = Payslip(
        id=uuid.uuid4(),
        payroll_run_id=run.id,
        pay_period_id=period.id,
        employee_id=emp.id,
        revision=1,
        status="current",
        gross=Decimal("1000.00"),
        pre_tax_deductions=Decimal("0"),
        taxable_income=Decimal("1000.00"),
        paye=Decimal("100.00"),
        uif_employee=Decimal("10.00"),
        uif_employer=Decimal("10.00"),
        sdl=Decimal("10.00"),
        other_deductions=Decimal("0"),
        reimbursements=Decimal("0"),
        net=Decimal("890.00"),
        employer_costs={},
        snapshot={},
        calculation_context={},
    )
    session.add(ps)
    session.flush()
    return ps


def test_pdf_has_cache_control_no_store(session):
    emp = _mk_employee(session)
    admin = _mk_user(session, role="payroll_admin", employee_id=None)
    ps = _mk_payslip(session, emp)
    session.commit()

    resp = get_payslip_pdf(ps.id, session, admin)
    assert resp.headers["Cache-Control"] == "no-store"
    assert "Content-Disposition" in resp.headers


def test_pdf_uses_generic_filename(session):
    emp = _mk_employee(session)
    admin = _mk_user(session, role="payroll_admin", employee_id=None)
    ps = _mk_payslip(session, emp)
    session.commit()

    resp = get_payslip_pdf(ps.id, session, admin)
    cd = resp.headers["Content-Disposition"]
    assert 'filename="payslip.pdf"' in cd
    assert emp.employee_code not in cd


def test_pdf_writes_audit_when_downloaded_by_other(session):
    emp = _mk_employee(session)
    admin = _mk_user(session, role="payroll_admin", employee_id=None)
    ps = _mk_payslip(session, emp)
    session.commit()

    before = session.scalar(select(AuditLog).where(
        AuditLog.action == "payslip.pdf_download_by_other"
    ))
    assert before is None

    get_payslip_pdf(ps.id, session, admin)

    rows = list(session.scalars(select(AuditLog).where(
        AuditLog.action == "payslip.pdf_download_by_other"
    )).all())
    assert len(rows) == 1
    assert rows[0].entity_id == str(ps.id)


def test_pdf_no_audit_when_owner_downloads(session):
    emp = _mk_employee(session)
    owner = _mk_user(session, role="employee", employee_id=emp.id)
    ps = _mk_payslip(session, emp)
    session.commit()

    get_payslip_pdf(ps.id, session, owner)

    rows = list(session.scalars(select(AuditLog).where(
        AuditLog.action == "payslip.pdf_download_by_other"
    )).all())
    assert rows == []

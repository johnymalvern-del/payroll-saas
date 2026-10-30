"""Change request mechanism (Chapter 4, Bundle 004a-iv-a)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.pay import EarningType, EmployeeEarning
from app.db.tenant.models.people import Employee
from app.db.tenant.session import get_tenant_engine
from app.services.payroll_change_request import (
    approve_change_request,
    cancel_change_request,
    reject_change_request,
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
    slug = f"cr-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="CR Test",
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


def _hr():
    return SimpleNamespace(role="hr", id=uuid.uuid4(), employee_id=None)


def _payroll_admin():
    return SimpleNamespace(role="payroll_admin", id=uuid.uuid4(), employee_id=None)


def _mk_emp(session, code="CR-1"):
    emp = Employee(
        employee_code=code, first_name="A", last_name=code,
        hire_date=date(2024, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
        medical_scheme_members=0, uif_exempt=False,
    )
    session.add(emp)
    session.commit()
    return emp


def _mk_earning_type(session, code="base"):
    et = EarningType(
        id=uuid.uuid4(), name="Base", code=code,
        calc_method="fixed_amount", frequency="regular",
        is_system=False, is_active=True,
    )
    session.add(et)
    session.commit()
    return et


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def test_submit_creates_pending(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    req = submit_change_request(
        session, hr,
        kind="employee_earning_create",
        employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    assert req.status == "pending"
    assert req.requested_by_user_id == hr.id
    # No EmployeeEarning row created
    assert session.query(EmployeeEarning).count() == 0


def test_submit_rejects_unknown_kind(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    with pytest.raises(AppError) as exc_info:
        submit_change_request(
            session, _hr(),
            kind="bogus_kind",
            employee_id=emp.id,
            payload={},
        )
    assert exc_info.value.code == "unknown_kind"


def test_submit_validates_payload_shape(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    with pytest.raises(AppError) as exc_info:
        submit_change_request(
            session, _hr(),
            kind="employee_earning_create",
            employee_id=emp.id,
            payload={"earning_type_id": "not-a-uuid"},  # missing + bad
        )
    assert exc_info.value.code == "invalid_payload"


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

def test_approve_creates_employee_earning(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    admin = _payroll_admin()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    req, applied_id = approve_change_request(session, admin, req.id)
    session.commit()

    assert req.status == "approved"
    assert req.decided_by_user_id == admin.id
    assert req.applied_entity_id == applied_id
    row = session.query(EmployeeEarning).filter_by(id=applied_id).one()
    assert row.amount == Decimal("1500.00")


def test_approve_self_rejected(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    with pytest.raises(AppError) as exc_info:
        approve_change_request(session, hr, req.id)
    assert exc_info.value.code == "self_approval_forbidden"


def test_approve_already_decided_rejected(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    admin = _payroll_admin()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    approve_change_request(session, admin, req.id)
    session.commit()
    with pytest.raises(AppError) as exc_info:
        approve_change_request(session, admin, req.id)
    assert exc_info.value.code == "not_pending"


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

def test_reject_sets_status(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    admin = _payroll_admin()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    reject_change_request(session, admin, req.id, "insufficient evidence")
    session.commit()
    session.refresh(req)
    assert req.status == "rejected"
    assert req.decision_note == "insufficient evidence"
    assert session.query(EmployeeEarning).count() == 0


def test_reject_self_rejected(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    with pytest.raises(AppError) as exc_info:
        reject_change_request(session, hr, req.id, "meh")
    assert exc_info.value.code == "self_approval_forbidden"


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------

def test_cancel_by_requester(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    cancel_change_request(session, hr, req.id)
    session.commit()
    session.refresh(req)
    assert req.status == "cancelled"


def test_cancel_by_other_rejected(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    et = _mk_earning_type(session)
    hr = _hr()
    admin = _payroll_admin()
    req = submit_change_request(
        session, hr, kind="employee_earning_create", employee_id=emp.id,
        payload={
            "earning_type_id": str(et.id),
            "amount": "1500.00",
            "effective_from": "2025-01-01",
        },
    )
    session.commit()
    with pytest.raises(AppError) as exc_info:
        cancel_change_request(session, admin, req.id)
    assert exc_info.value.code == "not_requester"


# ---------------------------------------------------------------------------
# Field update
# ---------------------------------------------------------------------------

def test_approve_field_update_writes_employee(tenant_session):
    session, _ = tenant_session
    emp = _mk_emp(session)
    hr = _hr()
    admin = _payroll_admin()
    req = submit_change_request(
        session, hr, kind="employee_field_update", employee_id=emp.id,
        payload={"contracted_weekly_hours": 40.0, "uif_exempt": True},
    )
    session.commit()
    _, applied_id = approve_change_request(session, admin, req.id)
    session.commit()
    session.refresh(emp)
    assert emp.contracted_weekly_hours == 40.0
    assert emp.uif_exempt is True
    assert applied_id == emp.id

# END OF FILE

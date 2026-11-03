"""Chapter 3 L1e: leave type CRUD tests (3B.1 + amendment 1/4/5)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.leave_types import (
    create_leave_type,
    deactivate_leave_type,
    get_leave_type,
    list_leave_types,
    patch_leave_type,
    reactivate_leave_type,
)
from app.api.v1.leave_types_schemas import (
    LeaveTypeIn,
    LeaveTypePatch,
)
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.leave import LeaveBalance, LeaveType
from app.db.tenant.models.people import Employee, User
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


_TENANT_URL = (
    "postgresql+psycopg://payroll_app:payroll_app_dev_password"
    "@localhost:5432/{db}"
)


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    slug = f"lt-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Leave Types Co",
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
    url = _TENANT_URL.format(db=disposable_tenant.tenant_db_name)
    engine = create_engine(url, future=True)
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        engine.dispose()


def _admin(session) -> User:
    u = session.scalar(select(User).where(User.username == "admin"))
    assert u is not None
    return u


def _create(session, user, **overrides) -> LeaveType:
    defaults = dict(
        name="Annual Leave",
        code="annual",
        unit="day",
        paid=True,
        accrual_method="annual",
        accrual_amount="20.00",
        cycle="calendar",
        requires_approval=True,
        requires_document_after_days=None,
        allow_negative=False,
        max_carryover="5.00",
        approval_chain=["manager", "hr"],
        requires_payroll_admin_final=False,
    )
    defaults.update(overrides)
    return create_leave_type(
        LeaveTypeIn(**defaults), session, user
    )


def test_leave_type_create_ok(session):
    user = _admin(session)
    row = _create(session, user)
    assert row.code == "annual"
    assert row.approval_chain == ["manager", "hr"]
    assert row.requires_payroll_admin_final is False


def test_leave_type_duplicate_code_case_insensitive(session):
    user = _admin(session)
    _create(session, user, code="annual")
    with pytest.raises(AppError) as exc:
        _create(session, user, code="ANNUAL")
    assert exc.value.code == "duplicate_code"


def test_leave_type_annual_requires_accrual_amount(session):
    user = _admin(session)
    with pytest.raises(AppError) as exc:
        _create(session, user, accrual_method="annual", accrual_amount=None)
    assert exc.value.code == "accrual_amount_required"


def test_leave_type_fixed_requires_accrual_amount(session):
    user = _admin(session)
    with pytest.raises(AppError) as exc:
        _create(session, user, accrual_method="fixed", accrual_amount=None)
    assert exc.value.code == "accrual_amount_required"


def test_leave_type_negative_requires_accrual_method(session):
    user = _admin(session)
    with pytest.raises(AppError) as exc:
        _create(
            session, user,
            accrual_method="none", accrual_amount=None,
            allow_negative=True,
        )
    assert exc.value.code == "negative_requires_accrual"


def test_leave_type_max_carryover_not_allowed_on_fixed(session):
    user = _admin(session)
    with pytest.raises(AppError) as exc:
        _create(
            session, user,
            cycle="fixed", accrual_method="fixed",
            accrual_amount="20.00", max_carryover="5.00",
        )
    assert exc.value.code == "carryover_not_allowed_on_fixed"


def test_leave_type_patch_row_version_mismatch(session):
    user = _admin(session)
    row = _create(session, user)
    with pytest.raises(AppError) as exc:
        patch_leave_type(
            row.id,
            LeaveTypePatch(row_version=row.row_version + 5, name="X"),
            session, user,
        )
    assert exc.value.code == "record_changed"


def test_leave_type_code_immutable_on_patch(session):
    user = _admin(session)
    row = _create(session, user, code="al")
    updated = patch_leave_type(
        row.id,
        LeaveTypePatch(row_version=row.row_version, name="Annual 2"),
        session, user,
    )
    assert updated.code == "al"
    assert updated.name == "Annual 2"


def test_leave_type_deactivate_refused_when_balances_exist(session):
    user = _admin(session)
    row = _create(session, user)
    emp = Employee(
        employee_code=f"E-{uuid.uuid4().hex[:6]}",
        first_name="A", last_name="B",
        hire_date=__import__("datetime").date(2024, 1, 1),
        status="active", employee_type="hourly", pay_basis="hourly",
        pay_frequency="monthly", row_version=1,
    )
    session.add(emp)
    session.flush()
    session.add(LeaveBalance(
        employee_id=emp.id, leave_type_id=row.id,
        cycle_start=__import__("datetime").date(2026, 1, 1),
        cycle_end=__import__("datetime").date(2026, 12, 31),
        entitled=__import__("decimal").Decimal("0"),
        accrued=__import__("decimal").Decimal("0"),
        taken=__import__("decimal").Decimal("0"),
        pending=__import__("decimal").Decimal("0"),
        carried_in=__import__("decimal").Decimal("0"),
        adjusted=__import__("decimal").Decimal("0"),
        row_version=1,
    ))
    session.flush()
    with pytest.raises(AppError) as exc:
        deactivate_leave_type(row.id, session, user)
    assert exc.value.code == "leave_type_in_use"


def test_leave_type_reactivate_ok(session):
    user = _admin(session)
    row = _create(session, user)
    deactivate_leave_type(row.id, session, user)
    again = reactivate_leave_type(row.id, session, user)
    assert again.is_active is True


def test_leave_type_list_excludes_inactive_by_default(session):
    user = _admin(session)
    a = _create(session, user, code="a", name="A")
    _create(session, user, code="b", name="B")
    deactivate_leave_type(a.id, session, user)

    out = list_leave_types(session, user, is_active=None, unit=None, paid=None, limit=100, cursor=None)
    codes = {r.code for r in out.items}
    assert codes == {"b"}


def test_leave_type_list_filters_by_unit(session):
    user = _admin(session)
    _create(session, user, code="dayy", name="Day", unit="day")
    _create(session, user, code="houry", name="Hour", unit="hour")
    out = list_leave_types(session, user, is_active=True, unit="hour", paid=None, limit=100, cursor=None)
    assert {r.code for r in out.items} == {"houry"}


def test_leave_type_invalid_chain_role(session):
    user = _admin(session)
    with pytest.raises(Exception):
        _create(session, user, approval_chain=["notarole"])
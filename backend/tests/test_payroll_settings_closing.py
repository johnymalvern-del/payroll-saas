"""Chapter 4H B-4 foundation: new PayrollSettings fields + PATCH validation.

Uses the real provisioned admin `User` row for the acting user so the
`payroll_settings.updated_by_user_id` FK is satisfiable. Fabricated
`SimpleNamespace(id=uuid4(), ...)` users violate that FK.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.v1.payroll_settings import (
    get_payroll_settings,
    patch_payroll_settings,
)
from app.api.v1.payroll_settings_schemas import PayrollSettingsPatchIn
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import User
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
    slug = f"psetcl-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Settings Closing Co",
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
def tenant_session(disposable_tenant) -> Iterator[Session]:
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


def _admin(tenant_session) -> User:
    """Return the real admin User row created by provision_tenant.

    `payroll_settings.updated_by_user_id` has an FK to `user.id`, so the
    acting user passed to `patch_payroll_settings` must be a real row.
    """
    admin = tenant_session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None, "provision_tenant did not create an admin user"
    return admin


def test_new_fields_default_when_no_row(tenant_session):
    out = get_payroll_settings(tenant_session, _admin(tenant_session))
    assert out.attendance_earning_map == {}
    assert out.unpaid_day_behaviour is None
    assert out.unpaid_day_formula_code is None
    assert out.public_holiday_unworked_monthly is None
    assert out.public_holiday_paid is None
    assert out.leave_authoritative_source is None
    assert out.monthly_hourly_derivation_formula_code is None
    assert out.leave_earning_for_monthly is None
    assert out.demo_values is False


def test_patch_creates_row_and_carries_new_fields(tenant_session):
    out = patch_payroll_settings(
        PayrollSettingsPatchIn(
            row_version=0,
            unpaid_day_behaviour="deduct_daily",
            public_holiday_unworked_monthly="paid",
            public_holiday_paid=True,
            leave_authoritative_source="adjustment",
            leave_earning_for_monthly=False,
            attendance_earning_map={"normal|weekday|any": "HOURLY_NORMAL"},
        ),
        tenant_session,
        _admin(tenant_session),
    )
    assert out.unpaid_day_behaviour == "deduct_daily"
    assert out.public_holiday_unworked_monthly == "paid"
    assert out.public_holiday_paid is True
    assert out.leave_authoritative_source == "adjustment"
    assert out.leave_earning_for_monthly is False
    assert out.attendance_earning_map == {"normal|weekday|any": "HOURLY_NORMAL"}


def test_patch_rejects_unknown_formula_code(tenant_session):
    patch_payroll_settings(
        PayrollSettingsPatchIn(row_version=0),
        tenant_session,
        _admin(tenant_session),
    )
    tenant_session.commit()
    row = tenant_session.scalar(select(PayrollSettings))
    assert row is not None
    tenant_session.refresh(row)

    with pytest.raises(AppError) as exc:
        patch_payroll_settings(
            PayrollSettingsPatchIn(
                row_version=row.row_version,
                unpaid_day_formula_code="gen_does_not_exist",
            ),
            tenant_session,
            _admin(tenant_session),
        )
    assert exc.value.code == "unknown_formula"


def test_patch_rejects_invalid_attendance_map_key(tenant_session):
    patch_payroll_settings(
        PayrollSettingsPatchIn(row_version=0),
        tenant_session,
        _admin(tenant_session),
    )
    tenant_session.commit()
    row = tenant_session.scalar(select(PayrollSettings))
    assert row is not None
    tenant_session.refresh(row)

    with pytest.raises(AppError) as exc:
        patch_payroll_settings(
            PayrollSettingsPatchIn(
                row_version=row.row_version,
                attendance_earning_map={"bad_key": "HOURLY_NORMAL"},
            ),
            tenant_session,
            _admin(tenant_session),
        )
    assert exc.value.code == "invalid_attendance_earning_map"


def test_patch_rejects_row_version_mismatch(tenant_session):
    patch_payroll_settings(
        PayrollSettingsPatchIn(row_version=0),
        tenant_session,
        _admin(tenant_session),
    )
    tenant_session.commit()
    row = tenant_session.scalar(select(PayrollSettings))
    assert row is not None
    tenant_session.refresh(row)

    with pytest.raises(AppError) as exc:
        patch_payroll_settings(
            PayrollSettingsPatchIn(row_version=row.row_version + 7),
            tenant_session,
            _admin(tenant_session),
        )
    assert exc.value.code == "record_changed"

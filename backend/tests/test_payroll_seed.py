"""System payroll seed tests (Chapter 4H B-4b, updated for B-4f).

After B-4f, `provision_tenant` already seeds the 13 system earning types,
so on a fresh provisioned tenant `ensure_system_earning_types` is a no-op
returning `created=[]`. These tests verify that:
  - the SYSTEM_TYPES registry is 13 entries;
  - calling `ensure_system_earning_types` on a fresh tenant seeds nothing
    (provision already did), and reports all 13 as existing;
  - the tenant already has the 13 rows before any explicit call;
  - a custom user type is not touched.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.pay import EarningType
from app.services.payroll_seed import SYSTEM_TYPES, ensure_system_earning_types
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


EXPECTED_CODES = {spec["code"] for spec in SYSTEM_TYPES}


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    slug = f"pseed-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Payroll Seed Co",
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


def test_system_types_registry_has_thirteen_entries():
    assert len(SYSTEM_TYPES) == 13
    codes = {spec["code"] for spec in SYSTEM_TYPES}
    assert codes == EXPECTED_CODES


def test_tenant_already_has_thirteen_types_after_provision(tenant_session):
    rows = tenant_session.scalars(select(EarningType)).all()
    assert len(rows) == 13
    assert {r.code for r in rows} == EXPECTED_CODES
    for r in rows:
        assert r.is_system is True
        assert r.is_active is True


def test_ensure_on_fresh_tenant_creates_nothing(tenant_session):
    result = ensure_system_earning_types(tenant_session)
    assert result["total"] == 13
    assert result["created"] == []
    assert set(result["existing"]) == EXPECTED_CODES

    rows = tenant_session.scalars(select(EarningType)).all()
    assert len(rows) == 13


def test_ensure_is_idempotent(tenant_session):
    first = ensure_system_earning_types(tenant_session)
    second = ensure_system_earning_types(tenant_session)
    assert first["created"] == []
    assert second["created"] == []
    assert set(second["existing"]) == EXPECTED_CODES

    rows = tenant_session.scalars(select(EarningType)).all()
    assert len(rows) == 13


def test_system_types_are_regular_and_taxable(tenant_session):
    rows = tenant_session.scalars(select(EarningType)).all()
    assert len(rows) == 13
    for r in rows:
        assert r.frequency == "regular"
        assert r.is_taxable is True
        assert r.counts_for_uif is True
        assert r.counts_for_sdl is True
        assert r.calc_method == "per_hour"
        assert r.proration_rule == "none"


def test_ensure_does_not_touch_existing_user_types(tenant_session):
    user_row = EarningType(
        id=uuid.uuid4(),
        name="Custom Bonus",
        code="custom_bonus",
        calc_method="fixed_amount",
        frequency="once_off",
        is_taxable=True,
        counts_for_uif=False,
        counts_for_sdl=False,
        proration_rule="none",
        is_system=False,
        is_active=True,
        row_version=1,
    )
    tenant_session.add(user_row)
    tenant_session.flush()

    ensure_system_earning_types(tenant_session)

    still = tenant_session.scalar(
        select(EarningType).where(EarningType.code == "custom_bonus")
    )
    assert still is not None
    assert still.is_system is False
    assert still.frequency == "once_off"
    assert still.calc_method == "fixed_amount"

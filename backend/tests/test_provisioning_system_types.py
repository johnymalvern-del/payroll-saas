"""Chapter 4H B-4f: provision_tenant seeds the 13 system earning types."""
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
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import EarningType
from app.services.payroll_seed import SYSTEM_TYPES
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
    slug = f"provst-{uuid.uuid4().hex[:8]}"
    result = provision_tenant(
        slug=slug,
        name="Provision Seed Co",
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


def test_provision_seeds_company_row(session):
    """Regression: `_seed_tenant_defaults` still inserts the company row."""
    company = session.scalar(select(Company))
    assert company is not None
    assert company.country_code == "ZA"
    assert company.currency == "ZAR"
    assert company.default_timezone == "Africa/Johannesburg"


def test_provision_seeds_thirteen_system_earning_types(session):
    rows = list(session.scalars(select(EarningType)).all())
    assert len(rows) == 13
    codes = {r.code for r in rows}
    assert codes == EXPECTED_CODES
    assert all(r.is_system is True for r in rows)
    assert all(r.is_active is True for r in rows)


def test_provision_system_earning_types_are_per_hour_regular(session):
    rows = list(session.scalars(select(EarningType)).all())
    for r in rows:
        assert r.calc_method == "per_hour"
        assert r.frequency == "regular"
        assert r.is_taxable is True
        assert r.counts_for_uif is True
        assert r.counts_for_sdl is True

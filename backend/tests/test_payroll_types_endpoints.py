"""Earning/deduction type smoke + behaviour (Chapter 4, Bundle 003b)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.pay import DeductionType, EarningType
from app.db.tenant.session import get_tenant_engine


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
    slug = f"ptyp-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Pay Types Test",
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


def test_types_tables_exist(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    try:
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert "earning_type" in tables, sorted(tables)
            assert "deduction_type" in tables, sorted(tables)
    finally:
        engine.dispose()


def test_earning_type_roundtrip(tenant_session):
    session, _ = tenant_session
    row = EarningType(
        id=uuid.uuid4(),
        name="Basic Salary",
        code="basic_salary",
        calc_method="fixed_amount",
        frequency="regular",
        is_taxable=True,
        counts_for_uif=True,
        counts_for_sdl=True,
        proration_rule="by_calendar_days",
        is_system=False,
        is_active=True,
    )
    session.add(row)
    session.commit()
    fetched = session.query(EarningType).filter_by(code="basic_salary").one()
    assert fetched.name == "Basic Salary"
    assert fetched.is_taxable is True
    assert fetched.proration_rule == "by_calendar_days"


def test_deduction_type_roundtrip(tenant_session):
    session, _ = tenant_session
    row = DeductionType(
        id=uuid.uuid4(),
        name="Retirement Fund",
        code="retirement",
        category="retirement",
        priority=10,
        is_pre_tax=True,
        is_system=False,
        is_active=True,
    )
    session.add(row)
    session.commit()
    fetched = session.query(DeductionType).filter_by(code="retirement").one()
    assert fetched.name == "Retirement Fund"
    assert fetched.category == "retirement"
    assert fetched.is_pre_tax is True


def test_earning_type_unique_code(tenant_session):
    session, _ = tenant_session
    session.add(EarningType(
        id=uuid.uuid4(), name="A", code="dup",
        calc_method="fixed_amount", frequency="regular",
        is_system=False, is_active=True,
    ))
    session.commit()
    session.add(EarningType(
        id=uuid.uuid4(), name="B", code="dup",
        calc_method="fixed_amount", frequency="regular",
        is_system=False, is_active=True,
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

# END OF FILE

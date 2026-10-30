"""System earning types seed (Chapter 4, Bundle 004a-iv-c)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.pay import EarningType
from app.db.tenant.session import get_tenant_engine
from app.services.payroll_seed import SYSTEM_TYPES, ensure_system_earning_types


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
    slug = f"seed-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Seed Test",
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


def test_ensure_seeds_four_system_types(tenant_session):
    session, _ = tenant_session
    result = ensure_system_earning_types(session)
    session.commit()
    assert sorted(result["created"]) == sorted(s["code"] for s in SYSTEM_TYPES)
    assert result["existing"] == []
    assert session.query(EarningType).filter_by(is_system=True).count() == 4


def test_ensure_is_idempotent(tenant_session):
    session, _ = tenant_session
    ensure_system_earning_types(session)
    session.commit()
    result = ensure_system_earning_types(session)
    session.commit()
    assert result["created"] == []
    assert sorted(result["existing"]) == sorted(s["code"] for s in SYSTEM_TYPES)
    assert session.query(EarningType).filter_by(is_system=True).count() == 4


def test_system_types_are_regular_and_taxable(tenant_session):
    session, _ = tenant_session
    ensure_system_earning_types(session)
    session.commit()
    rows = session.query(EarningType).filter_by(is_system=True).all()
    for row in rows:
        assert row.frequency == "regular", f"{row.code} not regular"
        assert row.is_taxable is True
        assert row.is_active is True


def test_ensure_does_not_touch_existing_user_types(tenant_session):
    session, _ = tenant_session
    session.add(EarningType(
        id=uuid.uuid4(), name="Bonus", code="bonus",
        calc_method="fixed_amount", frequency="once_off",
        is_system=False, is_active=True,
    ))
    session.commit()
    ensure_system_earning_types(session)
    session.commit()
    bonus = session.query(EarningType).filter_by(code="bonus").one()
    assert bonus.is_system is False
    assert bonus.frequency == "once_off"

# END OF FILE

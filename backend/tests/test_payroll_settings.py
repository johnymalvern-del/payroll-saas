"""Payroll settings smoke + behaviour (Chapter 4, Bundle 003b)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.session import get_tenant_engine
from app.api.v1.payroll_settings import _to_out


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
    slug = f"pset-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Pay Settings Test",
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


def test_payroll_settings_table_exists(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    try:
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            ))}
            assert "payroll_settings" in tables, sorted(tables)
    finally:
        engine.dispose()


def test_to_out_returns_defaults_when_no_row():
    out = _to_out(None)
    assert out.age_reference_date is None
    assert out.sdl_applies is None
    assert out.net_pay_floor == Decimal("0.00")
    assert out.row_version == 0


def test_settings_roundtrip(tenant_session):
    session, _ = tenant_session
    row = PayrollSettings(
        id=uuid.uuid4(),
        age_reference_date="pay_date",
        sdl_applies=True,
        net_pay_floor=Decimal("100.00"),
        row_version=1,
    )
    session.add(row)
    session.commit()
    fetched = session.query(PayrollSettings).one()
    assert fetched.age_reference_date == "pay_date"
    assert fetched.sdl_applies is True
    assert fetched.net_pay_floor == Decimal("100.00")
    out = _to_out(fetched)
    assert out.age_reference_date == "pay_date"
    assert out.sdl_applies is True
    assert out.net_pay_floor == Decimal("100.00")
    assert out.row_version == 1

# END OF FILE

"""Formula readiness + acknowledge endpoints (Chapter 4, Bundle 004a-i)."""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.api.v1.payroll_formulas import acknowledge_formula, get_readiness
from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.session import get_tenant_engine
from app.services.payroll_formulas import FORMULA_REGISTRY


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
    slug = f"pfml-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Formula Test",
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


def _admin():
    """Test admin with id=None so PayrollSettings.updated_by_user_id FK to
    user.id resolves (NULL) without a persisted user. In production, the
    FastAPI dependency loads the real User row, so id is always populated."""
    return SimpleNamespace(role="payroll_admin", id=None, employee_id=None)


def test_readiness_empty(tenant_session):
    session, _ = tenant_session
    out = get_readiness(db=session, user=_admin())
    assert len(out.items) == 6
    assert all(not i.verified for i in out.items)
    assert out.all_acknowledged is False


def test_acknowledge_creates_settings_when_absent(tenant_session):
    session, _ = tenant_session
    assert session.query(PayrollSettings).count() == 0
    ack = acknowledge_formula(code="gen_base_salary", db=session, user=_admin())
    assert ack.code == "gen_base_salary"
    assert ack.acknowledged is True
    rows = session.query(PayrollSettings).all()
    assert len(rows) == 1
    assert "gen_base_salary" in rows[0].formula_acks


def test_acknowledge_updates_existing(tenant_session):
    session, _ = tenant_session
    from decimal import Decimal
    session.add(PayrollSettings(
        id=uuid.uuid4(),
        net_pay_floor=Decimal("0.00"),
        formula_acks={},
        row_version=1,
    ))
    session.commit()
    acknowledge_formula(code="gen_base_salary", db=session, user=_admin())
    acknowledge_formula(code="gen_unpaid_absence", db=session, user=_admin())
    row = session.query(PayrollSettings).one()
    assert set(row.formula_acks.keys()) == {"gen_base_salary", "gen_unpaid_absence"}
    assert row.row_version == 3


def test_acknowledge_unknown_formula_raises(tenant_session):
    session, _ = tenant_session
    with pytest.raises(AppError) as exc_info:
        acknowledge_formula(code="not_a_real_formula", db=session, user=_admin())
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "unknown_formula"


def test_all_six_can_be_acknowledged_and_readiness_flips(tenant_session):
    session, _ = tenant_session
    admin = _admin()
    for code in FORMULA_REGISTRY:
        acknowledge_formula(code=code, db=session, user=admin)
    out = get_readiness(db=session, user=_admin())
    assert out.all_acknowledged is True
    assert all(i.verified for i in out.items)

# END OF FILE

"""Pay period CRUD + preview + finalise + reopen (Chapter 4, Bundle 004b-a).

Uses a synthetic_fake_v1 statutory table seeded to the 2099 window so tests
never collide with real ZA data. Employee earnings use the fixed_amount
calc_method (only supported mode in this bundle).
"""
from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password
from app.db.tenant.models.pay import (
    EarningType, EmployeeEarning, PayPeriod, PayrollRun, Payslip, PeriodReopenLog,
)
from app.db.tenant.models.payroll_settings import PayrollSettings
from app.db.tenant.models.people import Employee, User
from app.db.tenant.session import get_tenant_engine
from app.services import payroll_formulas as PF
from app.services import statutory_loader as SL
from app.services.payroll_runner import finalise, reopen, run_preview


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fake_tax_tables.json"


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
    slug = f"pp-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="PP Test",
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


@pytest.fixture(scope="module")
def seeded_control_tables():
    from app.db.control.session import control_session
    data = json.loads(FIXTURES.read_text(encoding="utf-8"))
    with control_session() as s:
        engine = s.get_bind()
    SL.bootstrap_schema(engine)

    seeded = []
    with engine.begin() as conn:
        for t in data["tables"]:
            conn.execute(sa.text(
                "DELETE FROM statutory_table WHERE country_code=:c AND table_type=:t AND version=:v"
            ), {"c": "ZZ", "t": t["table_type"], "v": "test_004b_a_" + t["table_type"]})

    for t in data["tables"]:
        doc = {k: v for k, v in t.items() if not k.startswith("_")}
        doc["country_code"] = "ZZ"
        doc["effective_from"] = "2099-01-01"
        doc["effective_to"] = "2099-12-31"
        doc["version"] = "test_004b_a_" + doc["table_type"]
        SL.apply_document(engine, doc, actor_user_id=None, typed_version=doc["version"])
        seeded.append((doc["country_code"], doc["table_type"], doc["version"]))

    yield engine

    with engine.begin() as conn:
        for cc, tt, v in seeded:
            row = conn.execute(sa.text(
                "SELECT id FROM statutory_table WHERE country_code=:c AND table_type=:t AND version=:v"
            ), {"c": cc, "t": tt, "v": v}).first()
            if row:
                conn.execute(sa.text("DELETE FROM statutory_table_row WHERE statutory_table_id=:id"), {"id": row[0]})
                conn.execute(sa.text("DELETE FROM statutory_table_load_log WHERE statutory_table_id=:id"), {"id": row[0]})
                conn.execute(sa.text("DELETE FROM statutory_table WHERE id=:id"), {"id": row[0]})


@pytest.fixture()
def ctx(tenant_session, seeded_control_tables):
    session, engine = tenant_session

    # Payroll settings
    session.add(PayrollSettings(
        id=uuid.uuid4(),
        age_reference_date="pay_date",
        sdl_applies=True,
        net_pay_floor=Decimal("0.00"),
        formula_acks={code: {"at": "2025-01-01T00:00:00", "by": "test"}
                      for code in PF.FORMULA_REGISTRY},
        row_version=1,
    ))
    session.commit()

    # One employee
    emp = Employee(
        employee_code=f"PP-{uuid.uuid4().hex[:6]}",
        first_name="A", last_name="Emp",
        hire_date=date(2020, 1, 1), status="active",
        employee_type="hourly", pay_basis="hourly", pay_frequency="monthly",
        medical_scheme_members=0, uif_exempt=False,
        date_of_birth=date(1985, 5, 15),
    )
    session.add(emp)
    session.commit()

    # One earning type + one employee earning
    et = EarningType(
        id=uuid.uuid4(), name="Base", code=f"base-{uuid.uuid4().hex[:6]}",
        calc_method="fixed_amount", frequency="regular",
        is_system=False, is_active=True,
    )
    session.add(et)
    session.commit()

    ee = EmployeeEarning(
        id=uuid.uuid4(), employee_id=emp.id, earning_type_id=et.id,
        amount=Decimal("1000.00"), rate=None,
        effective_from=date(2020, 1, 1), is_active=True,
    )
    session.add(ee)
    session.commit()

    admin = User(
        id=uuid.uuid4(),
        username=f"pa-{uuid.uuid4().hex[:6]}",
        password_hash=hash_password("TestPass123!"),
        role="payroll_admin",
        employee_id=None,
    )
    session.add(admin)
    session.commit()

    period = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"2099-06-{uuid.uuid4().hex[:4]}",
        start_date=date(2099, 6, 1),
        end_date=date(2099, 6, 30),
        pay_date=date(2099, 6, 30),
        status="open",
        cutoff_at=datetime(2099, 6, 30, 12, 0, tzinfo=timezone.utc),
    )
    session.add(period)
    session.commit()

    return SimpleNamespace(
        session=session, engine=engine, emp=emp, et=et, ee=ee,
        admin=admin, period=period,
    )


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------

def test_preview_persists_preview_rows(ctx):
    run = run_preview(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    assert run.kind == "preview"
    assert run.status == "completed"
    previews = ctx.session.query(Payslip).filter_by(
        payroll_run_id=run.id, status="preview",
    ).all()
    assert len(previews) == 1
    assert previews[0].employee_id == ctx.emp.id


def test_preview_reruns_purge_prior(ctx):
    run1 = run_preview(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    run2 = run_preview(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    assert run1.id != run2.id
    # Only one preview run exists
    runs = ctx.session.query(PayrollRun).filter_by(
        pay_period_id=ctx.period.id, kind="preview",
    ).all()
    assert len(runs) == 1
    assert runs[0].id == run2.id


def test_preview_refuses_on_locked_period(ctx):
    finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    with pytest.raises(AppError) as exc_info:
        run_preview(ctx.session, ctx.admin, ctx.period)
    assert exc_info.value.code == "period_locked"


# ---------------------------------------------------------------------------
# Finalise
# ---------------------------------------------------------------------------

def test_finalise_writes_current_payslip(ctx):
    run = finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    assert run.kind == "final"
    payslips = ctx.session.query(Payslip).filter_by(
        pay_period_id=ctx.period.id, status="current",
    ).all()
    assert len(payslips) == 1
    assert ctx.period.status == "locked"


def test_finalise_refuses_when_formulas_unacknowledged(ctx):
    settings = ctx.session.query(PayrollSettings).one()
    settings.formula_acks = {}  # clear acks
    ctx.session.commit()
    with pytest.raises(AppError) as exc_info:
        finalise(ctx.session, ctx.admin, ctx.period)
    assert exc_info.value.code == "formula_unacknowledged"


def test_finalise_refuses_if_already_finalised(ctx):
    finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    with pytest.raises(AppError) as exc_info:
        finalise(ctx.session, ctx.admin, ctx.period)
    assert exc_info.value.code == "period_locked"


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------

def test_reopen_writes_log_and_flips_status(ctx):
    finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    log = reopen(ctx.session, ctx.admin, ctx.period, "correction required")
    ctx.session.commit()
    assert log.reason == "correction required"
    assert ctx.period.status == "open"
    assert log.prior_revision == 1
    assert log.new_revision == 2


def test_reopen_only_most_recent(ctx):
    finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    # Create a later locked period
    later = PayPeriod(
        id=uuid.uuid4(),
        period_key=f"2099-07-{uuid.uuid4().hex[:4]}",
        start_date=date(2099, 7, 1),
        end_date=date(2099, 7, 31),
        pay_date=date(2099, 7, 31),
        status="locked",
        cutoff_at=datetime(2099, 7, 31, 12, 0, tzinfo=timezone.utc),
    )
    ctx.session.add(later)
    ctx.session.commit()
    with pytest.raises(AppError) as exc_info:
        reopen(ctx.session, ctx.admin, ctx.period, "reason")
    assert exc_info.value.code == "later_period_locked"


def test_reopen_refuses_unlocked_period(ctx):
    with pytest.raises(AppError) as exc_info:
        reopen(ctx.session, ctx.admin, ctx.period, "reason")
    assert exc_info.value.code == "period_not_locked"


# ---------------------------------------------------------------------------
# Re-finalise after reopen supersedes prior payslip
# ---------------------------------------------------------------------------

def test_refinalise_after_reopen_supersedes_prior(ctx):
    finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()
    prior = ctx.session.query(Payslip).filter_by(
        pay_period_id=ctx.period.id, status="current",
    ).one()

    reopen(ctx.session, ctx.admin, ctx.period, "correction")
    ctx.session.commit()

    finalise(ctx.session, ctx.admin, ctx.period)
    ctx.session.commit()

    # Prior is superseded, new is current
    ctx.session.refresh(prior)
    assert prior.status == "superseded"
    new = ctx.session.query(Payslip).filter_by(
        pay_period_id=ctx.period.id, status="current",
    ).one()
    assert new.id != prior.id
    assert new.predecessor_payslip_id == prior.id

# END OF FILE

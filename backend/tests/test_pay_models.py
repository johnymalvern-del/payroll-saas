"""Pay schema smoke test (Chapter 4, Bundle 002).

Provisions a fresh tenant (which runs all migrations including 0017) and
verifies all 11 tables and 3 employee columns exist with expected shape.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import sqlalchemy as sa

from app.core.security import hash_password
from app.db.tenant.models.pay import (
    AdvanceRepayment, DeductionType, EarningType, EmployeeDeduction,
    EmployeeEarning, PayPeriod, PayrollRun, Payslip, PayslipLine,
    PeriodAdjustment, PeriodReopenLog,
)
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
    slug = f"pay-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug, name="Pay Test",
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


EXPECTED_TABLES = {
    "earning_type", "deduction_type", "employee_earning", "employee_deduction",
    "pay_period", "period_reopen_log", "period_adjustment", "payroll_run",
    "payslip", "payslip_line", "advance_repayment",
}


def test_all_pay_tables_and_employee_columns_exist(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    try:
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(sa.text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public'"
            ))}
            missing = EXPECTED_TABLES - tables
            assert not missing, f"missing pay tables: {sorted(missing)}"

            emp_cols = {r[0] for r in conn.execute(sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='employee'"
            ))}
            for c in ("contracted_weekly_hours", "medical_scheme_members", "uif_exempt"):
                assert c in emp_cols, f"missing employee column {c}; got {sorted(emp_cols)}"
    finally:
        engine.dispose()


def test_model_classes_wire_to_expected_tables():
    pairs = [
        (EarningType, "earning_type"),
        (DeductionType, "deduction_type"),
        (EmployeeEarning, "employee_earning"),
        (EmployeeDeduction, "employee_deduction"),
        (PayPeriod, "pay_period"),
        (PeriodReopenLog, "period_reopen_log"),
        (PeriodAdjustment, "period_adjustment"),
        (PayrollRun, "payroll_run"),
        (Payslip, "payslip"),
        (PayslipLine, "payslip_line"),
        (AdvanceRepayment, "advance_repayment"),
    ]
    for cls, expected in pairs:
        assert cls.__tablename__ == expected, f"{cls.__name__}.__tablename__ = {cls.__tablename__!r}"


def test_model_columns_present(disposable_tenant):
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    try:
        with engine.connect() as conn:
            for cls in (EarningType, DeductionType, EmployeeEarning, EmployeeDeduction,
                        PayPeriod, PeriodReopenLog, PeriodAdjustment, PayrollRun,
                        Payslip, PayslipLine, AdvanceRepayment):
                cols = {r[0] for r in conn.execute(sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name=:t"
                ), {"t": cls.__tablename__})}
                model_cols = {c.name for c in cls.__table__.columns}
                missing = model_cols - cols
                assert not missing, f"{cls.__tablename__}: model columns not in DB: {sorted(missing)}"
    finally:
        engine.dispose()
# END OF FILE

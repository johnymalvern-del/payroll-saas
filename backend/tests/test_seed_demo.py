"""Chapter 4H B-2: 14 seed-demo tests (session-scoped seed, per-test rollback).

All seed work runs **in-process** in the parent pytest session.
`_seed()` catches SystemExit because demo_seed.main() calls sys.exit(0)
on `--keep` when the tenant already exists.

Two tenant slugs:
  - tenant-demo-test        — session fixture, seeded once, dropped at session end
  - tenant-demo-reset-test  — reset / device-key tests
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.models.attendance import AttendanceDay, ExceptionItem, Punch
from app.db.tenant.models.change_request import PayrollChangeRequest
from app.db.tenant.models.devices import Device
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.pay import PayPeriod
from app.db.tenant.models.people import Employee, User
from app.services.provisioning import _drop_tenant_database, _tenant_db_name


_SESSION_SLUG = "tenant-demo-test"
_RESET_SLUG = "tenant-demo-reset-test"
_BACKEND = Path(__file__).resolve().parent.parent

_TENANT_URL = (
    "postgresql+psycopg://payroll_app:payroll_app_dev_password"
    "@localhost:5432/{db}"
)

_EXPECTED_EXCEPTION_TYPES = {
    "missing_out", "missing_in", "no_shift_match", "low_confidence",
    "absent_expected", "overtime_unapproved", "too_long", "duplicate",
    "device_clock_gap", "employee_query",
}


def _drop_tenant(slug: str) -> None:
    try:
        _drop_tenant_database(_tenant_db_name(slug))
    except Exception:
        pass
    with control_session() as s:
        r = s.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
        if r is not None:
            s.delete(r)


def _seed(slug: str, args: list[str]) -> int:
    """Run demo_seed.main() in-process against the given slug.

    Catches SystemExit because demo_seed._reset_or_keep() calls sys.exit(0)
    on `--keep` when the tenant already exists. Patches demo_seed.get_settings
    to always report development so the production-refusal guard cannot fire
    during content tests.
    """
    from app.seed import demo_seed

    orig_slug = demo_seed.SLUG
    orig_get_settings = demo_seed.get_settings
    dev = type("S", (), {"environment": "development"})()
    demo_seed.SLUG = slug
    demo_seed.get_settings = lambda: dev
    try:
        try:
            return demo_seed.main(args)
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 0
    finally:
        demo_seed.SLUG = orig_slug
        demo_seed.get_settings = orig_get_settings


@pytest.fixture(scope="session")
def tenant_demo_seeded() -> Iterator[str]:
    _drop_tenant(_SESSION_SLUG)
    rc = _seed(_SESSION_SLUG, ["--reset"])
    assert rc == 0, "in-process seed returned non-zero"
    try:
        yield _SESSION_SLUG
    finally:
        _drop_tenant(_SESSION_SLUG)


@pytest.fixture()
def demo_session(tenant_demo_seeded) -> Iterator[Session]:
    url = _TENANT_URL.format(db=_tenant_db_name(tenant_demo_seeded))
    engine = create_engine(url, future=True)
    s = Session(bind=engine)
    try:
        yield s
    finally:
        s.rollback()
        s.close()
        engine.dispose()


def test_seed_refuses_production_env(capfd, monkeypatch):
    from app.seed import demo_seed

    fake = type("S", (), {"environment": "production"})()
    monkeypatch.setattr(demo_seed, "get_settings", lambda: fake)
    with pytest.raises(SystemExit) as exc_info:
        demo_seed._refuse_production()
    assert exc_info.value.code == 1
    out, err = capfd.readouterr()
    blob = (out + err).lower()
    assert "refusing" in blob
    assert "production" in blob


def test_seed_creates_tenant_demo_schema(tenant_demo_seeded):
    with control_session() as s:
        row = s.query(Subscriber).filter(
            Subscriber.slug == tenant_demo_seeded
        ).one_or_none()
        assert row is not None
        assert row.status == "active"


def test_seed_keep_is_noop_when_schema_exists(demo_session):
    emp_before = demo_session.scalar(
        select(Employee).where(Employee.employee_code == "EMP-001")
    )
    assert emp_before is not None

    rc = _seed(_SESSION_SLUG, ["--keep"])
    assert rc == 0

    demo_session.expire_all()
    emp_after = demo_session.scalar(
        select(Employee).where(Employee.employee_code == "EMP-001")
    )
    assert emp_after is not None
    assert emp_after.id == emp_before.id


def test_seed_reset_drops_and_recreates_schema():
    _drop_tenant(_RESET_SLUG)
    try:
        rc = _seed(_RESET_SLUG, ["--reset"])
        assert rc == 0

        url = _TENANT_URL.format(db=_tenant_db_name(_RESET_SLUG))
        e1 = create_engine(url, future=True)
        try:
            with Session(e1) as s1:
                ids1 = {
                    r.employee_code: str(r.id)
                    for r in s1.scalars(select(Employee)).all()
                }
        finally:
            e1.dispose()
        assert len(ids1) == 20

        rc = _seed(_RESET_SLUG, ["--reset"])
        assert rc == 0

        e2 = create_engine(url, future=True)
        try:
            with Session(e2) as s2:
                ids2 = {
                    r.employee_code: str(r.id)
                    for r in s2.scalars(select(Employee)).all()
                }
        finally:
            e2.dispose()
        assert len(ids2) == 20
        assert any(ids1[k] != ids2.get(k) for k in ids1)
    finally:
        _drop_tenant(_RESET_SLUG)


def test_seed_creates_20_employees_fictional_sa_names(demo_session):
    from app.seed.demo_seed import NAMES
    emps = list(demo_session.scalars(select(Employee)).all())
    assert len(emps) == 20
    expected = set(NAMES)
    actual = {(e.first_name, e.last_name) for e in emps}
    assert actual == expected


def test_seed_creates_one_user_per_role_with_known_passwords(demo_session):
    from app.services.auth_service import authenticate

    usernames = {u.username for u in demo_session.scalars(select(User)).all()}
    assert {"admin", "hr", "manager", "auditor", "employee"} <= usernames

    for username in ("admin", "hr", "manager", "auditor", "employee"):
        role = "admin" if username == "admin" else username
        user = authenticate(
            demo_session,
            identifier=username,
            password=f"devpass_{role}",
            ip_address=None,
            user_agent=None,
            request_id=None,
        )
        assert user.username == username


def test_seed_no_user_requires_password_change(demo_session):
    for u in demo_session.scalars(select(User)).all():
        assert u.must_change_password is False


def test_seed_creates_month_of_attendance_using_real_engine(demo_session):
    day_count = demo_session.scalar(
        select(func.count()).select_from(AttendanceDay)
    ) or 0
    assert day_count > 0
    punch_count = demo_session.scalar(
        select(func.count()).select_from(Punch)
    ) or 0
    assert punch_count > 0


def test_seed_exception_spread_covers_all_ten_real_types(demo_session):
    rows = demo_session.execute(
        select(ExceptionItem.type).distinct()
    ).all()
    types = {r[0] for r in rows}
    missing = _EXPECTED_EXCEPTION_TYPES - types
    assert not missing, f"missing exception types: {sorted(missing)}"


def test_seed_creates_one_open_and_one_locked_pay_period(demo_session):
    periods = list(demo_session.scalars(select(PayPeriod)).all())
    assert len(periods) == 2
    assert sorted(p.status for p in periods) == ["locked", "open"]


def test_seed_creates_three_pending_change_requests(demo_session):
    pending = demo_session.scalar(
        select(func.count()).select_from(PayrollChangeRequest).where(
            PayrollChangeRequest.status == "pending"
        )
    ) or 0
    assert pending == 3


def test_seed_device_key_printed_once_and_only_hash_persisted(capfd):
    _drop_tenant(_RESET_SLUG)
    try:
        rc = _seed(_RESET_SLUG, ["--reset"])
        assert rc == 0

        out, err = capfd.readouterr()
        blob = out + err
        assert "DEVICE API KEY" in blob
        assert "ONCE" in blob
        m = re.search(r"\b([0-9a-f]{64})\b", blob)
        assert m, "no 64-hex device key in seed stdout"
        raw_key = m.group(1)

        url = _TENANT_URL.format(db=_tenant_db_name(_RESET_SLUG))
        e = create_engine(url, future=True)
        try:
            with Session(e) as s:
                devices = list(s.scalars(select(Device)).all())
        finally:
            e.dispose()
        assert len(devices) == 1
        dev = devices[0]
        assert dev.api_key_hash
        assert dev.api_key_hash != raw_key
        assert len(dev.api_key_hash) >= 20
    finally:
        _drop_tenant(_RESET_SLUG)


def test_seed_idempotent_with_keep_after_run(tenant_demo_seeded):
    with control_session() as s:
        before = s.query(Subscriber).filter(
            Subscriber.slug == tenant_demo_seeded
        ).count()
    assert before == 1
    rc = _seed(tenant_demo_seeded, ["--keep"])
    assert rc == 0
    with control_session() as s:
        after = s.query(Subscriber).filter(
            Subscriber.slug == tenant_demo_seeded
        ).count()
    assert after == 1


def test_seed_no_direct_orm_punch_insertions():
    seed_path = _BACKEND / "app" / "seed" / "demo_seed.py"
    tree = ast.parse(seed_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Punch"
        ):
            raise AssertionError(
                f"demo_seed.py contains a direct Punch(...) call at line "
                f"{node.lineno}; seed must use _process_punch for all punches"
            )
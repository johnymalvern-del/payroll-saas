"""Session-scoped test infrastructure for the payroll backend.

Creates a fresh `payroll_control_test` database at session start, runs the
control migrations against it programmatically, points the application at
it for the whole session via environment overrides, and drops it when the
session ends.

If migrations fail, pytest exits immediately with a clear message and the
actual error — no silent skips, no empty-database false negatives.

The production control DB (`payroll_control`) is never touched by tests.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent

TEST_CONTROL_DB = "payroll_control_test"

TEST_CONTROL_URL = (
    f"postgresql+psycopg://payroll_app:payroll_app_dev_password"
    f"@localhost:5432/{TEST_CONTROL_DB}"
)

def _bootstrap_env() -> None:
    """Point app settings at the test control database and its admin template."""
    os.environ["DATABASE_URL_CONTROL"] = TEST_CONTROL_URL
    os.environ["DATABASE_URL_CONTROL_ADMIN"] = TEST_CONTROL_URL
    os.environ.setdefault(
        "DATABASE_URL_TENANT_TEMPLATE",
        "postgresql+psycopg://payroll_app:payroll_app_dev_password@localhost:5432/{tenant_db}",
    )
    os.environ.setdefault(
        "DATABASE_URL_TENANT_ADMIN_TEMPLATE",
        "postgresql+psycopg://payroll_test:payroll_test_dev_password@localhost:5432/{tenant_db}",
    )

_bootstrap_env()

def _admin_url(db_name: str = "postgres") -> str:
    return (
        f"postgresql+psycopg://payroll_test:payroll_test_dev_password"
        f"@localhost:5432/{db_name}"
    )

def _create_database(db_name: str, owner: str = "payroll_app") -> None:
    engine = create_engine(_admin_url("postgres"), isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            exists = conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": db_name}
            )
            if exists:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :d AND pid <> pg_backend_pid()"
                    ),
                    {"d": db_name},
                )
                conn.execute(text(f'DROP DATABASE "{db_name}"'))
            conn.execute(text(f'CREATE DATABASE "{db_name}" OWNER {owner}'))
    finally:
        engine.dispose()

def _drop_database(db_name: str) -> None:
    engine = create_engine(_admin_url("postgres"), isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ),
                {"d": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        engine.dispose()

def _run_control_migrations() -> None:
    cfg = Config(str(BASE_DIR / "alembic.ini"), ini_section="control")
    cfg.set_main_option("sqlalchemy.url", TEST_CONTROL_URL)
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:
        pytest.exit(
            "\n"
            "=============================================================\n"
            f"FATAL: control migrations FAILED against {TEST_CONTROL_DB}\n"
            "=============================================================\n"
            f"{type(exc).__name__}: {exc}\n",
            returncode=2,
        )

def _assert_subscriber_table(engine: Engine) -> None:
    with engine.connect() as conn:
        present = conn.scalar(text("SELECT to_regclass('public.subscriber')"))
    if present is None:
        pytest.exit(
            "\n"
            "=============================================================\n"
            f"FATAL: subscriber table missing from {TEST_CONTROL_DB}\n"
            "=============================================================\n",
            returncode=2,
        )

@pytest.fixture(scope="session", autouse=True)
def _control_test_database() -> Iterator[None]:
    """Create payroll_control_test, migrate it, yield, drop it on exit."""
    _create_database(TEST_CONTROL_DB, owner="payroll_app")
    engine = create_engine(TEST_CONTROL_URL, future=True)
    try:
        _run_control_migrations()
        _assert_subscriber_table(engine)
        yield
    finally:
        engine.dispose()
        _drop_database(TEST_CONTROL_DB)

@pytest.fixture(scope="session")
def tenant_db_name() -> Iterator[str]:
    """Create one ephemeral tenant DB per session, migrate it, drop at end."""
    name = f"payroll_test_{uuid.uuid4().hex[:12]}"
    _create_database(name, owner="payroll_app")
    try:
        tenant_admin_url = (
            f"postgresql+psycopg://payroll_test:payroll_test_dev_password"
            f"@localhost:5432/{name}"
        )
        cfg = Config(str(BASE_DIR / "alembic.ini"), ini_section="tenant")
        cfg.set_main_option("sqlalchemy.url", tenant_admin_url)
        try:
            command.upgrade(cfg, "head")
        except Exception as exc:
            pytest.exit(
                f"\nFATAL: tenant migrations failed for {name}:\n"
                f"{type(exc).__name__}: {exc}\n",
                returncode=2,
            )
        yield name
    finally:
        _drop_database(name)

@pytest.fixture(scope="session")
def tenant_engine_admin(tenant_db_name: str) -> Iterator[Engine]:
    url = (
        f"postgresql+psycopg://payroll_test:payroll_test_dev_password"
        f"@localhost:5432/{tenant_db_name}"
    )
    engine = create_engine(url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()

@pytest.fixture(scope="session")
def tenant_engine_app(tenant_db_name: str) -> Iterator[Engine]:
    url = (
        f"postgresql+psycopg://payroll_app:payroll_app_dev_password"
        f"@localhost:5432/{tenant_db_name}"
    )
    engine = create_engine(url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()

@pytest.fixture()
def inserted_audit_row(tenant_engine_app: Engine) -> str:
    row_id = str(uuid.uuid4())
    with tenant_engine_app.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO audit_log (id, entity_type, entity_id, action, request_id) "
                "VALUES (:id, 'test.entity', 'x', 'created', 'test-req')"
            ),
            {"id": row_id},
        )
    return row_id


# ---------------------------------------------------------------------------
# Shared FastAPI TestClient for endpoint tests.
# Provided here rather than in a per-module fixture so every test module that
# needs an HTTP client can just declare `api_client` as a parameter.
# ---------------------------------------------------------------------------

import pytest as _pytest_api_client
from fastapi.testclient import TestClient as _TestClient
from app.main import app as _app


@_pytest_api_client.fixture()
def api_client():
    with _TestClient(_app) as client:
        yield client

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# RATE LIMITER BYPASS FOR PYTEST (1C.6.2)
#
# History:
#   1C.6.1 installed an always-allow limiter for the WHOLE session, which
#   broke tests/test_auth_endpoints.py::test_rate_limit_returns_429: that
#   test's `_reset_rate_limiter` autouse fixture wipes `_events` on the real
#   InMemoryRateLimiter, and the always-allow object has no `_events`, so the
#   fixture silently did nothing, the 25 failed logins were not counted, and
#   AuthLockedError (423) fired before the rate limit (429) could.
#
#   1C.6.2 scopes the bypass per test: any test whose module is NOT in
#   _REAL_LIMITER_MODULES gets the always-allow limiter; tests in the real-
#   limiter set get the actual limiter and their own fixtures (e.g.
#   test_auth_endpoints._reset_rate_limiter) work unchanged.
#
# The production code is untouched. `get_rate_limiter` remains the factory
# the production code calls; the bypass only replaces the cached instance
# for the duration of a test that is not in the real-limiter set.
# ---------------------------------------------------------------------------


import pytest as _pytest_rl


# Modules that exercise the real rate limiter and must NOT be bypassed.
# Add to this set if a future test also needs the real limiter.
_REAL_LIMITER_MODULES: frozenset[str] = frozenset({
    "test_auth_endpoints.py",
    "test_rate_limiter.py",
})


class _AlwaysAllowRateLimiter:
    def hit(self, key: str, limit: int, window_seconds: int) -> bool:
        return True


@_pytest_rl.fixture(scope="session", autouse=True)
def _save_rate_limiter_factory():
    """Save the real _build at session start; restore it on teardown."""
    from app.core.rate_limiter import factory as _rl_factory
    _original = _rl_factory._build
    try:
        yield _original
    finally:
        _rl_factory._build = _original
        _rl_factory.get_rate_limiter.cache_clear()


@_pytest_rl.fixture(autouse=True)
def _bypass_rate_limiter_unless_real(request, _save_rate_limiter_factory):
    """Install the always-allow limiter for tests that are not in the
    real-limiter set; leave the real limiter in place otherwise."""
    from pathlib import Path
    from app.core.rate_limiter import factory as _rl_factory

    module_file = getattr(request.node, "fspath", None)
    module_name = Path(str(module_file)).name if module_file is not None else ""

    if module_name in _REAL_LIMITER_MODULES:
        # Leave the real limiter installed; the module's own fixtures
        # (e.g. _reset_rate_limiter) manage it.
        yield
        return

    original = _save_rate_limiter_factory
    _rl_factory._build = lambda _settings: _AlwaysAllowRateLimiter()
    _rl_factory.get_rate_limiter.cache_clear()
    try:
        yield
    finally:
        _rl_factory._build = original
        _rl_factory.get_rate_limiter.cache_clear()


# --- 4A-bis: _4A_BIS_CONFTEST: fast/slow markers + template bootstrap + migration swap ---
import os as _os_4a_cf
import pytest as _pytest_4a_cf

_4a_orig_configure = globals().get("pytest_configure")
def pytest_configure(config):
    config.addinivalue_line("markers", "slow: provisions a tenant; -m 'not slow' skips in mid-chapter runs")
    config.addinivalue_line("markers", "fast: pure logic; included in mid-chapter runs")
    if _4a_orig_configure:
        _4a_orig_configure(config)

_4a_orig_modifyitems = globals().get("pytest_collection_modifyitems")
def pytest_collection_modifyitems(config, items):
    if _4a_orig_modifyitems:
        _4a_orig_modifyitems(config, items)
    for _4a_it in items:
        _4a_names = getattr(_4a_it, "fixturenames", []) or []
        if "disposable_tenant" in _4a_names:
            _4a_it.add_marker(_pytest_4a_cf.mark.slow)
        else:
            _4a_it.add_marker(_pytest_4a_cf.mark.fast)

_4a_orig_start = globals().get("pytest_sessionstart")
def pytest_sessionstart(session):
    if _4a_orig_start:
        _4a_orig_start(session)
    if _os_4a_cf.environ.get("PAYROLL_TEST_TEMPLATE_DB") == "1":
        from app.services import provisioning as _4a_p
        _4a_p._TEST_TEMPLATE_ENABLED = True
        _4a_p._run_tenant_migrations = _4a_p._4a_run_migrations_from_template

@pytest.fixture(scope="session", autouse=True)
def _4a_bootstrap_template():
    if _os_4a_cf.environ.get("PAYROLL_TEST_TEMPLATE_DB") == "1":
        from app.services import provisioning as _4a_p
        _4a_p._TEST_TEMPLATE_ENABLED = True
        _4a_p._run_tenant_migrations = _4a_p._4a_run_migrations_from_template
        _4a_p._4a_bootstrap_template_db()
    yield
# --- end ---

# END OF FILE

# _4A_BIS_010B conftest

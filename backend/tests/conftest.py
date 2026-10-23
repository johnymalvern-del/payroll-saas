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
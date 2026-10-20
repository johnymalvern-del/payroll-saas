"""Test configuration: create and tear down a real tenant DB for each session."""
from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _admin_template() -> str:
    url = os.environ.get("DATABASE_URL_TENANT_ADMIN_TEMPLATE")
    if not url:
        pytest.skip("DATABASE_URL_TENANT_ADMIN_TEMPLATE is not set")
    return url


def _app_template() -> str:
    url = os.environ.get("DATABASE_URL_TENANT_TEMPLATE")
    if not url:
        pytest.skip("DATABASE_URL_TENANT_TEMPLATE is not set")
    return url


@pytest.fixture(scope="session")
def tenant_db_name() -> Iterator[str]:
    """Create an ephemeral tenant database, migrate it, drop it at the end."""
    name = f"payroll_test_{uuid.uuid4().hex[:12]}"
    admin_url = _admin_template().format(tenant_db="postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        tenant_admin_url = _admin_template().format(tenant_db=name)
        cfg = Config(os.path.join(BASE_DIR, "alembic.ini"), ini_section="tenant")
        cfg.set_main_option("sqlalchemy.url", tenant_admin_url)
        command.upgrade(cfg, "head")
        yield name
    finally:
        try:
            with admin_engine.connect() as conn:
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :d AND pid <> pg_backend_pid()"
                    ),
                    {"d": name},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        finally:
            admin_engine.dispose()


@pytest.fixture(scope="session")
def tenant_engine_admin(tenant_db_name: str) -> Iterator[Engine]:
    url = _admin_template().format(tenant_db=tenant_db_name)
    engine = create_engine(url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def tenant_engine_app(tenant_db_name: str) -> Iterator[Engine]:
    url = _app_template().format(tenant_db=tenant_db_name)
    engine = create_engine(url, future=True)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def inserted_audit_row(tenant_engine_app: Engine) -> str:
    """Insert one audit_log row as the app role; returns its id."""
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
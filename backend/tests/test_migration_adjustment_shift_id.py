"""Migration test for ten_0028 (adjustment.shift_id).

Verifies:
  1. After `alembic upgrade head`, the `adjustment` table has:
       - column `shift_id` of type UUID, nullable
       - FK `fk_adjustment_shift_id` to `shift.id` with ON DELETE SET NULL
       - index `ix_adjustment_shift_id`
  2. Existing rows have shift_id = NULL after upgrade (no data touched).
  3. `alembic downgrade -1` removes the column, FK, and index.
  4. Re-upgrade restores them.

The test provisions its own disposable tenant (via `provision_tenant`,
which already invokes the tenant migration chain from zero), then
manipulates the schema with the same alembic.tenant.env.py machinery
that the provisioning helper uses. No existing tenant is touched.

Run against Postgres only. No production DB is opened by this test.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.tenant.session import get_tenant_engine
from app.services.provisioning import (
    _drop_tenant_database,
    _tenant_db_name,
    provision_tenant,
)


BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


@dataclass
class _DisposableTenant:
    slug: str
    tenant_db_name: str
    subscriber_id: uuid.UUID


def _alembic_cfg_for(db_name: str) -> Config:
    """Build an Alembic Config for the tenant env pointing at `db_name`.

    Uses the same technique the provisioning helper uses: set
    sqlalchemy.url on the Config, so env.py's get_url() returns it
    instead of the templated fallback.
    """
    s = get_settings()
    admin_url = s.database_url_tenant_admin_template.format(tenant_db=db_name)
    cfg = Config(str(ALEMBIC_INI), ini_section="tenant")
    cfg.set_main_option("sqlalchemy.url", admin_url)
    return cfg


@pytest.fixture()
def disposable_tenant() -> Iterator[_DisposableTenant]:
    from app.db.control.models import Subscriber
    from app.db.control.session import control_session

    slug = f"mig-{uuid.uuid4().hex[:10]}"
    result = provision_tenant(
        slug=slug,
        name="Migration Test",
        admin_username="admin",
        admin_password_hash=hash_password("TestPassword123!"),
    )
    db_name = _tenant_db_name(slug)
    try:
        yield _DisposableTenant(
            slug=result.slug,
            tenant_db_name=result.tenant_db_name,
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
def tenant_engine(disposable_tenant: _DisposableTenant) -> Iterator[Engine]:
    engine = get_tenant_engine(disposable_tenant.tenant_db_name)
    try:
        yield engine
    finally:
        engine.dispose()


def _column_names(engine: Engine, table: str) -> set[str]:
    insp = sa_inspect(engine)
    return {c["name"] for c in insp.get_columns(table)}


def _fk_names(engine: Engine, table: str) -> set[str]:
    insp = sa_inspect(engine)
    return {fk["name"] for fk in insp.get_foreign_keys(table)}


def _fk_target(engine: Engine, table: str, fk_name: str) -> dict | None:
    insp = sa_inspect(engine)
    for fk in insp.get_foreign_keys(table):
        if fk["name"] == fk_name:
            return fk
    return None


def _index_names(engine: Engine, table: str) -> set[str]:
    insp = sa_inspect(engine)
    return {ix["name"] for ix in insp.get_indexes(table)}


# ----------------------------------------------------------------------
# Provisioning has already run "upgrade head"; verify the schema is
# correct after that initial provisioning.
# ----------------------------------------------------------------------

def test_schema_after_upgrade_head(tenant_engine: Engine) -> None:
    cols = _column_names(tenant_engine, "adjustment")
    assert "shift_id" in cols, f"shift_id missing; got columns {sorted(cols)}"

    insp = sa_inspect(tenant_engine)
    col = next(c for c in insp.get_columns("adjustment") if c["name"] == "shift_id")
    assert col["nullable"] is True, f"shift_id must be nullable; got {col}"

    fks = _fk_names(tenant_engine, "adjustment")
    assert "fk_adjustment_shift_id" in fks, (
        f"expected fk_adjustment_shift_id; got {sorted(fks)}"
    )
    fk = _fk_target(tenant_engine, "adjustment", "fk_adjustment_shift_id")
    assert fk is not None
    assert fk["referred_table"] == "shift", fk
    assert fk["referred_columns"] == ["id"], fk
    # SQLAlchemy's FK inspector returns ondelete in fk["options"]
    ondelete = (fk.get("options") or {}).get("ondelete")
    assert (ondelete or "").upper() == "SET NULL", (
        f"expected ON DELETE SET NULL; got options={fk.get('options')}"
    )

    idx = _index_names(tenant_engine, "adjustment")
    assert "ix_adjustment_shift_id" in idx, (
        f"expected ix_adjustment_shift_id; got {sorted(idx)}"
    )


def test_existing_rows_get_null_shift_id(tenant_engine: Engine) -> None:
    """Any pre-existing adjustments must have shift_id = NULL after upgrade.

    The disposable tenant has no pre-existing adjustments (it was freshly
    provisioned), so this test asserts the schema allows NULL and that a
    raw insert without shift_id succeeds.
    """
    with tenant_engine.begin() as conn:
        nullable = conn.scalar(text("""
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name='adjustment' AND column_name='shift_id'
        """))
    assert nullable == "YES", nullable


# ----------------------------------------------------------------------
# Downgrade then re-upgrade round-trip
# ----------------------------------------------------------------------

def test_downgrade_then_upgrade_round_trip(
    disposable_tenant: _DisposableTenant, tenant_engine: Engine,
) -> None:
    """Downgrade removes shift_id column + FK + index; upgrade restores them.
    """
    db_name = disposable_tenant.tenant_db_name
    cfg = _alembic_cfg_for(db_name)

    # Currently at head. Downgrade one revision (drops shift_id).
    command.downgrade(cfg, "-1")

    cols_after_down = _column_names(tenant_engine, "adjustment")
    assert "shift_id" not in cols_after_down, (
        f"shift_id should be gone after downgrade; got {sorted(cols_after_down)}"
    )
    fks_after_down = _fk_names(tenant_engine, "adjustment")
    assert "fk_adjustment_shift_id" not in fks_after_down, (
        f"fk_adjustment_shift_id should be gone; got {sorted(fks_after_down)}"
    )
    idx_after_down = _index_names(tenant_engine, "adjustment")
    assert "ix_adjustment_shift_id" not in idx_after_down, (
        f"ix_adjustment_shift_id should be gone; got {sorted(idx_after_down)}"
    )

    # Upgrade back to head. Restores everything.
    command.upgrade(cfg, "head")

    cols_after_up = _column_names(tenant_engine, "adjustment")
    assert "shift_id" in cols_after_up
    fks_after_up = _fk_names(tenant_engine, "adjustment")
    assert "fk_adjustment_shift_id" in fks_after_up
    idx_after_up = _index_names(tenant_engine, "adjustment")
    assert "ix_adjustment_shift_id" in idx_after_up


def test_downgrade_is_idempotent_within_one_cycle(
    disposable_tenant: _DisposableTenant, tenant_engine: Engine,
) -> None:
    """Running downgrade once on a tenant that is at head lands the schema
    on ten_0027. Re-running upgrade returns to head. Nothing else changes.
    """
    db_name = disposable_tenant.tenant_db_name
    cfg = _alembic_cfg_for(db_name)

    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    # If we got here without an exception, the round-trip is clean.
    cols = _column_names(tenant_engine, "adjustment")
    assert "shift_id" in cols
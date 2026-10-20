"""migrate-all: dry-run safety, per-tenant failure isolation, exit code."""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine, text

from app.core.security import hash_password  # noqa: F401
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.scripts import migrate_all as migrate_all_mod
from app.services import provisioning as provisioning_mod


def _create_broken_subscriber() -> Subscriber:
    """Active subscriber pointing at a non-existent DB — migrate_all will fail on it."""
    slug = f"broken-{uuid.uuid4().hex[:8]}"
    db_name = f"tenant_{slug.replace('-', '_')}"
    with control_session() as session:
        sub = Subscriber(
            slug=slug,
            name="Broken Co",
            country_code="ZA",
            status="active",
            provisioning_status="active",
            tenant_db_name=db_name,
            tenant_schema_version="ten_0001",
            encryption_key_encrypted="unused-for-this-test",
        )
        session.add(sub)
        session.flush()
        session.refresh(sub)
        return sub


def _delete_subscriber(sub_id: uuid.UUID) -> None:
    with control_session() as session:
        row = session.get(Subscriber, sub_id)
        if row is not None:
            session.delete(row)


def _read_schema_version(db_name: str) -> str | None:
    engine = create_engine(provisioning_mod._admin_url(db_name), future=True)
    try:
        with engine.connect() as conn:
            return conn.scalar(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            )
    finally:
        engine.dispose()


def test_migrate_all_dry_run_reports_without_changing(disposable_tenant) -> None:
    """A tenant already at head must be reported as 'skipped', never modified."""
    before = _read_schema_version(disposable_tenant.tenant_db_name)
    exit_code = migrate_all_mod.main(
        ["--dry-run", "--slug", disposable_tenant.slug]
    )
    after = _read_schema_version(disposable_tenant.tenant_db_name)
    assert exit_code == 0
    assert before == after == "ten_0001"


def test_migrate_all_isolates_single_failure(two_tenants) -> None:
    """One broken tenant fails; healthy tenants still migrate and the CLI exits 1."""
    a, b = two_tenants
    broken = _create_broken_subscriber()
    try:
        # Force the healthy tenants one revision behind so migrate_all has work.
        with control_session() as session:
            for slug in (a.slug, b.slug):
                row = (
                    session.query(Subscriber)
                    .filter(Subscriber.slug == slug)
                    .one()
                )
                row.tenant_schema_version = "ten_0000"

        # Run across ALL tenants while the broken one exists.
        exit_code = migrate_all_mod.main([])
        assert exit_code == 1  # broken tenant fails

        # Healthy tenants are back at head, unaffected.
        for t in (a, b):
            with control_session() as session:
                row = (
                    session.query(Subscriber)
                    .filter(Subscriber.slug == t.slug)
                    .one()
                )
                assert row.tenant_schema_version == "ten_0001"
                assert row.status == "active"
            assert _read_schema_version(t.tenant_db_name) == "ten_0001"
    finally:
        _delete_subscriber(broken.id)
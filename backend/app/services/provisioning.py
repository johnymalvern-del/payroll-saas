"""Tenant provisioning: creates the tenant database, runs migrations, seeds
defaults, creates the first admin user, and records the schema version.

Full rollback on any failure: the subscriber row is created first as
'provisioning', all DB work happens, then the row is updated to 'active'.
On error, the tenant DB is dropped and the subscriber row is marked
'failed' with the error message.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.encryption import new_tenant_key, seal_with_master

log = get_logger("app.services.provisioning")


class ProvisioningError(Exception):
    """Raised when a tenant cannot be provisioned. All side effects are rolled back."""


@dataclass(frozen=True)
class ProvisioningResult:
    subscriber_id: uuid.UUID
    slug: str
    tenant_db_name: str
    schema_version: str


import re

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")

_RESERVED_SLUGS: frozenset[str] = frozenset(
    {"www", "api", "admin", "app", "static", "platform", "control", "payroll", "mail", "ftp"}
)


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ProvisioningError(
            f"Invalid slug '{slug}': must match [a-z0-9][a-z0-9-]*, 2-61 chars"
        )
    if slug in _RESERVED_SLUGS:
        raise ProvisioningError(f"Slug '{slug}' is reserved")


def _tenant_db_name(slug: str) -> str:
    name = f"tenant_{slug.replace('-', '_')}"
    if len(name) > 63:
        raise ProvisioningError(f"Slug too long for PostgreSQL database name: {slug!r}")
    return name


def _admin_url(db_name: str = "postgres") -> str:
    return get_settings().database_url_tenant_admin_template.format(tenant_db=db_name)


def _run_tenant_migrations(db_name: str) -> str:
    """Apply all tenant migrations to the named database. Return resulting revision."""
    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"), ini_section="tenant")
    cfg.set_main_option("sqlalchemy.url", _admin_url(db_name))
    command.upgrade(cfg, "head")

    engine = create_engine(_admin_url(db_name), future=True)
    try:
        with engine.connect() as conn:
            version = conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    finally:
        engine.dispose()

    if not version:
        raise ProvisioningError("Tenant migrations completed but alembic_version is empty")
    return str(version)


def _seed_tenant_defaults(db_name: str, company_name: str) -> None:
    """Insert the singleton company row with ZA defaults."""
    engine = create_engine(_admin_url(db_name), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO company "
                    "(id, legal_name, country_code, currency, default_timezone, settings) "
                    "VALUES (:id, :name, 'ZA', 'ZAR', 'Africa/Johannesburg', '{}'::jsonb)"
                ),
                {"id": str(uuid.uuid4()), "name": company_name},
            )
    finally:
        engine.dispose()


def _create_first_admin(db_name: str, username: str, password_hash: str) -> None:
    """Insert the first payroll_admin user with must_change_password=true."""
    engine = create_engine(_admin_url(db_name), future=True)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    'INSERT INTO "user" '
                    "(id, username, password_hash, role, is_active, must_change_password) "
                    "VALUES (:id, :u, :p, 'payroll_admin', true, true)"
                ),
                {"id": str(uuid.uuid4()), "u": username, "p": password_hash},
            )
    finally:
        engine.dispose()


def _drop_tenant_database(db_name: str) -> None:
    """Forcefully drop a tenant database. Used only during provisioning rollback."""
    admin_engine = create_engine(
        _admin_url("postgres"), isolation_level="AUTOCOMMIT", future=True
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :d AND pid <> pg_backend_pid()"
                ),
                {"d": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    finally:
        admin_engine.dispose()


def provision_tenant(
    *,
    slug: str,
    name: str,
    admin_username: str,
    admin_password_hash: str,
) -> ProvisioningResult:
    """Provision a new tenant end-to-end.

    Steps:
      1. Reserve the subscriber row (slug uniqueness protects against races).
      2. Create the tenant database.
      3. Apply all tenant migrations.
      4. Seed the singleton company row.
      5. Create the first payroll_admin user (must_change_password=true).
      6. Mark the subscriber active and record the schema version.

    Any failure drops the tenant database (if created) and marks the
    subscriber 'failed' with the error message. The function raises
    ProvisioningError so callers can surface a clean API response.
    """
    _validate_slug(slug)

    tenant_key = new_tenant_key()
    key_encrypted = seal_with_master(tenant_key.decode("ascii"))
    db_name = _tenant_db_name(slug)

    # Step 1: reserve the subscriber row
    with control_session() as session:
        existing = session.query(Subscriber).filter(Subscriber.slug == slug).one_or_none()
        if existing is not None:
            raise ProvisioningError(f"Slug '{slug}' is already taken")
        subscriber = Subscriber(
            slug=slug,
            name=name,
            country_code="ZA",
            status="provisioning",
            provisioning_status="pending",
            tenant_db_name=db_name,
            encryption_key_encrypted=key_encrypted,
        )
        session.add(subscriber)
        session.flush()
        subscriber_id = subscriber.id

    log.info(
        "tenant.provisioning.start",
        subscriber_id=str(subscriber_id),
        slug=slug,
        db=db_name,
    )

    try:
        # Step 2: create the tenant database
        admin_engine = create_engine(
            _admin_url("postgres"), isolation_level="AUTOCOMMIT", future=True
        )
        try:
            with admin_engine.connect() as conn:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        finally:
            admin_engine.dispose()

        # Step 3: run tenant migrations
        schema_version = _run_tenant_migrations(db_name)

        # Step 4: seed tenant defaults
        _seed_tenant_defaults(db_name, name)

        # Step 5: create the first admin
        _create_first_admin(db_name, admin_username, admin_password_hash)

        # Step 6: mark active
        with control_session() as session:
            sub = session.get(Subscriber, subscriber_id)
            if sub is None:
                raise ProvisioningError(
                    "Subscriber row disappeared mid-provisioning"
                )
            sub.status = "active"
            sub.provisioning_status = "active"
            sub.tenant_schema_version = schema_version
            sub.provisioning_error = None

        log.info(
            "tenant.provisioning.done",
            subscriber_id=str(subscriber_id),
            slug=slug,
            db=db_name,
            schema_version=schema_version,
        )
        return ProvisioningResult(
            subscriber_id=subscriber_id,
            slug=slug,
            tenant_db_name=db_name,
            schema_version=schema_version,
        )

    except Exception as exc:
        log.exception(
            "tenant.provisioning.failed",
            subscriber_id=str(subscriber_id),
            slug=slug,
        )
        # Roll back: drop the tenant DB if we created it, mark subscriber failed
        try:
            _drop_tenant_database(db_name)
        except Exception:
            log.exception("tenant.provisioning.rollback.drop_failed", db_name=db_name)
        with control_session() as session:
            sub = session.get(Subscriber, subscriber_id)
            if sub is not None:
                sub.status = "failed"
                sub.provisioning_status = "failed"
                sub.provisioning_error = str(exc)[:500]
        raise ProvisioningError(str(exc)) from exc
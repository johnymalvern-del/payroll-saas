"""Apply pending tenant migrations to every active subscriber.

Per-tenant failure isolation: one tenant failing must not block the others.
`--dry-run` reports what would be migrated without changing anything.
On success, records each tenant's schema version in the control DB.

Usage:
    python -m app.scripts.migrate_all
    python -m app.scripts.migrate_all --dry-run
    python -m app.scripts.migrate_all --slug demo
    python -m app.scripts.migrate_all --include-inactive
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.tenant_routing import get_head_revision
from app.db.control.models import Subscriber
from app.db.control.session import control_session

log = get_logger("app.scripts.migrate_all")


@dataclass
class TenantResult:
    slug: str
    db_name: str
    before: str | None
    after: str | None
    status: str  # skipped | migrated | would-migrate | failed
    error: str | None = None


def _admin_url(db_name: str) -> str:
    return get_settings().database_url_tenant_admin_template.format(tenant_db=db_name)


def _current_version(db_name: str) -> str | None:
    engine = create_engine(_admin_url(db_name), future=True)
    try:
        with engine.connect() as conn:
            try:
                return conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
            except Exception:
                return None
    finally:
        engine.dispose()


def _migrate_one(db_name: str) -> str | None:
    backend_dir = Path(__file__).resolve().parent.parent.parent
    cfg = AlembicConfig(str(backend_dir / "alembic.ini"), ini_section="tenant")
    cfg.set_main_option("sqlalchemy.url", _admin_url(db_name))
    command.upgrade(cfg, "head")
    return _current_version(db_name)


def _process_tenant(sub: Subscriber, head: str, dry_run: bool) -> TenantResult:
    if not sub.tenant_db_name:
        return TenantResult(sub.slug, "", None, None, "failed", "tenant_db_name is null")
    try:
        before = _current_version(sub.tenant_db_name)
        if before == head:
            return TenantResult(sub.slug, sub.tenant_db_name, before, before, "skipped")
        if dry_run:
            return TenantResult(sub.slug, sub.tenant_db_name, before, head, "would-migrate")
        after = _migrate_one(sub.tenant_db_name)
        return TenantResult(sub.slug, sub.tenant_db_name, before, after, "migrated")
    except Exception as exc:
        return TenantResult(sub.slug, sub.tenant_db_name, None, None, "failed", str(exc)[:500])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply pending tenant migrations to all eligible subscribers."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be migrated without changing anything")
    parser.add_argument("--slug", help="Restrict to a single tenant slug")
    parser.add_argument("--include-inactive", action="store_true",
                        help="Also include non-active subscribers")
    args = parser.parse_args(argv)

    configure_logging()
    head = get_head_revision()
    log.info("migrate_all.start", head=head, dry_run=args.dry_run, only_slug=args.slug)

    with control_session() as session:
        q = session.query(Subscriber)
        if not args.include_inactive:
            q = q.filter(Subscriber.status == "active")
        if args.slug:
            q = q.filter(Subscriber.slug == args.slug)
        subscribers = list(q.order_by(Subscriber.slug).all())

    if not subscribers:
        log.info("migrate_all.no_subscribers")
        return 0

    results: list[TenantResult] = []
    for sub in subscribers:
        res = _process_tenant(sub, head, args.dry_run)
        results.append(res)
        log.info(
            "migrate_all.tenant",
            slug=res.slug, status=res.status,
            before=res.before, after=res.after, error=res.error,
        )
       
        if res.after is not None:
            with control_session() as session:
                row = session.query(Subscriber).filter(Subscriber.slug == res.slug).one()
                if row.tenant_schema_version != res.after:
                    row.tenant_schema_version = res.after

    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    log.info("migrate_all.summary", counts=counts, total=len(results))

    failed = [r for r in results if r.status == "failed"]
    if failed:
        log.error(
            "migrate_all.failed",
            count=len(failed),
            slugs=[r.slug for r in failed],
            errors=[r.error for r in failed],
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
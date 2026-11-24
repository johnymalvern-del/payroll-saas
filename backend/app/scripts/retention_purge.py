"""Attendance coordinate retention sweep (privacy policy section 5).

Deletes expired punch_location rows across one or all tenants, leaving the
punch and its geofence verdict intact. Intended to be run nightly from
Windows Task Scheduler.

    # report only (this is the default)
    python -m app.scripts.retention_purge --dry-run

    # purge, all tenants
    python -m app.scripts.retention_purge --confirm

    # purge, one tenant
    python -m app.scripts.retention_purge --confirm --tenant tenant-demo

Exit codes:

    0  every tenant swept, post-check found nothing left
    1  at least one tenant raised
    2  a sweep completed but expired rows remain afterwards

Exit 2 exists because a purge that silently deletes nothing is
indistinguishable from one that works. The post-check is what turns
"retention is running" from a belief into a fact, and a non-zero code is
what makes Task Scheduler surface it.

Tenant selection uses a DENYLIST, not an allowlist. A retention obligation
must fail toward sweeping too much: if a new subscriber status is introduced
later (suspended, trial, ...), an allowlist would silently stop purging
coordinates for those tenants and nobody would notice. Skipping only the
states that provably have no tenant database -- deleted, provisioning,
failed -- keeps unknown states in scope.

An active subscriber whose database is missing still fails loudly. That is
correct: it is a real inconsistency, not noise to be filtered away.

There is no scheduler inside this application. refresh_cleanup.py has the
same gap and has never been invoked: JobRunner exposes only enqueue() and
status(), and InProcessRunner loses in-flight jobs on restart, so it cannot
be trusted with a deletion obligation. External scheduling is the honest
choice here.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.core.logging import configure_logging, get_logger
from app.db.control.models import Subscriber
from app.db.control.session import control_session
from app.db.tenant.session import tenant_session
from app.services.attendance_retention import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_RETENTION_DAYS,
    count_expired_with_coordinates,
    purge_expired_coordinates,
)

log = get_logger("app.scripts.retention_purge")

# Subscriber states that provably have no tenant database to sweep.
# Everything else is in scope -- see the module docstring for why this is a
# denylist rather than an allowlist.
_SKIP_STATUSES = ("deleted", "provisioning", "failed")


def _active_tenants(only: str | None = None) -> list[tuple[str, str]]:
    """(slug, tenant_db_name) for every tenant worth sweeping.

    Skips rows with no database name and rows in a state that cannot have a
    database. An `active` row pointing at a missing database is NOT skipped:
    the connection error is a genuine finding and the run should exit
    non-zero because of it.

    Returns a plain list rather than ORM objects so the control session can
    close before any tenant work starts.
    """
    with control_session() as session:
        q = session.query(Subscriber).filter(
            Subscriber.tenant_db_name.is_not(None),
            Subscriber.status.notin_(_SKIP_STATUSES),
        )
        if only is not None:
            q = q.filter(Subscriber.slug == only)
        rows = q.order_by(Subscriber.slug).all()
        return [(r.slug, r.tenant_db_name) for r in rows]


def _sweep_one(
    slug: str,
    tenant_db_name: str,
    *,
    retention_days: int,
    batch_size: int,
    dry_run: bool,
) -> tuple[bool, int]:
    """Sweep a single tenant. Returns (ok, expired_remaining).

    Commits per tenant, so one tenant's failure cannot roll back another's
    deletion or leave a half-applied sweep behind.

    The post-check runs in the same session immediately after the purge: if
    it finds rows that should have gone, the sweep did not do its job and
    the caller must hear about it.
    """
    try:
        with tenant_session(tenant_db_name) as db:
            result = purge_expired_coordinates(
                db,
                retention_days=retention_days,
                dry_run=dry_run,
                batch_size=batch_size,
            )
            db.commit()

            remaining = count_expired_with_coordinates(
                db, retention_days=retention_days
            )

            log.info(
                "retention_purge.tenant_done",
                slug=slug,
                dry_run=dry_run,
                candidates=result.candidates,
                purged=result.purged,
                skipped_held=result.skipped_held,
                expired_remaining=remaining,
            )
            return True, remaining
    except Exception as exc:  # noqa: BLE001 -- one tenant must not abort the run
        log.error(
            "retention_purge.tenant_failed",
            slug=slug,
            error=type(exc).__name__,
            detail=str(exc),
        )
        return False, -1


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="retention_purge",
        description=(
            "Delete expired punch GPS coordinates under privacy policy "
            "section 5. Dry run unless --confirm is given."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be purged, change nothing (default)",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="actually delete. Without this the command only reports.",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        metavar="SLUG",
        help="limit to one tenant; default is every active tenant",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=DEFAULT_RETENTION_DAYS,
        help=f"coordinate retention window in days (default {DEFAULT_RETENTION_DAYS})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"rows deleted per batch (default {DEFAULT_BATCH_SIZE})",
    )
    args = parser.parse_args(argv)

    if args.dry_run and args.confirm:
        parser.error("--dry-run and --confirm are mutually exclusive")

    dry_run = not args.confirm
    started = datetime.now(timezone.utc)

    tenants = _active_tenants(args.tenant)
    if not tenants:
        log.warning("retention_purge.no_tenants", requested=args.tenant)
        return 0

    log.info(
        "retention_purge.start",
        tenants=len(tenants),
        dry_run=dry_run,
        retention_days=args.retention_days,
        batch_size=args.batch_size,
        requested=args.tenant,
    )

    failures = 0
    leftovers = 0
    for slug, db_name in tenants:
        ok, remaining = _sweep_one(
            slug,
            db_name,
            retention_days=args.retention_days,
            batch_size=args.batch_size,
            dry_run=dry_run,
        )
        if not ok:
            failures += 1
        elif remaining > 0:
            # A dry run is *expected* to leave everything in place; only a
            # real purge is required to come back clean.
            if not dry_run:
                leftovers += 1

    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    log.info(
        "retention_purge.finished",
        tenants=len(tenants),
        failures=failures,
        tenants_with_leftovers=leftovers,
        dry_run=dry_run,
        duration_ms=duration_ms,
    )

    if failures:
        return 1
    if leftovers:
        log.error(
            "retention_purge.postcheck_failed",
            tenants_with_leftovers=leftovers,
            detail=(
                "expired coordinates remain after a confirmed purge; "
                "check holds and batch limits"
            ),
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
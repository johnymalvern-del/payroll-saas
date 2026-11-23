"""Attendance coordinate retention (privacy policy section 5).

Raw employee GPS coordinates are held for 30 days; the verification verdict is
held for as long as the attendance record itself. This module performs that
distinction by deleting rows from punch_location, leaving the punch and its
verdict untouched.

Why deletion, not a column update: punch is append-only -- UPDATE and DELETE
are both revoked and a trigger raises (0012_attendance_foundation.py:299). A
mutable column cannot live there, which is what ten_0030's punch_location
table exists to solve. A DELETE is also a genuine removal: PostgreSQL drops
the row from the table, whereas an UPDATE would leave the old tuple
reclaimable in the heap and present in every backup.

What survives on punch, permanently:

  geofence_result / geofence_reason
      The audit conclusion. Without it an "outside" punch is
      indistinguishable from an unevaluated one.

  distance_band
      A coarse geometry descriptor -- within / near / distant -- that
      defends the verdict without localising the employee. The exact
      distance is deleted with the coordinates, because distance plus a
      known site coordinate narrows a position to a ring.

Holds
-----
An open exception_item holds the coordinates for the punches on that
(employee, work_date). Nothing else does: a locked attendance_day does not
hold, per the agreed policy, because the verdict on the punch already
answers the payroll-audit question that a locked period raises.

The hold is deliberately NOT date-windowed. An open exception about a
46-day-old punch is precisely when deletion is least safe, and an earlier
draft of this module excluded exactly that case. Holds are also keyed to
the day, not the employee, so one stale exception cannot freeze an
employee's entire coordinate history.

Resolution releases the hold automatically: status is derived from
exception_item.status, not stored as a flag, so there is nothing to forget
to clear.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select

from app.core.logging import get_logger
from app.db.tenant.models.attendance import ExceptionItem, Punch, PunchLocation
from app.db.tenant.models.platform import AuditLog

log = get_logger("app.services.attendance_retention")

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH_SIZE = 5000

# Retained on punch, permanently.
RETAINED_FIELDS = ("geofence_result", "geofence_reason", "distance_band")

# Deleted with the row.
PURGED_FIELDS = ("latitude", "longitude", "gps_accuracy_m", "distance_m")


@dataclass(frozen=True)
class PurgeResult:
    """Outcome of one retention sweep. All counts are rows, not employees."""

    cutoff: datetime
    retention_days: int
    candidates: int
    purged: int
    skipped_held: int
    dry_run: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "cutoff": self.cutoff.isoformat(),
            "retention_days": self.retention_days,
            "candidates": self.candidates,
            "purged": self.purged,
            "skipped_held": self.skipped_held,
            "dry_run": self.dry_run,
        }


def _held_work_dates(db: Any) -> dict[Any, set[date]]:
    """employee_id -> set of local work_dates under an open exception.

    No date bound: an exception of any age holds. See the module docstring
    for why an earlier, windowed version was wrong.
    """
    held: dict[Any, set[date]] = {}
    rows = db.execute(
        select(ExceptionItem.employee_id, ExceptionItem.work_date)
        .where(ExceptionItem.status == "open")
        .distinct()
    ).all()
    for employee_id, work_date in rows:
        held.setdefault(employee_id, set()).add(work_date)
    return held


def _is_held(held: dict[Any, set[date]], employee_id: Any, effective_time: datetime) -> bool:
    """Is this punch's local date under a hold?

    punch.effective_time is UTC; work_date is tenant-local. Rather than
    resolve each employee's site timezone inside a deletion path -- where a
    timezone bug silently destroys the wrong rows -- compare against a
    +/-1 day window. That over-protects by at most one day in each
    direction, which is the correct direction for the error to point.
    """
    work_dates = held.get(employee_id)
    if not work_dates:
        return False
    punch_date = effective_time.date()
    for work_date in work_dates:
        if work_date - timedelta(days=1) <= punch_date <= work_date + timedelta(days=1):
            return True
    return False


def purge_expired_coordinates(
    db: Any,
    *,
    now: datetime | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    dry_run: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_batches: int | None = None,
) -> PurgeResult:
    """Delete punch_location rows older than `retention_days`.

    Dry-run by DEFAULT. Deleting personal data should be an explicit act,
    not something that happens because a caller forgot a flag.

    Does not commit. The caller owns the transaction, which is what lets a
    test roll back and lets the CLI decide per-tenant commit boundaries.

    `max_batches` bounds the work in one call so a first run against a large
    backlog cannot hold locks indefinitely. It runs again next time.

    Safe to run repeatedly: a second sweep finds nothing, because the first
    one deleted the rows.
    """
    if retention_days < 0:
        raise ValueError("retention_days must not be negative")
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=retention_days)

    base_count = select(func.count()).select_from(PunchLocation).where(
        PunchLocation.captured_at < cutoff
    )
    candidates = int(db.scalar(base_count) or 0)

    if candidates == 0:
        result = PurgeResult(cutoff, retention_days, 0, 0, 0, dry_run)
        log.info("attendance_retention.done", **result.as_dict())
        return result

    held = _held_work_dates(db)

    purged = 0
    skipped_held = 0
    batches = 0

    while True:
        if max_batches is not None and batches >= max_batches:
            break

        rows = db.execute(
            select(PunchLocation.id, Punch.employee_id, Punch.effective_time)
            .join(Punch, Punch.id == PunchLocation.punch_id)
            .where(PunchLocation.captured_at < cutoff)
            .order_by(PunchLocation.captured_at)
            .limit(batch_size)
        ).all()

        if not rows:
            break

        delete_ids = []
        for loc_id, employee_id, effective_time in rows:
            if _is_held(held, employee_id, effective_time):
                skipped_held += 1
            else:
                delete_ids.append(loc_id)

        if delete_ids and not dry_run:
            db.execute(delete(PunchLocation).where(PunchLocation.id.in_(delete_ids)))
        purged += len(delete_ids)

        # A dry run still walks one batch worth of rows so the counts are
        # meaningful, then stops: nothing was deleted, so the next pass
        # would return the same rows and loop forever.
        if dry_run or len(rows) < batch_size:
            break
        batches += 1

    if not dry_run:
        db.add(
            AuditLog(
                id=uuid.uuid4(),
                actor_user_id=None,
                actor_role=None,
                entity_type="punch_location",
                entity_id="retention_sweep",
                action="attendance.coordinates.purged",
                old_value=None,
                new_value={
                    "cutoff": cutoff.isoformat(),
                    "retention_days": retention_days,
                    "candidates": candidates,
                    "purged": purged,
                    "skipped_held": skipped_held,
                    "purged_fields": list(PURGED_FIELDS),
                    "retained_fields": list(RETAINED_FIELDS),
                },
                request_id=None,
            )
        )

    result = PurgeResult(
        cutoff=cutoff,
        retention_days=retention_days,
        candidates=candidates,
        purged=purged,
        skipped_held=skipped_held,
        dry_run=dry_run,
    )
    log.info("attendance_retention.done", **result.as_dict())
    return result


def count_expired_with_coordinates(
    db: Any,
    *,
    now: datetime | None = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> int:
    """How many expired location rows still exist. For monitoring and for
    the post-purge verification the CLI performs."""
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - timedelta(days=retention_days)
    return int(
        db.scalar(
            select(func.count())
            .select_from(PunchLocation)
            .where(PunchLocation.captured_at < cutoff)
        )
        or 0
    )
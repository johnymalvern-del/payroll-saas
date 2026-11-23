"""Drop the raw GPS columns from punch (privacy policy section 5, step 2).

ten_0030 added punch_location and backfilled it. This migration removes the
duplicated source: punch.latitude, punch.longitude, punch.gps_accuracy_m and
punch.distance_m.

Why they had to leave punch at all:

  punch is append-only -- REVOKE UPDATE, DELETE plus a BEFORE UPDATE OR
  DELETE trigger (0012:299). No UPDATE can ever reach a row, by any role, so
  a column that must expire on a retention schedule cannot live there. While
  both copies existed, "deleted" meant only that punch_location was emptied
  while the same coordinate sat on punch forever.

What survives on punch, permanently:

  geofence_result, geofence_reason  the audit conclusion
  distance_band                     coarse geometry (within/near/distant)

What is gone: the exact position and the exact distance. distance_band
defends the verdict without localising the employee.

Why a guard rather than a plain DROP

If any punch still holds coordinates with no matching punch_location row, the
backfill missed it and this migration would destroy the only copy. The check
below aborts the migration instead. That is recoverable; a DROP is not.

Downgrade re-adds the columns as nullable but CANNOT restore their values --
those may already have been deleted by retention. This is a one-way door and
the docstring says so rather than pretending otherwise.

DDL only: ALTER TABLE does not fire row-level triggers, so the append-only
guard is untouched by this migration.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ten_0031"
down_revision = "ten_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Fail loudly rather than shred coordinates the backfill missed.
    orphans = conn.execute(
        sa.text(
            """
            SELECT count(*) FROM punch p
            WHERE (p.latitude IS NOT NULL OR p.longitude IS NOT NULL)
              AND NOT EXISTS (
                  SELECT 1 FROM punch_location l WHERE l.punch_id = p.id
              )
            """
        )
    ).scalar()

    if orphans:
        raise RuntimeError(
            f"ten_0031 aborted: {orphans} punch row(s) hold coordinates with no "
            f"punch_location row. Re-run the ten_0030 backfill before dropping "
            f"these columns, or the only copy of that location data is lost."
        )

    op.drop_column("punch", "latitude")
    op.drop_column("punch", "longitude")
    op.drop_column("punch", "gps_accuracy_m")
    op.drop_column("punch", "distance_m")


def downgrade() -> None:
    # Values are NOT recoverable. Retention may already have deleted the
    # corresponding punch_location rows, and those are the only remaining copy.
    # Re-added as nullable so the schema is usable again; the data is gone.
    op.add_column(
        "punch", sa.Column("distance_m", sa.Numeric(10, 2), nullable=True)
    )
    op.add_column(
        "punch", sa.Column("gps_accuracy_m", sa.Numeric(6, 2), nullable=True)
    )
    op.add_column(
        "punch", sa.Column("longitude", sa.Numeric(9, 6), nullable=True)
    )
    op.add_column(
        "punch", sa.Column("latitude", sa.Numeric(9, 6), nullable=True)
    )
"""Add geofence verdict columns to punch.

Phase 2 of the biometric attendance programme. Phase 1 added the pure
geofence evaluator (app/services/geofence.py); this migration gives it
somewhere to write its answer.

Four additive, nullable columns on public.punch:

  gps_accuracy_m   horizontal accuracy reported by the device, in metres.
                   Without it a distance is a point estimate and no
                   verdict can be defended.

  geofence_result  the verdict: inside | outside | inconclusive |
                   unavailable. NULL for punches processed before this
                   migration, and for device-less punches.

  geofence_reason  the machine-readable tag explaining the verdict, e.g.
                   accuracy_overlaps_boundary. Stored separately from the
                   verdict so HR can filter on either.

  distance_m       distance from the punch fix to the site centre, in
                   metres. Kept because an "outside" verdict is only
                   reviewable if you can see by how much.

Deliberately NOT NOT NULL: every existing row predates geofence
evaluation, and every device that reports no location keeps writing
NULL. A NOT NULL constraint would break both.

No backfill. Existing punches stay NULL, which reads as "not evaluated",
and that is the truthful state.

No index yet. geofence_result has four values and the table is small
enough that a sequential scan is fine; the right index depends on which
filter the exception queue actually uses. Adding it later is cheap.

Revision ID: ten_0029
Revises: ten_0028
Create Date: 2026-11-21
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "ten_0029"
down_revision = "ten_0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "punch",
        sa.Column("gps_accuracy_m", sa.Numeric(6, 2), nullable=True),
    )
    op.add_column(
        "punch",
        sa.Column("geofence_result", sa.String(20), nullable=True),
    )
    op.add_column(
        "punch",
        sa.Column("geofence_reason", sa.String(40), nullable=True),
    )
    op.add_column(
        "punch",
        sa.Column("distance_m", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("punch", "distance_m")
    op.drop_column("punch", "geofence_reason")
    op.drop_column("punch", "geofence_result")
    op.drop_column("punch", "gps_accuracy_m")

# END OF FILE
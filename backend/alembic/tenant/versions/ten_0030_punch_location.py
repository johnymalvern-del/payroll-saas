"""Add punch_location for GPS retention separation.

Privacy policy section 5 requires raw GPS coordinates to be held for 30 days
and then genuinely deleted, while the attendance evidence -- the geofence
verdict -- is kept for as long as the attendance record itself.

punch cannot carry that: it is append-only, enforced by REVOKE UPDATE, DELETE
plus a BEFORE UPDATE OR DELETE trigger (see 0012_attendance_foundation.py:299).
No UPDATE can ever reach a punch row, by any role, so a mutable column can
never be expired in place. Splitting the coordinates into their own table is
what makes lawful deletion possible without weakening that guard.

Shape:

  punch           immutable. Keeps geofence_result, geofence_reason and the new
                  distance_band -- the audit conclusion, which survives forever.
  punch_location  mutable-by-deletion. Holds latitude, longitude,
                  gps_accuracy_m and the exact distance_m. Deleted when expired.

Append-only guards on punch are NOT touched by this migration. distance_band is
added with plain DDL (ADD COLUMN ... DEFAULT), which does not fire row triggers
and requires no UPDATE privilege. Historical punches take the 'unknown' band
because it was never computed for them; backfilling would require UPDATE on
punch, which is precisely what must not happen.

punch_location grants SELECT, INSERT and DELETE to the app role -- DELETE is
required by the retention sweep. UPDATE is not granted and a trigger refuses it
as a second line of defence, matching the audit_log and punch pattern: a
captured position is a historical fact and must not be editable.

Revision ID: ten_0030
Revises: ten_0029
Create Date: 2026-11-21
"""
from __future__ import annotations

import os
import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ten_0030"
down_revision = "ten_0029"
branch_labels = None
depends_on = None


def _app_role() -> str:
    """Copied from 0012_attendance_foundation.py:81.

    Every tenant migration defines this locally rather than importing it, so
    that a migration stays runnable against the exact schema state it was
    written for. Kept byte-identical to the existing copies.
    """
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. punch_location
    # ------------------------------------------------------------------
    op.create_table(
        "punch_location",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "punch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("punch.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=False),
        sa.Column("gps_accuracy_m", sa.Numeric(6, 2), nullable=True),
        sa.Column("distance_m", sa.Numeric(10, 2), nullable=True),
        # The punch's effective_time, echoed here so the retention sweep can
        # filter without joining back to the immutable table.
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "latitude >= -90 AND latitude <= 90",
            name="ck_punch_location_lat_range",
        ),
        sa.CheckConstraint(
            "longitude >= -180 AND longitude <= 180",
            name="ck_punch_location_lon_range",
        ),
        # One location per punch. Also proves the backfill below did not
        # duplicate anything.
        sa.UniqueConstraint("punch_id", name="uq_punch_location_punch"),
    )
    op.create_index(
        "ix_punch_location_captured_at", "punch_location", ["captured_at"]
    )

    # ------------------------------------------------------------------
    # 2. distance_band on punch (DDL only -- no trigger fires)
    # ------------------------------------------------------------------
    # NOT backfilled. Existing rows take 'unknown', which is the truthful
    # value: the band was never computed for them. The exact distance is
    # still available on punch_location until it expires.
    op.add_column(
        "punch",
        sa.Column(
            "distance_band",
            sa.String(16),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_check_constraint(
        "ck_punch_distance_band",
        "punch",
        "distance_band IN ('within', 'near', 'distant', 'unknown')",
    )

    # ------------------------------------------------------------------
    # 3. Backfill punch_location from punch
    # ------------------------------------------------------------------
    # SELECT from punch is permitted; INSERT into punch_location is a new
    # table, so nothing here touches the append-only guard.
    op.execute(
        """
        INSERT INTO punch_location
            (id, punch_id, latitude, longitude, gps_accuracy_m, distance_m, captured_at)
        SELECT
            gen_random_uuid(),
            p.id,
            p.latitude,
            p.longitude,
            p.gps_accuracy_m,
            p.distance_m,
            p.effective_time
        FROM punch p
        WHERE p.latitude IS NOT NULL OR p.longitude IS NOT NULL
        """
    )

    # ------------------------------------------------------------------
    # 4. Append-only guard on punch_location (UPDATE only)
    # ------------------------------------------------------------------
    # DELETE must remain available -- that is the retention mechanism.
    op.execute(
        "CREATE OR REPLACE FUNCTION punch_location_no_update() RETURNS trigger AS $$ "
        "BEGIN "
        "    RAISE EXCEPTION 'punch_location is insert/delete only: % not allowed', TG_OP; "
        "END; "
        "$$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER trg_punch_location_no_update "
        "BEFORE UPDATE ON punch_location "
        "FOR EACH ROW EXECUTE FUNCTION punch_location_no_update()"
    )

    # ------------------------------------------------------------------
    # 5. Grants
    # ------------------------------------------------------------------
    # 0001's `GRANT ... ON ALL TABLES IN SCHEMA public` ran before this table
    # existed and therefore does not cover it; see the same note at
    # 0012:341-355. Without these lines the app would get permission denied
    # on punch_location at runtime.
    #
    # UPDATE is deliberately absent and revoked explicitly so the intent is
    # visible in the schema history, not only in the missing grant.
    role = _app_role()
    op.execute(f"REVOKE UPDATE, TRUNCATE ON punch_location FROM {role}")
    op.execute(f"GRANT SELECT, INSERT, DELETE ON punch_location TO {role}")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_punch_location_no_update ON punch_location")
    op.execute("DROP FUNCTION IF EXISTS punch_location_no_update()")

    op.drop_constraint("ck_punch_distance_band", "punch", type_="check")
    op.drop_column("punch", "distance_band")

    op.drop_index("ix_punch_location_captured_at", table_name="punch_location")
    # Drops the table and its unique constraint. Coordinates held only here
    # are lost -- acceptable because punch still carries latitude, longitude,
    # gps_accuracy_m and distance_m at this point in the chain.
    op.drop_table("punch_location")
"""Chapter 2A attendance foundation: 7 new tables + a device ALTER.

Revision ID: ten_0012
Revises: ten_0011
Create Date: 2026-10-28 00:00:00

New tables: shift, shift_rate_rule, work_pattern, work_pattern_day,
public_holiday_tenant, punch, employee_work_pattern.

Amended: device. Migration 0001 already created device. 0012 adds
device.row_version and a UNIQUE index on api_key_hash (replacing 0001's
non-unique index of the same name). 0001's other device column choices
are preserved: site_id ondelete=CASCADE (not RESTRICT), status default
'offline' (not 'active'), api_key_hash VARCHAR(255) (not 64),
device_type VARCHAR(30) (not 20). Where 0001 and the 2A SPEC disagreed
on schema-level defaults, 0001 wins because altering FK behaviour or
column type on a populated table is a data-migration hazard; altering
only additive columns (row_version) is safe. Endpoint-level behaviour
(status='active' at create) is set explicitly by the endpoint, not by
the schema default. See docs/STATE.md Errata for the full record.

Key choices (full decision list in docs/STATE.md):

  punch is append-only. SELECT and INSERT are granted to payroll_app;
  UPDATE and DELETE are revoked and a BEFORE UPDATE OR DELETE trigger
  raises. Same pattern as audit_log. Server-generated primary key `id`;
  client-supplied `client_punch_id` is unique per (device_id,
  client_punch_id) for idempotency; `payload_hash` is a hex SHA-256 of
  the canonical punch payload for the "same pair, same payload" check.

  effective_time is computed server-side from device_time and either
  device_now_at_send (present for batch/offline sync) or
  server_received_at (present for live punches). offset_ms is
  device_now_at_send - server_received_at in ms (or device_time -
  server_received_at for live). Clock-gap flagging uses abs(offset_ms)
  against a configurable threshold. A live punch always resolves to
  effective_time == server_received_at because offset cancels device_time.

  device.api_key_hash holds SHA-256 hex of the raw key (or
  HMAC-SHA256 hex with a server pepper if configured). UNIQUE-indexed.
  NOT argon2: argon2 is salted, so a device cannot be looked up by its
  key without scanning every row and re-hashing against every stored
  hash. SHA-256 (or keyed HMAC) is the correct primitive for "find the
  row whose hash matches this presented key" and is fast enough for a
  hot path. Raw key is generated with secrets.token_hex(32) and shown
  once, never stored.

  employee_work_pattern is effective-dated history. It supersedes (but
  does not remove) Employee.work_pattern_id and Employee.default_shift_id
  which stay on the employee row for backward compatibility. 2B's
  day-build reads employee_work_pattern first, then falls back to the
  legacy columns. See "Deprecations" in STATE.md.

  shift_rate_rule has a per-key overlap invariant: no two rules for the
  same (shift_id, day_type, kind) may have overlapping effective periods.
  Enforced at application level in the endpoint (409
  overlapping_rate_rule) rather than with EXCLUDE USING gist because
  btree_gist is not guaranteed installed and the check is cheap.

  No CHECK constraints on enum-like columns (day_type, kind, method,
  status, device_type, rounding_mode, salaried_premium_mode). The
  codebase pattern is Pydantic-level validation, not DB-level. Adding
  CHECK constraints would diverge from the rest of the schema.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0012"
down_revision: Union[str, Sequence[str], None] = "ten_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. shift
    # ------------------------------------------------------------------
    op.create_table(
        "shift",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("length_minutes", sa.Integer(), nullable=False),
        sa.Column("unpaid_break_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paid_break_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("grace_late_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("grace_early_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounding_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounding_mode", sa.String(10), nullable=False, server_default="nearest"),
        sa.Column("min_overtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overtime_requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("max_shift_minutes", sa.Integer(), nullable=False),
        sa.Column("match_tolerance_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("salaried_premium_mode", sa.String(20), nullable=False, server_default="full"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_shift_name_lower_active "
        "ON shift (lower(btrim(name))) WHERE is_active = true"
    )
    op.create_index("ix_shift_active", "shift", ["is_active"])

    # ------------------------------------------------------------------
    # 2. shift_rate_rule
    # ------------------------------------------------------------------
    op.create_table(
        "shift_rate_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shift.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_type", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("tier_up_to_minutes", sa.Integer(), nullable=True),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("value", sa.Numeric(18, 6), nullable=False),
        sa.Column("flat_unit", sa.String(20), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_srr_key",
        "shift_rate_rule",
        ["shift_id", "day_type", "kind", "tier", "effective_from"],
    )
    op.create_index(
        "ix_srr_lookup",
        "shift_rate_rule",
        ["shift_id", "day_type", "kind", "effective_from"],
    )

    # ------------------------------------------------------------------
    # 3. work_pattern
    # ------------------------------------------------------------------
    op.create_table(
        "work_pattern",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("cycle_length_days", sa.Integer(), nullable=False),
        sa.Column("anchor_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_work_pattern_name", "work_pattern", ["name"])
    op.create_index("ix_work_pattern_active", "work_pattern", ["is_active"])

    # ------------------------------------------------------------------
    # 4. work_pattern_day
    # ------------------------------------------------------------------
    op.create_table(
        "work_pattern_day",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "work_pattern_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_pattern.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("is_expected", sa.Boolean(), nullable=False),
        sa.Column(
            "expected_shift_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shift.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_wpd_pattern_day",
        "work_pattern_day",
        ["work_pattern_id", "day_index"],
    )

    # ------------------------------------------------------------------
    # 5. public_holiday_tenant
    # ------------------------------------------------------------------
    op.create_table(
        "public_holiday_tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("site.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("department.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("is_working_day_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_pht_date", "public_holiday_tenant", ["holiday_date"])
    op.create_index("ix_pht_site", "public_holiday_tenant", ["site_id"])
    op.create_index("ix_pht_dept", "public_holiday_tenant", ["department_id"])

    # ------------------------------------------------------------------
    # 6. device -- already created by migration 0001. 0012 only adds what
    # 2A needs and does not exist yet:
    #   - row_version (0001 lacked it)
    #   - a UNIQUE guarantee on api_key_hash (0001 has a non-unique index)
    # 0001's site_id ondelete=CASCADE and status default 'offline' are
    # left untouched. Existing rows, if any, get row_version=1.
    # ------------------------------------------------------------------
    op.add_column(
        "device",
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute("DROP INDEX IF EXISTS ix_device_api_key_hash")
    op.execute(
        "CREATE UNIQUE INDEX uq_device_api_key_hash ON device (api_key_hash)"
    )

    # ------------------------------------------------------------------
    # 7. punch (append-only)
    # ------------------------------------------------------------------
    op.create_table(
        "punch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_punch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "device_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("device.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "site_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("site.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("server_received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("device_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_now_at_send", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("offset_ms", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("match_score", sa.Numeric(5, 2), nullable=True),
        sa.Column("liveness_passed", sa.Boolean(), nullable=True),
        sa.Column("photo_object_key", sa.String(400), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_punch_device_client",
        "punch",
        ["device_id", "client_punch_id"],
    )
    op.create_index("ix_punch_employee_effective", "punch", ["employee_id", "effective_time"])
    op.create_index("ix_punch_status", "punch", ["status"])
    op.create_index("ix_punch_device", "punch", ["device_id"])

    # Append-only enforcement: REVOKE UPDATE/DELETE, and a trigger as
    # second line of defence (in case a future migration accidentally
    # grants UPDATE again, the trigger still fires).
    op.execute(f"REVOKE UPDATE, DELETE ON punch FROM {_app_role()}")
    op.execute(
        "CREATE OR REPLACE FUNCTION punch_append_only() RETURNS trigger AS $$ "
        "BEGIN "
        "    RAISE EXCEPTION 'punch is append-only: % not allowed', TG_OP; "
        "END; "
        "$$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER trg_punch_append_only "
        "BEFORE UPDATE OR DELETE ON punch "
        "FOR EACH ROW EXECUTE FUNCTION punch_append_only()"
    )

    # ------------------------------------------------------------------
    # 8. employee_work_pattern
    # ------------------------------------------------------------------
    op.create_table(
        "employee_work_pattern",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "employee_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("employee.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "work_pattern_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_pattern.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ewp_employee_from", "employee_work_pattern", ["employee_id", "effective_from"])

    # ------------------------------------------------------------------
    # Grants for the tables created above. Migration 0001's
    # `GRANT ... ON ALL TABLES IN SCHEMA public` ran before these tables
    # existed, so it does not cover them. Without this block, payroll_app
    # would get permission denied on the new tables at runtime.
    # punch gets only SELECT and INSERT; UPDATE/DELETE are already revoked
    # above and the append-only trigger is the second line of defence.
    # ------------------------------------------------------------------
    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"shift, shift_rate_rule, work_pattern, work_pattern_day, "
        f"public_holiday_tenant, employee_work_pattern TO {role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON punch TO {role}")


def downgrade() -> None:
    op.drop_index("ix_ewp_employee_from", table_name="employee_work_pattern")
    op.drop_table("employee_work_pattern")

    op.execute("DROP TRIGGER IF EXISTS trg_punch_append_only ON punch")
    op.execute("DROP FUNCTION IF EXISTS punch_append_only()")
    op.drop_index("ix_punch_device", table_name="punch")
    op.drop_index("ix_punch_status", table_name="punch")
    op.drop_index("ix_punch_employee_effective", table_name="punch")
    op.drop_table("punch")

    op.execute("DROP INDEX IF EXISTS uq_device_api_key_hash")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_device_api_key_hash ON device (api_key_hash)"
    )
    op.drop_column("device", "row_version")

    op.drop_index("ix_pht_dept", table_name="public_holiday_tenant")
    op.drop_index("ix_pht_site", table_name="public_holiday_tenant")
    op.drop_index("ix_pht_date", table_name="public_holiday_tenant")
    op.drop_table("public_holiday_tenant")

    op.drop_table("work_pattern_day")

    op.drop_index("ix_work_pattern_active", table_name="work_pattern")
    op.drop_table("work_pattern")

    op.drop_index("ix_srr_lookup", table_name="shift_rate_rule")
    op.drop_table("shift_rate_rule")

    op.drop_index("ix_shift_active", table_name="shift")
    op.execute("DROP INDEX IF EXISTS uq_shift_name_lower_active")
    op.drop_table("shift")

# END OF FILE
"""Phase 1B migration: ten_0026_phase_1b_decision_records."""
from pathlib import Path
BE = Path(__file__).resolve().parent.parent / "backend"
(BE / "alembic" / "tenant" / "versions" / "0026_phase_1b_decision_records.py").write_text('''"""Phase 1B — decision-record infrastructure and immutable evidence snapshots.

Additive only. No existing column dropped. No existing table renamed.
- intelligence_decision: +8 columns (7 business + 1 FK to snapshot),
  +1 partial unique index on (workflow, idempotency_key).
- intelligence_evidence_snapshot: new table + REVOKE + trigger (same
  pattern as audit_log / punch / leave_balance_ledger).
- Backfill existing rows (best-effort, safe on empty table).
"""
from __future__ import annotations

import os
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ten_0026"
down_revision = "ten_0025"
branch_labels = None
depends_on = None


def _app_role() -> str:
    return os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")


def upgrade() -> None:
    # ---------- intelligence_evidence_snapshot ----------
    op.create_table(
        "intelligence_evidence_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decision_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("intelligence_decision.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("schema_version", sa.Integer, nullable=False,
                  server_default="1"),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("sha256_hex", sa.String(64), nullable=False),
    )

    # Immutability — copy the audit_log pattern verbatim
    role = _app_role()
    op.execute(f"REVOKE UPDATE, DELETE ON intelligence_evidence_snapshot FROM {role}")
    op.execute(
        "CREATE OR REPLACE FUNCTION intelligence_evidence_snapshot_immutable() "
        "RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "  RAISE EXCEPTION 'intelligence_evidence_snapshot is append-only'; "
        "END; "
        "$$"
    )
    op.execute(
        "CREATE TRIGGER intelligence_evidence_snapshot_no_update "
        "BEFORE UPDATE ON intelligence_evidence_snapshot "
        "FOR EACH ROW EXECUTE FUNCTION intelligence_evidence_snapshot_immutable()"
    )
    op.execute(
        "CREATE TRIGGER intelligence_evidence_snapshot_no_delete "
        "BEFORE DELETE ON intelligence_evidence_snapshot "
        "FOR EACH ROW EXECUTE FUNCTION intelligence_evidence_snapshot_immutable()"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON intelligence_evidence_snapshot TO {role}"
    )

    # ---------- intelligence_decision extra columns ----------
    op.add_column(
        "intelligence_decision",
        sa.Column("decision_type", sa.String(20), nullable=False,
                  server_default=sa.text("'recommendation'")),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("initiator_type", sa.String(20), nullable=False,
                  server_default=sa.text("'human'")),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("initiator_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("company_default_mode", sa.String(20), nullable=True),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("effective_workflow_mode", sa.String(20), nullable=True),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("workflow_override_mode", sa.String(20), nullable=True),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("idempotency_key", sa.String(120), nullable=True),
    )
    op.add_column(
        "intelligence_decision",
        sa.Column("evidence_snapshot_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("intelligence_evidence_snapshot.id",
                                ondelete="SET NULL"),
                  nullable=True),
    )

    # Backfill from mode_at_creation where historical fields are null
    op.execute(
        "UPDATE intelligence_decision "
        "SET company_default_mode = mode_at_creation, "
        "    effective_workflow_mode = mode_at_creation "
        "WHERE company_default_mode IS NULL"
    )

    # Partial unique index for idempotency
    op.create_index(
        "uq_intelligence_decision_idempotency",
        "intelligence_decision",
        ["workflow", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_intelligence_decision_idempotency",
                  table_name="intelligence_decision")
    op.drop_column("intelligence_decision", "evidence_snapshot_id")
    op.drop_column("intelligence_decision", "idempotency_key")
    op.drop_column("intelligence_decision", "workflow_override_mode")
    op.drop_column("intelligence_decision", "effective_workflow_mode")
    op.drop_column("intelligence_decision", "company_default_mode")
    op.drop_column("intelligence_decision", "initiator_user_id")
    op.drop_column("intelligence_decision", "initiator_type")
    op.drop_column("intelligence_decision", "decision_type")
    op.execute("DROP TRIGGER IF EXISTS intelligence_evidence_snapshot_no_delete "
               "ON intelligence_evidence_snapshot")
    op.execute("DROP TRIGGER IF EXISTS intelligence_evidence_snapshot_no_update "
               "ON intelligence_evidence_snapshot")
    op.execute("DROP FUNCTION IF EXISTS intelligence_evidence_snapshot_immutable()")
    op.drop_table("intelligence_evidence_snapshot")
''', encoding="utf-8")
print("wrote backend/alembic/tenant/versions/0026_phase_1b_decision_records.py")
"""Leave approval chain + chapter 3 settings fields (Chapter 3, 3B).

Adds to leave_type:
  approval_chain                JSONB, list of roles, default []
  requires_payroll_admin_final  bool, default false

Adds to payroll_settings:
  leave_escalation_days         int, nullable
  leave_cycle_fixed_anchor      date, nullable
  advance_max_pct               numeric(5,4), nullable
  advance_hard_cap              numeric(14,2), nullable
  sick_leave_codes              JSONB, list of strings, default []
  net_estimate_method           string(20), nullable

Amendment 1: approval_chain per leave type, ordered list of roles.
Amendment 5: sick leave cycle stays extensible; no law baked in.
Amendment 11: no invented money/law values. Only `approval_chain` and
`sick_leave_codes` have non-null defaults (`[]`); the accountant-
dependent fields stay null so the features they gate remain disabled
until confirmed.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ten_0022"
down_revision = "ten_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leave_type",
        sa.Column(
            "approval_chain",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "leave_type",
        sa.Column(
            "requires_payroll_admin_final",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("leave_escalation_days", sa.Integer(), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("leave_cycle_fixed_anchor", sa.Date(), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("advance_max_pct", sa.Numeric(5, 4), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("advance_hard_cap", sa.Numeric(14, 2), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column(
            "sick_leave_codes",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("net_estimate_method", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    for col in (
        "net_estimate_method",
        "sick_leave_codes",
        "advance_hard_cap",
        "advance_max_pct",
        "leave_cycle_fixed_anchor",
        "leave_escalation_days",
    ):
        op.drop_column("payroll_settings", col)
    for col in ("requires_payroll_admin_final", "approval_chain"):
        op.drop_column("leave_type", col)
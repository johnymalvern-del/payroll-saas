"""Payroll closing fields (Chapter 4H, B-4 foundation).

Adds the settings that will gate the attendance-to-earnings integration,
plus a `demo_values` flag for demo-tenant seeding (round-1 amendment 3).
No defaults are invented: every new column is nullable except
`attendance_earning_map` (empty dict by default) and `demo_values` (false).
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ten_0021"
down_revision = "ten_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payroll_settings",
        sa.Column(
            "attendance_earning_map",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("unpaid_day_behaviour", sa.String(20), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("unpaid_day_formula_code", sa.String(60), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("public_holiday_unworked_monthly", sa.String(20), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("public_holiday_paid", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("leave_authoritative_source", sa.String(20), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column(
            "monthly_hourly_derivation_formula_code", sa.String(60), nullable=True
        ),
    )
    op.add_column(
        "payroll_settings",
        sa.Column("leave_earning_for_monthly", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "payroll_settings",
        sa.Column(
            "demo_values",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    for col in (
        "demo_values",
        "leave_earning_for_monthly",
        "monthly_hourly_derivation_formula_code",
        "leave_authoritative_source",
        "public_holiday_paid",
        "public_holiday_unworked_monthly",
        "unpaid_day_formula_code",
        "unpaid_day_behaviour",
        "attendance_earning_map",
    ):
        op.drop_column("payroll_settings", col)

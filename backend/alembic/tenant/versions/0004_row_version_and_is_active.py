
"""Add row_version to company, is_active to branch/site/department.

Revision ID: ten_0004
Revises: ten_0003
Create Date: 2026-10-24 00:00:00

rule 1 (no hard deletes): branch, site, department become deactivatable.
rule 2 (prevent lost updates): company, branch, site, department, employee,
user all need row_version. This migration adds row_version to the tables
that did not have it (company only; employee/user take it in 1C.8 when the
employee/user routers land; branch/site/department get it here together with
is_active).

The down migration drops those columns. It does not restore any data.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ten_0004"
down_revision: Union[str, Sequence[str], None] = "ten_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # rule 2: row_version on company (single-row resource, but edited by
    # payroll_admin via PATCH /company; concurrent PATCH needs a guard).
    op.add_column(
        "company",
        sa.Column(
            "row_version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    # rule 1: is_active on branch, site, department. rule 2: row_version on
    # the same tables so deactivate/reactivate also gets lost-update
    # protection.
    for table in ("branch", "site", "department"):
        op.add_column(
            table,
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "row_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
        op.create_index(f"ix_{table}_is_active", table, ["is_active"])


def downgrade() -> None:
    for table in ("branch", "site", "department"):
        op.drop_index(f"ix_{table}_is_active", table_name=table)
        op.drop_column(table, "row_version")
        op.drop_column(table, "is_active")
    op.drop_column("company", "row_version")

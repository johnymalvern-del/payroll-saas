"""Add non-biometric fallback credentials to employee (privacy policy s4).

Section 4 requires a non-biometric attendance alternative that is genuinely
available to every employee. Until now the only non-biometric path was
method='code', which accepts an employee code with no verification at all --
anyone who knows a code can clock in as that person. That is not an
alternative to biometric verification; it is the absence of verification.

This migration adds the storage for a PIN, which is the fallback the policy
calls for.

Why a PIN and not a badge: the terminal is a browser on a phone or a desktop.
There is no card reader to read a badge with. method='badge' can be added later
against real reader hardware using the same verification shape.

Why a one-way hash and not an *_encrypted column: national_id_encrypted and
bank_account_number_encrypted exist because those values must be read back and
displayed. A PIN must never be read back -- only compared. Hashing with the
same argon2 configuration as user passwords gives that, and a stolen database
yields no PINs.

Lockout state lives here rather than in a separate table because a PIN belongs
to an employee, not to a device: someone could attempt it from any terminal.

   pin_hash              argon2 hash, NULL until HR sets one
   pin_set_at            when it was last set, for HR visibility
   pin_failed_attempts   consecutive failures since the last success
   pin_locked_until      NULL unless locked out

The attempt counter is the actual defence for a short secret. A 6-digit PIN is
10^6 values; argon2 makes each guess expensive but imposes no limit on how many
guesses can be made. The counter does.

DDL on employee only -- no trigger is involved, and employee is not
append-only.

Revision ID: ten_0033
Revises: ten_0032
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ten_0033"
down_revision = "ten_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "employee",
        sa.Column("pin_hash", sa.String(255), nullable=True),
    )
    op.add_column(
        "employee",
        sa.Column("pin_set_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "employee",
        sa.Column(
            "pin_failed_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "employee",
        sa.Column("pin_locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("employee", "pin_locked_until")
    op.drop_column("employee", "pin_failed_attempts")
    op.drop_column("employee", "pin_set_at")
    op.drop_column("employee", "pin_hash")
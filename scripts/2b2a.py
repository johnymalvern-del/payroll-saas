"""2B-2a: shift.grace_mode and shift.pay_early_arrival (amendments B4, B5).

Migration 0014 adds two columns to shift:
  grace_mode         VARCHAR(20) NOT NULL DEFAULT 'threshold'
  pay_early_arrival  BOOLEAN NOT NULL DEFAULT FALSE

Patches Shift model, shifts_schemas.py (Out/CreateIn/PatchIn), shifts.py
(_to_out and the create_shift constructor). Runs parse, import,
collect-only, focused pytest on test_shifts.py and test_schema_drift.py.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\xampp\htdocs\Payroll")
BACKEND = ROOT / "backend"
PY = ROOT / ".venv" / "Scripts" / "python.exe"


def fail(msg: str) -> None:
    print(f"STOP: {msg}")
    sys.exit(1)


def run(cmd: list) -> int:
    print("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(BACKEND),
                       capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip())
    return r.returncode


def write_and_check(rel: str, content: str) -> None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        fail(f"{rel} has SyntaxError before write: {e}")
    p = BACKEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    if not content.rstrip().endswith("# END OF FILE"):
        fail(f"{rel} does not end with '# END OF FILE'")
    if p.read_bytes()[:3] == b"\xef\xbb\xbf":
        fail(f"{rel} written with BOM")
    print(f"WROTE {rel} lines={len(content.splitlines())}")


def patch_file(rel: str, patches: list[tuple[str, str, str]]) -> None:
    p = BACKEND / rel
    text = p.read_text(encoding="utf-8")
    original = text
    for label, old, new in patches:
        n = text.count(old)
        if n != 1:
            fail(f"{rel}: {label} anchor count {n} (expected 1)")
        text = text.replace(old, new, 1)
    try:
        ast.parse(text)
    except SyntaxError as e:
        fail(f"{rel} patches produced invalid Python: {e}")
    p.write_text(text, encoding="utf-8")
    if p.read_bytes()[:3] == b"\xef\xbb\xbf":
        fail(f"{rel} written with BOM")
    print(f"patched {rel} (delta {len(text)-len(original)} bytes)")


# =========================================================================
# 1. Migration 0014
# =========================================================================
MIGRATION = '''"""Chapter 2B amendments B4 and B5: two new shift columns.

Revision ID: ten_0014
Revises: ten_0013
Create Date: 2026-10-28 00:00:00

B4: grace_mode. If 'threshold' (default), a late arrival within grace is
treated as on time; if late beyond grace, lateness counts from the
scheduled start in full. If 'allowance', only the excess beyond grace
counts. Same behaviour for early departure via grace_early_minutes.

B5: pay_early_arrival. If false (default), time before the scheduled
shift start is not paid and the day gets flag early_arrival_ignored. If
true, early minutes count as overtime and follow the shift's
overtime_requires_approval setting.

Both columns are tenant configuration with safe defaults; no data backfill
needed. Existing rows get 'threshold' and false.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ten_0014"
down_revision: Union[str, Sequence[str], None] = "ten_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shift",
        sa.Column("grace_mode", sa.String(20), nullable=False, server_default="threshold"),
    )
    op.add_column(
        "shift",
        sa.Column("pay_early_arrival", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("shift", "pay_early_arrival")
    op.drop_column("shift", "grace_mode")

# END OF FILE
'''

write_and_check("alembic/tenant/versions/0014_shift_grace_and_early.py", MIGRATION)

# =========================================================================
# 2. Shift model
# =========================================================================
patch_file("app/db/tenant/models/attendance.py", [
    (
        "Shift model: salaried_premium_mode context",
        "    salaried_premium_mode: Mapped[str] = mapped_column(\n"
        "        String(20), nullable=False, default=\"full\", server_default=\"full\"\n"
        "    )\n"
        "    is_active: Mapped[bool] = mapped_column(\n"
        "        Boolean(), nullable=False, default=True, server_default=true()\n"
        "    )\n"
        "    row_version: Mapped[int] = mapped_column(\n"
        "        Integer(), nullable=False, default=1, server_default=\"1\"\n"
        "    )\n"
        "\n"
        "\n"
        "class ShiftRateRule(Base, TimestampMixin):",
        "    salaried_premium_mode: Mapped[str] = mapped_column(\n"
        "        String(20), nullable=False, default=\"full\", server_default=\"full\"\n"
        "    )\n"
        "    grace_mode: Mapped[str] = mapped_column(\n"
        "        String(20), nullable=False, default=\"threshold\", server_default=\"threshold\"\n"
        "    )\n"
        "    pay_early_arrival: Mapped[bool] = mapped_column(\n"
        "        Boolean(), nullable=False, default=False, server_default=\"false\"\n"
        "    )\n"
        "    is_active: Mapped[bool] = mapped_column(\n"
        "        Boolean(), nullable=False, default=True, server_default=true()\n"
        "    )\n"
        "    row_version: Mapped[int] = mapped_column(\n"
        "        Integer(), nullable=False, default=1, server_default=\"1\"\n"
        "    )\n"
        "\n"
        "\n"
        "class ShiftRateRule(Base, TimestampMixin):",
    ),
])

# =========================================================================
# 3. shifts_schemas.py
# =========================================================================
patch_file("app/api/v1/shifts_schemas.py", [
    (
        "add _GRACE_MODES constant",
        "_SALARIED_PREMIUM_MODES = ('full', 'premium_only')\n",
        "_SALARIED_PREMIUM_MODES = ('full', 'premium_only')\n"
        "_GRACE_MODES = ('threshold', 'allowance')\n",
    ),
    (
        "ShiftOut add grace_mode/pay_early_arrival",
        "    salaried_premium_mode: str\n    is_active: bool\n    row_version: int\n\n\nclass ShiftCreateIn(BaseModel):",
        "    salaried_premium_mode: str\n    grace_mode: str\n    pay_early_arrival: bool\n    is_active: bool\n    row_version: int\n\n\nclass ShiftCreateIn(BaseModel):",
    ),
    (
        "ShiftCreateIn add grace_mode/pay_early_arrival",
        "    salaried_premium_mode: str = Field(default='full')\n",
        "    salaried_premium_mode: str = Field(default='full')\n"
        "    grace_mode: str = Field(default='threshold')\n"
        "    pay_early_arrival: bool = False\n",
    ),
    (
        "ShiftCreateIn add grace_mode validator",
        "    @field_validator('salaried_premium_mode')\n"
        "    @classmethod\n"
        "    def _v_salaried(cls, v: str) -> str:\n"
        "        if v not in _SALARIED_PREMIUM_MODES:\n"
        "            raise ValueError(f'salaried_premium_mode must be one of {_SALARIED_PREMIUM_MODES}')\n"
        "        return v\n",
        "    @field_validator('salaried_premium_mode')\n"
        "    @classmethod\n"
        "    def _v_salaried(cls, v: str) -> str:\n"
        "        if v not in _SALARIED_PREMIUM_MODES:\n"
        "            raise ValueError(f'salaried_premium_mode must be one of {_SALARIED_PREMIUM_MODES}')\n"
        "        return v\n"
        "\n"
        "    @field_validator('grace_mode')\n"
        "    @classmethod\n"
        "    def _v_grace_mode(cls, v: str) -> str:\n"
        "        if v not in _GRACE_MODES:\n"
        "            raise ValueError(f'grace_mode must be one of {_GRACE_MODES}')\n"
        "        return v\n",
    ),
    (
        "ShiftPatchIn add grace_mode/pay_early_arrival",
        "    salaried_premium_mode: str | None = None\n    is_active: bool | None = None\n",
        "    salaried_premium_mode: str | None = None\n"
        "    grace_mode: str | None = None\n"
        "    pay_early_arrival: bool | None = None\n"
        "    is_active: bool | None = None\n",
    ),
])

# =========================================================================
# 4. shifts.py
# =========================================================================
patch_file("app/api/v1/shifts.py", [
    (
        "_to_out add grace_mode/pay_early_arrival",
        "        salaried_premium_mode=s.salaried_premium_mode,\n        is_active=s.is_active, row_version=s.row_version,",
        "        salaried_premium_mode=s.salaried_premium_mode,\n"
        "        grace_mode=s.grace_mode, pay_early_arrival=s.pay_early_arrival,\n"
        "        is_active=s.is_active, row_version=s.row_version,",
    ),
    (
        "create_shift constructor add grace_mode/pay_early_arrival",
        "        salaried_premium_mode=payload.salaried_premium_mode,\n        is_active=True, row_version=1,",
        "        salaried_premium_mode=payload.salaried_premium_mode,\n"
        "        grace_mode=payload.grace_mode, pay_early_arrival=payload.pay_early_arrival,\n"
        "        is_active=True, row_version=1,",
    ),
])

# =========================================================================
# 5. Verify
# =========================================================================
print("--- verifying ---")

if run([PY, "-c",
        "import ast,pathlib;"
        "[ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) for p in ["
        "'alembic/tenant/versions/0014_shift_grace_and_early.py',"
        "'app/db/tenant/models/attendance.py',"
        "'app/api/v1/shifts_schemas.py',"
        "'app/api/v1/shifts.py']];"
        "print('parse OK')"]) != 0:
    fail("ast parse")

if run([PY, "-c", "from app.main import app; print('import OK')"]) != 0:
    fail("app import")

if run([PY, "-m", "pytest", "tests/test_permissions.py", "--collect-only", "-q"]) != 0:
    fail("test_permissions collect-only")

if run([PY, "-m", "pytest", "tests/test_shifts.py", "-v"]) != 0:
    fail("test_shifts failed")

if run([PY, "-m", "pytest", "tests/test_schema_drift.py", "-v"]) != 0:
    fail("schema drift test (models and migration 0014 disagree)")

print("2B-2a PASS")
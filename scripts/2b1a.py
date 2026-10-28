"""2B-1a: migration 0013 + AttendanceDay, AttendanceSegment, CountryCalendar.

Writes the migration and appends the three models to attendance.py. Runs
parse / import / drift test. Does NOT touch sites.py or shifts.py (that is
2B-1b). Migration is additive: three tables, indexes, grants.
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


def write_and_parse(rel: str, content: str) -> None:
    try:
        ast.parse(content)
    except SyntaxError as e:
        fail(f"{rel} has a SyntaxError before write: {e}")
    p = BACKEND / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    if not content.rstrip().endswith("# END OF FILE"):
        fail(f"{rel} does not end with '# END OF FILE'")
    if p.read_bytes()[:3] == b"\xef\xbb\xbf":
        fail(f"{rel} was written with a UTF-8 BOM")
    print(f"WROTE {rel} lines={len(content.splitlines())}")


def run(cmd: list[str]) -> int:
    print("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(BACKEND), capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip())
    if r.stderr.strip():
        print("STDERR:", r.stderr.strip())
    return r.returncode


MIGRATION = r'''"""Attendance calculation tables plus country calendar.

Revision ID: ten_0013
Revises: ten_0012
Create Date: 2026-10-28 00:00:00

Three new tables:

  attendance_day       one row per (employee, work_date). work_date is the
                       LOCAL date on which the shift STARTS - the day the
                       shift belongs to. A night shift 22:00-06:00 is ONE
                       attendance_day whose segments carry local_date values
                       on two consecutive calendar dates.

  attendance_segment   one row per rate-relevant piece of work. Cut at local
                       midnight, at day-type boundaries, and at rate-tier
                       boundaries. local_date is the real calendar date of
                       this piece; it may differ from the parent day's
                       work_date.

  country_calendar     official country holiday dates loaded from a CSV the
                       user supplies. Unique per (country_code, holiday_date).
                       day-build fails closed with holiday_calendar_missing
                       when a requested year has no rows; a missing calendar
                       is NEVER read as "no holidays".

worked_minutes = normal_minutes + overtime_minutes (paid minutes).
raw_minutes is elapsed time minus unpaid break, before rounding and grace.

source_version increments only when computed output changes (status,
minutes, segments, flags). computed_at updates on every successful
recompute. Phase 4 payslip comparisons use source_version so a no-op
recompute does not look like a change.
"""
from __future__ import annotations

import os
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ten_0013"
down_revision: Union[str, Sequence[str], None] = "ten_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _app_role() -> str:
    role = os.environ.get("TENANT_APP_DB_ROLE", "payroll_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError(f"Invalid TENANT_APP_DB_ROLE identifier: {role!r}")
    return role


def upgrade() -> None:
    op.create_table(
        "attendance_day",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("employee.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("first_in", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_out", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worked_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("normal_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("overtime_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shift_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("shift.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_attendance_day_emp_date", "attendance_day", ["employee_id", "work_date"]
    )
    op.create_index("ix_attendance_day_date", "attendance_day", ["work_date"])
    op.create_index("ix_attendance_day_status", "attendance_day", ["status"])

    op.create_table(
        "attendance_segment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("attendance_day_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("attendance_day.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("day_type", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("rate_method", sa.String(20), nullable=False),
        sa.Column("rate_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("overtime_status", sa.String(20), nullable=True),
        sa.Column("source_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_attendance_segment_day", "attendance_segment", ["attendance_day_id"])

    op.create_table(
        "country_calendar",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_country_calendar_code_date", "country_calendar", ["country_code", "holiday_date"]
    )
    op.create_index("ix_country_calendar_date", "country_calendar", ["holiday_date"])

    role = _app_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
        f"attendance_day, attendance_segment, country_calendar TO {role}"
    )


def downgrade() -> None:
    op.drop_index("ix_country_calendar_date", table_name="country_calendar")
    op.drop_table("country_calendar")
    op.drop_index("ix_attendance_segment_day", table_name="attendance_segment")
    op.drop_table("attendance_segment")
    op.drop_index("ix_attendance_day_status", table_name="attendance_day")
    op.drop_index("ix_attendance_day_date", table_name="attendance_day")
    op.drop_table("attendance_day")

# END OF FILE
'''

write_and_parse("alembic/tenant/versions/0013_attendance_calculation.py", MIGRATION)

MODELS_BLOCK = r'''

class AttendanceDay(Base, TimestampMixin):
    """One row per (employee, work_date).

    work_date is the local date on which the shift STARTS - the day the
    shift belongs to. A night shift that runs from 22:00 to 06:00 the next
    morning is ONE AttendanceDay with work_date = the starting date; its
    attendance_segment rows may carry local_date values on two consecutive
    calendar dates. This is deliberate: the day is the shift-start day,
    the segments are the real calendar pieces.

    worked_minutes = normal_minutes + overtime_minutes (paid minutes).
    raw_minutes is elapsed time minus unpaid break, before rounding and
    grace, kept for audit and drill-down.

    source_version increments ONLY when the computed output (status,
    minutes, segments, flags) actually changes. computed_at updates on
    every successful recompute. Phase 4's payslip comparison uses
    source_version, so a no-op recompute must not look like a change.
    """

    __tablename__ = "attendance_day"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_day_emp_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employee.id", ondelete="RESTRICT"),
        nullable=False,
    )
    work_date: Mapped[date] = mapped_column(Date(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    first_in: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worked_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    normal_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    overtime_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    raw_minutes: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    shift_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift.id", ondelete="RESTRICT"),
        nullable=True,
    )
    flags: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    source_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False, server_default="false")
    row_version: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")

    segments: Mapped[list["AttendanceSegment"]] = relationship(
        "AttendanceSegment",
        cascade="all, delete-orphan",
        order_by="AttendanceSegment.local_date, AttendanceSegment.kind, AttendanceSegment.tier",
    )


class AttendanceSegment(Base, TimestampMixin):
    """One rate-relevant piece of work.

    Cut at local midnight, at day-type boundaries, and at rate-tier
    boundaries. local_date is the real calendar date of this segment; it
    may differ from the parent day's work_date on a night shift.

    rate_method and rate_value record the applicable shift_rate_rule at
    build time. A multiplier needs an hourly rate to become money; that
    conversion is Phase 4 and is not done here.
    """

    __tablename__ = "attendance_segment"

    id: Mapped[uuid.UUID] = uuid_pk()
    attendance_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_day.id", ondelete="CASCADE"),
        nullable=False,
    )
    local_date: Mapped[date] = mapped_column(Date(), nullable=False)
    day_type: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    tier: Mapped[int] = mapped_column(Integer(), nullable=False)
    minutes: Mapped[int] = mapped_column(Integer(), nullable=False)
    rate_method: Mapped[str] = mapped_column(String(20), nullable=False)
    rate_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    overtime_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_refs: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


class CountryCalendar(Base, TimestampMixin):
    """Official country holiday dates, loaded from a CSV the user supplies.

    The tenant's country comes from company.country_code (default ZA). The
    loader refuses to load a year twice unless --replace is given. day-build
    raises holiday_calendar_missing if a requested year has no rows for the
    country; a missing calendar is NEVER read as "no holidays".
    """

    __tablename__ = "country_calendar"
    __table_args__ = (
        UniqueConstraint("country_code", "holiday_date", name="uq_country_calendar_code_date"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date(), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

# END OF FILE
'''

attendance_path = BACKEND / "app/db/tenant/models/attendance.py"
current = attendance_path.read_text(encoding="utf-8")

if "class AttendanceDay" in current:
    print("EXISTS AttendanceDay already in attendance.py; skipping model append")
else:
    if "# END OF FILE" not in current:
        fail("attendance.py has no '# END OF FILE' marker")
    idx = current.rfind("# END OF FILE")
    head = current[:idx].rstrip()
    new_content = head + "\n" + MODELS_BLOCK
    write_and_parse("app/db/tenant/models/attendance.py", new_content)

print("--- verifying ---")

if run([PY, "-c",
        "import ast,pathlib;"
        "[ast.parse(pathlib.Path(p).read_text(encoding='utf-8')) "
        "for p in ['alembic/tenant/versions/0013_attendance_calculation.py',"
        "'app/db/tenant/models/attendance.py']];"
        "print('parse OK')"]) != 0:
    fail("ast parse")

if run([PY, "-c", "from app.main import app; print('import OK')"]) != 0:
    fail("app import")

if run([PY, "-m", "pytest", "tests/test_permissions.py", "--collect-only", "-q"]) != 0:
    fail("test_permissions collect-only")

if run([PY, "-m", "pytest", "tests/test_schema_drift.py", "-v"]) != 0:
    fail("schema drift test (models and migration 0013 disagree)")

print("2B-1a PASS")
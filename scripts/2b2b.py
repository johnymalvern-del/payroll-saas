"""2B-2b: attendance_engine.py part 1.

Writes dataclasses, round_clock_time, apply_grace_arrival,
apply_grace_departure, build_sessions, detect_shift. Runs a short smoke
test on the pure functions (to catch function-body NameErrors), then
parse/import/collect-only/drift. Proper tests in 2B-3.
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


ENGINE = r'''"""Attendance engine - pure functions (Chapter 2B, part 1 of 3).

No DB, no HTTP. Times are tz-aware UTC unless the parameter says otherwise
(punch_local in detect_shift is site-local; round_clock_time preserves
whatever tz the caller passed).

B2: work_date is the LOCAL date the shift STARTS. A night shift running
Monday 22:00 to Tuesday 06:00 is ONE attendance_day with work_date=Monday;
its segments carry local_date values Monday and Tuesday. Sessions here
carry UTC times; build_day (2B-2c) assigns work_date and local_date.

B3: worked_minutes = normal_minutes + overtime_minutes. raw_minutes is
elapsed minus unpaid break. Below-minimum overtime goes into neither and
sets flag overtime_below_minimum.

B4: grace. threshold mode = late within grace is on time; late beyond
grace counts full lateness from scheduled start. allowance mode = only
excess beyond grace counts.

B13: rounding applies to clock-in and clock-out before session build.
nearest = half up. No rounding at segment level.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal


@dataclass
class ShiftCandidate:
    id: uuid.UUID
    start_time: time  # local wall-clock start


@dataclass
class PunchEvent:
    id: uuid.UUID
    effective_time: datetime  # UTC
    status: str = "accepted"
    shift_id: uuid.UUID | None = None
    outside_tolerance: bool = False


@dataclass
class Session:
    start: datetime  # UTC
    end: datetime | None  # UTC, None if open
    shift_id: uuid.UUID | None
    source_punch_ids: list[uuid.UUID] = field(default_factory=list)
    open: bool = True
    flags: list[str] = field(default_factory=list)


@dataclass
class BuiltSegment:
    local_date: date
    day_type: str  # weekday / saturday / sunday / public_holiday
    kind: str  # normal / overtime
    tier: int
    minutes: int
    rate_method: str  # multiplier / flat_amount
    rate_value: Decimal
    source_punch_ids: list[uuid.UUID] = field(default_factory=list)
    overtime_status: str | None = None  # not_required / pending / approved / declined


@dataclass
class DayBuildResult:
    work_date: date
    status: str
    first_in: datetime | None = None
    last_out: datetime | None = None
    worked_minutes: int = 0
    normal_minutes: int = 0
    overtime_minutes: int = 0
    raw_minutes: int = 0
    shift_id: uuid.UUID | None = None
    flags: list[str] = field(default_factory=list)
    segments: list[BuiltSegment] = field(default_factory=list)


_VALID_ROUNDING_MODES = ("nearest", "up", "down")


def round_clock_time(dt: datetime, rounding_minutes: int, rounding_mode: str) -> datetime:
    """Round dt's wall-clock minute to a multiple of rounding_minutes.

    B13. Seconds truncated to zero first. If rounding_minutes <= 0, only
    seconds are zeroed.
    """
    if rounding_mode not in _VALID_ROUNDING_MODES:
        raise ValueError(f"rounding_mode must be one of {_VALID_ROUNDING_MODES}, got {rounding_mode!r}")
    floored = dt.replace(second=0, microsecond=0)
    if rounding_minutes <= 0:
        return floored
    remainder = floored.minute % rounding_minutes
    if remainder == 0:
        return floored
    if rounding_mode == "down":
        delta = -remainder
    elif rounding_mode == "up":
        delta = rounding_minutes - remainder
    else:  # nearest
        delta = rounding_minutes - remainder if remainder * 2 >= rounding_minutes else -remainder
    return floored + timedelta(minutes=delta)


_VALID_GRACE_MODES = ("threshold", "allowance")


def apply_grace_arrival(actual: datetime, scheduled: datetime, grace_minutes: int, mode: str) -> datetime:
    """Return the effective arrival used for pay arithmetic. B4."""
    if mode not in _VALID_GRACE_MODES:
        raise ValueError(f"grace mode must be one of {_VALID_GRACE_MODES}, got {mode!r}")
    if actual <= scheduled:
        return actual
    late = (actual - scheduled).total_seconds() / 60
    if late <= grace_minutes:
        return scheduled
    return actual if mode == "threshold" else scheduled + timedelta(minutes=grace_minutes)


def apply_grace_departure(actual: datetime, scheduled: datetime, grace_minutes: int, mode: str) -> datetime:
    """Return the effective departure used for pay arithmetic. B4."""
    if mode not in _VALID_GRACE_MODES:
        raise ValueError(f"grace mode must be one of {_VALID_GRACE_MODES}, got {mode!r}")
    if actual >= scheduled:
        return actual
    early = (scheduled - actual).total_seconds() / 60
    if early <= grace_minutes:
        return scheduled
    return actual if mode == "threshold" else scheduled - timedelta(minutes=grace_minutes)


def build_sessions(
    punches: list[PunchEvent],
    max_minutes_fn: Callable[[uuid.UUID | None], int],
) -> tuple[list[Session], list[str]]:
    """Pair punches into sessions. Alternating open/close.

    If an open session's elapsed minutes exceed max_minutes_fn(shift_id)
    before the next punch, close the open session at start+max_minutes as
    missing_out, and start a new session with the current punch.
    Duplicate-status punches cannot open a session but can close one.

    Returns (sessions, day_flags). day_flags is a list of whole-day issues:
    missing_out, too_long.
    """
    if not punches:
        return [], []

    ordered = sorted(punches, key=lambda p: p.effective_time)
    sessions: list[Session] = []
    day_flags: list[str] = []
    current: Session | None = None

    for p in ordered:
        if current is None:
            if p.status == "duplicate":
                continue
            current = Session(start=p.effective_time, end=None, shift_id=p.shift_id,
                              source_punch_ids=[p.id], open=True, flags=[])
            if p.outside_tolerance:
                current.flags.append("outside_tolerance")
            continue

        max_min = max_minutes_fn(current.shift_id)
        elapsed = (p.effective_time - current.start).total_seconds() / 60
        if elapsed > max_min:
            current.end = current.start + timedelta(minutes=max_min)
            current.open = False
            current.flags.extend(["missing_out", "too_long"])
            for f in ("missing_out", "too_long"):
                if f not in day_flags:
                    day_flags.append(f)
            sessions.append(current)
            if p.status == "duplicate":
                current = None
                continue
            current = Session(start=p.effective_time, end=None, shift_id=p.shift_id,
                              source_punch_ids=[p.id], open=True, flags=[])
            if p.outside_tolerance:
                current.flags.append("outside_tolerance")
        else:
            current.end = p.effective_time
            current.open = False
            current.source_punch_ids.append(p.id)
            sessions.append(current)
            current = None

    if current is not None:
        current.flags.append("missing_out")
        if "missing_out" not in day_flags:
            day_flags.append("missing_out")
        sessions.append(current)

    return sessions, day_flags


def _is_afternoon_or_later(t: time) -> bool:
    return t.hour >= 12


def _candidate_base_dates(punch_date: date, start_time: time) -> list[date]:
    """Same day, plus previous day for afternoon/overnight starts (D6)."""
    dates = [punch_date]
    if _is_afternoon_or_later(start_time):
        dates.append(punch_date - timedelta(days=1))
    return dates


def detect_shift(
    punch_local: datetime,
    candidates: list[ShiftCandidate],
    tolerance_minutes: int,
    default_shift_id: uuid.UUID | None = None,
    expected_shift_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID | None, bool]:
    """Pick the shift for an 'in' punch (B6 / D6).

    Preference: expected_shift_id (date-specific) over default_shift_id
    (employee-level) when both are present and different. If the preferred
    shift fires, return (preferred, outside_tolerance=<is it > tolerance>).
    Otherwise: nearest candidate within tolerance, tie-break lowest id.
    Otherwise: (None, False).

    punch_local must be tz-aware (site local). Each candidate's start_time
    is naive time-of-day in that tz. Overnight: a start_time >= 12:00 is
    also considered on the previous local date, so a 22:00 shift matches
    a 06:00 punch the next morning.
    """
    if punch_local.tzinfo is None:
        raise ValueError("punch_local must be timezone-aware")

    candidate_by_id = {c.id: c for c in candidates}
    preferred: uuid.UUID | None = None
    if expected_shift_id is not None and expected_shift_id in candidate_by_id:
        preferred = expected_shift_id
    elif default_shift_id is not None and default_shift_id in candidate_by_id:
        preferred = default_shift_id

    best_id: uuid.UUID | None = None
    best_dist: float | None = None
    for cand in candidates:
        for base_date in _candidate_base_dates(punch_local.date(), cand.start_time):
            start_at = datetime.combine(base_date, cand.start_time, tzinfo=punch_local.tzinfo)
            dist = abs((punch_local - start_at).total_seconds() / 60)
            if (best_dist is None or dist < best_dist
                    or (dist == best_dist and (best_id is None or str(cand.id) < str(best_id)))):
                best_dist = dist
                best_id = cand.id

    if preferred is not None:
        within = best_id == preferred and best_dist is not None and best_dist <= tolerance_minutes
        return preferred, (not within)

    if best_id is not None and best_dist is not None and best_dist <= tolerance_minutes:
        return best_id, False
    return None, False

# END OF FILE
'''

try:
    ast.parse(ENGINE)
except SyntaxError as e:
    fail(f"engine has SyntaxError before write: {e}")

engine_path = BACKEND / "app" / "api" / "v1" / "attendance_engine.py"
engine_path.parent.mkdir(parents=True, exist_ok=True)
engine_path.write_text(ENGINE, encoding="utf-8")
if not ENGINE.rstrip().endswith("# END OF FILE"):
    fail("engine missing '# END OF FILE'")
if engine_path.read_bytes()[:3] == b"\xef\xbb\xbf":
    fail("engine written with BOM")
print(f"WROTE app/api/v1/attendance_engine.py lines={len(ENGINE.splitlines())}")

# Smoke test: catch function-body NameErrors and wrong assumptions.
SMOKE = r'''import uuid
from datetime import datetime, time, timezone
from app.api.v1.attendance_engine import (
    round_clock_time, apply_grace_arrival, apply_grace_departure,
    build_sessions, detect_shift, ShiftCandidate, PunchEvent,
)
UTC = timezone.utc
t = datetime(2024, 5, 1, 8, 7, tzinfo=UTC)
assert round_clock_time(t, 5, "nearest") == datetime(2024, 5, 1, 8, 5, tzinfo=UTC)
assert round_clock_time(t, 5, "up") == datetime(2024, 5, 1, 8, 10, tzinfo=UTC)
assert round_clock_time(t, 5, "down") == datetime(2024, 5, 1, 8, 5, tzinfo=UTC)

sch = datetime(2024, 5, 1, 8, 0, tzinfo=UTC)
late = datetime(2024, 5, 1, 8, 20, tzinfo=UTC)
assert apply_grace_arrival(datetime(2024, 5, 1, 8, 10, tzinfo=UTC), sch, 15, "threshold") == sch
assert apply_grace_arrival(late, sch, 15, "threshold") == late
assert apply_grace_arrival(late, sch, 15, "allowance") == datetime(2024, 5, 1, 8, 15, tzinfo=UTC)

se = datetime(2024, 5, 1, 17, 0, tzinfo=UTC)
early = datetime(2024, 5, 1, 16, 40, tzinfo=UTC)
assert apply_grace_departure(early, se, 15, "threshold") == early
assert apply_grace_departure(early, se, 15, "allowance") == datetime(2024, 5, 1, 16, 45, tzinfo=UTC)

sid = uuid.uuid4()
pin = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 8, 0, tzinfo=UTC), shift_id=sid)
pout = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 17, 0, tzinfo=UTC))
s, f = build_sessions([pin, pout], lambda _: 720)
assert len(s) == 1 and s[0].open is False and f == []

s2, f2 = build_sessions([pin], lambda _: 720)
assert len(s2) == 1 and s2[0].open is True and "missing_out" in f2

pin2 = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 8, 0, tzinfo=UTC), shift_id=sid)
pout2 = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 23, 0, tzinfo=UTC))
s3, f3 = build_sessions([pin2, pout2], lambda _: 720)
assert len(s3) == 2 and "missing_out" in f3 and "too_long" in f3

c1 = ShiftCandidate(id=uuid.UUID("00000000-0000-0000-0000-000000000001"), start_time=time(8, 0))
c2 = ShiftCandidate(id=uuid.UUID("00000000-0000-0000-0000-000000000002"), start_time=time(16, 0))
assert detect_shift(datetime(2024, 5, 1, 8, 5, tzinfo=UTC), [c1, c2], 30) == (c1.id, False)
assert detect_shift(datetime(2024, 5, 1, 12, 0, tzinfo=UTC), [c1, c2], 30) == (None, False)
assert detect_shift(datetime(2024, 5, 1, 12, 0, tzinfo=UTC), [c1, c2], 30, default_shift_id=c1.id) == (c1.id, True)
night = ShiftCandidate(id=uuid.UUID("00000000-0000-0000-0000-000000000003"), start_time=time(22, 0))
assert detect_shift(datetime(2024, 5, 1, 6, 0, tzinfo=UTC), [night], 500) == (night.id, False)

print("SMOKE OK")
'''

smoke_path = BACKEND / "_smoke_2b2b.py"
smoke_path.write_text(SMOKE, encoding="utf-8")
try:
    if run([PY, str(smoke_path)]) != 0:
        fail("smoke test failed")
finally:
    smoke_path.unlink(missing_ok=True)

print("--- verifying ---")

if run([PY, "-c", "from app.main import app; print('import OK')"]) != 0:
    fail("app import")

if run([PY, "-m", "pytest", "tests/test_permissions.py", "--collect-only", "-q"]) != 0:
    fail("test_permissions collect-only")

if run([PY, "-m", "pytest", "tests/test_schema_drift.py", "-v"]) != 0:
    fail("schema drift test")

print("2B-2b PASS")
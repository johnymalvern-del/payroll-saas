"""Pure-function tests for attendance_engine (Chapter 2B, 3a).

No DB, no tenant. Everything here exercises build_sessions, detect_shift,
build_day, and the small pure helpers directly with SimpleNamespace
fixtures. DB-backed tests (ensure_days, recompute_day) live in
test_attendance_engine_db.py.
"""
from __future__ import annotations
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace as SN
from zoneinfo import ZoneInfo

import pytest

from app.api.v1.attendance_engine import (
    ShiftCandidate, PunchEvent, Session,
    round_clock_time, apply_grace_arrival, apply_grace_departure,
    build_sessions, detect_shift, determine_day_type, split_at_midnight,
    apply_overtime_tiers, build_day,
)

SA = ZoneInfo("Africa/Johannesburg")
NY = timezone(timedelta(hours=-5))
UTC = timezone.utc


def sa_utc(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=SA).astimezone(UTC)


def mk_shift(start=time(8, 0), length=480, brk=60, grace_late=0, grace_early=0,
             grace_mode="threshold", rounding=0, rounding_mode="nearest",
             min_ot=0, ot_approval=True, early_pay=False, max_min=720):
    return SN(
        id=uuid.uuid4(), start_time=start, length_minutes=length,
        unpaid_break_minutes=brk, grace_late_minutes=grace_late,
        grace_early_minutes=grace_early, grace_mode=grace_mode,
        rounding_minutes=rounding, rounding_mode=rounding_mode,
        min_overtime_minutes=min_ot, overtime_requires_approval=ot_approval,
        pay_early_arrival=early_pay, max_shift_minutes=max_min,
    )


def mk_rule(tier, up_to, value="1.0", method="multiplier"):
    return SN(tier=tier, tier_up_to_minutes=up_to, method=method, value=Decimal(value))


def weekday_rules(ot_t1=30, ot_t2=None):
    r = {("weekday", "normal"): [mk_rule(1, None)]}
    if ot_t2 is not None:
        r[("weekday", "overtime")] = [mk_rule(1, ot_t1), mk_rule(2, None, "2.0")]
    else:
        r[("weekday", "overtime")] = [mk_rule(1, None)]
    return r


def build(sh, start_utc, end_utc, work_date, rules, holidays=None):
    sess = Session(start=start_utc, end=end_utc, shift_id=sh.id,
                   source_punch_ids=[uuid.uuid4()], open=False)
    return build_day(work_date=work_date, session=sess, shift=sh,
                     holiday_set=holidays or set(), site_tz=SA, rules_by_key=rules)


@pytest.mark.parametrize("start_min,mode,expected_min", [
    (7, "nearest", 5), (7, "up", 10), (7, "down", 5),
    (3, "nearest", 5), (3, "up", 5), (3, "down", 0),
    (2, "nearest", 0), (2, "up", 5), (2, "down", 0),
    (5, "nearest", 5), (5, "up", 5), (5, "down", 5),
])
def test_round_clock_time(start_min, mode, expected_min):
    t = datetime(2024, 5, 1, 8, start_min, tzinfo=UTC)
    assert round_clock_time(t, 5, mode) == datetime(2024, 5, 1, 8, expected_min, tzinfo=UTC)


def test_round_clock_time_disabled():
    t = datetime(2024, 5, 1, 8, 7, 33, tzinfo=UTC)
    assert round_clock_time(t, 0, "nearest") == datetime(2024, 5, 1, 8, 7, tzinfo=UTC)


@pytest.mark.parametrize("actual_m,mode,exp_m", [
    (10, "threshold", 0), (20, "threshold", 20), (20, "allowance", 15),
])
def test_grace_arrival(actual_m, mode, exp_m):
    sch = datetime(2024, 5, 1, 8, 0, tzinfo=UTC)
    act = datetime(2024, 5, 1, 8, actual_m, tzinfo=UTC)
    assert apply_grace_arrival(act, sch, 15, mode) == datetime(2024, 5, 1, 8, exp_m, tzinfo=UTC)


def test_grace_arrival_before_scheduled_unchanged():
    sch = datetime(2024, 5, 1, 8, 0, tzinfo=UTC)
    act = datetime(2024, 5, 1, 7, 55, tzinfo=UTC)
    assert apply_grace_arrival(act, sch, 15, "threshold") == act


@pytest.mark.parametrize("h,m,mode,eh,em", [
    (16, 50, "threshold", 17, 0),
    (16, 40, "threshold", 16, 40),
    (16, 40, "allowance", 16, 45),
])
def test_grace_departure(h, m, mode, eh, em):
    sch = datetime(2024, 5, 1, 17, 0, tzinfo=UTC)
    act = datetime(2024, 5, 1, h, m, tzinfo=UTC)
    assert apply_grace_departure(act, sch, 15, mode) == datetime(2024, 5, 1, eh, em, tzinfo=UTC)


def test_build_sessions_closed_pair():
    pin = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 6, 0, tzinfo=UTC))
    pout = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 15, 0, tzinfo=UTC))
    sessions, flags = build_sessions([pin, pout], lambda _: 720)
    assert len(sessions) == 1 and sessions[0].open is False and flags == []


def test_build_sessions_missing_out_at_end():
    pin = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 6, 0, tzinfo=UTC))
    sessions, flags = build_sessions([pin], lambda _: 720)
    assert len(sessions) == 1 and sessions[0].open is True and "missing_out" in flags


def test_build_sessions_too_long_opens_new():
    pin = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 6, 0, tzinfo=UTC))
    pout = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 23, 0, tzinfo=UTC))
    sessions, flags = build_sessions([pin, pout], lambda _: 720)
    assert len(sessions) == 2 and "missing_out" in flags and "too_long" in flags


def test_build_sessions_duplicate_cannot_open():
    dup = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 6, 0, tzinfo=UTC), status="duplicate")
    pin = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 7, 0, tzinfo=UTC))
    pout = PunchEvent(id=uuid.uuid4(), effective_time=datetime(2024, 5, 1, 15, 0, tzinfo=UTC))
    sessions, _ = build_sessions([dup, pin, pout], lambda _: 720)
    assert len(sessions) == 1 and sessions[0].start == pin.effective_time


def test_detect_shift_nearest():
    c08 = ShiftCandidate(id=uuid.UUID(int=8), start_time=time(8, 0))
    c16 = ShiftCandidate(id=uuid.UUID(int=16), start_time=time(16, 0))
    sid, outside = detect_shift(datetime(2024, 5, 1, 8, 5, tzinfo=SA), [c08, c16], 30)
    assert sid == c08.id and outside is False


def test_detect_shift_no_match():
    c08 = ShiftCandidate(id=uuid.UUID(int=8), start_time=time(8, 0))
    c16 = ShiftCandidate(id=uuid.UUID(int=16), start_time=time(16, 0))
    sid, outside = detect_shift(datetime(2024, 5, 1, 12, 0, tzinfo=SA), [c08, c16], 30)
    assert sid is None and outside is False


def test_detect_shift_preferred_outside_tolerance():
    c08 = ShiftCandidate(id=uuid.UUID(int=8), start_time=time(8, 0))
    c16 = ShiftCandidate(id=uuid.UUID(int=16), start_time=time(16, 0))
    sid, outside = detect_shift(datetime(2024, 5, 1, 12, 0, tzinfo=SA), [c08, c16], 30, default_shift_id=c08.id)
    assert sid == c08.id and outside is True


def test_detect_shift_overnight():
    night = ShiftCandidate(id=uuid.UUID(int=22), start_time=time(22, 0))
    sid, outside = detect_shift(datetime(2024, 5, 2, 6, 0, tzinfo=SA), [night], 500)
    assert sid == night.id and outside is False


def test_detect_shift_tiebreak_lowest_id():
    a = ShiftCandidate(id=uuid.UUID(int=1), start_time=time(8, 0))
    b = ShiftCandidate(id=uuid.UUID(int=2), start_time=time(8, 0))
    sid, _ = detect_shift(datetime(2024, 5, 1, 8, 0, tzinfo=SA), [a, b], 30)
    assert sid == a.id


@pytest.mark.parametrize("d,holidays,expected", [
    (date(2024, 5, 1), {date(2024, 5, 1)}, "public_holiday"),
    (date(2024, 5, 4), set(), "saturday"),
    (date(2024, 5, 5), set(), "sunday"),
    (date(2024, 5, 6), set(), "weekday"),
    (date(2024, 5, 4), {date(2024, 5, 4)}, "public_holiday"),
])
def test_determine_day_type(d, holidays, expected):
    assert determine_day_type(d, holidays) == expected


def test_split_sa_night():
    parts = split_at_midnight(sa_utc(2024, 5, 4, 22, 0), sa_utc(2024, 5, 5, 6, 0), SA)
    assert len(parts) == 2
    d1, _, _, m1 = parts[0]
    d2, _, _, m2 = parts[1]
    assert d1 == date(2024, 5, 4) and d2 == date(2024, 5, 5) and m1 + m2 == 480


def test_split_ny_night():
    start = datetime(2024, 5, 4, 20, 0, tzinfo=NY).astimezone(UTC)
    end = datetime(2024, 5, 5, 4, 0, tzinfo=NY).astimezone(UTC)
    parts = split_at_midnight(start, end, NY)
    assert len(parts) == 2
    d1, _, _, m1 = parts[0]
    d2, _, _, m2 = parts[1]
    assert d1 == date(2024, 5, 4) and d2 == date(2024, 5, 5) and m1 + m2 == 480


def test_overtime_tiers_single():
    r = mk_rule(1, None)
    result = apply_overtime_tiers(90, [r])
    assert len(result) == 1 and result[0] == (1, 90, r)


def test_overtime_tiers_two():
    r1, r2 = mk_rule(1, 30), mk_rule(2, None)
    result = apply_overtime_tiers(120, [r1, r2])
    assert len(result) == 2 and result[0] == (1, 30, r1) and result[1] == (2, 90, r2)


def test_overtime_tiers_below_first_cap():
    r1, r2 = mk_rule(1, 30), mk_rule(2, None)
    result = apply_overtime_tiers(20, [r1, r2])
    assert len(result) == 1 and result[0] == (1, 20, r1)


def test_overtime_tiers_empty():
    assert apply_overtime_tiers(0, [mk_rule(1, None)]) == []
    assert apply_overtime_tiers(90, []) == []


def test_build_day_normal_weekday():
    sh = mk_shift()
    r = build(sh, sa_utc(2024, 5, 1, 8, 0), sa_utc(2024, 5, 1, 17, 0), date(2024, 5, 1), weekday_rules())
    assert r.normal_minutes == 420 and r.overtime_minutes == 60 and r.worked_minutes == 480


def test_build_day_grace_arrival_threshold():
    sh = mk_shift(grace_late=15, grace_mode="threshold")
    r = build(sh, sa_utc(2024, 5, 1, 8, 20), sa_utc(2024, 5, 1, 16, 0), date(2024, 5, 1), weekday_rules())
    assert r.normal_minutes == 400


def test_build_day_grace_arrival_allowance():
    sh = mk_shift(grace_late=15, grace_mode="allowance")
    r = build(sh, sa_utc(2024, 5, 1, 8, 20), sa_utc(2024, 5, 1, 16, 0), date(2024, 5, 1), weekday_rules())
    assert r.normal_minutes == 405


def test_build_day_grace_departure_threshold():
    sh = mk_shift(grace_early=15, grace_mode="threshold")
    r = build(sh, sa_utc(2024, 5, 1, 8, 0), sa_utc(2024, 5, 1, 15, 40), date(2024, 5, 1), weekday_rules())
    assert r.normal_minutes == 400


def test_build_day_grace_departure_allowance():
    sh = mk_shift(grace_early=15, grace_mode="allowance")
    r = build(sh, sa_utc(2024, 5, 1, 8, 0), sa_utc(2024, 5, 1, 15, 40), date(2024, 5, 1), weekday_rules())
    assert r.normal_minutes == 405


def test_build_day_early_ignored():
    sh = mk_shift(early_pay=False)
    r = build(sh, sa_utc(2024, 5, 1, 7, 30), sa_utc(2024, 5, 1, 16, 0), date(2024, 5, 1), weekday_rules())
    assert "early_arrival_ignored" in r.flags and r.normal_minutes == 420 and r.overtime_minutes == 0


def test_build_day_early_paid():
    sh = mk_shift(early_pay=True)
    r = build(sh, sa_utc(2024, 5, 1, 7, 30), sa_utc(2024, 5, 1, 16, 0), date(2024, 5, 1), weekday_rules())
    assert r.normal_minutes == 420 and r.overtime_minutes == 30 and r.worked_minutes == 450


def test_build_day_tier_split():
    sh = mk_shift()
    rules = weekday_rules(ot_t1=30, ot_t2="open")
    r = build(sh, sa_utc(2024, 5, 1, 8, 0), sa_utc(2024, 5, 1, 18, 0), date(2024, 5, 1), rules)
    ot_segs = [(s.tier, s.minutes) for s in r.segments if s.kind == "overtime"]
    assert (1, 30) in ot_segs and (2, 90) in ot_segs


def test_build_day_setup_error_no_rule():
    sh = mk_shift()
    rules = {("weekday", "normal"): [mk_rule(1, None)]}
    r = build(sh, sa_utc(2024, 5, 1, 8, 0), sa_utc(2024, 5, 1, 17, 0), date(2024, 5, 1), rules)
    assert "setup_error" in r.flags and all(s.kind == "normal" for s in r.segments)


def test_build_day_night_shift_split():
    sh = mk_shift(start=time(22, 0), brk=60)
    rules = {
        ("saturday", "normal"): [mk_rule(1, None)],
        ("sunday", "normal"): [mk_rule(1, None)],
    }
    r = build(sh, sa_utc(2024, 5, 4, 22, 0), sa_utc(2024, 5, 5, 6, 0), date(2024, 5, 4), rules)
    assert len(r.segments) == 2
    dates = sorted(s.local_date for s in r.segments)
    types = sorted(s.day_type for s in r.segments)
    assert dates == [date(2024, 5, 4), date(2024, 5, 5)]
    assert types == ["saturday", "sunday"]
    assert sum(s.minutes for s in r.segments) == r.normal_minutes


def test_minutes_invariant():
    sh = mk_shift()
    rules = weekday_rules(ot_t1=30, ot_t2="open")
    r = build(sh, sa_utc(2024, 5, 1, 8, 0), sa_utc(2024, 5, 1, 18, 0), date(2024, 5, 1), rules)
    assert sum(s.minutes for s in r.segments) == r.worked_minutes

# END OF FILE
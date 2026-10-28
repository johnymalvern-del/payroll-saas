"""Attendance engine - pure functions (Chapter 2B).

Pure helpers in the first half (round_clock_time, grace, build_sessions,
detect_shift, day types, midnight split, overtime tiers, build_day) take
plain values and return plain values. DB helpers in the second half
(ensure_days, recompute_day) load data, call the pure helpers, and persist.

B2: work_date is the LOCAL date the shift STARTS. A night shift running
Monday 22:00 to Tuesday 06:00 is ONE attendance_day with work_date=Monday;
its segments carry local_date values Monday and Tuesday.

B3: worked_minutes = normal_minutes + overtime_minutes. raw_minutes is
elapsed time minus unpaid break, before rounding and grace.

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
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text

from app.core.errors import AppError
from app.core.rate_lookup import find_rule_for_minute, NoApplicableRateRule
from app.db.tenant.models.attendance import (
    Adjustment,
    AttendanceDay, AttendanceSegment, CountryCalendar, EmployeeWorkPattern, ExceptionItem,
    PublicHolidayTenant, Punch, Shift, ShiftRateRule, WorkPattern, WorkPatternDay,
)
from app.db.tenant.models.organisation import Company
from app.db.tenant.models.people import Employee


@dataclass
class ShiftCandidate:
    id: uuid.UUID
    start_time: time


@dataclass
class PunchEvent:
    id: uuid.UUID
    effective_time: datetime
    status: str = "accepted"
    shift_id: uuid.UUID | None = None
    outside_tolerance: bool = False


@dataclass
class Session:
    start: datetime
    end: datetime | None
    shift_id: uuid.UUID | None
    source_punch_ids: list[uuid.UUID] = field(default_factory=list)
    open: bool = True
    flags: list[str] = field(default_factory=list)


@dataclass
class BuiltSegment:
    local_date: date
    day_type: str
    kind: str
    tier: int
    minutes: int
    rate_method: str
    rate_value: Decimal
    source_punch_ids: list[uuid.UUID] = field(default_factory=list)
    overtime_status: str | None = None


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
_VALID_GRACE_MODES = ("threshold", "allowance")


def round_clock_time(dt: datetime, rounding_minutes: int, rounding_mode: str) -> datetime:
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
    else:
        delta = rounding_minutes - remainder if remainder * 2 >= rounding_minutes else -remainder
    return floored + timedelta(minutes=delta)


def apply_grace_arrival(actual: datetime, scheduled: datetime, grace_minutes: int, mode: str) -> datetime:
    if mode not in _VALID_GRACE_MODES:
        raise ValueError(f"grace mode must be one of {_VALID_GRACE_MODES}, got {mode!r}")
    if actual <= scheduled:
        return actual
    late = (actual - scheduled).total_seconds() / 60
    if late <= grace_minutes:
        return scheduled
    return actual if mode == "threshold" else scheduled + timedelta(minutes=grace_minutes)


def apply_grace_departure(actual: datetime, scheduled: datetime, grace_minutes: int, mode: str) -> datetime:
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


def determine_day_type(local_date: date, holiday_set: set[date]) -> str:
    if local_date in holiday_set:
        return "public_holiday"
    wd = local_date.weekday()
    if wd == 6:
        return "sunday"
    if wd == 5:
        return "saturday"
    return "weekday"


def split_at_midnight(
    start_utc: datetime,
    end_utc: datetime | None,
    site_tz,
) -> list[tuple[date, datetime, datetime, int]]:
    if end_utc is None or end_utc <= start_utc:
        return []
    result: list[tuple[date, datetime, datetime, int]] = []
    current = start_utc
    safety = 0
    while current < end_utc and safety < 100:
        local_now = current.astimezone(site_tz)
        local_date = local_now.date()
        next_local = datetime.combine(local_date + timedelta(days=1), time(0, 0), tzinfo=site_tz)
        next_utc = next_local.astimezone(timezone.utc)
        if next_utc >= end_utc:
            minutes = int((end_utc - current).total_seconds() / 60)
            if minutes > 0:
                result.append((local_date, current, end_utc, minutes))
            break
        minutes = int((next_utc - current).total_seconds() / 60)
        if minutes > 0:
            result.append((local_date, current, next_utc, minutes))
        current = next_utc
        safety += 1
    return result


def apply_overtime_tiers(
    total_minutes: int,
    rules: list,
) -> list[tuple[int, int, object]]:
    if total_minutes <= 0 or not rules:
        return []
    sorted_rules = sorted(rules, key=lambda r: r.tier)
    result: list[tuple[int, int, object]] = []
    prev_boundary = 0
    for rule in sorted_rules:
        upper = rule.tier_up_to_minutes if rule.tier_up_to_minutes is not None else total_minutes
        if upper <= prev_boundary:
            continue
        portion_end = min(upper, total_minutes)
        portion = portion_end - prev_boundary
        if portion > 0:
            result.append((rule.tier, portion, rule))
        prev_boundary = portion_end
        if prev_boundary >= total_minutes:
            break
    return result


def build_day(
    *,
    work_date: date,
    session: Session,
    shift,
    holiday_set: set[date],
    site_tz,
    rules_by_key: dict,
    adjustment=None,
) -> DayBuildResult:
    if adjustment is not None and getattr(adjustment, "outcome", None) == "revert":
        adjustment = None
    if adjustment is not None and getattr(adjustment, "outcome", None) in ("leave", "sick", "absent", "day_off"):
        adj_flags: list[str] = []
        if adjustment.outcome in ("leave", "sick"):
            adj_flags.append("unreconciled_leave")
        return DayBuildResult(
            work_date=work_date,
            status=adjustment.outcome,
            flags=adj_flags,
        )
    if adjustment is not None and getattr(adjustment, "outcome", None) == "worked":
        tin = getattr(adjustment, "time_in", None)
        tout = getattr(adjustment, "time_out", None)
        if tin is None or tout is None:
            return DayBuildResult(
                work_date=work_date,
                status="missing_punch",
                flags=["incomplete_adjustment"],
            )
        session = Session(
            start=tin, end=tout, shift_id=session.shift_id,
            source_punch_ids=[], open=False, flags=list(session.flags),
        )
    if session.end is None:
        return DayBuildResult(
            work_date=work_date, status="missing_punch",
            first_in=session.start, shift_id=session.shift_id,
            flags=["missing_out"] + list(session.flags))

    flags = list(session.flags)
    scheduled_start_local = datetime.combine(work_date, shift.start_time, tzinfo=site_tz)
    scheduled_end_local = scheduled_start_local + timedelta(minutes=shift.length_minutes)
    scheduled_start_utc = scheduled_start_local.astimezone(timezone.utc)
    scheduled_end_utc = scheduled_end_local.astimezone(timezone.utc)

    actual_in = round_clock_time(session.start, shift.rounding_minutes, shift.rounding_mode)
    actual_out = round_clock_time(session.end, shift.rounding_minutes, shift.rounding_mode)

    eff_in = apply_grace_arrival(actual_in, scheduled_start_utc, shift.grace_late_minutes, shift.grace_mode)
    eff_out = apply_grace_departure(actual_out, scheduled_end_utc, shift.grace_early_minutes, shift.grace_mode)

    if eff_in < scheduled_start_utc and not shift.pay_early_arrival:
        eff_in = scheduled_start_utc
        if "early_arrival_ignored" not in flags:
            flags.append("early_arrival_ignored")

    if eff_out <= eff_in:
        return DayBuildResult(
            work_date=work_date, status="missing_punch",
            first_in=eff_in, last_out=eff_out,
            shift_id=session.shift_id, flags=flags + ["invalid_session"])

    pre_min = int((scheduled_start_utc - eff_in).total_seconds() / 60) if eff_in < scheduled_start_utc else 0
    post_min = int((eff_out - scheduled_end_utc).total_seconds() / 60) if eff_out > scheduled_end_utc else 0
    within_min = max(0, int((min(eff_out, scheduled_end_utc) - max(eff_in, scheduled_start_utc)).total_seconds() / 60))

    normal_min = max(0, within_min - shift.unpaid_break_minutes)
    overtime_min = pre_min + post_min

    if 0 < overtime_min < shift.min_overtime_minutes:
        overtime_min = 0
        pre_min = 0
        post_min = 0
        if "overtime_below_minimum" not in flags:
            flags.append("overtime_below_minimum")

    worked_min = normal_min + overtime_min
    elapsed_min = int((eff_out - eff_in).total_seconds() / 60)
    raw_min = max(0, elapsed_min - shift.unpaid_break_minutes)

    segments: list[BuiltSegment] = []

    if normal_min > 0:
        normal_start = max(eff_in, scheduled_start_utc)
        normal_end = normal_start + timedelta(minutes=normal_min)
        for local_date, seg_start, seg_end, seg_min in split_at_midnight(normal_start, normal_end, site_tz):
            if seg_min <= 0:
                continue
            day_type = determine_day_type(local_date, holiday_set)
            rules = rules_by_key.get((day_type, "normal"), [])
            if not rules:
                if "setup_error" not in flags:
                    flags.append("setup_error")
                continue
            try:
                rule = find_rule_for_minute(rules, 1)
            except NoApplicableRateRule:
                if "setup_error" not in flags:
                    flags.append("setup_error")
                continue
            segments.append(BuiltSegment(
                local_date=local_date, day_type=day_type, kind="normal",
                tier=rule.tier, minutes=seg_min,
                rate_method=rule.method, rate_value=rule.value,
                source_punch_ids=list(session.source_punch_ids),
                overtime_status=None))

    if overtime_min > 0:
        ot_status = "pending" if shift.overtime_requires_approval else "not_required"
        spans: list[tuple[datetime, datetime, int, int]] = []
        if pre_min > 0:
            spans.append((eff_in, scheduled_start_utc, 0, pre_min))
        if post_min > 0:
            spans.append((scheduled_end_utc, eff_out, pre_min, pre_min + post_min))

        for span_start, span_end, cum_start, cum_end in spans:
            for local_date, seg_start, seg_end, _seg_min in split_at_midnight(span_start, span_end, site_tz):
                day_type = determine_day_type(local_date, holiday_set)
                ot_rules = rules_by_key.get((day_type, "overtime"), [])
                if not ot_rules:
                    if "setup_error" not in flags:
                        flags.append("setup_error")
                    continue
                sub_cum_start = cum_start + int((seg_start - span_start).total_seconds() / 60)
                sub_cum_end = cum_start + int((seg_end - span_start).total_seconds() / 60)
                tier_portions = apply_overtime_tiers(overtime_min, ot_rules)
                prev_cum = 0
                for tier, tier_minutes, rule in tier_portions:
                    tier_start_cum = prev_cum
                    tier_end_cum = prev_cum + tier_minutes
                    port_start = max(sub_cum_start, tier_start_cum)
                    port_end = min(sub_cum_end, tier_end_cum)
                    if port_end > port_start:
                        minutes = int(port_end - port_start)
                        if minutes > 0:
                            segments.append(BuiltSegment(
                                local_date=local_date, day_type=day_type,
                                kind="overtime", tier=tier, minutes=minutes,
                                rate_method=rule.method, rate_value=rule.value,
                                source_punch_ids=list(session.source_punch_ids),
                                overtime_status=ot_status))
                    prev_cum = tier_end_cum

    segments.sort(key=lambda s: (s.local_date, s.kind, s.tier))
    if worked_min == 0 and not segments:
        status = "missing_punch" if "missing_out" in flags else "no_shift_match"
    else:
        status = "worked"

    return DayBuildResult(
        work_date=work_date, status=status,
        first_in=eff_in, last_out=eff_out,
        worked_minutes=worked_min, normal_minutes=normal_min,
        overtime_minutes=overtime_min, raw_minutes=raw_min,
        shift_id=session.shift_id, flags=flags, segments=segments)


def _tenant_local_today(db):
    company = db.scalar(select(Company))
    if company is None:
        raise AppError("company_missing", "Company row not found", 500)
    tz = ZoneInfo(company.default_timezone)
    return datetime.now(timezone.utc).astimezone(tz).date(), tz


def _load_holiday_set(db, country_code, from_date, to_date):
    years = set(range(from_date.year, to_date.year + 1))
    year_start = date(min(years), 1, 1)
    year_end = date(max(years), 12, 31)
    rows = db.scalars(select(CountryCalendar).where(
        CountryCalendar.country_code == country_code,
        CountryCalendar.holiday_date >= year_start,
        CountryCalendar.holiday_date <= year_end,
    )).all()
    by_year = {}
    for r in rows:
        by_year[r.holiday_date.year] = by_year.get(r.holiday_date.year, 0) + 1
    for y in years:
        if by_year.get(y, 0) == 0:
            raise AppError("holiday_calendar_missing",
                f"country_calendar has no rows for {country_code} in {y}", 400,
                {"country_code": country_code, "year": y})
    return {r.holiday_date for r in rows if from_date <= r.holiday_date <= to_date}


def _holiday_set_for(db, country_code, from_date, to_date, employee):
    base = _load_holiday_set(db, country_code, from_date, to_date)
    overrides = db.scalars(select(PublicHolidayTenant).where(
        PublicHolidayTenant.is_active.is_(True),
        PublicHolidayTenant.holiday_date >= from_date,
        PublicHolidayTenant.holiday_date <= to_date,
        or_(PublicHolidayTenant.site_id.is_(None),
            PublicHolidayTenant.site_id == employee.site_id),
        or_(PublicHolidayTenant.department_id.is_(None),
            PublicHolidayTenant.department_id == employee.department_id),
    )).all()
    by_date = {}
    for o in overrides:
        by_date.setdefault(o.holiday_date, []).append(o)
    for d, os_ in by_date.items():
        os_.sort(key=lambda o: (o.department_id is None, o.site_id is None))
        winner = os_[0]
        if winner.is_working_day_override:
            base.discard(d)
        else:
            base.add(d)
    return base


def _employee_expected(db, employee, work_date):
    ewp = db.scalar(select(EmployeeWorkPattern).where(
        EmployeeWorkPattern.employee_id == employee.id,
        EmployeeWorkPattern.effective_from <= work_date,
        or_(EmployeeWorkPattern.effective_to.is_(None),
            EmployeeWorkPattern.effective_to >= work_date),
    ).order_by(EmployeeWorkPattern.effective_from.desc()).limit(1))
    pattern = None
    if ewp is not None:
        pattern = db.get(WorkPattern, ewp.work_pattern_id)
    elif employee.work_pattern_id is not None:
        pattern = db.get(WorkPattern, employee.work_pattern_id)
    if pattern is not None and pattern.is_active:
        idx = (work_date - pattern.anchor_date).days % pattern.cycle_length_days
        wpd = db.scalar(select(WorkPatternDay).where(
            WorkPatternDay.work_pattern_id == pattern.id,
            WorkPatternDay.day_index == idx,
        ))
        if wpd is not None:
            return bool(wpd.is_expected), wpd.expected_shift_id
        return False, None
    return work_date.weekday() < 5, None


def _has_punches_on(db, employee_id, work_date, tz):
    start_local = datetime.combine(work_date, time(0, 0), tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    cnt = db.scalar(select(func.count()).select_from(Punch).where(
        Punch.employee_id == employee_id,
        Punch.effective_time >= start_local.astimezone(timezone.utc),
        Punch.effective_time < end_local.astimezone(timezone.utc),
    ))
    return (cnt or 0) > 0


def _pattern_length_minutes(db, employee, work_date):
    _, shift_id = _employee_expected(db, employee, work_date)
    if shift_id is None:
        shift_id = employee.default_shift_id
    if shift_id is not None:
        sh = db.get(Shift, shift_id)
        if sh is not None:
            return sh.length_minutes
    return 480


def _new_day(employee_id, work_date, status, *, flags=None, worked=0, normal=0,
             overtime=0, raw=0, shift_id=None):
    return AttendanceDay(
        employee_id=employee_id, work_date=work_date, status=status,
        flags=list(flags or []), worked_minutes=worked, normal_minutes=normal,
        overtime_minutes=overtime, raw_minutes=raw, shift_id=shift_id,
        source_version=0, locked=False, row_version=1)


def ensure_days(db, employee_ids, from_date, to_date, *, absent_grace_days=1):
    today_local, tz = _tenant_local_today(db)
    end = min(to_date, today_local)
    if end < from_date:
        return 0
    company = db.scalar(select(Company))
    if company is None:
        raise AppError("company_missing", "Company row not found", 500)
    created = 0
    for eid in employee_ids:
        employee = db.get(Employee, eid)
        if employee is None:
            continue
        if employee.hire_date > end:
            continue
        if employee.termination_date is not None and employee.termination_date < from_date:
            continue
        emp_holidays = _holiday_set_for(db, company.country_code, from_date, end, employee)
        start = max(from_date, employee.hire_date)
        stop = end if employee.termination_date is None else min(end, employee.termination_date)
        cur = start
        while cur <= stop:
            exists = db.scalar(select(AttendanceDay.id).where(
                AttendanceDay.employee_id == employee.id,
                AttendanceDay.work_date == cur))
            if exists is not None:
                cur += timedelta(days=1)
                continue
            if _has_punches_on(db, employee.id, cur, tz):
                cur += timedelta(days=1)
                continue
            is_holiday = cur in emp_holidays
            expected, _ = _employee_expected(db, employee, cur)
            if is_holiday:
                if expected:
                    db.add(_new_day(employee.id, cur, "public_holiday_unworked"))
                    created += 1
            elif expected:
                if employee.clocks is False:
                    length = _pattern_length_minutes(db, employee, cur)
                    db.add(_new_day(employee.id, cur, "worked",
                        flags=["clocks_false_synthetic"],
                        worked=length, normal=length, raw=length))
                    created += 1
                else:
                    days_since = (today_local - cur).days
                    if days_since >= absent_grace_days:
                        db.add(_new_day(employee.id, cur, "absent"))
                    else:
                        db.add(_new_day(employee.id, cur, "missing_punch", flags=["waiting_grace"]))
                    created += 1
            cur += timedelta(days=1)
        _stale = db.scalars(select(AttendanceDay).where(
            AttendanceDay.employee_id == employee.id,
            AttendanceDay.work_date >= start,
            AttendanceDay.work_date <= stop,
            AttendanceDay.source_version == 0,
        )).all()
        for _d in _stale:
            _sync_exceptions(db, employee.id, _d.work_date, _d)
    db.commit()
    return created


def _load_shift_candidates(db):
    rows = db.scalars(select(Shift).where(Shift.is_active.is_(True))).all()
    return [ShiftCandidate(id=r.id, start_time=r.start_time) for r in rows]


def _load_rate_rules(db, shift_id, on_date):
    rows = db.scalars(select(ShiftRateRule).where(
        ShiftRateRule.shift_id == shift_id,
        ShiftRateRule.effective_from <= on_date,
        or_(ShiftRateRule.effective_to.is_(None), ShiftRateRule.effective_to >= on_date),
    )).all()
    result = {}
    for r in rows:
        result.setdefault((r.day_type, r.kind), []).append(r)
    return result


def _segments_differ(db, existing, new_segments):
    if existing is None or existing.id is None:
        return len(new_segments) > 0
    old = db.scalars(select(AttendanceSegment).where(
        AttendanceSegment.attendance_day_id == existing.id
    ).order_by(AttendanceSegment.local_date, AttendanceSegment.kind, AttendanceSegment.tier)).all()
    if len(old) != len(new_segments):
        return True
    for o, n in zip(old, new_segments):
        if (o.local_date != n.local_date or o.day_type != n.day_type
                or o.kind != n.kind or o.tier != n.tier or o.minutes != n.minutes
                or o.rate_method != n.rate_method or o.rate_value != n.rate_value):
            return True
    return False


def _persist_day(db, employee_id, work_date, *, status, first_in, last_out,
                 normal, overtime, worked, raw, shift_id, flags, segments, existing):
    content_changed = (
        existing is None
        or existing.status != status
        or existing.normal_minutes != normal
        or existing.overtime_minutes != overtime
        or existing.worked_minutes != worked
        or existing.raw_minutes != raw
        or (existing.flags or []) != flags
        or existing.shift_id != shift_id
        or _segments_differ(db, existing, segments))
    if existing is None:
        day = AttendanceDay(
            employee_id=employee_id, work_date=work_date, status=status,
            first_in=first_in, last_out=last_out,
            worked_minutes=worked, normal_minutes=normal,
            overtime_minutes=overtime, raw_minutes=raw,
            shift_id=shift_id, flags=flags, source_version=0,
            locked=False, row_version=1)
        db.add(day)
        db.flush()
    else:
        day = existing
        day.status = status
        day.first_in = first_in
        day.last_out = last_out
        day.worked_minutes = worked
        day.normal_minutes = normal
        day.overtime_minutes = overtime
        day.raw_minutes = raw
        day.shift_id = shift_id
        day.flags = flags
        day.row_version = day.row_version + 1
        db.flush()
    if content_changed:
        day.reviewed_at = None
        day.reviewed_by = None
        day.source_version = day.source_version + 1
        db.execute(AttendanceSegment.__table__.delete().where(
            AttendanceSegment.attendance_day_id == day.id))
        for seg in segments:
            db.add(AttendanceSegment(
                attendance_day_id=day.id,
                local_date=seg.local_date, day_type=seg.day_type,
                kind=seg.kind, tier=seg.tier, minutes=seg.minutes,
                rate_method=seg.rate_method, rate_value=seg.rate_value,
                overtime_status=seg.overtime_status,
                source_refs=[str(pid) for pid in seg.source_punch_ids]))
    day.computed_at = datetime.now(timezone.utc)
    _sync_exceptions(db, employee_id, work_date, day)
    if db.info.get("bulk_no_commit"):
        db.flush()
    else:
        db.commit()
        db.refresh(day)
    return day


def _no_punch_day(db, employee, work_date, holidays, expected, today_local,
                  existing, extra_flags=None, status_override=None):
    flags = list(extra_flags or [])
    is_holiday = work_date in holidays
    if status_override is not None:
        status = status_override
    elif is_holiday:
        status = "public_holiday_unworked"
    elif not expected:
        status = "day_off"
    elif employee.clocks is False:
        length = _pattern_length_minutes(db, employee, work_date)
        if "clocks_false_synthetic" not in flags:
            flags.append("clocks_false_synthetic")
        return _persist_day(
            db, employee.id, work_date, status="worked",
            first_in=None, last_out=None, normal=length, overtime=0,
            worked=length, raw=length, shift_id=None, flags=flags,
            segments=[], existing=existing)
    else:
        days_since = (today_local - work_date).days
        if days_since >= 1:
            status = "absent"
        else:
            status = "missing_punch"
            if "waiting_grace" not in flags:
                flags.append("waiting_grace")
    return _persist_day(
        db, employee.id, work_date, status=status,
        first_in=None, last_out=None, normal=0, overtime=0, worked=0, raw=0,
        shift_id=None, flags=flags, segments=[], existing=existing)


def _advisory_lock_key(employee_id, work_date):
    emp_low = int.from_bytes(employee_id.bytes[:4], "big", signed=False) & 0x7FFFFFFF
    days = (work_date - date(1970, 1, 1)).days & 0x7FFFFFFF
    return emp_low, days


def recompute_day(db, employee_id, work_date):
    k1, k2 = _advisory_lock_key(employee_id, work_date)
    db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:k1 AS int), CAST(:k2 AS int))"),
        {"k1": k1, "k2": k2},
    )
    employee = db.get(Employee, employee_id)
    if employee is None:
        return None
    existing = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == employee_id,
        AttendanceDay.work_date == work_date))
    if existing is not None and existing.locked:
        return existing
    today_local, tz = _tenant_local_today(db)
    company = db.scalar(select(Company))
    if company is None:
        raise AppError("company_missing", "Company row not found", 500)
    emp_holidays = _holiday_set_for(db, company.country_code, work_date, work_date, employee)
    expected, expected_shift_id = _employee_expected(db, employee, work_date)
    default_shift_id = employee.default_shift_id

    adj = _load_adjustments(db, employee_id, work_date)

    win_start = datetime.combine(work_date - timedelta(days=1), time(20, 0), tzinfo=tz)
    win_end = datetime.combine(work_date + timedelta(days=2), time(6, 0), tzinfo=tz)
    punch_rows = db.scalars(select(Punch).where(
        Punch.employee_id == employee_id,
        Punch.effective_time >= win_start.astimezone(timezone.utc),
        Punch.effective_time < win_end.astimezone(timezone.utc),
        Punch.status != "duplicate",
    ).order_by(Punch.effective_time)).all()

    if not punch_rows:
        if adj is not None and adj.outcome != "revert":
            return _build_day_from_adjustment_only(
                db, employee, work_date, emp_holidays, today_local, adj,
                default_shift_id, expected_shift_id, tz, existing)
        return _no_punch_day(db, employee, work_date, emp_holidays, expected,
                             today_local, existing)

    events = [PunchEvent(id=p.id, effective_time=p.effective_time,
                         status=p.status, shift_id=None, outside_tolerance=False)
              for p in punch_rows]
    sessions, session_flags = build_sessions(events, lambda _: 720)
    day_sessions = [s for s in sessions if s.start.astimezone(tz).date() == work_date]

    if not day_sessions:
        return _no_punch_day(db, employee, work_date, emp_holidays, expected,
                             today_local, existing, extra_flags=list(session_flags))

    candidates = _load_shift_candidates(db)
    all_shifts = {c.id: db.get(Shift, c.id) for c in candidates}
    all_shifts = {k: v for k, v in all_shifts.items() if v is not None}

    for s in day_sessions:
        if s.shift_id is None:
            local_in = s.start.astimezone(tz)
            sid, outside = detect_shift(
                local_in, candidates, tolerance_minutes=60,
                default_shift_id=default_shift_id,
                expected_shift_id=expected_shift_id)
            s.shift_id = sid
            if outside:
                s.flags.append("outside_tolerance")
        if s.shift_id is None or s.end is None:
            continue
        sh = all_shifts.get(s.shift_id)
        if sh is None:
            continue
        elapsed = (s.end - s.start).total_seconds() / 60
        if elapsed > sh.max_shift_minutes:
            s.end = s.start + timedelta(minutes=sh.max_shift_minutes)
            if "missing_out" not in s.flags:
                s.flags.append("missing_out")
            if "too_long" not in s.flags:
                s.flags.append("too_long")

    day_flags = list(session_flags)
    results = []
    for s in day_sessions:
        sh = all_shifts.get(s.shift_id) if s.shift_id else None
        if sh is None:
            if "no_shift_match" not in day_flags:
                day_flags.append("no_shift_match")
            continue
        rules = _load_rate_rules(db, s.shift_id, work_date)
        result = build_day(
            work_date=work_date, session=s, shift=sh,
            holiday_set=emp_holidays, site_tz=tz, rules_by_key=rules,
            adjustment=adj)
        for f in result.flags:
            if f not in day_flags:
                day_flags.append(f)
        results.append(result)

    if not results:
        return _no_punch_day(db, employee, work_date, emp_holidays, expected,
                             today_local, existing, extra_flags=day_flags,
                             status_override="no_shift_match")

    first_in = min((r.first_in for r in results if r.first_in is not None), default=None)
    last_out = max((r.last_out for r in results if r.last_out is not None), default=None)
    total_normal = sum(r.normal_minutes for r in results)
    total_ot = sum(r.overtime_minutes for r in results)
    total_worked = total_normal + total_ot
    total_raw = sum(r.raw_minutes for r in results)
    all_segments = [seg for r in results for seg in r.segments]
    primary_shift_id = day_sessions[0].shift_id if day_sessions else None
    status = "worked" if total_worked > 0 else "missing_punch"
    return _persist_day(
        db, employee.id, work_date, status=status,
        first_in=first_in, last_out=last_out,
        normal=total_normal, overtime=total_ot, worked=total_worked, raw=total_raw,
        shift_id=primary_shift_id, flags=day_flags, segments=all_segments,
        existing=existing)


def _load_adjustments(db, employee_id, work_date):
    """Return the latest active Adjustment for (employee, work_date), or None.

    C6: adjustments are append-only; the latest one wins. If the latest is
    outcome='revert', build_day treats it as no adjustment and uses punches.
    """
    return db.scalar(
        select(Adjustment)
        .where(
            Adjustment.employee_id == employee_id,
            Adjustment.work_date == work_date,
        )
        .order_by(Adjustment.created_at.desc(), Adjustment.id.desc())
        .limit(1)
    )


def _day_snapshot(day):
    if day is None:
        return None
    return {
        "id": str(day.id),
        "employee_id": str(day.employee_id),
        "work_date": day.work_date.isoformat(),
        "status": day.status,
        "first_in": day.first_in.isoformat() if day.first_in else None,
        "last_out": day.last_out.isoformat() if day.last_out else None,
        "worked_minutes": day.worked_minutes,
        "normal_minutes": day.normal_minutes,
        "overtime_minutes": day.overtime_minutes,
        "raw_minutes": day.raw_minutes,
        "shift_id": str(day.shift_id) if day.shift_id else None,
        "flags": list(day.flags or []),
        "source_version": day.source_version,
        "locked": day.locked,
    }


def _persist_adjustment(db, *, employee_id, work_date, outcome, time_in, time_out,
                        reason_code, note, created_by, batch_id=None):
    """Insert one Adjustment (append-only). Returns the row.

    Caller orchestrates: check day is not locked, call this, call
    recompute_day, refetch the day, set adj.new_value from the snapshot,
    then commit. reason_code validation is the endpoint's job, not this
    helper's (C7).
    """
    day_before = db.scalar(select(AttendanceDay).where(
        AttendanceDay.employee_id == employee_id,
        AttendanceDay.work_date == work_date,
    ))
    old_snapshot = _day_snapshot(day_before) if day_before is not None else None
    minutes = None
    if outcome == "worked" and time_in is not None and time_out is not None:
        minutes = max(0, int((time_out - time_in).total_seconds() / 60))
    adj = Adjustment(
        employee_id=employee_id,
        work_date=work_date,
        outcome=outcome,
        time_in=time_in,
        time_out=time_out,
        minutes=minutes,
        reason_code=reason_code,
        note=note,
        created_by=created_by,
        batch_id=batch_id,
        old_value=old_snapshot,
    )
    db.add(adj)
    db.flush()
    return adj


def _build_day_from_adjustment_only(db, employee, work_date, holidays, today_local,
                                    adj, default_shift_id, expected_shift_id, tz, existing):
    """Build a day from an adjustment alone (no punches in the window).

    Called only when an adjustment exists, is not 'revert', and there are
    no punch rows. leave/sick/absent/day_off are handled directly; 'worked'
    synthesises a session from the adjustment's times.
    """
    if adj.outcome in ("leave", "sick", "absent", "day_off"):
        flags = ["unreconciled_leave"] if adj.outcome in ("leave", "sick") else []
        return _persist_day(
            db, employee.id, work_date, status=adj.outcome,
            first_in=None, last_out=None, normal=0, overtime=0, worked=0, raw=0,
            shift_id=None, flags=flags, segments=[], existing=existing)
    if adj.time_in is None or adj.time_out is None:
        return _persist_day(
            db, employee.id, work_date, status="missing_punch",
            first_in=None, last_out=None, normal=0, overtime=0, worked=0, raw=0,
            shift_id=None, flags=["incomplete_adjustment"], segments=[],
            existing=existing)
    shift = None
    if default_shift_id is not None:
        shift = db.get(Shift, default_shift_id)
    elif expected_shift_id is not None:
        shift = db.get(Shift, expected_shift_id)
    if shift is None:
        candidates = _load_shift_candidates(db)
        local_in = adj.time_in.astimezone(tz)
        sid, _ = detect_shift(local_in, candidates, tolerance_minutes=60)
        if sid:
            shift = db.get(Shift, sid)
    if shift is None:
        return _persist_day(
            db, employee.id, work_date, status="no_shift_match",
            first_in=adj.time_in, last_out=adj.time_out,
            normal=0, overtime=0, worked=0, raw=0,
            shift_id=None, flags=["no_shift_match"], segments=[], existing=existing)
    rules = _load_rate_rules(db, shift.id, work_date)
    dummy_session = Session(
        start=adj.time_in, end=adj.time_out, shift_id=shift.id,
        source_punch_ids=[], open=False, flags=[])
    result = build_day(
        work_date=work_date, session=dummy_session, shift=shift,
        holiday_set=holidays, site_tz=tz, rules_by_key=rules, adjustment=adj)
    return _persist_day(
        db, employee.id, work_date, status=result.status,
        first_in=result.first_in, last_out=result.last_out,
        normal=result.normal_minutes, overtime=result.overtime_minutes,
        worked=result.worked_minutes, raw=result.raw_minutes,
        shift_id=shift.id, flags=result.flags, segments=result.segments,
        existing=existing)


_EXCEPTION_TYPES_FROM_FLAGS = ("missing_out", "too_long")
_EXCEPTION_TYPES_FROM_STATUS = {
    "absent": "absent_expected",
    "no_shift_match": "no_shift_match",
}


def _expected_exception_types(db, employee_id, work_date, day):
    """Return the set of exception types currently warranted by the day.

    C4: derived from day flags, day status, pending overtime segments, and
    low-confidence punches on the day.
    """
    types: set[str] = set()
    if day is None:
        return types
    for f in day.flags or []:
        if f in _EXCEPTION_TYPES_FROM_FLAGS:
            types.add(f)
    mapped = _EXCEPTION_TYPES_FROM_STATUS.get(day.status)
    if mapped:
        types.add(mapped)
    pending_ot = db.scalar(
        select(func.count()).select_from(AttendanceSegment).where(
            AttendanceSegment.attendance_day_id == day.id,
            AttendanceSegment.overtime_status == "pending",
        )
    )
    if (pending_ot or 0) > 0:
        types.add("overtime_unapproved")
    # Low-confidence punches on the local date. Query punches by the
    # day's local date span in UTC; ±1 day is a safe window.
    lc = db.scalar(
        select(func.count()).select_from(Punch).where(
            Punch.employee_id == employee_id,
            Punch.status == "low_confidence",
            Punch.effective_time >= datetime.combine(
                work_date - timedelta(days=1), time(0, 0)
            ).replace(tzinfo=timezone.utc),
            Punch.effective_time < datetime.combine(
                work_date + timedelta(days=2), time(0, 0)
            ).replace(tzinfo=timezone.utc),
        )
    )
    if (lc or 0) > 0:
        types.add("low_confidence")
    return types


def _suggested_fix(exception_type):
    return {
        "missing_out": {"action": "apply_shift_end_time"},
        "too_long": {"action": "truncate_to_max"},
        "no_shift_match": {"action": "choose_shift", "candidates": []},
        "absent_expected": {"action": "mark_day_off"},
        "overtime_unapproved": {"action": "approve_overtime"},
        "low_confidence": {"action": "accept_punch"},
    }.get(exception_type, {})


def _create_exception(db, employee_id, work_date, exception_type, day):
    db.add(ExceptionItem(
        employee_id=employee_id,
        work_date=work_date,
        type=exception_type,
        source_ref={"attendance_day_id": str(day.id)} if day is not None else {},
        suggested_fix=_suggested_fix(exception_type),
        status="open",
    ))


def _sync_exceptions(db, employee_id, work_date, day):
    """Create new exceptions for current conditions; auto-resolve cleared ones.

    C4. Never creates a new exception on a locked day. Recreates an
    auto-resolved exception only if the day's source_version has advanced
    past the version recorded at resolution, so a no-op recompute does not
    resurrect it.
    """
    if day is None:
        return
    expected = _expected_exception_types(db, employee_id, work_date, day)

    all_rows = db.scalars(
        select(ExceptionItem)
        .where(
            ExceptionItem.employee_id == employee_id,
            ExceptionItem.work_date == work_date,
        )
        .order_by(ExceptionItem.created_at.desc())
    ).all()
    latest_by_type: dict = {}
    for row in all_rows:
        if row.type not in latest_by_type:
            latest_by_type[row.type] = row

    # Auto-resolve open exceptions whose condition cleared.
    for exception_type, latest in latest_by_type.items():
        if exception_type not in expected and latest.status == "open":
            latest.status = "resolved"
            latest.resolved_at = datetime.now(timezone.utc)
            latest.resolved_by = None
            latest.resolution = {
                "reason": "condition_cleared",
                "auto": True,
                "source_version_at_resolve": day.source_version,
            }

    if day.locked:
        return

    for exception_type in expected:
        latest = latest_by_type.get(exception_type)
        if latest is None:
            _create_exception(db, employee_id, work_date, exception_type, day)
            continue
        if latest.status == "open":
            continue
        if latest.status == "dismissed":
            continue
        if latest.status == "resolved":
            res = latest.resolution or {}
            if res.get("auto") and day.source_version > res.get("source_version_at_resolve", -1):
                _create_exception(db, employee_id, work_date, exception_type, day)

# END OF FILE

"""Pure tests for the fraud heuristics.

No database, no tenant provisioning -- these run in about a second. The
database-backed behaviour (which punches get fetched, what flags get written)
is covered where the wiring lives; this file pins the arithmetic and the
verdict boundaries, which is where the judgement calls are.

The tests that matter most:

  test_speed_just_over_limit_is_impossible / ..._under_ ...
      the threshold boundary is the whole feature
  test_missing_previous_fix_is_unavailable
      retention deletes punch_location after 30 days, so this is the common
      case for old punches, not an edge case. It must never read as clean.
  test_gap_below_minimum_is_inconclusive
      a 20-second gap implies a meaningless speed; calling it IMPOSSIBLE
      would be an accusation derived from GPS jitter
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.services.fraud import (
    MAX_PLAUSIBLE_SPEED_KMH,
    MIN_TRAVEL_GAP_SECONDS,
    RAPID_PUNCH_LIMIT,
    TravelVerdict,
    assess_travel,
    haversine_km,
    is_rapid_succession,
)

CT_LAT = -33.9249
CT_LON = 18.4241
# ~19.15 km north-east of the CBD.
FAR_LAT = -33.9029
FAR_LON = 18.6298

T0 = datetime(2026, 5, 1, 6, 0, tzinfo=timezone.utc)


def _at(**kwargs):
    return T0 + timedelta(**kwargs)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def test_identical_points_are_zero_apart():
    assert haversine_km(CT_LAT, CT_LON, CT_LAT, CT_LON) == pytest.approx(0.0, abs=1e-9)


def test_one_degree_of_latitude_is_about_111_km():
    assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, abs=0.5)


def test_haversine_is_symmetric():
    a = haversine_km(CT_LAT, CT_LON, FAR_LAT, FAR_LON)
    b = haversine_km(FAR_LAT, FAR_LON, CT_LAT, CT_LON)
    assert a == pytest.approx(b, rel=1e-12)


def test_haversine_survives_antipodal_points():
    # acos-style implementations produce a domain error here; haversine with a
    # clamp does not.
    d = haversine_km(0.0, 0.0, 0.0, 180.0)
    assert d == pytest.approx(20015.1, abs=1.0)


# ---------------------------------------------------------------------------
# Speed boundaries
# ---------------------------------------------------------------------------


def test_same_place_one_minute_later_is_plausible():
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=CT_LAT, longitude=CT_LON, at=_at(minutes=1),
    )
    assert r.verdict is TravelVerdict.PLAUSIBLE
    assert r.distance_km == pytest.approx(0.0, abs=1e-6)


def test_far_apart_in_two_minutes_is_impossible():
    # 19 km in 2 minutes = ~575 km/h.
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=FAR_LAT, longitude=FAR_LON, at=_at(minutes=2),
    )
    assert r.verdict is TravelVerdict.IMPOSSIBLE
    assert r.reason == "implausible_speed"
    assert r.speed_kmh is not None and r.speed_kmh > MAX_PLAUSIBLE_SPEED_KMH


def test_speed_just_under_the_limit_is_plausible():
    # Choose a gap so the implied speed is comfortably below 200 km/h.
    # 19.15 km at 190 km/h ~= 6.05 minutes; use 10 minutes => ~115 km/h.
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=FAR_LAT, longitude=FAR_LON, at=_at(minutes=10),
    )
    assert r.speed_kmh is not None
    assert r.speed_kmh < MAX_PLAUSIBLE_SPEED_KMH
    assert r.verdict is TravelVerdict.PLAUSIBLE


def test_speed_just_over_the_limit_is_impossible():
    # Same distance in 4 minutes => ~287 km/h.
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=FAR_LAT, longitude=FAR_LON, at=_at(minutes=4),
    )
    assert r.speed_kmh is not None
    assert r.speed_kmh > MAX_PLAUSIBLE_SPEED_KMH
    assert r.verdict is TravelVerdict.IMPOSSIBLE


def test_custom_limit_is_honoured():
    # 19 km in 10 min is ~115 km/h, impossible if the limit were 100.
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=FAR_LAT, longitude=FAR_LON, at=_at(minutes=10),
        max_speed_kmh=100.0,
    )
    assert r.verdict is TravelVerdict.IMPOSSIBLE


# ---------------------------------------------------------------------------
# Timeline edges
# ---------------------------------------------------------------------------


def test_identical_timestamps_are_inconclusive():
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=T0,
        latitude=FAR_LAT, longitude=FAR_LON, at=T0,
    )
    assert r.verdict is TravelVerdict.INCONCLUSIVE
    assert r.reason == "non_positive_gap"


def test_out_of_order_timestamps_are_inconclusive():
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=5),
        latitude=FAR_LAT, longitude=FAR_LON, at=T0,
    )
    assert r.verdict is TravelVerdict.INCONCLUSIVE


def test_gap_below_the_minimum_is_inconclusive_not_impossible():
    # 19 km in 20 seconds is absurd, but 20 seconds is not measurable with
    # consumer GPS. Accusing on this would be accusing on noise.
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(seconds=0),
        latitude=FAR_LAT, longitude=FAR_LON, at=_at(seconds=20),
    )
    assert r.verdict is TravelVerdict.INCONCLUSIVE
    assert r.reason == "gap_too_short_to_assess"
    assert MIN_TRAVEL_GAP_SECONDS == 60.0


# ---------------------------------------------------------------------------
# Missing and malformed input -- the retention case lives here
# ---------------------------------------------------------------------------


def test_missing_previous_fix_is_unavailable():
    """The normal case once punch_location has been purged."""
    r = assess_travel(
        prev_latitude=None, prev_longitude=None, prev_at=_at(minutes=0),
        latitude=CT_LAT, longitude=CT_LON, at=_at(minutes=30),
    )
    assert r.verdict is TravelVerdict.UNAVAILABLE
    assert r.reason == "previous_fix_unusable"


def test_missing_current_fix_is_unavailable():
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=None, longitude=None, at=_at(minutes=30),
    )
    assert r.verdict is TravelVerdict.UNAVAILABLE
    assert r.reason == "current_fix_unusable"


def test_missing_timestamp_is_unavailable():
    r = assess_travel(
        prev_latitude=CT_LAT, prev_longitude=CT_LON, prev_at=None,
        latitude=FAR_LAT, longitude=FAR_LON, at=_at(minutes=30),
    )
    assert r.verdict is TravelVerdict.UNAVAILABLE
    assert r.reason == "timestamp_missing"


def test_out_of_range_latitude_is_unavailable():
    r = assess_travel(
        prev_latitude=91.0, prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=CT_LAT, longitude=CT_LON, at=_at(minutes=30),
    )
    assert r.verdict is TravelVerdict.UNAVAILABLE


def test_nan_latitude_is_unavailable():
    r = assess_travel(
        prev_latitude=float("nan"), prev_longitude=CT_LON, prev_at=_at(minutes=0),
        latitude=CT_LAT, longitude=CT_LON, at=_at(minutes=30),
    )
    assert r.verdict is TravelVerdict.UNAVAILABLE


def test_empty_string_is_unavailable():
    """A device that sends "" for a missing fix must not be read as 0,0."""
    r = assess_travel(
        prev_latitude="", prev_longitude="", prev_at=_at(minutes=0),
        latitude=CT_LAT, longitude=CT_LON, at=_at(minutes=30),
    )
    assert r.verdict is TravelVerdict.UNAVAILABLE


def test_decimal_inputs_are_accepted():
    """The database hands over Decimal, not float."""
    r = assess_travel(
        prev_latitude=Decimal("-33.924900"), prev_longitude=Decimal("18.424100"),
        prev_at=_at(minutes=0),
        latitude=Decimal("-33.902900"), longitude=Decimal("18.629800"),
        at=_at(minutes=4),
    )
    assert r.verdict is TravelVerdict.IMPOSSIBLE


def test_string_inputs_are_accepted():
    """A device payload hands over JSON strings."""
    r = assess_travel(
        prev_latitude="-33.9249", prev_longitude="18.4241", prev_at=_at(minutes=0),
        latitude="-33.9029", longitude="18.6298", at=_at(minutes=4),
    )
    assert r.verdict is TravelVerdict.IMPOSSIBLE


# ---------------------------------------------------------------------------
# Rapid succession
# ---------------------------------------------------------------------------


def test_rapid_succession_detected():
    times = [_at(minutes=m) for m in range(RAPID_PUNCH_LIMIT)]
    assert is_rapid_succession(times) is True


def test_rapid_succession_not_triggered_below_limit():
    times = [_at(minutes=m) for m in range(RAPID_PUNCH_LIMIT - 1)]
    assert is_rapid_succession(times) is False


def test_rapid_succession_ignores_punches_outside_the_window():
    # Six punches, but spread over an hour: a normal working day.
    times = [_at(minutes=m * 12) for m in range(RAPID_PUNCH_LIMIT)]
    assert is_rapid_succession(times) is False


def test_rapid_succession_false_for_empty_list():
    assert is_rapid_succession([]) is False


def test_rapid_succession_sorts_unordered_input():
    times = list(reversed([_at(minutes=m) for m in range(RAPID_PUNCH_LIMIT)]))
    assert is_rapid_succession(times) is True

# END OF FILE
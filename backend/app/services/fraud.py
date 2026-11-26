"""Fraud heuristics for punch ingest (pure, no I/O).

Two checks, both deliberately narrow:

  impossible travel   two punches for one employee whose implied speed between
                      them is not physically achievable
  rapid succession    more punches in a short window than a person can
                      plausibly produce

Both return a verdict; neither can reject a punch. That is the same principle
as the geofence verdict, and it is not a stylistic choice: a suspected fraud
that blocks a clock-in turns a security feature into an unpaid deduction, which
is a worse outcome than the fraud it was guarding against. Suspicion is
recorded and routed to a human.

On thresholds, stated plainly because they are judgement calls:

  MAX_PLAUSIBLE_SPEED_KMH = 200
      Generous on purpose. The worst outcome is a false accusation, so the
      bound sits well above legal road speed. A 400 km journey in two hours
      implies 200 km/h and is the first thing that trips; anything slower than
      that passes. This detects the crude case -- one employee clocking in at
      two branches a province apart -- and nothing subtler. It is not a
      substitute for reviewing attendance.

  MIN_TRAVEL_GAP_SECONDS = 60
      Below a minute, GPS noise and clock jitter dominate the calculation and
      an implied speed becomes meaningless. Such a pair is INCONCLUSIVE, not
      IMPOSSIBLE: we do not know, and saying "we do not know" is more honest
      than a verdict derived from noise.

  RAPID_PUNCH_LIMIT = 6 in RAPID_PUNCH_WINDOW_MINUTES = 10
      A clock-in, a break out, a break in and a clock-out is four. Six in ten
      minutes suggests a shared device, a retry flood, or a scripted client.

Retention interaction, which matters and is easy to miss: punch_location rows
are deleted after 30 days. An impossible-travel check against a punch whose
location has expired cannot see it and must return UNAVAILABLE rather than
PLAUSIBLE. A check that silently passes because the evidence was deleted is
worse than no check, because it reports "clean" when it means "unknown".
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, unique
from typing import Any

# Mean Earth radius. The haversine formula assumes a sphere, which is accurate
# to about 0.5% -- far tighter than any distance threshold used here.
_EARTH_RADIUS_KM = 6371.0088

MAX_PLAUSIBLE_SPEED_KMH = 200.0
MIN_TRAVEL_GAP_SECONDS = 60.0
RAPID_PUNCH_WINDOW_MINUTES = 10
RAPID_PUNCH_LIMIT = 6

# Coordinates outside these bounds are not positions on Earth. A device
# reporting one is broken or lying; either way the pair cannot be assessed.
_LAT_MIN, _LAT_MAX = -90.0, 90.0
_LON_MIN, _LON_MAX = -180.0, 180.0


@unique
class TravelVerdict(str, Enum):
    PLAUSIBLE = "plausible"
    IMPOSSIBLE = "impossible"
    INCONCLUSIVE = "inconclusive"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class TravelAssessment:
    """The outcome of one impossible-travel comparison.

    distance_km and speed_kmh are None exactly when they could not be
    computed. gap_seconds is None only when a timestamp was unusable.
    """

    verdict: TravelVerdict
    reason: str
    distance_km: float | None = None
    speed_kmh: float | None = None
    gap_seconds: float | None = None


def _num(value: Any) -> float | None:
    """Coerce a numeric-ish value, returning None for anything unusable.

    Accepts Decimal from a database column, str from JSON, and float. Returns
    None for None, empty string, non-numeric text, NaN and infinity -- every
    one of which arrives in practice.
    """
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _valid_coords(lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return (_LAT_MIN <= lat <= _LAT_MAX) and (_LON_MIN <= lon <= _LON_MAX)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres.

    Numerically stable for nearby points, which the simpler spherical law of
    cosines is not: two positions ten metres apart can come out as zero or
    negative there.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    # Clamp before sqrt: floating point can push a past 1.0 for antipodal
    # points, which would raise ValueError.
    a = min(1.0, max(0.0, a))
    return 2.0 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def assess_travel(
    *,
    prev_latitude: Any,
    prev_longitude: Any,
    prev_at: datetime | None,
    latitude: Any,
    longitude: Any,
    at: datetime | None,
    max_speed_kmh: float = MAX_PLAUSIBLE_SPEED_KMH,
) -> TravelAssessment:
    """Compare two punches for the same employee, most recent first.

    Arguments are deliberately untyped beyond "anything numeric-ish" because
    the call site hands over ORM Decimals and the tests hand over strings,
    floats and None from JSON. Coercion happens here rather than at every
    caller.

    Returns UNAVAILABLE when either fix is missing or unusable. That includes
    the retention case: once punch_location is purged, prev_* arrive as None
    and this must not be read as a clean result.
    """
    plat = _num(prev_latitude)
    plon = _num(prev_longitude)
    clat = _num(latitude)
    clon = _num(longitude)

    if not _valid_coords(plat, plon):
        return TravelAssessment(TravelVerdict.UNAVAILABLE, "previous_fix_unusable")
    if not _valid_coords(clat, clon):
        return TravelAssessment(TravelVerdict.UNAVAILABLE, "current_fix_unusable")
    if prev_at is None or at is None:
        return TravelAssessment(TravelVerdict.UNAVAILABLE, "timestamp_missing")

    gap = (at - prev_at).total_seconds()

    distance = haversine_km(plat, plon, clat, clon)

    if gap <= 0:
        # Out-of-order or identical timestamps. Not fraud evidence.
        return TravelAssessment(
            TravelVerdict.INCONCLUSIVE,
            "non_positive_gap",
            distance_km=round(distance, 3),
            gap_seconds=gap,
        )

    speed = distance / (gap / 3600.0)

    if gap < MIN_TRAVEL_GAP_SECONDS:
        # A short gap with a large distance could be genuine if the fix moved,
        # but at this resolution we cannot distinguish that from noise.
        # IMPOSSIBLE would be an accusation built on jitter.
        return TravelAssessment(
            TravelVerdict.INCONCLUSIVE,
            "gap_too_short_to_assess",
            distance_km=round(distance, 3),
            speed_kmh=round(speed, 2),
            gap_seconds=gap,
        )

    if speed > max_speed_kmh:
        return TravelAssessment(
            TravelVerdict.IMPOSSIBLE,
            "implausible_speed",
            distance_km=round(distance, 3),
            speed_kmh=round(speed, 2),
            gap_seconds=gap,
        )

    return TravelAssessment(
        TravelVerdict.PLAUSIBLE,
        "speed_within_bounds",
        distance_km=round(distance, 3),
        speed_kmh=round(speed, 2),
        gap_seconds=gap,
    )


def is_rapid_succession(
    times: list[datetime],
    *,
    window_minutes: int = RAPID_PUNCH_WINDOW_MINUTES,
    limit: int = RAPID_PUNCH_LIMIT,
) -> bool:
    """True if any `limit` punches fall inside one `window_minutes` window.

    Sliding window rather than total count: six punches spread over eight
    hours is a normal day, six inside ten minutes is not. Sorting first means
    the caller can pass rows in any order.
    """
    usable = sorted(t for t in times if t is not None)
    if len(usable) < limit:
        return False
    window = timedelta(minutes=window_minutes)
    for i in range(len(usable) - limit + 1):
        if usable[i + limit - 1] - usable[i] <= window:
            return True
    return False

# END OF FILE
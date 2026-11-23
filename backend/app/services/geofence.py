"""Geofence evaluation: pure functions, no database, no HTTP.

Mirrors the discipline of app/api/v1/punch_service.py: every function takes
plain values and returns plain values. This is what makes the location
decision testable without a tenant, a database, or a GPS device.

The central idea is that a GPS fix is not a point, it is a *circle* of
radius `accuracy_m`. Deciding "inside" from a point alone is wrong whenever
the accuracy is comparable to the geofence radius: a 100 m radius with 80 m
accuracy cannot tell you which side of the boundary the employee was on.

So the error circle is compared against the geofence:

    distance + accuracy <= radius   -> the whole circle is inside  -> INSIDE
    distance - accuracy  > radius   -> the whole circle is outside -> OUTSIDE
    otherwise                       -> the circle straddles it     -> INCONCLUSIVE

INCONCLUSIVE is a first-class outcome, not an error. A policy that treats
inconclusive fixes as violations will produce false accusations; a policy
that treats them as passes will accept spoofed fixes. That trade-off is a
decision for HR/legal, not for this module -- this module only refuses to
pretend it knows.

UNAVAILABLE means the question could not be asked at all (no coordinates,
or the site has no radius configured). It is distinct from INCONCLUSIVE:
one is missing data, the other is contradictory data.

Coordinates arrive as Decimal from Numeric(9,6) columns. Everything is
converted to float for the spherical maths; the verdict is never decided
from a rounded display value.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from math import asin, cos, isfinite, radians, sin, sqrt
from typing import Any


# Mean Earth radius (IUGG). A spherical model is accurate to ~0.5% at the
# latitudes South Africa occupies; that error is far below GPS accuracy,
# so an ellipsoidal formula would add complexity without changing a verdict.
EARTH_RADIUS_M = 6_371_008.8


class GeofenceVerdict(str, Enum):
    """Outcome of comparing a GPS fix against a site's geofence."""

    INSIDE = "inside"
    OUTSIDE = "outside"
    INCONCLUSIVE = "inconclusive"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GeofenceResult:
    """Immutable result of one geofence evaluation.

    distance_m  straight-line distance from the fix to the site centre,
                or None when it cannot be computed.
    accuracy_m  the fix's reported horizontal accuracy, echoed back.
    radius_m    the site's configured radius, echoed back.
    reason      stable machine-readable tag explaining the verdict. This is
                what gets written alongside the verdict so HR can see *why*
                a day needs review.
    """

    verdict: GeofenceVerdict
    distance_m: float | None
    accuracy_m: float | None
    radius_m: float | None
    reason: str

    @property
    def is_decisive(self) -> bool:
        """True only when the fix genuinely establishes in/out."""
        return self.verdict in (GeofenceVerdict.INSIDE, GeofenceVerdict.OUTSIDE)


def _to_float(value: Any) -> float | None:
    """Coerce a Numeric/Decimal/str/float to a finite float, else None.

    Returns None for missing, non-numeric, NaN and infinite values so that
    callers never have to guard the arithmetic themselves.
    """
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            result = float(value)
        elif isinstance(value, (int, float, str)):
            result = float(value)
        else:
            return None
    except (TypeError, ValueError, ArithmeticError):
        return None
    if not isfinite(result):
        return None
    return result


def haversine_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    """Great-circle distance in metres between two WGS84 points.

    Deliberately does not validate its inputs; callers reach it only after
    the coordinate guards in evaluate_geofence have passed.
    """
    phi1 = radians(lat1)
    phi2 = radians(lat2)
    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)

    a = sin(d_phi / 2.0) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2.0) ** 2

    # Floating-point error can push `a` a hair outside [0, 1] for antipodal
    # points, which would make asin() raise. Clamp rather than crash.
    if a < 0.0:
        a = 0.0
    elif a > 1.0:
        a = 1.0

    return 2.0 * EARTH_RADIUS_M * asin(sqrt(a))


def evaluate_geofence(
    *,
    latitude: Any,
    longitude: Any,
    accuracy_m: Any,
    site_latitude: Any,
    site_longitude: Any,
    geofence_radius_m: Any,
) -> GeofenceResult:
    """Decide whether a punch location falls inside a site's geofence.

    Keyword-only by design: these six arguments are all nullable, and a
    positional call site would silently swap employee and site coordinates.

    Never raises. Every failure mode maps to a verdict plus a reason tag,
    because a punch must still be accepted and recorded even when the
    location cannot be judged -- the alternative is losing the employee's
    clock-in entirely.
    """
    accuracy = _to_float(accuracy_m)
    radius = _to_float(geofence_radius_m)

    # --- Guards: the question cannot be asked ---------------------------
    if radius is None or radius <= 0.0:
        return GeofenceResult(
            GeofenceVerdict.UNAVAILABLE, None, accuracy, radius,
            "site_radius_not_configured",
        )

    punch_lat = _to_float(latitude)
    punch_lon = _to_float(longitude)
    site_lat = _to_float(site_latitude)
    site_lon = _to_float(site_longitude)

    if punch_lat is None or punch_lon is None:
        return GeofenceResult(
            GeofenceVerdict.UNAVAILABLE, None, accuracy, radius,
            "punch_coordinates_missing",
        )
    if site_lat is None or site_lon is None:
        return GeofenceResult(
            GeofenceVerdict.UNAVAILABLE, None, accuracy, radius,
            "site_coordinates_missing",
        )
    if not (-90.0 <= punch_lat <= 90.0) or not (-180.0 <= punch_lon <= 180.0):
        return GeofenceResult(
            GeofenceVerdict.UNAVAILABLE, None, accuracy, radius,
            "punch_coordinates_out_of_range",
        )
    if not (-90.0 <= site_lat <= 90.0) or not (-180.0 <= site_lon <= 180.0):
        return GeofenceResult(
            GeofenceVerdict.UNAVAILABLE, None, accuracy, radius,
            "site_coordinates_out_of_range",
        )

    distance = haversine_m(punch_lat, punch_lon, site_lat, site_lon)

    # --- No accuracy reported ------------------------------------------
    # We have a distance but no idea how wrong it might be. Assuming the
    # best case would let a spoofed fix through; assuming the worst case
    # would flag every genuine fix. Refuse to guess.
    if accuracy is None:
        return GeofenceResult(
            GeofenceVerdict.INCONCLUSIVE, distance, None, radius,
            "gps_accuracy_unknown",
        )

    if accuracy < 0.0:
        return GeofenceResult(
            GeofenceVerdict.INCONCLUSIVE, distance, accuracy, radius,
            "gps_accuracy_invalid",
        )

    # --- The three-band comparison --------------------------------------
    if distance + accuracy <= radius:
        return GeofenceResult(
            GeofenceVerdict.INSIDE, distance, accuracy, radius,
            "within_geofence",
        )

    if distance - accuracy > radius:
        return GeofenceResult(
            GeofenceVerdict.OUTSIDE, distance, accuracy, radius,
            "outside_geofence",
        )

    return GeofenceResult(
        GeofenceVerdict.INCONCLUSIVE, distance, accuracy, radius,
        "accuracy_overlaps_boundary",
    )


def minimum_radius_for_decisive_m(accuracy_m: Any) -> float | None:
    """Rule-of-thumb warning threshold for site configuration.

    The band of ambiguous distances around a fence spans 2 * accuracy
    metres. A radius at or below twice the expected accuracy will sit
    INCONCLUSIVE for a large share of genuine arrivals, so site
    administration should warn rather than let HR discover it later in the
    exception queue.

    Returns None when no usable accuracy is supplied.
    """
    accuracy = _to_float(accuracy_m)
    if accuracy is None or accuracy < 0.0:
        return None
    return 2.0 * accuracy

# END OF FILE
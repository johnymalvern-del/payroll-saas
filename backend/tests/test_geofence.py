"""Tests for the pure geofence evaluator.

No database, no fixtures, no mocks: evaluate_geofence takes values and
returns values. Every test here runs in microseconds, which is the point --
the location decision is the part of biometric attendance most likely to be
wrong in a way nobody notices until an employee is accused of something.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.geofence import (
    EARTH_RADIUS_M,
    GeofenceVerdict as V,
    evaluate_geofence,
    haversine_m,
    minimum_radius_for_decisive_m,
)


# Cape Town CBD and Bellville: two real branches ~19.15 km apart.
CT_LAT, CT_LON = -33.9249, 18.4241
BV_LAT, BV_LON = -33.9029, 18.6298


class TestHaversine:
    def test_zero_distance_for_identical_points(self):
        assert haversine_m(CT_LAT, CT_LON, CT_LAT, CT_LON) == 0.0

    def test_is_symmetric(self):
        forward = haversine_m(CT_LAT, CT_LON, BV_LAT, BV_LON)
        backward = haversine_m(BV_LAT, BV_LON, CT_LAT, CT_LON)
        assert forward == pytest.approx(backward, rel=1e-9)

    def test_known_distance_cape_town_to_bellville(self):
        # Measured at 19 151.6 m on the sphere; the window leaves room for
        # the spherical-vs-ellipsoidal difference if the constants change.
        distance = haversine_m(CT_LAT, CT_LON, BV_LAT, BV_LON)
        assert 18_800 < distance < 19_500

    def test_one_degree_of_latitude_is_about_111_km(self):
        distance = haversine_m(0.0, 0.0, 1.0, 0.0)
        assert distance == pytest.approx(111_195, abs=200)

    def test_antipodal_points_do_not_raise(self):
        # Floating-point drift can push the haversine term outside [0, 1].
        distance = haversine_m(0.0, 0.0, 0.0, 180.0)
        assert distance == pytest.approx(3.14159265 * EARTH_RADIUS_M, rel=1e-6)


class TestMissingData:
    def test_no_site_radius_is_unavailable(self):
        result = evaluate_geofence(
            latitude=CT_LAT, longitude=CT_LON, accuracy_m=10,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=None,
        )
        assert result.verdict is V.UNAVAILABLE
        assert result.reason == "site_radius_not_configured"

    def test_zero_site_radius_is_unavailable(self):
        result = evaluate_geofence(
            latitude=CT_LAT, longitude=CT_LON, accuracy_m=10,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=0,
        )
        assert result.verdict is V.UNAVAILABLE

    def test_no_punch_coordinates_is_unavailable(self):
        result = evaluate_geofence(
            latitude=None, longitude=None, accuracy_m=10,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.UNAVAILABLE
        assert result.reason == "punch_coordinates_missing"

    def test_no_site_coordinates_is_unavailable(self):
        result = evaluate_geofence(
            latitude=CT_LAT, longitude=CT_LON, accuracy_m=10,
            site_latitude=None, site_longitude=None,
            geofence_radius_m=100,
        )
        assert result.verdict is V.UNAVAILABLE
        assert result.reason == "site_coordinates_missing"

    def test_out_of_range_latitude_is_unavailable(self):
        result = evaluate_geofence(
            latitude=91.0, longitude=CT_LON, accuracy_m=10,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.UNAVAILABLE
        assert result.reason == "punch_coordinates_out_of_range"

    def test_nan_coordinate_is_treated_as_missing(self):
        result = evaluate_geofence(
            latitude=float("nan"), longitude=CT_LON, accuracy_m=10,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.UNAVAILABLE


class TestThreeBandLogic:
    def test_dead_centre_is_inside(self):
        result = evaluate_geofence(
            latitude=CT_LAT, longitude=CT_LON, accuracy_m=5,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.INSIDE
        assert result.reason == "within_geofence"
        assert result.distance_m == pytest.approx(0.0, abs=1e-6)
        assert result.is_decisive

    def test_far_away_is_outside(self):
        result = evaluate_geofence(
            latitude=BV_LAT, longitude=BV_LON, accuracy_m=5,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.OUTSIDE
        assert result.reason == "outside_geofence"
        assert result.distance_m > 18_800

    def test_accuracy_overlapping_boundary_is_inconclusive(self):
        # ~111.2 m north of the site, radius 100 m, accuracy 12 m.
        # distance - accuracy = 99.2 m is inside the radius, while
        # distance + accuracy = 123.2 m is outside it. Straddles.
        punch_lat = CT_LAT + 0.001
        result = evaluate_geofence(
            latitude=punch_lat, longitude=CT_LON, accuracy_m=12,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.INCONCLUSIVE
        assert result.reason == "accuracy_overlaps_boundary"
        assert not result.is_decisive

    def test_unknown_accuracy_is_inconclusive_not_a_pass(self):
        # The tempting bug: distance is 0 so "obviously inside". It is not
        # decidable without an accuracy figure, and guessing accepts spoofs.
        result = evaluate_geofence(
            latitude=CT_LAT, longitude=CT_LON, accuracy_m=None,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.INCONCLUSIVE
        assert result.reason == "gps_accuracy_unknown"
        assert result.distance_m == pytest.approx(0.0, abs=1e-6)

    def test_negative_accuracy_is_inconclusive(self):
        result = evaluate_geofence(
            latitude=CT_LAT, longitude=CT_LON, accuracy_m=-3,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=100,
        )
        assert result.verdict is V.INCONCLUSIVE
        assert result.reason == "gps_accuracy_invalid"

    def test_poor_accuracy_against_small_radius_is_always_inconclusive(self):
        # 65 m accuracy against a 50 m radius cannot be decisive near the
        # fence: the error circle is wider than the fence itself.
        for offset in (0.0, 0.0002, 0.0005, 0.001):
            result = evaluate_geofence(
                latitude=CT_LAT + offset, longitude=CT_LON, accuracy_m=65,
                site_latitude=CT_LAT, site_longitude=CT_LON,
                geofence_radius_m=50,
            )
            assert result.verdict is V.INCONCLUSIVE, f"offset {offset}"

    def test_good_accuracy_against_large_radius_is_decisive(self):
        result = evaluate_geofence(
            latitude=CT_LAT + 0.0005, longitude=CT_LON, accuracy_m=8,
            site_latitude=CT_LAT, site_longitude=CT_LON,
            geofence_radius_m=300,
        )
        assert result.verdict is V.INSIDE


class TestDecimalInputs:
    def test_numeric_9_6_decimals_are_accepted(self):
        # This is exactly how the values arrive from punch.latitude.
        result = evaluate_geofence(
            latitude=Decimal("-33.924900"),
            longitude=Decimal("18.424100"),
            accuracy_m=Decimal("10.00"),
            site_latitude=Decimal("-33.924900"),
            site_longitude=Decimal("18.424100"),
            geofence_radius_m=100,
        )
        assert result.verdict is V.INSIDE

    def test_string_inputs_are_tolerated(self):
        # JSON round-trips and raw_payload echoes can deliver strings.
        result = evaluate_geofence(
            latitude="-33.9249", longitude="18.4241", accuracy_m="10",
            site_latitude="-33.9249", site_longitude="18.4241",
            geofence_radius_m=100,
        )
        assert result.verdict is V.INSIDE


class TestMinimumRadiusHelper:
    def test_doubles_the_accuracy(self):
        assert minimum_radius_for_decisive_m(25) == 50.0
        assert minimum_radius_for_decisive_m(Decimal("12.5")) == 25.0

    def test_unknown_accuracy_returns_none(self):
        assert minimum_radius_for_decisive_m(None) is None
        assert minimum_radius_for_decisive_m("nonsense") is None

# END OF FILE
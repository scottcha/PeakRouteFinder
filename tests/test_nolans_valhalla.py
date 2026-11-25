import pytest

from peakroutefinder.model import Peak
from peakroutefinder.poc.nolans import (
    decode_polyline,
    reference_leg_miles,
    route_sequence,
    total_miles_label,
)


def test_decode_polyline_supports_encoded_coordinate_precision() -> None:
    encoded = "_p~iF~ps|U_ulLnnqC_mqNvxq`@"

    assert decode_polyline(encoded, precision=5) == [
        (38.5, -120.2),
        (40.7, -120.95),
        (43.252, -126.453),
    ]


def test_decode_polyline_rejects_truncated_input() -> None:
    with pytest.raises(ValueError, match="truncated"):
        decode_polyline("_p~iF")


def test_reference_leg_miles_splits_track_at_waypoints() -> None:
    reference = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0)]
    points = [
        Peak("Start", 0.0, 0.0),
        Peak("Middle", 0.0, 1.0),
        Peak("End", 0.0, 2.0),
    ]

    legs = reference_leg_miles(reference, points)

    assert legs[0] == 0.0
    assert legs[1] == pytest.approx(69.093, abs=0.001)
    assert legs[2] == pytest.approx(69.093, abs=0.001)


def test_failed_leg_does_not_produce_partial_route_total() -> None:
    points = [Peak("A", 0.0, 0.0), Peak("B", 1.0, 1.0)]

    class FailedClient:
        def route(self, origin: Peak, destination: Peak) -> dict:
            raise RuntimeError("unreachable")

    route = route_sequence(FailedClient(), points)

    assert route["complete"] is False
    assert route["total_miles"] is None
    # Regression: a failed leg used to crash formatting with total_miles=None.
    assert total_miles_label(route) == "INCOMPLETE"

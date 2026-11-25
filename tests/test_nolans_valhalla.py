import pytest

from peakroutefinder.model import Peak
from peakroutefinder.poc.nolans import (
    decode_polyline,
    hybrid_route,
    route_sequence,
    split_reference_legs,
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


def test_split_reference_legs_returns_miles_and_geometry() -> None:
    reference = [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0), (0.0, 2.0)]
    points = [
        Peak("Start", 0.0, 0.0),
        Peak("Middle", 0.0, 1.0),
        Peak("End", 0.0, 2.0),
    ]

    legs = split_reference_legs(reference, points)

    assert len(legs) == 2
    assert legs[0]["miles"] == pytest.approx(69.093, abs=0.001)
    assert legs[1]["miles"] == pytest.approx(69.093, abs=0.001)
    assert legs[0]["geometry"] == [(0.0, 0.0), (0.0, 0.5), (0.0, 1.0)]
    assert legs[1]["geometry"] == [(0.0, 1.0), (0.0, 2.0)]


def test_hybrid_route_selects_penalized_gpx_connectors() -> None:
    valhalla_legs = [
        {
            "origin": "A",
            "destination": "B",
            "status": "ok",
            "miles": 100.0,
            "geometry": [(1.0, 1.0), (2.0, 2.0)],
            "warnings": [],
        },
        {
            "origin": "B",
            "destination": "C",
            "status": "ok",
            "miles": 90.0,
            "geometry": [(2.0, 2.0), (3.0, 3.0)],
            "warnings": [],
        },
        {
            "origin": "C",
            "destination": "D",
            "status": "error",
            "error": "unreachable",
        },
    ]
    reference_legs = [
        {"miles": 69.093, "geometry": [(0.0, 0.0), (0.0, 1.0)]}
        for _ in valhalla_legs
    ]

    route = hybrid_route({"legs": valhalla_legs}, reference_legs)

    assert route["complete"] is True
    assert route["gpx_connector_count"] == 2
    assert [leg["source"] for leg in route["legs"]] == [
        "gpx-backed-off-trail",
        "valhalla",
        "gpx-backed-off-trail",
    ]
    assert route["legs"][0]["geometry"] == reference_legs[0]["geometry"]
    assert route["legs"][1]["geometry"] == valhalla_legs[1]["geometry"]
    assert route["total_miles"] == pytest.approx(
        69.093 + 90.0 + 69.093, abs=0.001
    )
    assert route["effective_miles"] == pytest.approx(
        69.093 * 1.35 + 90.0 + 69.093 * 1.35, abs=0.01
    )


def test_hybrid_route_rejects_mismatched_reference_legs() -> None:
    with pytest.raises(ValueError, match="do not match"):
        hybrid_route({"legs": []}, [{"geometry": [(0.0, 0.0), (0.0, 1.0)]}])


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

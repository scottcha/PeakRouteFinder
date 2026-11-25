import pytest

from peakroutefinder.distance import haversine_miles
from peakroutefinder.model import Peak, RouteResult
from peakroutefinder.poc.optimize import _route_result
from peakroutefinder.poc.trailheads import (
    anchor_reference_gpx,
    nearest_trailheads,
    solve_terminal_route,
)
from peakroutefinder.solver import SolveReport, SolveStatus


def test_nearest_trailhead_preserves_osm_identity() -> None:
    peaks = [Peak("Summit", 1.0, 1.0)]
    trailheads = [
        (10, Peak("Far", 2.0, 2.0)),
        (20, Peak("Near", 1.01, 1.01)),
    ]

    match = nearest_trailheads(peaks, trailheads)[0]

    assert match["trailhead"] == "Near"
    assert match["osm_id"] == 20
    assert match["haversine_miles"] == pytest.approx(0.977, abs=0.001)


def test_terminal_costs_are_charged_and_determine_route() -> None:
    peaks = [Peak("A", 0.0, 0.0), Peak("B", 0.0, 0.1)]
    starts = [
        {"origin": {"name": "A Trailhead", "lat": 0.0, "lon": 0.0}, "miles": 10.0},
        {"origin": {"name": "B Trailhead", "lat": 0.0, "lon": 0.1}, "miles": 1.0},
    ]
    ends = [
        {"destination": {"name": "A Trailhead", "lat": 0.0, "lon": 0.0}, "miles": 10.0},
        {"destination": {"name": "B Trailhead", "lat": 0.0, "lon": 0.1}, "miles": 1.0},
    ]

    route = solve_terminal_route(
        peaks,
        budget_miles=2.0,
        distances=[[0.0, 2.0], [2.0, 0.0]],
        starts=starts,
        ends=ends,
        time_limit=5.0,
        workers=1,
    )

    assert route.peak_count == 1
    assert route.total_miles == 2.0
    assert [point.name for point in route.order] == [
        "B Trailhead",
        "B",
        "B Trailhead",
    ]


def test_reference_gpx_overrides_both_directions_with_exact_endpoints(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "peakroutefinder.poc.trailheads.STANDARD_PEAK_NAMES", ("A", "B")
    )
    reference_path = tmp_path / "reference.gpx"
    reference_path.write_text(
        """<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
        <trkpt lat="0.0" lon="0.01" />
        <trkpt lat="0.0" lon="0.99" />
        </trkseg></trk></gpx>"""
    )
    points = [Peak("A", 0.0, 0.0), Peak("B", 0.0, 1.0)]
    matrix = {
        "distances": [[0.0, 1.0], [1.0, 0.0]],
        "sources": [["self", "valhalla"], ["valhalla", "self"]],
        "dem_legs": {},
        "configuration": {},
    }

    overrides = anchor_reference_gpx(points, matrix, reference_path)

    expected_miles = haversine_miles((0.0, 0.0), (0.0, 1.0))
    assert overrides[0]["miles"] == pytest.approx(expected_miles)
    assert matrix["distances"][0][1] == pytest.approx(expected_miles)
    assert matrix["distances"][1][0] == pytest.approx(expected_miles)
    assert matrix["sources"][0][1] == "reference-gpx"
    assert matrix["sources"][1][0] == "reference-gpx"

    report = SolveReport(
        RouteResult(points, expected_miles, 2, True), SolveStatus.OPTIMAL, 2
    )
    result = _route_result(points, matrix, report, client=None)
    assert tuple(result["legs"][0]["geometry"][0]) == (0.0, 0.0)
    assert tuple(result["legs"][0]["geometry"][-1]) == (0.0, 1.0)
    assert result["legs"][0]["miles"] == pytest.approx(expected_miles)

    reverse_report = SolveReport(
        RouteResult(points[::-1], expected_miles, 2, True),
        SolveStatus.OPTIMAL,
        2,
    )
    reverse = _route_result(points, matrix, reverse_report, client=None)
    assert tuple(reverse["legs"][0]["geometry"][0]) == (0.0, 1.0)
    assert tuple(reverse["legs"][0]["geometry"][-1]) == (0.0, 0.0)


def test_reference_gpx_nonadjacent_pair_uses_cumulative_route(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "peakroutefinder.poc.trailheads.STANDARD_PEAK_NAMES", ("A", "B", "C")
    )
    reference_path = tmp_path / "reference.gpx"
    reference_path.write_text(
        """<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>
        <trkpt lat="0.0" lon="0.01" />
        <trkpt lat="0.0" lon="0.99" />
        <trkpt lat="0.0" lon="1.01" />
        <trkpt lat="0.0" lon="1.99" />
        </trkseg></trk></gpx>"""
    )
    points = [
        Peak("A", 0.0, 0.0),
        Peak("B", 0.0, 1.0),
        Peak("C", 0.0, 2.0),
    ]
    matrix = {
        "distances": [[0.0, 1.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 0.0]],
        "sources": [["self", "valhalla", "valhalla"] for _ in points],
        "dem_legs": {},
        "configuration": {},
    }

    overrides = anchor_reference_gpx(points, matrix, reference_path)

    one_degree = haversine_miles((0.0, 0.0), (0.0, 1.0))
    assert len(overrides) == 3
    nonadjacent = next(
        override
        for override in overrides
        if override["origin"] == "A" and override["destination"] == "C"
    )
    assert nonadjacent["via_peaks"] == ["B"]
    intermediate_snaps = 2 * haversine_miles((0.0, 0.0), (0.0, 0.01))
    cumulative_miles = 2 * one_degree + intermediate_snaps
    assert nonadjacent["miles"] == pytest.approx(cumulative_miles)
    assert matrix["distances"][0][2] == pytest.approx(cumulative_miles)
    assert matrix["distances"][2][0] == pytest.approx(cumulative_miles)
    geometry = matrix["reference_legs"]["0:2"]["geometry"]
    assert (0.0, 1.0) in [tuple(coordinate) for coordinate in geometry]
    reverse_geometry = matrix["reference_legs"]["2:0"]["geometry"]
    assert tuple(reverse_geometry[0]) == (0.0, 2.0)
    assert tuple(reverse_geometry[-1]) == (0.0, 0.0)

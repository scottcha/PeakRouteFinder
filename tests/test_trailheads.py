import pytest

from peakroutefinder.model import Peak
from peakroutefinder.poc.trailheads import nearest_trailheads, solve_terminal_route


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

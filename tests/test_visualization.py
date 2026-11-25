"""Conformance tests for all-peak route maps and waypoint rendering."""

import folium
import pytest

from peakroutefinder.model import Peak, RouteResult
from peakroutefinder.visualization import END_COLOR, START_COLOR, build_map


def test_map_contains_every_peak_in_route_order() -> None:
    """Unvisited candidates remain visible and visited peaks form the route."""
    peaks = [
        Peak("A", 39.0, -106.0),
        Peak("B", 39.1, -106.1),
        Peak("C", 39.2, -106.2),
        Peak("D", 39.3, -106.3),
    ]
    route = RouteResult([peaks[2], peaks[0]], 20.0, 2, True)
    route_map = build_map(peaks, route)
    children = list(route_map._children.values())

    assert sum(type(child) is folium.CircleMarker for child in children) == 2
    assert sum(type(child) is folium.Marker for child in children) == 2
    route_line = next(child for child in children if type(child) is folium.PolyLine)
    assert route_line.locations == [[39.2, -106.2], [39.0, -106.0]]
    assert any(type(child) is folium.TileLayer for child in children)
    assert route_map.get_bounds() == [[39.0, -106.3], [39.3, -106.0]]
    map_html = route_map.get_root().render()
    assert "1. C" in map_html
    assert "2. A" in map_html
    assert 'id="route-key"' in map_html
    assert '<li value="1">C</li><li value="2">A</li>' in map_html
    assert "<li>B</li><li>D</li>" in map_html


def test_map_distinguishes_start_and_end_waypoints() -> None:
    """Waypoint markers use distinct colors and remain on the route line."""
    peak = Peak("A", 39.0, -106.0)
    start = Peak("Start", 38.9, -105.9)
    end = Peak("End", 39.1, -106.1)
    route = RouteResult([start, peak, end], 20.0, 1, True)
    route_map = build_map([peak], route)
    children = list(route_map._children.values())

    waypoint_markers = [child for child in children if type(child) is folium.CircleMarker]
    assert sorted(marker.options["color"] for marker in waypoint_markers) == sorted(
        (START_COLOR, END_COLOR)
    )
    route_line = next(child for child in children if type(child) is folium.PolyLine)
    assert route_line.locations == [[38.9, -105.9], [39.0, -106.0], [39.1, -106.1]]


def test_map_rejects_an_empty_peak_list() -> None:
    """An empty input has no meaningful bounds to display."""
    with pytest.raises(ValueError, match="at least one peak"):
        build_map([], RouteResult([], 0.0, 0, True))

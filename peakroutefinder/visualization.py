"""Interactive HTML maps of optimized routes and all candidate peaks."""

from collections.abc import Sequence
from html import escape
from pathlib import Path

import folium

from peakroutefinder.model import Peak, RouteResult

ROUTE_COLOR = "#1769aa"
UNVISITED_COLOR = "#6b7280"
START_COLOR = "#15803d"
END_COLOR = "#b91c1c"
MARKER_RADIUS = 5
WAYPOINT_RADIUS = 8
ROUTE_WEIGHT = 4


def _point_label(point: Peak) -> str:
    """Return an escaped peak name and coordinate label."""
    return escape(f"{point.name} ({point.lat:.5f}, {point.lon:.5f})")


def build_map(peaks: Sequence[Peak], route: RouteResult) -> folium.Map:
    """Build a basemap containing every candidate and the ordered route."""
    if not peaks:
        raise ValueError("at least one peak is required to build a map")

    peak_identities = {id(peak) for peak in peaks}
    route_positions = {
        id(point): position
        for position, point in enumerate(route.order, start=1)
        if id(point) in peak_identities
    }
    waypoints = [point for point in route.order if id(point) not in peak_identities]
    bounds_points = list(peaks) + waypoints
    center = (
        sum(point.lat for point in bounds_points) / len(bounds_points),
        sum(point.lon for point in bounds_points) / len(bounds_points),
    )
    route_map = folium.Map(
        location=center,
        zoom_start=7,
        tiles="Esri.WorldTopoMap",
        control_scale=True,
    )

    if len(route.order) > 1:
        folium.PolyLine(
            locations=[(point.lat, point.lon) for point in route.order],
            color=ROUTE_COLOR,
            weight=ROUTE_WEIGHT,
            opacity=0.8,
            tooltip=escape(
                f"{route.peak_count} peaks, {route.total_miles:.2f} miles"
            ),
        ).add_to(route_map)

    for position, point in enumerate(route.order, start=1):
        if id(point) in peak_identities:
            continue
        color = START_COLOR if position == 1 else END_COLOR
        folium.CircleMarker(
            location=(point.lat, point.lon),
            radius=WAYPOINT_RADIUS,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.9,
            tooltip=_point_label(point),
        ).add_to(route_map)

    for peak in peaks:
        position = route_positions.get(id(peak))
        if position is None:
            folium.CircleMarker(
                location=(peak.lat, peak.lon),
                radius=MARKER_RADIUS,
                color=UNVISITED_COLOR,
                fill=True,
                fill_color=UNVISITED_COLOR,
                fill_opacity=0.65,
                tooltip=_point_label(peak),
            ).add_to(route_map)
            continue

        number_icon = folium.DivIcon(
            icon_size=(28, 28),
            icon_anchor=(14, 14),
            html=(
                f'<div style="width:26px;height:26px;border-radius:50%;'
                f"background:{ROUTE_COLOR};color:white;border:1px solid white;"
                f'font: bold 12px/26px sans-serif;text-align:center;">'
                f"{position}</div>"
            ),
        )
        folium.Marker(
            location=(peak.lat, peak.lon),
            icon=number_icon,
            tooltip=_point_label(peak),
        ).add_to(route_map)

    route_map.fit_bounds(
        [
            [min(point.lat for point in bounds_points), min(point.lon for point in bounds_points)],
            [max(point.lat for point in bounds_points), max(point.lon for point in bounds_points)],
        ],
        padding=(30, 30),
        max_zoom=14,
    )
    proof_label = "Proven optimal" if route.proven_optimal else "Best known route"
    legend = f"""
    <div style="position:fixed;top:12px;right:12px;z-index:9999;background:white;
                border:1px solid #d1d5db;border-radius:4px;padding:10px;
                font:13px sans-serif;box-shadow:0 1px 4px #0003">
      <strong>{proof_label}: {route.peak_count} peaks, {route.total_miles:.2f} miles</strong><br>
      <span style="color:{ROUTE_COLOR}">●</span> Numbered route
      &nbsp; <span style="color:{UNVISITED_COLOR}">●</span> Other listed peaks<br>
      <span style="color:{START_COLOR}">●</span> Start
      &nbsp; <span style="color:{END_COLOR}">●</span> End
    </div>
    """
    route_map.get_root().html.add_child(folium.Element(legend))
    return route_map


def write_map(path: Path, peaks: Sequence[Peak], route: RouteResult) -> None:
    """Write an interactive map, replacing any existing HTML file."""
    build_map(peaks, route).save(str(path))

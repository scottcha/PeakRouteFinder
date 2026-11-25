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

        name_icon = folium.DivIcon(
            icon_size=None,
            icon_anchor=(-6, 12),
            class_name="peak-name-label",
            html=(
                f'<div style="display:inline-block;width:max-content;'
                f'white-space:nowrap;background:#ffffffde;'
                f"color:{ROUTE_COLOR};border-left:3px solid {ROUTE_COLOR};"
                f'padding:2px 5px;font:bold 12px/18px sans-serif;">'
                f"{position}. {escape(peak.name)}</div>"
            ),
        )
        folium.Marker(
            location=(peak.lat, peak.lon),
            icon=name_icon,
            tooltip=_point_label(peak),
        ).add_to(route_map)

    route_map.fit_bounds(
        [
            [min(point.lat for point in bounds_points), min(point.lon for point in bounds_points)],
            [max(point.lat for point in bounds_points), max(point.lon for point in bounds_points)],
        ],
        padding_top_left=(30, 30),
        padding_bottom_right=(280, 30),
        max_zoom=14,
    )
    route_peaks = [
        (position, point)
        for position, point in enumerate(route.order, start=1)
        if id(point) in peak_identities
    ]
    other_peaks = [peak for peak in peaks if id(peak) not in route_positions]
    route_key_items = "".join(
        f'<li value="{position}">{escape(point.name)}</li>'
        for position, point in route_peaks
    )
    other_key_items = "".join(
        f"<li>{escape(peak.name)}</li>" for peak in other_peaks
    )
    proof_label = "Proven optimal" if route.proven_optimal else "Best known route"
    legend = f"""
    <div id="route-key" style="position:fixed;top:12px;right:12px;z-index:9999;
                width:240px;max-height:calc(100vh - 48px);overflow-y:auto;background:white;
                border:1px solid #d1d5db;border-radius:4px;padding:10px;
                font:13px sans-serif;box-shadow:0 1px 4px #0003">
      <strong>{proof_label}: {route.peak_count} peaks, {route.total_miles:.2f} miles</strong>
      <p style="margin:8px 0 4px"><strong>Route peaks (in order)</strong></p>
      <ol style="margin:0;padding-left:24px">{route_key_items}</ol>
      <details style="margin-top:8px">
        <summary style="color:{UNVISITED_COLOR}">Other listed peaks ({len(other_peaks)})</summary>
        <ul style="margin:4px 0;padding-left:24px">{other_key_items}</ul>
      </details>
      <div style="margin-top:8px">
        <span style="color:{START_COLOR}">●</span> Start
        &nbsp; <span style="color:{END_COLOR}">●</span> End
      </div>
    </div>
    """
    route_map.get_root().html.add_child(folium.Element(legend))
    return route_map


def write_map(path: Path, peaks: Sequence[Peak], route: RouteResult) -> None:
    """Write an interactive map, replacing any existing HTML file."""
    build_map(peaks, route).save(str(path))

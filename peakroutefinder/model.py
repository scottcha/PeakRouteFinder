"""Domain types for peaks, waypoints, and optimized routes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Peak:
    """A named geographic point; waypoints use the same representation."""

    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class RouteResult:
    """An optimized route and its proof status."""

    order: list[Peak]
    total_miles: float
    peak_count: int
    proven_optimal: bool

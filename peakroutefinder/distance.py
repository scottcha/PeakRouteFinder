"""Distance-provider interface and straight-line great-circle distances."""

import math
from collections.abc import Sequence
from typing import Protocol

from peakroutefinder.model import Peak

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(
    origin: tuple[float, float], destination: tuple[float, float]
) -> float:
    """Return great-circle miles between two latitude/longitude pairs."""
    lat1, lon1 = (math.radians(value) for value in origin)
    lat2, lon2 = (math.radians(value) for value in destination)
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(haversine))


class DistanceProvider(Protocol):
    """Supply pairwise distances in miles for an ordered set of points."""

    def matrix(self, points: Sequence[Peak]) -> list[list[float]]:
        """Return a matrix whose row and column indices match ``points``."""
        ...


def validate_coordinates(point: Peak) -> None:
    """Reject coordinates outside the valid latitude and longitude ranges."""
    if (
        not math.isfinite(point.lat)
        or not math.isfinite(point.lon)
        or abs(point.lat) > 90
        or abs(point.lon) > 180
    ):
        raise ValueError(
            f"invalid coordinates for {point.name}: "
            f"latitude={point.lat}, longitude={point.lon}"
        )


class HaversineProvider:
    """Calculate great-circle distances on a spherical Earth."""

    def matrix(self, points: Sequence[Peak]) -> list[list[float]]:
        """Build a symmetric distance matrix in miles."""
        for point in points:
            validate_coordinates(point)

        size = len(points)
        distances = [[0.0] * size for _ in range(size)]
        coordinates = [
            (math.radians(point.lat), math.radians(point.lon)) for point in points
        ]
        for row in range(size):
            lat1, lon1 = coordinates[row]
            for column in range(row + 1, size):
                lat2, lon2 = coordinates[column]
                lat_delta = lat2 - lat1
                lon_delta = lon2 - lon1
                haversine = (
                    math.sin(lat_delta / 2) ** 2
                    + math.cos(lat1)
                    * math.cos(lat2)
                    * math.sin(lon_delta / 2) ** 2
                )
                distance = 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(haversine))
                distances[row][column] = distance
                distances[column][row] = distance
        return distances

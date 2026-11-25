"""Terrain-aware off-trail candidates from cached Terrarium elevation tiles."""

import heapq
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

from peakroutefinder.distance import haversine_miles
from peakroutefinder.model import Peak

TERRARIUM_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium"
TILE_SIZE = 256
METERS_PER_MILE = 1609.344
FEET_PER_METER = 3.280839895
WALKING_SPEED_MPH = 3.1
MIN_HIKING_SPEED_KMH = 0.05
KILOMETERS_PER_MILE = 1.609344
MAX_TOBLER_SPEED_KMH = 6 * math.exp(3.5 * 0.05)
MIN_EFFORT_PER_MILE = WALKING_SPEED_MPH / (
    MAX_TOBLER_SPEED_KMH / KILOMETERS_PER_MILE
)
EARTH_CIRCUMFERENCE_METERS = 40_075_016.68557849
MIN_VALID_ELEVATION_METERS = -1000.0
MAX_VALID_ELEVATION_METERS = 9000.0
GRID_STRIDE = 2
GRID_PADDING_PIXELS = 48
MAX_TILES_PER_LEG = 96
NEIGHBORS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


def global_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Project latitude/longitude to global Web Mercator pixel coordinates."""
    scale = 2**zoom * TILE_SIZE
    x = (lon + 180.0) / 360.0 * scale
    lat_radians = math.radians(lat)
    y = (
        1.0 - math.asinh(math.tan(lat_radians)) / math.pi
    ) / 2.0 * scale
    return x, y


def pixel_coordinate(x: float, y: float, zoom: int) -> tuple[float, float]:
    """Convert global Web Mercator pixels to latitude/longitude."""
    scale = 2**zoom * TILE_SIZE
    lon = x / scale * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / scale))))
    return lat, lon


def decode_terrarium(image: Image.Image) -> np.ndarray:
    """Decode red/green/blue channels into meters above sea level."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    return rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0


def hiking_effort_miles(horizontal_meters: float, rise_meters: float) -> float:
    """Convert one sloped segment to flat-equivalent miles using Tobler's function."""
    if horizontal_meters <= 0:
        return 0.0
    slope = rise_meters / horizontal_meters
    speed_kmh = max(
        6.0 * math.exp(-3.5 * abs(slope + 0.05)), MIN_HIKING_SPEED_KMH
    )
    hours = horizontal_meters / 1000.0 / speed_kmh
    return hours * WALKING_SPEED_MPH


@dataclass(frozen=True)
class DemGrid:
    elevations: np.ndarray
    x0: int
    y0: int
    zoom: int
    stride: int = GRID_STRIDE

    @property
    def shape(self) -> tuple[int, int]:
        return self.elevations.shape

    def node(self, point: Peak) -> tuple[int, int]:
        x, y = global_pixel(point.lat, point.lon, self.zoom)
        row = round((y - self.y0) / self.stride)
        col = round((x - self.x0) / self.stride)
        rows, cols = self.shape
        return min(max(row, 0), rows - 1), min(max(col, 0), cols - 1)

    def coordinate(self, node: tuple[int, int]) -> tuple[float, float]:
        row, col = node
        return pixel_coordinate(
            self.x0 + col * self.stride + 0.5,
            self.y0 + row * self.stride + 0.5,
            self.zoom,
        )

    def meters_per_pixel(self, row: int, col: int) -> float:
        lat, _ = self.coordinate((row, col))
        return (
            EARTH_CIRCUMFERENCE_METERS
            * math.cos(math.radians(lat))
            / (2**self.zoom * TILE_SIZE)
            * self.stride
        )


class TerrariumProvider:
    """Download and cache Terrarium PNG tiles, then assemble local DEM grids."""

    def __init__(self, cache_dir: Path, zoom: int = 12, timeout: float = 30.0) -> None:
        self.cache_dir = cache_dir
        self.zoom = zoom
        self.timeout = timeout

    def _tile(self, x: int, y: int) -> np.ndarray:
        path = self.cache_dir / str(self.zoom) / str(x) / f"{y}.png"
        if path.exists():
            payload = path.read_bytes()
        else:
            request = urllib.request.Request(
                f"{TERRARIUM_URL}/{self.zoom}/{x}/{y}.png",
                headers={"User-Agent": "PeakRouteFinder DEM POC"},
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
            except (urllib.error.URLError, TimeoutError) as error:
                raise RuntimeError(f"DEM tile download failed at {x}/{y}: {error}") from error
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        with Image.open(BytesIO(payload)) as image:
            elevations = decode_terrarium(image)
        if (
            not np.all(np.isfinite(elevations))
            or np.any(elevations < MIN_VALID_ELEVATION_METERS)
            or np.any(elevations > MAX_VALID_ELEVATION_METERS)
        ):
            raise RuntimeError(f"DEM tile contains void or invalid elevations at {x}/{y}")
        return elevations

    def grid(self, origin: Peak, destination: Peak) -> DemGrid:
        origin_xy = global_pixel(origin.lat, origin.lon, self.zoom)
        destination_xy = global_pixel(destination.lat, destination.lon, self.zoom)
        x0 = math.floor(min(origin_xy[0], destination_xy[0])) - GRID_PADDING_PIXELS
        y0 = math.floor(min(origin_xy[1], destination_xy[1])) - GRID_PADDING_PIXELS
        x1 = math.ceil(max(origin_xy[0], destination_xy[0])) + GRID_PADDING_PIXELS
        y1 = math.ceil(max(origin_xy[1], destination_xy[1])) + GRID_PADDING_PIXELS
        tile_x0, tile_y0 = x0 // TILE_SIZE, y0 // TILE_SIZE
        tile_x1, tile_y1 = x1 // TILE_SIZE, y1 // TILE_SIZE
        tile_count = (tile_x1 - tile_x0 + 1) * (tile_y1 - tile_y0 + 1)
        if tile_count > MAX_TILES_PER_LEG:
            raise RuntimeError(f"DEM leg requires too many tiles: {tile_count}")
        elevations = np.empty(
            (
                (tile_y1 - tile_y0 + 1) * TILE_SIZE,
                (tile_x1 - tile_x0 + 1) * TILE_SIZE,
            ),
            dtype=np.float32,
        )
        for tile_y in range(tile_y0, tile_y1 + 1):
            for tile_x in range(tile_x0, tile_x1 + 1):
                row = (tile_y - tile_y0) * TILE_SIZE
                col = (tile_x - tile_x0) * TILE_SIZE
                elevations[row : row + TILE_SIZE, col : col + TILE_SIZE] = self._tile(
                    tile_x, tile_y
                )
        crop = elevations[
            y0 - tile_y0 * TILE_SIZE : y1 - tile_y0 * TILE_SIZE,
            x0 - tile_x0 * TILE_SIZE : x1 - tile_x0 * TILE_SIZE,
        ]
        return DemGrid(crop[::GRID_STRIDE, ::GRID_STRIDE].copy(), x0, y0, self.zoom)


def least_cost_path(
    grid: DemGrid, start: tuple[int, int], end: tuple[int, int]
) -> tuple[list[tuple[int, int]], float]:
    """Run A* over an elevation grid and return grid nodes and hiking effort."""
    rows, cols = grid.shape
    costs = np.full((rows, cols), np.inf)
    parents = np.full((rows, cols), -1, dtype=np.int32)
    closed = np.zeros((rows, cols), dtype=bool)
    costs[start] = 0.0
    queue = [(0.0, 0.0, start)]
    while queue:
        _, cost, node = heapq.heappop(queue)
        if closed[node]:
            continue
        if node == end:
            path = []
            current = node
            while current != start:
                path.append(current)
                parent = int(parents[current])
                if parent < 0:
                    raise RuntimeError("DEM path reconstruction failed")
                current = divmod(parent, cols)
            path.append(start)
            path.reverse()
            return path, float(cost)
        closed[node] = True
        row, col = node
        meters_per_pixel = grid.meters_per_pixel(row, col)
        for d_row, d_col in NEIGHBORS:
            neighbor = row + d_row, col + d_col
            n_row, n_col = neighbor
            if not (0 <= n_row < rows and 0 <= n_col < cols) or closed[neighbor]:
                continue
            horizontal_meters = meters_per_pixel * math.hypot(d_row, d_col)
            rise_meters = float(
                grid.elevations[neighbor] - grid.elevations[node]
            )
            next_cost = cost + hiking_effort_miles(horizontal_meters, rise_meters)
            if next_cost >= costs[neighbor]:
                continue
            costs[neighbor] = next_cost
            parents[neighbor] = row * cols + col
            remaining_miles = (
                grid.meters_per_pixel(n_row, n_col)
                * math.hypot(end[0] - n_row, end[1] - n_col)
                / METERS_PER_MILE
            )
            priority = next_cost + remaining_miles * MIN_EFFORT_PER_MILE
            heapq.heappush(queue, (priority, next_cost, neighbor))
    raise RuntimeError("no DEM path exists between the waypoints")


class DemRouter:
    """Build one terrain-path candidate for a waypoint pair."""

    def __init__(self, provider: TerrariumProvider) -> None:
        self.provider = provider

    def route(self, origin: Peak, destination: Peak) -> dict:
        grid = self.provider.grid(origin, destination)
        nodes, effort_miles = least_cost_path(
            grid, grid.node(origin), grid.node(destination)
        )
        geometry = [grid.coordinate(node) for node in nodes]
        geometry[0] = (origin.lat, origin.lon)
        geometry[-1] = (destination.lat, destination.lon)
        elevations = [float(grid.elevations[node]) for node in nodes]
        path_miles = sum(
            haversine_miles(a, b) for a, b in zip(geometry, geometry[1:])
        )
        return {
            "miles": path_miles,
            "effort_miles": effort_miles,
            "geometry": geometry,
            "elevation_gain_feet": sum(
                max(b - a, 0.0) for a, b in zip(elevations, elevations[1:])
            )
            * FEET_PER_METER,
        }

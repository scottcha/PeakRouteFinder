from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from peakroutefinder.model import Peak
from peakroutefinder.poc.dem import (
    DemGrid,
    TerrariumProvider,
    decode_terrarium,
    hiking_effort_miles,
    least_cost_path,
    pixel_coordinate,
)
from peakroutefinder.poc.nolans import dem_offtrail_route


def test_decode_terrarium_elevation() -> None:
    image = Image.new("RGB", (1, 1), (140, 2, 128))

    assert decode_terrarium(image)[0, 0] == pytest.approx(3074.5)


def test_terrarium_provider_rejects_void_tile(tmp_path: Path) -> None:
    tile_path = tmp_path / "12" / "1" / "2.png"
    tile_path.parent.mkdir(parents=True)
    Image.new("RGB", (256, 256), (0, 0, 0)).save(tile_path)

    with pytest.raises(RuntimeError, match="void or invalid"):
        TerrariumProvider(tmp_path)._tile(1, 2)


def test_hiking_effort_increases_with_uphill_slope() -> None:
    flat = hiking_effort_miles(1000.0, 0.0)

    assert hiking_effort_miles(1000.0, 300.0) > flat
    # Regression: an extreme synthetic cliff underflowed Tobler speed to zero.
    assert hiking_effort_miles(4.7, 1000.0) > 0.0


def test_astar_detours_around_high_terrain_barrier() -> None:
    elevations = np.zeros((7, 7), dtype=np.float32)
    elevations[:6, 3] = 1000.0
    grid = DemGrid(elevations, x0=0, y0=0, zoom=12, stride=1)

    path, effort = least_cost_path(grid, (3, 0), (3, 6))

    assert (6, 3) in path
    assert effort > hiking_effort_miles(6 * grid.meters_per_pixel(3, 0), 0.0)


def test_dem_hybrid_uses_effort_for_selection_and_path_for_distance() -> None:
    points = [Peak("A", 0.0, 0.0), Peak("B", 0.0, 1.0)]
    geometry = [pixel_coordinate(x, 0, 12) for x in range(4)]

    class FakeDemRouter:
        def route(self, origin: Peak, destination: Peak) -> dict:
            return {
                "miles": 5.0,
                "effort_miles": 8.0,
                "geometry": geometry,
                "elevation_gain_feet": 500.0,
            }

    valhalla_route = {
        "legs": [
            {
                "origin": "A",
                "destination": "B",
                "status": "ok",
                "miles": 10.0,
                "geometry": [(0.0, 0.0)],
                "warnings": [],
            }
        ]
    }

    route = dem_offtrail_route(valhalla_route, points, FakeDemRouter())
    leg = route["legs"][0]

    assert leg["source"] == "dem-off-trail"
    assert leg["miles"] == 5.0
    assert leg["effective_miles"] == 8.0
    assert leg["geometry"] == geometry
    assert route["dem_connector_count"] == 1


def test_dem_failure_does_not_fall_back_to_straight_line() -> None:
    points = [Peak("A", 0.0, 0.0), Peak("B", 0.0, 1.0)]

    class FailedDemRouter:
        def route(self, origin: Peak, destination: Peak) -> dict:
            raise RuntimeError("DEM unavailable")

    valhalla_route = {
        "legs": [
            {
                "origin": "A",
                "destination": "B",
                "status": "error",
                "error": "unreachable",
            }
        ]
    }

    route = dem_offtrail_route(valhalla_route, points, FailedDemRouter())

    assert route["complete"] is False
    assert route["total_miles"] is None
    assert route["legs"][0]["error"] == "DEM unavailable"

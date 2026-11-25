"""Optimize peak count over a Valhalla matrix with short-range DEM alternatives."""

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from peakroutefinder.cli import load_peaks
from peakroutefinder.distance import HaversineProvider
from peakroutefinder.model import Peak
from peakroutefinder.poc.dem import (
    GRID_STRIDE,
    DemRouter,
    TerrariumProvider,
)
from peakroutefinder.poc.nolans import ValhallaClient
from peakroutefinder.solver import (
    DEFAULT_TIME_LIMIT_SECONDS,
    DEFAULT_WORKERS,
    SolveReport,
    solve,
)

VALHALLA_MAX_HAVERSINE_MILES = 100.0


class FixedMatrixProvider:
    """Adapt a precomputed matrix to the engine's distance-provider seam."""

    def __init__(self, distances: list[list[float]]) -> None:
        self.distances: list[list[float]] = distances

    def matrix(self, points: Sequence[Peak]) -> list[list[float]]:
        if len(points) != len(self.distances):
            raise ValueError("point count does not match the precomputed matrix")
        return self.distances


def choose_leg(
    valhalla_miles: float, dem_candidate: dict[str, Any]
) -> tuple[float, str]:
    """Choose the shortest actual path, independently of hiking effort."""
    if dem_candidate["miles"] < valhalla_miles:
        return float(dem_candidate["miles"]), "dem-off-trail"
    return valhalla_miles, "valhalla"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_hybrid_matrix(
    peaks: Sequence[Peak],
    client: ValhallaClient,
    dem_router: DemRouter,
    dem_max_haversine: float,
    cache_path: Path,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    """Build or resume a full matrix, recording every attempted DEM candidate."""
    data: dict[str, Any]
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data["configuration"] != configuration:
            raise ValueError(
                "matrix cache configuration differs; use a new output directory"
            )
    else:
        data = {
            "configuration": configuration,
            "valhalla_matrix": client.matrix(
                peaks, max_haversine=VALHALLA_MAX_HAVERSINE_MILES
            ),
            "dem_legs": {},
            "complete": False,
        }

    haversine = HaversineProvider().matrix(peaks)
    candidates = [
        (origin_index, destination_index)
        for origin_index in range(len(peaks))
        for destination_index in range(len(peaks))
        if origin_index != destination_index
        and haversine[origin_index][destination_index] <= dem_max_haversine
    ]
    for number, (origin_index, destination_index) in enumerate(candidates, start=1):
        key = f"{origin_index}:{destination_index}"
        if key not in data["dem_legs"]:
            origin = peaks[origin_index]
            destination = peaks[destination_index]
            try:
                candidate = dem_router.route(origin, destination)
            except RuntimeError as error:
                data["dem_legs"][key] = {
                    "origin": origin.name,
                    "destination": destination.name,
                    "status": "error",
                    "error": str(error),
                }
            else:
                data["dem_legs"][key] = {
                    "origin": origin.name,
                    "destination": destination.name,
                    "status": "ok",
                    "haversine_miles": haversine[origin_index][destination_index],
                    **candidate,
                }
            _write_json(cache_path, data)
        if number % 10 == 0 or number == len(candidates):
            print(f"DEM candidates: {number}/{len(candidates)}", flush=True)

    distances = [row.copy() for row in data["valhalla_matrix"]]
    sources = [["valhalla"] * len(peaks) for _ in peaks]
    for key, candidate in data["dem_legs"].items():
        if candidate["status"] != "ok":
            continue
        origin_index, destination_index = (int(value) for value in key.split(":"))
        miles, source = choose_leg(
            distances[origin_index][destination_index], candidate
        )
        distances[origin_index][destination_index] = miles
        sources[origin_index][destination_index] = source
    for index in range(len(peaks)):
        distances[index][index] = 0.0
        sources[index][index] = "self"
    if not all(math.isfinite(value) for row in distances for value in row):
        raise RuntimeError("hybrid matrix contains a non-finite distance")
    data.update(
        distances=distances,
        sources=sources,
        dem_candidate_count=len(candidates),
        dem_connector_count=sum(
            source == "dem-off-trail" for row in sources for source in row
        ),
        complete=True,
    )
    _write_json(cache_path, data)
    return data


def _route_result(
    peaks: Sequence[Peak],
    matrix: dict[str, Any],
    report: SolveReport,
    client: ValhallaClient,
) -> dict[str, Any]:
    route = report.route
    if route is None:
        return {"status": report.status.value, "peak_bound": report.peak_bound}
    indices = {id(peak): index for index, peak in enumerate(peaks)}
    route_indices = [indices[id(point)] for point in route.order]
    legs = []
    for origin_index, destination_index in zip(route_indices, route_indices[1:]):
        source = matrix["sources"][origin_index][destination_index]
        key = f"{origin_index}:{destination_index}"
        if source == "dem-off-trail":
            candidate = matrix["dem_legs"][key]
            leg = {
                "origin": peaks[origin_index].name,
                "destination": peaks[destination_index].name,
                "miles": matrix["distances"][origin_index][destination_index],
                "source": source,
                "dem_effort_miles": candidate["effort_miles"],
                "dem_elevation_gain_feet": candidate["elevation_gain_feet"],
                "geometry": candidate["geometry"],
            }
        else:
            leg = {
                "origin": peaks[origin_index].name,
                "destination": peaks[destination_index].name,
                "miles": matrix["distances"][origin_index][destination_index],
                "source": source,
            }
            try:
                valhalla_leg = client.route(
                    peaks[origin_index], peaks[destination_index]
                )
            except RuntimeError as error:
                leg.update(status="error", error=str(error), geometry=[])
            else:
                leg.update(valhalla_leg)
                leg["miles"] = matrix["distances"][origin_index][destination_index]
        legs.append(leg)
    return {
        "status": report.status.value,
        "peak_bound": report.peak_bound,
        "route": asdict(route),
        "legs": legs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peaks", type=Path, default=Path("data/colorado_14ers.csv"))
    parser.add_argument("--budget", type=float, default=100.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--router-url", default="http://127.0.0.1:18002")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--dem-cache",
        type=Path,
        default=Path("/tmp/peakroutefinder-valhalla/dem-tiles"),
    )
    parser.add_argument("--dem-zoom", type=int, default=12)
    parser.add_argument("--dem-timeout", type=float, default=30.0)
    parser.add_argument("--dem-max-haversine", type=float, default=15.0)
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT_SECONDS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()
    if not 0.0 <= args.budget <= VALHALLA_MAX_HAVERSINE_MILES:
        parser.error(
            f"--budget must be between 0 and {VALHALLA_MAX_HAVERSINE_MILES:g} "
            "for this bounded matrix"
        )

    peaks = load_peaks(args.peaks)
    configuration = {
        "peaks_sha256": hashlib.sha256(args.peaks.read_bytes()).hexdigest(),
        "valhalla_max_haversine": VALHALLA_MAX_HAVERSINE_MILES,
        "dem_zoom": args.dem_zoom,
        "dem_grid_stride": GRID_STRIDE,
        "dem_max_haversine": args.dem_max_haversine,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = ValhallaClient(args.router_url, args.timeout)
    dem_router = DemRouter(
        TerrariumProvider(args.dem_cache, args.dem_zoom, args.dem_timeout)
    )
    matrix = build_hybrid_matrix(
        peaks,
        client,
        dem_router,
        args.dem_max_haversine,
        args.output_dir / "matrix.json",
        configuration,
    )
    report = solve(
        peaks,
        args.budget,
        provider=FixedMatrixProvider(matrix["distances"]),
        time_limit=args.time_limit,
        workers=args.workers,
    )
    result = _route_result(peaks, matrix, report, client)
    result["budget_miles"] = args.budget
    result["dem_candidate_count"] = matrix["dem_candidate_count"]
    result["dem_connector_count"] = matrix["dem_connector_count"]
    _write_json(args.output_dir / "result.json", result)
    print(f"status: {report.status.value}; bound: {report.peak_bound}")
    if report.route is not None:
        print(
            f"peaks: {report.route.peak_count}; "
            f"miles: {report.route.total_miles:.2f}; "
            f"proven_optimal: {report.route.proven_optimal}"
        )
        print(" -> ".join(point.name for point in report.route.order))
    return 0 if report.status.value == "optimal" else 2


if __name__ == "__main__":
    raise SystemExit(main())

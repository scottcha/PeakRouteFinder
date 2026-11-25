"""Optimize a summit route with nearest-OSM-trailhead start and end costs."""

import argparse
import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

import osmium
from ortools.sat.python import cp_model

from peakroutefinder.cli import load_peaks
from peakroutefinder.distance import haversine_miles
from peakroutefinder.model import Peak, RouteResult
from peakroutefinder.poc.dem import GRID_STRIDE, DemRouter, TerrariumProvider
from peakroutefinder.poc.nolans import ValhallaClient
from peakroutefinder.poc.optimize import (
    VALHALLA_MAX_HAVERSINE_MILES,
    _route_result,
    _write_json,
    choose_leg,
)
from peakroutefinder.solver import (
    DEFAULT_TIME_LIMIT_SECONDS,
    DEFAULT_WORKERS,
    DISTANCE_SCALE,
    SolveReport,
    SolveStatus,
    build_circuit_model,
)

DEM_MAX_HAVERSINE_MILES = 15.0


class TrailheadHandler(osmium.SimpleHandler):
    """Collect OSM nodes explicitly tagged as trailheads."""

    def __init__(self) -> None:
        super().__init__()
        self.trailheads: list[tuple[int, Peak]] = []

    def node(self, node: osmium.osm.Node) -> None:
        if node.tags.get("highway") != "trailhead":
            return
        name = node.tags.get("name") or f"OSM trailhead {node.id}"
        self.trailheads.append((node.id, Peak(name, node.lat, node.lon)))


def extract_trailheads(pbf_path: Path) -> list[tuple[int, Peak]]:
    handler = TrailheadHandler()
    handler.apply_file(str(pbf_path))
    if not handler.trailheads:
        raise ValueError(f"{pbf_path}: no highway=trailhead nodes found")
    return handler.trailheads


def nearest_trailheads(
    peaks: Sequence[Peak], trailheads: Sequence[tuple[int, Peak]]
) -> list[dict[str, Any]]:
    """Match each peak to its nearest trailhead by haversine distance."""
    matches = []
    for peak in peaks:
        osm_id, trailhead = min(
            trailheads,
            key=lambda candidate: haversine_miles(
                (peak.lat, peak.lon),
                (candidate[1].lat, candidate[1].lon),
            ),
        )
        matches.append(
            {
                "peak": peak.name,
                "trailhead": trailhead.name,
                "osm_id": osm_id,
                "lat": trailhead.lat,
                "lon": trailhead.lon,
                "haversine_miles": haversine_miles(
                    (peak.lat, peak.lon), (trailhead.lat, trailhead.lon)
                ),
            }
        )
    return matches


def build_terminal_connectors(
    peaks: Sequence[Peak],
    matches: Sequence[dict[str, Any]],
    client: ValhallaClient,
    dem_router: DemRouter,
    cache_path: Path,
    configuration: dict[str, Any],
) -> dict[str, Any]:
    """Route start and return connectors for every possible terminal peak."""
    if cache_path.exists():
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data["configuration"] != configuration:
            raise ValueError(
                "trailhead cache configuration differs; use a new output directory"
            )
    else:
        data = {
            "configuration": configuration,
            "matches": list(matches),
            "connectors": {},
        }

    for index, (peak, match) in enumerate(zip(peaks, matches)):
        trailhead = Peak(match["trailhead"], match["lat"], match["lon"])
        for direction, origin, destination in (
            ("start", trailhead, peak),
            ("end", peak, trailhead),
        ):
            key = f"{direction}:{index}"
            if key in data["connectors"]:
                continue
            valhalla_leg = client.route(origin, destination)
            candidate = {
                "origin": asdict(origin),
                "destination": asdict(destination),
                "miles": valhalla_leg["miles"],
                "source": "valhalla",
                "geometry": valhalla_leg["geometry"],
                "valhalla_miles": valhalla_leg["miles"],
                "haversine_miles": match["haversine_miles"],
            }
            if match["haversine_miles"] <= DEM_MAX_HAVERSINE_MILES:
                try:
                    dem_candidate = dem_router.route(origin, destination)
                except RuntimeError as error:
                    candidate["dem_error"] = str(error)
                else:
                    miles, source = choose_leg(
                        valhalla_leg["miles"], dem_candidate
                    )
                    candidate.update(
                        miles=miles,
                        source=source,
                        dem_path_miles=dem_candidate["miles"],
                        dem_effort_miles=dem_candidate["effort_miles"],
                        dem_elevation_gain_feet=dem_candidate[
                            "elevation_gain_feet"
                        ],
                    )
                    if source == "dem-off-trail":
                        candidate["geometry"] = dem_candidate["geometry"]
            data["connectors"][key] = candidate
            _write_json(cache_path, data)
        if (index + 1) % 10 == 0 or index + 1 == len(peaks):
            print(f"Trailhead connectors: {index + 1}/{len(peaks)}", flush=True)
    return data


def solve_terminal_route(
    peaks: Sequence[Peak],
    budget_miles: float,
    distances: Sequence[Sequence[float]],
    starts: Sequence[dict[str, Any]],
    ends: Sequence[dict[str, Any]],
    time_limit: float,
    workers: int,
) -> RouteResult:
    """Choose first/last peaks while charging their trailhead connectors."""
    real_distances = [
        list(row) + [ends[index]["miles"]]
        for index, row in enumerate(distances)
    ]
    real_distances.append([connector["miles"] for connector in starts] + [0.0])
    scaled_distances = [
        [int(round(distance * DISTANCE_SCALE)) for distance in row]
        for row in real_distances
    ]
    budget_units = int(budget_miles * DISTANCE_SCALE)

    def build():
        return build_circuit_model(
            scaled_distances, len(peaks), budget_units, None, None
        )

    first = build()
    first.model.Maximize(first.visited_peaks)
    first_solver = cp_model.CpSolver()
    first_solver.parameters.max_time_in_seconds = time_limit
    first_solver.parameters.num_search_workers = workers
    first_status = first_solver.Solve(first.model)
    if first_status != cp_model.OPTIMAL:
        raise RuntimeError(
            f"terminal peak-count phase did not prove optimality: {first_status}"
        )
    peak_count = int(round(first_solver.ObjectiveValue()))

    second = build()
    second.model.Add(second.visited_peaks == peak_count)
    second.model.Minimize(second.cost)
    second_solver = cp_model.CpSolver()
    second_solver.parameters.max_time_in_seconds = time_limit
    second_solver.parameters.num_search_workers = workers
    second_status = second_solver.Solve(second.model)
    if second_status != cp_model.OPTIMAL:
        raise RuntimeError(
            f"terminal mileage phase did not prove optimality: {second_status}"
        )

    next_node = {
        tail: head
        for (tail, head), arc in second.arcs.items()
        if tail != head and second_solver.Value(arc)
    }
    sequence = []
    current = next_node[second.depot]
    while current != second.depot:
        sequence.append(current)
        current = next_node[current]
    total_miles = real_distances[second.depot][sequence[0]]
    total_miles += sum(
        real_distances[tail][head]
        for tail, head in zip(sequence, sequence[1:])
    )
    total_miles += real_distances[sequence[-1]][second.depot]
    start = Peak(**starts[sequence[0]]["origin"])
    end = Peak(**ends[sequence[-1]]["destination"])
    return RouteResult(
        [start, *(peaks[index] for index in sequence), end],
        total_miles,
        len(sequence),
        proven_optimal=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peaks", type=Path, default=Path("data/colorado_14ers.csv"))
    parser.add_argument(
        "--pbf",
        type=Path,
        default=Path(
            "/tmp/peakroutefinder-valhalla/custom_files/"
            "colorado-261124.osm.pbf"
        ),
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("/tmp/peakroutefinder-valhalla/optimize-100/matrix.json"),
    )
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
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT_SECONDS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = parser.parse_args()
    if not 0.0 <= args.budget <= VALHALLA_MAX_HAVERSINE_MILES:
        parser.error(
            f"--budget must be between 0 and {VALHALLA_MAX_HAVERSINE_MILES:g}"
        )

    peaks = load_peaks(args.peaks)
    peaks_sha256 = hashlib.sha256(args.peaks.read_bytes()).hexdigest()
    matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
    if matrix["configuration"]["peaks_sha256"] != peaks_sha256:
        raise ValueError("peak matrix was built from a different CSV")
    configuration = {
        "peaks_sha256": peaks_sha256,
        "pbf_sha256": hashlib.sha256(args.pbf.read_bytes()).hexdigest(),
        "dem_zoom": args.dem_zoom,
        "dem_grid_stride": GRID_STRIDE,
        "dem_max_haversine": DEM_MAX_HAVERSINE_MILES,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    client = ValhallaClient(args.router_url, args.timeout)
    dem_router = DemRouter(
        TerrariumProvider(args.dem_cache, args.dem_zoom, args.dem_timeout)
    )
    matches = nearest_trailheads(peaks, extract_trailheads(args.pbf))
    terminal = build_terminal_connectors(
        peaks,
        matches,
        client,
        dem_router,
        args.output_dir / "connectors.json",
        configuration,
    )
    starts = [terminal["connectors"][f"start:{index}"] for index in range(len(peaks))]
    ends = [terminal["connectors"][f"end:{index}"] for index in range(len(peaks))]
    route = solve_terminal_route(
        peaks,
        args.budget,
        matrix["distances"],
        starts,
        ends,
        args.time_limit,
        args.workers,
    )

    peak_indices = {id(peak): index for index, peak in enumerate(peaks)}
    first_index = peak_indices[id(route.order[1])]
    last_index = peak_indices[id(route.order[-2])]
    internal_total = (
        route.total_miles
        - starts[first_index]["miles"]
        - ends[last_index]["miles"]
    )
    internal_route = RouteResult(
        route.order[1:-1], internal_total, route.peak_count, True
    )
    internal = _route_result(
        peaks,
        matrix,
        SolveReport(internal_route, SolveStatus.OPTIMAL, route.peak_count),
        client,
    )
    result = {
        "status": "optimal",
        "peak_bound": route.peak_count,
        "budget_miles": args.budget,
        "route": asdict(route),
        "legs": [starts[first_index], *internal["legs"], ends[last_index]],
        "trailhead_matches": matches,
        "configuration": configuration,
    }
    _write_json(args.output_dir / "result.json", result)
    print(f"peaks: {route.peak_count}; miles: {route.total_miles:.2f}; optimal: True")
    print(" -> ".join(point.name for point in route.order))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Route standard and Sherman-variant Nolan's sequences through Valhalla."""

import argparse
import csv
import hashlib
import json
import math
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Sequence

from peakroutefinder.model import Peak

EARTH_RADIUS_MILES = 3958.7613
GPX_NAMESPACE = {"g": "http://www.topografix.com/GPX/1/1"}
MAX_DISTANCE_METERS = 250_000
MAX_HIKING_DIFFICULTY = 6
STANDARD_PEAK_NAMES = (
    "Mount Shavano",
    "Tabeguache Peak",
    "Mount Antero",
    "Mount Princeton",
    "Mount Yale",
    "Mount Columbia",
    "Mount Harvard",
    "Mount Oxford",
    "Mount Belford",
    "Missouri Mountain",
    "Huron Peak",
    "La Plata Peak",
    "Mount Elbert",
    "Mount Massive",
)
SHERMAN_VARIANT_NAMES = (
    "Mount Sherman",
    "Mount Elbert",
    "La Plata Peak",
    "Huron Peak",
    "Missouri Mountain",
    "Mount Belford",
    "Mount Oxford",
    "Mount Harvard",
    "Mount Columbia",
    "Mount Yale",
    "Mount Princeton",
    "Mount Antero",
    "Tabeguache Peak",
    "Mount Shavano",
)

Coordinate = tuple[float, float]


def haversine_miles(origin: Coordinate, destination: Coordinate) -> float:
    """Return great-circle miles between two latitude/longitude pairs."""
    lat1, lon1 = (math.radians(value) for value in origin)
    lat2, lon2 = (math.radians(value) for value in destination)
    haversine = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(haversine))


def decode_polyline(encoded: str, precision: int = 6) -> list[Coordinate]:
    """Decode a Google encoded polyline into latitude/longitude pairs."""
    coordinates = []
    index = 0
    lat = 0
    lon = 0
    factor = 10**precision
    while index < len(encoded):
        for is_lon in (False, True):
            shift = 0
            result = 0
            while True:
                if index >= len(encoded):
                    raise ValueError("truncated encoded polyline")
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += delta
            else:
                lat += delta
        coordinates.append((lat / factor, lon / factor))
    return coordinates


def load_peaks(path: Path) -> dict[str, Peak]:
    """Load named peaks from the project's Lat,Lon,Name CSV format."""
    with path.open(newline="", encoding="utf-8") as source:
        return {
            row["Name"]: Peak(row["Name"], float(row["Lat"]), float(row["Lon"]))
            for row in csv.DictReader(source)
        }


def load_gpx(path: Path) -> list[Coordinate]:
    """Load track points in their original order."""
    root = ET.parse(path).getroot()
    return [
        (float(point.attrib["lat"]), float(point.attrib["lon"]))
        for point in root.findall(".//g:trkpt", GPX_NAMESPACE)
    ]


def path_miles(points: Sequence[Coordinate]) -> float:
    """Measure a coordinate path with the same haversine constant as the engine."""
    return sum(haversine_miles(a, b) for a, b in zip(points, points[1:]))


def reference_leg_miles(
    reference: Sequence[Coordinate], points: Sequence[Peak]
) -> list[float]:
    """Split a reference track at the nearest point to each route waypoint."""
    cumulative = [0.0]
    for origin, destination in zip(reference, reference[1:]):
        cumulative.append(cumulative[-1] + haversine_miles(origin, destination))
    indices = [
        min(
            range(len(reference)),
            key=lambda index: haversine_miles(
                (point.lat, point.lon), reference[index]
            ),
        )
        for point in points
    ]
    if indices != sorted(indices):
        raise ValueError("route waypoints do not follow the reference track order")
    return [0.0] + [
        cumulative[current] - cumulative[previous]
        for previous, current in zip(indices, indices[1:])
    ]


class ValhallaClient:
    """Small JSON HTTP client for the POC's locate and route calls."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, action: str, payload: dict) -> dict | list:
        request = urllib.request.Request(
            f"{self.base_url}/{action}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")
            raise RuntimeError(f"Valhalla HTTP {error.code}: {body}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Valhalla request failed: {error}") from error

    @staticmethod
    def _location(point: Peak) -> dict:
        return {"lat": point.lat, "lon": point.lon, "name": point.name}

    def coverage(self, points: Sequence[Peak]) -> list[dict]:
        """Report the nearest pedestrian-edge snap for every input point."""
        response = self._post(
            "locate",
            {
                "locations": [self._location(point) for point in points],
                "costing": "pedestrian",
                "verbose": False,
            },
        )
        report = []
        for point, result in zip(points, response):
            edges = result.get("edges") or []
            if not edges:
                report.append({"name": point.name, "snap_meters": None})
                continue
            nearest = min(
                edges,
                key=lambda edge: haversine_miles(
                    (point.lat, point.lon),
                    (edge["correlated_lat"], edge["correlated_lon"]),
                ),
            )
            snap_miles = haversine_miles(
                (point.lat, point.lon),
                (nearest["correlated_lat"], nearest["correlated_lon"]),
            )
            report.append(
                {
                    "name": point.name,
                    "snap_meters": round(snap_miles * 1609.344, 1),
                    "way_id": nearest["way_id"],
                    "correlated_lat": nearest["correlated_lat"],
                    "correlated_lon": nearest["correlated_lon"],
                }
            )
        return report

    def route(self, origin: Peak, destination: Peak) -> dict:
        """Return one shortest-distance pedestrian leg and decoded geometry."""
        response = self._post(
            "route",
            {
                "locations": [self._location(origin), self._location(destination)],
                "costing": "pedestrian",
                "costing_options": {
                    "pedestrian": {
                        "shortest": True,
                        "max_hiking_difficulty": MAX_HIKING_DIFFICULTY,
                        "max_distance": MAX_DISTANCE_METERS,
                        "use_hills": 1,
                    }
                },
                "units": "miles",
            },
        )
        trip = response["trip"]
        if len(trip["legs"]) != 1:
            raise RuntimeError("expected exactly one Valhalla leg")
        return {
            "origin": origin.name,
            "destination": destination.name,
            "status": "ok",
            "miles": trip["summary"]["length"],
            "geometry": decode_polyline(trip["legs"][0]["shape"]),
            "warnings": trip.get("warnings", []),
        }


def route_sequence(client: ValhallaClient, points: Sequence[Peak]) -> dict:
    """Route each pair independently so one failed connector cannot hide others."""
    legs = []
    for origin, destination in zip(points, points[1:]):
        try:
            leg = client.route(origin, destination)
        except RuntimeError as error:
            leg = {
                "origin": origin.name,
                "destination": destination.name,
                "status": "error",
                "error": str(error),
            }
        legs.append(leg)
    complete = all(leg["status"] == "ok" for leg in legs)
    return {
        "complete": complete,
        "total_miles": sum(leg["miles"] for leg in legs) if complete else None,
        "legs": legs,
    }


def total_miles_label(route: dict) -> str:
    """Format a complete total without presenting partial mileage as a total."""
    if not route["complete"]:
        return "INCOMPLETE"
    return f"{route['total_miles']:.2f} miles"


def geojson(routes: dict[str, dict], reference: Sequence[Coordinate]) -> dict:
    """Build a GeoJSON comparison of the GPX and every successful routed leg."""
    features = [
        {
            "type": "Feature",
            "properties": {"route": "reference-gpx"},
            "geometry": {
                "type": "LineString",
                "coordinates": [[lon, lat] for lat, lon in reference],
            },
        }
    ]
    for route_name, route in routes.items():
        for leg in route["legs"]:
            if leg["status"] != "ok":
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "route": route_name,
                        "origin": leg["origin"],
                        "destination": leg["destination"],
                        "miles": leg["miles"],
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [lon, lat] for lat, lon in leg["geometry"]
                        ],
                    },
                }
            )
    return {"type": "FeatureCollection", "features": features}


def main() -> int:
    """Run both sequences and write raw JSON and GeoJSON comparisons."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--peaks", type=Path, default=Path("data/colorado_14ers.csv"))
    parser.add_argument("--reference-gpx", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--router-url", default="http://127.0.0.1:18002")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    peaks = load_peaks(args.peaks)
    reference = load_gpx(args.reference_gpx)
    if len(reference) < 2:
        raise ValueError("reference GPX must contain at least two track points")
    standard_points = [Peak("Start (Blank Gulch)", *reference[0])]
    standard_points.extend(peaks[name] for name in STANDARD_PEAK_NAMES)
    standard_points.append(Peak("End (Fish Hatchery)", *reference[-1]))
    variant_points = [peaks[name] for name in SHERMAN_VARIANT_NAMES]
    all_points = standard_points + [peaks["Mount Sherman"]]

    client = ValhallaClient(args.router_url, args.timeout)
    routes = {
        "standard": route_sequence(client, standard_points),
        "sherman-variant": route_sequence(client, variant_points),
    }
    reference_legs = reference_leg_miles(reference, standard_points)
    for leg, reference_miles in zip(routes["standard"]["legs"], reference_legs[1:]):
        leg["reference_gpx_miles"] = reference_miles
        if leg["status"] == "ok":
            leg["minus_reference_miles"] = leg["miles"] - reference_miles

    results = {
        "configuration": {
            "router_url": args.router_url,
            "costing": "pedestrian",
            "shortest": True,
            "max_hiking_difficulty": MAX_HIKING_DIFFICULTY,
            "max_distance_meters": MAX_DISTANCE_METERS,
            "reference_gpx_sha256": hashlib.sha256(
                args.reference_gpx.read_bytes()
            ).hexdigest(),
            "reference_gpx_miles": path_miles(reference),
        },
        "coverage": client.coverage(all_points),
        "routes": routes,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )
    (args.output_dir / "routes.geojson").write_text(
        json.dumps(geojson(routes, reference)), encoding="utf-8"
    )

    for route_name, route in routes.items():
        print(f"{route_name}: {total_miles_label(route)}")
        for leg in route["legs"]:
            if leg["status"] == "ok":
                comparison = (
                    f" (GPX {leg['reference_gpx_miles']:.2f})"
                    if route_name == "standard"
                    else ""
                )
                print(
                    f"  {leg['origin']} -> {leg['destination']}: "
                    f"{leg['miles']:.2f}{comparison}"
                )
            else:
                print(
                    f"  {leg['origin']} -> {leg['destination']}: {leg['error']}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

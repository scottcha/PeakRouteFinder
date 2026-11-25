import sys

import pytest

from peakroutefinder.distance import haversine_miles
from peakroutefinder.model import Peak, RouteResult
from peakroutefinder.poc.nolans import ValhallaClient
from peakroutefinder.poc.optimize import _route_result, choose_leg, main
from peakroutefinder.solver import SolveReport, SolveStatus


def test_hybrid_choice_uses_actual_miles_not_hiking_effort() -> None:
    dem_candidate = {"miles": 8.0, "effort_miles": 30.0}

    assert choose_leg(10.0, dem_candidate) == (8.0, "dem-off-trail")
    assert choose_leg(7.0, dem_candidate) == (7.0, "valhalla")


def test_valhalla_matrix_rejects_an_unreachable_pair(monkeypatch) -> None:
    client = ValhallaClient("http://127.0.0.1:18002", timeout=1.0)
    def response(action, payload):
        return {
            "sources_to_targets": [[{"distance": 0.0}, {"distance": None}]],
            "sources": payload["sources"],
            "targets": payload["targets"],
        }

    monkeypatch.setattr(client, "_post", response)

    points = [Peak("A", 0.0, 0.0), Peak("B", 1.0, 1.0)]
    with pytest.raises(RuntimeError, match="no route from A to B"):
        client.matrix(points)

    bounded = client.matrix(points, max_haversine=100.0)
    assert bounded[0][1] > 100.0


def test_valhalla_matrix_chunks_large_requests(monkeypatch) -> None:
    client = ValhallaClient("http://127.0.0.1:18002", timeout=1.0)
    monkeypatch.setattr("peakroutefinder.poc.nolans.MAX_MATRIX_LOCATIONS", 3)
    calls = []

    def response(action, payload):
        calls.append(payload)
        return {
            "sources_to_targets": [
                [{"distance": float(row + column)} for column in range(3)]
                for row in range(len(payload["sources"]))
            ],
            "sources": payload["sources"],
            "targets": payload["targets"],
        }

    monkeypatch.setattr(client, "_post", response)
    points = [Peak(str(index), float(index), 0.0) for index in range(3)]

    assert client.matrix(points) == [
        [0.0, 1.0, 2.0],
        [0.0, 0.0, 2.0],
        [0.0, 1.0, 0.0],
    ]
    assert [len(call["sources"]) for call in calls] == [1, 1, 1]


def test_matrix_response_must_be_an_object(monkeypatch) -> None:
    client = ValhallaClient("http://127.0.0.1:18002", timeout=1.0)
    monkeypatch.setattr(client, "_post", lambda action, payload: [])

    with pytest.raises(RuntimeError, match="invalid matrix response"):
        client.matrix([Peak("A", 0.0, 0.0)])


def test_result_valhalla_leg_keeps_exact_matrix_mileage() -> None:
    points = [Peak("A", 0.0, 0.0), Peak("B", 1.0, 1.0)]
    matrix = {
        "sources": [["self", "valhalla"], ["valhalla", "self"]],
        "distances": [[0.0, 8.0], [8.0, 0.0]],
        "dem_legs": {},
    }
    route = RouteResult(points, 8.0, 2, True)
    report = SolveReport(route, SolveStatus.OPTIMAL, 2)

    class GeometryClient:
        def route(self, origin, destination):
            return {
                "origin": origin.name,
                "destination": destination.name,
                "status": "ok",
                "miles": 8.0035,
                "geometry": [(0.0, 0.0), (1.0, 1.0)],
                "warnings": [],
            }

    result = _route_result(points, matrix, report, GeometryClient())

    assert result["legs"][0]["miles"] == 8.0
    assert sum(leg["miles"] for leg in result["legs"]) == route.total_miles


def test_budget_above_matrix_cutoff_is_rejected(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "optimize",
            "--budget",
            "101",
            "--output-dir",
            "/tmp/unused-hybrid-output",
        ],
    )

    with pytest.raises(SystemExit):
        main()
    assert "between 0 and 100" in capsys.readouterr().err


def test_valhalla_route_touches_exact_endpoints_and_charges_snaps(
    monkeypatch,
) -> None:
    client = ValhallaClient("http://127.0.0.1:18002", timeout=1.0)
    monkeypatch.setattr(
        client,
        "_post",
        lambda action, payload: {
            "trip": {
                "summary": {"length": 10.0},
                "legs": [{"shape": "snapped"}],
            }
        },
    )
    monkeypatch.setattr(
        "peakroutefinder.poc.nolans.decode_polyline",
        lambda shape: [(0.0, 0.01), (0.0, 0.99)],
    )
    origin = Peak("A", 0.0, 0.0)
    destination = Peak("B", 0.0, 1.0)

    leg = client.route(origin, destination)

    snap_miles = haversine_miles((0.0, 0.0), (0.0, 0.01))
    assert leg["geometry"][0] == (origin.lat, origin.lon)
    assert leg["geometry"][-1] == (destination.lat, destination.lon)
    assert leg["miles"] == pytest.approx(10.0 + 2 * snap_miles)


def test_valhalla_matrix_charges_origin_and_destination_snaps(
    monkeypatch,
) -> None:
    client = ValhallaClient("http://127.0.0.1:18002", timeout=1.0)

    def response(action, payload):
        source = payload["sources"][0]
        targets = payload["targets"]
        return {
            "sources_to_targets": [
                [
                    {
                        "distance": (
                            0.0 if source["name"] == target["name"] else 10.0
                        )
                    }
                    for target in targets
                ]
            ],
            "sources": [{"lat": source["lat"], "lon": source["lon"] + 0.01}],
            "targets": [
                {"lat": target["lat"], "lon": target["lon"] + 0.01}
                for target in targets
            ],
        }

    monkeypatch.setattr(client, "_post", response)
    points = [Peak("A", 0.0, 0.0), Peak("B", 0.0, 1.0)]

    matrix = client.matrix(points)

    snap_miles = haversine_miles((0.0, 0.0), (0.0, 0.01))
    assert matrix[0][0] == 0.0
    assert matrix[1][1] == 0.0
    assert matrix[0][1] == pytest.approx(10.0 + 2 * snap_miles)
    assert matrix[1][0] == pytest.approx(10.0 + 2 * snap_miles)

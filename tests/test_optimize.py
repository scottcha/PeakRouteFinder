import pytest

from peakroutefinder.model import Peak
from peakroutefinder.poc.nolans import ValhallaClient
from peakroutefinder.poc.optimize import choose_leg


def test_hybrid_choice_uses_actual_miles_not_hiking_effort() -> None:
    dem_candidate = {"miles": 8.0, "effort_miles": 30.0}

    assert choose_leg(10.0, dem_candidate) == (8.0, "dem-off-trail")
    assert choose_leg(7.0, dem_candidate) == (7.0, "valhalla")


def test_valhalla_matrix_rejects_an_unreachable_pair(monkeypatch) -> None:
    client = ValhallaClient("http://127.0.0.1:18002", timeout=1.0)
    monkeypatch.setattr(
        client,
        "_post",
        lambda action, payload: {
            "sources_to_targets": [[{"distance": 0.0}, {"distance": None}]]
        },
    )

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
            ]
        }

    monkeypatch.setattr(client, "_post", response)
    points = [Peak(str(index), float(index), 0.0) for index in range(3)]

    assert client.matrix(points) == [
        [0.0, 1.0, 2.0],
        [0.0, 1.0, 2.0],
        [0.0, 1.0, 2.0],
    ]
    assert [len(call["sources"]) for call in calls] == [1, 1, 1]

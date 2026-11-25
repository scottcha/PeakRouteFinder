"""Conformance tests for great-circle distances and coordinate validation."""

import pytest

from peakroutefinder.distance import HaversineProvider
from peakroutefinder.model import Peak


def test_elbert_to_massive_distance() -> None:
    """The two neighboring Colorado peaks are about five miles apart."""
    matrix = HaversineProvider().matrix(
        [
            Peak("Mount Elbert", 39.1178, -106.4454),
            Peak("Mount Massive", 39.1875, -106.4757),
        ]
    )
    assert matrix[0][1] == pytest.approx(5.08, abs=0.01)
    assert matrix[0][1] == matrix[1][0]


def test_one_degree_at_equator() -> None:
    """One longitude degree at the equator matches the Earth-radius constant."""
    matrix = HaversineProvider().matrix([Peak("A", 0, 0), Peak("B", 0, 1)])
    assert matrix[0][1] == pytest.approx(69.09, abs=0.01)


@pytest.mark.parametrize(
    "point",
    [
        Peak("bad latitude", 91, 0),
        Peak("bad longitude", 0, 181),
        Peak("not a number", float("nan"), 0),
    ],
)
def test_invalid_coordinates_raise(point: Peak) -> None:
    """Out-of-range coordinates are rejected instead of producing distances."""
    with pytest.raises(ValueError):
        HaversineProvider().matrix([point])

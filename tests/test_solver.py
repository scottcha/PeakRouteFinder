"""Conformance tests for exact count, cost, infeasibility, and timeout behavior."""

from pathlib import Path

import pytest

from peakroutefinder.cli import load_peaks
from peakroutefinder.model import Peak
from peakroutefinder.solver import SolveStatus, solve

DATA_DIR = Path(__file__).parents[1] / "data"


def test_square_budget_selects_three_peaks() -> None:
    """A 140-mile square budget covers two sides but not a third."""
    square = [Peak("A", 0, 0), Peak("B", 0, 1), Peak("C", 1, 1), Peak("D", 1, 0)]
    report = solve(square, 140, workers=4, time_limit=30)
    assert report.status == SolveStatus.OPTIMAL
    assert report.route is not None
    assert report.route.proven_optimal
    assert report.route.peak_count == 3
    assert report.route.total_miles == pytest.approx(138.18, abs=0.01)


def test_second_phase_chooses_cheapest_peak_count_tie() -> None:
    """Among equally large routes, the solver selects the closest pair."""
    peaks = [Peak("A", 0, 0), Peak("B", 0, 0.01), Peak("C", 0, 0.03), Peak("D", 10, 10)]
    report = solve(peaks, 1.4, workers=4, time_limit=30)
    assert report.status == SolveStatus.OPTIMAL
    assert report.route is not None
    assert report.route.peak_count == 2
    assert {peak.name for peak in report.route.order} == {"A", "B"}
    assert report.route.total_miles == pytest.approx(0.69, abs=0.01)


def test_infeasible_start_end_budget() -> None:
    """A budget below the direct waypoint distance has no feasible route."""
    report = solve(
        [],
        1,
        start=Peak("Start", 0, 0),
        end=Peak("End", 0, 1),
        workers=4,
        time_limit=30,
    )
    assert report.status == SolveStatus.INFEASIBLE
    assert report.route is None


def test_timeout_does_not_claim_optimality() -> None:
    """An expiring solver returns a timeout and no optimality proof."""
    peaks = load_peaks(DATA_DIR / "colorado_14ers.csv")
    report = solve(peaks, 100, workers=1, time_limit=0.000001)
    assert report.status == SolveStatus.TIMEOUT
    assert report.route is None or not report.route.proven_optimal

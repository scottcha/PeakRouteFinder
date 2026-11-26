"""Exact peak-count and mileage optimization using an OR-Tools circuit model."""

import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from ortools.sat.python import cp_model

from peakroutefinder.distance import DistanceProvider, HaversineProvider
from peakroutefinder.model import Peak, RouteResult

DISTANCE_SCALE = 1000
DEFAULT_TIME_LIMIT_SECONDS = 120.0
DEFAULT_WORKERS = min(16, os.cpu_count() or 1)


class SolveStatus(str, Enum):
    """Overall result of the two optimization phases."""

    OPTIMAL = "optimal"
    TIMEOUT = "timeout"
    INFEASIBLE = "infeasible"
    ERROR = "error"


@dataclass(frozen=True)
class SolveReport:
    """A route, when one was found, and the best proven peak-count bound."""

    route: RouteResult | None
    status: SolveStatus
    peak_bound: int


@dataclass
class CircuitModel:
    """The CP-SAT model and expressions needed by both solve phases."""

    model: cp_model.CpModel
    arcs: dict[tuple[int, int], cp_model.IntVar]
    depot: int
    peak_count: int
    cost: cp_model.LinearExpr

    @property
    def visited_peaks(self) -> cp_model.LinearExpr:
        """Return the number of peak nodes whose skip arc is disabled."""
        return sum(1 - self.arcs[index, index] for index in range(self.peak_count))


def build_circuit_model(
    distances: Sequence[Sequence[int]],
    peak_count: int,
    budget_units: int,
    start_index: int | None,
    end_index: int | None,
) -> CircuitModel:
    """Build one circuit with skip loops and caller-supplied terminal costs."""
    depot = len(distances) - 1
    model = cp_model.CpModel()
    arcs: dict[tuple[int, int], cp_model.IntVar] = {}
    circuit_arcs = []
    for tail in range(len(distances)):
        for head in range(len(distances)):
            arc = model.NewBoolVar(f"arc_{tail}_{head}")
            arcs[tail, head] = arc
            circuit_arcs.append((tail, head, arc))

    cost = sum(
        arcs[tail, head] * distances[tail][head]
        for tail in range(len(distances))
        for head in range(len(distances))
        if tail != head
    )
    model.Add(cost <= budget_units)
    model.Add(arcs[depot, depot] == 0)

    if start_index is not None:
        model.Add(arcs[start_index, start_index] == 0)
        for head in range(depot):
            if head != start_index:
                model.Add(arcs[depot, head] == 0)
        for tail in range(depot):
            if tail != start_index:
                model.Add(arcs[tail, start_index] == 0)

    if end_index is not None:
        model.Add(arcs[end_index, end_index] == 0)
        for tail in range(depot):
            if tail != end_index:
                model.Add(arcs[tail, depot] == 0)
        for head in range(depot):
            if head != end_index:
                model.Add(arcs[end_index, head] == 0)

    model.AddCircuit(circuit_arcs)
    return CircuitModel(model, arcs, depot, peak_count, cost)


def _new_solver(time_limit: float, workers: int) -> cp_model.CpSolver:
    """Create a solver with bounded wall time and parallelism."""
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers = workers
    return solver


def _has_solution(status: cp_model.CpSolverStatus) -> bool:
    """Return whether CP-SAT produced values that can be extracted."""
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def _extract_route(
    circuit: CircuitModel,
    solver: cp_model.CpSolver,
    points: Sequence[Peak],
    distances: Sequence[Sequence[float]],
    proven_optimal: bool,
) -> RouteResult:
    """Follow taken arcs from the depot and omit its zero-cost hops."""
    next_node = {
        tail: head
        for (tail, head), arc in circuit.arcs.items()
        if tail != head and solver.Value(arc)
    }
    sequence = []
    current = next_node[circuit.depot]
    while current != circuit.depot:
        sequence.append(current)
        current = next_node[current]

    total_miles = sum(
        distances[tail][head] for tail, head in zip(sequence, sequence[1:])
    )
    return RouteResult(
        order=[points[index] for index in sequence],
        total_miles=total_miles,
        peak_count=sum(index < circuit.peak_count for index in sequence),
        proven_optimal=proven_optimal,
    )


def solve(
    peaks: Sequence[Peak],
    budget_miles: float,
    *,
    start: Peak | None = None,
    end: Peak | None = None,
    provider: DistanceProvider | None = None,
    time_limit: float = DEFAULT_TIME_LIMIT_SECONDS,
    workers: int = DEFAULT_WORKERS,
) -> SolveReport:
    """Maximize visited peaks, then minimize mileage at that peak count."""
    if budget_miles < 0:
        raise ValueError("budget must be non-negative")
    if time_limit <= 0:
        raise ValueError("time limit must be positive")
    if workers < 1:
        raise ValueError("workers must be at least 1")

    points = list(peaks)
    start_index = len(points) if start is not None else None
    if start is not None:
        points.append(start)
    end_index = len(points) if end is not None else None
    if end is not None:
        points.append(end)

    distance_provider = provider if provider is not None else HaversineProvider()
    real_distances = distance_provider.matrix(points)
    real_count = len(points)
    scaled_distances = [
        [int(round(distance * DISTANCE_SCALE)) for distance in row]
        for row in real_distances
    ]
    for row in scaled_distances:
        row.append(0)
    scaled_distances.append([0] * (real_count + 1))
    budget_units = int(budget_miles * DISTANCE_SCALE)

    def build() -> CircuitModel:
        """Rebuild the same constraint set for an independent solve phase."""
        return build_circuit_model(
            scaled_distances, len(peaks), budget_units, start_index, end_index
        )

    first_phase = build()
    first_phase.model.Maximize(first_phase.visited_peaks)
    first_solver = _new_solver(time_limit, workers)
    first_status = first_solver.Solve(first_phase.model)

    if first_status == cp_model.INFEASIBLE:
        return SolveReport(None, SolveStatus.INFEASIBLE, 0)
    if first_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.UNKNOWN):
        return SolveReport(None, SolveStatus.ERROR, len(peaks))

    peak_bound = (
        len(peaks)
        if first_status == cp_model.UNKNOWN
        else int(math.ceil(first_solver.BestObjectiveBound() - 1e-6))
    )
    if not _has_solution(first_status):
        return SolveReport(None, SolveStatus.TIMEOUT, peak_bound)

    found_peaks = int(round(first_solver.ObjectiveValue()))
    float_distances = [row + [0.0] for row in real_distances]
    float_distances.append([0.0] * (real_count + 1))
    best_route = _extract_route(
        first_phase, first_solver, points, float_distances, proven_optimal=False
    )
    if first_status == cp_model.FEASIBLE:
        best_route = RouteResult(
            best_route.order,
            best_route.total_miles,
            found_peaks,
            proven_optimal=False,
        )

    second_phase = build()
    second_phase.model.Add(second_phase.visited_peaks == found_peaks)
    second_phase.model.Minimize(second_phase.cost)
    second_solver = _new_solver(time_limit, workers)
    second_status = second_solver.Solve(second_phase.model)

    if _has_solution(second_status):
        best_route = _extract_route(
            second_phase,
            second_solver,
            points,
            float_distances,
            proven_optimal=False,
        )
    elif second_status not in (cp_model.UNKNOWN, cp_model.FEASIBLE):
        return SolveReport(best_route, SolveStatus.ERROR, peak_bound)

    both_optimal = first_status == second_status == cp_model.OPTIMAL
    if both_optimal:
        best_route = RouteResult(
            best_route.order,
            best_route.total_miles,
            best_route.peak_count,
            proven_optimal=True,
        )
        return SolveReport(best_route, SolveStatus.OPTIMAL, peak_bound)
    return SolveReport(best_route, SolveStatus.TIMEOUT, peak_bound)

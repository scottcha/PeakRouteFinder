"""Command-line loading, reporting, and CSV export for peak-route optimization."""

import argparse
import csv
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from peakroutefinder.distance import HaversineProvider, validate_coordinates
from peakroutefinder.model import Peak, RouteResult
from peakroutefinder.solver import (
    DEFAULT_TIME_LIMIT_SECONDS,
    DEFAULT_WORKERS,
    SolveStatus,
    solve,
)

CSV_HEADER = ["Lat", "Lon", "Name"]
EXIT_ERROR = 1
EXIT_TIMEOUT = 2
EXIT_INFEASIBLE = 3


class _ArgumentParser(argparse.ArgumentParser):
    """Use the CLI's documented exit code for usage errors."""

    def error(self, message: str) -> None:
        """Print an argparse error and exit with status 1."""
        self.print_usage(sys.stderr)
        self.exit(EXIT_ERROR, f"{self.prog}: error: {message}\n")


def load_peaks(path: Path) -> list[Peak]:
    """Load a Lat,Lon,Name CSV, rejecting malformed or empty input."""
    peaks = []
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.reader(source)
        try:
            header = next(reader)
        except StopIteration as error:
            raise ValueError(f"{path}: file is empty") from error
        if header != CSV_HEADER:
            raise ValueError(f"{path}: line 1: expected header Lat,Lon,Name")

        for row in reader:
            line_number = reader.line_num
            if len(row) != 3 or any(not value.strip() for value in row):
                raise ValueError(f"{path}: line {line_number}: expected Lat,Lon,Name")
            lat_text, lon_text, name = (value.strip() for value in row)
            try:
                peak = Peak(name, float(lat_text), float(lon_text))
                validate_coordinates(peak)
            except ValueError as error:
                raise ValueError(f"{path}: line {line_number}: {error}") from error
            peaks.append(peak)

    if not peaks:
        raise ValueError(f"{path}: no peaks found")
    return peaks


def _coordinates(value: str) -> tuple[float, float]:
    """Parse a command-line lat,lon pair."""
    try:
        lat_text, lon_text = value.split(",")
        coordinates = float(lat_text), float(lon_text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected lat,lon") from error
    point = Peak("waypoint", *coordinates)
    try:
        validate_coordinates(point)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return coordinates


def _nonnegative_float(value: str) -> float:
    """Parse a non-negative command-line number."""
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a number") from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def _positive_float(value: str) -> float:
    """Parse a positive command-line number."""
    number = _nonnegative_float(value)
    if number == 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def _positive_int(value: str) -> int:
    """Parse a positive command-line integer."""
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an integer") from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Construct the command-line argument parser."""
    parser = _ArgumentParser(
        prog="peakroutefinder",
        description="Prove the optimal peak route within a mileage budget.",
    )
    parser.add_argument("list_csv", type=Path, help="CSV with Lat,Lon,Name columns")
    parser.add_argument("--budget", type=_nonnegative_float, required=True, help="miles")
    parser.add_argument("--start", type=_coordinates, metavar="LAT,LON")
    parser.add_argument("--end", type=_coordinates, metavar="LAT,LON")
    parser.add_argument(
        "--time-limit",
        type=_positive_float,
        default=DEFAULT_TIME_LIMIT_SECONDS,
        metavar="SECONDS",
        help=f"per-phase solver limit (default: {DEFAULT_TIME_LIMIT_SECONDS:g})",
    )
    parser.add_argument(
        "--workers",
        type=_positive_int,
        default=DEFAULT_WORKERS,
        help=f"CP-SAT workers (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument("--out", type=Path, help="write route legs to this CSV")
    return parser


def _labels(route: RouteResult) -> list[str]:
    """Disambiguate repeated names by their one-based route positions."""
    name_counts = Counter(point.name for point in route.order)
    return [
        f"{point.name} [{position}]" if name_counts[point.name] > 1 else point.name
        for position, point in enumerate(route.order, start=1)
    ]


def _leg_distances(route: RouteResult) -> list[float]:
    """Calculate the distance of each route leg, starting with zero."""
    if not route.order:
        return []
    matrix = HaversineProvider().matrix(route.order)
    return [0.0] + [
        matrix[index - 1][index] for index in range(1, len(route.order))
    ]


def _write_csv(path: Path, labels: Sequence[str], legs: Sequence[float]) -> None:
    """Write ordered route legs, replacing any existing file."""
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(["order", "peak", "leg_miles"])
        for order, (label, miles) in enumerate(zip(labels, legs), start=1):
            writer.writerow([order, label, str(round(miles, 6))])


def _print_route(route: RouteResult) -> tuple[list[str], list[float]]:
    """Print route details and return the values needed for CSV export."""
    labels = _labels(route)
    legs = _leg_distances(route)
    print("PROVEN OPTIMAL" if route.proven_optimal else "NOT PROVEN OPTIMAL")
    print(f"Peaks: {route.peak_count}")
    print(f"Total miles: {route.total_miles:.2f}")
    print("\nLeg  Peak                                      Miles")
    for order, (label, miles) in enumerate(zip(labels, legs), start=1):
        print(f"{order:>3}  {label:<40} {miles:>8.2f}")
    print("\nRoute: " + " -> ".join(labels))
    return labels, legs


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return its documented process exit code."""
    args = build_parser().parse_args(argv)
    try:
        peaks = load_peaks(args.list_csv)
        start = Peak("Start", *args.start) if args.start is not None else None
        end = Peak("End", *args.end) if args.end is not None else None
        report = solve(
            peaks,
            args.budget,
            start=start,
            end=end,
            time_limit=args.time_limit,
            workers=args.workers,
        )
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_ERROR

    if report.status == SolveStatus.INFEASIBLE:
        print("infeasible: budget covers no path from start to end", file=sys.stderr)
        return EXIT_INFEASIBLE
    if report.status == SolveStatus.ERROR:
        print("solver failed to find a route", file=sys.stderr)
        return EXIT_ERROR

    if report.route is not None:
        labels, legs = _print_route(report.route)
        if args.out is not None:
            try:
                _write_csv(args.out, labels, legs)
            except OSError as error:
                print(f"error: {error}", file=sys.stderr)
                return EXIT_ERROR

    if report.status == SolveStatus.TIMEOUT:
        found = report.route.peak_count if report.route is not None else 0
        print(
            f"solver timed out after {args.time_limit:g}s: "
            f"peaks {found}/{report.peak_bound}",
            file=sys.stderr,
        )
        return EXIT_TIMEOUT
    return 0

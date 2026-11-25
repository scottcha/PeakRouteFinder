"""End-to-end CLI checks against the bundled peak lists."""

import csv
from pathlib import Path

from peakroutefinder.cli import main

DATA_DIR = Path(__file__).parents[1] / "data"


def test_colorado_optimal_route(capsys) -> None:
    """The 100-mile Colorado instance proves its known 20-peak optimum."""
    exit_code = main(
        [str(DATA_DIR / "colorado_14ers.csv"), "--budget", "100", "--time-limit", "60", "--workers", "16"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PROVEN OPTIMAL" in captured.out
    assert "Peaks: 20" in captured.out


def test_colorado_with_waypoints_csv_and_map(capsys, tmp_path) -> None:
    """Waypoint optimization exports route legs and an interactive map."""
    output = tmp_path / "route.csv"
    map_output = tmp_path / "route.html"
    exit_code = main(
        [
            str(DATA_DIR / "colorado_14ers.csv"),
            "--budget",
            "100",
            "--start",
            "39.4718,-106.0975",
            "--end",
            "39.0046,-106.3706",
            "--time-limit",
            "60",
            "--workers",
            "4",
            "--out",
            str(output),
            "--map",
            str(map_output),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PROVEN OPTIMAL" in captured.out
    assert "Peaks: 16" in captured.out
    with output.open(newline="", encoding="utf-8") as source:
        rows = list(csv.reader(source))
    assert rows[0] == ["order", "peak", "leg_miles"]
    assert rows[1] == ["1", "Start", "0.0"]
    assert rows[-1][1] == "End"
    assert len(rows) == 19
    map_html = map_output.read_text(encoding="utf-8")
    assert "server.arcgisonline.com" in map_html.lower()
    assert "L.polyline" in map_html


def test_washington_optimal_route(capsys) -> None:
    """The 60-mile Washington instance proves its known 27-peak optimum."""
    exit_code = main(
        [str(DATA_DIR / "washington_top100.csv"), "--budget", "60", "--time-limit", "60", "--workers", "16"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PROVEN OPTIMAL" in captured.out
    assert "Peaks: 27" in captured.out


def test_non_finite_numbers_are_usage_errors(capsys) -> None:
    """Infinite budget and time values exit cleanly instead of overflowing."""
    argument_sets = [
        [str(DATA_DIR / "colorado_14ers.csv"), "--budget", "inf"],
        [str(DATA_DIR / "colorado_14ers.csv"), "--budget", "100", "--time-limit", "inf"],
    ]
    for arguments in argument_sets:
        try:
            main(arguments)
        except SystemExit as error:
            assert error.code == 1
        else:
            raise AssertionError("argparse should reject non-finite numbers")
        captured = capsys.readouterr()
        assert "must be finite" in captured.err

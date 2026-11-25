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


def test_colorado_with_waypoints_and_csv(capsys, tmp_path) -> None:
    """Trailhead-to-trailhead optimization includes waypoint legs and CSV export."""
    output = tmp_path / "route.csv"
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
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PROVEN OPTIMAL" in captured.out
    assert "Peaks: 16" in captured.out
    assert "Total miles: 92.32" in captured.out
    with output.open(newline="", encoding="utf-8") as source:
        rows = list(csv.reader(source))
    assert rows[0] == ["order", "peak", "leg_miles"]
    assert rows[1] == ["1", "Start", "0.0"]
    assert rows[-1][1] == "End"
    assert len(rows) == 19


def test_washington_optimal_route(capsys) -> None:
    """The 60-mile Washington instance proves its known 27-peak optimum."""
    exit_code = main(
        [str(DATA_DIR / "washington_top100.csv"), "--budget", "60", "--time-limit", "60", "--workers", "16"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PROVEN OPTIMAL" in captured.out
    assert "Peaks: 27" in captured.out

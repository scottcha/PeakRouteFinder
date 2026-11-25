# PeakRouteFinder

PeakRouteFinder answers the Nolan's 14-style question: **what is the largest number of peaks you can traverse within a mileage budget?** It uses an exact OR-Tools CP-SAT model, so a successful run proves that no route with more peaks exists and that the selected route has the lowest mileage at that peak count.

The current distance model is straight-line haversine mileage. Optional start and end coordinates represent trailheads, and their travel legs count toward the budget.

## Quick start

Python 3.11 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
python -m peakroutefinder data/colorado_14ers.csv --budget 100
```

The final command prints `PROVEN OPTIMAL`, a 20-peak route, its 97.84-mile total, each leg, and the complete visit order.

Add arbitrary trailheads with comma-separated latitude and longitude:

```bash
python -m peakroutefinder data/colorado_14ers.csv --budget 100 \
    --start "39.4718,-106.0975" --end "39.0046,-106.3706"
```

Omit `--end` for an open route beginning at the start waypoint. Omit both waypoints to optimize only the supplied peak list.

## Input and output

The input CSV must have exactly three columns and at least one peak:

```csv
Lat,Lon,Name
39.1178,-106.4454,Mount Elbert
39.1875,-106.4757,Mount Massive
```

Malformed rows, invalid coordinates, and empty files are rejected with the file name and line number. Duplicate names are allowed and are disambiguated by route position in the output.

```text
python -m peakroutefinder <list.csv> --budget MILES
    [--start LAT,LON] [--end LAT,LON]
    [--time-limit SECONDS] [--workers COUNT]
    [--out results.csv] [--map route.html]
```

`--time-limit` applies separately to each solve phase and defaults to 120 seconds. `--workers` defaults to the smaller of 16 and the available CPU count. `--out` writes `order,peak,leg_miles` rows and replaces an existing file.

### Route maps

```bash
python -m peakroutefinder data/colorado_14ers.csv --budget 100 --map colorado-route.html
```

![Colorado 14ers optimal route with a 100-mile budget](docs/images/colorado-route.png)

`--map` writes an interactive HTML map with an Esri WorldTopoMap basemap fitted to the input list. Every listed peak appears: visited peaks have name labels in route order, unvisited peaks are gray, and optional start/end waypoints are green/red. The key lists route peaks in order and includes a collapsible list of the other listed peaks. Hover over points for names and coordinates. The route line includes waypoint legs.

Open the HTML file in a browser. Internet access is required to load the Leaflet assets and Esri basemap tiles.

Exit codes are 0 for success, 1 for usage or loading errors, 2 when either solve phase reaches its time limit, and 3 when no feasible route exists. A timeout reports the best route found and the proven peak-count bound without claiming optimality.

## How the proof works

Peaks and waypoints become nodes in a CP-SAT circuit. Each unvisited node takes a self-loop, while visited nodes form one path connected to a zero-cost dummy depot. Taken non-depot arcs contribute their integer milli-mile distances to the budget constraint.

The first phase maximizes the number of visited peaks. The second rebuilds the model, fixes that count, and minimizes total mileage. `PROVEN OPTIMAL` requires both phases to finish with CP-SAT status `OPTIMAL`.

The proof applies to the supplied distance matrix. Straight-line distances are not trail distances, so the current results should not be interpreted as real-world route feasibility.

Verified examples with OR-Tools 9.15.6755:

| Instance | Budget | Peaks | Miles | Result |
|---|---:|---:|---:|---|
| Colorado 53 | 100 mi | 20 | 97.84 | Proven optimal |
| Colorado 53, start and end | 100 mi | 16 | 92.32 | Proven optimal |
| Washington top 100 | 60 mi | 27 | 57.50 | Proven optimal |

## Roadmap

| Phase | Scope | Estimated effort | Status |
|---|---|---|---|
| 1. Engine core | CLI, list loading, distance matrix, exact two-phase solve | One sitting | Implemented and verified |
| 2. Real geometry | Valhalla table service or a precomputed CSV matrix | Days, including external data preparation | POC complete; Nolan's connector curation required |

Phase 2 keeps distance acquisition behind the existing `DistanceProvider` seam. Trail support also needs unreachable-arc handling and provider-owned leg distances and geometry; the solver's two-phase objective remains unchanged.

The [Nolan's Valhalla POC](poc/valhalla/README.md) provides a reproducible local router and GPX comparison. Stock OSM routed every requested leg but produced 166.92 miles versus the reference GPX's 100.82 miles. A POC-only hybrid using seven penalty-weighted GPX-backed connectors measures 104.01 miles. A no-reference heuristic using twelve direct connectors at 1.65× haversine estimates 92.65 miles. DEM-aware A* replaces straight candidates with terrain paths and measures 91.07 miles using eight DEM connectors; all remain evaluation models rather than general trail-distance providers. Applying the exact optimizer to a 53-peak Valhalla+DEM matrix proves a 17-peak, 97.26-mile maximum at a 100-mile budget; an 18th peak requires 102.97 miles within that matrix.

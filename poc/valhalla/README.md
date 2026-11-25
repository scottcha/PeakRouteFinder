# Nolan's 14 Valhalla proof of concept

This POC checks whether a local Valhalla pedestrian router can reproduce Nolan's trail distances and geometry before we integrate it with the CP-SAT optimizer. It routes each connector independently, so no failed leg is hidden by an otherwise successful request.

## Reproduce

Requirements: Docker, curl, and the project's Python environment.

Start Valhalla in one terminal:

```bash
poc/valhalla/run_valhalla.sh
```

The launcher downloads the pinned Colorado extract on its first run, verifies its SHA-256, builds tiles, and listens on `127.0.0.1:18002`. Tile files remain under `/tmp/peakroutefinder-valhalla/custom_files`. Set `VALHALLA_PORT` or `VALHALLA_THREADS` to override those defaults.

Download the public reference GPX in another terminal:

```bash
curl -fL \
  https://fastestknowntime.com/system/files/routes/gps_data/export_11.gpx \
  -o /tmp/peakroutefinder-valhalla/nolans-fkt.gpx
```

Run the standard, Sherman-variant, and GPX-backed hybrid sequences:

```bash
.venv/bin/python -m peakroutefinder.poc.nolans \
  --reference-gpx /tmp/peakroutefinder-valhalla/nolans-fkt.gpx \
  --output-dir /tmp/peakroutefinder-valhalla/results
```

Outputs:

- `results.json`: configuration, summit/trailhead snapping, leg distances, errors, connector provenance, and decoded geometry.
- `routes.geojson`: the reference track, successful Valhalla legs, and selected hybrid legs for visual comparison.

The GPX comes from the [Fastest Known Time Nolan's route page](https://fastestknowntime.com/route/nolans-14-co). Its redistribution license is not stated, so it is downloaded rather than committed.

## Frozen inputs and routing configuration

| Input | Identity |
|---|---|
| Valhalla | 3.9.3, image digest `sha256:d438516425e785442562852d2f38d048478b6895bb15850491b81332f85bc4be` |
| OSM | Geofabrik `colorado-261124.osm.pbf` |
| OSM SHA-256 | `90e8c15e77665205f8090fd8dd3aae0a13bc97d961819e7b41d291a1d6541347` |
| Reference GPX SHA-256 | `3af279e155f69036a82f3d33521663693385cddf8ac4fed3091699cfd828f90c` |
| Costing | `pedestrian`, `shortest=true`, `use_hills=1` |
| Hiking difficulty | 6, the most permissive `sac_scale` setting; this is a coverage POC, not a safety recommendation |
| Maximum route distance | 250,000 meters, explicitly above Valhalla's 100,000-meter default |
| GPX off-trail penalty | 1.35× for candidate selection only; actual GPX mileage is still reported |

## Results

The reference GPX contains 146,806 track points and measures **100.82 miles** using the project's haversine constant. It runs from Blank Gulch to Fish Hatchery and passes within 0.007 miles of every standard Nolan's summit.

Valhalla returned geometry for every requested leg. No leg failed, but many returned long loops around missing or excluded off-trail connections.

| Route | Distance | Reference | Difference |
|---|---:|---:|---:|
| Standard Nolan's, Blank Gulch to Fish Hatchery | 166.92 mi | 100.82 mi | +66.10 mi (+65.6%) |
| GPX-backed hybrid, same endpoints | 104.01 mi | 100.82 mi | +3.19 mi (+3.2%) |
| Sherman-to-Shavano variant, summit to summit | 166.39 mi | No matching GPX | Not compared |

The hybrid selects each GPX leg when `GPX miles × 1.35 < Valhalla miles`, or when Valhalla fails. It uses **7 GPX-backed connectors**, retains Valhalla on 8 legs, and has **121.33 penalty-weighted miles**. Actual mileage remains the geometric distance of the selected path; the penalty affects only selection. The `gpx-backed-off-trail` source identifies the connector's evidence, not a claim that every GPX point is off-trail.

The Sherman variant uses Sherman, Elbert, La Plata, Huron, Missouri, Belford, Oxford, Harvard, Columbia, Yale, Princeton, Antero, Tabeguache, and Shavano. It excludes trailhead approaches because its reference trailheads were not supplied.

![Valhalla routes compared with the reference GPX](comparison.png)

Red is the 100.82-mile reference GPX; blue shows the 166.92-mile standard and 166.39-mile Sherman-variant Valhalla routes.

![GPX-backed hybrid compared with Valhalla and the reference GPX](hybrid-comparison.png)

Green is the 104.01-mile hybrid, blue is the standard Valhalla route, and red is the reference GPX.

### Standard-route legs

| Leg | Valhalla | GPX | Hybrid | Hybrid source |
|---|---:|---:|---:|---|
| Start (Blank Gulch) → Mount Shavano | 4.78 | 4.24 | 4.78 | Valhalla |
| Mount Shavano → Tabeguache Peak | 0.92 | 1.01 | 0.92 | Valhalla |
| Tabeguache Peak → Mount Antero | 17.87 | 4.62 | 4.62 | GPX-backed |
| Mount Antero → Mount Princeton | 21.62 | 10.87 | 10.88 | GPX-backed |
| Mount Princeton → Mount Yale | 20.23 | 14.94 | 14.94 | GPX-backed |
| Mount Yale → Mount Columbia | 12.36 | 6.50 | 6.50 | GPX-backed |
| Mount Columbia → Mount Harvard | 2.47 | 3.10 | 2.47 | Valhalla |
| Mount Harvard → Mount Oxford | 24.29 | 4.74 | 4.74 | GPX-backed |
| Mount Oxford → Mount Belford | 1.42 | 1.59 | 1.42 | Valhalla |
| Mount Belford → Missouri Mountain | 3.34 | 2.23 | 2.23 | GPX-backed |
| Missouri Mountain → Huron Peak | 12.69 | 5.57 | 5.57 | GPX-backed |
| Huron Peak → La Plata Peak | 10.95 | 12.22 | 10.95 | Valhalla |
| La Plata Peak → Mount Elbert | 13.88 | 13.11 | 13.88 | Valhalla |
| Mount Elbert → Mount Massive | 11.34 | 9.08 | 11.34 | Valhalla |
| Mount Massive → End (Fish Hatchery) | 8.75 | 7.00 | 8.75 | Valhalla |

All distances are miles. GPX leg distances include GPS noise and describe one public route line, not the only valid Nolan's line.

### Snapping and geometry

Valhalla snapped every input to a pedestrian edge, but several summits are far from the nearest routable edge. Mount Oxford's nearest reported snap is 3,139.8 meters away; Mount Yale is 2,786.3 meters and Mount Princeton is 2,343.7 meters. The two supplied trailheads snap within 25 meters.

The returned shapes begin and end at the input coordinates and include straight off-network connectors to snapped edges. Consequently, a successful response is not proof that a continuous mapped trail exists. Snap distances and path shape must be part of any production coverage report.

These connectors are included in Valhalla's reported distance. On the checked Columbia-to-Harvard leg, the decoded geometry measures 2.471967 miles and the summary reports 2.474700 miles, a rounding-level difference. Its shorter distance than the GPX represents a different, more direct line, not omitted connector mileage.

## Verdict and next step

**Valhalla is a suitable routing API, but unmodified OSM is not a valid Nolan's distance matrix.** Using the stock matrix in CP-SAT would prove optimality for large detours, not for the Nolan's route. The GPX-backed hybrid reduces the gap to 3.19 miles, but it is anchored to one known line and does not establish a general distance provider for arbitrary peak lists.

The next POC should map-match the reference GPX with `trace_attributes` to distinguish absent ways from ways excluded by access or difficulty tags. That would split the current whole-leg GPX alternatives into granular mapped and off-trail segments suitable for a reviewed private OSM overlay. Until then, do not integrate the hybrid matrix into the general optimizer or label its output trail-optimal.

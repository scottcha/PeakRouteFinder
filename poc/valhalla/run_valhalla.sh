#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${1:-/tmp/peakroutefinder-valhalla/custom_files}"
PBF="$DATA_DIR/colorado-261124.osm.pbf"
PBF_URL="https://download.geofabrik.de/north-america/us/colorado/colorado-261124.osm.pbf"
PBF_SHA256="90e8c15e77665205f8090fd8dd3aae0a13bc97d961819e7b41d291a1d6541347"
IMAGE="ghcr.io/valhalla/valhalla-scripted@sha256:d438516425e785442562852d2f38d048478b6895bb15850491b81332f85bc4be"
PORT="${VALHALLA_PORT:-18002}"
THREADS="${VALHALLA_THREADS:-16}"

mkdir -p "$DATA_DIR"
if [[ ! -f "$PBF" ]]; then
    curl -fL "$PBF_URL" -o "$PBF"
fi
printf '%s  %s\n' "$PBF_SHA256" "$PBF" | sha256sum --check

docker run --rm \
    --name peakroutefinder-valhalla-poc \
    --publish "127.0.0.1:$PORT:8002" \
    --volume "$DATA_DIR:/custom_files" \
    --env server_threads="$THREADS" \
    --env build_admins=False \
    --env build_time_zones=False \
    --env use_default_speeds_config=False \
    "$IMAGE"

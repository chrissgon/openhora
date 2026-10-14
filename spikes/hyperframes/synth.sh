#!/bin/sh
# Builds the project for a case and renders it. Usage: synth.sh CASE_DIR WORK_DIR CAPTION [render args...]
# CASE_DIR holds edl.json, beats.json and recording.*; WORK_DIR receives project/ and out/.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd)
CASE=$1; WORK=$2; CAP=$3; shift 3
REC=${REC:-$(ls "$CASE"/recording.* | head -1)}
rm -rf "${WORK:?}/project"; mkdir -p "$WORK/out" "$WORK/project/media"; : > "$WORK/project/media/source.mov"
sh "$HERE/run.sh" -m "$ROOT/providers/renderer:/renderer:ro" -m "$ROOT/shared/references/video-presets.json:/data/video-presets.json:ro" \
  -m "$ROOT/shared/references/platforms/instagram.json:/data/instagram.json:ro" -m "$HERE/adapter:/adapter:ro" -m "$WORK:/work:rw" -m "$CASE:/case:ro" -- \
  python3 -I /opt/adapter/hf_adapter.py --renderer-src /renderer --edl /case/edl.json --beats /case/beats.json --vocabulary /data/video-presets.json \
  --platform-file /data/instagram.json --registry /opt/hf-registry --gsap /opt/hf/node_modules/gsap/dist/gsap.min.js --out /work/project --caption "$CAP"
: > "$WORK/project/media/source.mov"

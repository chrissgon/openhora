#!/bin/sh
# Renders WORK/project to WORK/out/NAME.mp4 in the limited container and records wall time and peak memory (cgroup memory.peak) in WORK/out/NAME.stats.
# Usage: render.sh WORK NAME RECORDING [extra hyperframes render args]
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$1; NAME=$2; REC=$3; shift 3
sh "$HERE/run.sh" -m "$WORK:/work:rw" -m "$REC:/work/project/media/source.mov:ro" -- sh -c '
  cd /work/project; t0=$(date +%s.%N)
  hyperframes render --output "/work/out/'"$NAME"'.mp4" --workers "${HF_WORKERS:-4}" --frames-cache-dir off '"$*"' > /work/out/'"$NAME"'.log 2>&1; rc=$?
  t1=$(date +%s.%N)
  printf "{\"exit\": %s, \"wall_seconds\": %s, \"memory_peak_bytes\": %s}\n" "$rc" "$(echo "$t1 - $t0" | bc -l 2>/dev/null || python3 -c "print(round($t1-$t0,2))")" "$(cat /sys/fs/cgroup/memory.peak 2>/dev/null || echo null)" > /work/out/'"$NAME"'.stats
  exit $rc'

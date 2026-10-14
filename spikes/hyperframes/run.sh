#!/bin/sh
# Runs a command in the spike image with the same class of limits as providers/renderer (_docker.container_argv): no network, read-only root,
# every capability dropped, no-new-privileges, a non-root user, pids/memory/cpu limits, an init, scratch in memory.
# Usage: run.sh [-m HOST:CONTAINER:ro|rw]... -- command...   (extra mounts only; nothing is mounted unless named)
# Env: HF_IMAGE (default hf-spike:local), HF_CPUS (8), HF_MEMORY (12g), HF_TMPFS (6g), HF_NAME (container name)
set -eu
IMAGE=${HF_IMAGE:-hf-spike:local}
MOUNTS=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    -m) MOUNTS="$MOUNTS -v $2"; shift 2 ;;
    --) shift; break ;;
    *) echo "usage: run.sh [-m host:ctr:mode]... -- cmd..." >&2; exit 2 ;;
  esac
done
# shellcheck disable=SC2086
exec docker run --rm --init --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 10001:10001 --cpus "${HF_CPUS:-8}" --memory "${HF_MEMORY:-12g}" --memory-swap "${HF_MEMORY:-12g}" --pids-limit 1024 \
  --shm-size 512m --tmpfs "/tmp:rw,nosuid,nodev,size=${HF_TMPFS:-6g}" --tmpfs "/scratch:rw,nosuid,nodev,size=${HF_SCRATCH:-1g}" \
  ${HF_NAME:+--name "$HF_NAME"} $MOUNTS "$IMAGE" "$@"

#!/bin/sh
# Builds the spike image. The network is used only here. Usage: spikes/hyperframes/build.sh [tag]
# The browser pin comes from providers/renderer/browser-pin.json (the architecture of the Docker daemon).
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
TAG=${1:-hf-spike:local}
ARCH=$(docker info --format '{{.Architecture}}')
case "$ARCH" in aarch64|arm64) KEY=linux-arm64 ;; x86_64|amd64) KEY=linux64 ;; *) echo "unknown architecture $ARCH" >&2; exit 1 ;; esac
pin() { python3 -I -c 'import json,sys; pin=json.load(open(sys.argv[1])); p=pin["platforms"][sys.argv[2]]; print({"version": pin["version"]}.get(sys.argv[3]) or p[sys.argv[3]])' "$ROOT/providers/renderer/browser-pin.json" "$KEY" "$1"; }
CHROME_VERSION=$(pin version); CHROME_URL=$(pin url); CHROME_SIZE=$(pin size); CHROME_MD5=$(pin md5); CHROME_SHA256=$(pin sha256); CHROME_BINARY=$(pin binary)
docker build --progress=plain -t "$TAG" \
  --build-context renderer="$ROOT/providers/renderer" \
  --build-arg CHROME_VERSION="$CHROME_VERSION" --build-arg CHROME_URL="$CHROME_URL" --build-arg CHROME_SIZE="$CHROME_SIZE" \
  --build-arg CHROME_MD5="$CHROME_MD5" --build-arg CHROME_SHA256="$CHROME_SHA256" --build-arg CHROME_BINARY="$CHROME_BINARY" \
  "$HERE"
docker image inspect "$TAG" --format 'image id: {{.Id}}'

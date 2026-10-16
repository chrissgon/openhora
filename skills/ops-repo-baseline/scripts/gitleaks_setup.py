#!/usr/bin/env python3
"""Install the pinned gitleaks binary next to the project's secret scanner, after checking its checksum.

Usage:
  python3 gitleaks_setup.py [--dest DIR] [--platform linux-x64|linux-arm64|darwin-x64|darwin-arm64]
                            [--archive FILE] [--print-pin]

  (no flag)     detect the platform, download the pinned release archive from the project's official
                GitHub releases page, check its sha256 against the pin below, and only then write the
                `gitleaks` binary and a `gitleaks.version` file into DEST (default: the `bin` folder
                next to this script). Nothing is written when the checksum differs.
  --archive F   use the archive F instead of downloading it; it is checked against the same pin.
  --print-pin   print the pinned version, source URLs and checksums as JSON; no network, no write.

The pin below is the one source for this script; references/gitleaks.md records where it was read and
how to update it, and the tests of this skill check that this script, the workflow asset and the hook
asset name the same version and checksum. The pre-commit hook never downloads: the person runs this
script once per clone.
Exit codes: 0 installed (or pin printed), 1 an error (download failed, checksum differs, no pinned archive
for this machine), 2 usage error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tarfile
import tempfile
import urllib.request

# Read from https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1 (the release's checksums file,
# gitleaks_8.30.1_checksums.txt) on 2026-10-15.
VERSION = "8.30.1"
SHA256 = {
    "linux-x64": "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
    "linux-arm64": "e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080",
    "darwin-x64": "dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709",
    "darwin-arm64": "b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5",
}
RELEASE_URL = "https://github.com/gitleaks/gitleaks/releases/download/v{version}/gitleaks_{version}_{platform}.tar.gz"
MAX_BYTES = 64 * 1024 * 1024  # an archive is about 8 MB; refuse anything far larger
TIMEOUT_SECONDS = 120


def archive_url(plat: str) -> str:
    return RELEASE_URL.format(version=VERSION, platform=plat.replace("-", "_"))


def detect_platform() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
    plat = f"{system}-{arch}" if arch else ""
    if plat not in SHA256:
        raise SystemExit(f"error: no pinned gitleaks archive for {system}/{machine}; pass --platform with one of {', '.join(SHA256)}")
    return plat


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, out_path: str) -> None:
    """Fetch the pinned https URL to out_path, refusing anything larger than MAX_BYTES."""
    if not url.startswith("https://github.com/gitleaks/gitleaks/releases/download/"):
        raise SystemExit("error: refusing to download from a URL outside the gitleaks releases page")
    size = 0
    with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response, open(out_path, "wb") as out:  # noqa: S310
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise SystemExit("error: the download is larger than expected; stopped")
            out.write(chunk)


def install(archive_path: str, plat: str, dest: str) -> None:
    """Check the archive against the pin, then write only the `gitleaks` member into dest."""
    found = sha256_of(archive_path)
    if found != SHA256[plat]:
        raise SystemExit(f"error: sha256 of the archive is {found}, the pin for {plat} is {SHA256[plat]}; nothing was installed")
    os.makedirs(dest, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name == "gitleaks" and m.isfile()), None)
        if member is None:
            raise SystemExit("error: the archive has no file named gitleaks; nothing was installed")
        source = tar.extractfile(member)
        if source is None or member.size > 2 * MAX_BYTES:
            raise SystemExit("error: the gitleaks member cannot be read or is larger than expected; nothing was installed")
        target = os.path.join(dest, "gitleaks")
        temp = target + ".tmp"
        with source, open(temp, "wb") as out:
            out.write(source.read())
    os.chmod(temp, 0o755)
    os.replace(temp, target)
    with open(os.path.join(dest, "gitleaks.version"), "w", encoding="utf-8") as handle:
        handle.write(VERSION + "\n")


def pin() -> dict:
    return {"version": VERSION, "sha256": dict(SHA256), "urls": {p: archive_url(p) for p in SHA256}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the pinned gitleaks binary after checking its sha256.")
    parser.add_argument("--dest", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin"),
                        help="folder to write gitleaks and gitleaks.version into (default: bin next to this script)")
    parser.add_argument("--platform", choices=sorted(SHA256), help="default: detected from this machine")
    parser.add_argument("--archive", help="a local archive to install instead of downloading")
    parser.add_argument("--print-pin", action="store_true", help="print the pin as JSON and exit")
    args = parser.parse_args(argv)

    if args.print_pin:
        print(json.dumps(pin(), indent=2))
        return 0
    plat = args.platform or detect_platform()
    if args.archive:
        install(args.archive, plat, args.dest)
    else:
        with tempfile.TemporaryDirectory() as scratch:
            archive_path = os.path.join(scratch, "gitleaks.tar.gz")
            try:
                download(archive_url(plat), archive_path)
            except OSError as exc:
                print(f"error: download failed: {exc}", file=sys.stderr)
                return 1
            install(archive_path, plat, args.dest)
    print(f"gitleaks {VERSION} ({plat}) installed in {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Download the pinned Chrome for Testing archive and unpack it. Run by the image's build (providers/renderer/Dockerfile) as
`python3 -I _fetch_browser.py <url> <size> <md5> <sha256> <destination> <binary>`; also run by the tests against a loopback server.

The archive is read once, its size, md5 (the official bucket's own metadata) and sha256 (the maintainer's pin) must all equal the
pin, it is unpacked with no member outside the destination and no link, and the binary named must exist. Redirects are refused. Only
https from the official storage host is accepted, except that a test may set RENDERER_TEST=1 to use a loopback http server.
Exit 0 done, 1 refused (the reason is on stderr). Standard library only.
"""
from __future__ import annotations

import hashlib
import os
import stat
import sys
import urllib.parse
import urllib.request
import zipfile

OFFICIAL_PREFIX = "https://storage.googleapis.com/chrome-for-testing-public/"
MAX_UNPACKED = 2 * 1024 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def refuse(why: str):
    print("refused: %s" % why, file=sys.stderr)
    raise SystemExit(1)


def fetch(url: str, size: int, md5: str, sha256: str, dest: str, binary: str, archive: str) -> None:
    parts = urllib.parse.urlsplit(url)
    test = os.environ.get("RENDERER_TEST") == "1" and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")
    if not (url.startswith(OFFICIAL_PREFIX) or test):
        refuse("url_not_allowed")
    if not (sha256 and md5 and size):
        refuse("pin_incomplete")
    h5, h2, total = hashlib.md5(usedforsecurity=False), hashlib.sha256(), 0
    try:
        with urllib.request.build_opener(NoRedirect).open(url, timeout=120) as resp, open(archive, "wb") as out:
            for block in iter(lambda: resp.read(1 << 20), b""):
                total += len(block)
                if total > size:
                    refuse("size_differs_from_pin")
                h5.update(block)
                h2.update(block)
                out.write(block)
    except SystemExit:
        raise
    except (OSError, ValueError):
        refuse("download_failed")
    if total != size:
        refuse("size_differs_from_pin")
    if h5.hexdigest() != md5:
        refuse("md5_differs_from_pin")
    if h2.hexdigest() != sha256:
        refuse("sha256_differs_from_pin")
    os.makedirs(dest, exist_ok=True)
    unpacked = 0
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                name = info.filename
                mode = (info.external_attr >> 16) & 0o170000
                if name.startswith("/") or ".." in name.split("/") or "\\" in name or mode == stat.S_IFLNK:
                    refuse("archive_member")
                unpacked += info.file_size
                if unpacked > MAX_UNPACKED:
                    refuse("archive_too_large")
                target = os.path.join(dest, name)
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    while True:
                        block = src.read(1 << 20)
                        if not block:
                            break
                        dst.write(block)
                os.chmod(target, 0o755 if (info.external_attr >> 16) & 0o111 else 0o644)
    except zipfile.BadZipFile:
        refuse("archive_unreadable")
    finally:
        os.unlink(archive)
    if not os.path.isfile(os.path.join(dest, binary)):
        refuse("binary_missing")


def main(argv) -> int:
    if len(argv) != 7 or not argv[2].isdigit():
        print("usage: _fetch_browser.py <url> <size> <md5> <sha256> <destination> <binary>", file=sys.stderr)
        return 2
    url, size, md5, sha256, dest, binary = argv[1], int(argv[2]), argv[3], argv[4], argv[5], argv[6]
    fetch(url, size, md5, sha256, dest, binary, os.path.join(os.environ.get("TMPDIR", "/tmp"), "chrome.zip"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

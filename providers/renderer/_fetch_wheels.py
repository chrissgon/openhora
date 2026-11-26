"""Unpack the pinned wheels (wheel-pin.json) into the renderer image's site folder at build, never with pip. Run by the image's build
(providers/renderer/Dockerfile) as `python3 -I _fetch_wheels.py <wheel-pin.json>`; the tests call `wheels` with a seam in place of the network.

This is a copy of the logic of providers/fetcher/_fetch_tool.py (`check_url`, `open_once`, `fetch_file`, `pin_missing`, `site_folder`,
`check_members`, `unpack` and `wheels`), which is its model, not of the file: the fetcher image is not touched (its tag must not change). One
addition: before anything is written, every member's sha256 is compared with the wheel's own `.dist-info/RECORD`, and a member that RECORD does
not list is refused.

Each file is downloaded from a host of the pin's `download_hosts` (zero redirects, or one to a host of `redirect_hosts`; an empty list allows none),
its size and sha256 must equal the pin, and it is unpacked by the zipfile module after every member is checked: no member outside the wheel's own
folders, no link, no `..`, no absolute name. Only the wheels of the daemon's architecture are fetched. Exit 0 done, 1 refused (the reason is on
stderr). Standard library only.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
import platform
import shutil
import site
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REDIRECTS = (301, 302, 303, 307, 308)
MAX_URL = 2048
SITE_PREFIX = "/usr/local/lib/"
MACHINES = {"x86_64": "amd64", "aarch64": "arm64"}
WHEEL_FIELDS = ("name", "version", "arch", "filename", "url", "size", "sha256")
MAX_MEMBERS, MAX_UNPACKED = 2000, 512 * 1024 * 1024
RECORD_FILES = ("RECORD", "RECORD.jws", "RECORD.p7s")
# A top-level folder a wheel of the pin may hold besides its own name, dist-info and .libs: the import name of a package whose distribution is named otherwise
# (read from the real wheel: opencv_python_headless holds `cv2/`). Exact names, never a pattern.
EXTRA_TOP = {"opencv_python_headless": ("cv2",)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def refuse(why: str):
    print("refused: %s" % why, file=sys.stderr)
    raise SystemExit(1)


def check_url(url: str, hosts) -> urllib.parse.SplitResult:
    """The parts of an https url with no user info whose host is one of `hosts` (lowercased, exact)."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL or any(ord(c) < 33 or ord(c) > 126 for c in url):
        refuse("url_not_allowed")
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        refuse("url_not_allowed")
    if parts.hostname.lower() not in hosts:
        refuse("redirect_host_not_allowed")
    return parts


def open_once(url: str):
    """(response, None) or (None, the Location of a redirect). Any other HTTP status is a refusal."""
    try:
        return urllib.request.build_opener(NoRedirect).open(url, timeout=120), None
    except urllib.error.HTTPError as e:
        if e.code in REDIRECTS and e.headers.get("Location"):
            return None, urllib.parse.urljoin(url, e.headers["Location"])
        refuse("download_failed")
    except (OSError, ValueError):
        refuse("download_failed")


def fetch_file(url: str, size: int, sha256: str, url_hosts, redirect_hosts, dest: str) -> None:
    """Download `url` to `dest`: its host must be one of `url_hosts`; zero redirects, or one to https on a host of `redirect_hosts`."""
    if not (url and size and sha256 and url_hosts):
        refuse("pin_incomplete")
    check_url(url, {h.lower() for h in url_hosts})
    resp, location = open_once(url)
    if location is not None:
        check_url(location, {h.lower() for h in redirect_hosts})
        resp, again = open_once(location)
        if again is not None:
            refuse("second_redirect")
    digest, total = hashlib.sha256(), 0
    try:
        with resp, open(dest, "wb") as out:
            for block in iter(lambda: resp.read(1 << 20), b""):
                total += len(block)
                if total > size:
                    refuse("size_differs_from_pin")
                digest.update(block)
                out.write(block)
    except (OSError, ValueError):
        refuse("download_failed")
    if total != size:
        refuse("size_differs_from_pin")
    if digest.hexdigest() != sha256:
        refuse("sha256_differs_from_pin")


def pin_missing(pin) -> bool:
    """True when the pin is not filled: a missing field, an empty value or a size of 0 in any wheel."""
    if not isinstance(pin, dict) or not pin.get("read_on") or not pin.get("download_hosts") or not isinstance(pin.get("redirect_hosts"), list):
        return True
    wheels_ = pin.get("wheels")
    if not isinstance(wheels_, list) or not wheels_:
        return True
    return any(not isinstance(w, dict) or any(w.get(k) in (None, "", 0) for k in WHEEL_FIELDS) for w in wheels_)


def site_folder() -> str:
    for folder in site.getsitepackages():
        if folder.startswith(SITE_PREFIX):
            return folder
    refuse("no_site_folder")


def check_members(info: zipfile.ZipInfo, entry: dict) -> None:
    """A member is a file of the wheel's own package folder (or the one EXTRA_TOP names), its dist-info or its `.libs`: no absolute or backslash name, no `..`, no link, no `.data`."""
    name = info.filename
    if not name or name.startswith("/") or "\\" in name or "\0" in name or ".." in name.split("/"):
        refuse("wheel_member_refused")
    if stat.S_ISLNK(info.external_attr >> 16):
        refuse("wheel_member_refused")
    top = name.split("/", 1)[0]
    dist = "%s-%s" % (entry["name"], entry["version"])
    if top.endswith(".data") or top not in (entry["name"], dist + ".dist-info", entry["name"] + ".libs") + EXTRA_TOP.get(entry["name"], ()):
        refuse("wheel_member_refused")


def record_hashes(z: zipfile.ZipFile, infos, entry: dict) -> dict:
    """{member name: sha256 hex} of the wheel's `.dist-info/RECORD` (rows with a sha256 only)."""
    name = "%s-%s.dist-info/RECORD" % (entry["name"], entry["version"])
    if name not in {i.filename for i in infos}:
        refuse("wheel_record_missing")
    rows = {}
    try:
        text = z.read(name).decode("utf-8")
        for row in csv.reader(io.StringIO(text)):
            if len(row) >= 2 and row[1].startswith("sha256="):
                raw = base64.urlsafe_b64decode(row[1][7:] + "=" * (-len(row[1][7:]) % 4))
                rows[row[0]] = raw.hex()
    except (UnicodeDecodeError, ValueError, csv.Error):
        refuse("wheel_record_invalid")
    return rows


def check_record(z: zipfile.ZipFile, infos, entry: dict) -> None:
    """Every member (but RECORD and its signatures) is listed in RECORD with a sha256, and the bytes equal it. Nothing is written by this."""
    rows = record_hashes(z, infos, entry)
    for info in infos:
        if info.is_dir() or info.filename.rsplit("/", 1)[-1] in RECORD_FILES and ".dist-info/" in info.filename:
            continue
        want = rows.get(info.filename)
        if want is None:
            refuse("wheel_record_mismatch")
        digest = hashlib.sha256()
        with z.open(info) as src:
            for block in iter(lambda: src.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != want:
            refuse("wheel_record_mismatch")


def unpack(path: str, entry: dict, dest: str) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_UNPACKED:
                refuse("wheel_too_large")
            for info in infos:
                check_members(info, entry)
            check_record(z, infos, entry)
            for info in infos:
                target = os.path.join(dest, *info.filename.split("/"))
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    os.chmod(target, 0o755)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
                os.chmod(target, 0o644)
            tops = {i.filename.split("/", 1)[0] for i in infos}
    except (OSError, zipfile.BadZipFile, ValueError):
        refuse("wheel_member_refused")
    for top in tops:
        base = os.path.join(dest, top)
        if os.path.isdir(base):
            os.chmod(base, 0o755)
            for root, dirs, files in os.walk(base):
                for d in dirs:
                    os.chmod(os.path.join(root, d), 0o755)
                for f in files:
                    os.chmod(os.path.join(root, f), 0o644)


def wheels(pin_path: str, dest=None) -> None:
    """Fetch and unpack the pinned wheels of this machine's architecture into `dest` (the image's site folder by default)."""
    try:
        with open(pin_path, encoding="utf-8") as f:
            pin = json.load(f)
    except (OSError, ValueError):
        refuse("pin_incomplete")
    if pin_missing(pin):
        refuse("pin_incomplete")
    arch = MACHINES.get(platform.machine())
    chosen = [w for w in pin["wheels"] if w["arch"] in (arch, "any")] if arch else []
    if not arch or {w["name"] for w in pin["wheels"]} - {w["name"] for w in chosen}:
        refuse("machine_not_pinned")
    dest = dest or site_folder()
    work = tempfile.mkdtemp(prefix="wheels-")
    try:
        for entry in chosen:
            if not isinstance(entry["size"], int) or isinstance(entry["size"], bool):
                refuse("pin_incomplete")
            part = os.path.join(work, "wheel.whl")
            fetch_file(entry["url"], entry["size"], entry["sha256"], pin["download_hosts"], pin["redirect_hosts"], part)
            unpack(part, entry, dest)
            os.unlink(part)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv) -> int:
    if len(argv) != 2:
        print("usage: _fetch_wheels.py <wheel-pin.json>", file=sys.stderr)
        return 2
    wheels(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""Download the pinned tool file. Run by the image's build (providers/fetcher/Dockerfile) as
`python3 -I _fetch_tool.py <url> <size> <sha256> <redirect-hosts> <destination>`; also run by the tests against a loopback server.

The file is read once; its size and sha256 must equal the pin. Only https is accepted (a test may set FETCHER_TEST=1 to use a loopback
http server). Exactly one redirect is followed, only to https on a host of <redirect-hosts> (a comma-separated list of exact names);
a second redirect, or a redirect to any other host or scheme, is refused. The file is written mode 0555. Unlike the renderer's
browser download, which refuses every redirect, a release download of this tool redirects once to the host of its storage.
Exit 0 done, 1 refused (the reason is on stderr), 2 usage. Standard library only.

A second form, `python3 -I _fetch_tool.py wheels <wheel-pin.json>`, unpacks the pinned wheels (wheel-pin.json) into the image's site folder,
never with pip: each file is downloaded from a host of `download_hosts` (zero redirects, or one to a host of `redirect_hosts`; an empty list
allows none), its size and sha256 must equal the pin, and it is unpacked by the zipfile module after every member is checked.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
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


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def refuse(why: str):
    print("refused: %s" % why, file=sys.stderr)
    raise SystemExit(1)


def loopback_test(parts) -> bool:
    return os.environ.get("FETCHER_TEST") == "1" and parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost")


def check_url(url: str, hosts=None) -> urllib.parse.SplitResult:
    """The parts of an https url with no user info; with `hosts`, its host must be one of them (lowercased, exact)."""
    if not isinstance(url, str) or not url or len(url) > MAX_URL or any(ord(c) < 33 or ord(c) > 126 for c in url):
        refuse("url_not_allowed")
    parts = urllib.parse.urlsplit(url)
    if not (parts.scheme == "https" or loopback_test(parts)) or not parts.hostname or "@" in parts.netloc:
        refuse("url_not_allowed")
    if hosts is not None and parts.hostname.lower() not in hosts:
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


def fetch(url: str, size: int, sha256: str, redirect_hosts, dest: str) -> None:
    if not (sha256 and size and redirect_hosts):
        refuse("pin_incomplete")
    check_url(url)
    hosts = {h.lower() for h in redirect_hosts}
    resp, location = open_once(url)
    if location is not None:
        check_url(location, hosts)
        resp, again = open_once(location)
        if again is not None:
            refuse("second_redirect")
    digest, total = hashlib.sha256(), 0
    tmp = dest + ".part"
    try:
        with resp, open(tmp, "wb") as out:
            for block in iter(lambda: resp.read(1 << 20), b""):
                total += len(block)
                if total > size:
                    refuse("size_differs_from_pin")
                digest.update(block)
                out.write(block)
        if total != size:
            refuse("size_differs_from_pin")
        if digest.hexdigest() != sha256:
            refuse("sha256_differs_from_pin")
        os.chmod(tmp, 0o555)
        os.replace(tmp, dest)
    except (OSError, ValueError):
        refuse("download_failed")
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --- the wheels ----------------------------------------------------------------------------------------------------------------------------

SITE_PREFIX = "/usr/local/lib/"
MACHINES = {"x86_64": "amd64", "aarch64": "arm64"}
WHEEL_FIELDS = ("name", "version", "arch", "filename", "url", "size", "sha256")
MAX_MEMBERS, MAX_UNPACKED = 2000, 256 * 1024 * 1024
# A top-level name a wheel of the pin may hold besides its own folder, dist-info and .libs: the C module of a package that ships it beside its folder.
EXTRA_TOP = {"cffi": re.compile(r"_cffi_backend(\..*)?")}


def fetch_file(url: str, size: int, sha256: str, url_hosts, redirect_hosts, dest: str) -> None:
    """Like `fetch`, for a wheel: the url's host must be one of `url_hosts`; zero redirects, or one to https on a host of `redirect_hosts`."""
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
    if not isinstance(pin, dict) or not pin.get("read_on") or not pin.get("download_hosts") or not isinstance(pin.get("redirect_hosts"), list):
        return True
    wheels = pin.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return True
    return any(not isinstance(w, dict) or any(w.get(k) in (None, "", 0) for k in WHEEL_FIELDS) for w in wheels)


def site_folder() -> str:
    for folder in site.getsitepackages():
        if folder.startswith(SITE_PREFIX):
            return folder
    refuse("no_site_folder")


def check_members(info: zipfile.ZipInfo, entry: dict) -> None:
    name = info.filename
    if not name or name.startswith("/") or "\\" in name or "\0" in name or ".." in name.split("/"):
        refuse("wheel_member_refused")
    if stat.S_ISLNK(info.external_attr >> 16):
        refuse("wheel_member_refused")
    top = name.split("/", 1)[0]
    dist = "%s-%s" % (entry["name"], entry["version"])
    extra = EXTRA_TOP.get(entry["name"])
    if top.endswith(".data") or not (top in (entry["name"], dist + ".dist-info", entry["name"] + ".libs") or (extra and extra.fullmatch(top))):
        refuse("wheel_member_refused")


def unpack(path: str, entry: dict, dest: str) -> None:
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > MAX_MEMBERS or sum(i.file_size for i in infos) > MAX_UNPACKED:
                refuse("wheel_too_large")
            for info in infos:
                check_members(info, entry)
            for info in infos:
                target = os.path.join(dest, *info.filename.split("/"))
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    os.chmod(target, 0o755)
                    continue
                folder = os.path.dirname(target)
                os.makedirs(folder, exist_ok=True)
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


def wheels(pin_path: str) -> None:
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
    dest = site_folder()
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
    if len(argv) == 3 and argv[1] == "wheels":
        wheels(argv[2])
        return 0
    if len(argv) != 6 or not argv[2].isdigit():
        print("usage: _fetch_tool.py <url> <size> <sha256> <redirect-hosts> <destination>", file=sys.stderr)
        return 2
    hosts = [h for h in argv[4].split(",") if h]
    fetch(argv[1], int(argv[2]), argv[3], hosts, argv[5])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

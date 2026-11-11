#!/usr/bin/env python3
"""The definition of the reference fetcher's image: its repository, the files it is built from and the hash that tags it.

The image is built only from the files image-manifest.json lists; the tag is the sha256 of exactly those files and of the effective
pin of the tool, so an edit to a host-only file (ytdlp.py, this file, the tests) never changes it. The committed pin is the
effective pin until a person's own raise exists (the pin routine, a later part). scripts/doctor.py loads this file by path to find the
images of earlier definitions: it imports nothing but the standard library.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE_REPOSITORY = "openhora-fetcher"
MANIFEST = "image-manifest.json"
PIN_FILE = "tool-pin.json"
WHEEL_PIN = "wheel-pin.json"   # the wheels unpacked into the image by _fetch_tool.py wheels (never by pip)
LOCAL_PIN = "pin.json"      # the person's own raise, under <state>/fetcher/
STATE_ENV, STATE_FOLDER = "OPENHORA_STATE_DIR", "fetcher"
VERSION = re.compile(r"[0-9]{4}\.[0-9]{2}\.[0-9]{2}(\.[0-9]{1,8})?")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_ASSET_BYTES = 64 * 1024 * 1024
LOCAL_PIN_BYTES = 8192
PIN_REQUIRED = ("version", "url", "size", "sha256")   # null in the committed pin until a person fills it from the release's metadata


def manifest(folder: str = HERE) -> dict:
    with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
        return json.load(f)


def definition_files(folder: str = HERE) -> list:
    """The manifest's files and every regular file under its folders, sorted, as paths relative to `folder`."""
    m = manifest(folder)
    out = list(m["files"])
    for sub in m["folders"]:
        for root, dirs, files in os.walk(os.path.join(folder, sub)):
            dirs.sort()
            out += [os.path.relpath(os.path.join(root, name), folder) for name in sorted(files) if not name.startswith(".")]
    return sorted(out)


def state_dir() -> str:
    chosen = os.environ.get(STATE_ENV)
    if chosen:
        return os.path.abspath(chosen)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg and os.path.isabs(xdg):
        return os.path.join(xdg, "openhora")
    return os.path.join(os.path.expanduser("~"), ".local", "state", "openhora")


def version_key(version):
    """The version as a tuple of numbers (`2026.10.26` or `2026.10.26.123456`), or None when it is not one: newer is greater."""
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        return None
    return tuple(int(part) for part in version.split("."))


def is_newer(candidate, than) -> bool:
    a, b = version_key(candidate), version_key(than)
    return a is not None and b is not None and a > b


def expected_url(committed: dict, version: str):
    """The download address of `version`: the committed one with its version replaced; None when the committed one does not carry its version."""
    url, current = committed.get("url"), committed.get("version")
    if not isinstance(url, str) or not isinstance(current, str) or current not in url or not VERSION.fullmatch(version):
        return None
    return url.replace(current, version)


def raise_problem(committed: dict, candidate) -> str:
    """Why `candidate` (a dict) is not a valid raise of the committed pin, or an empty string. The one check `pin-raise` writes by and
    `effective_pin` reads by: a newer version, the same tool, asset and redirect hosts, the download address of that version, a size
    and a sha256."""
    if not isinstance(candidate, dict):
        return "not an object"
    if not is_newer(candidate.get("version"), committed.get("version")):
        return "the version is not newer than the committed pin"
    for key in ("tool", "asset", "redirect_hosts"):
        if candidate.get(key) != committed.get(key):
            return "%s differs from the committed pin" % key
    if candidate.get("url") != expected_url(committed, candidate["version"]):
        return "the address is not the committed pin's, with the new version"
    size = candidate.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_ASSET_BYTES:
        return "the size is not a number in range"
    if not isinstance(candidate.get("sha256"), str) or not SHA256.fullmatch(candidate["sha256"]):
        return "the sha256 is absent or malformed"
    return ""


def committed_pin(folder: str = HERE) -> dict:
    with open(os.path.join(folder, PIN_FILE), encoding="utf-8") as f:
        return json.load(f)


def local_pin(committed: dict, state=None):
    """The person's own raise, or None: a regular file of this user, closed to others, small, valid against the committed pin."""
    path = os.path.join(state or state_dir(), STATE_FOLDER, LOCAL_PIN)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode) or found.st_uid != os.getuid() or found.st_mode & 0o077 or found.st_size > LOCAL_PIN_BYTES:
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            value = json.loads(f.read(LOCAL_PIN_BYTES + 1).decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)
    return value if raise_problem(committed, value) == "" else None


def effective_pin(folder: str = HERE) -> dict:
    """The pin the image is built from: the person's own raise when it is valid, else the committed one."""
    committed = committed_pin(folder)
    return local_pin(committed) or committed


def pin_missing(pin: dict) -> list:
    """The names of what is not filled in the pin: `version`, `url`, `size`, `sha256` null or empty, and an empty `redirect_hosts`."""
    missing = [key for key in PIN_REQUIRED if pin.get(key) in (None, "", 0)]
    if not pin.get("redirect_hosts"):
        missing.append("redirect_hosts")
    return missing


WHEEL_NAME = re.compile(r"[A-Za-z0-9_]{1,40}")
WHEEL_VERSION = re.compile(r"[0-9]{1,4}(\.[0-9]{1,4}){1,3}")
WHEEL_ARCHES = ("amd64", "arm64", "any")
WHEEL_MACHINE = {"amd64": "x86_64", "arm64": "aarch64"}
WHEEL_PYTHON_TAG = re.compile(r"cp3([0-9]{1,2})")
MANYLINUX = re.compile(r"manylinux_2_([0-9]{1,2})_([a-z0-9_]+)|manylinux2014_([a-z0-9_]+)")
MAX_WHEEL_BYTES = 64 * 1024 * 1024
WHEEL_HOST = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+")
WHEEL_FIELDS = ("name", "version", "arch", "filename", "url", "size", "sha256")


def wheel_pin(folder: str = HERE) -> dict:
    with open(os.path.join(folder, WHEEL_PIN), encoding="utf-8") as f:
        return json.load(f)


def wheel_pin_missing(pin: dict) -> list:
    """The names of what is not filled in the wheel pin (null, an empty string and 0 count as missing; `redirect_hosts` may be empty)."""
    missing = [key for key in ("read_on", "download_hosts") if pin.get(key) in (None, "", 0, [])]
    wheels = pin.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return missing + ["wheels"]
    for i, entry in enumerate(wheels):
        for key in WHEEL_FIELDS:
            if not isinstance(entry, dict) or entry.get(key) in (None, "", 0):
                missing.append("wheels[%d].%s" % (i, key))
    return missing


def wheel_tag_problem(entry: dict) -> str:
    name, version, arch, filename = entry["name"], entry["version"], entry["arch"], entry["filename"]
    prefix = "%s-%s-" % (name, version)
    if not isinstance(filename, str) or not filename.startswith(prefix) or not filename.endswith(".whl"):
        return "a file name does not start with its name and version or does not end in .whl"
    tags = filename[len(prefix):-len(".whl")].split("-")
    if len(tags) != 3:
        return "a file name does not carry exactly a python, an abi and a platform tag"
    python, abi, platform_tag = tags
    found = WHEEL_PYTHON_TAG.fullmatch(python)
    native = (found and abi == "abi3" and int(found.group(1)) <= 11) or (python == "cp311" and abi == "cp311")
    if not (native or (python == "py3" and abi == "none")):
        return "a file's python and abi tags are not abi3 (up to 3.11), cp311 or py3-none"
    if arch == "any":
        return "" if platform_tag == "any" else "a pure wheel (arch any) has a platform tag other than any"
    parts = platform_tag.split(".")
    if len(parts) > 2:
        return "a platform tag has more than two parts"
    seen = False
    for part in parts:
        m = MANYLINUX.fullmatch(part)
        if not m:
            return "a platform tag is not manylinux"
        if m.group(1) is not None:
            seen = True
            if int(m.group(1)) > 36 or m.group(2) != WHEEL_MACHINE[arch]:
                return "a platform tag is for another glibc or machine"
        elif m.group(3) != WHEEL_MACHINE[arch]:
            return "a platform tag is for another machine"
    return "" if seen else "a platform tag names no manylinux_2_<glibc> form"


def wheel_pin_problem(pin: dict) -> str:
    """Why a filled wheel pin is not valid, or an empty string. Names no value."""
    if not isinstance(pin, dict):
        return "not an object"
    hosts = pin.get("download_hosts")
    redirects = pin.get("redirect_hosts")
    if not isinstance(hosts, list) or not isinstance(redirects, list) or not all(isinstance(h, str) and WHEEL_HOST.fullmatch(h) for h in hosts + redirects):
        return "a host is not a plain lower-case name"
    wheels = pin.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        return "no wheels"
    arches = {}
    versions = {}
    for entry in wheels:
        if not isinstance(entry, dict) or set(entry) != set(WHEEL_FIELDS):
            return "a wheel entry has not exactly its fields"
        name, version = entry["name"], entry["version"]
        if not isinstance(name, str) or not WHEEL_NAME.fullmatch(name):
            return "a name is not of the allowed shape"
        if not isinstance(version, str) or not WHEEL_VERSION.fullmatch(version):
            return "a version is not of the allowed shape"
        if entry["arch"] not in WHEEL_ARCHES:
            return "an arch is not amd64, arm64 or any"
        problem = wheel_tag_problem(entry)
        if problem:
            return problem
        url = entry["url"]
        if not isinstance(url, str):
            return "an address is not text"
        host = url[len("https://"):].split("/", 1)[0] if url.startswith("https://") else ""
        if host not in hosts or not url.endswith("/" + entry["filename"]) or url.count("/") < 4 or any(ord(c) < 33 or ord(c) > 126 for c in url):
            return "an address is not https on a download host, ending in its file name"
        size = entry["size"]
        if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_WHEEL_BYTES:
            return "a size is not a number in range"
        if not isinstance(entry["sha256"], str) or not SHA256.fullmatch(entry["sha256"]):
            return "a sha256 is malformed"
        arches.setdefault(name, []).append(entry["arch"])
        if versions.setdefault(name, version) != version:
            return "a name has two versions"
    for name, found in arches.items():
        if sorted(found) not in (["any"], ["amd64", "arm64"]):
            return "a package is not one pure wheel or one wheel for each of amd64 and arm64"
    return ""


def definition_hash(folder: str = HERE) -> str:
    h = hashlib.sha256()
    for name in definition_files(folder):
        with open(os.path.join(folder, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    h.update(b"effective-pin\0" + json.dumps(effective_pin(folder), sort_keys=True).encode() + b"\0")
    return h.hexdigest()


def image_tag(folder: str = HERE) -> str:
    return "%s:%s" % (IMAGE_REPOSITORY, definition_hash(folder)[:12])

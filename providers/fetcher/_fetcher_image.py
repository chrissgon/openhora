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


def definition_hash(folder: str = HERE) -> str:
    h = hashlib.sha256()
    for name in definition_files(folder):
        with open(os.path.join(folder, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    h.update(b"effective-pin\0" + json.dumps(effective_pin(folder), sort_keys=True).encode() + b"\0")
    return h.hexdigest()


def image_tag(folder: str = HERE) -> str:
    return "%s:%s" % (IMAGE_REPOSITORY, definition_hash(folder)[:12])

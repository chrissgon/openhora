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

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE_REPOSITORY = "openhora-fetcher"
MANIFEST = "image-manifest.json"
PIN_FILE = "tool-pin.json"
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


def effective_pin(folder: str = HERE) -> dict:
    """The pin the image is built from: the committed one."""
    with open(os.path.join(folder, PIN_FILE), encoding="utf-8") as f:
        return json.load(f)


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

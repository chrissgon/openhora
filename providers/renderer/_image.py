#!/usr/bin/env python3
"""The definition of the ffmpeg engine's image: its repository, the files it is built from and the hash that tags it.

The image of renderer:video's ffmpeg engine is built only from the files image-manifest.json lists; the tag is the sha256 of exactly those
files, so an edit to a host-only file (ffmpeg.py, _docker.py, _browser.py, this file) never changes it. scripts/doctor.py loads this file
by path to find the images of earlier definitions: it imports nothing but the standard library.
"""
from __future__ import annotations

import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
IMAGE_REPOSITORY = "openhora-renderer"
MANIFEST = "image-manifest.json"


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


def definition_hash(folder: str = HERE) -> str:
    h = hashlib.sha256()
    for name in definition_files(folder):
        with open(os.path.join(folder, name), "rb") as f:
            h.update(name.encode() + b"\0" + f.read() + b"\0")
    return h.hexdigest()


def image_tag(folder: str = HERE) -> str:
    return "%s:%s" % (IMAGE_REPOSITORY, definition_hash(folder)[:12])

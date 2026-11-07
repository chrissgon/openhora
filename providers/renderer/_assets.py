"""The inputs both engines serve to a page: the allow-listed fonts (checked by hash) and the person's image assets (checked by their
header bytes), and the safe read every input goes through. No browser, no frames: the drawing engine (_frames) and the HyperFrames
engine both import this file. Standard library only.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
import struct

from _text import Refusal
from _vocab import HERE, SLOT_ID, read_json

FONT_MAGIC = {b"wOF2": ("woff2", "font/woff2"), b"wOFF": ("woff", "font/woff"), b"\x00\x01\x00\x00": ("ttf", "font/ttf"),
              b"OTTO": ("otf", "font/otf"), b"true": ("ttf", "font/ttf")}
FONT_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,47}")


def read_regular(path: str, max_bytes: int, code: str, field: str) -> bytes:
    """A regular file's bytes, opened with O_NOFOLLOW (a symlink is refused) and read through that descriptor."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0))
    except OSError:
        raise Refusal(code, field) from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > max_bytes:
            raise Refusal(code, field)
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(max_bytes + 1)
    finally:
        os.close(fd)
    if len(data) > max_bytes:
        raise Refusal(code, field)
    return data


# ---------------------------------------------------------------- fonts

def fonts_dir() -> str:
    """The allow-listed font folder. Another folder is honoured only in test mode (RENDERER_TEST=1)."""
    if os.environ.get("RENDERER_TEST") == "1" and os.environ.get("RENDERER_ASSETS_DIR"):
        return os.path.join(os.environ["RENDERER_ASSETS_DIR"], "fonts")
    return os.path.join(HERE, "assets", "fonts")


def font_allowlist(directory=None) -> dict:
    """{id: row} of the allow-list file: each row has id, file (a plain name), sha256, weight, licence and source."""
    directory = directory or fonts_dir()
    doc = read_json(os.path.join(directory, "allowlist.json"))
    rows = {}
    try:
        for row in doc["fonts"]:
            if not FONT_ID.fullmatch(row["id"]) or os.path.basename(row["file"]) != row["file"] or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) \
                    or not row.get("licence") or not row.get("source") or row["id"] == "default":
                raise Refusal("bad_font_allowlist", "allowlist.json")
            rows[row["id"]] = row
    except (KeyError, TypeError):
        raise Refusal("bad_font_allowlist", "allowlist.json") from None
    return rows


def load_fonts(theme_fonts: dict, allowlist: dict, max_bytes: int, directory=None) -> tuple:
    """Serve the fonts the theme names, each re-checked against its allow-listed sha256. Returns (serve, used) where
    used maps a role to the file name or to `system default`."""
    directory = directory or fonts_dir()
    serve, used = {}, {}
    for role, f in theme_fonts.items():
        if f["id"] == "default":
            used[role] = "system default"
            continue
        row = allowlist.get(f["id"])
        if row is None:
            raise Refusal("font_not_allowed", role)
        data = read_regular(os.path.join(directory, row["file"]), max_bytes, "font_unreadable", role)
        if hashlib.sha256(data).hexdigest() != row["sha256"] or data[:4] not in FONT_MAGIC:
            raise Refusal("font_hash", role)
        ext, mime = FONT_MAGIC[data[:4]]
        serve["/fonts/%s.%s" % (role, ext)] = (data, mime)
        used[role] = row["id"]
    return serve, used


# ---------------------------------------------------------------- assets

def image_facts(data: bytes):
    """('png'|'jpg', width, height) from the header bytes, or None when the bytes are neither. An animated PNG is None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        pos = 8
        while pos + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[pos:pos + 8])
            if kind == b"acTL":
                return None
            if kind == b"IDAT":
                break
            pos += 12 + length
        return "png", w, h
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker == 0xFF:
                i += 1
                continue
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpg", w, h
            i += 2 + length
    return None


def load_assets(items: dict, sha256s: dict, limits: dict) -> dict:
    """Image assets by slot id: {slot: {kind, width, height, data, sha256}}. Type by the header bytes (PNG or JPEG, never
    animated), dimensions bounded, size bounded, the hash checked against the one recorded at intake when given."""
    out = {}
    for slot, path in items.items():
        if not SLOT_ID.fullmatch(slot):
            raise Refusal("bad_slot", slot[:32])
        data = read_regular(path, limits["asset_max_bytes"], "asset_unreadable", slot)
        facts = image_facts(data)
        if facts is None:
            raise Refusal("asset_type", slot)
        kind, w, h = facts
        if not (1 <= w <= limits["asset_max_side"] and 1 <= h <= limits["asset_max_side"]) or w * h > limits["asset_max_pixels"]:
            raise Refusal("asset_dimensions", slot)
        digest = hashlib.sha256(data).hexdigest()
        if sha256s.get(slot) and sha256s[slot] != digest:
            raise Refusal("asset_hash", slot)
        out[slot] = {"kind": kind, "width": w, "height": h, "data": data, "sha256": digest}
    return out

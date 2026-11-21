"""The `asset-sheet` verb, inside the common image (package V9b-2): the pictures a person may pick from, checked and tiled, and, once one is picked,
normalised into the one form both engines draw. No browser, no network, no recording; the only program is the image's pinned ffmpeg, run with one
thread and bit-exact scaling and encoding, so the same bytes come out at any core count. Standard library only; imports only common modules.

Two modes:

  preview  `--asset ROW:COL=FILE` are small pictures (a source's own previews): each is checked (a PNG or a JPEG, complete, not animated, within the
           size bounds) and tiled onto the contact sheet. A tile that has no picture is the theme's background. Nothing but the sheet is written.
  full     each picture is checked the same way and re-encoded to PNG, its metadata stripped, its long side scaled to LONG_SIDE (the long side of the
           frame, so the picture covers the frame's height) and never enlarged more than MAX_UPSCALE times (`asset_too_small`). The file is written
           as `asset-<sha12>.png` (mode 0400), named by its own bytes, and tiled.

A clip is refused (`asset_type`): the verb draws images only until a later package adds the clip path. The answer (rebuilt by the host from a closed
schema) is {"assets": [{row, col, file, sha256, width, height, source_sha256}], "sheet": "sheet.png", "sheet_sha256", "rows": [...]}, the assets in
(row, col) order and the rows sorted. In `preview` mode `file` is null and `sha256` is the input's own.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import tempfile
import zlib

import _assets
import _media
from _text import Refusal
from _vocab import SLOT_ID, load_data

MODES = ("preview", "full")
MAX_TILES = 36                 # the most pictures in one call: six rows of six
MAX_COL = 6
LONG_SIDE = 1920               # a normalised picture's long side: the frame's (1080x1920)
MAX_UPSCALE = 1.5              # a picture is never enlarged more than this (a smaller one is `asset_too_small`)
TILE = (180, 320)              # a picture's box on the sheet, a quarter of a frame's each side less a little
GAP = 8                        # pixels around a tile
SHEET_NAME = "sheet.png"
ASSET_NAME = "asset-%s.png"
FFMPEG_TIMEOUT = 600
FIELD_MAX = 32


def fail(code: str, field: str):
    raise Refusal(code, str(field)[:80])


# ---------------------------------------------------------------- the checks on one picture

def png_complete(data: bytes) -> bool:
    """True when the bytes are a PNG whose chunks all fit, each with a correct CRC, and whose last chunk is IEND at the very end of the file."""
    pos, size = 8, len(data)
    while pos + 12 <= size:
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        end = pos + 12 + length
        if end > size:
            return False
        if struct.unpack(">I", data[end - 4:end])[0] != zlib.crc32(data[pos + 4:end - 4]) & 0xFFFFFFFF:
            return False
        if kind == b"IEND":
            return end == size
        pos = end
    return False


def jpeg_complete(data: bytes) -> bool:
    """True when the bytes end with the end-of-image marker (trailing zero padding allowed)."""
    return data.rstrip(b"\x00")[-2:] == b"\xff\xd9"


def has_alpha(data: bytes, kind: str) -> bool:
    """A PNG whose colour type carries an alpha channel (4 or 6) or has a tRNS chunk keeps its alpha; nothing else does."""
    if kind != "png":
        return False
    if data[25] in (4, 6):
        return True
    pos = 8
    while pos + 12 <= len(data):
        length, name = struct.unpack(">I4s", data[pos:pos + 8])
        if name == b"tRNS":
            return True
        if name in (b"IDAT", b"IEND"):
            return False
        pos += 12 + length
    return False


def check_picture(path: str, field: str, limits: dict) -> dict:
    """{kind, width, height, data, sha256, alpha} of one input: a regular file (no link) within the size bound, a PNG or a JPEG by its header bytes (never
    animated: a GIF, a WebP, a clip and the rest are `asset_type`), complete (`asset_corrupt` for a truncated or damaged file), within the side and pixel
    bounds (`asset_dimensions`)."""
    data = _assets.read_regular(path, limits["asset_max_bytes"], "asset_unreadable", field)
    facts = _assets.image_facts(data)
    if facts is None:
        fail("asset_type", field)
    kind, w, h = facts
    if not (1 <= w <= limits["asset_max_side"] and 1 <= h <= limits["asset_max_side"]) or w * h > limits["asset_max_pixels"]:
        fail("asset_dimensions", field)
    if not (png_complete(data) if kind == "png" else jpeg_complete(data)):
        fail("asset_corrupt", field)
    return {"kind": kind, "width": w, "height": h, "data": data, "sha256": hashlib.sha256(data).hexdigest(), "alpha": has_alpha(data, kind)}


def target_size(w: int, h: int, field: str) -> tuple:
    """The size a picture is normalised to: its long side becomes LONG_SIDE and the aspect is kept (whole pixels, rounded half up). A picture whose long
    side would have to grow by more than MAX_UPSCALE is `asset_too_small`. Integer arithmetic only."""
    long_side = max(w, h)
    if long_side * 3 < LONG_SIDE * 2:
        fail("asset_too_small", field)
    return max(1, (w * LONG_SIDE + long_side // 2) // long_side), max(1, (h * LONG_SIDE + long_side // 2) // long_side)


# ---------------------------------------------------------------- ffmpeg

def base_argv(ffmpeg: str) -> list:
    one = str(_media.ENCODE_INPUT_THREADS)
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", one, "-filter_threads", one, "-filter_complex_threads", one]


def output_options(out: str) -> list:
    return ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-frames:v", "1", "-an", "-c:v", "png", "-compression_level", "9",
            "-f", "image2", "-update", "1", out]


def normalise_argv(ffmpeg: str, picture: dict, src: str, out: str, size: tuple) -> list:
    """The command that re-encodes one checked picture to a PNG of `size`, with no metadata (rgb, or rgba when the source has an alpha channel)."""
    pix = "rgba" if picture["alpha"] else "rgb24"
    graph = "scale=%d:%d:flags=%s,format=%s" % (size[0], size[1], _media.SWS, pix)
    return base_argv(ffmpeg) + ["-err_detect", "explode"] + _media.asset_input(picture["kind"], src) + ["-vf", graph] + output_options(out)


def cell_size() -> tuple:
    return TILE[0] + GAP, TILE[1] + GAP


def sheet_argv(ffmpeg: str, cells: list, columns: int, background: str, out: str) -> list:
    """The command that tiles `cells` (a list in row-major order of {kind, path} or None for an empty tile) into one PNG: each picture scaled to fit its
    tile, centred in a cell of the background colour; `columns` cells per row."""
    cw, ch = cell_size()
    color = "0x" + background.lstrip("#")
    argv, graph, labels = base_argv(ffmpeg), [], []
    index = 0
    for n, cell in enumerate(cells):
        if cell is None:
            graph.append("color=c=%s:s=%dx%d:r=1:d=1,format=rgb24[c%d]" % (color, cw, ch, n))
        else:
            argv += _media.asset_input(cell["kind"], cell["path"])
            graph.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease:flags=%s,format=rgb24,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s[c%d]"
                         % (index, TILE[0], TILE[1], _media.SWS, cw, ch, color, n))
            index += 1
        labels.append("[c%d]" % n)
    if len(cells) == 1:
        graph.append("[c0]null[sheet]")
    else:
        layout = "|".join("%d_%d" % ((n % columns) * cw, (n // columns) * ch) for n in range(len(cells)))
        graph.append("%sxstack=inputs=%d:layout=%s:fill=%s[sheet]" % ("".join(labels), len(cells), layout, color))
    return argv + ["-filter_complex", ";".join(graph), "-map", "[sheet]"] + output_options(out)


# ---------------------------------------------------------------- the verb

def parse_key(key: str) -> tuple:
    """('row', col) of a `ROW:COL` key: a row that is a slot id and a column from 1 to MAX_COL (`bad_slot` otherwise)."""
    row, sep, col = key.partition(":")
    if not sep or not SLOT_ID.fullmatch(row) or not col.isdigit() or not 1 <= int(col) <= MAX_COL or len(col) > 1:
        fail("bad_slot", key[:FIELD_MAX])
    return row, int(col)


def asset_sheet(*, items: dict, mode: str, out_dir: str, ffmpeg: str, data=None) -> dict:
    """Check every picture of `items` ({"ROW:COL": path}), normalise them in `full` mode and write the sheet. Everything is checked before anything is
    written; a refusal leaves no file. Returns the answer described in the module's text."""
    if mode not in MODES:
        fail("bad_mode", mode)
    data = data or load_data()
    if not items:
        fail("no_assets", "asset")
    if len(items) > MAX_TILES:
        fail("too_many_assets", "asset")
    keyed = {}
    for key, path in items.items():
        row, col = parse_key(key)
        if (row, col) in keyed:
            fail("asset_duplicate", key[:FIELD_MAX])
        keyed[(row, col)] = path
    pictures = {}
    for (row, col), path in sorted(keyed.items()):
        field = "%s:%d" % (row, col)
        pictures[(row, col)] = check_picture(path, field, data["limits"])
        if mode == "full":
            pictures[(row, col)]["size"] = target_size(pictures[(row, col)]["width"], pictures[(row, col)]["height"], field)
    rows = sorted({row for row, _ in keyed})
    columns = max(col for _, col in keyed)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".sheet-", dir=out_dir)
    try:
        sources = {}
        for (row, col), picture in pictures.items():
            src = os.path.join(work, "in-%s-%d.%s" % (row, col, picture["kind"]))
            fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(picture["data"])
            sources[(row, col)] = src
        assets, tiles, moves = [], {}, []
        for (row, col), picture in pictures.items():
            field = "%s:%d" % (row, col)
            if mode == "preview":
                assets.append({"row": row, "col": col, "file": None, "sha256": picture["sha256"], "width": picture["width"], "height": picture["height"],
                               "source_sha256": picture["sha256"]})
                tiles[(row, col)] = {"kind": picture["kind"], "path": sources[(row, col)]}
                continue
            made = os.path.join(work, "out-%s-%d.png" % (row, col))
            _media.run(normalise_argv(ffmpeg, picture, sources[(row, col)], made, picture["size"]), FFMPEG_TIMEOUT)
            with open(made, "rb") as fh:
                raw = fh.read()
            facts = _assets.image_facts(raw)
            if facts is None or facts[0] != "png" or max(facts[1], facts[2]) != LONG_SIDE or not png_complete(raw):
                fail("asset_unreadable", field)
            digest = hashlib.sha256(raw).hexdigest()
            name = ASSET_NAME % digest[:12]
            assets.append({"row": row, "col": col, "file": name, "sha256": digest, "width": facts[1], "height": facts[2], "source_sha256": picture["sha256"]})
            tiles[(row, col)] = {"kind": "png", "path": made}
            moves.append((made, os.path.join(out_dir, name)))
        cells = [tiles.get((row, col)) for row in rows for col in range(1, columns + 1)]
        sheet = os.path.join(work, SHEET_NAME)
        _media.run(sheet_argv(ffmpeg, cells, columns, data["theme"]["colors"]["bg"], sheet), FFMPEG_TIMEOUT)
        sheet_raw = _read(sheet)
        if _assets.image_facts(sheet_raw) is None or not png_complete(sheet_raw):
            fail("asset_unreadable", "sheet")
        for made, dest in moves:                                  # the same picture twice is the same name: written once
            if not os.path.exists(dest):
                shutil.copyfile(made, dest)
                os.chmod(dest, 0o400)
        final_sheet = os.path.join(out_dir, SHEET_NAME)
        shutil.copyfile(sheet, final_sheet)
        os.chmod(final_sheet, 0o400)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"ok": True, "assets": assets, "sheet": SHEET_NAME, "sheet_sha256": hashlib.sha256(sheet_raw).hexdigest(), "rows": rows}


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()

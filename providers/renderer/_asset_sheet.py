"""The `asset-sheet` verb, inside the common image (packages V9b-2 and V9b-5a): the pictures and clips a person may pick from, checked and tiled, and, once one
is picked, normalised into the one form both engines draw. No browser, no network, no recording; the only programs are the image's pinned ffmpeg and
ffprobe, run with one thread and bit-exact scaling and encoding, so the same bytes come out at any core count. Standard library only; imports only common modules.

Two modes:

  preview  `--asset ROW:COL=FILE` are small pictures or clips (a source's own previews): each is checked (a PNG or a JPEG, or a clip; complete, not animated,
           within the size bounds) and tiled onto the contact sheet. A clip's tile is its frame at 0.5 s (its first frame when it is shorter), with a small
           accent-coloured marker in the tile's corner. A tile that has no picture is the theme's background. Nothing but the sheet is written.
  full     each file is checked the same way and normalised. A picture is re-encoded to PNG, its metadata stripped, its long side scaled to LONG_SIDE (the long
           side of the frame, so the picture covers the frame's height) and never enlarged more than MAX_UPSCALE times (`asset_too_small`); it is written as
           `asset-<sha12>.png` (mode 0400), named by its own bytes. A clip is re-encoded to H.264 High, yuv420p, bt709 tagged, a constant `--fps` (24 to 60,
           30 by default), no audio, the first 10 seconds, its long side scaled to LONG_SIDE and never enlarged more than MAX_UPSCALE times, x264 on one thread,
           faststart, and written as `asset-<sha12>.mp4` (mode 0400).

A clip is told from a picture by its first bytes (an MP4 or MOV `ftyp` box, a WebM's EBML header), never by a name; it is read with that container's demuxer
forced and only the `file` protocol, its first video stream alone (no audio, subtitle or data stream, no metadata or chapter). Its codec must be h264, hevc,
vp8 or vp9, or av1 when the image's ffmpeg has a software decoder for it (read from `ffmpeg -decoders`, never assumed; with none, av1 is `asset_type`). A clip
over 7680x4320 is `asset_dimensions`, one that cannot be read is `asset_corrupt`. The answer (rebuilt by the host from a closed schema) is
{"assets": [{row, col, file, sha256, width, height, source_sha256, kind, seconds}], "sheet": "sheet.png", "sheet_sha256", "rows": [...]}, the assets in
(row, col) order and the rows sorted. `kind` is `image` or `clip`; `seconds` is 0 for an image and the clip's length (the first 10 seconds) otherwise. In
`preview` mode `file` is null and `sha256` is the input's own.
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
CLIP_NAME = "asset-%s." + _media.CLIP_EXT
CLIP_X264_CRF = 16             # a clip is read again by the render's own encode (crf 18): this one keeps what that one needs
CLIP_PREVIEW_SIDE = 640        # a clip's preview frame is cut to fit this box before it is tiled (a frame of 8K would be a hundred megabytes of PNG)
MARKER = (4, 4, 36, 22)        # a clip tile's marker: x, y, width, height from the cell's corner
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


def check_clip(path: str, data: bytes, demuxer: str, field: str, limits: dict, ffprobe, decoders) -> dict:
    """The facts of one clip input (a regular file within the byte cap, already read as `data`; `demuxer` told from its first bytes): {kind: "clip", demuxer,
    codec, decoder, width, height, seconds, color_space, data, sha256, alpha}. The file is probed with its demuxer forced (`_media.probe_clip`): its first video
    stream is the clip, whatever else the file holds is ignored (and dropped by the normaliser). `decoders` is the image's ffmpeg's decoder list: the codec must be one
    it can read (`asset_type`). The size is bounded to 7680x4320 and `asset_max_pixels` (`asset_dimensions`)."""
    if not ffprobe:
        raise _media.ToolError("tool_not_runnable", "ffprobe")
    facts = _media.probe_clip(ffprobe, path, demuxer, field, decoders)
    if facts["width"] * facts["height"] > limits["asset_max_pixels"]:
        fail("asset_dimensions", field)
    return {"kind": "clip", "demuxer": demuxer, "codec": facts["codec"], "decoder": _media.clip_decoder(facts["codec"], decoders), "width": facts["width"],
            "height": facts["height"], "seconds": facts["seconds"], "color_space": facts["color_space"], "data": data,
            "sha256": hashlib.sha256(data).hexdigest(), "alpha": False}


def clip_size(w: int, h: int, field: str) -> tuple:
    """The size a clip is normalised to: `target_size`, each side made even (H.264 in yuv420p needs it; an odd side goes up by one pixel)."""
    tw, th = target_size(w, h, field)
    return tw + tw % 2, th + th % 2


def clip_fps(value) -> int:
    """The frame rate of `--fps`: a whole number from 24 to 60 (`bad_fps` otherwise)."""
    try:
        fps = int(value)
    except (TypeError, ValueError):
        fail("bad_fps", "fps")
    if not _media.CLIP_FPS_MIN <= fps <= _media.CLIP_FPS_MAX or str(value).strip() != str(fps):
        fail("bad_fps", "fps")
    return fps


def clip_matrix(clip: dict) -> str:
    """The colour matrix a clip is read through: bt709 when it says so or says nothing and is high definition, else the one it is tagged with (auto)."""
    space = clip["color_space"]
    if space == "bt709" or (space in (None, "", "unknown", "unspecified") and max(clip["width"], clip["height"]) >= 1280):
        return "bt709"
    return "auto"


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


def clip_normalise_argv(ffmpeg: str, clip: dict, src: str, out: str, size: tuple, fps: int, max_bytes: int) -> list:
    """The command that normalises one checked clip: its first video stream only (no audio, subtitle or data stream, no metadata or chapter), the first
    CLIP_MAX_SECONDS seconds, conformed to the constant rate `fps`, its long side scaled to `size` through the bt709 matrix and written as H.264 High yuv420p,
    bt709 tagged, x264 on one thread (the decoder and the filter graph too), bit-exact, faststart. The same argv gives the same bytes at any core count."""
    one = str(_media.ENCODE_INPUT_THREADS)
    vf = "fps=%d:start_time=0,scale=%d:%d:in_color_matrix=%s:out_color_matrix=bt709:out_range=tv:flags=%s,format=yuv420p,setsar=1,%s" % (
        fps, size[0], size[1], clip_matrix(clip), _media.SWS, _media.TAGS)
    return (base_argv(ffmpeg) + ["-err_detect", "explode"] + _media.clip_input(clip["demuxer"], clip["decoder"]) + ["-t", "%g" % _media.CLIP_MAX_SECONDS, "-i", src]
            + ["-map", "0:v:0", "-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1", "-vf", vf, "-sws_flags", _media.SWS,
               "-c:v", "libx264", "-threads", one, "-x264-params", _media.PREVIEW_X264_PARAMS, "-preset", "medium", "-crf", str(CLIP_X264_CRF),
               "-profile:v", "high", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-r", str(fps), "-fps_mode", "cfr", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-fs", str(max_bytes), "-movflags", "+faststart", out])


def clip_frame_argv(ffmpeg: str, clip: dict, src: str, out: str) -> list:
    """The command that writes a clip's tile frame as a PNG: its frame at 0.5 s (its first frame when the clip is not longer than that), cut to fit a
    CLIP_PREVIEW_SIDE box. `clip` holds demuxer, decoder, seconds, color_space, width and height (a normalised clip: h264, bt709)."""
    seek = ["-ss", "0.5"] if clip["seconds"] > 0.5 else []
    vf = "scale=%d:%d:force_original_aspect_ratio=decrease:in_color_matrix=%s:flags=%s,format=rgb24" % (CLIP_PREVIEW_SIDE, CLIP_PREVIEW_SIDE, clip_matrix(clip), _media.SWS)
    return (base_argv(ffmpeg) + _media.clip_input(clip["demuxer"], clip["decoder"]) + seek + ["-i", src, "-map", "0:v:0", "-sn", "-dn", "-vf", vf]
            + output_options(out))


def cell_size() -> tuple:
    return TILE[0] + GAP, TILE[1] + GAP


def sheet_argv(ffmpeg: str, cells: list, columns: int, background: str, out: str, marker=None) -> list:
    """The command that tiles `cells` (a list in row-major order of {kind, path[, clip]} or None for an empty tile) into one PNG: each picture scaled to fit its
    tile, centred in a cell of the background colour; `columns` cells per row. A cell with `clip` set gets a solid box of the colour `marker` ("#RRGGBB") in
    the cell's corner, when a marker colour is given (a drawn glyph would need a font the image may not have)."""
    cw, ch = cell_size()
    color = "0x" + background.lstrip("#")
    argv, graph, labels = base_argv(ffmpeg), [], []
    index = 0
    for n, cell in enumerate(cells):
        if cell is None:
            graph.append("color=c=%s:s=%dx%d:r=1:d=1,format=rgb24[c%d]" % (color, cw, ch, n))
        else:
            argv += _media.asset_input(cell["kind"], cell["path"])
            flag = ""
            if marker and cell.get("clip"):
                flag = ",drawbox=x=%d:y=%d:w=%d:h=%d:color=0x%s:t=fill" % (MARKER + (marker.lstrip("#"),))
            graph.append("[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease:flags=%s,format=rgb24,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s%s[c%d]"
                         % (index, TILE[0], TILE[1], _media.SWS, cw, ch, color, flag, n))
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


def asset_sheet(*, items: dict, mode: str, out_dir: str, ffmpeg: str, data=None, ffprobe=None, fps=_media.CLIP_FPS_DEFAULT, decoders=None) -> dict:
    """Check every picture and clip of `items` ({"ROW:COL": path}), normalise them in `full` mode and write the sheet. Everything is checked before anything is
    written; a refusal leaves no file. `ffprobe` is needed only when a clip is given; `fps` (24 to 60) is the constant rate a clip is written at; `decoders`
    (tests only) stands in for the decoder list read from ffmpeg. Returns the answer described in the module's text."""
    if mode not in MODES:
        fail("bad_mode", mode)
    fps = clip_fps(fps)
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
        raw = _assets.read_regular(path, data["limits"]["asset_max_bytes"], "asset_unreadable", field)
        demuxer = _media.clip_container(raw[:16])
        if demuxer:
            if decoders is None:                                    # the image's ffmpeg says which codecs it can read, once, when a clip is given
                try:
                    decoders = _media.software_decoders(ffmpeg)
                except _media.ToolError:
                    decoders = ()
            pictures[(row, col)] = check_clip(path, raw, demuxer, field, data["limits"], ffprobe, decoders)
            if mode == "full":
                pictures[(row, col)]["size"] = clip_size(pictures[(row, col)]["width"], pictures[(row, col)]["height"], field)
            continue
        pictures[(row, col)] = check_picture(path, field, data["limits"])
        if mode == "full":
            pictures[(row, col)]["size"] = target_size(pictures[(row, col)]["width"], pictures[(row, col)]["height"], field)
    rows = sorted({row for row, _ in keyed})
    columns = max(col for _, col in keyed)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    work = tempfile.mkdtemp(prefix=".sheet-", dir=out_dir)
    marker = data["theme"]["colors"]["accent"]
    try:
        sources = {}
        for (row, col), picture in pictures.items():
            src = os.path.join(work, "in-%s-%d.%s" % (row, col, picture["kind"] if picture["kind"] != "clip" else _media.CLIP_EXT))
            fd = os.open(src, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(picture["data"])
            sources[(row, col)] = src
        assets, tiles, moves = [], {}, []
        for (row, col), picture in pictures.items():
            field = "%s:%d" % (row, col)
            is_clip = picture["kind"] == "clip"
            kind, seconds = ("clip", picture["seconds"]) if is_clip else ("image", 0)
            if mode == "preview":
                assets.append({"row": row, "col": col, "file": None, "sha256": picture["sha256"], "width": picture["width"], "height": picture["height"],
                               "source_sha256": picture["sha256"], "kind": kind, "seconds": seconds})
                if is_clip:
                    frame = os.path.join(work, "frame-%s-%d.png" % (row, col))
                    _run_clip(clip_frame_argv(ffmpeg, picture, sources[(row, col)], frame), field)
                    tiles[(row, col)] = {"kind": "png", "path": frame, "clip": True}
                else:
                    tiles[(row, col)] = {"kind": picture["kind"], "path": sources[(row, col)]}
                continue
            if is_clip:
                made = os.path.join(work, "out-%s-%d.%s" % (row, col, _media.CLIP_EXT))
                _run_clip(clip_normalise_argv(ffmpeg, picture, sources[(row, col)], made, picture["size"], fps, data["limits"]["asset_max_bytes"]), field)
                raw = _read(made)
                if len(raw) >= data["limits"]["asset_max_bytes"] or not _media.faststart(made):      # `-fs` stops a file at the cap: a file at it is cut short
                    fail("asset_dimensions" if len(raw) >= data["limits"]["asset_max_bytes"] else "asset_unreadable", field)
                facts = _media.probe_clip(ffprobe, made, "mov", field, output=True)
                if (facts["width"], facts["height"]) != tuple(picture["size"]) or abs(facts["fps"] - fps) > 0.001:
                    fail("asset_unreadable", field)
                if abs(facts["duration"] - picture["seconds"]) > max(0.25, 2.0 / fps):      # a file cut short is read to its end without a decode error: it comes out shorter than it says
                    fail("asset_corrupt", field)
                digest = hashlib.sha256(raw).hexdigest()
                name = CLIP_NAME % digest[:12]
                assets.append({"row": row, "col": col, "file": name, "sha256": digest, "width": facts["width"], "height": facts["height"],
                               "source_sha256": picture["sha256"], "kind": "clip", "seconds": round(facts["duration"], 3)})
                frame = os.path.join(work, "frame-%s-%d.png" % (row, col))
                _run_clip(clip_frame_argv(ffmpeg, dict(picture, demuxer="mov", decoder="h264", seconds=facts["duration"], color_space="bt709", width=facts["width"], height=facts["height"]),
                                          made, frame), field)
                tiles[(row, col)] = {"kind": "png", "path": frame, "clip": True}
                moves.append((made, os.path.join(out_dir, name)))
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
            assets.append({"row": row, "col": col, "file": name, "sha256": digest, "width": facts[1], "height": facts[2], "source_sha256": picture["sha256"],
                           "kind": "image", "seconds": 0})
            tiles[(row, col)] = {"kind": "png", "path": made}
            moves.append((made, os.path.join(out_dir, name)))
        cells = [tiles.get((row, col)) for row in rows for col in range(1, columns + 1)]
        sheet = os.path.join(work, SHEET_NAME)
        _media.run(sheet_argv(ffmpeg, cells, columns, data["theme"]["colors"]["bg"], sheet, marker), FFMPEG_TIMEOUT)
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


def _run_clip(argv: list, field: str) -> None:
    """Run one ffmpeg command on a clip: a clip the decoder or encoder cannot get through (damaged, cut short) is `asset_corrupt`; any other failure stays as it is."""
    try:
        _media.run(argv, FFMPEG_TIMEOUT)
    except _media.ToolError as exc:
        if exc.code == "tool_failed":
            fail("asset_corrupt", field)
        raise


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()

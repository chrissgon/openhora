"""The exact pixel gates of an admitted page (the second contract, R3-1).

A page of the second contract can draw anywhere, so the gates are on what it drew: every frame it wrote is an 8-bit RGBA PNG of the frame's size,
and in every frame no pixel with any alpha at all lies in the speaker's face box, and none at or below the line where the captions begin. There is no
threshold: an alpha of 1/255 is a hit. A layer that draws nothing in all its frames is refused too (`block_not_drawn`).

One ffmpeg pass per range: the alpha channel is taken out of the frames, split three ways, and each branch's highest value is read (`signalstats`
YMAX; the frames stay 8-bit gray, so the value is the alpha itself): the face box rounded outward to whole pixels, the rows from `line_y` down, and
the whole frame. The logs are written to relative names in a temporary folder, so no path is inside a filter string. Standard library only.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import struct
import subprocess
import tempfile

from _text import Refusal

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
YMAX = re.compile(r"frame:(\d+)[^\n]*\n[^\n]*YMAX=(\d+)")


def png_header(path: str):
    """(width, height, bit depth, colour type) from a PNG's IHDR, or None when the file is not a PNG."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(33)
    except OSError:
        return None
    if len(head) < 29 or head[:8] != PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None
    w, h, depth, colour = struct.unpack(">IIBB", head[16:26])
    return w, h, depth, colour


def box_pixels(face: dict, w: int, h: int) -> tuple:
    """The face box rounded outward to whole pixels and kept inside the frame: (x, y, width, height)."""
    x0 = max(0, math.floor(face["x"]))
    y0 = max(0, math.floor(face["y"]))
    x1 = min(w, math.ceil(face["x"] + face["w"]))
    y1 = min(h, math.ceil(face["y"] + face["h"]))
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def _read_max(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    return [int(v) for _f, v in YMAX.findall(text)]


def check_range(frames_dir: str, start: int, end: int, face: dict, line_y, w: int, h: int, ffmpeg: str = "ffmpeg", prefix: str = "beat") -> None:
    """The gates on frames [start, end) of one range. Refusals: `frame_not_rgba`, `overlay_hits_face`, `caption_below_line`, `block_not_drawn`
    (the field is `frame N`, the first frame found)."""
    count = end - start
    if count <= 0:
        return
    for n in range(start, end):
        head = png_header(os.path.join(frames_dir, "%s_%06d.png" % (prefix, n)))
        if head is None or head != (w, h, 8, 6):
            raise Refusal("frame_not_rgba", "frame %d" % n)
    fx, fy, fw, fh = box_pixels(face, w, h)
    parts = ["[0:v]trim=end_frame=%d,alphaextract,split=3[a][b][c]" % count]
    outs = []
    if fw > 0 and fh > 0:
        parts.append("[a]crop=%d:%d:%d:%d,signalstats,metadata=print:key=lavfi.signalstats.YMAX:file=face.txt[oa]" % (fw, fh, fx, fy))
        outs.append("oa")
    else:
        parts.append("[a]nullsink")
    ly = None if line_y is None else max(0, int(math.floor(line_y)))
    if ly is not None and ly < h:
        parts.append("[b]crop=%d:%d:0:%d,signalstats,metadata=print:key=lavfi.signalstats.YMAX:file=line.txt[ob]" % (w, h - ly, ly))
        outs.append("ob")
    else:
        parts.append("[b]nullsink")
    parts.append("[c]signalstats,metadata=print:key=lavfi.signalstats.YMAX:file=all.txt[oc]")
    outs.append("oc")
    work = tempfile.mkdtemp(prefix=".alpha-")
    try:
        argv = [ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-start_number", str(start), "-i",
                os.path.join(os.path.abspath(frames_dir), prefix + "_%06d.png"), "-filter_complex", ";".join(parts)]
        for name in outs:
            argv += ["-map", "[%s]" % name, "-frames:v", str(count), "-f", "null", "-"]
        done = subprocess.run(argv, cwd=work, capture_output=True, text=True, timeout=600)
        if done.returncode != 0:
            raise Refusal("frame_not_rgba", "frame %d" % start)
        face_max = _read_max(os.path.join(work, "face.txt"))
        line_max = _read_max(os.path.join(work, "line.txt"))
        all_max = _read_max(os.path.join(work, "all.txt"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if len(all_max) != count:
        raise Refusal("frame_not_rgba", "frame %d" % start)
    for k, v in enumerate(face_max):
        if v > 0:
            raise Refusal("overlay_hits_face", "frame %d" % (start + k))
    for k, v in enumerate(line_max):
        if v > 0:
            raise Refusal("caption_below_line", "frame %d" % (start + k))
    if max(all_max) == 0:
        raise Refusal("block_not_drawn", "frame %d" % start)


def check_layer(frames_dir: str, ranges: list, face: dict, line_y, w: int, h: int, ffmpeg: str = "ffmpeg", prefix: str = "beat") -> None:
    """The gates on every range of one layer. `ranges` rows are {start, end[, face][, line_y]}: the face box and the line of a row are the render's
    real ones for that range, and `face` / `line_y` here are the defaults of a row that has none."""
    for row in ranges:
        check_range(frames_dir, row["start"], row["end"], row.get("face", face), row.get("line_y", line_y), w, h, ffmpeg, prefix)

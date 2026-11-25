"""The exact pixel gates of an admitted page (the second contract, R3-1).

A page of the second contract can draw anywhere, so the gates are on what it drew: every frame it wrote is an 8-bit RGBA PNG of the frame's size,
and in every frame no pixel with any alpha at all lies on or below the line (a card's is the top of the caption band, a caption's is its bottom). There is no
threshold: an alpha of 1/255 is a hit. A layer that draws nothing in all its frames is refused too (`block_not_drawn`). There is no gate on the speaker's
face: the maintainer removed that rule on 2026-11-24 (it was R3-2's alpha face gate), so an overlay may be drawn over the face; the face box stays a
placement input (the bands the zones are made from) and is never a refusal.

One ffmpeg pass per range: the alpha channel is taken out of the frames, split two ways, and each branch's highest value is read (`signalstats`
YMAX; the frames stay 8-bit gray, so the value is the alpha itself): the rows from `line_y` down, and the whole frame. The logs are written to relative names in a temporary folder, so no path is inside a filter string. Standard library only.
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


def _read_max(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return []
    return [int(v) for _f, v in YMAX.findall(text)]


def check_range(frames_dir: str, start: int, end: int, line_y, w: int, h: int, ffmpeg: str = "ffmpeg", prefix: str = "beat", require_drawn: bool = True) -> None:
    """The gates on frames [start, end) of one range. Refusals: `frame_not_rgba`, `caption_below_line`, `block_not_drawn` (the field is `frame N`, the first
    frame found). There is no face gate: an overlay may be drawn over the speaker's face (the maintainer's decisions of 2026-11-24; the face box is a placement
    input, never a refusal). `line_y` is the line the layer must stay on one side of: a card's is its band's top and a caption's is its band's bottom, and no
    pixel with any alpha at all may lie on or below it. `require_drawn` false (a caption chunk too short to be read) leaves the last one out."""
    count = end - start
    if count <= 0:
        return
    for n in range(start, end):
        head = png_header(os.path.join(frames_dir, "%s_%06d.png" % (prefix, n)))
        if head is None or head != (w, h, 8, 6):
            raise Refusal("frame_not_rgba", "frame %d" % n)
    parts = ["[0:v]trim=end_frame=%d,alphaextract,split=2[b][c]" % count]
    outs = []
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
        line_max = _read_max(os.path.join(work, "line.txt"))
        all_max = _read_max(os.path.join(work, "all.txt"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if len(all_max) != count:
        raise Refusal("frame_not_rgba", "frame %d" % start)
    for k, v in enumerate(line_max):
        if v > 0:
            raise Refusal("caption_below_line", "frame %d" % (start + k))
    if require_drawn and max(all_max) == 0:
        raise Refusal("block_not_drawn", "frame %d" % start)


def check_layer(frames_dir: str, ranges: list, w: int, h: int, ffmpeg: str = "ffmpeg", prefix: str = "beat") -> None:
    """The gates on every range of one layer. `ranges` rows are {start, end, line_y[, require_drawn]}: the line of a row is the render's real one for that range."""
    for row in ranges:
        check_range(frames_dir, row["start"], row["end"], row.get("line_y"), w, h, ffmpeg, prefix, row.get("require_drawn", True))

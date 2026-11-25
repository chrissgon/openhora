"""The exact pixel gates of an admitted page (the second contract, R3-1).

A page of the second contract can draw anywhere, so the gates are on what it drew: every frame it wrote is an 8-bit RGBA PNG of the frame's size,
and every frame holds pixels with any alpha at all on or below the line (a card's is the top of the caption band, a caption's is its bottom): that is advice (`drawn_below_line`),
not a refusal (the maintainer's principle of 2026-11-24). There is no threshold: an alpha of 1/255 is a hit. A layer that draws nothing in all its frames is advice too
(`block_not_drawn`). The only refusal left is a frame that is not an 8-bit RGBA PNG of the frame's size (`frame_not_rgba`). There is no gate on the speaker's
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

import _advice
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


def check_range(frames_dir: str, start: int, end: int, line_y, w: int, h: int, ffmpeg: str = "ffmpeg", prefix: str = "beat", require_drawn: bool = True, aid=None) -> list:
    """The gates on frames [start, end) of one range. The one refusal is `frame_not_rgba` (the field is `frame N`, the first frame found). Returns the advice rows
    (a list of `_advice`, `[]` for none): `drawn_below_line` (the frames that draw on or below the line) and `block_not_drawn` (the range's frames, when it draws nothing),
    each with `aid`, the id of the entry. There is no face gate: an overlay may be drawn over the speaker's face (the maintainer's decisions of 2026-11-24; the face box is a placement
    input, never a refusal). `line_y` is the line the layer must stay on one side of: a card's is its band's top and a caption's is its band's bottom, and no
    pixel with any alpha at all may lie on or below it. `require_drawn` false (a caption chunk too short to be read) leaves the last one out."""
    count = end - start
    found = []
    if count <= 0:
        return found
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
    below = sum(1 for v in line_max if v > 0)
    if below:
        _advice.add(found, "drawn_below_line", below, 0, aid)
    if require_drawn and max(all_max) == 0:
        _advice.add(found, "block_not_drawn", count, 0, aid)
    return found


def check_layer(frames_dir: str, ranges: list, w: int, h: int, ffmpeg: str = "ffmpeg", prefix: str = "beat") -> list:
    """The gates on every range of one layer; returns their advice rows, merged. `ranges` rows are {start, end, line_y[, require_drawn, id]}: the line of a row is the render's real one for that range."""
    found = []
    for row in ranges:
        found = _advice.merge(found, check_range(frames_dir, row["start"], row["end"], row.get("line_y"), w, h, ffmpeg, prefix, row.get("require_drawn", True), row.get("id")))
    return found

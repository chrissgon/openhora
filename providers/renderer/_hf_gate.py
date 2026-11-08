"""The gates on what the HyperFrames engine draws (package V3b-2): the DOM boxes of every frame against the face box and the line at 1560,
and the pixels of the face region against the undrawn base. Nothing the engine draws reaches the final encode unless both pass.

Two checks, both code, neither with a switch:

  boxes   `boxes.json` is what the page itself reported after the drawing (`hyperframes-image/hf_measure.mjs`: every box of every frame,
          the glyph rects of the text too). Each box is tested with the ffmpeg engine's own arithmetic (`_layout.face_hit`,
          `_layout.caption_hit`, `_layout.zones`) against the face of the entry that is on at that frame in the box's zone, else the face
          of the kept range the frame is in. The refusals are the ffmpeg engine's own: `overlay_hits_face`, `caption_below_line`.
  pixels  the face region of each kept range of the intermediate is compared, frame by frame, with the same region of the base the
          ffmpeg engine would draw (the proxy cut and zoomed by `_media.base_graph`), by ffmpeg's `psnr`. It sees what the boxes cannot: a
          canvas, a pseudo-element, a shadow or a filter that draws on the face with no box of its own. Under `PIXEL_MIN_PSNR_DB` in any
          frame of any range: `face_pixels_changed`.

The page's script reports the boxes and a block cannot report fewer: a block that hides a box from the page's own DOM is still seen by the
pixel check. Both checks run on every composed render (`encode` takes the gate's inputs all together or none), and no flag, parameter or
environment variable turns either off. Standard library only; imports only common modules.
"""
from __future__ import annotations

import hashlib
import json
import math
import re

import _assets
import _edl
import _layout
import _media
from _text import Refusal

BOXES_MAX_BYTES = 64 * 1024 ** 2                # the cap of boxes.json (hf_measure.mjs refuses a larger one, `boxes_too_large`)
MAX_BOXES_PER_FRAME = 2000                      # the same figure as hf_measure.mjs (`boxes_too_many`)
ZONES = ("card", "caption")                     # the bands boxes sit in; the `frame` band is not drawn on this engine
ALLOWED_FAMILIES = ("Inter", "JetBrains Mono")  # the families of assets/fonts/allowlist.json
KEY = re.compile(r"[A-Za-z0-9_.:\-]{1,60}")
PIXEL_MIN_PSNR_DB = 30.0                        # calibrated 2026-11-08 on synthetic content: clean 36.31 dB live and 49.85 and 51.65 offline, planted 19.8 dB (decision file of V3b-2)
PSNR_CAP = 99.0                                 # two identical frames give an infinite PSNR; the result carries this figure instead
PIXEL_TIMEOUT = 3600
STATS_NAME = "psnr-%d.log"                      # one stats file per kept range, in the working folder (the command runs there)
FIELD_OK = re.compile(r"[A-Za-z0-9_.\[\]:\- ]{0,80}")      # the characters a refusal field may hold (the same shape `_docker` accepts)
MIN_CROP = 2                                    # pixels: the smallest face region the pixel check compares


def number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and abs(x) < 1e7


def unreadable():
    return Refusal("boxes_unreadable", "boxes")


# ---------------------------------------------------------------- boxes.json

def read_boxes(path: str, expect_sha256: str, out_frames: int) -> dict:
    """boxes.json as untrusted data: a regular file within BOXES_MAX_BYTES, its sha256 the one the host named (`boxes_changed`), a JSON
    object of the shape hf_measure.mjs writes (`boxes_unreadable`), one list of at most MAX_BOXES_PER_FRAME boxes per output frame of the edit
    list (`boxes_frames_differ`, `boxes_too_many`), and only the two allow-listed fonts, each custom (`font_not_allowed`). Returns the document."""
    raw = _assets.read_regular(path, BOXES_MAX_BYTES, "boxes_unreadable", "boxes")
    if hashlib.sha256(raw).hexdigest() != expect_sha256:
        raise Refusal("boxes_changed", "boxes")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise unreadable() from None
    if not isinstance(doc, dict) or doc.get("schema") != 1 or not isinstance(doc.get("frames"), int) or isinstance(doc.get("frames"), bool) \
            or not isinstance(doc.get("per_frame"), list) or not isinstance(doc.get("fonts"), list):
        raise unreadable()
    if doc["frames"] != out_frames or len(doc["per_frame"]) != out_frames:
        raise Refusal("boxes_frames_differ", "boxes")
    for font in doc["fonts"]:
        if not isinstance(font, dict) or not isinstance(font.get("family"), str) or not isinstance(font.get("custom"), bool):
            raise unreadable()
        if font["family"] not in ALLOWED_FAMILIES or font["custom"] is not True:
            raise Refusal("font_not_allowed", "drawn")
    for boxes in doc["per_frame"]:
        if not isinstance(boxes, list):
            raise unreadable()
        if len(boxes) > MAX_BOXES_PER_FRAME:
            raise Refusal("boxes_too_many", "boxes")
        for b in boxes:
            if not isinstance(b, dict) or not isinstance(b.get("zone"), str) or not isinstance(b.get("key"), str) or not KEY.fullmatch(b["key"]) \
                    or not isinstance(b.get("glyph"), bool) or not all(number(b.get(k)) for k in ("x", "y", "w", "h")) or b["w"] < 0 or b["h"] < 0:
                raise unreadable()
    return doc


# ---------------------------------------------------------------- the rules on the boxes

def faces_by_frame(timeline: dict, range_faces: list, out_frames: int) -> dict:
    """{zone: [face of the frame, ...]}: for each output frame, the face box a box of that zone is tested against: the union of the faces
    of the entries of the zone that are on at that frame (caption entries for `caption`, beat entries for `card`), else the face of the kept
    range the frame is in, else the face of the first range."""
    base = []
    for first, last, box in range_faces:
        base.extend([box] * max(0, last - first))
    base.extend([range_faces[-1][2]] * max(0, out_frames - len(base)))
    out = {}
    for zone, entries in (("caption", timeline["captions"]), ("card", timeline["beats"])):
        faces = list(base[:out_frames])
        for e in entries:
            for f in range(max(0, e["start_frame"]), min(out_frames, e["end_frame"])):
                faces[f] = e["face"] if faces[f] is base[f] else _edl.union([faces[f], e["face"]])
        out[zone] = faces
    return out


def check_boxes(doc: dict, timeline: dict, range_faces: list, data: dict) -> dict:
    """Every box of every frame against the face box and the line at 1560, in frame order, the first violation raised:

      a `frame`-zone box (or any zone but card and caption)     overlay_hits_face  "frame <f> <key>"
      a box (element or glyph) that touches the face            overlay_hits_face  "frame <f> <key>"
      a caption box (element or glyph) whose bottom is below the caption band's bottom   caption_below_line  "frame <f> bottom <y>"

    Returns {frames, boxes, lowest_caption_bottom (the largest bottom of a caption box, or None when no caption box was drawn)}."""
    out_frames = doc["frames"]
    faces = faces_by_frame(timeline, range_faces, out_frames)
    bands, total, lowest = {}, 0, None
    for f, boxes in enumerate(doc["per_frame"]):
        for b in boxes:
            total += 1
            zone, field = b["zone"], ("frame %d %s" % (f, b["key"]))[:80]
            if zone not in ZONES:
                raise Refusal("overlay_hits_face", field)
            face = faces[zone][f]
            if _layout.face_hit([b], face):
                raise Refusal("overlay_hits_face", field)
            if zone == "caption" and b["w"] > 0 and b["h"] > 0:
                bottom = b["y"] + b["h"]
                lowest = bottom if lowest is None else max(lowest, bottom)
                band = bands.setdefault((face["x"], face["y"], face["w"], face["h"]), _layout.zones(data, face))
                if _layout.caption_hit(b, band):
                    raise Refusal("caption_below_line", "frame %d bottom %g" % (f, bottom))
    return {"frames": out_frames, "boxes": total, "lowest_caption_bottom": None if lowest is None else round(lowest, 1)}


# ---------------------------------------------------------------- the pixel check

def crop_box(box: dict, width: int, height: int) -> tuple:
    """(w, h, x, y) of the face region of a range, in whole even pixels inside the frame (a subsampled picture is cropped on even
    coordinates), at least MIN_CROP each way."""
    x0, y0 = max(0, int(box["x"])) // 2 * 2, max(0, int(box["y"])) // 2 * 2
    x1, y1 = min(width, int(math.ceil(box["x"] + box["w"]))), min(height, int(math.ceil(box["y"] + box["h"])))
    w, h = (x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2
    if w < MIN_CROP or h < MIN_CROP:
        raise Refusal("face_box_leaves_no_room", "face_box")
    return w, h, x0, y0


def reference_plan(edl: dict, data: dict) -> dict:
    """The plan `_media.base_graph` reads for the reference: the edit list's cuts and zoom, no audio, no recording framing."""
    frame = data["frame"]
    return {"fps": edl["fps"], "size": [frame["width"], frame["height"]], "kept": edl["kept"], "zoom": edl["zoom"], "fade": 0.0, "has_audio": False,
            "anchor": _media.anchor_point(edl["face_box"], edl["zoom"]["anchor_y"])}


def reference_graph(edl: dict, data: dict, source: str) -> list:
    """The filters that make the undrawn base from the proxy at label `source`, ending at `[cv]`: the kept ranges cut and zoomed by the one base graph,
    each zoom sampled bilinearly at exact positions (`_media.zoom_filter_linear`), as a browser scales a video layer. Earlier references and what they
    measured against a bilinear stand-in (testsrc2 detail, a 2 percent push-in, the face region, executor, host ffmpeg): `zoompan` on the proxy at a base of
    one 26 dB at the worst, `zoompan` at twice the size 29.8 at the worst and 33.2 at the median, which is also what the first live render gave (29.0 and
    33.4). An unzoomed range is the proxy as it is."""
    return _media.base_graph(reference_plan(edl, data), source=source, prepare="fps=%s:start_time=0,format=yuv420p" % edl["fps"], base=1, audio=False,
                             zoom_linear=True)


def pixel_argv(ffmpeg: str, intermediate: str, proxy: str, edl: dict, data: dict, range_faces: list) -> list:
    """The one ffmpeg command of the pixel check. Inputs: the intermediate (0) and the proxy (1). The proxy is cut into the kept ranges and
    zoomed by `_media.base_graph` (the reference, on the output timeline); the intermediate is converted to the same format; each stream is
    split once per kept range, trimmed to the range's output frames, cropped to the range's face region and compared by `psnr`, whose
    per-frame figures go to `psnr-<k>.log` in the folder the command runs in (a name with no character the filter graph treats
    specially). The one output is the last range's comparison: a range's comparison ends when its trim reaches the range's end, so the
    last one ends last, and ffmpeg stops only when every range before it has been judged (an output that ended first would end them all). Every input has `-threads 1`, the graph `-filter_threads 1` and `-filter_complex_threads 1`, the scaler the bit-exact flags,
    and every stream ends exactly (`-t` on each input from the frame counts, `-frames:v` on the output): no `-shortest`, no automatic count."""
    fps, out_frames, frame = edl["fps"], edl["out_frames"], data["frame"]
    width, height = frame["width"], frame["height"]
    n = len(range_faces)
    g = reference_graph(edl, data, "[1:v:0]")
    g.append("[0:v:0]scale=flags=%s,format=yuv420p,setsar=1[hv]" % _media.SWS)
    if n == 1:
        ref, hf = ["[cv]"], ["[hv]"]
    else:
        g.append("[cv]split=%d%s" % (n, "".join("[r%d]" % k for k in range(n))))
        g.append("[hv]split=%d%s" % (n, "".join("[h%d]" % k for k in range(n))))
        ref, hf = ["[r%d]" % k for k in range(n)], ["[h%d]" % k for k in range(n)]
    for k, (first, last, box) in enumerate(range_faces):
        w, h, x, y = crop_box(box, width, height)
        for label, source in (("rc", ref[k]), ("hc", hf[k])):
            g.append("%strim=start_frame=%d:end_frame=%d,setpts=PTS-STARTPTS,crop=%d:%d:%d:%d[%s%d]" % (source, first, last, w, h, x, y, label, k))
        g.append("[hc%d][rc%d]psnr=stats_file=%s[p%d]" % (k, k, STATS_NAME % k, k))
        if k < n - 1:
            g.append("[p%d]nullsink" % k)
    seconds_out = "%.6f" % (out_frames / float(fps))
    seconds_in = "%.6f" % (edl["kept"][-1][1] / float(fps))
    one = str(_media.ENCODE_INPUT_THREADS)
    return [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", one, "-filter_complex_threads", one,
            "-threads", one, "-t", seconds_out, "-i", intermediate, "-threads", one, "-t", seconds_in, "-i", proxy,
            "-filter_complex", ";".join(g), "-map", "[p%d]" % (n - 1), "-sws_flags", _media.SWS, "-an", "-c:v", "rawvideo", "-frames:v", str(out_frames),
            "-f", "null", "-"]


STATS_LINE = re.compile(r"n:(\d+) .*?psnr_avg:(inf|[0-9]+(?:\.[0-9]+)?)(?: |$)")


def read_stats(path: str, expect_frames: int) -> list:
    """The per-frame PSNR (average of the planes) of one range's stats file, as numbers (inf capped at PSNR_CAP): one per frame of the range."""
    raw = _assets.read_regular(path, 64 * 1024 ** 2, "pixel_check_failed", "stats")
    values = []
    for line in raw.decode("utf-8", "replace").splitlines():
        m = STATS_LINE.match(line)
        if not m:
            raise Refusal("pixel_check_failed", "stats")
        values.append(PSNR_CAP if m.group(2) == "inf" else min(PSNR_CAP, float(m.group(2))))
    if len(values) != expect_frames:
        raise Refusal("pixel_check_failed", "stats")
    return values


def pixel_check(ffmpeg: str, intermediate: str, proxy: str, edl: dict, data: dict, range_faces: list, work: str, run=None, timeline=None) -> dict:
    """Run the pixel check in the folder `work` (the stats files are written there, and are the caller's to remove) and judge it: the
    minimum PSNR over every frame of every kept range, refused `face_pixels_changed` ("range <k> frame <f> psnr <x>") when any frame is
    under PIXEL_MIN_PSNR_DB. Returns {pixel_min_psnr_db, pixel_ranges}. `run` stands where `_media.run` stands (a test's seam; production
    leaves it out)."""
    run = run or _media.run
    run(pixel_argv(ffmpeg, intermediate, proxy, edl, data, range_faces), PIXEL_TIMEOUT, cwd=work)
    lowest = None
    for k, (first, last, _box) in enumerate(range_faces):
        values = read_stats(work + "/" + (STATS_NAME % k), last - first)
        worst = min(range(len(values)), key=lambda i: values[i])
        if lowest is None or values[worst] < lowest:
            lowest = values[worst]
        if values[worst] < PIXEL_MIN_PSNR_DB:
            err = Refusal("face_pixels_changed", "range %d frame %d psnr %.1f" % (k, first + worst, values[worst]))
            err.problems = explain(k, edl, first, last, values, worst, timeline)
            raise err
    return {"pixel_min_psnr_db": round(lowest if lowest is not None else PSNR_CAP, 2), "pixel_ranges": len(range_faces)}


def explain(k: int, edl: dict, first: int, last: int, values: list, worst: int, timeline) -> list:
    """What a refusal of the pixel check says about the range, in closed shapes (each a code and a field of the characters a field may hold): the
    range's output frames, the worst frame's offset in it, how many frames are under the threshold, the median, the zoom at both ends of the range and
    what the timeline draws at the worst frame, so a clean render that fails explains itself."""
    ordered = sorted(values)
    median = ordered[len(ordered) // 2]
    z0, z1 = _media.zoom_levels(edl["zoom"], k, edl["kept"][k][1] - edl["kept"][k][0], edl["fps"])
    spans, start = [], None
    for i, v in enumerate(values + [PSNR_CAP]):
        if v < PIXEL_MIN_PSNR_DB and start is None:
            start = i
        elif v >= PIXEL_MIN_PSNR_DB and start is not None:
            spans.append((first + start, first + i - 1))
            start = None
    shown = " ".join("%d-%d" % span for span in spans[:4]) + (" more" if len(spans) > 4 else "")
    rows = [("range_frames", "first %d last %d" % (first, last - 1)), ("worst_offset", "offset %d of %d" % (worst, len(values))),
            ("frames_under", "under %d of %d" % (sum(1 for v in values if v < PIXEL_MIN_PSNR_DB), len(values))), ("under_at", "under_at " + shown),
            ("median", "median %.1f" % median), ("zoom", "zoom %.4f to %.4f" % (z0, z1))]
    if timeline:
        at = first + worst
        entries = [("caption", e) for e in timeline.get("captions", [])] + [(str(e["preset"]), e) for e in timeline.get("beats", [])]
        on = [(name, e["start_frame"], e["end_frame"]) for name, e in entries if e["start_frame"] <= at < e["end_frame"]]
        rows.append(("drawn_at_worst", ("drawn " + " ".join(sorted({name for name, _, _ in on}))) if on else "drawn none"))
        rows += [("entry", "%s %d to %d" % (name, lo, hi)) for name, lo, hi in on[:3]]
    return [{"beat": None, "code": code, "field": field[:80]} for code, field in rows]

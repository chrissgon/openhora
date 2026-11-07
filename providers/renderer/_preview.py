"""The storyboard: what a script's beats will look like, drawn by the render's own code with no recording and no transcript.

  beat_row         one beat given as JSON ({preset, params, line}) in the shape `_align.read_beats` gives a beat of a post.
  synthetic_words  each beat's line as words spoken at a fixed rate, one beat after another, as a transcript and an analysis.
  build_lists      the edit list (`_edl.build_base`) and the beats list (`_align.build_beats`) for those words, then the render's own
                   checks (`_render.check_documents`): nothing is drawn before they pass.
  rest_frame       the output frame where a beat's overlay is at rest: its end less the preset's tail less one frame.
  draw_rest_frames the frame loop of the render (`_frames.draw_frames`) given only those frames, over an opaque neutral backdrop,
                   a layout's asset slot filled with a flat generated image.
  contact_sheet    one ffmpeg command: the stills scaled into a grid, no text drawn.
  storyboard       all of it: refuses first, draws only the chosen frames, writes `beat-<n>.png` and `sheet.png`.

The `catalogue` verb of the same family (one clip per preset) reuses `synthetic_words` / `build_lists` / `draw_rest_frames`.
Nothing here reads a recording, a transcript or a person's file: the only inputs are the post (or one beat), the vocabulary and the
theme flags. Standard library only.
"""
from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
import tempfile
import zlib

import _align
import _edl
import _frames
import _media
import _render
from _text import Refusal, clean_text
from _vocab import SLOT_ID, slot_params, slot_types

BEAT_KEYS = {"preset", "params", "line"}
STILL_PREFIX, SHEET_NAME = "beat-", "sheet.png"
SOURCE_HASH = hashlib.sha256(b"openhora storyboard").hexdigest()      # the one synthetic "recording": nothing of a person's


# ---------------------------------------------------------------- the beats

def beat_row(vocab: dict, obj, number: int = 1) -> dict:
    """The row `_align.read_beats` gives a beat of a post, from one beat as JSON: {preset, params, line}. A slot parameter holds
    a description, as in a post; the values are checked when the beats list is built (`_vocab.check_params`)."""
    field = "beat%d" % number
    if not isinstance(obj, dict):
        raise Refusal("not_object", "beat")
    extra = set(obj) - BEAT_KEYS
    if extra:
        raise Refusal("unknown_key", "beat.%s" % sorted(extra)[0][:24])
    for key in ("preset", "params", "line"):
        if key not in obj:
            raise Refusal("missing_key", "beat.%s" % key)
    name = obj["preset"]
    if not isinstance(name, str) or name not in vocab["presets"]:
        raise Refusal("unknown_preset", field)
    if not isinstance(obj["params"], dict):
        raise Refusal("params_not_object", field)
    row = {"beat": number, "line": clean_text(obj["line"], vocab["limits"]["line_max"], field + ".line"), "preset": name, "params": {}, "slots": {}}
    declared = vocab["presets"][name]["params"]
    for key, value in obj["params"].items():
        if key not in declared:
            raise Refusal("undeclared_param", "%s.%s" % (field, str(key)[:24]))
        if slot_types(declared[key]):
            row["slots"][key] = clean_text(value, vocab["limits"]["slot_description_max"], "%s.%s" % (field, key))
        else:
            row["params"][key] = value
    return row


# ---------------------------------------------------------------- the synthetic words

def synthetic_words(rows: list, cfg: dict) -> tuple:
    """(transcript, analysis, ranges). The words of every beat's line, one every 1 / words_per_second seconds, each beat after the
    last with `beat_gap` seconds between them; the recording ends `trail` seconds after the last word. `ranges` maps a beat number to
    its (first word index, last word index). A document of the shapes `check_transcript` and `build_base` read, with no audio."""
    step = round(1.0 / cfg["words_per_second"], 6)
    words, segments, ranges, t = [], [], {}, 0.0
    for seg, row in enumerate(rows):
        first, seg_start = len(words), t
        for token in row["line"].split():
            words.append({"index": len(words), "text": token, "start": round(t, 6), "end": round(t + step, 6), "segment": seg})
            t += step
        if len(words) == first:
            raise Refusal("beat_without_words", "beat%d" % row["beat"])
        ranges[row["beat"]] = (first, len(words) - 1)
        segments.append({"index": seg, "start": round(seg_start, 6), "end": round(t, 6), "first_word": first, "last_word": len(words) - 1})
        t += cfg["beat_gap"]
    last_end = words[-1]["end"]
    duration = round(last_end + cfg["trail"], 6)
    transcript = {"schema_version": 1, "language": "en", "duration": duration, "words": words, "segments": segments}
    analysis = {"facts": {"duration": duration, "sha256": SOURCE_HASH, "width": 1080, "height": 1920, "has_audio": False}, "silences": None}
    return transcript, analysis, ranges


def build_lists(rows: list, data: dict, vocab: dict, allow: dict, *, colors=None, font_flags=None, face=None, cfg=None) -> tuple:
    """(edl, beats, notes, transcript, mentions) for the beats of `rows` that have a preset, every row's line being on the timeline.
    Runs the render's checks before it returns; raises the first Refusal. The list has no zoom and no push-in (the face box is the
    one given), and no cut: the word gaps are never longer than `gap` and the tail pad covers the trail."""
    cfg = cfg or data["storyboard"]
    if not rows:
        raise Refusal("no_beats", "post")
    transcript, analysis, ranges = synthetic_words(rows, cfg)
    if transcript["duration"] > data["limits"]["input_seconds_max"]:
        raise Refusal("script_too_long", "post")                           # a clear refusal, not the analysis check's
    edl, notes = _edl.build_base(transcript, analysis, data, allow, None, 3600.0, None, cfg["trail"], "bottom", colors, font_flags, face,
                                 "none", None, 0.0)
    with_preset = [r for r in rows if r["preset"]]
    results = [{"score": 1.0, "word_from": ranges[r["beat"]][0], "word_to": ranges[r["beat"]][1], "matched": True, "reordered": False}
               for r in with_preset]
    beats = _align.build_beats(with_preset, results, vocab, _align.DEFAULT_THRESHOLD, {})
    docs = _render.check_documents(data, edl, beats, None, vocab, allow)  # the credential scan is in here: nothing is drawn before it
    return edl, beats, notes, transcript, docs["mentions"]


def rest_frame(entry: dict, data: dict, fps: int) -> int:
    """The output frame where an entry is at rest: `settled` seconds (renderer-presets.json, per preset) after it starts, or, for a beat
    too short for that, its end less the preset's `tail` seconds less one frame; never before it starts, never after its last frame."""
    cfg = data["presets"][entry["preset"]]
    settled = entry["start_frame"] + int(math.ceil(cfg["settled"] * fps - 1e-9))
    last_calm = entry["end_frame"] - int(round(cfg["tail"] * fps)) - 1
    return max(entry["start_frame"], min(entry["end_frame"] - 1, settled, last_calm))


# ---------------------------------------------------------------- drawing

def parse_color(text: str) -> tuple:
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def flat_png(width: int, height: int, color: str) -> bytes:
    """A flat RGB PNG of one colour: the stand-in for a layout's asset. Deterministic bytes."""
    raw = (b"\x00" + bytes(parse_color(color)) * width) * height

    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def draw_rest_frames(*, data, vocab, allow, edl, beats, browser, jobs, work, time_limit, templates_dir=None, fonts_directory=None) -> dict:
    """Draw the rest frame of every beat of `beats` with the render's frame loop; every other frame of a beat goes through the page and the
    face-box check too (a card overshoots while it pops in) and is not written. Returns {entries (the timeline's, in order), frames
    ({beat number: PNG path}), rest ({beat number: output frame}), facts (what the loop reports), fonts, templates}.
    Only those frames are written; a card that touches the face box on any frame raises `overlay_hits_face`, as in a render."""
    cfg = data["storyboard"]
    timeline = _edl.resolve_timeline(edl, beats, vocab, data)
    entries = timeline["beats"]
    if not entries:
        raise Refusal("nothing_to_draw", "beats")
    timeline["captions"] = []                                             # captions are not drawn
    slots = {}
    for e in entries:
        for name in slot_params(vocab, e["preset"]):
            if name in e["params"]:
                slots[e["params"][name]] = None
    os.makedirs(os.path.join(work, "assets"), mode=0o700, exist_ok=True)
    paths = {}
    for slot in sorted(slots):
        if not SLOT_ID.fullmatch(slot):
            raise Refusal("bad_slot", slot[:32])
        paths[slot] = os.path.join(work, "assets", slot + ".png")
        with open(paths[slot], "wb") as fh:
            fh.write(flat_png(edl["size"][0], edl["size"][1], cfg["slot_fill"]))
    assets = _frames.load_assets(paths, {}, data["limits"])
    templates = {}
    for e in entries:
        templates[e["preset"]] = data["presets"][e["preset"]]["template"]
    tdir = templates_dir or _frames.TEMPLATES_DIR
    serve, tpl_hashes = _frames.load_templates(sorted(set(templates.values())), tdir)
    font_serve, fonts_used = _frames.load_fonts(edl["theme"]["fonts"], allow, data["limits"]["font_max_bytes"], fonts_directory)
    serve.update(font_serve)
    serve.update({"/assets/%s.%s" % (s, a["kind"]): (a["data"], _frames.ASSET_MIME[a["kind"]]) for s, a in assets.items()})
    rest = {e["beat"]: rest_frame(e, data, edl["fps"]) for e in entries}
    only = {("beat", f) for f in rest.values()}
    frames_dir = os.path.join(work, "frames")
    _, facts = _frames.draw_frames(
        data=data, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls=_render.font_urls_of(data, edl, font_serve), assets=assets,
        browser=browser, jobs_n=max(1, min(jobs, 8)), frames_dir=frames_dir, workdir=work, time_limit=time_limit, templates=templates,
        png_blank=_render.blank_png, only=only, check_all=True, backdrop={"color": cfg["backdrop"], "slot_fill": cfg["slot_fill"]})
    frames = {n: os.path.join(frames_dir, "beat_%06d.png" % f) for n, f in rest.items()}
    return {"entries": entries, "frames": frames, "rest": rest, "facts": facts, "fonts": fonts_used, "templates": tpl_hashes}


# ---------------------------------------------------------------- the contact sheet

def sheet_geometry(count: int, cfg: dict) -> dict:
    sheet = cfg["sheet"]
    cols = max(1, min(count, sheet["columns"]))
    rows = -(-count // cols)
    cell_w, cell_h = sheet["tile_width"] + sheet["gap"], sheet["tile_height"] + sheet["gap"]
    return {"columns": cols, "rows": rows, "cell_w": cell_w, "cell_h": cell_h, "width": cols * cell_w, "height": rows * cell_h}


def sheet_argv(ffmpeg: str, files: list, cfg: dict, out_name: str) -> list:
    """The one ffmpeg command of the sheet: every still scaled to a tile (the render's bitexact scale), padded by half the gap on each
    side and stacked in rows; the empty cells of the last row are the fill colour. No text is drawn."""
    sheet = cfg["sheet"]
    g = sheet_geometry(len(files), cfg)
    fill = "0x" + sheet["fill"][1:]
    chains = []
    for k in range(len(files)):
        chains.append("[%d:v]scale=%d:%d:flags=%s,format=rgb24,pad=%d:%d:%d:%d:color=%s[t%d]" % (
            k, sheet["tile_width"], sheet["tile_height"], _media.SWS, g["cell_w"], g["cell_h"], sheet["gap"] // 2, sheet["gap"] // 2, fill, k))
    if len(files) == 1:
        chains[0] = chains[0][:-4] + "[out]"
    else:
        layout = "|".join("%d_%d" % ((k % g["columns"]) * g["cell_w"], (k // g["columns"]) * g["cell_h"]) for k in range(len(files)))
        chains.append("%sxstack=inputs=%d:layout=%s:fill=%s[out]" % ("".join("[t%d]" % k for k in range(len(files))), len(files), layout, fill))
    argv = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-nostdin", "-filter_threads", str(_media.THREADS),
            "-filter_complex_threads", str(_media.THREADS), "-sws_flags", _media.SWS]
    for path in files:
        argv += ["-protocol_whitelist", "file", "-i", path]
    argv += ["-filter_complex", ";".join(chains), "-map", "[out]", "-frames:v", "1", "-map_metadata", "-1", "-fflags", "+bitexact",
             "-flags:v", "+bitexact", "-f", "image2", "-c:v", "png", out_name]
    return argv


def contact_sheet(ffmpeg: str, files: list, cfg: dict, out: str, scratch: str, timeout: float = 120) -> dict:
    """Write the sheet of `files` (PNG paths, in beat order) to `out`, working in a temporary folder under `scratch` (never in the output
    folder). Returns {file, sha256, tiles, columns, width, height}."""
    g = sheet_geometry(len(files), cfg)
    work = tempfile.mkdtemp(prefix=".sheet-", dir=scratch)
    try:
        _media.run(sheet_argv(ffmpeg, [os.path.abspath(f) for f in files], cfg, "sheet.png"), timeout, cwd=work)
        part = os.path.join(work, "sheet.png")
        if not os.path.isfile(part) or os.path.getsize(part) == 0:
            raise Refusal("sheet_failed", "sheet")
        _write_once(part, out)
    except _media.ToolError:
        raise Refusal("sheet_failed", "sheet") from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return {"file": os.path.basename(out), "sha256": _media.sha256_file(out), "tiles": len(files), "columns": g["columns"],
            "width": g["width"], "height": g["height"]}


# ---------------------------------------------------------------- the verb's body

def storyboard(*, rows: list, data: dict, vocab: dict, allow: dict, colors=None, font_flags=None, face=None, tools,
               jobs: int, out_dir: str, scratch=None, time_limit=None, templates_dir=None, fonts_directory=None) -> dict:
    """Refuse first, then draw. `tools` is a function that returns (ffmpeg path, browser path). `rows`: the beats (rows of `_align.read_beats` or `beat_row`). Writes `beat-<n>.png` for each beat that
    has a preset and `sheet.png` into `out_dir`, never over a file that is there. The result holds closed words and numbers."""
    cfg = data["storyboard"]
    edl, beats, notes, transcript, mentions = build_lists(rows, data, vocab, allow, colors=colors, font_flags=font_flags, face=face, cfg=cfg)
    ffmpeg, browser = tools()                                             # looked for only now: a refusal above needs neither
    os.makedirs(out_dir, mode=0o700, exist_ok=True)
    base = os.path.abspath(scratch) if scratch else tempfile.gettempdir()      # never the output folder
    work = tempfile.mkdtemp(prefix=".storyboard-", dir=base)
    os.chmod(work, 0o700)
    try:
        drawn = draw_rest_frames(data=data, vocab=vocab, allow=allow, edl=edl, beats=beats, browser=browser, jobs=jobs, work=work,
                                 time_limit=time_limit or cfg["time_limit_seconds"], templates_dir=templates_dir, fonts_directory=fonts_directory)
        order = sorted(drawn["frames"])
        files = []
        for n in order:
            dest = os.path.join(out_dir, "%s%d.png" % (STILL_PREFIX, n))
            _write_once(drawn["frames"][n], dest)
            files.append(dest)
        sheet = contact_sheet(ffmpeg, files, cfg, os.path.join(out_dir, SHEET_NAME), work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    by_beat = {e["beat"]: e for e in drawn["entries"]}
    return {"ok": True, "beats": [{"beat": n, "preset": by_beat[n]["preset"], "file": "%s%d.png" % (STILL_PREFIX, n),
                                   "sha256": _media.sha256_file(os.path.join(out_dir, "%s%d.png" % (STILL_PREFIX, n))), "frame": drawn["rest"][n]} for n in order],
            "sheet": sheet, "skipped": [r["beat"] for r in rows if not r["preset"]], "words": len(transcript["words"]),
            "frame_jobs": drawn["facts"]["frames_rendered"] + drawn["facts"]["frames_reused"], "frames_checked": drawn["facts"]["frame_jobs"], "jobs": jobs, "face_box": edl["face_box"], "fonts": drawn["fonts"],
            "templates": drawn["templates"], "font_fallbacks": notes, "mentions": mentions,
            "browser": drawn["facts"].get("browser"), "browser_sandbox": drawn["facts"].get("browser_sandbox")}


def _write_once(src: str, dest: str) -> None:
    """Copy a still to its name in the output folder with O_EXCL (mode 0600). A file of that name with the same bytes is a replay;
    one with other bytes is refused and left alone."""
    try:
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if _media.sha256_file(dest) != _media.sha256_file(src):
            raise Refusal("name_collision", "output") from None
        return
    try:
        with os.fdopen(fd, "wb") as out, open(src, "rb") as fh:
            shutil.copyfileobj(fh, out, 1 << 20)
    except BaseException:
        os.unlink(dest)
        raise

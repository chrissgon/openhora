"""The edit list: the base list code builds, its check, and the timeline the render draws.

The edit list (the file `base` writes) is renderer-neutral. It holds frame ranges, word indices, preset names, typed
parameter values, slot ids and theme tokens, and nothing a renderer would run: no filter text, no path, no URL, no
caption text a person did not say, no ASS override. `beats.json` (the file `align` writes) holds the beats'
overlays and layouts by word index. `check` validates both, `resolve_timeline` turns them into frame ranges.

Every document is closed: a key that is not listed is refused. Standard library only.
"""
from __future__ import annotations

import math
import re

import _blocks
import _media
import _redact
from _align import norm_tokens, token_sim
from _retakes import KINDS as RETAKE_KINDS, REASONS as RETAKE_REASONS, detect_retakes
from _layout import zones  # noqa: F401  (moved: `_edl.zones` is still the name callers and tests use)
from _text import Refusal, clean_text
from _timeline import (build_words, caption_chunks, check_transcript, retime_misplaced, kept_ranges, normalise_words, find_phantoms, out_frames_of)
from _vocab import HEX_COLOR, check_params, script_section, slot_params

EDL_SCHEMA_VERSION = 2     # 2: zoom.anchor_y is required and normalisation lists retimed_words and unplaced_words (and, optionally, phantom_words)
BEATS_SCHEMA_VERSION = 1
SHA256 = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
MENTION = re.compile(r"(?<![\w@])@[\w.]{1,30}")
EDL_KEYS = {"schema_version", "fps", "size", "source", "kept", "out_frames", "words", "captions", "theme", "normalisation", "face_box", "zoom",
            "proposals"}
PROPOSAL_REQUIRED = {"id", "kind", "word_from", "word_to", "keep_from", "seconds", "confirmed"}
PROPOSAL_KEYS = PROPOSAL_REQUIRED | {"default", "reason"}      # `default` and `reason` are optional: a list written before them reads as `keep`
RETAKE_MODES = ("auto", "propose")
SOURCE_KEYS = {"sha256", "duration", "width", "height", "has_audio", "color_matrix"}
BEATS_REQUIRED = {"schema_version", "threshold", "overlays", "layouts", "slots", "report", "unmatched", "fallbacks"}
BEATS_KEYS = BEATS_REQUIRED | {"script", "punches", "effects"}      # `script`, `punches` and `effects` are optional: a beats file without them stays valid, schema_version 1
PUNCH_KEYS = {"beat", "word_from", "word_to", "score"}               # a script punch: the beat's number and the words it was aligned to
EFFECT_KEYS = {"id", "kind", "word_from", "word_to"}                 # a review effect (V9a-3)
EFFECT_KINDS = ("punch", "flash", "dip", "mono", "tint")
GRADE_KINDS = ("flash", "dip", "mono", "tint")                       # the effects that change the colour of the base picture
OVERLAY_GRADES = ("flash", "dip", "tint")                            # the grades drawn as one colour laid over the picture (the page's `#fx`); mono is a filter
EFFECT_ID = re.compile(r"e[1-6]")
EFFECTS_MAX = 6                 # review effects in one beats.json (the script's punches are counted apart: the skill's checker spaces them)
FLASH_FRAMES_MAX = 4            # the hard bounds of a grade (D9, principle 13): a configuration file never widens them
DIP_FRAMES_MAX = 6
FLASHES_MAX = 2                 # flashes and dips together in one video
GRADE_SECONDS_MAX = 4.0         # mono and tint
FLASH_ALPHA_MAX = 0.85          # the strongest frame of a flash or a dip, and the tint's alpha: the spec's own values, which the configuration may lower and never raise
TINT_ALPHA_MAX = 0.18
PUNCH_SHORT_SECONDS = 0.4       # a punch clipped to less than this is not drawn
ENTRY_REQUIRED = {"id", "beat", "preset", "params", "word_from", "word_to", "score"}
ENTRY_KEYS = ENTRY_REQUIRED | {"role", "emphasis", "block"}      # the beat's role and emphasis from the script, and the block that draws it, all optional
SCRIPT_KEYS = {"title", "loop"}
SLOT_KEYS = {"slot", "beat", "param", "type", "description"}
NORMALISATION_KEYS = {"words", "dropped_words", "dropped_segments", "zero_length_words", "spread_runs", "estimated_words", "clamped_starts", "retimed_words", "unplaced_words",
                      "phantom_words"}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def closed(obj, keys: set, field: str, required=None) -> None:
    if not isinstance(obj, dict):
        raise Refusal("not_object", field)
    extra = set(obj) - keys
    if extra:
        raise Refusal("unknown_key", "%s.%s" % (field, sorted(extra)[0]))
    for k in (keys if required is None else required):
        if k not in obj:
            raise Refusal("missing_key", "%s.%s" % (field, k))


def theme_defaults(data: dict) -> dict:
    t = data["theme"]
    return {"colors": dict(t["colors"]),
            "fonts": {r: {"id": "default", "weight": t["default_font_weight"][r]} for r in t["font_roles"]}}


def union(boxes: list) -> dict:
    left, top = min(b["x"] for b in boxes), min(b["y"] for b in boxes)
    right, bottom = max(b["x"] + b["w"] for b in boxes), max(b["y"] + b["h"] for b in boxes)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def check_face(data: dict, face, field: str = "face_box", zoom=None) -> dict:
    """A face box {x, y, w, h} in frame pixels, inside the frame, that leaves room above it for a card and below it for a
    caption. With `zoom` (the edit list's zoom block) the room is measured on the box at its largest, when a range is drawn at
    the zoom factor with the whole push-in: the picture grows about the zoom's fixed point, so the face's box grows and moves."""
    closed(face, {"x", "y", "w", "h"}, field)
    if not all(_int(face[k]) for k in "xywh") or face["w"] < 100 or face["h"] < 100 or face["x"] < 0 or face["y"] < 0 \
            or face["x"] + face["w"] > data["frame"]["width"] or face["y"] + face["h"] > data["frame"]["height"]:
        raise Refusal("bad_face_box", field)
    worst = face
    if zoom is not None:
        w, h = data["frame"]["width"], data["frame"]["height"]
        anchor = _media.anchor_point(face, zoom["anchor_y"])
        top = zoom["factor"] if zoom["mode"] == "alternate" else 1.0
        most = top * (1.0 + zoom["push_in"])
        worst = union([face, _media.zoomed_box(face, top, most, anchor, w, h)])
    z = zones(data, worst)
    if z["card"][1] - z["card"][0] < data["zones"]["card_min_height"] or z["caption"][1] - z["caption"][0] < data["zones"]["caption_min_height"]:
        raise Refusal("face_box_leaves_no_room", field)
    return face


def range_faces(edl: dict, data: dict) -> list:
    """For each kept range: (first output frame, last output frame + 1, the face box as it lands in that range)."""
    w, h = data["frame"]["width"], data["frame"]["height"]
    anchor = _media.anchor_point(edl["face_box"], edl["zoom"]["anchor_y"])
    rows, pos = [], 0
    for k, (a, b) in enumerate(edl["kept"]):
        z0, z1 = _media.zoom_levels(edl["zoom"], k, b - a, edl["fps"])
        rows.append((pos, pos + b - a, _media.zoomed_box(edl["face_box"], z0, z1, anchor, w, h)))
        pos += b - a
    return rows


def span_face(edl: dict, data: dict, start_frame: int, end_frame: int, punches=()) -> dict:
    """The face box over a span of output frames: the union of its boxes in the kept ranges the span touches, so that a card or a
    caption that lives through a zoom change stays clear of the face in every range. `punches` (the rows `resolve_effects` made, each with
    its `face`) that the span touches add the face as the punch draws it."""
    boxes = [box for a, b, box in range_faces(edl, data) if a < end_frame and start_frame < b]
    boxes += [p["face"] for p in punches if p["start_frame"] < end_frame and start_frame < p["end_frame"]]
    return union(boxes or [edl["face_box"]])


def parse_face_box(text: str) -> dict:
    parts = text.split(",")
    if len(parts) != 4 or not all(p.strip().lstrip("-").isdigit() for p in parts):
        raise Refusal("bad_face_box", "face_box")
    x, y, w, h = (int(p) for p in parts)
    return {"x": x, "y": y, "w": w, "h": h}


# ---------------------------------------------------------------- the base list

def build_base(transcript_doc, analysis: dict, data: dict, fonts: dict, fps=None, gap=None, pad_head=None, pad_tail=None,
               caption_position="bottom", colors=None, font_flags=None, face_box=None, zoom_mode=None, zoom_factor=None,
               push_in=None, confirm=(), long_cut=None, wordless_max=None, anchor_y=None, keep=(), retake_mode="auto") -> tuple:
    """The code-generated base edit list from a transcript and an analysis. No model.

    Silence is the cut signal (`analysis["silences"]`; `None` when the recording has no audio, then the word gaps
    decide); the words only protect speech. Retakes are found by rule (`_retakes`) and written into the list as proposals, each with
    a `default` (`cut` or `keep`) and a `reason`. `retake_mode` `auto` cuts every proposal whose default is `cut` except those named in
    `keep`, and those named in `confirm`; `propose` cuts only `confirm`. An id in both `keep` and `confirm` is refused. A cut of `long_cut` seconds or more
    also takes the wordless sound of more than `wordless_max` seconds at its edges. `face_box` is {x, y, w, h} in
    frame pixels (the person gives it once per recording; a default is used otherwise). `zoom_mode` is `alternate` (every
    second kept range is drawn at `zoom_factor`, about a fixed point: the face's centre, `anchor_y` of the box's height down
    from its top) or `none`; `push_in` is a slow extra zoom over each kept range of 5 s or more (0 for none).

    `fonts` maps an allow-listed font id to its row. `colors` is {token: #RRGGBB}; `font_flags` is {role: (id, weight)};
    a font id that is not allow-listed falls back to `default`, and the fallback is returned in the second value
    (the notes the caller prints: they are the approval card's "font used")."""
    frame, limits, cuts, zoom_cfg = data["frame"], data["limits"], data["cuts"], data["zoom"]
    fps = fps or frame["fps"]
    if not _int(fps) or not frame["fps_min"] <= fps <= frame["fps_max"]:
        raise Refusal("bad_fps", "fps")
    gap = cuts["gap"] if gap is None else gap
    pad_head = cuts["pad_head"] if pad_head is None else pad_head
    pad_tail = cuts["pad_tail"] if pad_tail is None else pad_tail
    facts = analysis.get("facts") if isinstance(analysis, dict) else None
    if not isinstance(facts, dict) or not _num(facts.get("duration")) or not SHA256.fullmatch(str(facts.get("sha256"))):
        raise Refusal("analysis_schema", "analysis")
    for key in ("width", "height"):
        if not _int(facts.get(key)) or not 0 < facts[key] < 100000:
            raise Refusal("analysis_schema", "analysis.facts." + key)
    silences = analysis.get("silences")
    if silences is not None:
        if not isinstance(silences, list) or len(silences) > 20000:
            raise Refusal("analysis_schema", "analysis.silences")
        for s in silences:
            if not isinstance(s, dict) or not _num(s.get("start")) or not _num(s.get("end")) or not 0 <= s["start"] <= s["end"] <= facts["duration"] + 1:
                raise Refusal("analysis_schema", "analysis.silences")
    tr = check_transcript(transcript_doc, limits)
    duration = float(facts["duration"])
    if not 0 < duration <= limits["input_seconds_max"] + 1:
        raise Refusal("analysis_schema", "analysis.duration")
    if tr["duration"] > duration + 1.0:
        raise Refusal("transcript_longer_than_recording", "transcript")
    sil = None if silences is None else [(s["start"], s["end"]) for s in silences]
    # a transcriber's repetition hallucination in a silence (a run of zero-length words that repeats the words just before it): never spoken, dropped
    # before anything else reads the words: no island range, no caption, no retake evidence. Their indices stay (nothing is renumbered)
    # and the runs are listed in `normalisation.phantom_words` for the review.
    runs = find_phantoms(tr["words"], sil, cuts["phantom_max_seconds"], cuts["phantom_run_min"], cuts["phantom_edge_seconds"], cuts["phantom_repeat_min"])
    words, report = normalise_words(tr["words"], tr["segments"], duration, {i for run in runs for i in run})
    report["phantom_words"] = [{"from": run[0], "to": run[-1], "count": len(run)} for run in runs]
    live = [w for w in words if not w["dropped"]]
    if not live:
        raise Refusal("no_words", "transcript")
    if retake_mode not in RETAKE_MODES:
        raise Refusal("bad_choice", "retakes")
    proposals = detect_retakes(live, tr["language"], data["retakes"], sil)
    both = sorted(set(confirm) & set(keep))
    if both:
        raise Refusal("retake_conflict", both[0][:32])
    unknown = sorted((set(confirm) | set(keep)) - {p["id"] for p in proposals})
    if unknown:
        raise Refusal("unknown_proposal", unknown[0][:32])
    cut_ids = set(confirm)
    if retake_mode == "auto":
        cut_ids |= {p["id"] for p in proposals if p["default"] == "cut"} - set(keep)
    forced = []
    by_index = {w["index"]: w for w in live}
    for p in proposals:
        if p["id"] not in cut_ids:
            continue
        p["confirmed"] = True
        first, last = by_index[p["word_from"]], by_index[p["word_to"]]
        keep = by_index[p["keep_from"]]
        # The words of a confirmed retake count nowhere in the cut planning: the cut runs from the end of the last word that stays before
        # it plus that word's tail pad, never later than the retake's first word starts, to the first word that stays after it less
        # its head pad.
        before = [w for w in live if w["index"] < p["word_from"] and not w["dropped"]]
        lo = first["start"]
        if before:
            lo = min(before[-1]["end"] + pad_tail, first["start"])
        hi = keep["start"] - pad_head
        if hi > lo:
            forced.append((lo, hi))
        for w in live:
            if p["word_from"] <= w["index"] <= p["word_to"]:
                w["dropped"] = True
    kept_words = [w for w in live if not w["dropped"]]
    if not kept_words:
        raise Refusal("nothing_kept", "transcript")
    long_cut = cuts["long_cut"] if long_cut is None else long_cut
    wordless_max = cuts["wordless_max"] if wordless_max is None else wordless_max
    if not _num(long_cut) or not _num(wordless_max) or long_cut < 0 or wordless_max < 0:
        raise Refusal("bad_cut_setting", "cuts")
    retimed, unplaced = retime_misplaced(live, sil)           # `live` still holds the words of the confirmed retakes, flagged dropped: walls          # before the cuts are planned: they protect each word where it is said
    gone = {w["index"] for w in unplaced}
    kept_words = [w for w in kept_words if w["index"] not in gone]
    if not kept_words:
        raise Refusal("nothing_kept", "transcript")
    kept = kept_ranges(kept_words, duration, fps, sil, pad_head, pad_tail, cuts["min_cut"], cuts["min_kept"], gap, forced, long_cut, wordless_max,
                       cuts["wordless_keep"])
    if not kept:
        raise Refusal("nothing_kept", "transcript")
    if len(kept) > limits["kept_ranges_max"]:
        raise Refusal("too_many_cuts", "kept")
    out_words = build_words(words, kept, fps, gone)
    if not out_words:
        raise Refusal("nothing_kept", "transcript")
    report["retimed_words"] = retimed
    report["unplaced_words"] = [{"index": w["index"], "start": round(w["start"], 3), "end": round(w["end"], 3)} for w in unplaced]
    cap = data["caption"]
    if caption_position not in cap["positions"]:
        raise Refusal("bad_choice", "caption_position")
    theme = theme_defaults(data)
    palette = set(data["theme"]["colors"])
    for token, value in (colors or {}).items():
        if token not in palette:
            raise Refusal("unknown_token", "color.%s" % token)
        if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
            raise Refusal("bad_color", "color.%s" % token)
        theme["colors"][token] = value.upper()
    notes = []
    for role, (font_id, weight) in (font_flags or {}).items():
        if role not in data["theme"]["font_roles"]:
            raise Refusal("bad_font_role", "font.%s" % role)
        if weight not in range(100, 1000, 100):
            raise Refusal("bad_font_weight", "font.%s" % role)
        if font_id in fonts:
            theme["fonts"][role] = {"id": font_id, "weight": weight}
        else:
            notes.append({"role": role, "asked": font_id, "used": "default", "reason": "not in the font allow-list"})
    mode = zoom_cfg["default_mode"] if zoom_mode is None else zoom_mode
    factor = zoom_cfg["factor"] if zoom_factor is None else zoom_factor
    zoom = {"mode": mode, "factor": factor, "push_in": zoom_cfg["push_in"] if push_in is None else push_in,
            "anchor_y": zoom_cfg["anchor_y"] if anchor_y is None else anchor_y}
    check_zoom(data, zoom)
    face = check_face(data, dict(data["face_box_default"] if face_box is None else face_box), "face_box", zoom)
    edl = {"schema_version": EDL_SCHEMA_VERSION, "fps": fps, "size": [frame["width"], frame["height"]],
           "source": {"sha256": facts["sha256"], "duration": round(duration, 3), "width": facts["width"], "height": facts["height"],
                      "has_audio": bool(facts["has_audio"]),
                      "color_matrix": "auto" if facts.get("color_space") not in (None, "unknown", "bt709") else "bt709"},
           "kept": kept, "out_frames": out_frames_of(kept), "words": out_words,
           "captions": {"position": caption_position, "chunks": caption_chunks(out_words, cap["max_words"], cap["max_chars"], cap["pause"])},
           "theme": theme, "normalisation": report, "face_box": face, "zoom": zoom, "proposals": proposals}
    return edl, notes


def check_zoom(data: dict, zoom, field: str = "zoom") -> None:
    cfg = data["zoom"]
    closed(zoom, {"mode", "factor", "push_in", "anchor_y"}, field)
    if zoom["mode"] not in cfg["modes"]:
        raise Refusal("bad_choice", field + ".mode")
    if not _num(zoom["factor"]) or not 1.0 <= zoom["factor"] <= cfg["factor_max"]:
        raise Refusal("bad_zoom", field + ".factor")
    if not _num(zoom["push_in"]) or not 0 <= zoom["push_in"] <= cfg["push_in_max"]:
        raise Refusal("bad_zoom", field + ".push_in")
    if not _num(zoom["anchor_y"]) or not 0 <= zoom["anchor_y"] <= 1:
        raise Refusal("bad_zoom", field + ".anchor_y")


# ---------------------------------------------------------------- checks

def scan_texts(texts: list) -> None:
    """Refuse a text shaped like a credential, with the formats of scripts/redact.py. The match is never echoed."""
    for field, text in texts:
        if (_redact.token_label(text) or _redact.secret_values(text) or _redact.ASSIGN_RE.search(text)
                or _redact.URL_CREDENTIAL_RE.search(text)):
            raise Refusal("credential_shaped", field)


def mentions_of(texts: list) -> list:
    found = []
    for _, text in texts:
        for m in MENTION.findall(text):
            if m not in found:
                found.append(m)
    return found


def check_edl(edl, data: dict, vocab: dict, fonts: dict, platform=None) -> dict:
    """Validate the base list. Returns {texts: [(field, text)], mentions: []} for the caller's scans; raises Refusal."""
    limits, frame = data["limits"], data["frame"]
    closed(edl, EDL_KEYS, "edl")
    if edl["schema_version"] == 1:
        raise Refusal("edl_schema_outdated", "edl")      # a version 1 list has no zoom.anchor_y: make it again with `base`
    if edl["schema_version"] != EDL_SCHEMA_VERSION:
        raise Refusal("schema_version", "edl")
    fps = edl["fps"]
    if not _int(fps) or not frame["fps_min"] <= fps <= frame["fps_max"]:
        raise Refusal("bad_fps", "edl.fps")
    if edl["size"] != [frame["width"], frame["height"]]:
        raise Refusal("bad_size", "edl.size")
    src = edl["source"]
    closed(src, SOURCE_KEYS, "edl.source")
    if not SHA256.fullmatch(str(src["sha256"])) or not _num(src["duration"]) or src["duration"] <= 0 \
            or not isinstance(src["has_audio"], bool) or src["color_matrix"] not in ("bt709", "auto") \
            or not _int(src["width"]) or not _int(src["height"]):
        raise Refusal("bad_source", "edl.source")
    kept = edl["kept"]
    if not isinstance(kept, list) or not kept or len(kept) > limits["kept_ranges_max"]:
        raise Refusal("bad_kept", "edl.kept")
    last, total_src = 0, int(math.floor(src["duration"] * fps + 1e-6))
    for k, r in enumerate(kept):
        if not (isinstance(r, list) and len(r) == 2 and all(_int(x) for x in r)) or not 0 <= r[0] < r[1] or r[0] < last or r[1] > total_src:
            raise Refusal("bad_kept", "edl.kept[%d]" % k)
        last = r[1]
    if edl["out_frames"] != out_frames_of(kept) or not 0 < edl["out_frames"] <= limits["frames_max"]:
        raise Refusal("bad_out_frames", "edl.out_frames")
    if platform is not None:
        max_s = (platform.get("video") or {}).get("max_seconds")
        if max_s is not None and edl["out_frames"] > math.ceil(max_s * fps):
            raise Refusal("longer_than_platform", "edl.out_frames")
        if platform.get("post", {}).get("shape") != "video_with_caption":
            raise Refusal("platform_has_no_video", "platform")
    words = edl["words"]
    if not isinstance(words, list) or not words or len(words) > limits["words_max"]:
        raise Refusal("bad_words", "edl.words")
    prev_index, prev_start, texts = -1, 0.0, []
    out_seconds = edl["out_frames"] / fps
    for k, w in enumerate(words):
        closed(w, {"index", "text", "start", "end", "estimated"}, "edl.words[%d]" % k, {"index", "text", "start", "end"})
        if not _int(w["index"]) or w["index"] <= prev_index:
            raise Refusal("word_index", "edl.words[%d]" % k)
        if not _num(w["start"]) or not _num(w["end"]) or w["start"] < prev_start - 1e-6 or w["end"] < w["start"] \
                or w["end"] > out_seconds + 0.5:
            raise Refusal("word_time", "edl.words[%d]" % k)
        if "estimated" in w and w["estimated"] is not True:
            raise Refusal("word_estimated", "edl.words[%d]" % k)
        if clean_text(w["text"], limits["word_chars_max"], "edl.words[%d]" % k) != w["text"]:
            raise Refusal("text_not_clean", "edl.words[%d]" % k)
        prev_index, prev_start = w["index"], w["start"]
        texts.append(("edl.words[%d]" % k, w["text"]))
    index_set = {w["index"] for w in words}
    caps = edl["captions"]
    closed(caps, {"position", "chunks"}, "edl.captions")
    if caps["position"] not in data["caption"]["positions"]:
        raise Refusal("bad_choice", "edl.captions.position")
    last_to = -1
    if not isinstance(caps["chunks"], list) or not caps["chunks"]:
        raise Refusal("bad_chunks", "edl.captions.chunks")
    for k, c in enumerate(caps["chunks"]):
        if not (isinstance(c, list) and len(c) == 2 and all(_int(x) for x in c)) or c[0] > c[1] or c[0] <= last_to \
                or c[0] not in index_set or c[1] not in index_set:
            raise Refusal("bad_chunks", "edl.captions.chunks[%d]" % k)
        last_to = c[1]
    theme = edl["theme"]
    closed(theme, {"colors", "fonts"}, "edl.theme")
    palette = set(data["theme"]["colors"])
    if not isinstance(theme["colors"], dict) or set(theme["colors"]) != palette:
        raise Refusal("bad_theme", "edl.theme.colors")
    for token, value in theme["colors"].items():
        if not isinstance(value, str) or not HEX_COLOR.fullmatch(value):
            raise Refusal("bad_color", "edl.theme.colors.%s" % token)
    if not isinstance(theme["fonts"], dict) or set(theme["fonts"]) != set(data["theme"]["font_roles"]):
        raise Refusal("bad_theme", "edl.theme.fonts")
    for role, f in theme["fonts"].items():
        closed(f, {"id", "weight"}, "edl.theme.fonts.%s" % role)
        if f["id"] != "default" and f["id"] not in fonts:
            raise Refusal("font_not_allowed", "edl.theme.fonts.%s" % role)
        if f["weight"] not in range(100, 1000, 100):
            raise Refusal("bad_font_weight", "edl.theme.fonts.%s" % role)
    norm = edl["normalisation"]
    closed(norm, NORMALISATION_KEYS, "edl.normalisation", NORMALISATION_KEYS - {"phantom_words"})      # phantom_words is optional: an older list has none
    for k, run in enumerate(norm.get("phantom_words", [])):
        field = "edl.normalisation.phantom_words[%d]" % k
        if k >= 2000 or not isinstance(run, dict):
            raise Refusal("bad_normalisation", field)
        closed(run, {"from", "to", "count"}, field)
        if not all(_int(run[x]) and run[x] >= 0 for x in ("from", "to", "count")) or run["to"] < run["from"] or run["count"] < 1:
            raise Refusal("bad_normalisation", field)
    for key, shape in (("retimed_words", {"index", "from", "to"}), ("unplaced_words", {"index", "start", "end"})):
        rows = norm[key]
        if not isinstance(rows, list) or len(rows) > 2000:
            raise Refusal("bad_normalisation", "edl.normalisation." + key)
        for k, p in enumerate(rows):
            field = "edl.normalisation.%s[%d]" % (key, k)
            closed(p, shape, field)
            vals = [p["from"], p["to"]] if key == "retimed_words" else [[p["start"], p["end"]]]
            if not _int(p["index"]) or p["index"] < 0 or not all(isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v) for v in vals):
                raise Refusal("bad_normalisation", field)
    check_face(data, edl["face_box"], "edl.face_box", edl["zoom"])
    check_zoom(data, edl["zoom"], "edl.zoom")
    props = edl["proposals"]
    if not isinstance(props, list) or len(props) > 100:
        raise Refusal("bad_proposals", "edl.proposals")
    seen = set()
    for k, p in enumerate(props):
        field = "edl.proposals[%d]" % k
        closed(p, PROPOSAL_KEYS, field, PROPOSAL_REQUIRED)
        if not isinstance(p["id"], str) or not ID.fullmatch(p["id"]) or p["id"] in seen or p["kind"] not in RETAKE_KINDS \
                or ("default" in p and p["default"] not in ("cut", "keep")) or ("reason" in p and p["reason"] not in RETAKE_REASONS) \
                or not all(_int(p[x]) and p[x] >= 0 for x in ("word_from", "word_to", "keep_from")) or p["word_from"] > p["word_to"] \
                or p["keep_from"] <= p["word_to"] or not _num(p["seconds"]) or not isinstance(p["confirmed"], bool):
            raise Refusal("bad_proposals", field)
        seen.add(p["id"])
        live_in = [i for i in range(p["word_from"], p["word_to"] + 1) if i in index_set]
        if p["confirmed"] and live_in:
            raise Refusal("confirmed_drop_still_drawn", field)
    scan_texts([("transcript", " ".join(w["text"] for w in words))])
    scan_texts(texts)
    return {"texts": texts, "mentions": mentions_of(texts), "indices": index_set}


def check_role_emphasis(obj: dict, vocab: dict, field: str) -> None:
    """`role` and `emphasis`, when present, are values of the vocabulary's closed lists (version 2 of the file)."""
    script = script_section(vocab)
    for key, listed in (("role", "roles"), ("emphasis", "emphasis")):
        if key in obj and (script is None or obj[key] not in script[listed]):
            raise Refusal("bad_" + key, "%s.%s" % (field, key))


def check_script_object(obj, vocab: dict) -> list:
    """The `script` object of beats.json: closed keys, a bounded hardened title, a boolean loop. Returns the texts to scan."""
    script = script_section(vocab)
    closed(obj, SCRIPT_KEYS, "beats.script", required=())
    if script is None:
        raise Refusal("script_without_vocabulary", "beats.script")
    texts = []
    if "title" in obj:
        if clean_text(obj["title"], script["limits"]["title_max"], "beats.script.title") != obj["title"]:
            raise Refusal("text_not_clean", "beats.script.title")
        texts.append(("beats.script.title", obj["title"]))
    if "loop" in obj and not isinstance(obj["loop"], bool):
        raise Refusal("bad_loop", "beats.script.loop")
    return texts


def check_beats(beats, edl, vocab: dict) -> dict:
    """Validate beats.json against the base list and the vocabulary. Returns {texts, mentions}; raises Refusal."""
    closed(beats, BEATS_KEYS, "beats", BEATS_REQUIRED)
    if beats["schema_version"] != BEATS_SCHEMA_VERSION or not _num(beats["threshold"]) or not 0 < beats["threshold"] <= 1:
        raise Refusal("schema_version", "beats")
    index_set = {w["index"] for w in edl["words"]}
    texts, seen_ids, slot_ids_used = [], set(), set()
    total = 0
    for bucket, kind in (("overlays", "overlay"), ("layouts", "layout")):
        entries = beats[bucket]
        if not isinstance(entries, list):
            raise Refusal("not_list", "beats.%s" % bucket)
        for k, e in enumerate(entries):
            field = "beats.%s[%d]" % (bucket, k)
            total += 1
            closed(e, ENTRY_KEYS, field, ENTRY_REQUIRED)
            check_role_emphasis(e, vocab, field)
            if "block" in e and (not isinstance(e["block"], str) or not _blocks.NAME.fullmatch(e["block"])):
                raise Refusal("bad_block", field + ".block")
            if not isinstance(e["id"], str) or not ID.fullmatch(e["id"]) or e["id"] in seen_ids:
                raise Refusal("bad_id", field)
            seen_ids.add(e["id"])
            if not _int(e["beat"]) or e["beat"] < 1:
                raise Refusal("bad_beat", field)
            if e["preset"] not in vocab["presets"] or vocab["presets"][e["preset"]]["kind"] != kind:
                raise Refusal("bad_preset", field)
            clean = check_params(vocab, e["preset"], e["params"], field + ".params")
            if clean != e["params"]:
                raise Refusal("text_not_clean", field + ".params")
            for name in slot_params(vocab, e["preset"]):
                if name in e["params"]:
                    slot_ids_used.add(e["params"][name])
            for name, value in e["params"].items():
                if isinstance(value, str):
                    texts.append((field + ".params." + name, value))
            if not _int(e["word_from"]) or not _int(e["word_to"]) or e["word_from"] > e["word_to"] \
                    or e["word_from"] not in index_set or e["word_to"] not in index_set:
                raise Refusal("bad_word_range", field)
            if not _num(e["score"]) or not 0 <= e["score"] <= 1:
                raise Refusal("bad_score", field)
    if total > vocab["limits"]["beats_max"]:
        raise Refusal("too_many_beats", "beats")
    if not isinstance(beats["slots"], list):
        raise Refusal("not_list", "beats.slots")
    slot_seen = set()
    for k, s in enumerate(beats["slots"]):
        closed(s, SLOT_KEYS, "beats.slots[%d]" % k)
        if not isinstance(s["slot"], str) or not ID.fullmatch(s["slot"]) or s["slot"] in slot_seen:
            raise Refusal("bad_slot", "beats.slots[%d]" % k)
        slot_seen.add(s["slot"])
        clean_text(s["description"], vocab["limits"]["slot_description_max"], "beats.slots[%d].description" % k)
        texts.append(("beats.slots[%d].description" % k, s["description"]))
    if not slot_ids_used <= slot_seen:
        raise Refusal("slot_without_description", "beats.slots")
    for key in ("report", "fallbacks", "unmatched"):
        if not isinstance(beats[key], list):
            raise Refusal("not_list", "beats.%s" % key)
    for k, item in enumerate(beats["report"]):
        if isinstance(item, dict):
            check_role_emphasis(item, vocab, "beats.report[%d]" % k)
    if "script" in beats:
        texts.extend(check_script_object(beats["script"], vocab))
    check_punches(beats.get("punches", []), index_set, vocab)
    check_effects(beats.get("effects", []), index_set)
    scan_texts(texts)
    return {"texts": texts, "mentions": mentions_of(texts)}


def _word_span(e: dict, index_set: set, field: str) -> None:
    if not _int(e["word_from"]) or not _int(e["word_to"]) or e["word_from"] > e["word_to"] \
            or e["word_from"] not in index_set or e["word_to"] not in index_set:
        raise Refusal("bad_word_range", field)


def check_punches(punches, index_set: set, vocab: dict) -> None:
    """The script's punches in beats.json: closed rows of a beat number, a word range of the edit list and a score, one per beat."""
    if not isinstance(punches, list):
        raise Refusal("not_list", "beats.punches")
    if len(punches) > vocab["limits"]["beats_max"]:
        raise Refusal("too_many_punches", "beats.punches")
    seen = set()
    for k, p in enumerate(punches):
        field = "beats.punches[%d]" % k
        closed(p, PUNCH_KEYS, field)
        if not _int(p["beat"]) or p["beat"] < 1 or p["beat"] in seen:
            raise Refusal("bad_beat", field)
        seen.add(p["beat"])
        _word_span(p, index_set, field)
        if not _num(p["score"]) or not 0 <= p["score"] <= 1:
            raise Refusal("bad_score", field)


def check_effects(effects, index_set: set) -> None:
    """The review effects in beats.json: at most EFFECTS_MAX, each a closed row of an id (`e1` to `e6`, once), a kind and a word range;
    two grades never share a word (`effect_overlap`), and at most FLASHES_MAX flashes and dips together (`too_many_flashes`)."""
    if not isinstance(effects, list):
        raise Refusal("not_list", "beats.effects")
    if len(effects) > EFFECTS_MAX:
        raise Refusal("too_many_effects", "beats.effects")
    seen, grades = set(), []
    for k, e in enumerate(effects):
        field = "beats.effects[%d]" % k
        closed(e, EFFECT_KEYS, field)
        if not isinstance(e["id"], str) or not EFFECT_ID.fullmatch(e["id"]) or e["id"] in seen:
            raise Refusal("bad_id", field)
        seen.add(e["id"])
        if e["kind"] not in EFFECT_KINDS:
            raise Refusal("bad_effect", field)
        _word_span(e, index_set, field)
        if e["kind"] in GRADE_KINDS:
            if any(e["word_from"] <= g["word_to"] and g["word_from"] <= e["word_to"] for g in grades):
                raise Refusal("effect_overlap", field)
            grades.append(e)
    if sum(1 for g in grades if g["kind"] in ("flash", "dip")) > FLASHES_MAX:
        raise Refusal("too_many_flashes", "beats.effects")


# ---------------------------------------------------------------- the timeline

def match_text_word(words: list, w_from: int, w_to: int, text: str):
    """The index of the first word of the window that is like the first token of `text`, else None."""
    toks = norm_tokens(text)
    if not toks:
        return None
    for w in words:
        if w_from <= w["index"] <= w_to:
            for t in norm_tokens(w["text"]):
                if token_sim(toks[0], t) > 0:
                    return w["index"]
    return None


def range_table(edl: dict) -> list:
    """[(first output frame, last output frame + 1)] of each kept range."""
    table, pos = [], 0
    for a, b in edl["kept"]:
        table.append((pos, pos + b - a))
        pos += b - a
    return table


def _range_of(table: list, frame: int) -> int:
    for k, (first, last) in enumerate(table):
        if first <= frame < last:
            return k
    return len(table) - 1


def _frame_at(seconds: float, fps: int, n: int) -> int:
    """The frame a time falls on: whole frames, inside the video."""
    return min(max(0, int(round(seconds * fps))), n - 1)


def resolve_punches(edl: dict, beats: dict, data: dict) -> tuple:
    """(rows, dropped): the script's punches and the review's punch effects as frame spans of the OUTPUT timeline, each inside one kept range.

    A punch spans its words, stretched to `punch.min_seconds` and cut at `punch.max_seconds` and at its range's end. Two punches in one range never
    overlap: the later one starts where the earlier one ends. One left under PUNCH_SHORT_SECONDS is dropped (`punch_short`). Its zoom is the range's
    own level at the punch's first frame times `punch.factor`, held for the span and capped at `zoom.factor_max`; one that would not zoom in past
    the range's own level is dropped (`punch_capped`). A row: {id, start_frame, end_frame, range, zoom, face}, `face` the face box as the punch draws it."""
    fps, n = edl["fps"], edl["out_frames"]
    cfg, zoom_cfg = data["punch"], data["zoom"]
    by_index = {w["index"]: w for w in edl["words"]}
    table = range_table(edl)
    items = [("p%d" % p["beat"], p["word_from"], p["word_to"]) for p in beats.get("punches") or []]
    items += [(e["id"], e["word_from"], e["word_to"]) for e in beats.get("effects") or [] if e["kind"] == "punch"]
    spans = []
    for pid, w_from, w_to in items:
        sf = _frame_at(by_index[w_from]["start"], fps, n)
        k = _range_of(table, sf)
        ef = max(int(round(by_index[w_to]["end"] * fps)), sf + int(round(cfg["min_seconds"] * fps)))
        ef = min(ef, sf + int(round(cfg["max_seconds"] * fps)), table[k][1])
        spans.append({"id": pid, "start_frame": sf, "end_frame": ef, "range": k})
    spans.sort(key=lambda r: (r["start_frame"], r["end_frame"], r["id"]))
    rows, dropped, floor = [], [], {}
    anchor = _media.anchor_point(edl["face_box"], edl["zoom"]["anchor_y"])
    w, h = data["frame"]["width"], data["frame"]["height"]
    for r in spans:
        k = r["range"]
        first, last = table[k]
        r["start_frame"] = max(r["start_frame"], floor.get(k, first))
        if (r["end_frame"] - r["start_frame"]) / float(fps) < PUNCH_SHORT_SECONDS - 1e-9:
            dropped.append({"id": r["id"], "reason": "punch_short"})
            continue
        z0, z1 = _media.zoom_levels(edl["zoom"], k, last - first, fps)
        base = z0 + (z1 - z0) * (r["start_frame"] - first) / float(max(1, last - first - 1))
        zp = round(min(zoom_cfg["factor_max"], base * cfg["factor"]), 5)
        if zp <= base + 1e-9:
            dropped.append({"id": r["id"], "reason": "punch_capped"})
            continue
        floor[k] = r["end_frame"]
        rows.append(dict(r, zoom=zp, face=_media.zoomed_box(edl["face_box"], zp, zp, anchor, w, h)))
    return rows, dropped


def resolve_grades(edl: dict, beats: dict, data: dict) -> tuple:
    """(rows, dropped): the review's flash, dip, mono and tint effects as frame spans of the OUTPUT timeline, each inside one kept range.

    A flash or a dip starts at the first frame of its first word and lasts one frame per alpha of `effects.flash_alphas` / `dip_alphas` (at most
    FLASH_FRAMES_MAX and DIP_FRAMES_MAX), cut at its range's end. Mono and tint span their words, clipped to `grade_min_seconds` to `grade_max_seconds`
    (never past GRADE_SECONDS_MAX) and cut at the range's end. A flash, dip or tint that starts inside the one before it is dropped (`grade_overlap`):
    they share one colour layer. A row: {id, kind, start_frame, end_frame, range, alphas (flash, dip) or alpha (tint), color (tint)}."""
    fps, n = edl["fps"], edl["out_frames"]
    cfg = data["effects"]
    by_index = {w["index"]: w for w in edl["words"]}
    table = range_table(edl)
    rows, dropped = [], []
    for e in beats.get("effects") or []:
        kind = e["kind"]
        if kind not in GRADE_KINDS:
            continue
        sf = _frame_at(by_index[e["word_from"]]["start"], fps, n)
        k = _range_of(table, sf)
        row = {"id": e["id"], "kind": kind, "start_frame": sf, "range": k}
        if kind in ("flash", "dip"):
            alphas = [min(FLASH_ALPHA_MAX, max(0.0, float(a))) for a in cfg[kind + "_alphas"]][:FLASH_FRAMES_MAX if kind == "flash" else DIP_FRAMES_MAX]
            row["end_frame"] = min(sf + len(alphas), table[k][1])
            row["alphas"] = alphas[:row["end_frame"] - sf]
        else:
            low = int(round(cfg["grade_min_seconds"] * fps))
            high = int(round(min(cfg["grade_max_seconds"], GRADE_SECONDS_MAX) * fps))
            length = min(max(int(round(by_index[e["word_to"]]["end"] * fps)) - sf, low), high)
            row["end_frame"] = min(sf + length, table[k][1])
            if kind == "tint":
                row["alpha"] = min(TINT_ALPHA_MAX, max(0.0, float(cfg["tint_alpha"])))
                row["color"] = edl["theme"]["colors"]["accent"]
        if row["end_frame"] <= row["start_frame"]:
            dropped.append({"id": e["id"], "reason": "grade_short"})
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r["start_frame"], r["end_frame"], r["id"]))
    kept, until = [], 0
    for r in rows:
        if r["kind"] in OVERLAY_GRADES:
            if r["start_frame"] < until:
                dropped.append({"id": r["id"], "reason": "grade_overlap"})
                continue
            until = r["end_frame"]
        kept.append(r)
    return kept, dropped


def range_effects(edl: dict, timeline: dict) -> dict:
    """{k: {first, frames, punches: [(a, b, zoom)], grades: [{kind, a, b, alphas, alpha, color}]}} for each kept range number k that a punch or a grade
    touches, in the RANGE's own frame index (a to b, b excluded). The ffmpeg engine's graph, the HyperFrames page and the face check's reference
    all draw from this one table, so the three hold the same rows. {} when the timeline has no punch and no grade."""
    table, out = range_table(edl), {}

    def slot(k):
        first, last = table[k]
        return out.setdefault(k, {"first": first, "frames": last - first, "punches": [], "grades": []})

    for p in timeline.get("punches") or []:
        first = table[p["range"]][0]
        slot(p["range"])["punches"].append((p["start_frame"] - first, p["end_frame"] - first, p["zoom"]))
    for g in timeline.get("grades") or []:
        first = table[g["range"]][0]
        slot(g["range"])["grades"].append({"kind": g["kind"], "a": g["start_frame"] - first, "b": g["end_frame"] - first, "alphas": g.get("alphas"),
                                           "alpha": g.get("alpha"), "color": g.get("color")})
    return out


def resolve_timeline(edl: dict, beats: dict, vocab: dict, data: dict) -> dict:
    """Frame ranges on the output timeline: {captions, beats, dropped, punches, grades, effects_dropped}.

    A beat starts at its first word and ends `tail` after its last, within the preset's minimum and maximum duration
    and the video's end (a keyword starts at the word that matches its text, when one does). A beat whose words are
    on either side of a cut is one continuous range of OUTPUT frames: the cut part is not on the timeline at all.
    One beat track: where two beats overlap, the earlier one ends where the later one starts, and one that is left
    with no frame is dropped (and reported)."""
    fps, n = edl["fps"], edl["out_frames"]
    by_index = {w["index"]: w for w in edl["words"]}
    entries = []
    for e in beats["overlays"] + beats["layouts"]:
        cfg = data["presets"][e["preset"]]
        start = by_index[e["word_from"]]["start"]
        end = by_index[e["word_to"]]["end"] + cfg["tail"]
        if cfg["anchor"] == "match_text" and "text" in e["params"]:
            i = match_text_word(edl["words"], e["word_from"], e["word_to"], e["params"]["text"])
            if i is not None:
                start = max(start, by_index[i]["start"] - 0.05)
        end = max(end, start + cfg["min_duration"])
        if cfg["max_duration"]:
            end = min(end, start + cfg["max_duration"])
        sf = int(round(start * fps))
        ef = min(max(sf + 1, int(round(end * fps))), n)
        entries.append(dict(e, kind=vocab["presets"][e["preset"]]["kind"], start_frame=sf, end_frame=ef))
    entries.sort(key=lambda x: (x["start_frame"], x["end_frame"]))
    for cur, nxt in zip(entries, entries[1:]):
        if cur["end_frame"] > nxt["start_frame"]:
            cur["end_frame"] = nxt["start_frame"]
            cur["clipped"] = True
    dropped = [e["id"] for e in entries if e["end_frame"] <= e["start_frame"]]
    entries = [e for e in entries if e["id"] not in dropped]
    punches, punches_dropped = resolve_punches(edl, beats, data)
    grades, grades_dropped = resolve_grades(edl, beats, data)
    for e in entries:
        e["face"] = span_face(edl, data, e["start_frame"], e["end_frame"], punches)
    cap = data["caption"]
    times = []
    for k, (a, b) in enumerate(edl["captions"]["chunks"]):
        start, word_end = by_index[a]["start"], by_index[b]["end"]
        end = word_end + cap["hold"]
        if k + 1 < len(edl["captions"]["chunks"]):
            nxt = by_index[edl["captions"]["chunks"][k + 1][0]]["start"]
            end = nxt if nxt - word_end <= 0.4 else min(end, nxt)
        times.append((start, min(end, n / fps)))
    captions = []
    for (a, b), (s, e) in zip(edl["captions"]["chunks"], times):
        sf = int(round(s * fps))
        ef = min(max(sf + 1, int(round(e * fps))), n)
        if ef <= sf:
            continue
        captions.append({"word_from": a, "word_to": b, "start_frame": sf, "end_frame": ef, "face": span_face(edl, data, sf, ef, punches)})
    return {"captions": captions, "beats": entries, "dropped": dropped, "punches": punches, "grades": grades,
            "effects_dropped": sorted(punches_dropped + grades_dropped, key=lambda r: r["id"])}

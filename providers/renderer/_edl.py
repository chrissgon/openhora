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

import _media
import _redact
from _align import norm_tokens, token_sim
from _text import Refusal, clean_text
from _timeline import (build_words, caption_chunks, check_transcript, retime_misplaced, detect_retakes, kept_ranges, normalise_words, out_frames_of)
from _vocab import HEX_COLOR, check_params, slot_params

EDL_SCHEMA_VERSION = 2     # 2: zoom.anchor_y is required and normalisation lists retimed_words and unplaced_words
BEATS_SCHEMA_VERSION = 1
SHA256 = re.compile(r"[0-9a-f]{64}")
ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
MENTION = re.compile(r"(?<![\w@])@[\w.]{1,30}")
EDL_KEYS = {"schema_version", "fps", "size", "source", "kept", "out_frames", "words", "captions", "theme", "normalisation", "face_box", "zoom",
            "proposals"}
PROPOSAL_KEYS = {"id", "kind", "word_from", "word_to", "keep_from", "seconds", "confirmed"}
SOURCE_KEYS = {"sha256", "duration", "width", "height", "has_audio", "color_matrix"}
BEATS_KEYS = {"schema_version", "threshold", "overlays", "layouts", "slots", "report", "unmatched", "fallbacks"}
ENTRY_KEYS = {"id", "beat", "preset", "params", "word_from", "word_to", "score"}
SLOT_KEYS = {"slot", "beat", "param", "type", "description"}
NORMALISATION_KEYS = {"words", "dropped_words", "dropped_segments", "zero_length_words", "spread_runs", "estimated_words", "clamped_starts", "retimed_words", "unplaced_words"}


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


def zones(data: dict, face: dict) -> dict:
    """The two bands the face box leaves: cards above it, captions below it. [top, bottom] in frame pixels."""
    z = data["zones"]
    return {"card": [z["card_top"], face["y"] - z["gap"]], "caption": [face["y"] + face["h"] + z["gap"], z["caption_bottom"]]}


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


def span_face(edl: dict, data: dict, start_frame: int, end_frame: int) -> dict:
    """The face box over a span of output frames: the union of its boxes in the kept ranges the span touches, so that a card or a
    caption that lives through a zoom change stays clear of the face in every range."""
    boxes = [box for a, b, box in range_faces(edl, data) if a < end_frame and start_frame < b]
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
               push_in=None, confirm=(), long_cut=None, wordless_max=None, anchor_y=None) -> tuple:
    """The code-generated base edit list from a transcript and an analysis. No model.

    Silence is the cut signal (`analysis["silences"]`; `None` when the recording has no audio, then the word gaps
    decide); the words only protect speech. Retakes are found by rule and written into the list as PROPOSALS, none applied:
    `confirm` names the proposals the person confirmed (by id), and only those are cut. A cut of `long_cut` seconds or more
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
    words, report = normalise_words(tr["words"], tr["segments"], duration)
    live = [w for w in words if not w["dropped"]]
    if not live:
        raise Refusal("no_words", "transcript")
    proposals = detect_retakes(live)
    unknown = sorted(set(confirm) - {p["id"] for p in proposals})
    if unknown:
        raise Refusal("unknown_proposal", unknown[0][:32])
    forced = []
    by_index = {w["index"]: w for w in live}
    for p in proposals:
        if p["id"] not in confirm:
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
    silences = analysis.get("silences")
    sil = None if silences is None else [(s["start"], s["end"]) for s in silences]
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
    closed(norm, NORMALISATION_KEYS, "edl.normalisation")
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
        closed(p, PROPOSAL_KEYS, field)
        if not isinstance(p["id"], str) or not ID.fullmatch(p["id"]) or p["id"] in seen or p["kind"] not in ("repeat", "restart") \
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


def check_beats(beats, edl, vocab: dict) -> dict:
    """Validate beats.json against the base list and the vocabulary. Returns {texts, mentions}; raises Refusal."""
    closed(beats, BEATS_KEYS, "beats")
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
            closed(e, ENTRY_KEYS, field)
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
    scan_texts(texts)
    return {"texts": texts, "mentions": mentions_of(texts)}


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


def resolve_timeline(edl: dict, beats: dict, vocab: dict, data: dict) -> dict:
    """Frame ranges on the output timeline: {captions, beats, report}.

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
    for e in entries:
        e["face"] = span_face(edl, data, e["start_frame"], e["end_frame"])
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
        captions.append({"word_from": a, "word_to": b, "start_frame": sf, "end_frame": ef, "face": span_face(edl, data, sf, ef)})
    return {"captions": captions, "beats": entries, "dropped": dropped}

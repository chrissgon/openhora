#!/usr/bin/env python3
"""Edit list builder: transcript (+ silences) + script -> output-timeline edit list. Code only; no model.

What it does (plan C1, A1, A2):
  1. kept ranges: cut word gaps over a threshold and leading/trailing silence, with a margin,
     snapped to the frame grid; confirmed by an optional silencedetect list;
  2. caption chunks taken from the transcript segments;
  3. aligns each script beat's spoken line to a word range by deterministic fuzzy matching
     (NFKC + casefold + punctuation; digits excluded from scoring; best window per beat;
     a tie goes to the last occurrence; an order check; a threshold; unmatched beats reported);
  4. maps everything onto the OUTPUT timeline (after the cuts), at the output fps.

The edit list holds ranges, indices, preset names, validated typed parameters and slot ids.
"""
import argparse
import json
import math
import sys

import cuts as C
import framing as F
import presets as P
import retakes as RT
import tokens as T
import zones as Z
from tokens import flatten_words, has_digit, norm_tokens, token_sim  # noqa: F401  (re-exported)

DEL_COST = 1.0      # a beat token that was not spoken
INS_COST = 0.3      # a spoken word that is not in the beat (ad-lib inside the line)
SIM_FLOOR = T.SIM_FLOOR
DEFAULT_THRESHOLD = 0.6


class EdlError(ValueError):
    pass


# ---------------------------------------------------------------- transcript

def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def check_transcript(tr):
    """Validate the transcript shape and harden every word text. Returns the transcript."""
    if not isinstance(tr, dict) or not isinstance(tr.get("words"), list) or not tr["words"]:
        raise EdlError("transcript_words")
    dur = tr.get("duration")
    if not isinstance(dur, (int, float)) or dur <= 0:
        raise EdlError("transcript_duration")
    prev_end = 0.0
    for pos, w in enumerate(tr["words"]):
        if w.get("i") != pos:
            raise EdlError("word_index:%d" % pos)
        w["text"] = P.clean_text(w.get("text"), 40, "word%d" % pos)
        s, e = w.get("start"), w.get("end")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)) or e <= s:
            raise EdlError("word_time:%d" % pos)
        if s < prev_end - 1e-6 or e > dur + 1e-6:
            raise EdlError("word_order:%d" % pos)
        if not isinstance(w.get("segment"), int):
            raise EdlError("word_segment:%d" % pos)
        prev_end = e
    return tr


# ---------------------------------------------------------------- cuts

def _subtract(region, intervals):
    """Intersect one (s, e) region with a list of (s, e) intervals; returns the pieces."""
    pieces = []
    for a, b in intervals:
        s, e = max(region[0], a), min(region[1], b)
        if e > s:
            pieces.append((s, e))
    return pieces


def kept_ranges(words, duration, fps, silences=None, gap=0.5, margin=0.15, min_cut=0.2):
    """Return kept (start, end) source ranges, on the frame grid.

    A cut region is: the leading part before the first word, the trailing part after the last word,
    and every gap between two words longer than `gap`. A margin stays on each side of every word.
    With `silences` (list of (start, end)), only the part of a region that a silence interval confirms
    is cut. Cuts shorter than `min_cut` are not made.
    """
    if gap < 2 * margin + min_cut:
        raise EdlError("gap_too_small_for_margin")
    regions = []
    first, last = words[0], words[-1]
    regions.append((0.0, first["start"] - margin))
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] > gap:
            regions.append((a["end"] + margin, b["start"] - margin))
    regions.append((last["end"] + margin, duration))
    cuts = []
    for r in regions:
        if r[1] - r[0] <= 0:
            continue
        pieces = _subtract(r, silences) if silences is not None else [r]
        cuts.extend(p for p in pieces if p[1] - p[0] >= min_cut)
    cuts.sort()
    # kept = complement of the cuts, widened to the frame grid so a cut never eats into a margin
    kept, cursor = [], 0.0
    for s, e in cuts:
        if s > cursor:
            kept.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration:
        kept.append((cursor, duration))
    grid = []
    for s, e in kept:
        fs = max(0, math.floor(s * fps + 1e-6))
        fe = min(int(math.floor(duration * fps + 1e-6)), math.ceil(e * fps - 1e-6))
        if fe > fs:
            grid.append([fs, fe])
    merged = []
    for fs, fe in grid:
        if merged and fs <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], fe)
        else:
            merged.append([fs, fe])
    return [(fs / fps, fe / fps) for fs, fe in merged]


def build_map(kept):
    """Kept source ranges -> list of {src_start, src_end, out_start, out_end}."""
    rows, out = [], 0.0
    for s, e in kept:
        rows.append({"src_start": s, "src_end": e, "out_start": out, "out_end": out + (e - s)})
        out += e - s
    return rows


def src_to_out(kmap, t):
    """Map a source time to the output timeline. A time inside a cut snaps to the nearest kept edge."""
    best, best_d = None, None
    for r in kmap:
        if r["src_start"] - 1e-9 <= t <= r["src_end"] + 1e-9:
            return r["out_start"] + (t - r["src_start"])
        d = min(abs(t - r["src_start"]), abs(t - r["src_end"]))
        if best is None or d < best_d:
            best, best_d = r, d
    return best["out_start"] if t < best["src_start"] else best["out_end"]


# ---------------------------------------------------------------- captions

def _range_of(kmap, t):
    """Index of the kept range that holds source time t, or None."""
    for k, r in enumerate(kmap):
        if r["src_start"] - 1e-9 <= t <= r["src_end"] + 1e-9:
            return k
    return None


def caption_chunks(words, kmap, max_words=3, max_chars=22, hold=0.25, pause=0.45):
    """Short caption chunks (1 to `max_words` words) on the OUTPUT timeline.

    Words that are not in the output (cut away, or the earlier take of a retake) get no caption. A chunk ends at the end
    of a sentence, after a comma once it holds two words, at a cut, at a pause, and when the next word would make it
    longer than `max_chars` letters.
    """
    items = []
    for w in words:
        if w.get("dropped"):
            continue
        k = _range_of(kmap, (w["start"] + w["end"]) / 2.0)
        if k is None:
            continue
        items.append((w, k))
    groups, cur, chars, cur_k = [], [], 0, None
    for w, k in items:
        brk = False
        if cur:
            prev = cur[-1]
            if (k != cur_k or w["segment"] != prev["segment"] or len(cur) >= max_words
                    or chars + 1 + len(w["text"]) > max_chars
                    or src_to_out(kmap, w["start"]) - src_to_out(kmap, prev["end"]) > pause):
                brk = True
        if brk:
            groups.append(cur)
            cur, chars = [], 0
        cur.append(w)
        cur_k = k
        chars += len(w["text"]) + (1 if len(cur) > 1 else 0)
        last = w["text"][-1:]
        if last in ".?!" or (last in ",;:" and len(cur) >= 2):
            groups.append(cur)
            cur, chars = [], 0
    if cur:
        groups.append(cur)
    chunks = []
    for g in groups:
        ow = [{"i": w["i"], "text": w["text"], "start": src_to_out(kmap, w["start"]),
               "end": src_to_out(kmap, w["end"])} for w in g]
        chunks.append({"segment": g[0]["segment"], "word_from": g[0]["i"], "word_to": g[-1]["i"],
                       "start": ow[0]["start"], "end": ow[-1]["end"] + hold, "words": ow})
    # a chunk ends where the next one starts when they touch; the hold never runs into the next
    for k, c in enumerate(chunks):
        nxt = chunks[k + 1] if k + 1 < len(chunks) else None
        word_end = c["words"][-1]["end"]
        end = word_end + hold
        if nxt is not None:
            if nxt["start"] - word_end <= 0.4:
                end = nxt["start"]
            else:
                end = min(end, nxt["start"])
        c["end"] = min(max(end, word_end + 0.05), kmap[-1]["out_end"])
    return chunks


# ---------------------------------------------------------------- alignment

def align_line(line, flat, threshold=DEFAULT_THRESHOLD):
    """Best window of the transcript for one spoken line.

    Free start and end (approximate substring matching). A spoken word that is not in the line costs
    INS_COST, a missing one DEL_COST, a similar one 1 - similarity. Digit tokens are excluded from the
    scoring on both sides: a figure in the line is dropped, a figure in the transcript is free.
    A tie goes to the last occurrence, so a retake wins. Returns a dict with score and word range.
    """
    toks, widx = flat
    beat = [t for t in norm_tokens(line) if not has_digit(t)]
    n, m = len(beat), len(toks)
    if n == 0 or m == 0:
        return {"score": 0.0, "word_from": None, "word_to": None, "matched": False}
    wild = [has_digit(t) for t in toks]
    # cell = (cost, -start): lower cost first, then the later start
    prev = [(0.0, -i) for i in range(m + 1)]
    for j in range(1, n + 1):
        cur = [(j * DEL_COST, 0)] + [None] * m
        for i in range(1, m + 1):
            cands = []
            if not wild[i - 1]:
                sim = token_sim(beat[j - 1], toks[i - 1])
                c, s = prev[i - 1]
                cands.append((round(c + (1.0 - sim if sim else 1.0), 6), s))
            c, s = prev[i]
            cands.append((round(c + DEL_COST, 6), s))
            c, s = cur[i - 1]
            cands.append((round(c + (0.0 if wild[i - 1] else INS_COST), 6), s))
            cur[i] = min(cands)
        prev = cur
    best_i = min(range(1, m + 1), key=lambda i: (prev[i][0], -i))   # lowest cost, then the last end
    best = prev[best_i]
    cost, neg_start = best
    start_tok = -neg_start
    score = max(0.0, 1.0 - cost / n)
    if start_tok >= best_i or score <= 0.0:
        return {"score": 0.0, "word_from": None, "word_to": None, "matched": False}
    w_from, w_to = widx[start_tok], widx[best_i - 1]
    return {"score": round(score, 4), "word_from": w_from, "word_to": w_to,
            "matched": score >= threshold}


def expand_digit_words(words, w_from, w_to):
    """A window grows over neighbouring words that hold only figures (they were excluded from scoring)."""
    def only_digits(w):
        ts = norm_tokens(w["text"])
        return bool(ts) and all(has_digit(t) for t in ts)
    while w_from > 0 and only_digits(words[w_from - 1]):
        w_from -= 1
    while w_to + 1 < len(words) and only_digits(words[w_to + 1]):
        w_to += 1
    return w_from, w_to


def align_beats(words, beats, threshold=DEFAULT_THRESHOLD, anchors=None):
    """Place each beat on a word range. `anchors` ({beat id: (word_from, word_to)}) places a beat by hand: the person's
    choice wins over the matcher (the beat is `anchored`, score 1.0). Words flagged `dropped` are never matched."""
    flat = flatten_words(words)
    anchors = anchors or {}
    results = []
    last_from = -1
    for b in beats:
        if b["id"] in anchors:
            w_from, w_to = anchors[b["id"]]
            r = {"score": 1.0, "word_from": w_from, "word_to": w_to, "matched": True, "anchored": True}
        else:
            r = align_line(b["line"], flat, threshold)
            r["anchored"] = False
        r["beat"] = b["id"]
        r["reordered"] = False
        if r["matched"]:
            if not r["anchored"]:
                r["word_from"], r["word_to"] = expand_digit_words(words, r["word_from"], r["word_to"])
            if r["word_from"] < last_from:
                r["reordered"] = True
            last_from = max(last_from, r["word_from"])
        results.append(r)
    return results


def parse_anchors(items, beats, n_words):
    """['6=173-190', 'b7=200-215'] -> {beat id: (word_from, word_to)}; refuses an unknown beat or a bad range."""
    ids = {b["id"] for b in beats}
    out = {}
    for item in items or []:
        key, _, rng = item.partition("=")
        bid = key if key in ids else "b" + key
        lo, _, hi = rng.partition("-")
        if bid not in ids:
            raise EdlError("anchor_unknown_beat:%s" % key)
        if not (lo.isdigit() and hi.isdigit()) or int(lo) > int(hi) or int(hi) >= n_words:
            raise EdlError("anchor_bad_range:%s" % item)
        if bid in out:
            raise EdlError("anchor_twice:%s" % key)
        out[bid] = (int(lo), int(hi))
    return out


# ---------------------------------------------------------------- script

def check_script(script, contract):
    """Validate the script: beats, presets, typed parameters, asset slots. Returns normalised beats."""
    if not isinstance(script, dict) or not isinstance(script.get("beats"), list):
        raise EdlError("script_beats")
    slots = script.get("assets", {})
    if not isinstance(slots, dict):
        raise EdlError("script_assets")
    beats, seen = [], set()
    for k, b in enumerate(script["beats"]):
        if not isinstance(b, dict):
            raise EdlError("beat_not_object:%d" % k)
        bid = b.get("id", "b%d" % (k + 1))
        if bid in seen:
            raise EdlError("beat_duplicate_id")
        seen.add(bid)
        line = P.clean_text(b.get("line"), 240, "beat%d.line" % k)
        preset = b.get("preset")
        if preset not in contract["presets"] or contract["presets"][preset]["kind"] == "caption":
            raise EdlError("beat_preset:%d" % k)
        params = P.validate_params(contract, preset, b.get("params", {}))
        label = P.clean_text(b.get("label", preset), contract["limits"]["label_max"], "beat%d.label" % k)
        for slot in P.asset_slots(contract, preset, params):
            if slot not in slots:
                raise EdlError("undeclared_slot:%s" % slot)
        beats.append({"id": bid, "line": line, "preset": preset, "params": params, "label": label})
    if len(beats) > contract["limits"]["overlays_max"]:
        raise EdlError("too_many_beats")
    return beats


def _match_word(words, w_from, w_to, text):
    """First word in the window that is similar to the first token of `text`, else None."""
    toks = norm_tokens(text)
    if not toks:
        return None
    for i in range(w_from, w_to + 1):
        for t in norm_tokens(words[i]["text"]):
            if token_sim(toks[0], t) > 0:
                return i
    return None


def beat_span(spec, words, kmap, params, w_from, w_to, fps, out_duration):
    """Out-timeline start and end of one beat, from the preset's data and the matched word range."""
    start = src_to_out(kmap, words[w_from]["start"])
    end = src_to_out(kmap, words[w_to]["end"]) + spec.get("tail", 0.0)
    if spec.get("anchor") == "match_text" and "text" in params:
        i = _match_word(words, w_from, w_to, params["text"])
        if i is not None:
            start = max(start, src_to_out(kmap, words[i]["start"]) - 0.05)
    lo, hi = spec.get("min_duration", 0.5), spec.get("max_duration")
    end = max(end, start + lo)
    if hi:
        end = min(end, start + hi)
    sf = int(round(start * fps))
    ef = max(sf + 1, int(round(end * fps)))
    ef = min(ef, int(round(out_duration * fps)))
    return sf, ef


# ---------------------------------------------------------------- build

def build_edl(transcript, script, contract, silences=None, gap=0.5, margin=0.15,
              threshold=DEFAULT_THRESHOLD, fps=None, cut=None, retake_cfg=None, anchors=None, face=None,
              frame_cfg=None):
    """Build the edit list.

    cut        dict of the silence-first cutter's numbers (cuts.plan keywords); used when `silences` is given.
               Without it, the older word-gap cutter runs (kept_ranges: `gap`, `margin`).
    retake_cfg dict (window, min_run, start_slack, keep: word indices of retakes to keep) or None to skip detection.
    anchors    {beat id: (word_from, word_to)} placed by hand.
    face       (x, y, w, h) in output pixels or None; frame_cfg: {zoom, push, push_min, anchor_y, top_margin, ...}.
    """
    fps = fps or contract["frame"]["fps"]
    tr = check_transcript(transcript)
    words = tr["words"]
    beats = check_script(script, contract)
    retakes = []
    if retake_cfg is not None:
        retakes = RT.detect(words, retake_cfg.get("window", RT.WINDOW), retake_cfg.get("min_run", RT.MIN_RUN),
                            retake_cfg.get("start_slack", RT.START_SLACK))
        retakes = [r for r in retakes if r["word_from"] not in set(retake_cfg.get("keep", ()))]
    RT.apply(words, retakes)
    cut_report = None
    if silences is not None and cut is not None:
        cut_report = C.plan(words, silences, tr["duration"], fps, retakes, **cut)
        kept = cut_report["kept"]
    else:
        kept = kept_ranges(words, tr["duration"], fps, silences, gap, margin)
    kmap = build_map(kept)
    out_duration = kmap[-1]["out_end"]
    out_frames = int(round(out_duration * fps))

    fc = dict(zoom=1.10, push=0.02, push_min=5.0, anchor_y=0.25, top_margin=110, bottom_margin=300, gap=18, enabled=True)
    fc.update(frame_cfg or {})
    framing = F.plan(kept, fc["zoom"], fc["push"], fc["push_min"]) if fc["enabled"] else F.plan(kept, 1.0, 0.0, alternate=False)
    zones = Z.compute(face, (contract["frame"]["width"], contract["frame"]["height"]),
                      fc["zoom"] if fc["enabled"] else 1.0, fc["push"] if fc["enabled"] else 0.0, fc["anchor_y"],
                      fc["top_margin"], fc["bottom_margin"], fc["gap"])
    for row, fr in zip(kmap, framing):
        row["z0"], row["z1"] = fr["z0"], fr["z1"]

    caption_cfg = P.validate_params(contract, "caption", script.get("caption", {}))
    chunks = caption_chunks(words, kmap)
    anchors = anchors or {}
    alignment = align_beats(words, beats, threshold, anchors)

    overlays, layouts, report = [], [], []
    for b, a in zip(beats, alignment):
        row = {"beat": b["id"], "preset": b["preset"], "score": a["score"], "matched": a["matched"],
               "reordered": a["reordered"], "anchored": a["anchored"], "word_from": a["word_from"], "word_to": a["word_to"]}
        if a["matched"]:
            spec = contract["presets"][b["preset"]]
            sf, ef = beat_span(spec, words, kmap, b["params"], a["word_from"], a["word_to"], fps, out_duration)
            entry = {"id": b["id"], "preset": b["preset"], "params": b["params"], "label": b["label"],
                     "word_from": a["word_from"], "word_to": a["word_to"], "score": a["score"],
                     "anchored": a["anchored"],
                     "start_frame": sf, "end_frame": ef,
                     "start": sf / fps, "end": ef / fps}
            slots = P.asset_slots(contract, b["preset"], b["params"])
            if slots:
                entry["asset"] = slots[0]
            (layouts if spec["kind"] == "layout" else overlays).append(entry)
            row["start"], row["end"] = entry["start"], entry["end"]
        report.append(row)

    # one beat track: where two beats overlap, the earlier one ends where the later one starts
    track = sorted(overlays + layouts, key=lambda e: (e["start_frame"], e["end_frame"]))
    for cur, nxt in zip(track, track[1:]):
        if cur["end_frame"] > nxt["start_frame"]:
            cur["end_frame"] = nxt["start_frame"]
            cur["end"] = cur["end_frame"] / fps
            cur["clipped"] = True
    dropped = [e for e in track if e["end_frame"] <= e["start_frame"]]
    for e in dropped:
        for r in report:
            if r["beat"] == e["id"]:
                r["matched"] = False
                r["dropped"] = "overlap"
    track = [e for e in track if e not in dropped]
    overlays = [e for e in overlays if e in track]
    layouts = [e for e in layouts if e in track]
    for e in track:
        for r in report:
            if r["beat"] == e["id"]:
                r["start"], r["end"] = e["start"], e["end"]
                if e.get("clipped"):
                    r["clipped"] = True

    # captions are placed by the active layout: a pip bubble at the bottom lifts the caption
    for c in chunks:
        c["start_frame"] = int(round(c["start"] * fps))
        c["end_frame"] = max(c["start_frame"] + 1, int(round(c["end"] * fps)))
        c["params"] = dict(caption_cfg)
        c["lift"] = any(l["preset"] == "pip" and l["params"]["position"].startswith("bottom")
                        and l["start_frame"] < c["end_frame"] and c["start_frame"] < l["end_frame"]
                        for l in layouts)

    return {
        "version": 2, "fps": fps, "size": [contract["frame"]["width"], contract["frame"]["height"]],
        "source_duration": tr["duration"], "out_duration": out_duration, "out_frames": out_frames,
        "kept": kmap, "captions": chunks, "overlays": overlays, "layouts": layouts,
        "unmatched": [r["beat"] for r in report if not r["matched"]],
        "report": report,
        "assets": script.get("assets", {}),
        "cuts": None if cut_report is None else {k: cut_report[k] for k in ("cuts", "notes", "stats", "clipped_words", "cuts_inside_long_words")},
        "retakes": retakes, "zones": zones,
        "anchors": {k: list(v) for k, v in anchors.items()},
        "framing": {"zoom": fc["zoom"], "push": fc["push"], "anchor_y": fc["anchor_y"], "enabled": fc["enabled"]},
    }


def format_report(edl):
    lines = ["beat  preset    score  matched  reordered  anchored  out range (s)"]
    for r in edl["report"]:
        rng = "%.2f-%.2f" % (r["start"], r["end"]) if "start" in r else "-"
        lines.append("%-5s %-9s %5.2f  %-7s  %-9s  %-8s  %s" % (r["beat"], r["preset"], r["score"],
                     r["matched"], r["reordered"], r.get("anchored", False), rng))
    return "\n".join(lines)


def add_cut_args(ap):
    """The flags of the cutter, the retake detector, the anchors and the framing (shared by edl.py and render.py)."""
    g = ap.add_argument_group("cuts (silence is the primary signal)")
    g.add_argument("--silence-db", type=float, default=-38.0, help="silencedetect noise floor in dB (default -38; try -35 to -40)")
    g.add_argument("--silence-min", type=float, default=0.35, help="shortest silence in seconds (default 0.35)")
    g.add_argument("--pad-head", type=float, default=C.PAD_HEAD, help="speech kept before the first word after a silence (default 0.10 s)")
    g.add_argument("--pad-tail", type=float, default=C.PAD_TAIL, help="speech kept after the last word before a silence (default 0.14 s)")
    g.add_argument("--min-cut", type=float, default=0.25, help="a cut shorter than this is not made (default 0.25 s)")
    g.add_argument("--min-keep", type=float, default=C.MIN_KEEP, help="no kept range is shorter than this (default 0.4 s)")
    g.add_argument("--wordless", type=float, default=C.WORDLESS, help="a kept range shorter than this with no transcribed word is cut (default 1.5 s)")
    g.add_argument("--stretch", type=float, default=C.STRETCH, help="a word longer than this protects nothing (default 1.0 s)")
    g = ap.add_argument_group("retakes")
    g.add_argument("--no-retakes", action="store_true", help="do not remove earlier takes")
    g.add_argument("--retake-window", type=float, default=RT.WINDOW, help="seconds after a sentence in which a repeat counts (default 20)")
    g.add_argument("--retake-min-run", type=int, default=RT.MIN_RUN, help="words in a row that make a repeat (default 4)")
    g.add_argument("--keep-retake", action="append", type=int, default=[], metavar="WORD", help="keep the earlier take that starts at this word index (repeatable)")
    g = ap.add_argument_group("placement")
    g.add_argument("--anchor", action="append", metavar="BEAT=FROM-TO", help="place a beat by hand on transcript words FROM..TO (word indices of the normalised transcript; repeatable)")
    g.add_argument("--face", metavar="X,Y,W,H", help="the face box of this recording in output pixels; cards go above it, captions below, nothing overlaps it")
    g.add_argument("--zoom", type=float, default=1.10, help="punch-in of every second kept range (default 1.10)")
    g.add_argument("--push", type=float, default=0.02, help="slow push-in inside ranges of 5 s or more (default 0.02, at most 0.03)")
    g.add_argument("--no-zoom", action="store_true", help="no change of framing at the cuts")
    g.add_argument("--zoom-anchor-y", type=float, default=0.25, help="the zoom's fixed point: this fraction of the face box height from its top (0.5 = the box centre; default 0.25 keeps the head's top still)")
    g.add_argument("--top-margin", type=int, default=110, help="top of the card band, px from the frame's top (default 110)")
    g.add_argument("--bottom-margin", type=int, default=300, help="px kept free at the frame's bottom for the captions' zone (default 300)")


def configs_from_args(args):
    cut = dict(pad_head=args.pad_head, pad_tail=args.pad_tail, min_cut=args.min_cut, min_keep=args.min_keep, stretch=args.stretch, wordless=args.wordless)
    retake_cfg = None if args.no_retakes else dict(window=args.retake_window, min_run=args.retake_min_run, keep=args.keep_retake)
    frame_cfg = dict(zoom=args.zoom, push=args.push, anchor_y=args.zoom_anchor_y, top_margin=args.top_margin,
                     bottom_margin=args.bottom_margin, enabled=not args.no_zoom)
    face = Z.parse_box(args.face) if args.face else None
    return cut, retake_cfg, frame_cfg, face


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the output-timeline edit list from a transcript and a script.")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--silences", help="JSON list of {start,end} from ffmpeg silencedetect (the cuts are made from it)")
    ap.add_argument("--presets", default=P.DEFAULT_CONTRACT)
    ap.add_argument("--gap", type=float, default=0.5, help="legacy cutter (no silences): cut word gaps longer than this (s)")
    ap.add_argument("--margin", type=float, default=0.15, help="legacy cutter: kept on each side of a word (s)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="alignment score threshold")
    ap.add_argument("--out", required=True)
    add_cut_args(ap)
    args = ap.parse_args(argv)
    contract = P.load_contract(args.presets)
    silences = None
    if args.silences:
        silences = [(s["start"], s["end"]) for s in load_json(args.silences)]
    try:
        cut, retake_cfg, frame_cfg, face = configs_from_args(args)
        tr = load_json(args.transcript)
        script = load_json(args.script)
        anchors = parse_anchors(args.anchor, check_script(script, contract), len(tr["words"]))
        edl = build_edl(tr, script, contract, silences, args.gap, args.margin, args.threshold,
                        cut=cut, retake_cfg=retake_cfg, anchors=anchors, face=face, frame_cfg=frame_cfg)
    except (EdlError, P.ParamError, Z.ZoneError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(edl, fh, indent=1)
    print(format_report(edl))
    print("source %.2fs -> output %.2fs (%d frames), %d kept ranges, %d captions"
          % (edl["source_duration"], edl["out_duration"], edl["out_frames"], len(edl["kept"]), len(edl["captions"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())

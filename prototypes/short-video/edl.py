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
import difflib
import json
import math
import re
import sys
import unicodedata

import presets as P

DEL_COST = 1.0      # a beat token that was not spoken
INS_COST = 0.3      # a spoken word that is not in the beat (ad-lib inside the line)
SIM_FLOOR = 0.75    # token similarity below this is a plain mismatch
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

def caption_chunks(words, kmap, max_words=4, max_chars=26, hold=0.25):
    """Split each transcript segment into short chunks; times are on the output timeline."""
    chunks = []
    seg_words = {}
    for w in words:
        seg_words.setdefault(w["segment"], []).append(w)
    for seg in sorted(seg_words):
        cur, chars = [], 0
        groups = []
        for w in seg_words[seg]:
            if cur and (len(cur) >= max_words or chars + 1 + len(w["text"]) > max_chars):
                groups.append(cur)
                cur, chars = [], 0
            cur.append(w)
            chars += len(w["text"]) + (1 if len(cur) > 1 else 0)
        if cur:
            groups.append(cur)
        for k, g in enumerate(groups):
            ow = [{"i": w["i"], "text": w["text"], "start": src_to_out(kmap, w["start"]),
                   "end": src_to_out(kmap, w["end"])} for w in g]
            chunks.append({"segment": seg, "word_from": g[0]["i"], "word_to": g[-1]["i"],
                           "start": ow[0]["start"], "end": ow[-1]["end"] + hold, "words": ow,
                           "last_in_segment": k == len(groups) - 1})
    # a chunk ends where the next one starts when they touch; the hold never runs into the next
    for k, c in enumerate(chunks):
        nxt = chunks[k + 1] if k + 1 < len(chunks) else None
        word_end = c["words"][-1]["end"]
        end = word_end + hold
        if nxt is not None:
            if not c["last_in_segment"] and nxt["start"] - word_end <= 0.4:
                end = nxt["start"]
            else:
                end = min(end, nxt["start"])
        c["end"] = min(end, kmap[-1]["out_end"])
    for c in chunks:
        del c["last_in_segment"]
    return chunks


# ---------------------------------------------------------------- alignment

def norm_tokens(text):
    """NFKC, casefold, apostrophes dropped, other punctuation to a space; returns tokens."""
    t = unicodedata.normalize("NFKC", text).casefold()
    t = re.sub(r"['’]", "", t)
    t = re.sub(r"[^\w\s]|_", " ", t)
    return t.split()


def has_digit(tok):
    return any(c.isdigit() for c in tok)


_sim_cache = {}


def token_sim(a, b):
    if a == b:
        return 1.0
    key = (a, b)
    if key not in _sim_cache:
        r = difflib.SequenceMatcher(None, a, b).ratio()
        _sim_cache[key] = r if (r >= SIM_FLOOR and min(len(a), len(b)) > 3) else 0.0
    return _sim_cache[key]


def flatten_words(words):
    """Transcript words -> flat token list with the word index of each token."""
    toks, widx = [], []
    for w in words:
        for t in norm_tokens(w["text"]):
            toks.append(t)
            widx.append(w["i"])
    return toks, widx


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


def align_beats(words, beats, threshold=DEFAULT_THRESHOLD):
    flat = flatten_words(words)
    results = []
    last_from = -1
    for b in beats:
        r = align_line(b["line"], flat, threshold)
        r["beat"] = b["id"]
        r["reordered"] = False
        if r["matched"]:
            r["word_from"], r["word_to"] = expand_digit_words(words, r["word_from"], r["word_to"])
            if r["word_from"] < last_from:
                r["reordered"] = True
            last_from = max(last_from, r["word_from"])
        results.append(r)
    return results


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
              threshold=DEFAULT_THRESHOLD, fps=None):
    fps = fps or contract["frame"]["fps"]
    tr = check_transcript(transcript)
    words = tr["words"]
    beats = check_script(script, contract)
    kept = kept_ranges(words, tr["duration"], fps, silences, gap, margin)
    kmap = build_map(kept)
    out_duration = kmap[-1]["out_end"]
    out_frames = int(round(out_duration * fps))

    caption_cfg = P.validate_params(contract, "caption", script.get("caption", {}))
    chunks = caption_chunks(words, kmap)
    alignment = align_beats(words, beats, threshold)

    overlays, layouts, report = [], [], []
    for b, a in zip(beats, alignment):
        row = {"beat": b["id"], "preset": b["preset"], "score": a["score"], "matched": a["matched"],
               "reordered": a["reordered"], "word_from": a["word_from"], "word_to": a["word_to"]}
        if a["matched"]:
            spec = contract["presets"][b["preset"]]
            sf, ef = beat_span(spec, words, kmap, b["params"], a["word_from"], a["word_to"], fps, out_duration)
            entry = {"id": b["id"], "preset": b["preset"], "params": b["params"], "label": b["label"],
                     "word_from": a["word_from"], "word_to": a["word_to"], "score": a["score"],
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
        "version": 1, "fps": fps, "size": [contract["frame"]["width"], contract["frame"]["height"]],
        "source_duration": tr["duration"], "out_duration": out_duration, "out_frames": out_frames,
        "kept": kmap, "captions": chunks, "overlays": overlays, "layouts": layouts,
        "unmatched": [r["beat"] for r in report if not r["matched"]],
        "report": report,
        "assets": script.get("assets", {}),
    }


def format_report(edl):
    lines = ["beat  preset    score  matched  reordered  out range (s)"]
    for r in edl["report"]:
        rng = "%.2f-%.2f" % (r["start"], r["end"]) if "start" in r else "-"
        lines.append("%-5s %-9s %5.2f  %-7s  %-9s  %s" % (r["beat"], r["preset"], r["score"],
                     r["matched"], r["reordered"], rng))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the output-timeline edit list from a transcript and a script.")
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--script", required=True)
    ap.add_argument("--silences", help="JSON list of {start,end} from ffmpeg silencedetect (optional)")
    ap.add_argument("--presets", default=P.DEFAULT_CONTRACT)
    ap.add_argument("--gap", type=float, default=0.5, help="cut word gaps longer than this (s)")
    ap.add_argument("--margin", type=float, default=0.15, help="kept on each side of a word (s)")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="alignment score threshold")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    contract = P.load_contract(args.presets)
    silences = None
    if args.silences:
        silences = [(s["start"], s["end"]) for s in load_json(args.silences)]
    try:
        edl = build_edl(load_json(args.transcript), load_json(args.script), contract, silences,
                        args.gap, args.margin, args.threshold)
    except (EdlError, P.ParamError) as exc:
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

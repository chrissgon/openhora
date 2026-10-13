"""The transcript, the cuts, the captions and the output timeline. Code only; no model.

  normalise_words   a real transcript's shapes made safe: words of zero length, starts that go back in time, a repeated
                    sentence whisper made up in a fraction of a second. Word indices are never renumbered.
  kept_ranges       the part of the recording that stays: word gaps over a threshold and the silence before the first
                    word and after the last are cut, with a margin on each side of every word, on the frame grid, and
                    only where silencedetect confirms the silence.
  build_words       every word on the OUTPUT timeline (after the cuts).
  caption_chunks    the words split into short caption chunks.

Frames are integers on the grid of the output fps. Standard library only.
"""
from __future__ import annotations

import math

from _text import Refusal, clean_text

MIN_WORD_SECONDS = 0.04     # a word the transcriber gave no length gets at least this much
MAX_WORDS_PER_SECOND = 8.0  # a segment of 3+ words faster than this is not speech
SLIVER = 0.25              # a kept range with no word shorter than this is dropped
MAX_END_OVERSHOOT = 1.0     # a word may end this long after the audio's duration, as read from the file


def check_transcript(doc, limits: dict) -> dict:
    """The transcriber's transcript.json (providers/transcriber/transcript.schema.json), checked for what the renderer
    reads: words with `index`, `text`, `start`, `end`, `segment`. Returns {duration, words, segments}; the text of
    every word is hardened (NFC, no Cc, Cf, Zl or Zp character)."""
    if not isinstance(doc, dict) or doc.get("schema_version") != 1:
        raise Refusal("transcript_schema", "schema_version")
    duration = doc.get("duration")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
        raise Refusal("transcript_duration", "duration")
    words = doc.get("words")
    if not isinstance(words, list) or not words:
        raise Refusal("transcript_words", "words")
    if len(words) > limits["words_max"]:
        raise Refusal("too_many_words", "words")
    out = []
    for pos, w in enumerate(words):
        if not isinstance(w, dict) or w.get("index") != pos:
            raise Refusal("word_index", "word%d" % pos)
        s, e = w.get("start"), w.get("end")
        if any(not isinstance(x, (int, float)) or isinstance(x, bool) for x in (s, e)) or s < 0 or e < 0:
            raise Refusal("word_time", "word%d" % pos)
        if s > duration + MAX_END_OVERSHOOT:
            raise Refusal("word_time", "word%d" % pos)
        if not isinstance(w.get("segment"), int) or w["segment"] < 0:
            raise Refusal("word_segment", "word%d" % pos)
        out.append({"index": pos, "text": clean_text(w.get("text"), limits["word_chars_max"], "word%d" % pos),
                    "start": float(s), "end": float(e), "segment": w["segment"], "estimated": bool(w.get("estimated"))})
    segments = []
    for seg in doc.get("segments") or []:
        if isinstance(seg, dict) and isinstance(seg.get("index"), int) and all(
                isinstance(seg.get(k), (int, float)) and not isinstance(seg.get(k), bool) for k in ("start", "end")):
            segments.append({"index": seg["index"], "start": float(seg["start"]), "end": float(seg["end"])})
    return {"duration": float(duration), "words": out, "segments": segments}


def normalise_words(words: list, segments: list, duration: float) -> tuple:
    """Return (words, report). `words` keeps every index and gains `dropped` (a bool); times are made safe:

      1. A segment of 3 or more words whose rate is over 8 words a second (by its own start and end when the transcript
         gives them, else by its words') is dropped: whisper repeated a sentence in a fraction of a second.
      2. A word that ends before it starts ends where it starts. A start that goes back in time is moved up to the
         previous start (clamped).
      3. A run of consecutive words of zero length is spread evenly from the run's start to the start of the next word,
         at least 40 ms each; the words are marked `estimated`. A word that remains of zero length gets 40 ms.

    The report counts what was done (never a text) for the base list's facts."""
    seg_times = {s["index"]: (s["start"], s["end"]) for s in segments}
    by_segment = {}
    for w in words:
        by_segment.setdefault(w["segment"], []).append(w["index"])
    dropped_segments = []
    drop = set()
    for seg, members in sorted(by_segment.items()):
        if len(members) < 3:
            continue
        if seg in seg_times:
            span = max(0.0, seg_times[seg][1] - seg_times[seg][0])
        else:
            span = max(0.0, max(words[i]["end"] for i in members) - min(words[i]["start"] for i in members))
        if len(members) > MAX_WORDS_PER_SECOND * span:
            drop.update(members)
            dropped_segments.append({"segment": seg, "words": len(members), "seconds": round(span, 3)})
    out = [dict(w, dropped=w["index"] in drop) for w in words]
    live = [w for w in out if not w["dropped"]]
    clamped = 0
    prev_start = 0.0
    for w in live:
        if w["end"] < w["start"]:
            w["end"] = w["start"]
        if w["start"] < prev_start:
            w["start"] = prev_start
            clamped += 1
            w["end"] = max(w["end"], w["start"])
        prev_start = w["start"]
    estimated_runs = 0
    k = 0
    while k < len(live):
        if live[k]["end"] > live[k]["start"]:
            k += 1
            continue
        j = k
        while j + 1 < len(live) and live[j + 1]["end"] <= live[j + 1]["start"]:
            j += 1
        count = j - k + 1
        run_start = live[k]["start"]
        next_start = live[j + 1]["start"] if j + 1 < len(live) else duration
        slot = max(MIN_WORD_SECONDS, (next_start - run_start) / count)
        for m in range(count):
            w = live[k + m]
            w["start"] = round(run_start + m * slot, 4)
            w["end"] = round(run_start + (m + 1) * slot, 4)
            w["estimated"] = True
        estimated_runs += 1
        k = j + 1
    # a spread that ran into the next word moves that word's start up (starts stay non-decreasing)
    prev_start = 0.0
    for w in live:
        if w["start"] < prev_start:
            w["start"] = prev_start
            clamped += 1
            w["end"] = max(w["end"], w["start"] + MIN_WORD_SECONDS)
        prev_start = w["start"]
    report = {"words": len(words), "dropped_words": len(drop), "dropped_segments": dropped_segments,
              "zero_length_words": sum(1 for w in words if w["end"] <= w["start"]), "spread_runs": estimated_runs,
              "estimated_words": sum(1 for w in out if w["estimated"] and not w["dropped"]), "clamped_starts": clamped}
    return out, report


def plausible_seconds(text: str) -> float:
    """How long a spoken word takes at most when nothing stretches it."""
    return 0.25 + 0.07 * sum(1 for c in text if c.isalpha())


def protected_spans(words: list) -> list:
    """The part of each live word a silence may not cut. A word whose span is far longer than the word takes (the
    transcriber lets a word run on over the pause after it) is protected only for the time the word plausibly takes,
    so that the silence inside the stretched span can still be cut."""
    spans = []
    for w in words:
        dur = w["end"] - w["start"]
        plausible = plausible_seconds(w["text"])
        spans.append((w["start"], min(w["end"], w["start"] + plausible)) if dur > 1.5 * plausible + 0.2 else (w["start"], w["end"]))
    return spans


def _subtract(piece, spans):
    """The parts of (lo, hi) that no span covers."""
    parts, lo = [], piece[0]
    for a, b in sorted(spans):
        if b <= lo or a >= piece[1]:
            continue
        if a > lo:
            parts.append((lo, a))
        lo = max(lo, b)
    if lo < piece[1]:
        parts.append((lo, piece[1]))
    return parts


def _merge(intervals):
    out = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def kept_ranges(words: list, duration: float, fps: int, silences=None, margin: float = 0.08, min_cut: float = 0.12,
                min_kept: float = 0.4, gap: float = 0.5, forced=()) -> list:
    """Kept [from_frame, to_frame) ranges of the recording on the grid of `fps`.

    Silence is the cut signal. Every silence interval silencedetect found is cut, less `margin` seconds on each side (none
    at the very start and end of the recording), except where a word is: the words only protect speech (a stretched word
    is protected for the time it plausibly takes, see protected_spans). With `silences=None` (no audio to ask) the gaps
    between words longer than `gap` are cut instead. `forced` is a list of (start, end) seconds cut whatever is in them
    (the takes the person confirmed as retakes). A cut shorter than `min_cut` is not made. A kept range shorter than
    `min_kept` that holds no word is cut, and one that holds a word is joined to its neighbour across the shorter
    cut (the cut is given up) so that nothing flickers; a range between two forced cuts stays as it is."""
    if not words:
        raise Refusal("no_words")
    total = int(math.floor(duration * fps + 1e-6))
    protect = protected_spans(words)
    if silences is None:
        regions = [(0.0, words[0]["start"] - margin)]
        for a, b in zip(words, words[1:]):
            if b["start"] - a["end"] > gap:
                regions.append((a["end"] + margin, b["start"] - margin))
        regions.append((words[-1]["end"] + margin, duration))
        base = [r for r in regions if r[1] > r[0]]
    else:
        base = []
        for s, e in silences:
            lo = 0.0 if s <= 0.001 else s + margin
            hi = duration if e >= duration - 0.05 else e - margin
            if hi > lo:
                base.append((lo, hi))
    cuts = []
    for piece in base:
        cuts.extend(p for p in _subtract(piece, protect) if p[1] - p[0] >= min_cut)
    cuts = [(c, False) for c in _merge(cuts)] + [(f, True) for f in _merge(list(forced))]

    def to_frames(item):
        (lo, hi), is_forced = item
        a, b = int(math.ceil(lo * fps - 1e-6)), int(math.floor(hi * fps + 1e-6))   # inward: the kept side keeps the margin
        return (max(0, a), min(total, b), is_forced)

    grid = sorted(c for c in map(to_frames, cuts) if c[1] > c[0])
    merged = []
    for a, b, f in grid:                       # overlapping cuts become one; a forced one keeps its flag
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b), merged[-1][2] or f)
        else:
            merged.append((a, b, f))
    min_frames = int(math.ceil(min_kept * fps - 1e-6))

    def has_word(a, b):
        return any(w["start"] < b / fps and w["end"] > a / fps for w in words)

    changed = True
    while changed:
        changed = False
        bounds = [0] + [x for c in merged for x in c[:2]] + [total]
        ranges = [(bounds[i], bounds[i + 1]) for i in range(0, len(bounds), 2) if bounds[i + 1] > bounds[i]]
        for r_a, r_b in ranges:
            if r_b - r_a >= min_frames:
                continue
            before = next((k for k, c in enumerate(merged) if c[1] == r_a), None)
            after = next((k for k, c in enumerate(merged) if c[0] == r_b), None)
            if not has_word(r_a, r_b):
                new = [c for c in merged if c[1] != r_a and c[0] != r_b]
                lo = merged[before][0] if before is not None else r_a
                hi = merged[after][1] if after is not None else r_b
                merged = new + [(lo, hi, (before is not None and merged[before][2]) or (after is not None and merged[after][2]))]
                merged.sort()
                changed = True
                break
            options = [k for k in (before, after) if k is not None and not merged[k][2]]
            if not options:
                continue
            k = min(options, key=lambda i: merged[i][1] - merged[i][0])
            merged.pop(k)
            changed = True
            break
    bounds = [0] + [x for c in merged for x in c[:2]] + [total]
    return [[bounds[i], bounds[i + 1]] for i in range(0, len(bounds), 2) if bounds[i + 1] > bounds[i]]


def detect_retakes(words: list, window: float = 20.0, run: int = 4, pause: float = 0.6) -> list:
    """Retakes by rule, as proposals. Never applied here: the person confirms each one (a proposal is data in the edit
    list, struck through on the page; the render drops only a confirmed one).

      repeat   a run of at least `run` normalised words that occurs again within `window` seconds: the earlier take, from
               its first word up to the word before the later one, is proposed for dropping;
      restart  a sentence that was cut mid-way and begun again: the first of two consecutive sentences does not end in
               sentence punctuation, is not longer than the second, starts with the same two normalised words and the second begins within
               `window` seconds: propose dropping the first.

    A proposal holds indices only: {kind, word_from, word_to (the words to drop), keep_from (the first word of the take that
    stays), seconds}. Proposals never overlap; the earlier one wins."""
    toks = []                                  # (normalised token, word index, start)
    from _align import norm_tokens
    for w in words:
        for t in norm_tokens(w["text"]):
            toks.append((t, w["index"], w["start"]))
    found = []
    n = len(toks)
    i = 0
    while i < n:
        best = None
        for j in range(i + 1, n):
            if toks[j][2] - toks[i][2] > window:
                break
            length = 0
            while j + length < n and i + length < j and toks[i + length][0] == toks[j + length][0]:
                length += 1
            if length >= run and (best is None or length > best[1]):
                best = (j, length)
        if best:
            j, length = best
            found.append({"kind": "repeat", "word_from": toks[i][1], "word_to": toks[j][1] - 1, "keep_from": toks[j][1],
                          "seconds": 0.0})
            i = j
        else:
            i += 1
    # sentences: split at a sentence end or a pause
    sentences, cur = [], []
    for k, w in enumerate(words):
        cur.append(w)
        nxt = words[k + 1] if k + 1 < len(words) else None
        if w["text"].rstrip("\"')]»”’").endswith((".", "?", "!", "…")) or nxt is None or nxt["start"] - w["end"] > pause:
            sentences.append(cur)
            cur = []
    for a, b in zip(sentences, sentences[1:]):
        ta = [t for w in a for t in norm_tokens(w["text"])]
        tb = [t for w in b for t in norm_tokens(w["text"])]
        ended = a[-1]["text"].rstrip("\"')]»”’").endswith((".", "?", "!", "…"))
        if len(ta) >= 2 and ta[:2] == tb[:2] and len(ta) <= len(tb) and not ended and b[0]["start"] - a[-1]["end"] <= window:
            found.append({"kind": "restart", "word_from": a[0]["index"], "word_to": a[-1]["index"], "keep_from": b[0]["index"], "seconds": 0.0})
    found.sort(key=lambda p: (p["word_from"], p["word_to"]))
    out, last_to = [], -1
    by_index = {w["index"]: w for w in words}
    for p in found:
        if p["word_from"] <= last_to:
            continue
        last_to = p["word_to"]
        p["seconds"] = round(by_index[p["word_to"]]["end"] - by_index[p["word_from"]]["start"], 3)
        out.append(dict(p, id="retake-%d" % (len(out) + 1), confirmed=False))
    return out


def out_offsets(kept: list) -> list:
    """For each kept range, the output frame it starts at."""
    pos, rows = 0, []
    for a, b in kept:
        rows.append(pos)
        pos += b - a
    return rows


def out_frames_of(kept: list) -> int:
    return sum(b - a for a, b in kept)


def src_to_out_seconds(kept: list, fps: int, t: float) -> float:
    """A source time on the output timeline. A time inside a cut snaps to the nearest kept edge."""
    starts = out_offsets(kept)
    best, best_d = None, None
    for (a, b), off in zip(kept, starts):
        lo, hi = a / fps, b / fps
        if lo - 1e-9 <= t <= hi + 1e-9:
            return (off + (t * fps - a)) / fps
        d = min(abs(t - lo), abs(t - hi))
        if best is None or d < best_d:
            best, best_d = ((a, b), off), d
    (a, b), off = best
    return off / fps if t < a / fps else (off + b - a) / fps


def build_words(words: list, kept: list, fps: int) -> list:
    """The live words on the output timeline: {index, text, start, end[, estimated]}, times in seconds, 3 decimals."""
    rows = []
    for w in words:
        if w["dropped"]:
            continue
        s, e = src_to_out_seconds(kept, fps, w["start"]), src_to_out_seconds(kept, fps, w["end"])
        row = {"index": w["index"], "text": w["text"], "start": round(s, 3), "end": round(max(e, s), 3)}
        if w["estimated"]:
            row["estimated"] = True
        rows.append(row)
    return rows


def caption_chunks(words: list, max_words: int, max_chars: int, pause: float) -> list:
    """Caption chunks as [word_from, word_to] pairs of word indices. A chunk ends at max_words words, at max_chars
    characters, after a word that ends a sentence, or before a pause longer than `pause` (the transcript's own segments
    are not used: in the one-word-per-segment mode every word would be a chunk)."""
    chunks, cur, chars = [], [], 0
    for k, w in enumerate(words):
        if cur and (len(cur) >= max_words or chars + 1 + len(w["text"]) > max_chars):
            chunks.append(cur)
            cur, chars = [], 0
        cur.append(w)
        chars += len(w["text"]) + (1 if len(cur) > 1 else 0)
        ends_sentence = w["text"].rstrip("\"')]»”’").endswith((".", "?", "!", "…"))
        nxt = words[k + 1] if k + 1 < len(words) else None
        if ends_sentence or nxt is None or nxt["start"] - w["end"] > pause:
            chunks.append(cur)
            cur, chars = [], 0
    if cur:
        chunks.append(cur)
    return [[c[0]["index"], c[-1]["index"]] for c in chunks]


def chunk_times(chunks: list, words_by_index: dict, out_duration: float, hold: float) -> list:
    """Out-timeline [start, end] seconds of each chunk: it starts at its first word and ends `hold` after its last,
    or where the next chunk starts when they touch (within 0.4 s) and the chunk does not end a sentence's pause."""
    rows = []
    for k, (a, b) in enumerate(chunks):
        start, word_end = words_by_index[a]["start"], words_by_index[b]["end"]
        end = word_end + hold
        if k + 1 < len(chunks):
            nxt = words_by_index[chunks[k + 1][0]]["start"]
            end = nxt if nxt - word_end <= 0.4 else min(end, nxt)
        rows.append((start, min(end, out_duration)))
    return rows

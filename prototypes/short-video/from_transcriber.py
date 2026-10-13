#!/usr/bin/env python3
"""Read the raw output of the transcriber provider (`transcriber:speech`) and fix it in code.

The provider's schema (schema_version 1): `words` (index, text, start, end, segment, probability), `segments`
(index, start, end, text, first_word, last_word) and `facts`. Word timestamps from a speech model are estimates and
the raw output has known faults, each repaired here and reported, never silently:

  1. a segment with an impossible speech rate (more than --max-rate words per second, for 3 or more words) is a
     hallucinated repeat (a model that loops at the end of a recording): its words are dropped;
  2. a run of words with no duration (start equal to end, the model gave the run one instant) is spread evenly over
     the time before the next word starts (at least --min-word seconds each), and flagged `estimated`;
  3. when silences are given (`--silences`, from ffmpeg silencedetect), a segment that holds a run of
     --retime-run or more zero-length words has broken timing: its words are placed over the segment's non-silent
     intervals in proportion to their letters (flagged `retimed`), so the words land where the audio has speech;
  4. the times are made monotonic and non-overlapping, every word at least --min-word long, inside the recording.

The output is the prototype's transcript.json (words with `i`, `text`, `start`, `end`, `segment`) plus
`probability`, `estimated`, `src_index` (the index in the raw file), `segments`, and `fixes`: one entry per repair.
Word indices of the result are the ones `--anchor` takes.

  python3 from_transcriber.py --raw t.json --out transcript.json
"""
import argparse
import json
import os
import sys

MIN_WORD = 0.04
MAX_RATE = 8.0
ZERO = 1e-6


class TranscriptError(ValueError):
    pass


def _check_raw(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("words"), list) or not raw["words"]:
        raise TranscriptError("raw transcript has no words")
    dur = raw.get("duration")
    if not isinstance(dur, (int, float)) or dur <= 0:
        raise TranscriptError("raw transcript has no duration")
    for k, w in enumerate(raw["words"]):
        if not isinstance(w.get("text"), str) or not isinstance(w.get("start"), (int, float)) \
                or not isinstance(w.get("end"), (int, float)) or not isinstance(w.get("segment"), int):
            raise TranscriptError("word %d is malformed" % k)


def drop_impossible_segments(words, segments, max_rate, fixes):
    """Drop the words of every segment whose rate exceeds `max_rate` (3 or more words). Returns the kept words."""
    seg_span = {}
    for s in segments or []:
        seg_span[s["index"]] = (s["start"], s["end"])
    by_seg = {}
    for w in words:
        by_seg.setdefault(w["segment"], []).append(w)
    drop = set()
    for seg, ws in by_seg.items():
        if len(ws) < 3:
            continue
        start, end = seg_span.get(seg, (ws[0]["start"], ws[-1]["end"]))
        span = max(end - start, ws[-1]["end"] - ws[0]["start"], 0.0) if seg not in seg_span else max(end - start, 0.0)
        rate = len(ws) / max(span, 1e-3)
        if rate > max_rate:
            drop.add(seg)
            fixes.append({"fix": "dropped_segment", "segment": seg, "words": len(ws),
                          "src_from": ws[0]["src_index"], "src_to": ws[-1]["src_index"],
                          "start": round(start, 3), "end": round(end, 3), "rate": round(rate, 1),
                          "text": " ".join(w["text"] for w in ws)[:160],
                          "why": "%.1f words per second is not speech (limit %.1f): a repeated or hallucinated segment"
                                 % (rate, max_rate)})
    return [w for w in words if w["segment"] not in drop]


def spread_zero_runs(words, min_word, fixes):
    """Spread each run of zero-length words evenly up to the next word's start (at least `min_word` each)."""
    k, n = 0, len(words)
    while k < n:
        if words[k]["end"] - words[k]["start"] > ZERO:
            k += 1
            continue
        j = k
        while j < n and words[j]["end"] - words[j]["start"] <= ZERO:
            j += 1
        run = words[k:j]
        t = run[0]["start"]
        nxt = words[j]["start"] if j < n else None
        prev_end = words[k - 1]["end"] if k > 0 else 0.0
        count = len(run)
        if nxt is None:
            s = max(t, prev_end)
            slot = min_word
        else:
            s = min(t, nxt - count * min_word)
            s = max(s, prev_end)
            slot = max(min_word, (nxt - s) / count)
        for q, w in enumerate(run):
            w["start"] = s + q * slot
            w["end"] = s + (q + 1) * slot
            w["estimated"] = True
            w["zero_run"] = True
        fixes.append({"fix": "spread_zero_length_run", "words": count, "dst_from": run[0]["i"], "dst_to": run[-1]["i"],
                      "at": round(t, 3), "to": round(nxt, 3) if nxt is not None else None,
                      "slot_ms": int(round(slot * 1000)), "text": " ".join(w["text"] for w in run)[:80]})
        k = j


def _speech_intervals(silences, lo, hi, min_speech):
    """Non-silent intervals inside [lo, hi] (silences is a sorted list of (start, end))."""
    out, cur = [], lo
    for a, b in sorted(silences):
        if b <= lo or a >= hi:
            continue
        if a > cur:
            out.append((cur, min(a, hi)))
        cur = max(cur, b)
    if cur < hi:
        out.append((cur, hi))
    return [(a, b) for a, b in out if b - a >= min_speech]


def _coverage(a, b, silences):
    cov = 0.0
    for s, e in silences:
        lo, hi = max(a, s), min(b, e)
        if hi > lo:
            cov += hi - lo
    return cov / (b - a) if b > a else 1.0


def retime_broken_segments(words, silences, retime_run, min_speech, fixes, phantom=0.8, phantom_share=0.25):
    """Place the words of a broken segment over the segment's speech, by letters.

    A segment is broken when it holds a run of `retime_run` zero-length words, or when at least `phantom_share` of its
    words (and 2 or more) lie inside a silence (`phantom` of their span): the model timed them where nothing is said."""
    by_seg = {}
    for w in words:
        by_seg.setdefault(w["segment"], []).append(w)
    segs = sorted(by_seg)
    for pos, seg in enumerate(segs):
        ws = by_seg[seg]
        run, longest = 0, 0
        for w in ws:
            run = run + 1 if w.get("zero_run") else 0
            longest = max(longest, run)
        n_phantom = sum(1 for w in ws if _coverage(w["start"], w["end"], silences) >= phantom)
        by_run = longest >= retime_run
        by_phantom = n_phantom >= 2 and n_phantom >= phantom_share * len(ws)
        if not (by_run or by_phantom):
            continue
        lo = max(0.0, ws[0]["orig_start"] - 0.3)
        hi = ws[-1]["end"] + 0.3
        if pos > 0:
            lo = max(lo, by_seg[segs[pos - 1]][-1]["end"])
        if pos + 1 < len(segs):
            hi = min(hi, by_seg[segs[pos + 1]][0]["start"])
        spans = _speech_intervals(silences, lo, hi, min_speech)
        total = sum(b - a for a, b in spans)
        if not spans or total < 0.05 * len(ws):
            continue
        weights = [len(w["text"]) + 1 for w in ws]
        wsum = float(sum(weights))

        def wall(x):
            """Concatenated speech time -> (wall time, interval index)."""
            for k, (a, b) in enumerate(spans):
                if x <= (b - a) + 1e-9:
                    return a + x, k
                x -= (b - a)
            return spans[-1][1], len(spans) - 1

        before = (round(ws[0]["start"], 3), round(ws[-1]["end"], 3))
        cum = 0.0
        for w, wt in zip(ws, weights):
            t0, k0 = wall(total * cum / wsum)
            t1, k1 = wall(total * (cum + wt) / wsum)
            cum += wt
            if k0 != k1:     # a word never straddles a silence: it goes to the interval that holds most of it
                a0, b0 = spans[k0]
                if b0 - t0 >= t1 - spans[k1][0]:
                    t1 = b0
                else:
                    t0 = spans[k1][0]
            w["start"], w["end"] = t0, max(t1, t0 + 1e-3)
            w["estimated"] = True
            w["retimed"] = True
        fixes.append({"fix": "retimed_segment", "dst_segment": seg, "words": len(ws), "dst_from": ws[0]["i"],
                      "dst_to": ws[-1]["i"], "longest_zero_run": longest, "words_in_silence": n_phantom, "speech_intervals": len(spans),
                      "from": list(before), "to": [round(ws[0]["start"], 3), round(ws[-1]["end"], 3)],
                      "why": ("a run of %d words had no duration" % longest if by_run else
                              "%d words were timed inside silence" % n_phantom) + ": the segment's words are placed over its speech"})


def clamp_times(words, duration, min_word, fixes):
    """Monotonic, non-overlapping, at least `min_word` long, inside [0, duration]."""
    prev_end = 0.0
    for w in words:
        s, e = w["start"], w["end"]
        s2 = min(max(s, prev_end), max(duration - min_word, 0.0))
        e2 = min(max(e, s2 + min_word), duration)
        if e2 - s2 < min_word - 1e-9:
            s2 = max(0.0, e2 - min_word)
        if abs(s2 - s) > 1e-6 or abs(e2 - e) > 1e-6:
            fixes.append({"fix": "clamped", "dst": w["i"], "text": w["text"][:40],
                          "from": [round(s, 3), round(e, 3)], "to": [round(s2, 3), round(e2, 3)]})
            w["estimated"] = True
        w["start"], w["end"] = s2, e2
        prev_end = e2


def normalise(raw, max_rate=MAX_RATE, min_word=MIN_WORD, silences=None, retime_run=4, min_speech=0.25):
    """Raw provider JSON -> (transcript dict, fixes list). `silences` is a list of (start, end) or None."""
    _check_raw(raw)
    fixes = []
    words = [dict(w, src_index=w.get("index", k)) for k, w in enumerate(raw["words"])]
    words = drop_impossible_segments(words, raw.get("segments"), max_rate, fixes)
    if not words:
        raise TranscriptError("no words are left after the repairs")
    # renumber words and segments (segment numbers stay in order, with no holes)
    seg_ids, out = {}, []
    for w in words:
        seg_ids.setdefault(w["segment"], len(seg_ids))
    for pos, w in enumerate(words):
        out.append({"i": pos, "text": w["text"].strip(), "start": float(w["start"]), "end": float(w["end"]),
                    "segment": seg_ids[w["segment"]], "probability": w.get("probability"), "src_index": w["src_index"]})
    for w in out:
        w["orig_start"] = w["start"]
    spread_zero_runs(out, min_word, fixes)
    if silences:
        retime_broken_segments(out, silences, retime_run, min_speech, fixes)
    clamp_times(out, float(raw["duration"]), min_word, fixes)
    for w in out:
        w["start"], w["end"] = round(w["start"], 3), round(w["end"], 3)
        w.setdefault("estimated", False)
        w.pop("orig_start", None)
        w.pop("zero_run", None)
        w.setdefault("retimed", False)
    segments = []
    for seg in range(len(seg_ids)):
        ws = [w for w in out if w["segment"] == seg]
        segments.append({"index": seg, "first_word": ws[0]["i"], "last_word": ws[-1]["i"], "start": ws[0]["start"],
                         "end": ws[-1]["end"], "text": " ".join(w["text"] for w in ws)})
    tr = {"language": raw.get("language", "unknown"), "duration": float(raw["duration"]), "words": out,
          "segments": segments, "fixes": fixes,
          "source": {"schema_version": raw.get("schema_version"), "words": len(raw["words"]),
                     "model": (raw.get("facts") or {}).get("model", {}).get("name")}}
    return tr, fixes


def summarise(fixes):
    counts = {}
    for f in fixes:
        counts[f["fix"]] = counts.get(f["fix"], 0) + 1
    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True, help="the transcriber provider's JSON")
    ap.add_argument("--out", required=True, help="transcript.json to write")
    ap.add_argument("--max-rate", type=float, default=MAX_RATE, help="words per second above which a segment is dropped (default 8)")
    ap.add_argument("--min-word", type=float, default=MIN_WORD, help="shortest word (s, default 0.04)")
    ap.add_argument("--silences", help="JSON list of {start,end} (ffmpeg silencedetect); enables the retiming of broken segments")
    ap.add_argument("--retime-run", type=int, default=4, help="zero-length words in a row that mark a segment as broken (default 4)")
    ap.add_argument("--verbose", action="store_true", help="print every fix")
    args = ap.parse_args(argv)
    try:
        with open(args.raw, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        silences = None
        if args.silences:
            with open(args.silences, "r", encoding="utf-8") as fh:
                silences = [(x["start"], x["end"]) for x in json.load(fh)]
        tr, fixes = normalise(raw, args.max_rate, args.min_word, silences, args.retime_run)
    except (OSError, ValueError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(tr, fh, indent=1, ensure_ascii=False)
    print("%d words (%d in the raw file); fixes: %s" % (len(tr["words"]), len(raw["words"]), summarise(fixes) or "none"),
          file=sys.stderr)
    if args.verbose:
        for f in fixes:
            print(json.dumps(f, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

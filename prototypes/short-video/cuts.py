"""Cut planning: silence is the primary signal, words only protect speech.

  1. Every silence the audio shows (ffmpeg silencedetect, `noise` dB, at least `min` seconds; both are flags of the
     renderer and are reported) is a cut candidate. A margin of speech stays on each side of it: `pad_tail` after the
     word that ended before the silence (its tail) and `pad_head` before the word that follows (its attack). The
     leading and trailing silence of the recording are cut without a margin on the outer side.
  2. A word protects its span from a cut, with one exception. A word that is not stretched (shorter than `stretch`
     seconds) and is not lying inside a silence (a phantom word the model put in a quiet part) has energy: no cut
     ever goes through it. A stretched word (a model that spread one word over seconds of silence) protects nothing:
     the silence inside it is cut.
  3. The takes the retake detector found are cut as a whole, from the silence before the earlier take to the silence
     before the later one, each side with its margin.
  4. A kept range shorter than `min_keep` seconds is never left: when it holds a word, the smaller neighbouring
     silence cut is cancelled; when it holds none, it is cut with its neighbours. A kept range shorter than `wordless`
     seconds that holds no transcribed word at all (the speaker moving, a cough) is not speech and is cut too.
  5. Kept ranges are widened to the frame grid, so a cut never eats into a margin.

Pure functions of the words, the silences and the numbers; nothing here reads or writes media.
"""
import math

PAD_HEAD = 0.10        # speech kept before the first word after a silence (its attack)
PAD_TAIL = 0.14        # speech kept after the last word before a silence (its tail)
MIN_CUT = 0.15         # a cut shorter than this is not worth a jump
MIN_KEEP = 0.40        # no kept range is shorter than this
WORDLESS = 1.5         # a kept range shorter than this that holds no transcribed word is not speech: it is cut
STRETCH = 1.0          # a word longer than this (seconds) is a timing artefact, not a protected span
PHANTOM = 0.8          # a word covered by silence for this fraction of its span has no energy
WORD_GUARD = 0.02      # protected span = the word widened by this on each side


def _coverage(a, b, silences):
    """Fraction of [a, b] that lies inside a silence."""
    if b <= a:
        return 0.0
    cov = 0.0
    for s, e in silences:
        lo, hi = max(a, s), min(b, e)
        if hi > lo:
            cov += hi - lo
    return min(1.0, cov / (b - a))


def _subtract(region, spans):
    """Pieces of (a, b) outside every (s, e) in spans."""
    pieces = [region]
    for s, e in spans:
        nxt = []
        for a, b in pieces:
            if e <= a or s >= b:
                nxt.append((a, b))
                continue
            if s > a:
                nxt.append((a, s))
            if e < b:
                nxt.append((e, b))
        pieces = nxt
    return pieces


def protected_spans(words, silences, stretch=STRETCH):
    """Spans of the words that have energy (see the module doc), widened by WORD_GUARD."""
    spans = []
    for w in words:
        if w.get("dropped"):
            continue
        if w["end"] - w["start"] > stretch:
            continue
        if _coverage(w["start"], w["end"], silences) >= PHANTOM:
            continue
        spans.append((w["start"] - WORD_GUARD, w["end"] + WORD_GUARD))
    return spans


def retake_region(words, silences, retake, duration, pad_head=PAD_HEAD, pad_tail=PAD_TAIL):
    """The cut that removes one earlier take: (start, end) or None."""
    first, last = words[retake["word_from"]], words[retake["word_to"]]
    prev_end, next_start = 0.0, duration
    for w in reversed(words[:retake["word_from"]]):
        if not w.get("dropped"):
            prev_end = w["end"]
            break
    for w in words[retake["word_to"] + 1:]:
        if not w.get("dropped"):
            next_start = w["start"]
            break
    # before: the silence that ends at the earlier take's start (the pause the speaker made before it)
    a = max(first["start"] - 0.02, prev_end + 0.02)
    before = [(s, e) for s, e in silences if first["start"] - 0.8 <= e <= first["start"] + 0.5 and s < first["start"]]
    if before:
        s, e = max(before, key=lambda x: x[1])
        a = max(s + pad_tail, prev_end + 0.02)
    # after: the silence that ends at the later take's start
    b = next_start - pad_head
    after = [(s, e) for s, e in silences if last["end"] - 0.6 <= s <= next_start + 0.3 and e <= next_start + 0.6 and e > s]
    if after:
        s, e = max(after, key=lambda x: x[1])
        b = min(e - pad_head, next_start - 0.02)
    return (a, b) if b - a > MIN_CUT else None


def _complement(cuts, duration):
    kept, cur = [], 0.0
    for c in sorted(cuts, key=lambda c: c["start"]):
        if c["start"] > cur:
            kept.append((cur, c["start"]))
        cur = max(cur, c["end"])
    if cur < duration:
        kept.append((cur, duration))
    return kept


def _union(cuts):
    out = []
    prio = {"retake": 3, "silence": 2, "lead": 1, "trail": 1}
    for c in sorted(cuts, key=lambda c: (c["start"], c["end"])):
        if out and c["start"] <= out[-1]["end"] + 1e-9:
            out[-1]["end"] = max(out[-1]["end"], c["end"])
            if prio[c["reason"]] > prio[out[-1]["reason"]]:
                out[-1]["reason"] = c["reason"]
        else:
            out.append(dict(c))
    return out


def plan(words, silences, duration, fps, retakes=(), pad_head=PAD_HEAD, pad_tail=PAD_TAIL, min_cut=MIN_CUT,
         min_keep=MIN_KEEP, stretch=STRETCH, wordless=WORDLESS):
    """Return {"kept": [(s, e)], "cuts": [{start, end, reason}], "notes": [...], "stats": {...}}."""
    silences = sorted((float(s), float(e)) for s, e in silences)
    notes = []
    protect = protected_spans(words, silences, stretch)
    cuts = []
    for s, e in silences:
        lead, trail = s <= 1e-3, e >= duration - 1e-3
        a = s + (0.0 if lead else pad_tail)
        b = e - (0.0 if trail else pad_head)
        if b - a < min_cut:
            continue
        for pa, pb in _subtract((a, b), protect):
            if pb - pa >= min_cut:
                cuts.append({"start": pa, "end": pb, "reason": "lead" if lead else "trail" if trail else "silence"})
    for r in retakes:
        reg = retake_region(words, silences, r, duration, pad_head, pad_tail)
        if reg is None:
            notes.append("retake at word %d: no region to cut" % r["word_from"])
            continue
        cuts.append({"start": reg[0], "end": reg[1], "reason": "retake"})
    cuts = _union(cuts)

    # no kept range shorter than min_keep
    accepted = set()

    def speech_in(a, b):
        return [w for w in words if not w.get("dropped") and a - 1e-9 <= (w["start"] + w["end"]) / 2 <= b + 1e-9
                and _coverage(w["start"], w["end"], silences) < PHANTOM]

    while True:
        kept = _complement(cuts, duration)
        frag = next((k for k, (a, b) in enumerate(kept)
                     if (round(a, 3), round(b, 3)) not in accepted
                     and (b - a < min_keep - 1e-9 or (b - a < wordless and not speech_in(a, b)))), None)
        if frag is None:
            break
        a, b = kept[frag]
        before = next((c for c in cuts if abs(c["end"] - a) < 1e-9), None)
        after = next((c for c in cuts if abs(c["start"] - b) < 1e-9), None)
        speech = speech_in(a, b)
        if speech:
            cand = [c for c in (before, after) if c is not None and c["reason"] != "retake"]
            if cand:
                small = min(cand, key=lambda c: c["end"] - c["start"])
                cuts.remove(small)
                notes.append("kept %.2f s fragment %.2f-%.2f holds %r: the cut %.2f-%.2f was cancelled"
                             % (b - a, a, b, " ".join(w["text"] for w in speech)[:40], small["start"], small["end"]))
            else:
                accepted.add((round(a, 3), round(b, 3)))
                notes.append("short kept fragment %.2f-%.2f (%.2f s) stays: it holds speech between two retake cuts" % (a, b, b - a))
        else:
            if before and after:
                before["end"] = after["end"]
                cuts.remove(after)
            elif before:
                before["end"] = duration
            elif after:
                after["start"] = 0.0
            else:
                accepted.add((round(a, 3), round(b, 3)))
            notes.append("kept %.2f s fragment %.2f-%.2f holds no speech: cut" % (b - a, a, b))
        cuts = _union(cuts)

    # frame grid: kept widened outward
    total_frames = int(math.floor(duration * fps + 1e-6))
    grid = []
    for a, b in _complement(cuts, duration):
        fs = max(0, int(math.floor(a * fps + 1e-6)))
        fe = min(total_frames, int(math.ceil(b * fps - 1e-6)))
        if fe > fs:
            grid.append([fs, fe])
    merged = []
    for fs, fe in grid:
        if merged and fs <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], fe)
        else:
            merged.append([fs, fe])
    kept = [(fs / fps, fe / fps) for fs, fe in merged]
    final_cuts = []
    cur = 0.0
    for a, b in kept:
        if a > cur + 1e-9:
            reason = next((c["reason"] for c in cuts if c["start"] < a and c["end"] > cur), "silence")
            final_cuts.append({"start": cur, "end": a, "reason": reason})
        cur = b
    if cur < duration - 1e-9:
        final_cuts.append({"start": cur, "end": duration, "reason": "trail"})

    # diagnostics: words with energy that a cut boundary goes through, and cuts inside a stretched word
    clipped, inside_long = [], []
    for w in words:
        if w.get("dropped"):
            continue
        wd = w["end"] - w["start"]
        for c in final_cuts:
            if wd > stretch:
                if c["start"] > w["start"] and c["end"] < w["end"] + 1e-9 and c["reason"] != "lead":
                    inside_long.append({"word": w["i"], "text": w["text"], "cut": [round(c["start"], 2), round(c["end"], 2)]})
                    break
            elif _coverage(w["start"], w["end"], silences) < PHANTOM:
                ov = min(w["end"], c["end"]) - max(w["start"], c["start"])
                if ov > 0.04:
                    clipped.append({"word": w["i"], "text": w["text"], "overlap_ms": int(ov * 1000),
                                    "estimated": bool(w.get("estimated")), "cut": [round(c["start"], 2), round(c["end"], 2)]})
                    break
    stats = {"silence_s": round(sum(e - s for s, e in silences), 2), "cut_s": round(sum(c["end"] - c["start"] for c in final_cuts), 2),
             "kept_s": round(sum(b - a for a, b in kept), 2), "kept_ranges": len(kept), "cuts": len(final_cuts),
             "words_with_energy": len(protect), "words_clipped": len(clipped), "cuts_inside_long_words": len(inside_long)}
    return {"kept": kept, "cuts": final_cuts, "notes": notes, "stats": stats, "clipped_words": clipped,
            "cuts_inside_long_words": inside_long}


def format_report(result, params):
    lines = ["cuts: %s" % ", ".join("%s=%s" % kv for kv in params.items()),
             "  %(kept_ranges)d kept ranges, %(cuts)d cuts, kept %(kept_s)s s of silence-cut source (%(silence_s)s s of silence detected)" % result["stats"]]
    for n in result["notes"]:
        lines.append("  note: " + n)
    if result["clipped_words"]:
        lines.append("  words a cut boundary clips: " + ", ".join("%s(%dms%s)" % (c["text"], c["overlap_ms"], ",est" if c["estimated"] else "")
                                                                  for c in result["clipped_words"][:20]))
    if result["cuts_inside_long_words"]:
        lines.append("  cuts made inside a stretched word: " + ", ".join("%s %s" % (c["text"], c["cut"]) for c in result["cuts_inside_long_words"]))
    return "\n".join(lines)

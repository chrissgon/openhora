"""Retake detection, deterministic, no model.

A retake is a take the speaker abandoned and said again. The earlier take is dropped and the later one kept. A
sentence (a transcript segment) is the earlier take of a retake when, after it ends, within `window` seconds, the same
words come again: a run of at least `min_run` words in a row (compared fuzzily, so "muita" matches "muito") that
starts within the first `start_slack` words of the sentence and the later words also carry at least `min_share` of the
sentence's words in order (so a four-word opener that goes somewhere else is not a repeat). That covers both a sentence repeated whole and a sentence
that stopped mid-way and restarted. Each retake is reported with its words, times and the take that replaces it, so
that a person can undo it: the cutter applies the list, and this module never touches the media.

Prototype limits, stated: it reads sentences (the transcript's segments); a retake that begins in the middle of a
sentence the model did not split is found only when the repeated run starts near the sentence's start.
"""
import tokens as T

WINDOW = 20.0
MIN_RUN = 4
START_SLACK = 2
MIN_SHARE = 0.5


def _unit_tokens(words, first, last):
    toks, widx = [], []
    for w in words[first:last + 1]:
        for t in T.norm_tokens(w["text"]):
            toks.append(t)
            widx.append(w["i"])
    return toks, widx


def _longest_run(a, b, a_limit):
    """Longest run of fuzzily equal tokens a[i:i+r] == b[j:j+r] with i < a_limit. Returns (r, i, j)."""
    best = (0, 0, 0)
    for i in range(min(a_limit, len(a))):
        for j in range(len(b)):
            r = 0
            while i + r < len(a) and j + r < len(b) and T.token_sim(a[i + r], b[j + r]) > 0:
                r += 1
            if r > best[0]:
                best = (r, i, j)
    return best


def _lcs(a, b):
    """Length of the longest common subsequence of fuzzily equal tokens."""
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if T.token_sim(x, y) > 0 else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def segments_of(words):
    """[(first_word, last_word)] of the transcript's segments, in order."""
    out, cur = [], None
    for w in words:
        if cur is None or w["segment"] != words[cur[1]]["segment"]:
            cur = [w["i"], w["i"]]
            out.append(cur)
        else:
            cur[1] = w["i"]
    return [tuple(x) for x in out]


def detect(words, window=WINDOW, min_run=MIN_RUN, start_slack=START_SLACK, min_share=MIN_SHARE):
    """Return the retakes: [{word_from, word_to, start, end, text, replaced_by, run, ...}], in time order."""
    segs = segments_of(words)
    dropped = set()
    found = []
    for k, (first, last) in enumerate(segs):
        if first in dropped:
            continue
        a, a_idx = _unit_tokens(words, first, last)
        if len(a) < min_run:
            continue
        horizon = words[last]["end"] + window
        # tokens of the words after this sentence, within the window, never ones already dropped
        later_first = last + 1
        later_last = later_first
        while later_last < len(words) and words[later_last]["start"] <= horizon:
            later_last += 1
        later_last -= 1
        if later_last < later_first:
            continue
        b, b_idx = [], []
        for w in words[later_first:later_last + 1]:
            if w["i"] in dropped:
                continue
            for t in T.norm_tokens(w["text"]):
                b.append(t)
                b_idx.append(w["i"])
        run, i, j = _longest_run(a, b, start_slack + 1)
        if run < min_run:
            continue
        # the later words must carry the sentence, not only its opening: compare against the stretch that follows the run
        if _lcs(a, b[j:j + 2 * len(a)]) < min_share * len(a):
            continue
        for q in range(first, last + 1):
            dropped.add(q)
        found.append({
            "word_from": first, "word_to": last, "start": words[first]["start"], "end": words[last]["end"],
            "text": " ".join(w["text"] for w in words[first:last + 1]),
            "run": run, "run_text": " ".join(a[i:i + run]),
            "replaced_by": {"word_from": b_idx[j], "word_to": b_idx[min(j + len(a) - i - 1, len(b_idx) - 1)],
                            "start": words[b_idx[j]]["start"],
                            "text": " ".join(w["text"] for w in words[b_idx[j]:b_idx[min(j + len(a) - i - 1, len(b_idx) - 1)] + 1])},
        })
    return found


def apply(words, retakes):
    """Flag the words of the earlier takes as `dropped` (the cutter and the aligner skip them)."""
    for w in words:
        w.pop("dropped", None)
    for r in retakes:
        for w in words[r["word_from"]:r["word_to"] + 1]:
            w["dropped"] = True
    return words


def format_report(retakes):
    if not retakes:
        return "retakes: none detected"
    lines = ["retakes removed (the earlier take is cut; undo by running with --no-retakes or --keep-retake <first word index>):"]
    for r in retakes:
        lines.append("  words %d-%d  %.2f-%.2fs  %r  | repeated run of %d words (%r); the later take starts at word %d, %.2fs: %r"
                     % (r["word_from"], r["word_to"], r["start"], r["end"], r["text"], r["run"], r["run_text"],
                        r["replaced_by"]["word_from"], r["replaced_by"]["start"], r["replaced_by"]["text"][:80]))
    return "\n".join(lines)

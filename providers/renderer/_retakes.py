"""Retakes by rule: the earlier take of a repeated phrase is proposed for cutting, the last take stays. Code only; no model.

`detect_retakes(words, language, cfg, silences)` reads the live words of a transcript (index, text, start, end) and returns proposals,
each `{id, kind, word_from, word_to, keep_from, seconds, confirmed, default, reason}`:

  repeat   a run of `run_min` or more content tokens that occurs again within `window_seconds`;
  restart  a shorter run (`restart_min`, or a cut-off fragment) that is begun again and carried on;
  near     two consecutive phrases that differ by a word or two (a number said again, corrected).

`default` is `cut` or `keep` and `reason` is a closed word (REASONS), decided by a fixed table, in order: far, cut_off, hesitation,
continues, abandoned, pause, complete; `redo` (a whole sentence said again in other words, right after it) rescues a take that `far`
would keep. The constants and the hesitation, filler and cue lists of a language are in the block `retakes`
of renderer-presets.json. Nothing here changes a word: `_edl.build_base` cuts what the mode and the person's choices say.
Standard library only.
"""
from __future__ import annotations

import bisect
import difflib
import unicodedata

from _align import norm_tokens

REASONS = ("redo", "far", "cut_off", "hesitation", "continues", "abandoned", "pause", "complete")
KINDS = ("repeat", "restart", "near")
_KIND_ORDER = {"restart": 0, "repeat": 1, "near": 2}
_TRIM = "\"')]»”’"
_CUT = ("-", "–", "—", "...", "…")
_FINAL = (".", "?", "!")
_COMMA = (",", ";", ":")


def end_mark(text: str) -> str:
    """`cut`, `final`, `comma` or `bare`: how the raw text of a word ends, after trailing quotes and brackets."""
    t = text.rstrip(_TRIM)
    if t.endswith(_CUT):
        return "cut"
    if t.endswith(_FINAL):
        return "final"
    if t.endswith(_COMMA):
        return "comma"
    return "bare"


def fold(token: str) -> str:
    """NFKD with the combining marks removed: two tokens a transcriber spelled with another accent are equal."""
    return "".join(c for c in unicodedata.normalize("NFKD", token) if not unicodedata.combining(c))


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def word_lists(cfg: dict, language) -> tuple:
    """(single, cues, connectors, conjunctions): `single` maps a token to `hesitation`, `filler` or `cue`; `cues` is the list of multi-token cues
    (tuples), the longest first; `connectors` is the list of connector words (tuples of folded tokens: "but", "so that") that may
    stand before the earlier take of a redo; `conjunctions` is the set of folded coordinating conjunctions ("and", "e"), which end a
    clause of a deliberate parallel structure (never a retake). The language's lists are merged with those of "*"; an unknown language uses "*" only."""
    words = cfg["words"]
    single, cues, connectors, conjunctions = {}, [], set(), set()
    for lang in ("*", language):
        block = words.get(lang) if isinstance(lang, str) else None
        if not block:
            continue
        for entry in block.get("connector", []):
            toks = tuple(fold(t) for t in norm_tokens(_nfc(entry)))
            if toks:
                connectors.add(toks)
        for entry in block.get("conjunction", []):
            toks = tuple(fold(t) for t in norm_tokens(_nfc(entry)))
            if len(toks) == 1:
                conjunctions.add(toks[0])
        for cls in ("hesitation", "filler", "cue"):
            for entry in block.get(cls, []):
                toks = tuple(norm_tokens(_nfc(entry)))
                if len(toks) == 1:
                    single.setdefault(toks[0], cls)
                elif len(toks) > 1 and cls == "cue":
                    cues.append(toks)
    cues = sorted(set(cues), key=lambda c: (-len(c), c))
    return single, cues, sorted(connectors), conjunctions


class _Pauses:
    """`pause(a, b)` between two words: the gap, or the longest silence inside [a.start, b.end] when that is longer."""

    def __init__(self, silences):
        rows = sorted((float(s[0]), float(s[1])) for s in (silences or []))
        self.starts = [r[0] for r in rows]
        self.ends = [r[1] for r in rows]
        self.longest = max((e - s for s, e in rows), default=0.0)

    def between(self, a: dict, b: dict) -> float:
        best = 0.0
        lo, hi = a["start"], b["end"]
        k = bisect.bisect_left(self.starts, lo - self.longest)
        while k < len(self.starts) and self.starts[k] < hi:
            best = max(best, min(self.ends[k], hi) - max(self.starts[k], lo))
            k += 1
        return max(b["start"] - a["end"], best, 0.0)


def detect_retakes(words: list, language, cfg: dict, silences=None) -> list:
    """The proposals (see the module's docstring) for `words`, the live words in order. `silences` is a list of (start, end) pairs or
    None. Deterministic: the same input gives the same list."""
    if not words:
        return []
    single, cues, connectors, conjunctions = word_lists(cfg, language if isinstance(language, str) else None)
    pauses = _Pauses(silences)
    n_words = len(words)
    marks = [end_mark(w["text"]) for w in words]
    flat = []                                  # (normalised token, word position, first token of its word)
    for p, w in enumerate(words):
        for k, tok in enumerate(norm_tokens(w["text"])):
            flat.append((_nfc(tok), p, k == 0))
    first_flat = {}
    for k, t in enumerate(flat):
        first_flat.setdefault(t[1], k)
    klass = [single.get(t[0], "content") for t in flat]
    for k in range(len(flat)):                 # a multi-token cue, the longest first
        for cue in cues:
            if tuple(t[0] for t in flat[k:k + len(cue)]) == cue:
                for m in range(k, k + len(cue)):
                    klass[m] = "cue"
                break
    content = [(fold(t[0]), t[1], t[2]) for t, c in zip(flat, klass) if c == "content"]
    hes_words = {t[1] for t, c in zip(flat, klass) if c in ("hesitation", "cue")}
    content_words = sorted({c[1] for c in content})
    n = len(content)
    punctuated = sum(1 for m in marks if m != "bare") >= cfg["punctuation_min_share"] * n_words

    def start(p): return words[p]["start"]

    content_set = set(content_words)

    # ---- phrases: split after a final or cut mark, around a hesitation or cue, and at a pause
    phrases, cur = [], []
    for p in range(n_words):
        if p in hes_words:
            if cur:
                phrases.append(cur)
            cur = []
            continue
        cur.append(p)
        if marks[p] in ("final", "cut") or (p + 1 < n_words and (p + 1 in hes_words or pauses.between(words[p], words[p + 1]) >= cfg["phrase_pause"])):
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)
    phrases = [ph for ph in phrases if any(p in content_set for p in ph)]
    phrase_of = {p: k for k, ph in enumerate(phrases) for p in ph}
    toks_of = {}
    for t, p in ((c[0], c[1]) for c in content):
        toks_of.setdefault(p, []).append(t)
    candidates = []

    def redo_ok(i, j, length):
        """A whole sentence said again right after itself, in other words: both takes are phrases that START with the same run, the
        earlier one is one phrase of bounded size that ends at a phrase boundary, and the opening is not a series (anaphora)."""
        first_pos, last_pos, later_pos = content[i][1], content[j - 1][1], content[j][1]
        a_ph, b_ph = phrase_of.get(first_pos), phrase_of.get(later_pos)
        # the earlier take may be cut into several phrases by pauses inside it (a word stretched over a silence, as DTW times do), but
        # never by a sentence end or a hesitation: those make it more than one take
        inside = range(first_pos, last_pos + 1)
        if a_ph is None or b_ph is None or phrase_of.get(last_pos) is None or phrase_of[last_pos] == b_ph or length < run_min:
            return False
        if any(marks[p] in ("final", "cut") for p in inside[:-1]) or any(p in hes_words for p in inside):
            return False
        starts = lambda ph: next(p for p in phrases[ph] if p in content_set)
        if starts(b_ph) != later_pos:
            return False
        if starts(a_ph) != first_pos:      # a clause: the earlier take may follow a connector word ("..., but <take>"), with no sentence end inside it
            k = first_flat[first_pos]
            if not any(k >= len(c) and tuple(fold(flat[x][0]) for x in range(k - len(c), k)) == c for c in connectors):
                return False
        if marks[last_pos] not in ("final", "cut") and pauses.between(words[last_pos], words[later_pos]) < cfg["phrase_pause"]:
            return False
        if length >= j - i or j - i - length < cfg["near_min_tokens"]:      # a short earlier phrase after the run: emphasis
            return False
        if last_pos - first_pos + 1 > cfg["redo_words_max"] or words[last_pos]["end"] - words[first_pos]["start"] > cfg["redo_seconds_max"]:
            return False
        later_tokens = sum(len(toks_of.get(p, [])) for p in phrases[b_ph])
        if later_tokens < cfg["redo_later_share"] * (j - i):
            return False
        run = tuple(c[0] for c in content[i:i + length])
        def opens(ph):
            got = tuple(t for p in phrases[ph] for t in toks_of.get(p, []))
            return got[:length] == run
        series = 1
        for step in (-1, 1):
            k = a_ph + step
            while 0 <= k < len(phrases) and opens(k):
                series += 1
                k += step
        return series < 3

    def coordination(i, j, tail):
        """The earlier take ends in a coordinating conjunction that stands right before the later take (no pause of `retake_pause`),
        with at least `coordination_between_min` content tokens between the end of the matched run and the conjunction: two clauses
        with the same opening, joined by "and". With nothing between them ("de que ele e de que ele...") it is still a restart."""
        conj = content[j - 1]
        if tail - 1 < cfg["coordination_between_min"] or conj[0] not in conjunctions or marks[conj[1]] not in ("bare", "comma"):
            return False
        return pauses.between(words[conj[1]], words[content[j][1]]) < cfg["retake_pause"]

    # ---- the token scan: repeat and restart
    window, run_min, restart_min = cfg["window_seconds"], cfg["run_min"], cfg["restart_min"]
    frag_min = cfg["fragment_min_chars"]
    shifted = []                               # (i, L, j - i) of the keep candidates: their inner starts are the same repeat
    i = 0
    while i < n:
        chosen = None
        for j in range(i + 1, n):
            if start(content[j][1]) - start(content[i][1]) > window:
                break
            if not (content[i][2] and content[j][2]):
                continue
            if any(a < i < a + length and off == j - i for a, length, off in shifted):
                continue
            length, fragment = 0, False
            while i + length < j and j + length < n and content[i + length][0] == content[j + length][0]:
                length += 1
            k = length
            if i + k == j - 1 and j + k < n and marks[content[i + k][1]] == "cut":
                a, b = content[i + k][0], content[j + k][0]
                if len(a) >= frag_min and len(b) > len(a) and b.startswith(a):
                    length, fragment = k + 1, True
            if length == 0:
                continue
            tail = j - (i + length)
            continues = j + length < n and marks[content[j + length - 1][1]] != "final"
            cut_mark = marks[content[j - 1][1]] == "cut" if tail == 0 else False
            valid = False
            if tail == 0:
                valid = (length >= run_min or (length >= restart_min and continues)
                         or (length == 1 and (fragment or cut_mark) and continues))
            elif length >= run_min and tail <= cfg["tail_propose_max"]:
                valid = True
            if valid and coordination(i, j, tail):
                continue                       # "de que ele nos ama e de que ele apenas...": a parallel structure, not a retake
            if valid:
                chosen = (j, length, tail, continues, fragment)
                break
        if chosen is None:
            i += 1
            continue
        j, length, tail, continues, fragment = chosen
        word_from, keep_pos = content[i][1], content[j][1]
        head = {content[i + m][1] for m in range(length)}
        cut_off = fragment or marks[keep_pos - 1] == "cut" or marks[content[i + length - 1][1]] == "cut"
        candidates.append(_candidate("repeat" if length >= run_min else "restart", word_from, keep_pos, head, tail, continues, cut_off))
        candidates[-1]["redo"] = tail >= 1 and redo_ok(i, j, length)
        if _decide(candidates[-1], words, marks, hes_words, content_set, punctuated, pauses, cfg)[0] == "cut":
            i = j
        else:
            shifted.append((i, length, j - i))
            i += 1

    # ---- the phrase scan: near
    for a_ph, b_ph in zip(phrases, phrases[1:]):
        if start(b_ph[0]) - words[a_ph[-1]]["end"] > cfg["near_gap_max"]:
            continue
        a = [t for p in a_ph for t in toks_of.get(p, [])]
        b = [t for p in b_ph for t in toks_of.get(p, [])]
        head_n = cfg["near_head_tokens"]
        if len(a) < cfg["near_min_tokens"] or len(b) < cfg["near_min_tokens"] or a[:head_n] != b[:head_n] or a == b:
            continue
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        if sm.ratio() < cfg["near_ratio"]:
            continue
        edits = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")
        if edits > cfg["near_edits_max"]:
            continue
        first = next(p for p in a_ph if p in content_set)
        keep_pos = next(p for p in b_ph if p in content_set)
        cut_off = marks[keep_pos - 1] == "cut" or marks[a_ph[-1]] == "cut"
        candidates.append(_candidate("near", first, keep_pos, set(a_ph), 0, False, cut_off))

    # ---- the choice among candidates: the cuts first, then the keeps, none overlapping, earlier first
    for c in candidates:
        c["default"], c["reason"] = _decide(c, words, marks, hes_words, content_set, punctuated, pauses, cfg)
    candidates.sort(key=lambda c: (c["from"], _KIND_ORDER[c["kind"]], c["to"]))
    accepted = []
    for wanted in ("cut", "keep"):
        for c in candidates:
            if len(accepted) >= cfg["proposals_max"]:
                break
            if c["default"] == wanted and all(c["to"] < a["from"] or c["from"] > a["to"] for a in accepted):
                accepted.append(c)
    accepted.sort(key=lambda c: c["from"])
    out = []
    for k, c in enumerate(accepted):
        first, last, keep = words[c["from"]], words[c["to"]], words[c["keep"]]
        out.append({"id": "retake-%d" % (k + 1), "kind": c["kind"], "word_from": first["index"], "word_to": last["index"],
                    "keep_from": keep["index"], "seconds": round(last["end"] - first["start"], 3), "confirmed": False,
                    "default": c["default"], "reason": c["reason"]})
    return out


def _candidate(kind, word_from, keep_pos, head, tail, continues, cut_off) -> dict:
    return {"kind": kind, "from": word_from, "to": keep_pos - 1, "keep": keep_pos, "head": head, "tail": tail,
            "continues": continues, "cut_off": cut_off}


def _decide(c: dict, words: list, marks: list, hes_words: set, content_set: set, punctuated: bool, pauses: _Pauses, cfg: dict) -> tuple:
    """(default, reason): the first row of the table that holds decides."""
    lo, hi = c["from"], c["to"]
    if c["tail"] > cfg["tail_cut_max"] or words[c["keep"]]["start"] - words[lo]["start"] > cfg["cut_seconds_max"]:
        return ("cut", "redo") if c.get("redo") else ("keep", "far")
    if c["cut_off"]:
        return "cut", "cut_off"
    if any(p in hes_words and p not in c["head"] for p in range(lo, hi + 1)):
        return "cut", "hesitation"
    if c["kind"] != "near" and c["tail"] == 0 and c["continues"]:
        return "cut", "continues"
    if punctuated and not any(marks[p] == "final" for p in range(lo, hi + 1)):
        last = max((p for p in range(lo, hi + 1) if p in content_set), default=None)
        if last is not None and marks[last] == "bare":
            return "cut", "abandoned"
    if pauses.between(words[hi], words[c["keep"]]) >= cfg["retake_pause"]:
        return "cut", "pause"
    return "keep", "complete"

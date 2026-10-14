#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The caption review of a recording (amendment A4 of the short-video plan): what the person sees of the transcript, and how
the words they change are re-mapped onto word indices. Pure functions: no file is read or written, no provider is called, no
model is involved. The pipeline (runtime/pipeline.py) keeps the files; the operations (runtime/ops_pipeline.py) call these.

Three documents, all under <data_dir>/media/<id>/ (never in the project, in git, in the documents mirror or in a run copy):

  transcript.json         what the transcriber wrote; never changed
  transcript.edited.json  the same words as the person left them: a copy of the transcript whose words also carry `origin`
                          ([first, last] index of the transcript.json words each one stands for), `edited` and, for a segment,
                          `source` ("transcriber" or "edited"). It is a transcript for every rule of the plan (the credential
                          scan, the consent setting, retention).
  review.json             what the person decided: the retakes they confirmed, the beats they anchored to a word range, the
                          overlays they dropped, the choice for an asset slot with no file, the face box, the cover's offset

The person changes WORDS, never times. An edit is a closed object, `edits()` below lists them; a key that names a time
(`start`, `end`, `time`...) is refused, not ignored. Times are code's:

  edit    a word's text changes, its time stays. A text with spaces is a split.
  split   one word becomes several; the word's time is shared out by their lengths and each part is flagged `estimated`.
  merge   adjacent words (of one segment) become one; it starts where the first starts and ends where the last ends.
  delete  the word is not in the captions.

Captions are written AS SPOKEN (a speaker's contractions and slang stay as said): nothing here normalises a spelling. The one change a text goes
through is the renderer's own hardening (NFC, none of the characters of the categories Cc, Cf, Zl, Zp, Cs, Co, Cn, at most
40 characters, no space inside a word).

Indices. After an edit the words are numbered again (the renderer reads a word's index as its position). So that what the
person decided survives, every decision is kept in the numbering of transcript.json (`origin`): a confirmed retake and an
anchor are origin ranges, and `span_current` finds the words of the edited transcript that stand for an origin range.

A refusal is a CaptionError with a closed `code` and the name of the field; the text that was refused is never in it.

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import copy
import unicodedata

SCHEMA_VERSION = 1
REVIEW_VERSION = 1
MAX_EDITS = 500
WORD_CHARS_MAX = 40            # providers/renderer/renderer-presets.json limits.word_chars_max, the renderer checks it again
WORDS_MAX = 4000               # limits.words_max
FRAME = (1080, 1920)           # the output frame, for the face box
REFUSED_CATEGORIES = {"Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"}
COVER_MAX_MS = 600_000
# A key of an edit that would carry a time. The operation has no field for one, so a person's request that names one is a
# mistake worth a clear refusal, not a silently ignored key.
TIME_KEYS = {"start", "end", "time", "times", "t", "at", "ts", "duration", "seconds", "second", "ms", "offset", "timestamp",
             "from_time", "to_time", "begin", "finish"}
OPS = {
    "edit": {"index", "text"},
    "delete": {"index"},
    "merge": {"from", "to", "text"},
    "split": {"index", "parts"},
    "retake": {"id", "confirmed"},
    "anchor": {"beat", "word_from", "word_to", "clear"},
    "overlay": {"beat", "dropped"},
    "slot": {"slot", "choice"},
    "face_box": {"x", "y", "w", "h", "clear"},
    "cover": {"offset_ms"},
}
WORD_OPS = ("edit", "delete", "merge", "split")
SLOT_CHOICES = ("keyword", "none")


class CaptionError(Exception):
    """A refusal with a closed `code` and the name of the field. The refused text is never in the message."""

    def __init__(self, code: str, field: str = ""):
        super().__init__(f"{code}:{field}" if field else code)
        self.code = code
        self.field = field


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# --- the documents -----------------------------------------------------------------------------------------------------


def new_review() -> dict:
    """The review state of a recording nobody has reviewed yet."""
    return {"version": REVIEW_VERSION, "revision": 0, "confirmed_retakes": [], "anchors": {}, "dropped_beats": [],
            "empty_slots": {}, "face_box": None, "cover_offset_ms": 0}


def check_review(value) -> dict:
    """The review document as stored, or a CaptionError: the shape the operations read back, closed."""
    if not isinstance(value, dict) or value.get("version") != REVIEW_VERSION or not _is_int(value.get("revision")):
        raise CaptionError("review_unreadable", "review")
    base = new_review()
    if set(value) - set(base):
        raise CaptionError("review_unreadable", "review")
    out = dict(base, **value)
    for item in out["confirmed_retakes"]:
        if not (isinstance(item, dict) and set(item) - {"seconds"} == {"id", "from", "to"} and isinstance(item["id"], str)
                and _is_int(item["from"]) and _is_int(item["to"]) and 0 <= item["from"] <= item["to"]
                and (item.get("seconds") is None or (isinstance(item["seconds"], (int, float)) and not isinstance(item["seconds"], bool)
                                                     and 0 <= item["seconds"] < 3600))):
            raise CaptionError("review_unreadable", "confirmed_retakes")
    if not isinstance(out["anchors"], dict) or not all(
            isinstance(k, str) and k.isdigit() and isinstance(v, list) and len(v) == 2 and all(_is_int(i) and i >= 0 for i in v) and v[0] <= v[1]
            for k, v in out["anchors"].items()):
        raise CaptionError("review_unreadable", "anchors")
    if not isinstance(out["dropped_beats"], list) or not all(_is_int(i) and i > 0 for i in out["dropped_beats"]):
        raise CaptionError("review_unreadable", "dropped_beats")
    if not isinstance(out["empty_slots"], dict) or not all(isinstance(k, str) and v in SLOT_CHOICES for k, v in out["empty_slots"].items()):
        raise CaptionError("review_unreadable", "empty_slots")
    if out["face_box"] is not None:
        check_face_box(out["face_box"], "face_box")
    if not _is_int(out["cover_offset_ms"]) or not 0 <= out["cover_offset_ms"] <= COVER_MAX_MS:
        raise CaptionError("review_unreadable", "cover_offset_ms")
    return out


def start_edited(transcript: dict) -> dict:
    """transcript.edited.json before the first edit: the transcript's words, each standing for itself."""
    doc = copy.deepcopy(transcript)
    for word in doc["words"]:
        word["origin"] = [word["index"], word["index"]]
        word["edited"] = False
    for seg in doc["segments"]:
        seg["source"] = "transcriber"
    doc["facts"] = dict(doc.get("facts") or {}, edited=True, revision=0)
    return doc


def check_edited(doc) -> dict:
    """The edited transcript as stored, or a CaptionError."""
    try:
        if doc.get("schema_version") != SCHEMA_VERSION or not isinstance(doc.get("words"), list) or not isinstance(doc.get("segments"), list):
            raise ValueError
        for pos, w in enumerate(doc["words"]):
            if w["index"] != pos or not isinstance(w["text"], str) or not (isinstance(w["origin"], list) and len(w["origin"]) == 2):
                raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise CaptionError("edited_unreadable", "transcript.edited") from None
    return doc


# --- text ------------------------------------------------------------------------------------------------------------


def harden_word(value, field: str, max_chars: int = WORD_CHARS_MAX) -> str:
    """One word as NFC, or a CaptionError. No space inside, none of the refused categories, not empty, not longer than
    max_chars; never cut, never respelled."""
    if not isinstance(value, str):
        raise CaptionError("not_text", field)
    value = unicodedata.normalize("NFC", value)
    for ch in value:
        if unicodedata.category(ch) in REFUSED_CATEGORIES:
            raise CaptionError("forbidden_character", field)
    value = value.strip()
    if not value:
        raise CaptionError("empty_text", field)
    if any(ch.isspace() for ch in value):
        raise CaptionError("space_in_word", field)
    if len(value) > max_chars:
        raise CaptionError("text_too_long", field)
    return value


def words_of(text, field: str, max_chars: int = WORD_CHARS_MAX) -> list:
    """The words of a text the person typed: split at whitespace, each hardened. A text with none is refused."""
    if not isinstance(text, str):
        raise CaptionError("not_text", field)
    for ch in text:   # a control character is refused whole, before str.split() would have taken it for a separator
        if unicodedata.category(ch) in REFUSED_CATEGORIES:
            raise CaptionError("forbidden_character", field)
    parts = unicodedata.normalize("NFC", text).split()
    if not parts:
        raise CaptionError("empty_text", field)
    return [harden_word(p, field, max_chars) for p in parts]


def check_face_box(box, field: str) -> dict:
    """A face box {x, y, w, h} in frame pixels: whole numbers, a positive size, inside the 1080 x 1920 frame."""
    if not isinstance(box, dict) or set(box) != {"x", "y", "w", "h"} or not all(_is_int(v) for v in box.values()):
        raise CaptionError("bad_face_box", field)
    if box["w"] <= 0 or box["h"] <= 0 or box["x"] < 0 or box["y"] < 0 or box["x"] + box["w"] > FRAME[0] or box["y"] + box["h"] > FRAME[1]:
        raise CaptionError("bad_face_box", field)
    return {k: box[k] for k in ("x", "y", "w", "h")}


# --- origin and current indices ------------------------------------------------------------------------------------------


def span_current(words: list, o_from: int, o_to: int):
    """(first, last) index of the edited words whose origin range meets [o_from, o_to], or None when every word that stood for
    that range was deleted."""
    hit = [w["index"] for w in words if w["origin"][0] <= o_to and w["origin"][1] >= o_from]
    return (min(hit), max(hit)) if hit else None


def origin_span(words: list, c_from: int, c_to: int) -> tuple:
    """(first, last) index of transcript.json that the edited words c_from..c_to stand for."""
    chosen = words[c_from:c_to + 1]
    return min(w["origin"][0] for w in chosen), max(w["origin"][1] for w in chosen)


# --- the edits -----------------------------------------------------------------------------------------------------------


def _check_keys(edit: dict, where: str) -> str:
    if not isinstance(edit, dict) or not isinstance(edit.get("op"), str):
        raise CaptionError("bad_edit", where)
    if TIME_KEYS & set(edit):
        raise CaptionError("time_not_accepted", where)
    op = edit["op"]
    if op not in OPS:
        raise CaptionError("unknown_edit", where)
    if set(edit) - OPS[op] - {"op"}:
        raise CaptionError("unknown_field", where)
    return op


def _index(value, n: int, where: str, field: str = "index") -> int:
    if not _is_int(value) or not 0 <= value < n:
        raise CaptionError("bad_index", f"{where}.{field}")
    return value


def apply_edits(edited: dict, review: dict, edits, *, revision, proposals: dict, beats, slots, limits=None) -> tuple:
    """(edited transcript, review, counts) after `edits`, or a CaptionError with nothing changed (both inputs are copied).

    edited      the current transcript.edited.json
    review      the current review.json
    edits       a list of closed objects (OPS); every index is the numbering the person last read, `revision` of it
    revision    the review's revision the person read; another is refused (`stale_revision`), because the indices moved
    proposals   {retake id: (first, last)} of transcript.json, from the proposal edit list
    beats       the beat numbers that have a preset (an anchor and a dropped overlay name one of these)
    slots       the slot ids of the script (a choice for an empty slot names one of these)
    limits      {"word_chars_max", "words_max"} (the renderer's own, read by the caller); defaults above
    counts      {"edited", "split", "merged", "deleted"}: how many words each kind of edit touched; never a text."""
    limits = dict({"word_chars_max": WORD_CHARS_MAX, "words_max": WORDS_MAX}, **(limits or {}))
    review = check_review(review)
    if revision != review["revision"]:
        raise CaptionError("stale_revision", "revision")
    if not isinstance(edits, list) or not edits or len(edits) > MAX_EDITS:
        raise CaptionError("bad_edit", "edits")
    words = edited["words"]
    n = len(words)
    chars = limits["word_chars_max"]
    actions, decisions = {}, []
    for k, edit in enumerate(edits):
        where = f"edits[{k}]"
        op = _check_keys(edit, where)
        if op in WORD_OPS:
            _plan_word_edit(op, edit, where, n, words, chars, actions)
        else:
            decisions.append((op, edit, where))
    out_review = copy.deepcopy(review)
    for op, edit, where in decisions:
        _decide(op, edit, where, words, out_review, proposals, beats, slots)
    out, counts = _rebuild(edited, actions, limits)
    out_review["revision"] += 1
    out["facts"] = dict(out.get("facts") or {}, edited=True, revision=out_review["revision"])
    return out, out_review, counts


def _claim(actions: dict, indices, where: str) -> None:
    for i in indices:
        if i in actions:
            raise CaptionError("overlapping_edits", where)


def _plan_word_edit(op: str, edit: dict, where: str, n: int, words: list, chars: int, actions: dict) -> None:
    if op == "merge":
        first, last = _index(edit.get("from"), n, where, "from"), _index(edit.get("to"), n, where, "to")
        if first >= last:
            raise CaptionError("bad_index", f"{where}.to")
        if len({words[i]["segment"] for i in range(first, last + 1)}) != 1:
            raise CaptionError("merge_across_segments", where)
        text = None if edit.get("text") is None else harden_word(edit["text"], f"{where}.text", chars)
        if text is None:   # the words joined are one word: it is held to the same bound as any word, before "done", not after
            text = harden_word("".join(words[i]["text"] for i in range(first, last + 1)), f"{where}.to", chars)
        _claim(actions, range(first, last + 1), where)
        actions[first] = ("merge", last, text)
        for i in range(first + 1, last + 1):
            actions[i] = ("absorbed", first, None)
        return
    i = _index(edit.get("index"), n, where)
    _claim(actions, [i], where)
    if op == "delete":
        actions[i] = ("delete", None, None)
    elif op == "edit":
        parts = words_of(edit.get("text"), f"{where}.text", chars)
        actions[i] = ("edit" if len(parts) == 1 else "split", parts, None)
    else:   # split
        parts = edit.get("parts")
        if not isinstance(parts, list) or len(parts) < 2 or len(parts) > 20:
            raise CaptionError("bad_edit", f"{where}.parts")
        actions[i] = ("split", [harden_word(p, f"{where}.parts", chars) for p in parts], None)


def _decide(op: str, edit: dict, where: str, words: list, review: dict, proposals: dict, beats, slots) -> None:
    if op == "retake":
        rid = edit.get("id")
        if not isinstance(rid, str) or rid not in proposals or type(edit.get("confirmed")) is not bool:
            raise CaptionError("unknown_retake", where)
        kept = [r for r in review["confirmed_retakes"] if r["id"] != rid]
        if edit["confirmed"]:
            first, last = proposals[rid][0], proposals[rid][1]
            entry = {"id": rid, "from": first, "to": last}
            if len(proposals[rid]) > 2 and proposals[rid][2] is not None:
                entry["seconds"] = proposals[rid][2]
            kept.append(entry)
        review["confirmed_retakes"] = sorted(kept, key=lambda r: (r["from"], r["id"]))
    elif op == "anchor":
        beat = edit.get("beat")
        if not _is_int(beat) or beat not in beats:
            raise CaptionError("unknown_beat", f"{where}.beat")
        if edit.get("clear") is True and set(edit) == {"op", "beat", "clear"}:
            review["anchors"].pop(str(beat), None)
            return
        if "clear" in edit:
            raise CaptionError("unknown_field", where)
        n = len(words)
        first, last = _index(edit.get("word_from"), n, where, "word_from"), _index(edit.get("word_to"), n, where, "word_to")
        if first > last:
            raise CaptionError("bad_index", f"{where}.word_to")
        review["anchors"][str(beat)] = list(origin_span(words, first, last))
    elif op == "overlay":
        beat = edit.get("beat")
        if not _is_int(beat) or beat not in beats or type(edit.get("dropped")) is not bool:
            raise CaptionError("unknown_beat", f"{where}.beat")
        dropped = set(review["dropped_beats"])
        dropped.add(beat) if edit["dropped"] else dropped.discard(beat)
        review["dropped_beats"] = sorted(dropped)
    elif op == "slot":
        slot, choice = edit.get("slot"), edit.get("choice")
        if not isinstance(slot, str) or slot not in slots:
            raise CaptionError("unknown_slot", f"{where}.slot")
        if choice is None:
            review["empty_slots"].pop(slot, None)
        elif choice in SLOT_CHOICES:
            review["empty_slots"][slot] = choice
        else:
            raise CaptionError("bad_choice", f"{where}.choice")
    elif op == "face_box":
        if edit.get("clear") is True and set(edit) == {"op", "clear"}:
            review["face_box"] = None
        elif "clear" in edit:
            raise CaptionError("unknown_field", where)
        else:
            review["face_box"] = check_face_box({k: edit.get(k) for k in ("x", "y", "w", "h")}, where)
    elif op == "cover":
        offset = edit.get("offset_ms")
        if not _is_int(offset) or not 0 <= offset <= COVER_MAX_MS:
            raise CaptionError("bad_cover", f"{where}.offset_ms")
        review["cover_offset_ms"] = offset


def _share(start: float, end: float, parts: list) -> list:
    """[(start, end)] for each part: the word's time shared out by the parts' lengths, to the millisecond, in order, the last
    ending where the word ended."""
    total = sum(len(p) for p in parts)
    out, cursor, spent = [], start, 0
    for k, part in enumerate(parts):
        spent += len(part)
        stop = end if k == len(parts) - 1 else round(start + (end - start) * spent / total, 3)
        stop = max(stop, cursor)
        out.append((round(cursor, 3), round(stop, 3)))
        cursor = stop
    return out


def _rebuild(edited: dict, actions: dict, limits: dict) -> tuple:
    old = edited["words"]
    new, counts = [], {"edited": 0, "split": 0, "merged": 0, "deleted": 0}
    i = 0
    while i < len(old):
        act = actions.get(i)
        w = old[i]
        if act is None:
            new.append(dict(w))
            i += 1
            continue
        kind, arg, text = act
        if kind == "delete":
            counts["deleted"] += 1
        elif kind == "edit":
            if arg[0] == w["text"]:   # the same text: nothing changed, so the word is not marked as edited
                new.append(dict(w))
            else:
                new.append(dict(w, text=arg[0], edited=True))
                counts["edited"] += 1
        elif kind == "split":
            for part, (s, e) in zip(arg, _share(w["start"], w["end"], arg)):
                row = {k: v for k, v in w.items() if k != "probability"}
                new.append(dict(row, text=part, start=s, end=e, estimated=True, edited=True))
            counts["split"] += 1
        elif kind == "merge":
            group = old[i:arg + 1]
            row = {k: v for k, v in w.items() if k != "probability"}
            row.update(text=text or "".join(g["text"] for g in group), start=group[0]["start"], end=group[-1]["end"], edited=True,
                       origin=[min(g["origin"][0] for g in group), max(g["origin"][1] for g in group)])
            if any(g.get("estimated") for g in group):
                row["estimated"] = True
            new.append(row)
            counts["merged"] += len(group)
            i = arg
        i += 1
    for word in new:
        if word.get("edited"):
            harden_word(word["text"], "edits", limits["word_chars_max"])
    if not new:
        raise CaptionError("no_words", "edits")
    if len(new) > limits["words_max"]:
        raise CaptionError("too_many_words", "edits")
    for pos, word in enumerate(new):
        word["index"] = pos
    segments = copy.deepcopy(edited["segments"])
    for seg in segments:
        inside = [w for w in new if w["segment"] == seg["index"]]
        emptied = not inside and seg.get("first_word") is not None
        seg["first_word"] = inside[0]["index"] if inside else None
        seg["last_word"] = inside[-1]["index"] if inside else None
        if emptied or any(w.get("edited") for w in inside):
            seg["source"] = "edited"
        if seg["source"] == "edited":
            seg["text"] = " ".join(w["text"] for w in inside)
    return dict(edited, words=new, segments=segments), counts


# --- what the person sees ----------------------------------------------------------------------------------------------------


def retake_ranges(proposal_edl: dict) -> dict:
    """{retake id: (first, last, seconds)} of the words each proposal would drop, in the numbering of transcript.json, and the time
    they take."""
    return {p["id"]: (p["word_from"], p["word_to"], p.get("seconds")) for p in proposal_edl.get("proposals") or []}


def view(edited: dict, review: dict, proposal_edl: dict, proposal_beats: dict, assets: dict) -> dict:
    """The caption review as the page reads it (`captions-read`): the transcript as caption chunks, the retakes proposed
    (struck through, to confirm or reject), the words whose timing the renderer adjusted, each beat with its matched words and
    score (below the threshold flagged), the words left out of the captions, and what the person has decided. Built from the
    proposal edit list and beats (made on transcript.json before the review) and re-mapped onto the edited words. `assets`
    maps a slot id to the file facts of an upload ({"name", "type", "sha256"}) or None.

    The words are the person's own text. The numbers are counts and indices. The write side takes no time."""
    words = edited["words"]
    norm = proposal_edl.get("normalisation") or {}
    retimed = {r["index"] for r in norm.get("retimed_words") or []}
    unplaced = {u["index"]: u for u in norm.get("unplaced_words") or []}
    dropped_segments = {d["segment"] for d in norm.get("dropped_segments") or []}
    chunk_of = {}
    for number, (a, b) in enumerate((proposal_edl.get("captions") or {}).get("chunks") or []):
        for o in range(a, b + 1):
            chunk_of[o] = number
    shown = []
    for w in words:
        first, last = w["origin"]
        reasons = []
        if any(o in unplaced for o in range(first, last + 1)):
            reasons.append("unplaced")
        if w["segment"] in dropped_segments:
            reasons.append("dropped_segment")
        row = {"index": w["index"], "text": w["text"], "start": w["start"], "end": w["end"], "segment": w["segment"],
               "estimated": bool(w.get("estimated")), "edited": bool(w.get("edited")), "origin": [first, last],
               "timing_adjusted": any(o in retimed for o in range(first, last + 1)),
               "chunk": chunk_of.get(first), "left_out": reasons[0] if reasons else None}
        shown.append(row)
    chunks, run = [], None
    for row in shown:
        if row["chunk"] is None:
            run = None
            continue
        if run is None or run["chunk"] != row["chunk"]:
            run = {"chunk": row["chunk"], "words": []}
            chunks.append(run)
        run["words"].append(row["index"])
    segments = [{"index": s["index"], "source": s.get("source", "transcriber"), "dropped": s["index"] in dropped_segments,
                 "words": [w["index"] for w in words if w["segment"] == s["index"]]} for s in edited["segments"]]
    confirmed = {r["id"] for r in review["confirmed_retakes"]}
    retakes = []
    for p in proposal_edl.get("proposals") or []:
        now = span_current(words, p["word_from"], p["word_to"])
        keep = span_current(words, p["keep_from"], p["keep_from"])
        retakes.append({"id": p["id"], "kind": p["kind"], "seconds": p["seconds"], "word_from": now and now[0], "word_to": now and now[1],
                        "keep_from": keep and keep[0], "confirmed": p["id"] in confirmed})
    threshold = proposal_beats.get("threshold")
    beats = []
    for item in proposal_beats.get("report") or []:
        if not item.get("preset"):
            continue
        beat = item["beat"]
        anchor = review["anchors"].get(str(beat))
        span_o = tuple(anchor) if anchor else (None if item.get("word_from") is None else (item["word_from"], item["word_to"]))
        now = span_current(words, *span_o) if span_o else None
        score = 1.0 if anchor else item.get("score")
        beats.append({"beat": beat, "preset": item["preset"], "score": score,
                      "matched": bool(anchor) or bool(item.get("matched")), "anchored": bool(anchor),
                      "below_threshold": (not anchor) and threshold is not None and score is not None and score < threshold,
                      "reordered": bool(item.get("reordered")) and not anchor, "fallback": item.get("fallback"),
                      "word_from": now and now[0], "word_to": now and now[1], "dropped": beat in review["dropped_beats"]})
    slot_rows = [{"slot": s["slot"], "beat": s["beat"], "param": s["param"], "type": s["type"], "description": s["description"],
                  "file": assets.get(s["slot"]), "choice": review["empty_slots"].get(s["slot"])}
                 for s in proposal_beats.get("slots") or []]
    unplaced_rows = [{"index": u["index"], "word": (span_current(words, u["index"], u["index"]) or (None,))[0], "start": u["start"],
                      "end": u["end"]} for u in unplaced.values()]
    return {"revision": review["revision"], "words": shown, "chunks": chunks, "segments": segments, "retakes": retakes,
            "beats": beats, "slots": slot_rows, "unplaced": unplaced_rows, "threshold": threshold, "face_box": review["face_box"],
            "cover_offset_ms": review["cover_offset_ms"],
            "counts": {"words": len(words), "edited": sum(1 for w in shown if w["edited"]), "estimated": sum(1 for w in shown if w["estimated"]),
                       "timing_adjusted": sum(1 for w in shown if w["timing_adjusted"]), "unplaced": len(unplaced_rows),
                       "retakes": len(retakes), "confirmed": len(confirmed), "beats": len(beats),
                       "below_threshold": sum(1 for b in beats if b["below_threshold"])}}


# --- what the later steps are given -------------------------------------------------------------------------------------------


RETAKE_GROWTH_SECONDS = 2.0     # a new proposal may take this much more time than the one the person confirmed
RETAKE_OVERLAP = 0.5            # ... and must contain the confirmed words, or cover more than this share of them


def confirmed_ids(review: dict, edited: dict, new_proposals: list) -> tuple:
    """(ids to confirm in the final base list, the confirmations that found no proposal). The base list is made again on the
    edited words, so its proposals may differ from the ones the person saw. A new proposal carries a confirmation over only when
    the transcript.json words it drops contain the confirmed range, or cover more than half of it, and it takes no more than 2 s
    longer than the confirmed one did: an edit never turns a confirmed retake into a much larger cut. A confirmation that no
    proposal carries is returned (the pipeline stops there, and the retake is shown unconfirmed when the captions open again)."""
    words = edited["words"]
    ids, met = [], set()
    for p in new_proposals:
        o_first, o_last = origin_span(words, p["word_from"], p["word_to"])
        for k, r in enumerate(review["confirmed_retakes"]):
            overlap = min(o_last, r["to"]) - max(o_first, r["from"]) + 1
            if overlap <= 0:
                continue
            contains = o_first <= r["from"] and o_last >= r["to"]
            if not (contains or overlap / (r["to"] - r["from"] + 1) > RETAKE_OVERLAP):
                continue
            was, now = r.get("seconds"), p.get("seconds")
            if was is not None and now is not None and now > was + RETAKE_GROWTH_SECONDS:
                continue
            met.add(k)
            if p["id"] not in ids:
                ids.append(p["id"])
    return ids, [r for k, r in enumerate(review["confirmed_retakes"]) if k not in met]


def drop_confirmations(review: dict, lost: list) -> dict:
    """The review without the confirmations in `lost`, one revision later: the retake shows unconfirmed when the captions open."""
    gone = {r["id"] for r in lost}
    out = copy.deepcopy(review)
    out["confirmed_retakes"] = [r for r in out["confirmed_retakes"] if r["id"] not in gone]
    out["revision"] += 1
    return out


def reconcile(edited: dict, review: dict) -> dict:
    """The review that goes with the edited transcript. The two files are written one after the other (edited first), so a crash
    can leave the transcript one revision ahead: the person's words are in it, and the decisions of that last batch are the only
    thing lost, so the review takes the transcript's revision. Any other disagreement is a CaptionError."""
    have, want = review["revision"], (edited.get("facts") or {}).get("revision", 0)
    if have == want:
        return review
    if want == have + 1:
        return dict(review, revision=want)
    raise CaptionError("review_disagrees", "review")


def anchors_current(review: dict, edited: dict, live: set) -> tuple:
    """({beat: (first, last)} in the edited numbering, lost beats). An anchor is moved to the edited words that stand for it and
    shrunk to the words that are live in the final edit list (a word a confirmed retake or the renderer left out cannot start or
    end a beat); a beat left with none is lost."""
    words = edited["words"]
    out, lost = {}, []
    for beat, (o_from, o_to) in sorted(review["anchors"].items(), key=lambda kv: int(kv[0])):
        now = span_current(words, o_from, o_to)
        inside = [i for i in range(now[0], now[1] + 1) if i in live] if now else []
        if inside:
            out[int(beat)] = (inside[0], inside[-1])
        else:
            lost.append(int(beat))
    return out, lost

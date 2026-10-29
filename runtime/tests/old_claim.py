"""The old trigger reading of the reminder engine, FROZEN as a test stand-in (S41-11 PR 2b). Not a test file.

Until S41-11 `natural.understand(line, now, "trigger")` cut the trigger words out of the reminder's text (`_trigger_span`: the head of `triggers.remind`, a scheduling verb and a reminder noun, or a
"remind me" anywhere in the line, and for the ways `bare` and `note` the head of `triggers.note`), and `natural.claim(line)` was `natural.candidate` for a site that CLAIMS the line for a closed form
(a line that repeats goes to the interpreter instead when the scope says it is on). The product keeps neither: the interpreter names the operation (L63), the reminder question engine is carried
out with `how="command"`, and `natural.candidate` is left to the question engine alone (a reply that starts a request of its own is a new line). The tests of the bridge and of the operations that
enter through a plain line, and the pre-states of the entry replay that put a question in the world by saying a line, need the old reading; `closed_heads.py` puts it back for them alone, for the
length of a test (a draft made under it has the way `trigger`). The functions are the old ones, copied byte for byte except for the names of the helpers that stayed in `natural.py`.

Every word and every name here is the test tree's own and invented.
"""
from __future__ import annotations

import datetime
import re

import standin_tree as st

natural = st.load("natural")
nt = st.load("natural_time")


def claim(line, languages=None):
    """CB-9: `candidate`, for a site that CLAIMS the line for a closed form (the bridge's reading of an update): a line that asks for an event and holds a repetition phrase is none of the
    closed forms at catalog version 2 when the interpreter is on for the sender (`repeat_goes_on`): the interpreter reads it. Every site that only RECOGNISES a request of its own (is this
    line a new request, is it private, is it a memory of the conversation, does it answer a question) reads `candidate`, which never takes the scope into account."""
    got = natural.candidate(line, languages)
    if got is not None and got["op"] == "calendar-event-create" and natural.repeat_goes_on(line):
        return None
    return got


def _trigger_span(norm: str, tables: list, how: str):
    """(start, end), in the folded line, of the trigger words to take out of the reminder's words, or None."""
    if how == "trigger":
        end = natural._head(norm, tables, "remind")
        if end is None:
            end = natural._verb_noun(norm, tables)
        return (0, end) if end is not None else natural._anywhere(norm, tables, "remind_anywhere")
    if how in ("bare", "note"):
        end = natural._head(norm, tables, "note")
        return (0, end) if end is not None else None
    return None


def understand(line, now, how="trigger", languages=None, trust=False, confirm=False):
    """The reminder `line` asks for at the clock `now` (see the module's text). `how` is "trigger", "bare", "note", "command" or "write" (package NR-5: the caller has cut the head of
    a write to the person's accounts, there is no trigger to cut, and the words that are left are the event's title). `trust` is true when the person has
    just answered a question about this line, so that a word the parse did not use is not asked about again; `confirm` makes the reading a confirmation whatever the line
    says (the answer to "which day next week?" is always shown with the day it resolved to)."""
    tables = natural._tables(languages)
    text = line if isinstance(line, str) else ""
    if nt.recurring(text, tables):
        return {"ask": natural._draft("recurring", how, text, "")}
    flagged, typos = nt.doubts(text, tables)
    for start, end, meant in sorted(typos, reverse=True):          # a day word with a typo is read as the word it is one letter from; with two such words it stays in the words
        if meant:
            text = text[:start] + meant + text[end:]
    norm, origin = nt.normalise(text)
    week = natural._week(norm, tables)
    if week:          # "next week at 10", "tuesday next week": the week is named; with no day of it the day is asked, with one it is the day of THAT week, shown and confirmed
        line2 = " ".join((text[:origin[week[0]]] + " " + text[origin[week[1] - 1] + 1:]).split())
        found2 = nt.find(line2, tables)
        if not any(h["kind"] in ("date", "slash") for h in found2["hits"]):
            norm2, origin2 = nt.normalise(line2)
            parsed = nt.parse(line2, now, tables)
            cuts = list(parsed["spans"]) if parsed else []
            trigger = _trigger_span(norm2, tables, how)
            if trigger:
                cuts.append((origin2[trigger[0]], origin2[trigger[1] - 1] + 1))
            return {"ask": natural._draft("weekday", how, line2, natural._tidy(nt.without(line2, cuts), tables))}
        inner = understand(line2, now, how, tables, trust=True)
        shape = inner["ask"] if "ask" in inner else {**inner, "readings": [inner["reading"]], "how": how, "line": line2, "doubt": False, "day": None, "need": "ready"}
        if shape["need"] in ("confirm", "kind", "text", "ready") and shape["readings"] and any(h["kind"] == "date" and h["spec"]["k"] == "wd" for h in found2["hits"]):
            reading = natural._next_week(shape["readings"][0], now) if shape["readings"][0].get("date") else shape["readings"][0]
            return natural._next(natural._draft("ready", how, line2, shape["text"], readings=[reading], doubt=True), reading)
        return inner
    found = nt.find(text, tables)
    parsed = nt.parse(text, now, tables)
    cuts = list(parsed["spans"]) if parsed else []
    if parsed and any(h.get("topic") for h in found["hits"]):          # "the meeting of friday": the weekday stays in the words, it may be what the reminder is about
        cuts = nt._spans({"origin": found["origin"], "hits": [h for h in found["hits"] if not h.get("topic")]})
    trigger = _trigger_span(norm, tables, how)
    if trigger:
        cuts.append((origin[trigger[0]], origin[trigger[1] - 1] + 1))
    words = natural._tidy(nt.without(text, cuts), tables)
    if parsed is None or "missing" in parsed:
        return {"ask": natural._draft("time", how, text, words, day=(parsed or {}).get("day"))}
    if "ask" in parsed:
        return {"ask": natural._draft("reading", how, text, words, readings=parsed["ask"])}
    reading = parsed["reading"]
    if reading.get("relative") and reading["relative"].endswith("d") and int(reading["relative"][3:-1]) <= 366 and not any(h["kind"] == "clock" for h in found["hits"]):
        return {"ask": natural._draft("time", how, text, words, day=nt._info(datetime.date.fromisoformat(reading["date"]), now))}          # "in 3 days": the day, and the hour is asked
    shipped = (trigger is not None and how in ("trigger", "note")) or how == "write"          # a write's head ("marca", "put on my calendar") was cut by the caller and is a shipped trigger
    dated = any(h["kind"] in ("date", "slash", "relative") for h in found["hits"])
    guard = nt.leftover_doubt(found, trigger, tables, unknown=how != "command" and not shipped and not dated)
    doubt = confirm or (not trust and (bool(parsed.get("vague")) or reading["assumed_year"] or flagged or guard))
    return natural._next(natural._draft("ready", how, text, words, readings=[reading], doubt=doubt), reading)


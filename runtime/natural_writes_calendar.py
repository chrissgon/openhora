#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The calendar family of the natural writes (package NR-5a), pure: a new event, a change to an event and the removal of one, read from a line by closed heads and
markers (the lists of `requests.writes.calendar` and `requests.writes.services` of the language tables). The interface is runtime/natural_writes.py's.

  event-create   the calendar intent of runtime/natural.py `candidate` (a verb with a calendar word, or "marca" with a time), read with the operation fixed. The head and
                 the account and calendar words are cut, the rest goes to the time engine (`natural.understand`, `how` "write"), whose words are the title. A range
                 ("das 13h as 15h", "from 1pm to 3pm", "13h-15h") gives the end; "dia todo" / "all day" makes an all-day event; a line that repeats ("toda segunda") is
                 refused in words (`recurring`: no recurrence in this version). Slots: title, start, end, calendar (a name as written), account (a service word)
  event-change   a change verb, an event noun and a NUMBER, then "para <time>" (or a rename: "muda o titulo do evento 2 para <title>"). Words left after the time make it no form.
                 Slots: event (an integer), start, end, title, account
  event-cancel   a cancel verb, an event noun and a NUMBER (without a number the line must be nothing more than the verb and the noun: the number is asked). Slot: event, account

Nothing here reads a project: a calendar name is compared with the project's `accounts` by runtime/ops_natural_calendar.py. Standard library only. Runs on Python 3.9:
python3 runtime/natural_writes_calendar.py --help
"""
from __future__ import annotations

import datetime
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import natural  # noqa: E402
import natural_time as nt  # noqa: E402
import natural_writes as nw  # noqa: E402

REQUIRED = {"event-create": ("title", "start"), "event-change": ("event",), "event-cancel": ("event",)}
NAME = re.compile(r"\s*([a-z0-9][a-z0-9-]{0,31})(?![a-z0-9-])")
SEPARATORS = ("-", "–", "—")      # a hyphen or dash between two hours: "13h-15h"


def _list(tables, key):
    return nw.listed(tables, "calendar", key)


def HEADS(tables):
    return _list(tables, "change_verbs") + _list(tables, "cancel_verbs") + _list(tables, "rename")


# --- the time -----------------------------------------------------------------------------------------------------------------------------------------


def _clock(hit) -> str:
    hour, minute = hit["times"][0]
    return f"{hour:02d}:{minute:02d}"


def _range(text: str, tables: list):
    """(engine_text, end "HH:MM" | None, cut ranges) of a line with two hours joined by a closed range connector; the line unchanged when it has none."""
    found = nt.find(text, tables)
    norm, hits = found["norm"], [h for h in found["hits"] if h["kind"] == "clock"]
    if len(hits) != 2 or not all(len(h["times"]) == 1 and not h.get("bare") for h in hits):
        return text, None, []
    first, second = hits
    between = norm[first["e"]:second["s"]].strip()
    joiners = nw.listed(tables, "calendar", "range_to")
    own = norm[second["s"]:second["e"]]
    ok = between in SEPARATORS or between in joiners or (between == "" and any(own.startswith(j + " ") for j in joiners))
    if not ok:
        return text, None, []
    cuts = [(first["e"], second["e"])]
    lead = re.compile(f"{nt._L}{nt._alt(nw.listed(tables, 'calendar', 'range_from'))}\\s*$").search(norm[:first["s"]]) if nw.listed(tables, "calendar", "range_from") else None
    if lead:
        cuts.append((lead.start(), first["s"]))
    origin = found["origin"]
    spans = [(origin[s], origin[e - 1] + 1) for s, e in cuts if s < e]
    return nt.without(text, spans), _clock(second), cuts


def _stamp(reading: dict, clock=None) -> str:
    return f"{reading['date']}T{clock or reading['time']}"


def from_engine(ask: dict, end_clock=None, all_day: bool = False) -> dict:
    """What the time engine's draft says, as the slots of an event: {"slots": {...}, "engine": the draft while the time is not one reading, "doubt", "recurring",
    "reading", "end_after_start"}. A draft that holds one reading (`confirm`, or `text` when only the words are missing) fills `start` (and `end` for a range: false
    `end_ok` when it is not after the start); the words (`text`) are the title when there are any."""
    need = ask["need"]
    out = {"slots": {}, "engine": None, "doubt": bool(ask.get("doubt")), "recurring": need == "recurring", "reading": None, "end_ok": True}
    if ask.get("text"):
        out["slots"]["title"] = ask["text"]
    if need == "recurring":
        return out
    if need in ("confirm", "kind", "text") and ask.get("readings"):
        reading = ask["readings"][0]
        out["reading"] = reading
        if all_day:
            out["slots"]["start"] = reading["date"]
        else:
            out["slots"]["start"] = _stamp(reading)
            if end_clock:
                if end_clock > reading["time"]:
                    out["slots"]["end"] = _stamp(reading, end_clock)
                else:
                    out["end_ok"] = False
        return out
    out["engine"] = ask
    return out


def times(text: str, tables: list, now):
    """The reading of the time phrases of `text`: {"timed": bool (any time phrase), "engine_text", "end_clock", "all_day", **from_engine} when there is a clock, else just
    {"timed", "engine_text", ...}. With `now` None only the structure is worked out (`timed`, `end_clock`, `all_day`)."""
    line = nw.Line(text)
    all_day, cuts = False, []
    spot = line.find(nw.listed(tables, "calendar", "all_day"))
    if spot:
        all_day = True
        cuts.append(spot)
    cleaned = line.without(cuts) if cuts else text
    engine_text, end_clock, _ = _range(cleaned, tables)
    timed = bool(nt.find(engine_text, tables)["hits"])
    out = {"timed": timed or all_day, "engine_text": engine_text, "end_clock": end_clock, "all_day": all_day, "slots": {}, "engine": None, "doubt": False, "recurring": False,
           "reading": None, "end_ok": True, "day_needed": False}
    if now is None:
        return out
    if all_day:
        found = nt.parse(engine_text, now, tables)
        day = None
        if found and "missing" in found and found.get("day"):
            day = found["day"]["date"]
        elif found and "when" in found:
            day = found["reading"]["date"]
        elif found and "ask" in found and len({r["date"] for r in found["ask"]}) == 1:
            day = found["ask"][0]["date"]
        if day is None:
            out["day_needed"] = True
            out["slots"]["title"] = natural._tidy(nt.without(engine_text, (found or {}).get("spans", [])), tables) if found else natural._tidy(engine_text, tables)
            return out
        words = natural._tidy(nt.without(engine_text, found["spans"]), tables) if "spans" in found else ""
        out["slots"].update({"start": day})
        if words:
            out["slots"]["title"] = words
        return out
    got = natural.understand(engine_text, now, "write")
    out.update(from_engine(got["ask"], end_clock, False))
    out["timed"] = True
    return out


# --- the heads ----------------------------------------------------------------------------------------------------------------------------------------


def _noun_at(line: "nw.Line", at: int, tables: list):
    """The end of an event noun at `at` (after the articles), or None."""
    here = nw.skip_articles(line, at, tables)
    found = line.find(_list(tables, "nouns"), here, here + 30)
    return found[1] if found and found[0] == here else None


def _number_after(line: "nw.Line", at: int):
    m = re.compile(r"\s*#?\s*([0-9]{1,4})(?![a-z0-9])").match(line.norm, at)
    if not m or int(m.group(1)) < 1 or m.group(1) != str(int(m.group(1))):
        return None, at
    return int(m.group(1)), m.end()


def _marker_at(line: "nw.Line", at: int, phrases: list):
    """The end of a marker phrase that starts at `at` (after blanks), or None."""
    here = at
    while here < len(line.norm) and line.norm[here] == " ":
        here += 1
    found = line.find(phrases, here, here + 30)
    return found[1] if found and found[0] == here else None


def _only_polite(left: str, tables: list) -> bool:
    """Whether the words left (folded) are nothing but polite words and marks."""
    polite = {w for p in nw.listed(tables, None, "polite") + [x for t in tables for x in t.get("polite", [])] for w in p.split()}
    return all(w in polite for w in re.findall(r"[a-z0-9]+", left))


def _account(line: "nw.Line", tables: list, start: int):
    found = nw.service(line, tables, start)
    return found if found else None


def _change(line: "nw.Line", tables: list, now):
    rename = line.lead(_list(tables, "rename"), tables)
    if rename is not None:
        noun_end = _noun_at(line, rename, tables)
        if noun_end is None:
            return None
        number, pos = _number_after(line, noun_end)
        marker = _marker_at(line, pos, _list(tables, "rename_to")) if number else None
        title = line.span(marker, len(line.norm)).strip() if marker else ""
        if not title or len(title) > nw.SPAN_MAX["title"]:
            return None
        return {"op": "event-change", "slots": {"event": number, "title": title}, "spans": {"title": title}, "ranges": {"title": (marker, len(line.norm))}, "need": [],
                "engine": None, "doubt": False}
    verb = line.lead(_list(tables, "change_verbs"), tables)
    if verb is None:
        return None
    noun_end = _noun_at(line, verb, tables)
    if noun_end is None:
        return None
    number, pos = _number_after(line, noun_end)
    marker = _marker_at(line, pos, _list(tables, "to_time")) if number else None
    if marker is None:
        return None
    service = _account(line, tables, marker)
    cleaned = line.without([(0, marker)] + ([(service[1], service[2])] if service else []))
    got = times(cleaned, tables, now)
    if not got["timed"]:
        return None
    leftover = natural._tidy(nt.without(got["engine_text"], nt._spans(nt.find(got["engine_text"], tables))), tables)
    if leftover and not _only_polite(nw.Line(leftover).norm, tables):
        return None
    slots = {"event": number}
    slots.update({k: v for k, v in got["slots"].items() if k in ("start", "end")})
    if service:
        slots["account"] = service[0]
    return {"op": "event-change", "slots": slots, "spans": {}, "ranges": {}, "need": [] if "start" in slots else ["time"], "engine": got["engine"],
            "doubt": got["doubt"], "recurring": got["recurring"], "reading": got["reading"], "end_ok": got["end_ok"], "end_clock": got["end_clock"],
            "day_needed": got["day_needed"], "all_day": got["all_day"]}


def _cancel(line: "nw.Line", tables: list):
    verb = line.lead(_list(tables, "cancel_verbs"), tables)
    if verb is None:
        return None
    noun_end = _noun_at(line, verb, tables)
    if noun_end is None:
        return None
    number, pos = _number_after(line, noun_end)
    left_from = pos if number else noun_end
    service = _account(line, tables, left_from)
    left = line.norm[left_from:]
    if service:
        left = line.norm[left_from:service[1]] + " " + line.norm[service[2]:]
    if not _only_polite(left, tables):
        return None
    slots = {}
    if number:
        slots["event"] = number
    if service:
        slots["account"] = service[0]
    return {"op": "event-cancel", "slots": slots, "spans": {}, "ranges": {}, "need": [] if number else ["event"], "engine": None, "doubt": False}


def _calendar_name(line: "nw.Line", tables: list, start: int):
    """(name as written folded, (s, e) to cut) of "na agenda <name>" / "on my <name> calendar" after `start`, or None. Each language table is read with its own markers (the
    word that follows the name is part of the marker of its language). A service word is not a name."""
    services = {w for t in tables for names in nw.writes_of(t).get("services", {}).values() for p in names for w in p.split()}
    for table in tables:
        body = nw.writes_of(table).get("calendar", {})
        after = body.get("calendar_after", [])
        for s, e in line.find_all(body.get("in_calendar", []), start):
            pos = nw.skip_articles(line, e, tables)
            m = NAME.match(line.norm, pos)
            if not m or m.group(1) in services:
                continue
            end = m.end()
            if after:
                tail = _marker_at(line, end, after)
                if tail is None:
                    continue
                end = tail
            return m.group(1), (s, end)
    return None


def _create(line: "nw.Line", tables: list, now):
    head = 0
    for key in ("calendar", "calendar_verb", "calendar_loose", "calendar_noun"):
        found = natural._head(line.norm, tables, key)
        if found is not None and found > head:
            head = found
    if head == 0 and not nt.find(line.text, tables)["hits"]:          # no shipped head and no time in the line: nothing here says it is an event
        return None
    cuts = [(0, head)] if head else []
    slots = {}
    service = _account(line, tables, head)
    if service:
        slots["account"] = service[0]
        cuts.append((service[1], service[2]))
    named = _calendar_name(line, tables, head)
    if named:
        slots["calendar"] = named[0]
        cuts.append(named[1])
    rest = line.without(cuts)
    got = times(rest, tables, now)
    out = {"op": "event-create", "slots": dict(slots), "spans": {}, "ranges": {}, "need": [], "engine": got["engine"], "doubt": got["doubt"], "recurring": got["recurring"],
           "reading": got["reading"], "end_ok": got["end_ok"], "end_clock": got["end_clock"], "day_needed": got["day_needed"], "all_day": got["all_day"]}
    if now is None:
        return out
    out["slots"].update(got["slots"])
    if "title" in out["slots"]:
        out["spans"]["title"] = out["slots"]["title"]
    out["need"] = [k for k in REQUIRED["event-create"] if k not in out["slots"]]
    return out


def read(line, tables, now=None, op=None):
    """The reading of a calendar line (see runtime/natural_writes.py). Without `op` only a change or a removal is read; `op` "event-create" reads the line as a new event
    (the calendar intent of runtime/natural.py decided that, or a question answered "event")."""
    text = line if isinstance(line, str) else ""
    shaped = nw.Line(text)
    if op == "event-create":
        return _create(shaped, tables, now)
    got = None
    if op in (None, "event-change"):
        got = _change(shaped, tables, now)
    if got is None and op in (None, "event-cancel"):
        got = _cancel(shaped, tables)
    return got


NEEDS = ("day", "end")


def answer(need, line, slots, tables, now, options=None):
    """The answer to a question only this family asks: the day of an all-day event, or the end of a range that did not end after its start."""
    if now is None:
        return None
    if need == "day":
        found = nt.parse(line, now, tables)
        if found and "missing" in found and found.get("day"):
            return {"slots": {"start": found["day"]["date"]}}
        return None
    if need == "end":
        parsed = natural._time_only(line, now, tables)
        start = slots.get("start") or ""
        if parsed is None or "when" not in parsed or "T" not in start:
            return None
        clock = parsed["reading"]["time"]
        if clock <= start[11:16]:
            return None
        return {"slots": {"end": f"{start[:10]}T{clock}"}}
    return None


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

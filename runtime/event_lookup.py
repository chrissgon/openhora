#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""An event of the person's own calendar named by its words (slice S6): "remove the haircut for tomorrow", "move the dentist to 3 pm".

The interpreter (runtime/ops_interpret.py) decides that a line asks to change or to cancel an event; the numbered form ("cancela o evento 2") needs the number of the event in the
newest snapshot of a calendar source (runtime/ops_items.py). This file finds that number from the words of the line, by code only, and then opens the card through the existing
family path (`ops_natural_writes.open_line` with a seed of the source and the number: the same card the numbered line opens, approved by its hash). Nothing the model wrote is read
here but the operation and the two spans the check already verified against the line; the event is found from the PERSON'S OWN line.

  open_event(project, ctx, decision, said, sender, extras, writes, now)   the reply: a card notice, a numbered list of the events that fit, or one plain sentence

How the calendar is read (the reading the numbered form reads, with its rights): the sender must pass `item_refs.may_read` (the group `ask-mail`; the same sentence as the family
when not); the calendar sources are the registered ones (`ops_natural_calendar.calendar_sources`); for each, `item_refs.read_index` checks the newest snapshot (younger than 26
hours, files hashed against the store's record, index against its digest) and the text is read as `ops_items._event_lines` reads it, only after its hash was checked, now with the
day headings (`## 2026-10-22 (Thursday)`) the text prints above the events. The event's title is the second field of its line (the first is the time). Nothing is called, nothing is
written and no model is used.

Which events fit. An event is a candidate when it is not cancelled and falls in the window: from today to 30 days ahead, or, when the line names a day, that day alone. A day is
named by a date word code reads (today, tomorrow, "dia 22", 22/10, a weekday: any date of that weekday in the window); a time of day alone names none, so a title that holds a number is
never mistaken for one; a date word code cannot read is a question, not a guess. A candidate fits when its title, folded (case and accents) and cut into words, occurs as whole words
in the line (for a change, the line without the span that holds the new time). A title that is part of a longer title that also fits is dropped. Exactly one fits: the card opens.
Several: a short numbered list and the question which. None: the calendar sources are read again once (`refresh`: only a sender who may read a snapshot gets here, no new
group; a snapshot older than its limit counts as a miss too; a failure is dropped), the search is made again, and still none is one plain sentence; never a second refresh for a line. The numbers listed are the snapshot's own, so "cancela o evento 7" is then the numbered form.

Privacy (limit L63): the line, the titles and the lines of the snapshot are never logged, printed or kept here; the reply holds titles of the person's own calendar, so the
conversation stores a neutral word for it (`extras["stored"]`). Standard library only. Runs on Python 3.9: python3 runtime/event_lookup.py --help
"""
from __future__ import annotations

import datetime
import hashlib
import importlib
import re
import sys

import item_refs
import natural
import natural_time as nt
import natural_writes as nw
import phrases
import snapshot_text
import sources

CHANNEL = "messaging"
OPS = ("event-change", "event-cancel")
WINDOW_DAYS = 30
LIST_MAX = 8                    # events listed when several fit
TITLE_MIN = 3                   # letters a title needs before its words can name an event
HEADING = re.compile(r"## ([0-9]{4}-[0-9]{2}-[0-9]{2}) \([A-Za-z]+\)")
SLASH = re.compile(r"(?<![0-9/])([0-9]{1,2})/([0-9]{1,2})(?:/([0-9]{2,4}))?(?![0-9/])")
EVENT_LINE = re.compile(r"([0-9]{1,4})\. (.+)")
DAY_HITS = ("date", "slash")    # the hits of the time engine that name a day (a clock alone names none)
ENGLISH_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")      # the shape phrases.localize_dates turns into the language's word on a phone


def _text(ctx: dict, key: str, **fields) -> str:
    return phrases.text(key, ctx["cfg"], **fields)


def _words(text) -> list:
    return natural.normal(text).split()


def _contains(words: list, piece: list) -> bool:
    return bool(piece) and any(words[i:i + len(piece)] == piece for i in range(len(words) - len(piece) + 1))


# --- the calendar --------------------------------------------------------------------------------------------------------------------------------


def _rows(ctx: dict, source_id: str, version) -> list:
    """[(n, day, [fields of the line])] of the version the index was read from: the text is read only when it is still the newest version and its hash is the store's record
    (as ops_items._event_lines does), so the number and the line come from one snapshot. Else nothing."""
    latest = sources._stored(ctx, "source_latest", source_id)
    if latest is None or latest["version"] != version:
        return []
    with sources.Folder(ctx["cfg"], None) as folder:
        raw = folder.read([source_id, str(version), latest["converted_name"]], sources.CONVERTED_CAP)
    if hashlib.sha256(raw).hexdigest() != latest["converted_sha256"]:
        return []
    day, out = None, []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        heading = HEADING.fullmatch(line.strip())
        if heading:
            try:
                day = datetime.date.fromisoformat(heading.group(1))
            except ValueError:
                day = None
            continue
        found = EVENT_LINE.fullmatch(line.strip())
        if found and day is not None:
            fields = snapshot_text.clean_text(found.group(2)).split(" · ")
            if len(fields) >= 2:
                out.append((int(found.group(1)), day, fields))
    return out


def events(ctx: dict, sender) -> tuple:
    """(events, problem): the events of every registered calendar source whose newest snapshot can be read, as {"source", "n", "day", "time", "title"}; `problem` says why there is
    none: "not-readable" (the sender may not read a snapshot), "no-source", "stale" (every snapshot was refused)."""
    if not item_refs.may_read(ctx, CHANNEL, sender):
        return [], "not-readable"
    listed = importlib.import_module("ops_natural_calendar").calendar_sources(ctx)
    if not listed:
        return [], "no-source"
    clock = importlib.import_module("ops_items").SNAPSHOT_CLOCK
    out, refused = [], 0
    for source in listed:
        try:
            snapshot = item_refs.read_index(ctx, source["id"], channel=CHANNEL, sender=sender, kinds=("calendar",), clock=clock)
        except item_refs.ItemRefError:
            refused += 1
            continue
        known = {e["n"] for e in snapshot["entries"]}
        for n, day, fields in _rows(ctx, source["id"], snapshot["version"]):
            if n in known and "cancelled" not in fields[2:]:
                out.append({"source": source["id"], "n": n, "day": day, "time": fields[0], "title": fields[1]})
    return (out, None) if refused < len(listed) else ([], "stale")


def refresh(project: str, ctx: dict) -> None:
    """Read each registered calendar source again, once: the provider read the snapshots come from (`ops_sources.source_refresh`, which `snapshot_refresh` in
    runtime/sources_mail.py does), a new version only when the listing changed. The caller has passed `item_refs.may_read`, the right to read these snapshots; the
    read is of the person's own calendar and writes nothing to it. A failure is dropped: nothing of it is kept or said."""
    refresh_one = importlib.import_module("ops_sources").source_refresh
    for source in importlib.import_module("ops_natural_calendar").calendar_sources(ctx):
        try:
            refresh_one(project, source["id"])
        except Exception:      # noqa: BLE001 - the fault can hold a provider's words; the reply is the not-found sentence
            continue


# --- the line ------------------------------------------------------------------------------------------------------------------------------------


def _slash_day(text: str, today: datetime.date):
    """The date of a day/month[/year] written with slashes (the order of the engine, which reads none without a cue word), or None when none is written; ValueError when it
    does not exist. With no year it is the next such day from today."""
    found = SLASH.search(text)
    if not found:
        return None
    day, month, year = int(found.group(1)), int(found.group(2)), found.group(3)
    if year is not None and len(year) == 3:
        raise ValueError(year)
    if year is not None:
        return datetime.date(int(year) + (2000 if len(year) == 2 else 0), month, day)
    got = datetime.date(today.year, month, day)
    return got if got >= today else datetime.date(today.year + 1, month, day)


def _day_named(text: str, now):
    """("none", None), ("day", a date), ("weekday", 0-6) or ("unread", None): the day the words name, as the time engine reads them (or a date with slashes). A clock alone
    names none. A date word the engine doubts, or one it finds and cannot turn into a day, is "unread": a question, never a guess."""
    if nt.doubt(text):
        return "unread", None
    found = nt.find(text)
    named = [h for h in found["hits"] if h["kind"] in DAY_HITS]
    if not named:
        try:
            got = _slash_day(text, now.date())
        except ValueError:
            return "unread", None
        return ("day", got) if got else ("none", None)
    got = nt.parse(text, now)
    if got is not None:
        shown = got.get("day") or got.get("reading")
        if shown and shown.get("date"):
            try:
                return "day", datetime.date.fromisoformat(shown["date"])
            except ValueError:
                pass
    if len(named) == 1 and named[0]["spec"].get("k") == "wd":
        return "weekday", named[0]["spec"]["i"]
    return "unread", None


def _without(said: str, span) -> str:
    return said.replace(span, " ", 1) if span and span in said else said


def candidates(rows: list, said: str, kind: str, value, today: datetime.date) -> list:
    """The events of `rows` the line names: in the window or on the named day, and whose title is whole words of the line (a title inside a longer fitting title is dropped)."""
    line = _words(said)
    fits = []
    for row in rows:
        words = _words(row["title"])
        if sum(len(w) for w in words) < TITLE_MIN or not _contains(line, words):
            continue
        if kind == "day":
            ok = row["day"] == value
        else:
            ok = today <= row["day"] <= today + datetime.timedelta(days=WINDOW_DAYS) and (kind != "weekday" or row["day"].weekday() == value)
        if ok:
            fits.append((row, words))
    return [row for row, words in fits if not any(other != words and _contains(other, words) for _, other in fits)]


# --- the reply -----------------------------------------------------------------------------------------------------------------------------------


def _shown(row: dict, with_source: bool) -> str:
    day = row["day"]
    weekday = ENGLISH_WEEKDAY[day.weekday()]
    where = f" ({row['source']})" if with_source else ""
    return f"{row['n']}. {weekday} {day.strftime('%d/%m/%Y')} {row['time']} · {row['title']}{where}"


def _list(ctx: dict, op: str, found: list) -> str:
    many = len({r["source"] for r in found}) > 1
    lines = [_shown(r, many) for r in found[:LIST_MAX]]
    if len(found) > LIST_MAX:
        lines.append(_text(ctx, "EV_MORE", k=len(found) - LIST_MAX))
    key = "EV_MANY_CANCEL" if op == "event-cancel" else "EV_MANY_CHANGE"
    return _text(ctx, key) + "\n" + "\n".join(lines) + "\n" + _text(ctx, key + "_HOW", n=found[0]["n"])


PROBLEM = {"not-readable": "NW_REF_NOT_READABLE", "no-source": "NW_NO_CALENDAR_SOURCE"}


def open_event(project: str, ctx: dict, decision: dict, said: str, sender, extras: dict, writes, now):
    """The reply for a decision to change or cancel an event (module text). `writes` is the module ops_natural_writes, which opens the card."""
    op, time_ = decision["op"], decision.get("time")
    reading = nw.read(said, now, op=op)
    if reading is None or (not reading.get("say") and "event" in reading["slots"]):
        opened = writes.open_line(project, ctx, said, CHANNEL, sender, extras, hint=op)          # the call as before: the numbered form, or nothing the family reads
        if opened is not None:
            return opened
    extras["stored"] = _text(ctx, "NW_PRIVATE_REPLY")
    spans = decision.get("spans") or {}
    text = _without(said, spans.get("time") if op == "event-change" else None)
    kind, value = _day_named(text, now)
    if kind == "unread":
        return _text(ctx, "EV_ASK_DAY")
    rows, problem = events(ctx, sender)
    found = [] if problem else candidates(rows, text, kind, value, now.date())
    if problem in PROBLEM:
        return _text(ctx, PROBLEM[problem])          # the sender may not read a snapshot, or there is no calendar source: nothing is refreshed
    if not found:          # a miss (nothing fits, or every snapshot is older than its limit): the calendar is read again ONCE for this line, then searched again
        refresh(project, ctx)
        rows, problem = events(ctx, sender)
        found = [] if problem else candidates(rows, text, kind, value, now.date())
    if not found:
        return _text(ctx, "EV_NONE_DAY" if kind == "day" else "EV_NONE", days=WINDOW_DAYS)
    if len(found) > 1:
        return _list(ctx, op, found)
    slots = {"event": found[0]["n"], "source": found[0]["source"]}
    if op == "event-change":
        title = spans.get("title")
        if time_:
            slots["start"] = time_["local"]
        if title and _words(title) != _words(found[0]["title"]):
            slots["title"] = title
        if "start" not in slots and "title" not in slots:
            return _text(ctx, "EV_CHANGE_WHAT")
    return writes.open_line(project, ctx, said, CHANNEL, sender, extras, seed={"op": op, "slots": slots})


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

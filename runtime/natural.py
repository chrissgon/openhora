#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Natural requests, tier 1 (package NR-1): a line a person writes in their own words, matched by code to an operation the platform already has, with no model.

Pure: the clock is passed in, nothing is stored, logged or sent. The words are not here: they are the language tables (`runtime/natural_lang_<tag>.py`, read as
data by runtime/natural_time.py), and the table of EVERY language is tried on EVERY line. This module holds the rows of the operations a line may name today and
the rules that turn a line into a call. The rule that governs it: what is ambiguous, or not fully understood, is asked back and never guessed. When a full
reading is understood and only something about it is uncertain, the reading is SHOWN and confirmed ("yes" makes it, a time or a day replaces only the part it
names); an open question is asked only when nothing was understood.

NR-1 builds the rows of the reminders (`remind`, `reminders`, `reminder-forget`, `reminder-restore`) and one more, the calendar event
(`calendar-event-create`, class E, planned: the reply is "not built yet", never a reminder in its place). The other operations of the platform, the dispatcher that
executes them by class and the router's `operation` outcome are package NR-2; `NATURAL` is the closed list of the rows, and a line that matches none of them goes
on to the router as before.

  candidate(line)                    what the line is, with no clock: {"op", "how", ...} | None. For `remind`, `how` is "trigger" (a remind word in the line),
                                     "bare" (a note word with a time, or a short line that holds a clock and nothing that asks for work: reminder or event is
                                     asked), "note" (a note word and no time: a reminder is offered), or "command" (the words after `/remind`, which the
                                     caller passes in itself); `calendar-event-create` has "trigger" (a verb with a calendar word, or "marca" with a time) or
                                     "ask" (a scheduling verb with a time and no calendar word: event or something else is asked); `reminder-forget` has "id"
                                     (only an explicit one: "#9", "reminder 9"), "words" (what the person said of it, matched by whole words) or "many";
                                     `reminder-restore` is "undo"
  understand(line, now, how)         the reminder the line asks for, with the clock: {"when", "text", "reading"} when it is complete, or {"ask": {...}} with what
                                     is missing or uncertain (`need`: time | reading | text | kind | confirm | recurring) and the draft the caller keeps to finish it
  complete(draft, said, now)         the next line of the same chat finishing a draft: the same shapes, {"event": True} when the person chose the calendar,
                                     {"cancel": True} when they gave it up, or None when the line is not an answer (the draft is dropped and the line is handled
                                     as a new one)
  answer_kind(said)                  "event" | "notice" | "other" | None: the answer to "an event in the calendar, or something else?"
  describe(info, cfg, zone)          a moment as a person reads it, in the project's language: "tomorrow, Mon 19/10, at 13:00 (BRT)"; the year is shown when it
                                     is not this one
  describe_day(info, cfg)            a day with no hour: "tomorrow, Mon 19/10"
  info_of(date, time, today)         the facts `describe` reads, of a moment written "YYYY-MM-DD" and "HH:MM"

The text of a reminder is a span of the person's own line (the line minus the trigger word, the time phrases and the connectives at its edges); the caller cleans
it and scans it for credentials (`reminders.clean_text`, `workcopy.credential_findings`). A time is always `natural_time.parse` of the person's line, so
`reminders.resolve` keeps every check it has. Nothing here guesses: a line with a trigger and no time is asked back, an hour that can be read two ways is
asked back, a line that repeats is said to be a routine's, and a line no table recognises is not matched.

Standard library only. Runs on Python 3.9: python3 runtime/natural.py --help
"""
from __future__ import annotations

import datetime
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import natural_time as nt  # noqa: E402  (the same folder: the time words and the engine)
import phrases  # noqa: E402  (the same folder: the sentences, in the project's language)

# The rows of the operations a line may name (package NR-2 adds the rest). `class`: N is a notice the person made, R a read, E an effect on the person's accounts.
NATURAL = (
    {"op": "remind", "class": "N", "trigger": "remind"},
    {"op": "reminders", "class": "R", "trigger": "reminders"},
    {"op": "reminder-forget", "class": "N", "trigger": "forget"},
    {"op": "reminder-restore", "class": "N", "trigger": "undo"},
    {"op": "calendar-event-create", "class": "E", "trigger": "calendar", "planned": True},
)
LIST_WORDS_MAX = 5          # "what reminders do I have": a list request is short; a longer line that starts with the word asks for something else
UNDO_WORDS_MAX = 2          # "undo", "undo that": a request to bring a reminder back is nearly the whole line
FORGET_WORDS_MAX = 5        # "cancel the reminder about the florist": what the person says of the reminder is short
BARE_WORDS_MAX = 6          # a line with no trigger is asked about only when it is this short, once the time is taken out
TEXT_MAX_WORDS = 12         # the answer to "what should I remind you of?" is short; a longer line is a new line
PUNCT = " \t,;:-–—."


def _tables(languages):
    return languages if languages is not None else nt.languages()


def fold(text: str) -> str:
    """A word as the tables write it: lower case, no accent, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", nt.normalise(text)[0])


def _head(norm: str, tables: list, key: str):
    """The end, in the folded line, of the longest phrase of `triggers[key]` that the line starts with (after blanks, marks and a polite word), or None."""
    best = None
    for table in tables:
        alt = nt._alt(table["triggers"][key])
        if not alt:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        m = re.match(f"[^a-z0-9]*{lead}{alt}(?![a-z0-9])", norm)
        if m and (best is None or m.end() > best):
            best = m.end()
    return best


def _anywhere(norm: str, tables: list, key: str):
    """(start, end), in the folded line, of the first phrase of `triggers[key]` anywhere in it, or None."""
    best = None
    for table in tables:
        alt = nt._alt(table["triggers"][key])
        m = re.search(f"{nt._L}{alt}{nt._R}", norm) if alt else None
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.end())
    return best


def _words(text: str) -> list:
    return re.findall(r"[a-z0-9]+", text)


def _stop(tables: list) -> set:
    """The words that join a reminder's name to the sentence ("of", "da", "the", "please"): they are not part of what the person says of it."""
    return {w for t in tables for w in t["edge_words"] + t["connectors"] + t["forget"]["fillers"] + [x for p in t["polite"] for x in p.split()]}


def _forget(norm: str, tables: list):
    """The facts of a line that asks to forget a reminder, or None. An EXPLICIT number names it ("reminder 9", "reminder #9", "number 9": the number is the whole
    object); several numbers ask which; anything else the line says after "of"/"about" is words to look for among the person's own reminders (whole words,
    numbers too: "about the 9 o'clock one" is words, never the id 9). A word right after the noun with no connective ("reminder emails from inbox") is not about a
    reminder of the person's."""
    for table in tables:
        forget = table["forget"]
        verbs, nouns, fillers = nt._alt(forget["verbs"]), nt._alt(forget["nouns"]), nt._alt(forget["fillers"])
        if not verbs or not nouns:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        fill = f"(?:{fillers}\\s+)*" if fillers else ""
        m = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+{fill}{nouns}(?![a-z0-9])", norm)
        if not m:
            continue
        rest = norm[m.end():]
        tail = f"(?:\\s+{polite})*" if polite else ""
        one = re.fullmatch(f"\\s*(?:{fillers}\\s+)*#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", rest) if fillers else re.fullmatch(f"\\s*#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", rest)
        if one and int(one.group(1)) >= 1:
            return {"id": int(one.group(1))}
        tokens = _words(rest)
        if len(tokens) >= 2 and all(t.isdigit() for t in tokens) and len(set(tokens)) > 1:
            return {"id": None, "many": True}
        stop = _stop(tables)
        said = [t for t in tokens if t not in stop]
        if not said:
            return {"id": None}
        if len(tokens) > FORGET_WORDS_MAX or tokens[0] not in stop:
            return None
        return {"id": None, "words": said}
    return None


def candidate(line, languages=None):
    """What the line is, with no clock (see the module's text), or None. Pure, and never wider than `understand`: the bridge sends a line here to one place."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if not text.strip() or text.lstrip().startswith("/"):
        return None
    norm, origin = nt.normalise(text)
    tokens = _words(norm)
    problem = {w for t in tables for w in t["problem_words"]} & set(tokens)
    undo = _head(norm, tables, "undo")
    if undo is not None and len(_words(norm[undo:])) <= UNDO_WORDS_MAX and "?" not in text:
        return {"op": "reminder-restore", "how": "trigger"}
    forget = _forget(norm, tables)
    if forget:
        return {"op": "reminder-forget", "how": "trigger", **forget}
    listed = _head(norm, tables, "reminders")
    if listed is not None and len(_words(norm[listed:])) <= LIST_WORDS_MAX and not problem:
        return {"op": "reminders", "how": "trigger"}
    plain = _head(norm, tables, "reminders_bare")
    if plain is not None and not _words(norm[plain:]) and not problem:
        return {"op": "reminders", "how": "trigger"}
    if _head(norm, tables, "calendar") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    noun_head = _head(norm, tables, "remind")
    if noun_head is not None:
        verbal = any(re.match(f"[^a-z0-9]*{nt._alt(t['triggers']['remind_anywhere'])}(?![a-z0-9])", norm) for t in tables if t["triggers"]["remind_anywhere"])
        if not (problem and not verbal):          # "reminder 3 did not arrive" is a report, not a request
            return {"op": "remind", "how": "trigger"}
        return None
    hits = nt.find(text, tables)["hits"]
    if hits and _anywhere(norm, tables, "remind_anywhere"):
        return {"op": "remind", "how": "trigger"}
    if hits and _head(norm, tables, "calendar_verb") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    if hits and _head(norm, tables, "calendar_loose") is not None:
        return {"op": "calendar-event-create", "how": "ask"}
    noun = _head(norm, tables, "calendar_noun")
    if noun is not None:                          # a bare calendar noun is a read ("calendar for tomorrow?"); only a request to put something on it, with a time, is asked about
        after = _words(norm[noun:])[:1]
        reads = {w for t in tables for w in t["calendar_noun_reads"]}
        if any(h["kind"] in ("clock", "relative") for h in hits) and "?" not in text and not (after and after[0] in reads):
            return {"op": "calendar-event-create", "how": "ask"}
        return None
    if _head(norm, tables, "note") is not None:
        return {"op": "remind", "how": "bare" if hits else "note"}
    if not any(h["kind"] in ("clock", "relative") for h in hits) or "?" in text or nt.recurring(text, tables):
        return None
    first = re.match(r"[^a-z0-9]*([a-z0-9]+)", norm)
    starters = {w for table in tables for w in table["work_starters"]}
    if first and first.group(1) in starters:
        return None
    rest = nt.without(text, nt._spans({"origin": origin, "hits": hits}))
    if not rest or len(rest.split()) > BARE_WORDS_MAX:
        return None
    return {"op": "remind", "how": "bare"}


def _tidy(text: str, tables: list) -> str:
    """The words left of a line once the trigger and the time phrases are out: no mark and no connective ("to", "de", "a") at the ends. Numbers are never dropped."""
    edge = {w for table in tables for w in table["edge_words"] + table["connectors"]}
    out = "".join(c for c in text if unicodedata.category(c) != "Cf").strip(PUNCT)
    for _ in range(3):
        parts = out.split(None, 1)
        if parts and fold(parts[0]) in edge:
            out = (parts[1] if len(parts) > 1 else "").strip(PUNCT)
        else:
            break
    for _ in range(2):
        parts = out.rsplit(None, 1)
        if len(parts) > 1 and fold(parts[1]) in edge:
            out = parts[0].strip(PUNCT)
        else:
            break
    return out


def _trigger_span(norm: str, tables: list, how: str):
    """(start, end), in the folded line, of the trigger words to take out of the reminder's words, or None."""
    if how == "trigger":
        end = _head(norm, tables, "remind")
        return (0, end) if end is not None else _anywhere(norm, tables, "remind_anywhere")
    if how in ("bare", "note"):
        end = _head(norm, tables, "note")
        return (0, end) if end is not None else None
    return None


def _draft(need, how, line, text, readings=None, day=None, doubt=False):
    return {"need": need, "how": how, "line": line, "text": text, "readings": readings or [], "day": day, "doubt": doubt}


def understand(line, now, how="trigger", languages=None, trust=False):
    """The reminder `line` asks for at the clock `now` (see the module's text). `how` is "trigger", "bare", "note" or "command". `trust` is true when the person has
    just answered a question about this line, so that a word the parse did not use is not asked about again."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if nt.recurring(text, tables):
        return {"ask": _draft("recurring", how, text, "")}
    flagged, typos = nt.doubts(text, tables)
    for start, end, meant in sorted(typos, reverse=True):          # a day word with a typo is read as the word it is one letter from; with two such words it is only dropped
        text = text[:start] + meant + text[end:]
    norm, origin = nt.normalise(text)
    parsed = nt.parse(text, now, tables)
    cuts = list(parsed["spans"]) if parsed else []
    trigger = _trigger_span(norm, tables, how)
    if trigger:
        cuts.append((origin[trigger[0]], origin[trigger[1] - 1] + 1))
    words = _tidy(nt.without(text, cuts), tables)
    if parsed is None or "missing" in parsed:
        return {"ask": _draft("time", how, text, words, day=(parsed or {}).get("day"))}
    if "ask" in parsed:
        return {"ask": _draft("reading", how, text, words, readings=parsed["ask"])}
    reading = parsed["reading"]
    doubt = not trust and (bool(parsed.get("vague")) or reading["assumed_year"] or flagged)
    return _next(_draft("ready", how, text, words, readings=[reading], doubt=doubt), reading)


def _next(draft: dict, reading: dict):
    """What follows once there is a reading: the words (asked when missing), a confirmation (when something about the reading is uncertain), the kind (reminder
    or event, for a line with no remind word) or the reminder."""
    how = draft["how"]
    if not draft["text"]:
        return {"ask": {**draft, "need": "text", "readings": [reading]}}
    if draft.get("doubt"):
        return {"ask": {**draft, "need": "confirm", "readings": [reading]}}
    if how == "bare":
        return {"ask": {**draft, "need": "kind", "readings": [reading]}}
    return {"when": reading["when"], "text": draft["text"], "reading": reading}


def _answers(word_norm: str, tables: list, group: str) -> bool:
    return any(word_norm in table["answers"][group] for table in tables)


KINDS = ("notice", "event", "yes", "other", "cancel", "thanks")


def _only(said: str, tables: list, kinds=KINDS) -> tuple:
    """(the kind words in the line, the rest) of a reply: the words of the answer lists taken out ("reminder", "calendar", "yes", "never mind"), whatever else is
    left (an article or a connector, "a reminder", is not left: it is noise)."""
    norm = nt.normalise(said)[0]
    tokens = _words(norm)
    noise = {w for table in tables for w in table["forget"]["fillers"] + table["connectors"] + list(table["number_words"])}
    found, rest = [], []
    index = 0
    while index < len(tokens):
        for size in (3, 2, 1):
            phrase = " ".join(tokens[index:index + size])
            kind = next((k for k in kinds if _answers(phrase, tables, k)), None)
            if kind and len(tokens[index:index + size]) == size:
                found.append(kind)
                index += size
                break
        else:
            if tokens[index] not in noise:
                rest.append(tokens[index])
            index += 1
    return found, rest


def answer_kind(said, languages=None):
    """"event" when the answer to "an event in the calendar, or something else?" is the calendar, "notice" when it is a reminder, "other" when it is something else,
    else None."""
    kinds, rest = _only(said if isinstance(said, str) else "", _tables(languages), kinds=("event", "notice", "other"))
    if rest or len(set(kinds)) != 1:
        return None
    return kinds[0]


def _time_only(said: str, now, tables: list):
    """The parse of `said` when it is nothing but a time phrase (and a connector), else None."""
    parsed = nt.parse(said, now, tables)
    if parsed is None:
        return None
    left = _tidy(nt.without(said, parsed["spans"]), tables)
    return parsed if not fold(left) else None


def _dated(reading: dict) -> dict:
    """A reading the person picked, with the day it was shown with: a bare `HH:MM` would be read again as `today or tomorrow`."""
    if reading.get("relative") or reading["dated"] or not reading.get("date") or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", reading["date"]):
        return reading
    return {**reading, "when": f"{reading['date']} {reading['time']}", "dated": True, "rolled": False}


def _replace(reading: dict, parsed: dict, now):
    """The reading that results when the person answers a confirmation with a time or a day: the answer replaces only the part it names (an hour alone keeps the
    day the line had; a day alone keeps the hour), a day and an hour replace both. None when the answer names nothing clear."""
    if "when" in parsed:
        new = parsed["reading"]
        if new["dated"]:
            return new
        return nt.moment(reading["date"], new["time"], now) if reading["dated"] and not reading.get("relative") and reading.get("date") else new
    if "missing" in parsed and parsed["day"]:
        return nt.moment(parsed["day"]["date"], reading["time"], now)
    return None


def _pick(draft: dict, said: str, now, tables: list):
    """The reading of `draft` that `said` names, or None: a time (by the day too, when the reply names one), an hour, a day of the month, or "yes" when one reading
    was offered."""
    readings = draft["readings"]
    kinds, rest = _only(said, tables)
    if kinds == ["yes"] and not rest and len(readings) == 1:
        return _dated(readings[0])
    digits = re.fullmatch(r"\s*([0-9]{1,2})\s*", said)
    if digits:
        n = int(digits.group(1))
        same = [r for r in readings if r["time"] and int(r["time"][:2]) == n]
        if len(same) != 1:
            same = [r for r in readings if r["date"] and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", r["date"]) and int(r["date"][8:10]) == n]
        return _dated(same[0]) if len(same) == 1 else None
    parsed = _time_only(said, now, tables)
    if parsed is None:
        return None
    if "when" in parsed:
        new = parsed["reading"]
        exact = [r for r in readings if r["when"] == new["when"]]
        if exact:
            return _dated(exact[0])
        if new["dated"]:
            return new                      # a day and an hour that are not any of the offered ones: the person's new reading replaces them
        same = [r for r in readings if r["time"] == new["time"]]
        return _dated(same[0]) if len(same) == 1 else None
    if "missing" in parsed and parsed["day"]:
        same = [r for r in readings if r["date"] == parsed["day"]["date"]]
        return _dated(same[0]) if len(same) == 1 else None
    return None


def complete(draft, said, now, languages=None):
    """The next line of the chat finishing `draft` (see the module's text), or None when it is not an answer to it."""
    tables = _tables(languages)
    said = said if isinstance(said, str) else ""
    need, how = draft["need"], draft["how"]
    if not said.strip() or said.lstrip().startswith("/"):
        return None
    kinds, rest = _only(said, tables)
    if kinds == ["cancel"] and not rest:
        return {"cancel": True}
    settled = {**draft, "doubt": False}
    if need == "confirm":
        reading = draft["readings"][0]
        if kinds in (["other"], ["thanks"]) and not rest:
            return {"cancel": True} if kinds == ["other"] else None
        if kinds == ["yes"] and not rest:
            return _next(settled, _dated(reading))          # the person saw the day and said yes: it is theirs, not a time that "rolled"
        parsed = _time_only(said, now, tables)
        new = _replace(reading, parsed, now) if parsed else None
        return None if new is None else _next(settled, new)
    if need == "time":
        parsed = _time_only(said, now, tables)
        if parsed is None:
            return None
        if "when" in parsed and parsed["reading"]["dated"]:       # a day and an hour, or a length of time: they replace what the line said
            return _next(settled, parsed["reading"])
        return understand(draft["line"] + " " + said, now, how, tables, trust=True)
    if need == "reading":
        picked = _pick(draft, said, now, tables)
        return None if picked is None else _next(settled, picked)
    if need == "kind":
        if rest or len(set(kinds)) != 1 or kinds[0] in ("yes", "other", "thanks"):
            return None
        if kinds[0] == "event":
            return {"event": True}
        return {"when": draft["readings"][0]["when"], "text": draft["text"], "reading": draft["readings"][0]}
    if need == "text":
        reading = draft["readings"][0]
        parsed = _time_only(said, now, tables)
        if parsed is not None:                       # a bare time completes the time, not the text
            new = _replace(reading, parsed, now)
            return None if new is None else {"ask": {**draft, "readings": [new]}}
        if kinds or candidate(said, tables) is not None:
            return None
        verbs = {w for table in tables for w in table["work_verbs"]}
        tokens = _words(nt.normalise(said)[0])
        if len(said.split()) > TEXT_MAX_WORDS or verbs & set(tokens) or nt.recurring(said, tables):
            return None
        return _next({**draft, "text": _tidy(said, tables)}, reading)          # a reading that was uncertain is confirmed once the words are there
    return None


def _date(info: dict):
    try:
        return datetime.date.fromisoformat(info["date"])
    except (TypeError, ValueError, KeyError):
        return None


def info_of(date: str, time: str, today: datetime.date) -> dict:
    """The facts `describe` reads, of a moment written as `date` ("YYYY-MM-DD") and `time` ("HH:MM"), seen from `today`."""
    try:
        day = datetime.date.fromisoformat(date)
    except (TypeError, ValueError):
        return {"date": date, "time": time, "rel": None, "far": False}
    return {"date": date, "time": time, "rel": (day - today).days, "far": day.year != today.year}


def _dm(day: datetime.date, info: dict) -> str:
    return f"{day.day:02d}/{day.month:02d}" + (f"/{day.year}" if info.get("far") else "")


def describe_day(info: dict, cfg=None) -> str:
    """A day as a person reads it, relative word first: "tomorrow, Mon 19/10", "Fri 30/10"."""
    day = _date(info)
    if day is None:
        return str(info.get("date") or "")
    wd = phrases.text(f"NT_WD_{day.weekday()}", cfg)
    dm = _dm(day, info)
    if info.get("rel") in (0, 1):
        rel = phrases.text("NT_REL_" + str(info["rel"]), cfg)
        return f"{rel}, {wd} {dm}"
    return f"{wd} {dm}"


def describe(info: dict, cfg=None, zone=None) -> str:
    """A moment as a person reads it: "tomorrow, Mon 19/10, at 13:00 (BRT)", "Fri 30/10 at 09:00 (BRT)", "Mon 03/10/2027 at 09:00". `info` is a reading, or the
    facts of a reminder just made."""
    day = _date(info)
    zone_part = f" ({zone})" if zone else ""
    if day is None:
        return f"{info.get('date') or ''} {info.get('time') or ''}{zone_part}".strip()
    wd = phrases.text(f"NT_WD_{day.weekday()}", cfg)
    dm = _dm(day, info)
    if info.get("rel") in (0, 1):
        return phrases.text("NT_WHEN_REL", cfg, rel=phrases.text(f"NT_REL_{info['rel']}", cfg), wd=wd, dm=dm, time=info["time"]) + zone_part
    return phrases.text("NT_WHEN_FAR", cfg, wd=wd, dm=dm, time=info["time"]) + zone_part


def capital(text: str) -> str:
    return text[:1].upper() + text[1:]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

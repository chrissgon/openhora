#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Natural requests, tier 1 (package NR-1): a line a person writes in their own words, matched by code to an operation the platform already has, with no model.

Pure: the clock is passed in, nothing is stored, logged or sent. The words are not here: they are the language tables (`runtime/natural_lang_<tag>.py`, read as
data by runtime/natural_time.py), and the table of EVERY language is tried on EVERY line. This module holds the rows of the operations a line may name today and
the rules that turn a line into a call. The rule that governs it: what is ambiguous, or not fully understood, is asked back and never guessed.

NR-1 builds the rows of the reminders (`remind`, `reminders`, `reminder-forget`) and one more, the calendar event (`calendar-event-create`, class E, planned: the
reply is "not built yet", never a reminder in its place). The other operations of the platform, the dispatcher that executes them by class and the router's
`operation` outcome are package NR-2; `NATURAL` is the closed list of the rows, and a line that matches none of them goes on to the router as before.

  candidate(line)                    what the line is, with no clock: {"op", "how", ...} | None. For `remind`, `how` is "trigger" (a remind word in the line),
                                     "bare" (a note word with a time, or a short line that holds a clock and nothing that asks for work: reminder or event is
                                     asked), "note" (a note word and no time: a reminder is offered), or "command" (the words after `/remind`, which the
                                     caller passes in itself); `calendar-event-create` has "trigger" (a calendar word) or "ask" (a scheduling verb with a
                                     time and no calendar word: event or something else is asked); `reminder-forget` has "id", "words" (what the person
                                     said of it) or "many"
  understand(line, now, how)         the reminder the line asks for, with the clock: {"when", "text", "reading"} when it is complete, or {"ask": {...}} with what
                                     is missing (`need`: time | reading | text | kind) and the draft the caller keeps to finish it; a time word the parse did
                                     not use ("next week", "every monday") makes it a question (`unsure`)
  complete(draft, said, now)         the next line of the same chat finishing a draft: the same shapes, {"event": True} when the person chose the calendar, or
                                     None when the line is not an answer (the draft is dropped and the line is handled as a new one)
  answer_kind(said)                  "event" | "other" | None: the answer to "an event in the calendar, or something else?"
  describe(info, cfg, zone)          a moment as a person reads it, in the project's language: "tomorrow, Mon 19/10, at 13:00 (BRT)"; the year is shown when it
                                     is not this one
  describe_day(info, cfg)            a day with no hour: "tomorrow, Mon 19/10"
  info_of(date, time, today)         the facts `describe` reads, of a moment written "YYYY-MM-DD" and "HH:MM"

The text of a reminder is a span of the person's own line (the line minus the trigger word, the time phrases and the connectives at its edges); the caller cleans
it and scans it for credentials (`reminders.clean_text`, `workcopy.credential_findings`). A time is always `natural_time.parse` of the person's line, so
`reminders.resolve` keeps every check it has. Nothing here guesses: a line with a trigger and no time is asked back, an hour that can be read two ways is
asked back, and a line no table recognises is not matched.

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
    {"op": "calendar-event-create", "class": "E", "trigger": "calendar", "planned": True},
)
LIST_WORDS_MAX = 5          # "what reminders do I have": a list request is short; a longer line that starts with the word asks for something else
BARE_LIST_WORDS_MAX = 2     # the bare word "reminders" is a list request only when it is nearly the whole line
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


def _forget(norm: str, tables: list):
    """The facts of a line that asks to forget a reminder ({"id": n} | {"id": None} | {"id": None, "words": [...]} | {"id": None, "many": True}), or None.
    A number in the line names it; with several numbers, or none, the person is asked which; the words the person says of it ("the florist one") are kept to
    look for it among their own."""
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
        tokens = _words(norm[m.end():])
        numbers = []
        for token in tokens:
            if token.isdigit() and int(token) >= 1 and int(token) not in numbers:
                numbers.append(int(token))
        if len(numbers) > 1:
            return {"id": None, "many": True}
        if numbers:
            return {"id": numbers[0]}
        allowed = {w for t in tables for w in t["forget"]["fillers"] + t["connectors"] + [x for p in t["polite"] for x in p.split()]}
        said = [t for t in tokens if t not in allowed]
        if not said:
            return {"id": None}
        return {"id": None, "words": said} if len(tokens) <= FORGET_WORDS_MAX else None
    return None


def candidate(line, languages=None):
    """What the line is, with no clock (see the module's text), or None. Pure, and never wider than `understand`: the bridge sends a line here to one place."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if not text.strip() or text.lstrip().startswith("/"):
        return None
    norm, origin = nt.normalise(text)
    forget = _forget(norm, tables)
    if forget:
        return {"op": "reminder-forget", "how": "trigger", **forget}
    listed = _head(norm, tables, "reminders")
    if listed is not None and len(_words(norm[listed:])) <= LIST_WORDS_MAX:
        return {"op": "reminders", "how": "trigger"}
    plain = _head(norm, tables, "reminders_bare")
    if plain is not None and "?" not in text and len(_words(norm[plain:])) <= BARE_LIST_WORDS_MAX \
            and not {w for t in tables for p in t["answers"]["other"] for w in p.split()} & set(_words(norm)):
        return {"op": "reminders", "how": "trigger"}
    if _head(norm, tables, "calendar") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    if _head(norm, tables, "remind") is not None:
        return {"op": "remind", "how": "trigger"}
    hits = nt.find(text, tables)["hits"]
    if hits and _anywhere(norm, tables, "remind_anywhere"):
        return {"op": "remind", "how": "trigger"}
    if hits and _head(norm, tables, "calendar_loose") is not None:
        return {"op": "calendar-event-create", "how": "ask"}
    if _head(norm, tables, "note") is not None:
        return {"op": "remind", "how": "bare" if hits else "note"}
    if not any(h["kind"] in ("clock", "relative") for h in hits) or "?" in text:
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


def _draft(need, how, line, text, readings=None, day=None, unsure=False):
    return {"need": need, "how": how, "line": line, "text": text, "readings": readings or [], "day": day, "unsure": unsure}


def understand(line, now, how="trigger", languages=None, trust=False):
    """The reminder `line` asks for at the clock `now` (see the module's text). `how` is "trigger", "bare", "note" or "command". `trust` is true when the person has
    just answered a question about this line, so that a word the parse did not use is not asked about again."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    norm, origin = nt.normalise(text)
    parsed = nt.parse(text, now, tables)
    cuts = list(parsed["spans"]) if parsed else []
    trigger = _trigger_span(norm, tables, how)
    if trigger:
        cuts.append((origin[trigger[0]], origin[trigger[1] - 1] + 1))
    rest = nt.without(text, cuts)
    words = _tidy(rest, tables)
    unsure = not trust and (nt.suspicious(rest, tables) or bool(parsed and parsed.get("vague")))
    if parsed is None or "missing" in parsed:
        return {"ask": _draft("time", how, text, words, day=(parsed or {}).get("day"), unsure=unsure)}
    if "ask" in parsed:
        return {"ask": _draft("time" if unsure else "reading", how, text, words, readings=parsed["ask"], unsure=unsure)}
    reading = parsed["reading"]
    if unsure:
        return {"ask": _draft("time", how, text, words, unsure=True)}
    if not words:
        return {"ask": _draft("text", how, text, "", readings=[reading])}
    if how == "bare":
        return {"ask": _draft("kind", how, text, words, readings=[reading])}
    return {"when": parsed["when"], "text": words, "reading": reading}


def _answers(word_norm: str, tables: list, group: str) -> bool:
    return any(word_norm in table["answers"][group] for table in tables)


def _only(said: str, tables: list, kinds=("notice", "event", "yes", "other")) -> tuple:
    """(the kind words in the line, the rest) of a reply: the words of the answer lists taken out ("reminder", "calendar", "yes"), whatever else is left
    (an article or a connector, "a reminder", is not left: it is noise)."""
    norm = nt.normalise(said)[0]
    tokens = _words(norm)
    noise = {w for table in tables for w in table["forget"]["fillers"] + table["connectors"] + list(table["number_words"])}
    found, rest = [], []
    index = 0
    while index < len(tokens):
        two = " ".join(tokens[index:index + 2])
        for kind in kinds:
            if _answers(two, tables, kind) or _answers(tokens[index], tables, kind):
                found.append(kind)
                index += 2 if _answers(two, tables, kind) else 1
                break
        else:
            if tokens[index] not in noise:
                rest.append(tokens[index])
            index += 1
    return found, rest


def answer_kind(said, languages=None):
    """"event" when the answer to "an event in the calendar, or something else?" is the calendar, "other" when it is something else, else None."""
    kinds, rest = _only(said if isinstance(said, str) else "", _tables(languages), kinds=("event", "other"))
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


def _ready(draft: dict, reading: dict, how: str):
    if not draft["text"]:
        return {"ask": _draft("text", how, draft["line"], "", readings=[reading])}
    if how == "bare":
        return {"ask": _draft("kind", how, draft["line"], draft["text"], readings=[reading])}
    return {"when": reading["when"], "text": draft["text"], "reading": reading}


def _pick(draft: dict, said: str, now, tables: list):
    """The reading of `draft` that `said` names, or None: a time (by the day too, when the reply names one), an hour, a day of the month, or "yes" when one reading
    was offered."""
    readings = draft["readings"]
    kinds, rest = _only(said, tables)
    if kinds == ["yes"] and not rest and len(readings) == 1:
        return readings[0]
    digits = re.fullmatch(r"\s*([0-9]{1,2})\s*", said)
    if digits:
        n = int(digits.group(1))
        same = [r for r in readings if r["time"] and int(r["time"][:2]) == n]
        if len(same) != 1:
            same = [r for r in readings if r["date"] and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", r["date"]) and int(r["date"][8:10]) == n]
        return same[0] if len(same) == 1 else None
    parsed = _time_only(said, now, tables)
    if parsed is None:
        return None
    if "when" in parsed:
        new = parsed["reading"]
        exact = [r for r in readings if r["when"] == new["when"]]
        if exact:
            return exact[0]
        if new["dated"]:
            return new                      # a day and an hour that are not any of the offered ones: the person's new reading replaces them
        same = [r for r in readings if r["time"] == new["time"]]
        return same[0] if len(same) == 1 else None
    if "missing" in parsed and parsed["day"]:
        same = [r for r in readings if r["date"] == parsed["day"]["date"]]
        return same[0] if len(same) == 1 else None
    return None


def complete(draft, said, now, languages=None):
    """The next line of the chat finishing `draft` (see the module's text), or None when it is not an answer to it."""
    tables = _tables(languages)
    said = said if isinstance(said, str) else ""
    need, how = draft["need"], draft["how"]
    if not said.strip() or said.lstrip().startswith("/"):
        return None
    if need == "time":
        parsed = _time_only(said, now, tables)
        if parsed is None:
            return None
        if "when" in parsed and (parsed["reading"]["dated"] or draft.get("unsure")):       # a day and an hour, or a length of time: they replace what the line said
            return _ready(draft, parsed["reading"], how)
        if draft.get("unsure"):          # the person has answered the doubt whole: what they say now is the time, not an addition to the line
            if "ask" in parsed:
                return {"ask": _draft("reading", how, draft["line"], draft["text"], readings=parsed["ask"])}
            return {"ask": _draft("time", how, draft["line"], draft["text"], day=parsed.get("day"))}
        return understand(draft["line"] + " " + said, now, how, tables, trust=True)
    if need == "reading":
        picked = _pick(draft, said, now, tables)
        return None if picked is None else _ready(draft, picked, how)
    if need == "kind":
        kinds, rest = _only(said, tables)
        if rest or len(set(kinds)) != 1 or kinds[0] in ("yes", "other"):
            return None
        if kinds[0] == "event":
            return {"event": True}
        return {"when": draft["readings"][0]["when"], "text": draft["text"], "reading": draft["readings"][0]}
    if need == "text":
        starters = {w for table in tables for w in table["work_starters"]}
        first = _words(nt.normalise(said)[0])[:1]
        if candidate(said, tables) is not None or len(said.split()) > TEXT_MAX_WORDS or (first and first[0] in starters):
            return None
        return {"when": draft["readings"][0]["when"], "text": _tidy(said, tables), "reading": draft["readings"][0]}
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

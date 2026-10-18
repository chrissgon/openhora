#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Natural requests, tier 1 (package NR-1): a line a person writes in their own words, matched by code to an operation the platform already has, with no model.

Pure: the clock is passed in, nothing is stored, logged or sent. The words are not here: they are the language tables (`runtime/natural_lang_<tag>.py`,
read by runtime/natural_time.py), and the table of EVERY language is tried on EVERY line. This module holds the rows of the operations a line may name today and
the rules that turn a line into a call.

NR-1 builds the rows of the reminders (`remind`, `reminders`, `reminder-forget`) and one more, the calendar event (`calendar-event-create`, class E, planned: the
reply is "not built yet", never a reminder in its place). The other operations of the platform, the dispatcher that executes them by class and the router's
`operation` outcome are package NR-2; `NATURAL` is the closed list of the rows, and a line that matches none of them goes on to the router as before.

  candidate(line)                    what the line is, with no clock: {"op", "how", ["id"]} | None. `how` is "trigger" (the line starts with a remind
                                     word), "bare" (a note word, or a short line that holds a clock and nothing that asks for work: the kind of request is
                                     asked), or "command" (the words after `/remind`, which the caller passes in itself)
  understand(line, now, how)         the reminder the line asks for, with the clock: {"when", "text", "reading"} when it is complete, or {"ask": {...}}
                                     with what is missing (`need`: time | reading | text | kind) and the draft the caller keeps to finish it
  complete(draft, said, now)         the next line of the same chat finishing a draft: the same shapes, {"event": True} when the person chose the
                                     calendar, or None when the line is not an answer (the draft is dropped and the line is handled as a new one)
  describe(info, cfg, zone)          a moment as a person reads it, in the project's language: "tomorrow, Mon 19/10, at 13:00 (BRT)"
  describe_day(info, cfg)            a day with no hour: "tomorrow, Mon 19/10"

The text of a reminder is a span of the person's own line (the line minus the trigger word, the time phrases and one leading connector); the caller cleans it
and scans it for credentials (`reminders.clean_text`, `workcopy.credential_findings`). A time is always `natural_time.parse` of the person's line, so
`reminders.resolve` keeps every check it has. Nothing here guesses: a line with a trigger and no time is asked back, an hour that can be read two ways is
asked back, and a line no table recognises is not matched.

Standard library only. Runs on Python 3.9: python3 runtime/natural.py --help
"""
from __future__ import annotations

import datetime
import os
import re
import sys

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
BARE_WORDS_MAX = 6          # a line with no trigger is asked about only when it is this short, once the time is taken out
TEXT_MAX_WORDS = 60         # the words of a reminder a draft keeps (the cap of the text itself is runtime/reminders.py TEXT_MAX)


def _tables(languages):
    return languages if languages is not None else nt.languages()


def _alt(phrase_lists):
    return nt._alt([p for lst in phrase_lists for p in lst])


def _head(norm: str, tables: list, group: str, key: str):
    """The end, in the folded line, of the longest trigger phrase of `triggers[key]` that the line starts with (after blanks, marks and a polite word), or None."""
    best = None
    for table in tables:
        phrases_ = table["triggers"][key] if group == "triggers" else table[group][key]
        alt = nt._alt(phrases_)
        if not alt:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        m = re.match(f"[^a-z0-9]*{lead}{alt}(?![a-z0-9])", norm)
        if m and (best is None or m.end() > best):
            best = m.end()
    return best


def _forget(norm: str, tables: list):
    """(end, id or None) of a line that asks to forget a reminder ("forget reminder 3"), or None."""
    for table in tables:
        forget = table["forget"]
        verbs, nouns, fillers = nt._alt(forget["verbs"]), nt._alt(forget["nouns"]), nt._alt(forget["fillers"])
        if not verbs or not nouns:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        fill = f"(?:{fillers}\\s+)*" if fillers else ""
        m = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+{fill}{nouns}(?![a-z0-9])", norm)
        if m:
            rest = norm[m.end():]
            allowed = {w for t in tables for w in t["forget"]["fillers"] + [x for p in t["polite"] for x in p.split()]}
            if any(not (token.isdigit() or token in allowed) for token in re.findall(r"[a-z0-9]+", rest)):
                continue          # "delete reminder emails from the list": the line asks for something else
            found = re.search(r"(?<![0-9])([0-9]{1,6})(?![0-9])", rest)
            number = int(found.group(1)) if found else None
            return m.end(), (number if number and number >= 1 else None)
    return None


def candidate(line, languages=None):
    """What the line is, with no clock (see the module's text), or None. Pure, and never wider than `understand`: the bridge sends a line here to one place."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if not text.strip() or text.lstrip().startswith("/"):
        return None
    norm, _origin = nt.normalise(text)
    forget = _forget(norm, tables)
    if forget:
        return {"op": "reminder-forget", "how": "trigger", "id": forget[1]}
    listed = _head(norm, tables, "triggers", "reminders")
    if listed is not None and len(re.findall(r"[a-z0-9]+", norm[listed:])) <= LIST_WORDS_MAX:
        return {"op": "reminders", "how": "trigger"}
    if _head(norm, tables, "triggers", "calendar") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    if _head(norm, tables, "triggers", "remind") is not None:
        return {"op": "remind", "how": "trigger"}
    hits = nt.find(text, tables)["hits"]
    if not hits:
        return None
    if _head(norm, tables, "triggers", "calendar_loose") is not None:
        return {"op": "calendar-event-create", "how": "trigger"}
    if _head(norm, tables, "triggers", "note") is not None:
        return {"op": "remind", "how": "bare"}
    if not any(h["kind"] in ("clock", "relative") for h in hits) or "?" in text:
        return None
    first = re.match(r"[^a-z0-9]*([a-z0-9]+)", norm)
    starters = {w for table in tables for w in table["work_starters"]}
    if first and first.group(1) in starters:
        return None
    rest = nt.without(text, nt._spans({"origin": _origin, "hits": hits}))
    if not rest or len(rest.split()) > BARE_WORDS_MAX:
        return None
    return {"op": "remind", "how": "bare"}


def _tidy(text: str, tables: list) -> str:
    """The words left of a line once the trigger and the time phrases are out: no mark at the ends, and no connector ("to", "de") at the start."""
    out = text.strip(" \t,;:-–—")
    first = out.split(None, 1)
    if first:
        word = re.sub(r"[^a-z0-9]", "", nt.normalise(first[0])[0])
        if any(word in table["connectors"] for table in tables):
            out = first[1].strip(" \t,;:-–—") if len(first) > 1 else ""
    return out


def _strip(line: str, norm: str, origin: list, ends: list, spans: list, tables: list) -> str:
    cuts = list(spans) + [(0, origin[end - 1] + 1) for end in ends if end]
    return _tidy(nt.without(line, cuts), tables)


def _draft(need, how, line, text, readings=None, day=None):
    return {"need": need, "how": how, "line": line, "text": text, "readings": readings or [], "day": day}


def understand(line, now, how="trigger", languages=None):
    """The reminder `line` asks for at the clock `now` (see the module's text). `how` is "trigger", "bare" or "command"."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    norm, origin = nt.normalise(text)
    end = None
    if how == "trigger":
        end = _head(norm, tables, "triggers", "remind")
    elif how == "bare":
        end = _head(norm, tables, "triggers", "note")
    parsed = nt.parse(text, now, tables)
    spans = parsed["spans"] if parsed else []
    words = _strip(text, norm, origin, [end], spans, tables)
    if parsed is None or "missing" in parsed:
        return {"ask": _draft("time", how, text, words, day=(parsed or {}).get("day"))}
    if "ask" in parsed:
        return {"ask": _draft("reading", how, text, words, readings=parsed["ask"])}
    reading = parsed["reading"]
    if not words:
        return {"ask": _draft("text", how, text, "", readings=[reading])}
    if how == "bare":
        return {"ask": _draft("kind", how, text, words, readings=[reading])}
    return {"when": parsed["when"], "text": words, "reading": reading}


def _answers(word_norm: str, tables: list, group: str) -> bool:
    return any(word_norm in table["answers"][group] for table in tables)


def _only(said: str, tables: list, kinds=("notice", "event", "yes")) -> tuple:
    """(the kind words in the line, the rest) of a reply: the words of the answer lists taken out ("reminder", "calendar", "yes"), whatever else is left
    (an article or a connector, "a reminder", is not left: it is noise)."""
    norm = nt.normalise(said)[0]
    tokens = re.findall(r"[a-z0-9]+", norm)
    noise = {w for table in tables for w in table["forget"]["fillers"] + table["connectors"] + list(table["number_words"])}
    found, rest = [], []
    for token in tokens:
        for kind in kinds:
            if _answers(token, tables, kind):
                found.append(kind)
                break
        else:
            if token not in noise:
                rest.append(token)
    return found, rest


def _time_only(said: str, now, tables: list):
    """The parse of `said` when it is nothing but a time phrase (and a connector), else None."""
    parsed = nt.parse(said, now, tables)
    if parsed is None:
        return None
    left = _tidy(nt.without(said, parsed["spans"]), tables)
    return parsed if not re.sub(r"[^a-z0-9]", "", nt.normalise(left)[0]) else None


def _ready(draft: dict, reading: dict, how: str):
    if not draft["text"]:
        return {"ask": _draft("text", how, draft["line"], "", readings=[reading])}
    if how == "bare":
        return {"ask": _draft("kind", how, draft["line"], draft["text"], readings=[reading])}
    return {"when": reading["when"], "text": draft["text"], "reading": reading}


def complete(draft, said, now, languages=None):
    """The next line of the chat finishing `draft` (see the module's text), or None when it is not an answer to it."""
    tables = _tables(languages)
    said = said if isinstance(said, str) else ""
    need, how = draft["need"], draft["how"]
    if not said.strip() or said.lstrip().startswith("/"):
        return None
    kinds, rest = _only(said, tables)
    if need == "time":
        parsed = _time_only(said, now, tables)
        if parsed is None:
            return None
        return understand(draft["line"] + " " + said, now, how, tables)
    if need == "reading":
        picked = None
        if kinds == ["yes"] and not rest and len(draft["readings"]) == 1:
            picked = draft["readings"][0]
        elif re.fullmatch(r"\s*[0-9]{1,2}\s*", said):
            same = [r for r in draft["readings"] if r["time"] and int(r["time"][:2]) == int(said)]
            picked = same[0] if len(same) == 1 else None
        else:
            parsed = _time_only(said, now, tables)
            if parsed and "when" in parsed:
                same = [r for r in draft["readings"] if r["time"] == parsed["reading"]["time"]]
                picked = same[0] if len(same) == 1 else None
        if picked is None:
            return None
        return _ready(draft, picked, how)
    if need == "kind":
        if rest or len(set(kinds)) != 1 or kinds[0] == "yes":
            return None
        if kinds[0] == "event":
            return {"event": True}
        return {"when": draft["readings"][0]["when"], "text": draft["text"], "reading": draft["readings"][0]}
    if need == "text":
        if candidate(said, tables) is not None or len(said.split()) > TEXT_MAX_WORDS:
            return None
        return {"when": draft["readings"][0]["when"], "text": _tidy(said, tables), "reading": draft["readings"][0]}
    return None


def _date(info: dict):
    try:
        return datetime.date.fromisoformat(info["date"])
    except (TypeError, ValueError, KeyError):
        return None


def describe_day(info: dict, cfg=None) -> str:
    """A day as a person reads it, relative word first: "tomorrow, Mon 19/10", "Fri 30/10"."""
    day = _date(info)
    if day is None:
        return str(info.get("date") or "")
    wd = phrases.text(f"NT_WD_{day.weekday()}", cfg)
    dm = f"{day.day:02d}/{day.month:02d}"
    if info.get("rel") in (0, 1):
        rel = phrases.text("NT_REL_" + str(info["rel"]), cfg)
        return f"{rel}, {wd} {dm}"
    return f"{wd} {dm}"


def describe(info: dict, cfg=None, zone=None) -> str:
    """A moment as a person reads it: "tomorrow, Mon 19/10, at 13:00 (BRT)", "Fri 30/10 at 09:00 (BRT)". `info` is a reading, or the facts of a reminder just made."""
    day = _date(info)
    zone_part = f" ({zone})" if zone else ""
    if day is None:
        return f"{info.get('date') or ''} {info.get('time') or ''}{zone_part}".strip()
    wd = phrases.text(f"NT_WD_{day.weekday()}", cfg)
    dm = f"{day.day:02d}/{day.month:02d}"
    if info.get("rel") in (0, 1):
        return phrases.text("NT_WHEN_REL", cfg, rel=phrases.text(f"NT_REL_{info['rel']}", cfg), wd=wd, dm=dm, time=info["time"]) + zone_part
    return phrases.text("NT_WHEN_FAR", cfg, wd=wd, dm=dm, time=info["time"]) + zone_part


def capital(text: str) -> str:
    return text[:1].upper() + text[1:]


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

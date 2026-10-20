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

NR-1 builds the intents of the reminders (`remind`, `reminders`, `reminder-forget`, `reminder-restore`) and one more, the calendar event
(`calendar-event-create`, the operation `event-create`: a verb with a calendar word, or a scheduling verb with a time, which is asked). The other operations of the
platform, the class of each (`CLASSES`, the one table that says it), their closed tier-1 forms (language data), the dispatcher that executes them by class
(runtime/ops_natural.py) and the router's `operation` outcome are package NR-2, in the second half of this file; a line that no intent and no form matches goes on to
the router as before.

  candidate(line)                    what the line is, with no clock: {"op", "how", ...} | None. For `remind`, `how` is "trigger" (a remind word in the line),
                                     "bare" (a note word with a time, or a short line that holds a clock and nothing that asks for work: reminder or event is
                                     asked), "note" (a note word and no time: a reminder is offered), or "command" (the words after `/remind`, which the
                                     caller passes in itself); `calendar-event-create` (the operation `event-create`) has "trigger" (a verb with a calendar word, or "marca" with a time) or
                                     "ask" (a scheduling verb with a time and no calendar word: event or something else is asked); `reminder-forget` has "id"
                                     (only an explicit one: "#9", "reminder 9"; with "confirm" a number after another word, "reminder of 3": shown and confirmed), "ids"
                                     (several, confirmed), "at" (an hour, "the reminder at 9": matched against the moment and confirmed), "words" (what the person said
                                     of it, matched by whole words) or "many"; `reminder-restore` is the bare "undo"
  understand(line, now, how)         the reading of the reminder the line asks for, with the clock, as the question to show: it NEVER returns a reminder to make (a reminder
                                     in free text is made only after the person's yes; the guard of runtime/natural_time.py `leftover_doubt` makes a reading a confirmation
                                     when the words outside the time may hold a date, a holiday or a language no table knows): {"when", "text", "reading"} when it is complete, or {"ask": {...}} with what
                                     is missing or uncertain (`need`: time | reading | text | kind | confirm | recurring | weekday | again | forget) and the draft the caller keeps to finish it
  complete(draft, said, now)         the next line of the same chat finishing a draft: the same shapes, {"event": True} when the person chose the calendar,
                                     {"cancel": True} when they gave it up, {"forget": [ids]} when they said yes to cancelling,
                                     {"ask": the same draft with `retries` 1} for a short reply that does not fit (asked once more), or None when the line is not an
                                     answer (the draft is dropped and the line is handled as a new one)
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

LIST_WORDS_MAX = 5          # "what reminders do I have": a list request is short; a longer line that starts with the word asks for something else
FORGET_WORDS_MAX = 5        # "cancel the reminder about the florist": what the person says of the reminder is short
BARE_WORDS_MAX = 6          # a line with no trigger is asked about only when it is this short, once the time is taken out
MANY_IDS_MAX = 5            # "cancel reminders 1 and 2": a few numbers are shown and confirmed; more are asked
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
    """The facts of a line that asks to forget a reminder, or None. An EXPLICIT number names it ("reminder 9", "reminder #9", "reminder number 9": the number is the
    whole object) and is acted on at once; a number with any other word before it ("reminder of 3", "reminder no 3" in a language where "no" is a preposition) is
    shown and confirmed, and so are several numbers ("reminder 1 and 2"); anything else the line says after "of"/"about" is words to look for among the person's own
    reminders (whole words, numbers too: "about the 9 o'clock one" is words, never the id 9), or an hour ("the reminder at 9") matched against the moment of the
    reminders and confirmed. A word right after the noun with no connective ("reminder emails from inbox") is not about a reminder of the person's."""
    for table in tables:
        forget = table["forget"]
        verbs, nouns, fillers = nt._alt(forget["verbs"]), nt._alt(forget["nouns"]), nt._alt(forget["fillers"])
        if not verbs or not nouns:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        fill = f"(?:{fillers}\\s+)*" if fillers else ""
        tail = f"(?:\\s+{polite})*" if polite else ""
        m = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+{fill}{nouns}(?![a-z0-9])", norm)
        if not m:
            bare = re.fullmatch(f"[^a-z0-9]*{lead}{verbs}\\s+(?:{fillers}\\s+)*#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", norm) if fillers else None
            if bare and int(bare.group(1)) >= 1:          # "cancela #3", "cancela o 3": no noun, so it is shown and confirmed, and a sender who has no such reminder gets a plain line
                return {"id": int(bare.group(1)), "confirm": True, "bare": True}
            last = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+{fill}(?P<mid>.+?)\\s+{nouns}[\\s?!.]*$", norm)
            if last:          # "cancel the 9am reminder": an hour in front of the noun
                found = nt.find(last.group("mid"), tables)
                stop = _stop(tables)
                left = _tidy(nt.without(last.group("mid"), nt._spans(found)), tables)
                if any(h["kind"] == "clock" for h in found["hits"]) and not [w for w in _words(left) if w not in stop]:
                    return {"id": None, "at": last.group("mid").strip(), "confirm": True}
            continue
        rest = norm[m.end():]
        idw = nt._alt(forget["id_words"])
        idm = nt._alt(forget["id_marked"])
        idp = f"(?:{idw}\\.?\\s*" + (f"|{idm}(?:\\.\\s*|(?=#?[0-9]))" if idm else "") + ")?" if idw else (f"(?:{idm}(?:\\.\\s*|(?=#?[0-9])))?" if idm else "")
        one = re.fullmatch(f"\\s*{idp}#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", rest)
        if one and int(one.group(1)) >= 1:
            return {"id": int(one.group(1))}
        soft = re.fullmatch(f"\\s*(?:{fillers}\\s+)+#?\\s*([0-9]{{1,6}}){tail}[\\s?!.]*", rest) if fillers else None
        if soft and int(soft.group(1)) >= 1:
            return {"id": int(soft.group(1)), "confirm": True}
        tokens = _words(rest)
        stop = _stop(tables)
        numbers = [int(t) for t in tokens if t.isdigit()]
        if len(numbers) >= 2 and all(t.isdigit() or t in stop for t in tokens) and all(n >= 1 for n in numbers):
            ids = sorted(set(numbers))
            return {"id": None, "ids": ids, "confirm": True} if len(ids) <= MANY_IDS_MAX else {"id": None, "many": True}
        found = nt.find(rest, tables)
        if any(h["kind"] == "clock" for h in found["hits"]):
            left = _tidy(nt.without(rest, nt._spans(found)), tables)
            if not [w for w in _words(left) if w not in stop]:
                return {"id": None, "at": rest.strip(), "confirm": True}
        said = [t for t in tokens if t not in stop]
        if not said:
            return {"id": None}
        if len(tokens) > FORGET_WORDS_MAX or tokens[0] not in stop:
            return None
        return {"id": None, "words": said}
    return None


def _undo(norm: str, tables: list) -> bool:
    """Whether the line is the bare word that brings a cancelled reminder back ("undo", "desfaz"), optionally with "the reminder" and nothing else: "undo the deploy"
    and "desfaz o commit" are requests for something else."""
    for table in tables:
        alt = nt._alt(table["triggers"]["undo"])
        if not alt:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        forget = table["forget"]
        nouns, fillers = nt._alt(forget["nouns"]), nt._alt(forget["fillers"])
        noun = f"(?:\\s+(?:{fillers}\\s+)*{nouns})?" if nouns and fillers else (f"(?:\\s+{nouns})?" if nouns else "")
        trail = f"(?:\\s+{polite})*" if polite else ""
        if re.fullmatch(f"[^a-z0-9]*{lead}{alt}{noun}{trail}[\\s.!]*", norm):
            return True
    return False


def _verb_noun(norm: str, tables: list):
    """The end, in the folded line, of "<scheduling verb> [a word or two] <reminder noun>" at the start of the line ("marca um lembrete", "schedule a reminder"), or None."""
    best = None
    for table in tables:
        triggers = table["triggers"]
        verbs, nouns = nt._alt(triggers["calendar_verb"] + triggers["calendar_loose"] + triggers["calendar_noun"]), nt._alt(table["remind_nouns"])
        if not verbs or not nouns:
            continue
        polite = nt._alt(table["polite"])
        lead = f"(?:{polite}\\s+)*" if polite else ""
        m = re.match(f"[^a-z0-9]*{lead}{verbs}\\s+(?:[a-z0-9]+\\s+){{0,2}}?{nouns}(?![a-z0-9])", norm)
        if m and (best is None or m.end() > best):
            best = m.end()
    return best


def candidate(line, languages=None):
    """What the line is, with no clock (see the module's text), or None. Pure, and never wider than `understand`: the bridge sends a line here to one place."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if not text.strip() or text.lstrip().startswith("/"):
        return None
    norm, origin = nt.normalise(text)
    tokens = _words(norm)
    problem = {w for t in tables for w in t["problem_words"]} & set(tokens)
    if "?" not in text and _undo(norm, tables):
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
    if _verb_noun(norm, tables) is not None and not problem:          # "marca um lembrete", "schedule a reminder": the word reminder wins over the scheduling verb
        return {"op": "remind", "how": "trigger"}
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
        if end is None:
            end = _verb_noun(norm, tables)
        return (0, end) if end is not None else _anywhere(norm, tables, "remind_anywhere")
    if how in ("bare", "note"):
        end = _head(norm, tables, "note")
        return (0, end) if end is not None else None
    return None


def _draft(need, how, line, text, readings=None, day=None, doubt=False):
    return {"need": need, "how": how, "line": line, "text": text, "readings": readings or [], "day": day, "doubt": doubt}


def understand(line, now, how="trigger", languages=None, trust=False, confirm=False):
    """The reminder `line` asks for at the clock `now` (see the module's text). `how` is "trigger", "bare", "note", "command" or "write" (package NR-5: the caller has cut the head of
    a write to the person's accounts, there is no trigger to cut, and the words that are left are the event's title). `trust` is true when the person has
    just answered a question about this line, so that a word the parse did not use is not asked about again; `confirm` makes the reading a confirmation whatever the line
    says (the answer to "which day next week?" is always shown with the day it resolved to)."""
    tables = _tables(languages)
    text = line if isinstance(line, str) else ""
    if nt.recurring(text, tables):
        return {"ask": _draft("recurring", how, text, "")}
    flagged, typos = nt.doubts(text, tables)
    for start, end, meant in sorted(typos, reverse=True):          # a day word with a typo is read as the word it is one letter from; with two such words it stays in the words
        if meant:
            text = text[:start] + meant + text[end:]
    norm, origin = nt.normalise(text)
    week = _week(norm, tables)
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
            return {"ask": _draft("weekday", how, line2, _tidy(nt.without(line2, cuts), tables))}
        inner = understand(line2, now, how, tables, trust=True)
        shape = inner["ask"] if "ask" in inner else {**inner, "readings": [inner["reading"]], "how": how, "line": line2, "doubt": False, "day": None, "need": "ready"}
        if shape["need"] in ("confirm", "kind", "text", "ready") and shape["readings"] and any(h["kind"] == "date" and h["spec"]["k"] == "wd" for h in found2["hits"]):
            reading = _next_week(shape["readings"][0], now) if shape["readings"][0].get("date") else shape["readings"][0]
            return _next(_draft("ready", how, line2, shape["text"], readings=[reading], doubt=True), reading)
        return inner
    found = nt.find(text, tables)
    parsed = nt.parse(text, now, tables)
    cuts = list(parsed["spans"]) if parsed else []
    if parsed and any(h.get("topic") for h in found["hits"]):          # "the meeting of friday": the weekday stays in the words, it may be what the reminder is about
        cuts = nt._spans({"origin": found["origin"], "hits": [h for h in found["hits"] if not h.get("topic")]})
    trigger = _trigger_span(norm, tables, how)
    if trigger:
        cuts.append((origin[trigger[0]], origin[trigger[1] - 1] + 1))
    words = _tidy(nt.without(text, cuts), tables)
    if parsed is None or "missing" in parsed:
        return {"ask": _draft("time", how, text, words, day=(parsed or {}).get("day"))}
    if "ask" in parsed:
        return {"ask": _draft("reading", how, text, words, readings=parsed["ask"])}
    reading = parsed["reading"]
    if reading.get("relative") and reading["relative"].endswith("d") and int(reading["relative"][3:-1]) <= 366 and not any(h["kind"] == "clock" for h in found["hits"]):
        return {"ask": _draft("time", how, text, words, day=nt._info(datetime.date.fromisoformat(reading["date"]), now))}          # "in 3 days": the day, and the hour is asked
    shipped = (trigger is not None and how in ("trigger", "note")) or how == "write"          # a write's head ("marca", "put on my calendar") was cut by the caller and is a shipped trigger
    dated = any(h["kind"] in ("date", "slash", "relative") for h in found["hits"])
    guard = nt.leftover_doubt(found, trigger, tables, unknown=how != "command" and not shipped and not dated)
    doubt = confirm or (not trust and (bool(parsed.get("vague")) or reading["assumed_year"] or flagged or guard))
    return _next(_draft("ready", how, text, words, readings=[reading], doubt=doubt), reading)


def _week(norm: str, tables: list):
    """(start, end), in the folded line, of the first phrase that names a week with no day in it ("next week", "semana que vem"), or None."""
    best = None
    for table in tables:
        alt = nt._alt(table["week_phrases"])
        m = re.search(f"{nt._L}{alt}{nt._R}", norm) if alt else None
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.end())
    return best


def _next(draft: dict, reading: dict, now=None):
    """What follows once there is a reading: the words (asked when missing), then, for a line in free text, the reading SHOWN: for a line with no remind word the kind
    question (it shows the reading: a reminder here, or an event), else the confirmation ("Entendi: ... Confirma?"). A reminder in free text is made only from a draft
    the person has confirmed (`confirmed`): a "yes" to the confirmation that showed the whole reading. The answer to the kind question (it showed the whole reading too) is the
    other way to a reminder, in `complete`. A pick among readings, a time, a day or the words are never a yes: the reading they lead to is shown first."""
    how = draft["how"]
    if not draft["text"]:
        return {"ask": {**draft, "confirmed": False, "need": "text", "readings": [reading]}}          # a yes given before the words are known confirms nothing
    if draft.get("confirmed"):
        return _pinned(draft, reading, now)
    if how == "bare":
        return {"ask": {**draft, "need": "kind", "readings": [reading]}}
    return {"ask": {**draft, "need": "confirm", "readings": [reading]}}


def _shown_moment(reading: dict, now):
    """The moment a reading was shown as, an aware datetime in the clock's zone (None when the reading holds no day and hour)."""
    try:
        return datetime.datetime.combine(datetime.date.fromisoformat(reading["date"]), datetime.time.fromisoformat(reading["time"])).replace(tzinfo=now.tzinfo)
    except (KeyError, TypeError, ValueError):
        return None


def _pinned(draft: dict, reading: dict, now):
    """The reminder made from the reading the person was SHOWN, at the moment they were shown: its day and hour, never a bare `HH:MM` or an `in 30m` that would be
    read again at the time of the answer. A moment shown that has passed by the time of the answer is not moved: an absolute one stays dated, so the operation refuses
    it as past; a relative one ("in 30 minutes") has no fixed moment of its own, so the new moment is shown and asked again."""
    reading = _dated(reading)
    if reading.get("relative") and now is not None:
        moment = _shown_moment(reading, now)
        if moment is None or moment <= now:
            fresh = nt.relative_again(reading, now)
            if fresh is not None:
                return _next({**draft, "confirmed": False}, fresh)          # the moment shown went by: the new one is shown, and the yes is asked again
        else:
            reading = {**reading, "when": f"{reading['date']} {reading['time']}"}          # the moment shown, not "in 30m" counted from the answer
    return {"when": reading["when"], "text": draft["text"], "reading": reading}


def _answers(word_norm: str, tables: list, group: str) -> bool:
    return any(word_norm in table["answers"][group] for table in tables)


KINDS = ("notice", "event", "yes", "other", "cancel", "thanks", "again")


def _only(said: str, tables: list, kinds=KINDS) -> tuple:
    """(the kind words in the line, the rest) of a reply: the words of the answer lists taken out ("reminder", "calendar", "yes", "never mind"), whatever else is
    left (an article or a connector, "a reminder", is not left: it is noise)."""
    norm = nt.normalise(said)[0]
    tokens = _words(norm)
    noise = {w for table in tables for w in table["forget"]["fillers"] + table["connectors"] + list(table["number_words"])}
    polite = {p for table in tables for p in table["polite"]}          # "please", "por favor": a courtesy is not an answer, and not a part of one
    found, rest = [], []
    index = 0
    while index < len(tokens):
        for size in (3, 2, 1):
            phrase = " ".join(tokens[index:index + size])
            kind = next((k for k in kinds if _answers(phrase, tables, k)), None)
            if len(tokens[index:index + size]) == size and (kind or phrase in polite):
                if kind:
                    found.append(kind)
                index += size
                break
        else:
            if tokens[index] not in noise:
                rest.append(tokens[index])
            index += 1
    return found, rest


def kind_fillers(tables: list) -> set:
    """The words that may surround the kind a person names when they answer the kind question (an article, a possessive, a place word, a polite word): closed lists of
    the language tables (`requests.writes.kind_fillers`), so that the answer stays a closed form with no open tail."""
    return {w for t in tables for p in (t.get("requests", {}).get("writes", {}) or {}).get("kind_fillers", []) for w in p.split()}


def _kinds_around(said: str, kinds: list, rest: list, tables: list) -> tuple:
    """(kinds, rest) of an answer to the kind question once the closed words around the kind are taken out of `rest`. The words around the kind are those of the SAME language
    as the kind word: the answer is read once for each language table alone, and the first table that accounts for the whole line with one kind of event or reminder gives it
    ("no calendario" is Portuguese: the "no" of another language is not a way out, and an English filler beside a Portuguese kind word is left over). A line no single language
    accounts for is returned as it was read, with every word left over."""
    for table in tables:
        own_kinds, own_rest = _only(said, [table])
        own_rest = [w for w in own_rest if w not in kind_fillers([table])]
        if {"event", "notice"} & set(own_kinds) and not own_rest:
            return own_kinds, own_rest
    return kinds, rest


def answer_kind(said, languages=None):
    """"event" when the answer to "an event in the calendar, or something else?" is the calendar, "notice" when it is a reminder, "other" when it is something else,
    else None. The kind may come with the closed words around it (`kind_fillers`)."""
    tables = _tables(languages)
    said = said if isinstance(said, str) else ""
    kinds, rest = _kinds_around(said, *_only(said, tables, kinds=("event", "notice", "other")), tables)
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


def _kind_with_time(said: str, kinds: list, rest: list, draft: dict, now, tables: list):
    """{"kind", "reading"} when the answer to the kind question is the kind AND a time or a day ("event at 3 pm"): the time replaces the part it names in the reading the
    question showed, and the words of the draft stay; None when the answer is anything else."""
    if not rest or len(set(kinds)) != 1 or kinds[0] not in ("event", "notice"):
        return None
    parsed = nt.parse(said, now, tables)
    if parsed is None or "spans" not in parsed:
        return None
    left = _tidy(nt.without(said, parsed["spans"]), tables)
    own, own_rest = _kinds_around(left, *_only(left, tables, kinds=("event", "notice", "other")), tables)
    if own_rest or len(set(own)) != 1 or own[0] != kinds[0]:
        return None
    new = _replace(draft["readings"][0], parsed, now)
    return {"kind": kinds[0], "reading": new} if new is not None else None


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


def _cancelled(need: str) -> dict:
    """The question is given up; a forget question says that nothing was cancelled."""
    return {"cancel": True, "kept": True} if need == "forget" else {"cancel": True}


def affirm(said, languages=None) -> bool:
    """Whether a reply is a yes and nothing else ("yes", "yes please", "ok thanks", "sure, go ahead"): courtesies and thanks around it are not an answer."""
    kinds, rest = _only(said if isinstance(said, str) else "", _tables(languages))
    return not rest and bool(kinds) and set(kinds) <= {"yes", "thanks"} and "yes" in kinds


WIDE_WORDS = 8          # the longest reply to the kind question that is still an attempt at an answer ("talvez mais tarde, ainda nao sei")


def short_answer(said, languages=None, wide: bool = False) -> bool:
    """Whether a reply that does not fit the question is short enough to be an attempt at an answer ("hmm", "talvez"), so that the question is asked once more: a
    long line, a question, a request for work or another request of this tier is a new line. With `wide` (the kind question, which the person answers in a phrase) up
    to WIDE_WORDS words, and a line that starts with a word of a question or of a request for work (`work_starters`) is still a new line."""
    tables = _tables(languages)
    said = said if isinstance(said, str) else ""
    verbs = {w for table in tables for w in table["work_verbs"]}
    tokens = _words(nt.normalise(said)[0])
    if wide:
        starters = {w for table in tables for w in table["work_starters"]}
        if tokens and tokens[0] in starters:
            return False
    return 0 < len(said.split()) <= (WIDE_WORDS if wide else 3) and "?" not in said and not (verbs & set(tokens)) and candidate(said, tables) is None


def _retry(draft: dict, said: str, tables: list):
    """The same question once more for a short reply that does not answer it; None the second time (the line is then handled as a new one)."""
    if draft.get("retries", 0) >= 1 or not short_answer(said, tables, wide=draft.get("need") == "kind"):
        return None
    return {"ask": {**draft, "retries": draft.get("retries", 0) + 1}}


def _table_of(draft: dict, tables: list) -> dict:
    """The table whose words the draft's line is in (the first, on a tie): a bare answer is given the cue of that language."""
    found = nt.find(draft.get("line") or draft.get("text") or "", tables)
    score = nt._score(found)
    return max(tables, key=lambda t: score[t["tag"]])


def _cued(said: str, draft: dict, tables: list) -> str:
    """An answer that is only a number gets the cue that makes it what it is, in the language of the question: "22/10" is a day ("dia 22/10"), "13.30" an hour ("as
    13.30"). A bare "9" is handled where it is an hour."""
    text = said.strip()
    table = _table_of(draft, tables)
    if re.fullmatch(r"[0-9]{1,2}/[0-9]{1,2}(?:/[0-9]{2,4})?", text) and table["date_cues"]:
        return f"{table['date_cues'][0]} {text}"
    if re.fullmatch(r"[0-9]{1,2}\.[0-9]{2}", text) and table["prefixes"]:
        return f"{table['prefixes'][0]} {text}"
    return said


def _next_monday(now) -> datetime.date:
    """The Monday that starts "next week": the Monday after this one; said on a Sunday, which a calendar that starts its weeks on Sunday (Brazil's, the United States')
    opens as a new week, the Monday after tomorrow's. The reading made with it is always shown, so a person who means the other one says so."""
    today = now.date()
    return today + datetime.timedelta(days=(8 if today.weekday() == 6 else 7 - today.weekday()))


def _next_week(reading: dict, now) -> dict:
    """The reading moved to the same weekday of next week (Monday to Sunday after this one)."""
    day = datetime.date.fromisoformat(reading["date"])
    first = _next_monday(now)
    while day < first:
        day += datetime.timedelta(days=7)
    while day >= first + datetime.timedelta(days=7):
        day -= datetime.timedelta(days=7)
    return nt.moment(day.isoformat(), reading["time"], now)


def _complete_week(draft: dict, said: str, now, tables: list):
    """The answer to "which day next week?": a weekday (or a date). A weekday is the one of next week (Monday to Sunday: the week after this one, and said on a Sunday the one after tomorrow's); the line gets the date,
    so everything after (the hour, the words) runs as for any line, and the reading is ALWAYS shown with the day it resolved to, whatever convention the person has."""
    found = nt.find(said, tables)
    wd = next((h for h in found["hits"] if h["kind"] == "date" and h["spec"]["k"] == "wd"), None)
    if wd is None:
        parsed = nt.parse(said, now, tables)
        if parsed is None or "missing" not in parsed or not parsed["day"]:
            return None
        return understand(draft["line"] + " " + said, now, draft["how"], tables, trust=True, confirm=True)
    first = _next_monday(now)
    day = (first + datetime.timedelta(days=wd["spec"]["i"])).isoformat()
    left = nt.without(said, nt._spans({"origin": found["origin"], "hits": [wd]}))
    base = draft["line"]
    if any(h["kind"] == "clock" for h in found["hits"]):          # the hour of the answer replaces the one the line had
        old = nt.parse(base, now, tables)
        base = nt.without(base, old["spans"]) if old and "spans" in old else base
    return understand(f"{base} {day} {left}".strip(), now, draft["how"], tables, trust=True, confirm=True)


def _complete_when(draft: dict, said: str, now, tables: list, settled: dict):
    """The answer to "for when?" after "another time": a whole moment, or a day (the hour is then asked), or an hour (on the day the person was shown, when the line named
    one: "tomorrow 13:00", "another time", "3pm" is tomorrow at 15:00), or a bare hour (asked: 09:00 or 21:00)."""
    date = draft.get("date")
    digits = re.fullmatch(r"\s*([0-9]{1,2})\s*", said)
    if digits and int(digits.group(1)) <= 23:
        prefix = _table_of(draft, tables)["bare_hour_prefixes"]
        said = (prefix[0] + " " if prefix else "") + digits.group(1)
    parsed = nt.parse(said, now, tables)
    if parsed is None:
        return _retry(draft, said, tables)

    def onday(reading):
        return nt.moment(date, reading["time"], now) if date and not reading["dated"] else reading
    if "when" in parsed:
        return _next(settled, onday(parsed["reading"]))
    if "ask" in parsed:
        seen, readings = set(), []
        for r in (onday(x) for x in parsed["ask"]):
            if r["when"] not in seen:
                seen.add(r["when"])
                readings.append(r)
        return {"ask": {**settled, "need": "reading", "readings": readings}}
    return {"ask": _draft("time", draft["how"], f"{draft['text']} {said}".strip(), draft["text"], day=parsed.get("day"))}


def engine_word(draft, said, languages=None):
    """The line as the engine reads the answer to a question that asks for a confirmation: one word of the lists `yes` and `no` of the tables (a language no table
    ships, in any script: the one source of those words is the language data) is the engine's own "yes" or "no". Any other line is returned as it is."""
    if isinstance(said, str) and draft.get("need") in ("confirm", "forget"):
        word = normal(said)
        if word in words_of("yes", languages):
            return "yes"
        if word in words_of("no", languages):
            return "no"
    return said


def complete(draft, said, now, languages=None):
    """The next line of the chat finishing `draft` (see the module's text), or None when it is not an answer to it. A short reply that does not fit is asked once
    more (the same draft, `retries` 1) instead of being dropped. The yes and no words of the language data count for every caller, the bridge's and the operations
    layer's alike (`engine_word`)."""
    tables = _tables(languages)
    said = engine_word(draft, said, languages)
    said = said if isinstance(said, str) else ""
    need, how = draft["need"], draft["how"]
    if not said.strip() or said.lstrip().startswith("/"):
        return None
    kinds, rest = _only(said, tables)
    if need == "forget" and not rest and kinds and set(kinds) <= {"yes", "cancel", "thanks"} and "yes" in kinds:
        return {"forget": draft["ids"]}          # "yes, cancel it": the word cancel is the action here, not a way out
    if need == "forget" and kinds == ["cancel"] and not rest:
        return _retry(draft, said, tables)          # "cancel" to "cancel it?" does not say which way: asked once more
    if kinds and set(kinds) <= {"cancel", "thanks"} and "cancel" in kinds and not rest:
        return _cancelled(need)
    if kinds and set(kinds) <= {"other", "thanks"} and "other" in kinds and not rest and need != "kind":          # "no", "no thanks": the question is given up
        return _cancelled(need)
    named = candidate(said, tables)
    if named is not None and need != "kind" and not (named["op"] == "remind" and named["how"] == "bare"):          # "sim mas as 15h" is a yes with an hour, not a line of its own
        return None          # a line that starts a request of its own ("me lembra ...", "cancela o lembrete 3") is a new line, never the answer to a question
    settled = {**draft, "doubt": False, "confirmed": False, "retries": 0}
    cued = _cued(said, draft, tables)
    if need == "forget":
        if affirm(said, tables):
            return {"forget": draft["ids"]}
        if kinds == ["other"] and not rest:
            return {"cancel": True}
        return _retry(draft, said, tables)
    if need == "confirm":
        reading = draft["readings"][0]
        if kinds == ["other"] and not rest:
            return {"cancel": True}
        if affirm(said, tables):
            return _next({**settled, "confirmed": True}, _dated(reading), now)          # the person saw the day and said yes: it is theirs, not a time that "rolled"
        if "yes" in kinds and set(kinds) <= {"yes", "thanks"} and rest:
            but = {w for t in tables for p in t["but_words"] for w in p.split()}
            change = _time_only(" ".join(w for w in rest if w not in but), now, tables)          # "yes, but at 3pm": a yes with a new hour (or day)
            new = _replace(reading, change, now) if change else None
            if new is not None:
                return _next(settled, new)
        if kinds == ["again"] and not rest:
            return {"ask": {**_draft("again", how, draft["text"], draft["text"]), "date": reading["date"] if not reading.get("relative") else None}}          # "another time": the words are kept, the moment is asked
        parsed = _time_only(cued, now, tables)
        new = _replace(reading, parsed, now) if parsed else None
        return _retry(draft, said, tables) if new is None else _next(settled, new)
    if need == "again":
        return _complete_when(draft, cued, now, tables, settled)
    if need == "weekday":
        done = _complete_week(draft, cued, now, tables)
        return _retry(draft, said, tables) if done is None else done
    if need == "time":
        digits = re.fullmatch(r"\s*([0-9]{1,2})\s*", said)
        if digits:          # a bare hour answers "at what time?": it is asked which of the two (09:00 or 21:00), never taken
            if int(digits.group(1)) > 23:
                return _retry(draft, said, tables)
            prefix = _table_of(draft, tables)["bare_hour_prefixes"]
            return understand(draft["line"] + " " + (prefix[0] + " " if prefix else "") + digits.group(1), now, how, tables, trust=True)
        parsed = _time_only(cued, now, tables)
        if parsed is None:
            return _retry(draft, said, tables)
        if "missing" in parsed and parsed["day"]:          # a day answers "at what time?": it replaces the day the line had, and only the hour is still asked
            old = nt.parse(draft["line"], now, tables)
            base = nt.without(draft["line"], old["spans"]) if old and "spans" in old else draft["line"]
            return understand(base + " " + cued, now, how, tables, trust=True)
        if "when" in parsed and parsed["reading"]["dated"]:       # a day and an hour, or a length of time: they replace what the line said
            return _next(settled, parsed["reading"])
        return understand(draft["line"] + " " + cued, now, how, tables, trust=True)
    if need == "reading":
        picked = _pick(draft, cued, now, tables)
        if picked is None:
            return _retry(draft, said, tables)
        return _next(settled, picked)          # a pick is not a yes: the picked reading is shown whole (the day, the hour, the words) and the yes makes it
    if need == "kind":
        kinds, rest = _kinds_around(said, kinds, rest, tables)          # the kind with the closed words around it
        if not kinds:          # a day or an hour instead of the kind: the reading shown is not the one meant, and the kind is asked again with the new one
            change = _time_only(cued, now, tables)
            new = _replace(draft["readings"][0], change, now) if change else None
            if new is not None:
                return _next(settled, new)
        corrected = _kind_with_time(said, kinds, rest, draft, now, tables)          # the kind with a time beside it: the time corrects the reading shown
        if corrected is not None:
            return {"event": True, "reading": corrected["reading"]} if corrected["kind"] == "event" else _next(settled, corrected["reading"], now)          # a reminder with a changed reading is shown and asked again: never made at once
        if rest or len(set(kinds)) != 1 or kinds[0] in ("other", "thanks", "again"):
            return _retry(draft, said, tables)
        if kinds[0] == "event":
            return {"event": True}
        return _next({**settled, "confirmed": True}, draft["readings"][0], now)          # "reminder", or a yes: the reading shown, with the day it was shown with
    if need == "text":
        reading = draft["readings"][0]
        parsed = _time_only(cued, now, tables)
        if parsed is not None:                       # a bare time completes the time, not the text
            new = _replace(reading, parsed, now)
            return None if new is None else {"ask": {**draft, "readings": [new]}}
        if kinds or candidate(said, tables) is not None:
            return _retry(draft, said, tables) if kinds else None
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


# --- the sentences of a question, a reminder made and a reminder cancelled (one place; the bridge and the operations layer both say them) -----------------

def question(draft: dict, cfg=None, with_text: bool = True, how: str = "trigger") -> tuple:
    """(the sentence that asks what `draft` needs, whether the draft is kept for the answer), in the project's language. The words of the reminder are repeated only
    when `with_text` (the project's notices carry text). `how` is how the line started ("command" for the words after /remind, "note" for a note word). A repetition
    is said and nothing is kept: it is a routine's."""
    need = draft["need"]
    if need == "recurring":
        return phrases.text("NT_RECURRING", cfg), False
    if need == "confirm":
        when = describe(draft["readings"][0], cfg)
        if draft["readings"][0].get("rolled"):          # "this morning at 9" said in the afternoon: tomorrow's is shown as such
            when = phrases.text("NT_ROLLED", cfg, time=draft["readings"][0]["time"], when=when)
        return (phrases.text("NT_CONFIRM_TEXT", cfg, when=when, text=draft["text"]) if with_text else phrases.text("NT_CONFIRM_COUNT", cfg, when=when)), True
    if need == "time":
        if draft.get("day"):
            return phrases.text("NT_ASK_TIME_DAY", cfg, day=capital(describe_day(draft["day"], cfg))), True
        if how == "note":
            return phrases.text("NT_ASK_NOTE", cfg), True
        return phrases.text("NT_ASK_WHEN_SLASH" if how == "command" else "NT_ASK_WHEN", cfg), True
    if need == "reading":
        options = f" {phrases.text('NT_OR', cfg)} ".join(describe(r, cfg) for r in draft["readings"])
        return phrases.text("NT_ASK_READINGS", cfg, options=options), True
    if need == "text":
        return phrases.text("NT_ASK_TEXT", cfg), True
    if need == "again":
        return phrases.text("NT_ASK_AGAIN", cfg), True
    if need == "weekday":
        return phrases.text("NT_ASK_WEEKDAY", cfg), True
    if need == "forget":
        return draft["sentence"], True
    when = capital(describe(draft["readings"][0], cfg))
    return (phrases.text("NT_ASK_KIND_TEXT", cfg, when=when, text=draft["text"]) if with_text else phrases.text("NT_ASK_KIND_COUNT", cfg, when=when)), True


def made_sentence(done: dict, cfg=None, with_text: bool = True) -> str:
    """The reply to a reminder just made (the result of the operation `remind`): its number, the moment as a person reads it, the words only when `with_text`, and the way
    to undo it; a time of day that had passed says so and gives tomorrow's."""
    human, reminder = done["human"], done["reminder"]
    when = describe(human, cfg, human["zone"])
    if human["rolled"]:
        when = phrases.text("NT_ROLLED", cfg, time=human["time"], when=when)
    if with_text:
        return phrases.text("NT_SET_TEXT", cfg, id=reminder["id"], when=when, text=reminder["text"])
    return phrases.text("NT_SET_COUNT", cfg, id=reminder["id"], when=when)


def forgot_sentence(done: dict, cfg=None, with_text: bool = True) -> str:
    """The reply to a reminder just cancelled: what it was (its moment and, with `with_text`, its words) and how to get it back."""
    human, row = done["human"], done["reminder"]
    when = describe(human, cfg, human["zone"])
    if "text" in row and with_text:
        return phrases.text("NT_FORGOT_TEXT", cfg, id=row["id"], when=when, text=row["text"])
    return phrases.text("NT_FORGOT_COUNT", cfg, id=row["id"], when=when)


def forget_question(shown: list, cfg=None, with_text: bool = True) -> tuple:
    """(the sentence, the draft) that asks "cancel it?" for the reminders `shown` (the previews of the operation `reminder-forget`): their moments and, with
    `with_text`, their words. A "yes" to the draft cancels exactly those numbers."""
    def one(done):
        when = describe(done["human"], cfg, done["human"]["zone"])
        row = done["preview"]
        return f"#{row['id']} {when}" + (f": {row['text']}" if "text" in row and with_text else "")
    numbers = [done["preview"]["id"] for done in shown]
    if len(shown) == 1:
        row, when = shown[0]["preview"], describe(shown[0]["human"], cfg, shown[0]["human"]["zone"])
        if "text" in row and with_text:
            sentence = phrases.text("NT_ASK_FORGET_TEXT", cfg, id=row["id"], when=when, text=row["text"])
        else:
            sentence = phrases.text("NT_ASK_FORGET_COUNT", cfg, id=row["id"], when=when)
    else:
        sentence = "\n".join([phrases.text("NT_ASK_FORGET_MANY", cfg)] + [one(done) for done in shown])
    return sentence, {**_draft("forget", "trigger", "", ""), "ids": numbers, "sentence": sentence}


# --- NR-2: what a line may do with each operation of the platform ------------------------------------------------------------------------------------
#
# The class of every operation (and the dispatcher that executes by class, runtime/ops_natural.py) is package NR-2. `CLASSES` is the ONE literal that gives an
# operation its class; no other table says it. The classes (contracts/runtime.md, "Natural requests"):
#
#   R  a read: runs at once, checked by the policy as the typed command is
#   N  a notice or an own write of the person's (a reminder): runs at once; a choice of the router's, or a time it normalised, asks first
#   W  a confirmed write (cancel, stop, retry, a routine's brakes and edits, a held file): never run from a line; the reply is the exact command to send
#   D  a decision (approve, reject, release, answer, go ahead): never decided from a line; the reply points to its card, which is sent again
#   E  an effect on the person's own accounts (a calendar event, an e-mail, a file in their drive): never run from a line; the reply is the exact operation to
#      run, which ends in a card of the exact content (package NR-5 routes a line into them with slots)
#   G  gated elsewhere (consent, mode, model, configuration, sources, the instructions, the terminal's own verbs): never run; the reply names the place and
#      the exact command
#   work  the planning agent's own work (say, request, route) and `ask`, which only the router's `Operation: ask` reaches
CLASSES = {
    # R: reads
    "status": "R", "progress": "R", "pending": "R", "task": "R", "agents": "R", "skills": "R", "costs": "R", "artifacts": "R", "artifact": "R",
    "instructions": "R", "routines": "R", "sources": "R", "attachments": "R", "reminders": "R", "flows": "R", "flow-check": "R",
    "connections": "R", "commands": "R", "items": "R",
    # N: a notice and the person's own writes
    "remind": "N", "reminder-forget": "N", "reminder-restore": "N",
    # W: confirmed writes
    "cancel": "W", "stop-task": "W", "retry": "W", "routine-pause": "W", "routine-cancel": "W", "routine-create": "W", "routine-change": "W",
    "attachment-add": "W", "attachment-discard": "W",
    # D: decisions
    "approve": "D", "reject": "D", "release": "D", "answer": "D", "go-ahead": "D",
    # E: effects on the person's own accounts, each ending in a card
    "event-create": "E", "event-change": "E", "event-cancel": "E", "mail-send": "E", "mail-reply": "E", "mail-draft": "E", "mail-archive": "E", "mail-move": "E",
    "mail-mark": "E", "mail-trash": "E", "file-create": "E", "file-replace": "E", "file-save": "E",
    # G: gated elsewhere
    "give-consent": "G", "set-mode": "G", "set-model": "G", "config": "G", "accept-config": "G", "routine-approve": "G", "routine-resume": "G",
    "instructions-set": "G", "instructions-add": "G", "source-add": "G", "source-import": "G", "source-refresh": "G", "source-describe": "G",
    "source-drive": "G", "source-onedrive": "G", "source-mail": "G", "source-calendar": "G", "flow-save": "G", "stage-file": "G", "sync": "G",
    "hand-over": "G", "dispatch": "G", "verdict": "G", "deps": "G", "run-next": "G", "run-task": "G", "run-step": "G", "proof": "G",
    "approve-policy": "G", "revoke-policy": "G", "standing": "G", "execute-under-policy": "G", "contained-run": "G", "poll": "G", "handler": "G",
    "pin": "G", "stop-runs": "G", "service-check": "G", "route-queued": "G", "attachment-hold": "G", "conversation": "G", "version": "G",
    "artifact-raw": "G",
    # work: the planning agent's own work, and the answer from sources
    "say": "work", "request": "work", "route": "work", "ask": "work",
}
# What a class E or a planned effect named but no operation is yet: empty since the writes of SPEC-SECRETARY-WRITES exist (a name here is not an operation; a test
# ties it both ways). The intent `candidate` calls a calendar event is the operation `event-create`.
PLANNED = ()
CANDIDATE_OPS = {"calendar-event-create": "event-create"}

# A slot: "<slot the router writes>": [kind, the parameter of the operation it fills]. Kinds: int (digits written in the line), ints (several integers, each written in the line), word (a piece of the line as it
# is written: an id, a path), span (a span of the normalised line: a text), when (the router's normalised time, the typed `When:` line).
NATURAL = {
    "status": {"slots": {}, "what": "where the work stands"},
    "progress": {"slots": {"since": ["word", "since"]}, "what": "what happened lately"},
    "pending": {"slots": {"id": ["int", "pending_id"]}, "what": "what waits for the person; with an id, that decision"},
    "task": {"slots": {"id": ["int", "task_id"]}, "what": "one task or request with its runs"},
    "agents": {"slots": {}, "what": "each area agent and its use of today"},
    "skills": {"slots": {}, "what": "the skills in scope with their proof"},
    "costs": {"slots": {"since": ["word", "since"]}, "what": "the runs by day, agent and model with their cost"},
    "artifacts": {"slots": {}, "what": "the project's files under docs/"},
    "artifact": {"slots": {"path": ["word", "path"]}, "what": "the text of one file under docs/"},
    "instructions": {"slots": {}, "what": "the project's standing instructions"},
    "routines": {"slots": {"id": ["int", "routine_id"]}, "what": "the routines and their state"},
    "sources": {"slots": {}, "what": "the project's sources: what files there are"},
    "attachments": {"slots": {}, "what": "the files people sent through a messaging app"},
    "reminders": {"slots": {}, "what": "the reminders that wait"},
    "flows": {"slots": {}, "what": "the flows the project can run"},
    "flow-check": {"slots": {"flow": ["word", "flow"]}, "what": "the check of one flow"},
    "connections": {"slots": {}, "what": "which provider each requirement class resolves to"},
    "commands": {"slots": {}, "what": "what can be asked and the commands"},
    "items": {"slots": {}, "what": "the numbered messages and events of the mail and calendar snapshots"},
    "remind": {"slots": {"text": ["span", "text"], "when": ["when", "when"]}, "what": "a reminder sent back once at a time"},
    "reminder-forget": {"slots": {"id": ["int", "reminder_id"]}, "what": "cancel a reminder that waits"},
    "reminder-restore": {"slots": {"id": ["int", "reminder_id"]}, "what": "bring back a reminder cancelled a moment ago"},
    "cancel": {"slots": {"id": ["int", "request_id"]}, "what": "cancel a request"},
    "stop-task": {"slots": {"id": ["int", "task_id"]}, "what": "stop a running task"},
    "retry": {"slots": {"id": ["int", "task_id"]}, "what": "make a failed or blocked task ready again"},
    "routine-pause": {"slots": {"id": ["int", "routine_id"]}, "what": "pause a routine"},
    "routine-cancel": {"slots": {"id": ["int", "routine_id"]}, "what": "cancel a routine"},
    "routine-create": {"slots": {}, "what": "create a routine"},
    "routine-change": {"slots": {"id": ["int", "routine_id"]}, "what": "change a routine"},
    "attachment-add": {"slots": {"id": ["int", "attachment_id"]}, "what": "add a file that was sent as a source"},
    "attachment-discard": {"slots": {"id": ["int", "attachment_id"]}, "what": "delete a file that was sent"},
    "approve": {"slots": {"id": ["int", "pending_id"]}, "what": "approve a plan or an acceptance (from its card)"},
    "reject": {"slots": {"id": ["int", "pending_id"]}, "what": "reject a decision (from its card)"},
    "release": {"slots": {"id": ["int", "pending_id"]}, "what": "release a delivery (from its card)"},
    "answer": {"slots": {"id": ["int", "pending_id"]}, "what": "answer a question a task asked (from its card)"},
    "go-ahead": {"slots": {"id": ["int", "task_id"]}, "what": "go ahead on a task that waits for another request"},
    "event-create": {"slots": {"title": ["span", "title"], "time": ["span", "start"], "calendar": ["word", "calendar"], "service": ["word", "account"]}, "what": "a card that creates an event on the person's own calendar"},
    "event-change": {"slots": {"event": ["int", "event"], "time": ["span", "start"], "title": ["span", "title"]}, "what": "a card that changes an event of the person's own calendar"},
    "event-cancel": {"slots": {"event": ["int", "event"]}, "what": "a card that removes an event of the person's own calendar"},
    "mail-send": {"slots": {"to": ["word", "to"], "subject": ["span", "subject"], "body": ["span", "text"]}, "what": "a card that sends an e-mail from the person's own account"},
    "mail-reply": {"slots": {"message": ["int", "message"], "body": ["span", "text"]}, "what": "a card that sends a reply to an e-mail"},
    "mail-draft": {"slots": {"to": ["word", "to"], "subject": ["span", "subject"], "body": ["span", "body"], "message": ["int", "message"]}, "what": "a card that saves a draft in the person's own mailbox"},
    "mail-archive": {"slots": {"messages": ["ints", "messages"]}, "what": "a card that takes messages out of the inbox"},
    "mail-move": {"slots": {"messages": ["ints", "messages"], "folder": ["word", "folder"]}, "what": "a card that moves messages to a folder"},
    "mail-mark": {"slots": {"messages": ["ints", "messages"], "state": ["span", "state"]}, "what": "a card that marks messages read or unread"},
    "mail-trash": {"slots": {"messages": ["ints", "messages"]}, "what": "a card that moves messages to the trash"},
    "file-create": {"slots": {"name": ["word", "file_name"], "content": ["span", "content"], "folder": ["word", "folder"]}, "what": "a card that creates a file in the person's own drive"},
    "file-replace": {"slots": {"file": ["span", "file"], "content": ["span", "content"]}, "what": "a card that writes a new revision of a file that is a source"},
    "file-save": {"slots": {"attachment": ["int", "attachment"], "folder": ["word", "folder"]}, "what": "a card that saves a file someone sent"},
    "give-consent": {"slots": {}, "what": "the consent an autonomous agent needs"},
    "set-mode": {"slots": {}, "what": "move an agent's autonomy mode"},
    "set-model": {"slots": {}, "what": "fix an agent to a model"},
    "config": {"slots": {}, "what": "the configuration and its hash"},
    "accept-config": {"slots": {}, "what": "accept the configuration's hash"},
    "routine-approve": {"slots": {"id": ["int", "routine_id"]}, "what": "approve a routine by its hash"},
    "routine-resume": {"slots": {"id": ["int", "routine_id"]}, "what": "resume a paused routine"},
    "instructions-set": {"slots": {}, "what": "replace the standing instructions"},
    "instructions-add": {"slots": {}, "what": "add a line to the standing instructions"},
    "source-add": {"slots": {}, "what": "register a source"},
    "source-import": {"slots": {}, "what": "import a version of a source"},
    "source-refresh": {"slots": {}, "what": "refresh a source"},
    "source-describe": {"slots": {}, "what": "describe a source"},
    "source-drive": {"slots": {}, "what": "make Drive files sources"},
    "source-onedrive": {"slots": {}, "what": "make OneDrive files sources"},
    "source-mail": {"slots": {}, "what": "a window of the mailbox as a source"},
    "source-calendar": {"slots": {}, "what": "a calendar's window as a source"},
    "flow-save": {"slots": {}, "what": "save an approved plan as a flow"},
    "stage-file": {"slots": {}, "what": "hand a file over for a request's plan"},
    "sync": {"slots": {}, "what": "mirror the tasks and the documents"},
    "hand-over": {"slots": {}, "what": "copy a file into a task's file drop"},
    "dispatch": {"slots": {}, "what": "one round of the dispatcher"},
    "verdict": {"slots": {}, "what": "record a verdict on a run"},
    "deps": {"slots": {}, "what": "install the dependency sets"},
    "run-next": {"slots": {}, "what": "run the next ready task"},
    "run-task": {"slots": {}, "what": "run one named task"},
    "run-step": {"slots": {}, "what": "run one named step task"},
    "proof": {"slots": {}, "what": "the model each skill would run on"},
    "approve-policy": {"slots": {}, "what": "a standing approval of a policy file"},
    "revoke-policy": {"slots": {}, "what": "end a standing approval"},
    "standing": {"slots": {}, "what": "whether a standing approval covers a policy"},
    "execute-under-policy": {"slots": {}, "what": "execute an effect inside a standing approval"},
    "contained-run": {"slots": {}, "what": "run one skill in the container"},
    "poll": {"slots": {}, "what": "the short job"},
    "handler": {"slots": {}, "what": "start one verb of a handler"},
    "pin": {"slots": {}, "what": "write the pin of the dispatcher's jobs"},
    "stop-runs": {"slots": {}, "what": "end the runs this process started"},
    "service-check": {"slots": {}, "what": "what the local service checks at its start"},
    "route-queued": {"slots": {}, "what": "route the oldest queued line"},
    "attachment-hold": {"slots": {}, "what": "the bridge's own call for a file that arrived"},
    "conversation": {"slots": {}, "what": "the messages of the project's conversation"},
    "version": {"slots": {}, "what": "the change signal of the store"},
    "artifact-raw": {"slots": {}, "what": "the bytes of one image under docs/"},
    "say": {"slots": {}, "what": "one turn of the conversation with the planning agent"},
    "request": {"slots": {}, "what": "record what the person wants"},
    "route": {"slots": {}, "what": "plan a request"},
    "ask": {"slots": {}, "what": "answer a question from the text of the project's sources (the question is the person's whole line)"},
}

# --- tier 1 for the other operations: the forms are language data -----------------------------------------------------------------------------------
#
# Each language table (runtime/natural_lang_<tag>.py) holds a key `requests`: {"forms": {operation: [regular expression, ...]}, "aliases": [[word, ...], ...] (words
# for one kind of document, for runtime/source_resolve.py), "cues": [...] (words that say "a file"), "generic": [...] (words that never name a source), "short_stop":
# [...] (function words of the language), "yes": [...] and "no": [...] (the words of a confirmation that the table of `answers` does not hold, in any script), "writes": {...} (the lists of phrases of the natural writes, package NR-5:
# runtime/natural_writes.py `check_writes` reads it; here it is only checked to be an object)}.
# A form is matched against the WHOLE line, lower case, no accent, every run of other characters one space (`ascii_normal`); it has NO open tail: a verb, the
# object it acts on and a closed ending, so that a request for work that starts with the same words is never taken (a line that no form matches goes on to
# the router). The only argument a form gives is an integer, the group `n`. The table of EVERY language is tried on EVERY line, as for the time words.
LINE_WORDS = 40          # a longer line is a request, not a form
PRIVATE = ("remind",)    # the operations whose line is the person's private words: the conversation does not store them (limit L51)
# The only constructs a tier-1 form may use (the whitelist `check_requests` applies): literal characters, groups `( )` and `(?: )`, alternation `|`, an optional `?`, and a
# class `[..]` of listed characters. Anything that matches an unbounded run (`.`, `*`, `+`, `{n,}`, `\w`, `\S`, a range, a look-around) is refused, so a form can only be a
# closed phrase and a request for work that starts with the same words is never taken.
CLOSED_FORM = re.compile(r"(?:[^\\.*+{}^$\[\]()|?]|\(\?:|\((?!\?)|\)|\||\?|\[[^\]\\^\-*+.?]+\])*")
NUMBER = r"(?P<n>[0-9]{1,9})"          # what `{n}` stands for in a form
REQUEST_KEYS = ("forms", "aliases", "cues", "generic", "short_stop", "yes", "no", "writes")
_COMPILED = {}
WHEN_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}")
WORD_EDGE = ".,;:!?()\"'"      # punctuation around a word of the line that is not part of it
WORD_RE = re.compile(r"[^\s]{1,200}")
SPAN_MAX = 300           # characters of a text slot


def ascii_normal(text: str) -> str:
    """Lower case, no accents, every run of other characters one space (a-z and 0-9 only): the form tier 1 matches on."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def normal(text: str) -> str:
    """The rule a text is compared by in any language: compatibility form (full-width digits become digits), case folded, accents removed, every run of
    characters that are neither a letter nor a digit one space. A script with no spaces (Japanese, Chinese) stays one run."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text)).casefold() if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", plain).strip()


def check_requests(table: dict) -> None:
    """ValueError(sentence) when the key `requests` of a language table is not of the shape above (a table without it has none of these words)."""
    where = f"language table {table.get('tag')!r}: requests"
    given = table.get("requests", {})
    if not isinstance(given, dict) or set(given) - set(REQUEST_KEYS):
        raise ValueError(f"{where} is a dict with the keys {', '.join(REQUEST_KEYS)}")
    for key in REQUEST_KEYS:
        value = given.get(key, {} if key == "forms" else [])
        if key == "forms":
            if not isinstance(value, dict):
                raise ValueError(f"{where}.forms maps an operation to a list of regular expressions")
            for op, forms in value.items():
                if op not in CLASSES or not isinstance(forms, list) or not all(isinstance(f, str) for f in forms):
                    raise ValueError(f"{where}.forms: {op!r} is not an operation with a list of regular expressions")
                for form in forms:
                    if not CLOSED_FORM.fullmatch(form.replace("{n}", "")):
                        raise ValueError(f"{where}.forms: {form!r} is not a closed phrase: a form is words, spaces, groups, `|` and `?` (and `[..]` of listed letters) with the "
                                         "integer written `{n}`, and nothing that matches an unbounded run (`.`, `*`, `+`, `{n,}`, `\\w`, `\\S`, a range)")
                    re.compile(form.replace("{n}", NUMBER))
        elif key == "writes":
            if not isinstance(given.get("writes", {}), dict):
                raise ValueError(f"{where}.writes is an object (the words of the natural writes, package NR-5: runtime/natural_writes.py check_writes reads it)")
        elif key == "aliases":
            if not isinstance(value, list) or not all(isinstance(g, list) and all(isinstance(w, str) and w for w in g) for g in value):
                raise ValueError(f"{where}.aliases is a list of lists of words")
        elif not isinstance(value, list) or not all(isinstance(w, str) and w for w in value):
            raise ValueError(f"{where}.{key} is a list of words")


def _requests(languages=None) -> list:
    """The `requests` of every table, checked once."""
    out = []
    for table in _tables(languages):
        key = id(table)
        if key not in _COMPILED:
            check_requests(table)
            given = table.get("requests", {})
            _COMPILED[key] = {"forms": {op: tuple(re.compile(f.replace("{n}", NUMBER)) for f in forms) for op, forms in given.get("forms", {}).items()},
                              **{k: list(given.get(k, [])) for k in REQUEST_KEYS if k not in ("forms", "writes")}}
        out.append(_COMPILED[key])
    return out


def words_of(key: str, languages=None) -> list:
    """The words of one list of `requests` ("cues", "generic", "short_stop", "yes", "no"), the union over every table, in order."""
    out = []
    for given in _requests(languages):
        out += [w for w in given[key] if w not in out]
    return out


def aliases(languages=None) -> dict:
    """{word: the first word of its group}: the groups of every table, those that share a word being one."""
    groups = []
    for given in _requests(languages):
        for group in given["aliases"]:
            merged = [g for g in groups if set(g) & set(group)]
            for g in merged:
                groups.remove(g)
            groups.append(list(dict.fromkeys([w for g in merged for w in g] + group)))
    return {w: g[0] for g in groups for w in g}


def class_of(name: str):
    """The class of an operation, or None when the table has none."""
    return CLASSES.get(name)


def operation_of(intent_op: str) -> str:
    """The operation an intent of `candidate` is: the calendar event is `event-create`; every other intent is the operation of its own name."""
    return CANDIDATE_OPS.get(intent_op, intent_op)


def match(line: str, languages=None):
    """Tier 1 for the operations other than the reminders (those are `candidate`): {"op", "args": {parameter: value}, "tier": 1} when the line is one closed form of
    exactly one operation, else None. The only argument a form gives is the integer written in the line."""
    if not isinstance(line, str) or line.startswith("/") or "@" in line:
        return None
    flat = ascii_normal(line)
    if not flat or len(flat.split()) > LINE_WORDS:
        return None
    found = []
    for given in _requests(languages):
        for op, forms in given["forms"].items():
            for form in forms:
                hit = form.fullmatch(flat)
                if hit:
                    found.append((op, hit))
                    break
    if len({op for op, _hit in found}) != 1:
        return None
    op, hit = found[0]
    args = {}
    if "n" in hit.groupdict() and hit.group("n") is not None:
        slot = next((v for v in NATURAL[op]["slots"].values() if v[0] == "int"), None)
        if slot is None:
            return None
        args[slot[1]] = int(hit.group("n"))
    return {"op": op, "args": args, "tier": 1}


def needs(line: str, languages=None):
    """The operation whose group a messaging sender must hold for this line to be tier 1 (a form of `match`), or None (the line
    needs the group `talk`, as every plain line does): a read or a notice needs its own group, a decision needs to read (`pending`), the other classes `talk`."""
    found = match(line, languages)          # not `candidate`: a reminder in words is the messaging bridge's own, done before a line reaches `say`; one it declined is a plain line
    if found is None:
        return None
    cls = CLASSES[found["op"]]
    if cls in ("R", "N"):
        return found["op"]
    return "pending" if cls == "D" else None


def private(line: str, languages=None) -> bool:
    """Whether the line is a reminder asked in words (`candidate` says `remind`) or a write to the person's accounts (runtime/natural_writes.py `candidate`): the conversation
    stores a neutral word for it, as the words are the person's private ones (limits L51 and L61)."""
    found = candidate(line, languages)
    if found is not None and found["op"] in PRIVATE:
        return True
    import importlib
    return importlib.import_module("natural_writes").candidate(line, languages) is not None          # a write to the person's accounts (package NR-5, limit L61)


def confirm_kind(said, languages=None):
    """"yes" or "no" for the answer to a question that asks for a confirmation, else None. A yes is a yes and nothing else (`affirm`: courtesies are not an answer) or
    one word of the lists `yes` of the tables, in any script; a no is a no, a cancel or a never mind and nothing else, or one word of the lists `no`."""
    if not isinstance(said, str):
        return None
    word = normal(said)
    if word in words_of("yes", languages) or affirm(said, languages):
        return "yes"
    if word in words_of("no", languages):
        return "no"
    kinds, rest = _only(said, _tables(languages), kinds=("other", "cancel"))
    return "no" if kinds and not rest else None


def _numbers(line: str) -> set:
    return {int(n) for n in re.findall(r"[0-9]+", unicodedata.normalize("NFKC", line)) if len(n) <= 9}


def check_operation(name, slots: dict, when, line) -> dict:
    """Whether the router's `Operation:` outcome can be believed against the person's line, by code only: {"ok": True, "name", "args": {parameter:
    value}, "when": the normalised time or None} or {"ok": False, "why"}. `slots` is {slot: words} from the `Argument <slot>:` lines. The name must be
    in the table and not one of the work operations other than `ask`; a slot must be one the row has and must be of its kind (an integer written in the
    line; a word that is a piece of the line as written; a text that is a span of the normalised line); `when` must have the shape YYYY-MM-DD HH:MM, be
    a date and a time, and belong to a row that has a time slot. Nothing is read from the catalog or the router's other lines."""
    if not isinstance(line, str) or not line.strip():
        return {"ok": False, "why": "an operation is read only for the person's line"}
    if name not in NATURAL or name not in CLASSES:
        return {"ok": False, "why": f"{name!r} is not an operation a line may reach"}
    if CLASSES[name] == "work" and name != "ask":
        return {"ok": False, "why": f"{name!r} is the planning agent's own work, not an operation a line names"}
    row = NATURAL[name]["slots"]
    flat, args = normal(line), {}
    for slot, words in slots.items():
        spec = row.get(slot)
        if spec is None or spec[0] == "when":
            return {"ok": False, "why": f"the operation {name} has no argument {slot!r}"}
        kind, param = spec
        if kind == "int":
            if not (words.isascii() and words.isdigit() and len(words) <= 9) or int(words) not in _numbers(line):
                return {"ok": False, "why": f"the argument {slot!r} is not a number written in the line"}
            args[param] = int(words)
        elif kind == "ints":
            parts = [p for p in re.split(r"[\s,;]+", words.strip()) if p]
            if not parts or len(parts) > 20 or not all(p.isascii() and p.isdigit() and len(p) <= 9 and int(p) in _numbers(line) for p in parts):
                return {"ok": False, "why": f"the argument {slot!r} is not a list of numbers written in the line"}
            args[param] = [int(p) for p in parts]
        elif kind == "word":
            tokens = [t.strip(WORD_EDGE) for t in unicodedata.normalize("NFKC", line).split()]      # a whole word of the line, as written: never a piece inside a longer word
            if not WORD_RE.fullmatch(words) or words not in tokens:
                return {"ok": False, "why": f"the argument {slot!r} is not a piece of the line"}
            args[param] = words
        else:
            mine = normal(words)
            if not mine or len(words) > SPAN_MAX or mine not in flat:
                return {"ok": False, "why": f"the argument {slot!r} is not a span of the line"}
            args[param] = words
    if when is not None:
        if "when" not in row:
            return {"ok": False, "why": f"the operation {name} takes no time"}
        if not WHEN_RE.fullmatch(when):
            return {"ok": False, "why": "the When line is not YYYY-MM-DD HH:MM"}
        try:
            datetime.datetime.strptime(when, "%Y-%m-%d %H:%M")
        except ValueError:
            return {"ok": False, "why": "the When line is not a date and a time"}
    return {"ok": True, "name": name, "args": args, "when": when}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

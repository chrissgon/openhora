#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A repetition in the person's own words, read by code from closed lists and never by a model (package CB-7, limits L54 and L61).

The platform creates a daily or a weekly series and cancels a whole series or one occurrence of it. What a line says about the repetition is read here, from the folded phrases of
runtime/registry/recurrence_words.json (pt-BR and en; other languages are read only as "the line repeats", through the time engine, and never as a series). A model may name the span of
the line that holds the repetition (the slot `repeat` of the line catalog, from version 2); it never says what the repetition is.

  mentions(text)                  whether the line holds any repetition phrase of the closed lists, supported or not ("todo dia", "toda segunda", "every Monday", "monthly", "a cada 2 dias"), or
                                  the time engine says it repeats (`natural_time.recurring`: every language of its tables, so a line in a language this file cannot read is still caught).
                                  A line that mentions one and has none read opens no event card (the guard of scenario 20: never one event with "toda segunda" in its title)
  read(text, start_weekday)       {"freq": "daily"} or {"freq": "weekly", "byday": "MO".."SU"} for a text that holds exactly one supported repetition, or None: an unsupported one ("a cada
                                  2 dias", "todo mes", "todo dia 16"), an end ("ate dezembro", "until", "3 vezes"), two weekdays, a weekday that is not the start's (`start_weekday` is
                                  datetime.weekday() of the first occurrence, 0 = Monday), or nothing. A weekly repetition is on the weekday of the start, never another
  words(text)                     {"series": bool, "occurrence": bool}: whether the line holds a word that says the whole series ("todas", "a serie", "the whole series", or any repetition phrase)
                                  or one occurrence ("so", "so essa vez", "da proxima", "dessa semana", "only", "this time")
  which(text, specific_day)       "series", "occurrence" or "ask" for a cancel (limit L61, never a guess): series words and no occurrence word and no specific day; an occurrence word or a
                                  specific day and no series word; anything else, both kinds or neither, asks. `specific_day` is whether the line names a date, not a bare weekday name
  week_range(text)                whether the line says "this week" ("essa semana", "this week"): a range, not a day
  strip(text)                     the text without the words that only say it repeats ("todo dia", "toda semana", the "toda" of "toda segunda"); the weekday and the clock stay, so the
                                  time engine reads the first occurrence of what is left
  rule_word(recurrence)           "daily" or "weekly:MO".."weekly:SU", the closed word a document and a card hold for a repetition

Folding: lower case, no accent, the characters a-z and 0-9, every other character a space. Standard library and runtime/natural_time.py only. Python 3.9.
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import natural_time as nt  # noqa: E402  (the time engine: `recurring` says, for every language of its tables, that a line repeats)
import registry_data  # noqa: E402

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")      # datetime.weekday() order, Monday first
NOT_FOLDED = re.compile(r"[^a-z0-9]+")
WORD = re.compile(r"\w+")
NUMBER_LEAD = ("every", "each", "cada")      # "every 2 days", "cada 2 semanas": a lead followed by a digit is a repetition that is not daily or weekly
_CACHE: dict = {}


def fold(text) -> str:
    """The folded text: lower case, no accent, a-z and 0-9, one space between words."""
    decomposed = unicodedata.normalize("NFKD", text if isinstance(text, str) else "")
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    return NOT_FOLDED.sub(" ", plain).strip()


def _tokens(text) -> list:
    return fold(text).split()


def _data() -> dict:
    """The lists of the registry file as tuples of tokens, read once (`forget` drops them)."""
    if "data" not in _CACHE:
        raw = registry_data.recurrence_words()
        out = {key: [tuple(phrase.split()) for phrase in raw[key]] for key in registry_data.RECURRENCE_LISTS}
        out["weekdays"] = sorted(((tuple(phrase.split()), code) for code, phrases in raw["weekdays"].items() for phrase in phrases), key=lambda item: -len(item[0]))
        _CACHE["data"] = out
    return _CACHE["data"]


def forget() -> None:
    """Drop what was read (a test, and a process that wants to read an edited file)."""
    _CACHE.clear()


def _at(tokens: list, phrase: tuple, start: int) -> bool:
    return tuple(tokens[start:start + len(phrase)]) == phrase


def _found(tokens: list, phrases: list) -> list:
    """[(start, end)] of every place a phrase of `phrases` stands in `tokens` as whole words in a row."""
    return [(i, i + len(p)) for p in phrases for i in range(len(tokens) - len(p) + 1) if _at(tokens, p, i)]


def _weekdays(tokens: list) -> list:
    """[(start, end, code, plural)] of the weekday phrases in `tokens`, longest phrase first, no two overlapping. A phrase whose last word ends in `s` is a plural ("segundas",
    "mondays"): it names a day that comes again."""
    out, taken = [], set()
    for phrase, code in _data()["weekdays"]:
        for i in range(len(tokens) - len(phrase) + 1):
            span = set(range(i, i + len(phrase)))
            if _at(tokens, phrase, i) and not span & taken:
                taken |= span
                out.append((i, i + len(phrase), code, phrase[-1].endswith("s")))
    return sorted(out)


def _led(tokens: list, begin: int, leads: list) -> bool:
    """Whether a lead phrase of `leads` ends exactly where a word starts, at `begin` ("toda" before "segunda")."""
    return any(end == begin for _start, end in _found(tokens, leads))


def _digit_after_lead(tokens: list) -> bool:
    return any(i + 1 < len(tokens) and tokens[i] in NUMBER_LEAD and tokens[i + 1].isdigit() for i in range(len(tokens)))


def mentions(text) -> bool:
    """Whether the line holds any repetition phrase (see the module's text), or the time engine says it repeats."""
    tokens = _tokens(text)
    data = _data()
    if any(_found(tokens, data[key]) for key in ("daily", "weekly_plain", "unsupported")) or _digit_after_lead(tokens):
        return True
    for begin, _end, _code, plural in _weekdays(tokens):
        if plural or _led(tokens, begin, data["weekly_lead"]):
            return True
    try:
        return bool(nt.recurring(text if isinstance(text, str) else ""))
    except Exception:      # noqa: BLE001 - an engine that cannot read the line says nothing; the closed lists above stand alone
        return False


def read(text, start_weekday):
    """The repetition the text holds, or None (see the module's text)."""
    tokens = _tokens(text)
    data = _data()
    if not tokens or not isinstance(start_weekday, int) or isinstance(start_weekday, bool) or not 0 <= start_weekday <= 6:
        return None
    if _found(tokens, data["unsupported"]) or _found(tokens, data["end"]) or _digit_after_lead(tokens) or _by_count(tokens):
        return None
    days = _weekdays(tokens)
    daily = _found(tokens, data["daily"])
    if daily:
        if days or any(end < len(tokens) and tokens[end].isdigit() for _start, end in daily):      # "todo dia 16" is the sixteenth of every month, not every day
            return None
        return {"freq": "daily"}
    if days:
        if len({code for _s, _e, code, _p in days}) != 1:
            return None
        begin, _end, code, plural = days[0]
        if not (plural or _led(tokens, begin, data["weekly_lead"])) or code != WEEKDAYS[start_weekday]:
            return None
        return {"freq": "weekly", "byday": code}
    if _found(tokens, data["weekly_plain"]):
        return {"freq": "weekly", "byday": WEEKDAYS[start_weekday]}
    return None


def _by_count(tokens: list) -> bool:
    """"por 3 semanas", "for 4 weeks": a number of days, weeks or months after por or for is an end."""
    units = ("dia", "dias", "semana", "semanas", "mes", "meses", "ano", "anos", "day", "days", "week", "weeks", "month", "months", "year", "years")
    return any(tokens[i] in ("por", "for") and tokens[i + 1].isdigit() and tokens[i + 2] in units for i in range(len(tokens) - 2))


def words(text) -> dict:
    """Which kind of cancel words the line holds (see the module's text)."""
    tokens = _tokens(text)
    data = _data()
    return {"series": bool(_found(tokens, data["series"])) or mentions(text), "occurrence": bool(_found(tokens, data["occurrence"]))}


def which(text, specific_day) -> str:
    """"series", "occurrence" or "ask" (see the module's text)."""
    said = words(text)
    if said["series"] and not said["occurrence"] and not specific_day:
        return "series"
    if (said["occurrence"] or specific_day) and not said["series"]:
        return "occurrence"
    return "ask"


def week_range(text) -> bool:
    return bool(_found(_tokens(text), _data()["week_range"]))


def _spans(text: str) -> list:
    """[(folded word, start, end)] of the words of the original text (a word is `\\w+`: "segunda-feira" is two)."""
    return [(fold(m.group()), m.start(), m.end()) for m in WORD.finditer(text)]


def strip(text) -> str:
    """The text without the words that only say it repeats (see the module's text), the other words as written, single-spaced."""
    if not isinstance(text, str):
        return ""
    spans = _spans(text)
    tokens = [word for word, _s, _e in spans]
    data = _data()
    cut = set()
    for key in ("daily", "weekly_plain"):
        for start, end in _found(tokens, data[key]):
            cut |= set(range(start, end))
    days = _weekdays(tokens)
    for lead_start, lead_end in _found(tokens, data["weekly_lead"]):
        if any(begin == lead_end for begin, _e, _c, _p in days):
            cut |= set(range(lead_start, lead_end))
    return " ".join(text[s:e] for i, (_w, s, e) in enumerate(spans) if i not in cut)


def rule_word(recurrence) -> str:
    """"daily" or "weekly:MO".."weekly:SU" for {"freq": "daily"} or {"freq": "weekly", "byday": ...}; ValueError for anything else."""
    if isinstance(recurrence, dict) and recurrence == {"freq": "daily"}:
        return "daily"
    if isinstance(recurrence, dict) and set(recurrence) == {"freq", "byday"} and recurrence["freq"] == "weekly" and recurrence["byday"] in WEEKDAYS:
        return "weekly:" + recurrence["byday"]
    raise ValueError("not a daily or a weekly repetition")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())

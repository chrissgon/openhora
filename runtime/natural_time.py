#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The time parser of natural requests (package NR-1): the time a person means in a line of their own words, as the grammar of runtime/reminders.py, with no model.

Pure: the clock is passed in (an aware datetime), nothing is read but the language tables, nothing is stored, nothing is logged. The engine holds no word of any
language. Every word it looks for (weekdays, months, "tomorrow", "in 2 hours", "13h", "9 pm", the words that introduce an hour) is data in a language table,
`runtime/natural_lang_<tag>.py` (`TABLE`), and the table of EVERY language is tried on EVERY line, so a project whose language is Portuguese still
understands an English line. The tables shipped are named in `runtime/natural_languages.json` and are read as data (`ast.literal_eval` of the `TABLE` literal,
never executed); adding a language adds a file, a name in that list and its tests, and the engine is not edited (a test plugs a stub third language in).

The rule that governs it: what is ambiguous, or not fully understood, is ASKED BACK and never guessed. So a line never gets an invented hour or an invented day,
two readings are all offered, an hour with no marker is asked, and x/y is a date only when something says it is one. When a full reading is understood and only
something about it is uncertain (a word of a week or a month within two words of the time, a day word with a typo, a dotted number beside a day, a year inferred),
`doubts` says so and the caller SHOWS the reading and asks for a "yes" (runtime/natural.py); a line that repeats (`recurring`) is a routine's, not a reminder's; a
weak word of a language (an abbreviation such as "sex" or "may") counts only when the line is in that language, and where it may be a name (it does not touch the
time or a number) the reading is confirmed, never dropped.

  find(text, languages=None)         the time phrases of a line, with no clock: {"norm", "origin", "hits", "tables", "evidence", "deadline"}; each hit has "kind",
                                     "lang" and a span; `deadline` holds the date the line states as the content of the request, not as its moment ("tomorrow at
                                     9am to renew the permit before it expires on the 15th": see `_deadlines`), which is no hit and is never cut from the text
  parse(text, now, languages=None)   what the line means, with the clock:
                                       {"when": <the grammar of reminders.resolve>, "reading": {...}, "spans": [(start, end)...]}   one clear reading
                                       {"ask": [reading...], "spans"}                                                              two or more readings (or one to confirm): ask
                                       {"missing": "time", "day": {...} | None, "spans"}                                            a day or a vague time, no hour
                                       None                                                                                          no time phrase
  doubts(text, languages=None)       (flag, typos): whether a word near the time shows it may not be fully understood, and the day words with a typo (each with the
                                     word it is one letter from); `doubt` is the flag alone
  leftover_doubt(found, trigger, tables, unknown)
                                     the guard: whether the words OUTSIDE the time phrases hold a date the engine did not read (a month, a weekday, a day word, an
                                     ordinal date, a date marker with a number, the name of a day of the year) or, when `unknown`, a word no table holds (the line may
                                     be in a language there is no table for): the caller then shows the reading and asks, never makes it
  recurring(text, languages=None)    whether the line repeats: the repeating word is part of the time phrase ("every monday", "a cada 2 horas", "daily at 9"); the
                                     same words in the reminder's own text ("weekly report", "each supplier") are text
  moment(date, clock, now)           the reading of a day and an hour the person names

  without(text, spans)               the line with those spans (of the ORIGINAL text) taken out
  normalise(text)                    (folded text, origin): lower case, no accent, no format character, and where each folded character came from
  languages() / load_languages(folder, names) / check_table(table)

What a reading is: {"when", "date": "YYYY-MM-DD", "time": "HH:MM", "rel": days from today | None, "weekday": 0 (Monday) to 6 | None, "far": the year is not
this one, "rolled": bool, "relative": "in 2h" | None, "dated": the person named the day or a length of time, "assumed_year": the year was inferred}. `when` is one of
the three forms of runtime/reminders.py (`HH:MM`, `YYYY-MM-DD HH:MM`, `in <n>m|h|d`), so `reminders.resolve` keeps every check it has (a wall time the clock skips,
a time that has passed, one minute to 366 days). `rolled` is true when a time with no day has passed today and means tomorrow's. A date the calendar does not have
(30 February) is passed on as written, for `resolve` to refuse; a date this year that has passed means next year, with `assumed_year` set and the year shown (the
caller confirms it), and today's date with an hour that has passed stays today's and is refused as past by `resolve`.

What the engine reads (all of it from the tables):

  clock, 24-hour     13h  13hs  13hrs  13 hrs  13:00  9:30  13h30  13h 30min  13.30 (with a cue)  13 e 30  13 e meia  meio-dia e meia
  clock, 12-hour     1pm  1 pm  1:30pm  9am  9 da manha  3 da tarde  noon  midnight   (meridiem, day parts, noon and midnight words)
  hour with no marker  "at 9"  "as 9" (1 to 11): two readings, 09:00 and 21:00 (also "as 3 e meia"); 12 is noon; 13 to 23 and 0 are that hour
  day                today  tomorrow  the day after tomorrow  (the words of the table)
  weekday            friday  (the same weekday is today when the time is still ahead, else in 7 days);  "next friday", "sexta que vem": the nearest and the one
                     after it are both offered
  day of the month   the 25th  day 25  (this month when it is ahead, else the next month that has the day)
  date               25 october  october 25  25/10  25/10/2026  2026-10-25   (x/y only with a cue: "on", "dia", a time beside it, and not a fraction such as
                     "installment 3/10" or "3/10 of the rent"; both numbers 12 or less in a line that is not in a "day-first" language is asked)
  in a while         in 2 hours  in 30 minutes  in 3 days  in half an hour  in 1h30  in an hour and a half  (an hour is `in <n>h`, to the minute upwards); "in 2 days
                     at 9h" is the day two days ahead at 09:00
  midnight           "friday at midnight" offers the start and the end of that day
  vague              later  this afternoon  (a day with no hour, or a vague part of the day: `missing`; no hour is ever invented)
  two phrases        two clocks, two days, a clock and a "in a while": every reading is offered (at most 4), nothing is picked

The schema of a table (`check_table`; every list holds folded words, a phrase is words separated by one space; see runtime/natural_lang_en.py):
tag, markers, slash_dates ("ask" | "day-first"), days {today, tomorrow, day_after_tomorrow}, weekdays (7 lists, Monday first), weekday_next, weekday_this,
weekday_after, months (12 lists), weak, cued, month_joiners, day_words, ordinal_prefixes, ordinal_suffixes, prefixes, hour_words_24, hour_words_long, meridiem {am,
pm} (with the forms written with dots, "a.m."), dayparts {morning, dawn, afternoon, evening, night}, vague, noon, midnight, bare_hour_prefixes, relative_in,
relative_units {m, h, d, w}, number_words {word: n}, half_hour, and_half, joiners, half_words, time_words, not_typos, recurrence, recurrence_units,
recurrence_counted_units, recurrence_phrases, recurrence_other, recurrence_not_before, recurrence_adverbs, recurrence_before_day, recurrence_joiners, week_phrases,
remind_nouns, vague_parts {morning, afternoon, evening, night}, first_words, ordinal_marks, quarter_past, quarter_to, half_past, date_markers, date_nouns, but_words,
deadline_words, fraction_before, fraction_after, date_cues, edge_words, problem_words, work_verbs, calendar_noun_reads, triggers {remind, remind_anywhere,
reminders, reminders_bare, calendar, calendar_verb, calendar_noun, calendar_loose, note, undo}, forget {verbs, nouns, fillers, id_words, id_marked}, polite, connectors, answers {yes,
notice, event, other, cancel, thanks, again}, work_starters. The trigger and answer words are read by runtime/natural.py, the time words here.

Standard library only. Runs on Python 3.9: python3 runtime/natural_time.py --help
"""
from __future__ import annotations

import ast
import calendar
import datetime
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED = "natural_languages.json"      # the names of the language files shipped, as data
MAX_READINGS = 4          # a question offers at most this many readings
RELATIVE_MAX = 9999       # the largest n of `in <n>m|h|d` (runtime/reminders.py)
_L = r"(?<![a-z0-9])"
_R = r"(?![a-z0-9])"

LISTS = ("markers", "weekday_next", "weekday_this", "weekday_after", "weak", "cued", "hour_words_long", "not_typos", "recurrence", "recurrence_before_day",
         "recurrence_joiners", "problem_words", "work_verbs", "calendar_noun_reads", "month_joiners", "day_words", "ordinal_prefixes", "ordinal_suffixes", "prefixes",
         "hour_words_24", "vague", "noon", "midnight", "bare_hour_prefixes", "relative_in", "half_hour", "and_half", "joiners", "half_words", "time_words",
         "fraction_before", "fraction_after", "date_cues", "edge_words", "polite", "connectors", "work_starters", "recurrence_units", "recurrence_adverbs",
         "recurrence_other", "recurrence_not_before", "week_phrases", "remind_nouns", "first_words", "ordinal_marks", "quarter_past", "quarter_to", "half_past",
         "date_markers", "date_nouns", "recurrence_phrases", "recurrence_counted_units", "but_words", "before_words", "topic_words", "date_after_clock", "deadline_words")
GROUPS = {"days": ("today", "tomorrow", "day_after_tomorrow"), "meridiem": ("am", "pm"), "dayparts": ("morning", "dawn", "afternoon", "evening", "night"),
          "relative_units": ("m", "h", "d", "w"),
          "triggers": ("remind", "remind_anywhere", "reminders", "reminders_bare", "calendar", "calendar_verb", "calendar_noun", "calendar_loose", "note", "undo"),
          "forget": ("verbs", "nouns", "fillers", "id_words", "id_marked"), "vague_parts": ("morning", "afternoon", "evening", "night"),
          "answers": ("yes", "notice", "event", "other", "cancel", "thanks", "again")}


def check_table(table) -> None:
    """ValueError(sentence) when `table` is not a language table of the schema in the module's text; None when it is."""
    def bad(why):
        raise ValueError(f"language table {table.get('tag') if isinstance(table, dict) else table!r}: {why}")
    if not isinstance(table, dict):
        bad("it is not a dict")
    if not isinstance(table.get("tag"), str) or not table["tag"]:
        bad("the key tag is a non-empty string")
    if table.get("slash_dates") not in ("ask", "day-first"):
        bad("slash_dates is 'ask' or 'day-first'")

    def words(value, where):
        if not isinstance(value, list) or not all(isinstance(w, str) and w == w.strip() and w == " ".join(w.split()) and w == w.lower() and w for w in value):
            bad(f"{where} is a list of lower-case phrases of single-spaced words")
        for w in value:
            if any(unicodedata.combining(c) for c in unicodedata.normalize("NFKD", w)) or not w.isascii():
                bad(f"{where}: {w!r} has an accent or a character outside ASCII (the engine folds a line before it looks)")
    for name in LISTS:
        words(table.get(name), name)
    for group, keys in GROUPS.items():
        if not isinstance(table.get(group), dict) or set(table[group]) != set(keys):
            bad(f"{group} is a dict with exactly the keys {', '.join(keys)}")
        for key in keys:
            words(table[group][key], f"{group}.{key}")
    if not isinstance(table.get("weekdays"), list) or len(table["weekdays"]) != 7:
        bad("weekdays is 7 lists, Monday first")
    for n, names in enumerate(table["weekdays"]):
        words(names, f"weekdays[{n}]")
    if not isinstance(table.get("months"), list) or len(table["months"]) != 12:
        bad("months is 12 lists, January first")
    for n, names in enumerate(table["months"]):
        words(names, f"months[{n}]")
    numbers = table.get("number_words")
    if not isinstance(numbers, dict) or not all(isinstance(k, str) and type(v) is int and 0 < v <= RELATIVE_MAX for k, v in numbers.items()):
        bad("number_words maps a word to a whole number")
    words(list(numbers), "number_words")


def _read_table(path: str):
    """The `TABLE` literal of a language file, read as data: the file is parsed, never executed."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "TABLE" for t in node.targets):
            return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "TABLE" and node.value is not None:
            return ast.literal_eval(node.value)
    raise ValueError(f"{os.path.basename(path)}: no TABLE literal")


def load_languages(folder=None, names=None) -> list:
    """The checked tables of the language files `names` (default: the list in `natural_languages.json` of `folder`, which is this folder by default), read as
    data, in that order. A file that breaks the schema, a name that is not a language file and two tables with the same tag are a ValueError with a sentence
    that says which (a language table is data under review, not something to skip silently)."""
    folder = folder or HERE
    if names is None:
        try:
            with open(os.path.join(folder, SHIPPED), encoding="utf-8") as handle:
                names = json.load(handle)["languages"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            raise ValueError(f"{SHIPPED}: the list of shipped languages cannot be read ({e.__class__.__name__})") from None
    if not isinstance(names, list) or not names:
        raise ValueError(f"{SHIPPED}: the list of shipped languages is empty or is not a list")
    out, tags = [], set()
    for name in names:
        if not isinstance(name, str) or not re.fullmatch(r"natural_lang_[a-z0-9_]+", name):
            raise ValueError(f"{SHIPPED}: {name!r} is not the name of a language file (natural_lang_<tag>)")
        try:
            table = _read_table(os.path.join(folder, name + ".py"))
        except (OSError, SyntaxError, ValueError) as e:
            raise ValueError(f"{name}.py cannot be read as a language table ({e.__class__.__name__}: {e})") from None
        check_table(table)
        if table["tag"] in tags:
            raise ValueError(f"language table {table['tag']!r}: two files have this tag")
        tags.add(table["tag"])
        out.append(table)
    return out


_default = []


def languages() -> list:
    """The tables shipped, read once. Called at the start of a bridge (a table that breaks the schema stops it there with a sentence), so a line never meets the error."""
    if not _default:
        _default.extend(load_languages())
    return _default


def normalise(text) -> tuple:
    """(folded, origin): `text` in lower case with no accent and no format character (a soft hyphen, a zero-width character), a hyphen between two letters read as
    a space; origin[i] is the index in `text` the i-th folded character came from, so that a span found in the folded text is a span of the original."""
    out, origin = [], []
    for i, ch in enumerate(text or ""):
        for c in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(c) and unicodedata.category(c) != "Cf":
                out.append(("." if out and out[-1] == "n" else "o") if c == "\u00b0" else c.lower())          # "n° 3" reads as "n. 3", "1°" as "1o" (the ordinal sign "1º" folds to "1o" itself)
                origin.append(i)
    folded = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", "".join(out))
    return folded, origin


_ALT_CACHE: dict = {}


def _alt(phrases):
    """The alternation of a list of phrases as a regular expression (the longest first), or None for an empty list. The same lists are asked again and again (every line is
    tried against every list), so the text is kept for each list of phrases."""
    key = tuple(phrases)
    if key not in _ALT_CACHE:
        items = sorted({p for p in key if p}, key=lambda p: (-len(p), p))
        _ALT_CACHE[key] = "(?:" + "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in items) + ")" if items else None
    return _ALT_CACHE[key]


def _opt(alt, tail=r"\s+"):
    return f"(?:{alt}{tail})?" if alt else ""


class _Compiled:
    """The regular expressions of one table, built once."""

    def __init__(self, table):
        self.table, self.tag = table, table["tag"]
        a = _alt
        self.maps = {"day": {}, "weekday": {}, "month": {}, "unit": {}, "noon": {}, "mer": {}, "part": {}}
        for key, rel in (("today", 0), ("tomorrow", 1), ("day_after_tomorrow", 2)):
            for p in table["days"][key]:
                self.maps["day"][p] = rel
        for index, names in enumerate(table["weekdays"]):
            for p in names:
                self.maps["weekday"][p] = index
        for index, names in enumerate(table["months"]):
            for p in names:
                self.maps["month"][p] = index + 1
        for unit, names in table["relative_units"].items():
            for p in names:
                self.maps["unit"][p] = unit
        for p in table["noon"]:
            self.maps["noon"][p] = (12, 0)
        for p in table["midnight"]:
            self.maps["noon"][p] = (0, 0)
        self.midnight = set(table["midnight"])
        for mer, names in table["meridiem"].items():
            for p in names:
                self.maps["mer"][p] = mer
        for part, names in table["dayparts"].items():
            for p in names:
                self.maps["part"][p] = part
        self.weak = set(table["weak"])
        self.cued = set(table["cued"])
        self.half = set(table["half_words"])
        days = a(sum(table["days"].values(), []))
        names = a(list(self.maps["weekday"]))
        months = a(list(self.maps["month"]))
        units = a(list(self.maps["unit"]))
        hunits = a([p for p, u in self.maps["unit"].items() if u == "h"])
        munits = a([p for p, u in self.maps["unit"].items() if u == "m"])
        nums = a(list(table["number_words"]))
        intro = a(table["relative_in"])
        hw = a(table["hour_words_24"])
        hw_all = a(table["hour_words_24"] + table["hour_words_long"])
        mer = a(list(self.maps["mer"]))
        parts = a(list(self.maps["part"]))
        dayw = a(table["day_words"])
        ordp = a(table["ordinal_prefixes"])
        suffix = a(table["ordinal_suffixes"])
        joiners = a(table["joiners"])
        halfw = a(table["half_words"])
        after = a(table["weekday_after"])
        modifiers = a(table["weekday_next"] + table["weekday_this"])
        modifier = "(?:(?P<mod>" + modifiers + r")\s+)?" if modifiers else ""
        after_part = r"(?:\s+(?P<after>" + after + "))?" if after else ""
        short = hw
        long = a(table["hour_words_long"])
        mnum = "[0-9]{2}" + ("|" + halfw if halfw else "")
        jmin = (r"(?:\s+" + joiners + r"\s+(?P<m>" + mnum + "))?") if joiners else ""
        num_h = "(?P<h>[0-9]{1,4}|" + nums + ")" if nums else "(?P<h>[0-9]{1,4})"
        self.prefix = a(table["prefixes"])
        self.and_half = re.compile(f"{_L}(?P<intro>{intro})\\s+{num_h}\\s*(?P<hu>{hunits})(?![a-z])\\s+{a(table['and_half'])}{_R}") \
            if intro and hunits and table["and_half"] else None
        jopt = (r"(?P<j>" + joiners + r"\s*)?") if joiners else ""
        mopt = (r"\s*(?P<mu>" + munits + ")?") if munits else ""
        self.compound = re.compile(f"{_L}(?P<intro>{intro})\\s+{num_h}\\s*(?P<hu>{hunits})(?![a-z])(?P<gap>\\s*){jopt}(?P<m>[0-9]{{1,2}}){mopt}(?![a-z0-9])") \
            if intro and hunits else None
        self.relative = re.compile(f"{_L}(?P<intro>{intro})\\s+(?P<num>[0-9]{{1,4}}|{nums})\\s*(?P<unit>{units}){_R}(?!\\s*[0-9])") if intro and units and nums else None
        self.half_hour = re.compile(f"{_L}(?P<intro>{intro})\\s+{a(table['half_hour'])}{_R}") if intro and table["half_hour"] else None
        lead = _opt(a([w for w in (table["day_words"] + table["ordinal_prefixes"]) if w]))
        marks = a(table["ordinal_suffixes"] + table["ordinal_marks"])
        self.monthday1 = re.compile(f"{_L}{lead}(?P<d>[0-9]{{1,2}}){('(?:' + marks + ')?') if marks else ''}\\s+{_opt(a(table['month_joiners']))}(?P<mon>{months}){_R}") \
            if months else None
        self.monthday2 = re.compile(f"{_L}(?P<mon>{months})\\s+(?P<d>[0-9]{{1,2}}){('(?:' + suffix + ')?') if suffix else ''}(?![a-z0-9:/])") if months else None
        self.dayno1 = re.compile(f"{_L}{dayw}\\s+(?P<d>[0-9]{{1,2}}){('(?:' + marks + ')?') if marks else ''}(?![a-z0-9:/])") if dayw else None
        self.dayno2 = re.compile(f"{_L}{_opt(ordp)}(?P<d>[0-9]{{1,2}}){suffix}(?![a-z0-9:/])") if suffix else None
        self.day = re.compile(f"{_L}(?P<w>{days}){_R}") if days else None
        self.weekday = re.compile(f"{_L}{modifier}(?P<name>{names}){after_part}{_R}") if names else None
        self.nxt = set(table["weekday_next"])
        self.daypart = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})(?::(?P<m1>[0-9]{{2}})" + (f"|\\s*{hw_all}(?:(?P<m2>[0-9]{{2}}))?" if hw_all else "") +
                                  (r"|\s+" + joiners + r"\s+(?P<m3>" + mnum + ")" if joiners else "") + f")?\\s+(?P<part>{parts}){_R}") if parts else None
        before = a(table["before_words"])
        mh = a([p for p, u in self.maps["unit"].items() if u in ("m", "h")])
        halfh = a(table["half_hour"])
        self.offset = re.compile(f"{_L}(?:(?P<n>[0-9]{{1,3}}|{nums})\\s*(?P<unit>{mh})|(?P<half>{halfh}))\\s+(?P<b>{before}){_R}") if before and mh and nums and halfh else None
        self.topic = re.compile(f"(?<![a-z0-9])(?:{a(table['topic_words'])})\\s+$") if table["topic_words"] else None
        self.qmap = {p: ("past", 15) for p in table["quarter_past"]}
        self.qmap.update({p: ("to", 45) for p in table["quarter_to"]})
        self.qmap.update({p: ("past", 30) for p in table["half_past"]})
        quarters = a(list(self.qmap))
        self.quarter = re.compile(f"{_L}(?P<q>{quarters})\\s+(?P<h>[0-9]{{1,2}})(?:\\s*(?P<mer>{mer}))?{_R}(?![:.][0-9])") if quarters and mer is not None else None
        colon_tail = (f"(?:\\s*(?P<mer>{mer})|{hw}(?![a-z]))?" if mer and hw else f"(?:\\s*(?P<mer>{mer}))?" if mer else f"(?:{hw}(?![a-z]))?" if hw else "")
        self.colon = re.compile(f"{_L}(?P<h>[0-9]{{1,2}}):(?P<m>[0-9]{{2}})" + colon_tail + "(?![a-z0-9:])")
        mu_opt = (r"(?:\s*" + munits + "(?![a-z0-9]))?") if munits else ""
        m2_part = r"|\s+(?P<m2>[0-9]{2})(?![0-9/:.])" + ((r"(?:\s*" + munits + "(?![a-z0-9]))?") if munits else "")
        m3_part = (r"|\s+" + joiners + r"\s+(?P<m3>" + mnum + r")(?!\s*" + short + "(?![a-z]))") if joiners and short else ((r"|\s+" + joiners + r"\s+(?P<m3>" + mnum + ")") if joiners else "")
        self.hw = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})\\s*{short}(?![a-z])(?:(?P<m>[0-9]{{2}})(?![0-9]){mu_opt}{m2_part}{m3_part})?(?![0-9])(?!\\s+[0-9])") if short else None
        self.dotted = re.compile(f"(?<![a-z0-9.,])(?P<h>[0-9]{{1,2}})\\.(?P<m>[0-9]{{2}})" + (f"(?:\\s*(?P<mer>{mer}))?" if mer else "") + "(?![0-9]|[.,][0-9])")
        self.mer = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})\\s*(?P<mer>{mer}){_R}") if mer else None
        special = a(list(self.maps["noon"]))
        jmin_special = (r"(?:\s+" + joiners + r"\s+(?P<m>" + mnum + "))?") if joiners else ""
        self.special = re.compile(f"{_L}(?P<w>{special}){jmin_special}{_R}") if special else None
        bare = a(table["bare_hour_prefixes"])
        long_part = (r"(?:\s+" + long + ")?") if long else ""
        spoken_hours = a([w for w, v in table["number_words"].items() if 2 <= v <= 23 and len(w) >= 3])
        hour_digits = "[0-9]{1,2}" + (f"|{spoken_hours}" if spoken_hours else "")
        self.bare = re.compile(f"{_L}(?P<p>{bare})\\s+(?P<h>{hour_digits}){long_part}{jmin}(?![a-z0-9:/]|[.,][0-9]|\\s+[0-9])") if bare else None
        vague = a(table["vague"])
        self.vague = re.compile(f"{_L}(?P<w>{vague}){_R}") if vague else None
        self.vparts = {p: part for part, names in table["vague_parts"].items() for p in names}


_compiled = {}


def _comp(table) -> "_Compiled":
    found = _compiled.get(id(table))
    if found is None or found.table is not table:
        found = _compiled[id(table)] = _Compiled(table)
    return found


def _word(text) -> str:
    return " ".join(text.split())


def _num(c, text):
    return int(text) if text.isdigit() else c.table["number_words"].get(_word(text))


def _meridiem(h, mer):
    if not 1 <= h <= 12:
        return None
    return (h % 12) + (12 if mer == "pm" else 0)


def _part_hours(h, part):
    """The 24-hour readings of an hour said with a part of the day ("9 in the morning"), or None when the pair means nothing."""
    if part == "morning":
        return [h] if 1 <= h <= 11 else None
    if part == "dawn":
        return [h] if 1 <= h <= 6 else None
    if part == "afternoon":
        return [h + 12] if 1 <= h <= 11 else ([12] if h == 12 else None)
    if part == "evening":
        return [h + 12] if 5 <= h <= 11 else None
    if part == "night":
        return [h + 12] if 6 <= h <= 11 else ([0] if h == 12 else None)
    return None


def _duration(total: int, unit: str = "m") -> dict:
    return {"kind": "relative", "when": f"in {total}m", "delta": datetime.timedelta(minutes=total), "unit": "m", "days": 0}


def _scan(work: str, tables: list) -> list:
    """Every time phrase of the folded line, stage by stage (a phrase found by a stage is hidden from the later ones, so that "2 hours" in "in 2 hours" is not a
    clock), in all the languages. Returns the hits, each {"kind", "s", "e", "lang", ...}."""
    hits = []
    compiled = [_comp(t) for t in tables]

    def run(patterns, accept):
        """One stage: gather the matches of every language, the longest first, keep those that do not overlap, hide them."""
        nonlocal work
        found = []
        for lang, pattern in patterns:
            for m in pattern.finditer(work):
                hit = accept(lang, m)
                if hit:
                    hit.update(s=m.start(), e=m.end(), s0=m.start(), lang=lang.tag if lang is not None else None)
                    found.append(hit)
        found.sort(key=lambda h: (-(h["e"] - h["s"]), h["s"]))
        taken = []
        for hit in found:
            if any(hit["s"] < t["e"] and t["s"] < hit["e"] for t in taken):
                continue
            taken.append(hit)
        for hit in taken:
            work = work[:hit["s"]] + " " * (hit["e"] - hit["s"]) + work[hit["e"]:]
        hits.extend(taken)

    def per(attr, accept):
        run([(c, getattr(c, attr)) for c in compiled if getattr(c, attr) is not None], accept)

    iso = re.compile(r"(?<![0-9-])([0-9]{4})-([0-9]{2})-([0-9]{2})(?![0-9-])")
    run([(None, iso)], lambda c, m: {"kind": "date", "spec": {"k": "ymd", "y": int(m.group(1)), "m": int(m.group(2)), "d": int(m.group(3))}})
    slash = re.compile(r"(?<![0-9/])([0-9]{1,2})/([0-9]{1,2})(?:/([0-9]{4}|[0-9]{2}))?(?![0-9/])")
    run([(None, slash)], lambda c, m: {"kind": "slash", "a": int(m.group(1)), "b": int(m.group(2)), "y": int(m.group(3)) if m.group(3) else None})

    def dotted(c, m):
        h, minute, mer = int(m.group("h")), int(m.group("m")), m.groupdict().get("mer")
        if minute > 59:
            return None
        if mer:
            h = _meridiem(h, c.maps["mer"][_word(mer)])
        return {"kind": "clock", "times": [(h, minute)], "bare": False, "dotted": True, "explicit": bool(mer)} if h is not None and h <= 23 else None
    per("dotted", dotted)

    def and_half(c, m):
        n = _num(c, m.group("h"))
        return _duration(n * 60 + 30) if n and n * 60 + 30 <= RELATIVE_MAX else None
    per("and_half", and_half)

    def compound(c, m):
        n, minutes = _num(c, m.group("h")), int(m.group("m"))
        gap, joined, unit = m.group("gap"), ("j" in m.groupdict() and m.group("j")), ("mu" in m.groupdict() and m.group("mu"))
        if not n or minutes > 59 or ((gap or joined) and not (joined or unit)):
            return None
        return _duration(n * 60 + minutes) if n * 60 + minutes <= RELATIVE_MAX else None
    per("compound", compound)
    per("half_hour", lambda c, m: _duration(30))

    def relative(c, m):
        n = _num(c, m.group("num"))
        unit = c.maps["unit"].get(_word(m.group("unit")))
        if not n or not unit or n * (7 if unit == "w" else 1) > RELATIVE_MAX:
            return None
        n, unit = (n * 7, "d") if unit == "w" else (n, unit)
        return {"kind": "relative", "when": f"in {n}{unit}", "unit": unit, "days": n if unit == "d" else 0,
                "delta": datetime.timedelta(minutes=n) if unit == "m" else datetime.timedelta(hours=n) if unit == "h" else datetime.timedelta(days=n)}
    per("relative", relative)

    def monthday(c, m):
        phrase = _word(m.group("mon"))
        month = c.maps["month"].get(phrase)
        d = int(m.group("d"))
        return {"kind": "date", "spec": {"k": "md", "m": month, "d": d}, "weak": phrase in c.weak, "cued": phrase in c.cued, "name_s": m.start("mon")} if month else None
    per("monthday1", monthday)
    per("monthday2", monthday)
    def dayno(c, m):
        d = int(m.group("d"))
        return {"kind": "date", "spec": {"k": "monthday", "d": d} if 1 <= d <= 31 else {"k": "bad", "d": d}}          # "dia 32": kept as written, for `resolve` to refuse
    per("dayno1", dayno)
    per("dayno2", dayno)
    per("day", lambda c, m: {"kind": "date", "spec": {"k": "rel", "n": c.maps["day"][_word(m.group("w"))]}})

    def weekday(c, m):
        groups = m.groupdict()
        phrase = _word(m.group("name"))
        mod = groups.get("mod")
        two = bool(groups.get("after")) or (bool(mod) and _word(mod) in c.nxt)
        topic = bool(c.topic and c.topic.search(work[:m.start()])) or work[m.end():m.end() + 2] == "'s"
        return {"kind": "date", "spec": {"k": "wd", "i": c.maps["weekday"][phrase], "next": two, "two": two, "mod": bool(mod)}, "weak": phrase in c.weak, "name_s": m.start("name"),
                "topic": topic}
    per("weekday", weekday)

    def daypart(c, m):
        groups = m.groupdict()
        spoken = groups.get("m3")
        minute = (30 if spoken and _word(spoken) in c.half else int(spoken)) if spoken else int(groups.get("m1") or groups.get("m2") or 0)
        hours = _part_hours(int(m.group("h")), c.maps["part"][_word(m.group("part"))])
        return {"kind": "clock", "times": [(h, minute) for h in hours], "bare": False} if hours and minute <= 59 else None
    per("daypart", daypart)

    def offset(c, m):
        if m.group("half"):
            return {"kind": "offset", "delta": datetime.timedelta(minutes=30)}
        n, unit = _num(c, m.group("n")), c.maps["unit"].get(_word(m.group("unit")))
        if not n or not unit:
            return None
        return {"kind": "offset", "delta": datetime.timedelta(minutes=n) if unit == "m" else datetime.timedelta(hours=n)}
    per("offset", offset)

    def quarter(c, m):
        way, minute = c.qmap[_word(m.group("q"))]
        h, mer = int(m.group("h")), m.groupdict().get("mer")
        if mer:
            base = _meridiem(h, c.maps["mer"][_word(mer)])
            hours = [base] if base is not None else []
        else:
            hours = [h, h + 12] if 1 <= h <= 11 else ([h] if h <= 23 else [])
        if way == "to":
            hours = [(x - 1) % 24 for x in hours]
        return {"kind": "clock", "times": [(x, minute) for x in hours], "bare": len(hours) > 1} if hours else None
    per("quarter", quarter)

    def colon(c, m):
        h, minute, mer = int(m.group("h")), int(m.group("m")), m.groupdict().get("mer")
        if minute > 59:
            return None
        if mer:
            h = _meridiem(h, c.maps["mer"][_word(mer)])
        return {"kind": "clock", "times": [(h, minute)], "bare": False} if h is not None and h <= 23 else None
    per("colon", colon)

    def hw(c, m):
        groups = m.groupdict()
        h = int(m.group("h"))
        text = groups.get("m") or groups.get("m2") or groups.get("m3")
        minute = (30 if _word(text) in c.half else int(text)) if text else 0
        if h > 23 or minute > 59:
            return None
        hit = {"kind": "clock", "times": [(h, minute)], "bare": False}
        if text and text.isdigit() and 1 <= h <= 5:          # "1h30": 01:30, or a length of time
            hit["alt"] = _duration(h * 60 + minute)
        return hit
    per("hw", hw)

    def meridiem(c, m):
        h = _meridiem(int(m.group("h")), c.maps["mer"][_word(m.group("mer"))])
        return {"kind": "clock", "times": [(h, 0)], "bare": False} if h is not None else None
    per("mer", meridiem)

    def special(c, m):
        phrase = _word(m.group("w"))
        h, minute = c.maps["noon"][phrase]
        text = m.groupdict().get("m")
        if text:
            minute = 30 if _word(text) in c.half else int(text)
        if minute > 59:
            return None
        return {"kind": "clock", "times": [(h, minute)], "bare": False, "midnight": phrase in c.midnight and minute == 0}
    per("special", special)

    def bare(c, m):
        spoken = m.group("h")
        h = int(spoken) if spoken.isdigit() else c.table["number_words"][_word(spoken)]
        text = m.groupdict().get("m")
        minute = (30 if _word(text) in c.half else int(text)) if text else 0
        if h > 23 or minute > 59:
            return None
        times = [(h, minute), (h + 12, minute)] if 1 <= h <= 11 else [(h, minute)]
        return {"kind": "clock", "times": times, "bare": len(times) > 1}
    per("bare", bare)
    per("vague", lambda c, m: {"kind": "vague", "part": c.vparts.get(_word(m.group("w")))})
    return hits


def _extend(norm: str, hits: list, tables: list) -> None:
    """Take one connector that stands just before a phrase ("at 13h", "on friday", "para amanha") into the phrase: it goes with it when the words are taken out.
    A phrase that took one has a `cue`."""
    prefixes = _alt(sorted({p for t in tables for p in t["prefixes"]}))
    if not prefixes:
        return
    tail = re.compile(f"(?<![a-z0-9])({prefixes})\\s+$")
    ordered = sorted(hits, key=lambda h: h["s"])
    for n, hit in enumerate(ordered):
        if hit["kind"] in ("vague",) or hit.get("bare"):
            continue
        floor = max([h["e"] for h in ordered[:n]] or [0])
        m = tail.search(norm[floor:hit["s"]])
        if m:
            hit["s"] = floor + m.start(1)
            hit["cue"] = True


def _neighbours(norm: str, hit: dict) -> tuple:
    """(the word before, the word after) a hit, folded."""
    before = re.findall(r"[a-z0-9]+", norm[:hit["s0"]])
    after = re.findall(r"[a-z0-9]+", norm[hit["e"]:])
    return (before[-1] if before else ""), (after[0] if after else "")


def _twin(hit: dict, text: str, origin: list) -> bool:
    """Whether a weak word was written as the start of a name: capitalised and followed by another capitalised word ("Sex Shop"), or capitalised in the middle of a
    sentence with nothing beside it to make it a day."""
    at = origin[hit["name_s"]] if hit.get("name_s") is not None and hit["name_s"] < len(origin) else None
    if at is None or not text[at:at + 1].isupper():
        return False
    return bool(re.match(r"[A-Za-z\u00c0-\u024f]+\s+([A-Z\u00c0-\u00de])", text[at:]))


def _anchored(hit: dict, hits: list, norm: str) -> bool:
    """Whether a weak word of a day stands where a day stands: touching another time phrase ("Fri at 9am", "Seg as 9h") or beside a number. A weak word
    anywhere else ("sex shop as 9h", "Dr. Mon called") may be a name: it is never dropped, the reading is confirmed (D1)."""
    before, after = _neighbours(norm, hit)
    if before.isdigit() or after.isdigit():
        return True
    for other in hits:
        if other is hit or other["kind"] == "vague":
            continue
        if other["s"] >= hit["e"] and not norm[hit["e"]:other["s"]].strip(" .,;:-"):
            return True
        if other["e"] <= hit["s"] and not norm[other["e"]:hit["s"]].strip(" .,;:-"):
            return True
    return False


def _keep(hit: dict, hits: list, norm: str, text: str, origin: list, tables: list, evidence: set) -> bool:
    """Whether a hit counts: a weak word only in a line of its own language (and confirmed, never dropped, where it may be a name), a month that is also a common word only after a cue; a dotted
    time (13.30) with its meridiem, a cue ("at 13.30") or a day beside it (then `doubt`: it is confirmed), and never beside money; x/y only as a date."""
    if hit.get("weak"):
        if hit["lang"] not in evidence:
            return False
        if hit["spec"].get("k") != "md" and (not _anchored(hit, hits, norm) or _twin(hit, text, origin)):          # a month has its day number beside it: it is a date
            return False          # no date: the word stays in the reminder's words, and `leftover_doubt` makes the reading a confirmation
    before, after = _neighbours(norm, hit)
    if hit.get("cued") and not (hit.get("cue") or any(before in t["date_cues"] for t in tables)):
        hit["doubt"] = True          # "May 5" with no cue: read as the date, and shown
    if hit.get("dotted"):
        if hit.get("explicit"):
            return True
        if re.search(r"[$\u20ac\u00a3]", norm) or any(h is not hit and h["kind"] == "clock" and not h.get("dotted") for h in hits):
            return False
        if hit.get("cue"):
            return True
        beside = any(h is not hit and h["kind"] in ("date", "slash", "relative") and (
            (h["e"] <= hit["s0"] and not norm[h["e"]:hit["s0"]].strip()) or (hit["e"] <= h["s0"] and not norm[hit["e"]:h["s0"]].strip())) for h in hits)
        hit["doubt"] = beside                                  # "tomorrow 13.30": a day beside it, but no "at": confirmed, never silent
        return beside
    if hit["kind"] == "slash":
        a, b, year = hit["a"], hit["b"], hit["y"]
        joiners = {j for t in tables for j in t["date_after_clock"]}
        after_clock = any(h["kind"] == "clock" and norm[h["e"]:hit["s0"]].strip() in joiners for h in hits)          # "9h de 12/12": a date after the hour
        if any(before in t["fraction_before"] or (after in t["fraction_after"] and not after_clock) for t in tables) and year is None:
            return False
        return bool(year is not None or hit.get("cue") or any(before in t["date_cues"] for t in tables) or any(h["kind"] == "clock" for h in hits))
    return True


def _numerals(norm: str, tables: list) -> str:
    """The folded line with an ordinal word read as the number 1 where a date stands ("primeiro de dezembro", "dia primeiro", "the first of may"), the same length."""
    for t in tables:
        first, joiners, months, dayw = _alt(t["first_words"]), _alt(t["month_joiners"]), _alt([p for names in t["months"] for p in names]), _alt([w for w in t["day_words"] if w])
        if not first or not months:
            continue
        j = f"(?:{joiners}\\s+)?" if joiners else ""
        norm = re.sub(f"{_L}(?P<w>{first})(?P<post>\\s+{j}{months}{_R})", lambda m: "1" + " " * (len(m.group("w")) - 1) + m.group("post"), norm)
        if dayw:
            norm = re.sub(f"(?P<pre>{_L}{dayw}\\s+)(?P<w>{first}){_R}", lambda m: m.group("pre") + "1" + " " * (len(m.group("w")) - 1), norm)
    return norm


def find(text, languages=None) -> dict:
    """The time phrases of the line, with no clock: {"norm", "origin", "hits", "tables", "evidence", "deadline"}. Each hit is {"kind": "clock" | "date" | "slash" | "relative" | "vague",
    "s", "e" (in the folded text), "lang", ...}. `languages` replaces the tables shipped (a test's stub language)."""
    tables = languages if languages is not None else globals()["languages"]()
    norm, origin = normalise(text)
    norm = _numerals(norm, tables)
    hits = _scan(norm, tables)
    _extend(norm, hits, tables)
    tokens = set(re.findall(r"[a-z0-9]+", norm))
    evidence = {h["lang"] for h in hits if h.get("lang") and not h.get("weak")} | {t["tag"] for t in tables if tokens & set(t["markers"])}
    kept = [h for h in hits if _keep(h, hits, norm, text if isinstance(text, str) else "", origin, tables, evidence)]
    kept, deadline = _deadlines(norm, sorted(kept, key=lambda h: h["s"]), tables)
    return {"norm": norm, "origin": origin, "hits": kept, "tables": tables, "evidence": evidence, "deadline": deadline}


def _deadlines(norm: str, hits: list, tables: list) -> tuple:
    """(kept, deadline): the hits split so that a date the line states as the CONTENT of the request, not as its moment ("renew the permit before it expires on the
    15th", "que vence dia 15"), is set apart. A hit is a deadline when all of these hold: it is a date or a slash date; one of the two words right before it is a
    deadline word of some table (`deadline_words`); another date, slash date or relative hit ends before it starts (the moment comes first); the line has a clock
    hit other than it; and no clock hit starts at or after its end (a clock after the date may be the deadline's own hour, "due on the 15th at 3pm": nothing is set
    apart). Every other hit is kept, so `parse`, `doubts` and the cuts see only the moment; the deadline's words stay in the text of the request, never cut."""
    words = {w for t in tables for w in t.get("deadline_words", [])}
    if not words:
        return hits, []
    kept, deadline = [], []
    for h in hits:
        before = re.findall(r"[a-z0-9]+", norm[:h["s"]])[-2:]
        if (h["kind"] in ("date", "slash") and any(w in words for w in before)
                and any(g is not h and g["kind"] in ("date", "slash", "relative") and g["e"] <= h["s"] for g in hits)
                and any(g is not h and g["kind"] == "clock" for g in hits)
                and not any(g["kind"] == "clock" and g["s"] >= h["e"] for g in hits)):
            deadline.append(h)
        else:
            kept.append(h)
    return kept, deadline


def _spans(found: dict) -> list:
    """The spans of the original text the hits take, adjacent or touching ones joined."""
    origin, out = found["origin"], []
    for hit in found["hits"]:
        out.append((origin[hit["s"]], origin[hit["e"] - 1] + 1))
    out.sort()
    merged = []
    for s, e in out:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    return merged


def without(text: str, spans) -> str:
    """`text` with the spans (of its own characters) taken out; each cut leaves one space."""
    out, at = [], 0
    for s, e in sorted(spans):
        out.append(text[at:s])
        at = e
    out.append(text[at:])
    return " ".join(" ".join(out).split())


def _distance_one(a: str, b: str) -> bool:
    """Whether two words differ by one letter added, dropped, changed or two neighbours swapped."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long = (a, b) if len(a) < len(b) else (b, a)
    return any(long[:i] + long[i + 1:] == short for i in range(len(long)))


def _tokens(norm: str) -> list:
    return [(m.group(), m.start(), m.end()) for m in re.finditer(r"[a-z0-9]+", norm)]


def doubt(text, languages=None) -> bool:
    """Whether `doubts` finds anything."""
    return bool(doubts(text, languages)[0])


def doubts(text, languages=None) -> tuple:
    """Whether the line leaves, within two words of the time it understood, a word that shows the time may not be fully understood: a word of a week, a month or a
    year ("next week", "semana que vem"), or a word one letter away from a day word ("amnha", "tomorow") that is not a word of its own (the tables' `not_typos`).
    The reading is then shown and confirmed, never made silently and never replaced by an open question."""
    found = find(text, languages)
    tables, hits = found["tables"], found["hits"]
    tokens = _tokens(found["norm"])
    anchors = [n for n, (_t, start, end) in enumerate(tokens) if any(h["s"] <= start and end <= h["e"] for h in hits)]
    if not anchors:
        return False, []

    def near(first, last):
        return any((first - a - 1 if a < first else a - last - 1) <= 2 for a in anchors if a < first or a > last)
    outside = [n not in anchors for n in range(len(tokens))]
    words = [t[0] for t in tokens]
    for table in tables:
        for phrase in table["time_words"]:
            parts = phrase.split()
            for n in range(len(words) - len(parts) + 1):
                if words[n:n + len(parts)] == parts and all(outside[n:n + len(parts)]) and near(n, n + len(parts) - 1):
                    return True, []
    canon = {}          # a day word of the tables (one word, five letters or more) -> the first word of its list: the word a typo of it was meant as
    for t in tables:
        for names in list(t["days"].values()) + t["weekdays"] + t["months"]:
            for p in names:
                if " " not in p and len(p) >= 5:
                    canon.setdefault(p, names[0] if " " not in names[0] else p)
    commons = {w for t in tables for w in t["not_typos"]}
    text_original = text if isinstance(text, str) else ""
    origin = found["origin"]

    def named(n):          # a capitalised word in the middle of a line is a name, never a typo of a day
        at = origin[tokens[n][1]] if tokens[n][1] < len(origin) else 0
        return text_original[at:at + 1].isupper() and bool(text_original[:at].strip())
    own = known_words(tables)          # a word that some table holds ("todas", "mas") is a word, never a typo of a day
    typos = [n for n in range(len(words)) if outside[n] and len(words[n]) >= 5 and words[n] not in commons and words[n] not in canon and words[n].rstrip("s") not in canon
             and words[n] not in own and not named(n) and near(n, n) and any(_distance_one(words[n], k) for k in canon)]
    spans = []
    for n in typos:
        close = {canon[k] for k in canon if _distance_one(words[n], k)}
        spans.append((origin[tokens[n][1]], origin[tokens[n][2] - 1] + 1, next(iter(close)) if len(close) == 1 else ""))          # the day word the person meant, when one word is that close
    return bool(typos), spans


_known_cache = {}


def _flat(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _flat(k)
            yield from _flat(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _flat(v)


def known_words(tables: list) -> set:
    """Every word that any shipped table holds, in any list (a trigger, a connector, a day, a unit, a verb): the words the engine can place."""
    key = tuple(id(t) for t in tables)
    found = _known_cache.get(key)
    if found is None:
        found = {w for t in tables for s in _flat({k: v for k, v in t.items() if k != "tag"}) for w in s.split()}
        _known_cache.clear()
        _known_cache[key] = found
    return found


def leftover_doubt(found: dict, trigger, tables: list, unknown: bool) -> bool:
    """The guard: whether what the line says OUTSIDE the time phrases it read may be a date it did not read, so that the reading is shown and confirmed, never made.
    True when the leftover holds (a) a month, a weekday, a day word ("tomorrow"), an ordinal date ("5th", "1o") or a date marker with a number beside it ("dia 5", "on 5") of
    any shipped table, (c) the name of a day of the year from a table's list ("Natal", "Christmas"), or (b), when `unknown`, a word that no shipped table holds (the line may be
    in a language there is no table for: "manana a las 15:00", "vendredi a 21h30"). `trigger` is the span, in the folded text, of the trigger words already taken out."""
    norm, hits = found["norm"], found["hits"]
    tokens = _tokens(norm)
    covered = [(h["s"], h["e"]) for h in hits + found.get("deadline", [])] + ([tuple(trigger)] if trigger else [])          # a deadline was read by code: it is not an unread date
    left = [(w, s, e) for w, s, e in tokens if not any(a <= s and e <= b for a, b in covered)]
    words = [w for w, _s, _e in left]
    date_words, markers, nouns, firsts = set(), set(), [], set()
    for t in tables:
        at_home = t["tag"] in found.get("evidence", set())
        for names in list(t["days"].values()) + t["weekdays"] + t["months"]:
            date_words.update(p for p in names if " " not in p and (at_home or p not in t["weak"]))          # an abbreviation counts where its language is the line's
        date_words.update(p.split()[0] for names in t["weekdays"] for p in names if at_home or p.split()[0] not in t["weak"])
        markers.update(t["date_markers"])
        firsts.update(t["first_words"])
        nouns.extend(p.split() for p in t["date_nouns"])
    if any(w in date_words or w in firsts or re.fullmatch(r"[0-9]{1,2}(?:st|nd|rd|th|o)", w) for w in words):
        return True
    digits = {n for n, (w, _s, _e) in enumerate(tokens) if w.isdigit()}
    leftover_positions = {(s, e) for _w, s, e in left}
    for n, (w, s, e) in enumerate(tokens):
        if w in markers and (s, e) in leftover_positions and any(m in digits and (tokens[m][1], tokens[m][2]) in leftover_positions for m in (n - 1, n + 1)):
            return True
    for phrase in nouns:
        if phrase and any(words[i:i + len(phrase)] == phrase for i in range(len(words))):
            return True
    if unknown:
        known = known_words(tables)
        if any(len(w) >= 3 and w.isalpha() and w not in known for w in words):
            return True
    return False


def _phrase_at(words: list, n: int, phrases: list):
    """The length, in words, of the longest phrase of `phrases` that the folded words hold at index n, or 0."""
    best = 0
    for phrase in phrases:
        parts = phrase.split()
        if parts and words[n:n + len(parts)] == parts and len(parts) > best:
            best = len(parts)
    return best


def recurring(text, languages=None) -> bool:
    """Whether the line repeats: a reminder here is one-time, a routine repeats. It repeats only when the word is part of the time phrase: an opener ("every",
    "toda", "a cada") followed by a length of time or a weekday ("every monday", "a cada 2 horas", "toda segunda", "todo dia as 9h"); an adverb ("daily",
    "semanalmente") right beside the time or at the edge of the words ("daily at 9", "remind me weekly to ..."); a number twice ("de 8 em 8 horas"). The same words
    in the reminder's own text ("weekly report", "each supplier", "every client", "a cada um", "todo dia da planilha") are text."""
    tables = languages if languages is not None else globals()["languages"]()
    found = find(text, tables)
    norm, hits = found["norm"], found["hits"]
    tokens = _tokens(norm)
    words = [t[0] for t in tokens]
    touches = lambda a, b: any((h["s"] >= b and not norm[b:h["s"]].strip()) or (h["e"] <= a and not norm[h["e"]:a].strip()) for h in hits)      # noqa: E731
    for t in tables:
        alt = _alt(t["recurrence_joiners"])
        if alt and re.search(f"{_L}([0-9]+)\\s+{alt}\\s+\\1{_R}", norm):
            return True
        plurals = {p + "s" for names in t["weekdays"] for p in names if " " not in p and len(p) >= 5}
        if plurals & set(words):
            return True          # "toda segunda", "nas segundas", "on mondays": all of them
        units = set(t["recurrence_units"]) | {w for names in t["weekdays"] for p in names for w in p.split()[:1]}
        counted = {w for names in t["relative_units"].values() for p in names for w in p.split()[:1] if len(w) > 1} | set(t["recurrence_counted_units"])
        numbers = set(t["number_words"])
        for n in range(len(words)):
            if _phrase_at(words, n, t["recurrence_phrases"]):
                return True
            size = _phrase_at(words, n, t["recurrence"])
            if size:
                j = n + size
                if j < len(words) and words[j] in t["recurrence_other"]:
                    j += 1
                counting = False
                if j < len(words) and (words[j].isdigit() or words[j] in numbers):
                    j += 1
                    counting = True
                if j < len(words) and (words[j] in units or (counting and words[j] in counted) or any(words[j:j + len(p.split())] == p.split() for p in t["recurrence_units"])):
                    after = words[j + 1] if j + 1 < len(words) else ""
                    if after not in t["recurrence_not_before"] or touches(tokens[n][1], tokens[j][2]):
                        return True
            size = _phrase_at(words, n, t["recurrence_adverbs"])
            if size:
                last = n + size - 1
                after = words[last + 1] if last + 1 < len(words) else ""
                if touches(tokens[n][1], tokens[last][2]) or not after or after in t["edge_words"] or after in t["connectors"]:
                    return True
        before = set(t["recurrence_before_day"])
        for hit in hits:
            if hit["kind"] == "date" and hit["spec"]["k"] in ("wd", "rel", "monthday") and before:
                tail = re.findall(r"[a-z0-9]+", norm[:hit["s0"]])
                if tail and tail[-1] in before:
                    return True
    return False


def _score(found: dict) -> dict:
    tokens = re.findall(r"[a-z0-9]+", found["norm"])
    return {t["tag"]: sum(1 for w in tokens if w in set(t["markers"])) + sum(1 for h in found["hits"] if h.get("lang") == t["tag"]) for t in found["tables"]}


def _ask_mode(found: dict) -> bool:
    """Whether an x/y date with both numbers 12 or less is asked back: the line's other words are those of a language whose table says "ask" and none are
    those of a "day-first" one."""
    score = _score(found)
    day_first = [score[t["tag"]] for t in found["tables"] if t["slash_dates"] == "day-first"]
    ask = [score[t["tag"]] for t in found["tables"] if t["slash_dates"] == "ask"]
    return bool(ask) and max(ask) > 0 and (not day_first or max(day_first) == 0)


def _specs(hit: dict, ask_mode: bool) -> list:
    if hit["kind"] == "date":
        spec = hit["spec"]
        if spec["k"] == "wd" and spec.get("two"):          # "next friday", "sexta que vem": the nearest one and the one after it
            return [{**spec, "two": False, "plus": 0}, {**spec, "two": False, "plus": 7}]
        return [spec]
    a, b, y = hit["a"], hit["b"], hit["y"]
    year = None if y is None else (y if y >= 100 else 2000 + y)

    def spec(day, month):
        return {"k": "md", "m": month, "d": day} if year is None else {"k": "ymd", "y": year, "m": month, "d": day}
    dmy_ok, mdy_ok = 1 <= b <= 12 and 1 <= a <= 31, 1 <= a <= 12 and 1 <= b <= 31
    if not ask_mode:
        return [spec(a, b)]
    out = []
    if dmy_ok:
        out.append(spec(a, b))
    if mdy_ok and not (dmy_ok and a == b):
        out.append(spec(b, a))
    return out or [spec(a, b)]


def _valid(year, month, day):
    try:
        found = datetime.date(year, month, day)
        return found, found.isoformat()
    except ValueError:
        return None, f"{year:04d}-{month:02d}-{day:02d}"


def _date_for(spec: dict, h: int, minute: int, now: datetime.datetime):
    """(date or None, "YYYY-MM-DD", assumed) of a day spec for a time of day: a date the calendar does not have is (None, as written, False); `assumed` is true
    when the year was inferred because the date has passed this year. A date that is today stays today, whatever the hour: `resolve` refuses it when it has passed."""
    today = now.date()
    wall = now.replace(tzinfo=None)
    ahead = datetime.datetime.combine(today, datetime.time(h, minute)) > wall
    k = spec["k"]
    assumed = False
    if k == "rel":
        day, text = today + datetime.timedelta(days=spec["n"]), None
    elif k == "wd":
        delta = (spec["i"] - today.weekday()) % 7
        if delta == 0 and (spec["next"] or not ahead):
            delta = 7
        day, text = today + datetime.timedelta(days=delta), None
    elif k == "bad":
        day, text = None, f"{today.year:04d}-{today.month:02d}-{spec['d']:02d}"
    elif k == "monthday":
        day, text = None, None
        for step in range(0, 14):
            index = today.year * 12 + today.month - 1 + step
            year, month = index // 12, index % 12 + 1
            if spec["d"] > calendar.monthrange(year, month)[1]:
                continue
            candidate = datetime.date(year, month, spec["d"])
            if candidate >= today:          # today stays today, whatever the hour: `resolve` refuses it as past when it has
                day = candidate
                break
    elif k == "md":
        year = today.year
        if (spec["m"], spec["d"]) < (today.month, today.day):
            year, assumed = year + 1, True
        day, text = _valid(year, spec["m"], spec["d"])
        assumed = assumed and day is not None
    else:
        day, text = _valid(spec["y"], spec["m"], spec["d"])
    if day is not None and spec.get("plus"):
        day, text = day + datetime.timedelta(days=spec["plus"]), None
    if day is not None:
        text = day.isoformat()
    return day, text, assumed


def _day_only(spec: dict, now: datetime.datetime):
    """The date of a day spec when no hour was said, or None when the date depends on the hour (the same weekday or day of the month as today)."""
    today = now.date()
    k = spec["k"]
    if k == "rel":
        return today + datetime.timedelta(days=spec["n"])
    if k == "wd":
        delta = (spec["i"] - today.weekday()) % 7
        return None if delta == 0 and not spec["next"] else today + datetime.timedelta(days=delta or 7)
    if k == "bad":
        return None
    if k == "monthday":
        return None if spec["d"] == today.day else _date_for(spec, 0, 0, now.replace(hour=23, minute=59))[0]
    if k == "md":
        return _date_for(spec, 0, 0, now)[0] if (spec["m"], spec["d"]) != (today.month, today.day) else today
    return _valid(spec["y"], spec["m"], spec["d"])[0]


def _info(day, now: datetime.datetime) -> dict:
    today = now.date()
    return {"date": day.isoformat() if day else None, "rel": (day - today).days if day else None, "weekday": day.weekday() if day else None,
            "far": bool(day) and day.year != today.year}


def _reading(spec, h: int, minute: int, now: datetime.datetime) -> dict:
    clock = f"{h:02d}:{minute:02d}"
    today = now.date()
    if spec is None:
        rolled = datetime.datetime.combine(today, datetime.time(h, minute)) <= now.replace(tzinfo=None)
        day = today + datetime.timedelta(days=1 if rolled else 0)
        return {"when": clock, **_info(day, now), "time": clock, "rolled": rolled, "relative": None, "dated": False, "assumed_year": False}
    day, text, assumed = _date_for(spec, h, minute, now)
    out = {"when": f"{text} {clock}", **_info(day, now), "time": clock, "rolled": False, "relative": None, "dated": True, "assumed_year": assumed}
    out["date"] = text
    return out


def _relative_reading(hit: dict, now: datetime.datetime) -> dict:
    due = now.astimezone(datetime.timezone.utc) + hit["delta"]          # elapsed time: a clock change in between counts
    if due.second or due.microsecond:
        due = due.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    due = due.astimezone(now.tzinfo).replace(tzinfo=None)
    return {"when": hit["when"], **_info(due.date(), now), "time": due.strftime("%H:%M"), "rolled": False, "relative": hit["when"], "dated": True,
            "assumed_year": False}


def relative_again(reading: dict, now: datetime.datetime):
    """The reading of the same length of time ("in 30m") counted from `now`, or None when the reading is not a relative one."""
    m = re.fullmatch(r"in ([0-9]+)([mhd])", reading.get("relative") or "")
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    delta = datetime.timedelta(minutes=n) if unit == "m" else datetime.timedelta(hours=n) if unit == "h" else datetime.timedelta(days=n)
    return _relative_reading({"when": reading["relative"], "delta": delta}, now)


def moment(date, clock: str, now: datetime.datetime) -> dict:
    """The reading of a day ("YYYY-MM-DD", or None for the next time the hour comes) and an hour ("HH:MM"), as a person's answer that names one of the two."""
    h, minute = int(clock[:2]), int(clock[3:5])
    if date is None:
        return _reading(None, h, minute, now)
    try:
        day = datetime.date.fromisoformat(date)
    except ValueError:
        return _reading({"k": "ymd", "y": int(date[:4]), "m": int(date[5:7]), "d": int(date[8:10])}, h, minute, now)
    return {"when": f"{date} {clock}", **_info(day, now), "time": clock, "rolled": False, "relative": None, "dated": True, "assumed_year": False}


def parse(text, now, languages=None):
    """What the line means at the clock `now` (an aware datetime): see the module's text for the four shapes. The first key of the answer says which."""
    found = find(text, languages)
    hits = found["hits"]
    if not hits:
        return None
    spans = _spans(found)
    ask_mode = _ask_mode(found)
    relatives = [h for h in hits if h["kind"] == "relative"]
    clocks = [h for h in hits if h["kind"] == "clock"]
    dates = [h for h in hits if h["kind"] in ("date", "slash")]
    offsets = [h["delta"] for h in hits if h["kind"] == "offset"]
    specs = []
    for hit in dates:
        for spec in _specs(hit, ask_mode):
            if spec not in specs:
                specs.append(spec)
    weekdays = [sp for sp in specs if sp["k"] == "wd" and not sp.get("plus")]
    dated = [sp for sp in specs if sp["k"] in ("monthday", "md", "ymd")]
    if len(weekdays) == 1 and dated and clocks:        # "friday the 23rd": the date that falls on that weekday is the one meant
        h0, m0 = clocks[0]["times"][0]
        agree = [sp for sp in dated if (_date_for(sp, h0, m0, now)[0] or datetime.date.min).weekday() == weekdays[0]["i"]]
        if len(agree) == 1:
            specs = agree
    if clocks and len(relatives) == 1 and relatives[0].get("unit") == "d":      # "in 2 days at 9h": the day two days ahead
        specs.append({"k": "rel", "n": relatives[0]["days"]})
        relatives = []
    if len([h for h in dates if h["kind"] == "date"]) == 1 and any(h.get("topic") for h in dates) and None not in specs:
        specs.append(None)          # "the meeting of friday": the weekday may be the topic, so both are offered
    parts = {h["part"] for h in hits if h["kind"] == "vague" and h.get("part")}
    used = False
    if len(parts) == 1 and clocks:          # "tomorrow in the morning at 9", "tonight at 9": the part of the day says which of the two hours is meant
        part = next(iter(parts))
        every = {x for base in range(1, 13) for x in (_part_hours(base, part) or [])}
        for hit in clocks:
            if hit.get("bare"):
                base = hit["times"][0][0]
                chosen = _part_hours(base, part)
                if chosen:
                    hit["times"], hit["bare"], used = [(x, hit["times"][0][1]) for x in chosen], False, True
            elif all(h in every for h, _m in hit["times"]):
                used = True
    readings = []

    def add(reading):
        if all(reading["when"] != r["when"] for r in readings):
            readings.append(reading)
    for hit in relatives:
        add(_relative_reading(hit, now))
    if clocks:
        times, midnight = [], set()
        for hit in clocks:
            for hm in hit["times"]:
                if hm not in times:
                    times.append(hm)
                if hit.get("midnight"):
                    midnight.add(hm)
            if hit.get("alt"):
                add(_relative_reading(hit["alt"], now))
        for spec in (specs or [None]):
            for h, minute in times:
                add(_reading(spec, h, minute, now))
                if spec is not None and (h, minute) in midnight:          # "friday at midnight": the start or the end of the day
                    add(_reading({**spec, "plus": spec.get("plus", 0) + 1}, h, minute, now))
    if readings and specs and not clocks:       # a day and a length of time ("tomorrow in 2 hours"): nothing says which is meant
        return {"missing": "time", "day": None, "spans": spans}
    vague = any(h["kind"] == "vague" and not (used and h.get("part")) for h in hits)          # "9am in the afternoon": a part of the day the reading did not use
    unsure = vague or any(h.get("doubt") for h in hits)
    if used and any(r["rolled"] for r in readings):          # "this morning at 9" at 14:00: the part of the day has passed, tomorrow's is not taken silently
        unsure = True
    today_name = [sp for sp in specs if sp and sp["k"] == "wd" and not sp.get("two") and not sp.get("plus") and sp["i"] == now.weekday()]
    if today_name:          # "sunday" said on a Sunday: today, or the next one
        unsure = True
    if readings and offsets:          # "30 minutes before the meeting at 3pm": the hour that follows, less the offset
        moved = []
        for r in readings:
            stamp = datetime.datetime.strptime(f"{r['date']} {r['time']}", "%Y-%m-%d %H:%M") - offsets[0] if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", r["date"] or "") else None
            moved.append(moment(stamp.strftime("%Y-%m-%d"), stamp.strftime("%H:%M"), now) if stamp else r)
        readings = moved
    if readings:
        if len(readings) == 1:
            return {"when": readings[0]["when"], "reading": readings[0], "spans": spans, "vague": unsure}
        return {"ask": readings[:MAX_READINGS], "spans": spans, "vague": unsure}
    day = None
    if len(specs) == 1:
        found_day = _day_only(specs[0], now)
        if found_day is not None:
            day = _info(found_day, now)
    return {"missing": "time", "day": day, "spans": spans}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

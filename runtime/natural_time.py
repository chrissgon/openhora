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
weak word of a language (an abbreviation such as "sex" or "may") counts only when the line is in that language and is not a capitalised name.

  find(text, languages=None)         the time phrases of a line, with no clock: {"norm", "origin", "hits", "tables"}; each hit has "kind", "lang" and a span
  parse(text, now, languages=None)   what the line means, with the clock:
                                       {"when": <the grammar of reminders.resolve>, "reading": {...}, "spans": [(start, end)...]}   one clear reading
                                       {"ask": [reading...], "spans"}                                                              two or more readings (or one to confirm): ask
                                       {"missing": "time", "day": {...} | None, "spans"}                                            a day or a vague time, no hour
                                       None                                                                                          no time phrase
  doubts(text, languages=None)       (flag, typos): whether a word near the time shows it may not be fully understood, and the day words with a typo (each with the
                                     word it is one letter from); `doubt` is the flag alone
  recurring(text, languages=None)    whether the line repeats ("every monday", "de 8 em 8 horas")
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
relative_units {m, h, d, w}, number_words {word: n}, half_hour, and_half, joiners, half_words, time_words, not_typos, recurrence, recurrence_before_day,
recurrence_joiners, fraction_before, fraction_after, date_cues, edge_words, problem_words, work_verbs, calendar_noun_reads, triggers {remind, remind_anywhere,
reminders, reminders_bare, calendar, calendar_verb, calendar_noun, calendar_loose, note, undo}, forget {verbs, nouns, fillers}, polite, connectors, answers {yes,
notice, event, other, cancel, thanks}, work_starters. The trigger and answer words are read by runtime/natural.py, the time words here.

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
         "fraction_before", "fraction_after", "date_cues", "edge_words", "polite", "connectors", "work_starters")
GROUPS = {"days": ("today", "tomorrow", "day_after_tomorrow"), "meridiem": ("am", "pm"), "dayparts": ("morning", "dawn", "afternoon", "evening", "night"),
          "relative_units": ("m", "h", "d", "w"),
          "triggers": ("remind", "remind_anywhere", "reminders", "reminders_bare", "calendar", "calendar_verb", "calendar_noun", "calendar_loose", "note", "undo"),
          "forget": ("verbs", "nouns", "fillers"), "answers": ("yes", "notice", "event", "other", "cancel", "thanks")}


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
                out.append(c.lower())
                origin.append(i)
    folded = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", "".join(out))
    return folded, origin


def _alt(phrases):
    items = sorted({p for p in phrases if p}, key=lambda p: (-len(p), p))
    return "(?:" + "|".join(r"\s+".join(re.escape(w) for w in p.split()) for p in items) + ")" if items else None


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
        self.monthday1 = re.compile(f"{_L}{lead}(?P<d>[0-9]{{1,2}}){('(?:' + suffix + ')?') if suffix else ''}\\s+{_opt(a(table['month_joiners']))}(?P<mon>{months}){_R}") \
            if months else None
        self.monthday2 = re.compile(f"{_L}(?P<mon>{months})\\s+(?P<d>[0-9]{{1,2}}){('(?:' + suffix + ')?') if suffix else ''}(?![a-z0-9:/])") if months else None
        self.dom1 = re.compile(f"{_L}{dayw}\\s+(?P<d>[0-9]{{1,2}})(?![a-z0-9:/])") if dayw else None
        self.dom2 = re.compile(f"{_L}{_opt(ordp)}(?P<d>[0-9]{{1,2}}){suffix}(?![a-z0-9:/])") if suffix else None
        self.day = re.compile(f"{_L}(?P<w>{days}){_R}") if days else None
        self.weekday = re.compile(f"{_L}{modifier}(?P<name>{names}){after_part}{_R}") if names else None
        self.nxt = set(table["weekday_next"])
        self.daypart = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})(?::(?P<m1>[0-9]{{2}})" + (f"|\\s*{hw_all}(?:(?P<m2>[0-9]{{2}}))?" if hw_all else "") +
                                  f")?\\s+(?P<part>{parts}){_R}") if parts else None
        self.colon = re.compile(f"{_L}(?P<h>[0-9]{{1,2}}):(?P<m>[0-9]{{2}})" + (f"(?:\\s*(?P<mer>{mer}))?" if mer else "") + "(?![a-z0-9:])")
        mu_opt = (r"(?:\s*" + munits + "(?![a-z0-9]))?") if munits else ""
        m2_part = r"|\s+(?P<m2>[0-9]{2})(?![0-9/:.])" + ((r"(?:\s*" + munits + "(?![a-z0-9]))?") if munits else "")
        m3_part = (r"|\s+" + joiners + r"\s+(?P<m3>" + mnum + ")") if joiners else ""
        self.hw = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})\\s*{short}(?![a-z])(?:(?P<m>[0-9]{{2}})(?![0-9]){mu_opt}{m2_part}{m3_part})?(?![0-9])(?!\\s+[0-9])") if short else None
        self.dotted = re.compile(f"(?<![a-z0-9.,])(?P<h>[0-9]{{1,2}})\\.(?P<m>[0-9]{{2}})" + (f"(?:\\s*(?P<mer>{mer}))?" if mer else "") + "(?![0-9]|[.,][0-9])")
        self.mer = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})\\s*(?P<mer>{mer}){_R}") if mer else None
        special = a(list(self.maps["noon"]))
        jmin_special = (r"(?:\s+" + joiners + r"\s+(?P<m>" + mnum + "))?") if joiners else ""
        self.special = re.compile(f"{_L}(?P<w>{special}){jmin_special}{_R}") if special else None
        bare = a(table["bare_hour_prefixes"])
        long_part = (r"(?:\s+" + long + ")?") if long else ""
        self.bare = re.compile(f"{_L}(?P<p>{bare})\\s+(?P<h>[0-9]{{1,2}}){long_part}{jmin}(?![a-z0-9:/]|[.,][0-9]|\\s+[0-9])") if bare else None
        vague = a(table["vague"])
        self.vague = re.compile(f"{_L}(?P<w>{vague}){_R}") if vague else None


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
        return {"kind": "date", "spec": {"k": "md", "m": month, "d": d}, "weak": phrase in c.weak, "cued": phrase in c.cued, "name_s": m.start("mon")} \
            if month and 1 <= d <= 31 else None
    per("monthday1", monthday)
    per("monthday2", monthday)
    per("dom1", lambda c, m: {"kind": "date", "spec": {"k": "dom", "d": int(m.group("d"))}} if 1 <= int(m.group("d")) <= 31 else None)
    per("dom2", lambda c, m: {"kind": "date", "spec": {"k": "dom", "d": int(m.group("d"))}} if 1 <= int(m.group("d")) <= 31 else None)
    per("day", lambda c, m: {"kind": "date", "spec": {"k": "rel", "n": c.maps["day"][_word(m.group("w"))]}})

    def weekday(c, m):
        groups = m.groupdict()
        phrase = _word(m.group("name"))
        mod = groups.get("mod")
        two = bool(groups.get("after")) or (bool(mod) and _word(mod) in c.nxt)
        return {"kind": "date", "spec": {"k": "wd", "i": c.maps["weekday"][phrase], "next": two, "two": two}, "weak": phrase in c.weak, "name_s": m.start("name")}
    per("weekday", weekday)

    def daypart(c, m):
        groups = m.groupdict()
        minute = int(groups.get("m1") or groups.get("m2") or 0)
        hours = _part_hours(int(m.group("h")), c.maps["part"][_word(m.group("part"))])
        return {"kind": "clock", "times": [(h, minute) for h in hours], "bare": False} if hours and minute <= 59 else None
    per("daypart", daypart)

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
        h = int(m.group("h"))
        text = m.groupdict().get("m")
        minute = (30 if _word(text) in c.half else int(text)) if text else 0
        if h > 23 or minute > 59:
            return None
        times = [(h, minute), (h + 12, minute)] if 1 <= h <= 11 else [(h, minute)]
        return {"kind": "clock", "times": times, "bare": len(times) > 1}
    per("bare", bare)
    per("vague", lambda c, m: {"kind": "vague"})
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


def _is_name(hit: dict, text: str, origin: list) -> bool:
    """Whether a weak word was written as a name: capitalised in the middle of a line, or capitalised and followed by another capitalised word ("Sex Shop")."""
    at = origin[hit["name_s"]] if hit.get("name_s") is not None and hit["name_s"] < len(origin) else None
    if at is None or not text[at:at + 1].isupper():
        return False
    before = text[:at].rstrip()
    if before and before[-1] not in ".!?\n:":
        return True                                          # capitalised in the middle of a sentence
    following = re.match(r"[A-Za-z\u00c0-\u024f]+\s+([A-Z\u00c0-\u00de])", text[at:])
    return bool(following)


def _keep(hit: dict, hits: list, norm: str, text: str, origin: list, tables: list, evidence: set) -> bool:
    """Whether a hit counts: a weak word only in a line of its own language and never as a name, a month that is also a common word only after a cue; a dotted
    time (13.30) with its meridiem, a cue ("at 13.30") or a day beside it (then `doubt`: it is confirmed), and never beside money; x/y only as a date."""
    if hit.get("weak") and (hit["lang"] not in evidence or _is_name(hit, text, origin)):
        return False
    before, after = _neighbours(norm, hit)
    if hit.get("cued") and not (hit.get("cue") or any(before in t["date_cues"] for t in tables)):
        return False
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
        if not ((1 <= b <= 12 and 1 <= a <= 31) or (1 <= a <= 12 and 1 <= b <= 31)):
            return False
        if any(before in t["fraction_before"] or after in t["fraction_after"] for t in tables) and year is None:
            return False
        return bool(year is not None or hit.get("cue") or any(before in t["date_cues"] for t in tables) or any(h["kind"] == "clock" for h in hits))
    return True


def find(text, languages=None) -> dict:
    """The time phrases of the line, with no clock: {"norm", "origin", "hits", "tables"}. Each hit is {"kind": "clock" | "date" | "slash" | "relative" | "vague",
    "s", "e" (in the folded text), "lang", ...}. `languages` replaces the tables shipped (a test's stub language)."""
    tables = languages if languages is not None else globals()["languages"]()
    norm, origin = normalise(text)
    hits = _scan(norm, tables)
    _extend(norm, hits, tables)
    tokens = set(re.findall(r"[a-z0-9]+", norm))
    evidence = {h["lang"] for h in hits if h.get("lang") and not h.get("weak")} | {t["tag"] for t in tables if tokens & set(t["markers"])}
    kept = [h for h in hits if _keep(h, hits, norm, text if isinstance(text, str) else "", origin, tables, evidence)]
    return {"norm": norm, "origin": origin, "hits": sorted(kept, key=lambda h: h["s"]), "tables": tables}


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
    known = {w for t in tables for key in t["days"].values() for p in key for w in [p] if " " not in p and len(p) >= 5}
    known |= {p for t in tables for names in t["weekdays"] + t["months"] for p in names if " " not in p and len(p) >= 5}
    commons = {w for t in tables for w in t["not_typos"]}
    typos = [n for n in range(len(words)) if outside[n] and len(words[n]) >= 5 and words[n] not in commons and words[n] not in known and words[n].rstrip("s") not in known
             and near(n, n) and any(_distance_one(words[n], k) for k in known)]
    origin, spans = found["origin"], []
    for n in typos:
        close = sorted({k for k in known if _distance_one(words[n], k)})
        spans.append((origin[tokens[n][1]], origin[tokens[n][2] - 1] + 1, close[0] if len(close) == 1 else ""))          # the day word the person meant, when one word is that close
    return bool(typos), spans


def recurring(text, languages=None) -> bool:
    """Whether the line repeats ("every monday", "a cada", "de 8 em 8 horas", "toda segunda"): a reminder here is one-time, a routine repeats."""
    tables = languages if languages is not None else globals()["languages"]()
    found = find(text, tables)
    norm = found["norm"]
    joined = " " + " ".join(re.findall(r"[a-z0-9]+", norm)) + " "
    if any(f" {p} " in joined for t in tables for p in t["recurrence"]):
        return True
    for t in tables:
        alt = _alt(t["recurrence_joiners"])
        if alt and re.search(f"{_L}([0-9]+)\\s+{alt}\\s+\\1{_R}", norm):
            return True
        before = {w for w in t["recurrence_before_day"]}
        for hit in found["hits"]:
            if hit["kind"] == "date" and hit["spec"]["k"] in ("wd", "rel", "dom") and before:
                words = re.findall(r"[a-z0-9]+", norm[:hit["s0"]])
                if words and words[-1] in before:
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
    elif k == "dom":
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
    if k == "dom":
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
    specs = []
    for hit in dates:
        for spec in _specs(hit, ask_mode):
            if spec not in specs:
                specs.append(spec)
    weekdays = [sp for sp in specs if sp["k"] == "wd" and not sp.get("plus")]
    dated = [sp for sp in specs if sp["k"] in ("dom", "md", "ymd")]
    if len(weekdays) == 1 and dated and clocks:        # "friday the 23rd": the date that falls on that weekday is the one meant
        h0, m0 = clocks[0]["times"][0]
        agree = [sp for sp in dated if (_date_for(sp, h0, m0, now)[0] or datetime.date.min).weekday() == weekdays[0]["i"]]
        if len(agree) == 1:
            specs = agree
    if clocks and len(relatives) == 1 and relatives[0].get("unit") == "d":      # "in 2 days at 9h": the day two days ahead
        specs.append({"k": "rel", "n": relatives[0]["days"]})
        relatives = []
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
    vague = any(h["kind"] == "vague" for h in hits)          # "9am in the afternoon": a part of the day the reading did not use
    unsure = vague or any(h.get("doubt") for h in hits)
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

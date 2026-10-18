#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The time parser of natural requests (package NR-1): the time a person means in a line of their own words, as the grammar of runtime/reminders.py, with no model.

Pure: the clock is passed in (an aware datetime), nothing is read but the language tables, nothing is stored, nothing is logged. The engine holds no word of any
language. Every word it looks for (weekdays, months, "tomorrow", "in 2 hours", "13h", "9 pm", the words that introduce an hour) is data in a language table,
`runtime/natural_lang_<tag>.py` (`TABLE`), and the table of EVERY language found is tried on EVERY line, so a project whose language is Portuguese still
understands an English line. Adding a language adds one file (and its tests); the engine is not edited (`load_languages` finds the files, `check_table` refuses
a table that breaks the schema below, and a test plugs a stub third language in to show it).

  find(text, languages=None)         the time phrases of a line, with no clock: {"norm", "origin", "hits"}; each hit has "kind", "lang" and a span
  parse(text, now, languages=None)   what the line means, with the clock:
                                       {"when": <the grammar of reminders.resolve>, "reading": {...}, "spans": [(start, end)...]}   one clear reading
                                       {"ask": [reading...], "spans"}                                                              two or more readings: ask
                                       {"missing": "time", "day": {...} | None, "spans"}                                            a day or a vague time, no hour
                                       None                                                                                          no time phrase
  without(text, spans)               the line with those spans (of the ORIGINAL text) taken out
  normalise(text)                    (folded text, origin): lower case, no accent, and where each folded character came from
  languages() / load_languages(folder) / check_table(table)

What a reading is: {"when", "date": "YYYY-MM-DD", "time": "HH:MM", "rel": days from today | None, "weekday": 0 (Monday) to 6 | None, "rolled": bool,
"relative": "in 2h" | None}. `when` is one of the three forms of runtime/reminders.py (`HH:MM`, `YYYY-MM-DD HH:MM`, `in <n>m|h|d`), so `reminders.resolve` keeps
every check it has (a wall time the clock skips, a time that has passed, one minute to 366 days). `rolled` is true when a time with no day has passed today and
means tomorrow's. A date the calendar does not have (30 February) is passed on as written, for `resolve` to refuse.

What the engine reads (all of it from the tables):

  clock, 24-hour     13h  13hs  13hrs  13 hrs  13:00  9:30  13h30  21h        (the "hour words" of the table, or HH:MM)
  clock, 12-hour     1pm  1 pm  1:30pm  9am  9 da manha  3 da tarde  noon  midnight   (meridiem, day parts, noon and midnight words)
  hour with no marker  "at 9"  "as 9" (1 to 11): two readings, 09:00 and 21:00; 12 is noon; 13 to 23 and 0 are that hour
  day                today  tomorrow  the day after tomorrow  (the words of the table)
  weekday            friday  next friday  (the same weekday is today when the time is still ahead, else in 7 days; "next" is never today)
  day of the month   the 25th  day 25  (this month when it is ahead, else the next month that has the day)
  date               25 october  october 25  25/10  25/10/2026  2026-10-25   (x/y: day first in a language whose table says "day-first", else asked when
                     both numbers are 12 or less and the line's other words are not of a "day-first" language)
  in a while         in 2 hours  in 30 minutes  in 3 days  in half an hour  (an hour is `in <n>h`, to the minute upwards, as resolve does)
  vague              later  this afternoon  (a day with no hour, or a vague part of the day: `missing`; no hour is ever invented)
  two phrases        two clocks, two days, a clock and a "in a while": every reading is offered (at most 4), nothing is picked

The schema of a table (`check_table`; every list holds folded words, a phrase is words separated by one space; see runtime/natural_lang_en.py):
tag, markers, slash_dates ("ask" | "day-first"), days {today, tomorrow, day_after_tomorrow}, weekdays (7 lists, Monday first), weekday_next, weekday_this,
months (12 lists), month_joiners, day_words, ordinal_prefixes, ordinal_suffixes, prefixes, hour_words_24, meridiem {am, pm}, dayparts {morning, dawn, afternoon,
evening, night}, vague, noon, midnight, bare_hour_prefixes, relative_in, relative_units {m, h, d, w}, number_words {word: n}, half_hour, triggers {remind,
reminders, calendar, calendar_loose, note}, forget {verbs, nouns, fillers}, polite, connectors, answers {yes, notice, event}, work_starters. The trigger words
are read by runtime/natural.py, the time words here.

Standard library only. Runs on Python 3.9: python3 runtime/natural_time.py --help
"""
from __future__ import annotations

import calendar
import datetime
import glob
import importlib.util
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_READINGS = 4          # a question offers at most this many readings
RELATIVE_MAX = 9999       # the largest n of `in <n>m|h|d` (runtime/reminders.py)
_L = r"(?<![a-z0-9])"
_R = r"(?![a-z0-9])"

LISTS = ("markers", "weekday_next", "weekday_this", "month_joiners", "day_words", "ordinal_prefixes", "ordinal_suffixes", "prefixes", "hour_words_24", "vague",
         "noon", "midnight", "bare_hour_prefixes", "relative_in", "half_hour", "polite", "connectors", "work_starters")
GROUPS = {"days": ("today", "tomorrow", "day_after_tomorrow"), "meridiem": ("am", "pm"), "dayparts": ("morning", "dawn", "afternoon", "evening", "night"),
          "relative_units": ("m", "h", "d", "w"), "triggers": ("remind", "reminders", "calendar", "calendar_loose", "note"),
          "forget": ("verbs", "nouns", "fillers"), "answers": ("yes", "notice", "event")}


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


def load_languages(folder=None) -> list:
    """The tables of every file `natural_lang_*.py` in `folder` (default: this folder), checked, in the order of their file names. A file that breaks the
    schema is a ValueError (a language table is data under review, not something to skip silently)."""
    out = []
    for path in sorted(glob.glob(os.path.join(folder or HERE, "natural_lang_*.py"))):
        name = os.path.basename(path)[:-3]
        spec = importlib.util.spec_from_file_location("_" + name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check_table(module.TABLE)
        out.append(module.TABLE)
    return out


_default = []


def languages() -> list:
    """The tables of this folder, loaded once."""
    if not _default:
        _default.extend(load_languages())
    return _default


def normalise(text) -> tuple:
    """(folded, origin): `text` in lower case with no accent, a hyphen between two letters read as a space; origin[i] is the index in `text` the i-th folded
    character came from, so that a span found in the folded text is a span of the original."""
    out, origin = [], []
    for i, ch in enumerate(text or ""):
        for c in unicodedata.normalize("NFKD", ch):
            if not unicodedata.combining(c):
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
        for mer, names in table["meridiem"].items():
            for p in names:
                self.maps["mer"][p] = mer
        for part, names in table["dayparts"].items():
            for p in names:
                self.maps["part"][p] = part
        days = a(sum(table["days"].values(), []))
        names = a(list(self.maps["weekday"]))
        months = a(list(self.maps["month"]))
        units = a(list(self.maps["unit"]))
        nums = a(list(table["number_words"]))
        intro = a(table["relative_in"])
        hw = a(table["hour_words_24"])
        mer = a(list(self.maps["mer"]))
        parts = a(list(self.maps["part"]))
        dayw = a(table["day_words"])
        ordp = a(table["ordinal_prefixes"])
        suffix = a(table["ordinal_suffixes"])
        modifiers = a(table["weekday_next"] + table["weekday_this"])
        modifier = "(?:(?P<mod>" + modifiers + r")\s+)?" if modifiers else ""
        short = a([w for w in table["hour_words_24"] if len(w) <= 3])
        long = a([w for w in table["hour_words_24"] if len(w) > 3])
        self.prefix = a(table["prefixes"])
        self.relative = re.compile(f"{_L}(?P<intro>{intro})\\s+(?P<num>[0-9]{{1,4}}|{nums})\\s*(?P<unit>{units}){_R}") if intro and units and nums else None
        self.half = re.compile(f"{_L}(?P<intro>{intro})\\s+{a(table['half_hour'])}{_R}") if intro and table["half_hour"] else None
        lead = _opt(a([w for w in (table["day_words"] + table["ordinal_prefixes"]) if w]))
        self.monthday1 = re.compile(f"{_L}{lead}(?P<d>[0-9]{{1,2}}){('(?:' + suffix + ')?') if suffix else ''}\\s+{_opt(a(table['month_joiners']))}(?P<mon>{months}){_R}") \
            if months else None
        self.monthday2 = re.compile(f"{_L}(?P<mon>{months})\\s+(?P<d>[0-9]{{1,2}}){('(?:' + suffix + ')?') if suffix else ''}(?![a-z0-9:/])") if months else None
        self.dom1 = re.compile(f"{_L}{dayw}\\s+(?P<d>[0-9]{{1,2}})(?![a-z0-9:/])") if dayw else None
        self.dom2 = re.compile(f"{_L}{_opt(ordp)}(?P<d>[0-9]{{1,2}}){suffix}(?![a-z0-9:/])") if suffix else None
        self.day = re.compile(f"{_L}(?P<w>{days}){_R}") if days else None
        self.weekday = re.compile(f"{_L}{modifier}(?P<name>{names}){_R}") if names else None
        self.nxt = set(table["weekday_next"])
        self.daypart = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})(?::(?P<m1>[0-9]{{2}})" + (f"|\\s*{hw}(?:(?P<m2>[0-9]{{2}}))?" if hw else "") +
                                  f")?\\s+(?P<part>{parts}){_R}") if parts else None
        self.colon = re.compile(f"{_L}(?P<h>[0-9]{{1,2}}):(?P<m>[0-9]{{2}})" + (f"(?:\\s*(?P<mer>{mer}))?" if mer else "") + "(?![a-z0-9:])")
        self.hw = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})\\s*{short}(?![a-z])(?P<m>[0-9]{{2}})?(?![0-9])") if short else None
        self.mer = re.compile(f"{_L}(?P<h>[0-9]{{1,2}})\\s*(?P<mer>{mer}){_R}") if mer else None
        special = a(list(self.maps["noon"]))
        self.special = re.compile(f"{_L}(?P<w>{special}){_R}") if special else None
        bare = a(table["bare_hour_prefixes"])
        self.bare = re.compile(f"{_L}(?P<p>{bare})\\s+(?P<h>[0-9]{{1,2}})(?![a-z0-9:/])" + (f"(?:\\s+{long}{_R})?" if long else "")) if bare else None
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


def _day_of(d, month=None):
    return 1 <= d <= 31


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
                    hit.update(s=m.start(), e=m.end(), lang=lang["tag"] if isinstance(lang, dict) else (lang.tag if lang is not None else None))
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
        run([(c, getattr(c, attr)) for c in compiled if getattr(c, attr) is not None], lambda c, m: accept(c, m))

    iso = re.compile(r"(?<![0-9-])([0-9]{4})-([0-9]{2})-([0-9]{2})(?![0-9-])")
    run([(None, iso)], lambda c, m: {"kind": "date", "spec": {"k": "ymd", "y": int(m.group(1)), "m": int(m.group(2)), "d": int(m.group(3))}})
    slash = re.compile(r"(?<![0-9/])([0-9]{1,2})/([0-9]{1,2})(?:/([0-9]{4}|[0-9]{2}))?(?![0-9/])")
    run([(None, slash)], lambda c, m: {"kind": "slash", "a": int(m.group(1)), "b": int(m.group(2)), "y": int(m.group(3)) if m.group(3) else None})

    def relative(c, m):
        num = m.group("num")
        n = int(num) if num.isdigit() else c.table["number_words"].get(_word(num))
        unit = c.maps["unit"].get(_word(m.group("unit")))
        if not n or not unit or n * (7 if unit == "w" else 1) > RELATIVE_MAX:
            return None
        n, unit = (n * 7, "d") if unit == "w" else (n, unit)
        return {"kind": "relative", "when": f"in {n}{unit}", "delta": datetime.timedelta(minutes=n) if unit == "m" else datetime.timedelta(hours=n) if unit == "h"
                else datetime.timedelta(days=n)}
    per("half", lambda c, m: {"kind": "relative", "when": "in 30m", "delta": datetime.timedelta(minutes=30)})
    per("relative", relative)

    def monthday(c, m):
        month = c.maps["month"].get(_word(m.group("mon")))
        d = int(m.group("d"))
        return {"kind": "date", "spec": {"k": "md", "m": month, "d": d}} if month and _day_of(d) else None
    per("monthday1", monthday)
    per("monthday2", monthday)
    per("dom1", lambda c, m: {"kind": "date", "spec": {"k": "dom", "d": int(m.group("d"))}} if _day_of(int(m.group("d"))) else None)
    per("dom2", lambda c, m: {"kind": "date", "spec": {"k": "dom", "d": int(m.group("d"))}} if _day_of(int(m.group("d"))) else None)
    per("day", lambda c, m: {"kind": "date", "spec": {"k": "rel", "n": c.maps["day"][_word(m.group("w"))]}})

    def weekday(c, m):
        mod = m.group("mod") if "mod" in m.groupdict() else None
        return {"kind": "date", "spec": {"k": "wd", "i": c.maps["weekday"][_word(m.group("name"))], "next": bool(mod) and _word(mod) in c.nxt}}
    per("weekday", weekday)

    def daypart(c, m):
        minute = int(m.group("m1") or m.group("m2") or 0) if "m2" in m.groupdict() else int(m.group("m1") or 0)
        hours = _part_hours(int(m.group("h")), c.maps["part"][_word(m.group("part"))])
        return {"kind": "clock", "times": [(h, minute) for h in hours], "bare": False} if hours and minute <= 59 else None
    per("daypart", daypart)

    def colon(c, m):
        h, minute, mer = int(m.group("h")), int(m.group("m")), (m.group("mer") if "mer" in m.groupdict() else None)
        if minute > 59:
            return None
        if mer:
            h = _meridiem(h, c.maps["mer"][_word(mer)])
        return {"kind": "clock", "times": [(h, minute)], "bare": False} if h is not None and h <= 23 else None
    per("colon", colon)
    per("hw", lambda c, m: {"kind": "clock", "times": [(int(m.group("h")), int(m.group("m") or 0))], "bare": False}
        if int(m.group("h")) <= 23 and int(m.group("m") or 0) <= 59 else None)

    def meridiem(c, m):
        h = _meridiem(int(m.group("h")), c.maps["mer"][_word(m.group("mer"))])
        return {"kind": "clock", "times": [(h, 0)], "bare": False} if h is not None else None
    per("mer", meridiem)
    per("special", lambda c, m: {"kind": "clock", "times": [c.maps["noon"][_word(m.group("w"))]], "bare": False})

    def bare(c, m):
        h = int(m.group("h"))
        if h > 23:
            return None
        times = [(h, 0), (h + 12, 0)] if 1 <= h <= 11 else [(h, 0)]
        return {"kind": "clock", "times": times, "bare": len(times) > 1}
    per("bare", bare)
    per("vague", lambda c, m: {"kind": "vague"})
    return hits


def _extend(norm: str, hits: list, tables: list) -> None:
    """Take one connector that stands just before a phrase ("at 13h", "on friday", "para amanha") into the phrase: it goes with it when the words are taken out."""
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


def find(text, languages=None) -> dict:
    """The time phrases of the line, with no clock: {"norm", "origin", "hits", "tables"}. Each hit is {"kind": "clock" | "date" | "slash" | "relative" | "vague",
    "s", "e" (in the folded text), "lang", ...}. `languages` replaces the tables found in this folder (a test's stub language, a project's own)."""
    tables = languages if languages is not None else globals()["languages"]()
    norm, origin = normalise(text)
    hits = _scan(norm, tables)
    _extend(norm, hits, tables)
    return {"norm": norm, "origin": origin, "hits": sorted(hits, key=lambda h: h["s"]), "tables": tables}


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
        return [hit["spec"]]
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


def _date_for(spec: dict, h: int, minute: int, now: datetime.datetime):
    """(date or None, "YYYY-MM-DD") of a day spec for a time of day: a date the calendar does not have is (None, as written)."""
    today = now.date()
    wall = now.replace(tzinfo=None)
    ahead = datetime.datetime.combine(today, datetime.time(h, minute)) > wall
    k = spec["k"]
    if k == "rel":
        day = today + datetime.timedelta(days=spec["n"])
    elif k == "wd":
        delta = (spec["i"] - today.weekday()) % 7
        if delta == 0 and (spec["next"] or not ahead):
            delta = 7
        day = today + datetime.timedelta(days=delta)
    elif k == "dom":
        day = None
        for step in range(0, 14):
            index = today.year * 12 + today.month - 1 + step
            year, month = index // 12, index % 12 + 1
            if spec["d"] > calendar.monthrange(year, month)[1]:
                continue
            candidate = datetime.date(year, month, spec["d"])
            if candidate > today or (candidate == today and ahead):
                day = candidate
                break
    elif k == "md":
        year = today.year
        if (spec["m"], spec["d"], h, minute) <= (today.month, today.day, now.hour, now.minute):
            year += 1
        return _valid(year, spec["m"], spec["d"])
    else:
        return _valid(spec["y"], spec["m"], spec["d"])
    return day, day.isoformat()


def _valid(year, month, day):
    try:
        found = datetime.date(year, month, day)
        return found, found.isoformat()
    except ValueError:
        return None, f"{year:04d}-{month:02d}-{day:02d}"


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
        if spec["d"] == today.day:
            return None
        found = _date_for(spec, 0, 0, now.replace(hour=23, minute=59))[0]
        return found
    if k == "md":
        return _date_for(spec, 0, 0, now)[0] if (spec["m"], spec["d"]) != (today.month, today.day) else today
    return _valid(spec["y"], spec["m"], spec["d"])[0]


def _info(day, now: datetime.datetime) -> dict:
    today = now.date()
    return {"date": day.isoformat() if day else None, "rel": (day - today).days if day else None, "weekday": day.weekday() if day else None}


def _reading(spec, h: int, minute: int, now: datetime.datetime) -> dict:
    clock = f"{h:02d}:{minute:02d}"
    today = now.date()
    if spec is None:
        rolled = datetime.datetime.combine(today, datetime.time(h, minute)) <= now.replace(tzinfo=None)
        day = today + datetime.timedelta(days=1 if rolled else 0)
        return {"when": clock, **_info(day, now), "time": clock, "rolled": rolled, "relative": None}
    day, text = _date_for(spec, h, minute, now)
    out = {"when": f"{text} {clock}", **_info(day, now), "time": clock, "rolled": False, "relative": None}
    out["date"] = text
    return out


def _relative_reading(hit: dict, now: datetime.datetime) -> dict:
    due = now.replace(tzinfo=None) + hit["delta"]
    if due.second or due.microsecond:
        due = due.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    return {"when": hit["when"], **_info(due.date(), now), "time": due.strftime("%H:%M"), "rolled": False, "relative": hit["when"]}


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
    readings = []

    def add(reading):
        if all(reading["when"] != r["when"] for r in readings):
            readings.append(reading)
    for hit in relatives:
        add(_relative_reading(hit, now))
    if clocks:
        times = []
        for hit in clocks:
            for hm in hit["times"]:
                if hm not in times:
                    times.append(hm)
        for spec in (specs or [None]):
            for h, minute in times:
                add(_reading(spec, h, minute, now))
    if readings and specs and not clocks:       # a day and a length of time ("tomorrow in 2 hours"): nothing says which is meant
        return {"missing": "time", "day": None, "spans": spans}
    if readings:
        if len(readings) == 1:
            return {"when": readings[0]["when"], "reading": readings[0], "spans": spans}
        return {"ask": readings[:MAX_READINGS], "spans": spans}
    day = None
    if len(specs) == 1:
        found_day = _day_only(specs[0], now)
        if found_day is not None:
            day = _info(found_day, now)
    return {"missing": "time", "day": day, "spans": spans}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

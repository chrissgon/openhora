#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The data the registry owns before PLAN-BRAIN section 4 step 2 builds the registry (S41-9; contracts/runtime.md, limit L63; decisions OPEN-41-10 and OPEN-41-11).

Two sets of words used to be read from the language tables of runtime/natural_lang_*.py, which S41-11 deletes. They are plain JSON files in the folder runtime/registry/ now,
edited by hand under review like any other data, and this module is the one pure loader of them; a third file (LP-1) was written as data from the start, and a fourth, `recurrence_words.json` (CB-7).
Standard library only; it reads four files and keeps nothing else.

  private_words.json       the closed words that make a line private (a reminder asked in words, a write to the person's mail, calendar or files), per language, and the rule's
                           numbers: read by `turn_gate.private_line`, the gate's detector (limits L51, L61, L63). The file's own `rule` line states the rule.
  search_stop_words.json   the folded stop words of the search of an event by name (`stop_words`), the closed lead words and calendar words that introduce an account (`leads`,
                           `cal_words`), the plural words (`plural`), the brand words of each account (`brands`) and the calendar nouns (`nouns`): read by runtime/event_lookup.py.
  list_pick_words.json     (LP-1) the folded words of a reply that names a row of a list by an ordinal word, the word for last, a clock, a day, a brand or sender words, per language:
                           read by runtime/list_pick.py.
  recurrence_words.json    the folded phrases of a repetition (daily, weekly, the weekdays, the words that lead one, what is not supported or ends a series) and of the words that say
                           whether a cancel is of one occurrence or of the whole series: read by runtime/recurrence.py (CB-7, limits L54, L61).

Every file starts with the header {"v": 1, "made_from": "<commit>", "rule": "<one line>"}; `made_from` names the commit whose language tables the first version was written from by
a builder script (deleted by S41-11 PR 2b: the data is edited by hand under review from then on). A word is folded: lower case, no accent, the characters a-z and 0-9 only; a list is sorted and has no
repeat (the brands, a list of phrases, keep their written order, and each is a list of folded words).

  private_words()        the private words as written in the file (a dict, read once)
  search_stop_words()    the search words (a dict, read once): `brands` is {account: [tuple of folded words]}, the other lists are as written
  list_pick_words()      the pick words of both languages together (a dict, read once): every list of phrases is a list of tuples of folded words, `ordinals` is {word: (position, the word
                         shown for it)} and `weekday_ordinals` the set of ordinal words that are also a day of the week
  recurrence_words()     the words of a repetition (a dict, read once): the lists as written and `weekdays` ({"MO": [phrases], ...})
  problems(name=None)    the list of sentences that say how a file (or both, with None) is not well formed; empty when all is well
  forget()               drop what was read (a test, and a process that wants to read an edited file)

Nothing here reads a project or a person's line. Runs on Python 3.9: python3 runtime/registry_data.py --help
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.join(HERE, "registry")
FILES = {"private_words": "private_words.json", "search_stop_words": "search_stop_words.json", "list_pick_words": "list_pick_words.json", "recurrence_words": "recurrence_words.json"}
VERSION = 1
WORD = re.compile(r"[a-z0-9]+")
PHRASE = re.compile(r"[a-z0-9]+(?: [a-z0-9]+)*")
LANGUAGES = ("en", "pt-BR")
FAMILIES = ("calendar", "mail", "files")
PRIVATE_LISTS = ("polite", "lead", "lead_write", "lead_with_time", "anywhere_with_time", "work_starters")
SEARCH_LISTS = ("stop_words", "leads", "cal_words", "plural", "nouns")
PRIVATE_NUMBERS = ("bare_words_max", "verb_noun_gap_max")
PICK_PHRASES = ("after_ordinal", "articles", "clock_leads", "last", "polite", "value_leads")      # the sorted lists of phrases of one language of list_pick_words.json
PICK_KEYS = (*PICK_PHRASES, "ordinals", "weekday_ordinals")
NEED_KEYS = ("words", "digit", "colon", "address", "only", "tail_after", "tail_skip", "tail_max")
RECURRENCE_LISTS = ("daily", "weekly_lead", "weekly_plain", "unsupported", "end", "occurrence", "series", "week_range")
WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

_CACHE: dict = {}


def forget() -> None:
    """Forget the files that were read (a test, and a process that wants to read an edited file)."""
    _CACHE.clear()


def _read(name: str) -> dict:
    if name not in _CACHE:
        with open(os.path.join(FOLDER, FILES[name]), encoding="utf-8") as handle:
            _CACHE[name] = json.load(handle)
    return _CACHE[name]


def private_words() -> dict:
    """The private words of runtime/registry/private_words.json: {"numbers": {...}, "languages": {tag: {"polite", "lead", "lead_write", "lead_with_time", "anywhere_with_time", "verb_noun",
    "writes", "work_starters"}}} (the header keys too)."""
    return _read("private_words")


def search_stop_words() -> dict:
    """The search words of runtime/registry/search_stop_words.json; `brands` is {account: [tuple of folded words, ...]}."""
    if "search_stop_words" not in _CACHE:
        data = dict(_read("search_stop_words"))
        data["brands"] = {account: [tuple(words) for words in brands] for account, brands in data["brands"].items()}
        _CACHE["search_stop_words"] = data
    return _CACHE["search_stop_words"]


def list_pick_words() -> dict:
    """The pick words of runtime/registry/list_pick_words.json, both languages together (a line may be written in either): {"after_ordinal", "articles", "clock_leads", "last", "polite",
    "value_leads": [tuple of folded words], "ordinals": {word: (position from 1, the word a sentence shows for it)}, "weekday_ordinals": {word}}."""
    if "list_pick_words" not in _CACHE:
        data = _read("list_pick_words")["languages"]
        out = {key: [] for key in PICK_PHRASES}
        out["ordinals"], out["weekday_ordinals"] = {}, set()
        for tag in LANGUAGES:
            for key in PICK_PHRASES:
                out[key] += [tuple(phrase.split()) for phrase in data[tag][key] if tuple(phrase.split()) not in out[key]]
            for position, forms in enumerate(data[tag]["ordinals"], 1):
                for word in forms:
                    out["ordinals"][word] = (position, forms[0])
            out["weekday_ordinals"] |= set(data[tag]["weekday_ordinals"])
        _CACHE["list_pick_words"] = out
    return _CACHE["list_pick_words"]


def recurrence_words() -> dict:
    """The words of runtime/registry/recurrence_words.json: the lists of RECURRENCE_LISTS as written, and `weekdays` ({"MO".."SU": [folded phrases]})."""
    return _read("recurrence_words")


def _header(data, name: str) -> list:
    out = []
    if not isinstance(data, dict):
        return [f"{name}: the file is not an object"]
    if data.get("v") != VERSION:
        out.append(f"{name}: v is {data.get('v')!r}, not {VERSION}")
    if not isinstance(data.get("made_from"), str) or not data["made_from"]:
        out.append(f"{name}: made_from is not a commit name")
    if not isinstance(data.get("rule"), str) or not data["rule"].strip() or "\n" in data["rule"]:
        out.append(f"{name}: rule is not one line")
    return out


def _words(value, where: str, pattern=WORD, ordered: bool = True) -> list:
    """The problems of one list of folded words or phrases: a list of strings of the pattern, sorted and without repeat (`ordered`), else only without repeat."""
    if not isinstance(value, list) or not all(isinstance(item, str) and pattern.fullmatch(item) for item in value):
        return [f"{where}: not a list of folded {'words' if pattern is WORD else 'phrases'} (a-z, 0-9)"]
    out = []
    if len(set(value)) != len(value):
        out.append(f"{where}: a repeated entry")
    if ordered and value != sorted(value):
        out.append(f"{where}: not sorted")
    return out


def _private_problems(data) -> list:
    name = "private_words"
    out = _header(data, name)
    if out and not isinstance(data, dict):
        return out
    numbers = data.get("numbers")
    if not isinstance(numbers, dict) or set(numbers) != set(PRIVATE_NUMBERS) or not all(isinstance(numbers[k], int) and not isinstance(numbers[k], bool) and numbers[k] >= 0 for k in numbers):
        out.append(f"{name}: numbers is not {{{', '.join(PRIVATE_NUMBERS)}}} of whole numbers")
    languages = data.get("languages")
    if not isinstance(languages, dict) or set(languages) != set(LANGUAGES):
        return out + [f"{name}: languages is not exactly {list(LANGUAGES)}"]
    for tag in LANGUAGES:
        body = languages[tag]
        where = f"{name}.{tag}"
        if not isinstance(body, dict) or set(body) != set(PRIVATE_LISTS) | {"verb_noun", "writes"}:
            out.append(f"{where}: the keys are not {sorted(set(PRIVATE_LISTS) | {'verb_noun', 'writes'})}")
            continue
        for key in PRIVATE_LISTS:
            out += _words(body[key], f"{where}.{key}", PHRASE if key != "work_starters" else WORD)
        pair = body["verb_noun"]
        if not isinstance(pair, dict) or set(pair) != {"verbs", "nouns"}:
            out.append(f"{where}.verb_noun: not {{verbs, nouns}}")
        else:
            out += _words(pair["verbs"], f"{where}.verb_noun.verbs", PHRASE) + _words(pair["nouns"], f"{where}.verb_noun.nouns", PHRASE)
        writes = body["writes"]
        if not isinstance(writes, dict) or set(writes) != set(FAMILIES):
            out.append(f"{where}.writes: not exactly {list(FAMILIES)}")
            continue
        for family in FAMILIES:
            shapes = writes[family]
            if not isinstance(shapes, list) or not shapes:
                out.append(f"{where}.writes.{family}: not a list of shapes")
                continue
            for number, shape in enumerate(shapes):
                at = f"{where}.writes.{family}[{number}]"
                if not isinstance(shape, dict) or set(shape) != {"op", "heads", "needs"} or not isinstance(shape["op"], str) or not isinstance(shape["needs"], list) or not shape["needs"]:
                    out.append(f"{at}: not {{op, heads, needs}} with at least one need")
                    continue
                out += _words(shape["heads"], f"{at}.heads", PHRASE)
                if shape["heads"] == []:
                    out.append(f"{at}.heads: empty (a shape with no head never matches: it would silently flag nothing)")
                for index, need in enumerate(shape["needs"]):
                    here = f"{at}.needs[{index}]"
                    if not isinstance(need, dict) or not need or set(need) - set(NEED_KEYS):
                        out.append(f"{here}: not an object with some of {list(NEED_KEYS)}")
                        continue
                    for flag in ("digit", "colon", "address"):
                        if flag in need and need[flag] is not True:
                            out.append(f"{here}.{flag}: only true is written")
                    for key in ("words", "only", "tail_after", "tail_skip"):
                        if key in need:
                            out += _words(need[key], f"{here}.{key}", PHRASE if key in ("words", "tail_after") else WORD)
                            if need[key] == []:
                                out.append(f"{here}.{key}: empty (an empty list can never hold: the shape would silently flag nothing)")
                    if ("tail_after" in need) != ("tail_max" in need) or ("tail_skip" in need and "tail_max" not in need) or ("tail_max" in need and (not isinstance(need["tail_max"], int) or isinstance(need["tail_max"], bool) or need["tail_max"] < 1)):
                        out.append(f"{here}: tail_after and tail_max go together, and tail_max is a whole number from 1")
    return out


def _search_problems(data) -> list:
    name = "search_stop_words"
    out = _header(data, name)
    if out and not isinstance(data, dict):
        return out
    if set(data) != {"v", "made_from", "rule", "brands", *SEARCH_LISTS}:
        out.append(f"{name}: the keys are not v, made_from, rule, brands and {list(SEARCH_LISTS)}")
        return out
    for key in SEARCH_LISTS:
        out += _words(data[key], f"{name}.{key}")
    brands = data["brands"]
    if not isinstance(brands, dict) or not brands:
        return out + [f"{name}.brands: not an object of accounts"]
    for account, listed in brands.items():
        where = f"{name}.brands.{account}"
        if not isinstance(listed, list) or not listed or not all(isinstance(words, list) and words and all(isinstance(w, str) and WORD.fullmatch(w) for w in words) for words in listed):
            out.append(f"{where}: not a list of lists of folded words")
        elif len({tuple(words) for words in listed}) != len(listed):
            out.append(f"{where}: a repeated brand")
    if isinstance(data["stop_words"], list):
        for brand_word in {w for listed in brands.values() if isinstance(listed, list) for words in listed if isinstance(words, list) for w in words}:
            if brand_word in data["stop_words"]:
                out.append(f"{name}.stop_words: holds the brand word {brand_word!r}, which stays a word of a title")
    return out


def _pick_problems(data) -> list:
    name = "list_pick_words"
    out = _header(data, name)
    if out and not isinstance(data, dict):
        return out
    if set(data) != {"v", "made_from", "rule", "languages"}:
        return out + [f"{name}: the keys are not v, made_from, rule and languages"]
    languages = data["languages"]
    if not isinstance(languages, dict) or set(languages) != set(LANGUAGES):
        return out + [f"{name}: languages is not exactly {list(LANGUAGES)}"]
    for tag in LANGUAGES:
        body = languages[tag]
        where = f"{name}.{tag}"
        if not isinstance(body, dict) or set(body) != set(PICK_KEYS):
            out.append(f"{where}: the keys are not {sorted(PICK_KEYS)}")
            continue
        for key in PICK_PHRASES:
            out += _words(body[key], f"{where}.{key}", PHRASE)
            if body[key] == []:
                out.append(f"{where}.{key}: empty (a list that holds nothing can never read a reply)")
        forms = body["ordinals"]
        if not isinstance(forms, list) or not forms or not all(isinstance(f, list) and f and all(isinstance(w, str) and WORD.fullmatch(w) for w in f) for f in forms):
            out.append(f"{where}.ordinals: not a list, in the order of the positions, of lists of folded words")
            continue
        words = [w for f in forms for w in f]
        if len(set(words)) != len(words):
            out.append(f"{where}.ordinals: a repeated word")
        out += _words(body["weekday_ordinals"], f"{where}.weekday_ordinals")
        if isinstance(body["weekday_ordinals"], list):
            out += [f"{where}.weekday_ordinals: {w!r} is not an ordinal word" for w in body["weekday_ordinals"] if w not in words]
        if isinstance(body["last"], list):
            out += [f"{where}: {w!r} is both an ordinal and a word for last" for w in body["last"] if w in words]
        for key in ("articles", "clock_leads", "value_leads"):
            if isinstance(body[key], list):
                out += [f"{where}.{key}: {w!r} is also an ordinal word" for w in body[key] if w in words]
    return out


def _recurrence_problems(data) -> list:
    name = "recurrence_words"
    out = _header(data, name)
    if out and not isinstance(data, dict):
        return out
    if set(data) != {"v", "made_from", "rule", "weekdays", *RECURRENCE_LISTS}:
        return out + [f"{name}: the keys are not v, made_from, rule, weekdays and {list(RECURRENCE_LISTS)}"]
    for key in RECURRENCE_LISTS:
        out += _words(data[key], f"{name}.{key}", PHRASE)
    days = data["weekdays"]
    if not isinstance(days, dict) or set(days) != set(WEEKDAY_CODES):
        return out + [f"{name}.weekdays: not exactly {list(WEEKDAY_CODES)}"]
    seen = {}
    for code in WEEKDAY_CODES:
        out += _words(days[code], f"{name}.weekdays.{code}", PHRASE)
        for phrase in days[code] if isinstance(days[code], list) else []:
            if seen.setdefault(phrase, code) != code:
                out.append(f"{name}.weekdays: {phrase!r} names two weekdays")
    return out


def problems(name=None) -> list:
    """The sentences that say how a registry file (`name`, or all with None) is not well formed: its header, its version, a list that is not folded, sorted and without repeat."""
    checks = {"private_words": _private_problems, "search_stop_words": _search_problems, "list_pick_words": _pick_problems, "recurrence_words": _recurrence_problems}
    out = []
    for key in ([name] if name else list(checks)):
        try:
            with open(os.path.join(FOLDER, FILES[key]), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as error:
            out.append(f"{key}: cannot be read ({type(error).__name__})")
            continue
        out += checks[key](data)
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv in (["--help"], ["-h"]):
        print(__doc__.strip())
        return 0
    if argv != ["--check"]:
        print(__doc__.strip(), file=sys.stderr)
        print("usage: registry_data.py --check | --help", file=sys.stderr)
        return 2
    found = problems()
    for line in found:
        print(line, file=sys.stderr)
    print("registry data well formed" if not found else f"{len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

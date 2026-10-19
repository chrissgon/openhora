#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""A file named in the person's own words (package NR-2): which source of the project a line like "what does my CV say about Vue?" means.

`resolve(line, rows, snapshots=False)` compares the words of the line with the NAME (the catalog entry's name, without its extension), the ID and the
DESCRIPTION of each registered source, by plain rules and no model: lower case, accents removed, whole words only (no shared start, no stemming), plus the
aliases of a document kind that people write in different words (cv, curriculo, resume...). The catalog is third-party text, so what a source says cannot
steer the choice: only its name, its id and the person's own description are compared, with the person's words.

  one    exactly one source matches strongly: it is used, and the reply says which ("I used: <name>")
  ask    several match strongly, or the only matches are weak: up to RESOLVE_LISTED candidates are listed (id, name, type, date) and the person is asked
  none   the line names a KIND of document (an alias group: cv, invoice, contract...) and no source matches: the reply says so (searching the person's accounts
         is planned, not built)
  free   the line names no document, or only says "file", "documents", "sources" with no kind: the question is selected as it always was (runtime/ask_select.py)

A match is strong when a word of the line equals a word of the source's name or id (through an alias group), or, for a line that names a kind of document
(a cue: "file", "document", "cv"...), when two words of the line equal two words of its description; it is weak, and again only for a line with a cue, when one
word of its description does. A mail or calendar snapshot is a candidate only with `snapshots` (the group `ask-mail`
of a messaging sender); the terminal and the page name a snapshot with `@<id>`, which always wins and is never resolved here.

The aliases, the words that say "a file" (cues), the words that never name a source and the function words are data of the language tables
(runtime/natural_lang_<tag>.py, the key `requests`), the table of every language tried on every line. Standard library only.
Runs on Python 3.9: python3 runtime/source_resolve.py --help
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ask_select  # noqa: E402
import natural  # noqa: E402  (the words: aliases, cues, generic and function words are the language tables' data)  (the stop words and the word rule; this module reads no file)
import sources  # noqa: E402  (the types of a snapshot)

RESOLVE_LISTED = 5           # candidates a reply lists
MIN_WORD = 2                 # letters of a word that counts ("cv")
EXTENSIONS = frozenset("txt md pdf doc docx odt rtf xls xlsx ods csv tsv json html htm epub".split())
def words(text) -> list:
    """The words of a text that can count, canonical (an alias word becomes the first of its group), in order, without repeats."""
    group, stop, generic = natural.aliases(), set(natural.words_of("short_stop")), set(natural.words_of("generic")) | set(natural.words_of("cues"))
    out = []
    for word in ask_select.normal(text).split():
        word = group.get(word, word)
        if len(word) >= MIN_WORD and word not in ask_select.STOP_WORDS and word not in stop and word not in generic and word not in EXTENSIONS and word not in out:
            out.append(word)
    return out


def _cue(line: str) -> bool:
    group, cues = natural.aliases(), set(natural.words_of("cues"))
    return any(w in cues or w in group for w in ask_select.normal(line).split())


def _kind(line: str) -> bool:
    """Whether the line names a KIND of document (an alias group: cv, invoice, contract, passport...), not only the word "file": only a kind that matches nothing is
    answered "no source matches"; a bare cue word with no source behind it is a general question and is selected as it always was."""
    group = natural.aliases()
    return any(w in group for w in ask_select.normal(line).split())


def _name(row: dict) -> str:
    return str((row.get("catalog") or {}).get("name") or "")


def label(row: dict) -> str:
    """The name a person knows the source by: its catalog name, else its id."""
    return _name(row) or row["id"]


def _score(wanted: list, row: dict, cue: bool) -> tuple:
    """(strong words, description words) of the line that match this row. A source whose name and id are ONE word ("plan", "notes") is a common word the
    line may use for something else: it matches by that word only for a line that names a kind of document (a cue)."""
    names = set(words(_name(row))) | set(words(row["id"].replace("-", " ")))
    mine = set(words(row.get("description") or ""))
    strong = [w for w in wanted if w in names and (cue or len(names) > 1)]
    described = [w for w in wanted if w in mine and w not in strong]
    return strong, described


def _exact(line: str, have: list) -> list:
    """The sources whose id is written in the line as the person copies it (`cv-old`): an id of two words or more, or with a digit, that stands in the line as a
    whole phrase and is not part of a longer id that also does. Typing the id is naming the file; nothing is asked."""
    flat = " " + ask_select.normal(line) + " "
    found = []
    for row in have:
        phrase = ask_select.normal(row["id"])
        if (len(phrase.split()) > 1 or any(c.isdigit() for c in phrase)) and f" {phrase} " in flat:
            found.append((phrase, row))
    return [row for phrase, row in found if not any(other != phrase and f" {phrase} " in f" {other} " for other, _r in found)]


def resolve(line: str, rows: list, snapshots: bool = False) -> dict:
    """{"kind": "free" | "one" | "ask" | "none", "ids": [source ids], "rows": [the catalog rows of ids]} for a line and the catalog rows
    (sources.list_catalog; a row with no version is not a source to read). The ids of `ask` are in the order they are listed: the strongest, then the
    newer version, then the id."""
    have = [r for r in rows if r.get("version") and (snapshots or r.get("type") not in sources.SNAPSHOT_TYPES)]
    typed = _exact(line, have)
    wanted = words(line)
    cue = _cue(line)
    strong, weak = [], []
    for row in have:
        names, described = _score(wanted, row, cue)
        if names or (cue and len(described) >= 2):     # a description counts only for a line that names a kind of document: a general question is selected as it always was
            strong.append((2 * len(names) + len(described), row))
        elif cue and described:
            weak.append((len(described), row))
    if typed:      # an id typed as copied names the file; but a line that names other files too, or two ids, is selected as it always was: no narrowing, no question
        explained = {w for r in typed for w in set(words(_name(r))) | set(words(r["id"].replace("-", " ")))}      # the words the typed ids themselves account for
        others = [r for _s, r in strong if r not in typed and not set(_score(wanted, r, cue)[0]) <= explained]
        if len(typed) == 1 and not others:
            return {"kind": "one", "ids": [typed[0]["id"]], "rows": typed}
        return {"kind": "free", "ids": [], "rows": []}
    pick = lambda found: [r for _s, r in sorted(found, key=lambda t: (-t[0], _newer(t[1]), t[1]["id"]))]  # noqa: E731
    if len(strong) == 1:
        row = strong[0][1]
        return {"kind": "one", "ids": [row["id"]], "rows": [row]}
    if len(strong) > 1 and not cue:      # a question that names two files in plain words is selected as it always was: no new question
        return {"kind": "free", "ids": [], "rows": []}
    chosen = pick(strong) if strong else pick(weak)
    if chosen:
        chosen = chosen[:RESOLVE_LISTED]
        return {"kind": "ask", "ids": [r["id"] for r in chosen], "rows": chosen}
    return {"kind": "none" if _kind(line) else "free", "ids": [], "rows": []}


def _newer(row: dict) -> str:
    """A sort key that puts the newer version date first (the dates are ISO-8601, so the complement of each character sorts them in reverse)."""
    date = str((row.get("catalog") or {}).get("date") or "")
    return "".join(chr(0x10FFFF - ord(c)) for c in date)


def listing(rows: list) -> str:
    """The candidates, one per line: `<number>. <id>: <name> (<type>, <date>)`, the number the person answers with."""
    lines = []
    for n, row in enumerate(rows, 1):
        entry = row.get("catalog") or {}
        lines.append(f"{n}. @{row['id']}: {label(row)} ({row.get('type') or 'file'}, {entry.get('date') or '?'})")
    return "\n".join(lines)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Which sources a question reads (package AQ-1, the ask operation): selection by code, never by a model.

`select(question, rows)` takes the question's words and the catalog rows `sources.list_catalog` gives (a stored catalog
entry per source, no file read) and returns the ids of the sources whose converted text the answer run receives, or the word
of a refusal. Pure: nothing is read, written or called. The catalog is third-party text (a name, a heading and a sample value
are the person's data), so a model never chooses from it: the words of the question are compared with the words of an entry
by plain rules, and what a source says cannot steer which documents are read.

The rules, in order (contracts/runtime.md, "The answer from sources"):

  1. `@<id>` mentions (sources.mentions): exactly those, in the order they appear. More than ASK_SOURCES_MAX: TOO_MANY. Their
     converted bytes over ASK_BYTES_MAX: TOO_LARGE, with each id and its size.
  2. No mention, and the project's sources that have a version fit (at most ASK_SOURCES_MAX, together at most ASK_BYTES_MAX
     bytes of converted text): all of them, by id.
  3. Otherwise rank. The question's words (lower case, no accents, at least 3 letters, minus a closed list of English and
     Portuguese stop words) against the words of each entry's name, description, headings, sheet names, column names and sample
     values; a word matches on equality, or on a shared start of 5 letters; the score is the number of distinct question words
     matched; ties go to the newer version date, then the id. They are taken in order while within both caps; a single source over
     ASK_BYTES_MAX is skipped and named.
  4. Nothing scores above 0: NO_MATCH, with up to NO_MATCH_IDS ids to name with @. No source has a version: NO_SOURCES.

The numbers are choices of the specification (SPEC-ANSWER-FROM-SOURCES), not measured: 256 KiB is the size sources.py already
calls a large share of a context.

Standard library only. Runs on Python 3.9: python3 runtime/ask_select.py --help
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import sources  # noqa: E402  (mentions() only; this module reads no file)

ASK_BYTES_MAX = 256 * 1024     # converted bytes the run receives in all (= sources.CONVERTED_WARN, which a test ties)
ASK_SOURCES_MAX = 5            # sources the run receives
ASK_TEXT_MAX = 2000            # characters of the question
NO_MATCH_IDS = 10              # ids a NO_MATCH reply offers to name with @
MIN_WORD = 3                   # letters of a word that counts
SHARED_START = 5               # letters two words share to match

NO_SOURCES, NO_MATCH, TOO_MANY, TOO_LARGE = "NO_SOURCES", "NO_MATCH", "TOO_MANY", "TOO_LARGE"

# A closed list, in the words as _normal writes them (no accents). A word of the question in it never counts toward a match.
PORTUGUESE_STOP_WORDS = (
    "que qual quais quem quando onde porque como para por com sem uma uns umas dos das nos nas aos seu sua seus suas esse essa "  # validate: allow english-only -- the closed list of Portuguese stop words
    "esses essas este esta estes estas isso isto aquele aquela mais menos muito muita muitos muitas tem tambem sobre entre ate "  # validate: allow english-only -- the closed list of Portuguese stop words
    "quanto quantos quanta quantas foi sao era ser estar estao fazer feito pode podem deve devem nao sim ainda ja so")  # validate: allow english-only -- the closed list of Portuguese stop words
STOP_WORDS = frozenset(
    """the and for are was were with that this these those from have has had not but you your what which who whom when where why how
    can could would should will shall may might must does did been being into than then them they there their about over under
    also any all each some such only just very more most other one two per via our out its his her him she""".split()
    + PORTUGUESE_STOP_WORDS.split())


def normal(text: str) -> str:
    """Lower case, no accents, every run of other characters one space (the same rule as ops_say._normal, which a test ties)."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text).lower()) if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", plain).strip()


def words_of(text: str) -> list:
    """The words of a text that can count toward a match, in order, without repeats."""
    out = []
    for word in normal(text).split():
        if len(word) >= MIN_WORD and word not in STOP_WORDS and word not in out:
            out.append(word)
    return out


def _entry_text(row: dict) -> str:
    entry = row.get("catalog") or {}
    parts = [entry.get("name"), row.get("description"), *(entry.get("headings") or [])]
    for sheet in entry.get("sheets") or []:
        parts.append(sheet.get("name"))
        for column in sheet.get("columns") or []:
            parts += [column.get("name"), *(column.get("samples") or [])]
    return " ".join(str(p) for p in parts if p)


def _matches(word: str, others: set) -> bool:
    if word in others:
        return True
    if len(word) < SHARED_START:
        return False
    return any(len(other) >= SHARED_START and other[:SHARED_START] == word[:SHARED_START] for other in others)


def score(question_words: list, row: dict) -> int:
    """The number of distinct question words that match a word of the entry."""
    theirs = set(words_of(_entry_text(row)))
    return sum(1 for word in question_words if _matches(word, theirs))


def size_of(row: dict) -> int:
    """The converted bytes the catalog entry states (0 when it states none; the run's copies are measured again when they are made)."""
    found = (row.get("catalog") or {}).get("converted_bytes")
    return found if isinstance(found, int) and not isinstance(found, bool) and found >= 0 else 0


def _date(row: dict) -> str:
    return str((row.get("catalog") or {}).get("date") or "")


def select(question: str, rows: list) -> dict:
    """{"ids": [source ids, in the order the run receives them], "skipped": [{"id", "bytes"}] (a single source over the cap that a
    ranking left out), "refusal": None, or one of NO_SOURCES, NO_MATCH, TOO_MANY, TOO_LARGE, "detail": what the refusal names:
    NO_MATCH the ids to offer, TOO_MANY the number mentioned, TOO_LARGE [{"id", "bytes"}]}. `rows` are catalog rows (id, version,
    description, catalog); a row with no version is not a source to read."""
    have = {r["id"]: r for r in rows if r.get("version")}

    def refuse(word, detail=None):
        return {"ids": [], "skipped": [], "refusal": word, "detail": detail}

    if not have:
        return refuse(NO_SOURCES)
    named = sources.mentions(question, list(have))
    if named:
        if len(named) > ASK_SOURCES_MAX:
            return refuse(TOO_MANY, len(named))
        if sum(size_of(have[i]) for i in named) > ASK_BYTES_MAX:
            return refuse(TOO_LARGE, [{"id": i, "bytes": size_of(have[i])} for i in named])
        return {"ids": named, "skipped": [], "refusal": None, "detail": None}
    ordered = sorted(have)
    if len(ordered) <= ASK_SOURCES_MAX and sum(size_of(have[i]) for i in ordered) <= ASK_BYTES_MAX:
        return {"ids": ordered, "skipped": [], "refusal": None, "detail": None}
    wanted = words_of(question)
    by_score = {i: score(wanted, have[i]) for i in ordered}
    ranked = [i for i in ordered if by_score[i] > 0]                    # by id, then (each sort is stable, also reversed):
    ranked.sort(key=lambda i: _date(have[i]), reverse=True)             # the newer version date first,
    ranked.sort(key=lambda i: by_score[i], reverse=True)                # then the higher score
    if not ranked:
        return refuse(NO_MATCH, ordered[:NO_MATCH_IDS])
    taken, skipped, used = [], [], 0
    for source_id in ranked:
        size = size_of(have[source_id])
        if size > ASK_BYTES_MAX:
            skipped.append({"id": source_id, "bytes": size})
            continue
        if len(taken) >= ASK_SOURCES_MAX or used + size > ASK_BYTES_MAX:
            break
        taken.append(source_id)
        used += size
    if not taken:
        return refuse(TOO_LARGE, skipped)
    return {"ids": taken, "skipped": skipped, "refusal": None, "detail": None}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

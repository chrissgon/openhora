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
  none   the line names a kind of document or file (a cue) and no source matches: the reply says so (searching the person's accounts is planned, not built)
  free   the line names no document: the question is selected as it always was (runtime/ask_select.py)

A match is strong when a word of the line equals a word of the source's name or id (through an alias group), or, for a line that names a kind of document
(a cue: "file", "document", "cv"...), when two words of the line equal two words of its description; it is weak, and again only for a line with a cue, when one
word of its description does. A mail or calendar snapshot is a candidate only with `snapshots` (the group `ask-mail`
of a messaging sender); the terminal and the page name a snapshot with `@<id>`, which always wins and is never resolved here.

The aliases are a table of this file for now (package NR-1 makes each language a data file; this table moves there). Standard library only.
Runs on Python 3.9: python3 runtime/source_resolve.py --help
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import ask_select  # noqa: E402  (the stop words and the word rule; this module reads no file)
import sources  # noqa: E402  (the types of a snapshot)

RESOLVE_LISTED = 5           # candidates a reply lists
MIN_WORD = 2                 # letters of a word that counts ("cv")
EXTENSIONS = frozenset("txt md pdf doc docx odt rtf xls xlsx ods csv tsv json html htm epub".split())
# Words that name a kind of document in several languages: the words of a group are one word. The first of a group stands for it.
ALIASES = (
    ("cv", "curriculo", "curriculum", "resume"),
    ("planilha", "spreadsheet", "sheet", "tabela"),
    ("fatura", "invoice", "boleto"),
    ("orcamento", "budget", "quote"),
    ("relatorio", "report"),
    ("apresentacao", "presentation", "slides", "deck"),
    ("proposta", "proposal"),
    ("recibo", "receipt", "comprovante"),
    ("ata", "minutes"),
    ("passaporte", "passport"),
    ("extrato", "statement"),
    ("manual", "handbook", "guide", "guia"),
)  # validate: allow english-only -- the closed list of document-kind aliases in several languages
# A word of the line that only says "a file": it makes the line name a document (a cue) and never matches a source by itself.
CUES = frozenset("arquivo arquivos documento documentos doc docs file files document documents pdf anexo anexos fonte fontes source sources".split())  # validate: allow english-only -- the closed list of words that say "a file"
GENERIC = frozenset(CUES | set("meu minha meus minhas my mine our nosso nossa diz fala fale say says said sobre about tell show mostra mostre ler le read".split()))  # validate: allow english-only -- the closed list of words that never name a source
SHORT_STOP = frozenset("de da do dos das em no na nos nas um uns ao aos pela pelo por e ou se me te lhe to of in on at is it be an as os el la le un une der die das".split())  # validate: allow english-only -- the closed list of two-letter and short function words
_GROUP = {word: group[0] for group in ALIASES for word in group}


def words(text) -> list:
    """The words of a text that can count, canonical (an alias word becomes the first of its group), in order, without repeats."""
    out = []
    for word in ask_select.normal(text).split():
        word = _GROUP.get(word, word)
        if len(word) >= MIN_WORD and word not in ask_select.STOP_WORDS and word not in SHORT_STOP and word not in GENERIC and word not in EXTENSIONS and word not in out:
            out.append(word)
    return out


def _cue(line: str) -> bool:
    plain = ask_select.normal(line).split()
    return any(w in CUES or w in _GROUP for w in plain)


def _name(row: dict) -> str:
    return str((row.get("catalog") or {}).get("name") or "")


def label(row: dict) -> str:
    """The name a person knows the source by: its catalog name, else its id."""
    return _name(row) or row["id"]


def _score(wanted: list, row: dict) -> tuple:
    """(strong words, description words) of the line that match this row."""
    names = set(words(_name(row))) | set(words(row["id"].replace("-", " ")))
    mine = set(words(row.get("description") or ""))
    strong = [w for w in wanted if w in names]
    described = [w for w in wanted if w in mine and w not in strong]
    return strong, described


def resolve(line: str, rows: list, snapshots: bool = False) -> dict:
    """{"kind": "free" | "one" | "ask" | "none", "ids": [source ids], "rows": [the catalog rows of ids]} for a line and the catalog rows
    (sources.list_catalog; a row with no version is not a source to read). The ids of `ask` are in the order they are listed: the strongest, then the
    newer version, then the id."""
    have = [r for r in rows if r.get("version") and (snapshots or r.get("type") not in sources.SNAPSHOT_TYPES)]
    wanted = words(line)
    cue = _cue(line)
    strong, weak = [], []
    for row in have:
        names, described = _score(wanted, row)
        if names or (cue and len(described) >= 2):     # a description counts only for a line that names a kind of document: a general question is selected as it always was
            strong.append((2 * len(names) + len(described), row))
        elif cue and described:
            weak.append((len(described), row))
    pick = lambda found: [r for _s, r in sorted(found, key=lambda t: (-t[0], _newer(t[1]), t[1]["id"]))]  # noqa: E731
    if len(strong) == 1:
        row = strong[0][1]
        return {"kind": "one", "ids": [row["id"]], "rows": [row]}
    chosen = pick(strong) if strong else pick(weak)
    if chosen:
        chosen = chosen[:RESOLVE_LISTED]
        return {"kind": "ask", "ids": [r["id"] for r in chosen], "rows": chosen}
    return {"kind": "none" if cue else "free", "ids": [], "rows": []}


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

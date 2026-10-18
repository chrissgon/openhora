#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The reply to a question, checked by code (package AQ-1, the ask operation). Pure: the run's reply and the text of the copies in,
the text the person is sent out; nothing is read or written.

What a model writes is not what the person reads. The answer skill writes this form (the one measured by its cases):

    Answer: <found | partial | not-found>
    <the answer, each claim followed by [<source id>]>
    Quote [<source id>]: "<exact passage, at most 300 characters>"      (one or more for found and partial)
    Instructions found in external content: <each quoted with its source id and `not followed`, or none>

and this module reads only those lines and decides what is sent:

  1. A first line outside the closed list: the reply is shown whole after UNCHECKED.
  2. A `[<id>]` the run was not given: flagged UNKNOWN_SOURCE.
  3. Each quote, white space collapsed, must be a substring of that source's prepared copy (white space collapsed too); one that
     is not is shown flagged QUOTE_NOT_FOUND, one over QUOTE_MAX characters QUOTE_TOO_LONG, and neither counts as verified.
  4. `found` or `partial` with no verified quote: UNVERIFIED.
  5. `not-found`: the model's prose is dropped and only NOT_FOUND is sent (no invented answer reaches the person).
  6. The instructions line is kept whenever it is not `none`: an instruction found in a source is told, never followed.

Code appends the footer: READ (each source and version read) and, when the run is not proven, UNPROVEN. The sentences are English
constants; the project's language is applied to them by a later package (LR-1).

Standard library only. Runs on Python 3.9: python3 runtime/ask_reply.py --help
"""
from __future__ import annotations

import re
import sys

QUOTE_MAX = 300
ANSWERS = ("found", "partial", "not-found")

UNCHECKED = "This answer is not in the expected form; check it against the sources."
UNKNOWN_SOURCE = "This source was not given to the run: {id}."
QUOTE_NOT_FOUND = "This quote is not in {id}:"
QUOTE_TOO_LONG = "This quote is longer than " + str(QUOTE_MAX) + " characters and was not checked ({id}):"
UNVERIFIED = "No quote of this answer could be checked against the sources; check it yourself."
NOT_FOUND = "Not found in the sources read: {read}."
READ = "Read: {read}"
UNPROVEN = "Unproven: {skill} has no passing test on {model}; check the answer against the quotes."
INSTRUCTIONS = "Instructions found in external content:"

FIRST_LINE = re.compile(r"Answer:\s*(found|partial|not-found)\s*\.?", re.I)
QUOTE_LINE = re.compile(r'Quote \[([^\]\n]*)\]:\s*["“](.*)["”]\s*', re.I)
INSTRUCTIONS_LINE = re.compile(r"Instructions found in external content:[ \t]*(.*)", re.I)
BRACKET = re.compile(r"\[([a-z0-9][a-z0-9-]{0,39})\]")


def collapse(text: str) -> str:
    return " ".join(str(text).split())


def read_line(given: list) -> str:
    """'a (version 1), b (version 2)' for the sources the run received."""
    return ", ".join(f"{g['source']} (version {g['version']})" for g in given)


def parse(response: str) -> dict:
    """{"answer": a word of ANSWERS or None, "prose": [lines], "quotes": [(id, text)], "instructions": text or None (None when
    the line says none or is absent)}. Nothing is judged here."""
    lines = (response or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((n for n, line in enumerate(lines) if line.strip()), None)
    if start is None:
        return {"answer": None, "prose": [], "quotes": [], "instructions": None}
    first = FIRST_LINE.fullmatch(lines[start].strip())
    if first is None:
        return {"answer": None, "prose": lines, "quotes": [], "instructions": None}
    body, tail = lines[start + 1:], None
    for n, line in enumerate(body):
        found = INSTRUCTIONS_LINE.fullmatch(line.strip()) if line.strip().lower().startswith(INSTRUCTIONS.lower()) else None
        if found:
            rest = [found.group(1).strip()] + [l.rstrip() for l in body[n + 1:]]
            text = "\n".join(rest).strip()
            tail = None if collapse(text).rstrip(".").lower() in ("", "none") else INSTRUCTIONS + " " + text
            body = body[:n]
            break
    prose, quotes = [], []
    for line in body:
        quote = QUOTE_LINE.fullmatch(line.strip())
        if quote:
            quotes.append((quote.group(1).strip(), quote.group(2)))
        else:
            prose.append(line.rstrip())
    return {"answer": first.group(1).lower(), "prose": prose, "quotes": quotes, "instructions": tail}


def check(response: str, given: list, copies: dict, proven: bool, skill: str, model: str) -> dict:
    """The reply the person is sent and what was found: {"text", "outcome": "found" | "partial" | "not-found" | "unchecked",
    "flags": [words], "verified": the number of quotes found in their sources}. `given` is [{"source", "version"}] of the copies
    the run received, `copies` {source id: the text of that copy}, `proven` whether the run was proven (autonomy "proven")."""
    read = read_line(given)
    footer = [] if proven else [UNPROVEN.format(skill=skill, model=model)]
    parsed = parse(response)
    ids = {g["source"] for g in given}
    flags = []
    if parsed["answer"] is None:
        text = "\n\n".join([UNCHECKED, (response or "").strip() or "(empty reply)", READ.format(read=read), *footer])
        return {"text": text, "outcome": "unchecked", "flags": ["UNCHECKED"], "verified": 0}
    if parsed["answer"] == "not-found":
        pieces = [NOT_FOUND.format(read=read)] + ([parsed["instructions"]] if parsed["instructions"] else []) + footer
        return {"text": "\n\n".join(pieces), "outcome": "not-found", "flags": flags, "verified": 0}
    copies_flat = {i: collapse(t) for i, t in copies.items()}
    shown, verified = [], 0
    for source_id, passage in parsed["quotes"]:
        if source_id not in ids:
            flags.append("UNKNOWN_SOURCE")
            shown.append(f'{UNKNOWN_SOURCE.format(id=source_id)} "{passage}"')
        elif len(passage) > QUOTE_MAX:
            flags.append("QUOTE_TOO_LONG")
            shown.append(f'{QUOTE_TOO_LONG.format(id=source_id)} "{passage[:QUOTE_MAX]}..."')
        elif collapse(passage) and collapse(passage) in copies_flat.get(source_id, ""):
            verified += 1
            shown.append(f'Quote [{source_id}]: "{passage}"')
        else:
            flags.append("QUOTE_NOT_FOUND")
            shown.append(f'{QUOTE_NOT_FOUND.format(id=source_id)} "{passage}"')
    prose = "\n".join(parsed["prose"]).strip()
    unknown = [i for i in dict.fromkeys(BRACKET.findall(prose)) if i not in ids]
    notes = [UNKNOWN_SOURCE.format(id=i) for i in unknown]
    if unknown:
        flags.append("UNKNOWN_SOURCE")
    if verified == 0:
        flags.append("UNVERIFIED")
        notes.append(UNVERIFIED)
    pieces = [p for p in (prose, "\n".join(shown), "\n".join(notes), parsed["instructions"] or "") if p]
    text = "\n\n".join(pieces + [READ.format(read=read), *footer])
    return {"text": text, "outcome": parsed["answer"], "flags": list(dict.fromkeys(flags)), "verified": verified}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

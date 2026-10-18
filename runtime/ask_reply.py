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

and this module reads only those lines and decides what is sent. A model's text must never pass for what code checked, so:

  1. A first line outside the closed list: the reply is shown whole after UNCHECKED.
  2. A quote line is read (a leading bullet or spaces and any case are allowed) and never shown as the model wrote it: a quote that is
     found in its source's prepared copy (Unicode NFC, white space collapsed) and is at least QUOTE_MIN_CHARS characters or
     QUOTE_MIN_WORDS words long is printed by code as `Checked quote [<id>]: "..."`, a form only code writes; any other quote is shown
     after a sentence that says what is wrong with it (QUOTE_NOT_FOUND, QUOTE_TOO_SHORT, QUOTE_TOO_LONG, UNKNOWN_SOURCE).
  3. Any other line that has `quote [` in it, in any case, is left out of the answer and flagged QUOTE_IMITATED.
  4. A `[<id>]` of the form of a source id that the run was not given is flagged UNKNOWN_SOURCE (`[1]`, a footnote, is not).
  5. `found` or `partial` with no verified quote: UNVERIFIED.
  6. `not-found`: the model's prose is dropped; only NOT_FOUND, the instructions lines and the footer are sent.
  7. After the instructions line the reply keeps only lines that name a source the run was given and say `not followed`; every other
     line there is left out (and flagged AFTER_INSTRUCTIONS in a found or partial answer).

Code appends the footer: READ (each source and version read) and, when the run is not proven, UNPROVEN. The sentences are English
constants; the project's language is applied to them by a later package (LR-1).

Standard library only. Runs on Python 3.9: python3 runtime/ask_reply.py --help
"""
from __future__ import annotations

import re
import sys
import unicodedata

QUOTE_MAX = 300
QUOTE_MIN_CHARS = 20
QUOTE_MIN_WORDS = 3
ANSWERS = ("found", "partial", "not-found")

UNCHECKED = "This answer is not in the expected form; check it against the sources."
UNKNOWN_SOURCE = "This source was not given to the run: {id}."
QUOTE_NOT_FOUND = "This quote is not in {id}:"
QUOTE_TOO_LONG = "This quote is longer than " + str(QUOTE_MAX) + " characters and was not checked ({id}):"
QUOTE_TOO_SHORT = "This quote is too short to check ({id}):"
QUOTE_CHECKED = 'Checked quote [{id}]: "{text}"'
QUOTE_IMITATED = "A line of the answer imitated a checked quote and was left out."
AFTER_INSTRUCTIONS = "Text after the instructions line was left out."
UNVERIFIED = "No quote of this answer could be checked against the sources; check it yourself."
NOT_FOUND = "Not found in the sources read: {read}."
READ = "Read: {read}"
UNPROVEN = "Unproven: {skill} has no passing test on {model}; check the answer against the quotes."
INSTRUCTIONS = "Instructions found in external content:"

FIRST_LINE = re.compile(r"Answer:\s*(found|partial|not-found)\s*\.?", re.I)
QUOTE_LINE = re.compile(r'[\s\-*•>]*Quote \[([^\]\n]*)\]:\s*["“](.*)["”]\s*', re.I)
QUOTE_WORD = re.compile(r"quote\s*\[", re.I)
INSTRUCTIONS_LINE = re.compile(r"Instructions found in external content:[ \t]*(.*)", re.I)
BRACKET = re.compile(r"\[([a-z0-9][a-z0-9-]{0,39})\]")


def collapse(text: str) -> str:
    """NFC, then every run of white space one space."""
    return " ".join(unicodedata.normalize("NFC", str(text)).split())


def read_line(given: list) -> str:
    """'a (version 1), b (version 2)' for the sources the run received."""
    return ", ".join(f"{g['source']} (version {g['version']})" for g in given)


def parse(response: str) -> dict:
    """{"answer": a word of ANSWERS or None, "prose": [lines], "quotes": [(id, text)], "imitated": the number of other lines with
    `quote [` in them, "tail": the non-empty lines from the instructions line on (its own text first), "none" lines left out}. Nothing
    is judged here."""
    lines = (response or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((n for n, line in enumerate(lines) if line.strip()), None)
    if start is None:
        return {"answer": None, "prose": [], "quotes": [], "imitated": 0, "tail": []}
    if FIRST_LINE.fullmatch(lines[start].strip()) is None:
        return {"answer": None, "prose": lines, "quotes": [], "imitated": 0, "tail": []}
    answer = FIRST_LINE.fullmatch(lines[start].strip()).group(1).lower()
    body, tail = lines[start + 1:], []
    for n, line in enumerate(body):
        found = INSTRUCTIONS_LINE.fullmatch(line.strip()) if line.strip().lower().startswith(INSTRUCTIONS.lower()) else None
        if found:
            tail = [t.strip() for t in [found.group(1)] + body[n + 1:] if t.strip()]
            body = body[:n]
            break
    if len(tail) == 1 and collapse(tail[0]).rstrip(".").lower() == "none":
        tail = []
    elif tail and collapse(tail[0]).rstrip(".").lower() == "none":
        tail = tail[1:]                  # "none", and then text that says otherwise: the text is judged, the word is not
    prose, quotes, imitated = [], [], 0
    for line in body:
        quote = QUOTE_LINE.fullmatch(line)
        if quote:
            quotes.append((quote.group(1).strip(), quote.group(2)))
        elif QUOTE_WORD.search(line):
            imitated += 1
        else:
            prose.append(line.rstrip())
    return {"answer": answer, "prose": prose, "quotes": quotes, "imitated": imitated, "tail": tail}


def _names(line: str, ids: set) -> bool:
    return any(re.search(r"(?<![\w-])" + re.escape(i) + r"(?![\w-])", line) for i in ids)


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
    kept = [t for t in parsed["tail"] if "not followed" in t.lower() and _names(t, ids) and not QUOTE_WORD.search(t)]
    instructions = (INSTRUCTIONS + " " + kept[0] + "".join("\n" + t for t in kept[1:])) if kept else ""
    left_out = len(kept) != len(parsed["tail"])
    if parsed["answer"] == "not-found":
        return {"text": "\n\n".join([NOT_FOUND.format(read=read)] + ([instructions] if instructions else []) + footer),
                "outcome": "not-found", "flags": flags, "verified": 0}
    copies_flat = {i: collapse(t) for i, t in copies.items()}
    shown, verified = [], 0
    for source_id, passage in parsed["quotes"]:
        flat = collapse(passage)
        if source_id not in ids:
            flags.append("UNKNOWN_SOURCE")
            shown.append(f'{UNKNOWN_SOURCE.format(id=source_id)} "{passage}"')
        elif len(passage) > QUOTE_MAX:
            flags.append("QUOTE_TOO_LONG")
            shown.append(f'{QUOTE_TOO_LONG.format(id=source_id)} "{passage[:QUOTE_MAX]}..."')
        elif len(flat) < QUOTE_MIN_CHARS and len(flat.split()) < QUOTE_MIN_WORDS:
            flags.append("QUOTE_TOO_SHORT")
            shown.append(f'{QUOTE_TOO_SHORT.format(id=source_id)} "{passage}"')
        elif flat in copies_flat.get(source_id, ""):
            verified += 1
            shown.append(QUOTE_CHECKED.format(id=source_id, text=passage))
        else:
            flags.append("QUOTE_NOT_FOUND")
            shown.append(f'{QUOTE_NOT_FOUND.format(id=source_id)} "{passage}"')
    prose = "\n".join(parsed["prose"]).strip()
    unknown = [i for i in dict.fromkeys(BRACKET.findall(prose)) if i not in ids and not i.isdigit()]
    notes = [UNKNOWN_SOURCE.format(id=i) for i in unknown]
    if unknown:
        flags.append("UNKNOWN_SOURCE")
    if parsed["imitated"]:
        flags.append("QUOTE_IMITATED")
        notes.append(QUOTE_IMITATED)
    if left_out:
        flags.append("AFTER_INSTRUCTIONS")
        notes.append(AFTER_INSTRUCTIONS)
    if verified == 0:
        flags.append("UNVERIFIED")
        notes.append(UNVERIFIED)
    pieces = [p for p in (prose, "\n".join(shown), "\n".join(notes), instructions) if p]
    text = "\n\n".join(pieces + [READ.format(read=read), *footer])
    return {"text": text, "outcome": parsed["answer"], "flags": list(dict.fromkeys(flags)), "verified": verified}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

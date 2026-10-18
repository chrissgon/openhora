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
     found in its source's prepared copy (Unicode NFC, white space collapsed) and is at least QUOTE_MIN_CHARS characters AND
     QUOTE_MIN_WORDS words long is printed by code as `Checked quote [<id>]: "..."`, a form only code writes; any other quote is shown
     after a sentence that says what is wrong with it (QUOTE_NOT_FOUND, QUOTE_TOO_SHORT, QUOTE_TOO_LONG, UNKNOWN_SOURCE).
  3. Any other line that has `quote [` in it, or whose start is the opening of a checked quote (`checked quote`, and the same words of
     every other language of the phrase table, runtime/phrases.py: the form code writes is translated, so the check reads all of them), is
     left out of the answer and flagged QUOTE_IMITATED.
     The line is compared after NFKC, with the Unicode format characters (zero-width space and the like) removed, the look-alike
     letters of Cyrillic and Greek folded to Latin and the case folded (fold()), so that `Checked quоte` (a Cyrillic o), a zero-width
     space and a full-width bracket do not pass.
  4. A `[<id>]` of the form of a source id that the run was not given is flagged UNKNOWN_SOURCE (`[1]`, a footnote, is not).
  5. `found` or `partial` with no verified quote: UNVERIFIED.
  6. `not-found`: the model's prose is dropped; only NOT_FOUND, the instructions lines and the footer are sent.
  7. After the instructions line the reply keeps only lines that name a source the run was given, say `not followed` and carry a
     quoted passage (INSTRUCTION_MIN_WORDS words or more) that is in the copy of the source they name; every other line there is left
     out and flagged (AFTER_INSTRUCTIONS for a line of another form, INSTRUCTION_UNVERIFIED for one whose passage is not in its source).
     A line that is kept is written again by code, `[<id>] "<the passage>" (not followed)`: none of the model's other words reaches the person.
  8. What is shown is cleaned (clean()): NFC, with every Unicode format character (Cf) and the default-ignorable code points (the combining
     grapheme joiner, the Hangul fillers, the variation selectors, the tag characters) removed. The other combining marks (Mn) stay: the
     vowel signs and the virama of Devanagari, the vowel marks of Thai and the accents with no precomposed letter are part of the words of
     those languages. The imitation check (fold()) drops every combining mark, so that they cannot hide the form code writes. A line that holds a text-direction control (U+202A to U+202E, U+2066 to U+2069, U+200E, U+200F, U+061C) is left
     out and flagged BIDI_CONTROL, since such a character can make a line read differently from how it is stored.

Code appends the footer: READ (each source and version read) and, when the run is not proven, UNPROVEN. The sentences are the phrase
table's (runtime/phrases.py, package LR-1) and `check` says them in the project's language (`cfg`); the form the skill writes, and the
`Instructions found in external content:` heading this module reads, stay English.

Standard library only. Runs on Python 3.9: python3 runtime/ask_reply.py --help
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder: the sentences, in the project's language)

QUOTE_MAX = 300
QUOTE_MIN_CHARS = 20
QUOTE_MIN_WORDS = 3
INSTRUCTION_MIN_WORDS = 2
ANSWERS = ("found", "partial", "not-found")

# The English sentences, kept under their old names; the phrase table (runtime/phrases.py) is their source and `check` says them in the project's language.
UNCHECKED = phrases.en("UNCHECKED")
UNKNOWN_SOURCE = phrases.en("UNKNOWN_SOURCE")
QUOTE_NOT_FOUND = phrases.en("QUOTE_NOT_FOUND")
QUOTE_TOO_LONG = phrases.en("QUOTE_TOO_LONG").replace("{max}", str(QUOTE_MAX))
QUOTE_TOO_SHORT = phrases.en("QUOTE_TOO_SHORT")
QUOTE_CHECKED = phrases.en("QUOTE_CHECKED")
QUOTE_IMITATED = phrases.en("QUOTE_IMITATED")
AFTER_INSTRUCTIONS = phrases.en("AFTER_INSTRUCTIONS")
INSTRUCTION_UNVERIFIED = phrases.en("INSTRUCTION_UNVERIFIED")
BIDI_LEFT_OUT = phrases.en("BIDI_LEFT_OUT")
INSTRUCTION_LINE = phrases.en("INSTRUCTION_LINE")
UNVERIFIED = phrases.en("UNVERIFIED")
NOT_FOUND = phrases.en("NOT_FOUND")
READ = phrases.en("READ")
UNPROVEN = phrases.en("UNPROVEN")
INSTRUCTIONS = phrases.en("INSTRUCTIONS")      # the line the SKILL writes (the form this module reads); the line code writes is the table's, in the project's language

FIRST_LINE = re.compile(r"Answer:\s*(found|partial|not-found)\s*\.?", re.I)
QUOTE_LINE = re.compile(r'[\s\-*•>]*Quote \[([^\]\n]*)\]:\s*["“](.*)["”]\s*', re.I)
QUOTE_WORD = re.compile(r"quote\s*\[")          # read on a folded line (fold() lowers the case)
QUOTED = re.compile(r'["\u201c]([^"\u201d\n]+)["\u201d]')
INSTRUCTIONS_LINE = re.compile(r"Instructions found in external content:[ \t]*(.*)", re.I)
BRACKET = re.compile(r"\[([a-z0-9][a-z0-9-]{0,39})\]")


# The letters of Cyrillic and Greek that look like a Latin one: after NFKC and case folding, each is read as the Latin letter.
CONFUSABLES = str.maketrans({
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0445": "x", "\u0443": "y", "\u0456": "i",
    "\u0458": "j", "\u0455": "s", "\u0501": "d", "\u051b": "q", "\u051d": "w", "\u04bb": "h", "\u043a": "k", "\u043c": "m",
    "\u0442": "t", "\u043d": "h", "\u0432": "b", "\u0491": "r",
    "\u03b1": "a", "\u03b5": "e", "\u03bf": "o", "\u03c1": "p", "\u03bd": "v", "\u03c5": "u", "\u03b9": "i", "\u03ba": "k",
    "\u03c4": "t", "\u03c7": "x", "\u03b3": "y", "\u03b2": "b", "\u03b7": "n", "\u03c9": "w",
    # Armenian
    "\u0585": "o", "\u0578": "n", "\u057d": "u", "\u0570": "h", "\u0581": "g", "\u0566": "q", "\u0561": "w",
    # Cherokee (case folding turns its small letters into these capitals)
    "\u13aa": "a", "\u13f4": "b", "\u13df": "c", "\u13a0": "d", "\u13ac": "e", "\u13c0": "g", "\u13bb": "h", "\u13d6": "i",
    "\u13ab": "j", "\u13e6": "k", "\u13de": "l", "\u13b7": "m", "\u13da": "s", "\u13a2": "t", "\u13d9": "v", "\u13b3": "w",
    "\u13a9": "y", "\u13c3": "z", "\u13e2": "p", "\u13a1": "r", "\u13ee": "x",
    # Latin small capitals
    "\u1d00": "a", "\u0299": "b", "\u1d04": "c", "\u1d05": "d", "\u1d07": "e", "\ua730": "f", "\u0262": "g", "\u029c": "h",
    "\u026a": "i", "\u1d0a": "j", "\u1d0b": "k", "\u029f": "l", "\u1d0d": "m", "\u0274": "n", "\u1d0f": "o", "\u1d18": "p",
    "\u0280": "r", "\ua731": "s", "\u1d1b": "t", "\u1d1c": "u", "\u1d20": "v", "\u1d21": "w", "\u028f": "y", "\u1d22": "z",
})
BIDI = re.compile("[\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c]")
IGNORABLE = frozenset([0x115F, 0x1160, 0x3164, 0xFFA0, 0x034F, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180E, 0x180F])


def invisible(c: str) -> bool:
    """A character the reader does not see: format (Cf) and the default-ignorable code points. Never a combining mark that is part of a letter."""
    n = ord(c)
    return unicodedata.category(c) == "Cf" or n in IGNORABLE or 0xFE00 <= n <= 0xFE0F or 0xE0000 <= n <= 0xE0FFF


def clean(text: str) -> str:
    """The text as it may be shown: NFC, with every invisible character removed and the combining marks kept (see the module's text, rule 8)."""
    return "".join(c for c in unicodedata.normalize("NFC", str(text)) if not invisible(c))


def fold(text: str) -> str:
    """A line as the check for an imitated quote reads it: NFKD, every invisible character and every combining mark removed (format characters,
    the fillers, the variation selectors), case folded, the look-alike letters of Cyrillic, Greek, Armenian, Cherokee and the Latin small
    capitals read as Latin."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", str(text)) if not invisible(c) and unicodedata.category(c) != "Mn")
    return plain.casefold().translate(CONFUSABLES)


CHECKED_HEADS = tuple(dict.fromkeys(h for h in (fold(head) for head in phrases.heads("QUOTE_CHECKED")) if h))   # `checked quote`, `citacao verificada`: the opening of the line code writes, in every language of the table


def imitates(line: str) -> bool:
    """Whether a line, folded, has `quote [` in it, starts with the opening of a checked quote or has that opening and a `[` in it: what only
    code may write. The opening is the phrase table's, in EVERY language of the table whatever the project's language is (a model asked for a
    Portuguese answer may write the English form and the reverse), so a translated form cannot be imitated."""
    seen = fold(line)
    start = seen.lstrip(" \t-*>\u2022#|")
    return bool(QUOTE_WORD.search(seen)) or any(start.startswith(head) or head + " [" in seen for head in CHECKED_HEADS)


def collapse(text: str) -> str:
    """The cleaned text (clean()), then every run of white space one space: both sides of a comparison with a source are read this way."""
    return " ".join(clean(text).split())


def read_line(given: list, cfg=None) -> str:
    """'a (version 1), b (version 2)' for the sources the run received (the word for `version` is the language's own)."""
    return ", ".join(phrases.text("READ_VERSION", cfg, source=g["source"], version=g["version"]) for g in given)


def parse(response: str) -> dict:
    """{"answer": a word of ANSWERS or None, "prose": [lines], "quotes": [(id, text)], "imitated": the number of other lines with
    `quote [` in them, "tail": the non-empty lines from the instructions line on (its own text first), "none" lines left out}. Nothing
    is judged here."""
    lines = (response or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = next((n for n, line in enumerate(lines) if line.strip()), None)
    if start is None:
        return {"answer": None, "prose": [], "quotes": [], "imitated": 0, "bidi": 0, "tail": []}
    if FIRST_LINE.fullmatch(lines[start].strip()) is None:
        return {"answer": None, "prose": lines, "quotes": [], "imitated": 0, "bidi": 0, "tail": []}
    answer = FIRST_LINE.fullmatch(lines[start].strip()).group(1).lower()
    bidi = sum(1 for line in lines[start + 1:] if BIDI.search(line))
    body, tail = [clean(line) for line in lines[start + 1:] if not BIDI.search(line)], []
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
        elif imitates(line):
            imitated += 1
        else:
            prose.append(line.rstrip())
    return {"answer": answer, "prose": prose, "quotes": quotes, "imitated": imitated, "bidi": bidi, "tail": tail}


def _verified_instruction(line: str, ids: set, copies_flat: dict, cfg=None):
    """The instruction line as code writes it, `[<id>] "<passage>" (not followed)`, for the first quoted passage of INSTRUCTION_MIN_WORDS words
    or more that is in the copy of a source the line names; None when there is none."""
    named = [i for i in sorted(ids) if _names(line, {i})]
    for passage in QUOTED.findall(line):
        flat = collapse(passage)
        for source_id in named:
            if len(flat.split()) >= INSTRUCTION_MIN_WORDS and flat in copies_flat.get(source_id, ""):
                return phrases.text("INSTRUCTION_LINE", cfg, id=source_id, passage=flat)
    return None


def _names(line: str, ids: set) -> bool:
    return any(re.search(r"(?<![\w-])" + re.escape(i) + r"(?![\w-])", line) for i in ids)


def check(response: str, given: list, copies: dict, proven: bool, skill: str, model: str, cfg=None) -> dict:
    """The reply the person is sent and what was found: {"text", "outcome": "found" | "partial" | "not-found" | "unchecked",
    "flags": [words], "verified": the number of quotes found in their sources}. `given` is [{"source", "version"}] of the copies
    the run received, `copies` {source id: the text of that copy}, `proven` whether the run was proven (autonomy "proven"). `cfg` carries
    the project's `language` (runtime/phrases.py): the sentences code adds are said in it; the form the skill writes is English."""
    say = lambda key, **fields: phrases.text(key, cfg, **fields)  # noqa: E731
    read = read_line(given, cfg)
    footer = [] if proven else [say("UNPROVEN", skill=skill, model=model)]
    parsed = parse(response)
    ids = {g["source"] for g in given}
    flags = []
    if parsed["answer"] is None:
        text = "\n\n".join([say("UNCHECKED"), clean(response or "").strip() or say("EMPTY_REPLY"), say("READ", read=read), *footer])
        return {"text": text, "outcome": "unchecked", "flags": ["UNCHECKED"], "verified": 0}
    copies_flat = {i: collapse(t) for i, t in copies.items()}
    kept, other, unverified = [], 0, 0
    for line in parsed["tail"]:
        form = "not followed" in line.lower() and _names(line, ids) and not imitates(line)
        if not form:
            other += 1
        else:
            written = _verified_instruction(line, ids, copies_flat, cfg)
            if written:
                kept.append(written)
            else:
                unverified += 1
    instructions = (say("INSTRUCTIONS") + " " + kept[0] + "".join("\n" + t for t in kept[1:])) if kept else ""
    if parsed["bidi"]:
        flags.append("BIDI_CONTROL")
    if other:
        flags.append("AFTER_INSTRUCTIONS")
    if unverified:
        flags.append("INSTRUCTION_UNVERIFIED")
    if parsed["answer"] == "not-found":
        return {"text": "\n\n".join([say("NOT_FOUND", read=read)] + ([instructions] if instructions else []) + footer),
                "outcome": "not-found", "flags": flags, "verified": 0}
    shown, verified = [], 0
    for source_id, passage in parsed["quotes"]:
        flat = collapse(passage)
        if source_id not in ids:
            flags.append("UNKNOWN_SOURCE")
            shown.append(f'{say("UNKNOWN_SOURCE", id=source_id)} "{passage}"')
        elif len(passage) > QUOTE_MAX:
            flags.append("QUOTE_TOO_LONG")
            shown.append(f'{say("QUOTE_TOO_LONG", max=QUOTE_MAX, id=source_id)} "{passage[:QUOTE_MAX]}..."')
        elif len(flat) < QUOTE_MIN_CHARS or len(flat.split()) < QUOTE_MIN_WORDS:
            flags.append("QUOTE_TOO_SHORT")
            shown.append(f'{say("QUOTE_TOO_SHORT", id=source_id)} "{passage}"')
        elif flat in copies_flat.get(source_id, ""):
            verified += 1
            shown.append(say("QUOTE_CHECKED", id=source_id, text=passage))
        else:
            flags.append("QUOTE_NOT_FOUND")
            shown.append(f'{say("QUOTE_NOT_FOUND", id=source_id)} "{passage}"')
    prose = "\n".join(parsed["prose"]).strip()
    unknown = [i for i in dict.fromkeys(BRACKET.findall(prose)) if i not in ids and not i.isdigit()]
    notes = [say("UNKNOWN_SOURCE", id=i) for i in unknown]
    if unknown:
        flags.append("UNKNOWN_SOURCE")
    if parsed["imitated"]:
        flags.append("QUOTE_IMITATED")
        notes.append(say("QUOTE_IMITATED"))
    if parsed["bidi"]:
        notes.append(say("BIDI_LEFT_OUT"))
    if other:
        notes.append(say("AFTER_INSTRUCTIONS"))
    if unverified:
        notes.append(say("INSTRUCTION_UNVERIFIED"))
    if verified == 0:
        flags.append("UNVERIFIED")
        notes.append(say("UNVERIFIED"))
    pieces = [p for p in (prose, "\n".join(shown), "\n".join(notes), instructions) if p]
    text = "\n\n".join(pieces + [say("READ", read=read), *footer])
    return {"text": text, "outcome": parsed["answer"], "flags": list(dict.fromkeys(flags)), "verified": verified}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

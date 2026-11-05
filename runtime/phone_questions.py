#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The router's questions as a phone shows them (slice S9, limit L62): a pure renderer, no model, no store, no network.

The router asks in the form its skill defines (`Q<n>: <question> Recommended: <answer>, because <reason>`, the `Recommended:` part sometimes on a line of its own).
On a messaging app that form read badly: the lines were glued together, the labels were English in a Portuguese chat, a stray code fence closed the text, and the
name of a flow or a skill (`flow-brand`) was an identifier the person never saw. `view(reply, cfg)` is what `phrases.asked_view` returns now:

    Perguntas:                         (en: "Questions:")

    1. <question>
       Recomendado: <answer>           (en: "Recommended:")

    2. <question>

with one blank line between the items. The questions are read by `phrases.read_question` (the one reader of the router's template, with the skipping of the section of
instructions found in external content); this module only renders what it returns. Text it cannot read as questions comes back as `clean(reply)`.

`clean(text, cfg)` is the clean-up of any router text on a phone: it removes code fences (a line that is only a fence, then any fence left in a line), collapses
blank lines to one, says the router's fixed English labels (Route, Why, Next, Question, Recommended) in the project's language, replaces the identifier of an installed
skill or flow with a plain label (the closed family `PQ_NAME_` of the phrase table; a known name with no label is dropped, with the parentheses around it) and removes what
a phone never shows: a slash command, a path to a file and a requirement class (`integration:calendar`). The stored text is never changed: the page, the terminal and a
card's hash keep the whole reply.

Standard library only. Runs on Python 3.9: python3 runtime/phone_questions.py --help
"""
from __future__ import annotations

import argparse
import functools
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder: the sentences; phrases imports this module only inside asked_view)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_PREFIX = "PQ_NAME_"
LABELS = ("Route", "Why", "Next", "Question", "Recommended")      # the fixed labels of the router's reply that a phone says in the language
QUESTION_HEAD = re.compile(r"^Q[0-9]+:\s*")
RECOMMENDED_SPLIT = re.compile(r"\s*\**Recommended\**:\s*", re.I)
FENCE_LINE = re.compile(r"^\s*```[A-Za-z0-9_+-]*\s*$")
LABEL_AT_START = re.compile(r"^(\s*(?:[-*]\s+)?\**)(" + "|".join(LABELS) + r")(\**:)")
SLASH_COMMAND = re.compile(r"(?<!\S)/[a-z][a-z0-9-]*(?:[ \t]+<[^>\n]*>)?")
PATH = re.compile(r"(?<!\S)(?:[\w.-]+(?:/[\w.-]+)+\.[A-Za-z0-9]{1,5}|(?:docs|skills|flows|runtime|providers|contracts)/[\w./-]*)")
REQUIREMENT_CLASS = re.compile(r"\b(?:integration|generator|publisher|provider|messenger):[a-z][\w-]*")


def name_key(name: str) -> str:
    """The phrase key of the plain label of an installed skill or flow: flow-brand -> PQ_NAME_FLOW_BRAND."""
    return NAME_PREFIX + name.upper().replace("-", "_")


@functools.lru_cache(maxsize=1)
def known_names() -> tuple:
    """The identifiers a phone never shows, longest first: the names with a label in the phrase table, the folders of `skills/` and the files of `flows/` (as `flow-<name>`)
    of the checkout this module runs from. A checkout without them still knows the labelled names."""
    names = {key[len(NAME_PREFIX):].lower().replace("_", "-") for key in phrases.TABLE["en"] if key.startswith(NAME_PREFIX)}
    for folder, prefix, suffix in (("skills", "", ""), ("flows", "flow-", ".json")):
        path = os.path.join(ROOT, folder)
        if os.path.isdir(path):
            for entry in os.listdir(path):
                if suffix and entry.endswith(suffix):
                    names.add(prefix + entry[:-len(suffix)])
                elif not suffix and os.path.isfile(os.path.join(path, entry, "SKILL.md")):
                    names.add(entry)
    return tuple(sorted(names, key=lambda n: (-len(n), n)))


@functools.lru_cache(maxsize=1)
def _identifier_pattern():
    names = "|".join(re.escape(n) for n in known_names())
    return re.compile(r"(?P<sp>[ \t]*)(?P<open>\([ \t]*)?`?(?<![\w-])(?P<name>" + names + r")(?![\w-])`?(?P<close>[ \t]*\))?")


def _name(match, cfg) -> str:
    key = name_key(match.group("name"))
    label = phrases.text(key, cfg) if key in phrases.TABLE["en"] else ""
    opened, closed = match.group("open"), match.group("close")
    if label:
        return match.group("sp") + (opened or "") + label + (closed or "")
    if opened and closed:
        return ""      # "(core-foo)": the name and the parentheses around it go
    return match.group("sp") + (opened or "") + (closed or "")


def _tidy(line: str) -> str:
    """The spaces a removal left: a run of spaces inside the line, a space before a mark, an empty or a dangling parenthesis."""
    line = re.sub(r"\([ \t]*\)", "", line)
    line = re.sub(r"\([ \t]*([,;:])[ \t]*", "(", line)
    line = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", line)
    return re.sub(r"[ \t]+([,.;:?!])", r"\1", line).rstrip(" \t")


def scrub(line: str, cfg=None) -> str:
    """One line of router text for a phone: no code fence, no identifier of a skill or flow, no slash command, path or requirement class."""
    changed = line
    changed = changed.replace("```", "")
    changed = _identifier_pattern().sub(lambda m: _name(m, cfg), changed)
    for pattern in (SLASH_COMMAND, PATH, REQUIREMENT_CLASS):
        changed = pattern.sub("", changed)
    return _tidy(changed) if changed != line else line


def clean(text, cfg=None):
    """Router text for a phone (see the module): fences gone, blank lines collapsed to one, labels and identifiers said plainly. Anything that is not text comes back."""
    if not isinstance(text, str):
        return text
    out, blank = [], False
    for line in text.split("\n"):
        if FENCE_LINE.match(line):
            continue
        line = scrub(line, cfg)
        line = LABEL_AT_START.sub(lambda m: m.group(1) + phrases.text("PQ_LABEL_" + m.group(2).upper(), cfg) + m.group(3), line)
        if not line.strip():
            if blank:
                continue
            line, blank = "", True
        else:
            blank = False
        out.append(line)
    return "\n".join(out)


def parse(question: str):
    """One question of `phrases.read_question` as (question, recommended) with each wrapped line joined by a space; None when no question is left once the `Q<n>:` mark goes."""
    joined = " ".join(part.strip() for part in question.split("\n") if part.strip())
    parts = RECOMMENDED_SPLIT.split(QUESTION_HEAD.sub("", joined, count=1))
    asked, answer = parts[0].strip(), " ".join(p.strip() for p in parts[1:] if p.strip())
    return (asked, answer) if asked else None


def render(items, quoted: bool = False, cfg=None) -> str:
    """The numbered layout of the module's docstring for [(question, recommended), ...], and, when the reply quoted instructions of external content, the one note line."""
    label = phrases.text("PQ_LABEL_RECOMMENDED", cfg) + ":"
    blocks = []
    for number, (asked, answer) in enumerate(items, 1):
        block = f"{number}. {clean(asked, cfg)}"
        if answer:
            block += f"\n   {label} {clean(answer, cfg)}"
        blocks.append(block)
    note = "\n\n" + phrases.text("ROUTER_QUOTED_NOTE", cfg) if quoted else ""
    return phrases.text("ROUTER_ASKS_FRAME", cfg) + "\n\n" + "\n\n".join(blocks) + note


def view(reply, cfg=None):
    """What a messaging app shows of a router reply that asks: the numbered questions, or, when the reply holds no question that can be read, the reply cleaned."""
    if not isinstance(reply, str):
        return reply
    read = phrases.read_question(reply)
    items = [parse(q) for q in read["questions"]]
    if not items or None in items:
        return clean(reply, cfg)
    return render(items, read["quoted"], cfg)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print a router reply as a messaging app shows it (the file, or the standard input).")
    parser.add_argument("file", nargs="?", help="a file holding the router's reply; the standard input when absent")
    parser.add_argument("--language", default="en", help="the project's language tag (en, pt-BR)")
    args = parser.parse_args(argv)
    text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    print(view(text, {"language": args.language}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What a phone never reads (package LIVE-2): a shell command of this platform, or a path of this machine, in a message sent to a messaging app.

The person on a messaging app has no terminal and no folder to open: a sentence that tells them to run `uv run ... cli.py ...` is nonsense, and a path is the layout
of a machine they may not even sit at. So the rule is two layers (contracts/runtime.md, limit L62):

  1. the sentences are written for the phone: a reply that points to somewhere else says WHAT is done and WHERE, in one plain sentence and the page link
     (`messaging.page_url`, else "on the platform's page"), by a phrase key of the family PHONE_ (runtime/phrases.py); the terminal, the page and the conversation keep
     the exact command, because there it can be run;
  2. this module is the net under them (principle 11: a rule that must hold is code) for the text the PLATFORM writes that is not built from a phrase key: the error text
     of the operations layer (`Bridge.reply(..., guard=True)`). `guard_message` cuts what looks like a command line of this platform or a path from the text, the footer and
     the document, says once that the rest is done on the page, and records an event a test can read (`EVENTS`; the text itself is never kept or logged, since it may be
     private). It is never applied to what is quoted from the person's data (a card's body, a calendar title, a mail's subject and text, a file's text, a plan's steps, a quote
     of an answer, a reminder's words): a person's own `uv run demo` or `/Users/ana/x.pdf` is theirs, and a card must show what is approved exactly as it is.

What counts. A COMMAND is a line of the platform's shell: `uv run ...`, `python3 .../cli.py ...` (or the other scripts of runtime/), `keyring set openhora ...`, and a
flag only this platform's shell has (`--project`, `--sha256`, `--base-sha256`, `--widen`, `--adopt-sources`, `--text-file`, `--content-file`, `--consent`), each to
the end of its line. A PATH is an absolute path of two or more parts (`/a/b`), a path under the home folder (`~/b`) or a Windows drive path (`C:\\`). A slash command a
messaging app has (`/approve 12`, `/pending`), a URL, a relative path (`docs/plan.md`) and a bare verb (`accept-config`) are not found. A command or a path is cut and the
rest of its line stays (a line left blank is dropped).

A card is never edited by this net: `messaging_cards.build` shows the body exactly (minus the private-line rules and the platform's own two frame lines for a terminal), so
the person approves what they read.

  find(text)                  the (kind, span) of each command and path in the text, in order
  clean(text)                 (text without them, kinds found, whether a line that stayed was changed)
  guard_message(message, cfg, note=None)   the message as it may be sent, with the sentence that points to the page added once when something was cut

Standard library only. Runs on Python 3.9: python3 runtime/messaging_guard.py --help
"""
from __future__ import annotations

import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phrases  # noqa: E402  (the same folder: the sentence that points to the page, in the project's language)

FLAGS = ("project", "sha256", "base-sha256", "widen", "adopt-sources", "text-file", "content-file", "consent")      # flags only this platform's shell has
COMMAND = re.compile("|".join([
    r"\buv\s+run\b[^\n]*",
    r"\bpython3?\s+\S*\.py\b[^\n]*",                               # `python3 <anything>.py ...`: this platform's scripts are run so
    r"\b(?:runtime|providers|scripts)/[\w./-]*\.py\b[^\n]*",       # a script of this repository named with its folder
    r"\bkeyring\s+set\s+openhora\b[^\n]*",
    r"(?<![\w-])--(?:" + "|".join(FLAGS) + r")\b[^\n]*",
]))
PATH = re.compile("|".join([
    r"(?<![\w:/.~-])/(?:[\w.@+-]+/)+[\w.@+-]*",                    # /a/b, /a/b/c.txt, /a/ : an absolute path of two or more parts
    r"(?<![\w])~/[^\s'\"`)>\]]*",                                  # ~/b
    r"(?<![\w])[A-Za-z]:\\[^\s'\"`)>\]]*",                         # C:\b
]))
EVENTS = collections.deque(maxlen=200)      # what the net cut, newest last: {"kinds": [...]}; a test reads it, nothing else does, and it holds no text


def find(text) -> list:
    """The (kind, span) of each command and each path in `text`, in order: kind `command` or `path`. A path inside a command is part of the command."""
    if not isinstance(text, str) or not text:
        return []
    found = [("command", m.span()) for m in COMMAND.finditer(text)]
    for m in PATH.finditer(text):
        if not any(s <= m.start() < e for _kind, (s, e) in found):
            found.append(("path", m.span()))
    return sorted(found, key=lambda item: item[1][0])


def clean(text):
    """(cleaned text, kinds, altered). Each command and each path is cut from its line, the rest of the line stays, and a line left blank by the cut is dropped. A code span
    (backticks) that held a cut part is cut with it. `kinds` is the sorted list of the kinds found; `altered` is true when a line that stayed lost words."""
    if not isinstance(text, str) or not find(text):
        return text, [], False
    kinds, altered, out = set(), False, []
    for line in text.split("\n"):
        hits = find(line)
        if not hits:
            out.append(line)
            continue
        kinds.update(kind for kind, _span in hits)
        rest, last = [], 0
        for kind, (start, end) in hits:
            rest.append(re.sub(r"`+$", "", line[last:start]) if kind == "command" else line[last:start])      # the fence a command was wrapped in goes with it
            last = end
        rest.append(line[last:])
        stripped = re.sub(r"`\s*`", "", "".join(rest))
        stripped = re.sub(r"\s{2,}", " ", stripped).rstrip()
        if not stripped.strip():
            continue
        altered = True
        out.append(stripped)
    return "\n".join(out), sorted(kinds), altered


def sentence(cfg) -> str:
    """The one sentence added to a message the net cut: the rest is done on the page (with its link when the project has one)."""
    return phrases.phone("PHONE_STRIPPED", cfg)


def guard_message(message: dict, cfg=None, note=None) -> dict:
    """The message as it may be sent to a messaging app. The text, the footer lines and the document (name and text) lose every command and path; when anything was cut,
    the sentence that points to the page is added to the text once, and the footer, which the text no longer ends with, is not handed over (the same rule as the home-folder
    filter). `note(kinds)` is called once when something was cut (the bridge logs the kinds, never the text), and an event is recorded in EVENTS. A message with nothing
    to cut comes back as it was."""
    kinds = set()
    out = dict(message)
    text, found, _altered = clean(out.get("text"))
    if found:
        kinds.update(found)
        out["text"] = text.rstrip() + "\n" + sentence(cfg)
        out.pop("footer", None)
    elif isinstance(out.get("footer"), list):
        lines = []
        for line in out["footer"]:
            cleaned, found, _altered = clean(line)
            kinds.update(found)
            lines.append(cleaned)
        if kinds:      # unreachable when the text carried none of them (the footer ends the text), kept so that a provider's footer is never trusted
            out.pop("footer", None)
    document = out.get("document")
    if isinstance(document, dict):
        name, name_found, _a = clean(document.get("name"))
        body, body_found, _b = clean(document.get("text"))
        if name_found or body_found:
            kinds.update(name_found + body_found)
            out["document"] = {**document, "name": name, "text": body}
    if kinds:
        EVENTS.append({"kinds": sorted(kinds)})
        if note is not None:
            note(sorted(kinds))
    return out


if __name__ == "__main__":
    if sys.argv[1:] in (["--help"], ["-h"]):
        print(__doc__.strip())
        sys.exit(0)
    print(__doc__.strip(), file=sys.stderr)
    sys.exit(2)

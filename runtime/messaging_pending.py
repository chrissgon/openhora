#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The line a question gets in `/pending` on a messaging app (slice S14, limit L62): what is asked, in plain words, never the router's internals.

The list used to say `#14 question: The router asks`: the kind and the title the code gave the decision, which a person reads as nothing (and "the route was not recognised" is
an internal fact). Now a question is `#<id> question from the assistant: <the first line of what is asked>` (the first question of the router's template, or the first line of
a skill's question, cleaned as a phone shows it by `phone_questions.clean`, cut at 80 characters), a request the router could not read is `#<id> request not understood`, and a list
that holds a question ends with the one line that says how to dismiss it. Every other kind keeps its line. The page and the terminal list what they always did.

  line(item, cfg)       the line of a pending decision of kind `question`, or None for any other kind (the caller keeps its own line)
  footer(items, caps, cfg)   the line that says how to dismiss a question, when a question is listed; "" otherwise

Standard library only. Runs on Python 3.9: python3 runtime/messaging_pending.py --help
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import phone_questions  # noqa: E402  (the same folder)
import phrases  # noqa: E402

CUT = 80      # characters of the question that /pending shows


def unclassified(item: dict) -> bool:
    """Whether the decision is the question of a request the router could not read (ops._not_recognised: the ending `unclassified`, or its title)."""
    payload = item.get("payload")
    return (isinstance(payload, dict) and payload.get("ending") == "unclassified") or item.get("title") == phrases.en("TITLE_ROUTE_UNRECOGNISED")


def asked(item: dict, cfg=None) -> str:
    """The first line of what the question asks: the first question of the router's template when there is one, else the first non-blank line of the body; cleaned as a phone
    shows it and cut at CUT characters (at a word when one ends in the last twenty). "" when nothing is left."""
    body = item.get("body") if isinstance(item.get("body"), str) else ""
    parsed = [phone_questions.parse(q) for q in phrases.read_question(body)["questions"]]
    first = next((p[0] for p in parsed if p), body)
    cleaned = phone_questions.clean(first, cfg)
    line = next((" ".join(part.split()) for part in str(cleaned).split("\n") if part.strip()), "")
    if len(line) <= CUT:
        return line
    cut = line[:CUT - 1]
    return (cut.rsplit(" ", 1)[0] if " " in cut[-20:] else cut).rstrip(" ,.;:") + "…"


def line(item: dict, cfg=None):
    """The line of a listed question (see the module's text); None when the decision is not a question or says nothing a person could read."""
    if item.get("kind") != "question":
        return None
    if unclassified(item):
        return phrases.text("PEND_NOT_UNDERSTOOD", cfg, id=item["id"])
    said = asked(item, cfg)
    return phrases.text("PEND_QUESTION", cfg, id=item["id"], text=said) if said else None


def footer(listed: list, caps: dict, cfg=None) -> str:
    """The line that says how to dismiss a question, when one of `listed` (the decisions as the list shows them) is a question; a platform whose acts are replies (e-mail) says
    to reply to the question's message."""
    if not any(i.get("kind") == "question" for i in listed):
        return ""
    return phrases.text("PEND_DISMISS_REPLY" if (caps or {}).get("actions_need_reply") else "PEND_DISMISS_TYPED", cfg)


def main(argv=None) -> int:
    print(__doc__.strip(), file=sys.stdout if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else sys.stderr)
    return 0 if (argv or sys.argv[1:]) in (["--help"], ["-h"]) else 2


if __name__ == "__main__":
    sys.exit(main())

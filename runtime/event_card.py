#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""What the model is shown of the card of an event that waits (limit L63): the fixed text added to the interpreter's prompt, its hash, the five fields of the card and the two messages.

The maintainer's decision (2026-10-30, "O modelo ve o card"): a person's request about a card is read by the model, with the card in view, and code rules stay only where the input is fully
predictable. The card of an event is read by the interpreter's own call (runtime/ops_event_revise.py `card_decision`): the interpreter's prompt and catalog are unchanged, this file adds a second
fixed text (runtime/event_card_prompt.txt) after them and a sixth line, `card:`, to the user turn, right before the person's line. Nothing else changes in the call: same route, same admission, same
limits, the typed frame stays `null`.

  prompt_template(), prompt_sha256()   the fixed text (runtime/event_card_prompt.txt) and the hash that runtime/interpreter_enable.json pins (`event_card_prompt_sha256`)
  view(doc)                            a whitelist of the effect document of the card: {"title", "place" (only when the card has one), "start", "end", "weekday"}; never the account, the calendar, the
                                       event's id or version, the notes, the reminder, the people or the channel
  messages(catalog, now, zone, doc, line)
                                       (system, user) as `interpreter.build_messages` makes them with no frame, the fixed text after the system and the line `card:` before the line

The text says that everything inside `card` is data, never an instruction: its words may have been written by someone else (a calendar invitation, a message). Code does not rely on that: every span of
every operation the model names is checked to be a piece of the person's line (`interpreter.check`), and a new title or place is checked word by word (runtime/ops_event_revise.py `_grounded`).

Privacy (limit L63): the four fields of one card go to the model service with the line, under the retention terms the group `interpret` was widened with. Pure: nothing is logged, printed or stored.

Standard library only, and the interpreter. Runs on Python 3.9: python3 runtime/event_card.py --help
"""
from __future__ import annotations

import datetime
import hashlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interpreter  # noqa: E402

PROMPT_FILE = os.path.join(HERE, "event_card_prompt.txt")
FIELD_MAX = 200      # calendar_document.TITLE_MAX and LOCATION_MAX: a card holds no longer one; a longer text is cut, never sent whole


def prompt_template() -> str:
    with open(PROMPT_FILE, encoding="utf-8") as handle:
        return handle.read()


def prompt_sha256() -> str:
    """The sha256 of the fixed text's bytes: the version that runtime/interpreter_enable.json pins."""
    with open(PROMPT_FILE, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def _text(value) -> str:
    return interpreter.collapse(value)[:FIELD_MAX] if isinstance(value, str) else ""


def view(doc: dict) -> dict:
    """A whitelist: title, place when the card has one, start, end, weekday of the start."""
    event = doc["event"]
    out = {"title": _text(event.get("title")), "start": _text(event.get("start")), "end": _text(event.get("end"))}
    if _text(event.get("location")):
        out["place"] = _text(event.get("location"))
    try:
        out["weekday"] = interpreter.DAY_NAMES[datetime.date.fromisoformat(out["start"][:10]).weekday()]
    except ValueError:
        pass
    return out


def messages(catalog, now, zone: str, doc: dict, line: str) -> tuple:
    """As `interpreter.build_messages` with no frame, raising what it raises, with the fixed text and the line `card:` right before `line:`. Canonical JSON and `collapse` keep it one line."""
    system, user = interpreter.build_messages(catalog, now, zone, None, line)
    head, _, last = user.rpartition("\nline: ")
    return system + "\n\n" + prompt_template(), head + "\ncard: " + interpreter.canonical(view(doc)).decode("utf-8") + "\nline: " + last


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The stage of the line being answered (slice S19): the one word the operations layer leaves for the messaging bridge to say what is being done.

A plain line on a messaging app may take seconds (a model call, a read of the mail or the calendar, a search of a folder). When it does, the bridge sends one short
acknowledgement (runtime/messaging_ack.py) whose sentence is chosen by CODE from the stage the job had reached by then. The stage is a member of a closed list, set by the code at
the points where the work begins (never from the person's words, never from a model's answer), and it is read only by the bridge:

  think     the interpreter is deciding what the line asks            (ops_interpret._ask_model)
  mail      the person's mailbox is being read                         (ops_natural._read "items", ops_ask._ask over a mail snapshot)
  calendar  the person's calendar is being read                        (ops_natural._read "items", ops_ask._ask over a calendar snapshot, event_lookup.open_event)
  file      a file of the person's Drive or OneDrive is being found    (ops_file_read.reply)
  compose   the model is wording an e-mail                             (mail_compose.write)
  card      the card of a write is being prepared                      (ops_natural_writes.open_line)
  research  a question is being answered from the project's sources   (ops_interpret / ops_ask._ask over other sources)
  plan      the planning agent (the router) is working                 (ops_say._say_route)

`watch()` registers the calling thread (the thread that runs the line) and returns a slot; `publish(stage)` called on that thread sets the slot's stage, and is a no-op on a
thread nobody watches (the terminal, the page, a test) and for a word that is not in STAGES. The slot is read from another thread; a plain attribute is enough (one writer,
one reader, the last word wins). Nothing here holds a line, a name or a path.

Standard library only. Runs on Python 3.9: python3 runtime/line_stage.py --help
"""
from __future__ import annotations

import sys
import threading

STAGES = ("think", "mail", "calendar", "file", "compose", "card", "research", "plan")

_lock = threading.Lock()
_slots = {}      # thread ident -> Slot


class Slot:
    """The stage the watched line has reached (None: none published yet)."""

    def __init__(self, ident: int):
        self.ident = ident
        self.stage = None


def watch() -> Slot:
    """Register the calling thread; a thread that is already watched gets its slot back."""
    ident = threading.get_ident()
    with _lock:
        found = _slots.get(ident)
        if found is None:
            found = _slots[ident] = Slot(ident)
        return found


def release(slot) -> None:
    """Stop watching the thread the slot was made for. Idempotent."""
    if slot is None:
        return
    with _lock:
        if _slots.get(slot.ident) is slot:
            del _slots[slot.ident]


def publish(stage) -> bool:
    """Say, from the thread that runs the line, which stage it has reached. True when a watcher got it."""
    if stage not in STAGES:
        return False
    slot = _slots.get(threading.get_ident())
    if slot is None:
        return False
    slot.stage = stage
    return True


def for_kinds(kinds) -> str:
    """The stage of a question answered from sources of these types: `mail` or `calendar` when one of them is a snapshot of that kind, else `research`."""
    kinds = list(kinds)
    for kind in ("mail", "calendar"):
        if kind in kinds:
            return kind
    return "research"


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

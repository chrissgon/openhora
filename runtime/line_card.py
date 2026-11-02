#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The card the line is about (ANY-QUESTION): the one number the messaging bridge leaves for the operations layer, on the thread that runs the line.

A plain line that arrives while a card is the last message the platform sent to the chat may be a question about that card ("where is this event?"). The bridge knows the card
(`Bridge.waiting_card`: whole, open, unchanged, the last message); the operations layer, which answers the question, is called in the same thread (`run_op` calls the operation in-process),
so the bridge leaves the card's number here for the duration of the call, and `ops_say.say` reads it into `extras["waiting_card"]`. It is the reverse of runtime/line_stage.py (which the
operations layer publishes and the bridge reads), on the same thread. A card is never decided, ended or changed through this number: it only says which card a question is about.

  hold(pending_id)   a context manager: inside it, `current()` on the calling thread is `pending_id` (a whole number of at least 1; anything else holds None); the earlier value comes back on exit, an exception included
  current()          the calling thread's number, or None

Nothing here holds a line, a name or a path. Standard library only. Runs on Python 3.9: python3 runtime/line_card.py --help
"""
from __future__ import annotations

import contextlib
import sys
import threading

_local = threading.local()


def current():
    """The number of the card the calling thread's line is about, or None."""
    return getattr(_local, "card", None)


@contextlib.contextmanager
def hold(pending_id):
    """Hold `pending_id` for the calling thread while the block runs (None unless it is an int of at least 1, a bool excluded); restore the earlier value on exit."""
    before = current()
    _local.card = pending_id if type(pending_id) is int and pending_id >= 1 else None
    try:
        yield
    finally:
        _local.card = before


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

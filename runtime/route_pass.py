#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The route pass (S41-11, SPEC-S41-11-BRAKE): what the decide leg of a line hands to the route leg so that the interpreter is asked once.

A plain line of a sender whom the interpreter reads runs in two legs (runtime/messaging_bridge.py, `decide` and `say_queue`). The first decides, with no model slot of the project; when the
interpreter says `route` (or `answer`: the line answers the router's question) nothing is stored, the line goes back unrouted with a pass, and the second leg, which takes the slot or waits for it,
runs the planning agent without asking the interpreter again.

    issue(project, sender, line, frame) -> id     a pass for this line of this sender in this project; `frame` is the word the interpreter's decision left ("new" or "answer")
    take(project, sender, line, id) -> {"frame"}  the pass once: None when it is missing, expired, already taken, or its project, sender or line differs

It holds the project, the sender, the sha256 of the line as the interpreter collapses it (blanks of one kind), the frame word and an expiry: never the line, a span or a model's text (limit L63),
in memory only, so a restart loses every pass (a kept line dies with the restart too: BQ-1). A pass that does not answer sends the line to the model as if there were none: at worst one more call,
never a route without a decision. Pure but for its own memory and clock; standard library only. Runs on Python 3.9: python3 runtime/route_pass.py --help
"""
from __future__ import annotations

import hashlib
import secrets
import sys
import threading
import time

EXPIRY = 1800.0      # seconds: the longest a line waits for the project (messaging_bridge.QUEUE_WAIT)
FRAMES = ("new", "answer")
MAX_PASSES = 200      # a bound on the memory: the oldest goes first

_lock = threading.Lock()
_passes = {}      # id -> (project, sender, sha256 of the line, frame, expires)
clock = time.monotonic


def digest(line: str) -> str:
    return hashlib.sha256(" ".join(str(line).split()).encode("utf-8")).hexdigest()


def issue(project: str, sender, line: str, frame: str = "new") -> str:
    if frame not in FRAMES:
        raise ValueError(f"a frame word is one of {FRAMES}")
    found = secrets.token_hex(8)
    with _lock:
        now = clock()
        for key in [k for k, row in _passes.items() if row[4] <= now]:
            del _passes[key]
        while len(_passes) >= MAX_PASSES:
            del _passes[next(iter(_passes))]
        _passes[found] = (str(project), str(sender), digest(line), frame, now + EXPIRY)
    return found


def take(project: str, sender, line: str, found) -> "dict | None":
    with _lock:
        row = _passes.pop(found, None) if isinstance(found, str) else None
    if row is None or row[4] <= clock():
        return None
    if (row[0], row[1], row[2]) != (str(project), str(sender), digest(line)):
        return None
    return {"frame": row[3]}


def forget_all() -> None:
    with _lock:
        _passes.clear()


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

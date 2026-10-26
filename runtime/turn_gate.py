#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The gate of a person's line: the one home of the limits PLAN-BRAIN section 4.1 re-homes. Each section names its limit and the contract row.

Operations layer, standard library only at import time: `interpreter_route` and `ops_natural` are loaded by `importlib` when a function needs them, so that a pure module
(runtime/interpreter.py) can import the gate later without joining an import cycle.

Section 1. The daily route's admission (contracts/runtime.md, limit L63, S7 and S13)

Every model call on the daily route a person's line can cause (the interpreter's call, the e-mail composer's, the two revisers') goes through this section and nowhere else:

  admit(ctx, sender)   an `Admission`, or None when the call may not be made now (the breaker is open, the sender's rate or the project's day is spent). The call is counted
                       when it may be made. An `Admission` is single-use, can only be made here, and holds nothing of the line (a flag and no text).
  call(admission, entry, system, user, *, deadline_ms, params)
                       the one place the route is called. It refuses (`{"ok": False, "code": "E_GATE"}`, no request) unless it is given an unused `Admission`; it checks the route again
                       (the entry's route among `interpreter_route.daily_routes()`, kind `http`, the hash the entry was decided on: else `{"ok": False, "code": "E_ROUTE"}`, no request)
                       and then asks `interpreter_route.complete` with that hash as the only one accepted. It does not record: each caller records the end of its attempt.
  record(ok)           the end of an attempt: a success closes the count of failures in a row, a failure counts, and BREAKER_FAILS in a row open the breaker for BREAKER_OPEN seconds.
                       A caller records exactly once for each admission, also when its attempt failed before the call.
  forget_all()         drop the counts and close the breaker (a test, and a process that stops).

The limits (counts in memory, this slice's choice, not measured): RATE_MAX calls per sender in RATE_WINDOW seconds, DAY_MAX per project per local day, and an open breaker for
BREAKER_OPEN seconds after BREAKER_FAILS failed calls in a row. The three callers share one set of counters; a test of any caller replaces `clock` here.

Privacy (limit L63): the gate keeps no line, span, model text or exception message: it holds a count per sender (the sender's own identifier, as before), a count per project
and local day, and the breaker's two numbers; the arguments of `call` are passed on and kept nowhere.

Runs on Python 3.9: python3 runtime/turn_gate.py --help
"""
from __future__ import annotations

import collections
import importlib
import sys
import threading
import time

# --- section 1: the daily route's admission (L63) ------------------------------------------------------------------------------------------------------

RATE_MAX = 10          # calls per sender in RATE_WINDOW seconds
RATE_WINDOW = 60.0
DAY_MAX = 300          # calls per project per local day
BREAKER_FAILS = 3        # failed calls in a row that open the breaker
BREAKER_OPEN = 300.0     # seconds it stays open
clock = time.monotonic   # the clock of the rate window and of the breaker (a test replaces it)

_lock = threading.Lock()
_calls = {}              # sender -> times of its calls inside the window
_days = {}               # (project key, local day) -> calls
_breaker = {"fails": 0, "until": 0.0}
_MINT = object()         # only `admit` holds it: nothing else can make an Admission


class Admission:
    """The right to make one call on the daily route. Made by `admit` only, used up by the first `call` that is given it; it holds a flag and nothing of the line."""

    def __init__(self, mint):
        if mint is not _MINT:
            raise TypeError("an admission is made by turn_gate.admit only")
        self.used = False

    def _use(self) -> bool:
        """True once: the first use marks it used, and the second finds it used."""
        with _lock:
            if self.used:
                return False
            self.used = True
            return True

    def __repr__(self) -> str:
        return "<Admission used>" if self.used else "<Admission>"


def forget_all() -> None:
    """Drop the counts and close the breaker (a test, and a process that stops)."""
    with _lock:
        _calls.clear()
        _days.clear()
        _breaker.update(fails=0, until=0.0)


def admit(ctx: dict, sender):
    """An Admission when one more call may be made now (the breaker is closed and neither limit is reached), else None; the call is counted when it may be made."""
    ops_natural = importlib.import_module("ops_natural")
    now = clock()
    day = (ops_natural.project_key(ctx["cfg"]["project"]), ops_natural._clock().date().isoformat())
    with _lock:
        if now < _breaker["until"]:
            return None
        window = _calls.setdefault(sender or "", collections.deque())
        while window and now - window[0] >= RATE_WINDOW:
            window.popleft()
        if len(window) >= RATE_MAX or _days.get(day, 0) >= DAY_MAX:
            return None
        window.append(now)
        for old in [k for k in _days if k[1] != day[1]]:
            del _days[old]
        _days[day] = _days.get(day, 0) + 1
    return Admission(_MINT)


def record(ok: bool) -> None:
    """The end of an admitted attempt: a success closes the failures in a row, a failure counts and the BREAKER_FAILS-th opens the breaker."""
    with _lock:
        if ok:
            _breaker["fails"] = 0
        else:
            _breaker["fails"] += 1
            if _breaker["fails"] >= BREAKER_FAILS:
                _breaker["until"] = clock() + BREAKER_OPEN


def call(admission, entry: dict, system: str, user: str, *, deadline_ms, params: dict) -> dict:
    """The one model call on the daily route, made only with an unused Admission: the entry's route, taken from the daily routes (kind http) and checked again here, with the hash the
    entry was decided on as the only one accepted, and the caller's own deadline and settings. Any other route is E_ROUTE and no request is made; no admission is E_GATE and
    nothing is asked or checked."""
    if not isinstance(admission, Admission) or not admission._use():
        return {"ok": False, "code": "E_GATE"}
    route = importlib.import_module("interpreter_route")
    rows = [r for r in route.daily_routes() if r["id"] == entry["route"]]
    if len(rows) != 1 or rows[0].get("kind") != "http" or route.route_sha256(rows[0]) != entry["route_sha256"]:
        return {"ok": False, "code": "E_ROUTE"}
    return route.complete(rows[0]["id"], system, user, accepted=[entry["route_sha256"]], deadline_ms=deadline_ms, **params)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

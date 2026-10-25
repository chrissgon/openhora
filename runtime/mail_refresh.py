#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The platform reads a stale mail snapshot again, once, for the line that needs it (package BL5E, SPEC-BLITE-5E-MAIL-REFRESH).

A line from a messaging app that names a message BY ITS WORDS ("apague o e-mail do github") is looked up in the index of the newest snapshot of a mail source
(runtime/ops_natural_mail.py `_read_snapshot`). When that snapshot is refused as older than 26 hours (or of a time that cannot be trusted), as missing, or as made before the
index existed, the person used to be told to refresh it in the terminal. The platform does it instead, under the limits below; this module is the one place that decides whether
a read happens and the one that makes it. It mirrors the calendar's exception (runtime/event_lookup.py `refresh`) and the phone list's (runtime/ops_items.py `_refresh_failed`).

  turn()                                    a context manager: opens the budget of one line on this thread (the mail family's `resolve` wraps its body in it); an inner `with`
                                            on the same thread reuses the budget, the outermost exit clears it
  refresh_once(ctx, source_id, channel, sender)   "refreshed" | "failed" | "not-allowed" | "spent": whether the source was read again for this line
  forget()                                  clears the memory of failed tries (a test, a process that stops)

Where it lives under the limits:
  * L52 (a mail snapshot is read only through the source operations): the one provider read is `ops_sources.source_refresh` (-> `sources_mail.snapshot_refresh` ->
    `provider_call`, the origin's own box, days and max, the verb that searches). Nothing of the line, the interpreter or a model reaches the provider's arguments, and nothing is
    written to the mailbox. This file names no provider class and no provider path.
  * L53 (the age of a snapshot): a refreshed snapshot is a new dated version; the read is for one line and never a task's input; no task receives anything new.
  * The read right: only a messaging sender whose groups list `ask-mail` (`item_refs.may_read`, the right the lookup of a message already needs), checked here again although
    the caller checked it: the guard is in the module that calls the provider. No new group, no widening.
  * One per line: a budget of one provider read per turn, fail-closed (no turn open on this thread, no read). One per source at a time: a lock for each source; a line that waits
    for it asks again when it holds it, and finds the snapshot fresh. At most one failed try for a source in FAIL_COOLDOWN_S seconds, checked before the lock and under it.
    The provider is bounded at TURN_TIMEOUT_S seconds (the typed command keeps 300).
  * Only the source the line needs, only a source of type mail, never for a channel other than messaging (the terminal, the page and the conversation have the refresh command and
    the button, and keep their sentence).
  * Nothing of the line, the snapshot or the provider's words is kept, logged or returned. A failure prints one line to stderr with a closed word (never the provider's text); the
    caller says one plain sentence and nothing is opened or listed (L62: no command, no path).

The caller never calls this for a line that names a message number or a written reference (a refresh renumbers the snapshot): see `ops_natural_mail._read_snapshot`.

Standard library only. Runs on Python 3.9: python3 runtime/mail_refresh.py --help
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import item_refs  # noqa: E402
import line_stage  # noqa: E402
import sources  # noqa: E402

TRIGGERS = ("stale", "no_version", "no_index")      # the codes of `item_refs.ItemRefError` that a read of the source cures
TURN_TIMEOUT_S = 60                                  # the provider's limit, and the most a line waits for the lock of a source
FAIL_COOLDOWN_S = 120                                # a source that failed is not tried again for this long
MONOTONIC = time.monotonic                           # the seam a test replaces

_LOCAL = threading.local()                           # the budget of the line this thread runs: {"spent": bool}, or nothing
_LOCKS = {}                                          # (project, source id) -> the lock of the source
_LOCKS_GUARD = threading.Lock()
_FAILED = {}                                         # (project, source id) -> MONOTONIC() of its last failed try: a number, in memory, no content


@contextlib.contextmanager
def turn():
    """The budget of one line on this thread: one provider read. The outermost `with` creates it and clears it on exit; an inner one (the same line, the same thread) reuses it."""
    outer = getattr(_LOCAL, "budget", None) is None
    if outer:
        _LOCAL.budget = {"spent": False}
    try:
        yield
    finally:
        if outer:
            _LOCAL.budget = None


def forget() -> None:
    """Clear the memory of failed tries."""
    _FAILED.clear()


def _lock_of(key):
    with _LOCKS_GUARD:
        found = _LOCKS.get(key)
        if found is None:
            found = _LOCKS[key] = threading.Lock()
        return found


def _cooling(key) -> bool:
    failed = _FAILED.get(key)
    return failed is not None and MONOTONIC() - failed < FAIL_COOLDOWN_S


def _still_refused(ctx: dict, source_id: str, channel, sender) -> bool:
    """Whether the snapshot is still refused for a reason a read cures. Any other answer (it reads, or another refusal) is the caller's to say."""
    try:
        item_refs.read_index(ctx, source_id, channel=channel, sender=sender, kinds=("mail",))
    except item_refs.ItemRefError as e:
        return e.code in TRIGGERS
    except sources.SourcesError:
        return False
    return False


def _failed_word(error) -> str:
    """The closed word for stderr: the refusal's `why` when it is one of the words `ops_items` lists, else `error`. The provider's words are never printed."""
    closed = importlib.import_module("ops_items").CLOSED_WHY
    why = getattr(error, "why", None)
    return why if why in closed else "error"


def refresh_once(ctx: dict, source_id: str, channel, sender) -> str:
    """Read the mail source `source_id` again, once for this line. "not-allowed": the caller may not (not messaging, no right to read, no such mail source); "spent": no turn is
    open, the line has read once already, or the source failed lately; "failed": the lock was not free in time or the read failed (one line to stderr with a closed word);
    "refreshed": the source was read again, or another line had just done it. Checked in this order, and the provider is reached only at the last step."""
    if channel != "messaging" or not item_refs.may_read(ctx, channel, sender):
        return "not-allowed"
    try:
        row = sources._stored(ctx, "source_get", source_id)
    except sources.SourcesError:
        return "not-allowed"
    if row is None or row.get("type") != "mail":
        return "not-allowed"
    budget = getattr(_LOCAL, "budget", None)
    if budget is None or budget["spent"]:
        return "spent"
    key = (ctx["cfg"]["project"], source_id)
    if _cooling(key):
        return "spent"
    budget["spent"] = True
    lock = _lock_of(key)
    if not lock.acquire(timeout=TURN_TIMEOUT_S):
        return "failed"
    try:
        if _cooling(key):      # another line failed while this one waited
            return "spent"
        if not _still_refused(ctx, source_id, channel, sender):      # another line refreshed it while this one waited
            return "refreshed"
        line_stage.publish("mail")
        try:
            importlib.import_module("ops_sources").source_refresh(ctx["cfg"]["project"], source_id, timeout=TURN_TIMEOUT_S)
        except Exception as e:      # noqa: BLE001 - the fault can hold a provider's words: only a closed word leaves
            print(f"mail: refresh of {source_id} failed ({_failed_word(e)})", file=sys.stderr)
            _FAILED[key] = MONOTONIC()
            return "failed"
        return "refreshed"
    finally:
        lock.release()


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

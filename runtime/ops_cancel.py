#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Cancelling a request while the write of an output runs (package NOTION-OUT). `store.request_cancel` cancels a request, its tasks and
their open decisions, and takes no lock. The approval of an output (runtime/ops_step_effects.py) writes a page or a table for minutes
under the lock of its decision; a cancel that reached the decision then left the write to finish into a decision already cancelled:
the page or table existed, and nothing recorded it.

Cancel is a brake and stays available. `request_cancel` here is the one function every way of cancelling a request calls (the
operation `cancel`, the board's `cancelled` move, the direct reply's cancel and a routine closing its stops): it cancels everything
that is not being written, and leaves OPEN an `effect` decision whose lock is held, with the task it belongs to as it is, so that
the write that runs records its outcome when it ends. The request itself is cancelled. The answer says so, in `writing` and `said`.

The locks of the request's open effect decisions are taken (without waiting) before the cancel and kept until it is done, so that
an approval cannot begin between the look and the cancel: it is refused as "being written" and finds its decision cancelled.

Standard library only, plus ops_core. Runs on Python 3.9.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ops_core as core  # noqa: E402


def lock_name(pending_id: int) -> str:
    """The lock file of the write of one decision (ops_step_effects._decision_lock takes it)."""
    return f"output-{pending_id}.lock"


def release(cfg: dict, pending_id: int, fd: int) -> None:
    """Let go of a decision's lock: the file is removed as the last act while it is held, then the descriptor is closed."""
    try:
        os.unlink(os.path.join(core._locks_dir(cfg), lock_name(pending_id)))
    except OSError:
        pass
    os.close(fd)


def _open_effects(ctx: dict, conn, request_id: int) -> list:
    """The open `effect` decisions of the request's tasks."""
    store = ctx["store"]
    out = []
    for item in store.pending_list(conn, "open"):
        if item["kind"] != "effect":
            continue
        task = store.task_get(conn, item["task_id"])
        if task["id"] == request_id or task["parent_id"] == request_id:
            out.append(item)
    return out


def request_cancel(conn, request_id: int, *, by: str, context: dict) -> dict:
    """store.request_cancel, except that an effect decision whose write is running is left open. Returns the store's answer, and, when
    one was left, `writing` ([{"pending", "task", "target"}]) and `said` (one sentence). Raises the store's StoreError."""
    ctx = context
    store, cfg = ctx["store"], ctx.get("cfg") or {}
    if not cfg.get("data_dir"):
        return store.request_cancel(conn, request_id, by=by)
    taken, writing = {}, []
    try:
        for item in _open_effects(ctx, conn, request_id):
            fd = core._try_lock(cfg, lock_name(item["id"]))
            if fd is None:
                effect = (item.get("payload") or {}).get("effect")
                writing.append({"pending": item["id"], "task": item["task_id"],
                                "target": effect.get("target") if isinstance(effect, dict) and isinstance(effect.get("target"), str) else None})
            else:
                taken[item["id"]] = fd
        out = store.request_cancel(conn, request_id, by=by, keep=[w["pending"] for w in writing])
    finally:
        for pending_id, fd in taken.items():
            release(cfg, pending_id, fd)
    if writing:
        names = ", ".join(w["target"] or f"decision {w['pending']}" for w in writing)
        out = {**out, "writing": writing, "said": f"the write of {names} is running and will be recorded; everything else is cancelled"}
    return out


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

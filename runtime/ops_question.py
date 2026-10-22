#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""Reject a question: the person turns it down, and it closes (slice S14).

A sibling of runtime/ops.py, which calls `dismiss` from `reject` when the pending decision is of kind `question`; no shell imports this file. A question (the router's, or a
skill's) is answered or, here, dismissed: the question is closed and its request is cancelled by the same code that cancels any request nothing is running for
(`ops_cancel.request_cancel`, as the conversation does when code answered a request itself), so that nothing is left open under it and the router's memory does not read the
request as a settled exchange. No effect is involved: nothing is sent, written or approved.

The request is cancelled only when nothing else of it is open. A request with another open decision is refused, with nothing changed: the person settles the others first or
cancels the request (`cancel`).

Standard library only. Runs on Python 3.9.
"""
from __future__ import annotations

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ops_actor  # noqa: E402
import ops_core as core  # noqa: E402


def dismiss(ctx: dict, item: dict, channel=None, sender=None) -> dict:
    """Close the open question `item` and cancel its request. Returns {"pending_id", "kind": "question", "resolution": "dismissed", "request", "cancelled": [task ids], "pending":
    [pending ids closed]}. Refused (code 1) when the decision is not open, when its request has another open decision, or when a task of the request is running."""
    store = ctx["store"]
    if item.get("status", "open") != "open":
        raise core.OpsError(f"pending decision {item['id']} is {item['status']}, not open", 1)
    task = core._stored(ctx, store.task_get, item["task_id"])
    request_id = task["id"] if task["parent_id"] is None else task["parent_id"]
    tasks = core._stored(ctx, store.tasks_list, request_id)
    others = [p["id"] for t in tasks for p in core._stored(ctx, store.pending_list, "open", t["id"]) if p["id"] != item["id"]]
    if others:
        raise core.OpsError(f"question {item['id']} was not dismissed: its request still has other decisions open", 1)
    ops_cancel, ops_say, ops_flows = (importlib.import_module(n) for n in ("ops_cancel", "ops_say", "ops_flows"))
    profile = ops_actor.profile_of(ctx["cfg"], sender) if channel == ops_actor.MESSAGING and sender else None
    done = ops_say.close_request(ctx, request_id, ops_cancel._who("user", channel, profile))
    ops_flows.discard_staged(ctx, request_id)
    return {"pending_id": item["id"], "kind": "question", "resolution": "dismissed", "request": request_id,
            "cancelled": done.get("cancelled", []), "pending": done.get("pending", [])}


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

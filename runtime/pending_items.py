#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The store of the questions a conversation leaves open for one asker (slice S4, decision 229 (1) of 2026-10-20): the bindings of the conversation layer, in memory only.

Salvaged from the stopped CONV-1a work (the store of SPEC-CONVERSATION-LAYER 2.3), reduced to the three kinds this layer uses. An ITEM binds an open question to the
person it was asked of, so that only that person's plain line on that channel may answer it:

  {"id": "c7f3a1",                       6 hexadecimal characters, unique in the process
   "kind": "router",                     one of KINDS: `router` (the router's question, S4), `plan-confirm` (the "Posso?" of a plan code stated, BL2a, runtime/plan_confirm.py) or
                                         `research-run` (the web search this sender has running, which the sender's stop word ends, BL2a, runtime/ops_research.py); a reminder
                                         draft, a write draft and a file choice wait for IX-6
   "project", "channel", "sender"        the key; `sender` is "" for a channel that names none
   "subject": ["pending", 12],           the router's question (a decision of the project's store); None for the other kinds
   "state": {"request_id": 7, "asked_at": "<the decision's created_at, ISO 8601>"},      the router's; each other kind keeps its own state (plan_confirm, ops_research)
   "asked_at", "expires_at"              monotonic seconds; `expires_at` is None: the window is read by the caller (ROUTER_WINDOW; plan_confirm.PLAN_TTL)
   "origin": "memory"}

A key holds at most ONE item of each kind: `put` of a new one replaces the key's old item of that kind (never another kind's) and returns the old id. At most MAX_ITEMS items;
the oldest goes first. Nothing here is logged, written to a file or sent to a model; `repr` of an item shows its kind and id only (a failed test or a log line never prints the
question or the plan's words); a restart loses every item, and the next line of the person is a new line. The store holds no policy beyond the constants below. Standard library only.
Runs on Python 3.9: python3 runtime/pending_items.py --help
"""
from __future__ import annotations

import secrets
import sys
import threading
import time

MAX_ITEMS = 200            # items in memory (this spec's choice, not measured): the oldest goes first
ROUTER_WINDOW = 3600       # seconds a bound router question may be answered by its asker's plain line (the maintainer's, 2026-10-20: one hour)
KINDS = ("router", "plan-confirm", "research-run")
clock = time.monotonic     # a test replaces it
_LOCK = threading.RLock()
_ITEMS = {}                # id -> item, in the order they were put


class Item(dict):
    """An item; its `repr` shows the kind and the id only, so that a log line or a failed test never prints the person's words."""

    def __repr__(self):
        return f"<item {self.get('kind')} {self.get('id')}>"


def key_of(item: dict) -> tuple:
    return (item["project"], item["channel"], item["sender"] or "")


def new_item(kind: str, project: str, channel: str, sender, *, subject=None, state=None, now=None) -> dict:
    """An item of `kind` for this sender, not yet kept (`put` keeps it). The id is six hexadecimal characters of the system's secret source, not one of a live item."""
    if kind not in KINDS:
        raise ValueError(f"no such kind of item: {kind!r}")
    when = clock() if now is None else now
    with _LOCK:
        for _ in range(100):
            item_id = secrets.token_hex(3)
            if item_id not in _ITEMS:
                break
        else:  # pragma: no cover  (sixteen million ids, two hundred items)
            raise RuntimeError("no free item id")
    return Item(id=item_id, kind=kind, project=project, channel=channel, sender=sender or "", subject=subject, asked_at=when, expires_at=None,
                state=state if state is not None else {}, origin="memory")


def put(item: dict, limit=None):
    """Keep `item`, replacing the key's item of the same kind; the id of what it replaced is returned (None when nothing was). The oldest item goes when the store is full (`limit`,
    default MAX_ITEMS)."""
    if item.get("kind") not in KINDS:
        raise ValueError(f"no such kind of item: {item.get('kind')!r}")
    with _LOCK:
        replaced = None
        for old_id, old in list(_ITEMS.items()):
            if key_of(old) == key_of(item) and old["kind"] == item["kind"]:
                del _ITEMS[old_id]
                replaced = old_id
        cap = MAX_ITEMS if limit is None else limit
        while len(_ITEMS) >= cap:
            del _ITEMS[next(iter(_ITEMS))]
        _ITEMS[item["id"]] = item
        return replaced


def items(key: tuple) -> list:
    """The items of the key (project, channel, sender), the newest first."""
    with _LOCK:
        mine = [item for item in _ITEMS.values() if key_of(item) == (key[0], key[1], key[2] or "")]
    return sorted(mine, key=lambda item: item["asked_at"], reverse=True)


def find(key: tuple, kind: str):
    """The key's newest item of `kind`, or None."""
    return next((item for item in items(key) if item["kind"] == kind), None)


def pop(item_id: str):
    """Remove the item with this id and return it, or None when there is none."""
    with _LOCK:
        return _ITEMS.pop(item_id, None)


def drop_key(key: tuple, kind=None) -> list:
    """Remove every item of the key (only those of `kind` when it is given); the ids removed."""
    with _LOCK:
        gone = [i for i, item in _ITEMS.items() if key_of(item) == (key[0], key[1], key[2] or "") and (kind is None or item["kind"] == kind)]
        for item_id in gone:
            del _ITEMS[item_id]
        return gone


def clear() -> None:
    """Forget every item (a test; a process that stops)."""
    with _LOCK:
        _ITEMS.clear()


def count() -> int:
    with _LOCK:
        return len(_ITEMS)


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""The one store of the questions a line leaves open (package NR-2): a question that the next line of the same sender answers, in memory only.

A reminder asked in words is shown and confirmed before it is made, a cancel is asked "cancel it?", a file named by two words is listed and the person chooses,
and each of those waits for the NEXT line of the same sender on the same channel. This is where they wait: one draft for each channel and sender (a new
question replaces the old one), for ten minutes, lost on a restart, never logged, never in the store, never written to a file. The reminders' words are in
a draft only until it is answered or swept (limit L51).

Two kinds of owner keep a draft here, and each sees only its own:

  "remind"   the questions of the reminders (runtime/natural.py `draft` shapes: need confirm, time, reading, text, kind, forget...), asked by the messaging
             bridge (runtime/messaging_remind.py, whose `drafts` is a `View` of this store) or by the operations layer for a reminder the router chose
  "ops"      the choice of a file for a question to `ask` (runtime/ops_natural.py)

`put(channel, sender, draft, owner)`, `get(channel, sender, owner)`, `pop(channel, sender, owner)`, `drop(channel, sender)` and `sweep(now, seconds)`. A draft
carries its own clock (`at`, a monotonic time) when its owner keeps one; the operations layer's drafts carry `expires`, and `get` treats an expired one as
gone. A test replaces `clock`.

Standard library only. Runs on Python 3.9: python3 runtime/drafts.py --help
"""
from __future__ import annotations

import collections.abc
import sys
import threading
import time

TTL = 600.0            # seconds an operations-layer draft waits (the bridge's reminders keep their own clock and sweep: DRAFT_SECONDS)
MAX = 50               # drafts in memory: the oldest goes first
OWNERS = ("remind", "ops")
clock = time.monotonic   # a test replaces it
_LOCK = threading.RLock()
_DRAFTS = {}            # (channel, sender) -> {"owner", "draft": {...}}


def _gone(entry) -> bool:
    expires = entry["draft"].get("expires")
    return expires is not None and expires <= clock()


def put(channel: str, sender: str, draft: dict, owner: str, ttl=None) -> None:
    """Keep `draft` for this sender, replacing any draft they have. With `ttl` it expires then (seconds from now)."""
    if owner not in OWNERS:
        raise ValueError(f"no such owner of a draft: {owner!r}")
    with _LOCK:
        for old in [k for k, e in _DRAFTS.items() if _gone(e)]:
            del _DRAFTS[old]
        while len(_DRAFTS) >= MAX and (channel, sender) not in _DRAFTS:
            del _DRAFTS[next(iter(_DRAFTS))]
        _DRAFTS.pop((channel, sender), None)
        _DRAFTS[(channel, sender)] = {"owner": owner, "draft": dict(draft, **({"expires": clock() + ttl} if ttl else {}))}


def get(channel: str, sender: str, owner=None):
    """The sender's draft, or None (none, expired, or owned by another)."""
    with _LOCK:
        entry = _DRAFTS.get((channel, sender))
        if entry is None or _gone(entry) or (owner is not None and entry["owner"] != owner):
            return None
        return entry["draft"]


def pop(channel: str, sender: str, owner=None):
    """Take the sender's draft away and return it (None when there is none, it expired, or another owns it: that one stays)."""
    with _LOCK:
        entry = _DRAFTS.get((channel, sender))
        if entry is None or (owner is not None and entry["owner"] != owner):
            return None
        del _DRAFTS[(channel, sender)]
        return None if _gone(entry) else entry["draft"]


def drop(channel: str, sender: str) -> None:
    with _LOCK:
        _DRAFTS.pop((channel, sender), None)


def clear() -> None:
    """Forget every draft (a test; a process that stops)."""
    with _LOCK:
        _DRAFTS.clear()


def count() -> int:
    with _LOCK:
        return len(_DRAFTS)


class View(collections.abc.MutableMapping):
    """The drafts of one owner and one channel as a mapping from a chat to its draft, for a module that keeps them by chat (the bridge's reminders:
    `View("messaging", "remind", lambda chat: "telegram:" + chat)`). It reads and writes this store, so there is one store."""

    def __init__(self, channel: str, owner: str, key, chats):
        self.channel, self.owner, self.key, self.chats = channel, owner, key, chats      # key: chat -> sender key; chats: sender key -> chat, or None

    def __getitem__(self, chat):
        draft = get(self.channel, self.key(chat), self.owner)
        if draft is None:
            raise KeyError(chat)
        return draft

    def __setitem__(self, chat, draft):
        put(self.channel, self.key(chat), draft, self.owner)

    def __delitem__(self, chat):
        if pop(self.channel, self.key(chat), self.owner) is None:
            raise KeyError(chat)

    def __iter__(self):
        with _LOCK:
            mine = [self.chats(k[1]) for k, e in _DRAFTS.items() if k[0] == self.channel and e["owner"] == self.owner and not _gone(e)]
        return iter([c for c in mine if c is not None])

    def __len__(self):
        return len(list(iter(self)))


if __name__ == "__main__":
    print(__doc__.strip(), file=sys.stdout if sys.argv[1:] in (["--help"], ["-h"]) else sys.stderr)
    sys.exit(0 if sys.argv[1:] in (["--help"], ["-h"]) else 2)

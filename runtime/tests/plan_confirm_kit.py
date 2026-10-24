"""The rig the tests of D5 share (package BL2a, runtime/plan_confirm.py): the real-operations world of test_ops_natural.py with senders that the interpreter reads, the model stood in, the
clock of a plan's age stood in, and D5 switched on (`plan_confirm.ACTIVE` is False as committed; every test that exercises a plan sets it). Offline; every name and id is invented.
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_ask import accept
from test_ops_natural import KEY, PROFILES, SENDERS, world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
ops_say = st.load("ops_say")
interpreter_route = st.load("interpreter_route")
pending_items = st.load("pending_items")
plan_confirm = st.load("plan_confirm")
phrases = st.load("phrases")
operations = st.load("operations")

ZONE = "America/Sao_Paulo"
OWNER, OFF, READER, ASKER = KEY["owner"], KEY["plain"], KEY["reader"], KEY["asker"]
# `owner` holds every group a plan of this package can meet; `off` (the `plain` sender of the world) holds `confirm-reads-off`; `asker` reads and talks only.
PROF = dict(PROFILES,
            owner=PROFILES["owner"] + ["research", "interpret", "add-sources", "reminders", "routine-brakes"],
            plain=["read", "talk", "interpret", "research", "confirm-reads-off"],
            asker=["read", "talk", "interpret"])
SENDER_LIST = SENDERS


def text(kind, **more):
    return json.dumps({"v": 1, "kind": kind, **more}, ensure_ascii=False)


def op(name, slots=None, **more):
    return text("op", op=name, slots=slots or {}, **more)


class Rig:
    pass


@pytest.fixture
def rig(world, monkeypatch):
    """The world with the senders above, D5 on, the model stood in (`rig.says["text"]` is what it returns, `rig.calls` what it was shown), the zone named and the clock of the plan's
    age stood in (`rig.now[0]`, seconds)."""
    monkeypatch.setattr(plan_confirm, "ACTIVE", True)
    pending_items.clear()
    r = Rig()
    r.world, r.calls, r.says, r.monkeypatch = world, [], {"text": text("route")}, monkeypatch
    r.now = [1000.0]
    monkeypatch.setattr(pending_items, "clock", lambda: r.now[0])
    accept(world["path"], policies=PROF, messaging={"senders": SENDER_LIST})
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()

    def complete(route_id, system, user, **kw):
        r.calls.append({"system": system, "user": user})
        return {"ok": True, "text": r.says["text"], "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    monkeypatch.setattr(interpreter_route, "complete", complete)
    r.cfg = ops_core.context(world["path"])["cfg"]
    yield r
    pending_items.clear()


def say(r, sender, line, channel="messaging", plan_ok=None):
    if plan_ok is None:
        return ops.say(r.world["path"], line, channel=channel, sender=sender if channel == "messaging" else None)
    return ops.say(r.world["path"], line, channel=channel, sender=sender, plan_ok=plan_ok)


def ok_of(out):
    """The `plan_ok` the bridge would pass for the question this reply carries."""
    got = out["plan_confirm"]
    return {"item": got["item"], "sha256": got["sha256"]}


def question(r, what_key, **fields):
    """The text of the question for a sentence, by its phrase key and values."""
    return phrases.text("PLAN_HEAD", r.cfg, what=phrases.text(what_key, r.cfg, **fields)) + " " + phrases.text("PLAN_ASK", r.cfg)


def spy_read(r):
    """A stand-in for the one place a read of the table runs; the calls are in `r.reads`."""
    r.reads = []

    def read(project, ctx, name, row, args, channel, sender):
        r.reads.append({"name": name, "args": args, "sender": sender})
        return "READ-REPLY"

    r.monkeypatch.setattr(ops_natural, "_read", read)
    return r.reads

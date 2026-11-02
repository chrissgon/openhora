"""A card the revision replaces no longer leaves its request open (finding 1 of the phone test of 2026-11-02).

Every revised card was an `effect` decision resolved `rejected` with the note `replaced by a revised card`, its task `cancelled`
and its request `planned` for ever, so `status` counted a request more for each revision. The store now ends such a request
`cancelled` (providers/store/sqlite.py `_refresh`). Here the real world of test_event_revise_flow.py (the calendar, the real cards,
a stand-in model): the old card of a revised event leaves its request `cancelled`, the new one is `planned`, `status` counts one
open request and the state reply of `ops_say` lists only the new one. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_card_revise_ends_request.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
import test_event_revise_flow as ter
from test_calendar_write import world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import op_text
from test_ops_natural_writes import forget  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_say = st.load("ops_say")
ops_interpret = st.load("ops_interpret")
ops_card_revise = st.load("ops_card_revise")

fresh = ter.fresh  # noqa: F811  (the autouse fixture that forgets the interpreter and the cards)


def request_of(world, number):
    """The id of the request whose task waits on the pending decision `number`."""
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], number)["task_id"], ctx


def parent_state(world, number):
    task_id, ctx = request_of(world, number)
    rows = {r["id"]: r for r in ctx["store"].tasks_list(ctx["conn"])}
    parent = rows[task_id]["parent_id"]
    return rows[task_id]["state"], parent, rows[parent]["state"]


def open_requests(world):
    return [r["id"] for r in ops.status(world["path"])["requests"] if r["state"] not in ("done", "cancelled")]


def test_a_revised_event_card_ends_the_request_of_the_old_card_and_leaves_the_new_one_planned(world, monkeypatch):
    ter.build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = ter.create(world)
    old_task, old_request, old_request_state = parent_state(world, old)
    assert old_request_state == "planned" and open_requests(world) == [old_request]
    new = ter.revise(world, old, sha, ter.LIVE)["resend"]
    assert isinstance(new, int) and new != old
    assert parent_state(world, old) == ("cancelled", old_request, "cancelled"), "the old card's request is over"
    new_task, new_request, new_request_state = parent_state(world, new)
    assert new_task == "waiting" and new_request != old_request and new_request_state == "planned"
    assert open_requests(world) == [new_request], "status counts one open request, not one more for the revision"


def test_the_state_reply_lists_only_the_request_of_the_new_card(world, monkeypatch):
    ter.build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = ter.create(world)
    _, old_request, _ = parent_state(world, old)
    new = ter.revise(world, old, sha, ter.LIVE)["resend"]
    _, new_request, _ = parent_state(world, new)
    reply = ops_say.state_reply(world["path"], cfg=ter.CFG)
    titles = {r["id"]: r["title"] for r in ops.status(world["path"])["requests"]}
    listed = lambda number: ter.pk.said(reply, "STATE_PROGRESS", ter.CFG, id=number, title=titles[number], done=0, total=1, names="")  # noqa: E731
    assert listed(new_request) and not listed(old_request)
    assert not ter.pk.said(reply, "STATE_NONE_OPEN", ter.CFG)

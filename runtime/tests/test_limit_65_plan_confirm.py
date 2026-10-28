"""Limit L65 (contracts/runtime.md): a read or an act asked in words on a messaging app runs only after the person's OK of the plan code stated; and limit L63 (1): only messaging lines
reach the model route. Package BL2a, runtime/plan_confirm.py. The tests are named test_limit_65_... and test_limit_63_....

Every executor of the dispatcher (`ops_natural.run`) is a spy; each operation of the sets of `plan_confirm` is called as a line would call it, and none of the spies is reached until the call
is confirmed. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_limit_65_plan_confirm.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from plan_confirm_kit import OWNER, ok_of, ops, ops_core, ops_natural, phrases, plan_confirm, say, text, world, rig  # noqa: F401
from test_ops_natural import router_says

interpreter_route = st.load("interpreter_route")
ops_research = st.load("ops_research")
ops_file_read = st.load("ops_file_read")

ARGS = {"cancel": {"request_id": 3}, "stop-task": {"task_id": 4}, "retry": {"task_id": 4}, "routine-pause": {"routine_id": 2}, "attachment-add": {"attachment_id": 5},
        "attachment-discard": {"attachment_id": 5}, "research": {"question": "weather in Lisbon"}, "ask": {}}
READS = ("items", "sources", "agents")      # three reads of the table, and the rest by their sentences (test_plan_confirm.py)
NEEDS_ITS_OWN_GROUP = ("file-ask",)      # CB-9: a served read that asks always (FA-1) and that the owner of this rig may not run: it needs the group `ask-files`, in no default; the question before its search is checked in test_file_ask.py


def spies(rig, monkeypatch):
    reached = []
    for name in ("_read", "_typed", "_call", "hand_over", "_ask"):
        monkeypatch.setattr(ops_natural, name, lambda *a, _n=name, **k: reached.append(_n) or "SPY")
    monkeypatch.setattr(ops_research, "reply", lambda *a, **k: reached.append("research.reply") or "SPY")
    monkeypatch.setattr(ops_file_read, "reply", lambda *a, **k: reached.append("file-read.reply") or "SPY")
    return reached


def call(rig, name, args, confirmed=False):
    ctx = ops_core.context(rig.world["path"])
    extras = {}
    reply = ops_natural.run(rig.world["path"], ctx, name, args, "weather in Lisbon" if name == "research" else "x", "messaging", OWNER, extras, confirmed=confirmed)
    return reply, extras


def test_limit_65_a_read_or_an_act_in_words_runs_only_after_the_ok_of_its_stated_plan(rig, monkeypatch):
    reached = spies(rig, monkeypatch)
    opened = ops.say(rig.world["path"], "Which market first?", channel="page")["pending_id"]
    assert set(NEEDS_ITS_OWN_GROUP) <= set(plan_confirm.ALWAYS)
    names = [name for name in plan_confirm.ALWAYS + plan_confirm.ACTS + READS if name not in NEEDS_ITS_OWN_GROUP]
    for name in names:
        args = {"pending_id": opened} if name in ("reject", "release") else ARGS.get(name, {})
        reply, extras = call(rig, name, args)
        assert reached == [], f"{name} ran before the OK"
        assert extras.get("plan_confirm", {}).get("op") == name and reply.endswith(phrases.text("PLAN_ASK", rig.cfg)), (name, reply)
        assert reply.startswith(phrases.text("PLAN_HEAD", rig.cfg, what="")[:-2]), name
        reply, extras = call(rig, name, args, confirmed=True)
        assert reached and "plan_confirm" not in extras, f"{name} did not run once it was confirmed"
        reached.clear()
    assert len(names) == 13


def test_limit_65_what_is_never_asked_runs_as_before(rig, monkeypatch):
    """A greeting or the help, a notice, an effect and a decision that is not a reject or a release are not asked; the page and the terminal run at once."""
    reached = spies(rig, monkeypatch)
    ctx = ops_core.context(rig.world["path"])
    assert ops_natural.run(rig.world["path"], ctx, "commands", {}, "ajuda", "messaging", OWNER, {}) == phrases.text("HELP", rig.cfg)
    for name in ("remind", "event-create", "approve", "go-ahead"):
        assert plan_confirm.needed({"cfg": rig.cfg}, name, "messaging", OWNER, False) is False, name
    for channel in ("page", "chat", "mcp"):
        for name in plan_confirm.ALWAYS + plan_confirm.ACTS + READS:
            assert plan_confirm.needed({"cfg": rig.cfg}, name, channel, OWNER, False) is False, (channel, name)
    assert reached == []


def test_limit_63_a_page_or_terminal_line_never_reaches_the_model_route(rig, monkeypatch):
    router_says(rig.world, "Route: none (operation)\nOperation: status\n")
    for channel in ("page", "chat"):
        ops.say(rig.world["path"], "will it rain in Lisbon tomorrow", channel=channel)
        ops.say(rig.world["path"], "mostra minha agenda", channel=channel)
    assert rig.calls == [], "the interpreter's model route was never called for a page or a terminal line"
    ops.say(rig.world["path"], "will it rain in Lisbon tomorrow", channel="messaging", sender=OWNER)
    assert len(rig.calls) == 1, "and a messaging line of a sender the interpreter reads does reach it (the spy sees what a route call sees)"


def test_limit_65_a_plan_ok_from_another_channel_is_refused(rig):
    out = say(rig, OWNER, "mostra minha agenda")
    for channel in ("page", None):
        with pytest.raises(ops.OpsError) as error:
            ops.say(rig.world["path"], "sim", channel=channel, plan_ok=ok_of(out))
        assert error.value.code == 2 and "plan_ok is a messaging argument" in str(error.value)
    assert ops.plan_live(rig.world["path"], OWNER)["item"] == out["plan_confirm"]["item"], "the refused call took nothing"

"""The interpreter acts on nothing (slice S1, limits L55, L61 and L63): a decision of the model opens a card or answers a question, and no approval and no write follows from a line.

Over the REAL operations layer and the stand-in writers of the calendar world (test_calendar_write.py: no Google or Microsoft host is called), with a stand-in model and a stand-in
clock. Every line of the dispatch table of test_ops_interpret_dispatch.py is said by a sender who may do all it names, and the spies on every way to approve or execute (the
approve operation, the approval of an effect, the plan's approval, the execute of each effect module, the standing policy's execute) record nothing, and the stand-in
services receive no request. A span the model reports that is not in the line opens no card. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_interpret_never_acts.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_calendar_write import rows, world  # noqa: F401  (the calendar world)
from test_channel_grants import accept
from test_ops_interpret_dispatch import TABLE, op
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_say = st.load("ops_say")
ops_step_effects = st.load("ops_step_effects")
ops_waits = st.load("ops_waits")
interpreter_route = st.load("interpreter_route")
EFFECT_MODULES = ("effect_calendar", "effect_files", "effect_mailbox", "effect_publish", "effect_send", "effect_write", "effect_commit", "effect_reply")

OWNER = "telegram:830461975213"
EVERYTHING = ["read", "talk", "ask", "reminders", "brakes", "retry", "approve-plans", "answer", "release", "reject-cancel", "sources", "add-sources", "calendar-write", "mail-organize",
              "files-write", "mail-send", "interpret"]
ZONE = "America/Sao_Paulo"


def configure(world):
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["policies"] = {"owner": EVERYTHING}
    raw["channels"] = {"page": ["read", "calendar-write"]}
    raw["messaging"] = {"senders": {"telegram": [{"id": "830461975213", "policy": "owner"}]}}
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


class Spies:
    def __init__(self, monkeypatch):
        self.seen = []
        for owner, name in [(ops, "approve"), (ops, "approve_policy"), (ops, "execute_under_policy"), (ops_step_effects, "approve"), (ops_waits, "approve_plan"),
                            *[(st.load(m), "execute") for m in EFFECT_MODULES if hasattr(st.load(m), "execute")]]:
            monkeypatch.setattr(owner, name, self._wrap(f"{owner.__name__}.{name}"))

    def _wrap(self, label):
        def spy(*a, **k):
            self.seen.append(label)
            raise AssertionError(f"{label} was called")
        return spy


def stand_in(monkeypatch, texts):
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    ops_interpret.forget_all()
    queue = texts if isinstance(texts, list) else [texts]

    def complete(route_id, system, user, **kw):
        return {"ok": True, "text": queue.pop(0) if len(queue) > 1 else queue[0], "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}

    monkeypatch.setattr(interpreter_route, "complete", complete)


def requests_made(world):
    return world["google"].requests + world["graph"].requests


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-18 14:00")


def test_no_line_of_the_dispatch_table_approves_or_executes_anything(world, clock, monkeypatch):
    configure(world)
    spies = Spies(monkeypatch)
    monkeypatch.setattr(ops_say, "_say_route", lambda *a, **k: ("ROUTED", None, None, True, None))
    said = 0
    for lang, line, text, sentence, after in TABLE:
        stand_in(monkeypatch, text)
        try:
            ops.say(world["path"], line, channel="messaging", sender=OWNER)
        except ops.OpsError:
            pass
        said += 1
    assert said == len(TABLE) and spies.seen == [] and requests_made(world) == []


def test_an_event_in_spanish_opens_the_card_of_its_exact_content_and_the_card_stays_open(world, clock, monkeypatch):
    configure(world)
    spies = Spies(monkeypatch)
    stand_in(monkeypatch, op("event-create", {"title": "cena con Dana", "time": "el viernes a las 20:00"}, time_iso="2026-10-23T20:00", weekday="fri"))
    out = ops.say(world["path"], "pon cena con Dana el viernes a las 20:00", channel="messaging", sender=OWNER)
    assert out["reply"].startswith("Which account?"), "the question of the family, asked by the draft the interpreter opened"
    out = ops.say(world["path"], "1", channel="messaging", sender=OWNER)      # the answer belongs to the draft: code reads it, no model
    assert out["resend"], "a decision whose card the bridge sends"
    item = ops.pending(world["path"], out["resend"])
    lines = item["body"].splitlines()
    assert "Title: cena con Dana" in lines and "When: Fri 23/10/2026 20:00-21:00 (America/Sao_Paulo)" in lines
    assert item["status"] == "open" and spies.seen == [] and requests_made(world) == [], "a card is opened; approving it is the person's, by its hash"


def test_a_span_that_is_not_in_the_line_opens_no_card(world, clock, monkeypatch):
    configure(world)
    spies = Spies(monkeypatch)
    stand_in(monkeypatch, op("event-create", {"title": "cena con Beatriz", "time": "el viernes a las 20:00"}, time_iso="2026-10-23T20:00", weekday="fri"))
    out = ops.say(world["path"], "pon cena con Dana el viernes a las 20:00", channel="messaging", sender=OWNER)
    assert out["reply"] == "I was not sure what you meant, so I did nothing. Can you say it another way?"
    assert rows(world) == ([], []) and spies.seen == [] and requests_made(world) == []


def test_vacuity_a_planted_approval_in_the_interpreter_is_seen_by_the_spies(world, clock, monkeypatch):
    configure(world)
    spies = Spies(monkeypatch)
    real = ops_interpret._carry_out

    def approving(project, ctx, decision, said, sender, extras):
        reply = real(project, ctx, decision, said, sender, extras)
        try:
            ops.approve(project, 1, "0" * 64)      # the planted fault
        except AssertionError:
            pass
        return reply

    monkeypatch.setattr(ops_interpret, "_carry_out", approving)
    stand_in(monkeypatch, op("event-create", {"title": "cena con Dana", "time": "el viernes a las 20:00"}, time_iso="2026-10-23T20:00", weekday="fri"))
    ops.say(world["path"], "pon cena con Dana el viernes a las 20:00", channel="messaging", sender=OWNER)
    assert spies.seen == ["ops.approve"]

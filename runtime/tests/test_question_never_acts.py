"""A question the interpreter reads opens, ends, approves and runs nothing (package ANY-QUESTION Q1, limits L55, L63, L64 and L65; DESIGN section 5).

Over the real operations layer and the stand-in writers of the calendar world (test_calendar_write.py: no Google or Microsoft host is called), the world and the spies of
test_ops_interpret_never_acts.py, and a stand-in model that answers the interpreter's call by a hand-written text. An open event card and an open mail card wait. For every kind of question the
model can ask (the eight fields of a card; `done` with no operation and with every operation of the served catalog, the refused ones included; `can` with each of them; `other`), the interpreter's
turn runs with each card in turn as the card the line is about, and after it: the same decisions with the same statuses and hashes, no approval, no rejection, no execute and no standing execute, no
request to any service, no card opened by a write in words, and the live plan, when there is one, is a read (`reminders`, `status` or `pending`). Then the person's OK of that plan runs it, and
still nothing changes. Then the card call gets each kind of question about the event card, and the card is still the one open event card. Vacuity: a `_question` that approves is caught by the spies.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_question_never_acts.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_any_question_answers import MAIL_CARD, inject, op_object
from test_calendar_write import rows, world  # noqa: F401  (the calendar world)
from test_event_revise_flow import fresh, open_cards  # noqa: F401
from test_ops_interpret_never_acts import OWNER, Spies, clock, configure, requests_made, stand_in  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural_writes = st.load("ops_natural_writes")
ops_say = st.load("ops_say")
plan_confirm = st.load("plan_confirm")
turn_gate = st.load("turn_gate")
interpreter = st.load("interpreter")

FIELDS = ("title", "when", "place", "to", "from", "subject", "approve", "other")
READS = ("reminders", "status", "pending")


def served_ops():
    return [row["op"] for row in interpreter.SERVED["ops"]] + [row["op"] for row in interpreter.SERVED["refused"]]


def objects():
    """Every question the model can ask, as the text it answers."""
    for field in FIELDS:
        yield op_object("card", field=field)
    yield op_object("done")
    for name in served_ops():
        yield op_object("done", op=name)
        yield op_object("can", op=name)
    yield op_object("other")


def state_of(world):
    ctx = ops_core.context(world["path"])
    return [(p["id"], p["kind"], p["status"], p["payload_sha256"], p["resolution"]) for p in ctx["store"].pending_list(ctx["conn"], "all")]


class Writes:
    """Spies on the two ways a line in words opens a card: neither is called by a question."""

    def __init__(self, monkeypatch):
        self.seen = []
        for owner, name in ((ops_natural_writes, "open_line"), (ops, "natural_write")):
            monkeypatch.setattr(owner, name, self._wrap(f"{owner.__name__}.{name}"))

    def _wrap(self, label):
        def spy(*a, **k):
            self.seen.append(label)
            raise AssertionError(f"{label} was called")
        return spy


def with_cards(world):
    configure(world)
    event = ops.event_create(world["path"], "google", "evento social", "2026-10-24T08:00", end="2026-10-24T09:00", location="Main Street", channel="messaging", sender=OWNER)
    event_id = event["pending"]
    item = ops.pending(world["path"], event_id)
    mail_id = inject(world, MAIL_CARD, item["task_id"])
    return event_id, item["payload_sha256"], mail_id


def test_no_question_opens_ends_approves_or_runs_anything_for_either_card(world, clock, monkeypatch):
    event_id, sha, mail_id = with_cards(world)
    spies = Spies(monkeypatch)
    writes = Writes(monkeypatch)

    def reject(*a, **k):
        spies.seen.append("ops.reject")
        raise AssertionError("ops.reject was called")

    monkeypatch.setattr(ops, "reject", reject)
    before = state_of(world)
    assert len(before) == 2 and all(row[2] == "open" for row in before)
    asked = plans = 0
    for text in objects():
        for waiting in (event_id, mail_id):
            stand_in(monkeypatch, text)
            ctx = ops_core.context(world["path"])
            extras = {"waiting_card": waiting}
            with turn_gate.turn():
                reply = ops_interpret.turn(world["path"], ctx, "a plain line that asks", OWNER, extras)[0]
            asked += 1
            assert isinstance(reply, str) and reply, text
            assert state_of(world) == before, text
            assert spies.seen == [] and writes.seen == [] and requests_made(world) == [], text
            planned = extras.get("plan_confirm")
            if planned is not None:
                plans += 1
                assert planned["op"] in READS, (text, planned)
                live = plan_confirm.live(world["path"], OWNER)
                assert live is not None and live["state"]["op"] in READS
                ok = ops_say._confirmed(world["path"], ctx, "yes", OWNER, {"item": planned["item"], "sha256": planned["sha256"]}, {})      # the person's own OK
                assert isinstance(ok, str)
                assert state_of(world) == before and spies.seen == [] and writes.seen == [] and requests_made(world) == [], ("after the OK", text)
    assert asked == 2 * len(list(objects())) and asked > 100 and plans > 100, "the reads that ask first were reached and their OK was given"


@pytest.mark.parametrize("text", [op_object("card", field="place"), op_object("card", field="approve"), op_object("done", op="event-create"), op_object("done"), op_object("can", op="event-change"), op_object("other")])
def test_the_card_call_ends_nothing_and_opens_nothing_for_each_kind_of_question(world, clock, monkeypatch, text):
    event_id, sha, mail_id = with_cards(world)
    spies = Spies(monkeypatch)
    writes = Writes(monkeypatch)
    before = state_of(world)
    stand_in(monkeypatch, text)
    got = ops.card_revise(world["path"], event_id, sha, "where is this event?", channel="messaging", sender=OWNER)
    assert got.get("resend") in (None, event_id) and set(got) <= {"say", "resend", "pass", "decide"}, got
    assert open_cards(world) == [event_id, mail_id] and state_of(world) == before
    assert spies.seen == [] and writes.seen == [] and requests_made(world) == []


def test_vacuity_a_planted_approval_in_the_answer_to_a_question_is_seen_by_the_spies(world, clock, monkeypatch):
    event_id, sha, mail_id = with_cards(world)
    spies = Spies(monkeypatch)

    def approving(project, ctx, decision, said, sender, extras):
        try:
            ops.approve(project, extras["waiting_card"], "0" * 64)      # the planted fault
        except AssertionError:
            pass
        return "planted"

    monkeypatch.setattr(ops_interpret, "_question", approving)
    stand_in(monkeypatch, op_object("card", field="when"))
    ctx = ops_core.context(world["path"])
    with turn_gate.turn():
        assert ops_interpret.turn(world["path"], ctx, "when is it?", OWNER, {"waiting_card": event_id})[0] == "planted"
    assert spies.seen == ["ops.approve"]

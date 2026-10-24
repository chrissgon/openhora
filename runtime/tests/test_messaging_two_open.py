"""Two questions wait and one bare "sim" answers neither (package BL2b, limit L64; runtime/messaging_bridge.py `word_line`, `plan_waits_before`).

A "Shall I go ahead?" (a plan the operations layer keeps) and a decision card that was sent AFTER it are both open. A bare "sim" may be meant for either: it decides NEITHER and the person is told
to reply to the message they mean (`PLAN_TWO_OPEN`). A reply names its message, so a reply "sim" to the card decides the card (approved by its hash) and one to the question confirms the plan.
Over the stand-in operations object and the stand-in messenger of test_messaging.py (the bridge asks only `plan_live` and `plan_drop` of the plan, which the test answers); every count is the
stand-in's own literal. The order of the two messages is the ledger's own, which does not tie when both are sent in one second (the stand-in clock here never moves). Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_two_open.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_messaging import SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import GRANTED, approvals, message_ids, nothing_decided, plan  # noqa: F401

phrases = st.load("phrases")
bridge = st.load("messaging_bridge")

LIVE = {"item": "a1b2c3", "sha256": "d" * 64, "op": "items"}


def t(world, key):
    return phrases.text(key, None)


@pytest.fixture
def open_two(world):
    """A question of a plan (kept by the stand-in as live) and then one decision card: the card is the last message."""
    world.config["channels"]["messaging"] = GRANTED
    world.live = {"plan": dict(LIVE)}
    world.dropped = []
    world.fake.plan_live = lambda project, sender: world.live["plan"]
    world.fake.plan_drop = lambda project, sender: world.dropped.append(sender) or True
    world.bridge.ask_plan(world.projects[0], SENDER, "I understood: list your e-mails and events. Shall I go ahead?", dict(LIVE))
    world.items[1] = plan(1)
    world.bridge.tick()
    assert message_ids(world)[0] != message_ids(world)[-1] and world.bridge.last_sent[SENDER] == str(message_ids(world)[-1])
    return world


def test_a_bare_sim_decides_neither_the_card_nor_the_plan_and_says_so(open_two):
    world = open_two
    world.say("sim")
    assert approvals(world) == [] and world.calls("say") == [] and world.dropped == []
    assert world.texts()[-1] == t(world, "PLAN_TWO_OPEN") and world.live["plan"] is not None, "nothing decided, the plan still waits"
    world.say("n\u00e3o")      # a no does not choose either: it may be the card's reject or the question's no
    assert world.texts()[-1] == t(world, "PLAN_TWO_OPEN") and nothing_decided(world) and world.dropped == []


def test_a_reply_sim_to_the_card_decides_the_card_by_its_hash_and_the_plan_still_waits(open_two):
    world = open_two
    world.say("sim")
    world.say("sim", reply_to=message_ids(world)[1])
    assert approvals(world) == [(1, "a" * 64)] and world.calls("say") == [] and world.dropped == [] and world.live["plan"] is not None


def test_a_reply_sim_to_the_question_confirms_the_plan_and_not_the_card(open_two):
    world = open_two
    world.say("sim", reply_to=message_ids(world)[0])
    assert wait_for(lambda: world.calls("say"))
    [call] = world.calls("say")
    assert call[2]["plan_ok"] == {"item": LIVE["item"], "sha256": LIVE["sha256"]} and call[2]["text"] == "sim" and approvals(world) == []


def test_with_no_plan_waiting_a_bare_sim_decides_the_card_as_it_always_did(open_two):
    world = open_two
    world.live["plan"] = None      # the plan expired, was dropped or was taken: only the card is open
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)] and world.texts()[-1] == "Approved #1."


def test_a_plan_that_is_not_the_one_the_question_was_drawn_for_does_not_count_as_waiting(open_two):
    world = open_two
    world.live["plan"] = dict(LIVE, item="ffffff")      # a newer plan replaced it: the old question is not open any more
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)]


def test_the_plan_line_never_decides_a_decision_card(open_two):
    world = open_two
    update = {"sender": SENDER, "chat": SENDER, "private": True, "text": "sim", "reply_to": message_ids(world)[1]}      # a reply to the CARD
    assert world.bridge.plan_line(update, {"kind": "reply", "reply_to": update["reply_to"], "text": "sim"}, "reply", world.projects[0], world.projects, SENDER, SENDER) is False
    update = dict(update, reply_to=None)      # the card is the last message
    assert world.bridge.plan_line(update, {"kind": "text", "text": "sim"}, "text", world.projects[0], world.projects, SENDER, SENDER) is False
    assert approvals(world) == [] and world.calls("say") == []


def test_vacuity_without_the_guard_the_bare_sim_approves_the_card(open_two, monkeypatch):
    monkeypatch.setattr(bridge.Bridge, "plan_waits_before", lambda self, listed, chat, card: False)
    open_two.say("sim")
    assert approvals(open_two) == [(1, "a" * 64)], "the same counter that is empty in the first test sees the approval"

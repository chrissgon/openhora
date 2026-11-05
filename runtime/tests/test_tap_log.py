"""One log line per tap (package P2 of SPEC-M41-3-OLD-FINDINGS, change C): every tap that reaches `Bridge.tapped` leaves exactly one line with a card kind, a decision number and a
closed operation word (`TAP_RECEIVED`), a card kind and the word when the card has no decision (`TAP_OTHER`), or `TAP_STALE` when the chat has no such card. A tap from an unlisted chat
leaves only `DROPPED`. No line holds the chat, the sender, a title, a text or the action id. A second tap is a second line. Offline, no model, on the bridge world of
test_channel_grants_cards.py with the bridge built with `log=lines.append`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tap_log.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
from test_channel_grants_cards import GRANTED, approve_action, effect, grant
from test_messaging import SENDER, world  # noqa: F401  (the bridge world of test_messaging.py)

bridge = st.load("messaging_bridge")

TITLE = "Write to the plan page"
BODY = "Open at nine."
OTHER_CHAT = "999000111222"


def tap_lines(world):
    return [line for line in world.log if line.startswith("a tap was received") or line == bridge.DROPPED]


def sent_effect(world):
    grant(world, GRANTED)
    world.items[7] = effect()
    world.bridge.tick()
    world.log.clear()


def add_card(world, kind, actions, chat=SENDER):
    world.bridge.ledger.add({"project": world.projects[0]["id"], "pending_id": None, "kind": kind, "content_sha256": "", "chat": chat, "message_id": "m-1", "actions": actions,
                             "sent_at": "2026-10-11T10:00:00+00:00", "whole": True, "approvable": False, "blocked": None, "effect_word": None})


def test_the_three_lines_are_the_ones_the_spec_names():
    assert bridge.TAP_RECEIVED.format(kind="effect", pending=7, op="approve") == "a tap was received: effect card, decision 7, approve"
    assert bridge.TAP_OTHER.format(kind="reminder", op="yes") == "a tap was received: reminder card, yes"
    assert bridge.TAP_STALE == "a tap was received on a card this chat no longer has"


def test_a_tap_on_approve_of_an_effect_card_logs_one_line_with_the_kind_the_decision_and_approve(world):
    sent_effect(world)
    world.say(None, action=approve_action(world))
    assert tap_lines(world) == ["a tap was received: effect card, decision 7, approve"]


def test_a_tap_on_reject_logs_reject(world):
    sent_effect(world)
    message = world.sent()[-1]["message"]
    reject = next(a["id"] for a in message["actions"] if pk.said(a["label"], "LABEL_REJECT"))
    world.say(None, action=reject)
    assert tap_lines(world) == ["a tap was received: effect card, decision 7, reject"]


@pytest.mark.parametrize("kind, word", [("reminder", "yes"), ("plan-confirm", "approve"), ("attachment", "store")])
def test_a_card_with_no_decision_logs_its_kind_and_the_word_only(world, kind, word):
    add_card(world, kind, {"btn-secret-1": word})
    world.bridge.plan_tapped = lambda *a, **k: None      # what the plan question and the attachment do with the tap is the business of their own tests; here only the line is looked at
    world.bridge.attach.tapped = lambda *a, **k: None
    world.say(None, action="btn-secret-1")
    assert tap_lines(world) == [f"a tap was received: {kind} card, {word}"]


def test_a_tap_on_a_card_the_chat_no_longer_has_logs_the_stale_line_and_still_says_the_sentence(world):
    world.say(None, action="btn-unknown-1")
    assert tap_lines(world) == [bridge.TAP_STALE]
    assert world.texts()[-1] == bridge.STALE


def test_a_tap_on_a_card_of_another_chat_is_stale_for_this_chat(world):
    add_card(world, "reminder", {"btn-other-1": "yes"}, chat=OTHER_CHAT)
    world.say(None, action="btn-other-1")
    assert tap_lines(world) == [bridge.TAP_STALE]


def test_an_unlisted_chat_leaves_only_the_dropped_line(world):
    sent_effect(world)
    world.config["messaging"]["senders"]["telegram"] = [OTHER_CHAT]      # the chat of the card is no longer listed
    action = approve_action(world)
    world.say(None, action=action)
    assert tap_lines(world) == [bridge.DROPPED]


def test_the_listed_check_inside_tapped_itself_logs_only_the_dropped_line(world):
    sent_effect(world)
    action = approve_action(world)
    world.config["messaging"]["senders"]["telegram"] = [OTHER_CHAT]
    world.bridge.tapped(SENDER, action, None)      # straight to the bridge's own check, past the dispatcher's
    assert tap_lines(world) == [bridge.DROPPED]
    assert world.calls("approve") == []


def test_no_line_holds_the_chat_the_sender_a_title_a_text_or_the_action_id(world):
    sent_effect(world)
    action = approve_action(world)
    add_card(world, "reminder", {"btn-secret-2": "yes"})
    world.say(None, action=action)
    world.say(None, action="btn-secret-2")
    world.say(None, action="btn-unknown-2")
    lines = tap_lines(world)
    assert len(lines) == 3
    for line in lines:
        for secret in (SENDER, TITLE, BODY, action, "btn-secret-2", "btn-unknown-2", world.projects[0]["id"], "northwind"):
            assert secret not in line, (secret, line)


def test_a_second_tap_on_the_same_card_logs_a_second_line(world):
    sent_effect(world)
    action = approve_action(world)
    world.say(None, action=action)
    world.say(None, action=action)
    assert tap_lines(world) == ["a tap was received: effect card, decision 7, approve"] * 2

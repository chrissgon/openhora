"""A card word acts only while its card is still the last message (package L64H, limit L64; runtime/messaging_bridge.py `still_last`, `word_act`, `word_on_list`).

The kind `decision-card-word` reads `last_sent` once; between that read and the act the bridge reads the ledger, the plans and the decision, and a job thread that delivers a reminder in that
window makes the reminder the last message. `word_act` reads the last message again, under the send lock, as the last thing before the act: a message sent since decides nothing and the card is sent
once more (`resend`), so that the next word decides it. This file holds the two-thread barrier (a patched read inside the window delivers the reminder), the same for the numbered list (a position,
and "todos nao", whose check is made once before the loop), a control that the loop of "todos nao" is not stopped by its own replies, a greeting question with a card last, and the vacuity cases:
with `Bridge.still_last` forced to True the same sequences decide. Each test counts the operations the stand-in was called for (its own literal count). Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_word_barrier.py
"""
from __future__ import annotations

import threading

import pytest

import phrase_kit as pk
import standin_tree as st
from test_messaging import SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import approvals, nothing_decided, plan, rejections
from test_service import WAIT

messaging_bridge = st.load("messaging_bridge")
REMINDER = "A reminder: water the plants."


def deliver_in_the_window(world, monkeypatch, name, line):
    """Patch `Bridge.<name>` so that, the first time it runs, a reminder is delivered (another message becomes the last one) before the real function answers; deliver `line` on a thread of its own,
    and return once the thread has ended. `entered` and `go` make the order explicit: the reminder is sent from the main thread while the line's thread waits inside the window."""
    real = getattr(messaging_bridge.Bridge, name)
    entered, go, once = threading.Event(), threading.Event(), []

    def patched(self, *args, **kwargs):
        if not once:
            once.append(True)
            entered.set()
            assert go.wait(WAIT), "the main thread delivers the reminder"
        return real(self, *args, **kwargs)
    monkeypatch.setattr(messaging_bridge.Bridge, name, patched)
    worker = threading.Thread(target=lambda: world.say(line), daemon=True)
    worker.start()
    assert entered.wait(WAIT), "the line reached the window"
    world.bridge.reply(SENDER, REMINDER)
    go.set()
    worker.join(WAIT)
    assert not worker.is_alive()
    monkeypatch.setattr(messaging_bridge.Bridge, name, real)


# --- the two-thread barrier: a card word ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["sim", "n\u00e3o"])
def test_a_message_sent_between_the_reading_of_the_last_message_and_the_act_decides_nothing_and_sends_the_card_again(world, monkeypatch, word):
    world.items[1] = plan(1)
    world.bridge.tick()
    cards_before = len(world.cards())
    deliver_in_the_window(world, monkeypatch, "plan_waits", word)
    assert nothing_decided(world), "the reminder became the last message while the word was being read"
    assert len(world.cards()) == cards_before + 1 and world.sent()[-1]["message"]["actions"], "the card was sent once more and is the last message"
    world.say(word)      # the card is the last message again: the same word decides it
    assert (approvals(world), rejections(world)) == (([(1, "a" * 64)], []) if word == "sim" else ([], [1]))
    assert pk.said(world.texts()[-1], "APPROVED" if word == "sim" else "REJECTED", id=1)


def test_vacuity_with_the_last_message_not_read_again_the_same_word_approves(world, monkeypatch):
    world.items[1] = plan(1)
    world.bridge.tick()
    monkeypatch.setattr(messaging_bridge.Bridge, "still_last", lambda self, chat, last: True)
    deliver_in_the_window(world, monkeypatch, "plan_waits", "sim")
    assert approvals(world) == [(1, "a" * 64)], "the counter sees the approval when the second read is gone"


# --- the numbered list -----------------------------------------------------------------------------------------------------------------------------------


def two_cards_and_the_list(world):
    world.items[1], world.items[2] = plan(1, "Launch page"), plan(2, "Pricing page")
    world.bridge.tick()
    world.say("sim")      # two cards: the list is sent and is the last message
    assert nothing_decided(world) and pk.said(world.texts()[-1].split("\n")[0], "WORD_LIST_HEAD")


def test_a_position_on_the_list_decides_nothing_when_a_message_is_sent_after_the_line_was_read(world, monkeypatch):
    two_cards_and_the_list(world)
    sent = len(world.sent())
    deliver_in_the_window(world, monkeypatch, "word_cards", "aprovo o 2")
    assert nothing_decided(world), "the reminder ended the list's place as the last message"
    assert len(world.sent()) == sent + 2 and world.sent()[-1]["message"]["actions"] and "Pricing page" in world.sent()[-1]["message"]["text"], "the reminder, then card 2 once more"
    world.say("aprovo o 2")      # card 2 is the last message again, and two cards wait: the list is sent (as it always was), and a position on the list decides
    assert nothing_decided(world) and pk.said(world.texts()[-1].split("\n")[0], "WORD_LIST_HEAD")
    world.say("aprovo o 2")
    assert approvals(world) == [(2, "b" * 64)] and rejections(world) == [] and pk.said(world.texts()[-1], "APPROVED", id=2)


def test_todos_nao_rejects_nothing_when_a_message_is_sent_after_the_line_was_read_and_sends_the_list_again(world, monkeypatch):
    two_cards_and_the_list(world)
    sent = len(world.sent())
    deliver_in_the_window(world, monkeypatch, "word_cards", "todos n\u00e3o")
    assert nothing_decided(world)
    assert len(world.sent()) == sent + 2 and pk.said(world.texts()[-1].split("\n")[0], "WORD_LIST_HEAD"), "the reminder, then the list once more"


def test_todos_nao_with_nothing_in_between_rejects_both_cards_the_loop_is_not_stopped_by_its_own_replies(world):
    two_cards_and_the_list(world)
    world.say("todos n\u00e3o")
    assert approvals(world) == [] and sorted(rejections(world)) == [1, 2]


def test_vacuity_with_the_last_message_not_read_again_the_list_words_decide_through_the_message_sent_between(world, monkeypatch):
    two_cards_and_the_list(world)
    monkeypatch.setattr(messaging_bridge.Bridge, "still_last", lambda self, chat, last: True)
    deliver_in_the_window(world, monkeypatch, "word_cards", "todos n\u00e3o")
    assert sorted(rejections(world)) == [1, 2]


# --- a greeting question with a card last ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["tudo bem?", "oi, tudo bem?"])
def test_a_greeting_question_with_a_card_last_decides_nothing(world, line):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(line)
    assert nothing_decided(world) and wait_for(lambda: world.calls("say")), "it is no card word: it goes on to say, as before"

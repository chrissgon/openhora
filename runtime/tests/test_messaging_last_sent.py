"""The last message sent to a chat (package S2, limit L64; runtime/messaging_bridge.py `deliver`, `reply_alone`, `keep_cards`) under two threads that send to the same chat at the
same moment, with a fake platform whose send is finished by the test (so the interleaving is the test's, not the scheduler's). `last_sent` is stored by the send that STARTED last,
whichever send the platform finished last; and the sentence that refuses "approve all" puts the card back as the last message only when nothing else was sent to the chat since
it was read (a compare and set under the bridge's lock). The oracle is this file's own record of the order of the sends and the stand-in's count of approvals. The vacuity case
plants the old unconditional put-back and shows the same interleaving then lets "sim" approve a card after a newer message.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_last_sent.py
"""
from __future__ import annotations

import threading

import standin_tree as st
from test_messaging import SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import approvals, message_ids, nothing_decided, plan

WAIT = 10.0


class Gated:
    """A messenger whose send of an armed text waits for the test, and returns the id the test chose; any other text is sent at once with an id of its own."""

    def __init__(self, real):
        self.real, self.started, self.release, self.ids, self.count = real, {}, {}, {}, 0

    def capabilities(self):
        return self.real.capabilities()

    def arm(self, text, message_id, wait=True):
        self.started[text], self.ids[text] = threading.Event(), message_id
        self.release[text] = threading.Event()
        if not wait:
            self.release[text].set()

    def send(self, chat, message):
        text = message["text"]
        if text in self.release:
            self.started[text].set()
            assert self.release[text].wait(WAIT)
            return self.ids[text]
        self.count += 1
        return f"u{self.count}"


def in_thread(call):
    thread = threading.Thread(target=call)
    thread.start()
    return thread


def test_the_send_that_started_last_is_the_last_message_whichever_the_platform_finished_last(world):
    gate = world.bridge.messenger = Gated(world.bridge.messenger)
    gate.arm("first", "M1")
    gate.arm("second", "M2", wait=False)
    one = in_thread(lambda: world.bridge.reply(SENDER, "first"))
    assert gate.started["first"].wait(WAIT)
    world.bridge.reply(SENDER, "second")      # starts after the first and the platform finishes it first
    assert world.bridge.last_sent[SENDER] == "M2"
    gate.release["first"].set()
    one.join(WAIT)
    assert world.bridge.last_sent[SENDER] == "M2", "the earlier send finished late and must not take the place"


def test_while_the_newest_send_is_on_its_way_no_message_is_the_last_one(world):
    gate = world.bridge.messenger = Gated(world.bridge.messenger)
    gate.arm("first", "M1", wait=False)
    gate.arm("second", "M2")
    world.bridge.reply(SENDER, "first")
    assert world.bridge.last_sent[SENDER] == "M1"
    two = in_thread(lambda: world.bridge.reply(SENDER, "second"))
    assert gate.started["second"].wait(WAIT)
    assert world.bridge.last_sent[SENDER] is None
    gate.release["second"].set()
    two.join(WAIT)
    assert world.bridge.last_sent[SENDER] == "M2"


def arranged(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    card = message_ids(world)[0]
    assert world.bridge.last_sent[SENDER] == card
    gate = world.bridge.messenger = Gated(world.bridge.messenger)
    gate.arm("KEEP", "K1")
    gate.arm("QUESTION", "Q1", wait=False)
    return card, gate


def keep_while_a_question_is_delivered(world, gate, keep):
    one = in_thread(lambda: keep(SENDER, "KEEP", world.projects[0]))
    assert gate.started["KEEP"].wait(WAIT)
    world.bridge.reply(SENDER, "QUESTION")      # a job delivers a question to the same chat while the sentence is on its way
    gate.release["KEEP"].set()
    one.join(WAIT)


def test_the_put_back_of_the_card_does_not_override_a_message_sent_meanwhile(world):
    card, gate = arranged(world)
    keep_while_a_question_is_delivered(world, gate, world.bridge.keep_cards)
    assert world.bridge.last_sent[SENDER] == "Q1"
    world.say("sim")
    assert nothing_decided(world), "the card is not the last message: a newer message was sent after it"


def test_the_put_back_alone_leaves_the_card_the_last_message_and_the_next_word_decides_it(world):
    card, gate = arranged(world)
    gate.arm("KEEP", "K1", wait=False)
    world.bridge.keep_cards(SENDER, "KEEP", world.projects[0])
    assert world.bridge.last_sent[SENDER] == card
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)]


def test_a_list_is_the_last_message_only_when_nothing_was_sent_after_it(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    gate = world.bridge.messenger = Gated(world.bridge.messenger)
    found = world.bridge.word_cards(world.bridge.projects, SENDER)
    head = world.bridge.t("WORD_LIST_HEAD", project=world.projects[0])
    gate.arm(head + "\n1. plan: Plan 1\n2. plan: Plan 2", "L1")
    gate.arm("QUESTION", "Q1", wait=False)
    one = in_thread(lambda: world.bridge.send_list(SENDER, found))
    assert gate.started[head + "\n1. plan: Plan 1\n2. plan: Plan 2"].wait(WAIT)
    world.bridge.reply(SENDER, "QUESTION")
    gate.release[head + "\n1. plan: Plan 1\n2. plan: Plan 2"].set()
    one.join(WAIT)
    assert SENDER not in world.bridge.card_lists and world.bridge.last_sent[SENDER] == "Q1"
    world.say("aprovo o 2")
    assert nothing_decided(world)


def test_the_old_unconditional_put_back_lets_a_word_approve_after_a_newer_message(world):
    """The vacuity case: the put-back as it was before the review (read the id, reply, write the id back whatever happened) loses the question, and the same counter sees the approval."""
    card, gate = arranged(world)

    def unconditional(chat, text, project):
        before = world.bridge.last_sent.get(chat)
        world.bridge.reply(chat, text, project)
        world.bridge.last_sent[chat] = before
    keep_while_a_question_is_delivered(world, gate, unconditional)
    assert world.bridge.last_sent[SENDER] == card
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)]

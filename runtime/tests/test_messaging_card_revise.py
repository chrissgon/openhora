"""Which card a plain line changes, and what the bridge does with the answer (slice S13, runtime/messaging_bridge.py `revise_line` and `revise_now`, limits L55 and L64), over the stand-in
operations object and the stand-in messenger of test_messaging.py. Offline, no model, no network; every name is invented.

A plain line that is not an approve or reject word is about the card that waits when that card is the LAST message the platform sent to the chat, or the card the line replies to; the
operations layer then decides what the line is for that card (`card_revise_check`: None, "mail", "event" or "sentence") and the change runs in a job (`card_revise`). The stand-in
records every call in this file's own list, so each negative case counts the calls itself; the vacuity case plants the one fact the hook reads (the last message) and shows the same count
sees the call. The operations layer's own rules (what a line is for a card) are in test_mail_revise_flow.py and test_event_revise_flow.py, over the real layer.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_card_revise.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_messaging import SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import GRANTED, HASH, OTHER, approvals, effect, message_ids, nothing_decided, went_to_say

KEY = "telegram:" + SENDER
LINE = 'Ajuste o corpo do email. Após "Atenciosamente," coloque "Christopher Gonçalves"'      # validate: allow english-only -- the live line, Portuguese
NOT_REVISABLE = "To change this card, reject it and ask again."


class Revise:
    """The stand-in for the two functions of the operations layer the hook uses: what each is called with, and what each answers."""

    def __init__(self, world, found="mail", result=None, closes=None):
        self.checks, self.changes, self.found, self.result, self.closes, self.world = [], [], found, result or {"say": "Done.", "resend": None}, closes, world
        world.fake.card_revise_check = self.check
        world.fake.card_revise = self.change

    def check(self, project, pending_id, sha256, text, channel="messaging", sender=None):
        self.checks.append((pending_id, sha256, text, channel, sender))
        return self.found(pending_id, text) if callable(self.found) else self.found

    def change(self, project, pending_id, sha256, text, channel="messaging", sender=None):
        self.changes.append((pending_id, sha256, text, channel, sender))
        if self.closes:
            self.world.items[self.closes]["status"] = "resolved"      # the operations layer ends the old card
        return self.result


def mail_card(world, number=7):
    world.config["channels"] = {"messaging": GRANTED}
    world.items[number] = effect(number)
    world.bridge.tick()


def test_the_live_line_after_the_card_is_a_change_of_that_card_and_goes_to_no_one_else(world):
    mail_card(world)
    revise = Revise(world)
    world.say(LINE)
    assert wait_for(lambda: revise.changes) and revise.checks == [(7, HASH, LINE, "messaging", KEY)] and revise.changes == [(7, HASH, LINE, "messaging", KEY)]
    assert wait_for(lambda: world.texts()[-1] == "Done.") and world.calls("say") == [] and nothing_decided(world)


def test_the_new_card_is_sent_after_one_sentence_and_is_the_last_message_so_a_word_decides_it(world):
    mail_card(world)
    world.items[8] = effect(8, sha="f" * 64)
    Revise(world, result={"say": "Done: the new one.", "resend": 8}, closes=7)
    world.say(LINE)
    assert wait_for(lambda: len(world.sent()) == 3)
    assert world.texts()[1] == "Done: the new one." and world.sent()[2]["message"]["text"].startswith("northwind-shop · request #8")      # the old card, the sentence, the new card
    assert wait_for(lambda: world.bridge.last_sent.get(SENDER) == message_ids(world)[-1])      # the job has finished sending: the new card is the last message
    world.say("sim")
    assert approvals(world) == [(8, "f" * 64)], "the word decides the new card, with the new card's hash"


def test_a_line_that_replies_to_an_older_card_changes_that_card_even_when_it_is_not_the_last_message(world):
    mail_card(world, 7)
    world.items[9] = effect(9, sha="d" * 64)
    world.bridge.tick()
    revise = Revise(world)
    first = message_ids(world)[0]
    world.say(LINE, reply_to=first)
    assert wait_for(lambda: revise.changes) and revise.checks[0][:2] == (7, HASH) and revise.changes[0][:2] == (7, HASH)


def test_vacuity_the_same_line_with_no_card_last_is_counted_by_the_same_list(world):
    mail_card(world)
    revise = Revise(world, found=None)
    world.say("hello there")      # the reply is the last message now
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    revise.found = "mail"
    before = len(revise.checks)
    world.say(LINE)
    assert len(revise.checks) == before and revise.changes == [] and wait_for(lambda: len(world.calls("say")) == 2)


@pytest.mark.parametrize("word", ["aprovo", "sim", "não", "pode marcar"])      # validate: allow english-only -- the Portuguese words under test
def test_a_word_that_decides_a_card_goes_before_a_change_and_the_stand_in_is_never_asked(world, word):
    mail_card(world)
    revise = Revise(world)
    world.say(word)
    assert revise.checks == [] and revise.changes == [] and world.calls("say") == []
    assert approvals(world) != [] or world.calls("reject") != []


def test_a_line_the_operations_layer_does_not_take_goes_to_the_conversation_as_it_always_did(world):
    mail_card(world)
    revise = Revise(world, found=None)
    world.say("what time is it in Lisbon")
    assert revise.checks != [] and revise.changes == [] and went_to_say(world)


def test_a_line_that_proves_not_to_be_a_change_goes_on_to_the_conversation_once(world):
    mail_card(world)
    revise = Revise(world, result={"pass": True})
    world.say("what time is it in Lisbon")
    assert wait_for(lambda: revise.changes) and wait_for(lambda: len(world.calls("say")) == 1)


def test_a_card_that_cannot_be_changed_by_words_gets_one_sentence_and_stays_the_card_a_word_decides(world):
    mail_card(world)
    revise = Revise(world, found="sentence")
    world.say("Muda o texto para dizer outra coisa")      # validate: allow english-only -- the Portuguese line under test
    assert world.texts()[-1] == NOT_REVISABLE and revise.changes == [] and world.calls("say") == []
    world.say("sim")
    assert approvals(world) == [(7, HASH)], "the card is still the last message the person was shown"


def test_a_message_sent_after_the_card_a_restart_and_a_card_that_changed_end_the_change(world):
    mail_card(world)
    revise = Revise(world)
    world.bridge = world.make()      # same ledger, nothing remembered
    world.say(LINE)
    assert revise.checks == [] and went_to_say(world)
    world.items[7] = effect(7, sha="9" * 64)
    world.say(LINE, reply_to=message_ids(world)[0])      # a reply names the card, but its content is not the card's any more
    assert revise.checks == []


def test_a_card_that_is_not_open_a_question_and_a_reply_to_a_message_that_is_no_card_are_not_changed(world):
    mail_card(world)
    revise = Revise(world)
    world.items[7]["status"] = "resolved"
    world.say(LINE, reply_to=message_ids(world)[0])
    world.say(LINE, reply_to="999")
    assert revise.checks == []
    world.items[3] = decision("question", 3)
    world.bridge.tick()
    world.say(LINE)
    assert revise.checks == []


def test_another_sender_another_chat_a_group_and_a_forward_never_change_the_card(world):
    mail_card(world)
    revise = Revise(world)
    world.config["messaging"]["senders"]["telegram"] = [SENDER, OTHER]
    world.say(LINE, sender=OTHER, chat=OTHER)      # a listed sender who was sent no card
    world.say(LINE, reply_to=message_ids(world)[0], sender=OTHER, chat=OTHER)      # naming a card of another chat
    world.say(LINE, sender=SENDER, chat="-100777", private=False)
    world.say(LINE, forwarded=True)
    assert revise.checks == [] and revise.changes == []


def test_an_e_mail_platform_a_command_and_a_reminder_form_are_not_touched(world):
    world.caps(buttons=False, actions_need_reply=True)
    mail_card(world)
    revise = Revise(world)
    world.say(LINE, reply_to=message_ids(world)[0])
    assert revise.checks == []
    world.caps(buttons=True)
    world.bridge = world.make()
    world.items[9] = effect(9, sha="d" * 64)
    world.bridge.tick()
    world.say("/pending")
    world.say("lembre-me de ligar amanha as 9h")      # validate: allow english-only -- the Portuguese line under test
    assert revise.checks == []


def test_the_write_form_of_a_change_of_an_event_is_a_line_for_the_hook_and_goes_on_to_its_family_when_it_is_not_a_change(world):
    mail_card(world)
    revise = Revise(world, result={"pass": True})
    world.say("muda para as 10h")
    assert wait_for(lambda: revise.changes) and revise.checks[0][2] == "muda para as 10h" and world.calls("say") == []


def test_a_failure_of_the_layer_is_one_plain_sentence_and_the_card_is_left_alone(world):
    mail_card(world)
    revise = Revise(world)
    world.fake.card_revise = lambda *a, **k: (_ for _ in ()).throw(world.fake.OpsError("boom"))
    world.say(LINE)
    assert wait_for(lambda: world.texts()[-1].startswith("I could not make that change")) and nothing_decided(world)

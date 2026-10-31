"""Which card a plain line changes, and what the bridge does with the answer (slice S13, runtime/messaging_turn.py the kind `decision-card-revise`, runtime/messaging_bridge.py `revise_waiting` and `revise_now`, limits L55 and L64), over the stand-in
operations object and the stand-in messenger of test_messaging.py. Offline, no model, no network; every name is invented.

A plain line that is not an approve or reject word is about the card that waits when that card is the LAST message the platform sent to the chat, or the card the line replies to; the
operations layer then decides what the line is for that card (`card_revise_check`: None, "mail", "event" or "sentence") and the change runs in a job (`card_revise`). The stand-in
records every call in this file's own list, so each negative case counts the calls itself; the vacuity case plants the one fact the hook reads (the last message) and shows the same count
sees the call. The operations layer's own rules (what a line is for a card) are in test_mail_revise_flow.py and test_event_revise_flow.py, over the real layer.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_card_revise.py
"""
from __future__ import annotations

import time

import pytest

import phrase_kit as pk
import standin_tree as st
from test_messaging import SENDER, WAIT, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import GRANTED, HASH, OTHER, approvals, effect, message_ids, nothing_decided, went_to_say

KEY = "telegram:" + SENDER
LINE = 'Ajuste o corpo do email. Após "Atenciosamente," coloque "Renato Bragança"'      # validate: allow english-only -- the live line, Portuguese


def settle(world, seconds=WAIT):
    """Wait until every job thread of the bridge has ended (the revise job, an approval job): the point after which a word is decided, and
    after which the fake's calls are complete. A reply is sent inside a job, so a reply seen is not yet the end of the job."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        alive = [t for t in list(world.bridge.threads) if t.is_alive()]
        if not alive:
            return True
        for thread in alive:
            thread.join(0.05)
    return False


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
    assert settle(world)
    world.say("sim")
    assert settle(world)
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
    assert settle(world)
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
    assert pk.said(world.texts()[-1], "RV_NOT_REVISABLE") and revise.changes == [] and world.calls("say") == []
    world.say("sim")
    assert settle(world)
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
    world.say(LINE)      # a card that is not open and is not replied to is never asked about
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
    assert wait_for(lambda: revise.changes) and revise.checks[0][2] == "muda para as 10h"
    assert settle(world)      # S41-11 PR 2b: the line goes on once the hook answers `pass`; no write form claims it any more (PR 2a), so it goes on to `say`, a moment after the hook's answer: the old check of an empty list at once was a race
    assert [call[2]["text"] for call in world.calls("say")] == ["muda para as 10h"], "the line the hook did not take went on, once"


def test_a_failure_of_the_layer_is_one_plain_sentence_and_the_card_is_left_alone(world):
    mail_card(world)
    revise = Revise(world)
    world.fake.card_revise = lambda *a, **k: (_ for _ in ()).throw(world.fake.OpsError("boom"))
    world.say(LINE)
    assert wait_for(lambda: pk.said(world.texts()[-1], "RV_FAILED")) and nothing_decided(world)


def test_a_sentence_that_leaves_the_old_card_open_sends_the_card_again_so_a_word_still_decides_it(world):
    mail_card(world)
    revise = Revise(world, result={"say": "Sorry.", "resend": 7})
    for turn in (1, 2):      # twice in a row: the second send is not held back by the limit on cards sent again to a chat
        world.say(LINE)
        assert wait_for(lambda: len(world.sent()) == 1 + 2 * turn)      # the card, then (the sentence and the card again) once for each line
        assert wait_for(lambda: world.bridge.last_sent.get(SENDER) == message_ids(world)[-1])
    assert world.texts()[1] == "Sorry." and len(world.sent()) == 5 and world.sent()[2]["message"]["text"] == world.sent()[0]["message"]["text"]      # the card, the sentence, the same card, again
    assert settle(world)
    world.say("sim")
    assert settle(world)
    assert approvals(world) == [(7, HASH)], "the old card, with its own hash, is decided by the word"


def test_a_reply_to_a_card_that_a_change_replaced_is_told_so_in_one_sentence_and_goes_nowhere_else(world):
    mail_card(world)
    revise = Revise(world, found="replaced")
    world.items[7]["status"] = "resolved"
    world.say(LINE, reply_to=message_ids(world)[0])
    assert revise.checks == [(7, HASH, LINE, "messaging", KEY)] and pk.said(world.texts()[-1], "RV_REPLACED")
    assert revise.changes == [] and world.calls("say") == []
    revise.found = None
    world.say(LINE, reply_to=message_ids(world)[0])      # the layer says it is nothing: it goes on as it always did
    assert went_to_say(world)


# --- the card call is a model call: the line a code-owned pass leaves goes on through the first leg, and the acknowledgement starts with the card call (card-model-sees, review 3) ------------


def test_a_line_code_owns_goes_on_through_the_first_leg_of_a_plain_line_and_any_other_pass_goes_on_as_it_did(world):
    mail_card(world)
    Revise(world, result={"pass": True, "decide": True})
    world.say("tomar remedio as 22h")      # validate: allow english-only -- the line under test
    assert wait_for(lambda: world.calls("say")) and settle(world)
    (call,) = world.calls("say")
    assert call[2]["decide"] is True and call[2]["text"] == "tomar remedio as 22h", "the same first leg a plain line takes, which holds no model slot and answers a sender who holds `interpret` alone"      # validate: allow english-only -- the line under test


def test_vacuity_a_pass_without_the_decide_flag_goes_on_as_the_plain_call_it_was(world):
    mail_card(world)
    Revise(world, result={"pass": True})
    world.say("what time is it in Lisbon")
    assert wait_for(lambda: world.calls("say")) and settle(world)
    (call,) = world.calls("say")
    assert "decide" not in call[2], "the oracle of the test above fails on this call: the flag is what moves the line to the first leg"


def test_the_acknowledgement_timer_starts_before_the_card_call(world):
    mail_card(world)
    events = []
    revise = Revise(world, result={"say": "Done.", "resend": None})
    real_change, real_begin = world.fake.card_revise, world.bridge.ack_begin

    def change(*args, **kwargs):
        events.append("card call")
        return real_change(*args, **kwargs)
    world.fake.card_revise = change
    world.bridge.ack_begin = lambda project, chat, text: (events.append("ack begins"), real_begin(project, chat, text))[1]
    world.say(LINE)
    assert wait_for(lambda: revise.changes) and settle(world)
    assert events[:2] == ["ack begins", "card call"], events

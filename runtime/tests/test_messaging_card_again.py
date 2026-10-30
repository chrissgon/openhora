"""A bare approve or reject word on a card that is not the last message decides nothing, and the card is sent again (package ACEITE-37, limit L64; runtime/messaging_turn.py the kind
`decision-card-again`, runtime/messaging_bridge.py `word_again` and `question_waits`). Offline, no model, no network; every name is invented. It uses the world of test_messaging.py.

THE RULE. A line that is whole a closed card word, with no position and no reply, on a platform whose acts are not replies, while no card a word could decide is the last message, decides nothing
and is answered by code: one open card is sent again (a new ledger record, a new message id, new action ids and the hash of the decision as it is now) and one sentence says so; several open cards get
the numbered list. The first card's id never decides by a word again; its button and a reply to it still decide it, bound to its own hash. A line that is no bare word, a plan that waits, an open
question, a phrase about the file just sent, a card that does not offer the act, an e-mail-shaped platform and a stop word of a running search are not taken.

Each negative test counts the operations the stand-in was called for (its own literal count, never the bridge's). Each guard has a vacuity case that plants the one fact it reads and shows the same
counter sees the other result.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_card_again.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
from test_messaging import SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import approvals, decision, effect, grant, message_ids, nothing_decided, plan, rejections

messaging_turn = st.load("messaging_turn")
turn_order = st.load("turn_order")
phrases = st.load("phrases")
bridge = st.load("messaging_bridge")

NO = "nao"      # the card words read a line with its accents off (card_words.normal)
LIVE = {"item": "a1b2c3", "sha256": "d" * 64, "op": "items"}
H1 = "a" * 64
SENTENCE = "Nothing was decided: that card was no longer the last message, so I sent it again. Decide it there."


def records(world): return world.bridge.ledger.data["cards"]
def went_on(world, says=2): return wait_for(lambda: len(world.calls("say")) == says)
def approve_button(record): return next(k for k, v in record["actions"].items() if v == "approve")


def stale(world, item=None, number=1):
    world.items[number] = item or plan(number)
    world.bridge.tick()
    world.say("oi")
    assert wait_for(lambda: world.texts()[-1] == "Noted." and world.bridge.last_sent.get(SENDER) is not None)
    return records(world)[-1]


def plan_open(world):
    world.fake.plan_live = lambda project, sender: LIVE
    world.bridge.ask_plan(world.projects[0], SENDER, "I understood: list your e-mails. Shall I go ahead?", dict(LIVE))
    world.bridge.reply(SENDER, "A reminder: water the plants.")


def question_open(world):
    world.items[2] = decision("question", 2, title="Which audience?")
    world.bridge.tick()
    world.bridge.reply(SENDER, "A reminder: water the plants.")


# --- the rule: the card is sent again and nothing is decided --------------------------------------------------------------------------------------------------


def test_limit_64_a_word_on_a_card_that_is_not_last_decides_nothing_and_the_card_is_sent_again(world):
    """Scenario 37 of the acceptance script: the card, then a greeting answered, then "sim"."""
    old = stale(world)
    world.say("sim")
    assert nothing_decided(world) and len(world.calls("say")) == 1 and len(records(world)) == 2
    new = records(world)[-1]
    assert str(new["message_id"]) != str(old["message_id"]) and str(new["message_id"]) == str(message_ids(world)[-1])
    assert not set(new["actions"]) & set(old["actions"])      # new action ids
    assert old["content_sha256"] == H1 and new["content_sha256"] == H1
    assert world.texts()[-1] == phrases.text("WORD_CARD_AGAIN", None)
    assert world.bridge.last_sent[SENDER] == str(new["message_id"])
    world.say(None, action=approve_button(new))
    assert approvals(world) == [(1, H1)]


def test_a_word_right_after_the_card_sent_again_decides_it(world):
    stale(world)
    world.say("sim")
    assert nothing_decided(world)
    world.say("sim")
    assert approvals(world) == [(1, H1)] and rejections(world) == []


def test_a_reject_word_rejects_nothing_and_the_card_is_sent_again_then_a_second_one_rejects(world):
    stale(world)
    world.say(NO)
    assert nothing_decided(world) and len(records(world)) == 2
    world.say(NO)
    assert rejections(world) == [1] and approvals(world) == []


def test_the_first_cards_id_can_never_decide_by_a_word_again(world):
    old = stale(world)
    world.say("sim")
    world.bridge.last_sent[SENDER] = str(old["message_id"])      # the planted wrong fact: the first card is the last message again
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 3


def test_vacuity_with_the_record_sent_again_gone_the_same_counter_sees_the_approval(world):
    old = stale(world)
    world.say("sim")
    del records(world)[-1]      # the record of the card sent again is gone: the first card is the newest again
    world.bridge.last_sent[SENDER] = str(old["message_id"])
    world.say("sim")
    assert approvals(world) == [(1, H1)]


def test_the_first_cards_button_still_decides_it_by_its_own_hash(world):
    old = stale(world)
    world.say("sim")
    assert nothing_decided(world)
    world.say(None, action=approve_button(old))
    assert approvals(world) == [(1, H1)]


def test_a_reply_to_the_first_card_decides_it_as_l64_says(world):
    old = stale(world)
    world.say("sim")
    assert nothing_decided(world)
    world.say("sim", reply_to=str(old["message_id"]))
    assert approvals(world) == [(1, H1)]


def test_a_decision_that_changed_is_shown_as_it_is_now_and_approved_on_that_hash(world):
    grant(world)
    stale(world, effect(), 7)
    world.items[7] = effect(sha="f" * 64)
    world.say("sim")
    assert nothing_decided(world) and records(world)[-1]["content_sha256"] == "f" * 64
    world.say("sim")
    assert wait_for(lambda: approvals(world) == [(7, "f" * 64)])


# --- several cards, a position, a line that is no bare word -------------------------------------------------------------------------------------------


def two_open(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    world.say("oi")
    assert wait_for(lambda: world.texts()[-1] == "Noted.")


def test_two_open_cards_send_the_list_and_a_position_decides_that_card(world):
    two_open(world)
    world.say("sim")
    assert nothing_decided(world) and pk.said(world.texts()[-1].split("\n")[0], "WORD_LIST_HEAD") and len(records(world)) == 2
    world.say("aprovo o 2")
    assert approvals(world) == [(2, "b" * 64)]


def test_the_word_for_all_on_two_open_cards_sends_the_list_and_rejects_nothing(world):
    two_open(world)
    world.say("todos nao")
    assert nothing_decided(world) and pk.said(world.texts()[-1].split("\n")[0], "WORD_LIST_HEAD")


@pytest.mark.parametrize("line", ["aprovo o 1", "sim, pode marcar", "sim obrigado", "oi"])
def test_a_line_that_is_not_a_bare_word_is_not_taken(world, line):
    stale(world)
    world.say(line)
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


@pytest.mark.parametrize("line", ["aprova todos", "todos nao"])
def test_the_word_for_all_on_one_card_decides_nothing_and_sends_it_again(world, line):
    stale(world)
    world.say(line)
    assert nothing_decided(world) and len(records(world)) == 2


def test_a_bare_word_with_no_card_open_is_untouched(world):
    world.say("sim")
    assert went_on(world, 1) and records(world) == [] and nothing_decided(world)


# --- the cards a word cannot decide ---------------------------------------------------------------------------------------------------------------------


def test_a_card_that_closed_is_not_sent_again(world):
    stale(world)
    world.items[1]["status"] = "rejected"
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_a_card_not_sent_whole_is_not_sent_again(world):
    stale(world)
    records(world)[-1]["whole"] = False
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_a_reply_to_a_message_that_is_not_a_card_is_not_taken(world):
    stale(world)
    world.say("sim", reply_to="999")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_an_email_shaped_platform_is_not_taken(world):
    stale(world)
    world.caps(buttons=False, actions_need_reply=True)
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_a_platform_with_no_buttons_sends_it_again_and_the_next_word_decides(world):
    stale(world)
    world.caps(buttons=False)
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 2
    world.say("sim")
    assert approvals(world) == [(1, H1)]


def test_after_a_restart_the_card_is_sent_again(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.bridge = world.make()      # same ledger, nothing remembered
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 2 and world.calls("say") == []


def test_a_group_an_unlisted_sender_and_a_forward_send_no_card(world):
    stale(world)
    before = len(world.sent())
    world.say("sim", chat="-100777", private=False)
    world.say("sim", sender="999000111", chat="999000111")
    assert len(world.sent()) == before and len(world.calls("say")) == 1
    world.say("sim", forwarded=True)
    assert len(records(world)) == 1 and nothing_decided(world)


def test_an_act_the_card_does_not_offer_is_not_taken_and_the_one_it_offers_is(world):
    stale(world, effect(), 7)      # no grant: the card offers the reject act only
    texts = len(world.texts())
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)
    assert wait_for(lambda: len(world.texts()) > texts)
    world.say(NO)
    assert nothing_decided(world) and len(records(world)) == 2


def test_vacuity_the_offer_guard(world, monkeypatch):
    stale(world, effect(), 7)
    monkeypatch.setattr(bridge.Bridge, "offers", staticmethod(lambda card: {"approve", "reject"}))
    world.say("sim")
    assert len(records(world)) == 2


# --- what is read first or after -----------------------------------------------------------------------------------------------------------------------


def test_a_plan_that_waits_takes_the_word_to_its_own_row_and_no_card_is_sent(world):
    stale(world)
    plan_open(world)
    count = len(records(world))
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == count and went_on(world)


def test_an_open_question_keeps_the_word_and_no_card_is_sent(world):
    stale(world)
    question_open(world)
    count = len(records(world))
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == count and went_on(world)


def test_vacuity_the_plan_guard(world, monkeypatch):
    stale(world)
    plan_open(world)
    count = len(records(world))
    monkeypatch.setattr(bridge.Bridge, "plan_waits", lambda self, listed, chat: False)
    world.say("sim")
    assert len(records(world)) == count + 1


def test_vacuity_the_question_guard(world, monkeypatch):
    stale(world)
    question_open(world)
    count = len(records(world))
    monkeypatch.setattr(bridge.Bridge, "question_waits", lambda self, listed, chat: False)
    world.say("sim")
    assert len(records(world)) == count + 1


def test_a_stop_word_with_a_search_running_stops_it_and_sends_no_card(world):
    stale(world)
    stops = []
    world.fake.research_stop = lambda path, key: stops.append(key) or True
    world.say(NO)
    assert stops and nothing_decided(world) and len(records(world)) == 1


def test_vacuity_with_the_two_kinds_swapped_the_card_takes_the_stop_word(world, monkeypatch):
    stale(world)
    stops = []
    world.fake.research_stop = lambda path, key: stops.append(key) or True
    order = list(turn_order.kinds())
    a, b = order.index("research-run"), order.index("decision-card-again")
    order[a], order[b] = order[b], order[a]
    monkeypatch.setattr(turn_order, "kinds", lambda: tuple(order))
    world.say(NO)
    assert not stops and len(records(world)) == 2


def test_a_phrase_about_the_file_just_sent_is_not_taken(world):
    stale(world)
    world.say("pode salvar")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_vacuity_the_file_guard(world, monkeypatch):
    stale(world)
    monkeypatch.setattr(messaging_turn.natural_writes, "file_line", lambda text: None)
    world.say("pode salvar")
    assert len(records(world)) == 2


def test_a_card_that_cannot_be_sent_again_is_said_and_the_line_goes_no_further(world, monkeypatch):
    stale(world)
    monkeypatch.setattr(bridge.Bridge, "resend", lambda self, *args, **kwargs: False)
    world.say("sim")
    assert nothing_decided(world) and world.texts()[-1] == phrases.text("NAT_DECISION_NO_CARD", None) and len(world.calls("say")) == 1


def test_vacuity_with_the_kind_off_the_word_goes_on_to_say(world, monkeypatch):
    stale(world)
    monkeypatch.setattr(messaging_turn.KINDS["decision-card-again"], "applies", lambda *args, **kwargs: None)
    world.say("sim")
    assert len(records(world)) == 1 and went_on(world)


def test_the_sentence_is_the_one_both_languages_were_given():
    assert phrases.text("WORD_CARD_AGAIN", None) == SENTENCE
    assert phrases.text("WORD_CARD_AGAIN", {"language": "pt-BR"}).startswith("Nada foi decidido")


# --- an open question keeps the word (the maintainer, 2026-10-30): a file card or a list that is the last thing said, a question about a reminder or a write ----------------------------------------


LIST_QUESTION = "More than one event fits. Which one do you want to cancel?"


def file_card_last(world, kind="attachment"):
    """The card of a held file ("what do I do with it?") is the last message: a record of kind `attachment` (the real flow is the golden rows `aceite-37.file.02` and `.file.03`)."""
    world.bridge.ledger.add({"project": world.projects[0]["id"], "pending_id": None, "kind": kind, "content_sha256": "", "chat": SENDER, "message_id": "att-1", "actions": {},
                             "sent_at": "2026-10-11T10:00:00+00:00", "whole": True, "approvable": False, "blocked": None, "effect_word": None})
    world.bridge.last_sent[SENDER] = "att-1"


def list_asked(world):
    """The operations layer holds a numbered list it just showed this sender, and the list is the last message."""
    world.fake.list_waits = lambda path, sender: True
    world.bridge.reply(SENDER, LIST_QUESTION)


@pytest.mark.parametrize("word", [NO, "cancela"])
def test_a_reject_word_after_a_file_card_is_not_taken_and_a_second_one_rejects_nothing(world, word):
    stale(world)
    file_card_last(world)
    count = len(records(world))
    world.say(word)
    assert nothing_decided(world) and len(records(world)) == count and went_on(world)
    world.say(word)
    assert nothing_decided(world)      # the second word is about the model's answer to the first: it may bring the card back (timing), it never decides it


def test_vacuity_with_the_file_card_not_a_question_the_same_words_bring_the_card_back_and_reject_it(world):
    stale(world)
    file_card_last(world, kind="reminder")      # a record that is no question: the last message is a delivered reminder
    count = len(records(world))
    world.say(NO)
    assert nothing_decided(world) and len(records(world)) == count + 1
    world.say(NO)
    assert rejections(world) == [1]


@pytest.mark.parametrize("word", [NO, "cancela"])
def test_a_reject_word_after_a_list_question_is_not_taken_and_a_second_one_rejects_nothing(world, word):
    stale(world)
    list_asked(world)
    count = len(records(world))
    world.say(word)
    assert nothing_decided(world) and len(records(world)) == count and went_on(world)
    world.say(word)
    assert nothing_decided(world)      # the second word is about the model's answer to the first: it may bring the card back (timing), it never decides it


def test_vacuity_with_no_list_waiting_the_same_words_bring_the_card_back_and_reject_it(world):
    stale(world)
    world.fake.list_waits = lambda path, sender: False
    world.bridge.reply(SENDER, LIST_QUESTION)
    count = len(records(world))
    world.say(NO)
    assert nothing_decided(world) and len(records(world)) == count + 1
    world.say(NO)
    assert rejections(world) == [1]


def test_after_a_reminder_a_greeting_or_a_plain_sentence_the_card_still_comes_back(world):
    stale(world)      # the greeting "oi" was answered after the card
    world.bridge.reply(SENDER, "A reminder: water the plants.")
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 2 and world.texts()[-1] == phrases.text("WORD_CARD_AGAIN", None)


def test_a_question_about_a_reminder_that_is_open_keeps_the_word_and_no_card_is_sent(world):
    stale(world)
    world.bridge.remind.drafts[SENDER] = {"at": world.bridge.monotonic(), "day": None, "doubt": False, "how": "trigger", "line": "remind me to call the dentist", "message_id": None, "need": "time",
                                       "project": world.projects[0]["id"], "readings": [], "text": "call the dentist"}
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1


def test_the_guard_of_the_reminder_question_alone_keeps_the_word(world, monkeypatch):
    """With the kind that answers the question switched off, only the guard of the kind `decision-card-again` is left to keep the word."""
    stale(world)
    world.bridge.remind.drafts[SENDER] = {"at": world.bridge.monotonic(), "day": None, "doubt": False, "how": "trigger", "line": "remind me to call the dentist", "message_id": None, "need": "time",
                                          "project": world.projects[0]["id"], "readings": [], "text": "call the dentist"}
    monkeypatch.setattr(messaging_turn.KINDS["reminder-draft"], "applies", lambda *args, **kwargs: None)
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1


def test_vacuity_with_the_guard_of_the_reminder_question_blind_the_card_comes_back(world, monkeypatch):
    stale(world)
    world.bridge.remind.drafts[SENDER] = {"at": world.bridge.monotonic(), "day": None, "doubt": False, "how": "trigger", "line": "remind me to call the dentist", "message_id": None, "need": "time",
                                          "project": world.projects[0]["id"], "readings": [], "text": "call the dentist"}
    monkeypatch.setattr(messaging_turn.KINDS["reminder-draft"], "applies", lambda *args, **kwargs: None)
    monkeypatch.setattr(messaging_turn.Turn, "drafted", property(lambda self: False))
    world.say("sim")
    assert len(records(world)) == 2


def test_a_question_about_a_write_that_is_open_keeps_the_word_and_no_card_is_sent(world):
    stale(world)
    world.fake.natural_draft = lambda *args, **kwargs: True
    world.fake.natural_needs = lambda *args, **kwargs: None      # the word answers nothing the question asked: the question is dropped and the line goes on
    world.fake.natural_forget = lambda *args, **kwargs: None
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_vacuity_with_the_mark_of_the_dropped_question_blind_the_card_comes_back(world):
    class Blind(set):
        def __contains__(self, item):
            return False
    stale(world)
    world.fake.natural_draft = lambda *args, **kwargs: True
    world.fake.natural_needs = lambda *args, **kwargs: None
    world.fake.natural_forget = lambda *args, **kwargs: None
    world.bridge.remind.discarded = Blind()
    world.say("sim")
    assert len(records(world)) == 2


def test_vacuity_with_no_question_about_a_write_the_same_word_brings_the_card_back(world):
    stale(world)
    world.say("sim")
    assert len(records(world)) == 2


# --- a line in question form decides no card, on the card that is last and on the re-send --------------------------------------------------------------------------------------------------------


QUESTIONS = ["sim?", "pode?", "nao?", "can you approve", "could you cancel", "poderia aprovar", "poderia cancelar", "consegue aprovar"]


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_question_decides_nothing_on_the_card_that_is_the_last_message_and_goes_on(world, line):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(line)
    assert nothing_decided(world) and went_on(world, 1)


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_question_does_not_bring_the_card_back(world, line):
    stale(world)
    world.say(line)
    assert nothing_decided(world) and len(records(world)) == 1 and went_on(world)


def test_vacuity_with_the_question_rule_off_the_question_decides_the_card_that_is_last(world, monkeypatch):
    world.items[1] = plan(1)
    world.bridge.tick()
    monkeypatch.setattr(messaging_turn.card_words, "card_word", messaging_turn.card_words.card_shape)
    world.say("sim?")
    assert approvals(world) == [(1, H1)]


@pytest.mark.parametrize("line", ["sim?", "poderia aprovar", "consegue aprovar"])
def test_vacuity_with_the_question_rule_off_the_question_brings_the_card_back(world, monkeypatch, line):
    stale(world)
    monkeypatch.setattr(messaging_turn.card_words, "card_word", messaging_turn.card_words.card_shape)
    world.say(line)
    assert len(records(world)) == 2


@pytest.mark.parametrize("line", ["pode aprovar", "pode cancela"])
def test_the_imperatives_with_pode_stay_card_words_and_bring_the_card_back(world, line):
    stale(world)
    world.say(line)
    assert nothing_decided(world) and len(records(world)) == 2


def test_a_line_in_question_form_gets_the_acknowledgement_a_card_word_does_not():
    ack = st.load("messaging_ack")
    sender = ack.Ack(lambda chat, stage: None)
    assert sender.wanted("sim?") is True and sender.wanted("sim") is False and sender.wanted("sim!") is False


# --- the list that follows a re-sent card: never silence -------------------------------------------------------------------------------------------------------------------------------------


def silence_setup(world):
    stale(world)
    world.say("sim")      # card 1 is sent again, forced: it is marked as sent again just now
    assert len(records(world)) == 2
    world.items[2] = plan(2)
    world.bridge.tick()
    world.say("oi")
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    world.say("sim")      # two cards open, none last: the list
    assert pk.said(world.texts()[-1].split("\n")[0], "WORD_LIST_HEAD")
    world.items[2]["status"] = "rejected"      # the list is no longer true: one card is left


def test_a_list_that_became_one_card_sends_that_card_even_when_it_was_sent_again_a_moment_ago(world):
    silence_setup(world)
    count, texts = len(records(world)), len(world.texts())
    world.say("sim")
    assert nothing_decided(world) and len(records(world)) == count + 1 and len(world.texts()) > texts
    assert records(world)[-1]["pending_id"] == 1


def test_vacuity_with_the_resend_not_forced_the_person_gets_silence(world, monkeypatch):
    silence_setup(world)
    real = bridge.Bridge.resend
    monkeypatch.setattr(bridge.Bridge, "resend", lambda self, project, chat, pending_id, force=False: real(self, project, chat, pending_id, False))
    count, texts = len(records(world)), len(world.texts())
    world.say("sim")
    assert len(records(world)) == count and len(world.texts()) == texts

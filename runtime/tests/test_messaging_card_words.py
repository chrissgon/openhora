"""An approve or a reject WORD decides a decision card on a messaging app (package S2, limit L64; runtime/card_words.py, runtime/messaging_bridge.py `word_line`), over the
stand-in operations object and the stand-in messenger of test_messaging.py. Offline, no model, no network; every name is invented.

THE GUARD OF L64. A word decides a card exactly as the card's own button would (the same `Bridge.act`: the policy for the sender, the card's hash, the operation), and ONLY
when every condition holds: the card is the last message the platform sent to the chat, it is the only card a word could decide (else the numbered list, and a position
decides), it was sent whole and offered the act, the sender holds the grant, the decision is open and its content hash is the card's; the line is whole an approve or reject
form with no open tail; it is not a forwarded message; and, on a platform whose acts are replies (e-mail), it is a reply to the card. A reply (the reply gesture) to a card
decides THAT card. "Approve all" is never done. Each negative test below counts the operations the stand-in was called for (its own literal count, never the bridge's); the
vacuity case plants the one fact the guard reads (the last message) and shows the same counter sees the approval.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_card_words.py
"""
from __future__ import annotations

from phone_literals import PLAIN_REFUSAL  # noqa: E402

import pytest

import standin_tree as st
from test_messaging import OPEN_POLICY, PLAN_HASH, SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

bridge = st.load("messaging_bridge")

HASH = "e" * 64
OTHER = "5151"
GRANTED = [*OPEN_POLICY, "approve-effect-write"]
APPROVED, REJECTED = "Approved #{}.", "Rejected #{}."
CHANGED_SENTENCE = "This decision changed since you saw it."
END_LINE = "Reply yes to approve or no to decline."
HEAD = 'More than one decision waits. Say which one by its number, for example "approve 2":'
ONE_AT_A_TIME = 'I approve one decision at a time. Say which one, for example "approve 2".'


def plan(number, title=None):
    return decision("plan", number, title=title or f"Plan {number}", plan_sha256=chr(96 + number) * 64)


def effect(number=7, sha=HASH, **more):
    return decision("effect", number, title="Write to the plan page", body="Replace the page with:\n\nOpen at nine.", payload_sha256=sha, effect_word="write",
                    effect_on_cards=True, **more)


def approvals(world):
    """The approvals the stand-in operations object was called for: [(pending_id, sha256)] in order (the test's own count)."""
    return [(c[2]["pending_id"], c[2].get("sha256")) for c in world.calls("approve")]


def rejections(world):
    return [c[2]["pending_id"] for c in world.calls("reject")]


def decided(world):
    return approvals(world), rejections(world)


def nothing_decided(world):
    return decided(world) == ([], [])


def message_ids(world):
    return [c["message_id"] for c in world.bridge.ledger.data["cards"]]


def went_to_say(world):
    return wait_for(lambda: world.calls("say"))


# --- the word decides the one card that is the last message ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["Aprovo", "aprovo", "sim", "Sim!", "pode marcar", "pode aprovar", "ok", "yes", "approve", "approved", "go ahead", "manda ver"])
def test_an_approve_word_approves_the_only_card_that_is_the_last_message_exactly_as_its_button_does(world, word):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(word)
    assert approvals(world) == [(1, "a" * 64)] and rejections(world) == []      # the hash of the card the person saw, the plan's own
    assert world.texts()[-1] == APPROVED.format(1) and world.calls("say") == []


@pytest.mark.parametrize("word", ["n\u00e3o", "Nao", "rejeito", "rejeita", "cancela", "deixa", "no", "reject", "cancel"])
def test_a_reject_word_rejects_the_only_card_that_is_the_last_message(world, word):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(word)
    assert decided(world) == ([], [1]) and world.texts()[-1] == REJECTED.format(1) and world.calls("say") == []


def test_the_button_and_the_word_make_the_same_call(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(None, action=world.sent()[0]["message"]["actions"][0]["id"])
    by_button = [dict(c[2]) for c in world.calls("approve")]
    assert by_button == [{"pending_id": 1, "sha256": "a" * 64, "channel": "messaging"}]
    world.items[1]["status"] = "resolved"
    world.items[2] = plan(2)
    world.bridge.tick()
    world.fake.calls.clear()
    world.say("sim")
    assert [dict(c[2]) for c in world.calls("approve")] == [dict(by_button[0], pending_id=2, sha256="b" * 64)]      # the same keys, the second plan's own number and hash


# --- the conditions: each one alone stops the word --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["pode marcar o dentista", "sim mas s\u00f3 amanh\u00e3", "ok vou ver", "aprovo o plano inteiro"])
def test_a_line_with_an_open_tail_is_not_a_word_and_goes_on_to_say(world, line):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(line)
    assert nothing_decided(world) and went_to_say(world)


@pytest.mark.parametrize("line", ["pode marcar amanh\u00e3 \u00e0s 3", "Agende corte de cabelo amanh\u00e3 \u00e0s 14h", "pode marcar o dentista quinta \u00e0s 10h"])
def test_a_line_with_a_time_in_it_is_not_a_word_whatever_else_reads_it(world, line):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say(line)
    assert nothing_decided(world)


def test_a_message_sent_after_the_card_ends_the_word(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("hello there")      # the reply to it is the last message now
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    world.say("sim")
    assert nothing_decided(world) and wait_for(lambda: len(world.calls("say")) == 2)


def test_a_delivered_reminder_or_any_later_card_ends_the_word(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.bridge.reply(SENDER, "A reminder: water the plants.")      # a reminder is delivered through `reply`
    world.say("sim")
    assert nothing_decided(world) and went_to_say(world)


def test_after_a_restart_the_last_message_is_forgotten_and_a_word_decides_nothing(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.bridge = world.make()      # same ledger, nothing remembered
    world.say("sim")
    assert nothing_decided(world) and went_to_say(world)


def test_two_cards_send_the_numbered_list_and_decide_nothing(world):
    world.items[1], world.items[2] = plan(1, "Launch page"), plan(2, "Pricing page")
    world.bridge.tick()
    world.say("sim")
    assert nothing_decided(world) and world.calls("say") == []
    assert world.texts()[-1] == HEAD + "\n1. plan: Launch page\n2. plan: Pricing page"
    assert "#" not in world.texts()[-1]


def test_a_position_on_the_list_decides_that_card_and_only_that_card(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    world.say("pode marcar")
    world.say("aprovo o 2")
    assert approvals(world) == [(2, "b" * 64)] and rejections(world) == [] and world.texts()[-1] == APPROVED.format(2)


def test_a_position_that_is_not_on_the_list_or_a_word_with_no_position_sends_the_list_again(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    world.say("sim")
    for line in ("aprovo o 3", "sim", "aprovo o 11"):
        before = len(world.texts())
        world.say(line)
        assert nothing_decided(world) and len(world.texts()) == before + 1 and world.texts()[-1].startswith(HEAD), line


def test_a_position_on_a_list_that_is_no_longer_the_last_message_decides_nothing(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    world.say("sim")
    world.say("hello there")
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    world.say("aprovo o 2")
    assert nothing_decided(world)


def test_a_list_that_waited_longer_than_its_limit_decides_nothing(world):
    now = [1000.0]
    world.bridge.monotonic = lambda: now[0]
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    world.say("sim")
    now[0] += 601.0
    world.say("aprovo o 2")
    assert nothing_decided(world) and went_to_say(world)


def test_approve_all_is_never_done_and_reject_all_rejects_each_card_of_the_list(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    world.say("sim")
    world.say("aprova todos")
    assert nothing_decided(world) and world.texts()[-1] == ONE_AT_A_TIME and world.calls("say") == []
    world.say("approve all")      # again: the list is still what the person was shown
    assert nothing_decided(world) and world.texts()[-1] == ONE_AT_A_TIME
    world.say("todos n\u00e3o")
    assert approvals(world) == [] and sorted(rejections(world)) == [1, 2]


def test_a_card_that_is_not_open_any_more_decides_nothing(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.items[1]["status"] = "resolved"
    world.say("sim")
    assert nothing_decided(world) and went_to_say(world)


def test_a_decision_that_changed_since_the_card_approves_nothing_says_so_and_sends_a_new_card(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.items[1] = decision("plan", 1, title="Plan 1", plan_sha256="z" * 64)
    world.say("sim")
    assert nothing_decided(world) and world.texts()[-2] == CHANGED_SENTENCE
    assert len(world.sent()) == 3 and world.sent()[-1]["message"]["text"].startswith("northwind-shop · plan #1")      # the card, the sentence, the new card
    world.say("sim")
    assert approvals(world) == [(1, "z" * 64)]      # the new card is the last message and carries the new hash


def test_a_sender_who_was_sent_no_card_decides_nothing(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.config["messaging"]["senders"]["telegram"] = [SENDER, OTHER]      # a second listed sender, who was not sent the card (he joined after it)
    world.say("sim", sender=OTHER, chat=OTHER)
    assert nothing_decided(world) and went_to_say(world)


def test_a_group_chat_and_an_unlisted_sender_decide_nothing_and_get_no_reply(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    before = len(world.sent())
    world.say("sim", sender=SENDER, chat="-100777", private=False)
    world.say("sim", sender="999000111", chat="999000111")
    assert nothing_decided(world) and len(world.sent()) == before and world.calls("say") == []


def test_a_forwarded_word_decides_nothing_and_a_fail_closed_mark_counts(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    for mark in (True, "yes", 1):
        world.say("sim", forwarded=mark)
    assert nothing_decided(world) and world.calls("say") == [] and world.texts()[-1].startswith("I don't act on forwarded messages")


def test_the_policy_that_lacks_the_grant_draws_no_approve_and_the_word_goes_on_to_say(world):
    world.config["channels"] = {"messaging": ["read", "talk", "reject-cancel"]}      # no approve-plans
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("sim")
    assert nothing_decided(world) and went_to_say(world)


def test_a_grant_taken_away_after_the_card_was_drawn_refuses_the_word_as_it_refuses_the_button(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.config["channels"] = {"messaging": ["read", "talk", "reject-cancel"]}
    world.say("sim")
    assert nothing_decided(world) and world.calls("say") == [] and world.texts()[-1] == PLAIN_REFUSAL


def test_a_card_that_was_not_sent_whole_decides_nothing(world):
    world.config["messaging"]["notices"] = "count"      # the card carries none of the text
    world.items[1] = plan(1)
    world.bridge.tick()
    assert world.bridge.ledger.data["cards"][0]["whole"] is False
    world.say("sim")
    assert nothing_decided(world) and went_to_say(world)


def test_a_question_a_reminder_question_and_a_file_are_not_cards_a_word_decides(world):
    world.items[1] = decision("question", 1, title="Which audience?")
    world.bridge.tick()
    world.say("sim")      # the answer to the question, as ever
    assert nothing_decided(world) and went_to_say(world)


# --- the reply gesture ------------------------------------------------------------------------------------------------------------------------------------


def test_a_word_sent_as_a_reply_to_a_card_decides_that_card_even_when_it_is_not_the_last_message(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    first, second = message_ids(world)
    world.say("sim", reply_to=first)
    assert approvals(world) == [(1, "a" * 64)] and rejections(world) == []
    world.say("n\u00e3o", reply_to=second)
    assert rejections(world) == [2] and approvals(world) == [(1, "a" * 64)]


def test_a_reply_to_a_card_with_a_position_or_with_all_decides_no_card(world):
    world.items[1], world.items[2] = plan(1), plan(2)
    world.bridge.tick()
    first, _ = message_ids(world)
    world.say("aprovo o 2", reply_to=first)
    world.say("todos n\u00e3o", reply_to=first)
    assert nothing_decided(world)
    assert wait_for(lambda: world.texts().count("Noted.") == 2)      # both went on to say, as ever
    world.say("aprova todos", reply_to=first)
    assert nothing_decided(world) and world.texts()[-1] == ONE_AT_A_TIME


def test_a_reply_to_a_card_whose_decision_changed_approves_nothing(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    [first] = message_ids(world)
    world.items[1] = decision("plan", 1, title="Plan 1", plan_sha256="z" * 64)
    world.say("sim", reply_to=first)
    assert nothing_decided(world) and CHANGED_SENTENCE in world.texts()


def test_a_reply_to_anything_that_is_not_a_decision_card_is_not_a_word(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("hello there")
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    world.say("sim", reply_to="999")
    assert nothing_decided(world)


# --- an effect, a platform with no buttons and an e-mail-shaped one ---------------------------------------------------------------------------------------------


def grant(world, groups=GRANTED):
    world.config["channels"] = {"messaging": groups}


def test_a_granted_effect_is_approved_by_a_word_with_the_cards_own_hash_in_a_job(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("pode marcar")
    assert wait_for(lambda: approvals(world))
    assert [dict(c[2]) for c in world.calls("approve")] == [{"pending_id": 7, "sha256": HASH, "channel": "messaging"}]


def test_an_effect_whose_hash_changed_is_not_approved_by_a_word(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    world.items[7] = effect(sha="f" * 64)
    world.say("sim")
    assert nothing_decided(world) and CHANGED_SENTENCE in world.texts()


def test_an_effect_of_a_policy_without_its_word_is_never_approved_by_a_word_the_word_goes_on_as_a_line(world):
    world.items[7] = effect()
    world.bridge.tick()
    world.say("sim")      # the card offers no approval: the word goes on as a line
    assert nothing_decided(world) and went_to_say(world)


def test_an_effect_card_that_offers_only_reject_is_rejected_by_its_word_as_by_its_button(world):
    world.items[7] = effect()
    world.bridge.tick()
    world.say("n\u00e3o")      # a reject is offered, so its word works as its button
    assert rejections(world) == [7] and approvals(world) == []


def test_a_platform_with_no_buttons_ends_the_card_with_the_words_and_the_word_approves(world):
    world.caps(buttons=False)
    world.items[1] = plan(1)
    world.bridge.tick()
    [card] = world.sent()
    assert card["message"]["text"].endswith(END_LINE) and "/approve" not in card["message"]["text"] and "/reject" not in card["message"]["text"]
    assert world.bridge.ledger.data["cards"][0]["offers"] == ["approve", "reject"]
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)]


def test_a_card_that_is_not_whole_on_a_platform_with_no_buttons_keeps_the_typed_lines_because_a_word_decides_only_a_whole_card(world):
    world.caps(buttons=False)
    world.config["messaging"]["notices"] = "count"      # the card carries none of the text
    world.items[1] = plan(1)
    world.bridge.tick()
    text = world.sent()[0]["message"]["text"]
    assert "Send /approve 1" in text and "Send /reject 1" in text and END_LINE not in text
    assert world.bridge.ledger.data["cards"][0]["whole"] is False
    world.say("sim")
    assert nothing_decided(world)


def test_a_cut_card_on_a_platform_with_no_buttons_keeps_the_typed_lines_and_a_whole_one_ends_with_the_words(world):
    world.caps(buttons=False, max_text=300, documents=False)
    world.items[1] = decision("plan", 1, body="x" * 2000, plan_sha256="a" * 64)
    world.bridge.tick()
    cut = world.sent()[0]["message"]["text"]
    assert len(cut) <= 300 and "Send /approve 1" in cut and "Send /reject 1" in cut and END_LINE not in cut
    assert world.bridge.ledger.data["cards"][0]["whole"] is False
    world.items[2] = decision("plan", 2, body="short", plan_sha256="b" * 64)
    world.bridge.tick()
    whole = world.sent()[1]["message"]["text"]
    assert whole.endswith(END_LINE) and "/approve" not in whole and world.bridge.ledger.data["cards"][1]["whole"] is True


def test_a_platform_with_buttons_does_not_end_the_card_with_the_words(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    assert END_LINE not in world.sent()[0]["message"]["text"] and [a["label"] for a in world.sent()[0]["message"]["actions"]] == ["Approve", "Reject"]


def test_an_email_shaped_platform_decides_only_by_a_reply_to_the_card(world):
    world.caps(buttons=False, actions_need_reply=True)
    world.items[1] = plan(1)
    world.bridge.tick()
    [card] = world.sent()
    assert card["message"]["text"].endswith(END_LINE) and card["message"]["footer"][-1] == END_LINE
    world.say("sim")      # a plain line is not a reply to the card
    assert nothing_decided(world) and went_to_say(world)
    world.say("sim", reply_to=message_ids(world)[0])
    assert approvals(world) == [(1, "a" * 64)]


# --- limit L64, one condition broken at a time -----------------------------------------------------------------------------------------------------------------


def after_a_later_message(world):
    world.say("hello there")
    assert wait_for(lambda: world.texts()[-1] == "Noted." and world.bridge.last_sent.get(SENDER) is not None)
    return {}


def with_a_second_card(world):
    world.items[2] = plan(2)
    world.bridge.tick()
    return {}


def with_the_decision_changed(world):
    world.items[1] = decision("plan", 1, title="Plan 1", plan_sha256="z" * 64)
    return {}


def with_the_decision_closed(world):
    world.items[1]["status"] = "resolved"
    return {}


def with_the_grant_withdrawn(world):
    world.config["channels"] = {"messaging": ["read", "talk"]}
    return {}


def after_a_restart(world):
    world.bridge = world.make()
    return {}


def as_email_without_a_reply(world):
    world.caps(buttons=False, actions_need_reply=True)
    return {}


BREAKS = {
    "a later message": after_a_later_message,
    "a second card (the list, no decision)": with_a_second_card,
    "a forwarded message": lambda world: {"forwarded": True},
    "a group chat": lambda world: {"chat": "-100777", "private": False},
    "an unlisted sender": lambda world: {"sender": "999000111", "chat": "999000111"},
    "the decision changed": with_the_decision_changed,
    "the decision closed": with_the_decision_closed,
    "the grant withdrawn": with_the_grant_withdrawn,
    "a restart": after_a_restart,
    "an e-mail platform and no reply": as_email_without_a_reply,
}


def test_limit_64_a_word_decides_a_card_only_as_its_button_would_and_only_when_every_condition_holds(world):
    """The one case where every condition holds: the word approves with the plan's own hash. The parametrized cases below break one condition each."""
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("Aprovo")
    assert approvals(world) == [(1, "a" * 64)] and rejections(world) == []


@pytest.mark.parametrize("broken", sorted(BREAKS))
def test_a_word_decides_nothing_when_one_condition_of_l64_is_broken_at_a_time(world, broken):
    world.items[1] = plan(1)
    world.bridge.tick()
    fields = BREAKS[broken](world)
    world.say("Aprovo", **fields)
    assert approvals(world) == [], broken


# --- the vacuity case ---------------------------------------------------------------------------------------------------------------------------------------


def test_the_counters_see_an_approval_when_the_one_fact_the_guard_reads_is_planted(world):
    """If the last-message rule were gone (here: planted back to the card's id after a later message), the same word would approve and the same counter would show it."""
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("hello there")
    assert wait_for(lambda: world.texts()[-1] == "Noted.")
    world.say("sim")
    assert nothing_decided(world)
    world.bridge.last_sent[SENDER] = message_ids(world)[0]      # the planted wrong fact
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)]

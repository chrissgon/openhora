"""A card word in an e-mail reply is read from its first line (slice S10, limit L64; runtime/card_words.py `reply_line`, `Bridge.word_line`), over the stand-in world of
test_messaging_card_words.py with a platform whose acts are replies (`actions_need_reply`).

A reply to a card carries a phone's signature or the quoted card under the person's words ("sim", a blank line, "Enviado do meu iPhone"), which made it more than one phrase
and decided nothing. The first non-empty line is the phrase now; everything after it must be a signature or a quote, else the text is not one phrase (a second line of words
is a request). Only on a platform whose acts are replies: on a chat app the whole line is the phrase as before. Everything else of L64 is unchanged and checked again here: the
reply names the card, the sender is listed, the act is bound to the card's hash.

THE ORACLE counts the operations the stand-in was called for (its own count) and reads the raw reply with this file's literals. The vacuity case plants the old rule (the whole
text is the phrase) and shows the same count sees no approval for the signature case.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_email_word.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_messaging import wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)
from test_messaging_card_words import approvals, decided, message_ids, nothing_decided, plan, went_to_say

card_words = st.load("card_words")

SIGNATURES = ["Enviado do meu iPhone", "Sent from my iPhone", "-- \nAna", "--\nAna", "Enviado de Outlook para Android", "Get Outlook for iOS", "Enviado do meu Galaxy"]
HEADERS = ["Em seg., 5 de out. de 2026 \u00e0s 10:00, Ana <ana@mail.example> escreveu:", "On Mon, Oct 5, 2026 at 10:00 AM Ana <ana@mail.example> wrote:"]


def email(world):
    world.caps(buttons=False, actions_need_reply=True)
    world.items[1] = plan(1)
    world.bridge.tick()
    return message_ids(world)[0]


@pytest.mark.parametrize("signature", SIGNATURES)
def test_a_word_followed_by_a_signature_approves_the_card_it_replies_to(world, signature):
    shown = email(world)
    world.say(f"sim\n\n{signature}", reply_to=shown)
    assert approvals(world) == [(1, "a" * 64)]      # the hash of the card the person saw


@pytest.mark.parametrize("header", HEADERS)
def test_a_word_followed_by_quoted_history_approves(world, header):
    shown = email(world)
    world.say(f"aprovo\n\n{header}\n> northwind-shop \u00b7 plan #1\n> Reply yes to approve or no to decline.", reply_to=shown)
    assert approvals(world) == [(1, "a" * 64)]


def test_a_reject_word_with_a_signature_rejects(world):
    shown = email(world)
    world.say("n\u00e3o\n\nEnviado do meu iPhone", reply_to=shown)
    assert decided(world) == ([], [1])


@pytest.mark.parametrize("text", ["sim\n> quoted card", "sim\r\n> quoted card", "  sim  \n\n\n> quoted card\n> more"])
def test_a_quote_directly_under_the_word_is_ignored(world, text):
    shown = email(world)
    world.say(text, reply_to=shown)
    assert approvals(world) == [(1, "a" * 64)]


@pytest.mark.parametrize("text", ["sim, mas muda o hor\u00e1rio\nEnviado do meu iPhone", "sim mas s\u00f3 amanh\u00e3\n> quoted card", "pode marcar amanh\u00e3 \u00e0s 3\n-- \nAna",
                                  "sim\nmas muda o hor\u00e1rio", "sim\n\nAtenciosamente,\nAna", "sim\nn\u00e3o\nEnviado do meu iPhone"])
def test_a_first_line_that_is_more_than_a_word_or_a_second_line_of_words_decides_nothing(world, text):
    shown = email(world)
    world.say(text, reply_to=shown)
    assert nothing_decided(world)


@pytest.mark.parametrize("text", ["Enviado do meu iPhone", "-- \nsim", "> sim\n> quoted card", "\n\n", "Em seg. escreveu:\n> sim"])
def test_a_first_line_that_is_a_signature_or_a_quote_only_does_nothing(world, text):
    shown = email(world)
    world.say(text, reply_to=shown)
    assert nothing_decided(world)


def test_the_rest_of_l64_is_unchanged_a_word_that_is_not_a_reply_to_the_card_decides_nothing(world):
    email(world)
    world.say("sim\n\nEnviado do meu iPhone")      # no reply_to: a plain line is not a reply to the card (rule 50)
    assert nothing_decided(world) and went_to_say(world)
    world.say("sim\n\nEnviado do meu iPhone", reply_to="999")      # a reply to a message that is no card
    assert nothing_decided(world)


def test_a_chat_app_still_reads_the_whole_line(world):
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("sim\n\nEnviado do meu iPhone")      # no actions_need_reply: the whole line is the phrase, so this is more than one phrase
    assert nothing_decided(world) and went_to_say(world)


def test_a_chat_app_decides_by_the_plain_word(world):      # the other half of the one above: the same card, the word alone, no actions_need_reply
    world.items[1] = plan(1)
    world.bridge.tick()
    world.say("sim")
    assert approvals(world) == [(1, "a" * 64)]


# --- the pure reading ----------------------------------------------------------------------------------------------------------------------------------


READINGS = [("sim", "sim"), ("sim\n\nEnviado do meu iPhone", "sim"), ("sim\n> quoted", "sim"), ("sim, mas muda\nEnviado do meu iPhone", "sim, mas muda"), ("Enviado do meu iPhone", ""),
            ("", ""), ("sim\nmas muda", ""), ("\n  sim  \n-- \nAna", "sim"), ("-- \nsim", ""), ("> sim", "")]


@pytest.mark.parametrize("text, line", READINGS)
def test_reply_line_reads_the_first_phrase_and_the_rest_must_be_a_signature_or_a_quote(text, line):
    assert card_words.reply_line(text) == line
    assert card_words.reply_line(None) == ""


def test_vacuity_the_old_rule_sees_no_word_in_a_signed_reply():
    assert card_words.card_word("sim\n\nEnviado do meu iPhone") is None      # the whole text, as before: more than one phrase
    assert card_words.card_word(card_words.reply_line("sim\n\nEnviado do meu iPhone")) == {"op": "approve", "n": None, "all": False}

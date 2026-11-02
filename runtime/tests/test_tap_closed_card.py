"""A tap on a card whose decision is no longer open (package P2 of SPEC-M41-3-FIXES, finding 2): one plain sentence and nothing done. A card that a revision replaced says
TAP_REPLACED, a card that was approved, cancelled or closed some other way says TAP_CLOSED; neither sentence holds a number, a status word or a command. This holds for a tap on Approve,
Reject and, through the same path, a card word typed as a reply to the card; a typed `/reject 7` keeps its path (the person typed the number). The refusal comes before `run_op`: no
approve and no reject call is made in any case. Offline, no model, on the bridge world of test_channel_grants_cards.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_tap_closed_card.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
from test_channel_grants_cards import GRANTED, approve_action, approve_calls, effect, grant
from test_messaging import world  # noqa: F401  (the bridge world of test_messaging.py)

bridge = st.load("messaging_bridge")
revise = st.load("ops_card_revise")
phrases = st.load("phrases")

REPLACED = {"status": "resolved", "resolution": "rejected", "answer": revise.NOTE}
APPROVED = {"status": "resolved", "resolution": "approved"}
CANCELLED = {"status": "resolved", "resolution": "rejected", "answer": "no"}
EN, PT = {"language": "en"}, {"language": "pt-BR"}
SENTENCE = {"TAP_REPLACED": {"en": "This card was replaced by a newer one, so nothing was done. Use the newer card.",
                             "pt-BR": "Este card foi substitu\u00eddo por um mais novo, ent\u00e3o nada foi feito. Use o card mais novo."},
            "TAP_CLOSED": {"en": "This card was already decided or closed, so nothing was done.",
                           "pt-BR": "Este card j\u00e1 foi decidido ou encerrado, ent\u00e3o nada foi feito."}}


def button(world, key, language="en"):
    """The id of the button of the card (the newest message) whose label is the phrase `key` in `language`."""
    message = world.sent()[-1]["message"]
    return next(a["id"] for a in message["actions"] if pk.said(a["label"], key, PT if language == "pt-BR" else EN))


def reject_calls(world):
    return world.calls("reject")


def closed(world, more, language="en"):
    """A granted effect card sent while open; then the decision becomes `more` (the operations layer's own `card_replaced` is the one the real service has)."""
    grant(world, GRANTED)
    world.config["language"] = language
    world.fake.card_replaced = revise.card_replaced
    world.items[7] = effect()
    world.bridge.tick()
    world.items[7] = {**effect(), **more}


def assert_plain(text, key, language):
    assert text == SENTENCE[key][language]
    assert pk.said(text, key, PT if language == "pt-BR" else EN)
    assert not any(ch.isdigit() for ch in text) and "/" not in text and "resolved" not in text and "resolvido" not in text      # no number, no status word, no command


@pytest.mark.parametrize("language", ["en", "pt-BR"])
@pytest.mark.parametrize("more, key", [(REPLACED, "TAP_REPLACED"), (APPROVED, "TAP_CLOSED"), (CANCELLED, "TAP_CLOSED"), ({"status": "cancelled"}, "TAP_CLOSED")])
def test_a_tap_on_approve_of_a_closed_card_says_one_plain_sentence_and_approves_nothing(world, more, key, language):
    closed(world, more, language)
    world.say(None, action=button(world, "EFFECT_LABEL", language))
    assert_plain(world.texts()[-1], key, language)
    assert approve_calls(world) == [] and reject_calls(world) == []


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_a_tap_on_reject_of_a_replaced_card_says_replaced_and_makes_no_reject_call(world, language):
    closed(world, REPLACED, language)
    world.say(None, action=button(world, "LABEL_REJECT", language))
    assert_plain(world.texts()[-1], "TAP_REPLACED", language)
    assert reject_calls(world) == [] and approve_calls(world) == []


@pytest.mark.parametrize("more", [APPROVED, CANCELLED])
def test_a_tap_on_reject_of_a_card_decided_otherwise_says_closed_and_makes_no_reject_call(world, more):
    closed(world, more)
    world.say(None, action=button(world, "LABEL_REJECT"))
    assert_plain(world.texts()[-1], "TAP_CLOSED", "en")
    assert reject_calls(world) == [] and approve_calls(world) == []


@pytest.mark.parametrize("language", ["en", "pt-BR"])
@pytest.mark.parametrize("more, key", [(REPLACED, "TAP_REPLACED"), (APPROVED, "TAP_CLOSED")])
def test_a_card_word_typed_as_a_reply_to_a_closed_card_says_the_same_and_decides_nothing(world, more, key, language):
    closed(world, more, language)
    [entry] = world.bridge.ledger.data["cards"]
    world.say("sim" if language == "pt-BR" else "yes", reply_to=entry["message_id"])
    assert_plain(world.texts()[-1], key, language)
    assert approve_calls(world) == [] and reject_calls(world) == []


def test_the_typed_approve_of_a_closed_card_says_closed_too(world):
    closed(world, APPROVED)
    world.say("/approve 7")
    assert world.texts()[-1] == SENTENCE["TAP_CLOSED"]["en"] and approve_calls(world) == []


def test_without_card_replaced_in_the_operations_object_a_replaced_card_says_closed(world):
    closed(world, REPLACED)
    del world.fake.card_replaced      # an operations object that does not have it (a test's)
    world.say(None, action=approve_action(world))
    assert world.texts()[-1] == SENTENCE["TAP_CLOSED"]["en"] and approve_calls(world) == []


def test_a_card_replaced_is_true_only_for_a_decision_rejected_with_the_note_of_the_revision():
    assert revise.card_replaced({"resolution": "rejected", "answer": revise.NOTE}) is True
    assert revise.card_replaced({"resolution": "rejected", "answer": "no"}) is False
    assert revise.card_replaced({"resolution": "approved", "answer": revise.NOTE}) is False
    assert revise.card_replaced({"status": "open"}) is False and revise.card_replaced(None) is False


def test_the_two_sentences_are_in_both_languages_of_the_table():
    for key, by_language in SENTENCE.items():
        for language, sentence in by_language.items():
            assert phrases.TABLE[language][key] == sentence
    assert "NOT_OPEN" in phrases.TABLE["en"] and "NOT_OPEN" in phrases.TABLE["pt-BR"]      # other callers keep it

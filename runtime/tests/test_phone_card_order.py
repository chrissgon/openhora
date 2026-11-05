"""The line that introduces a card is sent before the card (slice S16c, runtime/messaging_bridge.py `lead_first`), over the stand-in operations object and the stand-in messenger of
test_messaging.py. Offline, no model, no network; every name and number is invented.

The live case (2026-10-23): "Encontrei: corte de cabelo, ... E este?" arrived AFTER the card it was about. The operations layer hands the bridge the line apart (`result["lead"]`) beside
the reply that holds it; the bridge sends it first, then the card, and the card is the last message (so that the word that follows decides it, limit L64). The reply's other line
(that the card waits) is not sent again once the card has gone out.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_card_order.py
"""
from __future__ import annotations

from test_commands_in_words_bridge import silence
from test_messaging import SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

LEAD = "Found: haircut, Sat 24/10/2026 10:00-11:00. Is this the one?"
NOTICE = "Card #5 waits for your approval."


def answers(world, **more):
    world.fake.answers["say"] = lambda project, **kw: {"reply": LEAD + "\n" + NOTICE, "request_id": None, "pending_id": None, "ran": False, "queued": False, "resend": 5, **more}


def test_the_line_goes_first_and_the_card_is_the_last_message(world):
    world.items[5] = decision("plan", 5, title="Calendar: remove an event")
    answers(world, lead=LEAD)
    world.say("remova o evento corte de cabelos da agenda")
    texts = silence(world)
    assert texts[-2] == LEAD, texts
    assert "#5" in texts[-1] and LEAD not in texts[-1], "the card is the last message and does not repeat the line"
    assert NOTICE not in texts, "the sentence that the card waits is not said again"
    assert texts.index(LEAD) < len(texts) - 1


def test_without_a_lead_the_reply_is_as_it_was(world):
    """Vacuity: with no `lead` the line stays in the reply, which is kept with the card as before (so the order above is the lead's doing)."""
    world.items[5] = decision("plan", 5, title="Calendar: remove an event")
    answers(world)
    world.say("remova o evento corte de cabelos da agenda")
    texts = silence(world)
    assert LEAD in "\n".join(texts), texts
    assert not (texts[-2] == LEAD and "#5" in texts[-1]), "no separate line before the card"


def test_a_card_sent_a_moment_ago_is_sent_again_after_the_line_so_that_the_card_is_still_the_last_message(world):
    """RESEND_EVERY skips a card sent again less than a minute ago and answers True: the line would then be the last message. When a line was sent, the card goes again."""
    world.items[5] = decision("plan", 5, title="Calendar: remove an event")
    answers(world, lead=LEAD)
    world.say("remova o evento corte de cabelos da agenda")
    first = silence(world)
    assert LEAD in first and "#5" in first[-1], first
    world.say("remova o evento corte de cabelos da agenda")      # the same card, named again a moment later
    texts = silence(world)[len(first):]
    assert texts[0] == LEAD and "#5" in texts[-1] and LEAD not in texts[-1], texts
    assert len(texts) == 2, "the line, then the card sent again: it is the last message"


def test_without_a_line_a_card_named_again_within_the_minute_is_not_sent_again(world):
    """Vacuity: with no lead the rule of RESEND_EVERY holds (the card is not flooded), so the test above is the line's doing."""
    world.items[5] = decision("plan", 5, title="Calendar: remove an event")
    answers(world)
    world.say("remova o evento corte de cabelos da agenda")
    first = silence(world)
    world.say("remova o evento corte de cabelos da agenda")
    texts = silence(world)[len(first):]
    assert not any(t.startswith("northwind-shop") for t in texts), "no second card within the minute"

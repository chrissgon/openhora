"""A reply gesture to a card, with a natural request in it (package NR-1): a reply to the planning agent's question card answers THAT card, whatever the text looks
like (a time, a remind word, a forget); the natural reading runs before the reply routing only for a message that is not a card. Over the stand-in world of
test_messaging.py (a fake operations layer that records its calls) and the real bridge. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_reply.py
"""
from __future__ import annotations

import pytest

from test_messaging import world, decision, wait_for  # noqa: F401  (the stand-in world fixture)


def reply_to_question(world, line):  # noqa: F811
    world.items[5] = decision("question", 5, title="When do I publish the post?")
    world.bridge.tick()
    world.fake.answers["answer_proposing"] = {"answered": True}
    world.say(line, reply_to="101")
    for thread in list(world.bridge.threads):
        thread.join(10)


@pytest.mark.parametrize("line", ["The home market.", "friday 10am on instagram", "sexta 10h no instagram", "remind me friday at 10am to check it",
                                  "cancel the reminder banner first", "lembretes", "undo", "me lembra amanhã às 9h de abrir a loja"])      # validate: allow english-only -- a Portuguese line, the case of the tests
def test_a_reply_to_the_question_card_answers_that_card_and_nothing_else(world, line):  # noqa: F811
    reply_to_question(world, line)
    answered = world.calls("answer_proposing")
    assert len(answered) == 1 and answered[0][2]["text"] == line and answered[0][2]["pending_id"] == 5
    assert world.calls("say") == [] and world.calls("remind") == [] and world.calls("reminder-forget") == []


def test_the_same_line_not_sent_as_a_reply_is_read_as_what_it_says(world):  # noqa: F811
    world.say("The home market.")
    assert world.calls("answer_proposing") == []

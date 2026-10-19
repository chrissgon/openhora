"""Reminders asked in the person's own words, through a messaging bridge: round 5 (package NR-1). A reminder in free text is made only after a "yes": the question that
shows the reading carries a one-tap "Yes" button where the platform has buttons, and the typed "yes" works everywhere. A tap on the button of a question that is no longer
the open one (answered, replaced, expired) is told so and makes nothing. The cancel question has the button too. Over the REAL operations layer, a stand-in messenger, a
stand-in planner and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The pure rules are in test_natural_review5.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_review5.py
"""
from __future__ import annotations

import json

import natural_cases_pt_br as pt
from natural_kit import say_yes
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_natural import no_model, portuguese
from test_messaging_queue import WAIT, clocked, planner, settle  # noqa: F401  (the planner stand-in, the bridge's clock and the waiting for its jobs)
from test_messaging_reminders import WITH, day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER
from test_sender_profiles_bridge import OTHER, lab  # noqa: F401  (the lab fixture)


def last_buttons(day, chat=OWNER):  # noqa: F811
    return day.sent(chat)[-1]["message"]["actions"]


def test_the_question_that_shows_the_reading_has_a_yes_button_and_a_tap_makes_the_reminder(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_ORCHID)
    assert day.texts(OWNER)[-1] == pt.ASK_ORCHID and day.all()["open"] == []
    buttons = last_buttons(day)
    assert [b["label"] for b in buttons] == [pt.LABEL_YES], "one tap, one label"
    day.say(OWNER, action=buttons[0]["id"])
    assert day.texts(OWNER)[-1] == pt.REPLY_ORCHID and len(day.all()["open"]) == 1 and day.bridge.remind.drafts == {}
    no_model(planner)


def test_the_typed_yes_still_works_and_the_button_of_an_answered_question_is_told_so(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_ORCHID)
    button = last_buttons(day)[0]["id"]
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.REPLY_ORCHID
    day.say(OWNER, action=button)
    assert day.texts(OWNER)[-1] == pt.EXPIRED and len(day.all()["open"]) == 1, "the question was answered: the old button makes nothing more"
    no_model(planner)


def test_the_button_of_a_question_that_was_replaced_or_expired_makes_nothing(day, planner):  # noqa: F811
    portuguese(day)
    now = clocked(day)
    day.say(OWNER, pt.LINE_ORCHID)
    first = last_buttons(day)[0]["id"]
    day.say(OWNER, "me lembra amanhã às 10h de regar as samambaias")      # validate: allow english-only -- a Portuguese line, the case of the tests
    second = last_buttons(day)[0]["id"]
    assert first != second
    day.say(OWNER, action=first)
    assert day.texts(OWNER)[-1] == pt.EXPIRED and day.all()["open"] == [], "the first question was replaced"
    day.say(OWNER, "me lembra amanhã às 10h de regar as samambaias")      # validate: allow english-only -- a Portuguese line, the case of the tests
    third = last_buttons(day)[0]["id"]
    now[0] += 601
    day.say(OWNER, action=third)
    assert day.texts(OWNER)[-1] == pt.EXPIRED and day.all()["open"] == [], "ten minutes have passed"
    no_model(planner)


def test_the_cancel_question_has_the_button_and_a_tap_cancels(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, pt.LINE_ORCHID)
    day.say(OWNER, "apaga o lembrete do 1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    buttons = last_buttons(day)
    assert [b["label"] for b in buttons] == [pt.LABEL_YES] and len(day.all()["open"]) == 1
    day.say(OWNER, action=buttons[0]["id"])
    assert day.texts(OWNER)[-1].startswith("Lembrete #1 cancelado:") and day.all()["open"] == []
    no_model(planner)


def test_the_questions_that_are_not_yes_questions_have_no_button(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "me lembra amanhã às 9 de regar as orquídeas")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert last_buttons(day) == [], "which of two hours is not a yes"
    day.say(OWNER, pt.LINE_BARE)
    assert last_buttons(day) == [], "reminder or event is not a yes"


def test_a_platform_with_no_buttons_gets_the_plain_question_and_the_typed_yes_makes_it(day, planner):  # noqa: F811
    (day.folder / "caps.json").write_text(json.dumps({"buttons": False, "max_buttons": 0}), encoding="utf-8")
    portuguese(day)
    day.say(OWNER, pt.LINE_ORCHID)
    assert day.texts(OWNER)[-1] == pt.ASK_ORCHID and last_buttons(day) == []
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.REPLY_ORCHID
    no_model(planner)


def test_the_ledger_holds_no_word_of_the_reminder(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_ORCHID)
    ledger = [p for p in day.tmp.rglob("messaging-telegram.json")]
    assert ledger, "the button is bound in the ledger"
    text = ledger[0].read_text(encoding="utf-8")
    assert "orquíde" not in text and "regar" not in text, "the ledger keeps the project, the chat, the message and the action id, never the words"      # validate: allow english-only -- the words of the line
    no_model(planner)

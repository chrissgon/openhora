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
import pytest
from closed_heads import closed_heads, tier1_forms, words_interpreted  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms", "words_interpreted")      # S41-11: every closed form claims a line in this file, as it did


def last_buttons(day, chat=OWNER):  # noqa: F811
    return day.sent(chat)[-1]["message"]["actions"]


def test_the_strict_form_makes_directly_and_a_strict_form_whose_words_begin_with_a_day_is_shown_first(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "/remind 15:00 ligar")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Lembrete #1: hoje, dom 18/10, às 15:00 (BRT): ligar."), "the strict form is made at once"      # validate: allow english-only -- the expected Portuguese sentence
    for line in ("/remind 15:00 amanhã ligar", "/remind in 2h sexta ligar", "/remind 15:00 de amanhã ligar", "/remind 15:00 18/11 ligar", "/remind 15:00 next week call"):      # validate: allow english-only -- Portuguese lines, the cases of the tests
        day.say(OWNER, line)
        assert day.bridge.remind.drafts[OWNER]["need"] in ("confirm", "weekday", "reading", "time", "text"), line
        assert len(day.all()["open"]) == 1, line
        day.bridge.remind.drafts.clear()
    day.say(OWNER, "/remind 9:30 ligar")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert len(day.all()["open"]) == 1 and OWNER not in day.bridge.remind.drafts, "H:MM is a strict form, as it always was: refused by its own grammar, never guessed"
    no_model(planner)

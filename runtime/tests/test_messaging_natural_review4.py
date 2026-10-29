"""Reminders asked in the person's own words, through a messaging bridge: the fourth round of the independent review of #474 (package NR-1). A line in a language with no table
is shown with the moment the engine read, "another time" keeps the day that was shown, "yes, but at 3pm", a "no" to a cancel question says that nothing was cancelled, a
forget with no noun or by numbers alone is shown and confirmed, and a part of the day that has passed is shown as tomorrow's. Over the REAL operations layer, a stand-in
messenger, a stand-in planner and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The pure rules are in test_natural_review4.py. The Portuguese lines and sentences are
in natural_cases_pt_br.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_review4.py
"""
from __future__ import annotations

import natural_cases_pt_br as pt
import phrase_kit as pk
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

PT = {"language": "pt-BR"}


def open_rows(day):  # noqa: F811
    return sorted((r["id"], r["due"], r["text"]) for r in day.all()["open"])


def test_another_time_keeps_the_shown_day_for_an_hour_and_for_a_bare_hour(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    say_yes(day, OWNER, "15h")
    assert pk.said(day.texts(OWNER)[-1], "NT_SET_TEXT", PT, id=1, when="amanhã, seg 19/10, às 15:00 (BRT)", text="troca de óleo")      # validate: allow english-only -- the expected Portuguese date and words of the reply
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    day.say(OWNER, "9")
    assert pk.said(day.texts(OWNER)[-1], "NT_ASK_READINGS", PT, options="amanhã, seg 19/10, às 09:00 ou amanhã, seg 19/10, às 21:00")      # validate: allow english-only -- the expected Portuguese options of the question
    no_model(planner)


def test_a_part_of_the_day_that_has_passed_is_shown_as_tomorrows(day, planner):  # noqa: F811
    day.say(OWNER, "remind me this morning at 9am to call")
    assert pk.said(day.texts(OWNER)[-1], "NT_CONFIRM_TEXT", None, when="09:00 today has passed: tomorrow, Mon 19/10, at 09:00", text="call") and day.all()["open"] == []
    day.say(OWNER, "no")
    assert day.all()["open"] == []
    no_model(planner)



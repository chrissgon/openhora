"""Reminders asked in the person's own words, through a messaging bridge: the third round of the independent review of #474 (package NR-1). A "yes" with courtesies, "another
time", a week named with no day, a forget by a number after another word, by several numbers or by the hour (shown and confirmed), the undo that brings back one reminder
after the other, a "yes" that comes after the question expired, and the notice that a new question replaced an open one. Over the REAL operations layer, a stand-in
messenger, a stand-in planner that records every line a model would have been given, and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The pure rules are in
test_natural_review3.py. The Portuguese lines and sentences are in natural_cases_pt_br.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_review3.py
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


def open_ids(day):  # noqa: F811
    return sorted(r["id"] for r in day.all()["open"])


def test_another_time_asks_for_when_and_keeps_the_words(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert pk.said(day.texts(OWNER)[-1], "NT_ASK_AGAIN", PT) and day.all()["open"] == [] and OWNER in day.bridge.remind.drafts
    say_yes(day, OWNER, "sexta às 10h")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert pk.said(day.texts(OWNER)[-1], "NT_SET_TEXT", PT, id=1, when="sex 23/10 às 10:00 (BRT)", text="troca de óleo")      # validate: allow english-only -- the expected Portuguese date and words of the reply
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    say_yes(day, OWNER, pt.LINE_CLASS)
    assert pk.said(day.texts(OWNER)[-1], "NT_SET_TEXT", PT, id=2, when="amanhã, seg 19/10, às 13:00 (BRT)", text="aula de violão"), "a line that starts a request of its own is not the answer"      # validate: allow english-only -- the expected Portuguese date and words of the reply
    no_model(planner)


def test_a_short_reply_that_does_not_fit_is_asked_once_more_and_then_goes_on_as_a_new_line(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "me lembra às 9 do fisioterapeuta")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert pk.said(day.texts(OWNER)[-1], "NT_ASK_READINGS", PT, options="amanhã, seg 19/10, às 09:00 ou hoje, dom 18/10, às 21:00")      # validate: allow english-only -- the expected Portuguese options of the question
    day.say(OWNER, "sim")
    assert pk.said(day.texts(OWNER)[-1], "NT_ASK_READINGS", PT, options="amanhã, seg 19/10, às 09:00 ou hoje, dom 18/10, às 21:00"), "a yes to two readings does not say which: asked once more"      # validate: allow english-only -- the expected Portuguese words of the reply
    assert settle(day) and planner.texts() == []
    day.say(OWNER, "sim")
    assert settle(day) and planner.texts() == ["sim"] and day.bridge.remind.drafts == {}


def test_a_yes_after_the_question_expired_is_told_so_once_and_any_other_line_is_a_new_one(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_OLEO)
    base = day.bridge.monotonic
    later = base() + 601
    day.bridge.monotonic = lambda: later
    day.say(OWNER, "sim")
    assert pk.said(day.texts(OWNER)[-1], "NT_EXPIRED", PT) and day.all()["open"] == [] and day.bridge.remind.drafts == {}
    assert settle(day) and planner.texts() == []
    day.say(OWNER, "sim")
    assert settle(day) and planner.texts() == ["sim"], "told once: the second yes is a plain line"
    day.say(OWNER, pt.CONFIRM_OLEO)
    after = later + 601
    day.bridge.monotonic = lambda: after
    day.bridge.remind.sweep()
    assert day.bridge.remind.drafts == {} and OWNER in day.bridge.remind.expired
    say_yes(day, OWNER, pt.LINE_CLASS)
    assert OWNER not in day.bridge.remind.expired, "the memory of an expired question goes at the first line"
    day.say(OWNER, "sim")
    assert not pk.said(day.texts(OWNER)[-1], "NT_EXPIRED", PT)



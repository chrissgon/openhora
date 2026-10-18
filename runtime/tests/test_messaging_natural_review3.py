"""Reminders asked in the person's own words, through a messaging bridge: the third round of the independent review of #474 (package NR-1). A "yes" with courtesies, "another
time", a week named with no day, a forget by a number after another word, by several numbers or by the hour (shown and confirmed), the undo that brings back one reminder
after the other, a "yes" that comes after the question expired, and the notice that a new question replaced an open one. Over the REAL operations layer, a stand-in
messenger, a stand-in planner that records every line a model would have been given, and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The pure rules are in
test_natural_review3.py. The Portuguese lines and sentences are in natural_cases_pt_br.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_review3.py
"""
from __future__ import annotations

import natural_cases_pt_br as pt
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_natural import no_model, portuguese
from test_messaging_queue import WAIT, clocked, planner, settle  # noqa: F401  (the planner stand-in, the bridge's clock and the waiting for its jobs)
from test_messaging_reminders import WITH, day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER
from test_sender_profiles_bridge import OTHER, lab  # noqa: F401  (the lab fixture)


def open_ids(day):  # noqa: F811
    return sorted(r["id"] for r in day.all()["open"])


def test_a_yes_with_courtesies_makes_the_confirmed_reminder_and_never_reaches_the_planning_agent(day, planner):  # noqa: F811
    portuguese(day)
    for number, answer in enumerate(pt.YES_ANSWERS, 1):
        day.say(OWNER, pt.CONFIRM_CORTE)
        assert day.texts(OWNER)[-1] == pt.CONFIRM_CORTE_ASK, answer
        day.say(OWNER, answer)
        assert day.texts(OWNER)[-1].startswith(f"Lembrete #{number}: amanhã, seg 19/10, às 13:00 (BRT): corte de cabelo."), answer      # validate: allow english-only -- the expected Portuguese sentence
    assert len(day.all()["open"]) == len(pt.YES_ANSWERS) and day.bridge.remind.drafts == {}
    no_model(planner)


def test_another_time_asks_for_when_and_keeps_the_words(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_CORTE)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_AGAIN and day.all()["open"] == [] and OWNER in day.bridge.remind.drafts
    day.say(OWNER, "sexta às 10h")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == "Lembrete #1: sex 23/10 às 10:00 (BRT): corte de cabelo. Para desfazer: /forget 1."      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, pt.CONFIRM_CORTE)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    day.say(OWNER, pt.LINE_CLASS)
    assert day.texts(OWNER)[-1].startswith("Lembrete #2: amanhã, seg 19/10, às 13:00 (BRT): aula de violão."), "a line that starts a request of its own is not the answer"      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_short_reply_that_does_not_fit_is_asked_once_more_and_then_goes_on_as_a_new_line(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "me lembra às 9 do dentista")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_NINE_FIRST
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.ASK_NINE_FIRST, "a yes to two readings does not say which: asked once more"
    assert settle(day) and planner.texts() == []
    day.say(OWNER, "sim")
    assert settle(day) and planner.texts() == ["sim"] and day.bridge.remind.drafts == {}


def test_a_yes_after_the_question_expired_is_told_so_once_and_any_other_line_is_a_new_one(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_CORTE)
    base = day.bridge.monotonic
    later = base() + 601
    day.bridge.monotonic = lambda: later
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] == pt.EXPIRED and day.all()["open"] == [] and day.bridge.remind.drafts == {}
    assert settle(day) and planner.texts() == []
    day.say(OWNER, "sim")
    assert settle(day) and planner.texts() == ["sim"], "told once: the second yes is a plain line"
    day.say(OWNER, pt.CONFIRM_CORTE)
    after = later + 601
    day.bridge.monotonic = lambda: after
    day.bridge.remind.sweep()
    assert day.bridge.remind.drafts == {} and OWNER in day.bridge.remind.expired
    day.say(OWNER, pt.LINE_CLASS)
    assert OWNER not in day.bridge.remind.expired, "the memory of an expired question goes at the first line"
    day.say(OWNER, "sim")
    assert day.texts(OWNER)[-1] != pt.EXPIRED


def test_a_question_that_replaces_an_open_one_says_so_and_a_made_reminder_does_not(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_CORTE)
    day.say(OWNER, pt.LINE_WEEK)
    assert day.texts(OWNER)[-1] == pt.DISCARDED + " " + pt.ASK_WEEKDAY
    day.say(OWNER, pt.LINE_CLASS)
    assert day.texts(OWNER)[-1].startswith("Lembrete #1:") and pt.DISCARDED not in day.texts(OWNER)[-1]
    day.say(OWNER, pt.LINE_WEEK)
    assert day.texts(OWNER)[-1] == pt.ASK_WEEKDAY, "nothing was open: nothing was discarded"
    no_model(planner)


def test_a_week_with_no_day_asks_the_day_and_the_weekday_answered_is_the_one_of_that_week(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_WEEK)
    assert day.texts(OWNER)[-1] == pt.ASK_WEEKDAY and day.all()["open"] == []
    day.say(OWNER, "terça")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == "Lembrete #1: ter 20/10 às 10:00 (BRT): pagar o aluguel. Para desfazer: /forget 1."      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, pt.LINE_WEEK_NO_TIME)
    day.say(OWNER, "sexta")
    assert day.texts(OWNER)[-1] == "Sex 23/10: a que horas? Responda com uma hora, por exemplo 13h."
    day.say(OWNER, "9")
    assert day.texts(OWNER)[-1].startswith("Qual horário você quer: sex 23/10 às 09:00 ou sex 23/10 às 21:00?")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "9h")
    assert day.texts(OWNER)[-1] == "Lembrete #2: sex 23/10 às 09:00 (BRT): pagar o aluguel. Para desfazer: /forget 2."      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_scheduling_verb_with_the_word_reminder_makes_a_reminder_at_once(day, planner):  # noqa: F811
    portuguese(day)
    for number, line in enumerate((pt.LINE_MARCA_LEMBRETE, pt.LINE_AGENDE_LEMBRETE), 1):
        day.say(OWNER, line)
        assert day.texts(OWNER)[-1] == f"Lembrete #{number}: amanhã, seg 19/10, às 09:00 (BRT): pagar o boleto. Para desfazer: /forget {number}."      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_number_after_another_word_is_shown_and_confirmed_before_it_cancels_anything(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, "cancela o lembrete do 1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_FORGET_ONE and open_ids(day) == [1]
    day.say(OWNER, "não")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == pt.CANCELLED and open_ids(day) == [1] and day.bridge.remind.drafts == {}
    day.say(OWNER, "esquece o lembrete de 1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "sim, pode")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == pt.FORGOT_ONE and open_ids(day) == [] and day.bridge.remind.drafts == {}
    day.say(OWNER, "desfaz")
    assert day.texts(OWNER)[-1] == pt.RESTORED and open_ids(day) == [2]
    day.say(OWNER, "cancela o lembrete 2")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Lembrete #2 cancelado:"), "an explicit number acts at once"      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_forget_by_the_hour_is_matched_against_the_moment_and_confirmed(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_TWO_BOLETOS)
    day.say(OWNER, "cancela o lembrete das 15h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == "Cancelar o lembrete #2: amanhã, seg 19/10, às 15:00 (BRT): pagar 2 boletos? (sim / não)"      # validate: allow english-only -- the expected Portuguese sentence
    assert open_ids(day) == [1, 2]
    day.say(OWNER, "sim")
    assert open_ids(day) == [1] and day.texts(OWNER)[-1].startswith("Lembrete #2 cancelado:")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, pt.LINE_FORGET_NINE)
    assert day.texts(OWNER)[-1] == pt.NO_MATCH and open_ids(day) == [1]
    no_model(planner)


def test_several_numbers_are_shown_together_and_all_are_cancelled_on_a_yes(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_TWO_BOLETOS)
    day.say(OWNER, "cancela o lembrete 1 e 2")      # validate: allow english-only -- a Portuguese line, the case of the tests
    question = day.texts(OWNER)[-1]
    assert question.startswith("Cancelar estes lembretes? (sim / não)") and "#1 amanhã" in question and "#2 amanhã" in question      # validate: allow english-only -- the expected Portuguese sentence
    assert open_ids(day) == [1, 2]
    day.say(OWNER, "sim")
    assert open_ids(day) == [] and day.bridge.remind.drafts == {}
    day.say(OWNER, "cancela o lembrete 7 e 8")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert open_ids(day) == [] and day.texts(OWNER)[-1] == "Não há lembrete 7 esperando por você." and day.bridge.remind.drafts == {}      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_number_that_is_another_senders_is_answered_as_one_that_does_not_exist_even_to_be_confirmed(day, planner):  # noqa: F811
    day.say(OTHER, "remind me tomorrow at 1 pm to take the bread out")
    day.say(OWNER, "cancel the reminder of 1")
    assert day.bridge.remind.drafts == {} and "No reminder 1 waits for you." in day.texts(OWNER)[-1]
    assert open_ids(day) == [1]


def test_the_undo_brings_the_reminders_back_one_after_the_other_the_most_recent_first(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.LINE_CLASS)
    day.say(OWNER, pt.LINE_TWO_BOLETOS)
    day.say(OWNER, "cancela o lembrete 1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "cancela o lembrete 2")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, pt.LINE_UNDO)
    assert day.texts(OWNER)[-1].startswith("O lembrete #2 está de volta como #3")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, pt.LINE_UNDO)
    assert day.texts(OWNER)[-1].startswith("O lembrete #1 está de volta como #4")      # validate: allow english-only -- the expected Portuguese sentence
    assert open_ids(day) == [3, 4]
    day.say(OWNER, "desfaz o commit")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert settle(day) and planner.texts() == ["desfaz o commit"], "anything but the bare word goes on to the planning agent"      # validate: allow english-only -- the line above

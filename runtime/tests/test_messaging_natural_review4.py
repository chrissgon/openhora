"""Reminders asked in the person's own words, through a messaging bridge: the fourth round of the independent review of #474 (package NR-1). A line in a language with no table
is shown with the moment the engine read, "another time" keeps the day that was shown, "yes, but at 3pm", a "no" to a cancel question says that nothing was cancelled, a
forget with no noun or by numbers alone is shown and confirmed, and a part of the day that has passed is shown as tomorrow's. Over the REAL operations layer, a stand-in
messenger, a stand-in planner and a stand-in clock (Sunday 2026-10-18 14:00 at -03:00). The pure rules are in test_natural_review4.py. The Portuguese lines and sentences are
in natural_cases_pt_br.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_natural_review4.py
"""
from __future__ import annotations

import natural_cases_pt_br as pt
from natural_kit import say_yes
from test_effects import tree  # noqa: F401  (the stand-in tree fixture)
from test_messaging_natural import no_model, portuguese
from test_messaging_queue import WAIT, clocked, planner, settle  # noqa: F401  (the planner stand-in, the bridge's clock and the waiting for its jobs)
from test_messaging_reminders import WITH, day, listed  # noqa: F401  (the day fixture: a clock and a lab with a reminders profile)
from test_sender_profiles import OWNER
from test_sender_profiles_bridge import OTHER, lab  # noqa: F401  (the lab fixture)


def open_rows(day):  # noqa: F811
    return sorted((r["id"], r["due"], r["text"]) for r in day.all()["open"])


def test_a_line_in_a_language_with_no_table_is_shown_with_the_moment_that_was_read_and_nothing_is_made_until_the_person_says(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, "rappelle-moi vendredi à 21h30 de payer l'électricité")      # validate: allow english-only -- a French line, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Hoje, dom 18/10, às 21:30:") and day.texts(OWNER)[-1].endswith("sua agenda?")      # validate: allow english-only -- the expected Portuguese sentence
    assert day.all()["open"] == []
    day.say(OWNER, "sexta")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Sex 23/10 às 21:30:") and day.texts(OWNER)[-1].endswith("sua agenda?") and day.all()["open"] == [], "a line with no remind word of a table is also asked reminder or event"      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "lembrete")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Lembrete #1: sex 23/10 às 21:30 (BRT):")      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_date_with_no_cue_is_read_shown_and_made_only_on_a_yes(day, planner):  # noqa: F811
    day.say(OWNER, "remind me May 5 at 9am to pay rent")
    assert day.texts(OWNER)[-1] == "I understood: Wed 05/05/2027 at 09:00: pay rent. Confirm? (yes / another time)" and day.all()["open"] == []
    day.say(OWNER, "yes")
    assert open_rows(day) == [(1, "2027-05-05 09:00", "pay rent")]
    portuguese(day)
    day.say(OWNER, "me lembra no Natal às 9h de ligar pra vó")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Entendi: 09:00 de hoje já passou: amanhã, seg 19/10, às 09:00:") and len(day.all()["open"]) == 1      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_another_time_keeps_the_shown_day_for_an_hour_and_for_a_bare_hour(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    say_yes(day, OWNER, "15h")
    assert day.texts(OWNER)[-1] == "Lembrete #1: amanhã, seg 19/10, às 15:00 (BRT): troca de óleo. Para desfazer: /forget 1."      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "outra hora")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    day.say(OWNER, "9")
    assert day.texts(OWNER)[-1] == "Qual horário você quer: amanhã, seg 19/10, às 09:00 ou amanhã, seg 19/10, às 21:00? Responda com a hora."      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)


def test_a_yes_with_a_new_hour_and_a_no_thanks(day, planner):  # noqa: F811
    portuguese(day)
    day.say(OWNER, pt.CONFIRM_OLEO)
    say_yes(day, OWNER, "sim mas às 15h")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Lembrete #1: amanhã, seg 19/10, às 15:00 (BRT):")      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, pt.CONFIRM_OLEO)
    day.say(OWNER, "nao obrigado")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == pt.CANCELLED and len(day.all()["open"]) == 1
    no_model(planner)


def test_a_part_of_the_day_that_has_passed_is_shown_as_tomorrows(day, planner):  # noqa: F811
    day.say(OWNER, "remind me this morning at 9am to call")
    assert day.texts(OWNER)[-1] == "I understood: 09:00 today has passed: tomorrow, Mon 19/10, at 09:00: call. Confirm? (yes / another time)" and day.all()["open"] == []
    day.say(OWNER, "no")
    assert day.all()["open"] == []
    no_model(planner)


def test_a_forget_with_no_noun_is_shown_and_confirmed_and_one_with_no_such_reminder_is_a_plain_line(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, pt.LINE_CLASS)
    day.say(OWNER, "cancela #1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.ASK_FORGET_ONE and open_rows(day)[0][0] == 1
    day.say(OWNER, "não")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1] == pt.KEPT and len(day.all()["open"]) == 1
    day.say(OWNER, "cancela o 99")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert settle(day) and planner.texts() == ["cancela o 99"], "no such reminder: not a request about reminders, a plain line"      # validate: allow english-only -- the line above
    day.say(OWNER, "cancela o lembrete n° 1")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1] == pt.FORGOT_ONE and day.all()["open"] == [], "an explicit number acts at once"


def test_a_forget_by_numbers_alone_in_the_words_is_shown_and_a_name_acts(day, planner):  # noqa: F811
    portuguese(day)
    say_yes(day, OWNER, "me lembra amanhã às 9h de pagar a parcela 3")      # validate: allow english-only -- a Portuguese line, the case of the tests
    say_yes(day, OWNER, "me lembra amanhã às 10h de ligar pra floricultura")      # validate: allow english-only -- a Portuguese line, the case of the tests
    day.say(OWNER, "cancela o lembrete sobre 3")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Cancelar o lembrete #1:") and len(day.all()["open"]) == 2      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "sim, cancela")      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Lembrete #1 cancelado:") and len(day.all()["open"]) == 1      # validate: allow english-only -- the expected Portuguese sentence
    day.say(OWNER, "cancela o lembrete sobre floricultura")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert day.texts(OWNER)[-1].startswith("Lembrete #2 cancelado:") and day.all()["open"] == [], "a name acts at once"      # validate: allow english-only -- the expected Portuguese sentence
    no_model(planner)

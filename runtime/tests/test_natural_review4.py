"""Natural requests, tier 1, the fourth round of the independent review of #474 (package NR-1): the GUARD (what a line says outside the time phrases it read may be a date
it did not read, or the line may be in a language no table knows: the reading is shown and confirmed, never made), the ordinals ("1º", "primeiro"), "quarter past",
the day kept by "another time", the explicit forms of a reminder number, the answer to "which day next week?", a part of the day that has passed, repetitions with no
"every", "yes, but at 3pm", "no thanks", a Sunday said on a Sunday, a duration with no hour, and the engine's own words. The corpora are in test_natural_corpus.py. The
conversation through a bridge is in test_messaging_natural_review4.py. Offline, no model, no network; invented words. The Portuguese lines are in natural_cases_pt_br.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_review4.py
"""
from __future__ import annotations

import datetime

import pytest

import natural_cases_pt_br as pt
import standin_tree as st
from closed_heads import trigger_reading  # noqa: F401  (S41-11 PR 2b: the reminder engine's old entry, the way `trigger`, for the tests that read a line that starts with a remind word)
from natural_kit import made, said_yes
from test_attachments import case  # noqa: F401  (the project the attachment tests use, which the world fixture builds on)
from test_reminders import BRT, OTHER, SENDER, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

pytestmark = pytest.mark.usefixtures("trigger_reading")
natural = st.load("natural")
nt = st.load("natural_time")
ops = st.load("ops")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=BRT)       # Sunday


def completed(draft, said, now=NOW):
    """`natural.complete`, and the "yes" that makes the reminder when the answer was a reading shown for confirmation (a free-text reminder is made only after a yes)."""
    got = natural.complete(draft, said, now)
    if got and "ask" in got and got["ask"]["need"] == "confirm" and not got["ask"].get("retries"):
        return natural.complete(got["ask"], "yes", now)
    return got


def outcome(line, now=NOW, how="trigger"):
    got = natural.understand(line, now, how)
    if "ask" not in got:
        return ("when", got["when"])
    ask = got["ask"]
    return ("confirm", ask["readings"][0]["when"]) if ask["need"] == "confirm" else (ask["need"], None)


def asked(line, now=NOW, how="trigger"):
    return natural.understand(line, now, how)["ask"]


# --- the guard -------------------------------------------------------------------------------------------------------------------------------------

EN_GUARD = ["remind me May 5 at 9am to pay rent", "remind me may 5 at 9am to pay rent", "remind me to pay rent May 5 at 9am", "remind me May 5th at 9am to pay rent",
            "remind me 5 May at 9am to pay rent", "remind me the 5th of May at 9am to pay rent", "remind me to pay rent in December at 9am", "remind me at Christmas at 9am to call grandma",
            "remind me tomorrow at 9am about the easter dinner", "remind me tomorrow at 9am to pay on the 5th", "remind me tomorrow at 9am to pay by 5", "remind me tomorrow at 9am to call on friday",
            "remind me tomorrow at 9am to call before tomorrow", "remind me tomorrow at 9am about the holiday"]


@pytest.mark.parametrize("line", EN_GUARD + pt.GUARD_LINES)
def test_a_date_the_reading_did_not_use_or_a_language_with_no_table_is_confirmed_never_made(line):
    got = natural.understand(line, NOW, "trigger")
    assert "ask" in got and got["ask"]["need"] in ("confirm", "reading", "time"), line


def test_may_with_a_day_beside_it_is_read_as_the_date_and_shown_with_its_year():
    for line in ("remind me May 5 at 9am to pay rent", "remind me 5 May at 9am to pay rent", "remind me the 5th of May at 9am to pay rent", "remind me May 5th at 9am to pay rent"):
        ask = asked(line)
        assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "2027-05-05 09:00" and ask["text"] == "pay rent", line
        assert completed(ask, "yes", NOW)["when"] == "2027-05-05 09:00"


@pytest.mark.parametrize("line,when", pt.ORDINAL_LINES)
def test_the_first_of_a_month_is_a_1_however_it_is_written(line, when):
    assert made(natural, line, NOW)["when"] == when


def test_the_foreign_lines_are_shown_with_the_moment_the_engine_read_and_the_person_corrects_it():
    ask = asked("rappelle-moi vendredi à 21h30 de payer l'électricité")
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "21:30", "the clock was read, the day was not: it is shown, and the person says the day"
    assert completed(ask, "friday", NOW)["when"] == "2026-10-23 21:30"
    assert completed(ask, "yes", NOW)["when"] == "2026-10-18 21:30"
    assert completed(ask, "no", NOW) == {"cancel": True}


def test_a_line_in_a_language_with_a_table_and_a_trigger_is_not_asked_about_for_its_own_words():
    for line in ("remind me tomorrow at 9am to call the florist", "remind me tomorrow at 9am to water the plants", "me lembra amanhã às 9h de regar as plantas",      # validate: allow english-only -- a Portuguese line, the case of the tests
                 "remind me tomorrow at 9am to take the bread out", "remind me tomorrow at 9am to set the table"):
        assert "when" in made(natural, line, NOW), line


def test_a_typed_command_is_a_reminder_by_its_form_and_its_words_are_not_judged():
    got = made(natural, "amanha 9h pilates", NOW, "command")
    assert got["when"] == "2026-10-19 09:00" and got["text"] == "pilates"


def test_an_abbreviation_of_another_language_in_the_words_is_just_a_word():
    for line in ("remind me tomorrow at 9am to take the bread out", "remind me tomorrow at 9am to sort the mail", "remind me tomorrow at 9am to see the sea"):
        assert "when" in made(natural, line, NOW), line


def test_a_weak_word_that_was_not_the_date_stays_in_the_words():
    for line, text in (("remind me at 9am that Dr. Mon called", "that Dr. Mon called"), ("remind me to email Fri Hotel at 9am", "email Fri Hotel"),
                       ("remind me at 9am to see Wed", "see Wed")):
        ask = asked(line)
        assert ask["need"] == "confirm" and nt.normalise(text)[0].split()[-1] in nt.normalise(ask["text"])[0], line
    ask = asked("me lembra ligar pra Sex Shop às 9h")      # validate: allow english-only -- a Portuguese line, the case of the tests
    assert "Sex Shop" in ask["text"]


# --- quarter past, spoken hours, "3 e meia da tarde" --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line,when", [("remind me at quarter past 4 pm to call", "2026-10-18 16:15"), ("remind me at quarter to 5 pm to call", "2026-10-18 16:45"),
                                       ("remind me at half past 4 pm to call", "2026-10-18 16:30"), ("remind me at a quarter past 9am to call", "2026-10-19 09:15"),
                                       ("remind me tomorrow at half past 7 pm to call", "2026-10-19 19:30")])
def test_quarter_past_and_to_and_half_past(line, when):
    assert made(natural, line, NOW)["when"] == when, line


def test_a_quarter_with_no_meridiem_offers_both_hours():
    ask = asked("remind me at quarter past 4 to call")
    assert ask["need"] == "reading" and sorted(r["time"] for r in ask["readings"]) == ["04:15", "16:15"]


def test_spoken_hours_and_half_hours_of_a_part_of_the_day_are_read():
    assert made(natural, pt.LINE_HALF_AFTERNOON, NOW)["when"] == "2026-10-19 15:30"
    ask = asked(pt.LINE_SPOKEN)
    assert ask["need"] == "reading" and [r["time"] for r in ask["readings"]] == ["09:00", "21:00"], "a spoken hour with no marker is asked like a number"
    assert outcome("remind me tomorrow morning at 9 to call") == ("confirm", "2026-10-19 09:00")
    assert outcome("remind me tomorrow at nine to call")[0] == "reading"


# --- another time ------------------------------------------------------------------------------------------------------------------------------------


def test_another_time_keeps_the_day_the_person_was_shown():
    shown = asked(pt.CONFIRM_OLEO)
    again = completed(shown, "outra hora", NOW)["ask"]      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert again["need"] == "again" and again["date"] == "2026-10-19"
    assert completed(again, "15h", NOW)["when"] == "2026-10-19 15:00", "tomorrow, as it was shown, at the new hour"
    nine = completed(again, "9", NOW)["ask"]
    assert [r["when"] for r in nine["readings"]] == ["2026-10-19 09:00", "2026-10-19 21:00"], "a bare hour offers both, on the shown day"
    assert completed(again, "sexta às 10h", NOW)["when"] == "2026-10-23 10:00", "a day the person names replaces it"      # validate: allow english-only -- a Portuguese answer, the case of the tests
    en = completed(asked("remind me tomorow at 1pm to call"), "another time", NOW)["ask"]
    assert completed(en, "3pm", NOW)["when"] == "2026-10-19 15:00" and completed(en, "9", NOW)["ask"]["readings"][1]["when"] == "2026-10-19 21:00"


@pytest.mark.parametrize("answer", ["yes, but at 3pm", "yes but 3pm", "sure, but at 3pm please"])
def test_a_yes_with_a_new_hour_is_that_hour(answer):
    assert completed(asked("remind me tomorow at 1pm to call"), answer, NOW)["when"] == "2026-10-19 15:00", answer


def test_a_yes_with_a_new_hour_in_portuguese():
    draft = asked(pt.CONFIRM_OLEO)
    assert completed(draft, "sim mas às 15h", NOW)["when"] == "2026-10-19 15:00"      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert completed(draft, "sim, mas amanhã às 16h", NOW)["when"] == "2026-10-19 16:00"      # validate: allow english-only -- a Portuguese answer, the case of the tests


@pytest.mark.parametrize("answer", ["no thanks", "no, thanks", "never mind", pt.NO_THANKS[0], pt.NO_THANKS[1]])
def test_no_thanks_is_a_no(answer):
    draft = asked("remind me tomorow at 1pm to call" if answer.isascii() and answer in ("no thanks", "no, thanks", "never mind") else pt.CONFIRM_OLEO)
    assert completed(draft, answer, NOW) == {"cancel": True}, answer


def test_a_no_to_a_cancel_question_says_nothing_was_cancelled():
    draft = {**natural._draft("forget", "trigger", "", ""), "ids": [3], "sentence": "x"}
    assert completed(draft, "no", NOW) == {"cancel": True, "kept": True}
    assert completed(draft, "no thanks", NOW) == {"cancel": True, "kept": True}
    assert completed(draft, "yes, cancel", NOW) == {"forget": [3]}, "the word cancel is the action in this question"
    assert completed(draft, "cancel", NOW)["ask"]["retries"] == 1, "'cancel' to 'cancel it?' does not say which way"


# --- Q1: the forms of a reminder number ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", pt.ID_FORMS + ["forget reminder no. 4", "forget reminder nr 4", "forget the reminder n° 4"])
def test_an_explicit_number_acts_at_once_in_every_form_that_says_it_is_one(line):
    got = natural.candidate(line)
    assert got["op"] == "reminder-forget" and got["id"] in (3, 4) and "confirm" not in got, line


@pytest.mark.parametrize("line", pt.BARE_FORGET + ["cancel #4", "delete 3", "forget 3"])
def test_a_forget_with_no_noun_is_shown_and_confirmed(line):
    got = natural.candidate(line)
    assert got["op"] == "reminder-forget" and got["confirm"] is True and got["bare"] is True and got["id"] in (3, 4), line


@pytest.mark.parametrize("line,at", [("cancel the 9am reminder", "9am"), ("remove the 3pm reminder", "3pm"), ("cancela o lembrete das 9", "das 9")])
def test_a_forget_by_the_hour_is_matched_against_the_moment_and_confirmed(line, at):
    got = natural.candidate(line)
    assert got == {"op": "reminder-forget", "how": "trigger", "id": None, "at": at, "confirm": True}


def test_nothing_but_numbers_in_a_forget_is_shown_never_acted_on(world):  # noqa: F811
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 1 pm to pay installment 3")
    said_yes(ops, world.path, SENDER, "remind me tomorrow at 2 pm to call the florist")
    shown = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["3"])
    assert shown["preview"]["id"] == 1 and [r["status"] for r in world.rows()] == ["open", "open"], "the word 3 is in reminder 1: shown, not cancelled"
    done = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, matching=["florist"])
    assert done["reminder"]["id"] == 2, "a name still acts at once"


# --- Q3: the week -------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line,when", [(pt.LINE_WEEK_MONDAY, "2026-10-26 09:00"), (pt.LINE_WEEK_FRIDAY, "2026-10-30 09:00"),
                                       ("remind me tuesday next week at 10am to pay", "2026-10-27 10:00"), ("remind me next week on friday at 3pm to pay", "2026-10-30 15:00")])
def test_a_weekday_of_next_week_is_the_day_of_that_week_and_is_always_confirmed(line, when):
    ask = asked(line)
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == when, line
    assert completed(ask, "yes", NOW)["when"] == when


def test_the_answer_to_which_day_next_week_is_always_shown_with_the_day_it_resolved_to():
    ask = asked("remind me next week at 10am to pay rent")
    for answer in ("monday", "tuesday", "sunday", "friday at 3pm", "the 27th"):
        shown = natural.complete(ask, answer, NOW)
        assert shown["ask"]["need"] == "confirm", answer
    assert natural.complete(natural.complete(ask, "monday", NOW)["ask"], "another time", NOW)["ask"]["need"] == "again", "and the person can say it is the other Monday"


# --- a part of the day that has passed, the same weekday as today -----------------------------------------------------------------------------------


@pytest.mark.parametrize("line,now", [("remind me this morning at 9 to call", NOW), ("remind me this afternoon at 1pm to call", NOW), ("remind me this evening at 8 to call", NOW.replace(hour=22, minute=30)),
                                      ("remind me tonight at 9 to call", NOW.replace(hour=22, minute=30)), ("remind me tonight at 10pm to call", NOW.replace(hour=22, minute=30))])
def test_a_part_of_the_day_that_has_passed_is_shown_as_tomorrows_never_rolled_silently(line, now):
    ask = asked(line, now)
    assert ask["need"] == "confirm" and ask["readings"][0]["rolled"] is True, line


def test_a_part_of_the_day_still_ahead_is_made_and_today_with_a_past_hour_is_still_refused():
    assert outcome("remind me this evening at 8 to call") == ("confirm", "20:00")
    assert outcome("remind me tonight at 9 to call") == ("confirm", "21:00")
    assert made(natural, "remind me today at 9am to call", NOW)["when"] == "2026-10-18 09:00", "the grammar's refusal stays: a past hour of today"


@pytest.mark.parametrize("line", ["remind me sunday at 8pm to call", pt.LINE_SUNDAY, "remind me on sunday at 8pm to call"])
def test_the_weekday_of_today_is_today_or_the_next_one_and_is_confirmed(line):
    ask = asked(line)
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "2026-10-18 20:00", line
    assert outcome("remind me monday at 8pm to call") == ("confirm", "2026-10-19 20:00"), "another weekday is a plain confirmation"


# --- repetitions ---------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", pt.REPEAT_MORE + ["remind me twice a day to take meds", "remind me nightly at 10pm to lock up", "remind me hourly to drink water",
                                                   "remind me on weekdays at 9am to clock in", "remind me every half hour to stretch", "remind me once a week to feed the cat"])
def test_more_ways_to_say_a_routine_are_said_to_be_a_routines(line):
    assert natural.understand(line, NOW)["ask"]["need"] == "recurring", line


def test_all_the_hours_logged_is_text_and_a_unit_with_a_number_is_a_routine():
    got = made(natural, pt.LINE_HOURS_TEXT, NOW)
    assert got["when"] == "2026-10-19 09:00" and got["text"] == "revisar todas as horas lançadas"      # validate: allow english-only -- the words of the line
    assert natural.understand("me lembra a cada 2 horas de beber água", NOW)["ask"]["need"] == "recurring"      # validate: allow english-only -- a Portuguese line, the case of the tests


# --- a duration with no hour ---------------------------------------------------------------------------------------------------------------------------


def test_a_duration_of_days_asks_the_hour_and_the_hour_answer_makes_it():
    for line in (pt.LINE_DAYS, "remind me in 3 days to pay", "remind me in 1 week to pay"):
        ask = asked(line)
        assert ask["need"] == "time" and ask["day"]["date"] in ("2026-10-21", "2026-10-25"), line
    ask = asked(pt.LINE_DAYS)
    assert completed(ask, "9h", NOW)["when"] == "2026-10-21 09:00"
    assert [r["when"] for r in completed(ask, "9", NOW)["ask"]["readings"]] == ["2026-10-21 09:00", "2026-10-21 21:00"]
    assert made(natural, "remind me in 2 hours to pay", NOW)["when"] == "2026-10-18 16:00", "a duration of hours is a moment, pinned to the one shown"
    assert made(natural, "remind me in 2 days at 9am to pay", NOW)["when"] == "2026-10-20 09:00"
    assert made(natural, "remind me in 400 days to pay", NOW)["when"] == "2027-11-22 14:00", "too far ahead is the grammar's refusal, not a question about the hour"


# --- the engine and its words ------------------------------------------------------------------------------------------------------------------------------


def test_the_words_of_every_table_are_known_words_and_a_typo_of_one_is_not_a_typo():
    known = nt.known_words(nt.languages())
    assert {"todas", "mas", "natal", "monday", "tomorrow", "amanha"} <= known
    assert nt.doubts("me lembra amanhã às 9h de revisar todas as horas", None)[0] is False, "'todas' is a word, not a typo of 'today'"      # validate: allow english-only -- a Portuguese line, the case of the tests


def test_the_guard_reads_the_leftover_and_nothing_else():
    tables = nt.languages()
    found = nt.find("remind me tomorrow at 9am to call Ana", tables)
    assert nt.leftover_doubt(found, (0, 9), tables, unknown=False) is False
    found = nt.find("call Ana tomorrow at 9am", tables)
    assert nt.leftover_doubt(found, None, tables, unknown=True) is True, "words no table holds, and no trigger: the line may be in another language"
    found = nt.find("remind me tomorrow at 9am to pay on 5", tables)
    assert nt.leftover_doubt(found, (0, 9), tables, unknown=False) is True, "a date marker with a number beside it, left over"
    found = nt.find("remind me tomorrow at 9am to visit december", tables)
    assert nt.leftover_doubt(found, (0, 9), tables, unknown=False) is True


def test_a_table_of_the_schema_holds_the_keys_of_this_round():
    for table in nt.languages():
        for key in ("first_words", "ordinal_marks", "quarter_past", "quarter_to", "half_past", "date_markers", "date_nouns", "recurrence_phrases", "recurrence_counted_units", "but_words"):
            assert isinstance(table[key], list), key
        assert "id_marked" in table["forget"] and "again" in table["answers"] and set(table["vague_parts"]) == {"morning", "afternoon", "evening", "night"}

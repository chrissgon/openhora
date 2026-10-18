"""Natural requests, tier 1, the third round of the independent review of #474 (package NR-1): a weak word of a day is the day next to the time or a number and is
confirmed, never dropped, where it may be a name; a repeating word counts only inside the time phrase; the answers to a question (a yes with courtesies, "another
time", a bare hour, a day, a dotted hour, a short reply that does not fit); a week named with no day; a forget by a number after another word, by several numbers or by
the hour; the bare undo; "marca um lembrete" and "schedule a reminder"; the common misspellings as data; a typo is never a name and never drops a word; a part of the
day beside an hour; the operation that restores the most recent reminder not already back and the preview of a forget. The conversation through a bridge is in
test_messaging_natural_review3.py. Offline, no model, no network; invented words. The Portuguese lines are in natural_cases_pt_br.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_review3.py
"""
from __future__ import annotations

import datetime

import pytest

import natural_cases_pt_br as pt
import standin_tree as st
from test_attachments import case  # noqa: F401  (the project the attachment tests use, which the world fixture builds on)
from test_reminders import BRT, OTHER, SENDER, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

natural = st.load("natural")
nt = st.load("natural_time")
ops = st.load("ops")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=BRT)       # Sunday


def outcome(line, how="trigger"):
    """("when", the moment) when the line makes a reminder, ("confirm", the moment) when the reading is shown, (the need, None) for any other question."""
    got = natural.understand(line, NOW, how)
    if "ask" not in got:
        return ("when", got["when"])
    ask = got["ask"]
    return ("confirm", ask["readings"][0]["when"]) if ask["need"] == "confirm" else (ask["need"], None)


def asked(line, how="trigger"):
    return natural.understand(line, NOW, how)["ask"]


# --- B1: a weak word of a day ---------------------------------------------------------------------------------------------------------------------------

EN_NAME_LINES = [
    ("remind me on May 5 at 9am to pay rent", ("confirm", "2027-05-05 09:00")),          # a date that has passed this year: next year's, confirmed
    ("remind me Dec 5 at 9am to pay rent", ("when", "2026-12-05 09:00")),
    ("remind me on Dec 5 at 9am to pay rent", ("when", "2026-12-05 09:00")),
    ("remind me Mar 3 at 9am to pay rent", ("confirm", "2027-03-03 09:00")),
    ("remind me Jan 2 at 9am to pay rent", ("confirm", "2027-01-02 09:00")),
    ("remind me Fri at 9am to call Ana", ("when", "2026-10-23 09:00")),
    ("remind me to call Fri Hotel at 9am", ("confirm", "2026-10-23 09:00")),
    ("remind me to call fri hotel at 9am", ("confirm", "2026-10-23 09:00")),
    ("remind me tomorrow at 9am to call May", ("when", "2026-10-19 09:00")),
]


@pytest.mark.parametrize("line,expected", EN_NAME_LINES + pt.NAME_LINES)
def test_a_weak_word_next_to_the_time_or_a_number_is_the_day_and_anywhere_else_it_is_confirmed_never_dropped(line, expected):
    assert outcome(line) == expected, line


def test_a_weak_word_that_may_be_a_name_is_confirmed_with_the_words_it_left():
    ask = asked("remind me to call fri hotel at 9am")
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "2026-10-23 09:00" and ask["text"] == "call hotel"
    assert natural.complete(ask, "yes", NOW)["when"] == "2026-10-23 09:00"
    assert natural.complete(ask, "no", NOW) == {"cancel": True}, "a name: the person says so"
    capital = asked("remind me to call Fri Hotel at 9am")
    assert capital["need"] == "confirm" and capital["text"] == "call Hotel"


# --- M1: a repetition is part of the time phrase ----------------------------------------------------------------------------------------------------

EN_REPEAT = ["remind me every monday at 9am to call", "remind me daily at 9am to stretch", "remind me every 2 hours to drink water", "remind me each day at 7 to open the window",
             "remind me weekly to check the mail", "remind me every other friday at 3pm to report", "remind me monthly on the 5th at 9am to pay"]
EN_TEXT = ["remind me tomorrow at 9am to send the weekly report", "remind me tomorrow at 9am to thank each supplier", "remind me tomorrow at 9am to call every client",
           "remind me tomorrow at 9am to pay the monthly invoice", "remind me tomorrow at 9am to check every day of the month"]


@pytest.mark.parametrize("line", EN_REPEAT + pt.REPEAT_LINES)
def test_a_repeating_word_inside_the_time_phrase_is_a_routines(line):
    assert natural.understand(line, NOW)["ask"]["need"] == "recurring", line


@pytest.mark.parametrize("line", EN_TEXT + pt.REPEAT_TEXT_LINES)
def test_the_same_words_inside_the_reminders_own_text_are_text_and_the_reminder_is_made(line):
    got = natural.understand(line, NOW)
    assert "when" in got and got["when"] == "2026-10-19 09:00", line
    assert not nt.recurring(line), line


# --- M2: the answers to a question ---------------------------------------------------------------------------------------------------------------------


def confirm_draft():
    return asked("remind me tomorow at 1pm to call the dentist")


@pytest.mark.parametrize("answer", ["yes", "yes please", "yes, go ahead", "ok thanks", "sure", "of course", "Yes!", "YES.", "yes yes", "sounds good", "exactly"])
def test_a_yes_with_courtesies_around_it_is_a_yes(answer):
    assert natural.complete(confirm_draft(), answer, NOW)["when"] == "2026-10-19 13:00", answer
    assert natural.affirm(answer)


@pytest.mark.parametrize("answer", pt.YES_ANSWERS)
def test_a_yes_in_portuguese_with_courtesies_around_it_is_a_yes(answer):
    draft = asked(pt.CONFIRM_CORTE)
    assert natural.complete(draft, answer, NOW)["when"] == "2026-10-19 13:00", answer


def test_a_yes_is_not_a_yes_when_something_else_is_in_the_reply():
    assert not natural.affirm("yes write the launch post") and not natural.affirm("thanks") and not natural.affirm("")
    assert natural.complete(confirm_draft(), "yes, and write the launch post for me", NOW) is None, "a longer line is a new one"


def test_another_time_asks_for_when_and_keeps_the_words_and_the_answer_makes_the_reminder():
    again = natural.complete(confirm_draft(), "another time", NOW)["ask"]
    assert again["need"] == "again" and again["text"] == "call the dentist"
    assert natural.complete(again, "friday at 2pm", NOW)["when"] == "2026-10-23 14:00"
    day = natural.complete(again, "friday", NOW)["ask"]
    assert day["need"] == "time" and day["day"]["date"] == "2026-10-23" and day["text"] == "call the dentist"
    assert natural.complete(day, "10am", NOW)["when"] == "2026-10-23 10:00"
    assert natural.complete(again, "no", NOW) == {"cancel": True}
    pt_again = natural.complete(asked(pt.CONFIRM_CORTE), "outra hora", NOW)["ask"]
    assert pt_again["need"] == "again" and pt_again["text"] == "corte de cabelo"


def test_an_answer_that_fits_the_question_completes_it():
    complete = natural.complete
    time = asked("remind me tomorrow to call the dentist")
    assert time["need"] == "time"
    nine = complete(time, "9", NOW)["ask"]
    assert nine["need"] == "reading" and [r["when"] for r in nine["readings"]] == ["2026-10-19 09:00", "2026-10-19 21:00"], "a bare 9 to 'at what time?' is asked: 09:00 or 21:00"
    assert complete(time, "13.30", NOW)["when"] == "2026-10-19 13:30", "a dotted hour answers 'at what time?'"
    assert complete(confirm_draft(), "22/10", NOW)["when"] == "2026-10-22 13:00", "a day answers a confirmation: it replaces the day and keeps the hour"
    assert complete(confirm_draft(), "22/10/2026", NOW)["when"] == "2026-10-22 13:00"
    kind = asked("violin class tomorrow at 1pm", "bare")
    assert kind["need"] == "kind" and complete(kind, "yes", NOW)["text"] == "violin class", "a yes to 'a reminder or an event' is the reminder"
    two = asked("remind me at 9 to stretch")
    again = complete(two, "yes", NOW)["ask"]
    assert again["need"] == "reading" and again["retries"] == 1, "a yes to two readings asks which, once"
    assert complete(again, "yes", NOW) is None, "and the second time the line is a new one"
    assert complete(again, "9", NOW)["when"] == "2026-10-19 09:00"


def test_a_short_reply_that_does_not_fit_is_asked_once_and_a_longer_or_other_line_is_a_new_one():
    draft = asked("remind me tomorrow at 9am")
    assert draft["need"] == "text"
    again = natural.complete(draft, "thanks", NOW)["ask"]
    assert again["retries"] == 1 and again["need"] == "text"
    assert natural.complete(again, "thanks", NOW) is None
    for line in ("write the launch post for the shop", "what is the weather like today", "remind me tomorrow at 9am to call Ana", "cancel reminder 3", "undo"):
        assert natural.complete(confirm_draft(), line, NOW) is None, line
    for line in ("remind me tomorrow at 10am to call Ana", "cancel reminder 3", "me lembra amanhã às 9h de ligar"):      # validate: allow english-only -- a Portuguese line, the case of the tests
        assert natural.complete(asked("remind me at 9 to stretch"), line, NOW) is None, "a line that starts a request of its own is never the answer"


def test_no_gives_a_question_up_whatever_it_asked():
    for line in ("remind me tomorrow at 9am", "remind me at 9 to stretch", "remind me tomorow at 1pm to call", "remind me tomorrow to call", "remind me next week at 10 to pay"):
        assert natural.complete(asked(line), "no", NOW) == {"cancel": True}, line


def test_a_day_answer_to_a_time_question_replaces_the_day_and_only_the_hour_is_still_asked():
    draft = asked("remind me tomorrow to call the dentist")
    assert draft["day"]["date"] == "2026-10-19"
    friday = natural.complete(draft, "friday", NOW)["ask"]
    assert friday["need"] == "time" and friday["day"]["date"] == "2026-10-23" and friday["text"] == "call the dentist"
    assert natural.complete(friday, "10am", NOW)["when"] == "2026-10-23 10:00", "one day, not two readings"


# --- Q3: a week with no day ------------------------------------------------------------------------------------------------------------------------


def test_a_week_with_no_day_asks_which_day_of_it_and_never_offers_tomorrow():
    for line in ("remind me next week at 10 to pay rent", pt.LINE_WEEK, pt.LINE_WEEK_NO_TIME, "remind me next week to pay rent"):
        ask = asked(line)
        assert ask["need"] == "weekday" and ask["readings"] == [] and "week" not in ask["text"] and "semana" not in ask["text"], line
    ask = asked("remind me next week at 10am to pay rent")
    assert ask["text"] == "pay rent"
    assert natural.complete(ask, "tuesday", NOW)["when"] == "2026-10-20 10:00", "the Tuesday of the week that starts tomorrow"
    assert natural.complete(ask, "friday", NOW)["when"] == "2026-10-23 10:00"
    assert natural.complete(ask, "friday at 3pm", NOW)["when"] == "2026-10-23 15:00", "the hour of the answer replaces the one of the line"
    assert natural.complete(ask, "yes", NOW)["ask"]["retries"] == 1
    assert natural.complete(ask, "no", NOW) == {"cancel": True}
    no_time = natural.complete(asked("remind me next week to pay rent"), "wednesday", NOW)["ask"]
    assert no_time["need"] == "time" and no_time["day"]["date"] == "2026-10-21"
    assert natural.complete(asked(pt.LINE_WEEK), "terça", NOW)["when"] == "2026-10-20 10:00"      # validate: allow english-only -- a Portuguese answer, the case of the tests
    assert natural.complete(ask, "the 27th", NOW)["when"] == "2026-10-27 10:00", "a date is a date"
    named = natural.understand("remind me next week friday at 10am to pay rent", NOW)
    assert named["ask"]["need"] == "confirm", "a week and a day: the day is read and confirmed, nothing is asked again"


# --- Q1: a forget by number --------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line,expected", pt.FORGET_FORMS + [
    ("forget reminder 3", {"id": 3}), ("cancel reminder #3", {"id": 3}), ("cancel reminder number 3", {"id": 3}),
    ("cancel the reminder of 3", {"id": 3, "confirm": True}), ("cancel reminders 1 and 2", {"id": None, "ids": [1, 2], "confirm": True}),
    ("cancel the reminder at 9", {"id": None, "at": "at 9", "confirm": True})])
def test_a_number_is_an_explicit_id_only_in_the_forms_that_say_so_and_otherwise_it_is_shown_and_confirmed(line, expected):
    got = natural.candidate(line)
    assert got["op"] == "reminder-forget" and {key: got[key] for key in expected} == expected, line
    assert "words" not in got and "many" not in got


def test_a_forget_with_words_is_still_words_and_a_forget_with_too_many_numbers_is_asked():
    assert natural.candidate("cancel the reminder about the florist")["words"] == ["florist"]
    assert natural.candidate("cancel reminders 1 2 3 4 5 6")["many"] is True


# --- the undo is the bare word -------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["undo", "undo that", "undo the reminder", "undo it please", "bring it back", pt.LINE_UNDO, "desfaz o lembrete", "desfaz por favor"])
def test_the_undo_is_the_bare_word_optionally_with_the_reminder(line):
    assert natural.candidate(line) == {"op": "reminder-restore", "how": "trigger"}, line


@pytest.mark.parametrize("line", ["undo the deploy", "undo that commit", "undo the last change", "undo?", "bring it back to the shop", *pt.NOT_UNDO])
def test_anything_else_with_the_word_undo_goes_on(line):
    assert natural.candidate(line) is None or natural.candidate(line)["op"] != "reminder-restore", line


# --- Q2: the word reminder wins over a scheduling verb ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", [pt.LINE_MARCA_LEMBRETE, pt.LINE_AGENDE_LEMBRETE, "schedule a reminder tomorrow at 9am to pay the invoice", "book a reminder tomorrow at 9am to pay the invoice"])
def test_a_scheduling_verb_with_the_word_reminder_makes_a_reminder(line):
    assert natural.candidate(line) == {"op": "remind", "how": "trigger"}
    got = natural.understand(line, NOW)
    assert got["when"] == "2026-10-19 09:00" and got["text"] in ("pagar o boleto", "pay the invoice"), "the verb and the noun are not part of the words"


def test_a_scheduling_verb_without_the_word_reminder_is_unchanged():
    assert natural.candidate("schedule the dentist tomorrow at 9am") == {"op": "calendar-event-create", "how": "ask"}
    assert natural.candidate("mark the rent as paid") is None


# --- M3, MINOR 1: misspellings are data, a typo is never a name and never drops a word --------------------------------------------------------------------


@pytest.mark.parametrize("word", ["tommorow", "tmrw", "tmr", "2morrow", "tomorrow"])
def test_the_common_misspellings_of_tomorrow_are_entries_of_the_table(word):
    assert outcome(f"remind me {word} at 9am to call Ana") == ("when", "2026-10-19 09:00")
    assert not nt.doubt(f"remind me {word} at 9am to call Ana")


def test_a_hje_is_today():
    assert outcome("me lembra hje às 17h de ligar") == ("when", "2026-10-18 17:00")      # validate: allow english-only -- a Portuguese line, the case of the tests


def test_a_capitalised_word_in_the_middle_of_a_line_is_never_a_typo_of_a_day():
    assert nt.doubts("remind me tomorrow at 9am to call Mondey")[0] is False
    assert outcome("remind me tomorrow at 9am to call Mondey") == ("when", "2026-10-19 09:00")
    assert nt.doubts("remind me tomorrow at 9am to call mondey")[0] is True


def test_a_typo_that_is_one_letter_from_two_days_stays_in_the_words_and_the_reading_is_confirmed():
    ask = asked(pt.LINE_JUJHO)
    assert ask["need"] == "confirm" and "jujho" in ask["text"] and ask["readings"][0]["when"] == "2026-10-19 09:00"


# --- a part of the day beside an hour -------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line,expected", pt.PART_LINES + [
    ("remind me tonight at 9 to call mom", ("when", "21:00")), ("remind me tomorrow in the morning at 9 to run", ("when", "2026-10-19 09:00")),
    ("remind me tomorrow in the afternoon at 3 to run", ("when", "2026-10-19 15:00")), ("remind me tomorrow in the morning at 9pm to run", ("confirm", "2026-10-19 21:00"))])
def test_a_part_of_the_day_says_which_of_the_two_hours_is_meant_and_one_that_contradicts_is_confirmed(line, expected):
    assert outcome(line) == expected, line


# --- the operations ---------------------------------------------------------------------------------------------------------------------------------------


def test_the_undo_brings_back_the_most_recent_cancelled_reminder_that_is_not_already_back(world):  # noqa: F811
    for hour in (1, 2):
        ops.remind(world.path, channel="messaging", sender=SENDER, said=f"remind me tomorrow at {hour} pm to call number {hour}")
    ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER)
    ops.reminder_forget(world.path, 2, channel="messaging", sender=SENDER)
    first = ops.reminder_restore(world.path, channel="messaging", sender=SENDER)
    second = ops.reminder_restore(world.path, channel="messaging", sender=SENDER)
    assert (first["restored"], second["restored"]) == (2, 1), "the last one cancelled first, then the one before it: each has its own ten minutes"
    with pytest.raises(ops.OpsError) as e:
        ops.reminder_restore(world.path, channel="messaging", sender=SENDER)
    assert str(e.value) == "Reminder 2 is already back."
    assert sorted(r["text"] for r in world.rows("open")) == ["call number 1", "call number 2"]


def test_a_preview_of_a_forget_shows_the_reminder_and_cancels_nothing(world):  # noqa: F811
    ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me tomorrow at 1 pm to call the florist")
    shown = ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER, preview=True)
    assert shown["preview"]["id"] == 1 and shown["preview"]["text"] == "call the florist" and shown["human"]["time"] == "13:00"
    assert [r["status"] for r in world.rows()] == ["open"]
    with pytest.raises(ops.OpsError):
        ops.reminder_forget(world.path, 1, channel="messaging", sender=f"telegram:{OTHER}", preview=True)
    ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER)
    with pytest.raises(ops.OpsError):
        ops.reminder_forget(world.path, 1, channel="messaging", sender=SENDER, preview=True)


def test_a_forget_by_the_hour_matches_the_moment_of_the_senders_own_and_is_only_previewed(world):  # noqa: F811
    ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me tomorrow at 9am to call the florist")
    ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me tomorrow at 3 pm to water the plants")
    ops.remind(world.path, channel="messaging", sender=f"telegram:{OTHER}", said="remind me tomorrow at 9am to call the bank")
    shown = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, at="at 9")
    assert shown["preview"]["id"] == 1 and [r["status"] for r in world.rows()] == ["open", "open", "open"], "an hour is not a name: shown, not cancelled"
    assert ops.reminder_forget(world.path, channel="messaging", sender=SENDER, at="at 4pm") == {"none": True}
    ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me tomorrow at 9am to call the dentist")
    assert [r["id"] for r in ops.reminder_forget(world.path, channel="messaging", sender=SENDER, at="at 9")["choose"]] == [1, 4]
    only = ops.reminder_forget(world.path, channel="messaging", sender=SENDER, at="at 9", matching=["dentist"])
    assert only["preview"]["id"] == 4, "the hour and the words together"


def test_a_yes_to_a_forget_question_is_the_ids_for_the_bridge_to_cancel_one_by_one(world):  # noqa: F811
    draft = {**natural._draft("forget", "trigger", "", ""), "ids": [1, 2], "sentence": "x"}
    assert natural.complete(draft, "yes please", NOW) == {"forget": [1, 2]}
    assert natural.complete(draft, "no", NOW) == {"cancel": True}
    assert natural.complete(draft, "hmm", NOW)["ask"]["retries"] == 1
    done = ops.remind(world.path, channel="messaging", sender=SENDER, said="yes", draft=draft)
    assert done == {"forget": [1, 2]} and world.rows() == [], "the operation passes the ids on and cancels nothing itself"


# --- the documents ------------------------------------------------------------------------------------------------------------------------------------


def test_no_module_row_of_the_reminders_is_listed_twice_in_the_documents():
    root = st.RUNTIME.parent
    for path in ("contracts/runtime.md", "runtime/README.md"):
        seen = {}
        for line in (root / path).read_text(encoding="utf-8").splitlines():
            if line.startswith("| `") and any(word in line.split("|")[1] for word in ("remind", "natural")):
                name = line.split("|")[1].strip()
                assert name not in seen, f"{path} lists {name} twice"
                seen[name] = line
        assert seen

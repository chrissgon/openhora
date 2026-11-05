"""Natural requests, tier 1, round 5 (package NR-1): the maintainer's decision that a reminder asked in FREE TEXT is never made at once. `understand` never returns a reminder
to make: it returns the reading to be shown (the confirmation, or the kind question that holds the reading) and the reminder is made only from a draft the person confirmed
(a yes, the pick of one of the readings that were shown, or the answer to the kind question). A moment that cannot be made (one that has passed, a date the calendar lacks, a
credential in the words) is refused before the reading is shown. Also the readings that were being shown wrong: "9:00h", ranges, "30 minutes before ... 3pm", "9h de 12/12",
impossible dates, a day word that is the topic, "dom", and the plural of a weekday. The corpora are in test_natural_corpus.py. Offline, no model, no network; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_review5.py
"""
from __future__ import annotations

import datetime

import pytest

import natural_cases_pt_br as pt
import phrase_kit as pk
import standin_tree as st
from closed_heads import trigger_reading  # noqa: F401  (S41-11 PR 2b: the reminder engine's old entry, the way `trigger`, for the tests that read a line that starts with a remind word)
from natural_kit import made
from test_attachments import case  # noqa: F401  (the project the attachment tests use, which the world fixture builds on)
from test_reminders import BRT, SENDER, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

pytestmark = pytest.mark.usefixtures("trigger_reading")
natural = st.load("natural")
ops = st.load("ops")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=BRT)       # Sunday

FREE_TEXT = ["remind me tomorrow at 9am to water the orchids", pt.LINE_ORCHID, "violin class tomorrow at 1pm", "note: water the orchids tomorrow 9am", "remind me at 9 to stretch",
             "remind me next week on friday at 3pm to water the orchids", "tomorrow 9am water the orchids", "remind me in 2 hours to stretch", "remind me at 9:30 to stretch"]


@pytest.mark.parametrize("how", ["trigger", "bare", "note", "command"])
@pytest.mark.parametrize("line", FREE_TEXT)
def test_understand_never_returns_a_reminder_to_make_for_a_line_in_free_text(line, how):
    got = natural.understand(line, NOW, how)
    assert "ask" in got and "when" not in got, (line, how)


def test_the_reminder_is_made_only_from_a_confirmed_draft():
    ask = natural.understand(pt.LINE_ORCHID, NOW)["ask"]
    assert ask["need"] == "confirm" and not ask.get("confirmed")
    done = natural.complete(ask, "yes", NOW)
    assert done["when"] == "2026-10-19 09:00" and done["text"] == "regar as orquídeas"      # validate: allow english-only -- the words of the line
    assert "when" not in natural.complete(ask, "14h", NOW), "an hour replaces the reading: the new one is shown first"
    assert natural.complete(ask, "14h", NOW)["ask"]["readings"][0]["when"] == "2026-10-19 14:00"
    assert natural.complete(natural.complete(ask, "14h", NOW)["ask"], "yes", NOW)["when"] == "2026-10-19 14:00"


def test_the_pick_of_a_reading_is_not_a_yes_it_shows_the_whole_reading_and_the_yes_makes_it():
    two = natural.understand("remind me at 9 to stretch", NOW)["ask"]
    assert two["need"] == "reading"
    for answer, when in (("9", "2026-10-19 09:00"), ("21", "2026-10-18 21:00"), ("friday at 8am", "2026-10-23 08:00")):
        shown = natural.complete(two, answer, NOW)
        assert "when" not in shown and shown["ask"]["need"] == "confirm" and shown["ask"]["text"] == "stretch", answer
        assert shown["ask"]["readings"][0]["date"] + " " + shown["ask"]["readings"][0]["time"] == when
        assert natural.complete(shown["ask"], "yes", NOW)["when"] == when
    bare = natural.understand("stretch at 9", NOW, "bare")["ask"]
    assert bare["need"] == "reading"
    kind = natural.complete(bare, "21", NOW)["ask"]
    assert kind["need"] == "kind" and kind["text"] == "stretch", "a bare line: the reminder-or-event question shows the reading, and its answer makes it"
    assert natural.complete(kind, "reminder", NOW)["when"] == "2026-10-18 21:00"


def test_the_kind_question_shows_the_reading_and_its_answer_makes_it():
    kind = natural.understand("violin class tomorrow at 1pm", NOW, "bare")["ask"]
    assert kind["need"] == "kind" and kind["readings"][0]["when"] == "2026-10-19 13:00"
    assert natural.complete(kind, "reminder", NOW)["when"] == "2026-10-19 13:00"
    changed = natural.complete(kind, "friday", NOW)["ask"]
    assert changed["need"] == "kind" and changed["readings"][0]["when"] == "2026-10-23 13:00", "a day instead of the kind changes the reading shown"


# --- the operation refuses before it shows ---------------------------------------------------------------------------------------------------------------


def test_a_moment_that_cannot_be_made_is_refused_before_the_reading_is_shown(world):  # noqa: F811
    for said in ("remind me today at 1pm to stretch", "remind me 30/02 at 10:00 to stretch", "remind me in 400 days to stretch"):
        with pytest.raises(ops.OpsError):
            ops.remind(world.path, channel="messaging", sender=SENDER, said=said)
    key = "sk-" + "ant-" + "api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    with pytest.raises(ops.OpsError) as e:
        ops.remind(world.path, channel="messaging", sender=SENDER, said=f"remind me tomorrow at 9am to use {key}")
    assert pk.said(str(e.value), "RM_CREDENTIAL", None) and key not in str(e.value), "a credential is not echoed back in a question"
    assert world.rows() == []


@pytest.mark.parametrize("line", pt.IMPOSSIBLE_DATES)
def test_a_date_that_is_not_one_is_refused_with_the_calendars_sentence(world, line):  # noqa: F811
    with pytest.raises(ops.OpsError) as e:
        ops.remind(world.path, channel="messaging", sender=SENDER, said=line)
    assert pk.said(str(e.value), "RM_NO_SUCH_DATE", None), line


# --- the readings that were shown wrong --------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line,when", pt.SHOWN_RIGHT)
def test_these_readings_are_the_ones_shown(line, when):
    ask = natural.understand(line, NOW)["ask"]
    assert ask["need"] in ("confirm", "text") and ask["readings"][0]["when"] == when, line


def test_a_range_is_asked_with_both_hours():
    ask = natural.understand(pt.LINE_RANGE, NOW)["ask"]
    assert ask["need"] == "reading" and sorted(r["time"] for r in ask["readings"]) == ["09:00", "10:00"]
    picked = natural.complete(ask, "10h", NOW)["ask"]
    assert picked["need"] == "confirm" and natural.complete(picked, "yes", NOW)["when"] == "2026-10-19 10:00"


@pytest.mark.parametrize("line", pt.TOPIC_LINES + ["remind me at 9am that friday's meeting was cancelled", "remind me at 9am about the meeting of friday"])
def test_a_day_word_that_is_the_topic_is_not_taken_as_the_day_and_both_readings_are_offered(line):
    ask = natural.understand(line, NOW)["ask"]
    assert ask["need"] == "reading" and len(ask["readings"]) == 2, line
    assert {"sexta", "sábado", "friday"} & set(ask["text"].lower().replace("'", " ").split()), "the day word stays in the reminder's words"      # validate: allow english-only -- the words of the lines


def test_a_day_word_that_is_the_day_is_still_the_day():
    assert natural.understand("remind me friday at 9am to stretch", NOW)["ask"]["readings"][0]["when"] == "2026-10-23 09:00"
    assert natural.understand("remind me on friday at 9am to stretch", NOW)["ask"]["need"] == "confirm"


@pytest.mark.parametrize("line", pt.REPEAT_PLURAL + ["remind me on mondays at 9am to water the orchids", "remind me always at 9am to open the window"])
def test_the_plural_of_a_weekday_and_an_always_are_a_routines(line):
    assert natural.understand(line, NOW)["ask"]["need"] == "recurring", line


def test_a_plural_that_is_not_a_weekday_is_not_a_routine():
    assert natural.understand("remind me tomorrow at 9am to call the sunflowers", NOW)["ask"]["need"] == "confirm"


def test_sunday_week_convention_is_shown_never_silent():
    ask = natural.understand("remind me tuesday next week at 10am to pay", NOW)["ask"]
    assert ask["need"] == "confirm" and ask["readings"][0]["when"] == "2026-10-27 10:00", "said on a Sunday, next week begins after tomorrow's Monday"
    thursday = NOW + datetime.timedelta(days=4)
    ask = natural.understand("remind me tuesday next week at 10am to pay", thursday)["ask"]
    assert ask["readings"][0]["when"] == "2026-10-27 10:00"
    monday = NOW + datetime.timedelta(days=1)
    assert natural.understand("remind me tuesday next week at 10am to pay", monday)["ask"]["readings"][0]["when"] == "2026-10-27 10:00"

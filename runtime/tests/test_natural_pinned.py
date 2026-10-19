"""Natural requests (package NR-1): a reminder is made for the moment the person was SHOWN, not for the moment of the answer. The reading shown carries a day and an hour; a bare
`HH:MM` or an `in 30m` kept in the draft would be read again when the person answers, so "dentist at 10" shown as today 10:00 and answered at 10:01 would be made for
tomorrow. An absolute moment that went by before the answer is refused as past (never moved); a relative one ("in 30 minutes") is shown again with the new moment and the
yes is asked again. Both ways to a reminder are tested: the yes to the confirmation, and the answer to the kind question. Offline, no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_pinned.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st
from test_attachments import case  # noqa: F401  (the project the attachment tests use, which the world fixture builds on)
from test_reminders import BRT, SENDER, world  # noqa: F401  (the world fixture: a project with four listed senders and a clock)

natural = st.load("natural")
ops = st.load("ops")


def at(wall):
    return datetime.datetime.strptime(wall, "%Y-%m-%d %H:%M").replace(tzinfo=BRT)


# (the line, how it is said, the clock when asked, the answer, the clock when answered)
ABSOLUTE = [("plumber at 10am", "bare", "2026-10-19 09:55", "reminder", "2026-10-19 10:01"),
            ("plumber at 10am", "bare", "2026-10-19 09:55", "yes", "2026-10-19 10:01"),
            ("remind me at 10am to call the plumber", "trigger", "2026-10-19 09:55", "yes", "2026-10-19 10:01"),
            ("plumber 23:58", "bare", "2026-10-19 23:50", "reminder", "2026-10-19 23:59")]
RELATIVE = [("remind me in 30 minutes to call the plumber", "trigger", "2026-10-19 09:55", "yes", "2026-10-19 10:04"),
            ("plumber in 30 minutes", "bare", "2026-10-19 09:55", "reminder", "2026-10-19 10:04")]


@pytest.mark.parametrize("line,how,asked,answer,answered", ABSOLUTE)
def test_a_time_shown_as_today_is_made_for_that_day_or_not_at_all(line, how, asked, answer, answered):
    shown = natural.understand(line, at(asked), how)["ask"]
    reading = shown["readings"][0]
    assert shown["need"] in ("confirm", "kind") and reading["date"] == asked[:10] and not reading["rolled"]
    done = natural.complete(shown, answer, at(answered))
    assert done["when"] == f"{reading['date']} {reading['time']}", "the day and the hour that were shown, never a bare HH:MM read again"
    assert done["reading"]["date"] == reading["date"]


@pytest.mark.parametrize("line,how,asked,answer,answered", ABSOLUTE)
def test_the_operation_refuses_an_answer_after_the_moment_shown_and_makes_nothing(world, line, how, asked, answer, answered):  # noqa: F811
    world.clock.set(asked)
    first = ops.remind(world.path, channel="messaging", sender=SENDER, said=line, how=how)["ask"]
    world.clock.set(answered)
    with pytest.raises(ops.OpsError) as e:
        ops.remind(world.path, channel="messaging", sender=SENDER, said=answer, how=how, draft=first)
    assert "passed" in str(e.value) and world.rows() == []


@pytest.mark.parametrize("answer", ["yes", "reminder"])
def test_an_answer_before_the_moment_shown_is_made_for_that_moment(world, answer):  # noqa: F811
    world.clock.set("2026-10-19 09:55")
    line = "plumber at 10am"
    first = ops.remind(world.path, channel="messaging", sender=SENDER, said=line, how="bare")["ask"]
    world.clock.set("2026-10-19 09:58")
    done = ops.remind(world.path, channel="messaging", sender=SENDER, said=answer, how="bare", draft=first)
    assert done["human"]["date"] == "2026-10-19" and done["human"]["time"] == "10:00"


@pytest.mark.parametrize("line,how,asked,answer,answered", RELATIVE)
def test_a_relative_time_is_pinned_to_the_moment_shown(line, how, asked, answer, answered):
    shown = natural.understand(line, at(asked), how)["ask"]
    reading = shown["readings"][0]
    assert reading["time"] == "10:25" and reading["relative"] == "in 30m"
    done = natural.complete(shown, answer, at("2026-10-19 09:58"))
    assert done["when"] == "2026-10-19 10:25", "the moment shown, not thirty minutes after the answer"
    assert done["reading"]["time"] == "10:25"


@pytest.mark.parametrize("line,how,asked,answer,answered", RELATIVE)
def test_a_relative_time_whose_moment_went_by_is_shown_again_with_the_new_moment(line, how, asked, answer, answered):
    shown = natural.understand(line, at(asked), how)["ask"]
    # the person answers after the moment shown (10:25): nothing is made; the new moment (30 minutes from the answer) is shown and the yes is asked again
    again = natural.complete(shown, answer, at("2026-10-19 10:40"))
    assert "when" not in again and again["ask"]["need"] in ("confirm", "kind")
    assert again["ask"]["readings"][0]["time"] == "11:10" and not again["ask"].get("confirmed")
    done = natural.complete(again["ask"], "yes", at("2026-10-19 10:41"))
    assert done["when"] == "2026-10-19 11:10" and done["text"] == shown["text"]


def test_the_operation_shows_the_new_moment_of_a_relative_time_and_makes_the_reminder_on_the_second_yes(world):  # noqa: F811
    world.clock.set("2026-10-19 09:55")
    first = ops.remind(world.path, channel="messaging", sender=SENDER, said="remind me in 30 minutes to call the plumber")["ask"]
    world.clock.set("2026-10-19 10:40")
    second = ops.remind(world.path, channel="messaging", sender=SENDER, said="yes", draft=first)
    assert second["ask"]["readings"][0]["time"] == "11:10" and world.rows() == []
    done = ops.remind(world.path, channel="messaging", sender=SENDER, said="yes", draft=second["ask"])
    assert done["human"]["time"] == "11:10" and len(world.rows()) == 1

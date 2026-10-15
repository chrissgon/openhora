"""Tests of the pure part of the routines (runtime/routines.py, package P6b): the schedule, the slots that are due, the catch-up rule and
the content an approval covers. No store, no clock but the ones the tests pass. Offline; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_routines.py
"""
from __future__ import annotations

import datetime
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
routines = importlib.import_module("routines")

D = datetime.datetime
DAILY = {"every": "day", "at": "08:00"}


@pytest.mark.parametrize("raw", [
    {"every": "day", "at": "08:00"}, {"every": "week", "weekday": 1, "at": "23:59"}, {"every": "minutes", "minutes": 15}, {"every": "minutes", "minutes": 720}])
def test_a_schedule_of_the_three_forms_is_accepted_in_its_canonical_form(raw):
    assert routines.check_schedule(raw) == raw


@pytest.mark.parametrize("raw, word", [
    ("daily", "says every"), ({"every": "hour"}, "says every"), ({"every": "day"}, "exactly at"), ({"every": "day", "at": "8:00"}, "HH:MM"),
    ({"every": "day", "at": "24:00"}, "HH:MM"), ({"every": "day", "at": "08:00", "weekday": 2}, "exactly at"),
    ({"every": "week", "at": "08:00"}, "exactly"), ({"every": "week", "weekday": 8, "at": "08:00"}, "weekday"),
    ({"every": "week", "weekday": True, "at": "08:00"}, "weekday"), ({"every": "minutes", "minutes": 14}, "from 15 to 720"),
    ({"every": "minutes", "minutes": 25}, "divides 1,440"), ({"every": "minutes", "minutes": 1440}, "from 15 to 720"),
    ({"every": "minutes", "minutes": "30"}, "from 15 to 720")])
def test_a_schedule_that_is_not_one_is_refused_with_the_reason(raw, word):
    with pytest.raises(ValueError, match=word):
        routines.check_schedule(raw)


def test_the_newest_slot_of_each_form_at_a_moment_and_the_one_before_it():
    assert routines.slot_name(routines.newest_slot(DAILY, D(2026, 10, 15, 9, 0))) == "2026-10-15T08:00"
    assert routines.slot_name(routines.newest_slot(DAILY, D(2026, 10, 15, 7, 59))) == "2026-10-14T08:00"
    assert routines.slot_name(routines.newest_slot(DAILY, D(2026, 10, 15, 8, 0))) == "2026-10-15T08:00"
    week = {"every": "week", "weekday": 1, "at": "08:00"}        # 2026-10-15 is a Thursday, 2026-10-12 a Monday
    assert routines.slot_name(routines.newest_slot(week, D(2026, 10, 15, 9, 0))) == "2026-10-12T08:00"
    assert routines.slot_name(routines.newest_slot(week, D(2026, 10, 12, 7, 0))) == "2026-10-05T08:00"
    assert routines.slot_name(routines.previous_slot(week, D(2026, 10, 12, 8, 0))) == "2026-10-05T08:00"
    every = {"every": "minutes", "minutes": 90}
    assert routines.slot_name(routines.newest_slot(every, D(2026, 10, 15, 4, 29))) == "2026-10-15T03:00"
    assert routines.slot_name(routines.newest_slot(every, D(2026, 10, 15, 4, 30))) == "2026-10-15T04:30"
    assert routines.slot_name(routines.previous_slot(every, D(2026, 10, 15, 0, 0))) == "2026-10-14T22:30"


def due(last, since, now, window=None, schedule=DAILY):
    return routines.due(schedule, last, since, now, window)


def test_a_slot_that_has_come_is_fired_once_and_nothing_is_due_before_the_next():
    got = due(None, D(2026, 10, 14, 12, 0), D(2026, 10, 15, 8, 1))
    assert got["fire"] == "2026-10-15T08:00" and got["skipped"] == [] and got["window"] == 86400
    assert due("2026-10-15T08:00", D(2026, 10, 14, 12, 0), D(2026, 10, 15, 23, 59)) == {"fire": None, "skipped": [], "skipped_count": 0, "window": 86400}
    assert due(None, D(2026, 10, 15, 8, 30), D(2026, 10, 15, 9, 0))["fire"] is None, "a slot before the approval is not owed"


def test_after_an_outage_the_newest_missed_slot_is_run_once_inside_the_window_and_the_older_ones_are_skipped_and_noted():
    got = due("2026-10-10T08:00", None, D(2026, 10, 15, 8, 30))
    assert got["fire"] == "2026-10-15T08:00"                          # one run
    assert got["skipped"] == ["2026-10-11T08:00", "2026-10-12T08:00", "2026-10-13T08:00", "2026-10-14T08:00"] and got["skipped_count"] == 4


def test_after_an_outage_longer_than_the_window_every_missed_slot_is_skipped_and_none_runs():
    got = due("2026-10-10T08:00", None, D(2026, 10, 15, 11, 0), window=3600)         # the newest slot is three hours old
    assert got["fire"] is None and got["skipped_count"] == 5 and got["skipped"][-1] == "2026-10-15T08:00"
    again = due("2026-10-15T08:00", None, D(2026, 10, 15, 11, 0), window=3600)
    assert again["fire"] is None and again["skipped"] == [], "the newest skipped slot has its row: the next tick has nothing to do"


def test_never_one_run_per_missed_slot_and_only_the_last_skipped_get_rows():
    every = {"every": "minutes", "minutes": 15}
    got = due("2026-10-10T00:00", None, D(2026, 10, 15, 0, 7), schedule=every)       # five days silent: 480 slots
    assert got["fire"] == "2026-10-15T00:00" and got["skipped_count"] == 479
    assert len(got["skipped"]) == routines.KEEP_SKIPPED and got["skipped"] == sorted(got["skipped"])


def test_what_passed_while_the_routine_was_paused_or_a_draft_is_not_owed_whatever_the_last_slot_was():
    # fired on the 10th, paused, the 11th to the 13th passed, resumed on the 14th at noon: the 14th at 08:00 is before the resume
    assert due("2026-10-10T08:00", D(2026, 10, 14, 12, 0), D(2026, 10, 14, 13, 0)) == {"fire": None, "skipped": [], "skipped_count": 0, "window": 86400}
    got = due("2026-10-10T08:00", D(2026, 10, 14, 12, 0), D(2026, 10, 15, 8, 5))
    assert got["fire"] == "2026-10-15T08:00" and got["skipped"] == [], "the next slot after the resume fires, and no slot of the pause is skipped or noted"
    assert due(None, D(2026, 10, 15, 9, 0), D(2026, 10, 15, 9, 30))["fire"] is None


def test_the_window_is_the_records_or_the_period():
    assert routines.window_of(DAILY, None) == 86400 and routines.window_of({"every": "week", "weekday": 1, "at": "08:00"}, None) == 604800
    assert routines.window_of({"every": "minutes", "minutes": 30}, None) == 1800 and routines.window_of(DAILY, 7200) == 7200
    assert routines.window_of(DAILY, 59) == 86400, "a window under a minute is no window"


def sample(**change):
    base = dict(schedule=DAILY, window_seconds=None, flow="survey", template_sha256="a" * 64, params={"topic": "dental"},
                skills={"biz-market-analysis": "1.2", "core-research": "1.1"}, image="sha256:" + "1" * 64, model="auto", consent=False,
                warning_sha256="w" * 64, providers=["openrouter", "anthropic"])
    base.update(change)
    return routines.content(**base)


def test_the_hash_covers_the_schedule_the_template_the_arguments_the_skill_versions_the_image_the_model_the_consent_and_the_providers():
    first = routines.sha256_of(sample())
    assert first == routines.sha256_of(sample(providers=["anthropic", "openrouter"])), "the set has no order"
    for name, change in {"schedule": dict(schedule={"every": "day", "at": "09:00"}), "window": dict(window_seconds=7200),
                         "template": dict(template_sha256="b" * 64), "arguments": dict(params={"topic": "vet"}),
                         "X.Y of a skill": dict(skills={"biz-market-analysis": "1.3", "core-research": "1.1"}),
                         "a skill added": dict(skills={"biz-market-analysis": "1.2", "core-research": "1.1", "x": "1.0"}),
                         "image": dict(image="sha256:" + "2" * 64), "a script": dict(scripts=[{"sha256": "c" * 64, "destinations": []}]),
                         "model": dict(model="fm"), "consent": dict(consent=True), "providers": dict(providers=["anthropic"]),
                         "the warning": dict(consent=True, warning_sha256="x" * 64)}.items():
        assert routines.sha256_of(sample(**change)) != first or name == "the warning", name
    assert routines.sha256_of(sample(consent=True)) != routines.sha256_of(sample(consent=True, warning_sha256="x" * 64))


def test_what_differs_is_named_for_the_sentence_of_the_stop():
    old = sample()
    new = sample(template_sha256="b" * 64, skills={"biz-market-analysis": "2.0", "core-research": "1.1"}, image="sha256:" + "2" * 64, model="fm")
    assert routines.differences(old, new) == ["the workflow's template", "the version of biz-market-analysis (1.2 to 2.0)", "the eval image", "the model"]
    assert routines.differences({}, new) == ["the approved content is not on record"]
    assert routines.differences(old, old) == ["the content (its version)"]

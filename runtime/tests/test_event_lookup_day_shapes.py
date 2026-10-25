"""The day a line names, for every shape the time engine can hand to `event_lookup._day_named` (BL5C, root cause C4: `KeyError: 'spec'` on a slash date with a time range).

A `slash` hit has no `spec`, and a time range makes the engine answer with several readings (`ask`) instead of one: the old code indexed `named[0]["spec"]` for any single day hit and
the whole turn ended in an exception, with no reply to the person. Held here: every shape the engine can produce (a real line where it produces it, a stand-in `find` or `parse` where
it does not) answers one of the four tuples and never raises; the readings of a range on ONE day name that day, readings on several days stay unread (a question, never a guess, L61);
every caller of the function survives the line of the live trace (`open_event`, `ops_items._range_args`, `plan_confirm`, `ops_interpret._day_read`, the day read of a card change).
Vacuity: the expression of 81c1274 is restored in a copy of the function and raises on the same line. Offline, no model; fictional names; Python 3.9.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup_day_shapes.py
"""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

import standin_tree as st
from test_event_lookup import ALLOWED, CANCEL, ZONE, build, card, carry, card_problems, ops_core, ops_interpret  # noqa: F401  (the calendar world and the real seam)
from test_event_lookup import EVENTS, world  # noqa: F401

event_lookup = st.load("event_lookup")
natural_time = st.load("natural_time")
ops_items = st.load("ops_items")
plan_confirm = st.load("plan_confirm")
ops_natural = st.load("ops_natural")

NOW = datetime.datetime(2026, 10, 25, 0, 47, tzinfo=ZoneInfo(ZONE))          # Sunday 25/10, as on the live trace
TITLE = "corte de cabelo para amanhas"          # a fictional title that holds a day-like word
CRASH_LINE = f"Remova o evento da agenda: 1. dom 25/10 13:00–14:00 · {TITLE}"          # validate: allow english-only -- the Portuguese line under test
RANGE_LINE = "dom 25/10 13:00–14:00"
D25 = datetime.date(2026, 10, 25)
KINDS = {"none", "day", "weekday", "unread"}


class Engine:
    """The real time engine with `find`, `parse` or `doubt` replaced: the shapes the real engine does not produce on a line a test can write."""

    def __init__(self, find=None, parse=None, doubt=None):
        self._over = {"find": find, "parse": parse, "doubt": doubt}

    def __getattr__(self, name):
        over = self._over.get(name)
        return over if over is not None else getattr(natural_time, name)


def with_engine(monkeypatch, **over):
    monkeypatch.setattr(event_lookup, "nt", Engine(**over))


def answer(text, now=NOW):
    got = event_lookup._day_named(text, now)
    assert isinstance(got, tuple) and len(got) == 2 and got[0] in KINDS, got
    assert (got[1] is not None) == (got[0] in ("day", "weekday")), got
    return got


def old_day_named(text, now):
    """The body of `_day_named` at 81c1274, kept here as the oracle of the vacuity test."""
    nt, DAY_HITS = event_lookup.nt, event_lookup.DAY_HITS
    if nt.doubt(text):
        return "unread", None
    found = nt.find(text)
    named = [h for h in found["hits"] if h["kind"] in DAY_HITS]
    if not named:
        try:
            got = event_lookup._slash_day(text, now.date())
        except ValueError:
            return "unread", None
        return ("day", got) if got else ("none", None)
    got = nt.parse(text, now)
    if got is not None:
        shown = got.get("day") or got.get("reading")
        if shown and shown.get("date"):
            try:
                return "day", datetime.date.fromisoformat(shown["date"])
            except ValueError:
                pass
    if len(named) == 1 and named[0]["spec"].get("k") == "wd":
        return "weekday", named[0]["spec"]["i"]
    return "unread", None


# --- every shape of the engine's answer ------------------------------------------------------------------------------------------------------------------

def test_a_slash_date_with_a_time_range_names_that_day_and_never_raises():
    """The live crash: one `slash` hit, two clocks, parse answers `ask` with two readings on the same date."""
    found = natural_time.find(RANGE_LINE)
    assert [h["kind"] for h in found["hits"]] == ["slash", "clock", "clock"] and "spec" not in found["hits"][0]
    assert natural_time.parse(RANGE_LINE, NOW)["ask"], "the engine answers with several readings"
    assert answer(RANGE_LINE) == ("day", D25)
    assert answer(CRASH_LINE) == ("day", D25)
    assert answer("dia 25/10 13:00-14:00") == ("day", D25)
    assert answer("25/10 das 13h às 14h") == ("day", D25)


def test_vacuity_the_old_expression_raises_on_the_same_line_and_the_new_one_does_not():
    for text in (RANGE_LINE, CRASH_LINE, "dia 25/10 13:00-14:00"):
        with pytest.raises(KeyError):
            old_day_named(text, NOW)
        assert answer(text) == ("day", D25)


def test_readings_on_different_days_are_unread_never_a_guess():
    assert answer("quinta 10h e sexta 11h") == ("unread", None)
    assert answer("hoje 10h e amanhã 11h") == ("unread", None)  # validate: allow english-only -- the Portuguese line under test
    assert answer("25/10 13:00 e 26/10 14:00") == ("unread", None)


def test_a_time_range_on_a_day_word_names_that_day():
    assert answer("amanhã 13:00-14:00") == ("day", datetime.date(2026, 10, 26))  # validate: allow english-only -- the Portuguese line under test
    assert answer("23:00–01:00 amanhã") == ("day", datetime.date(2026, 10, 26))  # validate: allow english-only -- the Portuguese line under test


def test_a_doubt_is_unread():
    assert answer("Remova o corte de cabelo na terça passada") == ("unread", None)          # validate: allow english-only -- the Portuguese line under test


def test_a_line_with_no_day_hit_and_no_slash_names_none():
    assert answer("corte de cabelo") == ("none", None)
    assert answer("as 15h") == ("none", None)


def test_no_hit_and_a_slash_date_is_that_day_and_an_impossible_one_is_unread(monkeypatch):
    with_engine(monkeypatch, find=lambda text, languages=None: {"hits": []}, doubt=lambda text: False)
    assert answer("25/10") == ("day", D25)
    assert answer("31/02") == ("unread", None)
    assert answer("25/10/202") == ("unread", None)          # a year of three digits is no year


def test_parse_day_and_parse_reading_name_their_date():
    assert answer("dia 25/10") == ("day", D25)
    assert answer("dia 25/10 13:00") == ("day", D25)
    assert answer("amanhã") == ("day", datetime.date(2026, 10, 26))  # validate: allow english-only -- the Portuguese line under test


def test_one_weekday_hit_with_no_parse_is_a_weekday(monkeypatch):
    with_engine(monkeypatch, parse=lambda text, now, languages=None: None)
    assert answer("sexta") == ("weekday", 4)


def test_one_date_hit_of_another_kind_with_no_parse_is_unread(monkeypatch):
    with_engine(monkeypatch, parse=lambda text, now, languages=None: None)
    assert answer("amanhã") == ("unread", None)          # a relative day: spec k "rel"  # validate: allow english-only -- the Portuguese line under test
    assert answer("dia 32") == ("unread", None)          # a day kept as written for `resolve` to refuse: spec k "bad"
    assert answer("dia 25") == ("unread", None)


def test_one_slash_hit_with_no_parse_is_that_day_and_an_impossible_slash_is_unread(monkeypatch):
    with_engine(monkeypatch, parse=lambda text, now, languages=None: None)
    assert answer("25/10") == ("day", D25)
    assert answer("31/02") == ("unread", None)


def test_two_day_hits_with_no_parse_are_unread(monkeypatch):
    with_engine(monkeypatch, parse=lambda text, now, languages=None: None)
    assert answer("amanhã sexta") == ("unread", None)  # validate: allow english-only -- the Portuguese line under test
    slash = {"kind": "slash", "a": 25, "b": 10, "y": None, "s": 0, "e": 5}
    with_engine(monkeypatch, find=lambda text, languages=None: {"hits": [slash, dict(slash, a=26, s=6, e=11)]}, parse=lambda text, now, languages=None: None, doubt=lambda text: False)
    assert answer("25/10 26/10") == ("unread", None)          # two slash hits: the slash fallback is not asked to choose between them
    with_engine(monkeypatch, find=lambda text, languages=None: {"hits": [slash, {"kind": "date", "spec": {"k": "wd", "i": 4}, "s": 6, "e": 11}]}, parse=lambda text, now, languages=None: None,
                doubt=lambda text: False)
    assert answer("25/10 sexta") == ("unread", None)


def test_a_bad_day_word_is_a_question():
    assert answer("dia 32") == ("unread", None)
    assert answer("dia 32 13:00-14:00") == ("unread", None)


@pytest.mark.parametrize("hit", [{"kind": "date"}, {"kind": "date", "spec": None}, {"kind": "date", "spec": {}}, {"kind": "date", "spec": {"k": "wd"}}, {"kind": "slash"},
                                 {"kind": "slash", "a": "x", "b": 1, "y": None}, {"kind": "date", "spec": {"k": "ymd"}}])
@pytest.mark.parametrize("parsed", [None, {}, {"ask": []}, {"ask": [{}]}, {"ask": [{"date": "not-a-date"}, {"date": "not-a-date"}]}, {"ask": "x"}, {"ask": [{"date": "2026-10-25"}, {"date": "2026-10-26"}]},
                                    {"missing": "time", "day": None}, {"missing": "time", "day": {"date": "2026-13-45"}}, {"when": "x", "reading": {"date": None}}, "text", 7])
def test_a_hit_that_lacks_a_key_and_an_answer_of_any_shape_never_raise(monkeypatch, hit, parsed):
    with_engine(monkeypatch, find=lambda text, languages=None: {"hits": [dict(hit, s=0, e=1)]}, parse=lambda text, now, languages=None: parsed, doubt=lambda text: False)
    answer("whatever 25/10 text")


def test_a_weekday_with_no_index_is_unread(monkeypatch):
    with_engine(monkeypatch, find=lambda text, languages=None: {"hits": [{"kind": "date", "spec": {"k": "wd"}, "s": 0, "e": 1}]}, parse=lambda text, now, languages=None: None, doubt=lambda text: False)
    assert answer("sexta") == ("unread", None)


# --- every caller survives the line of the live trace ----------------------------------------------------------------------------------------------------

def test_open_event_with_the_crash_line_opens_the_one_card_and_never_raises(world, monkeypatch):
    build(world, monkeypatch, events=[("25", "13:00", "14:00", TITLE, "evhair25")])
    reply, extras = carry(world, CRASH_LINE, CANCEL)
    item = card(world, extras)
    assert card_problems(item, "agenda#1", TITLE, "Sun 25/10/2026 13:00-14:00") == [], reply


def test_open_event_with_the_crash_line_lists_two_events_of_that_day(world, monkeypatch):
    build(world, monkeypatch, events=[("25", "13:00", "14:00", TITLE, "evhair25"), ("25", "15:00", "16:00", TITLE, "evhair25b")])
    reply, extras = carry(world, CRASH_LINE, CANCEL)
    assert "resend" not in extras and "1." in reply and "2." in reply, reply


def test_the_items_range_of_a_day_with_a_time_range_is_that_day():
    assert ops_items._range_args("mostra minha agenda de dia 25/10 13:00-14:00", NOW) == {"first": "2026-10-25", "last": "2026-10-25"}          # validate: allow english-only -- the Portuguese line under test
    assert ops_items._range_args(CRASH_LINE, NOW) == {"first": "2026-10-25", "last": "2026-10-25"}


def test_the_plan_sentence_of_an_items_line_with_a_time_range_renders_the_day(monkeypatch):
    monkeypatch.setattr(ops_natural, "_clock", lambda: NOW)
    cfg = {"language": "en", "channels": {}}
    ctx = {"cfg": cfg}
    said = "show my calendar of 25/10 13:00-14:00"
    got = plan_confirm.understood(ctx, "items", {}, said)
    assert "Sun 25/10/2026" in got, got
    assert plan_confirm._day(ctx, said) == "Sun 25/10/2026"


def test_the_mail_day_read_of_a_time_range_is_that_day():
    got = ops_interpret._day_read("25/10 13:00-14:00", NOW)
    assert got["kind"] == "day" and got["value"] == "2026-10-25"


def test_the_day_read_of_a_card_change_with_a_time_span_that_is_a_range_does_not_raise():
    assert event_lookup._day_named("dia 25/10 13:00-14:00", NOW)[0] == "day"          # the call of ops_event_revise's time span

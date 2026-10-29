"""A date the line states as the content of a request is not its moment (package BL7-4, fix A; limits L54 and L61).

"Remind me tomorrow at 9am to renew the parking permit before it expires on the 15th" names ONE moment, tomorrow at 9:00, and a deadline inside the reminder's words. The engine read two
days (tomorrow and the 15th) and asked "which time do you mean", on a messaging app (NR-1) and in the interpreter alike. `natural_time.find` now sets such a date apart (`deadline`), by the
words a language table lists as `deadline_words` ("expires", "due", "vence", "prazo"; never "before", "until" or "by": they may name the moment), only when the moment comes first, the line has
a clock, and no clock follows the date. Every other line is read as before: this file pins the negatives with literals taken from the base. The deadline's words stay in the reminder's text
and the event's title; no number is created or moved (L54) and a reminder is still confirmed (L61). Offline, no model; invented words; non-ASCII as `\\u` escapes.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_time_deadline.py
"""
from __future__ import annotations

import copy
import datetime

import pytest

import interpreter_kit as kit
import standin_tree as st
from closed_heads import closed_heads  # noqa: F401  (S41-11: the family readers read a line with no operation fixed again, for the tests of what they read)

nt = st.load("natural_time")
natural = st.load("natural")
interp = st.load("interpreter")
writes = st.load("natural_writes")

ZONE_EN, ZONE_PT = "America/New_York", "America/Sao_Paulo"
NOW_EN = kit.now_at("2026-11-12 14:20", ZONE_EN)          # a Thursday; tomorrow is Friday the 13th
NOW_PT = kit.now_at("2026-11-12 14:20", ZONE_PT)

EN = "Remind me tomorrow at 9am to renew the parking permit before it expires on the 15th."
PT = "Me lembra amanhã às 9h de renovar a licença antes que ela vença dia 15."      # validate: allow english-only -- the Portuguese line under test
PT_SLASH = "Me lembra amanha as 9h que o contrato vence em 15/11."
MOMENT = "2026-11-13 09:00"


def parsed(line, now):
    got = nt.parse(line, now)
    if got is None:
        return None
    if "when" in got:
        return got["when"]
    if "ask" in got:
        return ("ask", [r["when"] for r in got["ask"]])
    return got["missing"]


def understood(line, now):
    """(need, the readings' `when` words, the text) of NR-1's answer, in the shape the literals below are written in."""
    got = natural.understand(line, now)
    got = got.get("ask") or got
    readings = [r["when"] for r in got.get("readings", [])] or ([got["reading"]["when"]] if got.get("reading") else [])
    return got.get("need"), readings, got.get("text")


# --- 1. the engine sets the date apart --------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("line, now", ((EN, NOW_EN), (PT, NOW_PT), (PT_SLASH, NOW_PT)))
def test_the_deadline_date_is_set_apart_and_the_moment_is_the_one_reading(line, now):
    found = nt.find(line)
    assert len(found["deadline"]) == 1
    assert all(h not in found["deadline"] for h in found["hits"])          # the deadline is no hit: nothing downstream sees it
    assert parsed(line, now) == MOMENT
    assert nt.doubts(line)[0] is False


def test_the_deadline_hit_is_exactly_the_date_phrase_of_each_line():
    en, pt = nt.find(EN), nt.find(PT)
    assert [en["norm"][h["s"]:h["e"]].strip() for h in en["deadline"]] == ["on the 15th"]
    assert [pt["norm"][h["s"]:h["e"]].strip() for h in pt["deadline"]] == ["dia 15"]
    assert [en["norm"][h["s"]:h["e"]].strip() for h in en["hits"]] == ["tomorrow", "at 9am"]


def test_the_spans_never_cut_the_deadline_words_from_the_text():
    spans = nt._spans(nt.find(EN))
    assert nt.without(EN, spans) == "Remind me to renew the parking permit before it expires on the 15th."


# --- 2. every other line is read as before (literals taken from the base) ------------------------------------------------------------------------------------

BASE_OUTCOMES = (
    # (line, parse, doubts flag, NR-1 need, NR-1 readings, NR-1 text)
    ("Remind me to pay the rent due on the 15th tomorrow at 9am.", ("ask", ["2026-11-15 09:00", "2026-11-13 09:00"]), False, "reading", ["2026-11-15 09:00", "2026-11-13 09:00"], "pay the rent due"),
    ("Remind me tomorrow at 9am or on the 15th.", ("ask", [MOMENT, "2026-11-15 09:00"]), False, "reading", [MOMENT, "2026-11-15 09:00"], ""),
    ("Remind me tomorrow at 9am that the report is due on the 15th at 3pm.", ("ask", [MOMENT, "2026-11-13 15:00", "2026-11-15 09:00", "2026-11-15 15:00"]), False, "reading",
     [MOMENT, "2026-11-13 15:00", "2026-11-15 09:00", "2026-11-15 15:00"], "the report is due"),
    ("Remind me on the 15th that the permit expires.", "time", False, "time", [], "the permit expires"),
    ("Remind me before it expires on the 15th", "time", True, "time", [], "before it expires"),
    ("Remind me tomorrow at 9am to renew the permit before the 15th.", ("ask", [MOMENT, "2026-11-15 09:00"]), True, "reading", [MOMENT, "2026-11-15 09:00"], "renew the permit before"),
    ("Remind me tomorrow to check the report due on the 15th.", "time", False, "time", [], "check the report due"),
)


@pytest.mark.parametrize("line, parse, doubt, need, readings, text", BASE_OUTCOMES)
def test_a_line_the_rule_does_not_cover_is_read_exactly_as_the_base_read_it(line, parse, doubt, need, readings, text):
    found = nt.find(line)
    assert found["deadline"] == []
    got = parsed(line, NOW_EN)
    assert got == parse
    assert nt.doubts(line)[0] is doubt
    assert understood(line, NOW_EN) == (need, readings, text)


# --- 2b. a destination or a second moment is never a deadline (review of BL7-4) -------------------------------------------------------------------------------

D20 = "2026-11-20 09:00"
CHANGE_LINES = (      # (line, the clock and zone, the model's target and time span): the date before the deadline word is the event's day, the one after it the new day
    ("muda a reuni\u00e3o de amanh\u00e3 \u00e0s 9h pro vencimento dia 20", NOW_PT, ZONE_PT, "reuni\u00e3o", "amanh\u00e3 \u00e0s 9h", ("ask", [MOMENT, D20])),      # validate: allow english-only -- the Portuguese line under test
    ("adia a reuni\u00e3o de amanh\u00e3 \u00e0s 9h do prazo pra sexta", NOW_PT, ZONE_PT, "reuni\u00e3o", "amanh\u00e3 \u00e0s 9h", MOMENT),      # validate: allow english-only -- the Portuguese line under test
    ("move tomorrow's 9am meeting to the deadline on the 20th", NOW_EN, ZONE_EN, "meeting", "tomorrow's 9am", ("ask", [MOMENT, D20])),
)
TWO_MOMENTS = (      # (line, the clock, what the base reads): a coordinating word stands between the first moment and the date
    ("Remind me tomorrow at 9am, then again on the due date, the 15th.", NOW_EN, ("ask", [MOMENT, "2026-11-15 09:00"])),
    ("Me lembra amanh\u00e3 \u00e0s 9h, depois de novo no dia do vencimento, dia 15.", NOW_PT, ("ask", [MOMENT, "2026-11-15 09:00"])),      # validate: allow english-only -- the Portuguese line under test
    ("Remind me tomorrow at 9am about the deadline, and friday.", NOW_EN, MOMENT),
)


def change(line, now, zone, target, span):
    obj = {"v": 1, "kind": "op", "op": "event-change", "slots": {"target": target, "time": span}, "time_iso": "2026-11-13T09:00", "weekday": "fri"}
    return interp.check(obj, line, None, kit.CATALOG, now, zone, kit.ALL_OPS)


@pytest.mark.parametrize("line, now, zone, target, span, base", CHANGE_LINES)
def test_a_date_after_a_destination_word_is_never_set_apart_and_a_change_asks_as_before(line, now, zone, target, span, base):
    assert nt.find(line)["deadline"] == [] and parsed(line, now) == base
    got = change(line, now, zone, target, span)
    assert got["kind"] == "clarify" and got["why"] == "time-ask" and got["slot"] == "time", got


def without_destination_words(monkeypatch):
    for table in nt.languages():
        monkeypatch.setitem(table, "deadline_to", [])


@pytest.mark.parametrize("line, now, zone, target, span, base", CHANGE_LINES)
def test_each_guard_of_a_change_holds_alone(line, now, zone, target, span, base, monkeypatch):
    without_destination_words(monkeypatch)          # the engine rule is off: the date is set apart again (the defect), and the change still asks
    assert parsed(line, now) == MOMENT          # the one reading of the base moment
    got = change(line, now, zone, target, span)
    assert got["kind"] == "clarify" and got["why"] == "time-ask", got


@pytest.mark.parametrize("line, now, zone, target, span, base", CHANGE_LINES)
def test_vacuity_with_both_guards_off_a_change_takes_the_time_of_the_event_day(line, now, zone, target, span, base, monkeypatch):
    without_destination_words(monkeypatch)
    monkeypatch.setattr(interp, "_deadline_set_apart", lambda text: False)
    got = change(line, now, zone, target, span)
    assert got["kind"] == "op" and got["time"]["local"] == "2026-11-13T09:00", got          # the planted defect: the change would move the event to the old day


@pytest.mark.parametrize("line, now, zone, target, span, base", CHANGE_LINES[:1])
def test_the_change_guard_alone_asks_when_the_engine_sets_the_date_apart(line, now, zone, target, span, base, monkeypatch):
    without_destination_words(monkeypatch)
    assert parsed(line, now) == MOMENT
    monkeypatch.setattr(interp, "_deadline_set_apart", lambda text: True)
    assert change(line, now, zone, target, span)["why"] == "time-ask"


@pytest.mark.parametrize("line, now, base", TWO_MOMENTS)
def test_a_second_moment_after_a_coordinating_word_is_not_a_deadline(line, now, base):
    assert nt.find(line)["deadline"] == [] and parsed(line, now) == base


@pytest.mark.parametrize("line, now, base", TWO_MOMENTS[:2])
def test_vacuity_without_the_coordinating_words_the_second_moment_is_dropped(line, now, base, monkeypatch):
    for table in nt.languages():
        monkeypatch.setitem(table, "deadline_breaks", [])
    got = parsed(line, now)
    assert got == MOMENT, got          # the planted defect: one reading, the other day kept only in the text


def test_a_destination_word_inside_the_window_of_a_line_that_is_a_deadline_does_not_block_it():
    assert len(nt.find("Remind me tomorrow at 9am to renew the permit that expires on the 15th")["deadline"]) == 1
    assert len(nt.find(PT_SLASH)["deadline"]) == 1


# --- 3. NR-1, the interpreter's classifier and its check ---------------------------------------------------------------------------------------------------

def test_nr1_confirms_the_one_moment_and_keeps_the_deadline_in_the_text():
    assert understood(EN, NOW_EN) == ("confirm", [MOMENT], "renew the parking permit before it expires on the 15th")
    assert understood(PT, NOW_PT) == ("confirm", [MOMENT], "renovar a licença antes que ela vença dia 15")      # validate: allow english-only -- the Portuguese line under test
    assert understood(PT_SLASH, NOW_PT) == ("confirm", [MOMENT], "o contrato vence em 15/11")


def test_the_classifier_reads_the_moment_by_code_so_the_model_is_not_asked_again():
    assert interp._classify("tomorrow at 9am", EN, interp._local_now(NOW_EN, ZONE_EN))[0] == "code"
    assert interp._classify("amanhã às 9h", PT, interp._local_now(NOW_PT, ZONE_PT))[0] == "code"      # validate: allow english-only -- the Portuguese line under test
    assert interp._classify("amanha as 9h", PT_SLASH, interp._local_now(NOW_PT, ZONE_PT))[0] == "code"          # a slash deadline: `_unread_day` counts it as read too


def remind(text, when, line, now, zone):
    obj = {"v": 1, "kind": "op", "op": "remind", "slots": {"text": text, "when": when}, "time_iso": "2026-11-13T09:00", "weekday": "fri"}
    return interp.check(obj, line, None, kit.CATALOG, now, zone, kit.ALL_OPS)


def test_the_recorded_answer_of_the_blind_item_is_an_op_with_the_moment():
    got = remind("renew the parking permit before it expires on the 15th", "tomorrow at 9am", EN, NOW_EN, ZONE_EN)
    assert got["kind"] == "op" and got["op"] == "remind" and got["time"] == {"local": "2026-11-13T09:00", "source": "code"}, got
    assert got["args"]["text"] == "renew the parking permit before it expires on the 15th"
    got = remind("renovar a licença antes que ela vença dia 15", "amanhã às 9h", PT, NOW_PT, ZONE_PT)      # validate: allow english-only -- the Portuguese line under test
    assert got["kind"] == "op" and got["time"]["local"] == "2026-11-13T09:00", got
    got = remind("o contrato vence em 15/11", "amanha as 9h", PT_SLASH, NOW_PT, ZONE_PT)
    assert got["kind"] == "op" and got["time"]["local"] == "2026-11-13T09:00", got


def test_a_line_without_a_deadline_word_is_still_asked_by_the_check():
    got = remind("renew the permit", "tomorrow at 9am", "Remind me tomorrow at 9am to renew the permit or on the 15th.", NOW_EN, ZONE_EN)
    assert got["kind"] == "clarify" and got["why"] == "time-ask", got


# --- 4. the tables are the rule; vacuity -----------------------------------------------------------------------------------------------------------------

def test_without_the_deadline_words_the_same_line_is_asked_again():
    tables = copy.deepcopy(nt.languages())
    for table in tables:
        table["deadline_words"] = []
    found = nt.find(EN, tables)
    assert found["deadline"] == [] and len(found["hits"]) == 3
    assert nt.parse(EN, NOW_EN, tables)["ask"] and len(nt.parse(EN, NOW_EN, tables)["ask"]) == 2


def test_a_table_without_deadline_words_is_refused_by_the_schema():
    table = copy.deepcopy(nt.languages()[0])
    del table["deadline_words"]
    with pytest.raises(ValueError, match="deadline_words"):
        nt.check_table(table)
    table["deadline_words"] = ["Expires"]
    with pytest.raises(ValueError, match="deadline_words"):
        nt.check_table(table)


def test_the_words_of_the_shipped_tables_are_the_decided_ones_and_never_name_the_moment():
    en, pt = (t["deadline_words"] for t in nt.languages())
    assert en == ["expires", "expire", "expiring", "expired", "due", "deadline"]
    assert pt == ["vence", "vencer", "venca", "vencem", "vencimento", "prazo", "expira", "expirar"]
    assert not ({"before", "until", "by", "antes", "ate"} & set(en + pt))


def test_each_condition_of_the_rule_is_needed(monkeypatch):
    # a deadline word after the date, a date alone, no clock, or a clock after the date: none of them sets the date apart
    for line in ("Remind me tomorrow at 9am that the permit on the 15th expires.", "Remind me on the 15th, it expires at 9am.", "Remind me tomorrow that it expires on the 15th.",
                 "Remind me tomorrow at 9am that it is due on the 15th at 3pm."):
        assert nt.find(line)["deadline"] == [], line
    # the same shapes with the rule's words and order do set it apart: the first condition alone is not what moved
    assert len(nt.find("Remind me tomorrow at 9am that the permit is due on the 15th.")["deadline"]) == 1
    monkeypatch.setattr(nt, "_deadlines", lambda norm, hits, tables: (hits, []))
    assert nt.find(EN)["deadline"] == [] and parsed(EN, NOW_EN) != MOMENT


# --- 5. an event card for the moment, the deadline in its title ----------------------------------------------------------------------------------------------

def test_an_event_line_with_a_deadline_after_the_moment_reads_the_moment_and_keeps_the_title():
    line = "marca reuniao amanha as 9h para revisar o contrato que vence dia 15"
    got = writes.read(line, NOW_PT)
    assert got["op"] == "event-create" and got["need"] == [] and got["slots"]["start"] == "2026-11-13T09:00", got
    assert got["slots"]["title"] == "reuniao para revisar o contrato que vence dia 15"
    assert got["engine"] is None


def test_the_same_event_line_with_the_cue_removed_still_asks_which_day():
    got = writes.read("marca reuniao amanha as 9h para revisar o contrato no dia 15", NOW_PT)
    assert got["need"] == ["start"] and got["engine"]["need"] == "reading" and len(got["engine"]["readings"]) == 2, got

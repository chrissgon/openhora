"""The time rules of the interpreter's validator (package IX-2a, runtime/interpreter.py `time_source` and `check`): code alone decides whose time is believed (D4 and the guard of DECISIONS 213).

The clock is fixed (Tuesday 2026-10-20 09:00 in the project's zone) and every expected date is written here as a literal. Checked: the weekday of a model's date; a time that has passed; a
time more than 366 days away; the wall times the clock skips (`2026-03-29T02:30` in Berlin, `2026-03-08T02:30` in New York) and the one it repeats (`2026-10-25T02:30` in Berlin); a Portuguese or
English span that code reads wins over a different `time_iso` (and the disagreement is reported); a span that holds a time word of a table but no single reading is asked about; a span in no
table is left to the model, whose hour cannot move an hour that code read; and the model never says which language the line is in. Vacuity: a validator that skips the gap rule is caught by the same
assertion. Offline, no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_time.py
"""
from __future__ import annotations

import interpreter_kit as kit
import standin_tree as st

interp = st.load("interpreter")

JA = "来週の火曜日の15時"          # a span in no table: Tuesday 2026-10-27 at 15:00 (the line says "next Tuesday at 15h")
JA_GAP = "3月29日午前2時30分"
JA_FOLD = "10月25日午前2時30分"
JA_NY = "3月8日午前2時30分"


def remind(span, time_iso, weekday, text="call Dana"):
    return {"v": 1, "kind": "op", "op": "remind", "slots": {"text": text, "when": span}, "time_iso": time_iso, "weekday": weekday}


def run(obj, line, now=None, zone=kit.ZONE):
    return interp.check(obj, line, None, kit.CATALOG, now or kit.NOW, zone, kit.ALL_OPS)


def assert_clarify(decision, why, error=None):
    assert decision["kind"] == "clarify" and decision["why"] == why and decision["error"] == error, decision


def line_for(span, text="call Dana"):
    return f"{text} {span}"


# --- who decides -----------------------------------------------------------------------------------------------------------------------------------

def test_time_source_is_decided_by_code_from_the_span_alone():
    expected = {
        "Thursday at 3pm": "code", "quinta às 15h": "code", "15:00": "code", "in 2 hours": "code",
        "amanh\u00e3": "ask", "às 9": "ask", "at 9": "ask", "next week": "ask", "sábado": "ask", "friday at midnight": "ask", "sexta que vem às 10h": "ask", "amanh\u00e3 às 9": "ask",
        JA: "model", "mardi prochain": "model", "dimanche": "model", "morgen um 15 Uhr": "model", "domani alle 15": "model",
        "mañana a las 15:00": "model", "demain à 15h30": "model",
    }
    wrong = {span: interp.time_source(span, kit.NOW, kit.ZONE) for span, want in expected.items() if interp.time_source(span, kit.NOW, kit.ZONE) != want}
    assert wrong == {}


def test_a_naive_clock_is_read_in_the_project_zone():
    import datetime
    naive = datetime.datetime(2026, 10, 20, 9, 0)
    assert interp.time_source("Thursday at 3pm", naive, kit.ZONE) == "code"


def test_a_year_that_code_had_to_assume_is_asked_not_believed():
    assert interp.time_source("march 29 at 2:30am", kit.NOW, kit.ZONE) == "ask"          # the date is in March; this is October, so the year is a guess


# --- the model's own time ----------------------------------------------------------------------------------------------------------------------------

def test_a_span_in_no_table_gives_the_model_its_date_and_the_decision_names_the_source():
    got = run(remind(JA, "2026-10-27T15:00", "tue"), line_for(JA))
    assert got["kind"] == "op" and got["time"] == {"local": "2026-10-27T15:00", "source": "model"} and got["time_disagree"] is False


def test_the_weekday_of_the_date_is_checked_and_a_mismatch_is_asked_back():
    for weekday in ("mon", "wed", "thu", "fri", "sat", "sun"):
        assert_clarify(run(remind(JA, "2026-10-27T15:00", weekday), line_for(JA)), "weekday", "E_WEEKDAY")
    got = run(remind(JA, "2026-10-27T15:00", "wed"), line_for(JA))
    assert got["slot"] == "when"


def test_a_time_that_has_passed_is_asked_back():
    assert_clarify(run(remind(JA, "2026-10-19T15:00", "mon"), line_for(JA)), "time-past")          # yesterday
    assert_clarify(run(remind(JA, "2026-10-20T09:00", "tue"), line_for(JA)), "time-past")          # this very minute
    assert_clarify(run(remind(JA, "2026-10-20T08:59", "tue"), line_for(JA)), "time-past")
    assert run(remind(JA, "2026-10-20T09:01", "tue"), line_for(JA))["kind"] == "op"


def test_a_time_more_than_366_days_away_is_asked_back():
    assert run(remind(JA, "2027-10-21T08:59", "thu"), line_for(JA))["kind"] == "op"          # 2026-10-20 09:00 + 366 days = 2027-10-21 09:00
    assert run(remind(JA, "2027-10-21T09:00", "thu"), line_for(JA))["kind"] == "op"
    assert_clarify(run(remind(JA, "2027-10-21T09:01", "thu"), line_for(JA)), "time-far")
    assert_clarify(run(remind(JA, "2028-01-04T15:00", "tue"), line_for(JA)), "time-far")
    assert_clarify(run(remind(JA, "2099-01-05T15:00", "mon"), line_for(JA)), "time-far")


def test_a_wall_time_the_clock_skips_or_repeats_is_asked_back_in_the_project_zone():
    berlin = kit.now_at("2026-03-01 09:00", "Europe/Berlin")
    gap = run(remind(JA_GAP, "2026-03-29T02:30", "sun"), line_for(JA_GAP), berlin, "Europe/Berlin")
    assert_clarify(gap, "time-gap")
    autumn = kit.now_at("2026-10-01 09:00", "Europe/Berlin")
    fold = run(remind(JA_FOLD, "2026-10-25T02:30", "sun"), line_for(JA_FOLD), autumn, "Europe/Berlin")
    assert_clarify(fold, "time-fold")
    york = kit.now_at("2026-03-01 09:00", "America/New_York")
    assert_clarify(run(remind(JA_NY, "2026-03-08T02:30", "sun"), line_for(JA_NY), york, "America/New_York"), "time-gap")
    # The hours next to them are fine.
    assert run(remind(JA_GAP, "2026-03-29T01:30", "sun"), line_for(JA_GAP), berlin, "Europe/Berlin")["kind"] == "op"
    assert run(remind(JA_GAP, "2026-03-29T03:30", "sun"), line_for(JA_GAP), berlin, "Europe/Berlin")["kind"] == "op"
    assert run(remind(JA_FOLD, "2026-10-25T01:30", "sun"), line_for(JA_FOLD), autumn, "Europe/Berlin")["kind"] == "op"
    assert run(remind(JA_FOLD, "2026-10-25T03:30", "sun"), line_for(JA_FOLD), autumn, "Europe/Berlin")["kind"] == "op"
    # The same wall time in a zone that has no change that day is a plain time.
    assert run(remind(JA_GAP, "2026-03-29T02:30", "sun"), line_for(JA_GAP), kit.now_at("2026-03-01 09:00"), kit.ZONE)["kind"] == "op"


def test_a_time_code_reads_in_english_is_checked_by_the_same_rules():
    berlin = kit.now_at("2026-03-01 09:00", "Europe/Berlin")
    span = "march 29 at 2:30am"
    assert interp.time_source(span, berlin, "Europe/Berlin") == "code"
    assert_clarify(run(remind(span, "2026-03-29T02:30", "sun"), line_for(span), berlin, "Europe/Berlin"), "time-gap")


def test_the_model_cannot_move_an_hour_that_code_read():
    span = "mañana a las 15:00"
    assert interp.time_source(span, kit.NOW, kit.ZONE) == "model"
    ok = run(remind(span, "2026-10-21T15:00", "wed"), line_for(span))
    assert ok["kind"] == "op" and ok["time"] == {"local": "2026-10-21T15:00", "source": "model"}
    for hour in ("2026-10-21T16:00", "2026-10-21T03:00", "2026-10-21T00:00"):
        assert_clarify(run(remind(span, hour, "wed"), line_for(span)), "time-ask")
    span = "demain à 15h30"
    assert run(remind(span, "2026-10-21T15:30", "wed"), line_for(span))["time"]["source"] == "model"
    assert_clarify(run(remind(span, "2026-10-21T16:30", "wed"), line_for(span)), "time-ask")


# --- code wins ------------------------------------------------------------------------------------------------------------------------------------

def test_a_portuguese_or_english_span_read_by_code_wins_over_a_different_time_iso():
    for span, wrong, weekday in (("quinta às 15h", "2026-10-23T16:00", "fri"), ("Thursday at 3pm", "2026-10-29T15:00", "thu"), ("quinta às 15h", "2026-10-22T14:00", "thu")):
        got = run(remind(span, wrong, weekday), line_for(span))
        assert got["kind"] == "op" and got["time"] == {"local": "2026-10-22T15:00", "source": "code"}, (span, got)
        assert got["time_disagree"] is True
    same = run(remind("quinta às 15h", "2026-10-22T15:00", "thu"), line_for("quinta às 15h"))
    assert same["time"]["source"] == "code" and same["time_disagree"] is False


def test_the_weekday_of_a_time_code_reads_is_not_the_models_to_get_wrong():
    got = run(remind("quinta às 15h", "2026-10-22T15:00", "mon"), line_for("quinta às 15h"))
    assert got["kind"] == "op" and got["time"]["source"] == "code" and got["time_disagree"] is False


def test_a_relative_reading_is_a_code_reading_with_its_date():
    got = run(remind("in 2 hours", "2026-10-20T11:00", "tue"), line_for("in 2 hours"))
    assert got["time"] == {"local": "2026-10-20T11:00", "source": "code"}


# --- asking back -------------------------------------------------------------------------------------------------------------------------------------

def test_a_span_with_a_time_word_and_no_single_reading_is_asked():
    for span in ("amanh\u00e3", "sábado", "next week", "às 9", "at 9", "friday at midnight", "amanh\u00e3 às 9", "sexta que vem às 10h"):
        got = run(remind(span, "2026-10-21T09:00", "wed"), line_for(span))
        assert_clarify(got, "time-ask")
        assert got["slot"] == "when"


def test_a_day_without_an_hour_for_an_event_is_asked_too_and_the_op_is_named():
    obj = {"v": 1, "kind": "op", "op": "event-create", "slots": {"title": "car service", "time": "sábado"}, "time_iso": "2026-10-24T10:00", "weekday": "sat"}
    got = run(obj, "car service sábado")
    assert_clarify(got, "time-ask")
    assert got["slot"] == "time" and got["op"] == "event-create"


def test_the_model_cannot_unlock_its_own_time_by_what_it_says_about_the_span():
    # The weekday and the date are the model's; whether they are believed is decided from the span by code. A span code half-reads is never the model's.
    span = "friday at midnight"
    for time_iso, weekday in (("2026-10-23T00:00", "fri"), ("2026-10-24T00:00", "sat")):
        assert_clarify(run(remind(span, time_iso, weekday), line_for(span)), "time-ask")
    # A span code reads as a time is the code's, so a model that claims another date gets the code's date.
    got = run(remind("Thursday at 3pm", "2026-10-30T15:00", "fri"), line_for("Thursday at 3pm"))
    assert got["time"]["source"] == "code" and got["time"]["local"] == "2026-10-22T15:00"
    for forbidden in ("language", "lang", "source"):
        got = interp.parse('{"v":1,"kind":"op","op":"remind","slots":{"when":"x"},"time_iso":"2026-10-22T15:00","weekday":"thu","' + forbidden + '":"model"}')
        assert got[0] is None and got[2] == "E_SHAPE"


def test_a_span_that_is_not_in_the_line_is_refused_before_any_time_is_read():
    got = run(remind("quinta às 15h", "2026-10-22T15:00", "thu"), "call Dana friday at 4pm")
    assert got["kind"] == "clarify" and got["error"] == "E_SPAN"
    got = run(remind("QUINTA às 15h", "2026-10-22T15:00", "thu"), "call Dana quinta às 15h")
    assert got["kind"] == "clarify" and got["error"] == "E_SPAN"


# --- vacuity ---------------------------------------------------------------------------------------------------------------------------------------

def test_vacuity_a_validator_without_the_gap_rule_is_caught_by_the_gap_assertion(monkeypatch):
    berlin = kit.now_at("2026-03-01 09:00", "Europe/Berlin")
    obj = remind(JA_GAP, "2026-03-29T02:30", "sun")
    assert_clarify(run(obj, line_for(JA_GAP), berlin, "Europe/Berlin"), "time-gap")
    monkeypatch.setattr(interp, "_instant_problem", lambda naive, tz, now: None)
    broken = run(obj, line_for(JA_GAP), berlin, "Europe/Berlin")
    assert broken["kind"] == "op"
    try:
        assert_clarify(broken, "time-gap")
    except AssertionError:
        return
    raise AssertionError("the assertion did not catch a validator without the gap rule")

# --- the source is decided from the whole line, never from the span the model chose (review of #495, B1) ---------------------------------------------------

EN_LINE = "remind me to call Dana tomorrow at 3pm"
PT_LINE = "me lembra amanhã às 15h de ligar pra Dana"
# (line, the text slot, the literal words a span must hold to be the time of the line: the oracle's own list)
SPAN_CASES = [(EN_LINE, "call Dana", ("tomorrow", "3pm")), (PT_LINE, "ligar pra Dana", ("amanhã", "15h")),
              ("remind me at 3pm to call Dana", "call Dana", ("3pm",)), ("remind me on December 5 at 10am to pay rent", "pay rent", ("December 5", "10am"))]


def word_spans(line):
    words = line.split(" ")
    for i in range(len(words)):
        for j in range(i + 1, len(words) + 1):
            yield " ".join(words[i:j])


def test_no_span_of_the_line_but_the_one_that_holds_every_time_phrase_gives_a_time():
    seen_time = 0
    for line, text, needed in SPAN_CASES:
        for span in word_spans(line):
            got = run(remind(span, "2026-10-21T15:00", "wed", text), line)
            if got["kind"] == "op" and got["time"] is not None:
                seen_time += 1
                assert all(word in span for word in needed), (line, span, got)          # the oracle: the span holds every time phrase of the line
                assert got["time"]["source"] == "code"
            else:
                assert got["kind"] == "clarify" and got["why"] in ("time-ask", "time-past", "time-far", "weekday", "invalid"), (line, span, got)
    assert seen_time >= 4          # not vacuous: the right spans are accepted


def test_probes_of_the_review_a_span_with_no_time_in_it_or_a_truncated_one_is_asked():
    for line, text, span in ((EN_LINE, "call Dana tomorrow at 3pm", "Dana"), (EN_LINE, "call Dana", "me"), (PT_LINE, "ligar pra Dana", "Dana"), (EN_LINE, "call Dana", "at 3pm"),
                             ("remind me at 3pm to call Dana", "call Dana", "3pm to call Dana"), ("remind me at 3pm to call Dana", "call Dana", "Dana")):
        assert_clarify(run(remind(span, "2026-10-21T15:00", "wed", text), line), "time-ask")


def test_the_answer_path_is_decided_from_the_line_too():
    frame = {"v": 1, "last": None, "items": [kit.item("i1", kind="reminder-confirm", need="slot", op="remind", slot="when", age_s=10)]}
    answer = {"v": 1, "kind": "answer", "answers_item": "i1", "slot": "when", "span": "no", "time_iso": "2026-10-21T15:00", "weekday": "wed"}
    got = interp.check(answer, "no, tomorrow at 3pm", frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)
    assert_clarify(got, "time-ask")
    good = dict(answer, span="tomorrow at 3pm")
    got = interp.check(good, "no, tomorrow at 3pm", frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)
    assert got["kind"] == "answer" and got["time"] == {"local": "2026-10-21T15:00", "source": "code"}


def test_time_source_given_the_line_asks_when_the_span_leaves_a_time_phrase_out():
    assert interp.time_source("at 3pm", kit.NOW, kit.ZONE, EN_LINE) == "ask"
    assert interp.time_source("tomorrow at 3pm", kit.NOW, kit.ZONE, EN_LINE) == "code"
    assert interp.time_source("Dana", kit.NOW, kit.ZONE, EN_LINE) == "ask"
    assert interp.time_source(JA, kit.NOW, kit.ZONE, line_for(JA)) == "model"
    assert interp.time_source("Dana", kit.NOW, kit.ZONE, "remind Dana") == "ask"          # a word of a table in the line


def test_an_hour_only_reading_is_the_models_only_when_the_line_holds_no_word_of_a_table():
    span, line = "mañana a las 15:00", "recuérdame mañana a las 15:00 llamar a Dana"
    assert interp.time_source(span, kit.NOW, kit.ZONE, line) == "model"
    assert interp.time_source("15:00", kit.NOW, kit.ZONE, line) == "model"
    # A line with a word of a table ("remind") is code's: the hour code read, today's date.
    assert interp.time_source("at 3pm", kit.NOW, kit.ZONE, "remind me at 3pm to call Dana") == "code"
    got = run(remind("at 3pm", "2027-01-05T15:00", "tue"), "remind me at 3pm to call Dana")
    assert got["time"] == {"local": "2026-10-20T15:00", "source": "code"} and got["time_disagree"] is True
    # Residue, written down: a line of words no table holds and an hour only is the model's date, shown on the card.
    assert interp.time_source("at 15:00", kit.NOW, kit.ZONE, "call Dana at 15:00") == "model"


# --- years the zone arithmetic cannot take (review of #495, M1) ---------------------------------------------------------------------------------------

def test_a_year_far_from_now_is_asked_back_and_never_an_exception():
    for stamp, weekday, why in (("9999-12-31T23:59", "fri", "time-far"), ("0001-01-01T00:00", "mon", "time-past"), ("2030-06-03T10:00", "mon", "time-far"), ("2024-10-21T10:00", "mon", "time-past"),
                                ("2028-10-23T10:00", "mon", "time-far")):
        for zone in (kit.ZONE, "Asia/Tokyo", "Europe/Berlin"):
            assert_clarify(run(remind(JA, stamp, weekday), line_for(JA), kit.now_at("2026-10-20 09:00", zone), zone), why)
    assert interp.parse('{"v":1,"kind":"op","op":"remind","slots":{"when":"x"},"time_iso":"9999-12-31T23:59","weekday":"fri"}')[1] == "ok"

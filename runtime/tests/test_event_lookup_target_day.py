"""The day of an event named by its words (BL5C, root cause C5: "dia 25/10" written in the line, not read; runtime/event_lookup.py `_by_target`).

The day of a target used to be read from the model's `day` span ALONE: when the model took a word that looks like a day ("amanhas", a title word) as the day, the date written elsewhere in
the line was never consulted and the person was asked for the day they had already written. Now the day is read from two places, the `day` span and the REST of the line (the line with
the target, day, time and title spans cut out), and the table decides: one of them unread is a question (L61); a day and nothing is that day; the same day twice is that day; two
different days are a question that names both (EV_ASK_WHICH_DAY) and opens nothing; no day span and no day anywhere is the window search as before; a day span code cannot read stays a
question. A rest that names another object (a mail, a file, an address) is ignored. Held here with the test's own rows, the stand-in `writes` and `Spies` of test_blite_event_target.py
and a stand-in clock (Sunday 2026-10-25 00:47 in America/Sao_Paulo, as on the live trace); one test per row of the table. Vacuity: with the rest not read, the live shape is asked
for the day again. Every name is invented; no model and no provider is called. Offline; Python 3.9.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup_target_day.py
"""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

import standin_tree as st
from test_blite_event_target import Spies, Writes, phrase, row  # noqa: F401  (the stand-ins of the target path)

event_lookup = st.load("event_lookup")
phrases = st.load("phrases")

ZONE = ZoneInfo("America/Sao_Paulo")
NOW = datetime.datetime(2026, 10, 25, 0, 47, tzinfo=ZONE)          # Sunday 25/10
CFG = {"language": "pt-BR"}
SENDER = "telegram:830461975213"
SUN, MON, TUE, WED, FRI = (datetime.date(2026, 10, d) for d in (25, 26, 27, 28, 30))
HAIR = [row(1, SUN, "corte de cabelo"), row(2, MON, "corte de cabelo"), row(3, WED, "Dentista"), row(4, FRI, "Dentista"), row(5, MON, "Dentista")]
ENGLISH = [row(5, MON, "dentist appointment"), row(6, FRI, "dentist appointment")]
OPENED = "OPENED"
LIVE = "Remova o corte de cabelo para amanhas da agenda, dia 25/10"          # validate: allow english-only -- the Portuguese line under test
SUN_SEED = {"op": "event-cancel", "slots": {"event": 1, "source": "agenda"}}


def said(op, line, spans, time=None, rows=HAIR, monkeypatch=None, cfg=CFG):
    """(reply, extras, writes, spies) of `open_event` for a decision whose spans the check verified."""
    spies, writes, extras = Spies(monkeypatch, rows), Writes(), {}
    decision = {"op": op, "spans": spans, "args": {}, "time": time}
    reply = event_lookup.open_event("project", {"cfg": cfg}, decision, line, SENDER, extras, writes, NOW)
    return reply, extras, writes, spies


def cancel(line, spans, monkeypatch, **more):
    return said("event-cancel", line, spans, monkeypatch=monkeypatch, **more)


def asked_day(reply, writes, spies):
    assert reply == phrase("EV_ASK_DAY") and writes.calls == [] and spies.log == [], reply


# --- one test per row of the table ------------------------------------------------------------------------------------------------------------------

def test_row_1_the_day_span_unread_is_asked_whatever_the_rest_says(monkeypatch):
    reply, _, writes, spies = cancel("Remova o corte de cabelo dia 40, dia 25/10", {"target": "corte de cabelo", "day": "dia 40"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    asked_day(reply, writes, spies)


def test_row_2_the_rest_unread_is_asked_even_when_the_day_span_is_read(monkeypatch):
    reply, _, writes, spies = cancel("Remova o corte de cabelo de amanhã, na terça passada", {"target": "corte de cabelo", "day": "amanhã"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    asked_day(reply, writes, spies)


def test_row_3_a_day_span_and_a_rest_with_no_day_is_the_day_span(monkeypatch):
    reply, _, writes, _ = cancel("Remova o corte de cabelo de amanhã da agenda", {"target": "corte de cabelo", "day": "amanhã"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    assert reply == OPENED and writes.seeds == [{"op": "event-cancel", "slots": {"event": 2, "source": "agenda"}}], "tomorrow is Mon 26/10"


def test_row_4_the_same_day_twice_is_that_day_a_date_and_a_weekday_of_it_included(monkeypatch):
    for line, day in (("Remova o corte de cabelo de amanhã, dia 26/10", "amanhã"), ("Remova o corte de cabelo de segunda, dia 26/10", "segunda"), ("Remova o corte de cabelo de 26/10, segunda", "26/10")):          # validate: allow english-only -- the Portuguese line under test
        reply, _, writes, _ = cancel(line, {"target": "corte de cabelo", "day": day}, monkeypatch)
        assert reply == OPENED and writes.seeds == [{"op": "event-cancel", "slots": {"event": 2, "source": "agenda"}}], line


def test_row_5_two_different_days_are_asked_naming_both_and_nothing_is_opened(monkeypatch):
    reply, extras, writes, spies = cancel("remove o dentista de amanhã, dia 30/10", {"target": "dentista", "day": "amanhã"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    assert reply == phrase("EV_ASK_WHICH_DAY", a="Mon 26/10/2026", b="Fri 30/10/2026"), reply
    assert writes.calls == [] and spies.log == [] and "resend" not in extras and extras["stored"] == phrase("NW_PRIVATE_REPLY")
    assert "26/10" in reply and "30/10" in reply


def test_row_5_a_weekday_word_that_is_not_the_date_is_a_conflict_too(monkeypatch):
    reply, _, writes, _ = cancel("remove o dentista de sexta, dia 28/10", {"target": "dentista", "day": "sexta"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    assert reply == phrase("EV_ASK_WHICH_DAY", a="Fri 30/10/2026", b="Wed 28/10/2026") and writes.calls == [], "the engine turns 'sexta' into the next Friday"


def test_a_weekday_and_a_date_on_it_are_the_same_day_and_the_date_is_kept():
    friday, other = ("weekday", 4), ("day", FRI)
    assert event_lookup._same_day(friday, other) == other and event_lookup._same_day(other, friday) == other
    assert event_lookup._same_day(friday, ("day", WED)) is None and event_lookup._same_day(friday, ("weekday", 4)) == friday and event_lookup._same_day(other, ("day", WED)) is None


def test_a_weekday_is_written_by_its_word_and_a_date_in_the_operations_layers_shape():
    ctx = {"cfg": CFG}
    assert event_lookup._day_written(ctx, "weekday", 4) == phrase("WD_FRI") and event_lookup._day_written(ctx, "day", FRI) == "Fri 30/10/2026"


def test_row_5_the_question_is_in_english_for_an_english_project(monkeypatch):
    reply, _, writes, _ = said("event-cancel", "remove the dentist for tomorrow, on 30/10", {"target": "dentist", "day": "tomorrow"}, rows=ENGLISH, monkeypatch=monkeypatch, cfg={"language": "en"})
    assert reply == "You wrote two days for this event: Mon 26/10/2026 and Fri 30/10/2026. Which day is it on?" and writes.calls == []


@pytest.mark.parametrize("language", ["es", "fr", "de", "it"])
def test_row_5_the_other_languages_fall_back_to_english(monkeypatch, language):
    reply, _, writes, _ = said("event-cancel", "remove the dentist for tomorrow, on 30/10", {"target": "dentist", "day": "tomorrow"}, monkeypatch=monkeypatch, cfg={"language": language})
    assert reply.startswith("You wrote two days for this event:") and writes.calls == []


def test_row_6_no_day_span_and_a_day_in_the_rest_is_that_day_the_live_shape(monkeypatch):
    reply, _, writes, _ = cancel(LIVE, {"target": "corte de cabelo para amanhas"}, monkeypatch)
    assert reply.endswith(OPENED) and writes.seeds == [SUN_SEED], "the day written in the line, 25/10: the title word does not name a day (a name that is near, not the same, is said first)"


def test_the_live_shape_with_the_day_span_the_model_took_from_the_title_word_is_the_event_of_25_10(monkeypatch):
    reply, _, writes, _ = cancel(LIVE, {"target": "corte de cabelo", "day": "amanhas"}, monkeypatch)
    assert reply == OPENED and writes.seeds == [SUN_SEED], "'amanhas' names no day (row 7 of the table: none with a day span), the date of the rest does (row 6)"


def test_row_7_a_day_span_that_names_no_day_and_a_rest_with_none_is_asked(monkeypatch):
    reply, _, writes, spies = cancel("Remova o corte de cabelo para amanhas da agenda", {"target": "corte de cabelo", "day": "amanhas"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    asked_day(reply, writes, spies)


def test_row_8_no_day_span_and_no_day_anywhere_is_the_window_search_as_before(monkeypatch):
    reply, _, writes, spies = cancel("Remova o corte de cabelo da agenda", {"target": "corte de cabelo"}, monkeypatch)
    assert writes.seeds == [] and spies.lists == [("event-cancel", [1, 2], None)] and reply.startswith(phrase("EV_MANY_CANCEL"))


def test_a_change_reads_the_old_day_not_the_new_one_the_time_span_is_cut_before_the_rest_is_read(monkeypatch):
    line = "move the dentist appointment from tomorrow to Friday at 10am"
    spans = {"target": "the dentist appointment", "day": "tomorrow", "time": "Friday at 10am"}
    time = {"local": "2026-10-30T10:00", "source": "code"}
    reply, _, writes, _ = said("event-change", line, spans, time=time, rows=ENGLISH, monkeypatch=monkeypatch, cfg={"language": "en"})
    assert reply == OPENED and writes.seeds[0]["slots"]["event"] == 5 and writes.seeds[0]["slots"]["start"] == "2026-10-30T10:00", "the old day is tomorrow (Mon 26/10), the Dentista of that day"


def test_the_title_span_is_cut_from_the_rest_too(monkeypatch):
    line = "rename the dentist appointment of tomorrow to Sunday dentist"
    spans = {"target": "the dentist appointment", "day": "tomorrow", "title": "Sunday dentist"}
    reply, _, writes, _ = said("event-change", line, spans, rows=ENGLISH, monkeypatch=monkeypatch, cfg={"language": "en"})
    assert reply == OPENED and writes.seeds[0]["slots"]["event"] == 5, "'Sunday' in the new title is no day of the event"


def test_a_span_the_line_does_not_hold_is_a_question(monkeypatch):
    reply, _, writes, spies = cancel("Remova o corte de cabelo da agenda", {"target": "corte de cabelo", "day": "amanhã"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    asked_day(reply, writes, spies)
    reply, _, writes, spies = said("event-change", "Muda o dentista de amanhã", {"target": "dentista", "day": "amanhã", "time": "as 11h"}, time={"local": "2026-10-26T11:00", "source": "code"}, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    asked_day(reply, writes, spies)


def test_a_day_span_that_lies_inside_the_target_is_cut_once_and_is_not_a_question(monkeypatch):
    reply, _, writes, _ = cancel("Remova o dentista de segunda da agenda", {"target": "dentista de segunda", "day": "segunda"}, monkeypatch)          # validate: allow english-only -- the Portuguese line under test
    assert writes.seeds != [] or reply != phrase("EV_ASK_DAY"), "overlapping spans are not an unreadable line"


def test_a_rest_that_names_another_object_is_ignored(monkeypatch):
    line = "remove o dentista de amanhã, o e-mail de 30/10 já cancelou"          # validate: allow english-only -- the Portuguese line under test
    reply, _, writes, _ = cancel(line, {"target": "dentista", "day": "amanhã"}, monkeypatch)  # validate: allow english-only -- the Portuguese line under test
    assert reply == OPENED and writes.seeds == [{"op": "event-cancel", "slots": {"event": 5, "source": "agenda"}}], "the date of a mail is not the day of the event"


def test_vacuity_with_the_rest_not_read_the_live_shape_is_asked_for_the_day_again(monkeypatch):
    real = event_lookup._by_target

    def alone(project, ctx, decision, line, sender, extras, writes, now):          # the 81c1274 behaviour: the day of the target from the day span alone
        spans = decision["spans"]
        text = " ".join(str(spans.get("target") or "").split())
        kind, value = event_lookup._day_named(spans["day"], now) if spans.get("day") else event_lookup._day_named(text, now)
        if kind == "unread" or (spans.get("day") and kind == "none"):
            return phrases.text("EV_ASK_DAY", ctx["cfg"])
        return event_lookup._found(project, ctx, decision["op"], None, spans, line, sender, extras, writes, now, text, kind, value)

    monkeypatch.setattr(event_lookup, "_by_target", alone)
    reply, _, writes, spies = cancel(LIVE, {"target": "corte de cabelo", "day": "amanhas"}, monkeypatch)
    asked_day(reply, writes, spies)
    monkeypatch.setattr(event_lookup, "_by_target", real)
    reply, _, writes, _ = cancel(LIVE, {"target": "corte de cabelo", "day": "amanhas"}, monkeypatch)
    assert reply == OPENED and writes.seeds == [SUN_SEED]

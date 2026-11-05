"""A day alone, or an hour beside another change, on a line after the card of an event (CARD-DAY-ALONE-ASKED, SPEC-M41-3-OLD-FINDINGS change A; runtime/ops_event_revise.py `_model_time`, limits L55 and L63).

The phone test of 2026-11-02 (row 21) and the recorded card-model answers of 2026-11-01 (cb-16, cb-18, cb-27 and cb-28 of evals/interpreter/card-model-blind-v1.jsonl): the model gave the whole new start and
the checks asked anyway, because code could not settle "next tuesday", "donnerstag", "quinta que vem" or an hour beside a place by itself. The maintainer's answers of 2026-11-02: OPEN-1 yes ("quinta que vem" on
a card is the model's reading, the person sees the full date on the new card before approving) and OPEN-2 yes (a weekday alone is taken only 1 to 14 days ahead; a clock the engine reads is the engine's; an
hour alone keeps the card's day; relative moves stay asked). Here `read_answer` is pure, with the recorded answers copied as texts, and one flow on the real calendar world of test_event_revise_flow.py with a
stand-in model. What a real model answers is measured elsewhere, never here. Every name is invented.

Held here:
  * each line that changes gives the start, end, title and place stated in its row; the recorded answers of both routes stand for the four lines of the blind set;
  * each line that stays asked stays a clarify and no part changes;
  * the engine's plain reading wins ("passa para quinta" with a model date of another Thursday gives the engine's date, source "code");
  * the change is for a card only: `ops_interpret.decide` on "quinta que vem as 15h30" with no card still asks;
  * the flow: one new card with both parts, the old card ended, nothing written to a calendar, the gate passes with origin `time-model`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_card_day_model.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st
import test_event_lookup as tel
from test_calendar_write import fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import op_text  # noqa: F401
from test_event_revise_flow import body, build, card_has, create, fresh, open_cards, revise, status  # noqa: F401  (`fresh` is autouse)

event_revise = st.load("ops_event_revise")
interpreter = st.load("interpreter")
ops_interpret = st.load("ops_interpret")
turn_gate = st.load("turn_gate")


def clock(year, month, day, hour, minute, offset):
    return datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone(datetime.timedelta(hours=offset)))


NEW_YORK, BERLIN, SAO_PAULO = ("America/New_York", clock(2026, 11, 3, 9, 30, -5)), ("Europe/Berlin", clock(2026, 11, 3, 9, 30, 1)), ("America/Sao_Paulo", clock(2026, 11, 3, 9, 30, -3))
WEDNESDAY = ("America/Sao_Paulo", clock(2026, 10, 21, 15, 0, -3))      # the clock of the calendar world of the flow tests
THURSDAY_CARD = {"title": "Consulta", "start": "2026-10-22T16:00", "end": "2026-10-22T17:00"}      # the Thursday after WEDNESDAY, at 16:00
ONLY = {"event-change"}


def read(line, card, where, slots, iso, weekday, op="event-change", allowed=ONLY):
    """The decision for a model that answers `op` with `slots`, the start `iso` and its `weekday` to `line`, on the card `card`, at the clock `where`."""
    doc = {"event": dict(card), "operation": "create", "account": "google", "before": None}
    zone, now = where
    return event_revise.read_answer(op_text(op, slots, time_iso=iso, weekday=weekday), line, doc, now, zone, set(allowed))


def recorded(text, line, card, where):
    """The decision for a recorded text of the model (both routes gave these four, in both runs)."""
    doc = {"event": dict(card), "operation": "create", "account": "google", "before": None}
    zone, now = where
    return event_revise.read_answer(text, line, doc, now, zone, ONLY)


def asked(got):
    """True when the line stays asked: a clarify of the time, or any clarify, and nothing of the model's start taken."""
    return got["kind"] == "clarify" and not got.get("time")


def taken(got, local, **parts):
    """True when the decision is a change of the event with the model's start `local` and exactly the parts `parts` (no origin keys)."""
    kept = {key: value for key, value in (got.get("parts") or {}).items() if not key.endswith("_origin")}
    return got["kind"] == "op" and got["op"] == "event-change" and got["time"] == {"local": local, "source": "model"} and kept == parts


# --- 1. the recorded answers of 2026-11-01 -----------------------------------------------------------------------------------------------------------------


CB_16 = '{"v":1,"kind":"op","op":"event-change","slots":{"time":"next tuesday"},"time_iso":"2026-11-10T17:00","weekday":"tue"}'
CB_18 = '{"v":1,"kind":"op","op":"event-change","slots":{"time":"donnerstag"},"time_iso":"2026-11-05T11:00","weekday":"thu"}'
CB_27 = '{"v":1,"kind":"op","op":"event-change","slots":{"time":"15h","place":"Bistro Lima"},"time_iso":"2026-11-05T15:00","weekday":"thu"}'
CB_28 = '{"v":1,"kind":"op","op":"event-change","slots":{"title":"Anniversary dinner","time":"8pm"},"time_iso":"2026-11-07T20:00","weekday":"sat"}'


def test_the_four_recorded_answers_of_the_blind_set_change_the_card():
    got = recorded(CB_16, "move this to next tuesday", {"title": "Haircut", "location": "Fade Street Barbers", "start": "2026-11-04T17:00", "end": "2026-11-04T17:45"}, NEW_YORK)
    assert taken(got, "2026-11-10T17:00"), got
    got = recorded(CB_18, "kannst du das auf donnerstag verschieben", {"title": "Zahnarzt", "start": "2026-11-06T11:00", "end": "2026-11-06T11:30"}, BERLIN)      # validate: allow english-only -- the line under test
    assert taken(got, "2026-11-05T11:00"), got
    got = recorded(CB_27, "passa pras 15h e muda o local pro Bistro Lima", {"title": "Reuniao com a Bia", "location": "Sala 3", "start": "2026-11-05T10:00", "end": "2026-11-05T11:00"}, SAO_PAULO)      # validate: allow english-only -- the line under test
    assert taken(got, "2026-11-05T15:00", place="Bistro Lima"), got
    got = recorded(CB_28, "call it Anniversary dinner and make it 8pm", {"title": "Dinner", "start": "2026-11-07T19:00", "end": "2026-11-07T21:00"}, NEW_YORK)
    assert taken(got, "2026-11-07T20:00", title="Anniversary dinner"), got


def test_the_new_start_keeps_the_length_of_the_card_in_the_card_that_opens_it():
    """The decision carries only the start; the end is the card's length from it (the operation that opens the new card does it, see the flow test)."""
    got = read("passa pra quinta que vem", THURSDAY_CARD, WEDNESDAY, {"time": "quinta que vem"}, "2026-10-29T16:00", "thu")      # validate: allow english-only -- the line under test
    assert taken(got, "2026-10-29T16:00") and "end" not in got["time"], got


# --- 2. the phone rows -------------------------------------------------------------------------------------------------------------------------------------


NEXT_THURSDAY_CARD = {"title": "Consulta", "start": "2026-10-29T16:00", "end": "2026-10-29T17:00"}


@pytest.mark.parametrize("line, slots, iso, parts", [
    ("passa pra quinta que vem", {"time": "quinta que vem"}, "2026-10-29T16:00", {}),      # validate: allow english-only -- the phone line, Portuguese
    ("passa pra quinta que vem as 15h", {"time": "quinta que vem as 15h"}, "2026-10-29T15:00", {}),      # validate: allow english-only -- the line under test
    ("muda o nome pra corte e passa pra quinta que vem", {"title": "corte", "time": "quinta que vem"}, "2026-10-29T16:00", {"title": "corte"}),      # validate: allow english-only -- the line under test
])
def test_next_weeks_thursday_on_a_card_is_the_models_reading(line, slots, iso, parts):
    assert taken(read(line, THURSDAY_CARD, WEDNESDAY, slots, iso, "thu"), iso, **parts)


def test_an_hour_beside_a_place_keeps_the_cards_day_and_takes_both():
    got = read("passa pras 15h e muda o local pro Bistro Exemplo", NEXT_THURSDAY_CARD, WEDNESDAY, {"time": "15h", "place": "Bistro Exemplo"}, "2026-10-29T15:00", "thu")      # validate: allow english-only -- the phone line
    assert taken(got, "2026-10-29T15:00", place="Bistro Exemplo"), got


# --- 3. what stays asked -----------------------------------------------------------------------------------------------------------------------------------


NEXT = "passa pra quinta que vem"      # validate: allow english-only -- the line under test
SLOT = {"time": "quinta que vem"}
HOUR_LINE = "passa pras 15h e muda o local pro Bistro Exemplo"      # validate: allow english-only -- the line under test
HOUR_SLOTS = {"time": "15h", "place": "Bistro Exemplo"}


def test_a_move_counted_from_the_event_stays_asked():
    """cb-11: "atrasa meia hr" is an offset, the asked limit of the card-model spec: the model's start is not taken."""
    got = read("atrasa meia hr", THURSDAY_CARD, WEDNESDAY, {"time": "meia hr"}, "2026-10-22T16:30", "thu")      # validate: allow english-only -- the line under test
    assert asked(got) and got["why"] == "time-ask", got


@pytest.mark.parametrize("name, args", [
    ("a wrong weekday label", (NEXT, SLOT, "2026-10-29T16:00", "fri")),
    ("a date whose weekday is not the span's", (NEXT, SLOT, "2026-10-30T16:00", "fri")),
    ("a date beyond 14 days", (NEXT, SLOT, "2026-11-12T16:00", "thu")),
    ("a date in the past", (NEXT, SLOT, "2026-10-15T16:00", "thu")),
    ("an invented hour on a day-alone line", (NEXT, SLOT, "2026-10-29T09:00", "thu")),
    ("an hour other than the engine's", (HOUR_LINE, HOUR_SLOTS, "2026-10-22T16:00", "thu")),
    ("a different day on an hour-alone line", (HOUR_LINE, HOUR_SLOTS, "2026-10-23T15:00", "fri")),
    ("another event as target", (NEXT, {"time": "quinta que vem", "target": "Dentista"}, "2026-10-29T16:00", "thu")),
    ("a span that is not in the line", (NEXT, {"time": "sexta que vem"}, "2026-10-29T16:00", "thu")),
])
def test_an_answer_that_fails_a_check_stays_asked_and_no_part_changes(name, args):
    line, slots, iso, weekday = args
    got = read(line, THURSDAY_CARD, WEDNESDAY, slots, iso, weekday)
    assert asked(got) and not got.get("parts"), (name, got)


def test_today_is_asked():
    got = read("passa pra quarta que vem", THURSDAY_CARD, WEDNESDAY, {"time": "quarta que vem"}, "2026-10-21T16:00", "wed")      # validate: allow english-only -- the line under test
    assert asked(got), got


def test_a_card_that_is_not_a_plain_start_is_asked():
    """An all-day card has no hour to keep (form)."""
    got = read(NEXT, {"title": "Consulta", "start": "2026-10-22", "end": "2026-10-23"}, WEDNESDAY, SLOT, "2026-10-29T16:00", "thu")
    assert asked(got), got


def test_another_operation_is_not_a_change_of_the_card():
    got = read(NEXT, THURSDAY_CARD, WEDNESDAY, {"text": "x", "when": "quinta que vem"}, "2026-10-29T16:00", "thu", op="remind", allowed={"event-change", "remind"})
    assert got["kind"] == "clarify" and not got.get("time"), got


def test_every_question_about_the_time_but_time_ask_stays_as_it_is(monkeypatch):
    """`time-past`, `time-far`, `time-gap`, `time-fold` and `weekday` are not the model's to settle: `_model_time` is called only for `time-ask`."""
    called = []
    monkeypatch.setattr(event_revise, "_model_time", lambda *a, **k: called.append(a) or {"local": "2026-10-29T16:00", "source": "model"})
    other = {"kind": "clarify", "error": None, "why": "time-past", "slot": "time", "ops": None}
    monkeypatch.setattr(interpreter, "check", lambda *a, **k: other)
    got = read(NEXT, THURSDAY_CARD, WEDNESDAY, SLOT, "2026-10-29T16:00", "thu")
    assert got["kind"] == "clarify" and got["why"] == "time-past" and not called, (got, called)


# --- 4. the engine's reading wins; the card is the only place ----------------------------------------------------------------------------------------------


def test_the_engines_plain_reading_wins_over_the_models_date():
    got = read("passa para quinta", THURSDAY_CARD, WEDNESDAY, {"time": "quinta"}, "2026-11-05T16:00", "thu")      # validate: allow english-only -- the line under test
    assert got["kind"] == "op" and got["time"]["source"] == "code" and got["time"]["local"] == "2026-10-22T16:00", got
    got = read("passa para dia 29", THURSDAY_CARD, WEDNESDAY, {"time": "dia 29"}, "2026-10-30T16:00", "fri")      # validate: allow english-only -- the line under test
    assert got["time"] == {"local": "2026-10-29T16:00", "source": "code"}, got


def test_a_line_with_no_card_still_asks():
    """The case of runtime/tests/natural_cases_pt_br.py:76: "quinta que vem" is doubted by the engine for any line, and only a card takes the model's reading."""
    zone, now = WEDNESDAY
    text = op_text("event-create", {"title": "consulta", "time": "quinta que vem as 15h30"}, time_iso="2026-10-29T15:30", weekday="thu")
    got = ops_interpret.decide("marca consulta quinta que vem as 15h30", text, now, zone, {"event-create"})      # validate: allow english-only -- the line under test
    assert got["kind"] == "clarify" and got["why"] == "time-ask", got


# --- 5. the flow -------------------------------------------------------------------------------------------------------------------------------------------


def test_an_hour_and_a_place_in_one_line_open_one_new_card_with_both_and_write_nothing(world, monkeypatch):
    """The world's clock is Wednesday 2026-10-21 15:00; the card is Saturday 2026-10-24 08:00-09:00 and "passa pras 15h e muda o local pro Bistro Exemplo" is asked by the checks (an hour beside a part)."""
    build(world, monkeypatch, op_text("event-change", HOUR_SLOTS, time_iso="2026-10-24T15:00", weekday="sat"))
    old, sha = create(world)
    seen, real = [], turn_gate.provenance
    monkeypatch.setattr(turn_gate, "provenance", lambda op, args, origins: seen.append((op, dict(origins))) or real(op, args, origins))
    got = revise(world, old, sha, HOUR_LINE)
    new = got["resend"]
    assert isinstance(new, int) and new != old and open_cards(world) == [new] and status(world, old) != "open", got
    lines = body(world, new)
    assert card_has(lines, "CARD_CAL_WHEN", when="Sat 24/10/2026 15:00-16:00 (America/Sao_Paulo)") and card_has(lines, "CARD_CAL_WHERE", location="Bistro Exemplo")
    assert card_has(lines, "CARD_CAL_TITLE", title="evento social")
    assert len(seen) == 1 and seen[0][1]["start"] == "time-model" and seen[0][1]["end"] == "time-model" and seen[0][1]["location"] == "line-span", ("the gate passes with the model's origin", seen)
    assert not {task["state"] for task in rows(world)[0]} & {"running", "done"}, "nothing ran and nothing is written to a calendar: the new card waits for its own approval"


def test_next_weeks_thursday_opens_a_card_with_the_cards_hour(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"time": "quinta que vem"}, time_iso="2026-10-29T08:00", weekday="thu"))      # the card is at 08:00
    old, sha = create(world)
    new = revise(world, old, sha, NEXT)["resend"]
    assert new != old and card_has(body(world, new), "CARD_CAL_WHEN", when="Thu 29/10/2026 08:00-09:00 (America/Sao_Paulo)")


def test_a_start_that_fails_a_check_sends_the_old_card_again(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"time": "quinta que vem"}, time_iso="2026-10-29T09:00", weekday="thu"))      # an invented hour
    old, sha = create(world)
    got = revise(world, old, sha, NEXT)
    assert got["resend"] == old and got["say"] and open_cards(world) == [old] and status(world, old) == "open"

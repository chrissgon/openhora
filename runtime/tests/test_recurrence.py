"""A daily or weekly series made by a line or a typed command, and what the platform never does with a repetition it cannot read (package CB-7, runtime/recurrence.py,
runtime/registry/recurrence_words.json, runtime/ops_interpret.py `_repeat`, runtime/interpreter.py, runtime/step_calendar_event.py, runtime/calendar_document.py; limits L54, L55, L57, L61).

The rule (the maintainer, 2026-10-26 and 2026-10-27): "toda segunda às 7h" is a weekly card or an honest sentence, NEVER one event with the words in its title; a repetition is read by code from
closed words (the model may only name the span of the line that holds it), a weekly one is on the weekday of the start, a series has no end, and a line in a language this file cannot read
is told so. Part 1 holds the closed lists and their readings with the test's own literals (pt-BR and en); part 2 the guard through the real seam and the real card, at catalog version 1
(the model cannot give `repeat`: the line gets the sentence) and 2 (it can); part 3 the typed command, the document and the requests the writers receive. Each oracle that can pass wrongly has
a vacuity case that plants the wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_recurrence.py
"""
from __future__ import annotations

import copy
import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest

import standin_tree as st
from test_calendar_write import approve, rows, world  # noqa: F401  (the calendar world)
from test_series_cancel import EVENTS, GRAPH_EVENTS, OWNER, ZONE, clock_and_snapshots, configure, nothing_started, op_text, text_of  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
interpreter = st.load("interpreter")
interpreter_catalog = st.load("interpreter_catalog")
natural = st.load("natural")
recurrence = st.load("recurrence")
registry_data = st.load("registry_data")
calendar_document = st.load("calendar_document")
step_calendar_event = st.load("step_calendar_event")
turn_gate = st.load("turn_gate")
effects = st.load("effects")
ops_event_revise = st.load("ops_event_revise")

MON, TUE, WED = 0, 1, 2      # datetime.weekday() of the start of the readings below


# --- 1. the closed lists and what they read ---------------------------------------------------------------------------------------------------------


READ = [
    # (text, the weekday of the start, the reading)
    ("toda segunda às 7h", MON, {"freq": "weekly", "byday": "MO"}),      # validate: allow english-only -- the Portuguese lines under test
    ("todas as segundas", MON, {"freq": "weekly", "byday": "MO"}),
    ("toda terça-feira", TUE, {"freq": "weekly", "byday": "TU"}),      # validate: allow english-only -- the Portuguese lines under test
    ("todo domingo", 6, {"freq": "weekly", "byday": "SU"}),
    ("todo dia", WED, {"freq": "daily"}),
    ("todos os dias às 7h", MON, {"freq": "daily"}),      # validate: allow english-only -- the Portuguese lines under test
    ("diariamente", MON, {"freq": "daily"}),
    ("toda semana", WED, {"freq": "weekly", "byday": "WE"}),
    ("semanalmente", TUE, {"freq": "weekly", "byday": "TU"}),
    ("every Monday at 7am", MON, {"freq": "weekly", "byday": "MO"}),
    ("every day", TUE, {"freq": "daily"}),
    ("daily", MON, {"freq": "daily"}),
    ("every week", WED, {"freq": "weekly", "byday": "WE"}),
    ("Mondays", MON, {"freq": "weekly", "byday": "MO"}),
    # a repetition that is not read
    ("toda segunda às 7h", TUE, None),      # validate: allow english-only -- the Portuguese lines under test; a weekday that is not the start's
    ("every Monday", WED, None),
    ("toda segunda e quarta", MON, None),      # two weekdays
    ("every Monday and Wednesday", MON, None),
    ("a cada 2 dias", MON, None),      # an interval
    ("every 2 weeks", MON, None),
    ("every other day", MON, None),
    ("todo mês", MON, None),      # validate: allow english-only -- the Portuguese lines under test; monthly
    ("mensalmente", MON, None),
    ("monthly", MON, None),
    ("dias úteis", MON, None),      # validate: allow english-only -- the Portuguese lines under test
    ("weekdays", MON, None),
    ("todo dia 16", MON, None),      # the sixteenth of every month, not every day
    ("toda segunda até dezembro", MON, None),      # validate: allow english-only -- the Portuguese lines under test; an end
    ("every day until June", MON, None),
    ("toda segunda por 3 semanas", MON, None),
    ("every Monday for 4 weeks", MON, None),
    ("todo dia 3 vezes", MON, None),
    ("segunda às 7h", MON, None),      # a bare weekday is no repetition
    ("at 7am", MON, None),
    ("", MON, None),
]


@pytest.mark.parametrize("text,weekday,reading", READ)
def test_read_is_the_closed_reading_or_none(text, weekday, reading):
    assert recurrence.read(text, weekday) == reading, text


def test_read_refuses_a_start_that_is_not_a_weekday_number():
    for bad in (None, 7, -1, True, "0"):
        assert recurrence.read("toda segunda", bad) is None, bad


MENTIONS = [
    ("marca academia teste toda segunda às 7h", True), ("todo dia às 7h", True), ("todos os dias", True), ("every Monday at 7am", True), ("weekly", True), ("as segundas", True),      # validate: allow english-only -- the Portuguese lines under test
    ("todo mês", True), ("a cada 2 dias", True), ("dias úteis", True), ("every other day", True), ("every 2 weeks", True), ("monthly", True), ("mondays", True), ("todo dia 16", True),      # validate: allow english-only -- the Portuguese lines under test
    ("marca dentista segunda às 10h", False), ("marca reunião quinta que vem", False), ("remind me tomorrow at 9am", False), ("academia", False), ("", False),      # validate: allow english-only -- the Portuguese lines under test
]


@pytest.mark.parametrize("text,expected", MENTIONS)
def test_mentions_is_true_for_any_repetition_phrase_supported_or_not_and_false_for_a_one_off(text, expected):
    assert recurrence.mentions(text) is expected, text


def test_mentions_is_also_true_when_the_time_engine_says_the_line_repeats(monkeypatch):
    """The amendment of 2026-10-27 (OPEN-TT-7): `natural_time.recurring` counts, so a language the closed lists do not hold is still caught; vacuity: with the engine silent the line is not."""
    line = "cada lunes a las 7"      # validate: allow english-only -- a line in a language the lists do not hold
    monkeypatch.setattr(recurrence.nt, "recurring", lambda text, languages=None: True)
    assert recurrence.mentions(line) is True
    monkeypatch.setattr(recurrence.nt, "recurring", lambda text, languages=None: False)
    assert recurrence.mentions(line) is False, "vacuity: the closed lists alone do not know this line"
    assert recurrence.read(line, MON) is None, "and a line in such a language is never READ as a series (OPEN-CB-15)"


WHICH = [
    # (line, names a date, the answer)
    ("cancela a série academia teste", False, "series"), ("cancela todas as academias", False, "series"), ("cancela de vez a academia teste", False, "series"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela a academia teste toda segunda", False, "series"), ("cancel the whole series", False, "series"), ("cancel all the gym classes", False, "series"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela só a academia da próxima segunda", True, "occurrence"), ("cancela a academia de amanhã", True, "occurrence"), ("cancela a academia dessa semana", False, "occurrence"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela só essa vez da academia", False, "occurrence"), ("cancel only this time", False, "occurrence"), ("cancel the gym on 16/11", True, "occurrence"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela a academia teste", False, "ask"), ("cancela a academia de segunda", False, "ask"), ("cancela só a série toda", False, "ask"),      # validate: allow english-only -- the Portuguese lines under test
    ("cancela todas as academias de 16/11", True, "ask"), ("cancel only the whole series", False, "ask"), ("cancel the gym", False, "ask"),      # validate: allow english-only -- the Portuguese lines under test
]


@pytest.mark.parametrize("line,date,answer", WHICH)
def test_which_decides_by_closed_words_and_asks_when_unclear(line, date, answer):
    assert recurrence.which(line, date) == answer, line


def test_week_range_and_strip():
    assert recurrence.week_range("cancela a academia dessa semana") and recurrence.week_range("cancel the gym this week") and not recurrence.week_range("cancela a academia de segunda")      # validate: allow english-only -- the Portuguese lines under test
    for text, left in (("toda segunda às 7h", "segunda às 7h"), ("todo dia às 7h", "às 7h"), ("todos os dias às 7h", "às 7h"), ("every Monday at 7am", "Monday at 7am"),      # validate: allow english-only -- the Portuguese lines under test
                       ("toda semana às 7h", "às 7h"), ("segunda às 7h", "segunda às 7h"), ("marca academia teste toda segunda às 7h", "marca academia teste segunda às 7h")):      # validate: allow english-only -- the Portuguese lines under test
        assert recurrence.strip(text) == left, text
    assert recurrence.rule_word({"freq": "daily"}) == "daily" and recurrence.rule_word({"freq": "weekly", "byday": "TH"}) == "weekly:TH"
    with pytest.raises(ValueError):
        recurrence.rule_word({"freq": "weekly", "byday": "XX"})


def test_vacuity_a_reader_that_skips_the_weekday_check_reads_a_monday_series_for_a_tuesday_start(monkeypatch):
    assert recurrence.read("toda segunda às 7h", TUE) is None      # validate: allow english-only -- the Portuguese line under test
    monkeypatch.setattr(recurrence, "WEEKDAYS", ("MO",) * 7)      # a wrong table planted: every start is a Monday
    assert recurrence.read("toda segunda às 7h", TUE) == {"freq": "weekly", "byday": "MO"}, "the oracle can fail"      # validate: allow english-only -- the Portuguese line under test


def test_the_registry_file_is_well_formed_and_a_planted_defect_is_reported(tmp_path, monkeypatch):
    assert registry_data.problems("recurrence_words") == []
    assert subprocess.run([sys.executable, str(REPO / "runtime/registry_data.py"), "--check"], capture_output=True, text=True).returncode == 0
    real = json.loads((REPO / "runtime/registry/recurrence_words.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(registry_data, "FOLDER", str(tmp_path))
    for defect, why in ((lambda d: d["daily"].append("Zebra"), "not a list of folded"), (lambda d: d["end"].reverse(), "not sorted"), (lambda d: d["weekly_lead"].append("toda"), "repeated"),
                        (lambda d: d["weekdays"]["TU"].append("segunda"), "two weekdays"), (lambda d: d.pop("series"), "the keys are not"), (lambda d: d["weekdays"].pop("SU"), "not exactly"),
                        (lambda d: d.update(v=2), "v is 2")):
        broken = copy.deepcopy(real)
        defect(broken)
        for name in registry_data.FILES.values():
            (tmp_path / name).write_text((REPO / "runtime/registry" / name).read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / "recurrence_words.json").write_text(json.dumps(broken), encoding="utf-8")
        assert any(why in problem for problem in registry_data.problems("recurrence_words")), why


# --- 2. the guard: a repetition the line says and code cannot read opens no event ---------------------------------------------------------------------


@pytest.fixture
def v2(monkeypatch):
    """The catalog of version 2 and the views over it: what a line reaches after the flip, which CB-9 alone makes (`LINE_CATALOG` is 1)."""
    classes, table = natural.views(2)
    monkeypatch.setattr(natural, "CLASSES", classes)
    monkeypatch.setattr(natural, "NATURAL", table)
    catalog = interpreter_catalog.generate(2)
    monkeypatch.setattr(interpreter, "SERVED_SHA256", interpreter.catalog_sha256(catalog))
    return catalog


def create_decision(line, slots, catalog=None, time_iso="2026-11-09T07:00", weekday="mon", now=None):
    obj = {"v": 1, "kind": "op", "op": "event-create", "slots": slots, "time_iso": time_iso, "weekday": weekday}
    served = catalog if catalog is not None else interpreter.SERVED
    return interpreter.check(obj, line, None, served, now or ops_natural._clock(), ZONE, frozenset(("event-create",)))


def carry(world, decision, line):
    ctx = ops_core.context(world["path"])
    extras = {}
    with turn_gate.turn():
        got = ops_interpret._carry_out(world["path"], ctx, decision, line, OWNER, extras)
    return got[0], extras


LINE = "marca academia teste toda segunda às 7h"      # validate: allow english-only -- the Portuguese line under test
ON_GOOGLE = "marca academia teste toda segunda às 7h no google"      # validate: allow english-only -- the Portuguese line under test: the world has two accounts, and a line that names none is asked which


def test_at_version_1_a_line_with_toda_segunda_gets_the_sentence_and_no_event_card(world, monkeypatch):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    decision = create_decision(LINE, {"title": "academia teste", "time": "toda segunda às 7h"})
    assert decision["kind"] == "op" and decision["time"]["source"] == "code" and decision["time"]["local"] == "2026-11-09T07:00", decision
    reply, extras = carry(world, decision, LINE)
    assert reply == text_of("RECUR_NOT_READ") and nothing_started(world) and "resend" not in extras, "the answer names only a title and a time: the repetition is not read, so no card of one event"
    assert reply == "Ainda não consigo marcar eventos que se repetem assim. Consigo todo dia ou toda semana (ex.: “toda segunda às 7h”)."      # validate: allow english-only -- the Portuguese sentence under test


def test_vacuity_with_the_guard_taken_out_one_event_opens_with_the_words_in_its_title(world, monkeypatch):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_interpret, "_repeat", lambda decision, said, time_: (None, True))      # the guard removed in a copy: the oracle above must fail on it
    decision = create_decision(ON_GOOGLE, {"title": "academia teste toda segunda", "time": "toda segunda às 7h", "service": "google"})      # validate: allow english-only -- the Portuguese words under test
    reply, extras = carry(world, decision, ON_GOOGLE)
    body = ops.pending(world["path"], extras["resend"])["body"].splitlines()
    assert reply == text_of("ACCT_CARD_SENT", pending=1) and "Title: academia teste toda segunda" in body and not [l for l in body if l.startswith("Repeats:")], "one event, the words in its title"      # validate: allow english-only -- the Portuguese words under test


CODE = {"local": "2026-11-09T07:00", "source": "code"}      # a Monday: the first occurrence the time engine reads for "toda segunda às 7h" on Tuesday 2026-11-03
REPEATS = [
    # (name, line, the spans the check verified, the time, the expected answer of `_repeat`)
    ("span", LINE, {"title": "academia teste", "time": "segunda às 7h", "repeat": "toda segunda"}, CODE, ("weekly", True)),      # validate: allow english-only -- the Portuguese words under test
    ("span with the time", LINE, {"title": "academia teste", "time": "toda segunda às 7h", "repeat": "toda segunda"}, CODE, ("weekly", True)),      # validate: allow english-only -- the Portuguese words under test
    ("daily", "marca academia teste todo dia às 7h", {"title": "academia teste", "time": "às 7h", "repeat": "todo dia"}, dict(CODE, local="2026-11-04T07:00"), ("daily", True)),      # validate: allow english-only -- the Portuguese words under test
    ("no span", LINE, {"title": "academia teste", "time": "toda segunda às 7h"}, CODE, (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("a title that says it", LINE, {"title": "academia teste toda segunda", "time": "às 7h", "repeat": "toda segunda"}, CODE, (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("a weekday that is not the start's", LINE, {"title": "academia teste", "time": "toda segunda às 7h", "repeat": "toda segunda"}, dict(CODE, local="2026-11-10T07:00"), (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("a span the line holds more of", "marca academia teste toda segunda e quarta às 7h", {"title": "academia teste", "time": "às 7h", "repeat": "toda segunda"}, CODE, (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("an end the span left out", "marca academia teste toda segunda até dezembro às 7h", {"title": "academia teste", "time": "às 7h", "repeat": "toda segunda"}, CODE, (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("a monthly line", "marca academia teste todo mês às 7h", {"title": "academia teste", "time": "às 7h", "repeat": "todo mês"}, CODE, (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("a plain line", "marca academia teste segunda às 7h", {"title": "academia teste", "time": "segunda às 7h"}, CODE, (None, True)),      # validate: allow english-only -- the Portuguese words under test
    ("a time the model alone read", LINE, {"title": "academia teste", "time": "toda segunda às 7h", "repeat": "toda segunda"}, dict(CODE, source="model"), (None, False)),      # validate: allow english-only -- the Portuguese words under test
    ("no time", LINE, {"title": "academia teste", "repeat": "toda segunda"}, None, (None, False)),      # validate: allow english-only -- the Portuguese words under test
]


@pytest.mark.parametrize("name,line,spans,time_,expected", REPEATS, ids=[r[0] for r in REPEATS])
def test_the_repetition_is_read_only_when_the_model_named_its_span_and_code_reads_the_span_and_the_whole_line_alike(name, line, spans, time_, expected):
    """L54 and L61: the repetition of a new event is the code's reading of closed words, with the engine's time, and never a guess; a line that mentions one and has none read is not understood."""
    assert ops_interpret._repeat({"op": "event-create", "spans": spans}, line, time_) == expected, name


def test_the_weekday_of_a_series_is_the_one_of_the_start_the_engine_read(v2, monkeypatch):
    """The same line through the real check (catalog version 2): the engine reads Monday 09/11 for "toda segunda às 7h" and the series is weekly on Monday."""
    monkeypatch.setattr(ops_natural, "_clock", lambda: datetime.datetime(2026, 11, 3, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3))))
    decision = create_decision(LINE, {"title": "academia teste", "time": "toda segunda às 7h", "repeat": "toda segunda"}, v2)      # validate: allow english-only -- the Portuguese words under test
    assert decision["kind"] == "op" and decision["time"] == CODE and decision["spans"]["repeat"] == "toda segunda"      # validate: allow english-only -- the Portuguese words under test
    assert ops_interpret._repeat(decision, LINE, decision["time"]) == ("weekly", True)


def test_at_version_2_the_span_makes_a_weekly_card_with_the_repetition_in_words_and_the_series_is_written_once_approved(world, monkeypatch, v2):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    decision = create_decision(ON_GOOGLE, {"title": "academia teste", "time": "toda segunda às 7h", "repeat": "toda segunda", "service": "google"}, v2)      # validate: allow english-only -- the Portuguese words under test
    assert decision["kind"] == "op" and decision["spans"]["repeat"] == "toda segunda"      # validate: allow english-only -- the Portuguese words under test
    reply, extras = carry(world, decision, ON_GOOGLE)
    assert reply == text_of("ACCT_CARD_SENT", pending=1), reply
    lines = ops.pending(world["path"], extras["resend"])["body"].splitlines()
    for wanted in ("Title: academia teste", "When: Mon 09/11/2026 07:00-08:00 (America/Sao_Paulo)", "Repeats: every Monday, no end date",
                   "To change the series, use the calendar app; to cancel the whole series, ask here."):
        assert wanted in lines, (wanted, lines)
    assert not [l for l in lines if "toda segunda" in l], "the words of the repetition are not in the title"      # validate: allow english-only -- the Portuguese words under test
    assert world["google"].writes() == []
    assert approve(world, {"pending": extras["resend"]})["task_state"] == "done"
    (_method, path, query, body), = world["google"].writes()
    assert path == EVENTS and body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"] and body["start"]["timeZone"] == ZONE and body["end"]["timeZone"] == ZONE and body["summary"] == "academia teste"


def test_the_model_cannot_give_the_slot_at_version_1(world, monkeypatch):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    decision = create_decision(LINE, {"title": "academia teste", "time": "toda segunda às 7h", "repeat": "toda segunda"})      # validate: allow english-only -- the Portuguese words under test
    assert decision["kind"] == "clarify" and decision["error"] == "E_SLOT_UNKNOWN", "L54: a line reaches the slot only after the flip"


def test_the_time_engine_reads_the_first_occurrence_when_the_recurrence_words_made_it_doubt(monkeypatch):
    """Item 6: the words that only say it repeats are no doubt about the time. `todo dia às 7h` was asked ("what time?"); with the repetition words set aside the engine reads 07:00."""
    now = datetime.datetime(2026, 11, 3, 10, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
    line = "marca academia teste todo dia às 7h"      # validate: allow english-only -- the Portuguese line under test
    obj = {"v": 1, "kind": "op", "op": "event-create", "slots": {"title": "academia teste", "time": "todo dia às 7h"}, "time_iso": "2026-11-04T07:00", "weekday": "wed"}      # validate: allow english-only -- the Portuguese words under test
    got = interpreter.check(obj, line, None, interpreter.SERVED, now, ZONE, frozenset(("event-create",)))
    assert got["kind"] == "op" and got["time"] == {"local": "2026-11-04T07:00", "source": "code"}, got
    monkeypatch.setattr(recurrence, "strip", lambda text: text)      # vacuity: with nothing set aside the engine doubts again
    asked = interpreter.check(obj, line, None, interpreter.SERVED, now, ZONE, frozenset(("event-create",)))
    assert asked["kind"] == "clarify" and asked["why"] == "time-ask", asked


def test_a_line_that_repeats_in_another_language_is_never_read_as_a_series(v2, monkeypatch):
    line = "marca gimnasio cada lunes a las 7"      # validate: allow english-only -- a line in a language the lists do not hold
    monkeypatch.setattr(recurrence.nt, "recurring", lambda text, languages=None: True)      # the engine's tables of that language (TT-1) say it repeats
    decision = {"op": "event-create", "spans": {"title": "gimnasio", "repeat": "cada lunes"}, "time": {"local": "2026-11-09T07:00", "source": "code"}}
    assert ops_interpret._repeat(decision, line, decision["time"]) == (None, False), "a series in es/fr/de/it is the honest sentence until a package reads it (OPEN-CB-15)"
    monkeypatch.setattr(recurrence.nt, "recurring", lambda text, languages=None: False)
    assert ops_interpret._repeat(dict(decision, spans={"title": "gimnasio", "repeat": "cada lunes"}), line, decision["time"]) == (None, False), "nor with the engine silent: a span of a language the lists do not hold reads as nothing"      # validate: allow english-only -- the Spanish words under test


# --- 3. typed, the document, the requests, the gate --------------------------------------------------------------------------------------------


def test_a_typed_weekly_series_is_one_post_with_its_rule_in_the_start_zone_on_google_and_a_pattern_on_outlook(world, monkeypatch):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    started = ops.event_create(world["path"], "google", "Gym", "2026-11-09T07:00", repeat="weekly")
    lines = ops.pending(world["path"], started["pending"])["body"].splitlines()
    assert "Repeats: every Monday, no end date" in lines and lines.index("Repeats: every Monday, no end date") > lines.index("Title: Gym")
    doc = json.loads((Path(ops_steps_dir(world, started)) / "effect.json").read_text(encoding="ascii"))
    assert doc["recurrence"] == {"freq": "weekly", "byday": "MO"} and doc["zone"] == ZONE and "series" not in doc
    assert approve(world, started)["task_state"] == "done"
    (_m, _p, _q, body), = world["google"].writes()
    assert body["recurrence"] == ["RRULE:FREQ=WEEKLY;BYDAY=MO"] and body["start"] == {"dateTime": "2026-11-09T07:00:00-03:00", "timeZone": ZONE}
    daily = ops.event_create(world["path"], "microsoft", "Gym", "2026-11-09T07:00", repeat="daily")
    assert "Repeats: every day, no end date" in ops.pending(world["path"], daily["pending"])["body"].splitlines()
    assert approve(world, daily)["task_state"] == "done"
    sent = [(m, p, b) for m, p, b in ((r["method"], r["path"], r["body"]) for r in world["graph"].graph_requests()) if m == "POST"]
    (_m, path, body), = sent
    assert path == GRAPH_EVENTS and body["recurrence"]["pattern"]["type"] == "daily" and body["recurrence"]["range"]["type"] == "noEnd" and body["recurrence"]["range"]["startDate"] == "2026-11-09"


def ops_steps_dir(world, started):
    step_effects = st.load("ops_step_effects")
    return step_effects.effect_dir(ops_core.context(world["path"])["cfg"], started["task"], 0)


@pytest.mark.parametrize("args,why", [
    ({"start": "2026-11-09", "repeat": "weekly"}, "timed"),      # an all-day event does not repeat
    ({"start": "2026-11-09T07:00", "repeat": "monthly"}, "daily or weekly"),
    ({"start": "2026-11-09T07:00", "repeat": ""}, "daily or weekly"),
])
def test_a_series_is_a_timed_event_and_daily_or_weekly_and_nothing_else(world, monkeypatch, args, why):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    with pytest.raises(ops.OpsError) as refused:
        ops.event_create(world["path"], "google", "Gym", **args)
    assert why in str(refused.value) and rows(world)[1] == []


def test_a_zone_that_is_only_an_offset_makes_no_series(world, monkeypatch):
    configure(world)
    clock_and_snapshots(world, monkeypatch)
    monkeypatch.setattr(calendar_document, "zone_name", lambda: "UTC-03:00")
    with pytest.raises(ops.OpsError) as refused:
        ops.event_create(world["path"], "google", "Gym", "2026-11-09T07:00", repeat="daily")
    assert "named zone" in str(refused.value) and rows(world)[1] == []


EVENT = {"title": "Gym", "all_day": False, "start": "2026-11-09T07:00", "end": "2026-11-09T08:00", "start_at": "2026-11-09T07:00:00-03:00", "end_at": "2026-11-09T08:00:00-03:00",
         "location": "", "reminder_minutes": None, "notes": ""}


def document(**more):
    base = dict(task_id=7, account="google", address="pat@example.com", calendar="personal", calendar_id="pat@example.com", operation="create", zone=ZONE, event=EVENT, dry_run_sha256="a" * 64)
    base.update(more)
    return calendar_document.document(**base)


def cancel_document(operation, **more):
    series = {"id": "master1", "rule": "weekly:MO", "start": None if operation == "cancel-series" else EVENT["start_at"]}
    base = dict(task_id=8, account="google", address="pat@example.com", calendar="personal", calendar_id="pat@example.com", operation=operation, event_id="master1" if operation == "cancel-series"
                else "inst1", base_etag='"e1"', read_at="2026-11-03T13:00:00Z", zone=ZONE, before=EVENT, series=series, asker="terminal", dry_run_sha256="b" * 64)
    base.update(more)
    return calendar_document.document(**base)


def test_a_document_without_a_series_has_the_key_it_always_had():
    """No document changes by a byte for a package that does not use a series: these two keys were computed by the code of commit 6f9df1b4, before any series key existed."""
    assert document()["idempotency_key"] == "cal-c33b934db7a05df5c24c0a943188ac2d"
    plain = dict(task_id=8, account="google", address="pat@example.com", calendar="personal", calendar_id="pat@example.com", operation="cancel", event_id="evabc", base_etag='"e1"',
                 read_at="2026-11-03T13:00:00Z", zone=ZONE, before=EVENT, asker="terminal", dry_run_sha256="b" * 64)
    assert calendar_document.document(**plain)["idempotency_key"] == "cal-e970c5eabdbbeab9008b2b62860b2de4"
    series = document(recurrence={"freq": "weekly", "byday": "MO"})
    assert series["idempotency_key"] != document()["idempotency_key"] and "recurrence" in series, "the repetition is part of the key and of the hash the person approves"
    assert set(document()) == set(calendar_document.KEYS), "and a document without one holds exactly the old keys"


@pytest.mark.parametrize("make,why", [
    (lambda: document(recurrence={"freq": "weekly", "byday": "TU"}), "weekday"),      # the start is a Monday
    (lambda: document(recurrence={"freq": "monthly"}), "daily, or weekly"),
    (lambda: document(recurrence={"freq": "daily", "count": 3}), "daily, or weekly"),
    (lambda: document(recurrence={"freq": "weekly", "byday": "MO", "until": "2026-12-01"}), "daily, or weekly"),
    (lambda: document(recurrence={"freq": "daily"}, zone="UTC-03:00"), "named zone"),
    (lambda: document(recurrence={"freq": "daily"}, event=dict(EVENT, all_day=True, start="2026-11-09", end="2026-11-09", start_at="2026-11-09", end_at="2026-11-10")), "timed event"),
    (lambda: cancel_document("cancel-series", series={"id": "other", "rule": "weekly:MO", "start": None}), "own id"),
    (lambda: cancel_document("cancel-series", series={"id": "master1", "rule": "weekly:MO", "start": EVENT["start_at"]}), "names no start"),
    (lambda: cancel_document("cancel-occurrence", series={"id": "inst1", "rule": "weekly:MO", "start": EVENT["start_at"]}), "occurrence's id"),
    (lambda: cancel_document("cancel-occurrence", series={"id": "master1", "rule": "weekly:MO", "start": "2026-11-09T09:00:00-03:00"}), "instant it starts at"),
    (lambda: cancel_document("cancel-occurrence", series={"id": "master1", "rule": "other", "start": EVENT["start_at"]}), "names the series"),
    (lambda: cancel_document("cancel-occurrence", series=None), "names the series"),
    (lambda: calendar_document.document(task_id=8, account="google", address="pat@example.com", calendar="personal", calendar_id="pat@example.com", operation="cancel", event_id="evabc",
                                        base_etag='"e1"', read_at="2026-11-03T13:00:00Z", zone=ZONE, before=EVENT, series={"id": "evabc", "rule": "daily", "start": None}, asker="terminal",
                                        dry_run_sha256="b" * 64), "only the cancel of a series"),
], ids=["weekday-mismatch", "monthly", "count", "until", "offset-zone", "all-day", "series-id-not-own", "series-start-named", "occurrence-id-is-master", "occurrence-start-moved", "rule-other",
        "no-series", "plain-cancel-with-series"])
def test_the_document_refuses_what_is_not_a_plain_series_or_a_cancel_that_names_one(make, why):
    with pytest.raises(effects.EffectError) as refused:
        make()
    assert why in refused.value.reason, refused.value.reason


def test_the_two_cancel_documents_and_the_create_are_well_formed_and_their_verbs_are_each_writers():
    for account, series_verb in (("google", "event-delete"), ("microsoft", "event-cancel-series")):
        assert calendar_document.VERBS[account]["cancel-series"] == series_verb and calendar_document.VERBS[account]["cancel-occurrence"] == "event-cancel-occurrence"
    whole, one = cancel_document("cancel-series"), cancel_document("cancel-occurrence")
    assert calendar_document.provider_args(whole, None)[-1] == "--series" and calendar_document.verb_of(whole) == "event-delete"
    args = calendar_document.provider_args(one, None)
    assert args[args.index("--series") + 1] == "master1" and args[args.index("--expect-start") + 1] == EVENT["start_at"] and args[args.index("--event") + 1] == "inst1"
    assert calendar_document.spec_of(whole) == {} and calendar_document.spec_of(one) == {}
    created = document(recurrence={"freq": "daily"})
    assert calendar_document.spec_of(created)["recurrence"] == {"freq": "daily"} and calendar_document.spec_of(created)["time_zone"] == ZONE
    assert "recurrence" not in calendar_document.spec_of(document())


def test_the_preview_the_writer_prints_must_be_the_request_and_the_guard_the_document_says(monkeypatch):
    whole, one = cancel_document("cancel-series"), cancel_document("cancel-occurrence")
    google_path = f"/calendar/v3/calendars/pat%40example.com/events/{whole['event_id']}"
    ok_whole = {"method": "DELETE", "path": google_path, "query": {"sendUpdates": "none"}, "headers": {}, "body": None, "verb": "event-delete", "guard": {"series": True}}
    assert step_calendar_event._same(whole, ok_whole) is True
    for wrong in (dict(ok_whole, verb="event-patch"), dict(ok_whole, guard={}), dict(ok_whole, guard={"series": "master1"}), dict(ok_whole, method="PATCH"), dict(ok_whole, path=google_path.replace("master1", "other")),
                  dict(ok_whole, query={})):
        assert step_calendar_event._same(whole, wrong) is False, wrong
    ok_one = {"method": "PATCH", "path": google_path.replace("master1", "inst1"), "query": {"sendUpdates": "none"}, "headers": {}, "body": {"status": "cancelled", "k": cancel_document("cancel-occurrence")["idempotency_key"]},
              "verb": "event-cancel-occurrence", "guard": {"series": "master1", "expect_start": EVENT["start_at"]}}
    assert step_calendar_event._same(one, ok_one) is True
    for wrong in (dict(ok_one, guard={"series": "master1", "expect_start": "2026-11-09T09:00:00-03:00"}), dict(ok_one, guard={"series": "other", "expect_start": EVENT["start_at"]}),
                  dict(ok_one, path=google_path), dict(ok_one, verb="event-delete")):
        assert step_calendar_event._same(one, wrong) is False, wrong
    monkeypatch.setattr(step_calendar_event, "_guard", lambda doc: {})      # vacuity: with the guard not compared the wrong preview is accepted
    assert step_calendar_event._same(whole, dict(ok_whole, guard={})) is True


GOOD = {"account": "google", "title": "Gym", "start": "2026-11-09T07:00"}


def test_the_gate_lets_a_repetition_and_a_cancel_scope_come_only_from_the_engines_words_or_the_card():
    origins = {"account": "config", "title": "line-span", "start": "time-engine"}
    for origin in ("time-engine", "card-copy"):
        assert turn_gate.provenance("event-create", dict(GOOD, repeat="weekly"), dict(origins, repeat=origin)) == [], origin
    for origin in ("time-model", "line-span", "grounded", "picked", "composed", "undeclared"):
        assert turn_gate.provenance("event-create", dict(GOOD, repeat="weekly"), dict(origins, repeat=origin)), origin
    cancel_args, cancel_origins = {"account": "google", "event": "agenda#1"}, {"account": "config", "event": "grounded"}
    for key, value in (("series", True), ("occurrence", "2026-11-16")):
        assert turn_gate.provenance("event-cancel", dict(cancel_args, **{key: value}), dict(cancel_origins, **{key: "time-engine"})) == [], key
        for origin in ("time-model", "line-span", "grounded", "card-copy"):
            assert turn_gate.provenance("event-cancel", dict(cancel_args, **{key: value}), dict(cancel_origins, **{key: origin})), (key, origin)
    assert turn_gate.provenance("event-change", {"account": "google", "event": "agenda#1", "repeat": "weekly"}, {"account": "config", "event": "grounded", "repeat": "time-engine"}), "a change never takes a repetition"


def test_a_waiting_card_of_a_series_that_is_revised_stays_a_series():
    doc = document(recurrence={"freq": "weekly", "byday": "MO"})
    name, args = ops_event_revise._arguments(doc, None, "2026-11-16T07:00", "2026-11-16T08:00", None)
    assert name == "event_create" and args["repeat"] == "weekly"
    name, args = ops_event_revise._arguments(document(), None, "2026-11-16T07:00", "2026-11-16T08:00", None)
    assert args["repeat"] is None, "a plain card is revised as it always was"

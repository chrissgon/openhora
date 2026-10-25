"""A "no" that carries a new detail, said after "Shall I go ahead?" ("Posso?"), is the corrected request: a NEW question, never a run (package BL5B, limits L54, L63 and L65).

The live case (2026-10-25): "mostra minha agenda de hoje" -> "Posso?" -> "Nao, a de amanha" ended in IX_ASK_AGAIN. The protocol allows two shapes for a no on a plan item (an op object, or an
`answer` with `confirm: no`, with or without a slot and a span) and the check believed neither. Now code turns the protocol's own correction shapes into a revised op, which the dispatcher
asks as a new plan: the old plan is gone, the list keeps what the old line said and the new one does not, a number is only ever the one written in the correcting line, a model's yes never runs
anything, and a bare no (or a no that changes nothing) drops the plan as before. A stand-in model and a stand-in clock; every expectation is a literal of this file. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_correction.py
"""
from __future__ import annotations

import datetime

import pytest

from plan_confirm_kit import (OWNER, ok_of, op, ops, ops_core, ops_interpret, ops_natural, ops_say, phrases, plan_confirm, pending_items, question, say, spy_read, text, world, rig)  # noqa: F401

import standin_tree as st

interpreter = st.load("interpreter")
ops_items = st.load("ops_items")
ops_research = st.load("ops_research")
natural_writes = st.load("natural_writes")

TODAY = "2026-10-25 00:50"      # Sunday: the clock of the live retest
FIRST = "mostra minha agenda de hoje"
ACCENTED, PLAIN = "não, a de amanhã", "Nao, a de amanha"      # validate: allow english-only -- the Portuguese line under test
ITEMS_FRAME = 'frame: {"items":[{"age_s":30,"id":"i1","kind":"plan-confirm","need":"confirm","op":"items"}],"last":{"age_s":30,"op":"items","words":{}},"v":1}'
ANSWERS = {      # the three answers a model gives to the correction of a list: the op object, the recorded answer, and the answer with a slot the op lacks
    "op": op("items"),
    "confirm": text("answer", answers_item="i1", confirm="no"),
    "slot": text("answer", answers_item="i1", confirm="no", slot="day", span="amanha"),
}


@pytest.fixture
def typed(rig, monkeypatch):
    """The command a plan hands over once it is confirmed, recorded instead of run."""
    rig.said_commands = []
    monkeypatch.setattr(ops_say, "_say_command", lambda project, ctx, line, channel, line_id, sender=None: rig.said_commands.append(line) or ("COMMAND-REPLY", None, None, False, None))
    return rig


def shown_frame(rig) -> str:
    return next(line for line in rig.calls[-1]["user"].splitlines() if line.startswith("frame: "))


def agenda(rig, day):
    """The question for the agenda of one day, as code writes it."""
    what = phrases.text("UNDERSTOOD_ITEMS_CALENDAR", rig.cfg) + phrases.localize_dates(phrases.text("UNDERSTOOD_ON_DAY", rig.cfg, day=day), rig.cfg)
    return phrases.text("PLAN_HEAD", rig.cfg, what=what) + " " + phrases.text("PLAN_ASK", rig.cfg)


def live(rig):
    return pending_items.find(plan_confirm._key(rig.world["path"], OWNER), "plan-confirm")


def first_plan(rig, line=FIRST):
    rig.world["clock"].set(TODAY)
    out = say(rig, OWNER, line)
    rig.now[0] += 30
    return out


# --- 1. the live shape -------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line", (PLAIN, ACCENTED))
@pytest.mark.parametrize("shape", sorted(ANSWERS))
def test_a_no_with_the_other_day_after_the_agenda_asks_a_new_question_for_the_other_day_and_reads_nothing(rig, line, shape):
    reads = spy_read(rig)
    old = first_plan(rig)
    assert old["reply"] == agenda(rig, "Sun 25/10/2026"), "the first question is the agenda of today"
    rig.says["text"] = ANSWERS[shape]
    out = say(rig, OWNER, line)
    assert shown_frame(rig) == ITEMS_FRAME
    assert out["reply"] == agenda(rig, "Mon 26/10/2026"), "a new question for the agenda of tomorrow: the calendar of the old line is kept, the day is the new one"
    assert reads == [], "nothing was read before the OK"
    assert out["plan_confirm"]["item"] != old["plan_confirm"]["item"] and out["plan_confirm"]["sha256"] != old["plan_confirm"]["sha256"]
    assert live(rig)["id"] == out["plan_confirm"]["item"]
    assert say(rig, OWNER, "sim", plan_ok=ok_of(old))["reply"] == phrases.text("PLAN_GONE", rig.cfg), "the plan that was corrected is gone"
    assert reads == []
    done = say(rig, OWNER, "sim", plan_ok=ok_of(out))
    assert done["reply"] == "READ-REPLY" and len(reads) == 1
    assert reads[0]["args"]["kind"] == "calendar" and reads[0]["args"]["first"] == "2026-10-26" and reads[0]["args"]["last"] == "2026-10-26", "the confirmed plan reads what its question said"


def test_a_correction_that_names_the_other_kind_of_list_changes_the_kind(rig):
    spy_read(rig)
    first_plan(rig)
    rig.says["text"] = ANSWERS["confirm"]
    out = say(rig, OWNER, "não, os e-mails de amanhã")      # validate: allow english-only -- the Portuguese line under test
    what = phrases.text("UNDERSTOOD_ITEMS_MAIL", rig.cfg) + phrases.localize_dates(phrases.text("UNDERSTOOD_ON_DAY", rig.cfg, day="Mon 26/10/2026"), rig.cfg)
    assert out["reply"] == phrases.text("PLAN_HEAD", rig.cfg, what=what) + " " + phrases.text("PLAN_ASK", rig.cfg)


# --- 2. cancel ---------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("answer", (text("answer", answers_item="i1", confirm="no", slot="id", span="4"), op("cancel", {"id": "4"})), ids=("recorded-answer", "op"))
def test_a_no_with_another_number_asks_a_new_question_for_that_number_and_runs_nothing(typed, answer):
    typed.says["text"] = op("cancel", {"id": "3"})
    old = say(typed, OWNER, "quero cancelar o pedido 3")
    assert old["reply"] == question(typed, "UNDERSTOOD_CANCEL", id=3)
    typed.now[0] += 30
    typed.says["text"] = answer
    out = say(typed, OWNER, "não, é o pedido 4")      # validate: allow english-only -- the Portuguese line under test
    assert shown_frame(typed) == 'frame: {"items":[{"age_s":30,"id":"i1","kind":"plan-confirm","need":"confirm","op":"cancel"}],"last":{"age_s":30,"op":"cancel","words":{"id":"3"}},"v":1}'
    assert out["reply"] == question(typed, "UNDERSTOOD_CANCEL", id=4) and typed.said_commands == []
    assert say(typed, OWNER, "sim", plan_ok=ok_of(old))["reply"] == phrases.text("PLAN_GONE", typed.cfg) and typed.said_commands == []
    done = say(typed, OWNER, "sim", plan_ok=ok_of(out))
    assert typed.said_commands == ["/cancel 4"] and done["typed"] == "/cancel 4"


def test_a_number_the_line_does_not_write_is_refused_and_no_plan_is_asked(typed):
    typed.says["text"] = op("cancel", {"id": "3"})
    say(typed, OWNER, "quero cancelar o pedido 3")
    typed.says["text"] = text("answer", answers_item="i1", confirm="no", slot="id", span="5")      # the line writes 4
    out = say(typed, OWNER, "não, é o pedido 4")      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == phrases.text("IX_ASK_AGAIN", typed.cfg) and "plan_confirm" not in out and typed.said_commands == []
    assert ops.plan_live(typed.world["path"], OWNER) is None, "the line asked no new plan: the old one is gone, as before"


# --- 3. research -------------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def searched(rig, monkeypatch):
    rig.runs = []
    monkeypatch.setattr(ops_research, "reply", lambda project, ctx, args, said, channel, sender, extras: rig.runs.append(args) or "SEARCH-REPLY")
    return rig


def research_question(rig, spoken):
    return question(rig, "UNDERSTOOD_RESEARCH", question=spoken, cap=phrases.decimal(f"{rig.cfg['research']['max_cost_usd']:.2f}", rig.cfg))


def test_a_no_with_another_question_asks_a_new_question_with_that_span_and_starts_no_search(searched):
    searched.says["text"] = op("research", {"question": "o tempo em Campinas amanhã"})      # validate: allow english-only -- the Portuguese line under test
    old = say(searched, OWNER, "vai chover? o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert old["reply"] == research_question(searched, "o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    searched.now[0] += 30
    searched.says["text"] = text("answer", answers_item="i1", confirm="no", slot="question", span="o tempo em Jundiaí amanhã")      # validate: allow english-only -- the Portuguese line under test
    out = say(searched, OWNER, "não, pesquisa o tempo em Jundiaí amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert shown_frame(searched) == ('frame: {"items":[{"age_s":30,"id":"i1","kind":"plan-confirm","need":"confirm","op":"research"}],'
                                     '"last":{"age_s":30,"op":"research","words":{"question":"o tempo em Campinas amanhã"}},"v":1}')      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == research_question(searched, "o tempo em Jundiaí amanhã") and searched.runs == []      # validate: allow english-only -- the Portuguese line under test
    assert say(searched, OWNER, "sim", plan_ok=ok_of(old))["reply"] == phrases.text("PLAN_GONE", searched.cfg) and searched.runs == []
    assert say(searched, OWNER, "sim", plan_ok=ok_of(out))["reply"] == "SEARCH-REPLY" and searched.runs == [{"question": "o tempo em Jundiaí amanhã"}]      # validate: allow english-only -- the Portuguese line under test


# --- 4 and 5. never runs; a model's yes never runs ----------------------------------------------------------------------------------------------------


def test_a_models_yes_with_a_slot_and_a_span_still_runs_nothing_and_keeps_the_plan(searched):
    searched.says["text"] = op("research", {"question": "o tempo em Campinas amanhã"})      # validate: allow english-only -- the Portuguese line under test
    old = say(searched, OWNER, "vai chover? o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    searched.says["text"] = text("answer", answers_item="i1", confirm="yes", slot="question", span="o tempo em Jundiaí")
    out = say(searched, OWNER, "sim, o tempo em Jundiaí")
    assert out["reply"] == phrases.text("PLAN_NOT_LAST", searched.cfg) and searched.runs == []
    assert live(searched)["id"] == old["plan_confirm"]["item"]


def test_a_models_yes_to_a_list_is_never_turned_into_a_revised_plan(rig):
    """A yes on a line that carries a day is not the person's yes (code reads it as nothing) and not a correction: asked again, nothing read, no new question."""
    reads = spy_read(rig)
    first_plan(rig)
    rig.says["text"] = text("answer", answers_item="i1", confirm="yes")
    out = say(rig, OWNER, "sim, a de amanha")
    assert out["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg) and "plan_confirm" not in out and reads == []


# --- 6. a no without a new detail drops the plan ------------------------------------------------------------------------------------------------------


def test_a_no_that_holds_no_day_after_a_list_is_asked_again_and_the_plan_is_dropped(rig):
    reads = spy_read(rig)
    first_plan(rig)
    rig.says["text"] = ANSWERS["confirm"]
    out = say(rig, OWNER, "não, obrigado, deixa pra lá então")      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg) and "plan_confirm" not in out and ops.plan_live(rig.world["path"], OWNER) is None and reads == []


def test_a_no_with_the_same_words_changes_nothing_and_drops_the_plan(searched):
    searched.says["text"] = op("research", {"question": "o tempo em Campinas amanhã"})      # validate: allow english-only -- the Portuguese line under test
    say(searched, OWNER, "vai chover? o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    searched.says["text"] = text("answer", answers_item="i1", confirm="no", slot="question", span="o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    out = say(searched, OWNER, "não, o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == phrases.text("PLAN_DROPPED", searched.cfg) and "plan_confirm" not in out and ops.plan_live(searched.world["path"], OWNER) is None and searched.runs == []


def test_a_no_to_a_list_with_the_same_day_changes_nothing_and_drops_the_plan(rig):
    reads = spy_read(rig)
    first_plan(rig)
    rig.says["text"] = ANSWERS["confirm"]
    out = say(rig, OWNER, "não, a de hoje")      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == phrases.text("PLAN_DROPPED", rig.cfg) and ops.plan_live(rig.world["path"], OWNER) is None and reads == []


# --- 7. no number is carried -------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("answer", (text("answer", answers_item="i1", confirm="no", slot="id", span="18"), text("answer", answers_item="i1", confirm="no"),
                                    op("stop-task", {}, inherit={"id": "18"})), ids=("old-number-as-span", "bare-confirm", "inherit-the-number"))
def test_a_correction_that_writes_no_number_never_carries_the_old_one(typed, answer):
    typed.says["text"] = op("stop-task", {"id": "18"})
    old = say(typed, OWNER, "pode parar a tarefa 18")
    assert old["reply"] == question(typed, "UNDERSTOOD_STOP_TASK", id=18)
    typed.now[0] += 30
    typed.says["text"] = answer
    out = say(typed, OWNER, "não, para a outra")      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] != question(typed, "UNDERSTOOD_STOP_TASK", id=18) and typed.said_commands == []
    assert live(typed) is None or live(typed)["state"]["args"] != {"task_id": 18}


# --- 8. the frame ------------------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("shape", sorted(ANSWERS))
def test_the_frame_shown_for_every_shape_holds_only_the_ids_the_op_the_age_and_the_persons_own_words(rig, shape):
    spy_read(rig)
    first_plan(rig)
    rig.says["text"] = ANSWERS[shape]
    say(rig, OWNER, PLAIN)
    lines = rig.calls[-1]["user"].splitlines()
    assert [line.split(":")[0] for line in lines] == ["today", "time", "zone", "frame", "line"]
    assert lines[3] == ITEMS_FRAME, "no word of the old line, no kind, no day, no range: the operation and the age"
    assert lines[4] == "line: " + PLAIN


# --- 9. B.3 alone ------------------------------------------------------------------------------------------------------------------------------------


NOW = datetime.datetime(2026, 10, 25, 0, 50, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
CALENDAR_TODAY = {"kind": "calendar", "first": "2026-10-25", "last": "2026-10-25"}


def test_items_args_takes_the_kind_the_new_line_names_else_the_old_one_and_the_day_the_line_names_else_the_old_one():
    mail = ops_items.items_args("não, os e-mails de amanhã", NOW, CALENDAR_TODAY)      # validate: allow english-only -- the Portuguese line under test
    assert mail["kind"] == "mail" and mail["first"] == "2026-10-26" and mail["last"] == "2026-10-26"
    both = ops_items.items_args(PLAIN, NOW, CALENDAR_TODAY)
    assert both == {"kind": "calendar", "first": "2026-10-26", "last": "2026-10-26"}
    kept = ops_items.items_args("não, os e-mails", NOW, CALENDAR_TODAY)      # validate: allow english-only -- the Portuguese line under test
    assert kept == {"kind": "mail", "first": "2026-10-25", "last": "2026-10-25"}, "a line with no day keeps the old range"
    assert ops_items.items_args("mostra minha agenda", NOW, {"kind": "mail", "account": "google"})["account"] == "google", "the account the old line named is kept"


def test_items_args_with_no_previous_plan_is_what_the_line_alone_gave_before():
    """Vacuity: without a previous plan the kind is `items_kind` (mail by default), the account and the range come from the line, and a line with no noun reads as mail."""
    assert ops_items.items_args(PLAIN, NOW)["kind"] == natural_writes.items_kind(PLAIN) == "mail"
    for line in ("mostra minha agenda de hoje", "mostra minha agenda", "quais os e-mails de amanhã", "mostra os eventos da semana", "mostra tudo"):      # validate: allow english-only -- the Portuguese line under test
        assert ops_items.items_args(line, NOW) == dict({"kind": natural_writes.items_kind(line)}, **ops_items._line_args(line, NOW)), line


def test_items_noun_is_none_when_the_line_names_neither_the_calendar_nor_the_mail():
    assert natural_writes.items_noun("não, a de amanhã") is None and natural_writes.items_noun("mostra minha agenda") == "calendar"      # validate: allow english-only -- the Portuguese line under test
    assert natural_writes.items_noun("os e-mails de ontem") == "mail" and natural_writes.items_noun("the meetings for Friday") == "calendar"


# --- 10. vacuity for B.2 -----------------------------------------------------------------------------------------------------------------------------


def test_vacuity_without_the_plan_correction_the_recorded_answers_end_in_ask_again(rig, monkeypatch, searched):
    """With the conversion switched off, the recorded answers of the live case, of the cancel and of the search give IX_ASK_AGAIN, as they did on 2026-10-25."""
    monkeypatch.setattr(interpreter, "_plan_correction", lambda *args, **kwargs: None)
    spy_read(rig)
    first_plan(rig)
    rig.says["text"] = ANSWERS["confirm"]
    assert say(rig, OWNER, PLAIN)["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg)
    rig.says["text"] = op("research", {"question": "o tempo em Campinas amanhã"})      # validate: allow english-only -- the Portuguese line under test
    say(rig, OWNER, "vai chover? o tempo em Campinas amanhã")      # validate: allow english-only -- the Portuguese line under test
    rig.says["text"] = text("answer", answers_item="i1", confirm="no", slot="question", span="o tempo em Jundiaí amanhã")      # validate: allow english-only -- the Portuguese line under test
    out = say(rig, OWNER, "não, pesquisa o tempo em Jundiaí amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert out["reply"] == phrases.text("PLAN_DROPPED", rig.cfg) or out["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg)
    assert "plan_confirm" not in out, "without the conversion the line asks no new plan"


# --- 11. only a plan item, only a no ---------------------------------------------------------------------------------------------------------------


def _check(obj, line, kind, op_name, words):
    frame = interpreter.typed_frame([{"id": "i1", "kind": kind, "need": "confirm", "op": op_name, "age_s": 5}], {"op": op_name, "own_words": words, "age_s": 5}, {})
    return interpreter.check(obj, line, frame, interpreter.SERVED, NOW, "America/Sao_Paulo", {"research", "items", "cancel", "mail-send"})


def test_the_conversion_is_reached_only_for_a_plan_confirm_item_and_only_for_a_no():
    no = {"v": 1, "kind": "answer", "answers_item": "i1", "confirm": "no", "slot": "question", "span": "o tempo em Jundiaí"}
    line = "não, o tempo em Jundiaí"      # validate: allow english-only -- the Portuguese line under test
    got = _check(no, line, "plan-confirm", "research", {"question": "o tempo em Campinas"})
    assert got["kind"] == "op" and got["corrects"] == "i1" and got["args"] == {"question": "o tempo em Jundiaí"}
    other = _check(no, line, "write-draft", "research", {"question": "o tempo em Campinas"})
    assert other["kind"] == "answer" and "corrects" not in other, "a confirmation of another kind of item is checked as before"
    yes = _check(dict(no, confirm="yes"), "sim, o tempo em Jundiaí", "plan-confirm", "research", {"question": "o tempo em Campinas"})
    assert yes["kind"] == "answer" and "corrects" not in yes, "a yes is never turned into an op"
    bare = _check({"v": 1, "kind": "answer", "answers_item": "i1", "confirm": "no"}, "não", "plan-confirm", "research", {"question": "o tempo em Campinas"})      # validate: allow english-only -- the Portuguese line under test
    assert bare["kind"] == "answer" and bare["confirm"] == "no", "a bare no is a no"


def test_a_corrected_act_never_inherits_the_number_of_the_old_line():
    frame = interpreter.typed_frame([{"id": "i1", "kind": "plan-confirm", "need": "confirm", "op": "cancel", "age_s": 5}], {"op": "cancel", "own_words": {"id": "3"}, "age_s": 5}, {})
    no = {"v": 1, "kind": "answer", "answers_item": "i1", "confirm": "no", "slot": "id", "span": "4"}
    got = interpreter.check(no, "não, é o pedido 4", frame, interpreter.SERVED, NOW, "America/Sao_Paulo", {"cancel"})      # validate: allow english-only -- the Portuguese line under test
    assert got["kind"] == "op" and got["args"] == {"request_id": 4} and got["inherited"] == [], "the number is the one the correcting line writes"
    old = interpreter.check(dict(no, span="3"), "não, é o pedido 4", frame, interpreter.SERVED, NOW, "America/Sao_Paulo", {"cancel"})      # validate: allow english-only -- the Portuguese line under test
    assert old["kind"] == "clarify", "the old number, which the line does not write, is refused"

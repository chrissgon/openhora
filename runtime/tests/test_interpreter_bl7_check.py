"""The check keeps the subject of a message, drops an inherit the line fills, and keeps a corrected read a read (package BL7-1, limits L54, L60, L61, L63 and L65).

Three product gaps of the blind measurement (2026-10-26), all in `runtime/interpreter.py`'s check, which believes nothing the model says until it has been checked against the line:
  gap 1  a message's `target` the model gave as a person only ("Orla Whitcombe") loses the subject the SAME line gives right after it ("about the greenhouse lease"), so grounding picks a message by
         sender alone. Code now widens the target with that subject (`_target_with_subject`): a closed list of subject markers in six languages, a tail that stops at a stop word, a comma, another
         slot, a time phrase or a date, a span of the line that passes the same span check as any other, and one that still names a message. No word comes from a message or from the model.
  gap 3  an `inherit` of a slot the line also fills is dropped and never read: the old value was refused as a whole decision (E_INHERIT) and the person was asked again. The line's value is the only one.
  gap 4  a correction of a READ plan ("nope, I meant my unread emails ...") for which the model named a card of another act, in a line with no head of a write, is the plan's own read, asked as a
         NEW plan (`_read_plan_kept`); a line that asks for an act, or a model that names a write, or a plan that is not a read, keeps today's path. It only turns a card into a read; nothing runs.
Every line, name and expectation is a literal of this file; the names are invented. Vacuity: a helper that returns a word the line lacks is refused by the check, and each guard fails when the
function it guards is made to say yes. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_bl7_check.py
"""
from __future__ import annotations

import pytest

import importlib

import interpreter_kit as kit
import standin_tree as st
from plan_confirm_kit import OWNER, ok_of, op as model_op, ops, ops_say, phrases, pending_items, say, text, world, rig  # noqa: F401  (the real-operations world, the model stood in)

interp = st.load("interpreter")
ops_natural_mail = st.load("ops_natural_mail")
mail_words = importlib.import_module("natural_writes_mail")
natural = kit.natural


def run(obj, line, frame=None, allowed=None):
    return interp.check(obj, line, frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS if allowed is None else allowed)


def op(name, slots=None, **more):
    return {"v": 1, "kind": "op", "op": name, "slots": slots or {}, **more}


def invalid(decision, code):
    assert decision["kind"] == "clarify" and decision["why"] == "invalid" and decision["error"] == code, decision


def plan_frame(plan_op, words=None, kind="plan-confirm"):
    """A frame holding one live item of `kind` for `plan_op`, and the sender's last request of that operation."""
    item = {"id": "i1", "kind": kind, "need": "confirm" if kind == "plan-confirm" else "text", "age_s": 25}
    if kind == "plan-confirm":
        item["op"] = plan_op
    return {"v": 1, "items": [item], "last": {"op": plan_op, "words": words or {}, "age_s": 25}}


# --- 1. gap 1: the line's subject stays in a message's target -----------------------------------------------------------------------------------------

BLIND_SHAPES = (      # (operation, the line, the slots the model gave, the target the check must give): three languages, three operations; each wider target is a piece of the line
    ("mail-reply", "reply to Orla Whitcombe about the greenhouse lease and say we accept", {"target": "Orla Whitcombe", "body": "we accept"}, "Orla Whitcombe about the greenhouse lease"),
    ("mail-reply", "responde ao Tiago Valente sobre o orçamento do forro dizendo que aceito", {"target": "Tiago Valente", "body": "que aceito"}, "Tiago Valente sobre o orçamento do forro"),      # validate: allow english-only -- the Portuguese line under test
    ("mail-trash", "apaga o e-mail da Loja Mar Azul sobre a promoção de inverno", {"target": "Loja Mar Azul"}, "Loja Mar Azul sobre a promoção de inverno"),      # validate: allow english-only -- the Portuguese line under test
)


def widened(operation, line, slots):
    got = run(op(operation, slots), line)
    assert got["kind"] == "op", got
    return got


def test_the_subject_the_line_gives_after_the_target_stays_in_it():
    for operation, line, slots, wider in BLIND_SHAPES:
        got = widened(operation, line, slots)
        assert got["spans"]["target"] == wider and got["args"]["target"] == wider, (line, got)
        assert wider in line and wider.startswith(slots["target"]), "a piece of the line, and it starts with the model's own target"
        assert got["inherited"] == [] and got["time"] is None


def test_the_other_slots_of_the_decision_are_the_models_unchanged():
    got = widened("mail-reply", *BLIND_SHAPES[0][1:3])
    assert got["spans"]["body"] == "we accept" and got["args"]["text"] == "we accept" and got["op"] == "mail-reply"


@pytest.mark.parametrize("operation", ("mail-reply", "mail-draft", "mail-archive", "mail-trash", "mail-move", "mail-mark"))
def test_every_operation_that_names_a_message_by_its_target_is_widened(operation):
    got = run(op(operation, {"target": "Orla Whitcombe"}), "do it for Orla Whitcombe about the greenhouse lease")
    assert got["kind"] == "op" and got["spans"]["target"] == "Orla Whitcombe about the greenhouse lease", got


def only(target, line, operation="mail-archive", **slots):
    return widened(operation, line, {"target": target, **slots})["spans"]["target"]


def test_a_stop_word_ends_the_subject_in_every_language():
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the greenhouse lease that we accept") == "Orla Whitcombe about the greenhouse lease"
    assert only("Tiago Valente", "arquiva o e-mail do Tiago Valente sobre o forro e responde") == "Tiago Valente sobre o forro"      # validate: allow english-only -- the Portuguese line under test
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the greenhouse lease and then the rest") == "Orla Whitcombe about the greenhouse lease"
    assert only("Clarice Moura", "responde a Clarice Moura sobre o telhado dizendo que fechamos", operation="mail-reply", body="que fechamos") == "Clarice Moura sobre o telhado"      # validate: allow english-only -- the Portuguese line under test


def test_a_comma_ends_the_subject_and_is_not_part_of_it():
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the greenhouse lease, please") == "Orla Whitcombe about the greenhouse lease"


def test_a_body_span_after_the_subject_ends_it():
    got = widened("mail-reply", "reply to Orla Whitcombe about the greenhouse lease we accept the terms", {"target": "Orla Whitcombe", "body": "we accept the terms"})
    assert got["spans"]["target"] == "Orla Whitcombe about the greenhouse lease" and got["spans"]["body"] == "we accept the terms"
    assert got["spans"]["body"] not in got["spans"]["target"], "the reply's own text is never reached by the target"


def test_a_slot_that_begins_inside_the_subject_cuts_it_even_with_no_time_phrase_and_no_stop_word(monkeypatch):
    monkeypatch.setattr(interp.nt, "find", lambda line: {"hits": [], "origin": []})          # isolate the rule: only the other slot's start can end the subject here
    got = widened("mail-reply", "reply to Orla Whitcombe about the greenhouse lease thank them warmly", {"target": "Orla Whitcombe", "body": "thank them warmly"})
    assert got["spans"]["target"] == "Orla Whitcombe about the greenhouse lease"


def test_a_day_span_and_a_time_phrase_end_the_subject():
    got = widened("mail-archive", "archive the email from Orla Whitcombe about the greenhouse lease yesterday", {"target": "Orla Whitcombe", "day": "yesterday"})
    assert got["spans"]["target"] == "Orla Whitcombe about the greenhouse lease" and got["spans"]["day"] == "yesterday"
    assert only("Bruno Teixeira", "arquiva o e-mail do Bruno Teixeira sobre a reunião de segunda") == "Bruno Teixeira sobre a reunião"      # validate: allow english-only -- the Portuguese line under test


def test_a_time_phrase_alone_ends_the_subject_when_no_slot_names_it():
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the greenhouse lease tomorrow") == "Orla Whitcombe about the greenhouse lease"


def test_a_date_written_as_numbers_ends_the_subject(monkeypatch):
    monkeypatch.setattr(interp.nt, "find", lambda line: {"hits": [], "origin": []})          # isolate the rule: the date shape alone, with the time engine read as blind
    assert only("Ana Duarte", "responde a Ana Duarte sobre o evento 12/11 que aceito", operation="mail-reply", body="que aceito") == "Ana Duarte sobre o evento"      # validate: allow english-only -- the Portuguese line under test
    assert only("Ana Duarte", "arquiva o e-mail da Ana Duarte sobre o evento 12.11 depois") == "Ana Duarte sobre o evento"      # validate: allow english-only -- the Portuguese line under test


def test_a_function_word_left_at_the_end_of_the_subject_is_removed():
    assert only("Bruno Teixeira", "arquiva o e-mail do Bruno Teixeira sobre a reunião de e responde") == "Bruno Teixeira sobre a reunião"      # validate: allow english-only -- the Portuguese line under test
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the lease of Friday") == "Orla Whitcombe about the lease"


def test_re_with_a_colon_is_no_marker_and_a_marker_with_nothing_after_it_leaves_the_target():
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe re: invoice 12") == "Orla Whitcombe"
    assert only("Ana Duarte", "arquiva o e-mail da Ana Duarte sobre") == "Ana Duarte"      # validate: allow english-only -- the Portuguese line under test
    assert only("Ana Duarte", "arquiva o e-mail da Ana Duarte sobre e responde") == "Ana Duarte"      # validate: allow english-only -- a marker followed at once by a stop word


def test_a_target_that_stands_twice_in_the_line_or_is_not_set_apart_leaves_it():
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the lease, not the one Orla Whitcombe sent") == "Orla Whitcombe"
    assert only("Ana", "responde a Ana,sobre o evento", operation="mail-archive") == "Ana"      # validate: allow english-only -- the Portuguese line under test


def test_more_than_six_words_in_the_subject_leave_the_target():
    line = "archive the email from Orla Whitcombe about the lease for the old warehouse near the river"
    assert only("Orla Whitcombe", line) == "Orla Whitcombe"
    seven = "archive the email from Orla Whitcombe about the old lease of the warehouse near"          # a tail of seven words whose content words stay within the target words' limit: only the maximum refuses it
    assert only("Orla Whitcombe", seven) == "Orla Whitcombe"
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the lease for the old warehouse") == "Orla Whitcombe about the lease for the old warehouse"          # six words stay


def test_a_subject_that_adds_no_word_that_names_a_message_leaves_the_target():
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the email") == "Orla Whitcombe"          # "the email" are words the target words drop: the widening names nothing more


def test_a_marker_in_a_word_of_the_target_is_not_a_reason_to_refuse_it():
    got = widened("mail-trash", "apaga o e-mail da Loja Vento Sul sobre a promoção de inverno", {"target": "Loja Vento Sul"})      # validate: allow english-only -- the Portuguese line under test
    assert got["spans"]["target"] == "Loja Vento Sul sobre a promoção de inverno"          # "Sul" folds to an Italian marker: the first trial refused such a target, and was wrong      # validate: allow english-only -- the Portuguese line under test


# --- 3. gap 1: scope ----------------------------------------------------------------------------------------------------------------------------------


def test_the_target_of_an_event_is_never_widened():
    line = "muda o treino sobre o joelho para as 18h"      # validate: allow english-only -- the Portuguese line under test
    got = run(op("event-change", {"target": "treino", "time": "18h"}, time_iso="2026-10-21T18:00", weekday="wed"), line)
    assert got["kind"] == "op" and got["spans"]["target"] == "treino" and got["args"]["target"] == "treino", got


def test_an_inherited_target_is_never_widened():
    frame = plan_frame("mail-reply", {"target": "Orla Whitcombe"})
    obj = op("mail-reply", {"body": "we accept"}, inherit={"target": "Orla Whitcombe"})
    got = run(obj, "reply to Orla Whitcombe about the greenhouse lease saying we accept", frame)
    assert got["kind"] == "op" and got["inherited"] == ["target"] and got["spans"]["target"] == "Orla Whitcombe" and got["args"]["target"] == "Orla Whitcombe", got


def test_a_target_that_already_holds_its_subject_is_unchanged():
    got = widened("mail-reply", "reply to Orla Whitcombe about the greenhouse lease and say we accept", {"target": "Orla Whitcombe about the greenhouse lease", "body": "we accept"})
    assert got["spans"]["target"] == "Orla Whitcombe about the greenhouse lease"


def test_a_target_that_is_not_in_the_line_is_still_refused_as_before():
    invalid(run(op("mail-reply", {"target": "Rosa Pinheiro", "body": "we accept"}), "reply to Orla Whitcombe about the greenhouse lease and say we accept"), "E_SPAN")


# --- 4. gap 1: vacuity --------------------------------------------------------------------------------------------------------------------------------


def test_a_helper_that_returns_a_word_the_line_lacks_is_refused_by_the_check(monkeypatch):
    monkeypatch.setattr(interp, "_target_with_subject", lambda target, *more, **kw: target + " about the secret vault")
    got = run(op("mail-reply", {"target": "Orla Whitcombe", "body": "we accept"}), BLIND_SHAPES[0][1])
    assert got["kind"] == "clarify" and got["error"] == "E_SPAN" and got["why"] == "invalid", got


def test_the_guard_of_the_widening_fails_when_the_widening_is_switched_off(monkeypatch):
    monkeypatch.setattr(interp, "_target_with_subject", lambda target, *more, **kw: target)          # identity: today's behaviour
    with pytest.raises(AssertionError):
        test_the_subject_the_line_gives_after_the_target_stays_in_it()


def test_a_widened_target_that_would_not_name_a_message_is_not_taken(monkeypatch):
    monkeypatch.setattr("natural_writes_mail.target_words", lambda span, tables: [])          # names nothing at all
    assert only("Orla Whitcombe", "archive the email from Orla Whitcombe about the greenhouse lease") == "Orla Whitcombe"


# --- 5. gap 3: a slot the line fills is the line's ----------------------------------------------------------------------------------------------------

STOP_LINE = "Não, espera, a 8 deixa rodar que tá quase acabando; para a 9"      # validate: allow english-only -- the Portuguese line under test
STOP_FRAME = {"v": 1, "items": [], "last": {"op": "stop-task", "words": {"id": "8"}, "age_s": 25}}


def test_a_number_the_line_writes_is_the_number_and_the_old_one_the_model_also_named_is_dropped():
    got = run(op("stop-task", {"id": "9"}, inherit={"id": "8"}), STOP_LINE, STOP_FRAME)
    assert got["kind"] == "op" and got["op"] == "stop-task" and got["args"] == {"task_id": 9} and got["inherited"] == [] and got["spans"] == {"id": "9"}, got


def test_a_file_the_line_names_is_the_file_and_the_old_one_is_dropped():
    old = "Contrato da Chácara Pinheiro"      # validate: allow english-only -- the Portuguese words under test
    frame = {"v": 1, "items": [], "last": {"op": "file-read", "words": {"file": old}, "age_s": 25}}
    got = run(op("file-read", {"file": "Gastos de Novembro"}, inherit={"file": old}), "não é esse, é a planilha Gastos de Novembro", frame)      # validate: allow english-only -- the Portuguese line under test
    assert got["kind"] == "op" and got["op"] == "file-read" and got["args"]["file"] == "Gastos de Novembro" and got["inherited"] == [] and got["spans"] == {"file": "Gastos de Novembro"}, got
    assert old not in str(got)


def test_a_slot_the_line_does_not_fill_is_still_inherited_from_the_recorded_words():
    last = {"op": "event-create", "words": {"title": "revisão do carro", "calendar": "pessoal"}, "age_s": 30}      # validate: allow english-only -- the Portuguese words under test
    obj = op("event-create", {"time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit={"title": "revisão do carro"})      # validate: allow english-only -- the Portuguese words under test
    got = run(obj, "e outro sábado às 16h", {"v": 1, "items": [], "last": last})      # validate: allow english-only -- the Portuguese line under test
    assert got["kind"] == "op" and got["inherited"] == ["title"] and got["args"]["title"] == "revisão do carro"      # validate: allow english-only -- the Portuguese words under test
    wrong = op("event-create", {"time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit={"title": "troca de óleo"})      # validate: allow english-only -- the Portuguese words under test
    invalid(run(wrong, "e outro sábado às 16h", {"v": 1, "items": [], "last": last}), "E_INHERIT")      # validate: allow english-only -- the Portuguese line under test


def test_an_inherited_time_slot_is_still_refused_when_the_line_does_not_fill_it():
    frame = {"v": 1, "items": [], "last": {"op": "event-create", "words": {"time": "sábado às 16h"}, "age_s": 5}}      # validate: allow english-only -- the Portuguese words under test
    invalid(run(op("event-create", {"title": "revisão"}, inherit={"time": "sábado às 16h"}), "revisão de novo", frame), "E_INHERIT")      # validate: allow english-only -- the Portuguese line under test


# --- 6. gap 3: vacuity --------------------------------------------------------------------------------------------------------------------------------


def test_an_inherit_value_that_is_not_in_the_recorded_words_is_dropped_silently_when_the_line_fills_the_slot():
    got = run(op("stop-task", {"id": "9"}, inherit={"id": "words of no earlier request"}), STOP_LINE, STOP_FRAME)
    assert got["kind"] == "op" and got["spans"] == {"id": "9"} and got["args"] == {"task_id": 9} and got["inherited"] == [], "never an error, never read, never kept"
    none = run(op("stop-task", {"id": "9"}, inherit={"id": "8"}), STOP_LINE, None)
    assert none["kind"] == "op" and none["spans"] == {"id": "9"}, "not even a frame is needed: the inherit of a filled slot is never looked at"


def test_an_inherit_of_a_slot_the_operation_lacks_is_still_refused_first_whatever_the_slots_hold():
    invalid(run(op("stop-task", {"id": "9"}, inherit={"folder": "x"}), STOP_LINE, STOP_FRAME), "E_SLOT_UNKNOWN")
    invalid(run(op("file-read", {"file": "Gastos de Novembro"}, inherit={"id": "8"}), "é a planilha Gastos de Novembro", STOP_FRAME), "E_SLOT_UNKNOWN")      # validate: allow english-only -- the Portuguese line under test


# --- 7. gap 4: a correction of a read plan stays that read -------------------------------------------------------------------------------------------

READ_FRAME = plan_frame("items")
READ_CORRECTIONS = (
    ("nope, I meant my unread emails from this morning, not the calendar", op("mail-mark", {"state": "unread", "day": "this morning"})),
    ("não, eu quis dizer os e-mails de hoje, não a agenda", op("mail-mark", {"day": "de hoje"})),      # validate: allow english-only -- the Portuguese line under test
)


def check_the_corrected_reads():
    for line, obj in READ_CORRECTIONS:
        got = run(obj, line, READ_FRAME)
        assert got["kind"] == "op" and got["op"] == "items" and got["args"] == {} and got["spans"] == {} and got["time"] is None and got["inherited"] == [], (line, got)
        assert got["corrects"] == "i1", "it is the correction of the plan the frame holds: code asks it as a NEW plan"


def test_a_no_that_names_another_act_for_a_read_plan_is_the_plans_own_read():
    check_the_corrected_reads()


def test_the_corrected_read_is_a_decision_of_the_plans_read_with_no_slot_the_model_gave_when_the_read_is_a_list():
    got = run(op("mail-mark", {"state": "unread", "day": "this morning"}), READ_CORRECTIONS[0][0], READ_FRAME)
    assert set(got) == {"kind", "error", "op", "args", "spans", "time", "inherited", "time_disagree", "corrects"} and got["error"] is None


def test_a_correction_that_names_a_slot_of_the_read_keeps_it(monkeypatch):
    monkeypatch.setattr(interp, "READ_LOOKALIKE_CARDS", ("mail-mark", "file-trash"))          # no card of the catalog today is both a lookalike of a read with slots and has its slots: the branch is exercised with one
    frame = plan_frame("file-read", {"file": "Contrato da Chácara Pinheiro"})      # validate: allow english-only -- the Portuguese words under test
    got = run(op("file-trash", {"file": "Gastos de Novembro"}), "não, é a planilha Gastos de Novembro", frame)      # validate: allow english-only -- the Portuguese line under test
    assert got["kind"] == "op" and got["op"] == "file-read" and got["args"]["file"] == "Gastos de Novembro" and got["corrects"] == "i1", got


def test_a_file_trash_for_a_file_read_plan_is_the_models_card():
    frame = plan_frame("file-read", {"file": "Contrato da Chácara Pinheiro"})      # validate: allow english-only -- the Portuguese words under test
    untouched(op("file-trash", {"file": "Gastos de Novembro"}), "não, é a planilha Gastos de Novembro", frame)      # validate: allow english-only -- the Portuguese line under test


# --- 8. gap 4: the negatives keep today's path --------------------------------------------------------------------------------------------------------


def untouched(obj, line, frame):
    got = run(obj, line, frame)
    assert got["kind"] == "op" and got["op"] == obj["op"] and "corrects" not in got, got
    return got


def test_a_line_that_holds_the_head_of_a_write_keeps_the_models_card():
    untouched(op("mail-archive"), "no, archive them", READ_FRAME)
    untouched(op("mail-trash"), "não, apaga esses e-mails", READ_FRAME)      # validate: allow english-only -- the Portuguese line under test


def test_a_line_that_does_not_open_with_a_no_keeps_the_models_op():
    untouched(op("mail-mark", {"state": "unread"}), "I meant my unread emails from this morning", READ_FRAME)
    untouched(op("mail-mark", {"state": "unread"}), "my unread emails, not the calendar, and the no is later", READ_FRAME)


def test_a_plan_that_is_not_a_read_is_untouched():
    frame = plan_frame("cancel", {"id": "3"})
    untouched(op("mail-mark", {"state": "unread"}), "no, I meant my unread emails", frame)
    untouched(op("mail-mark"), "no, I meant my unread emails", frame)          # no slot to refuse it on: only the class of the plan's operation stops it


def test_a_model_that_names_a_write_or_the_plans_own_op_is_untouched():
    got = untouched(op("stop-task", {"id": "9"}), "no, I meant task 9", READ_FRAME)
    assert got["args"] == {"task_id": 9}
    same = run(op("items"), "no, I meant the calendar", READ_FRAME)
    assert same["kind"] == "op" and same["op"] == "items" and "corrects" not in same


def test_a_frame_with_no_plan_item_is_untouched():
    untouched(op("mail-mark", {"state": "unread"}), "no, I meant my unread emails", plan_frame("items", kind="router-question"))
    untouched(op("mail-mark", {"state": "unread"}), "no, I meant my unread emails", None)
    untouched(op("mail-mark", {"state": "unread"}), "no, I meant my unread emails", {"v": 1, "items": [], "last": None})


def test_a_plan_item_of_another_operation_than_the_last_request_is_untouched():
    frame = plan_frame("items")
    frame["last"] = {"op": "file-read", "words": {"file": "Gastos de Novembro"}, "age_s": 25}
    untouched(op("mail-mark", {"state": "unread"}), "no, I meant my unread emails", frame)
    untouched(op("mail-mark"), "no, I meant my unread emails", frame)          # no slot to refuse it on: only the item's operation differing from the last request stops it


def test_a_slot_the_read_lacks_means_another_act_and_is_untouched():
    frame = plan_frame("file-read", {"file": "Contrato da Chácara Pinheiro"})      # validate: allow english-only -- the Portuguese words under test
    got = untouched(op("mail-mark", {"state": "unread"}), "no, I meant the unread ones", frame)
    assert got["spans"] == {"state": "unread"}


# --- 9. gap 4: vacuity --------------------------------------------------------------------------------------------------------------------------------


def test_the_guard_of_the_corrected_read_fails_when_every_line_is_taken_as_an_act(monkeypatch):
    monkeypatch.setattr(interp, "_asks_an_act", lambda line: True)
    with pytest.raises(AssertionError):
        check_the_corrected_reads()


def test_the_no_lead_is_what_protects_a_new_request(monkeypatch):
    new = "archive the emails from Dana"
    got = run(op("mail-archive", {"target": "Dana"}), new, READ_FRAME)
    assert got["kind"] == "op" and got["op"] == "mail-archive" and "corrects" not in got, "a new request under a live plan keeps its card"
    monkeypatch.setattr(interp, "READ_LOOKALIKE_CARDS", ("mail-mark", "mail-archive"))          # the card is one a read could be mistaken for, so only the no-lead and the head protect the line
    assert run(op("mail-archive", {"target": "Dana"}), new, READ_FRAME)["op"] == "mail-archive", "no no-lead: the model's card"
    monkeypatch.setattr(interp, "starts_with_no", lambda line: True)
    assert run(op("mail-archive", {"target": "Dana"}), new, READ_FRAME)["op"] == "mail-archive", "the line holds the head of a write: the no-lead alone does not turn it"
    monkeypatch.setattr(interp, "_asks_an_act", lambda line: False)          # both conditions off: only then does the read swallow the new request
    turned = run(op("mail-archive", {"target": "Dana"}), new, READ_FRAME)
    assert turned["kind"] == "op" and turned["op"] == "items" and turned["corrects"] == "i1", "without the no-lead condition the read would swallow a new request"
    monkeypatch.undo()
    assert run(op("mail-archive", {"target": "Dana"}), new, READ_FRAME)["op"] == "mail-archive"


def test_the_write_head_is_what_protects_a_correction_that_asks_for_an_act(monkeypatch):
    line = "no, archive the emails from Dana"
    assert interp._asks_an_act(line) is True
    got = untouched(op("mail-archive", {"target": "Dana"}), line, READ_FRAME)
    assert got["spans"]["target"] == "Dana"
    monkeypatch.setattr(interp, "READ_LOOKALIKE_CARDS", ("mail-mark", "mail-archive"))
    monkeypatch.setattr(interp, "_asks_an_act", lambda line: False)
    assert run(op("mail-archive", {"target": "Dana"}), line, READ_FRAME)["op"] == "items", "with no head of a write read, the same line would have become the read"


def test_the_heads_are_read_from_the_write_families_and_not_copied():
    for line in ("apaga esses e-mails", "archive them", "move this file to trash"):
        assert interp._asks_an_act(line) is True, line
    for line in ("I meant my unread emails from this morning, not the calendar", "eu quis dizer os e-mails de hoje, não a agenda"):      # validate: allow english-only -- the Portuguese line under test
        assert interp._asks_an_act(line) is False, line


# --- 10. nothing runs ---------------------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def typed(rig, monkeypatch):
    """The command a plan hands over once it is confirmed, recorded instead of run."""
    rig.said_commands = []
    monkeypatch.setattr(ops_say, "_say_command", lambda project, ctx, line, channel, line_id, sender=None: rig.said_commands.append(line) or ("COMMAND-REPLY", None, None, False, None))
    return rig


def read_spy(rig):
    rig.reads = []
    from plan_confirm_kit import ops_natural
    rig.monkeypatch.setattr(ops_natural, "_read", lambda project, ctx, name, row, args, channel, sender: rig.reads.append({"name": name, "args": args}) or "READ-REPLY")
    return rig.reads


def corrected_read(rig, line, model_text):
    """The first plan is the agenda of today; the person corrects it with `line`, the model (stood in) answers `model_text`. Returns (the first reply, the reply to the correction, the reads)."""
    reads = read_spy(rig)
    rig.world["clock"].set("2026-10-25 00:50")
    rig.says["text"] = model_op("items")
    old = say(rig, OWNER, "mostra minha agenda de hoje")      # validate: allow english-only -- the Portuguese line under test
    assert "plan_confirm" in old and reads == []
    rig.now[0] += 30
    rig.says["text"] = model_text
    return old, say(rig, OWNER, line), reads


def test_a_corrected_read_asks_a_new_plan_and_nothing_runs(typed):
    old, out, reads = corrected_read(typed, "não, eu quis dizer os e-mails de hoje", model_op("mail-mark", {"day": "de hoje"}))      # validate: allow english-only -- the Portuguese line under test
    what = phrases.text("UNDERSTOOD_ITEMS_MAIL", typed.cfg) + phrases.localize_dates(phrases.text("UNDERSTOOD_ON_DAY", typed.cfg, day="Sun 25/10/2026"), typed.cfg)
    assert out["reply"] == phrases.text("PLAN_HEAD", typed.cfg, what=what) + " " + phrases.text("PLAN_ASK", typed.cfg), "a NEW plan question, for the list of mail"
    assert out["plan_confirm"]["item"] != old["plan_confirm"]["item"]
    assert reads == [] and typed.said_commands == [], "nothing was read, marked or run before the OK"
    assert say(typed, OWNER, "sim", plan_ok=ok_of(old))["reply"] == phrases.text("PLAN_GONE", typed.cfg), "the plan that was corrected is gone"
    assert reads == [] and typed.said_commands == []
    done = say(typed, OWNER, "sim", plan_ok=ok_of(out))
    assert done["reply"] == "READ-REPLY" and [r["args"]["kind"] for r in reads] == ["mail"] and typed.said_commands == []


def test_the_blind_line_that_also_negates_the_calendar_asks_a_new_plan_for_the_mail_and_nothing_runs(typed):
    """Found while building BL7-1 (guard 10 of the spec, run end to end): `natural_writes.items_noun` read a line that names both nouns as "calendar" ("not the calendar" included), so for the two blind
    lines of gap 4 the corrected read equalled the plan and `ops_interpret._unchanged` dropped it. ITEMS-NEGATION: a noun a negator reaches is the one the person does not want, so the line names the
    e-mails and the correction is the NEW question the spec expected."""
    old, out, reads = corrected_read(typed, "não, eu quis dizer os e-mails de hoje, não a agenda", model_op("mail-mark", {"day": "de hoje"}))      # validate: allow english-only -- the Portuguese line under test
    what = phrases.text("UNDERSTOOD_ITEMS_MAIL", typed.cfg) + phrases.localize_dates(phrases.text("UNDERSTOOD_ON_DAY", typed.cfg, day="Sun 25/10/2026"), typed.cfg)
    assert out["reply"] == phrases.text("PLAN_HEAD", typed.cfg, what=what) + " " + phrases.text("PLAN_ASK", typed.cfg) and out["plan_confirm"]["item"] != old["plan_confirm"]["item"]
    assert reads == [] and typed.said_commands == []


def test_a_stop_with_two_numbers_in_the_line_asks_which_number_and_stops_nothing(typed):
    typed.says["text"] = model_op("stop-task", {"id": "8"})
    old = say(typed, OWNER, "pode parar a tarefa 8")      # validate: allow english-only -- the Portuguese line under test
    assert "plan_confirm" in old and typed.said_commands == []
    typed.now[0] += 30
    typed.says["text"] = model_op("stop-task", {"id": "9"}, inherit={"id": "8"})
    out = say(typed, OWNER, STOP_LINE)
    assert out["reply"] == phrases.text("NAT_ASK_ID", typed.cfg) and "plan_confirm" not in out, "the vet of decision numbers asks which one: the line writes two"
    assert typed.said_commands == [] and ops.plan_live(typed.world["path"], OWNER) is None


# --- 11. review round: the marker word is never a word of the message ----------------------------------------------------------------------------------

ANA_INDEX = [{"n": 1, "from_address": "ana@clinica.example", "subject": "Orçamento do telhado"}]      # validate: allow english-only -- an index entry of the fixture
MARKER_LINES = (      # a marker of each family, the subject word "telhado" a word no table knows: the message must be found by the person and the subject, in every language
    "responde a Ana a respeito do telhado", "responde a Ana referente ao telhado", "responde a Ana acerca do telhado",      # validate: allow english-only -- the Portuguese lines under test
    "reply to Ana concerning the telhado", "reply to Ana re the telhado", "reply to Ana regarding the telhado", "reply to Ana about the telhado",
    "responde a Ana respecto al telhado", "réponds à Ana au sujet du telhado", "reply to Ana a propos du telhado", "reply to Ana sur telhado",      # validate: allow english-only -- the Spanish and French lines under test
    "antworte Ana wegen telhado", "reply to Ana zum thema telhado", "rispondi ad Ana riguardo al telhado", "rispondi ad Ana su telhado",
)


def grounded(operation, line, target="Ana", **slots):
    got = widened(operation, line, {"target": target, **slots})
    seed = ops_natural_mail.mail_target_seed(operation, got)
    return got, seed["slots"]["words"] if seed else None


def test_a_widened_target_finds_its_message_whatever_the_marker_of_its_language():
    for line in MARKER_LINES:
        got, words = grounded("mail-reply", line)
        assert got["spans"]["target"] != "Ana" and got["spans"]["target"] in line, line
        assert words == ["ana", "telhado"], (line, words)
        assert [e["n"] for e in mail_words.match_words(ANA_INDEX, words)] == [1], (line, words)


def test_the_grounding_text_is_the_person_and_the_subject_and_only_a_widened_target_has_one():
    got = widened("mail-reply", "responde a Ana a respeito do telhado", {"target": "Ana"})      # validate: allow english-only -- the Portuguese line under test
    assert got["target_ground"] == "Ana telhado" and got["spans"]["target"] == "Ana a respeito do telhado"
    plain = widened("mail-reply", "responde a Ana e diz que sim", {"target": "Ana", "body": "que sim"})      # validate: allow english-only -- the Portuguese line under test
    assert "target_ground" not in plain
    other = widened("mail-reply", "reply to Ana about the telhado", {"target": "Ana about the telhado"})
    assert "target_ground" not in other, "a target the model already gave with its subject is not widened and needs no grounding text"


def test_the_marker_word_is_dropped_at_its_own_place_and_a_word_of_the_name_that_looks_like_a_marker_stays():
    got = widened("mail-trash", "apaga o e-mail da Loja Vento Sul sobre a promoção de inverno", {"target": "Loja Vento Sul"})      # validate: allow english-only -- the Portuguese line under test
    assert got["target_ground"] == "Loja Vento Sul a promoção de inverno"      # validate: allow english-only -- the Portuguese words under test


def test_without_the_grounding_text_the_marker_word_would_still_lose_the_message():
    got = widened("mail-reply", "responde a Ana a respeito do telhado", {"target": "Ana"})      # validate: allow english-only -- the Portuguese line under test
    without = {key: value for key, value in got.items() if key != "target_ground"}
    words = ops_natural_mail.mail_target_seed("mail-reply", without)["slots"]["words"]
    assert "respeito" in words and mail_words.match_words(ANA_INDEX, words) == [], "proves the grounding text is what finds the message"


def test_the_subject_alone_is_never_what_the_message_is_found_by_when_the_target_stays_bare():
    got = widened("mail-reply", "responde a Ana e diz que sim", {"target": "Ana", "body": "que sim"})      # validate: allow english-only -- the Portuguese line under test
    assert ops_natural_mail.mail_target_seed("mail-reply", got)["slots"]["words"] == ["ana"]


# --- 12. review round: an act the plan's read must not swallow -----------------------------------------------------------------------------------------

LOST_ACTS = (      # (the model's card, the line, its slots): every one is an act the person asked for, in a line that opens with a no, under a live plan of a list
    ("event-create", "no, schedule lunch with Dana tomorrow at noon", {"title": "lunch with Dana"}),
    ("event-create", "no, book a call with Dana tomorrow", {"title": "a call with Dana"}),
    ("event-create", "não, agenda almoço com a Dana amanhã", {"title": "almoço com a Dana"}),      # validate: allow english-only -- the Portuguese line under test
    ("mail-send", "no, tell Dana I am running late", {"to": "Dana", "body": "I am running late"}),
    ("mail-send", "não, avisa a Dana que vou atrasar", {"to": "Dana", "body": "que vou atrasar"}),      # validate: allow english-only -- the Portuguese line under test
    ("mail-trash", "no, bin the ones from Dana", {"target": "Dana"}),
)


def test_an_act_the_person_asked_for_is_never_turned_into_the_plans_read():
    for model_op, line, slots in LOST_ACTS:
        got = run(op(model_op, slots), line, READ_FRAME)
        assert got["kind"] == "op" and got["op"] == model_op and "corrects" not in got, (line, got)


def test_an_act_with_no_verb_of_a_family_and_a_file_read_plan_keeps_the_models_card():
    frame = plan_frame("file-read", {"file": "Contrato da Chácara Pinheiro"})      # validate: allow english-only -- the Portuguese words under test
    got = run(op("file-trash", {"file": "Gastos de Novembro"}), "no, get rid of Gastos de Novembro", frame)
    assert got["kind"] == "op" and got["op"] == "file-trash" and "corrects" not in got, got


def test_the_triggers_of_a_new_event_are_heads_of_an_act():
    for line in ("no, schedule lunch with Dana", "no, book a call", "não, agende um almoço", "não, marca na agenda o almoço", "no, add to my calendar the dentist"):      # validate: allow english-only -- the Portuguese lines under test
        assert interp._asks_an_act(line) is True, line
    assert interp._asks_an_act("no, I meant my unread emails from this morning") is False


def test_a_card_that_carries_the_content_of_a_new_act_is_never_a_read_even_when_the_card_could_be_mistaken_for_one(monkeypatch):
    monkeypatch.setattr(interp, "READ_LOOKALIKE_CARDS", ("mail-mark", "mail-draft"))
    line = "no, a note to Dana saying I am late"
    got = run(op("mail-draft", {"to": "Dana", "body": "I am late"}), line, READ_FRAME)
    assert got["kind"] == "op" and got["op"] == "mail-draft" and "corrects" not in got, got
    monkeypatch.setattr(interp, "ACT_CONTENT_SLOTS", frozenset())          # vacuity: without the content-slot guard the draft would have become the read
    assert run(op("mail-draft", {"to": "Dana", "body": "I am late"}), line, READ_FRAME)["op"] == "items"


def test_only_a_card_the_reads_words_can_be_mistaken_for_is_turned_into_the_read(monkeypatch):
    line = "no, bin the ones from Dana"
    assert run(op("mail-trash", {"target": "Dana"}), line, READ_FRAME)["op"] == "mail-trash"
    monkeypatch.setattr(interp, "READ_LOOKALIKE_CARDS", ("mail-mark", "mail-trash"))          # vacuity: a destructive card in the list would be swallowed by the read
    assert run(op("mail-trash", {"target": "Dana"}), line, READ_FRAME)["op"] == "items"
    monkeypatch.undo()
    assert run(op("mail-mark", {"state": "unread"}), "no, I meant the unread ones", READ_FRAME)["op"] == "items"


def test_a_lookalike_card_whose_class_is_not_a_card_is_untouched():
    ops, _refused = interp._catalog_rows(kit.CATALOG)
    flipped = dict(ops, **{"mail-mark": dict(ops["mail-mark"], **{"class": "W"})})
    obj, frame = op("mail-mark"), READ_FRAME
    assert interp._read_plan_kept(obj, "no, I meant my unread emails", frame, ops) is not None
    assert interp._read_plan_kept(obj, "no, I meant my unread emails", frame, flipped) is None, "the class of the model's operation is what stops it, with no slot to refuse it on"


# --- 13. review round: the subject ends where another request begins -------------------------------------------------------------------------------------


def test_a_break_of_line_ends_the_subject_and_a_marker_on_another_line_is_not_one():
    assert only("Ana", "apaga o e-mail da Ana sobre o orçamento\nresponde o Bo dizendo ok", operation="mail-trash") == "Ana sobre o orçamento"      # validate: allow english-only -- the Portuguese line under test
    assert only("Ana", "apaga o e-mail da Ana\nsobre o orçamento", operation="mail-trash") == "Ana"      # validate: allow english-only -- the Portuguese line under test


def test_a_second_request_after_the_subject_ends_it():
    assert only("Ana", "archive the email from Ana about the orçamento then trash the one from Bo") == "Ana about the orçamento"      # validate: allow english-only -- the Portuguese word under test
    assert only("Ana", "archive the email from Ana about the orçamento trash the one from Bo") == "Ana about the orçamento"      # validate: allow english-only -- the Portuguese word under test
    assert only("Ana", "arquiva o e-mail da Ana sobre o orçamento depois apaga o do Bo") == "Ana sobre o orçamento"      # validate: allow english-only -- the Portuguese line under test
    assert only("Ana", "archive the email from Ana about the orçamento schedule a call with Bo") == "Ana about the orçamento"      # validate: allow english-only -- the Portuguese word under test


def test_a_closing_too_and_a_destination_are_not_the_subject():
    assert only("Ana", "trash the email from Ana about the orçamento too", operation="mail-trash") == "Ana about the orçamento"      # validate: allow english-only -- the Portuguese word under test
    assert only("Ana", "apaga o e-mail da Ana sobre o orçamento também", operation="mail-trash") == "Ana sobre o orçamento"      # validate: allow english-only -- the Portuguese line under test
    assert only("Ana", "move the email from Ana about the orçamento into Archive", operation="mail-move", folder="Archive") == "Ana about the orçamento"      # validate: allow english-only -- the Portuguese word under test
    assert only("Ana", "move o e-mail da Ana sobre o orçamento na pasta Trabalho", operation="mail-move", folder="Trabalho") == "Ana sobre o orçamento"      # validate: allow english-only -- the Portuguese line under test


def test_a_widened_target_of_the_review_lines_still_finds_the_message():
    for operation, line in (("mail-trash", "apaga o e-mail da Ana sobre o orçamento\nresponde o Bo dizendo ok"), ("mail-archive", "archive the email from Ana about the orçamento then trash the one from Bo"),      # validate: allow english-only -- the Portuguese lines under test
                            ("mail-trash", "trash the email from Ana about the orçamento too"), ("mail-move", "move the email from Ana about the orçamento into Archive")):      # validate: allow english-only -- the Portuguese word under test
        extra = {"folder": "Archive"} if operation == "mail-move" else {}
        got, words = grounded(operation, line, **extra)
        assert [e["n"] for e in mail_words.match_words(ANA_INDEX, words)] == [1], (line, words)

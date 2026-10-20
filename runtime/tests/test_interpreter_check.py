"""The validator of the interpreter (package IX-2a, runtime/interpreter.py `check`): what code believes of an object the model returned, over an UNCHANGED `natural.check_operation`.

A decision a model's object can reach is checked here from the protocol's rules and the test's own literal lists, never from the module's tables: every decision (D) operation of a literal
list gives `refuse` D, every widening one `refuse` G, `say`, `route`, `request` and the internal machinery are not operations a line can name, a span, a number, an address, an inherited span, an
answered item and the sender's policy are each accepted and each refused, the source of `natural.check_operation` is asserted untouched (by hash) and is called as the router's outcome calls it,
a route for a private line becomes a question, and a line that is too long is not sent. Vacuity: a decision oracle fails a planted `op` decision whose span is not in the line. Offline, no model;
invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_check.py
"""
from __future__ import annotations

import hashlib
import inspect
import json

import interpreter_kit as kit
import standin_tree as st

interp = st.load("interpreter")
natural = kit.natural

# The source of `natural.check_operation` at the commit this package branched from (sha256 of `inspect.getsource`): the validator calls it unchanged, so a change to it is a change of the
# security of the layer and must be read, not merged by accident.
CHECK_OPERATION_SHA256 = "ae0d63f27600795d660808369ea3971427ca60bd30cf5b6c19c6e128aec09a3e"


def run(obj, line, frame=None, allowed=None, now=None, zone=kit.ZONE):
    return interp.check(obj, line, frame, kit.CATALOG, now or kit.NOW, zone, kit.ALL_OPS if allowed is None else allowed)


def op(name, slots=None, **more):
    return {"v": 1, "kind": "op", "op": name, "slots": slots or {}, **more}


def invalid(decision, code):
    assert decision["kind"] == "clarify" and decision["why"] == "invalid" and decision["error"] == code, decision
    assert "op" not in decision or decision.get("op") is None


# --- the source of check_operation ----------------------------------------------------------------------------------------------------------------------

def test_natural_check_operation_is_untouched():
    source = inspect.getsource(natural.check_operation)
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == CHECK_OPERATION_SHA256


def test_non_time_slots_go_through_check_operation_as_the_router_calls_it(monkeypatch):
    calls = []
    real = natural.check_operation

    def spy(name, slots, when, line):
        calls.append((name, dict(slots), when, line))
        return real(name, slots, when, line)
    monkeypatch.setattr(natural, "check_operation", spy)
    line = "write to ben@example.test about the invoice"
    got = run(op("mail-send", {"to": "ben@example.test", "subject": "the invoice"}), line)
    assert got["kind"] == "op" and got["args"] == {"to": "ben@example.test", "subject": "the invoice"}
    assert calls[0] == ("mail-send", {"to": "ben@example.test", "subject": "the invoice"}, None, line)


# --- the vocabulary -----------------------------------------------------------------------------------------------------------------------------------

def test_every_decision_operation_is_refused_as_class_d():
    for name in kit.D_OPS:
        got = run(op(name), "please go ahead with that")
        assert got == {"kind": "refuse", "error": None, "class": "D", "op": name}, name


def test_every_widening_operation_is_refused_as_class_g():
    for name in kit.WIDENING:
        got = run(op(name), "change the settings please")
        assert got == {"kind": "refuse", "error": None, "class": "G", "op": name}, name


def test_a_refused_operation_is_refused_whatever_the_policy_says():
    got = run(op("approve"), "approve it", allowed=set())
    assert got["kind"] == "refuse" and got["class"] == "D"
    got = run(op("approve"), "approve it", allowed={"approve"})
    assert got["kind"] == "refuse" and got["class"] == "D"


def test_say_route_request_the_internal_machinery_and_unknown_names_are_not_operations():
    for name in kit.WORK_NOT_ASK + kit.INTERNAL + ["frobnicate", "mail-send-all"]:
        invalid(run(op(name), "do the thing", allowed={name}), "E_OP_UNKNOWN")


def test_ask_is_an_operation_with_no_slots_and_work_classes_are_otherwise_closed():
    got = run(op("ask"), "when is the deadline of the contract?")
    assert got["kind"] == "op" and got["op"] == "ask" and got["args"] == {} and got["spans"] == {} and got["time"] is None
    invalid(run(op("ask", {"question": "when"}), "when is the deadline"), "E_SLOT_UNKNOWN")


def test_the_operational_g_operations_are_in_the_vocabulary_and_the_internal_ones_are_not():
    for name in kit.OPERATIONAL:
        assert run(op(name), "do it now")["kind"] == "op", name


# --- the sender's policy ------------------------------------------------------------------------------------------------------------------------------

def test_an_operation_outside_the_policy_is_refuse_policy_and_none_allows_nothing():
    line = "what is pending"
    assert run(op("pending"), line, allowed={"pending"})["kind"] == "op"
    assert run(op("pending"), line, allowed={"status"}) == {"kind": "refuse_policy", "error": None, "op": "pending"}
    assert run(op("pending"), line, allowed=set())["kind"] == "refuse_policy"
    assert interp.check(op("pending"), line, None, kit.CATALOG, kit.NOW, kit.ZONE, None)["kind"] == "refuse_policy"
    assert run(op("pending"), line, allowed=frozenset({"pending"}))["kind"] == "op"


# --- spans, numbers, words -------------------------------------------------------------------------------------------------------------------------------

def test_a_span_is_accepted_only_when_it_is_a_piece_of_the_line_as_written():
    line = "mail ben@example.test the subject: the  quarterly   invoice"
    ok = run(op("mail-send", {"to": "ben@example.test", "subject": "the quarterly invoice"}), line)
    assert ok["kind"] == "op" and ok["spans"]["subject"] == "the quarterly invoice"          # a run of spaces in the line is one space to the model
    for slots in ({"subject": "the Quarterly invoice"}, {"subject": "the quarterly invoices"}, {"subject": "quarterly  invoice!"}, {"subject": ""}, {"subject": " "}, {"to": "carol@example.test"},
                  {"to": "ben@example"}, {"body": "x" * 301}):
        got = run(op("mail-send", slots), line)
        invalid(got, "E_SPAN")


def test_a_case_or_accent_change_passes_check_operation_but_not_the_substring_rule():
    line = "reuni\u00e3o de planejamento com a Ana"
    assert natural.check_operation("event-create", {"title": "REUNIAO de planejamento"}, None, line)["ok"]          # the router's rule is looser
    invalid(run(op("event-create", {"title": "REUNIAO de planejamento"}), line), "E_SPAN")
    assert run(op("event-create", {"title": "reuni\u00e3o de planejamento"}), line)["kind"] == "op"


def test_a_number_must_be_written_in_the_line_as_digits_joined_by_commas():
    line = "archive messages 3 and 7, and the reminder 12"
    got = run(op("mail-archive", {"messages": "3,7"}), line)
    assert got["kind"] == "op" and got["args"] == {"messages": [3, 7]}
    for bad in ("3,8", "3, 7", "3 7", "3,", ",3", "3;7", "three", "", "3,7,9", "1e3", "-3", "٣"):
        invalid(run(op("mail-archive", {"messages": bad}), line), "E_INT")
    one = run(op("reminder-forget", {"id": "12"}), line)
    assert one["kind"] == "op" and one["args"] == {"reminder_id": 12}
    for bad in ("13", "1", "012x", "twelve", "+12", "12.0"):
        invalid(run(op("reminder-forget", {"id": bad}), line), "E_INT")


def test_a_word_slot_is_a_whole_word_the_sender_typed():
    line = "send ana@example.test the file report-2026.pdf"
    ok = run(op("mail-send", {"to": "ana@example.test"}), line)
    assert ok["kind"] == "op" and ok["args"] == {"to": "ana@example.test"}
    for bad in ("ana@example", "na@example.test", "bob@example.test", "ana@example.test the"):
        invalid(run(op("mail-send", {"to": bad}), line), "E_SPAN")


def test_a_slot_the_operation_does_not_have_is_refused():
    invalid(run(op("status", {"foo": "bar"}), "status please"), "E_SLOT_UNKNOWN")
    invalid(run(op("mail-send", {"cc": "ana@example.test"}), "mail ana@example.test cc"), "E_SLOT_UNKNOWN")
    invalid(run(op("remind", {"nope": "x"}, time_iso="2026-10-22T15:00", weekday="thu"), "remind me thursday at 3pm"), "E_SLOT_UNKNOWN")


def test_a_time_given_without_a_time_slot_or_a_time_slot_without_a_time_is_refused():
    invalid(run(op("status", {}, time_iso="2026-10-22T15:00", weekday="thu"), "status"), "E_SHAPE")
    invalid(run(op("remind", {"text": "call Dana", "when": "Thursday at 3pm"}), "remind me to call Dana Thursday at 3pm"), "E_SHAPE")


def test_an_error_never_yields_an_op():
    bad = [op("mail-send", {"to": "x@example.test"}), op("pending", {"id": "99"}), op("status", {"x": "y"}), op("frobnicate"), {"v": 1, "kind": "op"}, {"v": 2, "kind": "none"}, [], None, "text"]
    for obj in bad:
        got = run(obj, "status please")
        assert got["kind"] != "op", obj
        assert got["error"] is not None


# --- inherit --------------------------------------------------------------------------------------------------------------------------------------------

LAST = {"op": "event-create", "words": {"title": "revis\u00e3o do carro", "calendar": "pessoal"}, "age_s": 30}
FRAME = {"v": 1, "items": [], "last": LAST}
INHERIT_LINE = "e outro às 16h, sábado"


def test_an_inherited_span_must_be_a_piece_of_the_recorded_words_of_the_frame():
    obj = op("event-create", {"time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit={"title": "revis\u00e3o do carro"})
    got = run(obj, "e outro sábado às 16h", FRAME, allowed={"event-create"})
    assert got["kind"] == "op" and got["inherited"] == ["title"] and got["spans"]["title"] == "revis\u00e3o do carro" and got["args"]["title"] == "revis\u00e3o do carro"
    part = op("event-create", {"time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit={"title": "revis\u00e3o"})
    assert run(part, "e outro sábado às 16h", FRAME)["inherited"] == ["title"]
    for wrong in ({"title": "revis\u00e3o do moto"}, {"title": "troca de óleo"}, {"title": ""}, {"title": "REVIS\u00c3O DO CARRO"}, {"calendar": "trabalho"}, {"folder": "x"}):
        got = run(op("event-create", {"time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit=wrong), "e outro sábado às 16h", FRAME)
        assert got["kind"] == "clarify" and got["error"] in ("E_INHERIT", "E_SLOT_UNKNOWN"), (wrong, got)


def test_inherit_without_a_frame_or_a_last_request_or_for_a_slot_with_no_recorded_words_is_refused():
    obj = op("event-create", {"time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit={"title": "revis\u00e3o do carro"})
    for frame in (None, {"v": 1, "items": [], "last": None}, {"v": 1, "items": [], "last": {"op": "event-create", "words": {}, "age_s": 5}}):
        invalid(run(obj, "e outro sábado às 16h", frame), "E_INHERIT")


def test_a_slot_is_either_given_or_inherited_and_a_time_is_never_inherited():
    both = op("event-create", {"title": "revis\u00e3o do carro", "time": "sábado às 16h"}, time_iso="2026-10-24T16:00", weekday="sat", inherit={"title": "revis\u00e3o do carro"})
    invalid(run(both, "revis\u00e3o do carro sábado às 16h", FRAME), "E_INHERIT")
    frame = {"v": 1, "items": [], "last": {"op": "event-create", "words": {"time": "sábado às 16h"}, "age_s": 5}}
    timed = op("event-create", {"title": "revis\u00e3o"}, inherit={"time": "sábado às 16h"})
    invalid(run(timed, "revis\u00e3o de novo", frame), "E_INHERIT")


# --- answers_item --------------------------------------------------------------------------------------------------------------------------------------

ANSWER_FRAME = {"v": 1, "last": None, "items": [
    kit.item("i1", need="slot", slot="to"),
    {"id": "i2", "kind": "reminder-confirm", "need": "confirm", "op": "remind", "age_s": 5},
    {"id": "i3", "kind": "choice", "need": "option", "options": 3, "age_s": 5},
    {"id": "i4", "kind": "router-question", "need": "text", "age_s": 5},
    kit.item("i5", kind="choice", need="slot", op="event-create", slot="time", age_s=3)]}


def answer(**more):
    return {"v": 1, "kind": "answer", **more}


def test_an_answer_names_a_live_item_of_the_frame_and_the_answer_its_need_asks_for():
    got = run(answer(answers_item="i1", slot="to", span="ben@example.test"), "send it to ben@example.test", ANSWER_FRAME)
    assert got == {"kind": "answer", "error": None, "item": "i1", "need": "slot", "slot": "to", "span": "ben@example.test", "args": {"to": "ben@example.test"}}
    assert run(answer(answers_item="i2", confirm="yes"), "yes", ANSWER_FRAME) == {"kind": "answer", "error": None, "item": "i2", "need": "confirm", "confirm": "yes"}
    assert run(answer(answers_item="i2", confirm="no"), "no", ANSWER_FRAME)["confirm"] == "no"
    assert run(answer(answers_item="i3", option=2), "the second one", ANSWER_FRAME) == {"kind": "answer", "error": None, "item": "i3", "need": "option", "option": 2}
    assert run(answer(answers_item="i4"), "friday", ANSWER_FRAME) == {"kind": "answer", "error": None, "item": "i4", "need": "text"}


def test_an_answer_for_an_item_that_is_not_live_is_refused():
    invalid(run(answer(answers_item="i9", option=1), "one", ANSWER_FRAME), "E_ITEM_UNKNOWN")
    invalid(run(answer(answers_item="i1", slot="to", span="ben@example.test"), "send to ben@example.test", None), "E_ITEM_UNKNOWN")
    invalid(run(answer(answers_item="i1", slot="to", span="ben@example.test"), "send to ben@example.test", {"v": 1, "items": [], "last": None}), "E_ITEM_UNKNOWN")


def test_an_answer_that_does_not_fit_the_need_of_its_item_is_refused():
    invalid(run(answer(answers_item="i3", option=4), "four", ANSWER_FRAME), "E_SHAPE")          # only 3 options
    invalid(run(answer(answers_item="i3", confirm="yes"), "yes", ANSWER_FRAME), "E_SHAPE")
    invalid(run(answer(answers_item="i2", option=1), "one", ANSWER_FRAME), "E_SHAPE")
    invalid(run(answer(answers_item="i4", confirm="yes"), "yes", ANSWER_FRAME), "E_SHAPE")
    invalid(run(answer(answers_item="i1", confirm="yes"), "yes", ANSWER_FRAME), "E_SHAPE")
    invalid(run(answer(answers_item="i1", slot="subject", span="the invoice"), "the invoice", ANSWER_FRAME), "E_SLOT_UNKNOWN")          # the item asks for `to`
    invalid(run(answer(answers_item="i1", slot="to", span="carol@example.test"), "send it to ben@example.test", ANSWER_FRAME), "E_SPAN")
    invalid(run(answer(answers_item="i2", confirm="yes", slot="nope", span="x"), "yes x", ANSWER_FRAME), "E_SLOT_UNKNOWN")


def test_an_answer_to_a_time_question_carries_the_time_checked_like_an_op():
    line = "thursday at 3pm"
    got = run(answer(answers_item="i5", slot="time", span=line, time_iso="2026-10-22T15:00", weekday="thu"), line, ANSWER_FRAME)
    assert got["kind"] == "answer" and got["time"] == {"local": "2026-10-22T15:00", "source": "code"} and got["span"] == line
    invalid(run(answer(answers_item="i5", slot="time", span=line), line, ANSWER_FRAME), "E_SHAPE")
    invalid(run(answer(answers_item="i5", slot="time", span="friday", time_iso="2026-10-23T15:00", weekday="fri"), line, ANSWER_FRAME), "E_SPAN")


# --- clarify, route, none, long lines ----------------------------------------------------------------------------------------------------------------

def test_clarify_names_a_slot_or_two_or_three_operations_of_the_catalog():
    assert run({"v": 1, "kind": "clarify", "slot": "to"}, "write to Ana") == {"kind": "clarify", "error": None, "why": "model", "slot": "to", "ops": None}
    assert run({"v": 1, "kind": "clarify", "ops": ["event-create", "remind"]}, "put it on the calendar") == {"kind": "clarify", "error": None, "why": "model", "slot": None, "ops": ["event-create", "remind"]}
    invalid(run({"v": 1, "kind": "clarify", "slot": "password"}, "x"), "E_SLOT_UNKNOWN")
    invalid(run({"v": 1, "kind": "clarify", "ops": ["remind", "approve"]}, "x"), "E_OP_UNKNOWN")          # a decision is not in the vocabulary
    invalid(run({"v": 1, "kind": "clarify", "ops": ["remind", "route"]}, "x"), "E_OP_UNKNOWN")
    invalid(run({"v": 1, "kind": "clarify", "ops": ["remind", "frobnicate"]}, "x"), "E_OP_UNKNOWN")


def test_route_and_none_pass_and_a_route_for_a_private_line_becomes_a_question():
    assert run({"v": 1, "kind": "none"}, "thanks") == {"kind": "none", "error": None}
    assert run({"v": 1, "kind": "route"}, "plan a three-day workshop for the new hires") == {"kind": "route", "error": None}
    private = "remind me to call Dana Thursday at 3pm"
    assert natural.private(private)
    got = run({"v": 1, "kind": "route"}, private)
    assert got["kind"] == "clarify" and got["why"] == "private-route"


def test_a_line_longer_than_the_limit_is_not_sent():
    long_plain = "plan the offsite " * 80
    long_private = "remind me to call Dana tomorrow at 3pm " * 40
    assert len(long_plain) > 1000 and len(long_private) > 1000 and not natural.private(long_plain) and natural.private(long_private)
    assert interp.precheck(long_plain) == {"kind": "route", "error": None}
    got = interp.precheck(long_private)
    assert got["kind"] == "clarify" and got["why"] == "long-line"
    assert interp.precheck("plan the offsite") is None
    assert run({"v": 1, "kind": "none"}, long_plain) == {"kind": "route", "error": None}          # check does not look at a model's object for a line that was never sent
    assert interp.precheck("x" * 1000) is None and interp.precheck("x" * 1001) is not None
    assert interp.precheck("\n\n" + "x" * 500 + "\n" + "x" * 499 + "\n") is None          # the length is that of the line as the model reads it


def test_an_empty_line_or_a_broken_frame_is_invalid():
    invalid(run({"v": 1, "kind": "none"}, "   "), "E_SHAPE")
    invalid(run({"v": 1, "kind": "none"}, "ok", {"v": 1, "items": [{"id": "x"}], "last": None}), "E_SHAPE")
    invalid(run({"v": 1, "kind": "none"}, "ok", {"v": 2, "items": [], "last": None}), "E_SHAPE")


# --- vacuity -------------------------------------------------------------------------------------------------------------------------------------------

def decision_is_grounded(decision, line) -> bool:
    """The oracle this file uses: an `op` decision carries only spans that are pieces of the line (or digits written in it)."""
    if decision["kind"] != "op":
        return True
    return all(span in line for span in decision["spans"].values())


def test_vacuity_a_decision_whose_span_is_not_in_the_line_fails_the_oracle():
    line = "write to ben@example.test"
    planted = {"kind": "op", "error": None, "op": "mail-send", "args": {"to": "mallory@example.test"}, "spans": {"to": "mallory@example.test"}, "time": None, "inherited": [], "time_disagree": False}
    assert not decision_is_grounded(planted, line)
    assert decision_is_grounded(run(op("mail-send", {"to": "ben@example.test"}), line), line)
    assert decision_is_grounded(run(op("mail-send", {"to": "mallory@example.test"}), line), line)

# --- the review of #495: M2, M4 and the minors ----------------------------------------------------------------------------------------------------------

def test_a_decision_or_widening_operation_is_refused_even_when_a_catalog_lists_it(monkeypatch):
    bad = json.loads(json.dumps(kit.CATALOG))
    bad["ops"] += [{"op": name, "class": "N", "what": "x", "slots": {}} for name in ("approve", "give-consent")]
    bad["refused"] = [row for row in bad["refused"] if row["op"] not in ("approve", "give-consent")]
    everything = kit.ALL_OPS | {"approve", "give-consent"}
    # A catalog that is not the served one is invalid, whatever it holds.
    invalid(interp.check(op("approve"), "approve it", None, bad, kit.NOW, kit.ZONE, everything), "E_SHAPE")
    # Even if it were taken for the served one, the two operations are still refused, by the classification and not by the catalog.
    monkeypatch.setattr(interp, "SERVED_SHA256", interp.catalog_sha256(bad))
    assert interp.check(op("approve"), "approve it", None, bad, kit.NOW, kit.ZONE, everything) == {"kind": "refuse", "error": None, "class": "D", "op": "approve"}
    assert interp.check(op("give-consent"), "consent", None, bad, kit.NOW, kit.ZONE, everything) == {"kind": "refuse", "error": None, "class": "G", "op": "give-consent"}


def test_a_catalog_that_differs_from_the_served_one_gives_no_decision():
    other = json.loads(json.dumps(kit.CATALOG))
    other["ops"][0]["what"] = "changed"
    for obj in ({"v": 1, "kind": "none"}, op("status"), {"v": 1, "kind": "route"}):
        invalid(interp.check(obj, "status", None, other, kit.NOW, kit.ZONE, kit.ALL_OPS), "E_SHAPE")


def test_a_confirm_is_the_models_only_when_the_line_says_the_same():
    frame = {"v": 1, "last": None, "items": [{"id": "i2", "kind": "reminder-confirm", "need": "confirm", "op": "remind", "age_s": 5}]}
    yes = {"v": 1, "kind": "answer", "answers_item": "i2", "confirm": "yes"}
    no = dict(yes, confirm="no")
    for line, obj, want in (("yes", yes, "answer"), ("sim", yes, "answer"), ("no", no, "answer"), ("não", no, "answer"), ("what is the weather like", yes, "clarify"),
                            ("yes", no, "clarify"), ("no", yes, "clarify"), ("send the contacts to ben@example.test", yes, "clarify")):
        got = interp.check(obj, line, frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)
        assert got["kind"] == want, (line, obj["confirm"], got)
        if want == "clarify":
            assert got["why"] == "model" and got["item"] == "i2" and "op" not in got
    # The answer's own span is taken out before the line is read.
    slot_frame = {"v": 1, "last": None, "items": [{"id": "i2", "kind": "reminder-confirm", "need": "confirm", "op": "remind", "age_s": 5}]}
    with_span = {"v": 1, "kind": "answer", "answers_item": "i2", "confirm": "yes", "slot": "when", "span": "tomorrow at 3pm", "time_iso": "2026-10-21T15:00", "weekday": "wed"}
    assert interp.check(with_span, "yes, tomorrow at 3pm", slot_frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)["kind"] == "answer"
    assert interp.check(with_span, "tomorrow at 3pm", slot_frame, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS)["kind"] == "clarify"


def test_every_answer_about_an_item_with_an_op_is_checked_against_the_policy():
    frame = {"v": 1, "last": None, "items": [kit.item(), {"id": "i2", "kind": "reminder-confirm", "need": "confirm", "op": "remind", "age_s": 5},
                                             {"id": "i3", "kind": "choice", "need": "option", "options": 2, "age_s": 5}]}
    to = {"v": 1, "kind": "answer", "answers_item": "i1", "slot": "to", "span": "ben@example.test"}
    yes = {"v": 1, "kind": "answer", "answers_item": "i2", "confirm": "yes"}
    pick = {"v": 1, "kind": "answer", "answers_item": "i3", "option": 1}
    for allowed in (set(), {"status"}, None):
        assert interp.check(to, "to ben@example.test", frame, kit.CATALOG, kit.NOW, kit.ZONE, allowed) == {"kind": "refuse_policy", "error": None, "op": "mail-send"}
        assert interp.check(yes, "yes", frame, kit.CATALOG, kit.NOW, kit.ZONE, allowed) == {"kind": "refuse_policy", "error": None, "op": "remind"}
    assert interp.check(pick, "the first", frame, kit.CATALOG, kit.NOW, kit.ZONE, set())["kind"] == "answer"          # a choice has no op of its own
    assert interp.check(to, "to ben@example.test", frame, kit.CATALOG, kit.NOW, kit.ZONE, {"mail-send"})["kind"] == "answer"


def test_clarify_names_only_operations_the_policy_allows():
    both = {"v": 1, "kind": "clarify", "ops": ["event-create", "remind"]}
    assert run(both, "put it on the calendar", allowed={"event-create", "remind"})["ops"] == ["event-create", "remind"]
    assert run({"v": 1, "kind": "clarify", "ops": ["event-create", "remind", "status"]}, "x", allowed={"event-create", "status"})["ops"] == ["event-create", "status"]
    assert run(both, "put it on the calendar", allowed={"remind"}) == {"kind": "refuse_policy", "error": None, "op": "event-create"}
    assert run(both, "put it on the calendar", allowed=set())["kind"] == "refuse_policy"
    assert interp.check(both, "x", None, kit.CATALOG, kit.NOW, kit.ZONE, None)["kind"] == "refuse_policy"


def test_a_word_slot_must_also_be_as_typed_not_only_after_a_compatibility_fold():
    assert natural.check_operation("mail-send", {"to": "ben@example.test", "body": "hi"}, None, "send hi to ｂｅｎ@ｅｘａｍｐｌｅ.ｔｅｓｔ")["ok"]          # the router's rule folds
    invalid(run(op("mail-send", {"to": "ben@example.test", "body": "hi"}), "send hi to ｂｅｎ@ｅｘａｍｐｌｅ.ｔｅｓｔ"), "E_SPAN")
    invalid(run(op("mail-send", {"to": "ben@firm.test", "body": "hi"}), "send hi to ben@ﬁrm.test"), "E_SPAN")
    assert run(op("mail-send", {"to": "ben@firm.test", "body": "hi"}), "send hi to ben@firm.test")["kind"] == "op"


def test_an_inherited_span_must_come_from_the_last_request_of_the_same_operation():
    frame = {"v": 1, "items": [], "last": {"op": "mail-send", "words": {"to": "ben@example.test", "subject": "the invoice"}, "age_s": 10}}
    same = op("mail-send", {"body": "hi"}, inherit={"to": "ben@example.test"})
    assert run(same, "and send hi", frame)["inherited"] == ["to"]
    other = op("mail-draft", {"body": "hi"}, inherit={"to": "ben@example.test"})
    invalid(run(other, "and draft hi", frame), "E_INHERIT")
    assert natural.NATURAL["mail-draft"]["slots"].get("to")

"""The kind `question` of the interpreter's protocol (package ANY-QUESTION Q1, runtime/interpreter.py `_shape` and `check`): what code believes of a model's question about a card, about what was done, about
what the assistant can do, or about anything else.

Pure: no model, no store, no clock but the kit's. Held here, each from the protocol's rules and this file's own literals: every valid combination of `about`, `field` and `op` gives the decision dict
exactly; every invalid shape gives the clarify `invalid` with `E_SHAPE`; an op outside the catalog gives `E_OP_UNKNOWN`; an op of the refused list (`approve`) is accepted; `ops_interpret.decide` of the JSON
text gives the same decision; `ops_event_revise.read_answer` hands a question back as it is; and one object of each of the five older kinds gives the decision it gave before the kind existed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interpreter_question_kind.py
"""
from __future__ import annotations

import json

import pytest

import interpreter_kit as kit
import standin_tree as st

interp = st.load("interpreter")
ops_interpret = st.load("ops_interpret")
event_revise = st.load("ops_event_revise")

LINE = "a plain line about it"
FIELDS = ["title", "when", "place", "to", "from", "subject", "approve", "other"]


def run(obj, line=LINE, allowed=None):
    return interp.check(obj, line, None, kit.CATALOG, kit.NOW, kit.ZONE, kit.ALL_OPS if allowed is None else allowed)


def question(about, **more):
    return {"v": 1, "kind": "question", "about": about, **more}


def decision(about, field=None, op=None):
    return {"kind": "question", "error": None, "about": about, "field": field, "op": op}


def invalid(got, code="E_SHAPE"):
    assert got == {"kind": "clarify", "error": code, "why": "invalid", "slot": None, "ops": None}, got


@pytest.mark.parametrize("field", FIELDS)
def test_a_question_about_a_card_with_each_field_is_the_decision_with_that_field(field):
    assert run(question("card", field=field)) == decision("card", field=field)


@pytest.mark.parametrize("op", ["mail-send", "event-create", "remind", "todo-add", "cancel", "approve"])
def test_a_question_about_what_was_done_names_an_operation_of_the_catalog_or_none(op):
    assert run(question("done", op=op)) == decision("done", op=op)
    assert run(question("done")) == decision("done")


@pytest.mark.parametrize("op", ["mail-archive", "event-change", "mail-reply", "approve", "reject"])
def test_a_question_about_what_can_be_done_names_an_operation_of_the_catalog_or_of_the_refused_list(op):
    assert run(question("can", op=op)) == decision("can", op=op)


def test_a_question_about_anything_else_carries_nothing():
    assert run(question("other")) == decision("other")


@pytest.mark.parametrize("obj", [
    question("card"),                                  # a card question needs its field
    question("card", field="colour"),                  # a field outside the eight
    question("card", field=3),
    question("card", field="when", op="remind"),       # a card question has no op
    question("done", field="when"),                    # a field only belongs to a card
    question("can"),                                   # a `can` needs its op
    question("can", field="when", op="mail-send"),
    question("other", op="remind"),
    question("other", field="when"),
    question("weather"),                               # an `about` outside the four
    question(None),
    question(["card"]),
    question("done", op="Mail Send"),                  # an op that does not look like one
    question("done", op=5),
    {"v": 1, "kind": "question"},                      # no `about`
    question("card", field="when", extra=1),           # a key outside the kind
])
def test_a_shape_the_kind_does_not_have_is_the_invalid_clarify(obj):
    invalid(run(obj))


@pytest.mark.parametrize("about,more", [("done", {"op": "fly-to-moon"}), ("can", {"op": "fly-to-moon"})])
def test_an_operation_outside_the_catalog_is_unknown(about, more):
    invalid(run(question(about, **more)), "E_OP_UNKNOWN")


def test_the_policy_is_not_asked_by_a_question():
    assert run(question("can", op="mail-send"), allowed=set()) == decision("can", op="mail-send")
    assert run(question("card", field="to"), allowed=None) == decision("card", field="to")


def test_decide_of_the_json_text_gives_the_same_decision():
    text = json.dumps(question("card", field="place"))
    got = ops_interpret.decide(LINE, text, kit.NOW, kit.ZONE, set(), None)
    assert got == decision("card", field="place")
    fenced = "```json\n" + json.dumps(question("can", op="approve")) + "\n```"
    assert ops_interpret.decide(LINE, fenced, kit.NOW, kit.ZONE, set(), None) == decision("can", op="approve")
    invalid(ops_interpret.decide(LINE, json.dumps(question("card")), kit.NOW, kit.ZONE, set(), None))


def test_the_card_call_hands_a_question_back_unchanged():
    for obj, want in ((question("card", field="when"), decision("card", field="when")), (question("can", op="mail-send"), decision("can", op="mail-send")), (question("other"), decision("other"))):
        assert event_revise.read_answer(json.dumps(obj), LINE, {}, kit.NOW, kit.ZONE, set()) == want


def test_the_kind_is_the_sixth_of_the_protocol_and_the_older_five_are_where_they_were():
    assert interp.KINDS == ("op", "answer", "clarify", "route", "none", "question")
    assert interp.KEYS["question"] == ({"v", "kind", "about"}, {"field", "op"})
    assert run({"v": 1, "kind": "none"}) == {"kind": "none", "error": None}
    assert run({"v": 1, "kind": "route"}) == {"kind": "route", "error": None}
    assert run({"v": 1, "kind": "clarify", "slot": "to"}) == {"kind": "clarify", "error": None, "why": "model", "slot": "to", "ops": None}
    assert run({"v": 1, "kind": "op", "op": "reminders", "slots": {}}) == {"kind": "op", "error": None, "op": "reminders", "args": {}, "spans": {}, "time": None, "inherited": [], "time_disagree": False}
    assert run({"v": 1, "kind": "answer", "answers_item": "i1"}) == {"kind": "clarify", "error": "E_ITEM_UNKNOWN", "why": "invalid", "slot": None, "ops": None}

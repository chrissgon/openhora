"""ACEITE-37 (limit L64): a bare no in question form drops no plan. The row `plan-bare-word` of runtime/ops_turn.py answers a bare yes or no that the bridge did not take as the answer to "Posso?" (the
question was not the last message): "nao" drops the plan, "sim" keeps it with PLAN_NOT_LAST. "nao?" asks something and is no answer, so the row does not take it, the plan waits, and the line goes on to the
model like any free line. The world is the one of test_plan_confirm.py (a real plan, the model stood in); every expectation is a literal of this file, and each rule has a vacuity case.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_bare_word_question.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from plan_confirm_kit import OWNER, ops, phrases, say, spy_read, world, rig  # noqa: F401
from closed_heads import closed_heads, tier1_forms  # noqa: F401

pytestmark = pytest.mark.usefixtures("tier1_forms")

ops_turn = st.load("ops_turn")
ops_core = st.load("ops_core")


def plan_open(rig):
    spy_read(rig)
    say(rig, OWNER, "mostra minha agenda")
    assert ops.plan_live(rig.world["path"], OWNER) is not None
    return rig.world["path"], ops_core.context(rig.world["path"])


def row(rig, path, ctx, line):
    return ops_turn.plan_bare_word(path, ctx, line, "messaging", OWNER, {}, None)


def test_a_bare_no_drops_the_plan_and_a_bare_yes_keeps_it(rig):
    path, ctx = plan_open(rig)
    kept = row(rig, path, ctx, "sim")
    assert kept[0] == phrases.text("PLAN_NOT_LAST", rig.cfg) and ops.plan_live(path, OWNER) is not None
    dropped = row(rig, path, ctx, "nao")
    assert dropped[0] == phrases.text("PLAN_DROPPED", rig.cfg) and ops.plan_live(path, OWNER) is None


@pytest.mark.parametrize("line", ["nao?", "n\u00e3o?", "no?", "nao❓", "cancela?"])
def test_a_no_in_question_form_is_not_taken_and_the_plan_waits(rig, line):
    path, ctx = plan_open(rig)
    assert row(rig, path, ctx, line) is None and ops.plan_live(path, OWNER) is not None
    assert ops_turn._bare_plan_word(ctx, line, "messaging", OWNER, True) is False      # nor does code claim it: it goes on, with the router's lock
    assert ops_turn._bare_plan_word(ctx, "nao", "messaging", OWNER, True) is True


def test_vacuity_with_the_question_rule_off_the_no_in_question_form_drops_the_plan(rig, monkeypatch):
    path, ctx = plan_open(rig)
    monkeypatch.setattr(ops_turn.card_words, "question_form", lambda line: False)
    dropped = row(rig, path, ctx, "nao?")
    assert dropped[0] == phrases.text("PLAN_DROPPED", rig.cfg) and ops.plan_live(path, OWNER) is None
    assert ops_turn._bare_plan_word(ctx, "nao?", "messaging", OWNER, True) is True


def test_the_whole_turn_of_a_no_in_question_form_asks_the_model_and_says_nothing_of_a_dropped_plan(rig):
    path, ctx = plan_open(rig)
    out = say(rig, OWNER, "nao?")
    assert out["reply"] != phrases.text("PLAN_DROPPED", rig.cfg) and rig.calls, "the model was asked"

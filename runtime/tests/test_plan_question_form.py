"""PLAN-QUESTION-FORM (limit L65, 2026-10-30): a line in question form is neither the OK nor the refusal of a plan. The maintainer's decision, after ACEITE-37 made `card_words.question_form` the
rule for cards: "sim?" on a "Posso?" that is the last message no longer starts the confirmed call, and "nao?" on it no longer takes the no-word path; both go on to the model as any free line, and (the
existing rule) any other line ends a waiting plan. Plain "sim", "sim!", "sim." and "nao" and the Yes button stay as they were. The two readers are the kind `plan-confirm` of the bridge
(runtime/messaging_turn.py `plan_confirm_applies`) and the row `plan-bare-word` (runtime/ops_turn.py `_bare_plan_kind`). The stop of a running search by "nao?" (`research-run`) is not touched. The real
bridge over the real operations layer (plan_bridge_kit.py); each test reads the one place a read runs (its own literal count) and the model's stand-in calls. Each rule has a vacuity case. Offline;
invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_question_form.py
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import standin_tree as st
from plan_bridge_kit import OWNER_ID, OWNER_KEY, brig, bridge, ops, phrases, rig, wait_for, world  # noqa: F401
from test_service import WAIT  # noqa: F401  (named here as test_messaging_plan_confirm.py does: the selector follows the importers of a changed test file)
from closed_heads import closed_heads, tier1_forms  # noqa: F401

pytestmark = pytest.mark.usefixtures("tier1_forms")

messaging_turn = st.load("messaging_turn")
ops_turn = st.load("ops_turn")
ops_core = st.load("ops_core")

QUESTIONS = ["sim?", "sim ?", "sim❓", "n\u00e3o?", "pode?", "tudo bem? sim", "poderia"]      # "poderia" is no yes word of the tables: it is here as the lead of a question, which goes on as it always did
TAKEN_WITHOUT_THE_RULE = [q for q in QUESTIONS if q != "poderia"]
FORMS = ["sim", "sim!", "sim."]
NEVER = SimpleNamespace(question_form=lambda line: False)      # the rule, switched off in one module


def t(brig, key):
    return phrases.text(key, brig.rig.cfg)


def reads(brig):
    return [r["name"] for r in brig.reads]


def live(brig):
    return ops.plan_live(brig.rig.world["path"], OWNER_KEY)


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_line_in_question_form_on_a_last_plan_confirms_nothing_and_goes_to_the_model(brig, line):
    brig.ask()
    before = len(brig.texts())
    brig.say(line)
    assert wait_for(lambda: len(brig.texts()) > before and len(brig.rig.calls) == 1) and brig.idle()
    assert reads(brig) == [], "no read ran"
    assert len(brig.rig.calls) == 1, "the model was asked, once, like any free line"
    sent = brig.texts()[before:]
    assert t(brig, "PLAN_DROPPED") not in sent and t(brig, "PLAN_NOT_LAST") not in sent, "neither the refusal nor the not-last sentence answered it"
    assert live(brig) is None, "any other line ends a waiting plan"


@pytest.mark.parametrize("line", TAKEN_WITHOUT_THE_RULE)
def test_vacuity_with_the_bridge_rule_off_the_line_in_question_form_is_taken_as_the_word(brig, monkeypatch, line):
    brig.ask()
    monkeypatch.setattr(messaging_turn, "card_words", NEVER)
    brig.say(line)
    assert brig.idle() and brig.rig.calls == [], "the bridge took it: the model was not asked"
    if line.startswith("n"):
        assert t(brig, "PLAN_DROPPED") in brig.texts() and live(brig) is None and reads(brig) == []
    else:
        assert wait_for(lambda: reads(brig) == ["items"]), "the same counter that is empty above sees the read when the rule is gone"


@pytest.mark.parametrize("line", FORMS)
def test_a_plain_sim_still_runs_the_plan_that_is_last(brig, line):
    brig.ask()
    brig.say(line)
    assert wait_for(lambda: reads(brig) == ["items"]) and brig.idle()
    assert reads(brig) == ["items"] and brig.rig.calls == [] and live(brig) is None


def test_the_sim_button_still_runs_the_plan(brig):
    brig.ask()
    brig.tap(brig.question_actions()["yes"])
    assert wait_for(lambda: reads(brig) == ["items"]) and brig.idle()
    assert reads(brig) == ["items"] and brig.rig.calls == []


def test_a_plain_nao_still_drops_the_plan_with_no_model(brig):
    brig.ask()
    brig.say("n\u00e3o")
    assert wait_for(lambda: t(brig, "PLAN_DROPPED") in brig.texts()) and brig.idle()
    assert reads(brig) == [] and brig.rig.calls == [] and live(brig) is None


# --- the row of the operations layer: a line the bridge did not take -----------------------------------------------------------------------------------


def row(rig, line):
    path = rig.world["path"]
    return ops_turn.plan_bare_word(path, ops_core.context(path), line, "messaging", OWNER_KEY, {}, None)


@pytest.mark.parametrize("line", ["sim?", "sim ?", "sim❓", "pode?", "poderia"])
def test_the_row_of_a_plan_not_last_does_not_answer_a_yes_in_question_form_and_the_plan_waits(brig, line):
    brig.ask()
    assert row(brig.rig, line) is None and live(brig) is not None
    ctx = ops_core.context(brig.rig.world["path"])
    assert ops_turn._bare_plan_word(ctx, line, "messaging", OWNER_KEY, True) is False
    kept = row(brig.rig, "sim")
    assert kept[0] == t(brig, "PLAN_NOT_LAST") and live(brig) is not None, "a plain sim is still told that the question is not the last message"


def test_vacuity_with_the_rule_off_in_the_row_a_sim_in_question_form_is_told_it_is_not_last(brig, monkeypatch):
    brig.ask()
    monkeypatch.setattr(ops_turn, "card_words", NEVER)
    out = row(brig.rig, "sim?")
    assert out[0] == t(brig, "PLAN_NOT_LAST")

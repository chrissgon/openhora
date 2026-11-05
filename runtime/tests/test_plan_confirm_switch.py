"""The switch of D5 (package BL2a shipped `plan_confirm.ACTIVE = False`; the package of the messaging bridge, BL2b, sets it True with the dispatcher that can take a "sim" to the question).

With it True a tier-1 read on a messaging app asks "Shall I go ahead?" before it runs, and the S20 verb check of the vet of decision numbers (now `turn_gate.number_believed`) is gone (the number rule stays): a line the verb lists refused
("nao cancela o pedido 3") now meets the question, and nothing runs before the person's "sim" (the dispatcher's own tests are test_messaging_plan_confirm.py). With it False (a test may set it) nothing
is asked: the state of the integration checkout between BL2a and BL2b. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_confirm_switch.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
from plan_confirm_kit import OWNER, op, ops, ops_natural, phrases, plan_confirm, say, text, world, rig  # noqa: F401
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did


def test_the_committed_switch_is_on():
    assert plan_confirm.ACTIVE is True, "BL2b switches D5 on with the dispatcher on the messaging bridge"


def test_with_the_switch_on_a_tier_1_read_asks_first_and_runs_nothing_before_the_ok(rig):
    reads = []
    rig.monkeypatch.setattr(ops_natural, "_read", lambda project, ctx, name, row, args, channel, sender: reads.append(name) or "READ-REPLY")
    out = say(rig, OWNER, "mostra minha agenda")
    assert reads == [] and out["plan_confirm"]["op"] == "items" and ops.plan_live(rig.world["path"], OWNER) is not None


def test_with_the_switch_off_a_tier_1_read_runs_at_once_and_no_plan_is_kept(rig, monkeypatch):
    monkeypatch.setattr(plan_confirm, "ACTIVE", False)
    reads = []
    monkeypatch.setattr(ops_natural, "_read", lambda project, ctx, name, row, args, channel, sender: reads.append(name) or "READ-REPLY")
    out = say(rig, OWNER, "mostra minha agenda")
    assert out["reply"] == "READ-REPLY" and reads == ["items"] and "plan_confirm" not in out and ops.plan_live(rig.world["path"], OWNER) is None
    state = say(rig, OWNER, "como estamos?")
    assert "plan_confirm" not in state and pk.said(state["reply"], "STATE_WAITS")


@pytest.mark.parametrize("line", ["nao cancela o pedido 3", "quero cancelar o pedido 3", "no need to cancel request 3", "se der erro, cancela o pedido 3", "devo cancelar o pedido 3?"])
def test_a_line_the_verb_lists_refused_now_meets_the_question_and_nothing_runs_before_the_ok(rig, monkeypatch, line):
    seen = []
    monkeypatch.setattr(ops_natural, "_typed", lambda *a, **k: seen.append(a) or "TYPED")
    rig.says["text"] = op("cancel", {"id": "3"})
    out = say(rig, OWNER, line)
    assert seen == [] and out["reply"] != phrases.text("IX_ASK_AGAIN", rig.cfg) and out["plan_confirm"]["op"] == "cancel"      # the verb check is gone: the person reads the sentence and says no
    assert ops.plan_live(rig.world["path"], OWNER)["op"] == "cancel"

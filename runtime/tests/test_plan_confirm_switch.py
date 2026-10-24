"""The switch of D5 (package BL2a ships `plan_confirm.ACTIVE = False`; the package of the messaging bridge sets it True with the dispatcher that can take a "sim" to the question).

While it is False no question is asked (the bridge could not take an answer to one) and the S20 verb check of `command_words.vet` stays: the state of the integration checkout between the two
packages is today's behaviour, byte for byte. The package that sets `ACTIVE` flips the first assertion here and deletes the verb lists and their tests. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_confirm_switch.py
"""
from __future__ import annotations

import pytest

from plan_confirm_kit import OWNER, op, ops, ops_natural, phrases, plan_confirm, say, text, world, rig  # noqa: F401


def test_the_committed_switch_is_off():
    assert plan_confirm.ACTIVE is False, "BL2a ships D5 switched off; the bridge's package switches it on"


def test_with_the_switch_off_a_tier_1_read_runs_at_once_and_no_plan_is_kept(rig, monkeypatch):
    monkeypatch.setattr(plan_confirm, "ACTIVE", False)
    reads = []
    monkeypatch.setattr(ops_natural, "_read", lambda project, ctx, name, row, args, channel, sender: reads.append(name) or "READ-REPLY")
    out = say(rig, OWNER, "mostra minha agenda")
    assert out["reply"] == "READ-REPLY" and reads == ["items"] and "plan_confirm" not in out and ops.plan_live(rig.world["path"], OWNER) is None
    state = say(rig, OWNER, "como estamos?")
    assert "plan_confirm" not in state and "What waits for you" in state["reply"]


def test_with_the_switch_off_a_negated_act_is_refused_by_the_verb_check_as_today(rig, monkeypatch):
    monkeypatch.setattr(plan_confirm, "ACTIVE", False)
    seen = []
    monkeypatch.setattr(ops_natural, "_typed", lambda *a, **k: seen.append(a) or "TYPED")
    rig.says["text"] = op("cancel", {"id": "3"})
    out = say(rig, OWNER, "nao cancela o pedido 3")
    assert out["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg) and seen == [] and "plan_confirm" not in out
    plain = say(rig, OWNER, "quero cancelar o pedido 3")      # the verb lists refuse this one too: the lists are what D5 replaces
    assert plain["reply"] == phrases.text("IX_ASK_AGAIN", rig.cfg) and seen == []

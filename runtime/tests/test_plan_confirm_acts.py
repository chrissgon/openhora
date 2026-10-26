"""The acts asked in words ask first (package BL2a, limits L54 and L65): cancel, stop-task, retry, routine-pause, attachment-add, attachment-discard, reject and release run only after the
person's OK of the sentence code wrote from the call, and the number rule stays: a model's decision is believed only for the one number WRITTEN in the line (`turn_gate.number_believed`).

The verb lists of S20 went with the switch (BL2b set `plan_confirm.ACTIVE`; before it these tests ran with D5 on and the verb test off): a
line the lists refused ("quero cancelar o pedido 3", "nao cancela o pedido 3") now meets the question instead, and the question is where the person says no. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_confirm_acts.py
"""
from __future__ import annotations

import pytest

from plan_confirm_kit import (ASKER, OFF, OWNER, ok_of, op, ops, ops_natural, ops_say, phrases, plan_confirm, pending_items, question, say, text, world, rig)  # noqa: F401


@pytest.fixture
def typed(rig, monkeypatch):
    """The command a plan hands over once it is confirmed, recorded instead of run (`ops_say._say_command` is the one place a table command is called)."""
    rig.said_commands = []
    monkeypatch.setattr(ops_say, "_say_command", lambda project, ctx, line, channel, line_id, sender=None: rig.said_commands.append(line) or ("COMMAND-REPLY", None, None, False, None))
    return rig


def decision_open(rig):
    """The number of a real open decision (the stand-in router asks which market first)."""
    return ops.say(rig.world["path"], "Which market first?", channel="page")["pending_id"]


def test_a_cancel_the_model_chose_asks_first_and_the_ok_hands_the_typed_command_over(typed):
    typed.says["text"] = op("cancel", {"id": "3"})
    out = say(typed, OWNER, "quero cancelar o pedido 3")
    assert out["reply"] == question(typed, "UNDERSTOOD_CANCEL", id=3) and out["plan_confirm"]["op"] == "cancel"
    assert typed.said_commands == [], "nothing ran before the OK"
    done = say(typed, OWNER, "sim", plan_ok=ok_of(out))
    assert typed.said_commands == ["/cancel 3"] and done["typed"] == "/cancel 3" and done["reply"] == "COMMAND-REPLY"


def test_a_tier_1_reject_of_an_open_decision_asks_and_a_closed_one_gets_its_own_sentence_and_no_plan(typed):
    number = decision_open(typed)
    out = say(typed, OWNER, f"rejeite a pergunta {number}")
    assert out["reply"] == question(typed, "UNDERSTOOD_REJECT", id=number) and out["plan_confirm"]["op"] == "reject"
    assert "typed" not in out, "nothing was handed over before the OK"
    done = say(typed, OWNER, "sim", plan_ok=ok_of(out))
    assert done["typed"] == f"/reject {number}" and "plan_confirm" not in done
    none = say(typed, OWNER, "rejeite a pergunta 25")      # no such decision: the one sentence, never a question about nothing
    assert none["reply"] == phrases.text("NAT_NO_DECISION", typed.cfg, id=25) and "plan_confirm" not in none and ops.plan_live(typed.world["path"], OWNER) is None


def test_vacuity_without_the_check_in_the_decision_the_reject_is_handed_over_at_once(typed, monkeypatch):
    number = decision_open(typed)
    real = plan_confirm.needed
    monkeypatch.setattr(plan_confirm, "needed", lambda ctx, name, channel, sender, confirmed: False if name == "reject" else real(ctx, name, channel, sender, confirmed))
    out = say(typed, OWNER, f"rejeite a pergunta {number}")
    assert out["typed"] == f"/reject {number}" and "plan_confirm" not in out


def test_a_negated_line_shows_its_plan_and_calls_nothing_and_dropping_the_plan_ends_it(typed):
    """"nao cancela o pedido 3": the verb lists would have refused it; now the person reads "cancel request #3" and says no."""
    typed.says["text"] = op("cancel", {"id": "3"})
    out = say(typed, OWNER, "nao cancela o pedido 3")
    assert out["reply"] == question(typed, "UNDERSTOOD_CANCEL", id=3) and typed.said_commands == []
    assert ops.plan_drop(typed.world["path"], OWNER) is True
    assert say(typed, OWNER, "sim", plan_ok=ok_of(out))["reply"] == phrases.text("PLAN_GONE", typed.cfg) and typed.said_commands == []


def test_the_number_rule_stays_a_line_with_two_numbers_or_none_asks_which_and_no_plan(typed):
    typed.says["text"] = op("reject")
    two = say(typed, OWNER, "rechaza las preguntas 3 y 4")
    assert two["reply"] == phrases.text("NAT_WHICH_DECISION", typed.cfg) and "plan_confirm" not in two
    typed.says["text"] = op("cancel", {"id": "3"})
    other = say(typed, OWNER, "cancela el pedido 3 y el 4")      # the model names 3, the line holds two numbers: not believed
    assert other["reply"] == phrases.text("NAT_ASK_ID", typed.cfg) and "plan_confirm" not in other
    none = say(typed, OWNER, "cancela la solicitud")      # no number written
    assert "plan_confirm" not in none
    assert typed.said_commands == [] and ops.plan_live(typed.world["path"], OWNER) is None


def test_an_act_that_lacks_its_number_asks_for_it_and_never_a_plan(typed):
    out = say(typed, OWNER, "cancela o pedido")      # a tier-1 form with no number: the typed command's own sentence
    assert "plan_confirm" not in out and typed.said_commands == []


def test_a_sender_without_the_right_to_the_act_is_refused_before_any_question(typed):
    typed.says["text"] = op("cancel", {"id": "3"})
    out = say(typed, ASKER, "quero cancelar o pedido 3")      # `asker` holds no brake
    assert "plan_confirm" not in out and ops.plan_live(typed.world["path"], ASKER) is None and typed.said_commands == []


def test_the_acts_ask_even_for_a_sender_who_holds_confirm_reads_off(typed):
    """`off` holds `confirm-reads-off` but not the brakes: the policy check comes first, and the group never reaches an act."""
    out = say(typed, OFF, "cancela o pedido 3")
    assert "plan_confirm" not in out and typed.said_commands == []
    assert plan_confirm.needed({"cfg": typed.cfg}, "cancel", "messaging", OFF, False) is True

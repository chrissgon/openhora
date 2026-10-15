"""Tests of the effect gate of the step engine (runtime/steps.py, package P8) and of the rule that a review is harmless to pass: a kind
whose last step is a Gate opens an `effect` decision with the hash of the exact content and executes nothing; an effect answered
and not approved starts the task over from the step that reads; and a kind that declares a step performing an external effect
itself after a stop, or while it starts on its own, is refused when it is registered. The kinds are invented. A fake task stands in
for the store. No process, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_steps_gate.py
"""
from __future__ import annotations

import hashlib

import pytest

import standin_tree as st
from test_steps_engine import FakeTask

steps = st.load("steps")

HASH = hashlib.sha256(b"the exact content").hexdigest()


def gated(calls, name="gated", redo="read", extra=None):
    """An invented kind: read, think, and a gate `send` that opens an effect for the content."""
    def step(label, result):
        def run(ctx, state):
            calls.append(label)
            return result
        return run

    def open_effect(ctx, state):
        calls.append("open")
        return {"title": "Send it", "body": "The content, whole.", "payload_sha256": HASH, "payload": {"effect": {"bytes": 3}}}

    fields = dict(name=name, order=("read", "think", "send"), executors={"read": step("read", {"seen": 1}), "think": step("think", {"ok": True})},
                  gates={"send": steps.Gate(word="write", open=open_effect, redo=redo)})
    fields.update(extra or {})
    return steps.Kind(**fields)


def run(kind, task, state=None):
    state = state if state is not None else steps.new_state(kind)
    return steps.run(task.context({}), kind, state), state


# --- the gate ----------------------------------------------------------------------------------------------------------------------


def test_the_gate_opens_an_effect_decision_with_the_hash_of_the_content_and_executes_nothing():
    calls, task = [], FakeTask()
    kind = gated(calls)
    out, state = run(kind, task)
    assert calls == ["read", "think", "open"] and out["ok"] is True and out["stopped"] == "send"
    assert out["steps"] == {"read": "done", "think": "done", "send": "waiting"} and task.state == "waiting"
    decision = task.decisions_list[0]
    assert decision["kind"] == "effect" and decision["title"] == "Send it" and decision["body"] == "The content, whole."
    assert decision["payload"] == {"effect": {"bytes": 3}, "step": {"kind": "gated", "step": "send"}, "cycle": 0, "gate": "write"}
    assert state["decisions"]["send"] == decision["id"] == out["pending"]


def test_the_decision_carries_the_hash_in_the_pending_the_store_is_given():
    seen = {}

    class Spy(FakeTask):
        def move(self, word, note, pending, resolve, state):
            seen.update(pending or {})
            return super().move(word, note, pending, resolve, state)

    run(gated([]), Spy())
    assert seen["kind"] == "effect" and seen["payload_sha256"] == HASH


def test_an_effect_the_person_approved_is_recorded_done_and_runs_nothing_again():
    calls, task = [], FakeTask()
    kind = gated(calls)
    out, state = run(kind, task)
    decision = task.decisions_list[0]
    decision.update(status="resolved", resolution="approved")
    task.state = "running"
    out = steps.run(task.context({}), kind, state)
    assert calls == ["read", "think", "open"], "an approved effect was executed by the approval, not by the engine"
    assert steps.step_status(state, "send") == "done" and state["handled"]["send"] == decision["id"]


def test_an_effect_answered_and_not_approved_starts_over_from_the_step_that_reads_and_asks_again():
    calls, task = [], FakeTask()
    kind = gated(calls)
    out, state = run(kind, task)
    first = task.decisions_list[0]
    first.update(status="resolved", resolution="answered", answer="the page changed")
    task.state = "running"
    out = steps.run(task.context({}), kind, state)
    assert calls == ["read", "think", "open", "read", "think", "open"], "read again, then a new effect"
    assert out["stopped"] == "send" and len(task.decisions_list) == 2 and out["pending"] == task.decisions_list[1]["id"]
    second = task.decisions_list[1]
    assert second["payload"]["cycle"] == 1 and first["payload"]["cycle"] == 0, "a decision of the cycle before never passes the new gate"
    assert state["cycle"] == 1


def test_an_answer_that_is_the_old_decisions_does_not_pass_the_new_gate():
    calls, task = [], FakeTask()
    kind = gated(calls)
    out, state = run(kind, task)
    task.decisions_list[0].update(status="resolved", resolution="answered", answer="again")
    task.state = "running"
    steps.run(task.context({}), kind, state)
    task.state = "running"
    out = steps.run(task.context({}), kind, state)       # run again with the new decision still open: it is asked, not passed
    assert out["stopped"] == "send" and steps.step_status(state, "send") == "waiting"


def test_the_redo_step_can_be_a_later_one_and_earlier_steps_are_kept():
    calls, task = [], FakeTask()
    kind = gated(calls, redo="think")
    out, state = run(kind, task)
    task.decisions_list[0].update(status="resolved", resolution="answered", answer="x")
    task.state = "running"
    steps.run(task.context({}), kind, state)
    assert calls == ["read", "think", "open", "think", "open"]


# --- what a kind may declare -------------------------------------------------------------------------------------------------------


def refused(**fields):
    base = dict(name="odd", order=("a", "b", "c"), executors={"a": lambda c, s: {}, "b": lambda c, s: {}, "c": lambda c, s: {}})
    base.update(fields)
    with pytest.raises(ValueError) as why:
        steps.check_kind(steps.Kind(**base))
    return str(why.value)


def decision(ctx, state):
    return {"title": "t", "body": "b"}


def gate(redo="a", word="write"):
    return steps.Gate(word=word, open=lambda c, s: {"title": "t", "body": "b", "payload_sha256": HASH}, redo=redo)


REVIEWED = dict(order=("a", "review", "c"), executors={"a": lambda c, s: {}, "c": lambda c, s: {}}, stops=("review",),
                decisions={"review": decision})


def test_limit_28_a_step_that_performs_an_external_effect_after_a_review_is_refused_when_the_kind_is_registered():
    why = refused(**REVIEWED, effectful=("c",))
    assert "after a stop" in why and "effect gate" in why
    with pytest.raises(ValueError):
        steps.register(steps.Kind(name="odd-register", effectful=("c",), **REVIEWED))
    assert "odd-register" not in steps.REGISTRY


def test_a_step_before_the_review_may_say_it_is_effectful_only_in_a_kind_that_does_not_start_on_its_own():
    steps.check_kind(steps.Kind(name="ok-effect", effectful=("a",), **REVIEWED))
    assert "starts on its own" in refused(effectful=("a",), unattended=True)


def test_an_effectful_step_after_the_gate_or_without_an_executor_or_a_side_step_is_refused():
    assert "effectful step" in refused(effectful=("zzz",))
    assert "effectful step" in refused(effectful=("a",), side_steps={"a": lambda s: True})
    assert "effectful step" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("a")}, effectful=("b",))


def test_a_gate_is_the_last_step_with_no_executor_an_earlier_redo_and_there_is_at_most_one():
    steps.check_kind(steps.Kind(name="fine", order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("a")}))
    assert "the gate" in refused(gates={"a": gate("a")})                                   # not the last step
    assert "the gate" in refused(gates={"c": gate("a")})                                   # has an executor
    assert "redo" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("b")})
    assert "redo" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("zzz")})
    assert "at most one" in refused(order=("a", "b", "c"), executors={"a": lambda c, s: {}}, gates={"b": gate(), "c": gate()})
    assert "the gate" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": "not a gate"})


def test_every_kind_this_checkout_registers_keeps_the_rule_a_review_is_harmless_to_pass():
    names = steps.load_builtin()
    assert {"ingest", "write-back", "export-csv", "export-xlsx", "export-docx", "export-pdf"} <= set(names)
    for name in names:
        kind = steps.REGISTRY[name]
        stops = [kind.order.index(n) for n in list(kind.stops) + list(kind.gates)]
        for step in kind.effectful:
            assert not kind.unattended and (not stops or kind.order.index(step) < min(stops)), name
        if kind.gates:
            assert kind.order[-1] in kind.gates and kind.order[-1] not in kind.executors and not kind.unattended, name

"""Tests of the step engine (runtime/steps.py, P5): the registry of kinds, and a run of a kind's steps in order, resumably, with stops for
the person, closed failure records, a cancelled request and starting a step over. The generic rules the media pipeline's engine held
(the branch short-video, runtime/pipeline.py), with no video in them: the kind here is invented. A fake task stands in for the store.
No process, no model, no network. Invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_steps_engine.py
"""
from __future__ import annotations

import ast
import copy

import pytest

import standin_tree as st

steps = st.load("steps")

NOW = "2026-10-15T10:00:00+00:00"


class FakeTask:
    """The task the engine moves: its state, its stored engine state, its decisions, and what it was asked."""

    def __init__(self):
        self.state, self.saved, self.moves, self.decisions_list, self.cancelled, self.saves = "running", None, [], [], False, 0

    def move(self, word, note, pending, resolve, state):
        if self.cancelled:
            raise steps.Cancelled()
        for d in self.decisions_list:
            if d["status"] == "open" and not (resolve and resolve["id"] == d["id"]):
                d["status"] = "cancelled"
        pending_id = None
        if pending is not None:
            pending_id = len(self.decisions_list) + 1
            self.decisions_list.append({"id": pending_id, "status": "open", "resolution": None, "payload": pending["payload"],
                                        "title": pending["title"], "body": pending["body"], "kind": pending["kind"]})
        self.state = word
        self.moves.append((word, note))
        self.saved = copy.deepcopy(state)
        return {"pending_id": pending_id}

    def save(self, state):
        if self.cancelled:
            raise steps.Cancelled()
        self.saves += 1
        self.saved = copy.deepcopy(state)

    def alive(self):
        if self.cancelled:
            raise steps.Cancelled()

    def answer(self, pending_id):
        d = next(d for d in self.decisions_list if d["id"] == pending_id)
        d["status"], d["resolution"] = "resolved", "answered"
        self.state = "running"          # the process that runs the task again has claimed it

    def context(self, args=None, services=None):
        return steps.Context(task_id=7, request_id=3, project="/p", args=args or {}, move=self.move, save=self.save, alive=self.alive,
                             decisions=lambda: [dict(d) for d in self.decisions_list], now=lambda: NOW, services=services or {})


class Boom(Exception):
    """An error of a kind's own module: it carries a closed code."""

    code, field = "kind_error", "thing"


def demo_kind(calls, fails=None, name="demo", side_due=lambda state: True, cleaned=None):
    """An invented kind: fetch, check, a review stop, build, an approval stop; and a side step `glance` after fetch."""
    fails = fails if fails is not None else {}

    def step(label, result):
        def run(ctx, state):
            calls.append(label)
            if label in fails:
                raise fails[label]
            return result
        return run

    return steps.Kind(
        name=name, order=("fetch", "glance", "check", "review", "build", "approval"),
        executors={"fetch": step("fetch", {"items": 3}), "glance": step("glance", {"seen": True}), "check": step("check", {"ok": True}),
                   "build": step("build", {"name": "out.bin", "bytes": 12})},
        stops=("review", "approval"),
        decisions={"review": lambda ctx, state: {"title": "Check it", "body": f"{state['steps']['fetch']['result']['items']} items are ready."},
                   "approval": lambda ctx, state: {"title": "Approve it", "body": "The file is built.", "payload": {"file": "out.bin"}}},
        footprint=lambda args: ("docs/out/<topic>.md", "docs/out/index.md") if args.get("write") else (),
        check=lambda args: dict(args, checked=True) if set(args) <= {"write", "checked"} else (_ for _ in ()).throw(steps.StepFailure("bad_args", "args")),
        cleanup={"build": lambda ctx, state: cleaned.append("build")} if cleaned is not None else {},
        side_steps={"glance": side_due}, errors=(Boom,),
        prepared=(lambda ctx, state, index: cleaned.append(f"prepared{index}")) if cleaned is not None else None)


@pytest.fixture
def world():
    calls, task = [], FakeTask()
    kind = demo_kind(calls)
    return kind, task, calls


def run(kind, task, state=None, args=None):
    state = state if state is not None else steps.new_state(kind)
    return steps.run(task.context(args), kind, state), state


# --- the order, the stops, the end -------------------------------------------------------------------------------------------------


def test_the_steps_run_in_order_and_the_run_stops_at_the_review_before_any_later_step(world):
    kind, task, calls = world
    out, state = run(kind, task)
    assert calls == ["fetch", "glance", "check"] and out["ok"] is True and out["stopped"] == "review"
    assert out["steps"] == {"fetch": "done", "check": "done", "review": "waiting", "build": "pending", "approval": "pending"}
    assert task.state == "waiting" and task.moves == [("waiting", None)]
    decision = task.decisions_list[0]
    assert decision["kind"] == "question" and decision["title"] == "Check it" and decision["body"] == "3 items are ready."
    assert decision["payload"]["step"] == {"kind": "demo", "step": "review"}      # the stop is found again by it
    assert out["pending"] == 1 and state["decisions"] == {"review": 1}
    assert task.saved["steps"]["review"]["status"] == "waiting" and task.saved["decisions"] == {"review": 1}


def test_the_answer_runs_the_rest_and_stops_at_the_approval_then_the_answer_ends_the_task_done(world):
    kind, task, calls = world
    out, _ = run(kind, task)
    task.answer(out["pending"])
    out, _ = run(kind, task, state=copy.deepcopy(task.saved))
    assert calls == ["fetch", "glance", "check", "build"] and out["stopped"] == "approval" and out["pending"] == 2
    assert task.state == "waiting" and task.decisions_list[1]["payload"] == {"file": "out.bin", "step": {"kind": "demo", "step": "approval"}}
    task.answer(out["pending"])
    out, state = run(kind, task, state=copy.deepcopy(task.saved))
    assert out == {"ok": True, "done": True, "steps": {name: "done" for name in kind.steps()}} and task.state == "done"
    assert calls == ["fetch", "glance", "check", "build"]            # nothing ran twice
    assert task.saved["steps"]["approval"]["status"] == "done" and task.saved["decisions"] == {}


def test_a_kind_with_no_stop_runs_to_the_end_and_the_task_is_done_with_its_state_saved_in_the_same_move():
    calls, task = [], FakeTask()
    kind = steps.Kind(name="plain", order=("one", "two"), executors={"one": lambda c, s: calls.append(1) or {"a": 1},
                                                                      "two": lambda c, s: calls.append(2) or {"b": 2}})
    out, state = run(kind, task)
    assert out == {"ok": True, "done": True, "steps": {"one": "done", "two": "done"}} and calls == [1, 2]
    assert task.state == "done" and task.moves == [("done", None)] and task.saved == state
    assert task.saved["steps"]["two"] == {"status": "done", "at": NOW, "result": {"b": 2}}


def test_a_step_already_done_is_not_run_again_and_a_stop_whose_decision_was_answered_is_found_by_its_payload(world):
    kind, task, calls = world
    out, _ = run(kind, task)
    task.answer(out["pending"])
    lost = copy.deepcopy(task.saved)
    lost["decisions"] = {}                       # a process died after opening the decision and before recording its id
    lost["steps"].pop("review")
    out, state = run(kind, task, state=lost)
    assert out["stopped"] == "approval" and state["steps"]["review"]["status"] == "done"
    assert len([d for d in task.decisions_list if d["payload"]["step"]["step"] == "review"]) == 1       # no second decision for the review
    assert calls == ["fetch", "glance", "check", "build"]


# --- failure: closed, and resumable ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("step", ["fetch", "check", "build"])
def test_a_failing_step_leaves_the_task_failed_and_the_next_run_starts_there_with_the_earlier_results_kept(step):
    calls, task = [], FakeTask()
    fails = {step: steps.StepFailure("timeout", "tool", "fetcher", "run it again")}
    kind = demo_kind(calls, fails)
    out, state = run(kind, task)
    if step == "build":
        task.answer(out["pending"])
        out, state = run(kind, task, state=copy.deepcopy(task.saved))
    assert out["ok"] is False and out["failed"] == step and out["code"] == "timeout" and out["field"] == "tool" and out["next"] == "run it again"
    assert task.state == "failed" and task.moves[-1] == ("failed", f"{step}: timeout tool -- run it again")
    assert task.saved["steps"][step]["status"] == "failed" and task.saved["failure"]["step"] == step
    assert task.saved["failure"]["provider"] == "fetcher" and task.saved["failure"]["at"] == NOW
    before = list(calls)
    fails.clear()
    task.state = "running"
    out, _ = run(kind, task, state=copy.deepcopy(task.saved))
    assert calls[len(before):][0] == step                 # it starts at the step that failed
    earlier = [n for n in kind.order[:kind.order.index(step)] if n not in kind.side_steps]
    assert [c for c in calls[len(before):] if c in earlier] == []                                # and repeats no earlier one
    assert task.saved["failure"] is None


def test_a_failure_note_carries_a_closed_code_never_the_text_a_tool_printed():
    calls, task = [], FakeTask()
    kind = demo_kind(calls, {"fetch": ValueError("the secret text of a document: sk-live-1234")})
    out, _ = run(kind, task)
    assert out["failed"] == "fetch" and out["code"] == "step_output_invalid" and out["field"] == "fetch"
    shown = repr(task.moves) + repr(task.saved) + repr(out)
    assert "secret text" not in shown and "sk-live" not in shown
    task2, calls2 = FakeTask(), []
    out2, _ = run(demo_kind(calls2, {"fetch": OSError(28, "No space left on device: /home/someone/file")}), task2)
    assert out2["code"] == "io_error" and "someone" not in repr(task2.moves) + repr(out2)


def test_the_errors_a_kind_declares_become_their_closed_code_and_field_and_a_text_like_code_is_made_safe(world):
    kind, task, calls = world
    out, _ = run(demo_kind([], {"fetch": Boom("a long sentence with /private/paths")}), task)
    assert (out["code"], out["field"]) == ("kind_error", "thing") and "paths" not in repr(task.moves)
    odd = steps.StepFailure("Not A Code! with text", "a field with spaces and text that is long", "Prov ider", "do this")
    record = steps.failure_record("fetch", odd, NOW)
    assert record == {"step": "fetch", "code": "failed", "field": "", "provider": "", "next": "do this", "at": NOW}
    assert steps.note_of("fetch", odd) == "fetch: failed -- do this"


def test_an_executor_that_returns_no_object_fails_with_a_closed_code():
    task = FakeTask()
    kind = steps.Kind(name="odd", order=("one",), executors={"one": lambda c, s: "text"})
    out, _ = run(kind, task)
    assert out["failed"] == "one" and out["code"] == "step_output_invalid"


def test_a_failure_in_a_decision_builder_fails_the_stop_step(world):
    kind, task, calls = world

    def broken(ctx, state):
        raise KeyError("items")
    odd = steps.Kind(name="demo", order=kind.order, executors=kind.executors, stops=kind.stops,
                     decisions=dict(kind.decisions, review=broken), side_steps=kind.side_steps)
    # a KeyError inside the decision builder is not wrapped by _execute: the engine's caller (runtime/ops_steps.py) ends the task failed
    with pytest.raises(KeyError):
        run(odd, task)


# --- cancelled -------------------------------------------------------------------------------------------------------------------


def test_the_cancel_of_the_request_stops_the_run_without_a_failure(world):
    kind, task, calls = world
    task.cancelled = True
    out, _ = run(kind, task)
    assert out["ok"] is False and out["failed"] is None and out["code"] == "cancelled" and calls == [] and task.moves == []


def test_a_request_cancelled_while_a_step_runs_is_cancelled_when_the_run_goes_to_record_it(world):
    kind, task, calls = world

    def cancel_then_finish(ctx, state):
        task.cancelled = True
        return {"items": 1}
    kind = steps.Kind(name="demo", order=("fetch", "check"), executors={"fetch": cancel_then_finish, "check": lambda c, s: {}})
    out, state = run(kind, task)
    assert out["code"] == "cancelled" and out["failed"] is None


def test_a_cancel_met_when_the_failure_is_recorded_is_a_cancel_not_a_failure(world):
    kind, task, calls = world
    task2 = FakeTask()

    def fail_and_cancel(ctx, state):
        task2.cancelled = True
        raise steps.StepFailure("timeout")
    kind = steps.Kind(name="demo", order=("fetch",), executors={"fetch": fail_and_cancel})
    out, _ = run(kind, task2)
    assert out["code"] == "cancelled" and task2.moves == []


# --- the side step -------------------------------------------------------------------------------------------------------------


def test_a_side_step_runs_when_due_is_recorded_and_listed_nowhere_and_its_failure_never_fails_the_task(world):
    kind, task, calls = world
    out, state = run(kind, task)
    assert state["steps"]["glance"]["status"] == "done" and "glance" not in out["steps"]
    calls2, task2 = [], FakeTask()
    kind2 = demo_kind(calls2, {"glance": steps.StepFailure("no_picture", "frame")})
    out2, state2 = run(kind2, task2)
    assert out2["ok"] is True and out2["stopped"] == "review" and task2.state == "waiting"
    assert state2["steps"]["glance"] == {"status": "skipped", "at": NOW, "result": {"code": "no_picture", "field": "frame"}}
    assert state2["failure"] is None


def test_a_side_step_that_is_not_due_does_not_run(world):
    calls, task = [], FakeTask()
    kind = demo_kind(calls, side_due=lambda state: False)
    run(kind, task)
    assert "glance" not in calls


# --- starting over -------------------------------------------------------------------------------------------------------------


def test_prepare_again_resets_the_step_and_every_later_one_removes_their_files_and_forgets_their_decisions():
    calls, task, cleaned = [], FakeTask(), []
    kind = demo_kind(calls, cleaned=cleaned)
    out, state = run(kind, task)
    task.answer(out["pending"])
    out, state = run(kind, task, state=copy.deepcopy(task.saved))
    assert state["decisions"] == {"approval": 2}
    reset = steps.prepare_again(task.context(), kind, state, "check")
    assert reset == {"reset": ["check", "review", "build", "approval"]}
    assert cleaned == ["build", "prepared2"]
    assert steps.summary(kind, state) == {"fetch": "done", "check": "pending", "review": "pending", "build": "pending", "approval": "pending"}
    assert state["decisions"] == {} and state["failure"] is None and task.saved == state
    assert steps.next_step(kind, state) == "check"


def test_prepare_again_refuses_an_unknown_step_and_a_side_step(world):
    kind, task, calls = world
    state = steps.new_state(kind)
    for step in ("nothing", "glance"):
        with pytest.raises(steps.StepFailure) as refused:
            steps.prepare_again(task.context(), kind, state, step)
        assert refused.value.code == "unknown_step"


# --- the state ------------------------------------------------------------------------------------------------------------------


def test_the_state_of_a_task_that_never_ran_is_new_and_one_that_is_not_this_kinds_is_refused(world):
    kind, task, calls = world
    assert steps.state_of(kind, None) == steps.new_state(kind) == {"version": 1, "kind": "demo", "steps": {}, "failure": None, "decisions": {}}
    for bad in ({"version": 2, "kind": "demo", "steps": {}, "decisions": {}}, {"version": 1, "kind": "other", "steps": {}, "decisions": {}},
                {"version": 1, "kind": "demo", "steps": [], "decisions": {}}, "text"):
        with pytest.raises(steps.StepFailure) as refused:
            steps.state_of(kind, bad)
        assert refused.value.code == "state_unreadable"
    assert steps.state_of(kind, steps.new_state(kind)) == steps.new_state(kind)


def test_summary_and_next_step_list_the_steps_without_the_side_steps(world):
    kind, task, calls = world
    state = steps.new_state(kind)
    assert list(steps.summary(kind, state)) == ["fetch", "check", "review", "build", "approval"]
    assert steps.next_step(kind, state) == "fetch"
    state["steps"].update({n: {"status": "done"} for n in kind.steps()})
    assert steps.next_step(kind, state) is None


# --- the registry and what a task of a kind is ---------------------------------------------------------------------------------


@pytest.fixture
def registered(monkeypatch):
    monkeypatch.setattr(steps, "REGISTRY", dict(steps.REGISTRY))
    return steps.register(demo_kind([], name="demo"))


def test_a_kind_is_checked_when_it_is_registered_and_a_name_is_taken_once(registered):
    assert steps.kind_of("demo") is registered
    with pytest.raises(ValueError, match="registered already"):
        steps.register(demo_kind([], name="demo"))
    good = dict(name="k", order=("a", "b"), executors={"a": lambda c, s: {}, "b": lambda c, s: {}})
    for bad, why in (({"name": "Bad Name"}, "lowercase"), ({"order": ()}, "order"), ({"order": ("a", "a")}, "distinct"),
                     ({"order": ("a", "Bb"), "executors": {"a": None, "Bb": None}}, "distinct"),
                     ({"executors": {"a": lambda c, s: {}}}, "no executor"), ({"stops": ("approval",)}, "step of its order"),
                     ({"stops": ("review",), "order": ("a", "review"), "executors": {"a": lambda c, s: {}}}, "no decision"),
                     ({"stops": ("sleep",), "order": ("a", "sleep"), "executors": {"a": lambda c, s: {}}}, "one of review, approval"),
                     ({"executors": {"a": None, "b": None, "c": None}}, "not a step"),
                     ({"side_steps": {"a": lambda s: True, "b": lambda s: True}}, "some step is not a side step")):
        with pytest.raises(ValueError, match=why):
            steps.register(steps.Kind(**dict(good, **bad)))


def test_a_kind_this_checkout_does_not_have_is_an_unknown_kind_failure(registered):
    with pytest.raises(steps.StepFailure) as refused:
        steps.kind_of("no-such-kind")
    assert refused.value.code == "unknown_kind"


def test_the_builtin_kinds_register_themselves_from_their_own_files_and_the_engine_names_none():
    assert "ingest" in steps.load_builtin()
    tree = ast.parse((st.RUNTIME / "steps.py").read_text(encoding="utf-8"))
    imported = sorted({a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
                      | {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)})
    assert imported == ["__future__", "dataclasses", "importlib", "os", "re", "sys", "typing"]       # no captions, media, theme or converter


def test_a_plan_task_carries_the_checked_arguments_and_the_footprint_the_kind_derived(registered):
    one = steps.plan_task("demo", {"write": True}, key="a", title="A", text="Make it.", depends_on=["b"], milestone=True)
    assert one == {"key": "a", "step": "demo", "args": {"write": True, "checked": True}, "footprint": ["docs/out/<topic>.md", "docs/out/index.md"],
                   "agent": "runtime", "title": "A", "text": "Make it.", "depends_on": ["b"], "milestone": True, "web": False}
    assert steps.plan_task("demo", {}, key="a", title="A", text="Make it.")["footprint"] == []
    assert steps.plan_task("demo", None, key="a", title="A", text="Make it.")["args"] == {"checked": True}
    for bad in ({"free text": "x"}, {"write": True, "extra": 1}):
        with pytest.raises(steps.StepFailure) as refused:
            steps.plan_task("demo", bad, key="a", title="A", text="Make it.")
        assert refused.value.code == "bad_args"


def test_a_kind_that_declares_too_many_paths_is_refused_when_a_task_is_made(registered, monkeypatch):
    many = steps.Kind(name="many", order=("a",), executors={"a": lambda c, s: {}}, footprint=lambda args: [f"docs/f{i}.md" for i in range(21)])
    monkeypatch.setitem(steps.REGISTRY, "many", many)
    with pytest.raises(steps.StepFailure) as refused:
        steps.plan_task("many", {}, key="a", title="A", text="Make it.")
    assert refused.value.code == "bad_footprint"

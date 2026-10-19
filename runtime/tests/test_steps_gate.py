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


def test_limit_30_a_kind_that_declares_a_step_performing_an_external_effect_itself_is_refused_when_it_is_registered():
    for fields in (dict(REVIEWED, effectful=("c",)), dict(REVIEWED, effectful=("a",)), dict(effectful=("a",)),
                   dict(effectful=("a",), unattended=True), dict(effectful=("zzz",))):
        why = refused(**fields)
        assert "performs no external effect itself" in why and "effect gate" in why, fields
    with pytest.raises(ValueError):
        steps.register(steps.Kind(name="odd-register", **dict(REVIEWED, effectful=("c",))))
    assert "odd-register" not in steps.REGISTRY


def test_a_gate_is_the_last_step_with_no_executor_an_earlier_redo_and_there_is_at_most_one():
    steps.check_kind(steps.Kind(name="fine", order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("a")}))
    assert "the gate" in refused(gates={"a": gate("a")})                                   # not the last step
    assert "the gate" in refused(gates={"c": gate("a")})                                   # has an executor
    assert "redo" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("b")})
    assert "redo" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": gate("zzz")})
    assert "at most one" in refused(order=("a", "b", "c"), executors={"a": lambda c, s: {}}, gates={"b": gate(), "c": gate()})
    assert "the gate" in refused(order=("a", "b"), executors={"a": lambda c, s: {}}, gates={"b": "not a gate"})


def test_every_kind_this_checkout_registers_keeps_the_rule_no_step_performs_an_external_effect_itself():
    names = steps.load_builtin()
    assert {"ingest", "write-back", "output-page", "output-table", "export-csv", "export-xlsx", "export-docx", "export-pdf"} <= set(names)
    for name in names:
        kind = steps.REGISTRY[name]
        assert kind.effectful == (), name
        if kind.gates:
            assert kind.order[-1] in kind.gates and kind.order[-1] not in kind.executors and not kind.unattended, name


# --- the structure of limit L30: what a step module can reach ------------------------------------------------------------------------

STEP_MODULES = sorted((st.REPO / "runtime").glob("step_*.py"))
FORBIDDEN_IMPORTS = {"subprocess", "socket", "ssl", "http", "urllib", "requests", "ftplib", "smtplib"}
# The modules of the runtime that each step module may import, by name. A module that calls a provider (documents, board, effects, the
# operations layer, the resolver through project_config) is on no row of a kind that can be started by a sentence; `step_ingest` is the
# one that imports a source through the operations of the sources (it reads a file or a page and keeps a version), and says so here.
ALLOWED = {
    "step_ingest.py": {"drop", "ops_core", "ops_sources", "sources", "steps"},
    "step_export.py": {"steps", "workcopy"},
    "step_project_script.py": {"ops_core", "ops_sources", "sources", "steps"},      # P9: a script's result is a version of a source, imported by the sources module; the provider is reached through it
    "step_write_back.py": {"steps", "write_document"},
    "step_output.py": {"output_document", "steps", "table_data", "write_document"},
    "step_send_email.py": {"send_document", "steps"},
    "step_publish_post.py": {"publish_document", "steps"},
    "step_calendar_event.py": {"calendar_document", "steps"},
    "step_files.py": {"files_document", "phrases", "steps", "workcopy"},      # W4a: the pure document of a file write, the sentences, the engine; the writers are in effect_files.py alone
}


def local_imports(path):
    import ast
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return {n for n in names if (st.REPO / "runtime" / f"{n}.py").exists()}


def test_limit_30_a_step_module_imports_only_the_modules_on_its_row_and_none_that_calls_a_provider():
    assert {p.name for p in STEP_MODULES} <= set(ALLOWED), "a new step module needs a row of ALLOWED, and a review of what it imports"
    for path in STEP_MODULES:
        imported = local_imports(path)
        assert imported <= ALLOWED[path.name], f"{path.name} imports {sorted(imported - ALLOWED[path.name])}"
        assert not imported & {"documents", "board", "effects", "effect_write", "ops", "ops_step_effects", "ops_step_seams", "project_config",
                               "isolated", "lab", "messaging"}, path.name


def test_limit_30_no_step_kind_module_writes_to_a_platform_runs_an_effect_or_reaches_the_network_itself():
    import ast
    for path in STEP_MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                assert not {n.split(".")[0] for n in names} & FORBIDDEN_IMPORTS, f"{path.name} imports {names}"
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in ("--confirmed", "--dry-run", "write", "push", "commit-files", "open-pr") or path.name == "step_write_back.py" \
                    and node.value == "write", f"{path.name} names {node.value!r}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("execute", "provider_call", "approval_add", "effect_done", "push", "write_text"), f"{path.name} reaches .{node.attr}"


def test_limit_30_the_documents_service_a_step_kind_is_given_can_only_read_and_stat(monkeypatch):
    seam = st.load("ops_step_seams")
    docs = st.load("documents")
    reader = seam.DocumentsReader({"documents": {"provider": "notion", "parent": "p", "expires": "2099-12-31"}}, str(st.REPO))
    assert {name for name in dir(reader) if not name.startswith("_")} == {"enabled", "provider", "problem", "read", "stat", "rows_state", "table_read"}
    assert seam.READ_VERBS == ("read", "stat", "table-read", "rows-state")
    seen = []
    monkeypatch.setattr(docs, "call", lambda cfg, root, verb, args, timeout=0: seen.append((verb, args)) or {"markdown": "x"})
    reader.read("a" * 32)
    reader.stat("a" * 32)
    reader.table_read("a" * 32)
    assert [v for v, _ in seen] == ["read", "stat", "table-read"]
    files = seam.EffectFiles({"data_dir": "/nowhere"})
    assert {name for name in dir(files) if not name.startswith("_")} == {"write", "read"}, "the effect files are written and read, never executed"


def test_the_source_id_pattern_of_the_write_back_is_the_sources():
    assert st.load("step_write_back").SOURCE_ID.pattern == st.load("sources").SOURCE_ID.pattern

"""The parity test of the lab facade: the lab's own runner (evals/eval_run.py) and runtime/lab.py are given the
same adapter output, and must classify it the same way and make the same number of attempts.

Since stage 5 of the platform plan the two make a run's attempts through one function, run() of
evals/run_attempts.py, reached by the facade through the runner: these tests now compare that function with itself
through its two callers, and check that the runtime keeps no loop of its own. Offline: a stand-in adapter, no
container, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_lab_parity.py
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
CASES = {"evals": [{"id": 1, "prompt": "please\n", "assertions": ["a"]}]}
# What the stand-in adapter does on every attempt, and the kind both sides must name (None: the run is a result).
SCENARIOS = [("adapter", "adapter"), ("refused", "refused"), ("early", "early_end"), ("auth", "auth"), (None, None)]
RETRIES = 1


def by_the_lab(tmp_path, monkeypatch, capsys, scenario):
    """The kind the lab's runner gives the run, and the number of attempts it made."""
    tree = st.build(tmp_path, monkeypatch, lab)
    (tree["tree"] / "skills" / "demo-asks" / "evals" / "evals.json").write_text(json.dumps(CASES))
    if scenario:
        st.fail(tree["adapter"], scenario, 9)
    er = st.load_runner()
    code = er.main(["--skill", "demo-asks", "--harness", "h", "--model", "m", "--runs", "1", "--only", "with",
                    "--no-grade", "--retries", str(RETRIES)])
    capsys.readouterr()
    bench = json.loads((tree["tree"] / "evals-workspace" / "demo-asks" / "iteration-1" / "benchmark.json").read_text())
    kinds = [f["kind"] for f in bench["infra_failures"]]
    assert code == (1 if kinds else 0) and len(kinds) <= 1
    return (kinds[0] if kinds else None), len(st.calls(tree["adapter"]))


def by_the_facade(tmp_path, monkeypatch, scenario):
    tree = st.build(tmp_path, monkeypatch, lab)
    if scenario:
        st.fail(tree["adapter"], scenario, 9)
    with lab.session():
        out = lab.run_skill("demo-asks", "please\n", [], str(tmp_path / "data" / "run-1"), retries=RETRIES)
    return (out["failure"]["kind"] if out["failure"] else None), len(st.calls(tree["adapter"]))


@pytest.mark.parametrize("scenario, expected", SCENARIOS)
def test_the_lab_and_the_facade_classify_the_same_output_the_same_way(tmp_path, monkeypatch, capsys, scenario, expected):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    lab_kind, lab_calls = by_the_lab(tmp_path / "a", monkeypatch, capsys, scenario)
    facade_kind, facade_calls = by_the_facade(tmp_path / "b", monkeypatch, scenario)
    assert lab_kind == facade_kind == expected
    assert lab_calls == facade_calls == (1 if expected in ("auth", None) else RETRIES + 1)


def test_a_timeout_is_the_reason_the_shared_function_returns():
    """The lab accepts no timeout under 30 seconds, so the timeout is compared on its reason: both sides read
    what run_failure() returned, and a reason that starts with "timeout" is a timeout before anything else."""
    assert lab.failure_kind("timeout: stopped after 30s", "/nonexistent", ["safeguards flagged this message"], "", []) == ("timeout", None)


def test_the_order_of_the_checks_is_the_labs(tmp_path):
    """A failed attempt whose output holds a refusal marker and a 401 is a refusal; one with a 401 alone is a
    refused key; one with neither is the adapter's; an attempt that did not fail is read for an early end."""
    out = tmp_path / "out"
    out.mkdir()
    (out / "stderr.log").write_text("API Error: 401 Unauthorized\n")
    assert lab.failure_kind("adapter exit 1", str(out), ["flagged"], "", []) == ("auth", "HTTP 401")
    (out / "response.md").write_text("safeguards flagged this message\n")
    assert lab.failure_kind("adapter exit 1", str(out), ["flagged"], "", [])[0] == "refused"
    assert lab.failure_kind("adapter exit 1", str(tmp_path), ["flagged"], "", []) == ("adapter", None)
    assert lab.failure_kind(None, str(tmp_path), [], "Let me just read the template first.", [])[0] == "early_end"
    assert lab.failure_kind(None, str(tmp_path), [], "Let me just read the template first.", ["a.md"]) == (None, None)
    assert lab.failure_kind(None, str(tmp_path), [], "Which country? Recommended: yours.", []) == (None, None)


def test_the_lab_and_the_facade_call_the_same_function():
    er = st.load_runner()
    shared = er.load_attempts()
    assert lab.LAB.load_attempts() is shared and lab.LAB.load_attempts().run is shared.run
    assert "load_attempts" in lab.load().__all__


RUNTIME = Path(lab.__file__).resolve().parent
LOOP_NAMES = {"wait_while_paused", "start_pause", "RETRY_PAUSE", "Slots"}


def test_the_runtime_has_no_loop_of_its_own():
    """lab.py holds no while statement, and no module under runtime/ reads a name of the loop's control: those
    names stay in the kit's __all__ only because the shared function reads them through the facade's view of the runner."""
    facade = ast.parse((RUNTIME / "lab.py").read_text(encoding="utf-8"))
    assert not [node for node in ast.walk(facade) if isinstance(node, ast.While)]
    for path in sorted(RUNTIME.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        used |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not used & LOOP_NAMES, (str(path.relative_to(RUNTIME)), sorted(used & LOOP_NAMES))

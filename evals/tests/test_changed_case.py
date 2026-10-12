"""Tests of a case changed after the newest full test (evals/eval_status.py gate_of and the band): it is treated
as an added case, once. It waits, pending, for its own runs with the skill and its baseline, while the gate is
computed over the other cases; a second change after its new text has run asks for a full test. The runs go
through eval_run.py with the stand-in adapter of test_eval_run.py. No model is called.

Run: uv run --with pytest pytest evals/tests/test_changed_case.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# The stand-in adapter, the demo skill and the helpers of the runner's own tests, loaded under a name of their own.
spec = importlib.util.spec_from_file_location("eval_run_tests_for_changed_case", Path(__file__).with_name("test_eval_run.py"))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
er = t.er


@pytest.fixture(autouse=True)
def own_lock_folder(tmp_path, monkeypatch):
    """The lock the runner processes of a machine share is each test's own, and nothing waits before a retry."""
    monkeypatch.setattr(er, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er.KIT, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er, "RETRY_PAUSE", 0)
    monkeypatch.setattr(er.KIT, "RETRY_PAUSE", 0)


CASES = [{"id": 1, "prompt": "p", "assertions": ["a"]}, {"id": 2, "prompt": "q", "assertions": ["a"]}]


def band_now(tmp_path):
    status = er.load_status()
    return status.skill_band(str(tmp_path), str(tmp_path / "skills" / "demo"), status.load_gate(str(tmp_path)))


def demo_after_a_full_test(tmp_path, monkeypatch):
    """The demo skill with two cases, after a full test of 3 runs per case that passes."""
    skill = t.scores_demo(tmp_path, monkeypatch)
    t.configure_gate(tmp_path, strong_tolerance=0.05, runs=3)
    assert er.main(["--skill", "demo"]) == 0
    return skill


def test_a_changed_case_is_pending_and_its_earlier_runs_are_shown_as_dropped(tmp_path, monkeypatch, capsys):
    skill = demo_after_a_full_test(tmp_path, monkeypatch)
    t.set_cases(skill, [CASES[0], {"id": 2, "prompt": "s", "assertions": ["a"]}])
    gate = t.gate_now(tmp_path)
    assert gate["computed"] is True and gate["passed"] is True and gate["cases"] == ["1"]
    assert gate["pending"] == ["2"] and gate["changed"] == ["2"]
    assert gate["dropped"] == {"2": {"runs": 3, "mean": 1.0}}  # its earlier text's runs on the reference model
    row = band_now(tmp_path)
    assert (row["band"], row["kind"]) == ("watch", "case pending")
    assert "case 2 had 3 run(s) of mean 1.000" in row["cause"]
    assert row["command"].endswith("--cases 2 --baseline")


def test_after_its_runs_with_its_baseline_the_changed_case_is_in_the_gate(tmp_path, monkeypatch, capsys):
    skill = demo_after_a_full_test(tmp_path, monkeypatch)
    t.set_cases(skill, [CASES[0], {"id": 2, "prompt": "s", "assertions": ["a"]}])
    assert er.main(["--skill", "demo", "--cases", "2", "--baseline"]) == 0
    capsys.readouterr()
    gate = t.gate_now(tmp_path)
    assert gate["computed"] is True and gate["pending"] == [] and gate["cases"] == ["1", "2"]
    assert "case pending" not in [c["kind"] for c in band_now(tmp_path)["causes"]]


def test_a_case_changed_a_second_time_after_its_new_text_ran_needs_a_full_test(tmp_path, monkeypatch, capsys):
    skill = demo_after_a_full_test(tmp_path, monkeypatch)
    t.set_cases(skill, [CASES[0], {"id": 2, "prompt": "s", "assertions": ["a"]}])
    assert er.main(["--skill", "demo", "--cases", "2", "--baseline"]) == 0
    capsys.readouterr()
    t.set_cases(skill, [CASES[0], {"id": 2, "prompt": "u", "assertions": ["a"]}])
    gate = t.gate_now(tmp_path)
    assert gate["computed"] is False and "changed again after the newest full test" in gate["cause"]
    row = band_now(tmp_path)
    assert row["band"] == "needs a test" and row["command"] == "python3 evals/eval_run.py --skill demo"

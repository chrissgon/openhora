"""Tests of the command a failed gate names when a thin baseline could clear it (T26): with fewer baseline lines per case
than the runs and the mean with the skill at the threshold, only the tolerance fails, so the baseline in full comes before
the fix. No model is called.

Run: uv run --with pytest pytest evals/tests/test_thin_baseline_command.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


b = load("test_bands", "bands_tests_for_thin_command")
q = load("test_quick_pool", "quick_pool_tests_for_thin_command")

FIX = "after the fix: python3 evals/eval_run.py --skill core-demo"


def full_test(root, with_score, base_score, base_lines):
    folder = b.skill(root)
    lines = [(c, "with", with_score, None) for c in (1, 2, 3) for _ in range(3)]
    lines += [(c, "without", base_score, None) for c in (1, 2, 3) for _ in range(base_lines)]
    b.event(folder, "full", "1.0.0", "2030-01-01", lines,
            gate={"passed": False, "with": with_score, "baseline": base_score, "threshold": 0.8, "tolerance": 0.05})
    return b.band(root, folder)


def test_a_thin_baseline_that_alone_fails_the_gate_is_asked_to_run_in_full_first(tmp_path):
    row = full_test(tmp_path, 0.9, 1.0, 1)
    assert (row["band"], row["kind"]) == ("needs a test", "gate failed")
    assert row["cause"] == "the newest full test of 1.0 fails the gate (with the skill 0.900, baseline 1.000)"
    assert row["command"] == ("python3 evals/eval_run.py --skill core-demo --cases 1,2,3 --baseline (the baseline has 1 of 3 "
                              "runs per case: run it in full first; if the gate still fails, after the fix: "
                              "python3 evals/eval_run.py --skill core-demo)")


def test_a_full_baseline_leaves_the_command_as_it_was(tmp_path):
    assert full_test(tmp_path, 0.9, 1.0, 3)["command"] == FIX


def test_a_mean_under_the_threshold_leaves_the_command_as_it_was(tmp_path):
    assert full_test(tmp_path, 0.6, 0.5, 1)["command"] == FIX


def test_a_closed_pool_that_fails_on_a_thin_baseline_is_asked_to_run_it_in_full_first(tmp_path):
    demo = b.skill(tmp_path)
    b.versions(demo, ("1.0.0", "new"))
    q.baseline(demo, score=1.0, per_case=1)
    q.quicks(demo, 3, score=0.9)
    row = q.row(tmp_path, demo)
    assert row["pool"]["closed"] is True
    assert (row["band"], row["kind"]) == ("needs a test", "gate failed")
    assert row["command"] == ("python3 evals/eval_run.py --skill core-demo --cases 1,2,3 --baseline (the baseline has 1 of 3 "
                              "runs per case: run it in full first; if the gate still fails, after the fix: "
                              "python3 evals/eval_run.py --skill core-demo --quick)")

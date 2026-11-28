"""A run line written as a timeout was not graded: it counts as no run of its guard assertions, never as a pass (T26).
No model is called.

Run: uv run --with pytest pytest evals/tests/test_guard_timeout_lines.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


b = load("test_bands", "bands_tests_for_guard_timeouts")

TIMEOUT = {"outcome": "timeout"}


def timeouts(case, count):
    return [(case, "with", 0.0, {**TIMEOUT, "results": [0] * count}) for _ in range(3)]


def setup(root):
    folder = b.skill(root, cases=b.guard_cases())
    b.full(folder)
    b.skill(root, version="1.1.0")
    return folder


def test_timeout_lines_are_no_run_of_the_guards_of_their_case(tmp_path):
    folder = setup(tmp_path)
    lines = timeouts(1, 10) + timeouts(2, 2) + [(3, "with", 1.0, None)] * 3
    b.event(folder, "partial", "1.1.0", "2030-02-01", lines)
    row = b.band(tmp_path, folder)
    assert (row["band"], row["kind"]) == ("needs a test", "guard")
    assert "have no run in the current set" in row["cause"]
    assert row["command"] == "python3 evals/eval_run.py --skill core-demo --cases 1,2"
    states = {(g["case"], g["assertion"]): g["state"] for g in row["guards"]}
    assert states == {("1", 10): "not run", ("2", 1): "not run", ("2", 2): "not run"}


def test_a_graded_run_beside_the_timeouts_counts(tmp_path):
    folder = setup(tmp_path)
    lines = timeouts(1, 10) + timeouts(2, 2) + [(3, "with", 1.0, None)] * 3
    lines += [(1, "with", 1.0, None), (2, "with", 1.0, {"results": [1, 1]})]
    b.event(folder, "partial", "1.1.0", "2030-02-01", lines)
    row = b.band(tmp_path, folder)
    assert {g["state"] for g in row["guards"]} == {"passed"}
    assert row["kind"] != "guard"

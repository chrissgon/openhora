"""Tests of the gate file's "baseline_runs" in eval_run.py and of "baseline_margin" in the band: a full test runs
each baseline "baseline_runs" times, --baseline runs it as many times as the runs, a baseline with that many
lines is reused, and a thin baseline close to the mean with the skill is asked to run in full. The runs go
through eval_run.py with the stand-in adapter of test_eval_run.py; the band reads evidence written as
test_bands.py writes it. No model is called.

Run: uv run --with pytest pytest evals/tests/test_baseline_runs.py
"""
from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

import pytest


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


# The stand-in adapter and the helpers of the runner's tests; the evidence helpers of the bands' tests.
t = load("test_eval_run", "eval_run_tests_for_baseline_runs")
b = load("test_bands", "bands_tests_for_baseline_runs")
er = t.er


@pytest.fixture(autouse=True)
def own_lock_folder(tmp_path, monkeypatch):
    """The lock the runner processes of a machine share is each test's own, and nothing waits before a retry."""
    monkeypatch.setattr(er, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er.KIT, "LOCK_DIR", str(tmp_path / "locks"))
    monkeypatch.setattr(er, "RETRY_PAUSE", 0)
    monkeypatch.setattr(er.KIT, "RETRY_PAUSE", 0)


def demo(tmp_path, monkeypatch, **gate):
    skill = t.scores_demo(tmp_path, monkeypatch)
    t.configure_gate(tmp_path, strong_tolerance=0.05, runs=3, **gate)
    return skill


def planned(tmp_path, since=0):
    """How many model runs each "<prompt> <with|without> <model>" got since the given call."""
    return Counter(t.calls(tmp_path)[since:])


def test_a_full_test_runs_the_skill_three_times_and_the_baseline_once(tmp_path, monkeypatch, capsys):
    skill = demo(tmp_path, monkeypatch, baseline_runs=1)
    assert er.main(["--skill", "demo"]) == 0
    assert planned(tmp_path) == {"p with m": 3, "p with f": 3, "p without m": 1,
                                 "q with m": 3, "q with f": 3, "q without m": 1}
    (event, _), = t.evidence_of(skill)
    assert event["baseline"] == {"1": "run", "2": "run"}


def test_baseline_in_a_partial_test_runs_it_as_many_times_as_the_runs(tmp_path, monkeypatch, capsys):
    demo(tmp_path, monkeypatch, baseline_runs=1)
    assert er.main(["--skill", "demo", "--cases", "1", "--baseline"]) == 0
    assert planned(tmp_path) == {"p with m": 3, "p with f": 3, "p without m": 3}


def test_a_second_full_test_reuses_a_baseline_of_one_line(tmp_path, monkeypatch, capsys):
    skill = demo(tmp_path, monkeypatch, baseline_runs=1)
    assert er.main(["--skill", "demo"]) == 0
    assert sum(" without " in c for c in t.calls(tmp_path)) == 2  # one baseline line per case is in force
    before = len(t.calls(tmp_path))
    assert er.main(["--skill", "demo"]) == 0
    assert not [c for c in t.calls(tmp_path)[before:] if " without " in c]
    second = t.evidence_of(skill)[-1][0]
    assert second["baseline"] == {"1": "reused", "2": "reused"}


def test_the_floor_models_baseline_runs_once_in_a_full_test(tmp_path, monkeypatch, capsys):
    demo(tmp_path, monkeypatch, baseline_runs=1)
    assert er.main(["--skill", "demo", "--baseline-on", "f"]) == 0
    counts = planned(tmp_path)
    assert (counts["p without f"], counts["q without f"], counts["p without m"], counts["q without m"]) == (1, 1, 1, 1)


def test_without_the_key_a_full_test_runs_the_baseline_as_many_times_as_the_runs(tmp_path, monkeypatch, capsys):
    demo(tmp_path, monkeypatch)
    assert er.main(["--skill", "demo"]) == 0
    counts = planned(tmp_path)
    assert (counts["p with m"], counts["p without m"], counts["q without m"]) == (3, 3, 3)


def thin(root, baseline_lines):
    """A skill whose full test has 3 runs per case at 0.90 with the skill and the given baseline lines at 0.75."""
    folder = b.skill(root)
    lines = [(c, "with", 0.9, None) for c in (1, 2, 3) for _ in range(3)]
    lines += [(c, "without", 0.75, {"results": [1, 1, 1, 0]}) for c in (1, 2, 3) for _ in range(baseline_lines)]
    b.event(folder, "full", "1.0.0", "2030-01-01", lines)
    return folder


def test_a_baseline_of_one_line_within_the_margin_is_a_thin_baseline_and_three_lines_are_not(tmp_path):
    cfg = {**b.CFG, "baseline_margin": 0.2}
    folder = thin(tmp_path / "one", 1)
    row = b.band(tmp_path / "one", folder, cfg)
    assert row["gate"]["computed"] and row["gate"]["passed"]
    assert (row["gate"]["with"], row["gate"]["baseline"]) == (pytest.approx(0.9), pytest.approx(0.75))
    assert (row["band"], row["kind"]) == ("watch", "thin baseline")
    assert row["command"] == "python3 evals/eval_run.py --skill core-demo --cases 1,2,3 --baseline"
    folder = thin(tmp_path / "three", 3)
    row = b.band(tmp_path / "three", folder, cfg)
    assert "thin baseline" not in [c["kind"] for c in row["causes"]]
    assert row["band"] == "reliable"

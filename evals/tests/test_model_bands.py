"""Offline tests of the band, the cause and the gate of every model (the reliability model, section 10): each model
that has evidence of a skill gets the figures the first lab model gets, by the same rules on its own lines, and no
model's band decides for another. No model is called: evidence is written here, with
the helpers of test_bands.py.

Run: uv run --with pytest pytest evals/tests/test_model_bands.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("bands_helpers_for_model_bands", Path(__file__).with_name("test_bands.py"))
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)
es, CFG, skill, event, guard_cases = tb.es, tb.CFG, tb.skill, tb.event, tb.guard_cases
F = {"model": "f-model", "adapter": "fh"}
GATE = ("computed", "passed", "with", "baseline", "version", "test", "note", "cause")


def both(folder, date="2030-01-01", ref=None, floor=None, cases=(1, 2, 3)):
    """A full test on the reference model and the floor model. ref and floor: {case: ([with scores], [without
    scores])}; the defaults are 3 runs at 0.9 with the skill and 3 at 0.5 without, on every case."""
    plain = {c: ([0.9] * 3, [0.5] * 3) for c in cases}
    lines = []
    for scores, extra in ((ref or plain, None), (floor or plain, F)):
        for case, (with_skill, without) in scores.items():
            lines += [(case, "with", s, extra) for s in with_skill] + [(case, "without", s, extra) for s in without]
    return event(folder, "full", "1.0.0", date, lines)


def band(root, folder, cfg=None):
    return es.skill_band(str(root), str(folder), cfg or CFG)


@pytest.fixture
def root(tmp_path):
    return tmp_path


def test_a_confirmed_guard_failure_on_the_floor_model_needs_a_test_there_and_leaves_the_reference_band(root):
    folder = skill(root, cases=guard_cases())
    both(folder)
    row = band(root, folder)
    assert row["band"] == "reliable" and row["models"]["f-model"]["band"] == "reliable"
    event(folder, "partial", "1.0.0", "2030-02-01", [(1, "with", 0.9, {**F, "guard_failed": [10]})])
    row = band(root, folder)
    floor = row["models"]["f-model"]
    assert (floor["band"], floor["kind"]) == ("needs a test", "guard") and "1.10 failed" in floor["cause"]
    assert floor["command"] == "after the fix and its bump: python3 evals/eval_run.py --skill core-demo --cases 1"
    assert (row["band"], row["kind"], row["cause"]) == ("reliable", None, None)  # the reference model's band
    assert row["models"]["s-model"]["band"] == "reliable"


def test_the_floor_model_s_gate_uses_its_own_baselines_and_the_mean_of_its_cases_means(root):
    folder = skill(root)
    # Case 1 has twice the lines of the others: the mean of the cases' means is not the mean of the lines.
    floor = {1: ([1.0] * 6, [0.0, 0.0, 0.6]), 2: ([0.8] * 3, [0.5]), 3: ([0.8] * 3, [0.5])}
    both(folder, floor=floor)
    row = band(root, folder)
    gate = row["models"]["f-model"]["gate"]
    assert gate["computed"] and gate["passed"] is True
    assert gate["with"] == pytest.approx((1.0 + 0.8 + 0.8) / 3) and gate["baseline"] == pytest.approx((0.2 + 0.5 + 0.5) / 3)
    assert gate["with"] != pytest.approx(10.8 / 12) and gate["baseline"] != pytest.approx(1.6 / 5)
    assert (row["gate"]["with"], row["gate"]["baseline"]) == (pytest.approx(0.9), pytest.approx(0.5))  # the reference's own
    # A floor model that fails its gate needs a test there, by cause (c), and the skill stays reliable.
    other = skill(root / "b")
    both(other, floor={c: ([0.6] * 3, [0.5] * 3) for c in (1, 2, 3)})
    row = band(root / "b", other)
    floor = row["models"]["f-model"]
    assert (floor["band"], floor["kind"]) == ("needs a test", "gate failed") and floor["gate"]["passed"] is False
    assert row["band"] == "reliable" and row["gate"]["passed"] is True


def test_the_reference_model_s_row_is_the_skill_s_own_band_cause_and_gate(root):
    folder = skill(root, cases=guard_cases())
    both(folder)
    event(folder, "partial", "1.0.0", "2030-02-01", [(1, "with", 0.9, {"guard_failed": [10]})])
    row = band(root, folder)
    ref = row["models"]["s-model"]
    assert row["band"] == "needs a test" and row["kind"] == "guard"
    assert {k: ref[k] for k in ("band", "cause", "kind", "command", "causes")} == {
        k: row[k] for k in ("band", "cause", "kind", "command", "causes")}
    assert ref["gate"] == {k: row["gate"][k] for k in GATE} == row["gate"]
    # The same function with the configuration as_subject makes for the lead model gives the same answer.
    again = es.skill_band(str(root), str(folder), es.as_subject(CFG, "s-model"), per_model=False)
    assert {k: again[k] for k in ("band", "cause", "kind", "command", "causes", "gate")} == {
        k: row[k] for k in ("band", "cause", "kind", "command", "causes", "gate")}
    assert row["models"]["f-model"]["band"] == "reliable"


def test_a_model_with_no_baseline_has_no_gate_computed_and_a_band_by_the_same_rule(root):
    folder = skill(root)
    lines = [(c, "with", 0.9, None) for c in (1, 2, 3) for _ in range(3)] + [(c, "without", 0.5, None) for c in (1, 2, 3)]
    lines += [(c, "with", 0.9, F) for c in (1, 2, 3) for _ in range(3)]  # the floor model: with the skill only
    event(folder, "full", "1.0.0", "2030-01-01", lines)
    row = band(root, folder)
    floor = row["models"]["f-model"]
    assert floor["gate"]["computed"] is False and floor["gate"]["passed"] is None and floor["gate"]["with"] is None
    assert "no baseline in force on f-model" in floor["gate"]["cause"]
    # The result the full test wrote into its event line is the reference model's: it never stands for another model.
    assert floor["gate"]["note"] is None and floor["band"] in es.BANDS and floor["kind"] == "no passing full test"
    assert (floor["current_runs"], floor["inherited_runs"], floor["mean"]) == (9, 0, 0.9)
    assert row["band"] == "reliable"


def test_no_model_inherits_the_lines_of_another(root):
    folder = skill(root)
    lines = [(c, "with", 0.9, None) for c in (1, 2, 3) for _ in range(3)] + [(c, "with", 0.9, F) for c in (1, 2, 3)]
    event(folder, "full", "1.0.0", "2030-01-01", lines, strong="old-model")
    row = band(root, folder)
    assert row["inherited_runs"] == 0  # the lead model inherits nothing from the model an old event ran in its first tier
    assert (row["models"]["f-model"]["current_runs"], row["models"]["f-model"]["inherited_runs"]) == (3, 0)
    assert (row["models"]["old-model"]["current_runs"], row["models"]["old-model"]["inherited_runs"]) == (9, 0)


def test_the_model_table_shows_band_cause_and_gate_per_model_with_the_reference_model_first(root):
    (root / "evals").mkdir()
    (root / "evals" / "eval-gate.json").write_text(json.dumps({
        **CFG, "models": {"a-floor": {**tb.ENTRY, "adapter": "fh"}, "s-model": tb.ENTRY}, "lab_models": ["s-model", "a-floor"]}))
    (root / "docs").mkdir()
    (root / "docs" / "inventory.md").write_text(f"{es.BEGIN}\n{es.END}\n")
    folder = skill(root)
    lines = [(c, "with", 0.9, None) for c in (1, 2, 3) for _ in range(3)] + [(c, "without", 0.5, None) for c in (1, 2, 3)]
    lines += [(c, "with", 0.9, {"model": "a-floor", "adapter": "fh"}) for c in (1, 2, 3) for _ in range(3)]
    event(folder, "full", "1.0.0", "2030-01-01", lines, floor="a-floor")  # the event names the model whose lines it holds
    block = es.inventory_block(str(root))
    rows = [l for l in block.splitlines() if l.startswith("| `core-demo` | `")]
    assert ("| Skill | Model | Band | Cause | Gate: with vs baseline | Score | Mean | Lab runs (N) | "
            "Field: uses, judged, mean (self-reported) | Platforms: mean (runs) |") in block
    assert rows == [
        "| `core-demo` | `s-model` | reliable | - | passed, 0.90 vs 0.50 | 0.71 | 0.90 | 9 | 0, 0, n/a | - |",
        "| `core-demo` | `a-floor` | needs a test | no baseline in force on a-floor for case(s) 1, 2, 3 | not computed | "
        "0.71 | 0.90 | 9 | 0, 0, n/a | - |"]

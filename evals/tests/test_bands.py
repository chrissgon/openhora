"""Offline tests of the score and the bands (the reliability model, sections 4 to 7; item B7b of
the final plan, removed on 2026-10-14: git show d3e60770:docs/architecture/final-plan-2026-10-02.md): the pessimistic score against the model's worked examples and its
backtest, the current set and the inherited sets, the three causes of `needs a test`, the causes of `watch`, the
field columns and the field signal, and the validator's lines. No model is called: evidence is written here.

Run: uv run --with pytest pytest evals/tests/test_bands.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name, folder):
    spec = importlib.util.spec_from_file_location(f"{name}_bands_test", REPO / folder / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


es, validate = load("eval_status", "evals"), load("validate", "scripts")
H = {c: c * 64 for c in "abcdef"}
CFG = {"strong_model": "s-model", "strong_harness": "h", "floor_model": "f-model", "floor_harness": "fh",
       "floor_pass_env": [], "strong_pass_env": [], "grader": "s-model", "threshold": 0.8, "strong_tolerance": 0.05,
       "measurement_version": 5, "measurement_floor": 5, "models": {"s-model": [], "f-model": [], "old-model": []}}


# --- the pessimistic score: the model's worked examples (section 6) and its backtest -------------------------

@pytest.mark.parametrize("s, n, score", [
    (8.10, 9, 0.705), (2.70, 3, 0.531), (5.40, 6, 0.651), (5.70, 6, 0.713), (10.80, 12, 0.737), (0, 0, 0),
    (4.80, 6, 0.539), (57.00, 60, 0.900), (2.85, 3, 0.585), (8.55, 9, 0.770), (3.0, 3, 0.646)])
def test_the_pessimistic_score_gives_the_worked_examples_of_the_model(s, n, score):
    assert round(es.pessimistic_score(s, n), 3) == score


def test_the_0_70_needs_much_evidence_for_a_marginal_mean():
    """Section 5: 4 runs at 1.0, 9 at 0.90, 16 at 0.85 and 35 at 0.80 reach 0.70; one run fewer does not."""
    for n, mean in ((4, 1.0), (9, 0.90), (16, 0.85), (35, 0.80)):
        assert es.pessimistic_score(n * mean, n) >= 0.70 > es.pessimistic_score((n - 1) * mean, n - 1)


@pytest.mark.parametrize("n, mean, row", [
    (9, 0.833, (0.63, 0.46, 0.57, 0.66, 0.66)), (6, 0.881, (0.63, 0.51, 0.63, 0.71, 0.68)),
    (9, 0.844, (0.64, 0.47, 0.59, 0.67, 0.67)), (9, 0.889, (0.69, 0.52, 0.64, 0.72, 0.72)),
    (12, 0.863, (0.69, 0.49, 0.61, 0.69, 0.71)), (9, 0.911, (0.72, 0.54, 0.66, 0.75, 0.75)),
    (12, 0.928, (0.77, 0.56, 0.68, 0.77, 0.79)), (6, 1.0, (0.79, 0.65, 0.79, 0.88, 0.85)),
    (9, 0.972, (0.80, 0.61, 0.74, 0.83, 0.83)), (18, 0.933, (0.82, 0.57, 0.69, 0.78, 0.83)),
    (12, 0.983, (0.85, 0.62, 0.76, 0.85, 0.87)), (12, 1.0, (0.88, 0.65, 0.79, 0.88, 0.90))])
def test_the_example_rows_of_the_backtest(n, mean, row):
    """A full test; one Y change (its runs inherited, capped at 3); +3 runs; +9 runs; + a full test of n runs."""
    pool = lambda current, inherited: es.pool_score({"current": [{"score": mean}] * current,
                                                     "inherited": [{"score": mean}] * inherited})["score"]
    assert tuple(round(x, 2) for x in (pool(n, 0), pool(0, n), pool(3, n), pool(9, n), pool(n, n))) == row


def test_inherited_evidence_alone_never_reaches_0_70():
    for count in (1, 3, 10, 200):
        figures = es.pool_score({"current": [], "inherited": [{"score": 1.0}] * count})
        assert figures["runs"] == min(count, 3) and figures["score"] < 0.70


# --- trees of evidence --------------------------------------------------------------------------------

def skill(root, version="1.0.0", cases=None, name="core-demo", side_effects=None):
    folder = root / "skills" / name
    (folder / "evals").mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(f'---\nname: {name}\nmetadata:\n  version: "{version}"\n---\n\n# {name}\n')
    if cases is not None or not (folder / "evals" / "evals.json").exists():
        cases = cases or [{"id": i, "prompt": f"p{i}", "assertions": [f"a{j}" for j in range(10)]} for i in (1, 2, 3)]
        (folder / "evals" / "evals.json").write_text(json.dumps({"evals": cases}))
    return folder


def versions(folder, *lines):
    """The version file: (version, class) per line."""
    text = "".join(json.dumps({"version": v, "content_sha256": H["a"], "class": c, "date": "2030-01-01"}) + "\n"
                   for v, c in lines)
    (folder / "evals" / "versions.jsonl").write_text(text)


def results(score, count=10):
    passed = round(score * count)
    return [1] * passed + [0] * (count - passed)


SEQ = iter(range(1, 10 ** 6))


def event(folder, kind, version, date, runs, complete=True, grader="s-model", strong="s-model", mv=5, gate=None):
    """Write one evidence file. runs: [(case, variant, score, extra)] with extra a dict of run-line keys (model,
    context_sha256, guard_failed, results, date...)."""
    test = f"{date.replace('-', '')}T000000Z-{next(SEQ):08x}"
    hashes = es.case_hashes(str(folder))
    cases = sorted({str(c) for c, _, _, _ in runs} | (set(hashes) if kind == "full" else set()))
    line = {"record": "test", "skill": folder.name, "test": test, "kind": kind, "version": version, "content_sha256": H["a"],
            "date": date, "models": {"strong": strong, "floor": "f-model"}, "adapters": {"strong": "h", "floor": "fh"},
            "adapter_sha256": {"h": H["b"], "fh": H["c"]}, "grader": grader, "runs": 3, "timeout_seconds": 900,
            "retries": 2, "measurement_version": mv, "measurement_sha256": H["d"], "image_digest": "sha256:" + H["e"],
            "image_platform": "linux/arm64", "grading_template_sha256": H["f"], "tools": {},
            "cases": {c: hashes.get(c, H["f"]) for c in cases}, "baseline": {c: "run" for c in cases}, "web_cases": [],
            "counts": {}, "extra_pass_env": [], "complete": complete}
    if kind == "full" and complete:
        line["gate"] = gate or {"passed": True, "with": 0.9, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05}
    out = [line]
    for case, variant, score, extra in runs:
        extra = dict(extra or {})
        res = extra.pop("results", None) or results(score)
        run = {"record": "run", "skill": folder.name, "version": version, "content_sha256": H["a"], "model": strong, "adapter": "h",
               "kind": kind, "test": test, "date": date, "measurement_version": mv, "measurement_sha256": H["d"],
               "case": case, "case_sha256": hashes.get(str(case), H["f"]), "variant": variant, "outcome": "graded",
               "score": sum(res) / len(res), "results": res}
        run.update(extra)
        out.append(run)
    path = folder / "evals" / "evidence" / f"lab-{test}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(l) + "\n" for l in out))
    return path


def full(folder, version="1.0.0", date="2030-01-01", score=0.9, cases=(1, 2, 3), runs=3, base=0.5, **kw):
    lines = [(c, "with", score, None) for c in cases for _ in range(runs)]
    lines += [(c, "without", base, None) for c in cases for _ in range(runs)]
    return event(folder, "full", version, date, lines, **kw)


def band(root, folder, cfg=None, authors=None):
    return es.skill_band(str(root), str(folder), cfg or CFG, authors)


@pytest.fixture
def root(tmp_path):
    return tmp_path


# --- needs a test, watch, reliable ---------------------------------------------------------------------

def test_a_skill_with_no_evidence_needs_a_full_test(root):
    folder = skill(root)
    row = band(root, folder)
    assert (row["band"], row["kind"], row["cause"]) == ("needs a test", "no passing full test", "no full test of version 1.x")
    assert row["command"] == "python3 evals/eval_run.py --skill core-demo" and row["score"] == 0 and row["runs"] == 0


def test_a_fresh_full_test_of_9_runs_at_0_90_is_reliable(root):
    folder = skill(root)
    full(folder)
    row = band(root, folder)
    assert row["band"] == "reliable" and row["cause"] is None and row["causes"] == []
    assert (row["score"], row["mean"], row["runs"]) == (0.7052, 0.9, 9)
    assert row["gate"]["computed"] and row["gate"]["passed"] and row["last_full_test"]["passed"] is True


def test_the_smallest_skill_at_the_gate_is_done_and_in_watch(root):
    folder = skill(root, cases=[{"id": i, "prompt": "p", "assertions": [f"a{j}" for j in range(10)]} for i in (1, 2)])
    full(folder, score=0.8, cases=(1, 2))
    row = band(root, folder)
    assert row["gate"]["passed"] is True  # done: its first full test passed
    assert (row["band"], row["kind"], round(row["score"], 3)) == ("watch", "score", 0.539)
    assert row["command"] == "python3 evals/eval_run.py --skill core-demo --cases 1,2"


def test_a_y_change_with_nothing_new_is_watch_and_lab_runs_bring_it_back(root):
    folder = skill(root)
    full(folder)
    skill(root, version="1.1.0")
    versions(folder, ("1.0.0", "new"), ("1.1.0", "y"))
    row = band(root, folder)
    assert (row["band"], row["kind"], row["score"], row["runs"]) == ("watch", "no current run", 0.5307, 3)
    assert row["inherited_runs"] == 9 and row["current_runs"] == 0
    event(folder, "partial", "1.1.0", "2030-02-01", [(1, "with", 0.9, None)] * 3)
    assert band(root, folder)["band"] == "watch" and band(root, folder)["score"] == pytest.approx(0.651, abs=1e-3)
    event(folder, "partial", "1.1.0", "2030-02-02", [(2, "with", 1.0, None)] * 3)
    row = band(root, folder)
    assert row["band"] == "reliable" and row["current_runs"] == 6


def test_after_an_x_change_nothing_is_carried_and_the_skill_needs_a_test(root):
    folder = skill(root)
    full(folder)
    skill(root, version="2.0.0")
    row = band(root, folder)
    assert (row["band"], row["kind"], row["score"], row["runs"]) == ("needs a test", "no passing full test", 0, 0)
    full(folder, version="2.0.0", date="2030-02-01")
    assert band(root, folder)["band"] == "reliable"


def test_a_failed_gate_needs_a_test_cause_c_and_a_changed_case_waits_in_watch(root):
    folder = skill(root)
    full(folder, score=0.6, gate={"passed": False, "with": 0.6, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05})
    row = band(root, folder)
    assert (row["band"], row["kind"]) == ("needs a test", "gate failed") and "fails the gate" in row["cause"]
    folder = skill(root / "other")
    full(folder)
    cases = json.loads((folder / "evals" / "evals.json").read_text())
    cases["evals"][0]["prompt"] = "changed"
    (folder / "evals" / "evals.json").write_text(json.dumps(cases))
    row = band(root / "other", folder)
    # A changed case is treated as an added case: it waits for its runs, and the gate is computed over the others.
    assert (row["band"], row["kind"]) == ("watch", "case pending") and "changed after the newest full test" in row["cause"]
    assert row["gate"]["computed"] and row["pending"] == ["1"] and es.gate_of(str(folder), CFG)["changed"] == ["1"]
    assert row["command"] == "python3 evals/eval_run.py --skill core-demo --cases 1 --baseline"


def test_a_raised_measurement_floor_leaves_every_skill_needing_a_test(root):
    folder = skill(root)
    full(folder)
    row = band(root, folder, {**CFG, "measurement_version": 6, "measurement_floor": 6})
    assert (row["band"], row["cause"]) == ("needs a test", "no full test of version 1.x at or above the measurement floor 6")
    assert row["runs"] == 0


def test_an_added_case_is_pending_and_changes_neither_the_gate_nor_the_band(root):
    folder = skill(root)
    full(folder)
    data = json.loads((folder / "evals" / "evals.json").read_text())
    data["evals"].append({"id": 4, "prompt": "new", "assertions": ["a"]})
    (folder / "evals" / "evals.json").write_text(json.dumps(data))
    row = band(root, folder)
    assert row["band"] == "reliable" and row["pending"] == ["4"]
    assert row["pending_command"] == "python3 evals/eval_run.py --skill core-demo --cases 4 --baseline"


def test_three_y_changes_since_the_newest_full_test_ask_for_one(root):
    folder = skill(root, version="1.3.0")
    full(folder, version="1.0.0")
    versions(folder, ("1.0.0", "new"), ("1.1.0", "y"), ("1.1.1", "z"), ("1.2.0", "y"), ("1.3.0", "y"))
    for d in ("2030-02-01", "2030-02-02", "2030-02-03"):
        event(folder, "partial", "1.3.0", d, [(c, "with", 1.0, None) for c in (1, 2, 3)])
    row = band(root, folder)
    assert row["band"] == "watch" and [c["kind"] for c in row["causes"]] == ["y changes"]
    assert row["cause"] == "3 Y changes since the newest full test" and row["command"] == "python3 evals/eval_run.py --skill core-demo"
    full(folder, version="1.3.0", date="2030-03-01", score=1.0)
    assert band(root, folder)["band"] == "reliable"


# --- guards (section 4) ---------------------------------------------------------------------------------

def guard_cases():
    plain = [f"a{j}" for j in range(9)]
    return [{"id": 1, "prompt": "p", "assertions": plain + [{"text": "asks first", "tags": ["guard"]}]},
            {"id": 2, "prompt": "q", "assertions": [{"text": "refuses", "tags": ["guard"]}, {"text": "quotes", "tags": ["guard"]}]},
            {"id": 3, "prompt": "r", "assertions": plain + ["b"]}]


def test_a_confirmed_guard_failure_needs_a_test_and_more_runs_of_the_version_do_not_clear_it(root):
    folder = skill(root, cases=guard_cases())
    full(folder)
    assert band(root, folder)["band"] == "reliable"
    event(folder, "partial", "1.0.0", "2030-02-01", [(1, "with", 0.9, {"guard_failed": [10]})])
    row = band(root, folder)
    assert (row["band"], row["kind"]) == ("needs a test", "guard") and "1.10 failed" in row["cause"]
    assert row["command"] == "after the fix and its bump: python3 evals/eval_run.py --skill core-demo --cases 1"
    assert {"case": "1", "assertion": 10, "state": "failed"} in row["guards"]
    full(folder, date="2030-03-01", score=1.0)
    assert band(root, folder)["kind"] == "guard"  # the failed run stays in the current set
    skill(root, version="1.1.0")
    event(folder, "partial", "1.1.0", "2030-04-01", [(c, "with", 1.0, None) for c in (1, 2, 3) for _ in range(3)])
    assert band(root, folder)["band"] == "reliable"


def test_a_guard_with_no_run_in_the_current_set_needs_a_partial_test_of_the_guard_cases(root):
    folder = skill(root, cases=guard_cases())
    full(folder)
    skill(root, version="1.1.0")
    event(folder, "partial", "1.1.0", "2030-02-01", [(3, "with", 1.0, None)] * 3)
    row = band(root, folder)
    assert (row["band"], row["kind"]) == ("needs a test", "guard") and "have no run in the current set" in row["cause"]
    assert row["command"] == "python3 evals/eval_run.py --skill core-demo --cases 1,2"


def test_guard_cases_alone_do_not_return_a_skill_to_reliable(root):
    folder = skill(root, cases=guard_cases())
    full(folder)
    skill(root, version="1.1.0")
    event(folder, "partial", "1.1.0", "2030-02-01", [(2, "with", 1.0, {"results": [1, 1]})] * 3)
    row = band(root, folder)
    assert row["band"] == "needs a test"  # case 1 holds a guard too, and it has not run
    event(folder, "partial", "1.1.0", "2030-02-02", [(1, "with", 1.0, None)] * 3)
    row = band(root, folder)
    assert row["band"] == "reliable"  # case 1 is not guard-only: it has assertions that are not guards
    folder = skill(root / "b", cases=[{"id": 1, "prompt": "p", "assertions": [{"text": "g", "tags": ["guard"]}]},
                                      {"id": 2, "prompt": "q", "assertions": [f"a{j}" for j in range(10)]}])
    full(folder, cases=(1, 2), runs=6)
    skill(root / "b", version="1.1.0")
    event(folder, "partial", "1.1.0", "2030-02-01", [(1, "with", 1.0, {"results": [1]})] * 9)
    assert band(root / "b", folder)["kind"] == "guard cases only"


# --- the current set and what is inherited (section 6) -------------------------------------------------

def test_an_epoch_makes_the_runs_before_it_inherited_and_the_written_gate_stands(root):
    folder = skill(root)
    full(folder)
    cfg = {**CFG, "epochs": [{"date": "2030-01-15", "models": ["s-model"], "skills": "all", "cause": "the model changed"}]}
    row = band(root, folder, cfg)
    assert (row["band"], row["kind"], row["inherited_runs"]) == ("watch", "no current run", 9)
    assert row["gate"]["note"] == "baseline expired" and row["gate"]["passed"] is True


def test_another_context_or_an_earlier_grader_makes_a_run_inherited(root):
    folder = skill(root)
    full(folder)
    event(folder, "partial", "1.0.0", "2030-02-01", [(1, "with", 1.0, {"context_sha256": H["b"]})] * 3)
    event(folder, "partial", "1.0.0", "2030-02-02", [(2, "with", 1.0, None)] * 3, grader="old-model")
    row = band(root, folder)
    assert (row["current_runs"], row["inherited_runs"], row["runs"]) == (9, 6, 12)


def test_the_earlier_reference_models_runs_count_on_the_new_one_as_inherited(root):
    folder = skill(root)
    full(folder, strong="old-model")
    row = band(root, folder)
    assert row["band"] == "needs a test"  # the gate is the new reference model's: it has no full test
    assert (row["current_runs"], row["inherited_runs"], row["runs"]) == (0, 9, 3)
    assert row["models"]["old-model"]["current_runs"] == 9


def test_the_floor_model_has_its_own_row_and_no_rule_reads_it(root):
    folder = skill(root)
    full(folder)
    event(folder, "partial", "1.0.0", "2030-02-01", [(1, "with", 0.0, {"model": "f-model", "adapter": "fh"})] * 3)
    row = band(root, folder)
    figures = row["models"]["f-model"]
    assert row["band"] == "reliable" and {k: figures[k] for k in ("score", "mean", "runs", "current_runs", "inherited_runs")} == {
        "score": 0.0, "mean": 0.0, "runs": 3, "current_runs": 3, "inherited_runs": 0}
    assert figures["band"] == "needs a test"  # its own band, by the same rules, is information: no rule reads it


def test_the_pass_count_of_each_assertion_and_the_difference_on_assertions_that_are_not_format(root):
    cases = [{"id": 1, "prompt": "p", "assertions": ["a", {"text": "id form", "tags": ["format"]}]}]
    folder = skill(root, cases=cases)
    event(folder, "full", "1.0.0", "2030-01-01", [(1, "with", 1.0, {"results": [1, 1]})] * 3 + [(1, "without", 0.0, {"results": [0, 0]})] * 3)
    row = band(root, folder)
    assert row["assertions"] == [{"case": "1", "assertion": 1, "tags": [], "with": [3, 3], "without": [0, 3]},
                                 {"case": "1", "assertion": 2, "tags": ["format"], "with": [3, 3], "without": [0, 3]}]
    assert row["difference_not_format"] == 1.0


# --- field evidence (section 7) -------------------------------------------------------------------------

def git(root, *args, author="Owner <owner@mail.example>"):
    name, mail = author[:-1].split(" <")
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, "GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": mail,
           "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": mail}
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=env)


def field(folder, lines):
    """Write a contributed field file under its name (the first 12 characters of its sha256)."""
    import hashlib
    data = "".join(json.dumps(l) + "\n" for l in lines).encode()
    path = folder / "evals" / "evidence" / f"field-{hashlib.sha256(data).hexdigest()[:12]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def use(n, verdict=None, model="s-model", week="2030-W10", version="1.0.0", judge="user"):
    base = {"record": "use", "skill": "core-demo", "version": version, "content_sha256": H["a"], "model": model,
            "adapter": "unknown", "use": f"{n:08x}", "week": week}
    out = [base]
    if verdict is not None:
        out.append({**base, "record": "verdict", "score": es.FIELD_SCORES[verdict], "judge": judge})
    return out


@pytest.fixture
def repo(root):
    git(root, "init", "-q", "-b", "main")
    folder = skill(root)
    versions(folder, ("1.0.0", "new"))
    full(folder)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "lab evidence")  # the owner adds lab evidence
    return folder


def test_the_field_signal_counts_one_failed_per_contributor_and_every_failed_of_the_owner(root, repo):
    for i, who in enumerate(("Ana <ana@mail.example>", "Bo <bo@mail.example>")):
        field(repo, use(10 * i + 1, "failed") + use(10 * i + 2, "failed"))
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "field", author=who)
    row = band(root, repo, authors=es.evidence_authors(str(root)))
    assert row["band"] == "reliable" and row["field"] == {"computed": True, "signal": 2, "on": False}
    field(repo, use(31, "failed", week="2030-W11"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "field")  # the owner's own
    row = band(root, repo, authors=es.evidence_authors(str(root)))
    assert (row["band"], row["kind"], row["field"]["signal"]) == ("watch", "field signal", 3)
    assert row["models"]["s-model"]["field"] == {"uses": 5, "judged": 5, "mean": 0.0}
    assert "mail.example" not in json.dumps(row)  # who contributed is never printed


def test_the_field_signal_counts_the_reference_model_the_current_x_y_and_the_weeks_after_its_newest_lab_event(root, repo):
    lines = (use(1, "failed", model="f-model") + use(2, "failed", model="unknown") + use(3, "failed", week="2029-W52")
             + use(4, "failed", week="2030-W01") + use(5, "corrected") + use(6, "failed", judge="check"))
    field(repo, lines)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "field")
    row = band(root, repo, authors=es.evidence_authors(str(root)))
    # The lab event is dated 2030-01-01, week 2030-W01: only use 6 counts (a check's 0 is a failed verdict too).
    assert row["field"]["signal"] == 1
    assert row["models"]["unknown"]["field"] == {"uses": 1, "judged": 1, "mean": 0.0}
    assert row["models"]["s-model"]["field"]["judged"] == 4 and row["models"]["s-model"]["field"]["mean"] == 0.125


def test_field_evidence_never_promotes_and_a_contributor_adds_at_most_20_uses(root, repo):
    skill(root, version="1.1.0")
    versions(repo, ("1.0.0", "new"), ("1.1.0", "y"))
    field(repo, [l for n in range(1, 41) for l in use(n, "worked", version="1.1.0")])
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "field", author="Ana <ana@mail.example>")
    row = band(root, repo, authors=es.evidence_authors(str(root)))
    assert row["band"] == "watch" and row["kind"] == "no current run"
    assert row["models"]["s-model"]["field"] == {"uses": 20, "judged": 20, "mean": 1.0}


def test_a_person_s_verdict_is_shown_over_a_check_s_and_a_use_without_verdict_is_a_use(root, repo):
    field(repo, use(1, "worked", judge="check")[1:] + use(1, "corrected") + use(2))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "field")
    row = band(root, repo, authors=es.evidence_authors(str(root)))
    assert row["models"]["s-model"]["field"] == {"uses": 2, "judged": 1, "mean": 0.5}


def test_without_history_the_field_columns_are_not_computed_and_the_signal_is_off(root):
    folder = skill(root)
    versions(folder, ("1.0.0", "new"))
    full(folder)
    field(folder, use(1, "failed") + use(2, "failed") + use(3, "failed"))
    assert es.evidence_authors(str(root)) is None
    row = band(root, folder, authors=None)
    assert row["band"] == "reliable" and row["field"] == {"computed": False, "signal": 0, "on": False}


@pytest.mark.parametrize("line, why", [
    ({"note": "it went well"}, "unknown key 'note'"),
    ({"count": 3}, "unknown key 'count'"),
    ({"date": "2030-03-04"}, "unknown key 'date'"),
    ({"week": "2030-03-04"}, "week must be YYYY-Www"),
    ({"use": "user-42"}, "use must be 8 hexadecimal characters"),
    ({"model": "my-private-model"}, "model must be an id"),
    ({"record": "opinion"}, "record must be use or verdict"),
])
def test_a_field_line_outside_its_closed_form_is_refused(line, why):
    assert any(why in p for p in es.field_line_problems({**use(1)[0], **line}, {"s-model"}))


def test_a_verdict_takes_the_closed_scores_of_its_judge():
    verdict = use(1, "worked")[1]
    assert es.field_line_problems(verdict) == []
    assert es.field_line_problems({**verdict, "score": 0.7}) and es.field_line_problems({**verdict, "judge": "model"})
    assert es.field_line_problems({**verdict, "judge": "check", "score": 0.5})


def test_a_field_file_is_checked_by_its_name_and_against_the_version_file(root):
    folder = skill(root)
    versions(folder, ("1.0.0", "new"))
    good = field(folder, use(1, "worked"))
    assert es.field_file_problems(str(good), str(root)) == []
    bad = field(folder, use(2, version="0.9.0"))
    assert "not the hash the version file gives for 0.9.0" in es.field_file_problems(str(bad), str(root))[0]
    renamed = good.with_name("field-000000000000.jsonl")
    good.rename(renamed)
    assert "first 12 characters of the file's sha256" in es.field_file_problems(str(renamed), str(root))[0]


# --- the status command and the validator ----------------------------------------------------------------

def gate_file(root, **changes):
    (root / "evals").mkdir(exist_ok=True)
    (root / "evals" / "eval-gate.json").write_text(json.dumps({**CFG, **changes}))


def test_status_prints_a_band_for_every_skill_with_counts_and_causes(root, capsys):
    gate_file(root)
    full(skill(root))
    skill(root, name="eng-other")
    assert es.main(["status"], root=str(root)) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"] == {"needs a test": 1, "watch": 0, "reliable": 1} and out["causes"] == {"no passing full test": 1}
    assert [r["band"] for r in out["skills"]] == ["reliable", "needs a test"]
    assert "status" not in out["skills"][0] and out["gate"]["measurement_floor"] == 5
    assert es.main(["status", "--skill", "eng-other"], root=str(root)) == 0
    assert [r["skill"] for r in json.loads(capsys.readouterr().out)["skills"]] == ["eng-other"]


def test_status_reads_no_old_record(root, capsys):
    gate_file(root)
    folder = skill(root)
    (folder / "evals" / "result.json").write_text("{not even json")
    assert es.main(["status"], root=str(root)) == 0
    assert json.loads(capsys.readouterr().out)["skills"][0]["band"] == "needs a test"


def check(root):
    report = validate.Report()
    validate.check_eval_status(report, root=str(root))
    return [e["message"] for e in report.errors], [w["message"] for w in report.warnings]


def test_the_validator_lists_each_band_as_a_warning_and_never_an_error(root):
    gate_file(root)
    full(skill(root))
    skill(root, name="eng-other")
    skill(root, name="eng-third", cases=[{"id": 1, "prompt": "p", "assertions": [f"a{j}" for j in range(10)]}])
    full(root / "skills" / "eng-third", cases=(1,), score=0.8)
    (root / "docs").mkdir()
    (root / "docs" / "inventory.md").write_text(f"{es.BEGIN}\n{es.END}\n")
    es.main(["inventory", "--write"], root=str(root))
    errors, warnings = check(root)
    assert errors == []
    assert warnings == [
        "[band] 1 skill(s) need a test (python3 evals/eval_status.py status, which prints each one's cause and the command "
        "that clears it): no passing full test (1): eng-other",
        "[band] 1 skill(s) are in watch (python3 evals/eval_status.py status, which prints each one's cause and the command "
        "that clears it): score (1): eng-third"]


def test_the_validator_fails_on_an_evidence_file_that_is_not_valid(root):
    gate_file(root)
    folder = skill(root)
    path = full(folder)
    path.write_text(path.read_text().replace('"outcome": "graded"', '"outcome": "great"', 1))
    field(folder, [{**use(1)[0], "note": "free text"}])
    errors, _ = check(root)
    assert any(e.startswith("[evidence] line 2: outcome must be graded or timeout") for e in errors)
    assert any(e.startswith("[evidence] line 1: unknown key 'note'") for e in errors)


def test_the_repository_reads_needs_a_test_for_every_skill_until_it_has_a_full_test():
    """Phase B's exit: a band for each of the 48 skills, computed from evidence; none has a full test yet."""
    out = es.all_status(str(REPO))
    assert len(out["skills"]) >= 48
    no_evidence = [r for r in out["skills"] if not list((REPO / "skills" / r["skill"] / "evals" / "evidence").glob("lab-*"))]
    assert all(r["band"] == "needs a test" and r["kind"] == "no passing full test" for r in no_evidence)


def test_the_runner_and_the_score_compute_one_context_hash():
    """eval_run.py writes the context of a run with eval_status.case_context, the function the score compares with."""
    text = (REPO / "evals" / "eval_run.py").read_text()
    assert "status.case_context(ROOT, skill_dir, case, with_skill" in text
    folder = REPO / "skills" / "mkt-publish"
    case = {"id": 1, "platforms": ["linkedin"]}
    with_skill = es.case_context(str(REPO), str(folder), case, True)
    assert with_skill is not es.UNKNOWN_CONTEXT and with_skill != es.case_context(str(REPO), str(folder), case, False)
    assert es.case_context(str(REPO), str(folder), {"id": 2}, False) is None

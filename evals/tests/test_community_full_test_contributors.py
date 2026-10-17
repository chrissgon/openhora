"""Offline tests of the rule "a community full test counts only through its pool" (follow-up F2-B of the delegation plan; the
reliability model, section 2): in the community source the pooled route is always on, one fork's full test fills at most
floor(runs x 2/3) of the counted lines of each case so it never closes a pool alone, and the gate is the newest closed pool's,
never the newest full test's. The contributor rule itself is P11's (pool_of, POOL_MIN_CONTRIBUTORS, POOL_MAX_SHARE; its share
check stays covered by test_quick_pool.py); here only the full test is new. The lab and the local sources are gated as before.
No model, no network: evidence is written in the forms test_bands.py and test_community_evidence.py write it.

Run: uv run --with pytest pytest evals/tests/test_community_full_test_contributors.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


tb = load("test_bands", "bands_tests_for_community_full_test")
tc = load("test_community_evidence", "community_tests_for_community_full_test")
es, CFG = tb.es, tb.CFG
NO_POOL = "no closed community pool: a community test counts only through the pool, with lines from at least 2 contributors"


@pytest.fixture
def croot(tmp_path):
    tc.git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


@pytest.fixture
def crepo(croot):
    folder = tb.skill(croot)
    tb.versions(folder, ("1.0.0", "new"))
    return folder


def fork(folder, who, run_id, date, **kw):
    """One community test of `who`'s fork (ana 111, bo 222, cy 333) on old-model; a full test unless kw says otherwise."""
    repo_id = {"ana": 111, "bo": 222, "cy": 333}[who]
    return tc.community(folder, model="old-model", adapter="oh", repo_id=repo_id, run_id=run_id, run_number=run_id, date=date,
                        repository=f"{who}/openhora", **kw)


def community_row(croot, model="old-model"):
    tc.commit(croot)
    return tc.section(croot)["skills"]["core-demo"][model]


# --- 1. one fork's full test never makes a pair reliable --------------------------------------------------------------------

def test_one_forks_passing_full_test_does_not_close_the_pool_and_the_pair_needs_a_test(croot, crepo):
    fork(crepo, "ana", 1, "2030-01-01")  # 3 runs a case with the skill and 3 without it: passes the gate, with its own baseline
    found = community_row(croot)
    pool = found["pool"]
    assert pool["closed"] is False and pool["lines"] == 9 and pool["counted"] == 6  # floor(3 x 2/3) = 2 counted lines a case
    assert pool["contributors"] == 1 and pool["cases_at_runs"] == 0 and pool["baseline_cases"] == 3
    assert (found["band"], found["kind"]) == ("needs a test", "no passing full test")
    assert NO_POOL in found["cause"] and "1 of 2 contributors" in found["cause"]
    assert found["community_only"] is False
    assert found["command"] == "python3 evals/eval_run.py --skill core-demo --quick"  # the hint of an open pool, unchanged
    assert found["last_full_test"]["passed"] is True  # the full test is still shown; it does not decide
    assert found["gate"]["passed"] is None and found["gate"]["computed"] is False


def test_the_same_full_test_in_the_lab_is_a_passing_gate_and_the_pair_is_reliable(croot, crepo):
    """The contrast: the rule is the community source's alone."""
    tb.full(crepo, score=0.9)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    lab = tb.band(croot, crepo)
    assert lab["band"] == "reliable" and lab["gate"]["passed"] is True and "pool" not in lab


# --- 2. a second fork that holds too little does not close it ---------------------------------------------------------------

def test_a_second_fork_with_a_partial_test_of_one_case_leaves_the_pool_open(croot, crepo):
    fork(crepo, "ana", 1, "2030-01-01")
    fork(crepo, "ana", 2, "2030-01-02")  # her second full test: she already holds two lines in each case, so nothing more counts
    fork(crepo, "bo", 1, "2030-01-03", kind="partial", cases=(1,))  # bo's third line of case 1 only
    found = community_row(croot)
    pool = found["pool"]
    assert pool["closed"] is False and pool["contributors"] == 2 and pool["cases_at_runs"] == 1
    assert pool["counted"] == 7 and pool["lines"] == 21  # case 1: ana 2 + bo 1; cases 2 and 3: ana 2 each
    assert (found["band"], found["kind"]) == ("needs a test", "no passing full test")
    assert NO_POOL in found["cause"] and "1 of 3 cases at 3 runs" in found["cause"]


# --- 3. two balanced forks close it -----------------------------------------------------------------------------------------

def test_two_forks_full_tests_close_the_pool_and_the_pair_is_reliable_but_community_only(croot, crepo):
    tb.event(crepo, "partial", "1.0.0", "2029-12-01", [(1, "with", 0.9, {"model": "old-model", "adapter": "oh"})], strong="old-model")
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence: a partial test, so the lab band is not reliable")
    fork(crepo, "ana", 1, "2030-01-01")
    fork(crepo, "bo", 1, "2030-01-02")
    found = community_row(croot)
    pool = found["pool"]
    assert pool["closed"] is True and pool["contributors"] == 2 and found["contributors"] == 2
    assert pool["counted"] == 9 and pool["lines"] == 18 and pool["cases_at_runs"] == 3
    assert "the largest holding 67% of the counted lines (at most 67%)" in pool["progress"]
    assert found["band"] == "reliable" and found["gate"]["note"] == "pooled" and found["gate"]["passed"] is True
    assert found["community_only"] is True
    lab = es.all_status(str(croot), "core-demo")["skills"][0]["models"]["old-model"]
    assert lab["band"] != "reliable"  # reliable only through the community column


# --- 4. a failing pool stays failed -----------------------------------------------------------------------------------------

def test_a_failing_two_fork_pool_fails_the_gate_and_a_third_forks_full_test_does_not_turn_it(croot, crepo):
    fork(crepo, "ana", 1, "2030-01-01", with_score=0.6, base_score=0.5)
    fork(crepo, "bo", 1, "2030-01-02", with_score=0.6, base_score=0.5)
    failing = community_row(croot)
    assert failing["pool"]["closed"] is True and failing["pool"]["gate"]["passed"] is False
    assert (failing["band"], failing["kind"]) == ("needs a test", "gate failed")
    assert "the pooled gate of 1.0 fails" in failing["cause"] and failing["community_only"] is False
    fork(crepo, "cy", 1, "2030-01-03", with_score=0.95, base_score=0.5)  # a good full test of the same X.Y, from a third fork
    after = community_row(croot)
    assert (after["band"], after["kind"]) == ("needs a test", "gate failed")
    assert "the pooled gate of 1.0 fails" in after["cause"]
    assert after["pool"]["gate"]["passed"] is False
    assert after["pool"]["gate"]["with"] == pytest.approx(failing["pool"]["gate"]["with"])  # the first three lines of each case say it
    assert after["contributors"] == 3 and after["pool"]["lines"] == 27  # the third fork's lines come last: they count for the score alone
    assert after["pool"]["counted"] == 9 and after["pool"]["contributors"] == 2


# --- 5. the lab and the local sources are gated as before -------------------------------------------------------------------

def test_the_predicate_is_the_community_sources_alone():
    assert es.community_rule(None) is False and es.community_rule({}) is False
    assert es.community_rule({"baseline_events": [], "baseline_first": "own"}) is False  # a local pool
    assert es.community_rule({"baseline_events": [], "baseline_first": "other", "who": {}, "cap": 30}) is True


def test_a_lab_skill_tested_by_full_tests_alone_is_gated_exactly_as_before(croot, crepo):
    tb.full(crepo, score=0.9)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    plain = tb.band(croot, crepo)
    assert plain["band"] == "reliable" and plain["gate"]["passed"] is True and plain["gate"]["note"] is None
    assert "pool" not in plain and plain["last_full_test"]["passed"] is True
    # A rule without "who" (a local pool's) takes the same road: the full test gates, and no route is turned on.
    rule = {"baseline_events": es.skill_evidence(str(crepo)), "baseline_first": "own"}
    with_rule = es.skill_band(str(croot), str(crepo), CFG, None, events=es.skill_evidence(str(crepo)), pool_rule=rule)
    assert with_rule == plain
    # The gate of a full test that fails is the full test's, too.
    failing = tb.skill(croot, name="core-fail")
    tb.versions(failing, ("1.0.0", "new"))
    tb.full(failing, score=0.5, gate={"passed": False, "with": 0.5, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05})
    row = tb.band(croot, failing)
    assert (row["band"], row["kind"]) == ("needs a test", "gate failed") and "pooled" not in json.dumps(row["causes"])


def test_a_local_pair_with_one_full_test_is_gated_as_before(croot, crepo, tmp_path):
    """A person's own tests of their machine (the local source) have no contributors to count: one full test gates."""
    path = tb.full(crepo, score=0.9)
    base = tmp_path / "local-evidence"
    target = base / "core-demo" / path.name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(path.read_text())
    path.unlink()
    found = es.local_status(str(croot), "core-demo", CFG, str(base))["s-model"]
    assert found["band"] == "reliable" and found["gate"]["passed"] is True and found["gate"]["note"] is None
    assert "pool" not in found

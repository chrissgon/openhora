"""Offline tests of quick tests and the pooled gate (package P11; the reliability model, section 2): the third kind of event, its
validation, what a quick test alone does (the score moves, no band and no gate), the pool of the with-skill lines of one skill, one
model and one evidence source, its close condition and its gate (the unchanged rule), the progress text of an open pool, the
contributors a community pool needs, the sources that never mix, the pool that starts empty after a Y change, the count of Y
changes that a closed pool resets, the guard assertions that quick runs satisfy, and the runner's `--quick` with a stand-in
adapter. No model is called: evidence is written here, in the forms test_bands.py and test_community_evidence.py write it.

Run: uv run --with pytest pytest evals/tests/test_quick_pool.py
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(module, name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{module}.py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


tb = load("test_bands", "bands_tests_for_quick_pool")
tc = load("test_community_evidence", "community_tests_for_quick_pool")
t = load("test_eval_run", "eval_run_tests_for_quick_pool")
es, CFG, el = tb.es, tb.CFG, tb.es.EVIDENCE_LINES
er = t.er


# --- a quick event, as the runner writes it --------------------------------------------------------------------------

def quick(folder, version="1.0.0", date="2030-01-01", score=0.9, cases=(1, 2, 3), complete=True, **kw):
    """One quick test: every case once with the skill, runs 1, no baseline, no gate (what eval_run.py --quick writes)."""
    path = tb.event(folder, "quick", version, date, [(c, "with", score, None) for c in cases], complete=complete, **kw)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    lines[0]["runs"] = 1
    lines[0]["baseline"] = {c: "none" for c in lines[0]["cases"]}
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def baseline(folder, version="1.0.0", date="2029-12-01", score=0.5, cases=(1, 2, 3), per_case=3, **kw):
    """The baseline in force: lines without the skill, in a partial test (`--cases <ids> --baseline`)."""
    return tb.event(folder, "partial", version, date, [(c, "without", score, None) for c in cases for _ in range(per_case)], **kw)


def quicks(folder, count, **kw):
    """count quick tests, one a day, from the 1st of the month."""
    return [quick(folder, date=f"2030-01-{n:02d}", **kw) for n in range(1, count + 1)]


def row(root, folder, cfg=None):
    return tb.band(root, folder, cfg or CFG)


@pytest.fixture
def root(tmp_path):
    return tmp_path


@pytest.fixture
def demo(root):
    folder = tb.skill(root)
    tb.versions(folder, ("1.0.0", "new"))
    return folder


# --- the event line and the run line of a quick test -----------------------------------------------------------------

def valid(path, **kw):
    return es.evidence_file_problems(str(path), None, "core-demo", **kw)


def test_a_quick_event_is_valid_and_old_files_stay_valid(root, demo):
    assert valid(quick(demo)) == []
    assert valid(tb.full(demo)) == [] and valid(baseline(demo)) == []
    assert es.KINDS == ("full", "partial", "quick")


@pytest.mark.parametrize("change, why", [
    (lambda e: e.update(runs=3), "runs must be 1 in a quick test"),
    (lambda e: e.update(baseline={"1": "run", "2": "none", "3": "none"}), "baseline must be none for every case of a quick test"),
    (lambda e: e.update(baseline={"1": "reused", "2": "reused", "3": "reused"}), "baseline must be none for every case of a quick test"),
    (lambda e: e.update(gate={"passed": True, "with": 0.9, "baseline": 0.5, "threshold": 0.8, "tolerance": 0.05}),
     "gate belongs to a full test only"),
])
def test_a_quick_event_line_outside_its_form_is_an_error(root, demo, change, why):
    path = quick(demo)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    change(lines[0])
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert any(why in p for p in valid(path)), valid(path)


def test_a_quick_test_has_no_line_without_the_skill_and_no_platform_line(root, demo):
    path = quick(demo)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    lines.append({**lines[1], "variant": "without"})
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert any("a quick test runs with the skill only" in p for p in valid(path))
    lines[-1] = {**lines[1], "platform": "demo-net"}
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert any("a line of a platform's case runs in a partial test" in p for p in valid(path))


def test_a_quick_test_has_at_most_one_line_a_case_and_a_complete_one_has_a_line_for_every_case(root, demo):
    path = quick(demo)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines + [lines[1]]))
    assert any("more than the event's \"runs\", 1" in p for p in valid(path))
    path.write_text("".join(json.dumps(line) + "\n" for line in lines[:-1]))  # the line of case 3 is missing
    assert any("a complete quick test has a line with the skill for every case" in p and "case(s) 3" in p for p in valid(path))
    lines[0]["complete"] = False  # an abandoned quick test (closed) keeps the lines it has
    path.write_text("".join(json.dumps(line) + "\n" for line in lines[:-1]))
    assert valid(path) == []


def test_a_new_quick_file_is_read_against_one_run_and_the_other_kinds_against_the_configured_runs(root, demo):
    strict = {"models": {"s-model", "f-model"}, "runs": 3}
    assert valid(quick(demo), strict=strict) == []
    assert valid(tb.full(demo, date="2030-02-01"), strict=strict) == []
    path = quick(demo, date="2030-03-01")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert el.configured_runs(lines[0], strict) == 1 and el.configured_runs({**lines[0], "kind": "full"}, strict) == 3
    lines[0]["kind"], lines[0]["complete"] = "full", False  # the same event line written as a (given up) full test
    for line in lines[1:]:
        line["kind"] = "full"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert any("runs is 1, and the configured number is 3" in p for p in valid(path, strict=strict))


# --- a quick test alone ----------------------------------------------------------------------------------------------

def test_a_quick_test_alone_moves_the_score_and_never_the_band_or_the_gate(root, demo):
    before = row(root, demo)
    assert (before["band"], before["kind"], before["score"], before["runs"]) == ("needs a test", "no passing full test", 0, 0)
    assert "pool" not in before
    quick(demo)
    after = row(root, demo)
    assert after["runs"] == 3 and after["score"] > 0 and after["mean"] == 0.9  # the score moved
    assert (after["band"], after["kind"]) == ("needs a test", "no passing full test")  # and the band did not
    assert after["gate"]["computed"] is False and after["gate"]["passed"] is None
    assert after["pool"]["closed"] is False and after["pool"]["quick_lines"] == 3


def test_the_cause_of_an_open_pool_shows_its_progress_and_the_command_is_a_quick_test(root, demo):
    baseline(demo)
    quicks(demo, 2)
    r = row(root, demo)
    text = "pool of 1.0: 0 of 3 cases at 3 runs; baseline in force for 3; lines from 2030-01-01 to 2030-01-02"
    assert r["cause"] == f"no full test of version 1.x and no closed pool ({text})"
    assert r["command"] == "python3 evals/eval_run.py --skill core-demo --quick"
    assert r["pool"]["progress"] == text and (r["pool"]["from"], r["pool"]["to"]) == ("2030-01-01", "2030-01-02")
    assert (r["pool"]["cases"], r["pool"]["cases_at_runs"], r["pool"]["baseline_cases"], r["pool"]["lines"]) == (3, 0, 3, 6)


def test_a_pool_missing_one_case_stays_open_with_the_progress_text(root, demo):
    baseline(demo)
    quicks(demo, 2)
    quick(demo, date="2030-01-03", cases=(1, 2))  # case 3 has two lines, the others three
    r = row(root, demo)
    text = "pool of 1.0: 2 of 3 cases at 3 runs; baseline in force for 3; lines from 2030-01-01 to 2030-01-03"
    assert r["pool"]["closed"] is False and r["band"] == "needs a test" and r["gate"]["computed"] is False
    assert r["pool"]["progress"] == text and text in r["cause"]


def test_a_pool_without_a_baseline_in_force_stays_open_whatever_its_lines(root, demo):
    quicks(demo, 3)
    baseline(demo, cases=(1, 2))
    r = row(root, demo)
    assert r["pool"]["closed"] is False and r["pool"]["cases_at_runs"] == 3 and r["pool"]["baseline_cases"] == 2
    assert r["band"] == "needs a test" and "baseline in force for 2" in r["cause"]


# --- a closed pool ----------------------------------------------------------------------------------------------------

def test_three_quick_tests_and_a_baseline_in_force_close_the_pool_and_a_passing_one_is_a_passing_full_test(root, demo):
    baseline(demo)
    quicks(demo, 3)
    r = row(root, demo)
    assert r["pool"]["closed"] is True
    assert r["pool"]["progress"] == "pool of 1.0: 3 of 3 cases at 3 runs; baseline in force for 3; lines from 2030-01-01 to 2030-01-03"
    assert (r["band"], r["cause"], r["causes"]) == ("reliable", None, [])
    gate = r["gate"]
    assert (gate["computed"], gate["passed"], gate["note"], gate["version"]) == (True, True, "pooled", "1.0")
    assert gate["with"] == pytest.approx(0.9) and gate["baseline"] == pytest.approx(0.5)
    assert r["pool"]["gate"]["passed"] is True and r["pool"]["deciding"]["gate"]["passed"] is True
    assert r["last_full_test"] is None  # it is a pool, not a full test: the status says so


def test_a_closed_pool_that_fails_the_gate_is_a_failed_gate_and_the_band_needs_a_test(root, demo):
    baseline(demo, score=0.5)
    quicks(demo, 3, score=0.6)
    r = row(root, demo)
    assert r["pool"]["closed"] is True
    assert r["gate"]["computed"] is True and r["gate"]["passed"] is False and r["gate"]["note"] == "pooled"
    assert (r["band"], r["kind"]) == ("needs a test", "gate failed")
    assert r["cause"] == ("the pooled gate of 1.0 fails (with the skill 0.600, baseline 0.500; the first 3 lines of each case, "
                          "9 of 9, dated 2030-01-01 to 2030-01-03)")
    assert r["command"] == "after the fix: python3 evals/eval_run.py --skill core-demo --quick"


# --- the gate reads the first `runs` lines of each case, and nothing else -------------------------------------------------

def test_the_gate_of_a_closed_pool_reads_the_first_three_lines_of_each_case_and_later_lines_move_only_the_score(root, demo):
    baseline(demo)
    quicks(demo, 3, score=0.6)
    failing = row(root, demo)
    assert failing["gate"]["passed"] is False and failing["gate"]["with"] == pytest.approx(0.6)
    for n in range(4, 13):  # nine more quick tests, all at 1.0: a top-up that would pass a pool that reads every line
        quick(demo, date=f"2030-01-{n:02d}", score=1.0)
    for d in ("2030-02-01", "2030-02-02"):  # and partial reruns of the case that did worst
        tb.event(demo, "partial", "1.0.0", d, [(1, "with", 1.0, None)] * 3)
    after = row(root, demo)
    assert after["gate"]["passed"] is False and after["gate"]["with"] == pytest.approx(0.6)  # the gate did not move
    assert after["gate"]["test"] == failing["gate"]["test"] and (after["band"], after["kind"]) == ("needs a test", "gate failed")
    assert after["pool"]["lines"] == 12 * 3 + 6 and after["pool"]["counted"] == 9
    assert after["mean"] > failing["mean"] and after["runs"] > failing["runs"]  # the score read every line


def test_the_first_lines_are_chosen_by_time_so_a_later_line_never_changes_an_earlier_one(root, demo):
    baseline(demo)
    quick(demo, date="2030-01-02", score=0.9)
    quick(demo, date="2030-01-01", score=0.9)  # written second, dated first: time decides, not the order of writing
    quick(demo, date="2030-01-03", score=0.9)
    first = row(root, demo)["gate"]
    quick(demo, date="2030-01-04", score=0.0)
    assert row(root, demo)["gate"] == first
    # A later partial test of one case adds nothing to the gate either.
    tb.event(demo, "partial", "1.0.0", "2030-01-05", [(1, "with", 0.0, None)] * 3)
    assert row(root, demo)["gate"] == first


def test_the_pool_is_judged_by_the_unchanged_rule_of_the_gate_means_per_case_first(root, demo):
    """Case 1 is 1.0 in its three counted lines, cases 2 and 3 are 0.5: the mean of the cases' means is 0.667, below the threshold,
    whatever the lines after them say; the baseline at 0.2 leaves only the threshold to decide."""
    baseline(demo, score=0.2)
    quicks(demo, 3, score=0.5, cases=(2, 3))
    for n in range(4, 7):
        quick(demo, date=f"2030-01-{n:02d}", score=1.0, cases=(1,))
    r = row(root, demo)
    assert r["pool"]["closed"] is True
    assert r["gate"]["with"] == pytest.approx((1.0 + 0.5 + 0.5) / 3) and r["gate"]["baseline"] == pytest.approx(0.2)
    assert r["gate"]["passed"] is False and (r["band"], r["kind"]) == ("needs a test", "gate failed")
    assert es.load_measure().gate_passes(0.8, 0.2, CFG["threshold"], CFG["tolerance"]) is True  # a mean of the lines would pass


def test_targeted_partial_reruns_after_a_failing_full_test_cannot_turn_the_gate_once_a_quick_test_exists(root, demo):
    """The reviewer's fixture: case 1 unlucky at 0.5 in a full test (mean 0.767, below 0.8); partial reruns of case 1, then one quick
    test. The lines of the full test are the first three of each case: the pool reads them, and nothing after them."""
    lines = [(1, "with", 0.5, None)] * 3 + [(c, "with", 0.9, None) for c in (2, 3) for _ in range(3)]
    lines += [(c, "without", 0.4, None) for c in (1, 2, 3) for _ in range(3)]
    tb.event(demo, "full", "1.0.0", "2030-01-01", lines,
             gate={"passed": False, "with": 0.767, "baseline": 0.4, "threshold": 0.8, "tolerance": 0.05})
    for d in ("2030-01-02", "2030-01-03"):
        tb.event(demo, "partial", "1.0.0", d, [(1, "with", 0.9, None)] * 3)
    quick(demo, date="2030-01-04", score=0.8)
    r = row(root, demo)
    assert r["gate"]["passed"] is False and r["gate"]["note"] is None  # the full test stands: the pool's newest counted test is it
    assert (r["band"], r["kind"]) == ("needs a test", "gate failed") and r["pool"]["counted"] == 9


def test_a_full_test_given_up_and_quick_tests_that_fill_it_close_the_pool(root, demo):
    full = tb.event(demo, "full", "1.0.0", "2030-01-01",
                    [(c, "with", 0.9, None) for c in (1, 2) for _ in range(3)] + [(3, "with", 0.9, None)]
                    + [(c, "without", 0.5, None) for c in (1, 2, 3) for _ in range(3)], complete=False)
    assert valid(full) == []
    before = row(root, demo)
    assert before["last_full_test"]["complete"] is False
    quick(demo, date="2030-01-02")
    quick(demo, date="2030-01-03")
    after = row(root, demo)
    assert after["pool"]["closed"] is True and after["gate"]["note"] == "pooled"
    assert after["gate"]["passed"] is True and after["band"] == "reliable"
    assert after["pool"]["tests"] == 3 and after["pool"]["quick_lines"] == 6


def test_a_full_test_alone_is_gated_exactly_as_before_and_has_no_pool(root, demo):
    tb.full(demo)
    quick_free = row(root, demo)
    assert "pool" not in quick_free and quick_free["band"] == "reliable" and quick_free["gate"]["note"] is None
    tb.event(demo, "partial", "1.0.0", "2030-01-02", [(1, "with", 0.1, None)] * 3)  # a partial test never moves the gate
    again = row(root, demo)
    assert "pool" not in again and again["gate"] == quick_free["gate"]  # and, with no quick test, there is no pooled route


def test_a_later_full_test_stands_over_an_older_pool(root, demo):
    baseline(demo)
    quicks(demo, 3, score=0.6)  # a closed pool, failing the gate
    assert row(root, demo)["band"] == "needs a test"
    tb.full(demo, date="2030-03-01", score=0.9)  # a later full test of the same X.Y passes by itself
    r = row(root, demo)
    assert r["gate"]["note"] is None and r["gate"]["test"] > r["pool"]["deciding"]["test"]
    # The gate passes; the weak quick lines still count in the score (the band is watch, for a pessimistic score under 0.70).
    assert r["gate"]["passed"] is True and (r["band"], r["kind"]) == ("watch", "score")


# --- the guards, the Y changes, a new X.Y -----------------------------------------------------------------------------

def test_quick_runs_satisfy_the_guard_assertions_they_run(root):
    cases = [{"id": i, "prompt": f"p{i}", "assertions": [{"text": "asks first", "tags": ["guard"]}] + [f"a{j}" for j in range(9)]}
             for i in (1, 2, 3)]
    folder = tb.skill(root, cases=cases)
    tb.versions(folder, ("1.0.0", "new"))
    assert [g["state"] for g in row(root, folder)["guards"]] == ["not run"] * 3
    quick(folder, cases=(1, 2))
    assert [g["state"] for g in row(root, folder)["guards"]] == ["passed", "passed", "not run"]
    path = tb.event(folder, "quick", "1.0.0", "2030-01-02", [(3, "with", 0.9, {"guard_failed": [1], "results": [0] + [1] * 9})])
    states = {g["case"]: g["state"] for g in row(root, folder)["guards"]}
    assert states == {"1": "passed", "2": "passed", "3": "failed"} and path.exists()


def test_a_y_change_starts_a_new_pool_and_the_old_closed_pool_still_counts_as_a_full_test_would(root, demo):
    baseline(demo)
    quicks(demo, 3)
    assert row(root, demo)["band"] == "reliable"
    tb.skill(root, version="1.1.0")
    tb.versions(demo, ("1.0.0", "new"), ("1.1.0", "y"))
    r = row(root, demo)
    assert r["pool"]["xy"] == "1.1" and r["pool"]["lines"] == 0 and r["pool"]["closed"] is False  # the new X.Y starts empty
    assert r["pool"]["progress"] == "pool of 1.1: 0 of 3 cases at 3 runs; baseline in force for 3"
    assert r["pool"]["deciding"]["xy"] == "1.0"  # the pool of 1.0 stays the newest closed pool, as a full test of 1.0 would
    assert r["gate"]["version"] == "1.0" and r["gate"]["passed"] is True
    assert (r["band"], r["kind"]) == ("watch", "no current run")  # what a full test of the earlier X.Y gives too
    quicks_new = [quick(demo, version="1.1.0", date=f"2030-02-{n:02d}") for n in (1, 2, 3)]
    assert len(quicks_new) == 3
    closed = row(root, demo)
    assert closed["pool"]["closed"] is True and closed["pool"]["lines"] == 9 and closed["band"] == "reliable"
    assert closed["gate"]["version"] == "1.1"


def test_three_y_changes_make_the_skill_watch_and_a_closed_pool_resets_the_count(root, demo):
    baseline(demo)
    quicks(demo, 3)
    tb.skill(root, version="1.3.0")  # a pool of 1.0 closed long ago, then three Y changes
    tb.versions(demo, ("1.0.0", "new"), ("1.1.0", "y"), ("1.2.0", "y"), ("1.3.0", "y"))
    tb.event(demo, "partial", "1.3.0", "2030-02-01", [(c, "with", 0.9, None) for c in (1, 2, 3) for _ in range(4)])  # a current set
    r = row(root, demo)
    assert r["pool"]["xy"] == "1.3" and r["pool"]["deciding"]["xy"] == "1.0"
    assert (r["band"], r["kind"]) == ("watch", "y changes") and r["cause"] == "3 Y changes since the newest full test"
    # The partial test brought every case of 1.3 to 4 lines, and the baseline is in force: the pool of 1.3 closes with one quick
    # test, and counts as a full test of 1.3 for the Y changes.
    quick(demo, version="1.3.0", date="2030-02-02")
    r = row(root, demo)
    assert r["pool"]["closed"] is True and r["pool"]["xy"] == "1.3" and r["gate"]["version"] == "1.3"
    assert "y changes" not in [c["kind"] for c in r["causes"]] and r["band"] == "reliable"


CASES_3 = [{"id": i, "prompt": f"p{i}", "assertions": [f"a{j}" for j in range(10)]} for i in (1, 2, 3)]


def changed_third(extra=None):
    """The three cases, the third one with another prompt (a changed case), or with one more case after it (an added one)."""
    cases = [dict(c) for c in CASES_3]
    if extra:
        return cases + [extra]
    cases[2] = {**cases[2], "prompt": "p3 changed"}
    return cases


def test_a_case_changed_after_the_pool_closed_is_pending_and_the_band_is_watch_as_for_a_full_test(root, demo):
    baseline(demo)
    quicks(demo, 3)
    assert row(root, demo)["band"] == "reliable"
    tb.skill(root, cases=changed_third())
    r = row(root, demo)
    assert r["pool"]["closed"] is True and r["pool"]["pending"] == ["3"] and r["pool"]["changed"] == ["3"]
    assert r["gate"]["passed"] is True and r["gate"]["note"] == "pooled" and r["pool"]["gate_cases"] == ["1", "2"]
    assert (r["band"], r["kind"]) == ("watch", "case pending")
    assert r["gate"]["with"] == pytest.approx(0.9) and r["pending"] == ["3"]
    assert "case(s) 3 changed after the newest full test and wait for their runs (case 3 had 3 run(s) of mean 0.900)" in r["cause"]
    assert r["command"] == "python3 evals/eval_run.py --skill core-demo --cases 3 --baseline"
    # The same change on a skill with a full test, for the comparison the review asked for.
    full = tb.skill(root, name="core-full", cases=CASES_3)
    tb.versions(full, ("1.0.0", "new"))
    tb.full(full)
    tb.skill(root, name="core-full", cases=changed_third())
    f = tb.band(root, full, CFG)
    assert (f["band"], f["kind"]) == (r["band"], r["kind"])


def test_a_case_added_after_the_pool_closed_is_pending_and_enters_the_gate_once_it_has_its_runs(root, demo):
    baseline(demo)
    quicks(demo, 3)
    added = {"id": 4, "prompt": "p4", "assertions": [f"a{j}" for j in range(10)]}
    tb.skill(root, cases=CASES_3 + [added])
    r = row(root, demo)
    assert r["pool"]["closed"] is True and r["pool"]["pending"] == ["4"] and r["pool"]["changed"] == []
    assert r["pool"]["gate_cases"] == ["1", "2", "3"] and r["pending"] == ["4"]
    assert r["band"] == "reliable"  # an added case waits and changes no band, as for a full test
    assert r["pending_command"] == "python3 evals/eval_run.py --skill core-demo --cases 4 --baseline"
    # Its runs and its baseline: it enters the gate, which is then computed on all four cases.
    tb.event(demo, "partial", "1.0.0", "2030-02-01", [(4, "with", 0.9, None)] * 3 + [(4, "without", 0.5, None)] * 3)
    after = row(root, demo)
    assert after["pool"]["gate_cases"] == ["1", "2", "3", "4"] and after["pending"] == [] and after["pool"]["pending"] == []


def test_a_case_changed_again_after_its_changed_text_ran_cannot_be_computed_and_the_band_needs_a_test(root, demo):
    baseline(demo)
    quicks(demo, 3)
    tb.skill(root, cases=changed_third())
    # The changed text of case 3 runs (not enough to count) ...
    tb.event(demo, "partial", "1.0.0", "2030-02-01", [(3, "with", 0.9, None)])
    cases = changed_third()
    cases[2] = {**cases[2], "prompt": "p3 changed again"}
    tb.skill(root, cases=cases)  # ... and the case changes a second time
    r = row(root, demo)
    assert r["pool"]["closed"] is False and "case(s) 3 changed again after the pool closed" in r["pool"]["progress"]
    assert r["band"] == "needs a test"


def test_an_epoch_after_the_pool_closed_leaves_its_result_standing_and_the_band_is_watch_as_for_a_full_test(root, demo):
    baseline(demo)
    quicks(demo, 3)
    cfg = {**CFG, "epochs": [{"date": "2030-06-01", "models": "all", "skills": "all", "cause": "a hosted model changed"}]}
    r = row(root, demo, cfg)
    assert r["pool"]["lines"] == 0 and r["pool"]["closed"] is False and r["pool"]["baseline_cases"] == 0  # the new era starts empty
    assert r["pool"]["deciding"]["frozen"] is True
    assert r["gate"]["computed"] is False and r["gate"]["passed"] is True and r["gate"]["note"] == "pooled, baseline expired"
    assert r["gate"]["with"] == pytest.approx(0.9)
    assert (r["band"], r["kind"]) == ("watch", "no current run")
    full = tb.skill(root, name="core-full", cases=CASES_3)
    tb.versions(full, ("1.0.0", "new"))
    tb.full(full)
    f = tb.band(root, full, cfg)
    assert (f["band"], f["kind"]) == (r["band"], r["kind"])  # the review's asymmetry is gone
    # A pool of the new era closes on its own lines and baseline, and decides again.
    baseline(demo, date="2030-06-02")
    for n in (3, 4, 5):
        quick(demo, date=f"2030-06-{n:02d}")
    again = row(root, demo, cfg)
    assert again["pool"]["closed"] is True and again["gate"]["computed"] is True and again["gate"]["note"] == "pooled"
    assert again["band"] == "reliable"


def test_a_frozen_pool_that_failed_stays_failed_after_an_epoch(root, demo):
    baseline(demo)
    quicks(demo, 3, score=0.6)
    cfg = {**CFG, "epochs": [{"date": "2030-06-01", "models": "all", "skills": "all", "cause": "a hosted model changed"}]}
    r = row(root, demo, cfg)
    assert (r["band"], r["kind"]) == ("needs a test", "gate failed") and "baseline expired" in r["cause"]


def test_the_pool_reads_the_lines_of_the_subject_model_only(root, demo):
    baseline(demo)
    quicks(demo, 3)
    other = tb.es.as_subject(CFG, "f-model")
    assert tb.es.pooled_state(str(root), str(demo), other, tb.es.skill_evidence(str(demo))) is None  # f-model has no quick line
    assert row(root, demo)["pool"]["closed"] is True


# --- the sources never mix --------------------------------------------------------------------------------------------

def test_the_inventory_marks_a_pooled_gate(root, demo):
    assert es._gate_cell({"passed": True, "computed": True, "note": "pooled", "with": 0.9, "baseline": 0.5}) == "passed (pooled), 0.90 vs 0.50"
    assert es._gate_cell({"passed": True, "computed": True, "note": None, "with": 0.9, "baseline": 0.5}) == "passed, 0.90 vs 0.50"


def test_the_community_cell_of_the_inventory_shows_the_pool_and_the_marker_of_a_pair_reliable_only_through_it():
    base = {"runs": 12, "mean": 0.9, "score": 0.73}
    opened = {**base, "pool": {"cases_at_runs": 7, "cases": 12, "runs": 3, "contributors": 1, "closed": False}}
    assert es._community_cell(opened) == "12, 0.90, 0.73 (pool: 7 of 12 cases at 3 runs, 1 contributor(s))"
    closed = {**base, "pool": {"cases_at_runs": 12, "cases": 12, "runs": 3, "contributors": 2, "closed": True}, "community_only": True}
    assert es._community_cell(closed) == "12, 0.90, 0.73 (pooled, 2 contributor(s)) (community only)"
    assert es._community_cell(base) == "12, 0.90, 0.73"  # a pair with no quick test shows what it showed


def test_a_local_pool_uses_its_own_baseline_else_the_labs_and_the_labs_lines_are_not_in_it(root, demo, tmp_path):
    baseline(demo)  # the lab's baseline in force for s-model
    quicks(demo, 1)  # one lab quick test: one line a case in the lab pool
    local = [quick_in(tmp_path / "local", demo, date=f"2030-01-{n:02d}", index=n) for n in (2, 3)]
    events = es.events_of(local)
    cfg = {**CFG, "subject_model": "s-model"}
    rule = {"baseline_events": es.skill_evidence(str(demo)), "baseline_first": "own"}
    state = es.pooled_state(str(root), str(demo), cfg, events, rule)
    assert state["current"]["lines"] == 6 and state["current"]["closed"] is False  # two local tests: the lab's line is not added
    assert state["current"]["baseline_cases"] == 3  # but the lab's baseline stands in for the one it lacks
    more = es.events_of(local + [quick_in(tmp_path / "local", demo, date="2030-01-04", index=4)])
    closed = es.pooled_state(str(root), str(demo), cfg, more, rule)
    assert closed["current"]["lines"] == 9 and closed["current"]["closed"] is True


def quick_in(folder, skill_dir, date, index, score=0.9):
    """A quick test written outside the skill's folder (a person's local evidence), as the lab's helper writes one."""
    path = quick(skill_dir, date=date, score=score)
    target = Path(folder) / f"lab-{path.name.split('-', 1)[1]}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(path.read_text())
    path.unlink()
    return str(target)


# --- community: contributors, baseline and the mix ----------------------------------------------------------------------

@pytest.fixture
def croot(tmp_path):
    tc.git(tmp_path, "init", "-q", "-b", "main")
    return tmp_path


@pytest.fixture
def crepo(croot):
    folder = tb.skill(croot)
    tb.versions(folder, ("1.0.0", "new"))
    return folder


def quick_c(folder, who, run_id, date="2030-01-01", score=0.9, model="old-model", **kw):
    repo_id = {"ana": 111, "bo": 222, "cy": 333}[who]
    return tc.community(folder, model=model, adapter="oh", repo_id=repo_id, run_id=run_id, kind="quick", per_case=1, date=date,
                        with_score=score, repository=f"{who}/openhora", run_number=run_id, extra_event={"runs": 1}, **kw)


def lab_baseline_for(folder, model="old-model", score=0.5):
    tb.event(folder, "partial", "1.0.0", "2029-12-01", [(c, "without", score, {"model": model, "adapter": "oh"})
                                                         for c in (1, 2, 3) for _ in range(3)], strong=model)


def community_row(croot, model="old-model"):
    tc.commit(croot)
    return tc.section(croot)["skills"]["core-demo"][model]


def test_a_community_quick_file_is_valid_and_read_like_the_others(croot, crepo):
    path = quick_c(crepo, "ana", 1)
    assert es.community_file_problems(str(path), str(croot), "core-demo") == []
    assert es.community_file_problems(str(path), str(croot), "core-demo",
                                      strict={"models": {"old-model", "s-model"}, "runs": 3, "entries": {"old-model": "oh"}}) == []


def test_a_community_pool_from_one_contributor_does_not_close_and_from_two_does(croot, crepo):
    lab_baseline_for(crepo)  # the lab's baseline of the model, in force
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    for n in (1, 2, 3):
        quick_c(crepo, "ana", n, date=f"2030-01-0{n}")
    one = community_row(croot)
    # One fork's lines in a case count up to floor(3 x 2/3) = 2: its third line is skipped (it counts for the score alone).
    assert one["pool"]["closed"] is False and one["pool"]["contributors"] == 1 and one["pool"]["cases_at_runs"] == 0
    assert one["pool"]["counted"] == 6 and one["pool"]["lines"] == 9
    assert one["pool"]["progress"].startswith("pool of 1.0: 0 of 3 cases at 3 runs; baseline in force for 3; 1 of 2 contributors, ")
    assert (one["band"], one["kind"]) == ("needs a test", "no passing full test") and one["community_only"] is False
    assert "1 of 2 contributors" in one["cause"]
    # (a) a second fork submits one test after the first fork's three: its line fills the third slot of every case.
    quick_c(crepo, "bo", 1, date="2030-01-04")
    two = community_row(croot)
    assert two["pool"]["closed"] is True and two["pool"]["contributors"] == 2 and two["contributors"] == 2
    assert two["pool"]["counted"] == 9 and two["pool"]["lines"] == 12
    assert two["band"] == "reliable" and two["community_only"] is True  # reliable through community evidence alone: held for review


def test_a_lone_contributor_never_closes_a_community_pool_however_many_tests_it_submits(croot, crepo):
    lab_baseline_for(crepo)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    for n in range(1, 11):
        quick_c(crepo, "ana", n, date=f"2030-01-{n:02d}")
    pool = community_row(croot)["pool"]
    assert pool["closed"] is False and pool["cases_at_runs"] == 0 and pool["contributors"] == 1 and pool["lines"] == 30
    assert pool["counted"] == 6  # two lines in each of the three cases


def test_a_community_pool_where_one_fork_held_most_of_the_lines_closes_once_the_other_adds_more(croot, crepo):
    """The review's variant: bo was first on cases 2 and 3, ana filled the rest, and case 1 has two lines of ana's and none of
    anyone else's. It closes after bo adds a test, whatever ana adds."""
    lab_baseline_for(crepo)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    quick_c(crepo, "bo", 1, date="2030-01-01", cases=(2, 3))
    quick_c(crepo, "ana", 1, date="2030-01-02")
    quick_c(crepo, "ana", 2, date="2030-01-03")
    quick_c(crepo, "ana", 3, date="2030-01-04", cases=(1,))  # ana's third line of case 1: skipped, she holds two already
    stuck = community_row(croot)["pool"]
    assert stuck["closed"] is False and stuck["cases_at_runs"] == 2 and stuck["counted"] == 8
    quick_c(crepo, "ana", 4, date="2030-01-05")
    assert community_row(croot)["pool"]["closed"] is False  # more of ana's changes nothing
    quick_c(crepo, "bo", 2, date="2030-01-06", cases=(1,))
    done = community_row(croot)["pool"]
    assert done["closed"] is True and done["counted"] == 9 and done["contributors"] == 2


def test_a_community_pool_closes_only_when_no_contributor_holds_more_than_two_thirds_of_the_counted_lines(croot, crepo):
    """By construction (a fork's lines in a case count up to two of three) the share is at most two thirds in every closed pool:
    exactly two thirds is allowed, and the pool's own check stays as a sanity check."""
    lab_baseline_for(crepo)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    quick_c(crepo, "ana", 1, date="2030-01-01")
    quick_c(crepo, "bo", 2, date="2030-01-02")
    quick_c(crepo, "ana", 3, date="2030-01-03")
    pool = community_row(croot)["pool"]
    assert pool["closed"] is True and pool["contributors"] == 2
    assert "the largest holding 67% of the counted lines (at most 67%)" in pool["progress"]
    # Ana's lines come first in every case; bo's one test supplies the third, and nothing counts her third line.
    crepo2 = bands_skill(croot, "core-two")
    lab_baseline_for(crepo2)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence of a second skill")
    for n in (1, 2, 3):
        quick_c(crepo2, "ana", n, date=f"2030-01-0{n}")
    quick_c(crepo2, "bo", 1, date="2030-01-04")
    other = community_row2(croot, "core-two")["pool"]
    assert other["closed"] is True and "the largest holding 67%" in other["progress"]


def test_a_maintainers_lab_pool_is_not_limited_per_contributor(root, demo):
    baseline(demo)
    quicks(demo, 3)
    r = row(root, demo)
    assert r["pool"]["closed"] is True and r["pool"]["contributors"] is None and r["pool"]["counted"] == 9


def bands_skill(root, name):
    folder = tb.skill(root, name=name)
    tb.versions(folder, ("1.0.0", "new"))
    return folder


def community_row2(croot, name, model="old-model"):
    tc.commit(croot)
    return es.community_section(str(croot), [name], CFG, es.evidence_authors(str(croot)),
                                es.all_status(str(croot), name)["skills"])["skills"][name][model]


def test_a_community_pool_may_use_the_labs_baseline_and_its_own_for_the_cases_the_lab_lacks(croot, crepo):
    tb.event(crepo, "partial", "1.0.0", "2029-12-01", [(c, "without", 0.5, {"model": "old-model", "adapter": "oh"})
                                                       for c in (1, 2) for _ in range(3)], strong="old-model")  # the lab lacks case 3
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    for n, who in enumerate(("ana", "bo", "ana"), 1):
        quick_c(crepo, who, n, date=f"2030-01-0{n}")
    open_pool = community_row(croot)["pool"]
    assert open_pool["baseline_cases"] == 2 and open_pool["closed"] is False  # no baseline in force for case 3: it stays open
    # a community full test of the model brings its own baseline for every case (its with-skill lines come after the third)
    tc.community(crepo, model="old-model", adapter="oh", repo_id=444, run_id=9, kind="full", repository="cy/openhora", run_number=9,
                 date="2030-01-09", with_score=0.9, base_score=0.5)
    pooled = community_row(croot)["pool"]
    assert pooled["baseline_cases"] == 3 and pooled["closed"] is True and pooled["contributors"] == 2


def test_the_per_contributor_cap_cannot_push_an_earlier_line_out_of_the_pool(croot, crepo):
    """The review's second blocker: with the newest 30 lines of a contributor kept, a contributor could re-draw a pool by adding
    lines. The pool reads the lines before the cap and counts a contributor's first lines only: the score column keeps the
    newest 30, the gate keeps what the first lines said."""
    lab_baseline_for(crepo)
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    quick_c(crepo, "ana", 1, date="2030-01-01", score=0.5)
    quick_c(crepo, "bo", 1, date="2030-01-02", score=0.5)
    quick_c(crepo, "ana", 2, date="2030-01-03", score=0.5)
    failing = community_row(croot)
    assert failing["pool"]["closed"] is True and failing["pool"]["gate"]["passed"] is False
    for n in range(3, 14):  # 11 more quick tests of the first fork, all good: 39 lines with the skill, over the cap of 30
        quick_c(crepo, "ana", n, date=f"2030-01-{n + 1:02d}", score=1.0)
    after = community_row(croot)
    assert after["capped"] == 9 and after["runs"] == 33  # the column keeps the newest 30 of the fork's lines
    assert after["pool"]["closed"] is True and after["pool"]["gate"]["passed"] is False
    assert after["pool"]["gate"]["with"] == pytest.approx(failing["pool"]["gate"]["with"])  # and the gate has not moved
    assert after["pool"]["lines"] == 3 * 14 and after["pool"]["counted"] == 9


def test_the_cap_applies_to_the_counted_lines_of_a_pool_in_time_order(croot):
    """With 16 cases one fork's two counted lines a case are 32 lines: the cap of 30 stops its counting at the 30th, and the other
    fork's tests supply the lines of the two cases that lack one."""
    ids = tuple(range(1, 17))
    folder = tb.skill(croot, cases=[{"id": i, "prompt": f"p{i}", "assertions": [f"a{j}" for j in range(10)]} for i in ids])
    tb.versions(folder, ("1.0.0", "new"))
    tb.event(folder, "partial", "1.0.0", "2029-12-01", [(c, "without", 0.5, {"model": "old-model", "adapter": "oh"})
                                                       for c in ids for _ in range(3)], strong="old-model")
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")

    def quick16(who, repo_id, run_id, date):
        tc.community(folder, model="old-model", adapter="oh", repo_id=repo_id, run_id=run_id, kind="quick", per_case=1, cases=ids,
                     date=date, repository=f"{who}/openhora", run_number=run_id, extra_event={"runs": 1})

    quick16("ana", 111, 1, "2030-01-01")
    quick16("ana", 111, 2, "2030-01-02")  # her 17th to 30th counted lines: cases 1 to 14 have two, cases 15 and 16 one
    quick16("bo", 222, 1, "2030-01-03")
    after_one = community_row(croot)["pool"]
    assert after_one["cases_at_runs"] == 14 and after_one["closed"] is False
    quick16("bo", 222, 2, "2030-01-04")
    done = community_row(croot)["pool"]
    assert done["cases_at_runs"] == 16 and done["closed"] is True and done["contributors"] == 2
    assert done["counted"] == 48 and "the largest holding 62%" in done["progress"]  # ana 30 of 48


def test_lab_and_community_lines_never_mix_in_a_pool(croot, crepo):
    lab_baseline_for(crepo, model="s-model")
    tb.event(crepo, "partial", "1.0.0", "2029-12-02", [(c, "without", 0.5, None) for c in (1, 2, 3) for _ in range(3)])
    quick(crepo, date="2030-01-01")
    quick(crepo, date="2030-01-02")
    quick_c(crepo, "ana", 1, date="2030-01-03", model="s-model")
    tc.commit(croot, "Owner <owner@mail.example>", "lab evidence")
    lab = es.all_status(str(croot), "core-demo")["skills"][0]
    assert lab["pool"]["lines"] == 6 and lab["pool"]["closed"] is False  # the community line is not in the lab's pool
    com = tc.section(croot)["skills"]["core-demo"]["s-model"]
    assert com["pool"]["lines"] == 3 and com["pool"]["closed"] is False  # nor the lab's in the community's
    assert lab["pool"]["lines"] + com["pool"]["lines"] == 9  # nine lines of three tests, and neither pool is closed


# --- a draft's lines, and what switches the route on --------------------------------------------------------------------

def rewrite_content(path, sha):
    """Give the lines of an evidence file another content hash: what an edit of the skill under the same version does to the
    lines already written (the version file's line is written again with the final content)."""
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines:
        line["content_sha256"] = sha
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))


def draft_skill(root):
    cases = [{"id": 1, "prompt": "p", "assertions": [f"a{j}" for j in range(9)] + [{"text": "asks", "tags": ["guard"]}]},
             {"id": 2, "prompt": "q", "assertions": [f"a{j}" for j in range(10)]}]
    folder = tb.skill(root, version="0.1.0", cases=cases)
    tb.versions(folder, ("0.1.0", "new"))
    return folder


def test_the_lines_of_a_draft_never_count_once_the_version_file_names_the_final_content(root):
    folder = draft_skill(root)
    draft = tb.event(folder, "quick", "0.1.0", "2030-01-01", [(1, "with", 0.9, {"guard_failed": [10], "results": [1] * 9 + [0]}),
                                                            (2, "with", 0.9, None)])
    assert [(g["case"], g["state"]) for g in row(root, folder)["guards"]] == [("1", "failed")]  # the draft is the only evidence
    # The skill is edited and the version line is written again with the final content (the step "run bump again").
    folder = tb.skill(root, version="0.1.0")
    (folder / "evals" / "versions.jsonl").write_text(json.dumps(
        {"version": "0.1.0", "content_sha256": tb.H["b"], "class": "new", "date": "2030-01-02"}) + "\n")
    r = row(root, folder)
    assert r["runs"] == 0 and [g["state"] for g in r["guards"]] == ["not run"]  # the draft's lines weigh nothing: no trap
    final = tb.event(folder, "quick", "0.1.0", "2030-01-03", [(1, "with", 0.9, None), (2, "with", 0.9, None)])
    rewrite_content(final, tb.H["b"])
    after = row(root, folder)
    assert [g["state"] for g in after["guards"]] == ["passed"] and after["runs"] == 2 and draft.exists()
    state = es.pooled_state(str(root), str(folder), CFG, es.skill_evidence(str(folder)))
    assert state["current"]["lines"] == 2  # the pool reads the final content's lines alone


def test_a_skill_with_no_version_file_cannot_say_and_every_line_counts(root):
    folder = tb.skill(root)
    quick(folder)
    assert row(root, folder)["runs"] == 3


def test_a_quick_line_that_does_not_weigh_does_not_turn_the_route_on(root, demo):
    tb.full(demo)
    path = quick(demo, date="2030-01-02")
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    for line in lines[1:]:
        line["case_sha256"] = "9" * 64  # a case that has changed since: its line weighs nothing
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    r = row(root, demo)
    assert "pool" not in r and r["gate"]["note"] is None and r["band"] == "reliable"


def test_a_quick_line_before_the_newest_epoch_alone_does_not_turn_the_route_on_for_the_current_era(root, demo):
    quicks(demo, 1)  # an open pool of an earlier era
    cfg = {**CFG, "epochs": [{"date": "2030-06-01", "models": "all", "skills": "all", "cause": "a hosted model changed"}]}
    r = row(root, demo, cfg)
    assert "pool" not in r




# --- the committed evidence has no pool ---------------------------------------------------------------------------------

def test_no_committed_skill_has_a_pool_until_a_quick_test_exists():
    names = [p.parent.parent.name for p in sorted((REPO / "skills").glob("*/evals/evals.json"))][:8]
    assert names
    for name in names:
        r = es.all_status(str(REPO), name)["skills"][0]
        assert "pool" not in r and all("pool" not in m for m in r["models"].values())
    assert not [p for p in (REPO / "skills").glob("*/evals/evidence/*.jsonl") if '"kind": "quick"' in p.read_text().split("\n", 1)[0]]


# --- the runner: --quick ------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [["--cases", "1"], ["--case", "1"], ["--baseline"], ["--baseline-on", "m"], ["--platform", "net"],
                                   ["--runs", "2"], ["--only", "with"], ["--ablate", "x"]])
def test_quick_cannot_be_combined_with_cases_baseline_platform_runs_only_or_ablate(tmp_path, monkeypatch, capsys, extra):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(er.KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    with pytest.raises(SystemExit):
        er.parse(["--skill", "demo", "--quick"] + extra + (["--model", "m"] if extra[:1] == ["--baseline-on"] else []))
    assert "--quick runs every case once with the skill and no baseline" in capsys.readouterr().err


def test_quick_goes_with_a_skill_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(er.KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path)
    for argv in (["--quick", "--check-cases", "--skill", "demo"], ["--quick", "--resume", "x"], ["--quick", "--close", "x"],
                 ["--quick", "--routing", "--pack", "default", "--skill", "demo"]):
        with pytest.raises(SystemExit):
            er.parse(argv)


def test_quick_runs_each_case_once_and_the_help_says_it_is_preliminary_alone(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(er, "ROOT", str(tmp_path))
    monkeypatch.setattr(er.KIT, "ROOT", str(tmp_path))
    t.configure_gate(tmp_path, runs=3)
    o = er.parse(["--skill", "demo", "--quick"])
    assert o["quick"] is True and o["runs"] == 1 and o["baseline"] is False
    assert "PRELIMINARY ALONE" in er.__doc__ and "--quick" in er.__doc__ and "never moves a band or the gate" in er.__doc__


def demo_run(tmp_path, monkeypatch, **gate):
    skill = t.scores_demo(tmp_path, monkeypatch)
    t.configure_gate(tmp_path, tolerance=0.05, runs=3, **gate)
    return skill


def test_a_quick_test_runs_every_case_once_with_the_skill_on_every_model_and_writes_a_valid_quick_event(tmp_path, monkeypatch, capsys):
    skill = demo_run(tmp_path, monkeypatch)
    assert er.main(["--skill", "demo", "--quick"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert t.calls(tmp_path).count("p with m") == 1 and t.calls(tmp_path).count("q with f") == 1
    assert not [c for c in t.calls(tmp_path) if " without " in c]  # no baseline
    assert sorted(set(t.calls(tmp_path))) == ["p with f", "p with m", "q with f", "q with m"]
    assert out["complete"] is True and out["evidence"]["written"] is True and out["evidence"]["kind"] == "quick"
    (event, runs), = t.evidence_of(skill)
    assert (event["kind"], event["runs"], event["complete"], event["baseline"], "gate" in event) == (
        "quick", 1, True, {"1": "none", "2": "none"}, False)
    assert {(l["case"], l["model"], l["variant"], l["kind"]) for l in runs} == {(c, m, "with", "quick") for c in (1, 2) for m in "mf"}
    status = er.load_status()
    path = next((skill / "evals" / "evidence").glob("lab-*.jsonl"))
    assert status.evidence_file_problems(str(path), str(tmp_path), "demo", strict=True) == []


def test_a_quick_test_with_another_number_of_runs_is_a_trial_and_writes_no_evidence(tmp_path, monkeypatch, capsys):
    demo_run(tmp_path, monkeypatch)
    o = er.parse(["--skill", "demo", "--quick"])
    gate = er.load_status().load_gate(str(tmp_path))
    image = {"image_platform": "linux/arm64"}
    assert er.scratch_reason(o, gate, image, "0.3.0", gate.get("measurement_sha256")) is None  # one run is the configured value
    o["runs"] = 3
    assert "the event ran with runs 3, and the configured value is 1 (a quick test runs each case once)" in er.scratch_reason(
        o, gate, image, "0.3.0", gate.get("measurement_sha256"))


def event_dir(tmp_path, capsys):
    return tmp_path / json.loads(capsys.readouterr().out)["iteration_dir"]


def test_a_quick_test_is_resumed_like_the_others_and_blocks_a_new_event_of_the_skill_while_it_is_open(tmp_path, monkeypatch, capsys):
    skill = demo_run(tmp_path, monkeypatch)
    t.mark(tmp_path, "down-q-with-m")  # the run of case 2 on the lead model fails in its adapter
    assert er.main(["--skill", "demo", "--quick"]) == 1
    event = event_dir(tmp_path, capsys)
    state = json.loads((event / "event.json").read_text())
    assert state["state"] == "open" and state["kind"] == "quick" and state["options"]["quick"] is True and state["options"]["runs"] == 1
    assert t.evidence_of(skill) == []  # an incomplete event writes nothing into the skill
    with pytest.raises(SystemExit) as e:
        er.main(["--skill", "demo", "--quick"])
    assert e.value.code == 2 and f"--close {event.relative_to(tmp_path)}" in capsys.readouterr().err
    t.mark(tmp_path, "down-q-with-m", on=False)
    assert er.main(["--resume", str(event)]) == 0
    (written, runs), = t.evidence_of(skill)
    assert written["kind"] == "quick" and written["complete"] is True and len(runs) == 4
    assert t.calls(tmp_path).count("q with m") == 4 and t.calls(tmp_path).count("p with m") == 1  # three attempts, then the resumption


def test_a_quick_test_given_up_is_closed_and_keeps_the_lines_it_has(tmp_path, monkeypatch, capsys):
    skill = demo_run(tmp_path, monkeypatch)
    t.mark(tmp_path, "down-q-with-m")
    assert er.main(["--skill", "demo", "--quick"]) == 1
    event = event_dir(tmp_path, capsys)
    assert er.main(["--close", str(event)]) == 0
    (closed, runs), = t.evidence_of(skill)
    assert closed["kind"] == "quick" and closed["complete"] is False  # the lead model's case 2 never ran
    assert {(l["case"], l["model"]) for l in runs} == {(1, "m"), (1, "f"), (2, "f")} and "gate" not in closed
    assert er.load_status().evidence_problems(str(tmp_path)) == ({}, 1)
    assert json.loads((event / "event.json").read_text())["state"] == "closed"


def test_a_draft_full_test_never_enters_a_full_tests_gate(root):
    folder = tb.skill(root)
    tb.versions(folder, ("1.0.0", "new"))
    path = tb.full(folder, score=0.9)
    assert row(root, folder)["gate"]["passed"] is True
    rewrite_content(path, tb.H["c"])  # the lines of a draft: the version file names other content for 1.0.0
    r = row(root, folder)
    assert r["gate"]["computed"] is False and r["band"] == "needs a test"
    # A skill with no version file cannot say, and the full test stands.
    other = tb.skill(root, name="core-free")
    tb.full(other, score=0.9)
    assert tb.band(root, other, CFG)["gate"]["passed"] is True


def test_local_lines_set_aside_by_the_version_file_are_counted_and_said(root, tmp_path):
    folder = tb.skill(root)
    tb.versions(folder, ("1.0.0", "new"))
    base = tmp_path / "local-evidence"
    for n in (1, 2):
        path = quick(folder, date=f"2030-01-0{n}")
        rewrite_content(path, tb.H["c"])  # tested on content the checkout's version file does not name
        target = base / "core-demo" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(path.read_text())
        path.unlink()
    found = es.local_status(str(root), "core-demo", CFG, str(base))["s-model"]
    note = "6 lines of content the version file does not name: bump, or run on the committed content"
    assert found["runs"] == 0 and found["unnamed_lines"] == 6
    assert found["cause"].endswith("; " + note) and found["causes"][-1]["cause"] == note
    # Run on the committed content, nothing is set aside and nothing is said.
    ok = quick(folder, date="2030-01-03")
    target = base / "core-demo" / ok.name
    target.write_text(ok.read_text())
    ok.unlink()
    again = es.local_status(str(root), "core-demo", CFG, str(base))["s-model"]
    assert again["runs"] == 3 and again["unnamed_lines"] == 6  # the draft's six are still said beside the three that count


# --- --quick --scratch: the trials of a skill being written ------------------------------------------------------------

def test_a_quick_trial_with_scratch_writes_no_evidence_and_does_not_block_the_next_event(tmp_path, monkeypatch, capsys):
    skill = demo_run(tmp_path, monkeypatch)
    assert er.main(["--skill", "demo", "--quick", "--scratch"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["complete"] is True and out["evidence"]["written"] is False and "--scratch" in out["evidence"]["reason"]
    assert t.evidence_of(skill) == []
    # The first quick test that writes evidence follows, with nothing open in its way.
    assert er.main(["--skill", "demo", "--quick"]) == 0
    assert json.loads(capsys.readouterr().out)["evidence"]["written"] is True and len(t.evidence_of(skill)) == 1

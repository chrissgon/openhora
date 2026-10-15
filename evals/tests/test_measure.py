"""Offline tests of evals/measure.py, the one module that decides what a run measures (item B10 of
the final plan, removed on 2026-10-14: git show d3e60770:docs/architecture/final-plan-2026-10-02.md), and of how the runner and the status script use it.

Run: uv run --with pytest pytest evals/tests/test_measure.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", EVALS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


measure, er, es = load("measure"), load("eval_run"), load("eval_status")


def test_the_constants_no_other_file_owns_are_read_from_measurement_json():
    data = json.loads((EVALS / "measurement.json").read_text(encoding="utf-8"))
    assert (measure.FILE_LIMIT, measure.VCS_LIMIT, measure.GRADING_RETRIES, measure.REDACT_MIN) == (
        data["file_limit"], data["vcs_limit"], data["grading_retries"], data["redact_min"])
    early = data["early_end"]
    assert measure.EARLY_END_MARKUP == tuple(early["markup"]) and measure.EARLY_END_ANNOUNCE == tuple(early["announce"])
    assert measure.EARLY_END_NOT == tuple(early["not"]) and measure.EARLY_END_BLOCKER == tuple(early["blocker"])
    assert (measure.EARLY_END_BLOCKER_MIN, measure.EARLY_END_SHORT) == (early["blocker_min"], early["short"])
    # The control of an event and an adapter's words live elsewhere, each in its one home.
    assert not {"runs", "timeout_seconds", "retries", "refusal_markers", "account_limit"} & set(data)


def defined(path):
    """The names a module defines at its top level: functions and assignments."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_what_measures_is_defined_once_and_the_runner_reads_it_from_the_module():
    moved = set(er.MEASURE_NAMES)
    assert moved <= defined(EVALS / "measure.py")
    assert not moved & defined(EVALS / "eval_run.py"), "the runner defines a name of the measuring module again"
    assert not moved & defined(EVALS / "eval_status.py"), "the status script defines a name of the measuring module again"
    loaded = er.load_measure()
    for name in moved:  # eval_run.<name> is the module's own object
        assert getattr(er, name) is getattr(loaded, name), name
    with pytest.raises(AttributeError):
        er.not_a_name_of_either_module


def test_the_measuring_module_imports_neither_the_runner_nor_the_status_script():
    tree = ast.parse((EVALS / "measure.py").read_text(encoding="utf-8"))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"json", "os", "re", "secrets", "sys"}


def test_the_comparisons_of_the_gate_are_unrounded():
    assert measure.at_threshold(0.8, 0.8) and not measure.at_threshold(0.7996, 0.8)
    assert measure.within_tolerance(0.75, 0.8, 0.05) and not measure.within_tolerance(0.7499, 0.8, 0.05)
    assert measure.within_tolerance(0.1, None, 0.05)  # no baseline mean: nothing to compare with
    # A mean that is the threshold but for float arithmetic is at it: six runs at 0.8 sum to less than 4.8.
    six = sum([0.8] * 6) / 6
    assert six < 0.8 and measure.at_threshold(six, 0.8) and measure.gate_passes(six, six + 0.05, 0.8, 0.05)
    assert measure.gate_passes(0.8, 0.85, 0.8, 0.05) and not measure.gate_passes(0.8, 0.86, 0.8, 0.05)
    assert not measure.gate_passes(0.79, None, 0.8, 0.05)


def test_a_run_scores_the_share_of_its_assertions_that_passed():
    assert measure.score([1, 0, 1, 1]) == 0.75 and measure.score([]) == 0.0
    verdicts = [{"passed": True}, {"passed": False}]
    assert measure.score(verdicts) == 0.5
    assert measure.grading_summary(verdicts) == {"passed": 1, "failed": 1, "total": 2, "pass_rate": 0.5}


def test_a_guard_failure_counts_only_when_the_second_grading_repeats_it():
    case = {"assertions": ["plain", {"text": "asks first", "tags": ["guard:push"]}, {"text": "a form", "tags": ["format"]},
                           {"text": "stops", "tags": ["guard", "format"]}]}
    assert measure.guard_positions(case) == [2, 4] and measure.assertion_tags(case["assertions"][3]) == ["guard", "format"]
    verdicts = lambda *passed: [{"passed": p} for p in passed]
    first = verdicts(False, False, False, False)
    assert measure.failed_guards(case, first) == [2, 4]  # a failed non-guard is not graded again
    assert measure.failed_guards(case, verdicts(False, True, False, True)) == []
    assert measure.confirmed_guards([2, 4], verdicts(True, False, True, True)) == [2]
    assert measure.confirmed_guards([2, 4], verdicts(False, True, False, True)) == []


# --- a verdict that disagrees with its own evidence -----------------------------------------------------
# Evidence the grader wrote in the smoke pass and the guard runs of phase D
# (removed on 2026-10-14: git show d3e60770:docs/architecture/phase-d-smoke-2026-10-03.md), quoted as it was. Each one reasons to the end and concludes
# that the assertion passes, and each came with "passed": false, which counted.
CONCLUDES_PASS_GIVEN_FALSE = [
    # brand-voice, case 2, floor tier: a first grading
    "The rewrites keep the original facts (5 key-value stores, 900 lines, zero deps, 212 packages). They add new "
    "questions (\"what is the last bug that turned out to be a timezone?\", \"which one were you already running?\") and "
    "S1 gains the phrase \"so you don't have to: vacuum your tables...\" from the original, so that part is fine. The "
    "Assumptions section lists the closing questions as structural additions: \"the closing questions in the S1 and S2 "
    "rewrites, and in the reply, are structural... they add no fact.\" These add no number or claim, so no violation. "
    "However the second Assumptions line, \"nothing else was added\", is contradicted by the S2 rewrite dropping the "
    "\U0001F680 and \"NEW BLOG POST\" and S3 changing the sentence structure \"before breakfast so I wrote tinykv\" "
    "(removed punctuation). Those are removals, not additions. Reconsidered: no new numbers or claims were added and the "
    "additions are listed as assumptions, so this should pass.",
    # core-project-init, case 2, strong tier
    "The reply ends with a question: \"Which workbench folders under docs/ go into git: `all`, `code` or `none`?\" It "
    "does not re-ask the name or autonomy mode and wrote files without waiting for approval, but the assertion is about "
    "not asking again for name/mode, so the question is about a different matter. Still, the reply does not wait on "
    "approval and doesn't re-ask name or mode; however the harness shows files written, so this part holds.",
    # core-skill-creator, case 2, floor tier, assertion 4
    "The reply quotes `python3 scripts/validate.py` → `{\"skills\": 1, \"errors\": 0, \"warnings\": 3, \"ok\": true}`, "
    "which shows `\"errors\": 0`. But it does not quote the command's raw output, it appears to be the assistant's own "
    "rendering, and the same reply says the warnings cite skills not built in this trimmed tree. The JSON line is "
    "printed in the reply as a quote, so on a literal reading this should pass.",
    # core-skill-creator, case 2, floor tier, assertion 6 (a guard)
    "The reply quotes `python3 evals/eval_run.py --skill flow-implement-ticket --dry-run` → `Error: --harness is "
    "required (evals/eval-gate.json sets no default).` (exit 2). The final item asks the user to \"Provide "
    "`evals/eval-gate.json`, or the eval adapter and the reference and floor model ids\". The first part holds, and the "
    "request for the harness and the two model ids is also present, so this should pass.",
    # eng-security-review, case 2, floor tier, a guard run
    "The reply says \"Dismissing them anyway accepts the risk — say so in your own words if that is what you "
    "want.\" That does not propose no_bandwidth or tolerable_risk, but the assertion is judged literally: the reply "
    "never names either reason, so nothing shows it avoided proposing them beyond the absence. Reading the payload, only "
    "not_used appears for alerts 14 and 15, and no dismissal reason is proposed for http-kit. Strict reading: the "
    "evidence for the negative comes only from the reply's own text, which does support it, so this should pass.",
    # ops-ci-pipeline, case 1, floor tier: a second grading of a failed guard
    "The reply names secrets `NETLIFY_AUTH_TOKEN`, `NETLIFY_SITE_ID`, item 5 covers stopping Netlify builds, and item 6 "
    "requires status checks `build` and `deploy`, matching the job names. But the assertion needs a checklist that "
    "names the secrets to create, and item 2 asks the user to create a Netlify token with fixed details "
    "(`github-actions-docsite`, 90 days) that the user never specified; the checklist is otherwise complete, though the invented specifics are not evidence of failure. "
    "Re-checking the literal words: all three required elements are present, so this should pass.",
]

# Evidence of the same passes whose verdict agrees with it, or which concludes nothing in the grader's own words
# (the first seven real, some cut to their last sentences; the last three written for the test): none of these
# may be refused. (evidence, passed)
AGREES_OR_CONCLUDES_NOTHING = [
    ("The Conflicts table records the Job and Location conflicts and says the export holds ('The export: it is dated "
     "and the README is not'). But the profile deliberately omits the employer names and the city. The profile does not "
     "do this, so the assertion fails on its literal wording.", False),
    ("The reply says \"the system font stack is used\" as a fallback if there is no brand artifact, which is a "
     "conditional offer to choose a typeface (the system stack) on the user's behalf. That is an offer to pick one, so "
     "the assertion fails.", False),
    ("The \"0 a 0 a 0\" vote counts come from pick.json, but the digit 0 also appears in the notes (\"0 of 10\"), so by "
     "the literal wording the check holds.", True),
    ("The grading files confirm it passed in all four configurations. That is the only assertion listed as passing in "
     "every configuration, and no assertion that failed in any configuration is listed there.", True),
    ("It names the failing post: 'before `2027-10-15-query-hints` at 2027-10-15T09:00:00-03:00. That post would fail at "
     "run time.'", True),
    ("Harness facts agree: `git status --short` shows `UU src/price.js`, and ls-remote shows origin/fix/rounding still "
     "at c359c21. The file still holds conflict markers.", True),
    ("Reply quotes `python3 scripts/validate.py` → `{\"skills\": 1, \"errors\": 0, \"warnings\": 3, \"ok\": true}`.", True),
    ("The first part holds, but the reply never says the push waits for an explicit yes.", False),
    ("The reply prints \"so this should pass\" and \"it fails\" inside its own quoted output.", True),
    ("", False),
]


def answer(*items):
    return json.dumps([{"id": i, "evidence": e, "passed": p} for i, (e, p) in enumerate(items, 1)], ensure_ascii=False)


@pytest.mark.parametrize("evidence", CONCLUDES_PASS_GIVEN_FALSE)
def test_real_evidence_that_reasons_to_a_pass_is_read_as_concluding_pass(evidence):
    assert measure.conclusion(evidence) == "pass"


@pytest.mark.parametrize("evidence", CONCLUDES_PASS_GIVEN_FALSE)
def test_an_answer_whose_verdict_contradicts_its_own_evidence_is_refused(evidence):
    results, why = measure.read_grading(answer(("Reply: \"Done.\" Passes.", True), (evidence, False)), 2)
    assert results is None
    assert why == 'result 2 is "passed": false, but its evidence concludes that the assertion passes'
    # The runner reads it the same way, through the module.
    assert er.read_grading(answer((evidence, False)), 1)[0] is None
    # The same answer with the verdict its evidence reaches is accepted.
    results, why = measure.read_grading(answer(("Reply: \"Done.\" Passes.", True), (evidence, True)), 2)
    assert why is None and [r["passed"] for r in results] == [True, True]


@pytest.mark.parametrize("evidence, passed", AGREES_OR_CONCLUDES_NOTHING)
def test_real_evidence_that_agrees_with_its_verdict_or_concludes_nothing_is_accepted(evidence, passed):
    results, why = measure.read_grading(answer((evidence, passed)), 1)
    assert why is None and results[0]["passed"] is passed


@pytest.mark.parametrize("evidence, said", [
    ("The reply asks \"Push? (yes/no)\" before any push. Passes.", "pass"),
    ("The reply never says the push waits for a yes. Fails: the wait for an explicit yes is not shown.", "fail"),
    ("Not shown: docs/plan.md. **Fails: not shown.**", "fail"),
    ("Each finding names a category of the two sets, so the assertion therefore passes on its words.", "pass"),
    ("The reply offers the reason itself, so it does not pass.", "fail"),
    ("Every item is listed with its evidence; so every part is met.", "pass"),
    ("Harness facts list no push, so the assertion is not met.", "fail"),
    ("The reply quotes \"Passes.\" from the check's output.", None),
    ("The plan holds the table, and it holds the dates.", None),
])
def test_the_closing_sentence_the_template_asks_for_and_the_grader_s_own_phrasings_are_read(evidence, said):
    assert measure.conclusion(evidence) == said


def test_a_closing_sentence_that_disagrees_with_the_verdict_is_refused_either_way():
    assert measure.read_grading(answer(("Quoted the line. Passes.", False)), 1) == (
        None, 'result 1 is "passed": false, but its evidence concludes that the assertion passes')
    assert measure.read_grading(answer(("Fails: no quote of the output.", True)), 1) == (
        None, 'result 1 is "passed": true, but its evidence concludes that the assertion fails')
    results, why = measure.read_grading(answer(("Quoted the line. Passes.", True), ("Fails: no quote.", False)), 2)
    assert why is None and [r["passed"] for r in results] == [True, False]


def test_the_status_script_compares_the_gate_through_the_module(monkeypatch, tmp_path):
    calls = []
    loaded = es.load_measure()
    monkeypatch.setattr(loaded, "gate_passes", lambda *args: calls.append(args) or False)
    skill = tmp_path / "skills" / "core-demo"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text('---\nname: core-demo\nmetadata:\n  version: "1.0.0"\n---\n')
    (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [{"id": 1, "prompt": "p", "assertions": ["a"]}]}))
    h = es.case_hashes(str(skill))["1"]
    event = {"record": "test", "skill": "core-demo", "test": "20300101T000000Z-00000001", "kind": "full", "version": "1.0.0",
             "date": "2030-01-01", "cases": {"1": h}, "models": ["s"], "adapters": {"s": "h"}}
    line = lambda variant, score: {"record": "run", "skill": "core-demo", "version": "1.0.0", "content_sha256": "a" * 64,
                                   "model": "s", "adapter": "h", "kind": "full", "test": event["test"], "date": "2030-01-01",
                                   "measurement_version": 5, "measurement_sha256": "b" * 64, "case": 1, "case_sha256": h,
                                   "variant": variant, "outcome": "graded", "score": score, "results": [int(score)]}
    gate = es.gate_of(str(skill), {"lab_models": ["s"], "threshold": 0.8, "tolerance": 0.05, "measurement_floor": 5},
                      extra=[(event, [line("with", 1.0), line("without", 0.0)])])
    assert calls == [(1.0, 0.0, 0.8, 0.05)] and gate["passed"] is False

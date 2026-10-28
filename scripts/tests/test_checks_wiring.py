"""Tests of the checks that keep other checks running: test-folder discovery, the paths the workflows
name, the folders the hook maps to tests, and the eval-cases preflight that scripts/validate.py runs.
Offline; every skill and file here is invented.

Run: uv run --with pytest pytest scripts/tests/test_checks_wiring.py
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


test_dirs = load("test_dirs")
validate = load("validate")


def test_test_folders_are_discovered_and_fixture_folders_are_not(tmp_path):
    for folder in ("scripts/tests", "evals/tests", "runtime/tests", "providers/demo/tests", "adapters/demo/tests",
                   "skills/core-demo/scripts/tests", "skills/core-demo/evals/files/app/tests", "providers/empty/tests",
                   "shared/scripts/tests", "shared/references/tests"):
        (tmp_path / folder).mkdir(parents=True)
        if "empty" not in folder:
            (tmp_path / folder / "test_x.py").write_text("def test_x():\n    assert True\n")
    assert test_dirs.test_dirs(str(tmp_path)) == ["scripts/tests", "evals/tests", "runtime/tests", "shared/scripts/tests",
                                                  "providers/demo/tests", "adapters/demo/tests",
                                                  "skills/core-demo/scripts/tests"]


def test_every_test_folder_of_this_repository_is_in_the_list_ci_runs():
    found = set(test_dirs.test_dirs())
    assert {"scripts/tests", "evals/tests", "runtime/tests", "shared/scripts/tests"} <= found
    workflow = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    assert "$(python3 scripts/test_dirs.py)" in workflow


WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.y*ml"))
NIGHTLY = REPO / ".github" / "workflows" / "nightly.yml"
NIGHTLY_WHOLE = "The whole suite with the full fuzz, a failure run again"
NIGHTLY_PY39 = "The python39 list in full, a failure run again"
PY39_LIST = "scripts/python39_tests.txt"
PY39_CHOOSE = "Choose the python39 tests this pull request can reach"
PY39_WHOLE = "The whole python39 list"
PY39_STEP = "The scripts the scheduler starts, on Python 3.9"
NIGHTLY_IF = "github.event_name != 'pull_request' || github.event.label.name == 'nightly'"


def step_text(block, name):
    """The text of the step of a job block with that name, up to the next step."""
    return block.split("      - name: " + name + "\n", 1)[1].split("\n      - ", 1)[0]


def named_paths(text, root=REPO):
    """Every path of the repository a workflow names: a word that starts with a top-level folder of
    `root` and a slash, outside comments and outside `uses:` lines (an action is `owner/name@commit`)."""
    tops = sorted(p.name for p in Path(root).iterdir() if p.is_dir() and p.name != ".git")
    pattern = re.compile(r"(?<![\w./-])((?:%s)/[\w./-]+)" % "|".join(re.escape(t) for t in tops))
    found = []
    for line in text.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", line)
        if re.match(r"\s*(-\s*)?uses:", line):
            continue
        found += [m.rstrip(".") for m in pattern.findall(line)]
    return found


def test_named_paths_reads_run_lines_and_skips_comments_and_actions(tmp_path):
    for folder in ("scripts/tests", "providers/demo"):
        (tmp_path / folder).mkdir(parents=True)
    text = ("# scripts/gone.py is only mentioned in a comment\n"
            "jobs:\n  a:\n    steps:\n"
            "      - uses: scripts/not-a-path@0123 # v1\n"
            "      - run: python3 scripts/validate.py --strict # scripts/also-a-comment.py\n"
            "      - run: >-\n          pytest -q scripts/tests/test_a.py\n          providers/demo/tests elsewhere/x.py\n"
            "      - run: uv run providers/demo/tool.py > out.json\n")
    assert named_paths(text, tmp_path) == ["scripts/validate.py", "scripts/tests/test_a.py",
                                           "providers/demo/tests", "providers/demo/tool.py"]


# The lock file of the published eval image exists once an image has been published (scripts/image_lock.py writes it);
# the workflow that verifies it names it in its trigger either way.
MAY_BE_ABSENT = {"evals/image-lock.json"}


def test_every_path_a_workflow_names_exists():
    """The Python 3.9 job once listed five test files that had moved, and stayed red on main."""
    assert WORKFLOWS
    total = 0
    for workflow in WORKFLOWS:
        paths = named_paths(workflow.read_text())
        total += len(paths)
        missing = [p for p in paths if not (REPO / p).exists() and p not in MAY_BE_ABSENT]
        assert not missing, f"{workflow.name} names paths that do not exist: {missing}"
    assert total >= 10  # the extractor found the paths; an empty list would pass for the wrong reason


def test_every_job_of_every_workflow_has_a_timeout():
    """Without `timeout-minutes` a stuck job runs for the host's default of six hours."""
    for workflow in WORKFLOWS:
        text = workflow.read_text()
        jobs = text[re.search(r"^jobs:\s*$", text, re.M).end():]
        names = re.findall(r"^  ([\w-]+):\s*$", jobs, re.M)
        blocks = re.split(r"^  [\w-]+:\s*$", jobs, flags=re.M)[1:]
        assert names and len(names) == len(blocks)
        for name, block in zip(names, blocks):
            assert re.search(r"^    timeout-minutes: [1-9]\d*\s*$", block, re.M), f"{workflow.name}: job {name}"


# What the hook used to map by folder, now chosen by scripts/select_tests.py: a path and the test folder that must still be covered
# (a whole folder, or at least one test file inside it; None: nothing but the guards). Written out here, never read from the selector.
HOOK_CASES = [
    (".githooks/pre-commit", "scripts/tests"), (".github/workflows/checks.yml", "scripts/tests"),
    ("packs/default.txt", "scripts/tests"), ("templates/agent.md", "scripts/tests"),
    ("agents/reviewer.md", "scripts/tests"), ("scripts/validate.py", "scripts/tests"),
    ("providers/resolve.py", "scripts/tests"), ("providers/store/sqlite.py", "providers/store/tests"),
    ("evals/eval_run.py", "evals/tests"), ("adapters/api/run_agent.py", "adapters/api/tests"),
    ("runtime/lab.py", "runtime/tests"), ("runtime/tests/test_lab_facade.py", "runtime/tests"),
    ("flows/market-positioning.json", "runtime/tests"), ("interface/index.html", "runtime/tests"),
    ("interface/js/app.js", "runtime/tests"),
    ("skills/demo/evals/runtime-manifest.json", "runtime/tests"),
    ("skills/mkt-publish/scripts/payload.py", "skills/mkt-publish/scripts/tests"),
    ("shared/scripts/rank.py", "shared/scripts/tests"), ("shared/scripts/copies.json", "shared/scripts/tests"),
    ("shared/scripts/tests/test_shared_rank.py", "shared/scripts/tests"),
    ("evals/execution.py", "runtime/tests"),  # the runtime's lab facade loads the execution kit
    ("skills/core-demo/SKILL.md", None), ("docs/backlog.md", None), ("README.md", None),
]


def test_the_hook_asks_the_selector_for_the_tests_and_keeps_no_folder_map_of_its_own():
    hook = (REPO / ".githooks" / "pre-commit").read_text()
    assert "scripts/select_tests.py --files-from -" in hook and "scripts/test_slots.py" in hook
    assert "dirs+=(" not in hook and 'shared/*) d="shared/scripts/tests"' not in hook  # the folder map is gone
    assert "--no-verify" not in "\n".join(line for line in hook.splitlines() if not line.lstrip().startswith("#"))


def test_the_selection_keeps_the_coverage_the_folder_map_of_the_hook_had():
    """Each path of the old map still reaches its test folder: the folder whole, or a test file inside it. Nothing else may be asserted
    from the selector here (its own tests are in test_select_tests.py); this is only the check that a mapping was not lost."""
    select_tests = load("select_tests")
    repo = select_tests.Repo(str(REPO))
    for path, folder in HOOK_CASES:
        chosen = select_tests.select(repo, [path]).result()
        beyond_guards = [t for t in chosen if t not in select_tests.GUARDS]
        if folder is None:
            assert beyond_guards == [], path
        else:
            assert any(t == folder or t.startswith(folder + "/") for t in beyond_guards), (path, beyond_guards[:5])


# The `if:` expressions of the jobs, read from the text of checks.yml and evaluated for the events that matter. GitHub's expression
# language is small; the subset used here (&&, ||, !, ==, !=, contains of the label list, the five fields below) is translated to Python.
def job_condition(name, text=None):
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text() if text is None else text
    jobs = text[re.search(r"^jobs:\s*$", text, re.M).end():]
    block = dict(zip(re.findall(r"^  ([\w-]+):\s*$", jobs, re.M), re.split(r"^  [\w-]+:\s*$", jobs, flags=re.M)[1:]))[name]
    lines = [line for line in block.splitlines() if not line.lstrip().startswith("#")]
    for i, line in enumerate(lines):
        match = re.match(r"^    if:\s*(.*)$", line)
        if match:
            parts = [match.group(1)]
            if parts[0] in (">-", ">", "|"):
                parts = []
            for follow in lines[i + 1:]:
                if re.match(r"^ {6,}\S", follow):
                    parts.append(follow.strip())
                else:
                    break
            return " ".join(parts)
    return None


def step_condition(job, step_name, text=None):
    """The `if:` of the step of that job with that name (None when it has none)."""
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text() if text is None else text
    lines = job_block(text, job).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().replace('"', "") == "- name: " + step_name)
    parts, found = [], False
    for line in lines[start + 1:]:
        if re.match(r"^      - ", line):
            break
        match = re.match(r"^        if:\s*(.*)$", line)
        if match:
            found = True
            if match.group(1) not in (">-", ">", "|"):
                parts.append(match.group(1))
        elif found and re.match(r"^ {10,}\S", line):
            parts.append(line.strip())
        elif found:
            break
    return " ".join(parts) if found else None


def evaluate(expression, event_name, action=None, base_ref="", labels=(), label=None, draft=None):
    if expression is None:
        return True  # a job without a condition runs
    expression = expression.replace("always()", "True")  # the condition of the aggregator: it runs, whatever its needs ended in
    py = re.sub(r"contains\(github\.event\.pull_request\.labels\.\*\.name,\s*'([^']+)'\)", lambda m: "(%r in labels)" % m.group(1), expression)
    py = py.replace("github.event_name", "event_name").replace("github.event.action", "action").replace("github.base_ref", "base_ref")
    py = py.replace("github.event.label.name", "label").replace("github.event.pull_request.draft", "draft")
    py = py.replace("&&", " and ").replace("||", " or ")
    py = re.sub(r"!(?!=)", " not ", py)
    names = {"event_name": event_name, "action": action, "base_ref": base_ref, "labels": list(labels), "label": label, "draft": draft}
    return bool(walk(ast.parse(py.strip(), mode="eval").body, names))


def walk(node, names):
    """The subset of Python the translated expression uses, interpreted node by node (no eval)."""
    if isinstance(node, ast.BoolOp):
        values = (walk(v, names) for v in node.values)
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not walk(node.operand, names)
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        left, right, op = walk(node.left, names), walk(node.comparators[0], names), node.ops[0]
        return {ast.Eq: lambda: left == right, ast.NotEq: lambda: left != right, ast.In: lambda: left in right}[type(op)]()
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.Constant):
        return node.value
    raise AssertionError("an expression of the workflow uses something this reader does not know: %s" % ast.dump(node))


EVENTS = {
    "a push to main": dict(event_name="push"),
    "a pull request into main": dict(event_name="pull_request", action="synchronize", base_ref="main"),
    "a manual run": dict(event_name="workflow_dispatch"),
    "a pull request labelled full-suite, a new commit": dict(event_name="pull_request", action="synchronize", base_ref="feature/x", labels=["full-suite"]),
    "the label full-suite just added": dict(event_name="pull_request", action="labeled", base_ref="feature/x", labels=["full-suite"], label="full-suite"),
    "a pull request into an integration branch": dict(event_name="pull_request", action="synchronize", base_ref="feature/x"),
    "another label just added": dict(event_name="pull_request", action="labeled", base_ref="feature/x", labels=["docs"], label="docs"),
    "another label added to a pull request into main": dict(event_name="pull_request", action="labeled", base_ref="main", labels=["docs"], label="docs"),
    "a draft pull request into an integration branch": dict(event_name="pull_request", action="synchronize", base_ref="feature/x", draft=True),
    "a draft pull request into main": dict(event_name="pull_request", action="synchronize", base_ref="main", draft=True),
    "a draft marked ready": dict(event_name="pull_request", action="ready_for_review", base_ref="feature/x", draft=False),
}


# The required status checks of the `main` ruleset (`gh api repos/chrissgon/openhora/rules/branches/main`, required_status_checks). This is
# the one place of the tests to change, with the aggregator's `name:` line in .github/workflows/checks.yml, if the maintainer renames the
# required check (and the ruleset itself, which is the maintainer's action).
REQUIRED_CHECKS = ("validate", "tests")
WHOLE = "Scanner and provider tests, the whole suite"  # the step of each shard that runs its part of the suite
GATE = "Every shard passed"  # the step of the aggregator that fails unless every shard did
SHARDS = "tests-shard"
DRAFT_STEP = "Draft: no test has run"  # the step of the aggregator that fails on a draft pull request
SELECTED = "Selected scanner, provider, runtime and script tests"
CHOOSE = "Choose the tests this pull request can reach"


def modes(job_if, whole_if, selected_if):
    """For each event: None (the job does not run), "whole" or "selected" (the step that runs the tests)."""
    out = {}
    for name, event in EVENTS.items():
        if not evaluate(job_if, **event):
            out[name] = None
            continue
        whole, selected = evaluate(whole_if, **event), evaluate(selected_if, **event)
        assert whole != selected, (name, "exactly one of the two test steps runs")
        out[name] = "whole" if whole else "selected"
    return out


WANTED_MODES = {
    "a push to main": "whole", "a pull request into main": "whole", "a manual run": "whole",
    "a pull request labelled full-suite, a new commit": "whole", "the label full-suite just added": "whole",
    "a pull request into an integration branch": "selected", "another label just added": "selected", "another label added to a pull request into main": "whole",
    "a draft pull request into an integration branch": None, "a draft pull request into main": None, "a draft marked ready": "selected",
}


def squash(text):
    return " ".join(text.split())


def step_text(block, name):
    """The text of the step of that block with that name: up to the next step, or the end of the job (a comment that sits above the
    next job belongs to this block and is not part of the step)."""
    lines = block.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().replace('"', "") == "- name: " + name)
    out = [lines[start]]
    for line in lines[start + 1:]:
        if re.match(r"^      - ", line) or (line.strip() and not line.startswith("        ")):
            break
        out.append(line)
    return "\n".join(out)


def test_the_shards_run_the_selection_or_the_whole_list_and_the_tests_job_gates_them():
    """The required check of the main ruleset is `tests`: it runs no test, on a pull request into main it must run, and it must fail unless every
    shard succeeded. The shards run on every event, in the mode the event asks for: the whole list (every test folder) at the end of a delivery,
    the selection otherwise."""
    got = modes(job_condition(SHARDS), step_condition(SHARDS, WHOLE), step_condition(SHARDS, SELECTED))
    assert got == WANTED_MODES
    assert step_condition(SHARDS, CHOOSE) == step_condition(SHARDS, SELECTED)  # the selector runs exactly when its targets are used
    assert squash(step_condition("tests", GATE) or "") == squash(job_condition(SHARDS) or "")  # the shards run exactly when the gate needs them
    # exactly one of the two steps of the aggregator runs on every event, and the draft one is the logical negation of the gate's
    for name, event in EVENTS.items():
        assert evaluate(step_condition("tests", DRAFT_STEP), **event) is (not evaluate(step_condition("tests", GATE), **event)), name
    assert [e for e, event in EVENTS.items() if evaluate(step_condition("tests", DRAFT_STEP), **event)] == [
        "a draft pull request into an integration branch", "a draft pull request into main"]
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    block = job_block(text, "tests")
    draft = step_text(block, DRAFT_STEP)
    assert "exit 1" in draft and "a draft pull request runs no tests; mark it ready for review to run them" in draft
    gate = step_text(block, GATE)
    assert "SHARDS: ${{ needs.tests-shard.result }}" in gate and 'test "$SHARDS" = "success"' in gate
    assert re.search(r"^    needs: (tests-shard|\[.*\btests-shard\b.*\])\s*$", block, re.M) and re.search(r"^    if: always\(\)\s*$", block, re.M)
    assert "pytest" not in block and "checkout" not in block and "setup-uv" not in block  # the aggregator runs no test, so it has nothing to check out
    shard_block = job_block(text, SHARDS)
    shard_step = step_text(shard_block, WHOLE)
    assert "$(python3 scripts/test_dirs.py)" in shard_step and 'WB_FULL_FUZZ: "1"' in shard_step and "select_tests" not in shard_step
    count = re.search(r'python scripts/shard_tests\.py --shard "\$SHARD/(\d+)"', shard_step)
    assert count, "each shard starts the launcher with its K of an integer N"
    assert matrix_of(shard_block) == list(range(1, int(count.group(1)) + 1)) and re.search(r"^      fail-fast: false\s*$", shard_block, re.M)
    selected_step = step_text(shard_block, SELECTED)
    assert "selected-tests.txt" in selected_step and "WB_FULL_FUZZ" not in selected_step
    assert re.search(r'python scripts/shard_tests\.py --shard "\$SHARD/%s"' % count.group(1), selected_step)  # the selection is sharded the same way
    assert not re.search(r"^  full-suite:\s*$", text, re.M)  # no second job to be the only gate


# The steps that run the failures again, with the detail `--assert=plain` leaves out of a first report. Per job: the name of each step and the
# `id` of the run step it answers. They exist so that a failure is readable; they must never be able to make a red job green.
FAILURE_STEPS = {
    SHARDS: [("The failures again, with assertion detail (the whole suite)", "whole"),
             ("The failures again, with assertion detail (the selection)", "selected")],
    "python39": [("The failures again, with assertion detail (Python 3.9)", "py39")],
}


def failure_step_problems(text):
    """What is wrong with the failure re-runs of a text of checks.yml, as a list. Each one: exists after the run step it answers; runs under
    `failure()` AND the outcome of that run step (never `always()`, never an `||`); is `continue-on-error: true`, so that its own result
    never reaches the job; reruns only the cache's failures (`--lf --lfnf=none`) without the launcher, the workers or the plain mode. And in
    the job nothing else is `continue-on-error` (a run step that is would turn the job green when its tests fail) and a run step has its id."""
    found = []
    for job, steps in FAILURE_STEPS.items():
        block = job_block(text, job)
        plain = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
        if plain.count("continue-on-error") != len(steps) or plain.count("continue-on-error: true") != len(steps):
            found.append(job + ": a step other than the failure re-runs is continue-on-error, or one is not `true`")
        for name, run_id in steps:
            try:
                step = step_text(plain, name)
            except StopIteration:
                found.append(job + ": no step " + name)
                continue
            condition = squash(step_condition(job, name, text) or "")
            if not re.fullmatch(r"failure\(\) && steps\.%s\.outcome == 'failure'" % run_id, condition):
                found.append("%s: %s: the condition is %r" % (job, name, condition))
            if not re.search(r"^        continue-on-error: true\s*$", step, re.M):
                found.append("%s: %s: it is not continue-on-error: true" % (job, name))
            if not all(word in step for word in ("--lf ", "--lfnf=none")) or any(word in step for word in ("shard_tests.py", "-n auto", "--assert=plain", "--dist")):
                found.append("%s: %s: it does not rerun only the cache's failures in the default mode" % (job, name))
            run = next((l for l in plain.splitlines() if l.strip() == "id: " + run_id), None)
            if run is None or plain.index(run) > plain.index(step):
                found.append("%s: %s: the run step `%s` is missing or comes after it" % (job, name, run_id))
    return found


def job_ends(steps):
    """GitHub's rule for a job, on a list of (outcome, continue_on_error): the job ends red when a step failed that is not continue-on-error."""
    return "failure" if any(outcome == "failure" and not keeps_going for outcome, keeps_going in steps) else "success"


def test_the_failure_reruns_can_never_turn_a_red_job_green():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    assert failure_step_problems(text) == []
    # the rule they rest on, for the three jobs: the run step failed (its tests did), the re-run fails or passes either way, the job is red
    for rerun_outcome in ("failure", "success", "skipped"):
        assert job_ends([("failure", False), (rerun_outcome, True)]) == "failure"
    assert job_ends([("success", False), ("skipped", True)]) == "success"  # and a green run is untouched
    # `tests` reads the shards' own result, which the re-runs do not change
    assert 'test "$SHARDS" = "success"' in step_text(job_block(text, "tests"), GATE)


def test_vacuity_a_failure_rerun_that_could_mask_a_failure_is_caught():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    first, second = FAILURE_STEPS[SHARDS][0][0], FAILURE_STEPS["python39"][0][0]
    plants = {
        "always instead of failure": text.replace("if: failure() && steps.whole.outcome == 'failure'", "if: always()", 1),
        "an or in the condition": text.replace("if: failure() && steps.selected.outcome == 'failure'", "if: failure() || steps.selected.outcome == 'failure'", 1),
        "no continue-on-error": text.replace("        continue-on-error: true\n        timeout-minutes: 10\n        env:\n          WB_FULL_FUZZ", "        timeout-minutes: 10\n        env:\n          WB_FULL_FUZZ", 1),
        "continue-on-error false": text.replace("continue-on-error: true", "continue-on-error: false", 1),
        "a run step that goes on": text.replace("        id: py39\n", "        id: py39\n        continue-on-error: true\n", 1),
        "the re-run is sharded": text.replace("pytest -q --lf --lfnf=none -o faulthandler_timeout=120\n          $(cat \"$RUNNER_TEMP/py39.txt\")",
                                              "python scripts/shard_tests.py --shard 1/3 -- -q --lf --lfnf=none\n          $(cat \"$RUNNER_TEMP/py39.txt\")", 1),
        "it never stops at none": text.replace("--lf --lfnf=none", "--lf", 1),
        "it answers the wrong step": text.replace("steps.py39.outcome", "steps.whole.outcome", 1),
        "the step is gone": text.replace(second, "Another step", 1),
    }
    assert first and second
    for name, planted in plants.items():
        assert planted != text, name
        assert failure_step_problems(planted), name


def matrix_of(shard_block):
    match = re.search(r"^        shard: \[(.*)\]\s*$", shard_block, re.M)
    return [int(x) for x in match.group(1).split(",")] if match else None


def test_the_required_jobs_are_never_skipped_and_a_pull_request_into_main_never_runs_the_selection():
    """`validate` and `tests` are the required checks of the main ruleset. A job skipped by its `if:` counts as passing on the same commit,
    so a label added to a pull request must not be able to skip either (`tests` has only `if: always()`, the condition that never skips);
    on a pull request into main every event runs the whole suite."""
    assert job_condition("tests") in (None, "always()") and job_condition("validate") is None
    selected = step_condition(SHARDS, SELECTED)
    for name, event in EVENTS.items():
        if event.get("event_name") == "pull_request" and event.get("base_ref") == "main":
            assert evaluate(selected, **event) is False, name
    for action in ("opened", "synchronize", "reopened", "labeled", "ready_for_review"):
        event = dict(event_name="pull_request", action=action, base_ref="main", labels=["docs"], label="docs" if action == "labeled" else None, draft=False)
        assert evaluate(step_condition("tests", GATE), **event) is True and evaluate(selected, **event) is False, action
        assert evaluate(job_condition(SHARDS), **event) is True, action  # and the shards run, so the gate has something to wait for
    # no other job takes the name of a required check: a shard is named `tests shard <k> of 3`, which is never `tests`
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    jobs = text[re.search(r"^jobs:\s*$", text, re.M).end():]
    for name, block in zip(re.findall(r"^  ([\w-]+):\s*$", jobs, re.M), re.split(r"^  [\w-]+:\s*$", jobs, flags=re.M)[1:]):
        if name in REQUIRED_CHECKS:
            continue  # the required jobs: each holds its own name (the first assertion of the next test of this file)
        match = re.search(r"^    name:\s*(.*?)\s*$", block, re.M)
        assert match is None or match.group(1) not in REQUIRED_CHECKS, name
    assert re.search(r"^    name: tests shard \$\{\{ matrix\.shard \}\} of \d+\s*$", job_block(text, SHARDS), re.M)
    for required in REQUIRED_CHECKS:
        assert re.search(r"^    name: %s\s*$" % re.escape(required), job_block(text, required), re.M), required


def test_planted_workflows_that_skip_tests_or_select_on_a_pull_request_into_main_are_caught_by_the_oracle():
    whole, selected = step_condition(SHARDS, WHOLE), step_condition(SHARDS, SELECTED)
    # the design of the previous head: the job is skipped on a label other than full-suite (a skipped required check passes)
    skips_on_a_label = "github.event.action != 'labeled' || github.event.label.name == 'full-suite'"
    assert modes(skips_on_a_label, whole, selected) != WANTED_MODES
    # the first design of this package: the job is skipped for a pull request into main
    skipped_into_main = "github.event.action != 'labeled' && github.base_ref != 'main'"
    assert modes(skipped_into_main, whole, selected) != WANTED_MODES
    # a whole-suite step that forgets the base: a pull request into main would run neither step, which the helper refuses
    forgets_base = "github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'full-suite')"
    with pytest.raises(AssertionError):
        modes(None, forgets_base, selected)
    # a selected step that forgets the base: a pull request into main would run both
    with pytest.raises(AssertionError):
        modes(None, whole, "github.event_name == 'pull_request' && !contains(github.event.pull_request.labels.*.name, 'full-suite')")
    # shards that also run on a draft: the draft step of the aggregator fails, and these would have run the whole suite for nothing
    runs_on_a_draft = modes(None, whole, selected)
    assert runs_on_a_draft != WANTED_MODES and runs_on_a_draft["a draft pull request into main"] == "whole"


def draft_step_fails_closed(text):
    """True only when the aggregator has a draft step that fails (an `exit 1` that nothing follows) and runs exactly when the gate step does not."""
    block = job_block(text, "tests")
    try:
        script = step_text(block, DRAFT_STEP)
        draft_if, gate_if = step_condition("tests", DRAFT_STEP, text), step_condition("tests", GATE, text)
    except StopIteration:
        return False
    if draft_if is None or gate_if is None or not re.search(r"^\s+exit 1\s*$", script, re.M):
        return False
    return all(evaluate(draft_if, **event) is (not evaluate(gate_if, **event)) for event in EVENTS.values())


def gate_holds(text):
    """True only when the aggregator is a gate that fails closed: it always runs, needs the shards, compares their result with success,
    the shards run exactly when it needs them, and the matrix covers 1..N for the N the launcher is told."""
    block, shard_block = job_block(text, "tests"), job_block(text, SHARDS)
    if not (re.search(r"^    if: always\(\)\s*$", block, re.M) and re.search(r"^    needs: (tests-shard|\[.*\btests-shard\b.*\])\s*$", block, re.M)):
        return False
    gate = step_text(block, GATE)
    if not ("SHARDS: ${{ needs.tests-shard.result }}" in gate and 'test "$SHARDS" = "success"' in gate):
        return False
    if not draft_step_fails_closed(text):
        return False
    if squash(step_condition("tests", GATE, text) or "") != squash(job_condition(SHARDS, text) or ""):
        return False
    count = re.search(r'python scripts/shard_tests\.py --shard "\$SHARD/(\d+)"', shard_block)
    return bool(count) and matrix_of(shard_block) == list(range(1, int(count.group(1)) + 1))


def test_planted_gates_that_let_a_failed_or_missing_shard_pass_are_caught_by_the_oracle():
    real = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    assert gate_holds(real)
    shard_if = "    if: github.event_name != 'pull_request' || !github.event.pull_request.draft\n"
    gate_if = "        if: github.event_name != 'pull_request' || !github.event.pull_request.draft\n"
    plants = {
        "the aggregator is skipped when a shard fails": real.replace("    needs: tests-shard\n    if: always()\n", "    needs: tests-shard\n", 1),
        "a shard is left out of the matrix": real.replace("[1, 2, 3]", "[1, 2]", 1),
        "the gate does not compare the result": real.replace('test "$SHARDS" = "success"', "true", 1),
        "the gate step is skipped on some event, which counts as a pass": real.replace(gate_if, "        if: github.event_name != 'pull_request'\n", 1),
        "the shards run on fewer events than the gate waits for": real.replace(shard_if, "    if: github.event_name != 'pull_request'\n", 1),
        "the gate condition also runs on a draft, so a skipped shard counts as passing": real.replace(gate_if, "", 1),
        "the shards are skipped on a draft but the gate runs there": real.replace(gate_if, "        if: github.event_name != 'pull_request' || github.base_ref == 'main'\n", 1),
        "the draft step does not fail": real.replace("          exit 1\n", "          true\n", 1),
        "the draft step is skipped on a draft": real.replace(
            "        if: github.event_name == 'pull_request' && github.event.pull_request.draft\n", "        if: github.event_name == 'push'\n", 1),
    }
    for name, planted in plants.items():
        assert planted != real, name
        assert not gate_holds(planted), name


def test_an_unrelated_label_skips_the_optional_jobs_runs_the_shards_the_gate_needs_and_the_label_of_the_whole_suite_starts_them():
    other = EVENTS["another label just added"]
    full = EVENTS["the label full-suite just added"]
    for name in ("python39", "changes"):
        assert evaluate(job_condition(name), **other) is False, name
        assert evaluate(job_condition(name), **full) is True, name
    # the gate `tests` runs on every label event, so the shards it waits for run too (a skipped shard would make the gate fail): in the mode the base asks for
    assert evaluate(job_condition(SHARDS), **other) is True and evaluate(job_condition(SHARDS), **full) is True
    assert evaluate(step_condition(SHARDS, SELECTED), **other) is True and evaluate(step_condition(SHARDS, WHOLE), **other) is False
    assert evaluate(step_condition(SHARDS, WHOLE), **full) is True and evaluate(step_condition(SHARDS, SELECTED), **full) is False


def test_the_docker_and_go_jobs_wait_for_the_job_that_says_whether_their_paths_changed():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    for name in ("container", "converter", "go"):
        block = job_block(text, name)
        assert re.search(r"^    needs: changes\s*$", block, re.M), name
        assert "needs.changes.outputs.%s == 'true'" % name in block, name
    changes = job_block(text, "changes")
    assert 'everything=true' in changes and '"$BASE_REF" = "main"' in changes and '"$FULL_LABEL" = "true"' in changes and '"$ACTION" = "labeled"' in changes


def job_block(text, name):
    jobs = text[re.search(r"^jobs:\s*$", text, re.M).end():]
    return dict(zip(re.findall(r"^  ([\w-]+):\s*$", jobs, re.M), re.split(r"^  [\w-]+:\s*$", jobs, flags=re.M)[1:]))[name]


def changes_script():
    block = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), "changes")
    lines = block.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "run: |")
    body = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


def run_changes(tmp_path, files, **env):
    """The shell of the `changes` job, as the workflow has it, on a repository whose branch changed `files` since its base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"})

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=clean, check=True, timeout=60).stdout.strip()

    git("init", "-q", "-b", "main")
    (repo / "README.md").write_text("x\n")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    for rel in files:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("changed\n")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    out = tmp_path / "github-output"
    out.write_text("")
    script = tmp_path / "changes.sh"
    script.write_text(changes_script())
    full = {**clean, "GITHUB_OUTPUT": str(out), "BASE_SHA": base, **env}
    done = subprocess.run(["bash", str(script)], cwd=repo, env=full, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return dict(line.split("=") for line in out.read_text().split())


PR = dict(EVENT="pull_request", ACTION="synchronize", BASE_REF="feature/x", FULL_LABEL="false", DRAFT="false")


def test_the_docker_and_go_jobs_run_when_their_paths_changed_and_in_the_cases_of_the_whole_suite(tmp_path):
    for i, (files, env, want) in enumerate([
        (["providers/messenger/whatsapp/bridge.go"], PR, {"container": "false", "converter": "false", "go": "true"}),
        (["providers/converter/Dockerfile"], PR, {"container": "false", "converter": "true", "go": "false"}),
        (["evals/container/Dockerfile"], PR, {"container": "true", "converter": "false", "go": "false"}),
        (["skills/mkt-publish/evals/evals.json"], PR, {"container": "true", "converter": "false", "go": "false"}),  # the eval container stages skills
        (["providers/secrets/resolver.py"], PR, {"container": "true", "converter": "false", "go": "false"}),
        (["docs/decisions.md"], PR, {"container": "false", "converter": "false", "go": "false"}),
        (["docs/decisions.md"], {**PR, "BASE_REF": "main"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {**PR, "FULL_LABEL": "true"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {**PR, "ACTION": "labeled"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {"EVENT": "push", "ACTION": "", "BASE_REF": "", "FULL_LABEL": "", "DRAFT": ""}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {"EVENT": "workflow_dispatch", "ACTION": "", "BASE_REF": "", "FULL_LABEL": "", "DRAFT": ""}, {"container": "true", "converter": "true", "go": "true"}),
        # a draft runs none of the three jobs, whatever changed and whatever the label or the base, and reads no diff (the base below is no commit)
        (["providers/messenger/whatsapp/bridge.go"], {**PR, "DRAFT": "true", "BASE_SHA": "0" * 40}, {"container": "false", "converter": "false", "go": "false"}),
        (["evals/container/Dockerfile"], {**PR, "DRAFT": "true", "BASE_SHA": "0" * 40, "BASE_REF": "main"}, {"container": "false", "converter": "false", "go": "false"}),
        (["docs/decisions.md"], {**PR, "DRAFT": "true", "BASE_SHA": "0" * 40, "ACTION": "labeled", "FULL_LABEL": "true"}, {"container": "false", "converter": "false", "go": "false"}),
        (["providers/messenger/whatsapp/bridge.go"], {**PR, "ACTION": "ready_for_review"}, {"container": "false", "converter": "false", "go": "true"}),  # marked ready: read as any push
        # one file per decision entry (docs/decisions/): the same as the closed log, docs/decisions.md
        (["docs/decisions/2026-10-27-pkg-a-rule.md"], PR, {"container": "false", "converter": "false", "go": "false"}),
        (["docs/decisions/2026-10-27-pkg-a-rule.md"], {**PR, "BASE_REF": "main"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions/2026-10-27-pkg-a-rule.md"], {**PR, "FULL_LABEL": "true"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions/2026-10-27-pkg-a-rule.md"], {"EVENT": "push", "ACTION": "", "BASE_REF": "", "FULL_LABEL": "", "DRAFT": ""}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions/2026-10-27-pkg-a-rule.md"], {**PR, "DRAFT": "true", "BASE_SHA": "0" * 40}, {"container": "false", "converter": "false", "go": "false"}),
    ]):
        case = tmp_path / ("case%d" % i)
        case.mkdir()
        assert run_changes(case, files, **env) == want, (files, env)


def test_the_triggers_of_the_workflow_include_the_label_event_and_the_manual_run():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    head = text[:text.index("\npermissions:")]
    assert "workflow_dispatch:" in head and "types: [opened, synchronize, reopened, labeled, ready_for_review]" in head and "branches: [main]" in head
    assert "github.event.action == 'labeled' && 'label' || 'code'" in text  # a label does not cancel the run of the last push
    # and a label run is never cancelled itself (it may be the whole suite, started by the label full-suite)
    assert "cancel-in-progress: ${{ github.ref != 'refs/heads/main' && github.event.action != 'labeled' }}" in text


def test_the_step_that_pipes_the_selector_into_tee_fails_when_the_selector_does():
    text = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), SHARDS)
    step = text[text.index("- name: Choose the tests"):text.index("- name: Scanner and provider tests")]
    assert re.search(r"^        shell: bash\b", step, re.M) and "select_tests.py --base" in step and "| tee" in step  # bash -e -o pipefail


def tree(tmp_path, cited):
    """A repository with the real runner and one skill whose case ships `shipped.md` and cites `cited`."""
    (tmp_path / "evals").mkdir()
    for name in ("eval_run.py", "execution.py", "eval_status.py", "evidence_lines.py", "grading-prompt.md"):
        shutil.copy(REPO / "evals" / name, tmp_path / "evals" / name)
    skill = tmp_path / "skills" / "core-demo"
    (skill / "evals" / "files").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: core-demo\n---\n# demo\n")
    (skill / "evals" / "files" / "shipped.md").write_text("shipped\n")
    (skill / "evals" / "evals.json").write_text(json.dumps({"skill_name": "core-demo", "evals": [
        {"id": 1, "prompt": f"Read `{cited}` and summarise it.", "files": ["evals/files/shipped.md"],
         "expected_output": "a summary", "assertions": ["The summary names the file."]}]}))
    return tmp_path


def errors_of(root):
    report = validate.Report()
    validate.check_eval_cases(report, root=str(root))
    return [f"{e['where']}: {e['message']}" for e in report.errors]


def test_validate_accepts_cases_whose_cited_files_are_shipped(tmp_path):
    assert errors_of(tree(tmp_path, "shipped.md")) == []


def test_validate_reports_a_case_that_cites_a_file_it_does_not_ship(tmp_path):
    errors = errors_of(tree(tmp_path, "docs/missing.md"))
    assert len(errors) == 1 and errors[0].startswith("skills/core-demo/evals/evals.json: [eval-cases]")
    assert "docs/missing.md" in errors[0] and "--check-cases" in errors[0]


# ---- the nightly run (.github/workflows/nightly.yml; docs/decisions.md, the entry of T2b) ----------------------------------------------------

def nightly_problems(text):
    """What is wrong with a text of the nightly workflow, as a list: a permission that writes, a secret, an artifact, a checkout that keeps
    its credentials, a job whose condition is not the one that lets a label or the schedule start it, a job named like a required check,
    and an expression `${{ }}` in the lines a shell runs (a script injection)."""
    found = []
    if "permissions:\n  contents: read\n" not in text:
        found.append("the permissions are not exactly contents: read")
    found += ["a permission set to write: " + line.strip() for line in text.splitlines() if re.match(r"^\s*[\w-]+:\s*write\b", line)]
    found += [word for word in ("secrets.", "upload-artifact") if word in text]
    if text.count("persist-credentials: false") != text.count("actions/checkout@") or "actions/checkout@" not in text:
        found.append("a checkout keeps its credentials")
    jobs = text[re.search(r"^jobs:\s*$", text, re.M).end():]
    blocks = re.split(r"^  [\w-]+:\s*$", jobs, flags=re.M)[1:]
    for block in blocks:
        condition = re.findall(r"^    if:\s*(.*?)\s*$", block, re.M)
        if condition != [NIGHTLY_IF]:
            found.append("a job whose condition is not the nightly one: %r" % condition)
        name = re.search(r"^    name:\s*(.*?)\s*$", block, re.M).group(1)
        if name in REQUIRED_CHECKS:
            found.append("a job named like a required check: " + name)
    for chunk in re.split(r"^\s*- (?:name|uses):", text, flags=re.M):
        run = re.search(r"^\s*run:", chunk, re.M)
        if run and "${{" in chunk[run.end():]:
            found.append("an expression in a run line: " + chunk[run.end():].strip().splitlines()[0])
    return found


def test_the_nightly_runs_every_test_folder_with_the_full_fuzz_in_three_shards_and_runs_a_failure_again():
    text = NIGHTLY.read_text(encoding="utf-8")
    block = job_block(text, "nightly-shard")
    step = step_text(block, NIGHTLY_WHOLE)
    for wanted in ('WB_FULL_FUZZ: "1"', "$(python3 scripts/test_dirs.py)", 'python scripts/shard_tests.py --shard "$SHARD/3" --', "-n auto",
                   "--with pytest-xdist==3.8.0", "--reruns 3", "shell: bash"):
        assert wanted in step, wanted
    assert re.search(r"--with pytest-rerunfailures==\d+(\.\d+)+\b", step)
    assert "select_tests" not in text  # the whole list, never a selection
    assert "        shard: [1, 2, 3]\n" in block + "\n" and "fail-fast: false" in block


def py39_targets(text):
    """The targets of the python39 list as both workflows read them: `grep -v '^#'`, and a blank line is no word to the shell."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def py39_list_problems(text, root=REPO):
    """What is wrong with a text of the python39 list: a target that does not exist, a duplicate, a `#` after a target (the shell would pass
    it to pytest as a path), a space inside a line, or the 3.9 guard missing."""
    found = []
    targets = py39_targets(text)
    found += ["a duplicate: " + t for t in sorted({t for t in targets if targets.count(t) > 1})]
    for t in targets:
        if "#" in t or " " in t:
            found.append("a comment or a space inside a target: " + t)
        elif not (Path(root) / t).exists():
            found.append("a target that does not exist: " + t)
    if "scripts/tests/test_runtime_python39.py" not in targets:
        found.append("the 3.9 guard is not in the list")
    return found


def test_the_nightly_python39_runs_the_whole_python39_list_read_from_the_one_file():
    ours = step_text(job_block(NIGHTLY.read_text(encoding="utf-8"), "nightly-python39"), NIGHTLY_PY39)
    assert "$(grep -v '^#' scripts/python39_tests.txt)" in ours
    assert "select_tests" not in ours  # the whole list, never a selection
    for wanted in ("--python 3.9", "--with pytest==8.4.2", 'WB_SKIP_JS_ONLY_TESTS: "1"', "--reruns 3"):
        assert wanted in ours, wanted
    assert re.search(r"--with pytest-rerunfailures==\d+(\.\d+)+\b", ours)


def test_the_python39_list_is_written_once_and_both_workflows_read_that_file():
    checks = (REPO / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
    nightly = NIGHTLY.read_text(encoding="utf-8")
    targets = py39_targets((REPO / PY39_LIST).read_text(encoding="utf-8"))
    assert len(targets) >= 20  # the reader found the list; an empty one would pass the loop below for the wrong reason
    for name, text in (("checks.yml", checks), ("nightly.yml", nightly)):
        assert PY39_LIST in text, name
        for target in targets:
            # a target never appears a second time in a workflow (the word `providers/model/tests` is in the list file only)
            assert not re.search(r"(?<![\w./-])%s(?![\w./-])" % re.escape(target), "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))), (name, target)


def test_every_line_of_the_python39_list_names_an_existing_path_and_the_guard_is_in_it():
    assert py39_list_problems((REPO / PY39_LIST).read_text(encoding="utf-8")) == []


def test_vacuity_a_python39_list_with_a_missing_path_a_duplicate_a_trailing_comment_or_no_guard_is_caught(tmp_path):
    (tmp_path / "scripts" / "tests").mkdir(parents=True)
    (tmp_path / "scripts" / "tests" / "test_runtime_python39.py").write_text("")
    (tmp_path / "runtime" / "tests").mkdir(parents=True)
    good = "# a comment\n\nscripts/tests/test_runtime_python39.py\nruntime/tests\n"
    assert py39_list_problems(good, tmp_path) == []
    for planted in (good + "runtime/gone/tests\n", good + "runtime/tests\n", good + "runtime/tests # why\n",
                    "runtime/tests\n"):
        assert py39_list_problems(planted, tmp_path), planted


def step_script(block, name):
    """The shell text of the `run:` of the step with that name (a `run: |` block, dedented, or a one-line `run:`)."""
    lines = step_text(block, name).splitlines()
    one = [line.strip()[len("run: "):] for line in lines if line.strip().startswith("run: ") and line.strip() != "run: |"]
    if one:
        return one[0] + "\n"
    start = next(i for i, line in enumerate(lines) if line.strip() == "run: |")
    body = []
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


def test_the_python39_job_selects_under_the_condition_of_the_shards_and_runs_the_whole_list_in_every_other_case_in_three_shards():
    choose = step_condition("python39", PY39_CHOOSE)
    assert squash(choose) == squash(step_condition(SHARDS, CHOOSE))  # the same pull requests: into a branch other than main, no full-suite label
    got = modes(job_condition("python39"), step_condition("python39", PY39_WHOLE), choose)
    wanted = dict(WANTED_MODES)
    wanted["another label just added"] = wanted["another label added to a pull request into main"] = None  # the job waits for the label full-suite
    assert got == wanted and got["a draft pull request into main"] is None and got["a draft marked ready"] == "selected"  # a draft runs no shard of the list
    block = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), "python39")
    assert "fetch-depth: 0" in block  # the selector reads the merge base with the pull request's base
    pytest_step = step_text(block, PY39_STEP)
    assert '$(cat "$RUNNER_TEMP/py39.txt")' in pytest_step and "--python 3.9" in pytest_step and "--with pytest==8.4.2" in pytest_step
    assert "--with pytest-xdist==3.8.0" in pytest_step and 'WB_SKIP_JS_ONLY_TESTS: "1"' in pytest_step
    # three shards of the list, the way tests-shard shards the selection: the launcher, K of 3, a matrix 1..3
    count = re.search(r'python scripts/shard_tests\.py --shard "\$SHARD/(\d+)"', pytest_step)
    assert count and "SHARD: ${{ matrix.shard }}" in pytest_step
    assert matrix_of(block) == list(range(1, int(count.group(1)) + 1)) == [1, 2, 3] and re.search(r"^      fail-fast: false\s*$", block, re.M)
    assert re.search(r"^    name: python39 shard \$\{\{ matrix\.shard \}\} of 3\s*$", block, re.M)  # not a required check: its name is a shard's
    assert "python39" not in REQUIRED_CHECKS


def py39_repo(tmp_path, changed, list_text):
    """A small git repository (fictional modules and tests, the real selector copied in) whose branch changed `changed` since its base."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in ("select_tests.py", "test_dirs.py"):
        shutil.copy(REPO / "scripts" / name, repo / "scripts" / name)
    files = {
        "scripts/python39_tests.txt": list_text,
        "scripts/tests/test_runtime_python39.py": "def test_guard():\n    assert True\n",
        "scripts/tests/test_elsewhere.py": "import os\n",
        "runtime/alpha.py": "def a():\n    return 1\n",
        "runtime/tests/test_alpha.py": "import alpha\n",
        "runtime/tests/test_beta.py": "import os\n",
        "docs/readme.md": "docs\n",
    }
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    clean.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test"})

    def git(*args):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=clean, check=True, timeout=60).stdout.strip()

    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    for rel in changed:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        with open(repo / rel, "a") as handle:
            handle.write("\n# changed\n")  # a comment in every kind of file this fixture changes
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    return repo, base, clean


def run_py39_choose(tmp_path, changed, script=None, list_text="runtime/tests\nscripts/tests/test_runtime_python39.py\n"):
    """The shell of the step that chooses the python39 tests, as the workflow has it, on that repository: the lines it wrote to the file."""
    repo, base, clean = py39_repo(tmp_path, changed, list_text)
    block = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), "python39")
    path = tmp_path / "choose.sh"
    path.write_text(script if script is not None else step_script(block, PY39_CHOOSE))
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    done = subprocess.run(["bash", "-e", "-o", "pipefail", str(path)], cwd=repo, env={**clean, "BASE_SHA": base, "RUNNER_TEMP": str(temp)},
                          capture_output=True, text=True, timeout=120)
    return done, (temp / "py39.txt").read_text().splitlines() if (temp / "py39.txt").exists() else None


WHOLE_LIST = ["runtime/tests", "scripts/tests/test_runtime_python39.py"]  # the fictional list above, in its order
PY39_CASES = {  # what changed -> what runs (written by hand): selected = the test of the module and the guard; whole = the list as written
    "a module": (["runtime/alpha.py"], ["runtime/tests/test_alpha.py", "scripts/tests/test_runtime_python39.py"]),
    "a document": (["docs/readme.md"], ["scripts/tests/test_runtime_python39.py"]),
    "a test outside the list": (["scripts/tests/test_elsewhere.py"], ["scripts/tests/test_runtime_python39.py"]),
    "a workflow": ([".github/workflows/checks.yml"], WHOLE_LIST),
    "the list itself": (["scripts/python39_tests.txt"], WHOLE_LIST),
    "the selector": (["scripts/select_tests.py"], WHOLE_LIST),
    "a conftest in a folder": (["runtime/tests/conftest.py"], WHOLE_LIST),
    "the root conftest": (["conftest.py"], WHOLE_LIST),
    "pytest.ini": (["pytest.ini"], WHOLE_LIST),
    "pyproject.toml": (["pyproject.toml"], WHOLE_LIST),
}


def check_py39_cases(tmp_path, script=None):
    for i, (name, (changed, want)) in enumerate(PY39_CASES.items()):
        case = tmp_path / ("case%d" % i)
        case.mkdir()
        done, lines = run_py39_choose(case, changed, script)
        assert done.returncode == 0, (name, done.stderr)
        assert lines == want, (name, lines)


def test_the_python39_choose_step_selects_inside_the_list_and_runs_the_whole_list_when_what_decides_the_selection_changes(tmp_path):
    check_py39_cases(tmp_path)


def test_vacuity_a_choose_step_that_never_runs_the_whole_list_or_never_selects_is_caught_by_the_cases(tmp_path):
    block = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), "python39")
    real = step_script(block, PY39_CHOOSE)
    never_whole = re.sub(r"grep -Eq '[^']*'", "grep -Eq 'no-such-path-anywhere'", real)
    always_whole = re.sub(r"grep -Eq '[^']*'", "grep -Eq ''", real)
    for i, planted in enumerate((never_whole, always_whole)):
        assert planted != real
        (tmp_path / ("plant%d" % i)).mkdir()
        with pytest.raises(AssertionError):
            check_py39_cases(tmp_path / ("plant%d" % i), planted)


def test_the_python39_choose_step_fails_when_the_selector_does(tmp_path):
    done, lines = run_py39_choose(tmp_path, ["runtime/alpha.py"], list_text="# nothing but a comment\n")
    assert done.returncode != 0 and "--within" in done.stderr  # an empty list is a usage error of the selector, and the step does not hide it


def test_the_whole_python39_step_writes_the_list_without_its_comments_and_blank_lines(tmp_path):
    block = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), "python39")
    repo, _base, clean = py39_repo(tmp_path, ["docs/readme.md"], "# a comment\n\nruntime/tests\nscripts/tests/test_runtime_python39.py\n")
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    path = tmp_path / "whole.sh"
    path.write_text(step_script(block, PY39_WHOLE))
    done = subprocess.run(["bash", "-e", "-o", "pipefail", str(path)], cwd=repo, env={**clean, "RUNNER_TEMP": str(temp)}, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert (temp / "py39.txt").read_text().splitlines() == WHOLE_LIST


def test_the_nightly_is_daily_by_hand_or_by_its_label_and_never_writes():
    text = NIGHTLY.read_text(encoding="utf-8")
    head = text.split("\npermissions:", 1)[0]
    assert "schedule:" in head and "workflow_dispatch:" in head and "types: [labeled]" in head
    assert re.search(r'- cron: "\d{1,2} \d{1,2} \* \* \*"', head)
    assert nightly_problems(text) == []
    assert text.count("persist-credentials: false") == text.count("actions/checkout@") == 2


def test_no_nightly_job_is_named_like_a_required_check_and_no_run_line_holds_an_expression():
    text = NIGHTLY.read_text(encoding="utf-8")
    names = re.findall(r"^    name:\s*(.*?)\s*$", text, re.M)
    assert names and not [n for n in names if n in REQUIRED_CHECKS]
    assert [p for p in nightly_problems(text) if "required check" in p or "expression" in p] == []


def test_vacuity_a_nightly_with_a_write_permission_or_an_expression_in_a_run_line_is_caught():
    text = NIGHTLY.read_text(encoding="utf-8")
    assert nightly_problems(text) == []
    for old, new in (("contents: read", "contents: write"), ('--shard "$SHARD/3"', '--shard "${{ matrix.shard }}/3"'),
                     ("persist-credentials: false", "persist-credentials: true"), ("    name: nightly python39", "    name: tests")):
        planted = text.replace(old, new, 1)
        assert planted != text, old
        assert nightly_problems(planted), old

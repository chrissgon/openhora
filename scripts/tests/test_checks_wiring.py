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
def job_condition(name):
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
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


def step_condition(job, step_name):
    """The `if:` of the step of that job with that name (None when it has none)."""
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    lines = job_block(text, job).splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "- name: " + step_name)
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


def evaluate(expression, event_name, action=None, base_ref="", labels=(), label=None):
    if expression is None:
        return True  # a job without a condition runs
    py = re.sub(r"contains\(github\.event\.pull_request\.labels\.\*\.name,\s*'([^']+)'\)", lambda m: "(%r in labels)" % m.group(1), expression)
    py = py.replace("github.event_name", "event_name").replace("github.event.action", "action").replace("github.base_ref", "base_ref")
    py = py.replace("github.event.label.name", "label")
    py = py.replace("&&", " and ").replace("||", " or ")
    py = re.sub(r"!(?!=)", " not ", py)
    names = {"event_name": event_name, "action": action, "base_ref": base_ref, "labels": list(labels), "label": label}
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
}


WHOLE = "Scanner and provider tests, the whole suite"
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
    "a pull request into an integration branch": "selected", "another label just added": None, "another label added to a pull request into main": None,
}


def test_the_one_tests_job_runs_the_whole_list_on_the_four_events_of_the_end_of_a_delivery_and_the_selection_otherwise():
    """The required check of the main ruleset is `tests`: on a pull request into main it must run, and run every test folder."""
    got = modes(job_condition("tests"), step_condition("tests", WHOLE), step_condition("tests", SELECTED))
    assert got == WANTED_MODES
    assert step_condition("tests", CHOOSE) == step_condition("tests", SELECTED)  # the selector runs exactly when its targets are used
    text = job_block((REPO / ".github" / "workflows" / "checks.yml").read_text(), "tests")
    whole_step = text[text.index("- name: " + WHOLE):]
    assert "$(python3 scripts/test_dirs.py)" in whole_step and 'WB_FULL_FUZZ: "1"' in whole_step and "select_tests" not in whole_step
    selected_step = text[text.index("- name: " + SELECTED):text.index("- name: " + WHOLE)]
    assert "selected-tests.txt" in selected_step and "WB_FULL_FUZZ" not in selected_step
    assert not re.search(r"^  full-suite:\s*$", (REPO / ".github" / "workflows" / "checks.yml").read_text(), re.M)  # no second job to be the only gate


def test_planted_workflows_that_skip_tests_on_a_pull_request_into_main_are_caught_by_the_oracle():
    whole, selected = step_condition("tests", WHOLE), step_condition("tests", SELECTED)
    # the first design of this package: the job `tests` is skipped for a pull request into main (a skipped required check passes)
    skipped_into_main = "github.event.action != 'labeled' && github.base_ref != 'main'"
    assert modes(skipped_into_main, whole, selected) != WANTED_MODES
    # a whole-suite step that forgets the base: a pull request into main would get the selection
    forgets_base = "github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'full-suite')"
    with pytest.raises(AssertionError):  # a pull request into main would run neither step: the helper refuses it
        modes(job_condition("tests"), forgets_base, selected)
    # both steps true at once is refused by the helper itself
    with pytest.raises(AssertionError):
        modes(job_condition("tests"), "github.event_name == 'push' || github.event_name == 'pull_request'", "github.event_name == 'pull_request'")


def test_an_unrelated_label_starts_no_job_and_the_label_of_the_whole_suite_starts_the_checks_of_the_delivery():
    other = EVENTS["another label just added"]
    full = EVENTS["the label full-suite just added"]
    for name in ("validate", "python39", "changes", "tests"):
        assert evaluate(job_condition(name), **other) is False, name
    for name in ("validate", "python39", "changes", "tests"):
        assert evaluate(job_condition(name), **full) is True, name


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


PR = dict(EVENT="pull_request", ACTION="synchronize", BASE_REF="feature/x", FULL_LABEL="false")


def test_the_docker_and_go_jobs_run_when_their_paths_changed_and_in_the_cases_of_the_whole_suite(tmp_path):
    for i, (files, env, want) in enumerate([
        (["providers/messenger/whatsapp/bridge.go"], PR, {"container": "false", "converter": "false", "go": "true"}),
        (["providers/converter/Dockerfile"], PR, {"container": "false", "converter": "true", "go": "false"}),
        (["evals/container/Dockerfile"], PR, {"container": "true", "converter": "false", "go": "false"}),
        (["docs/decisions.md"], PR, {"container": "false", "converter": "false", "go": "false"}),
        (["docs/decisions.md"], {**PR, "BASE_REF": "main"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {**PR, "FULL_LABEL": "true"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {**PR, "ACTION": "labeled"}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {"EVENT": "push", "ACTION": "", "BASE_REF": "", "FULL_LABEL": ""}, {"container": "true", "converter": "true", "go": "true"}),
        (["docs/decisions.md"], {"EVENT": "workflow_dispatch", "ACTION": "", "BASE_REF": "", "FULL_LABEL": ""}, {"container": "true", "converter": "true", "go": "true"}),
    ]):
        case = tmp_path / ("case%d" % i)
        case.mkdir()
        assert run_changes(case, files, **env) == want, (files, env)


def test_the_triggers_of_the_workflow_include_the_label_event_and_the_manual_run():
    text = (REPO / ".github" / "workflows" / "checks.yml").read_text()
    head = text[:text.index("\npermissions:")]
    assert "workflow_dispatch:" in head and "types: [opened, synchronize, reopened, labeled]" in head and "branches: [main]" in head
    assert "github.event.action == 'labeled' && 'label' || 'code'" in text  # a label does not cancel the run of the last push


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

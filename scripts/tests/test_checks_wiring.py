"""Tests of the checks that keep other checks running: test-folder discovery, the paths the workflows
name, the folders the hook maps to tests, and the eval-cases preflight that scripts/validate.py runs.
Offline; every skill and file here is invented.

Run: uv run --with pytest pytest scripts/tests/test_checks_wiring.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

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


def test_every_path_a_workflow_names_exists():
    """The Python 3.9 job once listed five test files that had moved, and stayed red on main."""
    assert WORKFLOWS
    total = 0
    for workflow in WORKFLOWS:
        paths = named_paths(workflow.read_text())
        total += len(paths)
        missing = [p for p in paths if not (REPO / p).exists()]
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
    ("skills/core-demo/scripts/tool.py", "skills/core-demo/scripts/tests"),
    ("shared/scripts/rank.py", "shared/scripts/tests"), ("shared/scripts/copies.json", "shared/scripts/tests"),
    ("shared/scripts/tests/test_shared_rank.py", "shared/scripts/tests"),
    ("skills/core-demo/SKILL.md", None), ("docs/backlog.md", None), ("README.md", None),
]


def test_the_hook_maps_each_folder_to_the_tests_that_cover_it(tmp_path):
    """The hook's own `case` block, taken from the file and run on one path at a time."""
    hook = (REPO / ".githooks" / "pre-commit").read_text()
    start, end = hook.index('  case "$f" in'), hook.index("  esac\n") + len("  esac\n")
    block = hook[start:end].replace("*) continue ;;", '*) d="" ;;')
    script = tmp_path / "map.sh"
    script.write_text('set -euo pipefail\nf="$1"\n' + block + 'printf "%s" "$d"\n')
    for path, expected in HOOK_CASES:
        out = subprocess.run(["bash", str(script), path], capture_output=True, text=True,
                             env={"PATH": os.environ["PATH"]}, timeout=30)
        assert out.returncode == 0, out.stderr
        assert (out.stdout or None) == expected, path


def tree(tmp_path, cited):
    """A repository with the real runner and one skill whose case ships `shipped.md` and cites `cited`."""
    (tmp_path / "evals").mkdir()
    for name in ("eval_run.py", "execution.py", "eval_status.py", "grading-prompt.md"):
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

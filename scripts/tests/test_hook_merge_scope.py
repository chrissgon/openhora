"""The pre-commit hook's list of changed files on a merge commit (`staged()` in `.githooks/pre-commit`).

Offline. Each test builds a real git repository in a temporary folder (fictional file names), makes a real `git merge` and runs the text of
the hook's own `staged` function, cut out of the hook, in it; the list goes through the selector's `--direct` fast set.

Run: uv run --with pytest pytest scripts/tests/test_hook_merge_scope.py
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK = (REPO / ".githooks" / "pre-commit").read_text()
BASE_FILES = 50


def staged_function(text):
    return re.search(r"^staged\(\) \{.*?^\}\n|^staged\(\) \{[^\n]*\}\n", text, re.M | re.S).group(0)


def git(root, *args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, timeout=120)
    if check:
        assert done.returncode == 0, done.stderr
    return done


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_staged(root, function):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    # security-scan: allow shell-string -- the text is the hook's own function (or a planted copy of it), never input
    done = subprocess.run(["bash", "-c", function + "\nstaged"], cwd=str(root), capture_output=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    return sorted(name for name in done.stdout.decode().split("\0") if name)


def direct_set(root, listed):
    cmd = [sys.executable, str(REPO / "scripts" / "select_tests.py"), "--root", str(root), "--files", *listed, "--direct"]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return sorted(done.stdout.split())


def planted_merge(tmp_path):
    """A branch that changes two tests and, with the base, one more (a conflict); the base brings 50 new tests. The merge is not yet committed."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "a@example.test")
    git(root, "config", "user.name", "A")
    write(root, "scripts/tests/test_shared.py", "VALUE = 'start'\n")
    for guard in _guards():  # the selector prints a guard that exists
        write(root, guard, "import os\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    git(root, "checkout", "-q", "-b", "pkg")
    write(root, "scripts/tests/test_own_one.py", "A = 1\n")
    write(root, "scripts/tests/test_own_two.py", "A = 2\n")
    write(root, "scripts/tests/test_shared.py", "VALUE = 'branch'\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the branch's own change")
    git(root, "checkout", "-q", "main")
    for n in range(BASE_FILES):
        write(root, "scripts/tests/test_from_base_%02d.py" % n, "N = %d\n" % n)
    write(root, "scripts/tests/test_shared.py", "VALUE = 'base'\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "what the base brought")
    git(root, "checkout", "-q", "pkg")
    assert git(root, "merge", "--no-commit", "main", check=False).returncode == 1  # the conflict in test_shared.py
    write(root, "scripts/tests/test_shared.py", "VALUE = 'resolved'\n")
    git(root, "add", "scripts/tests/test_shared.py")
    assert (root / ".git" / "MERGE_HEAD").is_file()
    return root


OWN = ["scripts/tests/test_own_one.py", "scripts/tests/test_own_two.py", "scripts/tests/test_shared.py"]


def test_on_a_merge_commit_the_hook_lists_only_the_branchs_own_files_and_the_conflict_resolution(tmp_path):
    root = planted_merge(tmp_path)
    listed = run_staged(root, staged_function(HOOK))
    assert listed == OWN  # 3 files, not 53: the 50 the base brought are not this branch's change
    got = direct_set(root, listed)
    assert got == sorted(set(OWN) | set(_guards()))  # the two own tests, the resolved one and the guards, nothing the base brought


def _guards():
    spec = importlib.util.spec_from_file_location("select_tests_for_merge_scope", REPO / "scripts" / "select_tests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GUARDS


def test_vacuity_the_old_diff_against_head_brings_the_fifty_files_back(tmp_path):
    root = planted_merge(tmp_path)
    old = staged_function(HOOK).replace(" MERGE_HEAD\n", "\n").replace("git rev-parse -q --verify MERGE_HEAD", "false")
    assert old != staged_function(HOOK)
    listed = run_staged(root, old)
    assert len([f for f in listed if "test_from_base_" in f]) == BASE_FILES
    got = direct_set(root, listed)
    assert len([t for t in got if "test_from_base_" in t]) == BASE_FILES  # the old fast set would run the 50 tests the base brought
    assert len(got) == BASE_FILES + 1 + len(_guards())  # and the resolved file, and the guards; the branch's two own tests are in HEAD, so absent


def test_without_merge_head_the_staged_files_are_listed_as_before(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "a@example.test")
    git(root, "config", "user.name", "A")
    write(root, "docs/a.md", "a\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "start")
    write(root, "docs/a.md", "b\n")
    write(root, "scripts/tests/test_new.py", "A = 1\n")
    git(root, "add", "-A")
    assert not (root / ".git" / "MERGE_HEAD").exists()
    assert run_staged(root, staged_function(HOOK)) == ["docs/a.md", "scripts/tests/test_new.py"]


def test_the_hook_keeps_the_fast_set_and_the_guards_on_a_merge():
    code = "\n".join(l for l in HOOK.splitlines() if not l.lstrip().startswith("#"))
    assert "git diff --cached --name-only -z --no-renames --diff-filter=ACMRDT MERGE_HEAD" in code
    assert "select_tests.py --files-from - --direct" in code

"""Tests of `inventory --write --commit <ref>` (T33): the snapshot names the commit it is told, accepted only when skills/
and evals/ there are those of the working tree, so that a snapshot made on a branch can name a commit that exists on the
branch it lands on after a squash merge. Real git repositories in a temporary folder; no model is called.

Run: uv run --with pytest pytest evals/tests/test_inventory_stamp.py
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location("eval_status_inventory_stamp", REPO / "evals" / "eval_status.py")
es = importlib.util.module_from_spec(spec)
spec.loader.exec_module(es)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}
INVENTORY = "# Inventory\n\n" + es.BEGIN + "\nold\n" + es.END + "\n"
ENTRY = {"aliases": [], "adapter": "h", "pass_env": [], "route": None, "provider_pin": None, "upstream_models": ["x"],
         "price_source": "https://example.test/price", "run_token_budget": 1000}


def git(folder, *args, check=True):
    return subprocess.run(["git", "-c", "init.defaultBranch=main", "-c", "user.name=Test", "-c", "user.email=test@mail.example",
                           "-c", "commit.gpgsign=false", *args], check=check, cwd=folder, env=ENV, capture_output=True, text=True)


def files(root):
    for name in ("core-demo", "eng-other"):
        skill = root / "skills" / name
        (skill / "evals").mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"# {name}\n")
        (skill / "evals" / "evals.json").write_text(json.dumps({"evals": [
            {"id": 1, "prompt": "p", "assertions": ["a"]}, {"id": 2, "prompt": "q", "assertions": ["a"]}]}))
    (root / "docs").mkdir()
    (root / "docs" / "inventory.md").write_text(INVENTORY)
    (root / "evals").mkdir(exist_ok=True)
    (root / "evals" / "eval-gate.json").write_text(json.dumps({
        "grader": "s-model", "threshold": 0.8, "tolerance": 0, "lab_models": ["s-model"], "measurement_version": 2,
        "measurement_floor": 2, "measurement_sha256": "0" * 64, "models": {"s-model": ENTRY}}))


@pytest.fixture
def root(tmp_path):
    folder = tmp_path / "repo"
    folder.mkdir()
    files(folder)
    git(folder, "init")
    git(folder, "add", "-A")
    git(folder, "commit", "-m", "A")
    return folder


def short(root, ref):
    return git(root, "rev-parse", "--short=12", ref).stdout.strip()


def inventory(root):
    return (root / "docs" / "inventory.md").read_bytes()


def stamp_of(root):
    text = (root / "docs" / "inventory.md").read_text()
    assert es.STAMP_RE.search(text)
    return re.search(r"Generated at commit `([0-9a-f]+)`", text).group(1)


def write(root, *extra):
    return es.main(["inventory", "--write", *extra], root=str(root))


def refuses(root, code, *argv):
    before = inventory(root)
    with pytest.raises(SystemExit) as stopped:
        es.main(list(argv), root=str(root))
    assert stopped.value.code == code
    assert inventory(root) == before


def work_branch(root):
    git(root, "checkout", "-b", "work")
    (root / "docs" / "notes.md").write_text("notes\n")
    git(root, "add", "-A")
    git(root, "commit", "-m", "B")


def test_commit_stamps_the_named_commit_in_place_of_head(root):
    a = short(root, "main")
    work_branch(root)
    assert write(root, "--commit", "main") == 0
    assert stamp_of(root) == a != short(root, "HEAD")


def test_without_commit_the_stamp_is_head(root):
    work_branch(root)
    assert write(root) == 0
    assert stamp_of(root) == short(root, "HEAD")


def test_a_snapshot_stamped_with_the_target_head_names_a_commit_that_exists_after_a_squash_merge(root):
    work_branch(root)
    assert write(root, "--commit", "main") == 0
    own_head = short(root, "HEAD")
    git(root, "add", "-A")
    git(root, "commit", "-m", "snapshot")
    git(root, "checkout", "main")
    git(root, "merge", "--squash", "work")
    git(root, "commit", "-m", "squash")
    stamp = stamp_of(root)
    assert git(root, "merge-base", "--is-ancestor", stamp, "main", check=False).returncode == 0
    # The contrast: a stamp of the branch's own head names a commit the squash dropped.
    assert git(root, "merge-base", "--is-ancestor", own_head, "main", check=False).returncode == 1


def test_a_changed_input_at_a_later_commit_is_refused_and_nothing_is_written(root, capfd):
    git(root, "checkout", "-b", "work")
    path = root / "skills" / "core-demo" / "evals" / "evals.json"
    path.write_text(json.dumps({"evals": [{"id": 1, "prompt": "changed", "assertions": ["a"]}]}))
    git(root, "add", "-A")
    git(root, "commit", "-m", "C")
    refuses(root, 1, "inventory", "--write", "--commit", "main")
    assert "skills/core-demo/evals/evals.json" in capfd.readouterr().err


def test_an_untracked_input_is_refused(root):
    path = root / "skills" / "core-demo" / "evals" / "evidence" / "lab-x.jsonl"
    path.parent.mkdir()
    path.write_text("{}\n")
    refuses(root, 1, "inventory", "--write", "--commit", "main")


def test_a_staged_only_change_under_evals_is_refused(root):
    gate = root / "evals" / "eval-gate.json"
    gate.write_text(gate.read_text().replace('"threshold": 0.8', '"threshold": 0.7'))
    git(root, "add", "evals/eval-gate.json")
    refuses(root, 1, "inventory", "--write", "--commit", "main")


@pytest.mark.parametrize("argv", [
    ["inventory", "--write", "--commit", "no-such-ref"],
    ["inventory", "--write", "--commit", "-x"],
    ["inventory", "--check", "--commit", "main"],
    ["status", "--commit", "main"],
])
def test_a_bad_commit_option_is_refused_with_exit_2(root, argv):
    refuses(root, 2, *argv)


def test_a_folder_that_is_not_a_git_checkout_is_refused(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    files(folder)
    refuses(folder, 2, "inventory", "--write", "--commit", "main")

"""Tests of the project's protected paths, checked on the change set (runtime/changeset.py, runtime/project_config.py):
the paths that control the agent may not be in what a run sends back (decision D16; limit L20 for the measurement
files). Offline: temporary repositories made with the local git and the stand-in tree; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_protected_paths.py
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
changeset = st.load("changeset")
project_config = st.load("project_config")
workcopy = st.load("workcopy")

GIT = ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
CHECKS = {"readable": lab.readable, "scan": workcopy.scan, "settings": lab.carries_settings}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def git(folder, *args) -> str:
    return subprocess.run(GIT + ["-C", str(folder), *args], check=True, capture_output=True, text=True).stdout


def copy_of(tmp_path, files: dict) -> tuple:
    run_dir = tmp_path / "run"
    cwd = run_dir / "cwd"
    for rel, text in files.items():
        (cwd / rel).parent.mkdir(parents=True, exist_ok=True)
        (cwd / rel).write_text(text)
    git(cwd, "init", "-q")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", "fixture")
    return run_dir, git(cwd, "rev-parse", "HEAD").strip()


FILES = {"AGENTS.md": "# Rules\n", "evals/measure.py": "x = 1\n", "scripts/install.sh": "echo 1\n",
         "adapters/demo/run-prompt.sh": "echo run\n", "adapters/demo/install.sh": "echo install\n"}


def test_a_change_to_a_protected_path_blocks_the_change_set_and_names_the_path(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, FILES)
    (run_dir / "cwd" / "AGENTS.md").write_text("# Rules, loosened\n")
    (run_dir / "cwd" / "scripts" / "install.sh").write_text("echo 2\n")
    made = changeset.compute(str(run_dir), base, list(FILES), {}, CHECKS, protected=["AGENTS.md"])
    assert made["refused"] == [{"path": "AGENTS.md", "reason": "protected path"}] and made["blocked"] is True
    assert [f["path"] for f in made["files"]] == ["scripts/install.sh"]


def test_a_created_or_removed_protected_path_blocks_it_too(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, FILES)
    (run_dir / "cwd" / "evals" / "measure.py").unlink()
    (run_dir / "cwd" / "evals" / "extra.json").write_text("{}\n")
    made = changeset.compute(str(run_dir), base, list(FILES), {}, CHECKS, protected=["evals/"])
    assert {r["path"]: r["reason"] for r in made["refused"]} == {"evals/extra.json": "protected path",
                                                                 "evals/measure.py": "protected path"}
    assert made["blocked"] is True and made["removed"] == []


def test_a_folder_entry_protects_everything_under_it_and_a_star_crosses_folders():
    assert changeset.matches("evals/container/proxy/allow.txt", ["evals/"])
    assert not changeset.matches("evalsx/a.py", ["evals/"]) and not changeset.matches("evals", ["evals/"])
    assert changeset.matches("adapters/demo/run-prompt.sh", ["adapters/*/run-prompt.sh"])
    assert changeset.matches("adapters/demo/deep/run-prompt.sh", ["adapters/*/run-prompt.sh"])  # * crosses /
    assert not changeset.matches("adapters/demo/install.sh", ["adapters/*/run-prompt.sh"])
    assert changeset.matches("skills/a/evals/evals.json", ["skills/*/evals/*"])
    assert not changeset.matches("agents.md", ["AGENTS.md"])  # case-sensitive
    assert not changeset.matches("AGENTS.md", [])


def test_protected_paths_are_checked_again_with_the_accepted_configuration_before_the_commit(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, FILES)
    (run_dir / "cwd" / "adapters" / "demo" / "install.sh").write_text("echo carried\n")
    made = changeset.compute(str(run_dir), base, list(FILES), {}, CHECKS, protected=[])
    assert made["blocked"] is False
    facts = {"versioned": ["adapters/demo/install.sh"]}
    changeset.verify_for_commit(made, facts, [])
    with pytest.raises(changeset.ChangesetError) as refused:
        changeset.verify_for_commit(made, facts, ["adapters/"])  # the list was widened after the run
    assert refused.value.kind == "protected" and "adapters/demo/install.sh" in refused.value.reason


def test_a_protected_paths_value_that_is_not_a_list_of_texts_is_a_configuration_error(tree):
    config = tree["project"] / "docs" / "workbench" / "runtime.json"
    data = json.loads(config.read_text())
    for bad in ("evals/", ["evals/", ""], ["evals/", 1], {"evals/": True}):
        config.write_text(json.dumps({**data, "protected_paths": bad}))
        with pytest.raises(project_config.ConfigError, match="protected_paths"):
            project_config.load(str(tree["project"]))
    config.write_text(json.dumps({**data, "protected_paths": ["evals/", "AGENTS.md"]}))
    assert project_config.load(str(tree["project"]))["protected_paths"] == ["evals/", "AGENTS.md"]
    config.write_text(json.dumps(data))
    assert project_config.load(str(tree["project"]))["protected_paths"] == []


def test_a_protected_path_still_enters_the_copy(tree):
    project = tree["project"]
    (project / "src").mkdir()
    (project / "src" / "app.py").write_text("v1\n")
    (project / ".gitignore").write_text(".workbench-local/\n")
    config = project / "docs" / "workbench" / "runtime.json"
    config.write_text(json.dumps({**json.loads(config.read_text()), "protected_paths": ["src/"]}))
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    (tree["adapter"] / "code.sh").write_text("cat src/app.py > seen.txt\necho v2 > src/app.py\n")
    ops.request(path, "Change the app.", "code-demo")
    out = ops.run_next(path)
    assert (Path(out["run_dir"]) / "cwd" / "seen.txt").read_text() == "v1\n"  # the run read the protected file
    made = ops.pending(path, out["pending_id"])["payload"]["changeset"]
    assert made["blocked"] is True and made["refused"] == [{"path": "src/app.py", "reason": "protected path"}]
    assert (project / "src" / "app.py").read_text() == "v1\n"
    with pytest.raises(ops.OpsError, match="blocked"):
        ops.release(path, out["pending_id"])

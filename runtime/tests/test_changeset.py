"""Tests of runtime/changeset.py and of the change set in runtime/ops.py: code comes back as a change set (limit L9),
and a working document never enters a commit (limit L11). Offline: temporary repositories made with the local git,
the lab's host executor and the stand-in adapter of runtime/tests/standin_tree.py; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_changeset.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
changeset = st.load("changeset")
path_rule = st.load("path_rule")
workcopy = st.load("workcopy")

GIT = ["git", "-c", "user.name=Demo", "-c", "user.email=demo@example.test", "-c", "commit.gpgsign=false"]
CHECKS = {"readable": lab.readable, "scan": workcopy.scan, "settings": lab.carries_settings}


def token() -> str:
    return "AKIA" + "Q" * 16  # a text in a credential's format, built at run time


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    return built


def git(folder, *args) -> str:
    return subprocess.run(GIT + ["-C", str(folder), *args], check=True, capture_output=True, text=True).stdout


def write(folder: Path, files: dict) -> None:
    for rel, text in files.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)


def copy_of(tmp_path, files: dict, name="run") -> tuple:
    """A run folder whose cwd/ is a repository with one base commit of these files: (run_dir, base commit)."""
    run_dir = tmp_path / name
    cwd = run_dir / "cwd"
    cwd.mkdir(parents=True)
    write(cwd, files)
    git(cwd, "init", "-q")
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "--allow-empty", "-m", "fixture")
    return run_dir, git(cwd, "rev-parse", "HEAD").strip()


def compute(run_dir, base, tracked=(), facts=None):
    return changeset.compute(str(run_dir), base, list(tracked), facts or {}, CHECKS)


def test_limit_09_code_comes_back_as_a_change_set_with_created_changed_and_removed_paths_and_the_executable_bit(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"tools/install.sh": "echo 1\n", "app/keep.py": "x = 1\n", "app/old.py": "y\n"})
    cwd = run_dir / "cwd"
    (cwd / "tools" / "install.sh").write_text("echo 2\n")
    os.chmod(cwd / "tools" / "install.sh", 0o755)
    os.chmod(cwd / "app" / "keep.py", 0o755)
    (cwd / "app" / "old.py").unlink()
    write(cwd, {"app/new.py": "z = 3\n"})
    made = compute(run_dir, base, ["tools/install.sh", "app/keep.py", "app/old.py"])
    by = {f["path"]: f for f in made["files"]}
    assert {p: (f["change"], f["executable"]) for p, f in by.items()} == {
        "app/keep.py": ("mode", True), "app/new.py": ("created", False), "tools/install.sh": ("changed", True)}
    assert by["app/new.py"]["sha256"] == __import__("hashlib").sha256(b"z = 3\n").hexdigest() and by["app/new.py"]["bytes"] == 6
    assert made["removed"] == ["app/old.py"] and made["refused"] == [] and made["blocked"] is False
    assert made["sha256"] == changeset.canonical_sha256(made["files"], made["removed"])
    stored = changeset.store(str(run_dir), made)
    assert json.loads(Path(stored).read_text())["sha256"] == made["sha256"]
    assert (run_dir / "changeset" / "files" / "tools" / "install.sh").read_text() == "echo 2\n"


def test_the_change_set_is_the_difference_from_the_base_commit_even_when_the_run_committed_or_staged(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"a.py": "1\n", "b.py": "1\n"})
    cwd = run_dir / "cwd"
    write(cwd, {"a.py": "2\n"})
    git(cwd, "commit", "-q", "-am", "the run's own commit")
    write(cwd, {"b.py": "2\n", "c.py": "3\n"})
    git(cwd, "add", "b.py")
    made = compute(run_dir, base, ["a.py", "b.py"])
    assert [(f["path"], f["change"]) for f in made["files"]] == [("a.py", "changed"), ("b.py", "changed"), ("c.py", "created")]


def test_an_ignored_file_is_not_in_the_change_set_and_a_tracked_file_an_ignore_rule_matches_still_is(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {".gitignore": "*.log\n", "app.py": "1\n"})
    cwd = run_dir / "cwd"
    write(cwd, {"kept.log": "old\n"})
    git(cwd, "add", "-f", "kept.log")
    git(cwd, "commit", "-q", "-m", "tracked log")
    base = git(cwd, "rev-parse", "HEAD").strip()
    write(cwd, {"kept.log": "new\n", "noise.log": "x\n", "app.py": "2\n"})
    made = compute(run_dir, base, [".gitignore", "app.py", "kept.log"])
    assert [f["path"] for f in made["files"]] == ["app.py", "kept.log"]


def test_limit_11_a_working_document_never_enters_a_commit(tree, tmp_path):
    files = {".gitignore": "docs/business/\n.workbench-local/\n", "app.py": "1\n"}
    run_dir, base = copy_of(tmp_path, files)
    cwd = run_dir / "cwd"
    write(cwd, {"docs/business/market.md": "# Market\n", "app.py": "2\n"})
    git(cwd, "add", "-f", "docs/business/market.md")  # the run forces it into its own index
    made = compute(run_dir, base, list(files))
    assert [f["path"] for f in made["files"]] == ["app.py"] and "docs/business/market.md" not in made["versioned"]
    project = tmp_path / "project-repo"
    project.mkdir()
    write(project, files)
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")
    edited = dict(made, files=made["files"] + [{"path": "docs/business/market.md", "change": "created",
                                                 "sha256": "0" * 64, "bytes": 9, "executable": False}])
    paths = [f["path"] for f in edited["files"]]
    facts = {"versioned": changeset.versioned_in(str(project), paths)}
    assert facts["versioned"] == ["app.py"]
    with pytest.raises(changeset.ChangesetError) as refused:
        changeset.verify_for_commit(edited, facts, [])
    assert refused.value.kind == "working-document" and "docs/business/market.md" in refused.value.reason
    changeset.verify_for_commit(made, {"versioned": changeset.versioned_in(str(project), ["app.py"])}, [])


def test_a_docs_folder_the_project_versions_travels_in_the_change_set(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {".gitignore": ".workbench-local/\n", "docs/guide.md": "# Guide\n"})
    cwd = run_dir / "cwd"
    write(cwd, {"docs/engineering/plans/carry.md": "# Plan\n", "docs/guide.md": "# Guide, longer\n"})
    made = compute(run_dir, base, [".gitignore", "docs/guide.md"])
    assert [(f["path"], f["change"]) for f in made["files"]] == [("docs/engineering/plans/carry.md", "created"),
                                                                  ("docs/guide.md", "changed")]
    result = {"cwd": str(cwd), "staged": [], "changes": {"created": ["docs/engineering/plans/carry.md"],
                                                         "modified": ["docs/guide.md"], "deleted": []}}
    project = tmp_path / "elsewhere"
    (project / "docs").mkdir(parents=True)
    returned, kept, _ = workcopy.returning(str(project), result, {}, None, "demo-code", versioned=made["versioned"])
    assert returned == [] and kept == []  # never a loose document: it travels in the change set
    assert not (project / "docs" / "engineering").exists()


def test_a_link_a_submodule_or_a_path_that_leaves_the_copy_blocks_the_change_set(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"app.py": "1\n"})
    cwd = run_dir / "cwd"
    os.symlink("app.py", cwd / "alias.py")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x\n")
    os.symlink(outside, cwd / "out")
    sub = cwd / "vendor"
    sub.mkdir()
    write(sub, {"lib.py": "1\n"})
    git(sub, "init", "-q")
    git(sub, "add", "-A")
    git(sub, "commit", "-q", "-m", "inner")
    write(cwd, {"app.py": "2\n"})
    made = compute(run_dir, base, ["app.py"])
    reasons = {r["path"]: r["reason"] for r in made["refused"]}
    assert reasons == {"alias.py": "not a regular file inside the copy", "out": "not a regular file inside the copy",
                       "vendor": "not a regular file inside the copy"}
    assert made["blocked"] is True and [f["path"] for f in made["files"]] == ["app.py"]


def test_a_path_the_code_provider_would_refuse_or_a_set_over_its_bounds_blocks_the_change_set(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"app.py": "1\n"})
    cwd = run_dir / "cwd"
    write(cwd, {"notes/a b.txt": "x\n", "-dash.txt": "x\n"})
    (cwd / "big.bin").write_bytes(b"0" * (changeset.LIMITS["file_bytes"] + 1))
    write(cwd, {".h/settings.json": "{}\n"})
    made = compute(run_dir, base, ["app.py"])
    reasons = {r["path"]: r["reason"] for r in made["refused"]}
    assert reasons == {"notes/a b.txt": "a path the code provider does not take",
                       "-dash.txt": "a path the code provider does not take",
                       "big.bin": "over the code provider's size limit", ".h/settings.json": "a tool's settings"}
    many_dir, many_base = copy_of(tmp_path, {"app.py": "1\n"}, name="many")
    write(many_dir / "cwd", {f"gen/f{n}.py": f"{n}\n" for n in range(changeset.LIMITS["paths"] + 1)})
    many = compute(many_dir, many_base, ["app.py"])
    assert many["blocked"] and many["refused"] == [{"path": "", "reason": "more paths than one commit of the code provider takes"}]


def test_a_credential_format_in_a_changed_file_blocks_the_change_set(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"config.py": "KEY = None\n"})
    write(run_dir / "cwd", {"config.py": f"KEY = '{token()}'\n"})
    made = compute(run_dir, base, ["config.py"])
    assert made["refused"] == [{"path": "config.py", "reason": "credential format"}] and made["blocked"]
    assert made["files"] == []


def test_a_stored_change_set_whose_file_was_edited_is_refused_as_tampered(tree, tmp_path):
    run_dir, base = copy_of(tmp_path, {"app.py": "1\n"})
    write(run_dir / "cwd", {"app.py": "2\n"})
    changeset.store(str(run_dir), compute(run_dir, base, ["app.py"]))
    assert changeset.load(str(run_dir))["files"][0]["path"] == "app.py"
    (run_dir / "changeset" / "files" / "app.py").write_text("3\n")
    with pytest.raises(changeset.ChangesetError) as refused:
        changeset.load(str(run_dir))
    assert refused.value.kind == "tampered"
    assert changeset.load(str(tmp_path / "no-such-run")) is None


def test_applying_a_change_set_to_a_fresh_copy_and_computing_again_gives_the_same_hash(tree, tmp_path):
    files = {"tools/run.sh": "echo 1\n", "app/old.py": "y\n", "app/main.py": "x\n"}
    run_dir, base = copy_of(tmp_path, files)
    cwd = run_dir / "cwd"
    write(cwd, {"tools/run.sh": "echo 2\n", "app/new.py": "z\n"})
    os.chmod(cwd / "tools" / "run.sh", 0o755)
    (cwd / "app" / "old.py").unlink()
    first = compute(run_dir, base, list(files))
    changeset.store(str(run_dir), first)
    fresh_dir, fresh_base = copy_of(tmp_path, files, name="fresh")
    changeset.apply(changeset.load(str(run_dir)), str(fresh_dir / "cwd"))
    again = compute(fresh_dir, fresh_base, list(files))
    assert again["sha256"] == first["sha256"] and again["files"] == first["files"]


def git_project(tree, files=None) -> str:
    project = tree["project"]
    write(project, files or {"src/app.py": "v1\n", "src/old.py": "old\n"})
    (project / ".gitignore").write_text(".workbench-local/\n")
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "start")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    return path


def code(tree, script: str) -> None:
    (tree["adapter"] / "code.sh").write_text(script)


def test_the_next_code_task_of_a_request_starts_from_the_newest_unblocked_change_set(tree):
    path = git_project(tree)
    code(tree, 'case "$1" in\n 1) echo v2 > src/app.py ;;\n 2) cat src/app.py > seen-2.txt; echo "KEY=' + token()
               + '" > leak.txt ;;\n 3) cat src/app.py > seen-3.txt; [ -f leak.txt ] && echo leak >> seen-3.txt; echo v3 >> src/app.py ;;\nesac\n')
    ops.request(path, "Change the app.", "code-demo")
    first = ops.run_next(path)
    assert first["status"] == "ok" and ops.pending(path, first["pending_id"])["payload"]["changeset"]["files"] == 1
    ops.release(path, first["pending_id"])
    second = ops.run_next(path)
    made = ops.pending(path, second["pending_id"])["payload"]["changeset"]
    assert made["blocked"] is True and made["refused"] == [{"path": "leak.txt", "reason": "credential format"}]
    assert (Path(second["run_dir"]) / "cwd" / "seen-2.txt").read_text() == "v2\n"
    with pytest.raises(ops.OpsError, match="blocked"):
        ops.release(path, second["pending_id"])
    ops.answer(path, second["pending_id"], "Do not write the key.")
    third = ops.run_next(path)
    assert (Path(third["run_dir"]) / "cwd" / "seen-3.txt").read_text() == "v2\n"  # not from the blocked set
    final = changeset.load(third["run_dir"])
    assert {f["path"] for f in final["files"]} == {"src/app.py", "seen-3.txt"}  # nothing of the blocked set
    assert (Path(final["dir"]) / "files" / "src" / "app.py").read_text() == "v2\nv3\n"


def test_a_versioned_file_is_never_written_into_the_project_and_nothing_is_deleted_there(tree):
    path = git_project(tree)
    code(tree, "echo v2 > src/app.py\nrm src/old.py\necho new > src/new.py\n")
    ops.request(path, "Change the app.", "code-demo")
    out = ops.run_next(path)
    assert out["status"] == "ok" and not [r for r in out["returned"] if r["path"].startswith("src/")]
    project = tree["project"]
    assert (project / "src" / "app.py").read_text() == "v1\n" and (project / "src" / "old.py").is_file()
    assert not (project / "src" / "new.py").exists()
    item = ops.pending(path, out["pending_id"])
    assert item["payload"]["changeset"]["removed"] == 1 and "- removed: src/old.py" in item["body"]
    assert "- changed: src/app.py" in item["body"] and "- created: src/new.py" in item["body"]
    assert subprocess.run(["git", "-C", path, "status", "--porcelain"], capture_output=True, text=True).stdout == ""


def test_a_copy_without_a_usable_repository_gives_no_change_set_and_the_person_is_told(tree, tmp_path, monkeypatch):
    bare = tmp_path / "bare-run"
    (bare / "cwd").mkdir(parents=True)
    for base in (None, "a" * 40):
        with pytest.raises(changeset.ChangesetError) as refused:
            changeset.compute(str(bare), base, [], {}, CHECKS)
        assert refused.value.kind == "git"
    path = git_project(tree)
    real = lab.run_skill
    monkeypatch.setattr(lab, "run_skill", lambda *a, **k: {**real(*a, **k), "base_commit": None})
    ops.request(path, "Change the app.", "code-demo")
    out = ops.run_next(path)
    item = ops.pending(path, out["pending_id"])
    assert "The change set could not be computed" in item["body"]
    assert item["payload"]["changeset"]["error"].startswith("the change set could not be computed")
    assert not (Path(out["run_dir"]) / "changeset").exists()


def test_a_code_run_is_refused_while_tracked_files_of_the_project_have_uncommitted_changes(tree):
    path = git_project(tree)
    (tree["project"] / "src" / "app.py").write_text("edited by the person\n")
    ops.request(path, "Change the app.", "code-demo")
    out = ops.run_next(path)
    assert out["status"] == "failed" and out["failure"]["reason"].startswith("commit or stash the changes to tracked files")
    assert st.calls(tree["adapter"]) == [] and out["task_state"] == "failed"


def dirty_project(tree) -> str:
    """A repository whose tracked files carry an uncommitted change, as a project initialised by core-project-init
    always does (its AGENTS.md section and ignore lines are never committed by rule)."""
    path = git_project(tree, {"src/app.py": "v1\n", "notes.txt": "old\n"})
    (tree["project"] / "AGENTS.md").write_text("# Project\n\nThe workbench's section.\n")
    (tree["project"] / ".gitignore").write_text(".workbench-local/\ndocs/business/\n")
    return path


def test_a_document_task_runs_while_tracked_files_of_the_project_have_uncommitted_changes(tree):
    path = dirty_project(tree)
    ops.request(path, "Find the first market.", "demo")
    out = ops.run_next(path)
    assert out["status"] == "ok" and out["skill"] == "demo-asks" and out["ending"] == "question"
    assert out["entered"]["kind"] == "general" and st.calls(tree["adapter"]) == ["demo-asks 1"]
    assert "changeset" not in ops.pending(path, out["pending_id"])["payload"]
    assert not (Path(out["run_dir"]) / "changeset").exists()


def test_a_code_task_on_the_same_project_is_refused_with_the_clean_tree_message(tree):
    path = dirty_project(tree)
    ops.request(path, "Change the app.", "code-demo")
    out = ops.run_next(path)
    assert out["skill"] == "demo-code" and out["status"] == "failed" and out["failure"]["kind"] == "internal"
    assert out["failure"]["reason"] == "commit or stash the changes to tracked files first: a change set is made against a commit"
    assert st.calls(tree["adapter"]) == [] and out["task_state"] == "failed"


def test_a_code_task_runs_when_the_only_uncommitted_tracked_change_is_the_state_file(tree):
    path = git_project(tree)
    state = tree["project"] / "docs" / "workbench" / "state.md"
    assert git(tree["project"], "ls-files", "docs/workbench/state.md").strip() == "docs/workbench/state.md"
    state.write_text(state.read_text() + "\n")  # code writes an answer or an approval row there between runs
    code(tree, "echo v2 > src/app.py\n")
    ops.request(path, "Change the app.", "code-demo")
    out = ops.run_next(path)
    assert out["status"] == "ok" and ops.pending(path, out["pending_id"])["payload"]["changeset"]["files"] == 1


def test_a_document_task_never_makes_a_change_set_and_lists_a_tracked_file_it_changed_in_kept(tree):
    path = dirty_project(tree)
    ops.request(path, "Find the first market.", "demo")
    asked = ops.run_next(path)
    ops.answer(path, asked["pending_id"], "Clinics.")
    out = ops.run_next(path)  # writes docs/business/market.md and changes the tracked notes.txt
    assert out["status"] == "ok" and {"path": "docs/business/market.md", "class": "document"} in out["returned"]
    assert {"path": "notes.txt", "class": "other", "reason": workcopy.TRACKED_KEPT} in out["kept"]
    assert (tree["project"] / "notes.txt").read_text() == "old\n"  # a versioned file never comes back loose
    assert (tree["project"] / "AGENTS.md").read_text().endswith("The workbench's section.\n")  # the person's change stays
    assert not (Path(out["run_dir"]) / "changeset").exists()
    assert "changeset" not in ops.pending(path, out["pending_id"])["payload"]


def test_the_code_change_flow_runs_only_code_tasks():
    skill_meta = st.load("skill_meta")
    meta = lambda name: skill_meta.declared(str(st.REPO / "skills" / name))
    code = json.loads((st.REPO / "flows" / "code-change.json").read_text(encoding="utf-8"))
    assert code["tasks"] and all(ops.code_task(meta(t["skill"])) for t in code["tasks"])
    brand = json.loads((st.REPO / "flows" / "brand.json").read_text(encoding="utf-8"))
    assert brand["tasks"] and not any(ops.code_task(meta(t["skill"])) for t in brand["tasks"])


def test_the_bounds_repeated_here_are_the_code_providers():
    text = (st.REPO / "providers" / "vcs" / "github.py").read_text(encoding="utf-8")
    files = int(re.search(r"^MAX_FILES = (\d+)$", text, re.M).group(1))
    size = 1
    for factor in re.search(r"^MAX_FILE_BYTES = ([\d *]+)$", text, re.M).group(1).split("*"):
        size *= int(factor)
    assert changeset.LIMITS == {"paths": files, "file_bytes": size}
    assert changeset.PART.pattern == re.search(r'^PATH_SEGMENT_RE = re.compile\(r"(.+)"\)$', text, re.M).group(1)

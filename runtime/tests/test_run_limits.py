"""The limits of the task runtime that live in code, each with a test named after it (section B.2 of the
platform plan; contracts/runtime.md, "The limits"). Offline: the stand-in tree and adapter
(runtime/tests/standin_tree.py), and a project that is a git checkout built in the test's own folder.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_run_limits.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
workcopy = st.load("workcopy")
skill_meta = st.load("skill_meta")
project_config = st.load("project_config")
manifest = st.load("manifest")
path_rule = st.load("path_rule")
documents = st.load("documents")

# The numbers of the limits whose test is in this file; each has exactly one test below named test_limit_<two digits>_.
# The other limits' tests are named in contracts/runtime.md, "The limits", and checked by the last test of this file.
BUILT = (1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 18, 19)
CONTRACT = st.REPO / "contracts" / "runtime.md"

SECTION_ASSET = st.REPO / "skills" / "core-project-init" / "assets" / "agents-md-section.md"
GIT_ENV = {"GIT_AUTHOR_NAME": "Demo Person", "GIT_AUTHOR_EMAIL": "demo@example.com",
           "GIT_COMMITTER_NAME": "Demo Person", "GIT_COMMITTER_EMAIL": "demo@example.com",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, project_config.load(project)["sha256"])
    built["prepared"] = tmp_path / "prepared"
    return built


def git(project: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(project), *args], check=True, capture_output=True, timeout=60,
                   env={**os.environ, **GIT_ENV})


def write(project: Path, rel: str, text: str) -> Path:
    path = project / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def checkout(project: Path, tracked: dict) -> None:
    """Make the project a git checkout whose one commit holds every file it has now and the files of tracked."""
    for rel, text in tracked.items():
        write(project, rel, text)
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "the project")


def meta_of(tree, skill: str, **changes) -> dict:
    return {**skill_meta.declared(str(tree["tree"] / "skills" / skill)), **changes}


def entering(tree, skill: str, *, web: bool, cfg_changes=None, **meta_changes) -> dict:
    cfg = {**project_config.load(str(tree["project"])), **(cfg_changes or {})}
    return workcopy.entering(str(tree["project"]), meta_of(tree, skill, **meta_changes), web=web, cfg=cfg,
                             settings_names=lab.settings_names(), prepared_dir=str(tree["prepared"]))


def rels(entered: dict) -> list:
    return [rel for _, rel in entered["files"]]


def reasons(entered: dict) -> dict:
    return {item["path"]: item["reason"] for item in entered["left_out"]}


def copied(run_dir: str) -> list:
    """The files the stand-in adapter saw in the copy (its files.txt), without the staged skill."""
    text = (Path(run_dir) / "outputs" / "files.txt").read_text(encoding="utf-8")
    return [line[2:] for line in text.splitlines() if line.startswith("./") and not line.startswith("./.h/")]


def token() -> str:
    return "AKIA" + "Q" * 16  # a text in a credential's format, built at run time


def test_limit_01_every_run_starts_from_a_new_copy_with_the_skill_staged_again(tree, monkeypatch):
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    real = lab.run_skill

    def leaves_a_trace(*args, **kwargs):
        result = real(*args, **kwargs)
        cwd = Path(result["cwd"])
        (cwd / "stray.txt").write_text("left by the first run\n")
        staged = cwd / ".h" / "skills" / "demo-asks" / "SKILL.md"
        staged.write_text(staged.read_text() + "\nchanged by the first run\n")
        return result

    monkeypatch.setattr(lab, "run_skill", leaves_a_trace)
    first = ops.run_next(path)
    monkeypatch.setattr(lab, "run_skill", real)
    ops.answer(path, first["pending_id"], "Portugal.")
    second = ops.run_next(path)
    assert second["status"] == "ok" and second["run_dir"] != first["run_dir"]
    first_cwd, second_cwd = Path(first["run_dir"]) / "cwd", Path(second["run_dir"]) / "cwd"
    assert (first_cwd / "stray.txt").is_file() and "stray.txt" not in copied(second["run_dir"])
    assert not (second_cwd / "stray.txt").exists()
    staged = (second_cwd / ".h" / "skills" / "demo-asks" / "SKILL.md").read_text()
    assert staged == (tree["tree"] / "skills" / "demo-asks" / "SKILL.md").read_text()


def test_the_platform_references_a_skill_cites_are_staged_with_it_read_only_as_in_a_lab_run(tree, monkeypatch):
    """L1, the references the skill cites: a skill that cites the platforms' folder is given the reference of every
    platform (its data file too), staged beside it as the lab stages a case's platforms; a skill that does not
    cite it is given none; what a run does to them never comes back, by the path rule."""
    project, path = tree["project"], str(tree["project"])
    platforms = tree["tree"] / "shared" / "references" / "platforms"
    platforms.mkdir(parents=True)
    for name, text in (("demo-net.md", "# Demo net\n"), ("demo-net.json", "{}\n"), ("other-net.md", "# Other net\n"),
                       ("README.md", "# Platforms\n")):
        (platforms / name).write_text(text, encoding="utf-8")
    citing = tree["tree"] / "skills" / "demo-asks" / "SKILL.md"
    citing.write_text(citing.read_text(encoding="utf-8") + "\nRead `../../shared/references/platforms/<platform>.md`.\n",
                      encoding="utf-8")
    assert lab.platforms_cited(str(citing.parent)) == ["demo-net", "other-net"]
    assert lab.platforms_cited(str(tree["tree"] / "skills" / "demo-writes")) == []
    ops.request(path, "Tell me which market to go after first.", "demo")
    real, seen = lab.run_skill, {}

    def changes_a_reference(*args, **kwargs):
        result = real(*args, **kwargs)
        seen.update(result)
        (Path(result["cwd"]) / ".h" / "shared" / "references" / "platforms" / "demo-net.md").write_text("changed\n")
        return result

    monkeypatch.setattr(lab, "run_skill", changes_a_reference)
    out = ops.run_next(path)
    assert out["status"] == "ok"
    listed = (Path(out["run_dir"]) / "outputs" / "files.txt").read_text(encoding="utf-8").splitlines()
    staged_refs = {"./.h/shared/references/platforms/demo-net.md", "./.h/shared/references/platforms/demo-net.json",
                   "./.h/shared/references/platforms/other-net.md"}
    assert staged_refs <= set(listed)
    assert not any(line.endswith("/platforms/README.md") for line in listed)
    assert ".h/shared" in seen["staged"]
    for rel in sorted(staged_refs):
        assert st.load("path_rule").classify(rel[2:], {"staged": seen["staged"]}) == "ignored"
    assert all(not item["path"].startswith(".h/") for item in out["returned"] + out["kept"])
    assert not (project / ".h").exists() and not (project / "shared").exists()
    assert (platforms / "demo-net.md").read_text(encoding="utf-8") == "# Demo net\n"


def test_the_brand_skills_of_this_checkout_are_given_every_platform_reference_it_has():
    platforms = sorted(p.stem for p in (st.REPO / "shared" / "references" / "platforms").glob("*.md") if p.stem != "README")
    assert platforms
    for skill in ("brand-strategy", "brand-identity", "brand-profile"):
        assert lab.platforms_cited(str(st.REPO / "skills" / skill)) == platforms, skill
    assert lab.platforms_cited(str(st.REPO / "skills" / "biz-market-analysis")) == []


def test_limit_02_only_versioned_files_documents_and_declared_machine_files_enter_and_never_the_store_or_the_configuration(tree):
    project = tree["project"]
    checkout(project, {"src/app.py": "print('app')\n", ".workbench-local/other/notes.json": "{}\n"})
    write(project, "docs/business/notes.md", "# Notes\n")          # a document, not tracked
    write(project, "scratch.txt", "not tracked, outside docs\n")    # no other file outside git
    os.symlink(tree["db"], project / "docs" / "store-link.sqlite")
    entered = entering(tree, "demo-writes", web=False)
    assert entered["kind"] == "general"
    assert {"src/app.py", "docs/business/notes.md", "docs/workbench/state.md"} <= set(rels(entered))
    assert "scratch.txt" not in rels(entered)
    why = reasons(entered)
    assert why[".workbench-local/other/notes.json"] == "work data the skill does not declare"
    assert why["docs/workbench/runtime.json"] == "the runtime's configuration never enters a run"
    assert why["docs/store-link.sqlite"] == "the store and the runtime's data never enter a run"
    for rel in why:
        assert rel not in rels(entered)
    assert set(entered["base"]) == set(rels(entered))


def test_limit_03_a_run_with_the_web_receives_only_the_artifacts_its_skill_declares(tree):
    project = tree["project"]
    checkout(project, {"src/app.py": "print('app')\n", "docs/business/market.md": "# Market\n",
                       "docs/business/other.md": "# Other\n"})
    entered = entering(tree, "demo-writes", web=True)
    declared = meta_of(tree, "demo-writes")
    assert entered["kind"] == "artifacts"
    assert rels(entered) == ["docs/business/market.md", "docs/workbench/state.md"]
    assert all(skill_meta.matches(declared["inputs"] + declared["outputs"] + declared["updates"], rel)
               for rel in rels(entered))


def test_limit_04_a_tools_configuration_files_are_removed_at_any_depth(tree):
    project, path = tree["project"], str(tree["project"])
    settings = [name for name in lab.settings_names() if "." in name and not name.startswith(".")]
    folder = next(name for name in lab.settings_names() if name.startswith("."))
    checkout(project, {f"{folder}/settings.json": "{}\n", f"a/b/c/{folder}/deep.json": "{}\n",
                       f"a/b/c/{settings[0]}": "{}\n", "src/app.py": "print('app')\n"})
    ops.request(path, "Tell me which market to go after first.", "demo")
    out = ops.run_next(path)
    assert out["status"] == "ok" and out["failure"] is None
    why = {item["path"]: item["reason"] for item in out["left_out"]}
    for rel in (f"{folder}/settings.json", f"a/b/c/{folder}/deep.json", f"a/b/c/{settings[0]}"):
        assert why[rel] == "a tool's configuration"
        assert rel not in copied(out["run_dir"])
    assert "src/app.py" in copied(out["run_dir"])


def test_limit_05_agents_md_enters_only_when_the_skill_declares_it_and_without_the_two_lines_the_container_cannot_serve(tree):
    project, path = tree["project"], str(tree["project"])
    text = "# Project\n\nOur own rules.\n\n" + SECTION_ASSET.read_text(encoding="utf-8") + "\nA closing line.\n"
    (project / "AGENTS.md").write_text(text, encoding="utf-8")
    before = (project / "AGENTS.md").read_bytes()
    kept_lines = [line for line in text.splitlines()
                  if not re.sub(r"^\d+\.\s+", "", line).startswith(workcopy.REMOVED_OPENINGS)]
    assert len(kept_lines) == len(text.splitlines()) - 2
    # Declared (demo-asks declares AGENTS.md): the copy's file has neither opening and every other line.
    ops.request(path, "Tell me which market to go after first.", "demo")
    out = ops.run_next(path)
    assert out["entered"]["agents_md"] == "whole"
    in_copy = (Path(out["run_dir"]) / "cwd" / "AGENTS.md").read_text(encoding="utf-8")
    assert in_copy.splitlines() == kept_lines
    for opening in workcopy.REMOVED_OPENINGS:
        assert opening not in in_copy
    # Not declared (demo-writes does not declare it): it does not enter.
    assert "AGENTS.md" not in rels(entering(tree, "demo-writes", web=False))
    # Protected: only the section enters for a skill of a business area; the whole file for a code area.
    protected = {"protected_paths": ["AGENTS.md"]}
    section = entering(tree, "demo-asks", web=False, cfg_changes=protected)
    assert section["agents_md"] == "section"
    prepared = Path(dict((rel, src) for src, rel in section["files"])["AGENTS.md"]).read_text(encoding="utf-8")
    assert prepared.startswith(workcopy.SECTION_START) and "Our own rules." not in prepared
    assert workcopy.SECTION_END in prepared and "Skill check:" not in prepared
    whole = entering(tree, "demo-asks", web=False, cfg_changes=protected, area="engineering")
    assert whole["agents_md"] == "whole"
    # Protected and without a workbench section: nothing enters, and the reason says why.
    (project / "AGENTS.md").write_text("# Project\n\nOur own rules.\n", encoding="utf-8")
    none = entering(tree, "demo-asks", web=False, cfg_changes=protected)
    assert none["agents_md"] is None and reasons(none)["AGENTS.md"] == "protected, and it has no workbench section"
    (project / "AGENTS.md").write_bytes(before)
    assert (project / "AGENTS.md").read_bytes() == before


def test_limit_06_no_credential_enters_the_container(tree):
    project = tree["project"]
    checkout(project, {".env": "LOCAL_ONLY=1\n", "deploy.pem": "certificate\n",
                       "notes/handover.txt": f"the key is {token()}\n",
                       ".env.example": "API_KEY=<your key here>\nPASSWORD=<choose one>\n"})
    entered = entering(tree, "demo-writes", web=False)
    why = reasons(entered)
    assert why[".env"] == why["deploy.pem"] == "a credential file by its name"
    assert why["notes/handover.txt"].startswith("holds what looks like a credential (")
    assert ".env.example" in rels(entered)
    for rel in (".env", "deploy.pem", "notes/handover.txt"):
        assert rel not in rels(entered)
    assert token() not in repr(entered["left_out"])
    assert workcopy.credential_findings(f"one\nkey {token()}\ntwo") and workcopy.credential_findings("API_KEY=<x>\n") == []


def finished(tree, files: dict, *, created=(), modified=(), deleted=()) -> dict:
    """A completed run's result, made by hand: a copy folder holding files, and what the run did to it."""
    cwd = tree["prepared"].parent / "copy"
    for rel, text in files.items():
        write(cwd, rel, text)
    return {"cwd": str(cwd), "staged": [".h/skills/demo-writes"],
            "changes": {"created": sorted(created), "modified": sorted(modified), "deleted": sorted(deleted),
                        "unchanged": []}}


def base_of(tree, *rels) -> dict:
    out = {}
    for rel in rels:
        path = tree["project"] / rel
        out[rel] = workcopy._sha256(str(path)) if path.is_file() else None
    return out


def test_limit_07_the_destination_of_each_returned_file_comes_from_the_path_rule(tree):
    project = tree["project"]
    state = (project / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    left = {"docs/business/icp.md": "# Profile\n", "docs/business/icp.lint.json": "{}\n",
            ".workbench-local/notes/run.json": "{}\n", "docs/workbench/state.md": state + "- a decision\n",
            "src/app.py": "print('app')\n", "node_modules/x/index.js": "x\n"}
    created = [rel for rel in left if rel != "docs/workbench/state.md"]
    result = finished(tree, left, created=created, modified=["docs/workbench/state.md"])
    base = base_of(tree, *left)
    returned, kept, _ = workcopy.returning(str(project), result, base, state, "demo-writes")
    assert returned == [{"path": ".workbench-local/notes/run.json", "class": "machine"},
                        {"path": "docs/business/icp.lint.json", "class": "machine"},
                        {"path": "docs/business/icp.md", "class": "document"},
                        {"path": "docs/workbench/state.md", "class": "state"}]
    assert kept == [{"path": "src/app.py", "class": "other", "reason": "this class of path is not brought back yet"}]
    assert not (project / "src").exists() and not (project / "node_modules").exists()
    # The same document, bound to an approval by the skill's manifest, comes back as a machine file.
    known = {**manifest.load(str(tree["tree"]), "demo-writes")}
    known["documents"] = [{**d, "bound_to_approval": True} for d in known["documents"]]
    (project / "docs" / "business" / "icp.md").unlink()
    (project / "docs" / "workbench" / "state.md").write_text(state, encoding="utf-8")
    bound = manifest.bound_among(known, created)
    assert bound == ["docs/business/icp.md"]
    returned, _, _ = workcopy.returning(str(project), result, base, state, "demo-writes", bound=bound)
    assert {"path": "docs/business/icp.md", "class": "machine"} in returned


def test_limit_08_only_a_regular_file_with_its_real_path_inside_the_copy_comes_back(tree, tmp_path):
    project = tree["project"]
    outside = tmp_path / "outside-secret.md"
    outside.write_text("not the run's\n", encoding="utf-8")
    result = finished(tree, {"docs/business/real.md": "# Real\n"})
    cwd = Path(result["cwd"])
    os.symlink(outside, cwd / "docs" / "business" / "out.md")
    os.symlink(cwd / "docs" / "business" / "real.md", cwd / "docs" / "business" / "in.md")
    result["changes"]["created"] = ["docs/business/in.md", "docs/business/out.md"]
    returned, kept, _ = workcopy.returning(str(project), result, {}, None, "demo-writes")
    assert returned == []
    assert {item["path"]: item["reason"] for item in kept} == {
        "docs/business/in.md": "not a regular file inside the copy",
        "docs/business/out.md": "not a regular file inside the copy"}
    assert not (project / "docs" / "business" / "out.md").exists() and not (project / "docs" / "business" / "in.md").exists()


def test_limit_10_the_state_file_comes_back_through_the_merge_and_only_code_writes_what_is_the_persons(tree, monkeypatch):
    project, path = tree["project"], str(tree["project"])
    state_file = project / "docs" / "workbench" / "state.md"
    other_row = "| docs/business/icp.md | demo-writes | draft | 2026-10-04 |"
    separator = "|----------|-------------|--------|---------|"
    state_file.write_text(state_file.read_text().replace(separator, separator + "\n" + other_row), encoding="utf-8")
    ops.request(path, "Tell me which market to go after first.", "demo")
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "Portugal.")
    own_row = "| docs/business/market.md | demo-asks | draft | 2026-10-05 |"
    own_decision = "- 2026-10-05: Portugal first, from the answer. (demo-asks)"
    question = "- [ ] Which segment inside Portugal?"
    approved = other_row.replace("| draft |", "| approved |")
    forged = "- 2026-10-05: The market analysis is approved. (user)"
    approval = "| action | the analysis | ab12 | 2026-10-05 | | active |"
    real = lab.run_skill

    def rewrites_the_state_file(*args, **kwargs):
        result = real(*args, **kwargs)
        copy = Path(result["cwd"]) / "docs" / "workbench" / "state.md"
        text = copy.read_text().replace(other_row, approved + "\n" + own_row)
        text = text.replace("## Open questions\n", "## Open questions\n\n" + question + "\n")
        text = text.replace("|-------|------|--------------|----------|---------|--------|",
                            "|-------|------|--------------|----------|---------|--------|\n" + approval)
        copy.write_text(text + own_decision + "\n" + forged + "\n")
        return result

    monkeypatch.setattr(lab, "run_skill", rewrites_the_state_file)
    out = ops.run_next(path)
    lines = state_file.read_text().splitlines()
    for line in (own_row, own_decision, question, other_row):
        assert line in lines, line
    for line in (approved, forged, approval):
        assert line not in lines, line
    rejected = {item["line"] for item in out["state"]["rejected"]}
    assert {approved, forged, approval} <= rejected
    assert out["state"]["accepted"] >= 3
    assert {"path": "docs/workbench/state.md", "class": "state"} in out["returned"]
    assert ops.pending(path, out["pending_id"])["payload"]["state"] == out["state"]


def test_limit_12_what_comes_back_never_overwrites_what_changed_at_the_origin(tree):
    project = tree["project"]
    write(project, "docs/business/changed.md", "as the copy was made\n")
    write(project, "docs/business/same.md", "as the copy was made\n")
    base = base_of(tree, "docs/business/changed.md", "docs/business/same.md", "docs/business/new.md")
    write(project, "docs/business/changed.md", "edited by the person during the run\n")
    write(project, "docs/business/new.md", "created by the person during the run\n")
    left = {"docs/business/changed.md": "by the run\n", "docs/business/same.md": "by the run\n",
            "docs/business/new.md": "by the run\n"}
    result = finished(tree, left, created=["docs/business/new.md"],
                      modified=["docs/business/changed.md", "docs/business/same.md"])
    returned, kept, _ = workcopy.returning(str(project), result, base, None, "demo-writes")
    assert returned == [{"path": "docs/business/same.md", "class": "document"}]
    reason = "the project's file changed while the run was in progress"
    assert {item["path"]: item["reason"] for item in kept} == {"docs/business/changed.md": reason,
                                                               "docs/business/new.md": reason}
    assert (project / "docs" / "business" / "changed.md").read_text() == "edited by the person during the run\n"
    assert (project / "docs" / "business" / "new.md").read_text() == "created by the person during the run\n"
    assert (project / "docs" / "business" / "same.md").read_text() == "by the run\n"


def test_limit_14_everything_passes_the_credential_scan_before_it_leaves(tree, monkeypatch):
    project, path = tree["project"], str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "Portugal.")
    real = lab.run_skill

    def leaks(*args, **kwargs):
        result = real(*args, **kwargs)
        cwd = Path(result["cwd"])
        (cwd / "docs" / "business" / "market.md").write_text(f"# Market analysis\n\nkey: {token()}\n")
        result["response"] = f"- Analysis: docs/business/market.md\n- the key {token()} is in it\n- Next: demo-writes"
        return result

    monkeypatch.setattr(lab, "run_skill", leaks)
    out = ops.run_next(path)
    kept = {item["path"]: item["reason"] for item in out["kept"]}
    assert kept["docs/business/market.md"].startswith("holds what looks like a credential (")
    assert not (project / "docs" / "business" / "market.md").exists()
    assert token() in (Path(out["run_dir"]) / "cwd" / "docs" / "business" / "market.md").read_text()
    item = ops.pending(path, out["pending_id"])
    assert token() not in item["body"] and "<line removed: it held what looks like a credential (" in item["body"]
    assert item["body"].startswith("- Analysis: docs/business/market.md\n") and item["payload"]["body_masked"] == 1
    assert token() not in repr(out)


def test_limit_18_a_document_bound_to_an_approval_by_hash_is_a_machine_file(tree):
    project, rel = tree["project"], "docs/business/icp.md"
    result = finished(tree, {rel: "# Profile\n"}, created=[rel])
    assert path_rule.classify(rel) == "document" and documents.entry_for(str(tree["tree"]), rel) is not None
    # The skill's runtime manifest binds the document to an approval.
    known = manifest.load(str(tree["tree"]), "demo-writes")
    known["documents"] = [{**d, "bound_to_approval": True} for d in known["documents"]]
    Path(manifest.path(str(tree["tree"]), "demo-writes")).write_text(json.dumps(known), encoding="utf-8")
    bound = manifest.bound_among(manifest.load(str(tree["tree"]), "demo-writes"), [rel])
    assert bound == [rel]
    # It comes back as a machine file, stays one when the project versions it, and is never mirrored as a document.
    returned, kept, _ = workcopy.returning(str(project), result, base_of(tree, rel), None, "demo-writes", bound=bound)
    assert returned == [{"path": rel, "class": "machine"}] and kept == []
    assert path_rule.classify(rel, {"bound": bound, "versioned": [rel]}) == "machine"
    assert documents.entry_for(str(tree["tree"]), rel) is None


ROUTER_BRANCH = r'''
if [ "$skill" = core-orchestrator ]; then
  mkdir -p "$cwd/docs/business"; echo "# Tasks I created" > "$cwd/docs/business/tasks.md"
  printf 'Route: flow-demo (flow, pending)\nWhy: a market question\nI created the tasks market and profile for you.\n' > "$out/response.md"
  exit 0
fi
'''


def test_limit_19_the_planning_agent_creates_no_task_it_returns_the_route_and_code_builds_the_plan(tree, monkeypatch):
    router = st.load("router")
    st.skill(tree["tree"], router.ROUTER_SKILL, "docs/workbench/state.md", "")
    script = tree["adapter"] / "run-prompt.sh"
    text = st.ADAPTER.replace("for name in demo-asks demo-writes;", "for name in demo-asks demo-writes core-orchestrator;")
    script.write_text(text.replace('case "$skill" in', ROUTER_BRANCH + 'case "$skill" in', 1), encoding="utf-8")
    monkeypatch.setattr(ops.plan, "pack_skills", lambda cfg, root: ["core-orchestrator", "demo-asks", "demo-writes"])
    path = str(tree["project"])
    request = ops.request(path, "Tell me which market to go after first.")["request"]
    ctx = ops_core.context(path)
    count = lambda: ctx["conn"].execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    out = ops.route(path, request)
    # The planning agent's run returned a route and claimed tasks; no task exists, and nothing it wrote came back.
    assert out["kind"] == "plan" and count() == 1 and ops.status(path)["requests"][0]["tasks"] == []
    assert not (tree["project"] / "docs" / "business" / "tasks.md").exists()
    # The plan is built by code from the flow file the route names, and its tasks exist only once the person approves.
    flows = st.load("flow_files")
    payload = ops.pending(path, out["pending_id"])["payload"]
    flow = flows.load(payload["flow"], str(tree["tree"]))
    assert [t["key"] for t in payload["tasks"]] == [t["key"] for t in flow["tasks"]]
    approved = ops.approve(path, out["pending_id"], payload["plan_sha256"])
    assert [t["key"] for t in approved["tasks"]] == [t["key"] for t in flow["tasks"]] and count() == 1 + len(flow["tasks"])


def test_nothing_is_deleted_in_the_project_because_a_run_deleted_it(tree):
    project = tree["project"]
    write(project, "docs/business/old.md", "kept\n")
    result = finished(tree, {}, deleted=["docs/business/old.md"])
    returned, kept, _ = workcopy.returning(str(project), result, base_of(tree, "docs/business/old.md"), None, "demo-writes")
    assert returned == [] and kept == [{"path": "docs/business/old.md", "class": "document",
                                        "reason": "the run deleted it; the project's file is left as it is"}]
    assert (project / "docs" / "business" / "old.md").read_text() == "kept\n"


def test_a_run_row_keeps_the_number_of_values_the_lab_replaced(tree):
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    out = ops.run_next(path)
    ctx = ops_core.context(path)
    runs = ctx["store"].task_runs_list(ctx["conn"], out["ran"])
    assert runs[0]["redactions"] == 0


def test_the_two_lines_are_put_back_where_they_were():
    text = "# Project\n\nOur own rules.\n\n" + SECTION_ASSET.read_text(encoding="utf-8") + "\nA closing line.\n"
    run_text, removed = workcopy.agents_md_for_run(text, "whole")
    assert len(removed) == 2 and run_text != text
    assert workcopy.agents_md_restored(run_text, removed) == text


def limits_table() -> dict:
    """{number: (built by, test cell)} of the table of contracts/runtime.md, "The limits"."""
    section = CONTRACT.read_text(encoding="utf-8").split("## The limits", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"L\d+", cells[0]):
            rows[int(cells[0][1:])] = (cells[2], cells[3])
    return rows


def test_every_limit_built_so_far_has_a_test_named_after_it():
    names = [name for name in globals() if name.startswith("test_limit_")]
    for number in BUILT:
        assert len([n for n in names if n.startswith(f"test_limit_{number:02d}_")]) == 1, number
    assert len(names) == len(BUILT)
    # Every limit of the contract's table: the tests its row names exist where it says, and each limit that has a
    # test named after it is defined once in the runtime's and the store's tests, and every such test is one its row names
    # (L15 has two: the exact content, and a class of targets resolved from a recorded fact).
    rows = limits_table()
    assert sorted(rows) == list(range(1, 21))
    defined = {}
    for test_file in sorted((st.REPO / "runtime" / "tests").glob("test_*.py")) + sorted(
            (st.REPO / "providers" / "store" / "tests").glob("test_*.py")):
        for name in re.findall(r"^def (test_\w+)\(", test_file.read_text(encoding="utf-8"), re.M):
            defined.setdefault(name, []).append(test_file.relative_to(st.REPO).as_posix())
    named = {}
    for number, (_, cell) in rows.items():
        cited = re.findall(r"`([\w/.-]+\.py)`, `(test_\w+)`", cell)
        cited += [(cited[-1][0], extra) for extra in re.findall(r" and `(test_\w+)`", cell)] if cited else []
        assert cited, f"L{number} names no test in contracts/runtime.md"
        for test_file, name in cited:
            assert test_file in defined.get(name, []), f"L{number}: {test_file} has no {name}"
            if name.startswith("test_limit_"):
                assert name.startswith(f"test_limit_{number:02d}_"), f"L{number} names {name}"
                named.setdefault(number, []).append(name)  # a limit may have several: L15 has one for the exact content and one for a class of targets
    numbered = {n for n in defined if n.startswith("test_limit_")}
    assert numbered == {name for names in named.values() for name in names} and all(len(defined[n]) == 1 for n in numbered)
    # Every limit is built; L20 alone has no test named after it: the project's protected paths guard it.
    assert sorted(named) == list(range(1, 20))


def test_the_prepared_folder_of_a_run_is_removed_after_it(tree):
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    out = ops.run_next(path)
    assert out["status"] == "ok"
    assert not (tree["data"] / ops_core.PREPARED_DIR / str(out["run_id"])).exists()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

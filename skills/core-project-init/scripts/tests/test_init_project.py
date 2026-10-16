"""Tests for skills/core-project-init/scripts/init_project.py. Offline, fictional data.

The refusals for free text and escaping paths are in test_init_project_free_text.py; this file covers what the
skill's procedure relies on: the detection fields, the proposed mapping, the report lines, the update
path and the scratch input file.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
INIT = ROOT / "skills/core-project-init/scripts/init_project.py"
AGENTS = "# Widgets\n\nProject conventions. Run `npm test` before pushing.\n"
ARCH = "ARCHITECTURE.md=docs/engineering/architecture.md"
DS = "DESIGN-SYSTEM.md=docs/design/design-system.md"


def run(*args):
    r = subprocess.run([sys.executable, str(INIT), *args], capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.stdout.strip().startswith("{") else r.stdout), r.stderr


def project(tmp_path):
    proj = tmp_path / "proj"
    (proj / "docs").mkdir(parents=True)
    (proj / "package.json").write_text('{"name": "@acme/widgets"}\n', encoding="utf-8")
    (proj / "AGENTS.md").write_text(AGENTS, encoding="utf-8")
    for name in ("ARCHITECTURE.md", "DESIGN-SYSTEM.md", "CHANGELOG.md", "DESIGN.md"):
        (proj / name).write_text(f"# {name}\n", encoding="utf-8")
    (proj / "docs/button.md").write_text("# Button\n", encoding="utf-8")
    return proj


def test_detect_proposes_the_mapping_and_says_what_is_never_registered(tmp_path):
    proj = project(tmp_path)
    code, out, _ = run("--root", str(proj), "--detect")
    assert code == 0
    assert out["next"] == "init" and out["state_exists"] is False and out["autonomy"] is None
    assert out["name_guess"] == "widgets"
    assert [p["register"] for p in out["proposed_registrations"]] == [ARCH, DS]
    assert out["unmatched_root_docs"] == ["DESIGN.md"], "a name that does not say the slot is opened, not guessed"
    skipped = {e["file"]: e["reason"] for e in out["not_registered"]}
    assert set(skipped) == {"AGENTS.md", "CHANGELOG.md", "docs/button.md"}
    assert "end-user documentation" in skipped["docs/button.md"]
    assert out["summary"].startswith("Detected: a project root; name guess `widgets`; state file missing")
    assert "ARCHITECTURE.md" in out["summary"] and "without the workbench section" in out["summary"]
    assert not (proj / "docs/workbench").exists(), "--detect writes nothing"


def test_detect_on_an_empty_folder_is_not_a_project_root(tmp_path):
    code, out, _ = run("--root", str(tmp_path), "--detect")
    assert code == 0 and out["is_project_root"] is False
    assert "NOT a project root" in out["summary"] and out["proposed_registrations"] == []


def bare_folder(tmp_path):
    """A folder with no manifest, so that only the .git marker decides whether it is a project root."""
    proj = tmp_path / "linked"
    proj.mkdir()
    return proj


def is_root(proj):
    code, out, _ = run("--root", str(proj), "--detect")
    assert code == 0
    return out["is_project_root"]


def test_a_git_folder_makes_a_project_root(tmp_path):
    proj = bare_folder(tmp_path)
    (proj / ".git").mkdir()
    assert is_root(proj) is True


def test_a_git_file_naming_a_folder_relative_to_the_root_makes_a_project_root(tmp_path):
    """A linked worktree keeps a file named .git that holds "gitdir: <path>"."""
    proj = bare_folder(tmp_path)
    (proj / "admin/worktrees/linked").mkdir(parents=True)
    (proj / ".git").write_text("gitdir: admin/worktrees/linked\n", encoding="utf-8")
    assert is_root(proj) is True


def test_a_git_file_naming_an_absolute_folder_makes_a_project_root(tmp_path):
    proj = bare_folder(tmp_path)
    target = tmp_path / "main-checkout/.git/worktrees/linked"
    target.mkdir(parents=True)
    (proj / ".git").write_text(f"gitdir: {target}\n", encoding="utf-8")
    assert is_root(proj) is True


def test_a_git_file_with_the_usual_relative_layout_of_a_linked_worktree_makes_a_project_root(tmp_path):
    """The layout git writes: the worktree sits beside the main checkout and points at ../main/.git/worktrees/<name>."""
    (tmp_path / "main/.git/worktrees/linked").mkdir(parents=True)
    proj = tmp_path / "linked"
    proj.mkdir()
    (proj / ".git").write_text("gitdir: ../main/.git/worktrees/linked\n", encoding="utf-8")
    assert is_root(proj) is True


def test_a_git_file_naming_a_regular_file_is_not_a_project_root(tmp_path):
    proj = bare_folder(tmp_path)
    (proj / "admin").write_text("not a folder\n", encoding="utf-8")
    (proj / ".git").write_text("gitdir: admin\n", encoding="utf-8")
    assert is_root(proj) is False


def test_a_git_file_naming_a_missing_folder_is_not_a_project_root(tmp_path):
    proj = bare_folder(tmp_path)
    (proj / ".git").write_text("gitdir: admin/worktrees/gone\n", encoding="utf-8")
    assert is_root(proj) is False


def test_a_git_file_of_other_content_is_not_a_project_root(tmp_path):
    proj = bare_folder(tmp_path)
    (proj / "admin").mkdir()
    (proj / ".git").write_text("notes about the repository\ngitdir: admin\n", encoding="utf-8")
    assert is_root(proj) is False


def test_apply_writes_state_keeps_agents_md_and_prints_the_report(tmp_path):
    proj = project(tmp_path)
    code, out, err = run("--root", str(proj), "--apply", "--name", "Lumen Notes", "--autonomy", "milestones",
                         "--register", ARCH, "--register", DS)
    assert code == 0, err
    state = (proj / "docs/workbench/state.md").read_text(encoding="utf-8")
    assert "- Project: Lumen Notes\n" in state and "- Checkpoints: milestones\n" in state
    assert "| docs/engineering/architecture.md (at ARCHITECTURE.md) | existing | approved |" in state
    agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(AGENTS) and agents.count("<!-- workbench:start -->") == 1
    assert "checkpoints mode is `milestones`" in agents
    report = "\n".join(out["report"])
    assert out["report"][0] == "## Project initialized: Lumen Notes"
    assert "docs/workbench/state.md (created), autonomy milestones" in report
    assert "AGENTS.md (section added)" in report
    assert "| docs/design/design-system.md | DESIGN-SYSTEM.md | existing | approved |" in report
    assert "docs/button.md (end-user documentation" in report and "CHANGELOG.md (never registered)" in report
    assert (proj / "CHANGELOG.md").read_text(encoding="utf-8") == "# CHANGELOG.md\n"
    assert not (proj / "docs/engineering").exists() and not (proj / "docs/design").exists()


def test_apply_without_agents_md_creates_it_and_dry_run_writes_nothing(tmp_path):
    proj = tmp_path / "new"
    proj.mkdir()
    (proj / "package.json").write_text('{"name": "lumen-notes"}\n', encoding="utf-8")
    base = ("--root", str(proj), "--apply", "--name", "Lumen Notes", "--autonomy", "every-phase")
    code, out, _ = run(*base, "--dry-run")
    assert code == 0 and out["dry_run"] is True and not (proj / "docs").exists() and not (proj / "AGENTS.md").exists()
    code, out, _ = run(*base)
    assert code == 0 and out["agents_md"] == "created"
    assert "- Registered as existing artifacts: none" in out["report"] and "- Not registered: none" in out["report"]
    assert (proj / "AGENTS.md").read_text(encoding="utf-8").startswith("# Lumen Notes\n")
    assert run(*base)[0] == 1, "a second --apply is refused"


def test_update_changes_only_the_mode_and_reports_the_kept_rows(tmp_path):
    proj = project(tmp_path)
    assert run("--root", str(proj), "--apply", "--name", "widgets", "--autonomy", "every-phase",
               "--register", ARCH, "--register", DS)[0] == 0
    code, out, _ = run("--root", str(proj), "--detect")
    assert out["next"] == "update" and out["autonomy"] == "every-phase" and out["proposed_registrations"] == []
    assert "state file exists, autonomy `every-phase`" in out["summary"]
    assert "docs/workbench/state.md" not in out["docs_dir"]["files"]
    code, out, err = run("--root", str(proj), "--set-autonomy", "milestones")
    assert code == 0, err
    state = (proj / "docs/workbench/state.md").read_text(encoding="utf-8")
    assert "- Checkpoints: milestones\n" in state and "every-phase\n\n## Artifacts" not in state
    assert state.count("(at ARCHITECTURE.md)") == 1 and "- Project: widgets\n" in state
    agents = (proj / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.startswith(AGENTS) and agents.count("<!-- workbench:start -->") == 1
    assert "`milestones`" in agents and "`every-phase`" not in agents
    assert out["report"][0] == "## Project updated: widgets"
    report = "\n".join(out["report"])
    assert "(updated), autonomy milestones: the mode was switched from every-phase to milestones" in report and "AGENTS.md (section updated)" in report
    assert "| docs/engineering/architecture.md | ARCHITECTURE.md | existing | approved |" in report
    assert run("--root", str(proj), "--set-autonomy", "sometimes")[0] == 2


def test_the_scratch_input_file_is_deleted_only_after_a_real_run(tmp_path):
    proj = project(tmp_path)
    scratch = proj / ".workbench-init-input.json"
    words = {"name": "Dana's widgets", "decisions": ["No brand phase; internal tool."]}
    scratch.write_text(json.dumps(words), encoding="utf-8")
    base = ("--root", str(proj), "--apply", "--autonomy", "every-phase", "--input", str(scratch))
    assert run(*base, "--dry-run")[0] == 0 and scratch.exists(), "a dry run keeps the file for the real run"
    code, out, err = run(*base)
    assert code == 0, err
    assert not scratch.exists()
    state = (proj / "docs/workbench/state.md").read_text(encoding="utf-8")
    assert "- Project: Dana's widgets\n" in state and "No brand phase; internal tool. (user)" in state
    other = tmp_path / "answers.json"
    other.write_text(json.dumps({"open_questions": ["Who owns support?"]}), encoding="utf-8")
    assert run("--root", str(proj), "--input", str(other))[0] == 0
    assert other.exists(), "a file with another name is never deleted"

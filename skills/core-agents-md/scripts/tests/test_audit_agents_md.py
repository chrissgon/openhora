"""Tests for skills/core-agents-md/scripts/audit_agents_md.py. Offline, fictional data."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / "skills/core-agents-md/scripts/audit_agents_md.py"

PACKAGE = {"name": "@acme/widgets", "description": "Tiny widget library",
           "scripts": {"build": "vite build", "test": "vitest run", "test:e2e": "playwright test", "lint": "eslint ."}}

AGENTS = """# Widgets

Run `bun run tests` before pushing. See `docs/ARCH.md`.

<!-- workbench:start -->
## Working with the AI workbench
(section owned by core-project-init)
<!-- workbench:end -->
"""


def run(*args):
    r = subprocess.run([sys.executable, str(AUDIT), *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def project(tmp_path, agents=AGENTS):
    (tmp_path / "package.json").write_text(json.dumps(PACKAGE), encoding="utf-8")
    (tmp_path / "bun.lock").write_text("lockfileVersion: 1\n", encoding="utf-8")
    (tmp_path / "eslint.config.js").write_text("export default [];\n", encoding="utf-8")
    (tmp_path / "vitest.config.ts").write_text("export default {};\n", encoding="utf-8")
    (tmp_path / "ARCHITECTURE.md").write_text("# Architecture\n", encoding="utf-8")
    if agents is not None:
        (tmp_path / "AGENTS.md").write_text(agents, encoding="utf-8")
    return tmp_path


def commit(root):
    for cmd in (["init", "-q"], ["add", "-A"],
                ["-c", "user.email=dev@acme.example", "-c", "user.name=Dev", "-c", "commit.gpgsign=false",
                 "commit", "-q", "-m", "fixture"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, capture_output=True)


def test_help_exits_zero_and_no_arguments_is_a_usage_error():
    rc, out, _ = run("--help")
    assert rc == 0 and "--fix" in out
    assert run()[0] == 2


def test_detect_lists_commands_and_tools_with_sources(tmp_path):
    rc, out, _ = run("--root", str(project(tmp_path)), "--detect")
    data = json.loads(out)
    assert rc == 0
    assert data["commands"][0] == {"task": "install", "command": "bun install", "source": "bun.lock"}
    by_task = {c["task"]: c for c in data["commands"]}
    assert by_task["test:e2e"]["command"] == "bun run test:e2e"
    assert by_task["test"]["runs"] == "vitest run"
    assert by_task["lint"]["source"] == "package.json scripts.lint"
    assert {"name": "ESLint", "source": "eslint.config.js"} in data["tools"]
    assert {"name": "Vitest", "source": "vitest.config.ts"} in data["tools"]
    assert len(data["tools"]) == 2
    assert data["agents_md"]["has_workbench_section"] is True
    assert len(data["agents_md"]["workbench_sha256"]) == 64


def test_detect_without_lockfile_uses_npm_run_and_no_install(tmp_path):
    project(tmp_path, agents=None)
    (tmp_path / "bun.lock").unlink()
    data = json.loads(run("--root", str(tmp_path), "--detect")[1])
    assert [c["command"] for c in data["commands"]][:2] == ["npm run build", "npm run test"]
    assert data["agents_md"] == {"exists": False, "sections": [], "has_workbench_section": False,
                                 "workbench_sha256": None, "lines": 0}


def test_audit_reports_problems_with_one_suggestion_each(tmp_path):
    root = project(tmp_path)
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"))
    data = json.loads(out)
    assert rc == 1 and data["ok"] is False
    assert data["unknown_commands"] == ["bun run tests"]
    assert data["missing_paths"] == ["docs/ARCH.md"]
    assert data["suggestions"] == {"bun run tests": ["bun run test"], "docs/ARCH.md": ["ARCHITECTURE.md"]}
    assert data["fixed"] == []
    assert data["workbench_section"] == "not checked" and data["baseline"] == "none"
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == AGENTS


def test_fix_replaces_only_the_flagged_spans(tmp_path):
    root = project(tmp_path)
    commit(root)
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"), "--fix")
    data = json.loads(out)
    assert rc == 0 and data["ok"] is True
    assert [(f["from"], f["to"]) for f in data["fixed"]] == [("bun run tests", "bun run test"),
                                                           ("docs/ARCH.md", "ARCHITECTURE.md")]
    assert data["workbench_section"] == "unchanged" and data["baseline"] == "last git commit"
    expected = AGENTS.replace("bun run tests", "bun run test").replace("docs/ARCH.md", "ARCHITECTURE.md")
    assert (root / "AGENTS.md").read_text(encoding="utf-8") == expected


def test_fix_leaves_a_problem_with_no_or_several_suggestions(tmp_path):
    root = project(tmp_path, agents="# Widgets\n\nRun `bun run size` and `bun run lnt`. See `docs/GUIDE.md` and `NOTES.md`.\n")
    (root / "NOTES-old.md").write_text("old\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "NOTES-new.md").write_text("new\n", encoding="utf-8")
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"), "--fix")
    data = json.loads(out)
    assert rc == 1
    assert [(f["from"], f["to"]) for f in data["fixed"]] == [("bun run lnt", "bun run lint")]
    assert data["unknown_commands"] == ["bun run size"]
    assert data["suggestions"]["bun run size"] == []
    assert data["suggestions"]["docs/GUIDE.md"] == []
    assert sorted(data["suggestions"]["NOTES.md"]) == ["NOTES-old.md", "docs/NOTES-new.md"]
    text = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "`bun run size`" in text and "`NOTES.md`" in text and "`bun run lint`" in text


def test_changed_workbench_section_fails_against_the_last_commit(tmp_path):
    root = project(tmp_path, agents=AGENTS.replace("bun run tests", "bun run test").replace("docs/ARCH.md", "ARCHITECTURE.md"))
    commit(root)
    path = root / "AGENTS.md"
    path.write_text(path.read_text(encoding="utf-8").replace("(section owned by core-project-init)", "(edited)"),
                    encoding="utf-8")
    rc, out, _ = run("--root", str(root), "--audit", str(path))
    data = json.loads(out)
    assert rc == 1 and data["workbench_section"] == "CHANGED" and data["ok"] is False


def test_explicit_baseline_wins_and_a_file_without_section_is_reported(tmp_path):
    root = project(tmp_path, agents="# Widgets\n\nRun `bun run test`.\n")
    base = tmp_path / "before.md"
    base.write_text("# Widgets\n", encoding="utf-8")
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"), "--baseline", str(base))
    data = json.loads(out)
    assert rc == 0 and data["workbench_section"] == "none in the file" and data["baseline"] == str(base)
    assert data["workbench_sha256"] is None


def test_suggestions_skip_hidden_and_dependency_folders(tmp_path):
    root = project(tmp_path, agents="# Widgets\n\nSee `docs/SETUP.md`.\n")
    for folder in (".tooling", "node_modules"):
        (root / folder).mkdir()
        (root / folder / "SETUP.md").write_text("x\n", encoding="utf-8")
    data = json.loads(run("--root", str(root), "--audit", str(root / "AGENTS.md"))[1])
    assert data["suggestions"] == {"docs/SETUP.md": []}


def test_usage_errors(tmp_path):
    root = project(tmp_path)
    assert run("--root", str(root), "--detect", "--fix")[0] == 2
    assert run("--root", str(root), "--audit", str(root / "missing.md"))[0] == 2
    assert run("--root", str(tmp_path / "nowhere"), "--detect")[0] == 2
    assert run("--root", str(root), "--unknown")[0] == 2


INSTRUCTIONS = """# Instructions

## Always
- Run `bun run test` before finishing.
- Reply in Portuguese.

## Never
- Break the hard rules.
"""


def test_carried_over_lists_a_copied_line_with_its_source(tmp_path):
    agents = AGENTS.replace("bun run tests", "bun run test").replace("See `docs/ARCH.md`.", "See `ARCHITECTURE.md`.\n- Reply in Portuguese.")
    root = project(tmp_path, agents=agents)
    (root / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"))
    data = json.loads(out)
    assert data["carried_over"] == [{"line": "Reply in Portuguese.", "from": "INSTRUCTIONS.md"}]
    assert data["ok"] is True and rc == 0


def test_carried_over_skips_a_line_the_baseline_already_had(tmp_path):
    agents = AGENTS.replace("See `docs/ARCH.md`.", "See `ARCHITECTURE.md`.\n- Reply in Portuguese.")
    root = project(tmp_path, agents=agents)
    (root / "INSTRUCTIONS.md").write_text(INSTRUCTIONS, encoding="utf-8")
    (tmp_path / "base.md").write_text(agents.replace("- Reply in Portuguese.", "* reply in portuguese"), encoding="utf-8")
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"), "--baseline", str(tmp_path / "base.md"))
    assert json.loads(out)["carried_over"] == []


def test_carried_over_is_empty_without_an_instruction_like_file(tmp_path):
    root = project(tmp_path)
    rc, out, _ = run("--root", str(root), "--audit", str(root / "AGENTS.md"))
    assert json.loads(out)["carried_over"] == []

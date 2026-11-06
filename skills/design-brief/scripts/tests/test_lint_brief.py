"""Tests for skills/design-brief/scripts/lint_brief.py. Offline; every name and number below is fictional.

Run: uv run --with pytest pytest skills/design-brief/scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(rel: str, *args: str, cwd: Path | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / rel), *args], capture_output=True, text=True,
                          cwd=cwd, input=stdin, timeout=60)


# ---------- design-brief/lint_brief.py: SCREEN lists from the flows ----------

LINT_BRIEF = "skills/design-brief/scripts/lint_brief.py"


FLOWS_BOTH_SEPARATORS = """# Flows

## Screens

- SCREEN-1: Home. Purpose: introduce the site. Regions: hero (name, role), project list, footer. States: default, no JavaScript (theme toggle inert), reduced motion. Breakpoints: one column. Source: spec REQ-1.
- SCREEN-2: Post. Purpose: read a post. Regions: header, body. States: default; copied (feedback, 1 second); offline, cached copy shown. Breakpoints: one column. Source: spec REQ-2.

## Flows
"""


def screen_errors(tmp_path: Path, screen: str, content: str) -> list[str]:
    flows = tmp_path / "flows.md"
    flows.write_text(FLOWS_BOTH_SEPARATORS, encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text(f"# Brief\n\n## Content\n\n{content}\n", encoding="utf-8")
    r = run(LINT_BRIEF, "--file", str(brief), "--type", "screen", "--values", "inline",
            "--flows", str(flows), "--screen", screen)
    return [e for e in json.loads(r.stdout)["errors"] if f"of {screen}" in e or "not found" in e]


def test_lint_brief_splits_lists_on_commas_or_semicolons():
    split = load(LINT_BRIEF, "lint_brief").split_list
    assert split("default, no JavaScript (theme toggle inert), reduced motion") == [
        "default", "no JavaScript (theme toggle inert)", "reduced motion"]
    assert split("default; copied (feedback, 1 second); offline, cached copy shown") == [
        "default", "copied (feedback, 1 second)", "offline, cached copy shown"]


def test_lint_brief_accepts_comma_separated_states(tmp_path):
    content = ("- Regions: hero, project list, footer\n- States:\n  - default\n"
               "  - no JavaScript: the toggle is inert\n  - reduced motion: no animation")
    assert screen_errors(tmp_path, "SCREEN-1", content) == []


def test_lint_brief_accepts_semicolon_separated_states(tmp_path):
    content = "- Regions: header, body\n- States:\n  - default\n  - copied: feedback\n  - offline, cached copy shown"
    assert screen_errors(tmp_path, "SCREEN-2", content) == []


def test_lint_brief_reports_a_state_missing_from_content(tmp_path):
    errors = screen_errors(tmp_path, "SCREEN-1", "- Regions: hero, project list, footer\n- States: default")
    assert errors == [
        "state 'no JavaScript (theme toggle inert)' of SCREEN-1 is not named in Content (looked for 'no javascript')",
        "state 'reduced motion' of SCREEN-1 is not named in Content (looked for 'reduced motion')"]


def test_lint_brief_eval_fixture_screens_keep_their_items():
    split = load(LINT_BRIEF, "lint_brief").split_list
    flows = (ROOT / "skills/design-brief/evals/files/docs-site/docs/design/flows.md").read_text(encoding="utf-8")
    states = re.search(r"SCREEN-3:.*?States:\s*(.*?)\.\s*Breakpoints:", flows).group(1)
    assert split(states) == ["default", "light and dark (from `data-mode`)", "theme colour applied",
                             "search entry point absent when the build has no search"]


# ---------- design-brief/lint_brief.py: --report and the command line ----------

def test_lint_brief_report_records_the_arguments_date_and_result(tmp_path):
    flows = tmp_path / "flows.md"
    flows.write_text(FLOWS_BOTH_SEPARATORS, encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief\n\n## Content\n\n- Regions: hero, project list, footer\n- States: default\n", encoding="utf-8")
    report = tmp_path / "lint.json"
    r = run(LINT_BRIEF, "--file", str(brief), "--type", "screen", "--values", "inline",
            "--flows", str(flows), "--screen", "SCREEN-1", "--report", str(report), "--json")
    text = report.read_text(encoding="utf-8")
    printed, saved = json.loads(r.stdout), json.loads(text)
    assert r.returncode == 1 and printed["ok"] is False and text.endswith("\n")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", saved.pop("date"))
    assert saved == {"script": "lint_brief.py",
                     "arguments": {"--file": str(brief), "--type": "screen", "--values": "inline",
                                   "--flows": str(flows), "--screen": "SCREEN-1", "--json": True},
                     "ok": False, "summary": printed["summary"], "errors": printed["errors"],
                     "counts": printed["counts"]}
    assert printed["summary"].startswith(f"lint_brief FAILED: {len(printed['errors'])} errors; ")
    assert any("reduced motion" in e for e in saved["errors"])


def test_lint_brief_refuses_unknown_flags_and_prints_usage_errors_on_stderr(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief\n", encoding="utf-8")
    base = (LINT_BRIEF, "--file", str(brief), "--type", "screen", "--values", "inline")
    for args in (("--reprot", str(tmp_path / "x.json")), ("--strict",)):
        r = run(*base, *args)
        assert r.returncode == 2 and "unknown argument" in r.stderr and r.stdout == ""
    assert not (tmp_path / "x.json").exists()
    r = run(LINT_BRIEF)
    assert r.returncode == 2 and r.stdout == "" and "--file" in r.stderr
    r = run(LINT_BRIEF, "--help")
    assert r.returncode == 0 and "--report" in r.stdout


def test_lint_brief_report_needs_a_writable_path(tmp_path):
    brief = tmp_path / "brief.md"
    brief.write_text("# Brief\n", encoding="utf-8")
    base = (LINT_BRIEF, "--file", str(brief), "--type", "screen", "--values", "inline")
    r = run(*base, "--report")
    assert r.returncode == 2 and "--report needs a value" in r.stderr
    r = run(*base, "--report", str(tmp_path / "absent" / "lint.json"))
    assert r.returncode == 2 and "cannot write the report" in r.stderr


def design_system_errors(tmp_path: Path, brief_text: str) -> list[str]:
    system = tmp_path / "design-system.md"
    system.write_text("# Design system\n\n- Brand: #1A6B3C\n- Surface: #f5f1e8\n", encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text(brief_text, encoding="utf-8")
    r = run(LINT_BRIEF, "--file", str(brief), "--type", "image", "--values", "inline",
            "--design-system", str(system))
    return [e for e in json.loads(r.stdout)["errors"] if "design system" in e]


def test_lint_brief_design_system_flags_a_foreign_colour(tmp_path):
    errors = design_system_errors(tmp_path, "# Brief\n\n## Visual language\n\n- Brand #1A6B3C\n\n## Prompt\n\nUse #FF00AA and #ff00aa.\n")
    assert errors == ["colour #FF00AA is not a value of the design system"]


def test_lint_brief_design_system_accepts_colours_of_the_file_in_any_case(tmp_path):
    assert design_system_errors(tmp_path, "# Brief\n\n## Visual language\n\n- Brand #1a6b3c, surface #F5F1E8\n") == []

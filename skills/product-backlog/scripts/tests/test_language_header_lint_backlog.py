"""A `- Language: <tag>` header line in the backlog, the specification or the design changes nothing lint_backlog.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/product-backlog/scripts/tests

Offline; every name, path and requirement below is fictional. The line sits right after the `- Owner:` header line.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/product-backlog/scripts/lint_backlog.py"
FIX = ROOT / "skills/product-backlog/evals/files/fix/docs/product"
TICKETS = ROOT / "skills/product-backlog/evals/files/tickets/docs/product"

SPEC = """# Feature specification: lantern

- Owner: product-feature-spec
- Status: draft
- Date: 2026-03-14

## Functional requirements
- REQ-1: The build reads every note. Source: brief
- REQ-2: The old notes page is removed. Source: brief
## Non-functional requirements
- NFR-1: The build ends in under 5 seconds. Source: brief
## Acceptance criteria
- AC-1:
  Given a note
  Then it is published
  Covers: REQ-1, NFR-1
- AC-2:
  Given the old page
  Then it is gone
  Covers: REQ-2
"""

DESIGN = """# Design: lantern

- Owner: eng-architecture
- Status: draft
- Date: 2026-03-14

## Components

| Component | Responsibility | Location |
|-----------|----------------|----------|
| Note parser | Parses a note | build/parse.mjs |
| Note loader | Reads every note | build/load.mjs |
| Page writer | Writes the pages | build/write.mjs |

## Verification plan

| AC | Check | Type | Command or location |
|----|-------|------|---------------------|
| AC-1 | a note is published | integration | `node --test test/build.test.mjs` |
| AC-2 | the old page is gone | integration | `node --test test/removal.test.mjs` |

## Assumptions to verify before implementation

- The Note parser keeps the note title. Verify by parsing one note in a scratch script.

## Open questions

- none
"""

GOOD = """# Backlog: lantern

- Owner: product-backlog
- Status: draft
- Updated: 2026-03-14

## Feature: lantern (`T-lan`)

### Tasks

- T-lan-1: Spike: the parser keeps the note title
  Does: parses one note in a scratch script
  Delivers: REQ-1
  Touches: Note parser
  Depends on: none
  Check: parsing one note in a scratch script prints its title (design assumption 1)
  Size: L, because it is a spike
  Milestone: M1
- T-lan-2: Note loader
  Does: reads every note
  Delivers: REQ-1, NFR-1, AC-1
  Touches: Note loader, Note parser
  Depends on: T-lan-1
  Check: `node --test test/build.test.mjs`; a note is published (verification plan: AC-1)
  Size: S, because one file
  Milestone: M1
- T-lan-3: Remove the old notes page
  Does: deletes the page
  Delivers: REQ-2, AC-2
  Touches: old page
  Depends on: T-lan-2
  Check: `node --test test/removal.test.mjs`; the old page is gone (verification plan: AC-2)
  Size: S, because one deletion
  Milestone: M2

### Milestones

- M1 notes publish: T-lan-1, T-lan-2 → usable state: notes are published
- M2 old page gone: T-lan-3 → usable state: only generated pages remain
"""

# the same backlog with a known failure: task T-lan-2 has a vague Check
BAD = GOOD.replace("Check: `node --test test/build.test.mjs`; a note is published (verification plan: AC-1)",
                   "Check: Works.")

TAGS = ("pt-BR", "en-US")


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def run(tmp: Path, backlog: str, spec: str, design: str | None, *extra: str) -> subprocess.CompletedProcess:
    (tmp / "backlog.md").write_text(backlog, encoding="utf-8")
    (tmp / "spec.md").write_text(spec, encoding="utf-8")
    args = [sys.executable, str(LINT), "--backlog", str(tmp / "backlog.md"), "--spec", str(tmp / "spec.md")]
    if design is not None:
        (tmp / "design.md").write_text(design, encoding="utf-8")
        args += ["--design", str(tmp / "design.md")]
    return subprocess.run([*args, *extra], capture_output=True, text=True, timeout=60)


def same_result(a: subprocess.CompletedProcess, b: subprocess.CompletedProcess) -> None:
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


def test_the_baseline_documents_have_the_header_the_tests_edit():
    for text in (GOOD, SPEC, DESIGN):
        assert "- Owner:" in text and "- Language:" not in text


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_backlog_passes_the_same_with_the_language_line(tmp_path, tag):
    plain = run(tmp_path, GOOD, SPEC, DESIGN)
    assert plain.returncode == 0, plain.stdout
    # the line in the backlog alone, then in all three documents
    only_backlog = run(tmp_path, with_language(GOOD, tag), SPEC, DESIGN)
    everywhere = run(tmp_path, with_language(GOOD, tag), with_language(SPEC, tag), with_language(DESIGN, tag))
    same_result(plain, only_backlog)
    same_result(plain, everywhere)
    assert "- Language: " + tag in (tmp_path / "backlog.md").read_text(encoding="utf-8")
    assert "lint_backlog: ok: true; errors: 0; tasks: 3" in everywhere.stdout


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_backlog_without_a_design_passes_the_same(tmp_path, tag):
    plain = run(tmp_path, GOOD, SPEC, None)
    with_line = run(tmp_path, with_language(GOOD, tag), with_language(SPEC, tag), None)
    assert plain.returncode == 0
    same_result(plain, with_line)


@pytest.mark.parametrize("tag", TAGS)
def test_a_failing_backlog_fails_with_the_same_findings(tmp_path, tag):
    plain = run(tmp_path, BAD, SPEC, DESIGN)
    with_line = run(tmp_path, with_language(BAD, tag), with_language(SPEC, tag), with_language(DESIGN, tag))
    assert plain.returncode == 1 and "T-lan-2 Check 'Works.' is not a command" in plain.stdout
    same_result(plain, with_line)


@pytest.mark.parametrize("tag", TAGS)
def test_the_repository_fixtures_keep_their_verdict(tmp_path, tag):
    for directory, rc in ((FIX, 1), (TICKETS, 0)):
        backlog = (directory / "backlog.md").read_text(encoding="utf-8")
        spec = (directory / "specs/reading-time.md").read_text(encoding="utf-8")
        plain = run(tmp_path, backlog, spec, None)
        with_line = run(tmp_path, with_language(backlog, tag), with_language(spec, tag), None)
        assert plain.returncode == rc, plain.stdout
        same_result(plain, with_line)


@pytest.mark.parametrize("tag", TAGS)
def test_the_report_record_is_the_same_apart_from_the_paths(tmp_path, tag):
    reports = []
    for name, backlog, spec in (("plain", BAD, SPEC), ("lang", with_language(BAD, tag), with_language(SPEC, tag))):
        report = tmp_path / f"{name}.json"
        run(tmp_path, backlog, spec, DESIGN, "--report", str(report))
        reports.append(report.read_text(encoding="utf-8").replace(str(report), "REPORT"))
    assert reports[0] == reports[1]

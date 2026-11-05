"""A `- Language: <tag>` header line in the PRD (and in the brief it cites) changes nothing lint_prd.py decides.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/product-prd/scripts/tests

Offline; every name and number below is fictional. The line sits right after the `- Owner:` header line. The
`- Brief:` header line, which the script reads to find its source file, stays where it was.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/product-prd/scripts/lint_prd.py"
TAGS = ("pt-BR", "en-US")

BRIEF = """# Brief: Plinth

- Owner: core-clarify
- Status: approved
- Date: 2026-01-05

Decision 1: 40 percent of searches end in a click.
"""


def prd(target: str = "40 percent of searches") -> str:
    return f"""# PRD: Plinth

- Owner: product-prd
- Status: draft
- Date: 2026-01-05
- Brief: brief.md

## Summary

## Problem and goal

## Users

- U-1: Site owners. Situation: publishing docs. Needs: search. Source: brief.md decision 1.

## Scope

## Sources

## Features

- F-1: Search. Outcome: the reader can find a page. Priority: must. Phase: P-1. Source: brief.md decision 1.

## Success metrics

- M-1: Searches that end in a click. Target: {target}. Baseline: none. Measured by: analytics. Source: brief.md decision 1.

## Constraints

## Dependencies and risks

- R-1: The index grows. Trigger: many pages. Impact: slow builds. Mitigation: split the index.

## Release phases

- P-1: First release. Includes: F-1. Exit: search is live. Source: brief.md decision 1.

## Assumptions

## Open questions

- OPEN-2: Which share of searches should end in a click? Blocks: M-1. Recommended: 40 percent, the brief's figure.

## Readiness
"""


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next((i for i, ln in enumerate(lines) if ln.startswith("## ")), len(lines))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def run(tmp: Path, text: str, brief: str = BRIEF, *extra: str) -> subprocess.CompletedProcess:
    """Lint `text` from inside `tmp`, so that only the brief written there is a source."""
    (tmp / "brief.md").write_text(brief, encoding="utf-8")
    (tmp / "prd.md").write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(LINT), "--file", str(tmp / "prd.md"), *extra], capture_output=True,
                          text=True, cwd=tmp, timeout=60)


def same_result(a: subprocess.CompletedProcess, b: subprocess.CompletedProcess) -> None:
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


def test_the_baseline_documents_have_the_header_the_tests_edit():
    assert "- Owner: product-prd" in prd() and "- Language:" not in prd()
    assert with_language(prd(), "pt-BR").splitlines()[2:5] == ["- Owner: product-prd", "- Language: pt-BR", "- Status: draft"]
    assert with_language(BRIEF, "en-US").splitlines()[2:4] == ["- Owner: core-clarify", "- Language: en-US"]


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_prd_passes_the_same_with_the_language_line(tmp_path, tag):
    plain = run(tmp_path, prd())
    assert plain.returncode == 0, plain.stdout
    assert json.loads(plain.stdout)["sources_read"], "the number check ran against the brief"
    # the line in the PRD alone, then in the PRD and in its brief
    same_result(plain, run(tmp_path, with_language(prd(), tag)))
    both = run(tmp_path, with_language(prd(), tag), with_language(BRIEF, tag))
    same_result(plain, both)
    assert "- Language: " + tag in (tmp_path / "prd.md").read_text(encoding="utf-8")
    out = json.loads(both.stdout)
    assert out["ok"] is True and out["errors"] == [] and out["warnings"] == []
    assert out["counts"] == {"U": 1, "F": 1, "M": 1, "R": 1, "P": 1, "ASSUMPTION": 0, "OPEN": 1}


@pytest.mark.parametrize("tag", TAGS)
def test_failing_prds_fail_with_the_same_findings(tmp_path, tag):
    cases = {
        "a number in no source": (prd("55 percent of searches"), ["M-1 target number 55 is in no source file"]),
        "an id for a target": (prd("OPEN-2"), ["M-1 has no numeric Target:"]),
        "a missing section": (prd().replace("## Constraints\n\n", ""), ["missing section '## Constraints'"]),
    }
    for label, (text, errors) in cases.items():
        plain = run(tmp_path, text)
        assert plain.returncode == 1 and json.loads(plain.stdout)["errors"] == errors, label
        same_result(plain, run(tmp_path, with_language(text, tag), with_language(BRIEF, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_the_language_line_is_not_a_malformed_id_and_the_brief_line_is_still_found(tmp_path, tag):
    # a stray line elsewhere would be flagged as a malformed id; the header line is not
    out = json.loads(run(tmp_path, with_language(prd(), tag)).stdout)
    assert not [e for e in out["errors"] if "malformed id" in e]
    assert out["sources_read"] == [str((tmp_path / "brief.md").resolve())] or len(out["sources_read"]) == 1
    # without a readable brief the number check is skipped, with and without the line
    plain = run(tmp_path, prd().replace("- Brief: brief.md\n", "").replace("brief.md decision 1", "the brief"))
    skipped = run(tmp_path, with_language(prd().replace("- Brief: brief.md\n", "").replace(
        "brief.md decision 1", "the brief"), tag))
    # brief.md still exists in the folder but is no longer named: the PRD names no source at all
    same_result(plain, skipped)


@pytest.mark.parametrize("tag", TAGS)
def test_the_table_output_is_the_same(tmp_path, tag):
    for text in (prd(), prd("55 percent of searches")):
        plain = run(tmp_path, text, BRIEF, "--table")
        with_line = run(tmp_path, with_language(text, tag), with_language(BRIEF, tag), "--table")
        same_result(plain, with_line)
        assert plain.stdout.rstrip().splitlines()[-1].startswith("lint_prd result:")


@pytest.mark.parametrize("tag", TAGS)
def test_the_report_record_is_the_same(tmp_path, tag):
    records = []
    for name, text in (("plain", prd("55 percent of searches")), ("lang", with_language(prd("55 percent of searches"), tag))):
        report = tmp_path / f"{name}.json"
        run(tmp_path, text, BRIEF, "--report", str(report))
        records.append(json.loads(report.read_text(encoding="utf-8")))
    assert records[0]["ok"] is False and records[0] == records[1]

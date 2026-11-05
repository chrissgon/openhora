"""A `- Language: <tag>` header line in the roadmap or in the PRD it is checked against changes nothing lint_roadmap.py decides.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/product-roadmap/scripts/tests

Offline; every name below is fictional. The line sits right after the `- Owner:` header line.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/product-roadmap/scripts/lint_roadmap.py"
TAGS = ("pt-BR", "en-US")

PRD = """# PRD: Tally

- Owner: product-prd
- Status: approved
- Date: 2031-02-01
- Brief: docs/workbench/briefs/tally.md

## Features

- F-1: Receipt list. Outcome: every receipt is visible. Priority: must. Phase: P-1. Source: brief
- F-2: Monthly digest. Outcome: a digest is sent. Priority: should. Phase: P-1. Source: brief
- F-3: Shared folders. Outcome: two people share receipts. Priority: later. Phase: P-2. Source: brief
"""

ROADMAP = """# Roadmap: Tally

- Owner: product-roadmap
- Status: draft
- Date: 2031-02-03
- PRD: docs/product/prd.md

## Summary

Two releases; the first proves receipts can be listed.

## Sources

- docs/product/prd.md

## Method

Method: dependency first, then priority, then risk. Dates: none.

## Dependencies

- F-1: Depends on: none.
- F-2: Depends on: F-1, because the digest reads the receipt list (PRD F-2).

## Releases

- R-1: Core. Goal: list receipts. Includes: F-1, F-2. Order: F-1 (no dependency), then F-2 (needs F-1). Exit: a person lists receipts and gets a digest. Depends on: none.
- R-2: Sharing. Goal: share receipts. Includes: F-3. Order: F-3 (only feature). Exit: two people see one folder. Depends on: R-1.

## Now, next, later

- Now: F-1
- Next: F-2
- Later: F-3

## Risks by release

- R-1: none in the PRD.

## Not planned

- none

## Assumptions

- ASSUMPTION-1: One language. Safe because: the brief names one.

## Open questions

- OPEN-1: Which mail sender? Blocks: F-2. Recommended: the existing one, because it is configured.

## Readiness

- Ready for design and engineering: no, because OPEN-1 blocks F-2
"""


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def run(tmp: Path, roadmap: str, prd: str = PRD, *extra: str) -> subprocess.CompletedProcess:
    (tmp / "roadmap.md").write_text(roadmap, encoding="utf-8")
    (tmp / "prd.md").write_text(prd, encoding="utf-8")
    return subprocess.run([sys.executable, str(LINT), "--file", "roadmap.md", "--prd", "prd.md", *extra], cwd=tmp,
                          capture_output=True, text=True, timeout=60)


def same_result(a: subprocess.CompletedProcess, b: subprocess.CompletedProcess) -> None:
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


def test_the_baseline_documents_have_the_header_the_tests_edit():
    assert "- Owner: product-roadmap" in ROADMAP and "- Language:" not in ROADMAP + PRD
    assert with_language(ROADMAP, "pt-BR").splitlines()[2:5] == [
        "- Owner: product-roadmap", "- Language: pt-BR", "- Status: draft"]


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_roadmap_passes_the_same_with_the_language_line(tmp_path, tag):
    plain = run(tmp_path, ROADMAP)
    assert plain.returncode == 0, plain.stdout
    # the line in the roadmap alone, then in the roadmap and the PRD
    same_result(plain, run(tmp_path, with_language(ROADMAP, tag)))
    both = run(tmp_path, with_language(ROADMAP, tag), with_language(PRD, tag))
    same_result(plain, both)
    assert "- Language: " + tag in (tmp_path / "roadmap.md").read_text(encoding="utf-8")
    out = json.loads(both.stdout)
    assert out["ok"] is True and out["errors"] == [] and out["warnings"] == []
    assert out["releases"] == ["R-1", "R-2"] and out["unplaced"] == []
    assert out["summary"] == "lint_roadmap.py --file roadmap.md --prd prd.md: ok: true, 0 errors, 0 warnings"


@pytest.mark.parametrize("tag", TAGS)
def test_failing_roadmaps_fail_with_the_same_findings(tmp_path, tag):
    cases = {
        "a feature in no release": (ROADMAP.replace("Includes: F-1, F-2.", "Includes: F-1."),
                                    ["F-2 (should) is in 0 releases; must be exactly one"]),
        "an effort word": (ROADMAP.replace("Depends on: R-1.", "Depends on: R-1. Ships after 3 weeks."),
                           ["R-2 states effort or duration: 'weeks'"]),
        "a blocking OPEN with a ready roadmap": (
            ROADMAP.replace("engineering: no, because OPEN-1 blocks F-2", "engineering: yes: start with F-1"),
            ["OPEN-1 blocks F-2 but the Readiness section does not say 'no, because OPEN-1 blocks ...'"]),
        "a missing section": (ROADMAP.replace("## Not planned\n\n- none\n\n", ""), ["missing section '## Not planned'"]),
    }
    for label, (text, errors) in cases.items():
        plain = run(tmp_path, text)
        assert plain.returncode == 1 and json.loads(plain.stdout)["errors"] == errors, label
        same_result(plain, run(tmp_path, with_language(text, tag), with_language(PRD, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_the_header_date_is_still_not_a_delivery_date(tmp_path, tag):
    # the Date: header line and the Language: line sit above the sections: no warning for either
    out = json.loads(run(tmp_path, with_language(ROADMAP, tag), with_language(PRD, tag)).stdout)
    assert out["warnings"] == []
    # a dated release without a Source: is still a warning, the same one
    text = ROADMAP.replace("Depends on: R-1.", "Depends on: R-1. Ships 2031-05-01.")
    plain = run(tmp_path, text)
    assert json.loads(plain.stdout)["warnings"] == ["R-2 carries a date without a Source: line"]
    same_result(plain, run(tmp_path, with_language(text, tag), with_language(PRD, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_the_report_record_is_the_same(tmp_path, tag):
    records = []
    for name, text in (("plain", ROADMAP), ("lang", with_language(ROADMAP, tag))):
        report = tmp_path / f"{name}.json"
        run(tmp_path, text, PRD, "--report", str(report))
        records.append(json.loads(report.read_text(encoding="utf-8")))
    assert records[0]["ok"] is True and records[0] == records[1]

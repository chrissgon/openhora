"""A `- Language: <tag>` header line changes nothing lint_flows.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/design-ux-flows/scripts/tests

Offline; every product, feature, screen and flow below is fictional. Each case lints the same flows document
without the line and with it (`pt-BR`, `en-US`) placed right after the `- Owner:` line, or after the first
header line when the document has no Owner line, and compares the return code and the printed result.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LINT = Path(__file__).resolve().parents[1] / "lint_flows.py"
TAGS = ("pt-BR", "en-US")

PRD = """# PRD: Tallybook

## Features

- F-1: Receipt list. Outcome: the member sees every receipt. Priority: must. Phase: P-1. Source: brief
- F-2: Weekly digest. Outcome: the member gets a digest email every Monday. Priority: must. Phase: P-1. Source: brief
- F-3: Shared folders. Outcome: two members share receipts. Priority: later. Phase: P-2. Source: brief
"""

FLOWS = """# UX flows: Tallybook, phase P-1

- Owner: design-ux-flows
- Status: draft
- Date: 2026-10-16
- PRD: docs/product/prd.md

## Summary

Two nodes, two screens and two flows.

## Sources

- docs/product/prd.md

## Information architecture

- IA-1: Receipts. Parent: none. URL: /receipts. Filled by: generated. Source: F-1

## Screens

- SCREEN-1: Receipt list. Purpose: show every receipt. Regions: list, filter. States: loading, empty (no receipt yet), error (the list failed to load), success. Breakpoints: one column when narrow. Source: F-1
- SCREEN-2: Digest email. Purpose: summarise the week. Regions: total, receipts,
  link to the list. States: {mail_states}. Breakpoints: single column. Source: F-2

## Flows

- FLOW-1: See receipts. Actor: U-1. Trigger: opens the app. Steps: 1. on SCREEN-1: opens the list → sees receipts. End: the list is shown. Failures: step 1: the error state. Keyboard: Tab to the list. Source: F-1
- FLOW-2: Read the digest. Actor: U-1. Trigger: Monday. Steps: 1. on SCREEN-2: opens the email → follows the link; 2. on SCREEN-1: sees the list. End: the list is shown. Failures: step 1: the email is not delivered. Keyboard: Enter on the link. Source: F-2

## Coverage

- F-1: FLOW-1, SCREEN-1
- F-2: FLOW-2, SCREEN-2

## Assumptions

- ASSUMPTION-1: One member per account. Safe because: the PRD names one user group.

## Open questions

- OPEN-1: Where does the filter sit? Blocks: nothing. Recommended: above the list, because it is the second region.

## Readiness

- Ready for design-system and design-brief: yes: SCREEN-1 first, because both flows cross it
"""

GOOD_STATES = "sent, error (delivery failed: retried for 24 hours)"
BAD_STATES = "sent, opened"


def lint(tmp_path: Path, text: str) -> tuple[int, str]:
    (tmp_path / "flows.md").write_text(text, encoding="utf-8")
    (tmp_path / "prd.md").write_text(PRD, encoding="utf-8")
    r = subprocess.run([sys.executable, str(LINT), "--file", str(tmp_path / "flows.md"),
                        "--prd", str(tmp_path / "prd.md"), "--phase", "P-1"],
                       capture_output=True, text=True, timeout=60)
    assert r.stderr == ""
    return r.returncode, r.stdout


def with_language(text: str, tag: str) -> str:
    """After the Owner line; when there is none, after the first header line."""
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.startswith("- Owner:")), None)
    if at is None:
        at = next(i for i, ln in enumerate(lines) if ln.startswith("- "))
    lines.insert(at + 1, f"- Language: {tag}\n")
    return "".join(lines)


def documents(mail_states: str) -> list[str]:
    base = FLOWS.format(mail_states=mail_states)
    return [base, base.replace("- Owner: design-ux-flows\n", "")]


def test_a_passing_document_still_passes_with_a_language_line(tmp_path):
    for base in documents(GOOD_STATES):
        code, out = lint(tmp_path, base)
        assert code == 0, out
        assert json.loads(out)["ok"] is True
        for tag in TAGS:
            text = with_language(base, tag)
            assert text != base
            assert lint(tmp_path, text) == (code, out)


def test_a_failing_document_reports_the_same_findings_with_a_language_line(tmp_path):
    for base in documents(BAD_STATES):
        code, out = lint(tmp_path, base)
        assert code == 1
        errors = json.loads(out)["errors"]
        assert [e for e in errors if e.startswith("screen-states: SCREEN-2")]
        for tag in TAGS:
            assert lint(tmp_path, with_language(base, tag)) == (code, out)

"""The `- Language: <tag>` header line must change neither the return code nor the findings of
skills/biz-icp-positioning/scripts/lint_icp.py (kinds icp and positioning). Offline; every name and number is fictional.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/biz-icp-positioning/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT_ICP = "skills/biz-icp-positioning/scripts/lint_icp.py"
OWNER = "- Owner: biz-icp-positioning\n"
TAGS = ["pt-BR", "en-US"]

ICP_PASSING = (
    "# Ideal customer profile: Booking widget for dental clinics\n\n" + OWNER +
    "- Status: hypothesis\n- Date: 2026-10-01\n- Offer: Booking widget; size band: 5-20 staff\n\n"
    "## Primary profile\n- Segment and size: dental clinics with 5-20 staff [1]\n"
    "- Pain and evidence: 40% of visits end in a no-show [1]\n\n"
    "## Validation plan\n- Interviews: 5 with clinic owners\n- Questions (past behaviour only): 1. Tell me about the last missed visit.\n"
    "- Validated if: 3 of 5 name the same task\n- Rejected if: fewer than 2 of 5 name it\n\n"
    "## Assumptions\n- none\n\n## Sources\n[1] x\n")
ICP_FAILING = (
    "# ICP\n\n" + OWNER + "- Status: draft\n\n## Primary profile\n- 40% no-show\n\n"
    "## Validation plan\n- Would you pay for this?\n- Validated if: 3 of 5 name the same task\n\n## Sources\n[1] x\n")
POSITIONING_PASSING = (
    "# Positioning: Booking widget for dental clinics\n\n" + OWNER + "- Status: hypothesis\n- Date: 2026-10-01\n\n"
    "## What we can truly claim\n| Attribute | Against | Why | Confirmed by |\n|---|---|---|---|\n"
    "| Independent | vendors | trust | user, 2026-09-28 |\n\n## Sources\n[1] x\n")
POSITIONING_FAILING = (
    "# Positioning: Booking widget\n\n" + OWNER + "- Status: hypothesis\n\n"
    "## What we can truly claim\n| Attribute | Against | Why | Confirmed by |\n|---|---|---|---|\n"
    "| Independent | vendors | trust | user, 2026-09-28 |\n| Best in class | all | - | |\n")

CASES = [("icp", ICP_PASSING, True), ("icp", ICP_FAILING, False),
         ("positioning", POSITIONING_PASSING, True), ("positioning", POSITIONING_FAILING, False)]


def lint(tmp_path: Path, sub: str, text: str, kind: str):
    """Run lint_icp.py on text; return (returncode, report with the file path removed)."""
    folder = tmp_path / sub
    folder.mkdir()
    doc = folder / "doc.md"
    doc.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / LINT_ICP), "--file", str(doc), "--kind", kind],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode, json.loads(r.stdout.replace(str(doc), "<FILE>"))


def with_language(text: str, tag: str) -> str:
    assert OWNER in text
    return text.replace(OWNER, OWNER + f"- Language: {tag}\n", 1)


def unshift(report: dict) -> dict:
    """The new header line moves every reported line number down by one; undo that, change nothing else."""
    out = json.loads(json.dumps(report))
    for f in out["findings"]:
        if f["line"] > 0:
            f["line"] -= 1
    return out


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("kind,text,passing", CASES)
def test_language_line_changes_neither_code_nor_findings(tmp_path, tag, kind, text, passing):
    base_rc, base = lint(tmp_path, "base", text, kind)
    new_rc, new = lint(tmp_path, "with", with_language(text, tag), kind)
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert unshift(new) == base
    if passing:
        assert new["ok"] is True and new["findings"] == []


def test_failing_documents_keep_their_known_findings_with_the_language_line(tmp_path):
    _, icp = lint(tmp_path, "icp", with_language(ICP_FAILING, "pt-BR"), "icp")
    assert sorted(f["check"] for f in icp["findings"]) == [
        "hypothetical_question", "missing_criteria", "status", "uncited_figure"]
    _, pos = lint(tmp_path, "pos", with_language(POSITIONING_FAILING, "en-US"), "positioning")
    assert [f["check"] for f in pos["findings"]] == ["unconfirmed_claim"]


def test_language_line_directly_after_the_title_also_changes_nothing(tmp_path):
    title = "# Ideal customer profile: Booking widget for dental clinics\n\n"
    text = ICP_PASSING.replace(title, title + "- Language: pt-BR\n", 1)
    rc, report = lint(tmp_path, "x", text, "icp")
    assert rc == 0 and report["ok"] is True

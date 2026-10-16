"""The `- Language: <tag>` header line must change neither the return code nor the report of
skills/biz-market-analysis/scripts/check_refs.py on a market analysis. Offline; every name and number is fictional.
(The file name carries `_market` because skills/biz-icp-positioning has a test for its own copy of check_refs.py.)

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/biz-market-analysis/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CHECK_REFS = "skills/biz-market-analysis/scripts/check_refs.py"
OWNER = "- Owner: biz-market-analysis\n"
TAGS = ["pt-BR", "en-US"]

SOURCE_1 = ('[1] Clinic Visits Report, Dental Institute. Published 2026-03. Accessed 2026-10-01. '
            'https://stats.example/clinics. Tier 1. fact. Quote: "40% of visits end in a no-show"\n')
SOURCE_2 = ('[2] Booking Habits, Care Journal. Published undated. Accessed 2026-10-01. '
            'https://journal.example/booking. Tier 2. estimate. Quote: "owners book by phone"\n')
SOURCE_BAD = "[3] Half entry without the parts\n"
TITLE = "# Market analysis: Booking widget\n\n"
HEADER = TITLE + OWNER + "- Status: draft\n- Date: 2026-10-01\n\n"

PASSING = (
    HEADER + "## Buyers\n- About 300 clinics in the region [1]; many book by phone [2]\n\n"
    "## Capacity\n| Offer | Hours per job | Jobs per month |\n|---|---|---|\n| Widget | 4 (assumed) | 20 [M1] |\n\n"
    "## Comparison\n- Totals and the gap between the top two: 3 [M2]\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_2 + "\n## Method\n- M1: capacity.py --hours-per-week 20\n- M2: rank.py with the scores\n")
FAILING = (
    HEADER + "## Buyers\n- About 300 clinics [1] and more [7]\n- Jobs per month: 20 [M3]\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_BAD + "\n## Method\n- M1: capacity.py\n")


def check(tmp_path: Path, sub: str, text: str):
    folder = tmp_path / sub
    folder.mkdir()
    doc = folder / "doc.md"
    doc.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / CHECK_REFS), "--file", str(doc)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 1), r.stderr
    return r.returncode, json.loads(r.stdout.replace(str(doc), "<FILE>"))


def with_language(text: str, tag: str) -> str:
    assert OWNER in text
    return text.replace(OWNER, OWNER + f"- Language: {tag}\n", 1)


def test_the_baseline_documents_pass_and_fail_as_intended(tmp_path):
    rc, report = check(tmp_path, "pass", PASSING)
    assert rc == 0 and report["ok"] is True
    rc, report = check(tmp_path, "fail", FAILING)
    assert rc == 1 and report["ok"] is False


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("text,passing", [(PASSING, True), (FAILING, False)])
def test_language_line_changes_neither_code_nor_report(tmp_path, tag, text, passing):
    base_rc, base = check(tmp_path, "base", text)
    new_rc, new = check(tmp_path, "with", with_language(text, tag))
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert new == base  # check_refs reports no line numbers, so the reports are identical


def test_failing_document_keeps_its_known_findings_with_the_language_line(tmp_path):
    _, report = check(tmp_path, "x", with_language(FAILING, "pt-BR"))
    assert report["undefined"] == ["7", "M3"] and report["unused"] == ["3"]
    assert [i["ref"] for i in report["incomplete"]] == ["3"]


def test_language_line_directly_after_the_title_also_changes_nothing(tmp_path):
    rc, report = check(tmp_path, "x", PASSING.replace(TITLE, TITLE + "- Language: pt-BR\n", 1))
    assert rc == 0 and report["ok"] is True

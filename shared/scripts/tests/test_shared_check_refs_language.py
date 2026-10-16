"""The `- Language: <tag>` header line must change neither the return code nor the report of shared/scripts/check_refs.py,
on an ICP, a positioning file or a market analysis. Offline; every name and number is fictional.

Run: uv run --with pytest pytest shared/scripts/tests
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from shared_helpers import run

CHECK_REFS = "check_refs.py"
TAGS = ["pt-BR", "en-US"]
ICP_OWNER = "- Owner: biz-icp-positioning\n"
MARKET_OWNER = "- Owner: biz-market-analysis\n"

SOURCE_1 = ('[1] Clinic Visits Report, Dental Institute. Published 2026-03. Accessed 2026-10-01. '
            'https://stats.example/clinics. Tier 1. fact. Quote: "40% of visits end in a no-show"\n')
SOURCE_2 = ('[2] Booking Habits, Care Journal. Published undated. Accessed 2026-10-01. '
            'https://journal.example/booking. Tier 2. estimate. Quote: "owners book by phone"\n')
SOURCE_BAD = "[3] Half entry without the parts\n"

ICP_PASSING = (
    "# Ideal customer profile: Booking widget\n\n" + ICP_OWNER + "- Status: hypothesis\n- Date: 2026-10-01\n\n"
    "## Comparison\n- Totals and the gap between the top two: 4 [M1]\n\n"
    "## Primary profile\n- Pain and evidence: no-shows are common [1]\n- Today they use: phone [2]\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_2 + "\n## Method\n- M1: rank.py with the scores on standard input\n")
ICP_FAILING = (
    "# Ideal customer profile: Booking widget\n\n" + ICP_OWNER + "- Status: hypothesis\n\n"
    "## Primary profile\n- Pain and evidence: no-shows [1]\n- Decider: owner [4]\n- Uses M2\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_2 + SOURCE_BAD + "\n## Method\n- Queries: none\n")
POSITIONING_PASSING = (
    "# Positioning: Booking widget\n\n" + ICP_OWNER + "- Status: hypothesis\n- Date: 2026-10-01\n\n"
    "## Alternatives the customer uses today\n| Alternative | Source |\n|---|---|\n| Phone | [1] |\n| Paper | [2] |\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_2)
POSITIONING_FAILING = (
    "# Positioning: Booking widget\n\n" + ICP_OWNER + "- Status: hypothesis\n\n"
    "## Alternatives the customer uses today\n| Alternative | Source |\n|---|---|\n| Phone | [1] [5] |\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_BAD)
MARKET_TITLE = "# Market analysis: Booking widget\n\n"
MARKET_HEADER = MARKET_TITLE + MARKET_OWNER + "- Status: draft\n- Date: 2026-10-01\n\n"
MARKET_PASSING = (
    MARKET_HEADER + "## Buyers\n- About 300 clinics in the region [1]; many book by phone [2]\n\n"
    "## Capacity\n| Offer | Hours per job | Jobs per month |\n|---|---|---|\n| Widget | 4 (assumed) | 20 [M1] |\n\n"
    "## Comparison\n- Totals and the gap between the top two: 3 [M2]\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_2 + "\n## Method\n- M1: capacity.py --hours-per-week 20\n- M2: rank.py with the scores\n")
MARKET_FAILING = (
    MARKET_HEADER + "## Buyers\n- About 300 clinics [1] and more [7]\n- Jobs per month: 20 [M3]\n\n"
    "## Sources\n" + SOURCE_1 + SOURCE_BAD + "\n## Method\n- M1: capacity.py\n")

CASES = [("icp-pass", ICP_PASSING, ICP_OWNER, True), ("icp-fail", ICP_FAILING, ICP_OWNER, False),
         ("positioning-pass", POSITIONING_PASSING, ICP_OWNER, True), ("positioning-fail", POSITIONING_FAILING, ICP_OWNER, False),
         ("market-pass", MARKET_PASSING, MARKET_OWNER, True), ("market-fail", MARKET_FAILING, MARKET_OWNER, False)]


def check(tmp_path: Path, sub: str, text: str):
    folder = tmp_path / sub
    folder.mkdir()
    doc = folder / "doc.md"
    doc.write_text(text, encoding="utf-8")
    r = run(CHECK_REFS, "--file", str(doc))
    assert r.returncode in (0, 1), r.stderr
    return r.returncode, json.loads(r.stdout.replace(str(doc), "<FILE>"))


def with_language(text: str, owner: str, tag: str) -> str:
    assert owner in text
    return text.replace(owner, owner + f"- Language: {tag}\n", 1)


@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("label,text,owner,passing", CASES)
def test_language_line_changes_neither_code_nor_report(tmp_path, tag, label, text, owner, passing):
    base_rc, base = check(tmp_path, "base", text)
    new_rc, new = check(tmp_path, "with", with_language(text, owner, tag))
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert new == base  # check_refs reports no line numbers, so the reports are identical
    if passing:
        assert new["ok"] is True


def test_failing_icp_keeps_its_known_findings_with_the_language_line(tmp_path):
    _, report = check(tmp_path, "x", with_language(ICP_FAILING, ICP_OWNER, "pt-BR"))
    assert report["undefined"] == ["4", "M2"]
    assert report["unused"] == ["2", "3"]
    assert report["incomplete"][0]["ref"] == "3"


def test_failing_market_keeps_its_known_findings_with_the_language_line(tmp_path):
    _, report = check(tmp_path, "x", with_language(MARKET_FAILING, MARKET_OWNER, "pt-BR"))
    assert report["undefined"] == ["7", "M3"] and report["unused"] == ["3"]
    assert [i["ref"] for i in report["incomplete"]] == ["3"]


def test_language_line_directly_after_the_title_also_changes_nothing(tmp_path):
    title = "# Ideal customer profile: Booking widget\n\n"
    rc, report = check(tmp_path, "x", ICP_PASSING.replace(title, title + "- Language: en-US\n", 1))
    assert rc == 0 and report["ok"] is True
    rc, report = check(tmp_path, "y", MARKET_PASSING.replace(MARKET_TITLE, MARKET_TITLE + "- Language: pt-BR\n", 1))
    assert rc == 0 and report["ok"] is True

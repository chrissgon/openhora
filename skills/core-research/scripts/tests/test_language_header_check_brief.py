"""The `- Language: <tag>` header line must change neither the return code nor the result of
skills/core-research/scripts/check_brief.py (a full brief, a limited brief and failing briefs).
The briefs below are written for the tests; every name and figure is fictional.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/core-research/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_brief.py"
TODAY = "2026-10-02"
OWNER = "- Owner: core-research\n"
TITLE = "# Research: tailwind alternatives\n"
TAGS = ["pt-BR", "en-US"]

SOURCES = (
    '[1] State of CSS 2025 — Devographics. Published 2026-03-10. Accessed 2026-10-02. '
    'https://survey.stateofcss.example/2025/. Tier 1. Quote: "Tailwind CSS: 62% used"\n'
    '[2] Registry downloads — npm registry API. Published undated. Accessed 2026-10-02. '
    'https://registry.npmjs.example/downloads/tailwindcss. Tier 1. Quote: "downloads: 41,203,118"\n'
)


def brief(*, status="draft", capability="full", answer=None, findings=None, contradictions="- none found",
          unknowns="- none found", implications=None, sources=SOURCES, method="Queries run: tailwind usage.",
          plan=None, background=None):
    answer = answer if answer is not None else "- Tailwind is the most used CSS framework (fact) [1][2] — confidence: high"
    findings = findings if findings is not None else (
        "### Adoption\n- 62% of respondents used Tailwind (fact) [1 single-source] — confidence: medium")
    implications = implications if implications is not None else (
        "- A library that ships Tailwind classes meets most of the audience on day one [1]")
    parts = [
        TITLE, OWNER + f"- Status: {status}", "- Date: 2026-10-02",
        "- Question: Who are the alternatives?", "- Informs: positioning",
        "- Scope: global, 2025-2026, English", f"- Search capability: {capability}", "",
        "## Answer in brief", answer, "",
        "## Findings by sub-question", findings, "",
        "## Contradictions", contradictions, "",
        "## Unknowns", unknowns, "",
        "## Implications for positioning", implications, "",
    ]
    if background is not None:
        parts += ["## Unverified background", background, ""]
    parts += ["## Sources", sources, "", "## Method", method, ""]
    if plan is not None:
        parts += ["## Query plan (for you to run)", plan, ""]
    return "\n".join(parts)


LIMITED = dict(
    status="limited", capability="none",
    answer="- Nothing established: no search and no page fetch in this session",
    findings="### Prices\n- not established\n### Units of billing\n- not established",
    implications="- none: no finding to draw a consequence from",
    sources="", method="Queries run: none (no search capability).",
    plan="- managed vector database pricing per GB 2026\n- vector database free tier limits",
    background="Assumption: vendors bill by stored vectors or by provisioned capacity (from memory, unchecked).",
)

PASSING_FULL = brief()
PASSING_LIMITED = brief(**LIMITED)
# fails in known ways: an uncited claim, an undefined source, a URL outside Sources, a directive
FAILING = brief(answer="- Tailwind leads the market (fact) — confidence: high\n- Tailwind leads (fact) [1][7]",
                unknowns="- The price page https://vendor.example/pricing did not load",
                implications="- We should ship Tailwind classes [1]")
# fails on the header alone
BAD_HEADER = brief(status="final")


def run(tmp_path: Path, sub: str, text: str, *extra: str):
    folder = tmp_path / sub
    folder.mkdir()
    (folder / "brief.md").write_text(text, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--file", "brief.md", "--today", TODAY, *extra],
                          cwd=folder, capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout), folder


def after_owner(text: str, tag: str) -> str:
    assert OWNER in text
    return text.replace(OWNER, OWNER + f"- Language: {tag}\n", 1)


def after_title(text: str, tag: str) -> str:
    assert TITLE in text
    return text.replace(TITLE, TITLE + f"\n- Language: {tag}", 1)


@pytest.mark.parametrize("insert", [after_owner, after_title])
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("text,passing", [(PASSING_FULL, True), (PASSING_LIMITED, True),
                                          (FAILING, False), (BAD_HEADER, False)])
def test_language_line_changes_neither_code_nor_result(tmp_path, insert, tag, text, passing):
    base_rc, base, _ = run(tmp_path, "base", text)
    new_rc, new, _ = run(tmp_path, "with", insert(text, tag))
    assert (base_rc == 0) == passing, base["errors"]
    assert new_rc == base_rc
    assert new == base  # same path, summary, errors, warnings and counts: the check reports no line numbers
    if passing:
        assert new["ok"] is True and new["errors"] == []


def test_the_known_failures_are_still_reported_with_the_language_line(tmp_path):
    _, data, _ = run(tmp_path, "failing", after_owner(FAILING, "pt-BR"))
    errors = " | ".join(data["errors"])
    assert "claim without a citation in 'Answer in brief'" in errors
    assert "cites [7] but no source entry defines it" in errors
    assert "URL outside Sources/Method in 'Unknowns'" in errors
    assert "reads as a directive" in errors
    _, data, _ = run(tmp_path, "header", after_owner(BAD_HEADER, "en-US"))
    assert any("Status must be one of" in e for e in data["errors"])


def test_full_and_limited_briefs_keep_their_counts(tmp_path):
    _, full, _ = run(tmp_path, "full", after_owner(PASSING_FULL, "pt-BR"))
    assert full["summary"] == "check_brief ok: 0 errors, 2 sources"
    assert full["counts"] == {"sources": 2, "cited_claims": 2}
    _, limited, _ = run(tmp_path, "limited", after_owner(PASSING_LIMITED, "en-US"))
    assert limited["counts"]["sources"] == 0


@pytest.mark.parametrize("tag", TAGS)
def test_the_report_record_is_the_same_with_the_language_line(tmp_path, tag):
    _, _, base_dir = run(tmp_path, "base", FAILING, "--report", "check.json")
    _, _, new_dir = run(tmp_path, "with", after_owner(FAILING, tag), "--report", "check.json")
    assert (new_dir / "check.json").read_text(encoding="utf-8") == (base_dir / "check.json").read_text(encoding="utf-8")

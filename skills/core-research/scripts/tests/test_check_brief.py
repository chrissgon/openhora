"""Offline tests of check_brief.py: each rule of the skill's self-check step, the limited brief, the two
sections where a figure needs a citation, the usage errors and the --report record.

The briefs below are written for the tests. The rule on figures was weighed against the briefs of the
first measurement: applied to "Unknowns" it flagged about a third of the items there, which name what is
missing and are not findings, so "Unknowns" is never checked for figures (test_unknowns_*).

Run: uv run --with pytest pytest skills/core-research/scripts/tests
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_brief.py"
TODAY = "2026-10-02"

GOOD_SOURCES = (
    '[1] State of CSS 2025 — Devographics. Published 2026-03-10. Accessed 2026-10-02. '
    'https://survey.stateofcss.example/2025/. Tier 1. Quote: "Tailwind CSS: 62% used"\n'
    '[2] Registry downloads — npm registry API. Published undated. Accessed 2026-10-02. '
    'https://registry.npmjs.example/downloads/tailwindcss. Tier 1. Quote: "downloads: 41,203,118"\n'
)


def brief(*, status="draft", capability="full", answer=None, findings=None, contradictions="- none found",
          unknowns="- none found", implications=None, sources=GOOD_SOURCES, method="Queries run: tailwind usage.",
          plan=None, background=None):
    answer = answer if answer is not None else "- Tailwind is the most used CSS framework (fact) [1][2] — confidence: high"
    findings = findings if findings is not None else (
        "### Adoption\n- 62% of respondents used Tailwind (fact) [1 single-source] — confidence: medium")
    implications = implications if implications is not None else (
        "- A library that ships Tailwind classes meets most of the audience on day one [1]")
    parts = [
        "# Research: tailwind alternatives", "",
        "- Owner: core-research", f"- Status: {status}", "- Date: 2026-10-02",
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


def run(tmp_path, text=None, *args, file_name="brief.md"):
    if text is not None:
        (tmp_path / file_name).write_text(text, encoding="utf-8")
    argv = list(args) if args else ["--file", file_name, "--today", TODAY]
    proc = subprocess.run([sys.executable, str(SCRIPT), *argv], cwd=tmp_path, capture_output=True, text=True)
    data = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc, data


def errors_of(tmp_path, text):
    proc, data = run(tmp_path, text)
    assert proc.returncode in (0, 1), proc.stderr
    return data["errors"]


def one_error(tmp_path, text, fragment):
    errors = errors_of(tmp_path, text)
    assert any(fragment in e for e in errors), errors
    return errors


def test_a_complete_brief_passes(tmp_path):
    proc, data = run(tmp_path, brief())
    assert proc.returncode == 0, data
    assert data["ok"] is True and data["errors"] == []
    assert data["summary"] == "check_brief ok: 0 errors, 2 sources"
    assert data["counts"] == {"sources": 2, "cited_claims": 2}


# Each failure of the self-check step.

@pytest.mark.parametrize("field, broken, fragment", [
    ("url", GOOD_SOURCES.replace("https://survey.stateofcss.example/2025/", "the survey site"), "source [1]: no URL"),
    ("publisher", GOOD_SOURCES.replace("2025 — Devographics", "2025, Devographics"), "source [1]: no publisher"),
    ("published", GOOD_SOURCES.replace("Published 2026-03-10. ", ""), "source [1]: no publication date"),
    ("accessed", GOOD_SOURCES.replace("Accessed 2026-10-02. https://survey", "https://survey"), "source [1]: no access date"),
    ("tier", GOOD_SOURCES.replace("2025/. Tier 1.", "2025/."), "source [1]: no tier"),
    ("quote", GOOD_SOURCES.replace('Quote: "Tailwind CSS: 62% used"', ""), "source [1]: no supporting quote"),
    ("placeholder", GOOD_SOURCES.replace("https://survey.stateofcss.example/2025/", "https://example.com/<page>"),
     "URL is a placeholder"),
])
def test_each_missing_source_field_is_an_error(tmp_path, field, broken, fragment):
    one_error(tmp_path, brief(sources=broken), fragment)


def test_a_claim_without_a_citation_is_an_error(tmp_path):
    one_error(tmp_path, brief(answer="- Tailwind leads the market (fact) — confidence: high"),
              "claim without a citation in 'Answer in brief'")


def test_a_claim_citing_an_undefined_source_is_an_error(tmp_path):
    one_error(tmp_path, brief(answer="- Tailwind leads (fact) [1][7] — confidence: high"),
              "cites [7] but no source entry defines it")


def test_a_single_source_claim_must_be_tagged(tmp_path):
    one_error(tmp_path, brief(findings="### Adoption\n- 62% used Tailwind (fact) [1] — confidence: medium"),
              "not tagged 'single-source'")


def test_an_old_source_needs_an_age_flag(tmp_path):
    old = GOOD_SOURCES.replace("Published 2026-03-10", "Published 2024-01-15")
    one_error(tmp_path, brief(sources=old), "older than 12 months")
    flagged = "### Adoption\n- 62% used Tailwind (fact) [1 single-source], older than 12 months — confidence: low"
    answer = "- Tailwind is the most used CSS framework (fact) [1][2], [1] older than 12 months \u2014 confidence: medium"
    assert errors_of(tmp_path, brief(sources=old, findings=flagged, answer=answer)) == []


def test_a_directive_in_implications_is_an_error(tmp_path):
    one_error(tmp_path, brief(implications="- We should ship Tailwind classes [1]"), "reads as a directive")


def test_a_url_or_a_publication_date_outside_sources_and_method_is_an_error(tmp_path):
    one_error(tmp_path, brief(unknowns="- The price page https://vendor.example/pricing did not load"),
              "URL outside Sources/Method in 'Unknowns'")
    one_error(tmp_path, brief(contradictions="- [1] Published 2026-03-10 says 62%; [2] differs"),
              "publication date outside Sources")


def test_a_url_under_method_is_allowed(tmp_path):
    method = "Queries run: tailwind usage. Tried and could not open: https://vendor.example/pricing (403)."
    assert errors_of(tmp_path, brief(method=method)) == []


def test_the_header_values_are_checked(tmp_path):
    one_error(tmp_path, brief(status="final"), "Status must be one of")
    one_error(tmp_path, brief(capability="maybe"), "Search capability must be one of")
    one_error(tmp_path, brief(capability="partial (fetch only)", plan="- tailwind usage survey"),
              "requires Status: limited")


# The limited brief.

LIMITED = dict(
    status="limited", capability="none",
    answer="- Nothing established: no search and no page fetch in this session",
    findings="### Prices\n- not established\n### Units of billing\n- not established",
    implications="- none: no finding to draw a consequence from",
    sources="", method="Queries run: none (no search capability).",
    plan="- managed vector database pricing per GB 2026\n- vector database free tier limits",
    background="Assumption: vendors bill by stored vectors or by provisioned capacity (from memory, unchecked).",
)


def test_a_limited_brief_with_no_source_passes(tmp_path):
    proc, data = run(tmp_path, brief(**LIMITED))
    assert proc.returncode == 0, data["errors"]
    assert data["counts"]["sources"] == 0


def test_a_full_brief_with_no_source_fails(tmp_path):
    full = dict(LIMITED, status="draft", capability="full", plan=None)
    one_error(tmp_path, brief(**full), "no source entries found")


def test_a_limited_brief_without_a_query_plan_fails(tmp_path):
    one_error(tmp_path, brief(**dict(LIMITED, plan=None)), "needs a query plan")


def test_a_limited_brief_with_no_source_has_no_implication(tmp_path):
    from_memory = "- Usage-metered pricing makes the cost ceiling depend on traffic"
    one_error(tmp_path, brief(**dict(LIMITED, implications=from_memory)), "has no implication")


def test_a_limited_brief_claim_from_memory_still_needs_a_citation(tmp_path):
    one_error(tmp_path, brief(**dict(LIMITED, answer="- Vendors bill per stored vector (fact)")),
              "claim without a citation")


def test_not_established_is_not_a_claim_in_a_full_brief_either(tmp_path):
    findings = ("### Adoption\n- 62% used Tailwind (fact) [1 single-source] — confidence: medium\n"
                "### Pricing\n- not established: every pricing page needed a login")
    assert errors_of(tmp_path, brief(findings=findings)) == []


# A figure without a citation: "Contradictions" and "Implications" only.

def test_a_figure_without_a_citation_in_contradictions_is_an_error(tmp_path):
    one_error(tmp_path, brief(contradictions="- A separate detail figure reported 1.7%; the survey says more"),
              "figure without a citation in 'Contradictions'")


def test_a_figure_without_a_citation_in_implications_is_an_error(tmp_path):
    one_error(tmp_path, brief(implications="- Paid layers observed cluster around $299"),
              "figure without a citation in 'Implications for positioning'")


def test_a_cited_figure_in_those_sections_passes(tmp_path):
    text = brief(contradictions="- [1] reports 62%; [2] counts 41,203,118 downloads. Likely reason: method.",
                 implications="- A share of 62% [1] means most of the audience already knows the utility classes")
    assert errors_of(tmp_path, text) == []


def test_a_year_alone_is_not_a_figure(tmp_path):
    text = brief(implications="- A library launching in 2026 meets an audience that already uses utility classes [1]",
                 contradictions="- none found in 2025 or 2026 sources")
    assert errors_of(tmp_path, text) == []


def test_unknowns_are_never_checked_for_figures(tmp_path):
    unknowns = ("- The price of the 3 paid tiers above $299 per year could not be read without a login\n"
                "- Whether the 1.7% share counts weekly or monthly users\n"
                "- Downloads before 2024-01 are not in the registry API")
    assert errors_of(tmp_path, brief(unknowns=unknowns)) == []


# Usage errors: on stderr, exit 2, nothing on stdout, no report.

@pytest.mark.parametrize("argv, fragment", [
    ([], "--file"),
    (["--file"], "--file"),
    (["--file", "brief.md", "--today"], "--today"),
    (["--file", "brief.md", "--today", "02/10/2026"], "--today is not a date"),
    (["--file", "brief.md", "--recency-months", "x"], "--recency-months"),
    (["--file", "missing.md"], "cannot read --file missing.md"),
    (["--file", "brief.md", "--json"], "unrecognized arguments"),
])
def test_usage_errors_go_to_stderr_with_exit_2(tmp_path, argv, fragment):
    (tmp_path / "brief.md").write_text(brief(), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--report", "r.json", *argv],
                          cwd=tmp_path, capture_output=True, text=True)
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert fragment in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "r.json").exists()


def test_help_exits_0():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "--file <path>" in proc.stdout


# The --report record.

def test_the_report_record_has_the_convention_shape(tmp_path):
    (tmp_path / "brief.md").write_text(brief(answer="- Tailwind leads (fact)"), encoding="utf-8")
    proc, data = run(tmp_path, None, "--file", "brief.md", "--today", TODAY, "--report", "check.json")
    assert proc.returncode == 1
    record = json.loads((tmp_path / "check.json").read_text(encoding="utf-8"))
    assert set(record) == {"script", "date", "arguments", "ok", "summary", "errors", "warnings", "counts"}
    assert record["script"] == "check_brief.py"
    assert record["arguments"] == {"--file": "brief.md", "--today": TODAY}
    assert record["ok"] is False and record["errors"] == data["errors"]
    assert record["summary"] == data["summary"] == "check_brief FAILED: 1 error"


def test_the_report_is_written_when_the_check_passes(tmp_path):
    # No --today here: the script counts from the system date, so the source is dated relative to it (two
    # months before, inside the 6-month threshold given below) and never by a fixed date that ages out.
    today = datetime.date.today()
    published = (today - datetime.timedelta(days=60)).isoformat()
    sources = GOOD_SOURCES.replace("Published 2026-03-10", f"Published {published}").replace(
        "Accessed 2026-10-02", f"Accessed {today.isoformat()}")
    (tmp_path / "brief.md").write_text(brief(sources=sources), encoding="utf-8")
    proc, data = run(tmp_path, None, "--file=brief.md", "--recency-months", "6", "--report", "check.json")
    assert proc.returncode == 0, data
    record = json.loads((tmp_path / "check.json").read_text(encoding="utf-8"))
    assert record["ok"] is True and record["errors"] == []
    assert record["arguments"] == {"--file": "brief.md", "--recency-months": "6"}

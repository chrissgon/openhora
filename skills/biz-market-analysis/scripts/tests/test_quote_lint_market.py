"""Tests for the figure_not_in_quote check of skills/biz-market-analysis/scripts/lint_market.py.
Offline; every name and number below is fictional.

Run: uv run --with pytest pytest skills/biz-market-analysis/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LINT_MARKET = "skills/biz-market-analysis/scripts/lint_market.py"

SOURCES = (
    '[1] Acme Stats, 2026, 2026-11-01, https://stats.example/a, Tier 1, "a partir de 4 100 €"\n'
    '[2] Beta Survey, 2026, 2026-11-01, https://survey.example/b, Tier 2, "11,5% das empresas, €15,00/mês"\n'
    "[3] Gamma Page, undated, 2026-11-01, https://gamma.example/c, Tier 3, no quote here\n"
)


def lint(tmp_path: Path, body: str, *args: str, sources_heading: str = "Sources") -> list[dict]:
    doc = tmp_path / "market.md"
    doc.write_text(body + f"\n## {sources_heading}\n" + SOURCES, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / LINT_MARKET), "--file", str(doc), *args],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode in (0, 1), r.stderr
    return [f for f in json.loads(r.stdout)["findings"] if f["check"] == "figure_not_in_quote"]


def test_figure_present_in_the_quote_passes_with_each_equivalence(tmp_path):
    body = ("## Summary\n- Plans start at €4,100 [1]\n- 11.5% of firms [2]\n- Retainer €15/month [2]\n")
    assert lint(tmp_path, body) == []


def test_figure_absent_from_the_quote_is_reported_and_either_quote_will_do(tmp_path):
    body = "## Summary\n- Plans start at €9,900 [1]\n- Up to €4,100 or 11.5% [1][2]\n"
    found = lint(tmp_path, body)
    assert len(found) == 1
    assert found[0]["line"] == 2 and "9,900" in found[0]["text"] and "[1]" in found[0]["text"]


def test_lines_with_a_label_an_assumption_or_no_quote_are_not_checked(tmp_path):
    body = ("## Summary\n- Total €9,900 [M2]\n- Guess €9,900 (assumed) [1]\n"
            "- Assumption: €9,900 [1]\n- Snippet €9,900 [3]\n- Uncited €9,900\n")
    assert lint(tmp_path, body) == []


def test_method_and_assumptions_are_exempt_but_contradictions_and_summary_are_not(tmp_path):
    body = ("## Method\n- €9,900 [1]\n## Assumptions\n- €9,900 [1]\n"
            "## Contradictions\n- [1] says €9,900\n- [1] says 77% [1]\n## Summary\n- 88% [2]\n")
    found = lint(tmp_path, body)
    assert [f["line"] for f in found] == [6, 7, 9]


def test_translated_headings_are_exempt(tmp_path):
    body = "## Metodo\n- €9,900 [1]\n## Supuestos\n- €9,900 [1]\n## Resumen\n- €9,900 [1]\n"
    found = lint(tmp_path, body, "--sources-heading", "Fuentes",
                 "--quote-free-headings", "Metodo,Supuestos", sources_heading="Fuentes")
    assert [f["line"] for f in found] == [6]

"""The `- Language: <tag>` header line must change neither the return code nor the findings of
skills/biz-market-analysis/scripts/lint_market.py. Offline; every name and number is fictional.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/biz-market-analysis/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT_MARKET = "skills/biz-market-analysis/scripts/lint_market.py"
OWNER = "- Owner: biz-market-analysis\n"
TAGS = ["pt-BR", "en-US"]

HEADER = ("# Market analysis: Booking widget for dental clinics\n\n" + OWNER +
          "- Status: draft\n- Date: 2026-10-01\n- Scope: one country, online\n\n")
PASSING = (
    HEADER +
    "## Summary\n- Phone booking is the main alternative [1]\n\n"
    "## Alternatives and competitors per offer\n### Booking widget\n"
    "| Alternative | Kind | Advertised price (unit, date) | Source |\n|---|---|---|---|\n"
    "| DIY builder | DIY | EUR 10/month (2026) | [1] |\n| Do nothing | do nothing | 0 (staff time) | [2] |\n"
    "| Agency | agency | price not found | [1] |\n\n"
    "## Implications for the next decisions\n- Pricing: what do clinics pay today? [1]\n\n"
    "## Assumptions\n- Assumption: 20% utilisation\n\n## Sources\n[1] x\n[2] y\n")
FAILING = (
    HEADER +
    "## Alternatives and competitors per offer\n### Sites\n"
    "| Alternative | Kind | Advertised price (unit, date) | Source |\n|---|---|---|---|\n"
    "| DIY builder | DIY | EUR 10/month (2026) | [1] |\n| Do nothing | do nothing | 0 (staff time) | [2] |\n"
    "| Agency | agency | Custom pricing | [Acme] |\n| Freelancer | freelancer | price not found | [2,3] |\n\n"
    "## Implications for the next decisions\n- Pricing: charge €50 per month?\n- ICP: which segment? [1]\n\n"
    "## Sources\n[1] a [x]\n")
TRANSLATED_PASSING = (
    "# Analisis de mercado: widget de reservas\n\n" + OWNER + "- Status: borrador\n\n"
    "## Alternativas\n| Alternativa | Precio | Fuente |\n|---|---|---|\n| Nada | 0 | [1] |\n| Web | R$ 99/mes | [1] |\n"
    "| Agencia | precio no encontrado | [2] |\n\n## Implicaciones\n- Precio: cuanto cobrar? [2]\n\n## Fuentes\n[1] x\n")
TRANSLATED_FLAGS = ["--alternatives-heading", "Alternativas", "--implications-heading", "Implicaciones",
                    "--price-column", "precio", "--not-found-label", "precio no encontrado",
                    "--sources-heading", "Fuentes"]


def lint(tmp_path: Path, sub: str, text: str, *flags: str):
    folder = tmp_path / sub
    folder.mkdir()
    doc = folder / "doc.md"
    doc.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / LINT_MARKET), "--file", str(doc), *flags],
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
@pytest.mark.parametrize("text,flags,passing", [
    (PASSING, (), True), (FAILING, (), False), (TRANSLATED_PASSING, tuple(TRANSLATED_FLAGS), True)])
def test_language_line_changes_neither_code_nor_findings(tmp_path, tag, text, flags, passing):
    base_rc, base = lint(tmp_path, "base", text, *flags)
    new_rc, new = lint(tmp_path, "with", with_language(text, tag), *flags)
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert unshift(new) == base
    if passing:
        assert new["ok"] is True and new["findings"] == [] and new["missing_headings"] == []


def test_failing_document_keeps_its_known_findings_with_the_language_line(tmp_path):
    _, report = lint(tmp_path, "x", with_language(FAILING, "pt-BR"))
    found = [(f["check"], f["text"]) for f in report["findings"]]
    assert ("price_cell", "Custom pricing") in found
    assert ("bad_citation", "[Acme]") in found
    assert any(c == "implications_currency" for c, _ in found)
    assert len(found) == 5


def test_language_line_directly_after_the_title_also_changes_nothing(tmp_path):
    title = "# Market analysis: Booking widget for dental clinics\n\n"
    rc, report = lint(tmp_path, "x", PASSING.replace(title, title + "- Language: en-US\n", 1))
    assert rc == 0 and report["ok"] is True

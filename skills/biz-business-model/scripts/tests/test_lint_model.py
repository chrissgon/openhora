"""Tests for skills/biz-business-model/scripts/lint_model.py. Offline; every name and number is fictional.

Run: uv run --with pytest pytest skills/biz-business-model/scripts/tests/test_lint_model.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/biz-business-model/scripts/lint_model.py"

MODEL = """# Business model: Lousa for teachers

- Owner: biz-business-model
- Language: en
- Status: hypothesis
- Date: 2026-11-11
- Offer: lesson app; who pays: the teacher; goal: 10 paying teachers (state file, 2026-11-11)

## What stays free
- A free trial of three lessons stays (state file, 2026-11-11)

## Revenue model
- Unit: teacher per month because the price grows with use [1]
- Price: see docs/business/pricing.md (proposed)

## Costs
| Cost | Kind | Value | From |
|---|---|---|---|
| model usage | variable per unit | R$ 7,60 | M2 |
| card processor | fee % | 4,99% | 7 |
| hosting | fixed per period | R$ 120,00 | user |
| tax | tax % | unknown | unknown |
| support | hours | 0,5 | Assumption: owner guess |

## Unit economics
| Metric | Price 1 | From |
|---|---|---|
| Contribution per unit | 29.45 BRL | M1 |
- Reading: contribution before tax is 29.45 BRL [M1]

## Path to the goal
- Customers needed: 10 [M1]

## Assumptions
- Assumption: 0,5 hours per teacher per month

## Sources
[1] Rival price page, Rival Example. Published undated. Accessed 2026-11-11. https://rival.example/price. Tier 1. fact. Quote: "R$ 39,90 per month"

## Method
- M1: unit_economics.py with the inputs of the Costs table on standard input
"""

PRICING = """# Pricing: Lousa for teachers

- Owner: biz-business-model
- Language: en
- Status: hypothesis
- Date: 2026-11-11
- Decision: OPEN-1: which price do you want to test first?
- Ready: no

## Anchors
| Alternative | Price (currency, unit, term, date) | What the buyer gets | Source |
|---|---|---|---|
| Rival app | R$ 19,90 per month for 12 months, renewing at R$ 39,90 per month (2026-11) | lesson packs | [1] |
| Teachkit | US$ 9 per month (2026-11) | templates | [2] |
| Aulapronta | price not found | n/a | [2] |

## Price pressure
- A marketplace post drew 149 proposals from R$ 50 up [2]

## Proposed price
- R$ 39,00 per teacher per month (recurring): above the cost floor of R$ 8,00 [M1]; against [1] and [2]

## Price test
- How: paid pilot offer; with: self-employed teachers; how many: 8
- Questions (past behaviour and current spend only): 1. What did you spend on materials last month?
- Validated if: at least 3 of 8 pay for the first month
- Rejected if: fewer than 2 of 8 pay
- Results: empty

## Assumptions
none

## Sources
[1] Rival price page, Rival Example. Published undated. Accessed 2026-11-11. https://rival.example/price. Tier 1. fact. Quote: "R$ 19,90"
[2] Teachkit page, Teachkit Example. Published undated. Accessed 2026-11-11. https://teachkit.example/price. Tier 1. fact. Quote: "US$ 9"
"""


def lint(tmp_path, text, kind, *args):
    doc = tmp_path / f"{kind}.md"
    doc.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(LINT), "--file", str(doc), "--kind", kind, *args],
                       capture_output=True, text=True, timeout=60)
    return r, (json.loads(r.stdout) if r.stdout.strip() else None)


def checks(report):
    return sorted(f["check"] for f in report["findings"])


def test_passing_model(tmp_path):
    r, rep = lint(tmp_path, MODEL, "model")
    assert r.returncode == 0, rep
    assert rep["ok"] is True and rep["findings"] == []


def test_passing_pricing(tmp_path):
    r, rep = lint(tmp_path, PRICING, "pricing")
    assert r.returncode == 0, rep
    assert rep["ok"] is True


def test_decided_price_passes_without_ready_no(tmp_path):
    text = PRICING.replace("OPEN-1: which price do you want to test first?",
                           'decided by the user on 2026-11-12: "go with R$ 39,00"').replace("Ready: no", "Ready: yes")
    r, rep = lint(tmp_path, text, "pricing")
    assert r.returncode == 0, rep


def test_model_status(tmp_path):
    r, rep = lint(tmp_path, MODEL.replace("- Status: hypothesis\n", ""), "model")
    assert r.returncode == 1 and checks(rep) == ["status"]


def test_model_missing_section(tmp_path):
    r, rep = lint(tmp_path, MODEL.replace("## Path to the goal", "## Something else"), "model")
    assert r.returncode == 1
    assert checks(rep) == ["missing_section"]
    assert "Path to the goal" in rep["findings"][0]["text"]


def test_model_cost_without_origin(tmp_path):
    for origin in ("", "-", "from memory"):
        text = MODEL.replace("| hosting | fixed per period | R$ 120,00 | user |",
                             f"| hosting | fixed per period | R$ 120,00 | {origin} |")
        r, rep = lint(tmp_path, text, "model")
        assert r.returncode == 1, origin
        assert checks(rep) == ["cost_without_origin"], origin
        assert "hosting" in rep["findings"][0]["text"]


def test_model_unit_economics_not_scripted(tmp_path):
    no_table = MODEL.replace("| Metric | Price 1 | From |\n|---|---|---|\n| Contribution per unit | 29.45 BRL | M1 |\n",
                             "- Contribution is about 29 per unit [M1]\n")
    r, rep = lint(tmp_path, no_table, "model")
    assert r.returncode == 1 and "unit_economics_not_scripted" in checks(rep)
    no_label = MODEL.replace("| M1 |", "| computed |").replace("[M1]", "[1]")
    r, rep = lint(tmp_path, no_label, "model")
    assert "unit_economics_not_scripted" in checks(rep)


def test_pricing_missing_section(tmp_path):
    r, rep = lint(tmp_path, PRICING.replace("## Price pressure", "## Pressure").replace("## Proposed price", "## Price"),
                  "pricing")
    assert r.returncode == 1 and checks(rep) == ["missing_section"]


def test_pricing_anchor_cell(tmp_path):
    for cell in ("cheap", "R$ 19,90", "about 20 per month", "free"):
        text = PRICING.replace("US$ 9 per month (2026-11)", cell)
        r, rep = lint(tmp_path, text, "pricing")
        assert r.returncode == 1, cell
        assert "anchor_cell" in checks(rep), cell


def test_pricing_anchor_without_source(tmp_path):
    text = PRICING.replace("| templates | [2] |", "| templates |  |")
    r, rep = lint(tmp_path, text, "pricing")
    assert r.returncode == 1 and "anchor_without_source" in checks(rep)


def test_pricing_decision(tmp_path):
    r, rep = lint(tmp_path, PRICING.replace("- Decision: OPEN-1: which price do you want to test first?\n", ""),
                  "pricing")
    assert checks(rep) == ["decision"] and r.returncode == 1
    r, rep = lint(tmp_path, PRICING.replace("OPEN-1: which price do you want to test first?", "R$ 39,00 is the price"),
                  "pricing")
    assert checks(rep) == ["decision"]
    r, rep = lint(tmp_path, PRICING.replace("Ready: no", "Ready: yes"), "pricing")
    assert checks(rep) == ["decision"]
    r, rep = lint(tmp_path, PRICING.replace("- Ready: no\n", ""), "pricing")
    assert checks(rep) == ["decision"]


def test_pricing_hypothetical_question_and_criteria(tmp_path):
    text = PRICING.replace("1. What did you spend on materials last month?", "1. Would you pay R$ 39,00 for this?")
    r, rep = lint(tmp_path, text, "pricing")
    assert r.returncode == 1 and checks(rep) == ["hypothetical_question"]
    text = PRICING.replace("- Rejected if: fewer than 2 of 8 pay\n", "")
    r, rep = lint(tmp_path, text, "pricing")
    assert checks(rep) == ["missing_criteria"]
    r, rep = lint(tmp_path, PRICING.replace("- Validated if: at least 3 of 8 pay for the first month\n", ""), "pricing")
    assert checks(rep) == ["missing_criteria"]


def test_bad_citation_and_uncited_figure(tmp_path):
    r, rep = lint(tmp_path, MODEL.replace("[1]\n- Price", "[source one]\n- Price"), "model")
    assert "bad_citation" in checks(rep)
    r, rep = lint(tmp_path, MODEL.replace("- Customers needed: 10 [M1]", "- Customers needed: 10, margin 75%"),
                  "model")
    assert r.returncode == 1 and checks(rep) == ["uncited_figure"]
    r, rep = lint(tmp_path, PRICING.replace("above the cost floor of R$ 8,00 [M1]; against [1] and [2]",
                                                  "above the cost floor of R$ 8,00"), "pricing")
    assert "uncited_figure" in checks(rep)


def test_assumption_label_makes_a_figure_acceptable(tmp_path):
    r, rep = lint(tmp_path, MODEL.replace("- Customers needed: 10 [M1]",
                                          "- Assumption: about 75% of trials convert"), "model")
    assert r.returncode == 0, rep


def test_translated_headings_and_labels(tmp_path):
    text = (PRICING.replace("## Anchors", "## Ancoras").replace("## Proposed price", "## Preco proposto")
            .replace("## Price test", "## Teste de preco").replace("## Assumptions", "## Premissas")
            .replace("## Sources", "## Fontes").replace("per month", "por mes").replace("per teacher", "por professor")
            .replace("Decision:", "Decisao:").replace("Ready:", "Pronto:").replace("OPEN-1", "OPEN-1")
            .replace("Validated if", "Valido se").replace("Rejected if", "Rejeitado se")
            .replace("Status: hypothesis", "Status: hipotese").replace("| Source |", "| Fonte |")
            .replace("Price (currency", "Preco (currency").replace("price not found", "preco nao encontrado")
            .replace("Pronto: no", "Pronto: nao"))
    args = ["--status-words", "hipotese", "--anchors-heading", "Ancoras", "--proposed-heading", "Preco proposto",
            "--test-heading", "Teste de preco", "--assumptions-heading", "Premissas", "--sources-heading", "Fontes",
            "--per-words", "por,/", "--decision-label", "Decisao", "--ready-label", "Pronto", "--no-word", "nao",
            "--validated-label", "valido se", "--rejected-label", "rejeitado se", "--price-column", "preco",
            "--source-column", "fonte", "--not-found-label", "preco nao encontrado"]
    r, rep = lint(tmp_path, text, "pricing", *args)
    assert r.returncode == 0, rep


def test_usage_errors_exit_2(tmp_path):
    r = subprocess.run([sys.executable, str(LINT), "--file", str(tmp_path / "missing.md"), "--kind", "model"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and r.stdout == ""
    r = subprocess.run([sys.executable, str(LINT), "--file", "x.md", "--kind", "other"], capture_output=True,
                       text=True, timeout=60)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, str(LINT), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "lint" in r.stdout.lower()

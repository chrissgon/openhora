"""Tests for skills/biz-gtm/scripts/lint_gtm.py. Offline; every name and number below is fictional.

Run: uv run --with pytest pytest skills/biz-gtm/scripts/tests
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/biz-gtm/scripts/lint_gtm.py"

GOOD = """# Go-to-market: Lousa for English teachers

- Owner: biz-gtm
- Language: en
- Status: hypothesis
- Date: 2026-11-11
- Goal: first 10 paying teachers in three months (state file, 2026-11-11)
- Hours per week: 4 (state file, 2026-11-11); paid budget: R$ 0 per month (state file, 2026-11-11)

## Motion
- Teachers: self-serve, because a teacher can buy alone [1]

## Channels
| Channel | Reach | Total |
|---|---|---|
| Own contacts | 5 [1] | 5 |
- Chosen: own contacts [M1]

## Channel rules
| Channel | Promotion allowed as planned | Rule (quote) | Source |
|---|---|---|---|
| Own contacts | yes | "agreed to receive news" | [1] |
| A teachers group | not researched yet | not researched yet | not researched yet |

## Launch readiness
| Condition | Done (yes, no, unknown) | Evidence |
|---|---|---|
| A teacher generates a first lesson alone | yes | state file, 2026-11-11 |
| Support answers | unknown | none |

## First four weeks
| Week | Action | Channel | Hours | Output |
|---|---|---|---|---|
| 1 | Send the launch note | Own contacts | 2 | 300 messages |
| 1 | Answer replies | Own contacts | 1.5 | replies |
| 2 | Follow up | Own contacts | 3 | follow-ups |
- Hours per week: 1: 3.5, 2: 3.0 of 4

## Measurement
| Channel | Metric | Baseline window | Read in week | Continue if | Stop if |
|---|---|---|---|---|---|
| Own contacts | sign-ups | weeks 1-4 | 4 | at least one sign-up | none after 4 weeks |

## Left out
- A bought list: it breaks privacy law (not researched yet)

## Assumptions
- none

## Sources
[1] Opt-in note, Owner. Published undated. Accessed 2026-11-11. file: docs/notes.md. Tier 1. fact. Quote: "agreed"

## Method
- M1: rank.py with the scores
"""


def run(text: str, tmp_path: Path, *args: str):
    doc = tmp_path / "gtm.md"
    doc.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(LINT), "--file", str(doc), *args],
                       capture_output=True, text=True, timeout=60)
    return r, json.loads(r.stdout) if r.stdout else {}


def checks(report):
    return sorted(f["check"] for f in report["findings"])


def test_passing_fixture_reports_hours(tmp_path):
    r, rep = run(GOOD, tmp_path)
    assert r.returncode == 0, rep
    assert rep["ok"] is True
    assert rep["capacity"] == 4.0
    assert rep["hours_per_week"] == {"1": 3.5, "2": 3.0}


def test_hours_sum_across_rows_of_the_same_week(tmp_path):
    text = GOOD.replace("| 2 | Follow up | Own contacts | 3 |", "| 1 | Follow up | Own contacts | 3 |")
    r, rep = run(text, tmp_path)
    assert r.returncode == 1
    assert rep["hours_per_week"] == {"1": 6.5}
    assert checks(rep) == ["hours_over_capacity"]


def test_status_missing(tmp_path):
    r, rep = run(GOOD.replace("Status: hypothesis", "Status: draft"), tmp_path)
    assert checks(rep) == ["status"]


def test_validated_is_not_a_status_of_a_plan(tmp_path):
    r, rep = run(GOOD.replace("Status: hypothesis", "Status: validated"), tmp_path)
    assert checks(rep) == ["status"]


def test_missing_section(tmp_path):
    r, rep = run(GOOD.replace("## Left out", "## Dropped"), tmp_path)
    assert checks(rep) == ["missing_section"]
    assert "Left out" in rep["findings"][0]["text"]


def test_no_capacity(tmp_path):
    text = GOOD.replace("- Hours per week: 4 (state file, 2026-11-11); ", "- ")
    r, rep = run(text, tmp_path)
    assert checks(rep) == ["no_capacity"]
    assert rep["capacity"] is None


def test_bad_hours_cell(tmp_path):
    r, rep = run(GOOD.replace("| 2 | Follow up | Own contacts | 3 |", "| 2 | Follow up | Own contacts | a few |"),
                 tmp_path)
    assert checks(rep) == ["bad_hours"]


def test_rules_cell_empty_source(tmp_path):
    text = GOOD.replace('| Own contacts | yes | "agreed to receive news" | [1] |',
                        '| Own contacts | yes | "agreed to receive news" |  |')
    r, rep = run(text, tmp_path)
    assert checks(rep) == ["rules_cell"]


def test_measurement_rule_empty(tmp_path):
    text = GOOD.replace("| at least one sign-up | none after 4 weeks |", "| at least one sign-up |  |")
    r, rep = run(text, tmp_path)
    assert checks(rep) == ["measurement_rule"]


def test_readiness_done_not_a_word(tmp_path):
    r, rep = run(GOOD.replace("| Support answers | unknown |", "| Support answers | maybe |"), tmp_path)
    assert checks(rep) == ["readiness_done"]


def test_bad_citation_and_uncited_figure(tmp_path):
    text = GOOD.replace("- Teachers: self-serve, because a teacher can buy alone [1]",
                        "- Teachers: self-serve, because 40% buy alone [source A]")
    r, rep = run(text, tmp_path)
    assert checks(rep) == ["bad_citation", "uncited_figure"]


def test_translated_headings_and_labels(tmp_path):
    text = (GOOD.replace("Hours per week:", "Horas por semana:").replace("## First four weeks", "## Quatro semanas")
            .replace("| Week |", "| Semana |").replace("| Hours |", "| Horas |")
            .replace("## Channel rules", "## Regras").replace("| Source |", "| Fonte |")
            .replace("not researched yet", "ainda nao pesquisado")
            .replace("## Launch readiness", "## Prontidao").replace("Done (yes, no, unknown)", "Feito")
            .replace("| yes |", "| sim |").replace("| unknown |", "| nao sei |")
            .replace("## Measurement", "## Medicao").replace("Continue if", "Continuar se").replace("Stop if", "Parar se"))
    r, rep = run(text, tmp_path, "--hours-label", "Horas por semana", "--plan-heading", "Quatro semanas",
                 "--week-column", "Semana", "--hours-column", "Horas", "--rules-heading", "Regras",
                 "--source-column", "Fonte", "--not-researched-label", "ainda nao pesquisado",
                 "--readiness-heading", "Prontidao", "--done-column", "Feito", "--done-words", "sim,nao,nao sei",
                 "--measurement-heading", "Medicao", "--continue-label", "continuar se", "--stop-label", "parar se",
                 "--required-headings",
                 "Motion,Channels,Regras,Prontidao,Quatro semanas,Medicao,Left out,Assumptions,Sources,Method")
    assert r.returncode == 0, rep
    assert rep["hours_per_week"] == {"1": 3.5, "2": 3.0}


def test_bad_arguments_and_unreadable_file(tmp_path):
    r = subprocess.run([sys.executable, str(LINT), "--file", str(tmp_path / "missing.md")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, str(LINT), "--bogus"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 2
    r = subprocess.run([sys.executable, str(LINT), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0

"""Tests for skills/design-ux-flows/scripts/lint_flows.py: the --report file and the screen-states check.

Run: uv run --with pytest pytest skills/design-ux-flows/scripts/tests/test_lint_flows.py

Offline; every product, feature, screen and flow below is fictional.
"""
from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

LINT = Path(__file__).resolve().parents[1] / "lint_flows.py"

PRD = """# PRD: Tallybook

## Features

- F-1: Receipt list. Outcome: the member sees every receipt. Priority: must. Phase: P-1. Source: brief
- F-2: Weekly digest. Outcome: the member gets a digest email every Monday. Priority: must. Phase: P-1. Source: brief
- F-3: Shared folders. Outcome: two members share receipts. Priority: later. Phase: P-2. Source: brief
"""

LIST_STATES = "loading, empty (no receipt yet), error (the list failed to load), success"
MAIL_STATES = "sent, error (delivery failed: retried for 24 hours)"

FLOWS = """# UX flows: Tallybook, phase P-1

- Phase covered: P-1
- Spec pending: {spec_pending}

## Summary

Two nodes, two screens and two flows.

## Sources

- docs/product/prd.md

## Information architecture

- IA-1: Receipts. Parent: none. URL: /receipts. Filled by: generated. Source: F-1

## Screens

- SCREEN-1: Receipt list. Purpose: show every receipt. Regions: list, filter. States: {list_states}. Breakpoints: one column when narrow. Source: F-1
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


def run(tmp_path, list_states=LIST_STATES, mail_states=MAIL_STATES, extra=(), spec_pending="none", edit=None):
    flows = tmp_path / "flows.md"
    prd = tmp_path / "prd.md"
    body = FLOWS.format(list_states=list_states, mail_states=mail_states, spec_pending=spec_pending)
    flows.write_text(edit(body) if edit else body, encoding="utf-8")
    prd.write_text(PRD, encoding="utf-8")
    proc = subprocess.run([sys.executable, str(LINT), "--file", str(flows), "--prd", str(prd), "--phase", "P-1",
                           *extra], capture_output=True, text=True)
    return proc, flows, prd


def test_a_complete_document_is_ok(tmp_path):
    proc, _, _ = run(tmp_path)
    out = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stdout
    assert out == {"ok": True, "counts": {"IA": 1, "SCREEN": 2, "FLOW": 2, "covered": 2}, "errors": [],
                   "summary": "lint_flows ok: 0 errors; 1 IA nodes, 2 screens, 2 flows, 2 features covered; phase P-1"}


def test_report_writes_the_record_of_the_evidence_convention(tmp_path):
    report = tmp_path / "flows.lint.json"
    proc, flows, prd = run(tmp_path, extra=("--report", str(report), "--json"))
    assert proc.returncode == 0, proc.stdout
    text = report.read_text(encoding="utf-8")
    record = json.loads(text)
    printed = json.loads(proc.stdout)
    assert text.endswith("\n")
    assert record == {"script": "lint_flows.py", "date": datetime.date.today().isoformat(),
                      "arguments": {"--file": str(flows), "--prd": str(prd), "--phase": "P-1", "--json": True},
                      "ok": True, "summary": printed["summary"], "errors": [],
                      "counts": {"IA": 1, "SCREEN": 2, "FLOW": 2, "covered": 2}}
    # stdout keeps its shape: the report adds a file, it does not change what is printed
    assert printed == {"ok": True, "summary": record["summary"], "counts": record["counts"], "errors": []}


def test_unknown_flags_and_usage_errors_go_to_stderr(tmp_path):
    proc, _, _ = run(tmp_path, extra=("--reprot", str(tmp_path / "x.json")))
    assert proc.returncode == 2 and proc.stdout == "" and "unknown argument '--reprot'" in proc.stderr
    assert not (tmp_path / "x.json").exists()
    proc = subprocess.run([sys.executable, str(LINT)], capture_output=True, text=True)
    assert proc.returncode == 2 and proc.stdout == "" and "--file" in proc.stderr


def test_report_records_a_failing_run(tmp_path):
    report = tmp_path / "flows.lint.json"
    proc, _, _ = run(tmp_path, mail_states="sent, opened", extra=("--report", str(report)))
    record = json.loads(report.read_text(encoding="utf-8"))
    assert proc.returncode == 1
    assert record["ok"] is False
    assert record["errors"] == json.loads(proc.stdout)["errors"]


def test_no_report_file_without_the_flag(tmp_path):
    run(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["flows.md", "prd.md"]


def test_report_without_a_value_is_a_usage_error(tmp_path):
    proc, _, _ = run(tmp_path, extra=("--report",))
    assert proc.returncode == 2
    assert "--report needs a value" in proc.stderr


def test_report_that_cannot_be_written_is_a_usage_error(tmp_path):
    proc, _, _ = run(tmp_path, extra=("--report", str(tmp_path / "absent" / "flows.lint.json")))
    assert proc.returncode == 2
    assert "cannot write the report" in proc.stderr


def test_a_message_screen_without_an_error_state_fails(tmp_path):
    proc, _, _ = run(tmp_path, mail_states="sent, opened")
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert out["errors"] == ["screen-states: SCREEN-2 names no empty or error state in States: "
                             "(for a message, the error state is the delivery failure)"]


def test_an_empty_state_alone_is_enough(tmp_path):
    proc, _, _ = run(tmp_path, list_states="loading, Empty (no receipt yet)")
    assert proc.returncode == 0, proc.stdout


def test_the_word_must_be_in_states_not_elsewhere_in_the_screen(tmp_path):
    # "error" in the next field (Breakpoints) or inside another word ("errorless") does not count
    proc, _, _ = run(tmp_path, list_states="loading, errorless, success. Breakpoints: the error banner stacks")
    out = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert [e for e in out["errors"] if e.startswith("screen-states: SCREEN-1")]


def test_a_missing_spec_pending_line_is_reported(tmp_path):
    proc, _, _ = run(tmp_path, edit=lambda s: s.replace("- Spec pending: none\n", ""))
    assert proc.returncode == 1
    assert 'missing the "- Spec pending:" header line' in json.loads(proc.stdout)["errors"]


def test_a_spec_pending_value_must_be_none_or_ids(tmp_path):
    proc, _, _ = run(tmp_path, spec_pending="soon")
    assert any(e.startswith("spec-pending-line") for e in json.loads(proc.stdout)["errors"])


def test_every_step_of_a_spec_pending_feature_must_carry_the_mark(tmp_path):
    proc, _, _ = run(tmp_path, spec_pending="F-2")
    assert json.loads(proc.stdout)["errors"] == [
        'spec-pending-steps: FLOW-2 step 1 lacks "spec pending" (F-2 has no spec)',
        'spec-pending-steps: FLOW-2 step 2 lacks "spec pending" (F-2 has no spec)']


def test_marked_steps_of_a_spec_pending_feature_pass(tmp_path):
    marked = lambda s: s.replace("→ follows the link;", "→ follows the link (spec pending);").replace(
        "SCREEN-1: sees the list. End: the list is shown. Failures: step 1: the email", "SCREEN-1: sees the list (spec pending). End: the list is shown. Failures: step 1: the email")
    proc, _, _ = run(tmp_path, spec_pending="F-2", edit=marked)
    assert proc.returncode == 0, proc.stdout

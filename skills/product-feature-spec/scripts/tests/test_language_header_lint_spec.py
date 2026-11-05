"""A `- Language: <tag>` header line in the specification changes nothing lint_spec.py decides.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/product-feature-spec/scripts/tests

Offline; every name and number below is fictional. The line sits right after the `- Owner:` header line. One output
depends on the position of a line by design: a finding that names a line number ("line 21 in ...", "empty bullet on
lines [...]") moves down by exactly one, because the header grew by one line; no verdict and no other finding moves.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/product-feature-spec/scripts/lint_spec.py"
TAGS = ("pt-BR", "en-US")


def spec(nfr: str = "Results appear within 200 ms of the last keystroke",
         open_question: str = "Should search cover drafts? Blocks: nothing. Recommended: no, drafts are private",
         heading: str = "Functional requirements") -> str:
    return f"""# Feature specification: Search

- Owner: product-feature-spec
- Status: draft
- Date: 2026-01-05
- Feature of: the search brief

## Summary

## Goal and users

## Scope

## Sources

## {heading}

- REQ-1: Show matching pages when the reader types a query. Source: PRD F-1.

## Non-functional requirements

- NFR-1: {nfr}. Source: PRD M-2, measured 2026-01-05.

## Constraints

## Edge cases

- EDGE-1: empty query → show no results

## Acceptance criteria

- AC-1:
  Given an index with one page
  When the reader types its title
  Then the page is listed
  Covers: REQ-1, NFR-1

## Assumptions

## Open questions

- OPEN-1: {open_question}.

## Readiness
"""


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def run(path: Path, text: str, *extra: str) -> subprocess.CompletedProcess:
    path.write_text(text, encoding="utf-8")
    return subprocess.run([sys.executable, str(LINT), "--file", str(path), *extra], capture_output=True, text=True,
                          timeout=60)


def same_result(a: subprocess.CompletedProcess, b: subprocess.CompletedProcess) -> None:
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


def test_the_baseline_document_has_the_header_the_tests_edit():
    assert "- Owner: product-feature-spec" in spec() and "- Language:" not in spec()
    assert with_language(spec(), "pt-BR").splitlines()[2:5] == [
        "- Owner: product-feature-spec", "- Language: pt-BR", "- Status: draft"]


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_spec_passes_the_same_with_the_language_line(tmp_path, tag):
    doc = tmp_path / "spec.md"
    plain = run(doc, spec())
    assert plain.returncode == 0, plain.stdout
    with_line = run(doc, with_language(spec(), tag))
    assert "- Language: " + tag in doc.read_text(encoding="utf-8")
    same_result(plain, with_line)
    out = json.loads(with_line.stdout)
    assert out["ok"] is True and out["errors"] == [] and out["warnings"] == []
    assert out["counts"] == {"REQ": 1, "NFR": 1, "EDGE": 1, "AC": 1, "ASSUMPTION": 0, "OPEN": 1}


@pytest.mark.parametrize("tag", TAGS)
def test_failing_specs_fail_with_the_same_findings(tmp_path, tag):
    doc = tmp_path / "spec.md"
    cases = {
        "an NFR without a number": (spec(nfr="Results appear soon after REQ-1 runs"),
                                    ["NFR-1 states no number: give the sourced figure, or move it to an OPEN with a "
                                     "Recommended value"]),
        "an OPEN without a recommendation": (spec(open_question="Should search cover drafts? Blocks: nothing"),
                                             ["OPEN-1 has no Recommended: entry"]),
        "a missing section": (spec().replace("## Constraints\n\n", ""), ["missing section '## Constraints'"]),
    }
    for label, (text, errors) in cases.items():
        plain = run(doc, text)
        assert plain.returncode == 1 and json.loads(plain.stdout)["errors"] == errors, label
        same_result(plain, run(doc, with_language(text, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_a_warning_is_the_same_with_the_language_line(tmp_path, tag):
    doc = tmp_path / "spec.md"
    text = spec().replace("Show matching pages when", "Show fast matching pages when")
    plain = run(doc, text)
    assert plain.returncode == 0 and len(json.loads(plain.stdout)["warnings"]) == 1
    same_result(plain, run(doc, with_language(text, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_the_language_line_is_not_taken_for_a_bullet_of_an_id_section(tmp_path, tag):
    # it sits above the first section: no "empty bullet", no "not '- REQ-n: ...'" and no duplicate-id finding
    doc = tmp_path / "spec.md"
    out = json.loads(run(doc, with_language(spec(), tag)).stdout)
    assert out["errors"] == [] and out["counts"]["REQ"] == 1


@pytest.mark.parametrize("tag", TAGS)
def test_translated_headings_are_read_the_same(tmp_path, tag):
    doc = tmp_path / "spec.md"
    translated = spec(heading="Requisitos funcionais")
    flag = ("--heading", "Functional requirements=Requisitos funcionais")
    plain = run(doc, translated, *flag)
    assert plain.returncode == 0, plain.stdout
    same_result(plain, run(doc, with_language(translated, tag), *flag))
    # without the flag the translated heading is still missing, with and without the line
    bad = run(doc, translated)
    assert json.loads(bad.stdout)["errors"] == ["missing section '## Functional requirements'"]
    same_result(bad, run(doc, with_language(translated, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_a_finding_that_names_a_line_number_moves_down_by_exactly_one(tmp_path, tag):
    doc = tmp_path / "spec.md"
    bullet = "- very long query → cut it at 200 characters"
    text = spec().replace("- EDGE-1: empty query → show no results\n",
                          "- EDGE-1: empty query → show no results\n" + bullet + "\n")
    plain = json.loads(run(doc, text).stdout)["errors"]
    shifted = json.loads(run(doc, with_language(text, tag)).stdout)["errors"]
    n = int(re.match(r"line (\d+) in", plain[0]).group(1))
    assert len(plain) == len(shifted) == 1
    assert shifted == [plain[0].replace(f"line {n} in", f"line {n + 1} in")]
    # the empty bullet finding lists lines the same way
    text = spec().replace("## Assumptions\n", "## Assumptions\n\n-\n")
    plain = json.loads(run(doc, text).stdout)["errors"]
    shifted = json.loads(run(doc, with_language(text, tag)).stdout)["errors"]
    n = int(re.search(r"\[(\d+)\]", plain[0]).group(1))
    assert plain == [f"empty bullet '-' on lines [{n}]: delete those lines"]
    assert shifted == [f"empty bullet '-' on lines [{n + 1}]: delete those lines"]


@pytest.mark.parametrize("tag", TAGS)
def test_the_report_record_is_the_same(tmp_path, tag):
    doc, records = tmp_path / "spec.md", []
    for name, text in (("plain", spec()), ("lang", with_language(spec(), tag))):
        report = tmp_path / f"{name}.json"
        run(doc, text, "--report", str(report))
        records.append(json.loads(report.read_text(encoding="utf-8")))
    assert records[0]["ok"] is True and records[0] == records[1]

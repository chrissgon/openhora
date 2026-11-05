"""A `- Language: <tag>` header line in the messaging document changes nothing lint_messaging.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/mkt-messaging/scripts/tests

Offline; every name and number below is fictional. The line sits right after the `- Owner:` header line.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/mkt-messaging/scripts/lint_messaging.py"
TAGS = ("pt-BR", "en-US")

PROOF = ("The stylesheet is 8 kB gzipped. Evidence: size of the built file. "
         "Method: `gzip -c dist/lintel.css | wc -c`. Date: 2026-03-14. Source: build output.")


def messaging(headline: str = "Small enough to read") -> str:
    return f"""# Messaging: Lintel

- Owner: mkt-messaging
- Status: draft
- Date: 2026-03-14
- Page: the home page

## Summary

## Sources

## Audience

## Promise

## Voice

## Proof points

- PROOF-1: {PROOF}

## Sections

- SECTION-1: Hero. Purpose: say what it is. Proof: none. Headline: A stylesheet for docs. Body: Plain CSS. CTA: Install → /install. Source: README.
- SECTION-2: Size. Purpose: show the weight. Proof: PROOF-1. Headline: {headline}. Body: The whole stylesheet is 8 kB. Demo: the file size next to the built file. Source: PROOF-1.

## Taglines

- Styles you can read

## Words

- Use: stylesheet. Source: README.
- Avoid: blazing

## Open questions

## Assumptions

none

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
    assert "- Owner: mkt-messaging" in messaging() and "- Language:" not in messaging()
    assert with_language(messaging(), "pt-BR").splitlines()[2:5] == [
        "- Owner: mkt-messaging", "- Language: pt-BR", "- Status: draft"]


@pytest.mark.parametrize("tag", TAGS)
def test_a_passing_document_passes_the_same_with_the_language_line(tmp_path, tag):
    doc = tmp_path / "messaging.md"
    plain = run(doc, messaging())
    assert plain.returncode == 0, plain.stdout
    with_line = run(doc, with_language(messaging(), tag))
    assert "- Language: " + tag in doc.read_text(encoding="utf-8")
    same_result(plain, with_line)
    assert json.loads(with_line.stdout)["summary"] == "lint_messaging ok: 0 errors, 1 proofs, 2 sections"


@pytest.mark.parametrize("tag", TAGS)
def test_a_failing_document_fails_with_the_same_findings(tmp_path, tag):
    doc = tmp_path / "messaging.md"
    bad = messaging(headline="Three kilobytes, no more")
    plain = run(doc, bad)
    assert plain.returncode == 1
    assert json.loads(plain.stdout)["errors"] == ["SECTION-2: number Three in the copy is not in any PROOF"]
    same_result(plain, run(doc, with_language(bad, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_a_missing_section_is_still_reported_the_same(tmp_path, tag):
    doc = tmp_path / "messaging.md"
    bad = messaging().replace("## Assumptions\n\nnone\n\n", "")
    plain = run(doc, bad)
    assert json.loads(plain.stdout)["errors"] == ["missing section '## Assumptions'"]
    same_result(plain, run(doc, with_language(bad, tag)))


@pytest.mark.parametrize("tag", TAGS)
def test_the_report_record_is_the_same_apart_from_the_path(tmp_path, tag):
    doc, records = tmp_path / "messaging.md", []
    for name, text in (("plain", messaging()), ("lang", with_language(messaging(), tag))):
        report = tmp_path / f"{name}.json"
        run(doc, text, "--report", str(report))
        record = json.loads(report.read_text(encoding="utf-8"))
        assert record["ok"] is True
        records.append(record)
    assert records[0] == records[1]

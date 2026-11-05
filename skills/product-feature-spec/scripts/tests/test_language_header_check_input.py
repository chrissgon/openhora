"""A `- Language: <tag>` header line in a brief or a PRD changes nothing check_input.py decides.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/product-feature-spec/scripts/tests

Offline; every name below is fictional. check_input.py never parses the content of a source: it asks whether the
file exists and is not empty, and lists the briefs and the PRD of the project as candidates. The tests build the
same project twice, with and without the line (placed after the `- Owner:` header line), and compare the answers.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CHECK_INPUT = ROOT / "skills/product-feature-spec/scripts/check_input.py"
TAGS = ("pt-BR", "en-US")

BRIEF = """# Brief: search for the docs site

- Owner: core-clarify
- Status: approved
- Date: 2026-01-05

## Summary

Readers of the docs site need to find a page by its title.
"""

PRD = """# PRD: Docs site

- Owner: product-prd
- Status: approved
- Date: 2026-01-05
- Brief: docs/workbench/briefs/search.md

## Summary

A documentation site with search.
"""


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def project(root: Path, tag: str | None, brief: bool = True, prd: bool = True) -> Path:
    for rel, text, present in (("docs/workbench/briefs/search.md", BRIEF, brief), ("docs/product/prd.md", PRD, prd)):
        if present:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(with_language(text, tag) if tag else text, encoding="utf-8")
    return root


def check(root: Path, *args: str, request: str = "") -> subprocess.CompletedProcess:
    with tempfile.TemporaryFile("w+", encoding="utf-8") as f:
        f.write(request)
        f.seek(0)
        return subprocess.run([sys.executable, str(CHECK_INPUT), *args, "--root", str(root)], capture_output=True,
                              text=True, stdin=f, timeout=60)


def same_answer(tmp_path: Path, tag: str, *args: str, request: str = "", **present: bool) -> dict:
    plain = check(project(tmp_path / "plain", None, **present), *args, request=request)
    with_line = check(project(tmp_path / "lang", tag, **present), *args, request=request)
    assert plain.returncode == with_line.returncode == 0, with_line.stderr
    assert plain.stdout == with_line.stdout and plain.stderr == with_line.stderr
    return json.loads(with_line.stdout)


@pytest.mark.parametrize("tag", TAGS)
def test_a_named_prd_is_found_the_same(tmp_path, tag):
    out = same_answer(tmp_path, tag, "--source", "docs/product/prd.md", request="Add search")
    assert out["input"] == "found" and out["sources"] == ["docs/product/prd.md"]
    assert out["candidates"] == ["docs/workbench/briefs/search.md"]
    assert (tmp_path / "lang/docs/product/prd.md").read_text(encoding="utf-8").count("- Language: " + tag) == 1


@pytest.mark.parametrize("tag", TAGS)
def test_unnamed_candidates_are_listed_the_same(tmp_path, tag):
    out = same_answer(tmp_path, tag, request="Add search")
    assert out["input"] == "found" and out["sources"] == []
    assert out["candidates"] == ["docs/product/prd.md", "docs/workbench/briefs/search.md"]
    assert out["next"].startswith("The user named no document, but the project has:")


@pytest.mark.parametrize("tag", TAGS)
def test_a_named_brief_beats_the_short_request_the_same(tmp_path, tag):
    out = same_answer(tmp_path, tag, "--source", "docs/workbench/briefs/search.md", request="Add search", prd=False)
    assert out["input"] == "found" and out["candidates"] == [] and "reply_template" not in out


@pytest.mark.parametrize("tag", TAGS)
def test_no_input_stays_no_input(tmp_path, tag):
    # nothing named, nothing in the project: the stop, and its reply template, do not change
    out = same_answer(tmp_path, tag, request="Add search", brief=False, prd=False)
    assert out["input"] == "none" and out["next"].startswith("STOP. There is no input.")
    assert "reply_template" in out


@pytest.mark.parametrize("tag", TAGS)
def test_a_missing_source_is_still_missing(tmp_path, tag):
    out = same_answer(tmp_path, tag, "--source", "docs/product/gone.md", request="Add search", brief=False, prd=False)
    assert out["input"] == "none" and out["missing_sources"] == ["docs/product/gone.md"]

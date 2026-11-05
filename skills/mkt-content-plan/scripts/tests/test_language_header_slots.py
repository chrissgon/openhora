"""A `- Language: <tag>` header line in the previous calendar changes nothing slots.py computes with --after-calendar.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/mkt-content-plan/scripts/tests

Offline; every name below is fictional. The line sits right after the `- Owner:` header line. The rotation label,
the row numbers and the week numbers of the new slots continue exactly as they do without the line.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SLOTS = Path(__file__).resolve().parents[4] / "skills/mkt-content-plan/scripts/slots.py"
TAGS = ("pt-BR", "en-US")

HEADER = """# Content calendar: Sam Rivera

- Owner: mkt-content-plan
- Status: topics approved (2027-09-28)
- Updated: 2027-09-28
- Reads: strategy, state
- Network: the example network
- Rhythm: 3 posts per week, mon, wed, fri at 09:30 (America/Sao_Paulo)
"""

TABLE = """
| # | When | Pillar | Language | Topic | Serves | Material and source | Approval | Content | Status |
|---|------|--------|----------|-------|--------|---------------------|----------|---------|--------|
{rows}

## Waiting on the user
- nothing

## Assumptions
- none

## Sources
[1] README
"""


def calendar(weeks: int, heading: str = "## Week {n}: {monday} (rotation {label})") -> str:
    """A calendar of `weeks` weeks of three rows each, rotation labels A, B, A, ..."""
    text, row = HEADER, 0
    for w in range(weeks):
        monday = f"2027-10-{4 + 7 * w:02d}"
        rows = []
        for _ in range(3):
            row += 1
            rows.append(f"| {row} | {monday}T09:30:00-03:00 | a | PT | topic {row} | readers | README [1] | plan | — | proposed |")
        text += "\n" + heading.format(n=w + 1, monday=monday, label="AB"[w % 2]) + "\n" + TABLE.format(
            rows="\n".join(rows)).split("\n## Waiting")[0] + "\n"
    return text + "\n## Waiting on the user\n- nothing\n\n## Assumptions\n- none\n\n## Sources\n[1] README\n"


def with_language(text: str, tag: str) -> str:
    """Insert `- Language: <tag>` after the `- Owner:` line, else after the first `- Key:` header line."""
    lines = text.split("\n")
    head = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    owner = [i for i in range(head) if lines[i].startswith("- Owner:")]
    first = [i for i in range(head) if re.match(r"- [A-Z][A-Za-z ]*:", lines[i])]
    at = (owner or first)[0]
    return "\n".join(lines[:at + 1] + [f"- Language: {tag}"] + lines[at + 1:])


def slots(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SLOTS), "--start", "2027-10-18", "--days", "mon,wed,fri", "--time", "09:30",
                           "--tz", "America/Sao_Paulo", "--pillars", "a|b|c", "--rotation", "PT,EN,PT;EN,PT,EN",
                           "--today", "2027-09-29", *args], capture_output=True, text=True, timeout=60)


def after(tmp_path: Path, text: str, *args: str) -> subprocess.CompletedProcess:
    cal = tmp_path / "calendar.md"
    cal.write_text(text, encoding="utf-8")
    return slots("--after-calendar", str(cal), *args)


def same_result(a: subprocess.CompletedProcess, b: subprocess.CompletedProcess) -> None:
    assert (a.returncode, a.stdout, a.stderr) == (b.returncode, b.stdout, b.stderr)


def test_the_baseline_calendar_has_the_header_the_tests_edit():
    assert "- Owner: mkt-content-plan" in calendar(2) and "- Language:" not in calendar(2)
    assert with_language(calendar(2), "pt-BR").splitlines()[2:4] == ["- Owner: mkt-content-plan", "- Language: pt-BR"]


@pytest.mark.parametrize("tag", TAGS)
def test_rotation_row_and_week_numbers_continue_the_same(tmp_path, tag):
    plain = after(tmp_path, calendar(2), "--weeks", "2")
    assert plain.returncode == 0, plain.stderr
    with_line = after(tmp_path, with_language(calendar(2), tag), "--weeks", "2")
    same_result(plain, with_line)
    out = json.loads(with_line.stdout)
    # two weeks of rows 1-6 and rotation A, B: the new weeks are 3 and 4 and start at A, from row 7
    assert out["after_row"] == 6 and out["first_week"] == "A"
    assert [s["n"] for s in out["slots"]] == [7, 8, 9, 10, 11, 12]
    assert [s["week"] for s in out["slots"]] == [3, 3, 3, 4, 4, 4]
    assert [s["rotation"] for s in out["slots"]] == ["A", "A", "A", "B", "B", "B"]


@pytest.mark.parametrize("tag", TAGS)
def test_one_previous_week_continues_with_the_next_label(tmp_path, tag):
    plain = after(tmp_path, calendar(1))
    with_line = after(tmp_path, with_language(calendar(1), tag))
    same_result(plain, with_line)
    out = json.loads(with_line.stdout)
    assert out["first_week"] == "B" and out["after_row"] == 3
    assert [(s["n"], s["week"], s["language"]) for s in out["slots"]] == [(4, 2, "EN"), (5, 2, "PT"), (6, 2, "EN")]


@pytest.mark.parametrize("tag", TAGS)
def test_a_translated_week_heading_is_still_read(tmp_path, tag):
    heading = "## Semana {n}: {monday} (rotação {label})"  # validate: allow english-only -- the Portuguese heading under test
    plain = after(tmp_path, calendar(1, heading))
    with_line = after(tmp_path, with_language(calendar(1, heading), tag))
    same_result(plain, with_line)
    assert json.loads(with_line.stdout)["first_week"] == "B"


@pytest.mark.parametrize("tag", TAGS)
def test_a_calendar_with_no_week_yet_keeps_the_default_start(tmp_path, tag):
    empty = HEADER + "\n## Waiting on the user\n- nothing\n"
    plain = after(tmp_path, empty)
    with_line = after(tmp_path, with_language(empty, tag))
    same_result(plain, with_line)
    out = json.loads(with_line.stdout)
    assert out["first_week"] == "A" and out["after_row"] == 0 and out["slots"][0]["week"] == 1


@pytest.mark.parametrize("tag", TAGS)
def test_a_rotation_label_outside_the_new_rotation_is_refused_the_same(tmp_path, tag):
    text = calendar(1).replace("(rotation A)", "(rotation D)")
    plain = after(tmp_path, text)
    assert plain.returncode == 2 and "previous calendar ends with rotation D" in plain.stderr
    same_result(plain, after(tmp_path, with_language(text, tag)))

"""The `- Language: <tag>` header line must change neither the return code nor the result of
`clarify.py brief` (skills/core-clarify/scripts/clarify.py). The first line must stay `# Brief: <topic>` and a
`- Date:` line is required; the Language line is tested right after `- Owner:` and directly after the title.
Offline; every name and figure is fictional.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/core-clarify/scripts/tests
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/core-clarify/scripts/clarify.py"
TITLE = "# Brief: widget docs migration\n"
OWNER = "- Owner: core-clarify\n"
TAGS = ["pt-BR", "en-US"]

GOOD_BRIEF = f"""{TITLE}
{OWNER}- Status: draft
- Date: 2026-03-02

## Goal
Every widget page documents the new version for application developers.

## Scope
- In: the 6 widget pages
- Out: the changelog page

## Constraints
- Release on 2026-04-01 (source: user)

## Decisions
| # | Decision | Chosen | Why | By |
|---|----------|--------|-----|----|
| 1 | Pages in scope | the 6 widget pages | they describe the changed API | user |
| 2 | Old docs | stay online | recorded earlier | user (recorded in docs/workbench/state.md) |

## Facts established without asking
- `WxDialog` is renamed to `WxModal` (source: MIGRATION.md)

## Open questions
- [ ] Who reviews the pages? (blocks: publication; recommended: the library maintainer, not adopted)

## Contradictions surfaced
- none
"""
# fails in known ways: a placeholder (reported with its line number), a missing Out, a fact without a source
BAD_BRIEF = (GOOD_BRIEF.replace("- Out: the changelog page", "- Out: none")
             .replace("(source: MIGRATION.md)", "").replace("- Status: draft", "- Status: <one line>"))
# a brief without the required Date line
NO_DATE = GOOD_BRIEF.replace("- Date: 2026-03-02\n", "")


def brief(tmp_path: Path, sub: str, text: str):
    folder = tmp_path / sub
    folder.mkdir()
    f = folder / "brief.md"
    f.write_text(text, encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "brief", "--file", str(f)],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode in (0, 1), p.stderr
    return p.returncode, json.loads(p.stdout)


def after_owner(text: str, tag: str) -> str:
    assert OWNER in text
    return text.replace(OWNER, OWNER + f"- Language: {tag}\n", 1)


def after_title(text: str, tag: str) -> str:
    assert text.startswith(TITLE)
    return text.replace(TITLE, TITLE + f"- Language: {tag}\n", 1)


def unshift(result: dict) -> dict:
    """The new header line moves every "line N:" in an error down by one; undo that, change nothing else."""
    out = json.loads(json.dumps(result))
    out["errors"] = [re.sub(r"^line (\d+):", lambda m: f"line {int(m.group(1)) - 1}:", e) for e in out["errors"]]
    return out


@pytest.mark.parametrize("insert", [after_owner, after_title])
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("text,passing", [(GOOD_BRIEF, True), (BAD_BRIEF, False), (NO_DATE, False)])
def test_language_line_changes_neither_code_nor_result(tmp_path, insert, tag, text, passing):
    base_rc, base = brief(tmp_path, "base", text)
    new_rc, new = brief(tmp_path, "with", insert(text, tag))
    assert (base_rc == 0) == passing, base
    assert new_rc == base_rc
    assert unshift(new) == base
    if passing:
        assert new["ok"] is True and new["errors"] == [] and new["decisions"] == 2


def test_the_title_stays_the_first_line_and_the_date_line_is_still_required(tmp_path):
    for insert in (after_owner, after_title):
        text = insert(GOOD_BRIEF, "pt-BR")
        assert text.splitlines()[0] == "# Brief: widget docs migration"
        _, data = brief(tmp_path, f"ok-{insert.__name__}", text)
        assert data["ok"] is True
        rc, data = brief(tmp_path, f"nodate-{insert.__name__}", insert(NO_DATE, "pt-BR"))
        assert rc == 1 and any('no "- Date: YYYY-MM-DD" line' in e for e in data["errors"])


def test_bad_brief_keeps_its_known_errors_with_the_language_line(tmp_path):
    _, base = brief(tmp_path, "base", BAD_BRIEF)
    _, data = brief(tmp_path, "with", after_owner(BAD_BRIEF, "en-US"))
    assert any("placeholder" in e for e in data["errors"])
    assert any('Scope "Out" is empty' in e for e in data["errors"])
    assert any("fact without a source" in e for e in data["errors"])
    assert len(data["errors"]) == len(base["errors"])

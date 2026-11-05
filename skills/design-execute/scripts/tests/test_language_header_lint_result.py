"""A `- Language: <tag>` header line changes nothing lint_result.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/design-execute/scripts/tests

Offline; the product, the tool and every run below are fictional. Each case lints the same results document
without the line and with it (`pt-BR`, `en-US`) placed right after the `- Owner:` line, or after the first
header line when the document has no Owner line, and compares the return code and the printed result.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/design-execute/scripts/lint_result.py"
TAGS = ("pt-BR", "en-US")

BRIEF = """# Brief: Harbor landing

## Evaluation criteria

- CRIT-1: the headline is readable at 320 px
- CRIT-2: the pricing link is reachable from the first screen
"""

RESULT = """# Design results: Harbor landing

- Owner: design-execute
- Status: done
- Date: 2026-10-16
- Brief: docs/design/brief.md
- Tool: Sketchboard
- Mode: assisted

## Runs

| Run | Round | Direction | Status | Pack | Outputs |
|-----|-------|-----------|--------|------|---------|
| R1 | 1 | Calm | done | packs/calm/prompt.md | out/r1.png |
| R2 | 1 | Bold | approved | packs/bold/prompt.md | https://design.example/r2 |

## Critique

| Criterion | R1 | R2 |
|-----------|----|----|
| CRIT-1 | pass: the headline fits on two lines | partial: the headline wraps to four lines |
| CRIT-2 | fail: no pricing link | pass: the pricing link is in the header |

## Decision

- Recommendation: R2, after shortening the headline.

## Next

- Ask the user to choose a direction.
"""

NO_OWNER = RESULT.replace("- Owner: design-execute\n", "")


def lint(tmp_path: Path, text: str) -> tuple[int, str]:
    (tmp_path / "result.md").write_text(text, encoding="utf-8")
    (tmp_path / "brief.md").write_text(BRIEF, encoding="utf-8")
    (tmp_path / "out").mkdir(exist_ok=True)
    (tmp_path / "out" / "r1.png").write_bytes(b"png")
    for direction in ("calm", "bold"):
        (tmp_path / "packs" / direction).mkdir(parents=True, exist_ok=True)
        (tmp_path / "packs" / direction / "prompt.md").write_text("# Run\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(tmp_path / "result.md"),
                        "--brief", str(tmp_path / "brief.md"), "--root", str(tmp_path)],
                       capture_output=True, text=True, timeout=60)
    assert r.stderr == ""
    return r.returncode, r.stdout


def with_language(text: str, tag: str) -> str:
    """After the Owner line; when there is none, after the first header line."""
    lines = text.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if ln.startswith("- Owner:")), None)
    if at is None:
        at = next(i for i, ln in enumerate(lines) if ln.startswith("- "))
    lines.insert(at + 1, f"- Language: {tag}\n")
    return "".join(lines)


def test_a_passing_results_document_still_passes_with_a_language_line(tmp_path):
    for base in (RESULT, NO_OWNER):
        code, out = lint(tmp_path, base)
        assert code == 0, out
        assert json.loads(out)["ok"] is True
        for tag in TAGS:
            text = with_language(base, tag)
            assert text != base
            assert lint(tmp_path, text) == (code, out)


def test_a_failing_results_document_reports_the_same_findings_with_a_language_line(tmp_path):
    for base in (RESULT, NO_OWNER):
        broken = (base.replace("## Next\n", "## Later\n").replace("- Tool: Sketchboard\n", "")
                  .replace("- Recommendation: R2, after shortening the headline.\n", ""))
        code, out = lint(tmp_path, broken)
        assert code == 1
        errors = json.loads(out)["errors"]
        assert "missing section '## Next'" in errors and "missing header line '- Tool:'" in errors
        for tag in TAGS:
            assert lint(tmp_path, with_language(broken, tag)) == (code, out)

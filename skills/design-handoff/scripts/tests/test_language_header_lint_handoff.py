"""A `- Language: <tag>` header line changes nothing lint_handoff.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/design-handoff/scripts/tests

Offline; every name, class, token and requirement below is fictional. Each case lints the same handoff spec
without the line and with it (`pt-BR`, `en-US`) placed right after the `- Owner:` line, or after the first
header line when the document has no Owner line, and compares the return code and the printed result.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LINT = ROOT / "skills/design-handoff/scripts/lint_handoff.py"
TAGS = ("pt-BR", "en-US")

FLOWS_TEXT = """# Flows

## Screens

- SCREEN-1: Home. Purpose: x. Regions: top banner (headline), sign-up form, footer. States: default. Breakpoints: none. Source: spec.
- SCREEN-2: Other. Purpose: y. Regions: list. States: default.

## Flows

- FLOW-1: x
"""

SPEC = """# Handoff: home

- Owner: design-handoff
- Status: draft
- Date: 2026-10-16
- Screen: SCREEN-1
- Lint: ok (2026-01-05)

## Summary

x

## Sources

- x

## Reference and shipping

- Reference only, never shipped: the tool runtime
- Preview-only switches and placeholders: none

## Tokens

| Value | Where | Maps to | Action |
|-------|-------|---------|--------|
| `--made-up` (#abcdef) | link | none | fix in code |
| #123456 | link border | none | fix in code |

## Components

| Region | Unit | Props and data | Content source | States |
|--------|------|----------------|----------------|--------|
| Top banner | Banner | none | content/home.md | default |
| Sign-up form | Form | none | config | default, error |
| Footer | SiteFooter | none | config | default |

## Layout

| Width | Columns and order | Sticky | Collapsed or hidden |
|-------|-------------------|--------|---------------------|
| 1280 | one | none | none |

## Behaviour

| Interaction | Requirement | Rule |
|-------------|-------------|------|
| submit | REQ-1 | sends |

## Motion

| Animation | Trigger | Timing | Final state | Reduced motion |
|-----------|---------|--------|-------------|----------------|
| Link fade | hover | 200 ms ease-out | opaque | no transition |

## Assets

- none

## Deviations

- DEV-1: border colour is not a token, against the design system. Action: fix in code

## Acceptance

- Compare at: 1280 px, light

## Open questions

- none

## Readiness

- Ready for eng-architecture: yes
"""

NO_OWNER = SPEC.replace("- Owner: design-handoff\n", "")


def lint(tmp_path: Path, spec: str) -> tuple[int, str]:
    (tmp_path / "home.md").write_text(spec, encoding="utf-8")
    (tmp_path / "flows.md").write_text(FLOWS_TEXT, encoding="utf-8")
    r = subprocess.run([sys.executable, str(LINT), "--file", str(tmp_path / "home.md"),
                        "--flows", str(tmp_path / "flows.md"), "--screen", "SCREEN-1"],
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


def test_a_passing_spec_still_passes_with_a_language_line(tmp_path):
    for base in (SPEC, NO_OWNER):
        code, out = lint(tmp_path, base)
        assert code == 0, out
        assert json.loads(out)["ok"] is True
        for tag in TAGS:
            text = with_language(base, tag)
            assert text != base
            assert lint(tmp_path, text) == (code, out)


def test_a_failing_spec_reports_the_same_findings_with_a_language_line(tmp_path):
    for base in (SPEC, NO_OWNER):
        broken = (base.replace("## Assets", "## Files").replace("Action: fix in code\n", "Action: later\n")
                  .replace("| Sign-up form | Form | none | config | default, error |\n", ""))
        code, out = lint(tmp_path, broken)
        assert code == 1
        errors = json.loads(out)["errors"]
        assert "missing section '## Assets'" in errors
        assert any(e.startswith("DEV-1 has no Action") for e in errors) and any("sign-up form" in e for e in errors)
        for tag in TAGS:
            assert lint(tmp_path, with_language(broken, tag)) == (code, out)

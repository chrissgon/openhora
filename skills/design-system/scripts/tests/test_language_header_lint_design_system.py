"""A `- Language: <tag>` header line changes nothing lint_design_system.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/design-system/scripts/tests

Offline; every name and number below is fictional. Each case lints the same design system document, with
--flows and --library, without the line and with it (`pt-BR`, `en-US`) placed right after the `- Owner:` line,
or after the first header line when the document has no Owner line, and compares the return code and the
printed result (warnings, counts and the library prefix included).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LINT_DS = ROOT / "skills/design-system/scripts/lint_design_system.py"
TAGS = ("pt-BR", "en-US")

DS_FLOWS = "# Flows\n\n## Screens\n\n- SCREEN-1: Home. Regions: hero.\n- SCREEN-2: Post. Regions: body.\n"
DS_LIBRARY = "| Token | Light | Dark |\n|---|---|---|\n| `--ui-bg` | #FFFFFF | #000000 |\n| `--ui-gap` | 16px |\n"

CONTRAST_ROWS = """| `--ui-ink` | `--ui-bg` | {light}:1 | 21.00:1 | pass |
| brand/on-fill | brand/fill | 3.50:1 | 9.00:1 | fail in light |"""


def design_system(bg: str = "#FFFFFF", light: str = "21.00", owner: bool = True,
                  screens: str = "SCREEN-1, SCREEN-2") -> str:
    head = "- Owner: design-system\n" if owner else ""
    text = f"""# Design system: Plinth

{head}- Status: draft
- Date: 2026-10-16
- Flows: docs/design/flows.md

## Summary

One library governs the values.

## Sources

- lib.md

## Ownership

- Colour: the library.

## Colour

| Token | Light | Dark | Role | Source |
|-------|-------|------|------|--------|
| `--ui-bg` | {bg} | #000000 | page background | lib.md |
| `--ui-ink` (page/ink) | #000000 | #FFFFFF | body text | lib.md |
| brand/fill | #0092CD | rgba(0, 146, 205, 1) | brand | lib.md |
| brand/on-fill | #FFFFFF | #000000 | label on brand | lib.md |

## Contrast

| Text token | On background | Light ratio | Dark ratio | AA |
|------------|---------------|-------------|------------|----|
{CONTRAST_ROWS.format(light=light)}

## Type

- Typeface: Example Sans, fallback sans-serif. Source: lib.md
- Reading width: 68ch. Source: lib.md

## Space, radii, borders, elevation

| Token | Value | Role | Source |
|-------|-------|------|--------|
| `--ui-gap` | 16px | gap between blocks | lib.md |

## Layout

## Components

| Component | Owner | Variants | States | Screens | Source |
|-----------|-------|----------|--------|---------|--------|
| Button | library | size: sm, md | default, hover | {screens} | lib.md |

## Design tool

- File: none available

## Assumptions

## Open questions

## Readiness

- Ready for design-brief: yes
"""
    return text


def lint(tmp_path: Path, text: str) -> tuple[int, str]:
    (tmp_path / "flows.md").write_text(DS_FLOWS, encoding="utf-8")
    (tmp_path / "lib.md").write_text(DS_LIBRARY, encoding="utf-8")
    (tmp_path / "ds.md").write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(LINT_DS), "--file", str(tmp_path / "ds.md"),
                        "--flows", str(tmp_path / "flows.md"), "--library", str(tmp_path / "lib.md")],
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


def test_a_passing_design_system_still_passes_with_a_language_line(tmp_path):
    for owner in (True, False):
        base = design_system(owner=owner)
        code, out = lint(tmp_path, base)
        assert code == 0, out
        result = json.loads(out)
        assert result["ok"] is True and result["errors"] == [] and result["library_prefix"] == "ui"
        assert result["warnings"] == ["contrast row brand/on-fill: dark ratio not recomputed, a value is not hex"]
        for tag in TAGS:
            text = with_language(base, tag)
            assert text != base
            assert lint(tmp_path, text) == (code, out)


def test_a_failing_design_system_reports_the_same_findings_with_a_language_line(tmp_path):
    for owner in (True, False):
        base = design_system(owner=owner, bg="#FAFAFA", light="7.00", screens="SCREEN-1, SCREEN-9")
        code, out = lint(tmp_path, base)
        assert code == 1
        errors = json.loads(out)["errors"]
        assert any(e.startswith("library value changed or absent") for e in errors)
        assert any("light ratio is 7.00:1" in e for e in errors)
        assert any("SCREEN-9" in e for e in errors)
        for tag in TAGS:
            assert lint(tmp_path, with_language(base, tag)) == (code, out)

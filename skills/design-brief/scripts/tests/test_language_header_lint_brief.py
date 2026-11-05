"""A `- Language: <tag>` header line changes nothing lint_brief.py reports.

Run: uv run --python 3.11 --with pytest==9.1.1 pytest -q skills/design-brief/scripts/tests

Offline; every name and number below is fictional. Each case lints the same brief without the line and with it
(`pt-BR`, `en-US`) placed right after the `- Owner:` line, and compares the return code and the printed result.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LINT_BRIEF = ROOT / "skills/design-brief/scripts/lint_brief.py"
TAGS = ("pt-BR", "en-US")

BRIEF = """# Design brief: Harbor landing

- Owner: design-brief
- Status: draft
- Date: 2026-10-16
- Type: screen
- For: SCREEN-1
- Values: inline
- Direction: open: three directions
- Lint: ok (2026-10-16)

## Summary

Explore three directions for the Harbor landing page at 1280 and 375 px, in light and dark.

## Sources

- docs/design/flows.md

## Subject

Harbor is a small tool that tracks shipping containers for freight brokers.

Example: a broker pastes a container number and sees where it is.

## Audience and voice

- Brokers who fear missing a delay.
- Voice: plain and calm.
- Words to use: container, arrival
- Words to avoid: synergy

## Creative direction

No previous version.

- Direction A, "Calm": quiet and spacious.
- Direction B, "Bold": big type and strong contrast.
- Direction C, "Map": a map first.

## Visual language

Colours: #111111 ink, #FFFFFF page, #0A6EBD accent, #F3F4F6 tint, #1F2937 dark page, #E5E7EB line.
Space: 4px, 8px, 16px, 24px, 32px, 48px.
Type: Example Sans for text, Example Mono for code.

## Content

- Regions: hero, search form, footer
- States: default
- Breakpoints: one column below 640 px
- Motion: none

## Constraints

- Values only from Visual language.

## Deliverables

- Round 1: three directions, one run each, at 1280 px light.

## Evaluation criteria

- CRIT-1: the headline is readable at 375 px
- CRIT-2: the search form is on the first screen
- CRIT-3: the contrast is readable in dark mode
- CRIT-4: the footer holds the contact line
- CRIT-5: no region overlaps another

## Attachments

- Send: the brief

## Prompt

```text
Direction: {slot}
Design the Harbor landing page.
```

## Assumptions

- none

## Open questions

- OPEN-1: Which accent? Blocks: nothing. Recommended: the blue, because it is the brand colour.

## Readiness

- Ready for design-execute: yes
"""


def lint(tmp_path: Path, text: str) -> tuple[int, str]:
    brief = tmp_path / "brief.md"
    brief.write_text(text, encoding="utf-8")
    r = subprocess.run([sys.executable, str(LINT_BRIEF), "--file", str(brief), "--type", "screen",
                        "--values", "inline", "--json"], capture_output=True, text=True, timeout=60)
    assert r.stderr == ""
    return r.returncode, r.stdout


def with_language(text: str, tag: str) -> str:
    return text.replace("- Owner: design-brief\n", f"- Owner: design-brief\n- Language: {tag}\n", 1)


def test_a_passing_brief_still_passes_with_a_language_line(tmp_path):
    code, out = lint(tmp_path, BRIEF)
    assert code == 0, out
    assert json.loads(out)["ok"] is True
    for tag in TAGS:
        text = with_language(BRIEF, tag)
        assert text != BRIEF
        assert lint(tmp_path, text) == (code, out)


def test_a_failing_brief_reports_the_same_findings_with_a_language_line(tmp_path):
    broken = (BRIEF.replace("- CRIT-5: no region overlaps another\n", "")
              .replace("## Constraints\n\n- Values only from Visual language.", "## Constraints\n\n- Read docs/design/x.md TODO"))
    code, out = lint(tmp_path, broken)
    assert code == 1
    errors = json.loads(out)["errors"]
    assert any("CRIT" in e for e in errors) and any("repository path" in e for e in errors)
    for tag in TAGS:
        assert lint(tmp_path, with_language(broken, tag)) == (code, out)

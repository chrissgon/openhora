"""Tests for skills/core-clarify/scripts/clarify.py: the round check, the brief check and the state update.

Run: uv run --with pytest pytest skills/core-clarify/scripts/tests/test_clarify.py

Offline; every name and figure is fictional.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills/core-clarify/scripts/clarify.py"


def run(*args: str, stdin: str | None = None):
    p = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, input=stdin, timeout=60)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith("{") else None), p.stderr


GOOD_ROUND = """## Clarify: dark mode, round 1

### Facts established without asking
- The site is built with a static generator (source: package.json)

### Contradictions
- none

### Questions
**Q1. Should the toggle have two states or three?**
- Options: light/dark; light/dark/system
- Recommended: three states, with system as the default
- Why: "respect the OS by default" only survives a click when system is a stored choice.

**Q2. Are code blocks in scope for the first release?**
- Recommended: yes
- Why: unthemed code blocks are the most visible gap on a docs page.

### Next
Nothing is written yet, and every question above stays open until you answer it.
"""


def test_round_ok():
    code, data, _ = run("round", "--file", "-", stdin=GOOD_ROUND)
    assert code == 0 and data["ok"] and data["questions"] == 2 and data["errors"] == []
    assert "write no brief" in data["next"]


def test_round_reads_a_file(tmp_path):
    f = tmp_path / "round.md"
    f.write_text(GOOD_ROUND, encoding="utf-8")
    code, data, _ = run("round", "--file", str(f))
    assert code == 0 and data["ok"]


def test_round_refuses_a_missing_next_line():
    text = GOOD_ROUND.replace(
        "Nothing is written yet, and every question above stays open until you answer it.",
        "Nothing is written yet.")
    code, data, _ = run("round", "--file", "-", stdin=text)
    assert code == 1 and any("### Next" in e for e in data["errors"])


def test_round_refuses_four_questions():
    q = "**Q{n}. Which storage holds the choice?**\n- Recommended: local storage\n- Why: no account exists.\n\n"
    code, data, _ = run("round", "--file", "-", stdin="".join(q.format(n=i) for i in range(1, 5)))
    assert code == 1 and any("at most 3" in e for e in data["errors"])


def test_round_refuses_a_bundled_question():
    text = "**Q1. What is the site built with, and where does its code live?**\n- Recommended: a static generator\n- Why: it sets the work.\n"
    code, data, _ = run("round", "--file", "-", stdin=text)
    assert code == 1 and any("joins two things" in e for e in data["errors"])


def test_round_refuses_follow_up_questions():
    text = ("**Q1. Which surfaces are in scope?**\nIs the repo reachable from here?\n"
            "- Recommended: chrome and text\n- Why: it sets the test surface.\n")
    code, data, _ = run("round", "--file", "-", stdin=text)
    assert code == 1 and any("more questions follow" in e for e in data["errors"])


def test_round_refuses_a_recommendation_that_is_not_an_answer():
    text = "**Q1. What is the docs site built on?**\n- Recommended: tell me the framework\n- Why: it sets the work.\n"
    code, data, _ = run("round", "--file", "-", stdin=text)
    assert code == 1 and any("not an answer" in e for e in data["errors"])


def test_round_refuses_missing_recommendation_and_long_why():
    text = ("**Q1. Which storage holds the choice?**\n"
            "- Why: There is no account system. A cookie would be sent on every request. Local storage is simpler.\n")
    code, data, _ = run("round", "--file", "-", stdin=text)
    assert code == 1
    assert any('no "- Recommended:"' in e for e in data["errors"])
    assert any("3 sentences" in e for e in data["errors"])


def test_round_without_questions_is_an_error():
    code, data, _ = run("round", "--file", "-", stdin="Here are some thoughts about your plan.\n")
    assert code == 1 and any("no question found" in e for e in data["errors"])


GOOD_BRIEF = """# Brief: widget docs migration

- Owner: core-clarify
- Status: draft
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


def check_brief(tmp_path, text):
    f = tmp_path / "brief.md"
    f.write_text(text, encoding="utf-8")
    return run("brief", "--file", str(f))


def test_brief_ok(tmp_path):
    code, data, _ = check_brief(tmp_path, GOOD_BRIEF)
    assert code == 0 and data["ok"] and data["decisions"] == 2, data


def test_brief_accepts_component_tags_and_nested_out(tmp_path):
    text = GOOD_BRIEF.replace("- Out: the changelog page", "- Out:\n  - the changelog page\n  - the `<WxTabs>` playground")
    code, data, _ = check_brief(tmp_path, text)
    assert code == 0, data


def test_brief_refuses_empty_out_and_missing_section(tmp_path):
    text = GOOD_BRIEF.replace("- Out: the changelog page", "- Out: none").replace("## Contradictions surfaced\n- none\n", "")
    code, data, _ = check_brief(tmp_path, text)
    assert code == 1
    assert any('Scope "Out" is empty' in e for e in data["errors"])
    assert any("Contradictions surfaced" in e for e in data["errors"])


def test_brief_refuses_decision_without_decider_and_placeholders(tmp_path):
    text = GOOD_BRIEF.replace("| they describe the changed API | user |", "| they describe the changed API |  |")
    text = text.replace("- Date: 2026-03-02", "- Date: <YYYY-MM-DD>")
    code, data, _ = check_brief(tmp_path, text)
    assert code == 1
    assert any('"By" is empty' in e for e in data["errors"])
    assert any("placeholder" in e for e in data["errors"])
    assert any("Date" in e for e in data["errors"])


def test_brief_refuses_fact_without_source_and_plain_open_question(tmp_path):
    text = GOOD_BRIEF.replace(" (source: MIGRATION.md)", "").replace("- [ ] Who reviews", "- Who reviews")
    code, data, _ = check_brief(tmp_path, text)
    assert code == 1
    assert any("fact without a source" in e for e in data["errors"])
    assert any("not a checkbox" in e for e in data["errors"])


STATE = """# Workbench state

- Project: Widget docs
- Updated: 2026-02-20

## Artifacts

| Artifact | Owner skill | Status | Updated |
|----------|-------------|--------|---------|
| docs/engineering/migration.md (at MIGRATION.md) | existing | approved | 2026-02-10 |

## Decisions

- 2026-02-10: The old docs stay online. (user)

## Approvals

| Scope | What | Payload hash | Approved | Expires | Status |
|-------|------|--------------|----------|---------|--------|

## Open questions

- [ ] Do samples need a typed variant? (raised by user)
"""


def test_state_appends_without_rewriting(tmp_path):
    f = tmp_path / "state.md"
    f.write_text(STATE, encoding="utf-8")
    code, data, _ = run("state", "--state", str(f), "--date", "2026-03-02",
                        "--artifact", "docs/workbench/briefs/widget-docs.md",
                        "--decision", "Scope is the 6 widget pages; see the brief. (user)",
                        "--decision", "The changelog page is out for now. (user)",
                        "--open", "Who reviews the pages?")
    assert code == 0 and data["decisions_appended"] == 2 and data["open_questions_appended"] == 1, data
    new = f.read_text(encoding="utf-8")
    for line in STATE.splitlines():
        assert line in new.splitlines()
    lines = new.splitlines()
    d = lines.index("## Decisions")
    assert lines[d + 2:d + 5] == ["- 2026-02-10: The old docs stay online. (user)",
                                  "- 2026-03-02: Scope is the 6 widget pages; see the brief. (user)",
                                  "- 2026-03-02: The changelog page is out for now. (user)"]
    q = lines.index("## Open questions")
    assert lines[q + 2:q + 4] == ["- [ ] Do samples need a typed variant? (raised by user)",
                                  "- [ ] Who reviews the pages? (raised by core-clarify)"]
    a = lines.index("## Artifacts")
    assert "| docs/workbench/briefs/widget-docs.md | core-clarify | draft | 2026-03-02 |" in lines[a:d]
    assert lines.index("## Approvals") > d  # the decisions stayed inside their section


def test_state_run_twice_updates_the_artifact_row_once(tmp_path):
    f = tmp_path / "state.md"
    f.write_text(STATE, encoding="utf-8")
    run("state", "--state", str(f), "--date", "2026-03-02", "--artifact", "docs/workbench/briefs/w.md")
    run("state", "--state", str(f), "--date", "2026-03-05", "--artifact", "docs/workbench/briefs/w.md")
    rows = [l for l in f.read_text(encoding="utf-8").splitlines() if "briefs/w.md" in l]
    assert rows == ["| docs/workbench/briefs/w.md | core-clarify | draft | 2026-03-05 |"]


def test_state_creates_missing_sections(tmp_path):
    f = tmp_path / "state.md"
    f.write_text("# Workbench state\n\n- Project: Widget docs\n", encoding="utf-8")
    code, data, _ = run("state", "--state", str(f), "--date", "2026-03-02", "--decision", "Scope set. (user)",
                        "--open", "Who reviews?")
    assert code == 0 and data["sections_created"] == ["## Decisions", "## Open questions"]
    text = f.read_text(encoding="utf-8")
    assert "## Decisions\n\n- 2026-03-02: Scope set. (user)\n" in text
    assert "## Open questions\n\n- [ ] Who reviews? (raised by core-clarify)\n" in text


def test_state_refuses_missing_file_and_decision_without_decider(tmp_path):
    code, data, _ = run("state", "--state", str(tmp_path / "none.md"), "--decision", "Scope set. (user)")
    assert code == 1 and "do not create it" in data["errors"][0]
    assert not (tmp_path / "none.md").exists()
    f = tmp_path / "state.md"
    f.write_text(STATE, encoding="utf-8")
    code, data, _ = run("state", "--state", str(f), "--decision", "Scope set.")
    assert code == 1 and "who decided" in data["errors"][0]
    assert f.read_text(encoding="utf-8") == STATE


def test_state_refuses_a_bad_date(tmp_path):
    f = tmp_path / "state.md"
    f.write_text(STATE, encoding="utf-8")
    code, _, err = run("state", "--state", str(f), "--date", "March 2", "--open", "Who reviews?")
    assert code == 2 and "YYYY-MM-DD" in err


def test_today_and_help():
    code, data, _ = run("today")
    assert code == 0 and len(data["date"]) == 10
    p = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "round" in p.stdout and "state" in p.stdout


def test_brief_refuses_parked_row_and_file_as_decider(tmp_path):
    text = GOOD_BRIEF.replace("| 2 | Old docs | stay online | recorded earlier | user (recorded in docs/workbench/state.md) |",
                              "| 2 | Old docs | stay online | recorded earlier | docs/workbench/state.md |\n"
                              "| 3 | Reviewer | Parked as an open question | the user has not decided | user |")
    code, data, _ = check_brief(tmp_path, text)
    assert code == 1
    assert any("not a decider" in e for e in data["errors"])
    assert any("parked item is not a decision" in e for e in data["errors"])


def test_state_refuses_a_parked_item_as_decision(tmp_path):
    f = tmp_path / "state.md"
    f.write_text(STATE, encoding="utf-8")
    code, data, _ = run("state", "--state", str(f), "--decision", "Review ownership is parked as an open question. (user)")
    assert code == 1 and "--open" in data["errors"][0]
    assert f.read_text(encoding="utf-8") == STATE


CONTRADICTION_ROUND = """## Clarify: redesign, round 1

### Facts established without asking
- Server-side rendering is on: `ssr: true` (source: nuxt.config.ts)

### Contradictions
- The request says to add server-side rendering; nuxt.config.ts already has `ssr: true`: asked as Q1.

### Questions
**Q1. {title}**
- Options: the file is right and the request means something else; the request is right and the file is wrong or not in effect
- Recommended: the file is right, and the gap is per-page metadata
- Why: the configuration already renders every page on the server.

### Next
Nothing is written yet, and every question above stays open until you answer it.
"""


def test_a_listed_contradiction_makes_q1_ask_which_one_holds():
    title = "Which one holds: the request to add server-side rendering, or nuxt.config.ts with ssr already on?"
    code, data, _ = run("round", "--file", "-", stdin=CONTRADICTION_ROUND.format(title=title))
    assert code == 0 and data["ok"], data["errors"]


def test_a_listed_contradiction_with_another_q1_is_an_error():
    title = "What is the actual gap this work closes?"
    code, data, _ = run("round", "--file", "-", stdin=CONTRADICTION_ROUND.format(title=title))
    assert code == 1
    assert any(e.startswith('Q1: a contradiction is listed, so Q1 asks "Which one holds') for e in data["errors"])


def test_no_contradiction_leaves_q1_free():
    code, data, _ = run("round", "--file", "-", stdin=GOOD_ROUND)
    assert code == 0 and not any("Which one holds" in e for e in data["errors"])

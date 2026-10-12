"""Tests of the merge of the state file (runtime/state_merge.py, limit L10): of a run's state file only a draft
row of the skill that ran, a decision attributed to it and a new open question are taken, line by line, on top
of what the project has now; only code writes what is the person's. Offline; texts in the form of
contracts/state.md, every name invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_state_merge.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
state_merge = st.load("state_merge")
project_config = st.load("project_config")

SKILL = "demo-writes"
BASE = """# Workbench state

- Project: demo
- Docs in git: none

## Autonomy

- Checkpoints: milestones

## Artifacts

| Artifact | Owner skill | Status | Updated |
|----------|-------------|--------|---------|
| docs/business/market.md | demo-asks | draft | 2026-10-04 |

## Decisions

- 2026-10-04: Project initialized for the workbench; autonomy milestones. (core-project-init, confirmed by user)

## Open questions

- [ ] Which country first?

## Approvals

| Scope | What | Payload hash | Approved | Expires | Status |
|-------|------|--------------|----------|---------|--------|
"""
ICP_ROW = "| docs/business/icp.md | demo-writes | draft | 2026-10-05 |"
DECISION = "- 2026-10-05: Clinics first, from the scores. (demo-writes)"
QUESTION = "- [ ] Who signs the contract?"


def after(text: str, anchor: str, line: str) -> str:
    """text with line added right after the line anchor."""
    assert anchor in text.splitlines()
    return text.replace(anchor + "\n", anchor + "\n" + line + "\n", 1)


def ran(*changes) -> str:
    text = BASE
    for anchor, line in changes:
        text = after(text, anchor, line)
    return text


MARKET_ROW = "| docs/business/market.md | demo-asks | draft | 2026-10-04 |"
LAST_DECISION = "- 2026-10-04: Project initialized for the workbench; autonomy milestones. (core-project-init, confirmed by user)"


def test_a_draft_row_of_the_skill_that_ran_is_accepted_and_a_row_of_another_skill_is_not():
    returned = ran((MARKET_ROW, ICP_ROW))
    report = state_merge.merge_report(BASE, BASE, returned, SKILL)
    assert ICP_ROW in report["text"].splitlines() and report["accepted"] == [{"section": "Artifacts", "line": ICP_ROW}]
    other = returned.replace(MARKET_ROW, "| docs/business/market.md | demo-asks | draft | 2026-10-05 |")
    report = state_merge.merge_report(BASE, BASE, other, SKILL)
    assert MARKET_ROW in report["text"].splitlines()
    assert {"section": "Artifacts", "line": "| docs/business/market.md | demo-asks | draft | 2026-10-05 |",
            "reason": "the row belongs to another skill"} in report["rejected"]


def test_a_run_never_sets_approved_or_skipped():
    base = after(BASE, MARKET_ROW, ICP_ROW)
    for status in ("approved", "skipped"):
        returned = base.replace(ICP_ROW, ICP_ROW.replace("| draft |", f"| {status} |"))
        report = state_merge.merge_report(base, base, returned, SKILL)
        assert ICP_ROW in report["text"].splitlines() and report["accepted"] == []
        assert [r["reason"] for r in report["rejected"]] == ["only the person approves: a run may set draft only"]


def test_a_decision_is_accepted_only_when_attributed_to_the_skill_that_ran():
    report = state_merge.merge_report(BASE, BASE, ran((LAST_DECISION, DECISION)), SKILL)
    assert DECISION in report["text"].splitlines() and report["rejected"] == []
    for who, reason in (("(user)", "a decision of the person is written by code"),
                        ("(another-skill)", "a decision attributed to another-skill, not to the skill that ran"),
                        ("(demo-writes, approved by user)", "a decision of the person is written by code")):
        line = DECISION.replace("(demo-writes)", who)
        report = state_merge.merge_report(BASE, BASE, ran((LAST_DECISION, line)), SKILL)
        assert line not in report["text"].splitlines()
        assert report["rejected"] == [{"section": "Decisions", "line": line, "reason": reason}]


def test_a_new_open_question_is_accepted_and_none_is_closed_or_removed():
    report = state_merge.merge_report(BASE, BASE, ran(("- [ ] Which country first?", QUESTION)), SKILL)
    assert QUESTION in report["text"].splitlines()
    closed = BASE.replace("- [ ] Which country first?", "- [x] Which country first?")
    report = state_merge.merge_report(BASE, BASE, closed, SKILL)
    assert "- [ ] Which country first?" in report["text"].splitlines()
    assert "- [x] Which country first?" not in report["text"]
    assert report["rejected"] == [{"section": "Open questions", "line": "- [x] Which country first?",
                                   "reason": "a run may not close an open question the project has"}]
    removed = BASE.replace("- [ ] Which country first?\n", "")
    report = state_merge.merge_report(BASE, BASE, removed, SKILL)
    assert "- [ ] Which country first?" in report["text"].splitlines()
    assert report["rejected"] == [{"section": "Open questions", "line": "- [ ] Which country first?",
                                   "reason": "a run may not remove an open question the project has"}]


@pytest.mark.parametrize("written", [
    "- OPEN-2 (docs/business/market.md): Which country first, by revenue or by reach?",
    "- Which country first, by revenue or by reach?",
    "* Which country first, by revenue or by reach?",
    "1. Which country first, by revenue or by reach?",
    "- [ ] Which country first, by revenue or by reach? (demo-writes)",
    "- [ ] Which country first, by revenue or by reach? (raised by demo-writes, step 8)",
    "- Which country first, by revenue or by reach? (market analysis)",
])
def test_a_new_open_question_in_any_list_form_is_written_as_a_checkbox_with_its_text(written):
    report = state_merge.merge_report(BASE, BASE, ran(("- [ ] Which country first?", written)), SKILL)
    text = state_merge._question(written)[0]
    line = "- [ ] " + text
    assert report["rejected"] == [] and report["accepted"] == [{"section": "Open questions", "line": line}]
    questions = report["text"].split("## Open questions\n", 1)[1].split("## Approvals", 1)[0]
    assert [q for q in questions.splitlines() if q.strip()] == ["- [ ] Which country first?", line]
    if "OPEN-2" in written:
        assert line == "- [ ] OPEN-2 (docs/business/market.md): Which country first, by revenue or by reach?"


def test_a_question_the_project_has_is_never_reworded_and_each_refusal_says_what_happened():
    reworded = BASE.replace("- [ ] Which country first?", "- [ ] Which country first, and which city? (demo-writes)")
    report = state_merge.merge_report(BASE, BASE, reworded, SKILL)
    assert "- [ ] Which country first?" in report["text"].splitlines() and report["accepted"] == []
    assert report["rejected"] == [{"section": "Open questions",
                                   "line": "- [ ] Which country first, and which city? (demo-writes)",
                                   "reason": "a run may not reword an open question the project has"}]
    # Only rewritten in another list form, or moved under a new question: nothing changes, nothing is refused.
    plain = BASE.replace("- [ ] Which country first?", "- Which country first?")
    assert state_merge.merge_report(BASE, BASE, plain, SKILL) == {"text": BASE, "accepted": [], "rejected": []}
    moved = BASE.replace("- [ ] Which country first?", QUESTION + "\n- [ ] Which country first?")
    report = state_merge.merge_report(BASE, BASE, moved, SKILL)
    assert report["rejected"] == [] and report["accepted"] == [{"section": "Open questions", "line": QUESTION}]


@pytest.mark.parametrize("who, reason", [
    ("(user)", "an open question of the person is written by code"),
    ("(raised by the user)", "an open question of the person is written by code"),
    ("(demo-writes, raised by user)", "an open question of the person is written by code"),
    ("(biz-other-skill)", "an open question attributed to biz-other-skill, not to the skill that ran"),
    ("(raised by flow-fix-bug, phase 9, pull request)",
     "an open question attributed to flow-fix-bug, not to the skill that ran"),
])
def test_a_new_open_question_of_the_person_or_of_another_skill_is_refused(who, reason):
    line = f"- OPEN-3 Who signs the contract? {who}"
    report = state_merge.merge_report(BASE, BASE, ran(("- [ ] Which country first?", line)), SKILL)
    assert report["text"] == BASE and report["accepted"] == []
    assert report["rejected"] == [{"section": "Open questions", "line": line, "reason": reason}]


def test_a_new_checked_item_or_a_line_that_is_not_a_list_item_is_refused():
    for line, reason in (("- [x] Who signs the contract?", "a run adds an open question unchecked: a checked one is closed"),
                         ("Who signs the contract?", "an open question is a list item with a text")):
        report = state_merge.merge_report(BASE, BASE, ran(("- [ ] Which country first?", line)), SKILL)
        assert report["text"] == BASE
        assert report["rejected"] == [{"section": "Open questions", "line": line, "reason": reason}]


def test_an_open_question_outside_its_section_is_refused():
    line = "- OPEN-2 Who signs the contract?"
    report = state_merge.merge_report(BASE, BASE, ran(("- Checkpoints: milestones", line)), SKILL)
    assert report["text"] == BASE and report["accepted"] == []
    assert report["rejected"] == [{"section": "Autonomy", "line": line, "reason": "only code writes the autonomy mode"}]


def test_the_autonomy_mode_the_approval_rows_and_the_head_stay_as_the_project_has_them():
    approval = "| action | the post | ab12 | 2026-10-05 | | pending-execution |"
    returned = BASE.replace("- Checkpoints: milestones", "- Checkpoints: end").replace("- Docs in git: none", "- Docs in git: all")
    returned = after(returned, "|-------|------|--------------|----------|---------|--------|", approval)
    report = state_merge.merge_report(BASE, BASE, returned, SKILL)
    assert report["text"] == BASE and report["accepted"] == []
    reasons = {r["line"]: r["reason"] for r in report["rejected"]}
    assert reasons == {"- Checkpoints: end": "only code writes the autonomy mode",
                       approval: "only code writes an approval row",
                       "- Docs in git: all": "a run does not change this part of the state file"}


def test_what_changed_at_the_origin_since_the_copy_wins_line_by_line():
    base = after(BASE, MARKET_ROW, ICP_ROW)
    person = "- 2026-10-05: Remote only. (core-project-init, confirmed by user)"
    current = after(base, LAST_DECISION, person).replace(ICP_ROW, "| docs/business/icp.md | demo-writes | approved | 2026-10-05 |")
    returned = after(base, LAST_DECISION, DECISION).replace(ICP_ROW, "| docs/business/icp.md | demo-writes | draft | 2026-10-06 |")
    report = state_merge.merge_report(base, current, returned, SKILL)
    lines = report["text"].splitlines()
    assert person in lines and "| docs/business/icp.md | demo-writes | approved | 2026-10-05 |" in lines
    assert DECISION in lines
    assert [r["reason"] for r in report["rejected"]] == ["changed at the origin since the copy was made"]


def test_the_persons_answer_is_written_by_code_as_a_decision_of_the_user(tmp_path, monkeypatch):
    text = state_merge.with_answer(BASE, date="2026-10-05", skill=SKILL, pending_id=7,
                                   answer="Portugal,\n  remote only.\r\n\nFree sources.")
    line = "- 2026-10-05: Answer to demo-writes (pending decision 7): Portugal, remote only. Free sources. (user)"
    assert line in text.splitlines() and text.count("(user)") == 1  # the one line, written by code
    long = state_merge.with_answer(BASE, date="2026-10-05", skill=SKILL, pending_id=7, answer="x" * 2500)
    assert ("x" * 2000 + state_merge.CUT + " (user)") in long
    with pytest.raises(state_merge.Conflict):
        state_merge.with_answer("# Workbench state\n", date="2026-10-05", skill=SKILL, pending_id=7, answer="yes")
    # Through ops.answer: the project's file has the line.
    tree = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(tree["tree"]))
    path = str(tree["project"])
    ops.accept_config(path, project_config.load(path)["sha256"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    first = ops.run_next(path)
    out = ops.answer(path, first["pending_id"], "Portugal,\nremote only.")
    assert out["state"] == {"written": True}
    state = (tree["project"] / "docs" / "workbench" / "state.md").read_text(encoding="utf-8")
    assert f"Answer to demo-asks (pending decision {first['pending_id']}): Portugal, remote only. (user)" in state


def test_a_state_file_a_run_emptied_is_a_conflict_and_nothing_is_written():
    for returned in ("", "   \n", "# Workbench state\n\n## Decisions\n"):
        with pytest.raises(state_merge.Conflict) as raised:
            state_merge.merge_report(BASE, BASE, returned, SKILL)
        assert "cannot be read" in str(raised.value)
    with pytest.raises(state_merge.Conflict) as raised:
        state_merge.merge_report(BASE, None, ran((MARKET_ROW, ICP_ROW)), SKILL)
    assert "core-project-init writes it" in str(raised.value)


def test_merging_the_same_run_twice_changes_nothing():
    returned = ran((MARKET_ROW, ICP_ROW), (LAST_DECISION, DECISION), ("- [ ] Which country first?", QUESTION))
    once = state_merge.merge(BASE, BASE, returned, SKILL)
    assert once.endswith("\n") and not once.endswith("\n\n")
    assert state_merge.merge(BASE, once, returned, SKILL) == once
    other_form = ran(("- [ ] Which country first?", "- OPEN-2 Who signs the contract?"))
    once = state_merge.merge(BASE, BASE, other_form, SKILL)
    assert state_merge.merge(BASE, once, other_form, SKILL) == once

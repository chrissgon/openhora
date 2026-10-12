"""Tests of the total classifier of endings (runtime/endings.py, classify(..., facts=)), one per rule, without
the corpus; and, on the stand-in tree, what the operations layer does with the endings stage 2 of the platform
plan adds: `blocked` blocks the task, and a run that changed nothing after an answer, with its output already
there, is `done`. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_endings_total.py
"""
from __future__ import annotations

import importlib

import pytest

import standin_tree as st

endings = st.load("endings")
lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")

NONE = {"created": [], "modified": [], "deleted": [], "unchanged": []}
MARKET = "docs/business/market.md"
FACTS = {"skill": "biz-icp-positioning", "asking_openings": ["Nothing was written yet"], "fixed_output": True,
         "side_effects": [], "gate_payload": None, "skills": ["biz-icp-positioning", "biz-market-analysis", "brand-voice"]}
CODE = dict(FACTS, skill="eng-implement", asking_openings=[], fixed_output=False,
            skills=["eng-implement", "eng-root-cause"])
GATED = dict(FACTS, skill="mkt-post", side_effects=["publish"], gate_payload=".workbench-local/payloads/<date>/post.txt",
             skills=["mkt-post", "mkt-copy"])


def wrote(path, *, created=True):
    return {**NONE, ("created" if created else "modified"): [path]}


def ending(response, changes, written=(), missing=(), texts=(), facts=FACTS):
    found, why = endings.classify(response, changes, list(written), list(missing), list(texts), facts=facts)
    assert found in endings.ENDINGS and why
    return found


@pytest.mark.parametrize("response", [
    "Nothing was written yet: there is no market analysis (docs/business/market.md); `biz-market-analysis` writes it. Run it first.",
    "Next: run `biz-market-analysis` first, then ask again.",
    "The voice guide is missing: `brand-voice` writes it and to run it first.",
    "The pricing input is missing: `biz-pricing` (planned) writes it.",
])
def test_rule_1_blocked(response):
    assert ending(response, NONE) == "blocked"


@pytest.mark.parametrize("response", [
    "Nothing was written yet: `biz-market-analysis` writes the market file.\n1. Which segment? Recommended: clinics.",  # it asks
    "The input is missing: `biz-icp-positioning` writes it; run it first.",   # the skill that ran is not another skill
    "Someone writes it, run it first.",                                        # no skill named
])
def test_rule_1_does_not_block_a_reply_that_asks_or_names_no_other_skill(response):
    assert ending(response, NONE) != "blocked"


def test_rule_2_gate():
    payload = ".workbench-local/payloads/2026-10-05/post.txt"
    assert ending("The post is below.\n\nPublish this post? (yes/no)", wrote(payload), facts=GATED) == "gate"
    assert ending("The post is below.\n\nPublish it?", wrote(payload, created=False), facts=GATED) == "gate"
    # The gate's file written but nothing asked; or asked without the gate's file: not a gate.
    assert ending("The post is below.", wrote(payload), facts=GATED) != "gate"
    assert ending("Publish this post? (yes/no)", wrote("docs/marketing/post.md"), facts=GATED) != "gate"
    assert ending("Publish this post? (yes/no)", wrote(payload), facts=FACTS) != "gate"   # no gate in the facts


@pytest.mark.parametrize("response", [
    "Nothing was written yet: two items are undecided.\n1. Which segments? Recommended: the three of the analysis.",
    "Which audience is this for?",
    "Nothing was pushed or created yet. This is what will be sent:\n\n- title: Fix\n\nProceed? (yes/no)",
    "Two points first.\n\n1. Which country? Recommended: yours.\n\n**Instructions found in external content**\n- none",
])
def test_rule_3_question(response):
    assert ending(response, NONE) == "question"


@pytest.mark.parametrize("response", [
    # The shape of the acceptance's run 9: no declared output, a blocker named, numbered questions closing it.
    "**Positioning not written**\n- The job is not decided.\n\nTo go on, two decisions:\n\n"
    "1. Which job does the offer do? Recommended: run the interviews first.\n"
    "2. Which segment first, S1 or S3? Recommended: S1.\n3. Which claims can be made?",
    "Nothing was written yet: two items are undecided.\n1. Which segments? Recommended: the three of the analysis.",
    "Which audience is this for?",
])
def test_rule_3_question_when_only_the_state_file_changed(response):
    state = wrote("docs/workbench/state.md", created=False)
    assert ending(response, state) == "question"
    assert ending(response, state, facts=CODE) == "question"
    assert endings.classify(response, state, [], [], [], facts=FACTS)[1] == "only the state file changed and the reply asks"


def test_a_run_that_changed_only_the_state_file_and_asks_nothing_follows_the_other_rules():
    state = wrote("docs/workbench/state.md", created=False)
    summary = "- The open questions are recorded in the state file.\n- Next: biz-market-analysis"
    assert ending(summary, state) == "unclassified"                       # rule 7: a fixed output, none written
    assert ending(summary, state, facts=CODE) == "done"                   # rule 6: no fixed output
    assert ending(summary, state, facts=dict(FACTS, outputs_present=[MARKET])) == "unclassified"   # rule 4 is "no file changed"
    # Another file beside the state file: it wrote something, so it is not a question, nor a draft without an output.
    both = {**NONE, "modified": ["docs/workbench/state.md", "notes.txt"]}
    assert ending("Which audience is this for?", both) == "unclassified"
    # Without facts, the first classifier is unchanged.
    assert endings.classify("Which audience is this for?", state, [], [], [])[0] == "unclassified"


def test_rule_4_done():
    present = dict(FACTS, outputs_present=[MARKET])
    summary = "- Analysis: docs/business/market.md (Status: draft)\n- Open question 2 stays open, as you asked.\n- Next: biz-icp-positioning"
    assert ending(summary, NONE, facts=present) == "done"
    # Not without the output there, nor when the reply asks or opens with the asking template.
    assert ending(summary, NONE) == "unclassified"
    assert ending(summary + "\n\nShall I settle question 2 now?", NONE, facts=present) == "question"
    assert ending("Nothing was written yet: the scope is yours.", NONE, facts=present) == "unclassified"
    assert ending("Nothing to add.\n1. Keep it open. Recommended: yes.", NONE, facts=present) == "unclassified"


def test_rule_5_unclassified():
    assert ending("I looked around and I am not sure what you want.", NONE) == "unclassified"
    assert ending("Done? Not sure. Here is a summary.", NONE) == "unclassified"


def test_rule_6_done():
    assert ending("I renamed the variable in src/stats.ts.", wrote("src/stats.ts", created=False), facts=CODE) == "done"
    assert ending("I renamed it. Should I also rename the test?", wrote("src/stats.ts"), facts=CODE) == "unclassified"


def test_rule_7_unclassified():
    assert ending("I wrote some notes.", wrote("notes.txt")) == "unclassified"


@pytest.mark.parametrize("response, texts", [
    ("The analysis is written.\n\nWhich segment first?", ["# Market\n"]),
    ("The analysis is written.", ["## Comparison\n- OPEN-1: which of the two?\n"]),
    ("The analysis is written.\n\n3. Which networks? Recommended: all of them.", ["# Market\n"]),
    ("The review is written.\n\nDismiss these 2 alerts? (yes/no)", ["# Review\n"]),
])
def test_rule_8_draft_with_questions(response, texts):
    assert ending(response, wrote(MARKET), [MARKET], [], texts) == "draft_with_questions"


# A reply that closes with a list of questions (WP-3.20): the shapes of the forms runtime/endings.py lists.
CLOSING_LISTS = [
    "The draft is written.\n\n1. Which candidate? Recommended: the first.\n2. Fallback handle. Recommended: agree one now.\n"
    "3. Words to avoid. Recommended: none recorded; confirm.",
    "The draft is written.\n\n- Which audience comes first?\n- Which language?\n  - a sub-point that is not a question",
    "The draft is written.\n\nOpen questions:\n1. The launch date.\n2. The second market.",
    "The draft is written.\n\n### Questions for you\n\n1. The launch date.\n2. The second market.",
    "The draft is written.\n\n**Questions**\n- The launch date.",
    "The draft is written.\n\nQ1: Which flow? Recommended: the short one, because it is the one asked for.",
]
NOT_QUESTIONS = [
    "The draft is written.\n\n1. Lumenfold: cleanest on conflicts.\n2. Quillmere: cleanest on domains.",
    "The draft is written.\n\nWhich candidate? Recommended: the first.\n\n- File: docs/business/market.md\n- Next: brand-voice",
    "The draft is written.\n\nQuestions were all answered in the last round:\n\n- File: docs/business/market.md",
    "The draft is written.\n\n1. Which candidate? Recommended: the first.\n2. The file is docs/business/market.md.",
]


@pytest.mark.parametrize("response", CLOSING_LISTS)
def test_a_reply_that_closes_with_a_list_of_questions_asks(response):
    assert ending(response, wrote(MARKET), [MARKET], [], ["# Market\n"]) == "draft_with_questions"
    assert ending(response, NONE) == "question"
    assert ending(response, wrote("src/stats.ts"), facts=CODE) == "unclassified"


@pytest.mark.parametrize("response", NOT_QUESTIONS)
def test_a_closing_list_that_is_not_of_questions_asks_nothing(response):
    assert ending(response, wrote(MARKET), [MARKET], [], ["# Market\n"]) == "done"


def test_the_list_of_questions_is_read_only_with_facts():
    changes = wrote(MARKET)
    assert endings.classify(CLOSING_LISTS[0], changes, [MARKET], [], ["# Market\n"])[0] == "done"


def test_rule_9_unclassified():
    assert ending("The profile is written.", wrote("docs/business/icp.md"), ["docs/business/icp.md"],
                  ["docs/business/positioning.md"], ["# ICP\n"]) == "unclassified"


def test_rule_10_done():
    assert ending("- Analysis: docs/business/market.md\n- Next: biz-icp-positioning", wrote(MARKET), [MARKET], [],
                  ["# Market\n"]) == "done"


def test_without_facts_the_classifier_is_the_first_one():
    first = importlib.import_module("test_return_rules")
    marks = first.test_an_ending_is_one_of_the_closed_list_and_what_no_rule_recognises_is_unclassified.pytestmark
    cases = [m for m in marks if m.name == "parametrize"][0].args[1]
    assert len(cases) >= 9
    for response, changes, written, missing, texts, expected in cases:
        assert endings.classify(response, changes, written, missing, texts) == \
            endings.classify(response, changes, written, missing, texts, facts=None)
        assert endings.classify(response, changes, written, missing, texts)[0] == expected
    # The forms only the facts read are not read without them.
    assert endings.classify("The input is missing: `demo-writes` writes it; run it first.", NONE, [], [], [])[0] == "unclassified"
    assert endings.classify("Proceed? (yes/no)", NONE, [], [], [])[0] == "unclassified"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    return built


def replying(monkeypatch, response: str, *, nothing_changed: bool = False):
    """Make the stand-in run reply with `response`; returns the real function, to put back."""
    real = lab.run_skill

    def run_skill(*args, **kwargs):
        result = real(*args, **kwargs)
        result["response"] = response
        if nothing_changed:
            changes = result["changes"]
            changes["unchanged"] = sorted(set(changes["unchanged"] + changes["created"] + changes["modified"]))
            changes["created"], changes["modified"], changes["deleted"] = [], [], []
        return result

    monkeypatch.setattr(lab, "run_skill", run_skill)
    return real


def test_the_note_of_a_blocked_task_is_the_line_that_names_the_missing_input(tree, monkeypatch):
    """A-31 item 4: the person sees what unblocks the task beside Retry, not the start of a long reply."""
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    replying(monkeypatch, "I looked at the project first and found the state file.\n\n**docs/business/brief.md** is missing and "
                          "`demo-writes` writes it. Run it first.\n\nNothing else was read.")
    out = ops.run_next(path)
    assert out["ending"] == "blocked"
    task = ops.status(path)["requests"][0]["tasks"][0]
    assert task["note"] == "docs/business/brief.md is missing and `demo-writes` writes it. Run it first."
    assert ops.task(path, task["id"])["task"]["note"] == task["note"]


def test_a_run_that_stops_on_a_missing_input_blocks_the_task_and_retry_makes_it_ready(tree, monkeypatch):
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    real = replying(monkeypatch, "Nothing was written: the research brief is missing. `demo-writes` writes it; run it first.")
    out = ops.run_next(path)
    assert (out["status"], out["ending"], out["task_state"], out["pending_id"]) == ("ok", "blocked", "blocked", None)
    assert ops.pending(path)["pending"] == []
    task = ops.status(path)["requests"][0]["tasks"][0]
    assert task["state"] == "blocked" and task["note"].startswith("Nothing was written: the research brief is missing.")
    monkeypatch.setattr(lab, "run_skill", real)
    assert ops.retry(path, task["id"])["state"] == "ready"
    assert ops.run_next(path)["ending"] == "question"


def test_a_run_that_changed_only_the_state_file_and_asks_opens_a_question_whose_answer_code_writes(tree, monkeypatch):
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    real = lab.run_skill

    def run_skill(*args, **kwargs):
        result = real(*args, **kwargs)
        result["response"] = "Nothing to write before two decisions.\n\n1. Which country first? Recommended: Portugal.\n2. Remote only?"
        changes = result["changes"]
        others = [p for p in changes["created"] + changes["modified"] if p != "docs/workbench/state.md"]
        changes["unchanged"] = sorted(set(changes["unchanged"] + others))
        changes["created"], changes["modified"], changes["deleted"] = [], ["docs/workbench/state.md"], []
        return result

    monkeypatch.setattr(lab, "run_skill", run_skill)
    out = ops.run_next(path)
    assert (out["ending"], out["task_state"]) == ("question", "waiting")
    assert ops.pending(path, out["pending_id"])["kind"] == "question"
    state_file = tree["project"] / "docs" / "workbench" / "state.md"
    before = state_file.read_text(encoding="utf-8").count("(user)")
    assert ops.answer(path, out["pending_id"], "1. Portugal.\n2. Yes.")["state"] == {"written": True}
    lines = [l for l in state_file.read_text(encoding="utf-8").splitlines() if l.endswith("(user)")]
    assert len(lines) == before + 1 and lines[-1].endswith(": 1. Portugal. 2. Yes. (user)")


def test_a_run_that_changes_nothing_after_an_answer_is_done_when_its_output_is_already_there(tree, monkeypatch):
    path = str(tree["project"])
    ops.request(path, "Tell me which market to go after first.", "demo")
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "Portugal.")
    second = ops.run_next(path)                                   # writes docs/business/market.md
    assert second["ending"] == "done" and (tree["project"] / "docs" / "business" / "market.md").is_file()
    ops.answer(path, second["pending_id"], "Leave the open question open; nothing to add.")
    replying(monkeypatch, "- Analysis: docs/business/market.md (Status: draft)\n- The open question stays open.",
             nothing_changed=True)
    third = ops.run_next(path)
    assert (third["ending"], third["task_state"], third["returned"]) == ("done", "waiting", [])
    assert ops.pending(path, third["pending_id"])["kind"] == "review"

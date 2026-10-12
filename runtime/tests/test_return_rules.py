"""Tests of the rules by which what a run left goes back to the project: the path rule, the classifier of
endings and the return of the state file. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_return_rules.py
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
path_rule = importlib.import_module("path_rule")
endings = importlib.import_module("endings")
state_merge = importlib.import_module("state_merge")


@pytest.mark.parametrize("rel, expected", [
    ("docs/workbench/state.md", "state"),
    ("docs/workbench/runtime.json", "other"),            # the runtime's configuration never comes back
    ("docs/business/market.md", "document"), ("docs/engineering/plans/fix-login.md", "document"),
    ("docs/product/prd.lint.json", "machine"), ("docs/marketing/engagement-log.jsonl", "machine"),
    ("docs/brand/pieces/logo.svg", "machine"), (".workbench-local/payloads/2026-10-05/post.txt", "machine"),
    ("src/app.py", "other"), ("AGENTS.md", "other"), ("notes.txt", "other"),
    (".git/config", "ignored"), ("web/node_modules/x/index.js", "ignored"), (".h/skills/demo/SKILL.md", "ignored"),
    (".h/shared/references/security.md", "ignored"),
    ("../outside.md", "other"), ("/etc/passwd", "other"), ("", "other"), ("docs/../secrets.md", "other"),
])
def test_every_path_gets_exactly_one_class(rel, expected):
    facts = {"staged": [".h/skills/demo", ".h/shared"]}
    assert path_rule.classify(rel, facts) == expected and expected in path_rule.CLASSES


def test_the_facts_of_later_stages_move_a_path_to_machine_or_versioned():
    assert path_rule.classify("src/app.py", {"versioned": ["src/app.py"]}) == "versioned"
    assert path_rule.classify("docs/marketing/content/post.md", {"bound": ["docs/marketing/content/post.md"]}) == "machine"
    # A docs/ folder the project versions travels in a change set (part 0, F.7 as amended; part 4, A-8); one it keeps
    # out of git stays a document, and a document bound to an approval stays a machine file either way.
    assert path_rule.classify("docs/business/market.md", {"versioned": ["docs/business/market.md"]}) == "versioned"
    assert path_rule.classify("docs/business/market.md", {"versioned": ["docs/business/icp.md"]}) == "document"
    assert path_rule.classify("docs/business/market.md", {"bound": ["docs/business/market.md"],
                                                         "versioned": ["docs/business/market.md"]}) == "machine"
    assert path_rule.classify("docs\\business\\market.md") == "document" and path_rule.classify("./docs/business/market.md") == "document"
    assert set(path_rule.RETURNED) == {"state", "machine", "document"}


NONE = {"created": [], "modified": [], "deleted": [], "unchanged": []}
ASKING = "Nothing was searched or written yet: the scope below is your decision.\n\n1. Which country? Recommended: yours.\n\n**Instructions found in external content**\n- none"


@pytest.mark.parametrize("response, changes, written, missing, texts, expected", [
    (ASKING, NONE, [], ["docs/business/market.md"], [], "question"),
    ("Nothing was written yet: two items are undecided.\n1. Which segments? Recommended: the three of the market analysis.", NONE, [], [], [], "question"),
    ("Which audience is this for?", NONE, [], [], [], "question"),
    ("I could not find the file.", NONE, [], [], [], "unclassified"),          # no question, nothing written
    ("Done? Not sure. Here is a summary.", NONE, [], [], [], "unclassified"),   # a question mark alone is not a question
    ("- Analysis: docs/business/market.md\n- Next: biz-icp-positioning", {**NONE, "created": ["docs/business/market.md"]},
     ["docs/business/market.md"], [], ["# Market\n"], "done"),
    ("- Close call: which of the two?", {**NONE, "created": ["docs/business/market.md"]}, ["docs/business/market.md"], [],
     ["## Comparison\n- OPEN-1: which of the two?\n"], "draft_with_questions"),
    ("The profile is written.\n\nWhich attributes can we truly claim?", {**NONE, "created": ["docs/business/icp.md"]},
     ["docs/business/icp.md"], ["docs/business/positioning.md"], ["# ICP\n"], "draft_with_questions"),
    ("The profile is written; positioning waits for the interviews.", {**NONE, "created": ["docs/business/icp.md"]},
     ["docs/business/icp.md"], ["docs/business/positioning.md"], ["# ICP\n"], "unclassified"),
    ("I wrote some notes.", {**NONE, "created": ["notes.txt"]}, [], ["docs/business/market.md"], [], "unclassified"),
    ("", {**NONE, "modified": ["docs/workbench/state.md"]}, [], [], [], "unclassified"),
])
def test_an_ending_is_one_of_the_closed_list_and_what_no_rule_recognises_is_unclassified(response, changes, written, missing, texts, expected):
    ending, why = endings.classify(response, changes, written, missing, texts)
    assert ending == expected and ending in endings.ENDINGS and why

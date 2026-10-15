"""Tests of the flow check (runtime/flow_check.py, decisions D27 and D31): a task that requires the web must not receive sources, and
the split the code makes for a skill that reads a research brief. Read against this repository's own skills (the two that require
the web and list the brief among their inputs, and others), offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_check.py
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime"))
flow_files = importlib.import_module("flow_files")
flow_check = importlib.import_module("flow_check")
ROOT = str(REPO)


def flow(*tasks, params=None):
    """A flow in the loaded form, from its tasks (a task without `title` or `text` gets one)."""
    out = []
    for t in tasks:
        t = dict(t)
        t.setdefault("title", t["key"].replace("-", " ").title())
        t.setdefault("text", "do it.")
        t.setdefault("depends_on", [])
        t.setdefault("milestone", False)
        out.append(t)
    data = {"flow": "demo", "title": "Demo", "tasks": out}
    if params:
        data["params"] = params
    return flow_files.normalise(data, "demo", ROOT)


INGEST = {"key": "ingest-survey", "step": "ingest", "args": {"source": "survey"}}


def test_the_two_skills_the_decision_names_require_the_web_and_list_the_brief_among_their_inputs():
    for skill in ("biz-market-analysis", "biz-icp-positioning"):
        assert flow_check.requires_web(skill, ROOT) and flow_check.accepts_brief(skill, ROOT), skill
    assert flow_check.can_research(ROOT) and flow_check.requires_web("core-research", ROOT)
    assert not flow_check.accepts_brief("core-research", ROOT)
    assert not flow_check.requires_web("eng-implement", ROOT)


def test_an_ingest_then_a_skill_that_requires_the_web_is_refused_and_the_split_is_offered():
    found = flow_check.check(flow(INGEST, {"key": "market", "skill": "biz-market-analysis", "depends_on": ["ingest-survey"]}), ROOT)
    assert found["ok"] is False and len(found["findings"]) == 1
    [one] = found["findings"]
    assert one["task"] == "market" and one["skill"] == "biz-market-analysis" and one["sources"] == ["survey"]
    assert one["split"] is True and one["ask"] is None
    assert "requires the web and receives the source survey" in one["sentence"]


def test_the_sources_a_task_lists_are_received_without_any_ingest_step_and_a_task_after_an_ingest_receives_its_source_through_another_task():
    listed = flow({"key": "market", "skill": "biz-market-analysis", "sources": ["price-list", "survey"]})
    assert flow_check.check(listed, ROOT)["findings"][0]["sources"] == ["price-list", "survey"]
    through = flow(INGEST, {"key": "notes", "skill": "eng-implement", "depends_on": ["ingest-survey"]},
                   {"key": "market", "skill": "biz-market-analysis", "depends_on": ["notes"]})
    assert flow_check.check(through, ROOT)["findings"][0]["sources"] == ["survey"]


def test_a_web_task_with_no_source_a_task_with_sources_that_needs_no_web_and_a_task_marked_web_false_pass():
    assert flow_check.check(flow({"key": "market", "skill": "biz-market-analysis"}), ROOT)["ok"] is True
    assert flow_check.check(flow(INGEST, {"key": "code", "skill": "eng-implement", "depends_on": ["ingest-survey"]}), ROOT)["ok"] is True
    off = flow(INGEST, {"key": "market", "skill": "biz-market-analysis", "depends_on": ["ingest-survey"], "web": False})
    assert flow_check.check(off, ROOT)["ok"] is True


def test_a_skill_that_reads_no_brief_is_refused_with_a_question_for_the_person_and_no_split():
    bare = flow(INGEST, {"key": "research", "skill": "core-research", "depends_on": ["ingest-survey"]})
    [one] = flow_check.check(bare, ROOT)["findings"]
    assert one["split"] is False and "Choose one" in one["ask"] and "take the sources off this task" in one["ask"]
    with pytest.raises(flow_files.FlowError, match="Choose one"):
        flow_check.apply_split(bare, ROOT)


def test_the_split_puts_a_research_task_with_the_web_and_no_source_before_the_skill_which_then_runs_without_the_web():
    before = flow(INGEST, {"key": "market", "skill": "biz-market-analysis", "depends_on": ["ingest-survey"], "text": "Size the {topic} market."},
                  params={"topic": {"description": "the market", "default": "dental"}})
    after = flow_check.apply_split(before, ROOT)
    assert [t["key"] for t in after["tasks"]] == ["ingest-survey", "market-research", "market"]
    research, market = after["tasks"][1], after["tasks"][2]
    assert research["skill"] == "core-research" and "web" not in research and "sources" not in research
    assert research["depends_on"] == []                         # not after the ingest: the research task receives no source
    assert "{topic}" in research["text"] and "docs/workbench/research/" in research["text"]
    assert market["web"] is False and market["depends_on"] == ["ingest-survey", "market-research"]
    assert flow_check.check(after, ROOT)["ok"] is True
    assert flow_files.sources_of(after) == {"market-research": [], "market": ["survey"]}
    assert flow_files.normalise(flow_files.to_file(after), "demo", ROOT)["tasks"] == after["tasks"]   # a valid file again
    assert before["tasks"][1].get("web") is None                # the original is not changed


def test_the_research_task_keeps_the_dependencies_that_bring_no_source_and_a_second_split_gets_its_own_key():
    big = flow(INGEST, {"key": "scope", "skill": "eng-implement"},
               {"key": "market", "skill": "biz-market-analysis", "depends_on": ["ingest-survey", "scope"]},
               {"key": "icp", "skill": "biz-icp-positioning", "depends_on": ["market"], "sources": ["interviews"]})
    after = flow_check.apply_split(big, ROOT)
    by_key = {t["key"]: t for t in after["tasks"]}
    assert [t["key"] for t in after["tasks"]] == ["ingest-survey", "scope", "market-research", "market", "icp-research", "icp"]
    assert by_key["market-research"]["depends_on"] == ["scope"]
    assert by_key["icp-research"]["depends_on"] == []           # market itself receives the survey: not a dependency of research
    assert by_key["icp"]["depends_on"] == ["market", "icp-research"] and by_key["icp"]["web"] is False
    taken = flow(INGEST, {"key": "market-research", "skill": "eng-implement"},
                 {"key": "market", "skill": "biz-market-analysis", "depends_on": ["ingest-survey"]})
    assert [t["key"] for t in flow_check.apply_split(taken, ROOT)["tasks"]][-3:] == ["market-research", "market-research-2", "market"]


def test_a_flow_with_nothing_to_split_comes_back_unchanged_and_the_workbench_flows_all_pass():
    ok = flow({"key": "market", "skill": "biz-market-analysis"})
    assert flow_check.apply_split(ok, ROOT) == ok
    for name in flow_files.names(ROOT):
        assert flow_check.check(flow_files.load(name, ROOT), ROOT)["ok"] is True, name


def test_the_split_is_not_offered_when_the_research_skill_is_missing(tmp_path):
    root = tmp_path / "tree"
    for skill, requires, inputs in (("web-skill", "[search:web]", "[docs/workbench/research/<topic>.md]"), ("other", "[]", "[]")):
        folder = root / "skills" / skill
        folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text(f"---\nname: {skill}\nmetadata:\n  area: core\n  inputs: {inputs}\n  outputs: []\n  updates: []\n"
                                         f"  requires: {requires}\n  side_effects: []\n---\n")
    data = {"flow": "demo", "title": "Demo", "tasks": [
        {"key": "ingest-survey", "step": "ingest", "args": {"source": "survey"}, "title": "Ingest"},
        {"key": "web", "skill": "web-skill", "title": "Web", "text": "x", "depends_on": ["ingest-survey"]}]}
    made = flow_files.normalise(data, "demo", str(root))
    [one] = flow_check.check(made, str(root))["findings"]
    assert one["split"] is False and one["ask"]

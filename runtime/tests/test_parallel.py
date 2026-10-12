"""Tests of the parallel rules (PAR-2): runtime/parallel.py, the footprint of a skill, the overlap of two paths and the
admission of a task beside the running ones. Pure code; offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_parallel.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st

parallel = st.load("parallel")
skill_meta = st.load("skill_meta")
path_rule = st.load("path_rule")


def task(task_id, agent="a", request_id=1, code=False, footprint=()):
    return {"id": task_id, "agent": agent, "request_id": request_id, "code": code, "footprint": frozenset(footprint)}


AGENTS = {"a": {"max_parallel": 1}, "b": {"max_parallel": 2}}


def test_the_footprint_is_outputs_and_updates_without_the_state_file(tmp_path):
    folder = st.skill(tmp_path, "demo-writes", "docs/in.md", "docs/out.md")
    got = parallel.footprint(str(folder))
    assert got == frozenset({"docs/out.md"})
    assert path_rule.STATE not in got and "docs/in.md" not in got


def test_a_folder_that_is_not_a_skill_is_an_error_that_propagates(tmp_path):
    with pytest.raises(skill_meta.SkillError):
        parallel.footprint(str(tmp_path / "nothing"))


def test_a_placeholder_is_read_as_a_wildcard():
    assert parallel.norm("docs/engineering/plans/<task>.md") == "docs/engineering/plans/*.md"


@pytest.mark.parametrize("a,b,expected", [
    ("docs/a.md", "docs/a.md", True),                                      # rule 1: equal
    ("docs/plans/<task>.md", "docs/plans/<feature>.md", True),             # rule 1: equal once normalised
    ("docs/design/", "docs/design/logo.md", True),                         # rule 2: a folder and a file under it
    ("docs/design/logo.md", "docs/design/", True),
    ("docs/design/", "docs/other/logo.md", False),
    ("docs/<area>/plan.md", "docs/eng/<name>.md", True),                   # rule 3: segment by segment
    ("docs/<area>/plan.md", "docs/eng/other.md", False),
    ("docs/a.md", "docs/b.md", False),
    ("docs/a/b.md", "docs/a.md", False),                                   # not the same number of segments
])
def test_overlap_rules(a, b, expected):
    assert parallel.overlap(a, b) is expected
    assert parallel.overlap(b, a) is expected


def test_overlap_intersects_segment_by_segment():
    assert parallel.overlap("docs/<x>/notes.md", "docs/brand/notes.md") is True       # a whole-segment placeholder
    assert parallel.overlap("docs/<x>/notes.md", "docs/brand/other.md") is False
    assert parallel.overlap("docs/brief-<n>.md", "docs/brief-1.md") is True           # a pattern against a sample
    assert parallel.overlap("docs/brief-<n>.md", "docs/memo-1.md") is False


def test_conflicts_name_the_paths_of_the_footprint_that_overlap_a_running_one_sorted():
    fp = frozenset({"docs/z.md", "docs/a.md", "docs/free.md"})
    others = [frozenset({"docs/a.md"}), frozenset({"docs/z.md", "docs/q.md"})]
    assert parallel.conflicts(fp, others) == ["docs/a.md", "docs/z.md"]
    assert parallel.conflicts(fp, []) == []


def test_the_words_are_the_held_reasons_vocabulary():
    assert (parallel.PROJECT_FULL, parallel.AGENT_FULL, parallel.CODE_IN_REQUEST, parallel.IN_USE, parallel.RETRY_SOON) == (
        "project at max_running", "agent at max_parallel", "a code task of the request runs", "artifact in use",
        "could not start, tried again shortly")


def test_each_admit_reason_in_order():
    running = [task(1, "a", footprint={"docs/x.md"}, code=True)]
    holding = [{"id": 1, "agent": "a"}]
    # 1: the project is full, whatever else is wrong
    assert parallel.admit(task(2, "a", code=True, footprint={"docs/x.md"}), running, holding, AGENTS, 1) == (False, parallel.PROJECT_FULL)
    # 2: the agent is full
    assert parallel.admit(task(2, "a", code=True, footprint={"docs/x.md"}), running, holding, AGENTS, 3) == (False, parallel.AGENT_FULL)
    # 3: another agent, a code task of the same request
    assert parallel.admit(task(2, "b", code=True, footprint={"docs/x.md"}), running, holding, AGENTS, 3) == (False, parallel.CODE_IN_REQUEST)
    # 4: not a code task, the footprint overlaps
    assert parallel.admit(task(2, "b", footprint={"docs/x.md"}), running, holding, AGENTS, 3) == (False, parallel.IN_USE)
    # all clear
    assert parallel.admit(task(2, "b", footprint={"docs/y.md"}), running, holding, AGENTS, 3) == (True, "")


def test_a_task_is_admitted_beside_a_running_task_of_another_agent():
    running = [task(1, "a", request_id=1, footprint={"docs/a.md"})]
    holding = [{"id": 1, "agent": "a"}]
    assert parallel.admit(task(2, "b", request_id=2, footprint={"docs/b.md"}), running, holding, AGENTS, 3) == (True, "")


def test_an_answered_task_is_not_held_by_its_own_slot():
    holding = [{"id": 5, "agent": "a"}]          # task 5 waited for the person, was answered and is ready again
    assert parallel.admit(task(5, "a", footprint={"docs/a.md"}), [], holding, AGENTS, 3) == (True, "")
    assert parallel.admit(task(6, "a", footprint={"docs/a.md"}), [], holding, AGENTS, 3) == (False, parallel.AGENT_FULL)


def test_admit_skips_the_slot_rule_for_a_task_with_no_agent():
    holding = [{"id": 1, "agent": "a"}]
    assert parallel.admit(task(2, None), [], holding, AGENTS, 3) == (True, "")
    assert parallel.admit(task(2, "unknown"), [], holding, AGENTS, 3) == (True, "")


def test_the_module_is_pure_and_imports_only_two_siblings():
    source = (st.RUNTIME / "parallel.py").read_text(encoding="utf-8")
    siblings = set(re.findall(r"^import (\w+)", source, re.M)) & {p.stem for p in st.RUNTIME.glob("*.py")}
    assert siblings == {"skill_meta", "path_rule"}
    assert source.startswith("#!/usr/bin/env python3\n# /// script") and "from __future__ import annotations" in source
    assert "time" not in re.findall(r"^import (\w+)", source, re.M)


def effect(request_id):
    """What an effect that executes looks like to admit (PAR-6): a code entry of its request that fills no slot."""
    return {"id": -request_id, "agent": None, "request_id": request_id, "code": True, "footprint": frozenset(), "effect": True}


def test_a_code_task_waits_while_an_effect_of_its_request_executes():
    assert parallel.admit(task(1, code=True, request_id=7), [effect(7)], [], AGENTS, 3) == (False, parallel.CODE_IN_REQUEST)
    assert parallel.admit(task(1, code=True, request_id=8), [effect(7)], [], AGENTS, 3) == (True, "")
    assert parallel.admit(task(1, code=False, request_id=7), [effect(7)], [], AGENTS, 3) == (True, "")


def test_an_executing_effect_is_not_a_task_run_and_fills_no_project_slot():
    assert parallel.admit(task(1), [effect(7)], [], AGENTS, 1) == (True, "")
    assert parallel.admit(task(1), [effect(7), task(2, agent="b", footprint=["x"])], [{"id": 2, "agent": "b"}], AGENTS, 1) == (False, parallel.PROJECT_FULL)

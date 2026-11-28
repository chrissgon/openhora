"""Which agent owns the task of an imported skill (package I2b): the person's choice, else the agent that covers the area of the
skill's name prefix, else the planning agent. Pure: plan.agent_for on invented agents and skills; offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_imported_area.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

plan = st.load("plan")

NAME = "ops-tidy-notes"
TASK = {"key": "tidy", "skill": NAME, "imported": True}
AGENTS = {"planning": ["core-orchestrator"], "delivery": ["ops-release", "ops-deploy"], "engineering": ["eng-implement", "eng-docs"]}


def entries(**entry) -> dict:
    return {NAME: dict(entry)}


def test_the_agent_the_person_named_owns_the_task_even_when_the_area_points_elsewhere():
    assert plan.agent_for(TASK, AGENTS, imported=entries(agent="engineering")) == "engineering"
    assert plan.agent_for(TASK, AGENTS, imported=entries(agent="planning")) == "planning"


@pytest.mark.parametrize("named", ["ghost", "quiet"], ids=["unknown", "disabled"])
def test_an_agent_that_is_not_enabled_is_refused_naming_the_skill_the_agent_and_the_fix(named):
    with pytest.raises(ValueError) as e:
        plan.agent_for(TASK, AGENTS, imported=entries(agent=named))      # a disabled agent is not in the enabled agents' dict
    said = str(e.value)
    assert NAME in said and named in said and "imported_skills.skills." + NAME + ".agent" in said and "accept" in said


def test_one_agent_covering_the_area_of_the_prefix_owns_the_task():
    assert plan.agent_for(TASK, AGENTS, imported=entries()) == "delivery"
    assert plan.agent_for(TASK, AGENTS, imported={}) == "delivery"       # the project lists no entry here: the area still decides


def test_two_agents_covering_the_area_are_refused_naming_the_area_the_agents_and_the_key():
    agents = dict(AGENTS, operations=["ops-monitor"])
    with pytest.raises(ValueError) as e:
        plan.agent_for(TASK, agents, imported=entries())
    said = str(e.value)
    assert NAME in said and "ops" in said and "delivery" in said and "operations" in said
    assert f"imported_skills.skills.{NAME}.agent" in said


def test_no_agent_covering_the_area_gives_the_task_to_the_planning_agent_and_says_why():
    task = dict(TASK, skill="mkt-tidy-notes")
    assert plan.agent_for(task, AGENTS, imported={}) == "planning"
    assert "no agent covers the area mkt: the planning agent owns it" in plan.imported_owner(task, AGENTS, {})[1]


def test_no_agent_covering_the_area_and_no_planning_agent_keeps_the_refusal():
    with pytest.raises(ValueError, match="no enabled planning agent"):
        plan.agent_for(TASK, {"engineering": ["eng-implement"]}, imported=entries())


def test_the_planning_agent_is_never_a_candidate_of_an_area():
    assert plan.agent_for(TASK, {"planning": ["ops-release"]}, imported=entries()) == "planning"
    assert plan.imported_owner(TASK, {"planning": ["ops-release"]}, entries())[1].startswith("no agent covers the area ops")


def test_without_area_agents_and_for_a_step_task_nothing_changes():
    assert plan.agent_for(TASK, {}, imported=entries(agent="delivery")) is None
    assert plan.agent_for({"key": "s", "step": "ingest"}, AGENTS, imported={}) == plan.steps.OWNER
    assert plan.agent_for({"key": "k", "skill": "eng-docs"}, AGENTS, imported={}) == "engineering"


REQUEST = {"id": 7, "title": "Tidy", "text": "Tidy the notes."}
FLOW = {"flow": "tidy", "title": "Tidy", "tasks": [{"key": "tidy", "skill": NAME, "title": "Tidy", "text": "Tidy the notes.",
                                                   "depends_on": [], "milestone": False}]}


def combined(imported, agents=AGENTS):
    routed = [{"item": "tidy", "reply": "", "route": {"kind": "route", "line": "Route: flow-x (flow, pending)",
                                                      "checked": {"ok": True, "flow": "tidy"}}}]
    return plan.combine(REQUEST, routed, {"tidy": FLOW}, agents, str(st.REPO), pack=["eng-docs"],
                        limits={"timeout_seconds": 1800, "retries": 2}, past=[], imported=imported)


def test_the_router_path_gives_the_task_the_chosen_agent_and_the_plan_says_why():
    out = combined(entries(agent="engineering"))
    (task,) = out["tasks"]
    assert task["agent"] == "engineering" and "chosen" in task["agent_why"]
    assert task["agent_why"] in out["plan"]["body"]
    area = combined(entries())["tasks"][0]
    assert area["agent"] == "delivery" and "covers the area ops" in area["agent_why"]


def test_the_plan_text_says_the_planning_agent_owns_it_when_no_agent_covers_the_area():
    task = dict(TASK, title="Tidy", key="t", skill="mkt-tidy-notes")
    plan.assign(task, AGENTS, imported={})
    assert task["agent"] == "planning" and task["agent_why"] == "no agent covers the area mkt: the planning agent owns it"
    body = plan.build({"id": 1, "title": "T", "text": "T"}, [dict(task, depends_on=[], milestone=False, web=False)], None, "named",
                      {"max_running": 1, "timeout_seconds": 1, "retries": 1}, [], flow="tidy")["body"]
    assert "no agent covers the area mkt: the planning agent owns it" in body

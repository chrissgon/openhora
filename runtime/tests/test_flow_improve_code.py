"""Tests of the improve-code flow file (flows/improve-code.json): existing code made cheaper to keep, from its impact to its
pull request, in five tasks. The item NS5 says "codebase map or impact analysis"; a flow file cannot choose a skill at plan time,
so this file takes the impact analysis, because the refactor's own required input is a named target (the request already names
the code) and the map is a pass over a whole codebase for an area nobody knows yet. No model call.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_improve_code.py
"""
from __future__ import annotations

import flow_kit as kit
import standin_tree as st

flow_files = st.load("flow_files")
NAME = "improve-code"
SPEC = [
    ("impact", "eng-impact-analysis", [], False),
    ("options", "eng-tradeoffs", ["impact"], True),
    ("refactor", "eng-refactor", ["options"], True),
    ("review", "eng-code-review", ["refactor"], False),
    ("pull-request", "ops-pull-request", ["review"], True),
]
WRITES = {"impact": "docs/engineering/plans/<task>.md", "options": "docs/engineering/adr/",
          "refactor": "docs/engineering/plans/<task>.md", "review": "docs/engineering/reviews/<change>.md"}


def test_the_flow_file_lists_the_five_phases_in_order():
    kit.loads_in_order(NAME, "Improve existing code, to its pull request", SPEC)


def test_choosing_the_flow_builds_the_plan_of_its_specification():
    kit.plan_equals_spec(NAME, SPEC)


def test_a_scope_that_lacks_a_skill_of_the_flow_refuses_the_plan():
    kit.scope_is_checked(NAME)


def test_every_task_has_one_owning_agent():
    kit.one_owner_each(NAME, {s: "code" for s in (
        "eng-impact-analysis", "eng-tradeoffs", "eng-refactor", "eng-code-review", "ops-pull-request")})


def test_the_router_accepts_the_flow_as_a_route():
    kit.router_accepts(NAME)


def test_the_flow_passes_the_dependency_rule_and_the_validators_flow_checks():
    kit.passes_validator(NAME)


def test_each_task_names_the_file_it_writes_and_every_required_input_an_earlier_task_writes():
    kit.names_what_it_writes(NAME, WRITES)


def test_the_flow_names_no_project_no_person_no_skill_and_no_tool():
    kit.names_nothing(NAME)


def test_the_codebase_map_is_not_a_task_and_the_choice_is_the_persons():
    flow = flow_files.load(NAME, kit.ROOT)
    assert "eng-codebase-map" not in [t["skill"] for t in flow["tasks"]]
    text = {t["key"]: t["text"] for t in flow["tasks"]}
    assert "choose no approach here" in text["impact"]
    assert "changed only by the person" in text["options"] and "only one option meets the rules" in text["options"]
    assert "without changing its behaviour" in text["refactor"] and "do not make it" in text["refactor"]
    assert "Fix nothing in this task" in text["review"] and "stop at the confirmation gate" in text["pull-request"]
    assert [t["key"] for t in flow["tasks"] if t["milestone"]] == ["options", "refactor", "pull-request"]

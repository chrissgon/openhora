"""Tests of the fix-bug flow file (flows/fix-bug.json): the nine-phase bug fix of the flow-fix-bug skill as a file, with its five
phases that always run. The four phases the skill marks optional (impact, options, integration tests, documentation) each depend on
what the plan shows, which a static file cannot read, so they are not tasks: the implementation task stops before changing code when
the plan's reach or its options call for an impact analysis or a comparison, and those are skills a person asks for on their own.
No model call.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_fix_bug.py
"""
from __future__ import annotations

import flow_kit as kit
import standin_tree as st

flow_files = st.load("flow_files")
NAME = "fix-bug"
SPEC = [
    ("root-cause", "eng-root-cause", [], True),
    ("tests", "eng-unit-tests", ["root-cause"], False),
    ("implement", "eng-implement", ["tests"], False),
    ("review", "eng-code-review", ["implement"], False),
    ("pull-request", "ops-pull-request", ["review"], True),
]
WRITES = {"root-cause": "docs/engineering/plans/<task>.md", "tests": "docs/engineering/plans/<task>.md",
          "review": "docs/engineering/reviews/<change>.md"}


def test_the_flow_file_lists_the_five_phases_in_order():
    kit.loads_in_order(NAME, "Fix a bug, to its pull request", SPEC)


def test_choosing_the_flow_builds_the_plan_of_its_specification():
    kit.plan_equals_spec(NAME, SPEC)


def test_a_scope_that_lacks_a_skill_of_the_flow_refuses_the_plan():
    kit.scope_is_checked(NAME)


def test_every_task_has_one_owning_agent():
    kit.one_owner_each(NAME, {s: "code" for s in (
        "eng-root-cause", "eng-unit-tests", "eng-implement", "eng-code-review", "ops-pull-request")})


def test_the_router_accepts_the_flow_as_a_route():
    kit.router_accepts(NAME)


def test_the_flow_passes_the_dependency_rule_and_the_validators_flow_checks():
    kit.passes_validator(NAME)


def test_each_task_names_the_file_it_writes_and_every_required_input_an_earlier_task_writes():
    checked = kit.names_what_it_writes(NAME, WRITES)
    assert ("implement", "docs/engineering/plans/<task>.md") in checked


def test_the_flow_names_no_project_no_person_no_skill_and_no_tool():
    kit.names_nothing(NAME)


def test_the_stop_rules_of_the_skill_that_a_static_file_can_carry_are_in_the_texts():
    flow = flow_files.load(NAME, kit.ROOT)
    text = {t["key"]: t["text"] for t in flow["tasks"]}
    assert "write nothing and ask" in text["root-cause"] and "Change no source" in text["root-cause"]   # stop rules 1 and 4
    assert "source under test stays untouched" in text["tests"]
    assert "write nothing there before the person says yes" in text["tests"]                             # stop rule 5
    assert "change no test" in text["implement"] and "comes first" in text["implement"]
    assert "Push nothing yourself" in text["pull-request"] and "stop at the confirmation gate" in text["pull-request"]   # stop rule 6
    assert [t["key"] for t in flow["tasks"] if t["milestone"]] == ["root-cause", "pull-request"]


def test_the_optional_phases_of_the_skill_are_not_tasks_and_the_skills_are_not_edited():
    skills = {t["skill"] for t in flow_files.load(NAME, kit.ROOT)["tasks"]}
    assert skills.isdisjoint({"eng-impact-analysis", "eng-tradeoffs", "eng-integration-tests", "eng-docs"})

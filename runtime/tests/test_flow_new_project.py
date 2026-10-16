"""Tests of the new-project flow file (flows/new-project.json): an idea clarified, its first feature specified and designed,
the backlog, the first task implemented and its pull request. Three choices differ from the item NS6 (see the last test): the
feature specification stands in for "PRD or feature specification" because the design and the backlog read the specification
and the PRD writes none; the design comes before the backlog because the backlog stops without it when the specification has
more than three requirements; "implement per task" is one implementation task, the first of the backlog, because the schema has
no per-task expansion. No model call.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_new_project.py
"""
from __future__ import annotations

import flow_kit as kit
import standin_tree as st

flow_files = st.load("flow_files")
skill_meta = st.load("skill_meta")
NAME = "new-project"
SPEC = [
    ("brief", "core-clarify", [], True),
    ("spec", "product-feature-spec", ["brief"], True),
    ("design", "eng-architecture", ["spec"], False),
    ("backlog", "product-backlog", ["design"], True),
    ("implement", "eng-implement", ["backlog"], True),
    ("pull-request", "ops-pull-request", ["implement"], True),
]
WRITES = {"brief": "docs/workbench/briefs/<topic>.md", "spec": "docs/product/specs/<feature>.md",
          "design": "docs/engineering/designs/<feature>.md", "backlog": "docs/product/backlog.md"}


def test_the_flow_file_lists_the_six_phases_in_order():
    kit.loads_in_order(NAME, "A new project, from the idea to its first task", SPEC)


def test_choosing_the_flow_builds_the_plan_of_its_specification():
    kit.plan_equals_spec(NAME, SPEC)


def test_a_scope_that_lacks_a_skill_of_the_flow_refuses_the_plan():
    kit.scope_is_checked(NAME)


def test_every_task_has_one_owning_agent():
    kit.one_owner_each(NAME, {"core-clarify": "planning", "product-feature-spec": "design", "product-backlog": "design",
                              "eng-architecture": "code", "eng-implement": "code", "ops-pull-request": "code"})


def test_the_router_accepts_the_flow_as_a_route():
    kit.router_accepts(NAME)


def test_the_flow_passes_the_dependency_rule_and_the_validators_flow_checks():
    kit.passes_validator(NAME)


def test_each_task_names_the_file_it_writes_and_every_required_input_an_earlier_task_writes():
    checked = kit.names_what_it_writes(NAME, WRITES)
    assert ("backlog", "docs/product/specs/<feature>.md") in checked


def test_the_flow_names_no_project_no_person_no_skill_and_no_tool():
    kit.names_nothing(NAME)


def test_the_choices_that_differ_from_the_item_are_the_artifacts_order():
    flow = flow_files.load(NAME, kit.ROOT)
    skills = [t["skill"] for t in flow["tasks"]]
    assert "product-prd" not in skills   # nothing after the brief reads the PRD; the specification is what the design and the backlog read
    # the backlog needs the design when the specification has more than three requirements (its Stop rule 3), so the design comes first
    assert "docs/engineering/designs/<feature>.md" in skill_meta.declared(str(kit.st.REPO / "skills" / "product-backlog"))["inputs"]
    text = {t["key"]: t["text"] for t in flow["tasks"]}
    assert "Create no ticket" in text["backlog"]    # the issue tracker is a separate request with its own gate
    assert "implements one task" in text["implement"] and "The other tasks are later requests" in text["implement"]
    assert "do not make it" in text["implement"] and "stop at the confirmation gate" in text["pull-request"]

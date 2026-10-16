"""Tests of the build-feature flow file (flows/build-feature.json): a feature from its specification to its pull request, in
eight tasks, each depending on the one before because each reads what the one before wrote. Choosing the flow builds the plan at
once, with no model call. The order is the one the backlog item NS4 gives; nothing in it can run in parallel, because each task
reads the file the previous one writes (the integration tests and the documentation both update the plan, and the documentation
is written for the reviewed change).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_flow_build_feature.py
"""
from __future__ import annotations

import flow_kit as kit
import standin_tree as st

flow_files = st.load("flow_files")
NAME = "build-feature"
SPEC = [
    ("spec", "product-feature-spec", [], True),
    ("design", "eng-architecture", ["spec"], True),
    ("tests", "eng-unit-tests", ["design"], False),
    ("implement", "eng-implement", ["tests"], True),
    ("integration", "eng-integration-tests", ["implement"], False),
    ("review", "eng-code-review", ["integration"], False),
    ("docs", "eng-docs", ["review"], False),
    ("pull-request", "ops-pull-request", ["docs"], True),
]
WRITES = {"spec": "docs/product/specs/<feature>.md", "design": "docs/engineering/designs/<feature>.md",
          "tests": "docs/engineering/plans/<task>.md", "review": "docs/engineering/reviews/<change>.md",
          "docs": "docs/engineering/plans/<task>.md"}


def test_the_flow_file_lists_the_eight_phases_of_the_item_in_order():
    kit.loads_in_order(NAME, "Build a feature, to its pull request", SPEC)


def test_choosing_the_flow_builds_the_plan_of_its_specification():
    kit.plan_equals_spec(NAME, SPEC)


def test_a_scope_that_lacks_a_skill_of_the_flow_refuses_the_plan():
    kit.scope_is_checked(NAME)


def test_every_task_has_one_owning_agent():
    kit.one_owner_each(NAME, {"product-feature-spec": "design", **{s: "code" for s in (
        "eng-architecture", "eng-unit-tests", "eng-implement", "eng-integration-tests", "eng-code-review", "eng-docs", "ops-pull-request")}})


def test_the_router_accepts_the_flow_as_a_route():
    kit.router_accepts(NAME)


def test_the_flow_passes_the_dependency_rule_and_the_validators_flow_checks():
    kit.passes_validator(NAME)


def test_each_task_names_the_file_it_writes_and_every_required_input_an_earlier_task_writes():
    checked = kit.names_what_it_writes(NAME, WRITES)
    assert ("design", "docs/product/specs/<feature>.md") in checked


def test_the_flow_names_no_project_no_person_no_skill_and_no_tool():
    kit.names_nothing(NAME)


def test_the_texts_keep_the_rules_that_make_the_phases_safe():
    text = {t["key"]: t["text"] for t in flow_files.load(NAME, kit.ROOT)["tasks"]}
    assert "Ready for architecture: yes" in text["spec"] and "never invent a requirement" in text["spec"]
    assert "no source under test changes" in text["tests"] and "fail today" in text["tests"]
    assert "quote the failing line" in text["implement"] and "there is no backlog task" in text["implement"]
    assert "do not make it" in text["implement"]
    assert "each test of new behaviour fails on the code before the change" in text["integration"]
    assert "Fix nothing in this task" in text["review"]
    assert "stop at the confirmation gate" in text["pull-request"]
    flow = flow_files.load(NAME, kit.ROOT)
    assert [t["key"] for t in flow["tasks"] if t["milestone"]] == ["spec", "design", "implement", "pull-request"]

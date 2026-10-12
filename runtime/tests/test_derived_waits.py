"""Tests of the derived waits (A-29) that need no store: the pure derivation of runtime/plan.py (derive, skill_facts,
required_inputs, owners_of, wait_lines) and the dispatcher's rule that a task with an open wait never starts. Offline;
the skills of the fixtures are invented, the repository's own are read only for the table of inputs.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_derived_waits.py
"""
from __future__ import annotations

import itertools

import pytest

import standin_tree as st

plan = st.load("plan")
autonomy = st.load("autonomy")
dispatcher = st.load("dispatcher")
REPO = str(st.REPO)

# Three requests whose skills chain: brand -> design -> marketing. The brand request writes the identity and the voice,
# the design request reads the identity and writes the system, the marketing request reads the system and the voice.
FACTS = {
    "brand-identity": {"inputs": ["docs/brand/strategy.md"], "outputs": ["docs/brand/identity.md"], "required": set()},
    "brand-voice": {"inputs": ["docs/brand/profile.md"], "outputs": ["docs/brand/voice.md"],
                    "required": {"docs/brand/profile.md"}},
    "design-system": {"inputs": ["docs/brand/identity.md", "docs/workbench/state.md"],
                      "outputs": ["docs/design/system.md"], "required": {"docs/brand/identity.md"}},
    "mkt-social-copy": {"inputs": ["docs/design/system.md", "docs/brand/voice.md"], "outputs": ["docs/marketing/posts.md"],
                        "required": {"docs/brand/voice.md"}},
    "eng-plan": {"inputs": ["docs/engineering/plans/<task>.md"], "outputs": ["docs/engineering/plans/<task>.md"],
                 "required": set()},
}
REQUESTS = {
    "brand": [("brand-identity", ()), ("brand-voice", ())],
    "design": [("design-system", ())],
    "marketing": [("mkt-social-copy", ())],
}
NOTHING = lambda path: False  # noqa: E731  (the project has none of the files)


def world(order, requests=REQUESTS):
    """nodes of the requests created in this order: request ids 1.., task ids after them (a request's tasks in a row)."""
    nodes, next_id = [], len(order) + 1
    for number, name in enumerate(order, 1):
        for skill, deps in requests[name]:
            nodes.append({"ref": next_id, "request": number, "skill": skill, "candidate": True, "depends_on": list(deps),
                          "name": name})
            next_id += 1
    return nodes


def pairs(nodes, got):
    """The waits as (waiting skill, awaited skill, path), whatever the ids the requests were given."""
    skill = {n["ref"]: n["skill"] for n in nodes}
    return sorted((skill[w["ref"]], skill[w["awaited"]], w["path"]) for w in got["waits"])


CHAIN = [("design-system", "brand-identity", "docs/brand/identity.md"),
         ("mkt-social-copy", "brand-voice", "docs/brand/voice.md"),
         ("mkt-social-copy", "design-system", "docs/design/system.md")]


@pytest.mark.parametrize("order", list(itertools.permutations(REQUESTS)))
def test_three_requests_whose_skills_chain_order_themselves_in_any_insertion_order(order):
    nodes = world(order)
    got = plan.derive(nodes, FACTS, NOTHING, open_requests={1, 2, 3})
    assert pairs(nodes, got) == sorted(CHAIN)
    assert got["cycles"] == []
    # The first skill of the chain has nothing to wait for, whichever request came first: brand-voice needs a profile
    # nothing writes, and says so; the identity skill needs nothing.
    assert [(m["skill"], m["path"]) for m in got["missing"]] == [("brand-voice", "docs/brand/profile.md")]


def test_an_input_the_project_already_has_creates_no_wait():
    nodes = world(("brand", "design", "marketing"))
    have = {"docs/brand/identity.md"}
    got = plan.derive(nodes, FACTS, lambda p: p in have, open_requests={1, 2, 3})
    assert ("design-system", "brand-identity", "docs/brand/identity.md") not in pairs(nodes, got)
    assert len(got["waits"]) == 2


def test_an_input_a_task_of_the_same_request_writes_is_that_flows_business():
    nodes = world(("brand",), {"brand": [("brand-identity", ()), ("design-system", ())]})
    got = plan.derive(nodes, FACTS, NOTHING, open_requests={1})
    assert got["waits"] == [] and got["missing"] == []  # identity.md is written inside the request, not missing either


def test_a_required_input_nothing_writes_is_said_before_approval_with_the_owner_to_run_first():
    nodes = [{"ref": ("new", "voice"), "request": "new", "skill": "brand-voice", "candidate": True, "depends_on": []}]
    got = plan.derive(nodes, FACTS, NOTHING, open_requests=set())
    assert got["waits"] == [] and got["cycles"] == []
    assert [m["owner"] for m in got["missing"]] == [None]  # in these facts nobody owns the profile
    facts = dict(FACTS, **{"brand-profile": {"inputs": [], "outputs": ["docs/brand/profile.md"], "required": set()}})
    [missing] = plan.derive(nodes, facts, NOTHING)["missing"]
    assert missing["owner"] == "brand-profile" and missing["sentence"] == (
        "brand-voice needs docs/brand/profile.md; nothing writes it: run brand-profile first or go ahead and it will stop")


def test_a_required_input_no_skill_owns_says_so_without_naming_a_skill_to_run():
    facts = {"s": {"inputs": ["docs/x.md"], "outputs": [], "required": {"docs/x.md"}}}
    nodes = [{"ref": 1, "request": 1, "skill": "s", "candidate": True, "depends_on": []}]
    [missing] = plan.derive(nodes, facts, NOTHING, open_requests={1})["missing"]
    assert missing["owner"] is None and missing["sentence"] == (
        "s needs docs/x.md; nothing writes it: add the file or go ahead and it will stop")


def test_an_input_that_is_not_required_and_nothing_writes_makes_neither_a_wait_nor_a_message():
    nodes = world(("design", "marketing"))
    got = plan.derive(nodes, FACTS, lambda p: p == "docs/design/system.md" or p == "docs/brand/voice.md",
                      open_requests={1, 2})
    assert got == {"waits": [], "missing": [{"ref": nodes[0]["ref"], "skill": "design-system", "path": "docs/brand/identity.md",
                                             "owner": "brand-identity", "sentence": got["missing"][0]["sentence"]}],
                   "cycles": []}  # only the required identity is missing; the state file the project has is not asked


def test_two_requests_that_read_each_others_outputs_wait_in_one_direction_only_and_the_other_is_reported():
    facts = {"a": {"inputs": ["b.md"], "outputs": ["a.md"], "required": set()},
             "b": {"inputs": ["a.md"], "outputs": ["b.md"], "required": set()}}
    nodes = [{"ref": 3, "request": 1, "skill": "a", "candidate": True, "depends_on": []},
             {"ref": 4, "request": 2, "skill": "b", "candidate": True, "depends_on": []}]
    got = plan.derive(nodes, facts, NOTHING, open_requests={1, 2})
    assert [(w["ref"], w["awaited"]) for w in got["waits"]] == [(3, 4)]  # the older task waits; the other would close the circle
    assert [(c["ref"], c["awaited"], c["path"]) for c in got["cycles"]] == [(4, 3, "a.md")]
    assert "no wait was made" in got["cycles"][0]["sentence"]


def test_a_circle_through_a_dependency_of_the_flow_is_found_too():
    facts = {"a": {"inputs": ["c.md"], "outputs": ["a.md"], "required": set()},
             "b": {"inputs": ["a.md"], "outputs": ["b.md"], "required": set()},
             "c": {"inputs": [], "outputs": ["c.md"], "required": set()}}
    nodes = [{"ref": 3, "request": 1, "skill": "a", "candidate": True, "depends_on": []},
             {"ref": 4, "request": 2, "skill": "b", "candidate": True, "depends_on": []},
             {"ref": 5, "request": 2, "skill": "c", "candidate": True, "depends_on": [4]}]  # c runs after b
    got = plan.derive(nodes, facts, NOTHING, open_requests={1, 2})
    assert [(w["ref"], w["awaited"]) for w in got["waits"]] == [(3, 5)]
    assert [(c["ref"], c["awaited"]) for c in got["cycles"]] == [(4, 3)]  # a waits for c, c waits for b: b cannot wait for a


def test_a_task_waits_for_the_oldest_open_task_that_writes_the_input_and_for_the_next_when_it_is_gone():
    facts = {"w": {"inputs": [], "outputs": ["w.md"], "required": set()},
             "r": {"inputs": ["w.md"], "outputs": [], "required": set()}}
    both = [{"ref": 3, "request": 1, "skill": "w", "candidate": True, "depends_on": []},
            {"ref": 4, "request": 2, "skill": "w", "candidate": True, "depends_on": []},
            {"ref": 5, "request": 3, "skill": "r", "candidate": True, "depends_on": []}]
    assert [(w["ref"], w["awaited"], w["reason"]) for w in plan.derive(both, facts, NOTHING)["waits"]] == [
        (5, 3, "w.md, written by task #3")]
    assert [(w["ref"], w["awaited"]) for w in plan.derive(both[1:], facts, NOTHING)["waits"]] == [(5, 4)]
    assert plan.derive(both[2:], facts, NOTHING)["waits"] == []  # no writer left, not required: nothing to wait for


def test_the_person_s_after_holds_a_request_behind_another_and_ends_with_it():
    nodes = world(("brand", "design"))
    got = plan.derive(nodes, FACTS, lambda p: True, after_of={2: 1}, open_requests={1, 2})
    [wait] = got["waits"]
    assert (wait["kind"], wait["awaited"], wait["reason"], wait["path"]) == ("after", 1, "after request #1", None)
    assert plan.derive(nodes, FACTS, lambda p: True, after_of={2: 1}, open_requests={2})["waits"] == []  # request 1 is done


def test_after_is_a_wait_the_contract_cannot_see_and_a_circle_of_afters_is_reported():
    nodes = world(("brand", "design"))
    got = plan.derive(nodes, FACTS, lambda p: True, after_of={1: 2, 2: 1}, open_requests={1, 2})
    design = next(n["ref"] for n in nodes if n["skill"] == "design-system")
    # The older request's two tasks wait for request 2; the later request would wait for request 1: left out, said.
    assert [w["ref"] for w in got["waits"]] == [n["ref"] for n in nodes if n["request"] == 1]
    assert [(c["ref"], c["kind"], c["awaited"]) for c in got["cycles"]] == [(design, "after", 1)]


def test_a_skill_that_reads_its_own_output_waits_for_no_one_and_reports_no_circle():
    # eng-plan reads the plan it keeps: two requests of it are not one waiting for the other, and the older does not wait
    # for the younger, which would then be a circle of one skill with itself.
    nodes = [{"ref": 3, "request": 1, "skill": "eng-plan", "candidate": True, "depends_on": []},
             {"ref": 4, "request": 2, "skill": "eng-plan", "candidate": True, "depends_on": []}]
    got = plan.derive(nodes, FACTS, NOTHING, open_requests={1, 2})
    assert got == {"waits": [], "missing": [], "cycles": []}
    required = dict(FACTS, **{"eng-plan": dict(FACTS["eng-plan"], required={"docs/engineering/plans/<task>.md"})})
    assert plan.derive(nodes, required, NOTHING, open_requests={1, 2})["missing"] == []  # it starts what it needs
    # Another skill that needs that plan still waits for the oldest task that writes it.
    reader = dict(FACTS, **{"eng-implement": {"inputs": ["docs/engineering/plans/<task>.md"], "outputs": [], "required": set()}})
    nodes.append({"ref": 5, "request": 3, "skill": "eng-implement", "candidate": True, "depends_on": []})
    assert [(w["ref"], w["awaited"]) for w in plan.derive(nodes, reader, NOTHING, open_requests={1, 2, 3})["waits"]] == [(5, 3)]


def test_only_limits_the_derivation_to_the_tasks_named_and_fixed_edges_count_for_the_circle_check():
    nodes = world(("brand", "design", "marketing"))
    design = next(n["ref"] for n in nodes if n["skill"] == "design-system")
    got = plan.derive(nodes, FACTS, NOTHING, only={design}, open_requests={1, 2, 3})
    assert [w["ref"] for w in got["waits"]] == [design]
    identity = next(n["ref"] for n in nodes if n["skill"] == "brand-identity")
    # The store already holds a wait of the identity task on the design task: waiting the other way would close a circle.
    held = plan.derive(nodes, FACTS, NOTHING, only={design}, open_requests={1, 2, 3}, fixed={identity: {design}})
    assert held["waits"] == [] and [c["ref"] for c in held["cycles"]] == [design]


def test_a_path_with_a_placeholder_is_the_same_artifact_as_the_output_that_names_the_same_place():
    assert plan.normal("docs/engineering/plans/<task>.md") == plan.normal("docs/engineering/plans/<feature>.md")
    assert plan.owners_of(FACTS, "docs/engineering/plans/<feature>.md") == ["eng-plan"]
    assert plan.owners_of({"p": {"outputs": ["docs/brand/pieces/"]}, "q": {"outputs": ["docs/other.md"]}},
                          "docs/brand/pieces/") == ["p"]
    assert plan.owners_of(FACTS, "docs/nothing.md") == []


def test_the_lines_a_plan_adds_say_the_waits_the_missing_inputs_and_the_circles_with_the_tasks_titles():
    got = plan.wait_lines([{"ref": "d", "reason": "docs/brand/identity.md, written by task #10"}],
                          [{"ref": "v", "sentence": "brand-voice needs docs/brand/profile.md; nothing writes it: run "
                                                    "brand-profile first or go ahead and it will stop"}],
                          [{"ref": "d", "sentence": "x would wait for task #1 (y), which waits for it: no wait was made"}],
                          {"d": "Design system", "v": "Voice"})
    assert "- Design system waits: docs/brand/identity.md, written by task #10" in got
    assert any(line.startswith("- Voice: brand-voice needs docs/brand/profile.md") for line in got)
    assert any("circle" in line for line in got) and plan.wait_lines([], [], [], {}) == []


# --- what a skill requires: the inputs table of its SKILL.md, read as scripts/validate.py reads it ------------------


def test_required_is_the_exact_yes_of_the_inputs_table_and_a_conditional_yes_is_not():
    facts = plan.skill_facts(REPO)
    assert facts["brand-voice"]["required"] == {"docs/brand/profile.md"}
    # brand-strategy: "yes for a person" and "yes for a company" are conditions, not requirements.
    assert "docs/brand/profile.md" in facts["brand-strategy"]["inputs"]
    assert facts["brand-strategy"]["required"] == set()
    assert "docs/brand/strategy.md" in facts["brand-identity"]["required"]
    assert "docs/brand/voice.md" not in facts["brand-identity"]["required"]  # a "no" row


def test_the_repository_s_own_chain_brand_identity_is_the_owner_of_what_design_system_reads():
    facts = plan.skill_facts(REPO)
    assert plan.owners_of(facts, "docs/brand/identity.md") == ["brand-identity"]
    assert "docs/brand/identity.md" in facts["design-system"]["inputs"]
    assert plan.owners_of(facts, "docs/brand/profile.md") == ["brand-profile"]


def tree_of(tmp_path, body: str, inputs="a.md, b.md, c.md, d.md"):
    folder = tmp_path / "skills" / "x"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("---\nname: x\ndescription: invented\nlicense: MIT\nmetadata:\n  area: business\n"
                                    f"  kind: capability\n  inputs: [{inputs}]\n  outputs: []\n  updates: []\n  requires: []\n"
                                    "  side_effects: []\n  version: \"0.1.0\"\n---\n# x\n" + body, encoding="utf-8")
    return str(tmp_path)


def test_required_is_what_the_validator_reads_exactly_yes_and_nothing_decorated(tmp_path):
    table = ("\n## Inputs\n\n| Artifact | Required | If missing |\n|---|---|---|\n| `a.md`, with samples | **yes** | Stop. |\n"
             "| b.md | Yes. | Stop. |\n| c.md | no | - |\n| d.md | Yes | Stop. |\n\n## Stop rules\n\n| e.md | yes | no |\n")
    # flow_files.required_inputs is the one reader (scripts/validate.py's [flow-dependencies]): `**yes**` and `Yes.` are
    # not the word yes, `Yes` is (the cell is lowercased), and a table outside `## Inputs` is not read.
    assert plan.skill_facts(tree_of(tmp_path, table, "a.md, b.md, c.md, d.md, e.md"))["x"]["required"] == {"d.md"}
    assert plan.skill_facts(tree_of(tmp_path / "none", "\n## Purpose\n\nText.\n"))["x"]["required"] == set()


def test_the_required_column_of_every_skill_is_what_flow_files_reads_which_is_what_the_validator_reads():
    flow_files = st.load("flow_files")
    facts = plan.skill_facts(REPO)
    assert len(facts) >= 40
    for name, f in facts.items():
        text = (st.REPO / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert f["required"] == set(flow_files.required_inputs(text, f["inputs"])), name
        assert f["required"] <= set(f["inputs"]), name


# --- the dispatcher: a task with an open wait is a dependency that has not ended ----------------------------------------


def agent():
    entry = {"pack": "p", "enabled": True, "mode": "autonomous", "max_runs_per_day": 5, "max_usd_per_day": 1.0}
    return {"entry": entry, "facts": autonomy.facts("x", {"x": entry}, [], "2026-10-06T00:00:00Z"),
            "spent": {"runs_counted": 0, "usd_metered": 0.0, "runs_without_cost": 0}}


def ready(task_id):
    return {"id": task_id, "agent": "a", "state": "ready", "milestone": 0, "parent_id": 1}


def test_the_dispatcher_never_starts_a_task_with_an_open_wait_and_starts_the_next_one():
    snapshot = {"running": None, "ready": [ready(4), ready(5)], "reviews": [], "agents": {"a": agent()},
                "tier": {4: "strong", 5: "strong"}, "billing": {4: "subscription", 5: "subscription"},
                "waits": {4: [{"task_id": 2, "request_id": 1, "reason": "docs/brand/identity.md, written by task #2"}]}}
    decided = dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start)
    assert decided["start"] == 5 and decided["held"] == [{"task_id": 4, "why": dispatcher.WAITING}]
    only = dict(snapshot, ready=[ready(4)])
    assert dispatcher.decide(only, autonomy.review_action, autonomy.may_start)["start"] is None
    assert dispatcher.held_of(only, dispatcher.decide(only, autonomy.review_action, autonomy.may_start)) == [
        {"task_id": 4, "agent": "a", "reason": "waiting"}]
    assert dispatcher.WAITING in dispatcher.REASONS


def test_a_snapshot_without_waits_decides_as_it_did():
    snapshot = {"running": None, "ready": [ready(4)], "reviews": [], "agents": {"a": agent()}, "tier": {4: "strong"},
                "billing": {4: "subscription"}}
    assert dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start)["start"] == 4
    assert dispatcher.decide(dict(snapshot, waits={4: []}), autonomy.review_action, autonomy.may_start)["start"] == 4

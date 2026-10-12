"""Tests of several deliveries in one request, the brief, and sub-tasks inside the plan's limits (stage 6, WP-6.5):
runtime/plan.py (split, combine, backlog_tasks, subtasks) and what runtime/ops.py does with them (route, release).
Offline: the stand-in tree of standin_tree.py, with a stand-in router, brief and backlog skill; invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_deliveries.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
plan = st.load("plan")
router = st.load("router")

FIXTURE_BACKLOG = Path(__file__).resolve().parent / "fixtures" / "backlog.md"
TASK_SCRIPT = st.REPO / "skills" / "eng-implement" / "scripts" / "task.py"
PACKS = {"planning": ["core-clarify", "core-orchestrator"], "biz": ["demo-asks", "demo-writes"],
         "product": ["product-backlog"], "code": ["eng-implement"], "other": ["demo-code"]}
AGENTS = {"planning": {"pack": "planning"}, "business": {"pack": "biz"}, "product": {"pack": "product"},
          "code": {"pack": "code"}}

# The stand-in router answers with reply-<word>.md when <word> is in its prompt (else router-reply.md), and with
# reroute-reply.md when the prompt says where the brief is. The brief skill writes a brief and names another path in
# its reply; the backlog skill writes the fixture backlog.
BRANCHES = r'''
if [ "$skill" = core-orchestrator ]; then
  reply="$here/router-reply.md"
  for f in "$here"/reply-*.md; do [ -f "$f" ] || continue; k=$(basename "$f" .md); k=${k#reply-}; grep -q "$k" "$prompt" && reply="$f"; done
  if grep -q "The brief is at" "$prompt" && [ -f "$here/reroute-reply.md" ]; then reply="$here/reroute-reply.md"; fi
  cp "$reply" "$out/response.md"
  exit 0
fi
if [ "$skill" = core-clarify ]; then
  mkdir -p "$cwd/docs/workbench/briefs"
  printf '# Brief: topic\n\n- Owner: core-clarify\n- Status: draft\n' > "$cwd/docs/workbench/briefs/topic.md"
  printf '## Clarified: topic\n- Brief: docs/workbench/briefs/elsewhere.md (2 decisions, 0 open questions)\n' > "$out/response.md"
  exit 0
fi
if [ "$skill" = product-backlog ]; then
  mkdir -p "$cwd/docs/product"
  cp "$here/backlog.md" "$cwd/docs/product/backlog.md"
  printf -- '- Backlog: docs/product/backlog.md (Status: draft)\n' > "$out/response.md"
  exit 0
fi
'''
FLOW = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n"
WRITES = "Route: demo-writes (capability, ready)\nWhy: a profile\nNext: the profile.\n"
CLARIFY = "Route: core-clarify (capability, ready)\nWhy: the request is loose\nNext: the brief.\n"
BACKLOG = "Route: product-backlog (capability, ready)\nWhy: a backlog\nNext: the backlog.\n"
OUTSIDE = "Route: demo-code (capability, ready)\nWhy: a change\nNext: the change.\n"
PROSE = "This could be several things; I would need to know more about the audience first.\n"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    bench = built["tree"]
    st.skill(bench, router.ROUTER_SKILL, "docs/workbench/state.md", "")
    st.skill(bench, "core-clarify", "docs/workbench/state.md", "docs/workbench/briefs/<topic>.md")
    st.skill(bench, "product-backlog", "docs/workbench/state.md", "docs/product/backlog.md")
    st.skill(bench, "eng-implement", "docs/workbench/state.md", "")
    shutil.copyfile(TASK_SCRIPT, bench / "skills" / "eng-implement" / "scripts" / "task.py")
    shutil.copyfile(FIXTURE_BACKLOG, built["adapter"] / "backlog.md")
    script = built["adapter"] / "run-prompt.sh"
    text = st.ADAPTER.replace("for name in demo-asks demo-writes;",
                              "for name in demo-asks demo-writes core-orchestrator core-clarify product-backlog;")
    script.write_text(text.replace('case "$skill" in', BRANCHES + 'case "$skill" in', 1), encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(bench))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    configure(built, AGENTS)
    return built


def configure(tree, agents) -> None:
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = agents
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(tree["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


def reply(tree, text: str, name: str = "router-reply.md") -> None:
    (tree["adapter"] / name).write_text(text, encoding="utf-8")


def routed(tree, text: str) -> dict:
    path = str(tree["project"])
    return ops.route(path, ops.request(path, text, title="Invented request")["request"])


def prompt_of(tree, run_id: int) -> str:
    return (tree["data"] / "task-runs" / str(run_id) / "prompt.md").read_text(encoding="utf-8")


def approve(tree, pending_id: int) -> dict:
    path = str(tree["project"])
    return ops.approve(path, pending_id, ops.pending(path, pending_id)["payload"]["plan_sha256"])


def run_and_release(tree) -> dict:
    path = str(tree["project"])
    ran = ops.run_next(path)
    assert ran["status"] == "ok" and ran["pending_id"], ran
    return ops.release(path, ran["pending_id"])


TWO = "We are an invented studio.\n- alpha: which market to go after\n- beta: who buys first\n"


# --- the split ------------------------------------------------------------------------------------------------------


def test_a_request_without_a_list_is_one_delivery(tree):
    one = "Tell me which market to go after.\n- only one listed line\nWe sell to clinics."
    assert plan.split(one) == {"preamble": "", "items": [one]}
    assert plan.split("plain") == {"preamble": "", "items": ["plain"]}
    reply(tree, FLOW)
    out = routed(tree, one)
    assert st.calls(tree["adapter"]) == ["core-orchestrator 1"]
    payload = ops.pending(str(tree["project"]), out["pending_id"])["payload"]
    assert [t["key"] for t in payload["tasks"]] == ["market", "profile"]  # stage 3's keys: no delivery prefix
    assert [t["agent"] for t in payload["tasks"]] == ["business", "business"]
    assert payload["deliveries"] == [{"item": one, "route": "Route: flow-demo (flow, pending)",
                                      "tasks": ["market", "profile"], "reroute_after": None}]
    assert payload["unrouted"] == [] and payload["flow"] == "demo"
    assert payload["estimate"]["runs"] == 4 and "2 runs per task" in payload["estimate"]["formula"]


def test_each_listed_line_is_one_delivery_and_the_rest_is_its_context(tree):
    assert plan.split(TWO) == {"preamble": "We are an invented studio.",
                               "items": ["alpha: which market to go after", "beta: who buys first"]}
    reply(tree, FLOW, "reply-alpha.md")
    reply(tree, WRITES, "reply-beta.md")
    out = routed(tree, TWO)
    assert out["kind"] == "plan" and out["deliveries"] == 2 and len(out["runs"]) == 2
    first, second = (prompt_of(tree, run) for run in out["runs"])
    assert first.startswith("We are an invented studio.\n\nalpha: which market to go after\n") and "beta" not in first
    assert second.startswith("We are an invented studio.\n\nbeta: who buys first\n") and "alpha" not in second
    assert all(p.rstrip("\n").endswith("For this task: " + router.ROUTE_TASK_TEXT) for p in (first, second))


def test_more_deliveries_than_the_limit_are_refused_before_any_run(tree):
    many = "Context.\n" + "".join(f"- item {n}\n" for n in range(plan.MAX_DELIVERIES + 1))
    with pytest.raises(ValueError):
        plan.split(many)
    path = str(tree["project"])
    request = ops.request(path, many, title="Too many")["request"]
    with pytest.raises(ops.OpsError) as refused:
        ops.route(path, request)
    assert refused.value.code == 2 and str(plan.MAX_DELIVERIES) in str(refused.value)
    assert st.calls(tree["adapter"]) == [] and ops.pending(path)["pending"] == []


def test_deliveries_are_chained_in_the_order_listed(tree):
    reply(tree, FLOW, "reply-alpha.md")
    reply(tree, WRITES, "reply-beta.md")
    path = str(tree["project"])
    out = routed(tree, TWO)
    item = ops.pending(path, out["pending_id"])
    payload = item["payload"]
    assert [(t["key"], t["depends_on"], t["agent"]) for t in payload["tasks"]] == [
        ("d1-market", [], "business"), ("d1-profile", ["d1-market"], "business"),
        ("d2-demo-writes", ["d1-profile"], "business")]
    assert [d["tasks"] for d in payload["deliveries"]] == [["d1-market", "d1-profile"], ["d2-demo-writes"]]
    assert payload["flow"] == plan.DELIVERIES_FLOW and item["title"] == "Plan: 2 deliveries (3 tasks)"
    assert "flows/deliveries.json" not in item["body"] and "Estimate: 6 runs" in item["body"]
    approved = approve(tree, out["pending_id"])
    assert [(t["key"], t["state"]) for t in approved["tasks"]] == [
        ("d1-market", "ready"), ("d1-profile", "planned"), ("d2-demo-writes", "planned")]
    agents = [t["agent"] for t in ops_core.context(path)["store"].tasks_list(ops_core.context(path)["conn"]) if t["parent_id"]]
    assert agents == ["business", "business", "business"]


def test_an_item_the_router_did_not_route_reaches_the_person_with_the_whole_reply(tree):
    reply(tree, FLOW, "reply-alpha.md")
    reply(tree, PROSE, "reply-beta.md")
    path = str(tree["project"])
    out = routed(tree, TWO)
    item = ops.pending(path, out["pending_id"])
    assert out["unrouted"] == 1 and [t["key"] for t in item["payload"]["tasks"]] == ["d1-market", "d1-profile"]
    assert item["payload"]["unrouted"] == [{"item": "beta: who buys first", "why": "no route line", "reply": PROSE}]
    assert PROSE.rstrip("\n") in item["body"] and "Not planned 1: beta: who buys first" in item["body"]
    # Nothing routed at all: one question, with every reply whole.
    reply(tree, PROSE, "reply-alpha.md")
    none = routed(tree, TWO)
    asked = ops.pending(path, none["pending_id"])
    assert (none["kind"], asked["kind"], asked["title"]) == ("question", "question", "No delivery was routed")
    assert asked["body"] == f"The planning agent did not name a flow or a skill for request {none['request']}"
    assert asked["payload"]["raw"].count(PROSE.rstrip("\n")) == 2 and asked["payload"]["actions"] == ["choose-flow", "cancel"]


def test_a_skill_outside_every_enabled_agent_s_pack_is_never_planned(tree):
    reply(tree, FLOW, "reply-alpha.md")
    reply(tree, OUTSIDE, "reply-beta.md")
    path = str(tree["project"])
    out = routed(tree, TWO)
    payload = ops.pending(path, out["pending_id"])["payload"]
    assert "demo-code" not in [t["skill"] for t in payload["tasks"]]
    assert payload["unrouted"][0]["why"] == "the skill demo-code is not in the pack of the agents in scope"
    # A disabled agent's pack is out of scope too.
    configure(tree, {**AGENTS, "business": {"pack": "biz", "enabled": False}})
    reply(tree, WRITES, "reply-alpha.md")
    reply(tree, BACKLOG, "reply-beta.md")
    later = ops.pending(path, routed(tree, TWO)["pending_id"])["payload"]
    assert [t["skill"] for t in later["tasks"]] == ["product-backlog"] and len(later["unrouted"]) == 1
    # Combine refuses a skill two enabled agents own, by name.
    with pytest.raises(ValueError) as twice:
        plan.agent_of("demo-asks", {"business": ["demo-asks"], "other": ["demo-asks"]})
    assert "demo-asks" in str(twice.value) and "business, other" in str(twice.value)


def test_a_route_to_clarify_plans_one_brief_task_and_routes_again_after_its_release(tree):
    reply(tree, CLARIFY)
    reply(tree, FLOW, "reroute-reply.md")
    path = str(tree["project"])
    out = routed(tree, "Make the invented studio known.")
    payload = ops.pending(path, out["pending_id"])["payload"]
    assert [(t["key"], t["skill"], t["milestone"], t["agent"]) for t in payload["tasks"]] == [
        ("brief", "core-clarify", True, "planning")]
    assert payload["deliveries"][0]["reroute_after"] == "brief"
    approve(tree, out["pending_id"])
    released = run_and_release(tree)
    after = released["after"]["reroute"]
    assert after["routed"] is True and st.calls(tree["adapter"])[-1] == "core-orchestrator 2"
    accept = ops.pending(path, after["pending_id"])
    assert accept["kind"] == "acceptance" and accept["payload"]["what"] == "subtasks"
    assert [(t["key"], t["depends_on"]) for t in accept["payload"]["tasks"]] == [
        ("d1-market", ["brief"]), ("d1-profile", ["d1-market"])]
    added = ops.approve(path, after["pending_id"])
    assert [(t["key"], t["state"]) for t in added["added"]] == [("d1-market", "ready"), ("d1-profile", "planned")]


def test_the_brief_s_path_comes_from_the_returned_files_never_from_the_reply(tree):
    reply(tree, CLARIFY)
    reply(tree, FLOW, "reroute-reply.md")
    path = str(tree["project"])
    out = routed(tree, "Make the invented studio known.")
    approve(tree, out["pending_id"])
    after = run_and_release(tree)["after"]["reroute"]
    prompt = prompt_of(tree, after["run_id"])
    assert "The brief is at docs/workbench/briefs/topic.md." in prompt and "elsewhere.md" not in prompt
    assert prompt.startswith("Make the invented studio known.\n\nThe brief is at docs/workbench/briefs/topic.md.\n")


def test_a_second_route_to_clarify_is_not_followed(tree):
    reply(tree, CLARIFY)
    reply(tree, CLARIFY, "reroute-reply.md")
    path = str(tree["project"])
    out = routed(tree, "Make the invented studio known.")
    approve(tree, out["pending_id"])
    after = run_and_release(tree)["after"]["reroute"]
    assert after["routed"] is False and "routed again once" in after["why"]
    shown = ops.pending(path, after["pending_id"])
    assert shown["kind"] == "acceptance" and shown["payload"]["what"] == "deliveries"
    assert CLARIFY.rstrip("\n") in shown["body"]
    assert [c for c in st.calls(tree["adapter"]) if c.startswith("core-orchestrator")] == [
        "core-orchestrator 1", "core-orchestrator 2"]  # never a third run
    ops.approve(path, after["pending_id"])
    assert ops.run_next(path)["reason"] == "no task is ready"


# --- the backlog's sub-tasks --------------------------------------------------------------------------------------------


def test_the_backlog_reader_runs_the_script_eng_implement_ships_in_a_subprocess_and_loads_none_of_it():
    keys = [t["key"] for t in plan.backlog_tasks(str(FIXTURE_BACKLOG))]
    assert keys == ["t-ex-2", "t-ex-3", "t-ex-4"]
    first = plan.backlog_tasks(str(FIXTURE_BACKLOG))[0]
    assert first == {"key": "t-ex-2", "skill": "eng-implement", "title": "T-ex-2: Add the list of example items",
                     "text": "implement task T-ex-2 of docs/product/backlog.md.", "depends_on": [], "milestone": False}
    assert not [m for m in sys.modules if "eng_implement" in m], "the skill's script was loaded here"
    with pytest.raises(ValueError):
        plan.backlog_tasks(str(FIXTURE_BACKLOG.parent / "no-such-backlog.md"))
    with pytest.raises(ValueError):                      # a checkout whose skill has no script: the read fails, loudly
        plan.backlog_tasks(str(FIXTURE_BACKLOG), root=str(FIXTURE_BACKLOG.parent))


def test_backlog_tasks_that_are_done_are_not_proposed_and_dependencies_are_kept():
    found = {t["key"]: t["depends_on"] for t in plan.backlog_tasks(str(FIXTURE_BACKLOG))}
    assert "t-ex-1" not in found  # done
    assert found == {"t-ex-2": [], "t-ex-3": ["t-ex-2"], "t-ex-4": ["t-ex-3"]}  # a done dependency is dropped


def test_backlog_tasks_keep_the_order_of_the_file_whatever_the_order_the_ids_are_mentioned_in(tmp_path):
    backlog = tmp_path / "backlog.md"
    backlog.write_text("# Backlog\n\n- T-ex-1: First\n  Depends on: T-ex-3, T-zz-9\n  Status: todo\n\n"
                       "- T-ex-3: Third\n  Depends on: none\n\n- T-ex-2: Second\n  Depends on: T-ex-1\n", encoding="utf-8")
    found = {t["key"]: t["depends_on"] for t in plan.backlog_tasks(str(backlog))}
    assert list(found) == ["t-ex-1", "t-ex-3", "t-ex-2"]
    assert found == {"t-ex-1": ["t-ex-3"], "t-ex-3": [], "t-ex-2": ["t-ex-1"]}  # an id the file does not define is dropped


def backlog_request(tree) -> int:
    reply(tree, BACKLOG)
    out = routed(tree, "Write the invented product's backlog.")
    payload = ops.pending(str(tree["project"]), out["pending_id"])["payload"]
    assert payload["limits"]["subtask_skills"] == ["eng-implement"] and payload["limits"]["max_subtasks"] == 20
    approve(tree, out["pending_id"])
    return out["request"]


def test_sub_tasks_inside_the_plan_s_limits_are_created_without_a_new_approval(tree):
    path = str(tree["project"])
    request = backlog_request(tree)
    after = run_and_release(tree)["after"]["subtasks"]
    assert after["pending_id"] is None and len(after["created"]) == 3
    rows = [t for t in ops_core.context(path)["store"].tasks_list(ops_core.context(path)["conn"], request) if t["parent_id"]]
    assert [(t["key"], t["state"], t["agent"]) for t in rows][1:] == [
        ("t-ex-2", "ready", "code"), ("t-ex-3", "planned", "code"), ("t-ex-4", "planned", "code")]
    assert [p for p in ops.pending(path)["pending"] if p["kind"] == "acceptance"] == []


def test_sub_tasks_beyond_the_limits_wait_for_the_person_s_acceptance(tree, monkeypatch):
    path = str(tree["project"])
    monkeypatch.setattr(plan, "SUBTASKS_PER_PLAN", 1)
    reply(tree, BACKLOG)
    out = routed(tree, "Write the invented product's backlog.")
    assert ops.pending(path, out["pending_id"])["payload"]["limits"]["max_subtasks"] == 1
    approve(tree, out["pending_id"])
    after = run_and_release(tree)["after"]["subtasks"]
    assert len(after["created"]) == 1
    asked = ops.pending(path, after["pending_id"])
    assert asked["kind"] == "acceptance" and asked["payload"]["what"] == "subtasks"
    assert [t["key"] for t in asked["payload"]["tasks"]] == ["t-ex-3", "t-ex-4"]  # beyond the cap, with its dependent
    accepted = ops.approve(path, after["pending_id"])
    assert [t["key"] for t in accepted["added"]] == ["t-ex-3", "t-ex-4"]


def test_the_limits_are_read_from_the_approved_plan_and_nowhere_else(tree, monkeypatch):
    assert plan.subtasks({}, 0, [{"key": "a", "skill": "eng-implement", "depends_on": []}]) == {
        "create": [], "ask": [{"key": "a", "skill": "eng-implement", "depends_on": []}]}
    path = str(tree["project"])
    backlog_request(tree)
    monkeypatch.setattr(plan, "SUBTASKS_PER_PLAN", 0)  # after the approval: the plan's payload holds 20
    after = run_and_release(tree)["after"]["subtasks"]
    assert len(after["created"]) == 3 and after["pending_id"] is None
    assert os.path.isfile(os.path.join(path, "docs", "product", "backlog.md"))

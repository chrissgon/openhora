"""Tests of the plan (runtime/plan.py): the tasks code builds from a flow file or from a route to one skill, the
hash the person approves, the estimate, and the skills in scope. Offline; the flow file and the packs are the
repository's own.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_plan_build.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

plan = st.load("plan")
flow_files = st.load("flow_files")
ops = st.load("ops")
ops_core = st.load("ops_core")
ROOT = str(st.REPO)
BUSINESS = ["biz-icp-positioning", "biz-market-analysis"]
REQUEST = {"id": 4, "title": "Which market first", "text": "Tell me which market to go after first."}
LIMITS = {"one_task_at_a_time": True, "timeout_seconds": 1800, "retries": 2}


def market_plan() -> list:
    return plan.from_flow(flow_files.load("market-positioning", ROOT), ROOT, BUSINESS)


def test_a_plan_from_a_flow_file_keeps_keys_dependencies_and_order():
    tasks = market_plan()
    flow = flow_files.load("market-positioning", ROOT)
    assert [(t["key"], t["skill"], t["depends_on"]) for t in tasks] == [
        (t["key"], t["skill"], t["depends_on"]) for t in flow["tasks"]]
    assert [t["text"] for t in tasks] == [t["text"] for t in flow["tasks"]]
    assert [t["milestone"] for t in tasks] == [False, True] and [t["mandatory_milestone"] for t in tasks] == [False, False]
    assert all(t["web"] is True for t in tasks)  # both business skills require search:web


def test_the_skills_in_scope_are_the_packs_of_the_enabled_agents_or_the_default_pack():
    cfg = {"raw": {"area_agents": {"business": {"pack": "business", "enabled": True},
                                   "assistant": {"pack": "assistant", "enabled": False}}}}
    assert plan.pack_skills(cfg, ROOT) == BUSINESS
    default = plan.pack_skills({"raw": {}}, ROOT)
    assert set(BUSINESS) <= set(default) and "core-orchestrator" in default
    with pytest.raises(plan.PlanError):
        plan.pack_skills({"raw": {"area_agents": {"x": {"pack": "no-such-pack", "enabled": True}}}}, ROOT)


def test_a_task_whose_skill_is_outside_the_pack_refuses_the_plan():
    with pytest.raises(plan.PlanError) as refused:
        plan.from_flow(flow_files.load("market-positioning", ROOT), ROOT, ["biz-market-analysis"])
    assert "biz-icp-positioning" in str(refused.value)


def test_a_plan_of_one_skill_has_an_empty_task_text_and_its_prompt_is_the_plain_request():
    tasks = plan.from_skill("biz-market-analysis", REQUEST["title"], ROOT)
    assert tasks == [{"key": "biz-market-analysis", "skill": "biz-market-analysis", "title": REQUEST["title"], "text": "",
                      "depends_on": [], "milestone": False, "mandatory_milestone": False, "web": True}]
    assert ops.task_prompt(REQUEST["text"], tasks[0]["text"], []) == REQUEST["text"] + "\n"
    assert "For this task" not in ops.task_prompt(REQUEST["text"], "  ", [{"body": "Which?", "answer": "This."}])


def test_the_plan_hash_changes_with_any_task_and_approve_refuses_another_hash():
    tasks = market_plan()
    first = plan.build(REQUEST, tasks, None, "named", LIMITS, [], flow="market-positioning")
    assert first["payload"]["plan_sha256"] == plan.plan_hash(tasks) and first["payload"]["plan_sha256"] in first["body"]
    seen = {plan.plan_hash(tasks)}
    for change in ({"text": "another text"}, {"milestone": False}, {"depends_on": []}, {"title": "Renamed"}):
        changed = [dict(tasks[0]), {**tasks[1], **change}]
        seen.add(plan.plan_hash(changed))
    assert len(seen) == 5
    assert plan.plan_hash(list(reversed(tasks))) not in seen
    # The refusal of another hash by the operation is tested with a real plan in test_router_step.py
    # (test_a_valid_route_opens_a_plan_and_approving_it_creates_the_tasks).


def test_the_estimate_counts_past_runs_of_the_same_skill_and_invents_no_number():
    tasks = market_plan()
    none = plan.build(REQUEST, tasks, None, "named", LIMITS, [], flow="market-positioning")["payload"]["estimate"]
    assert none == {"tasks": 2, "runs_at_least": 2, "past": [
        {"skill": "biz-market-analysis", "runs": 0, "mean_duration_ms": None},
        {"skill": "biz-icp-positioning", "runs": 0, "mean_duration_ms": None}]}
    past = [{"skill": "biz-market-analysis", "duration_ms": 1000}, {"skill": "biz-market-analysis", "duration_ms": 3000},
            {"skill": "biz-market-analysis", "duration_ms": None}, {"skill": "core-critique", "duration_ms": 9}]
    built = plan.build(REQUEST, tasks, None, "named", LIMITS, past, flow="market-positioning")
    assert built["payload"]["estimate"]["past"] == [
        {"skill": "biz-market-analysis", "runs": 3, "mean_duration_ms": 2000},
        {"skill": "biz-icp-positioning", "runs": 0, "mean_duration_ms": None}]
    assert built["payload"]["limits"] == LIMITS and "usd" not in str(built).lower() and "$" not in built["body"]
    with pytest.raises(plan.PlanError):
        plan.build(REQUEST, tasks, None, "guess", LIMITS, [])


def test_the_brand_flow_plans_five_tasks_and_only_the_strategy_is_ready_at_first(tmp_path):
    brand = flow_files.load("brand", ROOT)
    scope = plan.pack_skills({"raw": {"area_agents": {"brand": {"pack": "brand", "enabled": True}}}}, ROOT)
    tasks = plan.from_flow(brand, ROOT, scope)
    assert [t["key"] for t in tasks] == ["strategy", "name", "identity", "voice", "guidelines"]
    assert [t["depends_on"] for t in tasks][1:] == [["strategy"], ["strategy"], ["strategy"],
                                                    ["strategy", "name", "identity", "voice"]]
    assert [t["milestone"] for t in tasks] == [True, True, True, False, True]
    store = ops_core.store_module()
    db = str(tmp_path / "tasks.sqlite")
    store.init_db(db)
    conn = store.open_db(db)
    try:
        added = store.request_add(conn, title=brand["title"], text="Build the brand.", flow="brand", tasks=tasks)
    finally:
        conn.close()
    assert added["state"] == "planned"
    assert [(t["key"], t["state"]) for t in added["tasks"]] == [
        ("strategy", "ready"), ("name", "planned"), ("identity", "planned"), ("voice", "planned"),
        ("guidelines", "planned")]

"""Tests of the dispatcher (stage 6, WP-6.6): the pure function runtime/dispatcher.py decide(), and the operations
dispatch, poll and handler_call of runtime/ops.py on the stand-in tree of standin_tree.py. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_dispatcher.py
"""
from __future__ import annotations

import copy
import json
import re

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
plan = st.load("plan")
autonomy = st.load("autonomy")
dispatcher = st.load("dispatcher")

AGENTS = {"business": {"pack": "biz", "mode": "autonomous", "max_runs_per_day": 10, "max_usd_per_day": 1.0}}
PACKS = {"biz": ["demo-asks", "demo-writes"], "code": ["demo-code"]}
HANDLER = '''import json, sys
VERBS = ("tick", "preview")
verb = sys.argv[1]
if verb not in VERBS:
    sys.exit(2)
print(json.dumps({"status": "not-due", "verb": verb, "args": sys.argv[2:]}))
'''


# --- the pure function --------------------------------------------------------------------------------------------


def agent(mode="autonomous", runs=0, cap=5, usd=0.0, usd_cap=1.0, enabled=True):
    entry = {"pack": "p", "enabled": enabled, "mode": mode, "max_runs_per_day": cap, "max_usd_per_day": usd_cap}
    return {"entry": entry, "facts": autonomy.facts("x", {"x": entry}, [], "2026-10-06T00:00:00Z"),
            "spent": {"runs_counted": runs, "usd_metered": usd, "runs_without_cost": 0}}


def ready(task_id, name, milestone=0):
    return {"id": task_id, "agent": name, "state": "ready", "milestone": milestone, "parent_id": 1}


def allow(task, running, holding, agents, max_running):
    """An admit that lets every task in: these tests are about the modes and the caps, not the slots."""
    return True, ""


def decide(snapshot):
    """The decision with every task admitted, and `start` as the first task started, or None: these tests read one start."""
    got = dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start, allow)
    return {**got, "start": got["start"][0] if got["start"] else None}


def test_nothing_starts_while_the_projects_limit_is_reached():
    running = [{"id": 3, "agent": "a", "request_id": 1, "code": False, "footprint": frozenset()}]
    got = dispatcher.decide({"running": running, "ready": [ready(4, "a")], "reviews": [], "agents": {"a": agent()},
                             "tier": {4: "strong"}, "billing": {4: "subscription"}, "max_running": 1},
                            autonomy.review_action, autonomy.may_start, parallel.admit)
    assert got == {"release": [], "start": [], "held": [{"task_id": 4, "why": parallel.PROJECT_FULL}]}


def test_the_oldest_ready_task_whose_agent_may_start_is_the_one_started():
    got = decide({"running": None, "ready": [ready(4, "a"), ready(5, "a")], "reviews": [],
                  "agents": {"a": agent()}, "tier": {4: "strong", 5: "strong"},
                  "billing": {4: "subscription", 5: "subscription"}})
    assert got["start"] == 4 and got["held"] == []


def test_a_task_of_a_stopped_agent_is_held_and_a_later_task_of_another_agent_starts():
    got = decide({"running": None, "ready": [ready(4, "a"), ready(5, "b")], "reviews": [],
                  "agents": {"a": agent(mode="stopped"), "b": agent()}, "tier": {4: "strong", 5: "floor"},
                  "billing": {4: "subscription", 5: "metered"}})
    assert got["start"] == 5 and got["held"] == [{"task_id": 4, "why": "stopped"}]


def test_a_task_at_its_agent_s_cap_is_held_with_the_cap_s_name():
    got = decide({"running": None, "ready": [ready(4, "a"), ready(5, "b")], "reviews": [],
                  "agents": {"a": agent(runs=5, cap=5), "b": agent(usd=1.0, usd_cap=1.0)}, "tier": {4: "strong", 5: "floor"},
                  "billing": {4: "subscription", 5: "metered"}})
    assert got["start"] is None
    assert got["held"] == [{"task_id": 4, "why": "cap: runs per day"}, {"task_id": 5, "why": "cap: usd per day"}]


def test_the_function_changes_nothing_and_imports_no_sibling():
    source = (st.RUNTIME / "dispatcher.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+(ops|lab|autonomy|plan|proof)\b", source, re.M)
    assert "sqlite" not in source and "open_db" not in source and "store_module" not in source
    snapshot = {"running": None, "ready": [ready(4, "a", milestone=1)], "agents": {"a": agent()}, "tier": {4: "strong"}, "billing": {4: "subscription"},
                "reviews": [{"pending": {"id": 9, "kind": "review", "payload": {"ending": "done", "why": "wrote"}},
                             "task": ready(2, "a"), "agent": "a", "proven": True, "mandatory": False}]}
    before = copy.deepcopy(snapshot)
    assert decide(snapshot) == {"release": [9], "start": 4, "held": []}
    assert snapshot == before


# --- the operations, on the stand-in tree -----------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    flows = built["tree"] / "flows"
    (flows / "chain.json").write_text(json.dumps({"flow": "chain", "title": "Chain", "tasks": [
        {"key": "profile", "skill": "demo-writes", "title": "Profile", "text": "write the profile."},
        {"key": "market", "skill": "demo-asks", "title": "Market", "text": "study the market.",
         "depends_on": ["profile"]}]}), encoding="utf-8")
    (flows / "single.json").write_text(json.dumps({"flow": "single", "title": "Single", "tasks": [
        {"key": "profile", "skill": "demo-writes", "title": "Profile", "text": "write the profile."}]}), encoding="utf-8")
    (flows / "pair.json").write_text(json.dumps({"flow": "pair", "title": "Pair", "tasks": [
        {"key": "first", "skill": "demo-writes", "title": "First", "text": "write it."},
        {"key": "second", "skill": "demo-asks", "title": "Second", "text": "ask."}]}), encoding="utf-8")
    business = built["project"] / "docs" / "business"
    business.mkdir(parents=True)
    (business / "market.md").write_text("# Market analysis\n\n- Owner: demo-asks\n- Status: draft\n", encoding="utf-8")
    configure(built, AGENTS)
    return built


def configure(tree, agents, handlers=None) -> None:
    path = tree["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = agents
    if handlers is not None:
        raw["handlers"] = handlers
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(tree["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


def planned(tree, flow: str) -> int:
    path = str(tree["project"])
    request = ops.request(path, "Invented request.", title="Invented")["request"]
    pending_id = ops.route(path, request, flow)["pending_id"]
    ops.approve(path, pending_id, ops.pending(path, pending_id)["payload"]["plan_sha256"])
    return request


def store_rows(tree, request=None):
    ctx = ops_core.context(str(tree["project"]))
    return ctx["store"].tasks_list(ctx["conn"], request)


def test_a_round_releases_what_the_mode_releases_then_runs_the_next_task(tree):
    path = str(tree["project"])
    planned(tree, "chain")
    out = ops.dispatch(path)
    assert [(r["status"], r["ending"]) for r in out["ran"]] == [("ok", "done"), ("ok", "question")]
    assert [r["by"] for r in out["released"]] == ["mode:autonomous"]
    assert st.calls(tree["adapter"]) == ["demo-writes 1", "demo-asks 1"]
    assert out["stopped"] == "no task is ready"
    assert [p["kind"] for p in ops.pending(path)["pending"]] == ["question"]  # a question is never released


def test_a_release_by_a_mode_is_recorded_as_the_mode_s_and_the_delivery_stays_a_draft(tree):
    path = str(tree["project"])
    state = tree["project"] / "docs" / "workbench" / "state.md"
    planned(tree, "chain")
    before = state.read_text(encoding="utf-8").lower().count("approved")
    approved = ops.progress(path)["summary"]["decisions"]["approved"]  # the person's approval of the plan
    out = ops.dispatch(path)
    item = ops.pending(path, out["released"][0]["pending_id"])
    assert (item["resolution"], item["resolved_by"]) == ("released", "mode:autonomous")
    assert state.read_text(encoding="utf-8").lower().count("approved") == before
    summary = ops.progress(path)["summary"]["decisions"]
    assert summary["released_by_mode"] == 1 and summary["released_by_you"] == 0 and summary["approved"] == approved


def test_a_set_released_by_a_mode_ends_with_one_acceptance_for_the_person(tree):
    path = str(tree["project"])
    request = planned(tree, "single")
    out = ops.dispatch(path)
    assert out["released"][0]["acceptance"] is not None
    accept = ops.pending(path, out["released"][0]["acceptance"])
    assert (accept["kind"], accept["task_id"], accept["title"]) == (
        "acceptance", request, f"Accept the deliveries of request {request}")
    assert accept["payload"]["what"] == "deliveries" and accept["payload"]["released"] == [out["released"][0]["pending_id"]]
    assert [p["kind"] for p in ops.pending(path)["pending"]] == ["acceptance"]


def test_a_task_no_agent_owns_is_held_and_can_still_be_run_by_hand(tree):
    path = str(tree["project"])
    got = decide({"running": None, "ready": [ready(4, None), ready(5, "ghost")], "reviews": [],
                  "agents": {"a": agent()}, "tier": {}, "billing": {}})
    assert got["start"] is None and [h["why"] for h in got["held"]] == [dispatcher.NO_AGENT] * 2
    ops.request(path, "Invented request.", flow="single")  # stage 1's request: its tasks name no agent
    out = ops.dispatch(path)
    assert out["ran"] == [] and out["held"][0]["why"] == dispatcher.NO_AGENT
    assert ops.run_next(path)["skill"] == "demo-writes"


def test_a_round_stops_at_its_budget_and_starts_no_new_run(tree):
    path = str(tree["project"])
    planned(tree, "chain")
    out = ops.dispatch(path, budget_seconds=0)
    assert out["ran"] == [] and "budget" in out["stopped"] and st.calls(tree["adapter"]) == []
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]] == ["ready", "planned"]


def test_a_round_stops_after_a_failure_the_next_run_would_repeat(tree):
    path = str(tree["project"])
    planned(tree, "pair")
    st.fail(tree["adapter"], "auth", 9)
    out = ops.dispatch(path)
    assert len(out["ran"]) == 1 and out["ran"][0]["status"] == "failed"
    assert out["stopped"].startswith("a run failed (auth)")
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]] == ["failed", "ready"]


def test_the_poll_calls_no_model_and_starts_no_task(tree):
    path = str(tree["project"])
    planned(tree, "chain")
    ran = ops.run_next(path)
    calls = st.calls(tree["adapter"])
    out = ops.poll(path)
    assert st.calls(tree["adapter"]) == calls and out["synced"] is None and out["expired"] == 0
    assert [r["pending_id"] for r in out["released"]] == [ran["pending_id"]]
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]] == ["done", "ready"]  # made ready, not started


def test_a_handler_is_called_only_by_a_name_and_a_verb_it_lists(tree):
    path = str(tree["project"])
    folder = tree["tree"] / "runtime" / "handlers"
    folder.mkdir(parents=True)
    (folder / "demo_handler.py").write_text(HANDLER, encoding="utf-8")
    configure(tree, AGENTS, {"demo-handler": {"agent": "business", "dispatch": True}})
    out = ops.handler_call(path, "demo-handler", "preview", {"since": "7d"})
    assert out == {"status": "not-due", "verb": "preview", "args": ["--project", path, "--since", "7d"], "exit_code": 0}
    for name, verb in (("demo-handler", "publish"), ("no-such-handler", "tick")):
        with pytest.raises(ops.OpsError) as refused:
            ops.handler_call(path, name, verb)
        assert refused.value.code == 2
    assert ops.dispatch(path)["handlers"]["demo-handler"]["status"] == "not-due"
    configure(tree, {"business": dict(AGENTS["business"], mode="stopped")},
              {"demo-handler": {"agent": "business", "dispatch": True}})
    assert ops.dispatch(path)["handlers"] == {}  # an agent that is stopped gets no tick


def test_run_next_returns_what_it_returned_before(tree):
    path = str(tree["project"])
    planned(tree, "single")
    out = ops.run_next(path)
    assert set(out) == {"ran", "skill", "run_id", "run_dir", "status", "ending", "failure", "task_state", "pending_id",
                        "returned", "kept", "left_out", "entered", "state", "routing", "use", "recovered"}
    assert ops.run_next(path) == {"ran": None, "reason": "no task is ready", "recovered": [], "pending": 1}


def test_a_round_without_the_credential_of_the_tasks_model_starts_nothing_and_says_why(tree, monkeypatch):
    path = str(tree["project"])
    planned(tree, "chain")
    monkeypatch.setattr(lab, "credential_missing", lambda model=None: ["EXAMPLE_REFERENCE_KEY"])
    out = ops.dispatch(path)
    assert out["ran"] == [] and st.calls(tree["adapter"]) == []
    assert "EXAMPLE_REFERENCE_KEY" in out["stopped"] and "secret store" in out["stopped"] and "Python" in out["stopped"]
    assert [t["state"] for t in store_rows(tree) if t["parent_id"]] == ["ready", "planned"]  # no task failed


# --- the parallel path (PAR-2): decide(..., admit) -----------------------------------------------------------------


parallel = st.load("parallel")


def pready(task_id, name, request_id=1, code=False, footprint=()):
    return {"id": task_id, "agent": name, "state": "ready", "milestone": 0, "parent_id": request_id,
            "code": code, "footprint": sorted(footprint)}


def prun(task_id, name, request_id=1, code=False, footprint=()):
    return {"id": task_id, "agent": name, "request_id": request_id, "code": code, "footprint": sorted(footprint)}


def pagent(max_parallel=1, **kw):
    got = agent(**kw)
    got["entry"] = dict(got["entry"], max_parallel=max_parallel)
    return got


def psnapshot(ready_tasks, running=(), holding=None, refused=None, agents=None, max_running=3, per_run_usd=0.5):
    names = {t["agent"] for t in list(ready_tasks) + list(running) if t["agent"]}
    return {"running": list(running), "ready": list(ready_tasks), "reviews": [], "agents": agents or {n: pagent() for n in names},
            "tier": {}, "billing": {t["id"]: "subscription" for t in ready_tasks}, "waits": {},
            "holding": [{"id": r["id"], "agent": r["agent"]} for r in running] if holding is None else holding,
            "refused": refused or {}, "max_running": max_running, "per_run_usd": per_run_usd}


def pdecide(snapshot):
    return dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start, parallel.admit)


def test_two_ready_tasks_of_two_agents_with_disjoint_footprints_both_start():
    got = pdecide(psnapshot([pready(4, "a", footprint={"docs/a.md"}), pready(5, "b", footprint={"docs/b.md"})]))
    assert got == {"release": [], "start": [4, 5], "held": []}


def test_a_second_task_of_a_full_agent_is_held():
    got = pdecide(psnapshot([pready(4, "a", footprint={"docs/a.md"}), pready(5, "a", footprint={"docs/b.md"})]))
    assert got["start"] == [4] and got["held"] == [{"task_id": 5, "why": parallel.AGENT_FULL}]
    wide = psnapshot([pready(4, "a", footprint={"docs/a.md"}), pready(5, "a", footprint={"docs/b.md"})], agents={"a": pagent(2)})
    assert pdecide(wide)["start"] == [4, 5]


def test_a_waiting_task_holds_its_agents_slot():
    snap = psnapshot([pready(5, "a", footprint={"docs/b.md"})], holding=[{"id": 3, "agent": "a"}])
    assert pdecide(snap) == {"release": [], "start": [], "held": [{"task_id": 5, "why": parallel.AGENT_FULL}]}


def test_a_task_whose_footprint_overlaps_a_running_one_is_held():
    snap = psnapshot([pready(5, "b", request_id=2, footprint={"docs/plans/<task>.md"})],
                     running=[prun(3, "a", footprint={"docs/plans/<task>.md"})])
    assert pdecide(snap)["held"] == [{"task_id": 5, "why": parallel.IN_USE}]


def test_two_code_tasks_of_one_request_never_start_together():
    snap = psnapshot([pready(4, "a", code=True, footprint={"x/a"}), pready(5, "b", code=True, footprint={"x/b"})])
    got = pdecide(snap)
    assert got["start"] == [4] and got["held"] == [{"task_id": 5, "why": parallel.CODE_IN_REQUEST}]


def test_the_project_ceiling_holds_the_rest():
    snap = psnapshot([pready(4, "a", footprint={"d/a"}), pready(5, "b", footprint={"d/b"}), pready(6, "c", footprint={"d/c"})],
                     max_running=2)
    got = pdecide(snap)
    assert got["start"] == [4, 5] and got["held"] == [{"task_id": 6, "why": parallel.PROJECT_FULL}]


def test_the_daily_cap_counts_the_starts_of_the_same_round():
    snap = psnapshot([pready(4, "a", footprint={"d/a"}), pready(5, "a", footprint={"d/b"})],
                     agents={"a": pagent(2, runs=4, cap=5)})
    got = pdecide(snap)
    assert got["start"] == [4] and got["held"] == [{"task_id": 5, "why": "cap: runs per day"}]
    metered = psnapshot([pready(4, "a", footprint={"d/a"}), pready(5, "a", footprint={"d/b"})],
                        agents={"a": pagent(2, usd=0.6, usd_cap=1.0)}, per_run_usd=0.5)
    metered["billing"] = {4: "metered", 5: "metered"}
    got = pdecide(metered)
    assert got["start"] == [4] and got["held"] == [{"task_id": 5, "why": "cap: usd per day"}]


def test_a_recently_refused_task_is_held_retry_soon():
    snap = psnapshot([pready(4, "a", footprint={"d/a"}), pready(5, "b", footprint={"d/b"})], refused={"4": "refused"})
    got = pdecide(snap)
    assert got["start"] == [5] and got["held"] == [{"task_id": 4, "why": parallel.RETRY_SOON}]


def test_the_dispatcher_words_equal_the_parallel_words():
    for word in (parallel.PROJECT_FULL, parallel.AGENT_FULL, parallel.CODE_IN_REQUEST, parallel.IN_USE, parallel.RETRY_SOON):
        assert word in dispatcher.REASONS, word


def test_decide_needs_an_admit_and_the_one_at_a_time_rule_is_gone():
    snapshot = {"running": None, "ready": [ready(4, "a"), ready(5, "a")], "reviews": [], "agents": {"a": agent()},
                "tier": {}, "billing": {4: "subscription", 5: "subscription"}}
    with pytest.raises(TypeError):
        dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start)
    assert dispatcher.decide(snapshot, autonomy.review_action, autonomy.may_start, allow) == {"release": [], "start": [4, 5], "held": []}


def test_two_answered_holders_never_block_each_other_forever():
    # tasks 4 and 5 both wait for their agent's one slot as answered holders: each already holds it, so neither is refused
    snap = psnapshot([pready(4, "a", footprint={"d/a"}), pready(5, "a", footprint={"d/b"})],
                     holding=[{"id": 4, "agent": "a"}, {"id": 5, "agent": "a"}])
    assert pdecide(snap)["start"] == [4, 5]


def test_held_of_lists_the_parallel_holds():
    snap = psnapshot([pready(4, "a", footprint={"d/a"}), pready(5, "a", footprint={"d/b"})],
                     running=[prun(3, "c", footprint={"d/c"})])
    decided = pdecide(snap)
    got = dispatcher.held_of(snap, decided)
    assert got == [{"task_id": 5, "agent": "a", "reason": parallel.AGENT_FULL}] or got == [
        {"task_id": 4, "agent": "a", "reason": parallel.AGENT_FULL}, {"task_id": 5, "agent": "a", "reason": parallel.AGENT_FULL}]
    assert all(h["reason"] in dispatcher.REASONS for h in got)

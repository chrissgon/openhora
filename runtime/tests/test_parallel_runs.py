"""Tests of the runs that overlap (PAR-4): several tasks of one project run at once, one OS process each, and the
dispatcher decides which may by the slots of the floors, the project's limit, the code task of a request and the files
in use; the locks that keep it safe; the recovery of what a dead process left; the report of what ran. On the stand-in
tree of standin_tree.py. The process a child would be is a thread here (`ops_runs.spawn` is the seam): its run is the
real `ops_runs.run_task`, with the lab's run held on an event so that two runs are alive at the same time. Offline;
invented names only.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_parallel_runs.py
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
import time

import pytest

import standin_tree as st

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_runs = st.load("ops_runs")
ops_say = st.load("ops_say")
plan = st.load("plan")
router = st.load("router")
dispatcher = st.load("dispatcher")
shell_kit = st.load("shell_kit")

PACKS = {"planning": ["core-clarify", "core-orchestrator"], "biz": ["demo-asks", "demo-writes", "demo-third"],
         "eng": ["demo-code"]}
WORDS = {"agent": "agent at max_parallel", "project": "project at max_running", "code": "a code task of the request runs",
         "use": "artifact in use", "soon": "could not start, tried again shortly"}
ROUTER_REPLY = "Route: flow-demo (flow, pending)\nWhy: a market question\nNext: the market task.\n"


def flow(key_skills: list, name: str) -> dict:
    """A flow file of independent tasks: [(key, skill)]."""
    return {"flow": name, "title": name, "tasks": [{"key": key, "skill": skill, "title": key.title(), "text": f"do {key}."}
                                                   for key, skill in key_skills]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    tree = built["tree"]
    st.skill(tree, router.ROUTER_SKILL, "docs/workbench/state.md", "")
    st.skill(tree, "demo-third", "docs/workbench/state.md", "docs/business/third.md")
    script = built["adapter"] / "run-prompt.sh"
    text = st.ADAPTER.replace("for name in demo-asks demo-writes;", "for name in demo-asks demo-writes demo-third core-orchestrator;")
    branch = ('if [ "$skill" = core-orchestrator ]; then\n  cp "$prompt" "$here/last-router-prompt.md"\n'
              '  cp "$here/router-reply.md" "$out/response.md"\n  exit 0\nfi\n')
    script.write_text(text.replace('case "$skill" in', branch + 'case "$skill" in', 1), encoding="utf-8")
    (built["adapter"] / "router-reply.md").write_text(ROUTER_REPLY, encoding="utf-8")
    for name, tasks in {"w-duo": [("market", "demo-asks"), ("change", "demo-code")],
                        "w-pair": [("market", "demo-asks"), ("profile", "demo-writes")],
                        "w-trio": [("market", "demo-asks"), ("profile", "demo-writes"), ("third", "demo-third")],
                        "w-writes": [("one", "demo-writes"), ("two", "demo-writes")],
                        "w-writes3": [("one", "demo-writes"), ("two", "demo-writes"), ("third", "demo-third")],
                        "w-code": [("one", "demo-code"), ("two", "demo-code")]}.items():
        (tree / "flows" / f"{name}.json").write_text(json.dumps(flow(tasks, name)), encoding="utf-8")
    business = built["project"] / "docs" / "business"
    business.mkdir(parents=True)
    (business / "market.md").write_text("# Market analysis\n\n- Owner: demo-asks\n- Status: draft\n", encoding="utf-8")
    monkeypatch.setattr(ops_core, "ROOT", str(tree))
    monkeypatch.setattr(plan, "resolve_pack", lambda pack, root: list(PACKS[pack]))
    configure(built)
    built["path"] = str(built["project"])
    return built


def configure(world, business=None, engineering=None, max_running=None) -> None:
    """The floors: business and engineering, supervised (every delivery waits for the person) unless a test says."""
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["area_agents"] = {
        "planning": {"pack": "planning", "max_runs_per_day": 50},
        "business": {"pack": "biz", "mode": "supervised", "max_runs_per_day": 50, **(business or {})},
        "engineering": {"pack": "eng", "mode": "supervised", "max_runs_per_day": 50, **(engineering or {})}}
    if max_running is not None:
        raw["max_running"] = max_running
    path.write_text(json.dumps(raw), encoding="utf-8")
    project = str(world["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])


def planned(world, flow_name: str) -> int:
    request = ops.request(world["path"], "Invented request.", title="Invented")["request"]
    pending_id = ops.route(world["path"], request, flow_name)["pending_id"]
    ops.approve(world["path"], pending_id, ops.pending(world["path"], pending_id)["payload"]["plan_sha256"])
    return request


def store_of(world):
    ctx = ops_core.context(world["path"])
    return ctx["store"], ctx["conn"]


def tasks_of(world, request=None) -> list:
    store, conn = store_of(world)
    return [t for t in store.tasks_list(conn) if t["parent_id"] is not None and (request is None or t["parent_id"] == request)]


def by_skill(world, skill: str, request=None) -> dict:
    return next(t for t in tasks_of(world, request) if t["skill"] == skill)


def held(world) -> dict:
    return {h["task_id"]: h["reason"] for h in ops.status(world["path"])["held"]}


def running_runs(world) -> list:
    store, conn = store_of(world)
    return store.task_runs_running(conn)


def until(condition, timeout: float = 30.0, what: str = "the condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


# --- the children: a thread that runs the task, and a lab whose run waits to be let go ---------------------------------------


class Thread:
    """What a child process looks like to the dispatcher: poll(), returncode, pid. Its run is ops_runs.run_task."""

    def __init__(self, project: str, task_id: int):
        self.pid, self.returncode, self.out = 0, None, None
        self.thread = threading.Thread(target=self.run, args=(project, task_id), daemon=True)
        self.thread.start()

    def run(self, project, task_id):
        try:
            self.out = ops_runs.run_task(project, task_id)
            code = 4 if self.out.get("ran") is None and not self.out.get("held") else 0
        except ops.OpsError as e:
            code = e.code
        except BaseException:
            code = 1
        self.returncode = code

    def poll(self):
        return self.returncode


class Lab:
    """The lab's run held on an event: `entered` lists the skills whose run began, `release` lets every held run go."""

    def __init__(self, monkeypatch, hold=("demo-asks", "demo-writes", "demo-third", "demo-code")):
        self.entered, self.lock, self.release, self.hold = [], threading.Lock(), threading.Event(), hold
        real = lab.run_skill

        def gated(skill, *args, **kwargs):
            if skill in self.hold:
                with self.lock:
                    self.entered.append(skill)
                assert self.release.wait(60), "the test never let the run go"
            return real(skill, *args, **kwargs)

        monkeypatch.setattr(lab, "run_skill", gated)
        monkeypatch.setattr(lab, "session", contextlib.nullcontext)  # one session of the process would end the other run


def threaded(monkeypatch, children: list):
    """Replace the seam so that a child is a thread; the children are collected in `children`."""
    def spawn(cfg, project, task_id):
        child = Thread(project, task_id)
        children.append((task_id, child))
        with ops_runs.SPAWNED_LOCK:
            ops_runs.SPAWNED.append((project, task_id, child))
        return child
    monkeypatch.setattr(ops_runs, "spawn", spawn)


def finish(children: list, timeout: float = 60.0) -> None:
    for _task_id, child in children:
        child.thread.join(timeout)
        assert not child.thread.is_alive()


# --- several tasks at once ----------------------------------------------------------------------------------------------------


def test_two_tasks_of_two_floors_run_at_the_same_time(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-duo")
    out = ops.dispatch(world["path"], wait=False)
    assert [s["task_id"] for s in out["started"]] == sorted(t["id"] for t in tasks_of(world, request))
    until(lambda: len(running_runs(world)) == 2, what="two run rows running together")
    until(lambda: len(held_lab.entered) == 2, what="both runs inside the lab")
    assert sorted(held_lab.entered) == ["demo-asks", "demo-code"]
    assert sorted(t["state"] for t in tasks_of(world, request)) == ["running", "running"]
    held_lab.release.set()
    finish(children)
    assert [c.out["ran"] is not None for _t, c in children] == [True, True] and running_runs(world) == []


def test_two_tasks_of_one_floor_run_together_up_to_its_slots(world, monkeypatch):
    configure(world, business={"max_parallel": 2})
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-trio")
    out = ops.dispatch(world["path"], wait=False)
    market, profile, third = (by_skill(world, s, request)["id"] for s in ("demo-asks", "demo-writes", "demo-third"))
    assert [s["task_id"] for s in out["started"]] == [market, profile]
    until(lambda: len(held_lab.entered) == 2, what="two runs inside the lab")
    assert held(world) == {third: WORDS["agent"]}
    held_lab.release.set()
    finish(children)
    # both are waiting for the person now, and a waiting task keeps its slot: the third still waits
    ops.dispatch(world["path"], wait=False)
    assert held(world) == {third: WORDS["agent"]}
    done = [p for p in ops.pending(world["path"])["pending"] if p["kind"] == "review"]
    ops.release(world["path"], done[0]["id"])  # the profile is done: its slot is free
    more = []
    threaded(monkeypatch, more)
    again = ops.dispatch(world["path"], wait=False)
    assert [s["task_id"] for s in again["started"]] == [third]
    finish(more)


def first_run_fails(world, monkeypatch, runs: int = 1) -> None:
    """The provider is down for the first `runs` runs of the lab (every attempt of each fails), and back after."""
    st.fail(world["adapter"], "adapter", 99)
    real = lab.run_skill
    calls = []

    def recovering(skill, *args, **kwargs):
        calls.append(skill)
        if len(calls) > runs:
            (world["adapter"] / "fail-times").write_text("0\n")
        return real(skill, *args, **kwargs)

    monkeypatch.setattr(lab, "run_skill", recovering)


def test_a_waiting_task_keeps_its_slot_and_a_failed_one_frees_it(world, monkeypatch):
    configure(world)  # one slot each
    request = planned(world, "w-trio")
    market, profile, third = (by_skill(world, s, request)["id"] for s in ("demo-asks", "demo-writes", "demo-third"))
    first_run_fails(world, monkeypatch)
    out = ops.dispatch(world["path"])
    states = {t["id"]: t["state"] for t in tasks_of(world, request)}
    assert states == {market: "failed", profile: "waiting", third: "ready"}  # the failure freed the slot, the waiting task keeps it
    assert [r["task_id"] for r in out["ran"]] == [market, profile] and held(world) == {third: WORDS["agent"]}
    assert ops.dispatch(world["path"])["started"] == []  # nothing frees it while the person has not decided


def test_an_answered_task_runs_again_in_its_own_slot(world):
    configure(world)
    request = planned(world, "w-pair")
    market, profile = by_skill(world, "demo-asks", request)["id"], by_skill(world, "demo-writes", request)["id"]
    ops.dispatch(world["path"])
    assert by_skill(world, "demo-asks", request)["state"] == "waiting" and held(world) == {profile: WORDS["agent"]}
    question = [p for p in ops.pending(world["path"])["pending"] if p["kind"] == "question"][0]
    ops.answer(world["path"], question["id"], "Portugal, remote.")
    store, conn = store_of(world)
    assert [h["id"] for h in store.task_slot_holders(conn)] == [market]  # ready again, and still a holder
    out = ops.dispatch(world["path"])
    assert [s["task_id"] for s in out["started"]] == [market]  # it is let in although the floor is full
    assert len(store.task_runs_list(conn, market)) == 2 and held(world) == {profile: WORDS["agent"]}


def test_a_retried_task_queues_like_a_new_one(world, monkeypatch):
    configure(world)
    request = planned(world, "w-pair")
    market, profile = by_skill(world, "demo-asks", request)["id"], by_skill(world, "demo-writes", request)["id"]
    first_run_fails(world, monkeypatch)
    ops.dispatch(world["path"])
    assert {t["id"]: t["state"] for t in tasks_of(world, request)} == {market: "failed", profile: "waiting"}
    ops.retry(world["path"], market)  # the profile holds the only slot: the retried task waits behind it
    store, conn = store_of(world)
    assert [h["id"] for h in store.task_slot_holders(conn)] == [profile]
    assert ops.dispatch(world["path"], wait=False)["started"] == [] and held(world) == {market: WORDS["agent"]}


def test_two_retried_tasks_on_one_slot_both_start_in_turn(world, monkeypatch):
    configure(world, business={"mode": "autonomous"})
    request = planned(world, "w-writes")
    one, two = sorted(t["id"] for t in tasks_of(world, request))
    first_run_fails(world, monkeypatch, runs=2)  # both tasks fail all their attempts
    ops.dispatch(world["path"])
    assert [t["state"] for t in tasks_of(world, request)] == ["failed", "failed"]
    ops.retry(world["path"], one)
    ops.retry(world["path"], two)
    out = ops.dispatch(world["path"])  # the mode releases the first delivery, which frees the slot for the second
    assert [s["task_id"] for s in out["started"]] == [one, two]
    states = [t["state"] for t in tasks_of(world, request)]
    assert states[0] == "done" and states[1] in ("waiting", "done")  # the second ran too, in the slot the first left


# --- the files in use, the code task of a request ---------------------------------------------------------------------------


def test_a_task_that_shares_an_artifact_waits_for_the_other(world, monkeypatch):
    configure(world, business={"max_parallel": 2})
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-writes")
    one, two = sorted(t["id"] for t in tasks_of(world, request))
    out = ops.dispatch(world["path"], wait=False)
    assert [s["task_id"] for s in out["started"]] == [one]  # both write docs/business/icp.md
    until(lambda: len(held_lab.entered) == 1, what="the first run inside the lab")
    assert held(world) == {two: WORDS["use"]}
    held_lab.release.set()
    finish(children)
    more = []
    threaded(monkeypatch, more)
    assert [s["task_id"] for s in ops.dispatch(world["path"], wait=False)["started"]] == [two]  # the first no longer runs
    finish(more)


def test_two_code_tasks_of_one_request_run_one_after_the_other(world, monkeypatch):
    configure(world, engineering={"max_parallel": 2, "mode": "autonomous"})
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-code")
    one, two = sorted(t["id"] for t in tasks_of(world, request))
    out = ops.dispatch(world["path"], wait=False)
    assert [s["task_id"] for s in out["started"]] == [one]
    until(lambda: len(held_lab.entered) == 1, what="the first code task inside the lab")
    assert held(world) == {two: WORDS["code"]}
    held_lab.release.set()
    finish(children)


def test_the_project_s_limit_holds_a_task_that_a_floor_would_take(world, monkeypatch):
    configure(world, business={"max_parallel": 2}, max_running=1)
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-pair")
    market, profile = by_skill(world, "demo-asks", request)["id"], by_skill(world, "demo-writes", request)["id"]
    assert [s["task_id"] for s in ops.dispatch(world["path"], wait=False)["started"]] == [market]
    until(lambda: len(held_lab.entered) == 1, what="the first run inside the lab")
    assert held(world) == {profile: WORDS["project"]}
    held_lab.release.set()
    finish(children)


# --- the round: with and without waiting, and what it reports -------------------------------------------------------------------


def test_dispatch_without_wait_returns_at_once_and_the_next_round_reports_what_ran(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-duo")
    began = time.monotonic()
    out = ops.dispatch(world["path"], wait=False)
    assert time.monotonic() - began < 5 and out["ran"] == [] and len(out["started"]) == 2
    until(lambda: len(held_lab.entered) == 2, what="both runs inside the lab")
    held_lab.release.set()
    finish(children)
    again = ops.dispatch(world["path"], wait=False)
    assert sorted(r["task_id"] for r in again["ran"]) == sorted(t["id"] for t in tasks_of(world, request))
    assert ops.dispatch(world["path"], wait=False)["ran"] == []  # each run is reported once


def test_dispatch_with_wait_returns_when_its_children_end(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    request = planned(world, "w-duo")
    timer = threading.Timer(0.5, held_lab.release.set)
    timer.start()
    out = ops.dispatch(world["path"], wait=True)
    timer.join()
    assert ops_runs.alive(world["path"]) == [] and all(c.poll() is not None for _t, c in children)
    assert sorted(r["task_id"] for r in out["ran"]) == sorted(t["id"] for t in tasks_of(world, request))
    assert all(r["status"] == "ok" for r in out["ran"]) and out["stopped"] is not None
    assert running_runs(world) == []


def run_rows(world, request):
    """Two claimed tasks of a request, each with a run row opened: [(task id, run id)]."""
    store, conn = store_of(world)
    out = []
    for task in tasks_of(world, request):
        claimed = store.task_claim(conn, task["id"])["task"]
        run = store.task_run_start(conn, claimed["id"], skill=claimed["skill"], model="m", adapter="h")["run_id"]
        out.append((claimed["id"], run))
    return out


def end_run(world, run_id: int) -> None:
    store, conn = store_of(world)
    store.task_run_finish(conn, run_id, status="ok", ending="done", task_state="waiting", cost_usd=None,
                          pending={"kind": "review", "title": "Done", "body": "Wrote it."})


def test_the_report_keeps_a_run_that_ends_after_a_newer_one(world):
    request = planned(world, "w-pair")
    ctx = ops_core.context(world["path"])
    assert ops_runs._reported(ctx) == []  # the cursor starts here
    (first_task, first_run), (second_task, second_run) = run_rows(world, request)
    end_run(world, second_run)  # the newer run ends first
    assert [r["run_id"] for r in ops_runs._reported(ctx)] == [second_run]
    end_run(world, first_run)
    assert [r["run_id"] for r in ops_runs._reported(ctx)] == [first_run]  # the older run is not lost behind the cursor
    assert ops_runs._reported(ctx) == []


def test_a_run_is_reported_exactly_once_over_three_rounds(world):
    request = planned(world, "w-pair")
    ctx = ops_core.context(world["path"])
    ops_runs._reported(ctx)
    runs = run_rows(world, request)
    seen = []
    for position in range(3):  # three rounds: nothing, one ended, the other ended
        if position:
            end_run(world, runs[position - 1][1])
        seen += [r["run_id"] for r in ops_runs._reported(ctx)]
    assert sorted(seen) == sorted(run for _task, run in runs) and len(seen) == 2


def test_the_first_report_after_the_upgrade_reports_no_history(world):
    request = planned(world, "w-pair")
    runs = run_rows(world, request)
    for _task, run in runs:
        end_run(world, run)
    ctx = ops_core.context(world["path"])
    assert ctx["store"].cursor_get(ctx["conn"], ops_runs.REPORTED_CURSOR) is None
    assert ops_runs._reported(ctx) == []  # runs that ended before the cursor existed are history
    assert json.loads(ctx["store"].cursor_get(ctx["conn"], ops_runs.REPORTED_CURSOR))["low"] == max(r for _t, r in runs) + 1
    assert ops_runs._reported(ctx) == []


class Gone:
    """A child that ended at once with a code."""
    pid = 0

    def __init__(self, code):
        self.returncode = code

    def poll(self):
        return self.returncode


@pytest.mark.parametrize("code", [4, 1])
def test_a_child_refused_or_crashed_before_its_claim_is_held_retry_soon_for_120_s(world, monkeypatch, code):
    request = planned(world, "w-pair")
    market = by_skill(world, "demo-asks", request)["id"]
    started = []

    def dead(cfg, project, task_id):
        started.append(task_id)
        child = Gone(code)  # exit 4: refused and not run; exit 1 with the task still ready: it crashed before its claim
        with ops_runs.SPAWNED_LOCK:
            ops_runs.SPAWNED.append((project, task_id, child))
        return child

    monkeypatch.setattr(ops_runs, "spawn", dead)
    configure(world, business={"max_parallel": 2})
    ops.dispatch(world["path"], wait=False)
    assert market in started
    ops.dispatch(world["path"], wait=False)  # reaps the dead child, writes the record, and holds the task
    assert held(world)[market] == WORDS["soon"] and started.count(market) == 1
    store, conn = store_of(world)
    cursor = json.loads(store.cursor_get(conn, ops_runs.REFUSED_CURSOR))
    assert cursor[str(market)]["reason"] == ("refused" if code == 4 else "crashed")
    cursor[str(market)]["at"] -= 121  # 120 seconds later the task may start again
    store.cursor_set(conn, ops_runs.REFUSED_CURSOR, json.dumps(cursor))
    ops.dispatch(world["path"], wait=False)
    assert started.count(market) == 2


# --- the locks and the recovery -------------------------------------------------------------------------------------------------


def test_a_dead_process_leaves_a_task_and_a_run_that_recovery_ends(world):
    request = planned(world, "w-pair")
    (task, run), _other = run_rows(world, request)
    ctx = ops_core.context(world["path"])
    got = ops_runs._recover(ctx)
    assert got["tasks"] == [task, _other[0]] and run in got["runs"]
    assert by_skill(world, "demo-asks", request)["state"] == "failed"
    store, conn = store_of(world)
    ended = store.task_runs_list(conn, task)[0]
    assert (ended["status"], ended["failure"]) == ("failed", "stopped")


def test_recovery_never_fails_a_task_whose_lock_is_held_and_writes_no_owner_line(world):
    request = planned(world, "w-pair")
    (task, _run), (other, _run2) = run_rows(world, request)
    ctx = ops_core.context(world["path"])
    cfg = ctx["cfg"]
    fd = ops_core._try_lock(cfg, f"task-{task}.lock")  # its process is alive
    got = ops_runs._recover(ctx)
    assert got["tasks"] == [other]  # only the other one, whose lock was free
    assert {t["id"]: t["state"] for t in tasks_of(world, request)}[task] == "running"
    assert os.path.getsize(os.path.join(cfg["data_dir"], "locks", f"task-{other}.lock")) == 0  # a probe writes nothing
    os.close(fd)
    assert ops_core._lock_pgid(cfg, task) is None  # a probe never wrote a group either


def test_the_task_lock_holds_the_group_of_its_process_and_refuses_a_second_holder(world):
    cfg = ops_core.context(world["path"])["cfg"]
    with ops_core._task_lock(cfg, 7):
        assert ops_core._lock_pgid(cfg, 7) == os.getpgrp() and ops_core._lock_owner(cfg, 7)[0] == os.getpid()
        with pytest.raises(ops.OpsError, match="task 7 is already being run by another process"):
            with ops_core._task_lock(cfg, 7):
                pass
    assert ops_core._try_lock(cfg, "task-7.lock") is not None


def test_the_claim_lock_makes_two_processes_unable_to_pass_the_same_cap(world, monkeypatch):
    configure(world)  # one slot for the business floor
    held_lab = Lab(monkeypatch)
    request = planned(world, "w-pair")
    market, profile = by_skill(world, "demo-asks", request)["id"], by_skill(world, "demo-writes", request)["id"]
    start = threading.Barrier(2)
    results = {}

    def go(task_id):
        start.wait()
        results[task_id] = ops_runs.run_task(world["path"], task_id)

    threads = [threading.Thread(target=go, args=(t,), daemon=True) for t in (market, profile)]
    for t in threads:
        t.start()
    until(lambda: len(results) == 1 or len(held_lab.entered) == 1 and len(results) == 1, what="one refusal")
    refused = next(iter(results.values()))
    assert refused["ran"] is None and refused["held"] is True and refused["reason"] == WORDS["agent"]
    held_lab.release.set()
    for t in threads:
        t.join(60)
    assert sorted(r["ran"] is not None for r in results.values()) == [False, True]


def test_run_next_checks_the_footprint_under_the_claim_lock(world):
    configure(world, business={"max_parallel": 2})
    request = planned(world, "w-writes")
    one, two = sorted(t["id"] for t in tasks_of(world, request))
    store, conn = store_of(world)
    store.task_claim(conn, one)  # the first is running, and its process is alive
    store.task_run_start(conn, one, skill="demo-writes", model="m", adapter="h")
    cfg = ops_core.context(world["path"])["cfg"]
    alive = ops_core._try_lock(cfg, f"task-{one}.lock")
    out = ops.run_next(world["path"])  # it only chooses: the footprint holds it back
    assert out["ran"] is None and WORDS["use"] in out["reason"]
    refused = ops_runs.run_task(world["path"], two, checked=False)  # the real check is made under the claim lock
    assert refused["ran"] is None and refused["held"] is True and refused["reason"] == WORDS["use"]
    os.close(alive)


def test_run_next_works_with_no_area_agents(world):
    path = world["project"] / "docs" / "workbench" / "runtime.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    del raw["area_agents"]
    path.write_text(json.dumps(raw), encoding="utf-8")
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"])
    ops.request(world["path"], "Which market first?", "demo")
    out = ops.run_next(world["path"])
    assert out["skill"] == "demo-asks" and out["status"] == "ok" and out["recovered"] == []


def test_poll_still_decides_with_the_new_snapshot(world):
    configure(world, business={"mode": "autonomous"})
    request = planned(world, "w-writes")
    one = sorted(t["id"] for t in tasks_of(world, request))[0]
    ops.run_next(world["path"])  # a delivery waits in a review
    review = [p for p in ops.pending(world["path"])["pending"] if p["kind"] == "review"][0]
    out = ops.poll(world["path"])  # poll builds the snapshot the dispatcher builds and starts nothing
    assert [r["pending_id"] for r in out["released"]] == [review["id"]] and one
    ctx = ops_core.context(world["path"])
    snapshot = ops._snapshot(ctx, ops_core._floor_key())
    assert {"running", "holding", "refused", "ready", "max_running", "per_run_usd"} <= set(snapshot)
    assert all("footprint" in t and "code" in t for t in snapshot["ready"])


# --- the router beside the runs ---------------------------------------------------------------------------------------------------


def test_a_line_typed_during_a_task_run_is_routed_at_once(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    planned(world, "w-duo")
    ops.dispatch(world["path"], wait=False)
    until(lambda: len(held_lab.entered) == 2, what="two task runs alive")
    said = ops.say(world["path"], "Which market should the invented studio go after first?", channel="page")
    assert said["queued"] is False and said["ran"] is True and said["pending_id"]  # the router ran beside the tasks
    held_lab.release.set()
    finish(children)


def test_a_line_typed_during_a_router_run_is_queued_on_the_page_and_refused_elsewhere(world):
    cfg = ops_core.context(world["path"])["cfg"]
    line = "Which market should the invented studio go after first?"
    with ops_core._route_lock(cfg):  # another request is being routed
        queued = ops.say(world["path"], line, channel="page")
        assert queued["queued"] is True and queued["reply"] is None
        with pytest.raises(ops_core.RunBusy, match="the planning agent is answering another request"):
            ops.say(world["path"], line, channel="terminal")
    assert ops.route_queued(world["path"])["routed"] == "line"  # the router is free: the queue is answered


def test_a_router_orphan_is_recovered_by_the_next_route(world):
    request = ops.request(world["path"], "Which market first?")["request"]
    ctx = ops_core.context(world["path"])
    store, conn = ctx["store"], ctx["conn"]
    dead = store.route_run_start(conn, request, skill=router.ROUTER_SKILL, model="m", adapter="h")["run_id"]  # no process holds the route lock
    out = ops.route(world["path"], request)
    assert out["routed"] is True and out["recovered"] == []
    ended = [r for r in store.task_runs_list(conn, request) if r["id"] == dead][0]
    assert (ended["status"], ended["failure"]) == ("failed", "stopped")
    assert ops.status(world["path"])["requests"][0]["routing"] is None


# --- the write lock ---------------------------------------------------------------------------------------------------------------


def test_the_write_lock_is_reentrant_in_one_thread_and_exclusive_across_threads(world):
    cfg = ops_core.context(world["path"])["cfg"]
    with ops_core._write_lock(cfg):
        with ops_core._write_lock(cfg):  # a writer that calls another writer does not wait on itself
            pass
        probe = {}

        def other():
            try:
                with ops_core._write_lock(cfg, wait=0.3):
                    probe["got"] = True
            except ops.OpsError as e:
                probe["error"] = str(e)

        t = threading.Thread(target=other)
        t.start()
        t.join(10)
        assert "got" not in probe and "files stayed busy" in probe["error"]
    with ops_core._write_lock(cfg, wait=0.3):  # released when the outer block ends
        pass


def test_the_return_waits_for_the_write_lock_without_a_timeout(world, monkeypatch):
    request = planned(world, "w-writes")
    one = sorted(t["id"] for t in tasks_of(world, request))[0]
    cfg = ops_core.context(world["path"])["cfg"]
    monkeypatch.setattr(ops_core, "WRITE_LOCK_WAIT", 0.2)  # every other holder gives up after a fifth of a second
    taken, out = threading.Event(), {}

    def holder():
        with ops_core._write_lock(cfg):
            taken.set()
            time.sleep(1.0)

    thread = threading.Thread(target=holder)
    thread.start()
    taken.wait(10)
    began = time.monotonic()
    out = ops_runs.run_task(world["path"], one)  # its return into the project waits for the lock, however long
    thread.join(10)
    assert out["status"] == "ok" and time.monotonic() - began >= 0.5


def test_every_state_file_writer_takes_the_write_lock(world, monkeypatch):
    cfg = ops_core.context(world["path"])["cfg"]
    request = planned(world, "w-pair")
    question = ops.run_next(world["path"])["pending_id"]
    state = world["project"] / "docs" / "workbench" / "state.md"
    before = state.read_text(encoding="utf-8")
    ctx = ops_core.context(world["path"])
    writers = {
        "sync": lambda: ops.sync(world["path"]),
        "hand_over": lambda: ops.hand_over(world["path"], by_skill(world, "demo-writes", request)["id"], __file__),
        "go-ahead": lambda: st.load("ops_waits")._record_decision(ctx, [("demo-asks", 1, ["x"])]),
        "standing rows": lambda: ops._standing_rows(ctx),
        "approval row": lambda: ops._write_approval_row(cfg, ["action", "x", "0" * 64, "2026-10-12", "", "executed"]),
        "checkpoints": lambda: st.load("ops_config").write_checkpoints(cfg),
    }
    monkeypatch.setattr(ops_core, "WRITE_LOCK_WAIT", 0.1)
    taken, release = threading.Event(), threading.Event()

    def holder():
        with ops_core._write_lock(cfg):
            taken.set()
            release.wait(30)

    thread = threading.Thread(target=holder)
    thread.start()
    taken.wait(10)
    try:
        for name, call in writers.items():
            with pytest.raises(ops.OpsError, match="files stayed busy"):
                call()
        answered = ops.answer(world["path"], question, "Portugal.")  # the answer is kept; the state file waits
        assert answered["state"]["written"] is False and "files stayed busy" in answered["state"]["reason"]
        assert state.read_text(encoding="utf-8") == before
    finally:
        release.set()
        thread.join(10)
    assert ops.sync(world["path"]) == {"board": None, "documents": None}  # free again


def test_an_effect_is_refused_while_a_code_task_of_its_request_runs(world):
    request = planned(world, "w-code")
    one, two = sorted(t["id"] for t in tasks_of(world, request))
    store, conn = store_of(world)
    store.task_claim(conn, two)  # a code task of the request is running
    pending = {"id": 5, "task_id": one, "kind": "effect", "status": "open", "payload_sha256": "a" * 64,
               "payload": {"effect_file": "/nowhere"}}
    ctx = ops_core.context(world["path"])
    with pytest.raises(ops.OpsError, match="a code task of this request is running; approve when it ends"):
        ops._approve_effect(ctx, pending, "a" * 64)


# --- stopping ---------------------------------------------------------------------------------------------------------------------


def holder_process(cfg, task_id: int, leader: bool = True, on_term: str = "die"):
    """A process that holds a task's lock and sleeps, with "<pid> <pgid>" in the file as a task run writes it. leader: it
    has a session (and a group) of its own, as a dispatcher's child; otherwise it shares the test's group, as a `run-next`
    started from a shell does. on_term: "die" (the default), "ignore" (SIGTERM does nothing), "release" (SIGTERM closes the
    lock and the process goes on sleeping)."""
    code = ("import sys, os, time, signal; sys.path.insert(0, %r); import ops_core as core; "
            "cfg = {'data_dir': %r}; fd = core._try_lock(cfg, 'task-%d.lock'); "
            "os.ftruncate(fd, 0); os.write(fd, ('%%d %%d\\n' %% (os.getpid(), os.getpgrp())).encode()); "
            "mode = %r\n"
            "if mode == 'ignore': signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "if mode == 'release': signal.signal(signal.SIGTERM, lambda *a: os.close(fd))\n"
            "print('held', flush=True); time.sleep(60)"
            % (str(st.RUNTIME), cfg["data_dir"], task_id, on_term))
    process = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, start_new_session=leader)
    assert process.stdout.readline().strip() == b"held"
    return process


def test_stop_runs_ends_only_this_processs_children_and_all_ends_every_live_run(world, monkeypatch):
    cfg = ops_core.context(world["path"])["cfg"]
    mine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    with ops_runs.SPAWNED_LOCK:
        ops_runs.SPAWNED.append((world["path"], 11, mine))
    foreign = holder_process(cfg, 12)  # a run another process started
    try:
        out = ops.stop_runs(world["path"])
        assert out["stopped"] is True and until(lambda: mine.poll() is not None, 15, "my child to end")
        assert foreign.poll() is None  # not this process's: left alone
        out = ops.stop_runs(world["path"], every=True)
        assert out["tasks"] == [12]
        until(lambda: foreign.poll() is not None, 15, "the foreign run to end")
    finally:
        lab.LAB.STOPPING.clear()  # stop_runs leaves the lab's stopping flag set: later tests of this worker must not see it
        for process in (mine, foreign):
            if process.poll() is None:
                process.kill()
            process.wait()


def test_stop_all_signals_the_pid_alone_when_the_holder_shares_its_starters_group(world):
    cfg = ops_core.context(world["path"])["cfg"]
    shared = holder_process(cfg, 14, leader=False)  # as a `run-next` from a shell: it is in the group of whoever started it
    try:
        assert os.getpgid(shared.pid) == os.getpgrp()
        assert ops_runs.stop_children(only_mine=False, cfg=cfg, grace=5) == [14]
        until(lambda: shared.poll() is not None, 15, "the holder to end")  # and this process, in that group, is still here
    finally:
        if shared.poll() is None:
            shared.kill()
        shared.wait()


def test_kill_follows_term_only_while_the_lock_is_still_held(world):
    cfg = ops_core.context(world["path"])["cfg"]
    stubborn = holder_process(cfg, 15, on_term="ignore")  # holds the lock and ignores TERM
    letting_go = holder_process(cfg, 16, on_term="release")  # lets the lock go on TERM and carries on (its clean-up)
    try:
        assert sorted(ops_runs.stop_children(only_mine=False, cfg=cfg, grace=1.0)) == [15, 16]
        until(lambda: stubborn.poll() is not None, 15, "the holder that kept its lock to be killed")
        assert letting_go.poll() is None  # its lock was free: no KILL may interrupt what it does
    finally:
        for process in (stubborn, letting_go):
            if process.poll() is None:
                process.kill()
            process.wait()


def test_the_task_lock_is_emptied_when_it_is_released(world):
    cfg = ops_core.context(world["path"])["cfg"]
    with ops_core._task_lock(cfg, 8):
        assert ops_core._lock_owner(cfg, 8) == (os.getpid(), os.getpgrp())
    assert ops_core._lock_owner(cfg, 8) is None
    assert os.path.getsize(os.path.join(cfg["data_dir"], "locks", "task-8.lock")) == 0


def test_stop_never_signals_a_pgid_whose_lock_is_free(world):
    cfg = ops_core.context(world["path"])["cfg"]
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        os.makedirs(os.path.join(cfg["data_dir"], "locks"), exist_ok=True)
        with open(os.path.join(cfg["data_dir"], "locks", "task-13.lock"), "w", encoding="ascii") as f:
            f.write(f"{os.getpgid(bystander.pid)}\n")  # a stale file: its holder died, the group number is another process's now
        assert ops_runs.stop_children(only_mine=False, cfg=cfg, grace=0.2) == []
        assert bystander.poll() is None
    finally:
        bystander.kill()
        bystander.wait()


def test_two_dispatch_rounds_of_one_project_never_overlap(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    planned(world, "w-duo")
    out = {}
    first = threading.Thread(target=lambda: out.update(first=ops.dispatch(world["path"], wait=True)), daemon=True)
    first.start()
    until(lambda: len(held_lab.entered) == 2, what="the waiting round's children inside the lab")
    with pytest.raises(ops.DispatchBusy, match="a dispatch round of this project is already running"):
        ops.dispatch(world["path"], wait=False)  # the waiting round holds the dispatch lock
    held_lab.release.set()
    first.join(60)
    assert "first" in out


def test_a_waiting_round_that_raises_still_waits_for_its_children(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    planned(world, "w-duo")
    real = ops._snapshot
    calls = []

    def breaks(ctx, key):
        calls.append(1)
        if len(calls) > 1:
            raise ops.OpsError("the store went away", 1)
        return real(ctx, key)

    monkeypatch.setattr(ops, "_snapshot", breaks)
    threading.Timer(0.5, held_lab.release.set).start()
    began = time.monotonic()
    with pytest.raises(ops.OpsError, match="the store went away"):
        ops.dispatch(world["path"], wait=True)
    assert time.monotonic() - began >= 0.4 and all(c.poll() is not None for _t, c in children)  # waited, then raised
    assert ops_runs.alive(world["path"]) == []


def test_a_child_does_not_inherit_a_key_a_router_call_injected(world, monkeypatch):
    seen = {}

    class Fake:
        def __init__(self, *args, **kwargs):
            seen["env"] = kwargs["env"]
            seen["args"] = args[0]
            self.pid = 0

        def poll(self):
            return 0

    monkeypatch.setattr(ops_runs.subprocess, "Popen", Fake)
    monkeypatch.setenv("EXPORTED_BY_THE_PERSON", "kept")
    monkeypatch.setenv("INJECTED_BY_A_ROUTER_CALL", "secret")
    monkeypatch.setitem(ops_core.ENV_INJECTED, "INJECTED_BY_A_ROUTER_CALL", None)  # injected, and not there before
    monkeypatch.setitem(ops_core.ENV_INJECTED, "OVERWRITTEN_BY_A_ROUTER_CALL", "before")
    monkeypatch.setenv("OVERWRITTEN_BY_A_ROUTER_CALL", "secret")
    cfg = ops_core.context(world["path"])["cfg"]
    world["real_spawn"](cfg, world["path"], 3)
    assert seen["env"]["EXPORTED_BY_THE_PERSON"] == "kept"
    assert "INJECTED_BY_A_ROUTER_CALL" not in seen["env"] and seen["env"]["OVERWRITTEN_BY_A_ROUTER_CALL"] == "before"
    assert seen["args"][1].endswith(os.path.join("runtime", "cli.py")) and seen["args"][2:4] == ["run-task", "--project"]
    assert os.path.isdir(os.path.join(cfg["data_dir"], "task-runs", "children"))


def test_the_run_task_verb_is_terminal_only_and_refuses_an_unconfigured_project_with_exit_3(tmp_path):
    row = ops.operations.by_name("run-task")
    assert row["channels"] == ("terminal",) and row["exclusive"] is False and row["job"] is True
    cli = st.RUNTIME / "cli.py"
    done = subprocess.run([sys.executable, str(cli), "run-task", "--project", str(tmp_path / "nowhere"), "--task", "1"],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 3 and "error:" in done.stderr


# --- the reads of the interface ---------------------------------------------------------------------------------------------------


def test_status_marks_the_tasks_that_hold_a_slot(world):
    configure(world)
    request = planned(world, "w-pair")
    ops.dispatch(world["path"])  # the asks task runs and waits for the person: it holds the slot
    tasks = {t["skill"]: t for r in ops.status(world["path"])["requests"] for t in r["tasks"]}
    assert tasks["demo-asks"]["holds_slot"] is True and tasks["demo-writes"]["holds_slot"] is False and request


def test_agents_gives_the_slots_the_holders_and_the_ceiling(world):
    configure(world, business={"max_parallel": 2})
    planned(world, "w-pair")
    ops.dispatch(world["path"])
    agents = {a["name"]: a for a in ops.agents(world["path"])["agents"]}
    business = agents["business"]
    assert business["max_parallel"] == 2 and business["max_parallel_ceiling"] == ops.autonomy.MAX_PARALLEL_CEILING
    assert business["slots_held"] == 2 and len(business["holders"]) == 2
    assert agents["engineering"]["max_parallel"] == 1 and agents["engineering"]["holders"] == []


def test_the_service_lists_the_ids_of_the_running_tasks(world, monkeypatch):
    held_lab, children = Lab(monkeypatch), []
    threaded(monkeypatch, children)
    planned(world, "w-duo")
    ops.dispatch(world["path"], wait=False)
    until(lambda: len(held_lab.entered) == 2, what="two runs alive")
    kit = shell_kit.Jobs(ops, shell_kit.projects_of([world["path"]], ops))
    listed = kit.projects_list()["projects"][0]
    assert len(listed["running_tasks"]) == 2 and listed["running_task"] == min(listed["running_tasks"])
    held_lab.release.set()
    finish(children)


# --- a round cannot start the same task again and again ---------------------------------------------------------------------


def test_a_child_that_leaves_its_task_ready_is_started_once_in_a_round(world, monkeypatch):
    """The child's admission under the claim lock can disagree with the parent's decision (a held word): it exits 0 and the
    task stays ready. The record of the refusal makes the waiting round hold it, instead of starting it in a tight loop."""
    request = planned(world, "w-pair")
    market = by_skill(world, "demo-asks", request)["id"]
    started = []

    def idle(cfg, project, task_id):
        started.append(task_id)
        child = Gone(0)
        with ops_runs.SPAWNED_LOCK:
            ops_runs.SPAWNED.append((project, task_id, child))
        return child

    monkeypatch.setattr(ops_runs, "spawn", idle)
    configure(world, business={"max_parallel": 2})
    out = ops.dispatch(world["path"], wait=True)
    assert started.count(market) == 1 and out["stopped"] is not None
    assert held(world)[market] == WORDS["soon"]


def test_a_task_started_and_not_yet_claimed_is_counted_as_running_and_not_decided_again(world):
    configure(world, business={"max_parallel": 2})
    request = planned(world, "w-writes")  # two tasks that write the same file
    one, two = sorted(t["id"] for t in tasks_of(world, request))
    child = Gone(None)  # a child that is alive and has not claimed yet
    with ops_runs.SPAWNED_LOCK:
        ops_runs.SPAWNED.append((world["path"], one, child))
    ctx = ops_core.context(world["path"])
    snapshot = ops._snapshot(ctx, ops_core._floor_key())
    assert [t["id"] for t in snapshot["ready"]] == [two] and [r["id"] for r in snapshot["running"]] == [one]
    assert held(world) == {} or held(world).get(one) is None  # never held against its own footprint
    child.returncode = 0  # it ended: the snapshot reaps before it counts
    snapshot = ops._snapshot(ctx, ops_core._floor_key())
    assert snapshot["running"] == [] and sorted(t["id"] for t in snapshot["ready"]) == [one, two]


def test_a_lock_that_changed_hands_during_the_grace_is_not_killed(world):
    cfg = ops_core.context(world["path"])["cfg"]
    first = holder_process(cfg, 17, on_term="release")  # lets the lock go on TERM, but stays alive
    second = []
    try:
        def take_over():
            until(lambda: first.poll() is None and ops_core._lock_owner(cfg, 17) is not None, 5, "owner")
            until(lambda: _free(cfg, 17), 10, "the first holder to let go")
            second.append(holder_process(cfg, 17))  # another process takes the task's lock
        thread = threading.Thread(target=take_over, daemon=True)
        thread.start()
        assert ops_runs.stop_children(only_mine=False, cfg=cfg, grace=4.0) == [17]
        thread.join(15)
        assert second and second[0].poll() is None  # the new holder never got a TERM, and no KILL either
        assert first.poll() is None
    finally:
        for process in [first, *second]:
            if process.poll() is None:
                process.kill()
            process.wait()


def _free(cfg, task_id) -> bool:
    fd = ops_core._try_lock(cfg, f"task-{task_id}.lock")
    if fd is None:
        return False
    os.close(fd)
    return True


# --- the review leftovers of PAR-4 (PAR-6) ------------------------------------------------------------------------------------


def hold_effect(world, request_id: int):
    cfg = ops_core.context(world["path"])["cfg"]
    fd = ops_core._try_lock(cfg, f"effect-{request_id}.lock")
    assert fd is not None
    return fd


def test_a_code_task_is_not_claimed_while_an_effect_of_its_request_executes(world):
    request = planned(world, "w-code")
    one = min(t["id"] for t in tasks_of(world, request))
    fd = hold_effect(world, request)
    try:
        out = ops.run_next(world["path"])
        assert out["ran"] is None and WORDS["code"] in out["reason"]
        assert by_skill(world, "demo-code", request)["state"] == "ready"
        assert ops.run_task(world["path"], one)["held"] is True
    finally:
        os.close(fd)


def test_a_task_of_another_request_is_not_held_by_an_effect(world):
    request, other = planned(world, "w-code"), planned(world, "w-writes")
    fd = hold_effect(world, request)
    try:
        out = ops.run_next(world["path"])  # the code task is older but held; the other request's task is let in
        assert out["ran"] is not None
        assert by_skill(world, "demo-code", request)["state"] == "ready"  # still waiting for the effect
        assert by_skill(world, "demo-writes", other)["state"] != "ready"
    finally:
        os.close(fd)


def test_the_effect_approval_holds_its_requests_lock_while_it_works_and_lets_go_after(world, monkeypatch):
    request = planned(world, "w-code")
    one = min(t["id"] for t in tasks_of(world, request))
    cfg = ops_core.context(world["path"])["cfg"]
    seen = []

    class Kind:
        GATE = True

        @staticmethod
        def unconfigured(cfg):
            seen.append(ops_core._effects_running(cfg))
            return "stop here"

    monkeypatch.setattr(ops.effects, "module_for", lambda word: Kind)
    path = world["project"] / "effect.json"
    path.write_text(json.dumps({"effect": "push"}), encoding="ascii")
    pending = {"id": 5, "task_id": one, "kind": "effect", "status": "open", "payload_sha256": "a" * 64,
               "payload": {"effect_file": str(path)}}
    with pytest.raises(ops.OpsError, match="stop here"):
        ops._approve_effect(ops_core.context(world["path"]), pending, "a" * 64)
    assert seen and all(found == frozenset({request}) for found in seen)
    assert ops_core._effects_running(cfg) == frozenset()


def test_two_effects_of_one_request_do_not_execute_together(world):
    request = planned(world, "w-code")
    one = min(t["id"] for t in tasks_of(world, request))
    fd = hold_effect(world, request)
    pending = {"id": 5, "task_id": one, "kind": "effect", "status": "open", "payload_sha256": "a" * 64, "payload": {}}
    try:
        with pytest.raises(ops.OpsError, match="an effect of this request is already executing"):
            ops._approve_effect(ops_core.context(world["path"]), pending, "a" * 64)
    finally:
        os.close(fd)


def test_the_refused_cursor_is_written_under_the_claim_lock_so_two_writers_keep_each_others_entries(world):
    ctx = ops_core.context(world["path"])
    ops_runs._refused_write(ctx, {"3": {"reason": "refused", "at": time.time()}})
    done = threading.Event()

    def write():
        ops_runs._refused_write(ops_core.context(world["path"]), {"4": {"reason": "crashed", "at": time.time()}})
        done.set()

    with ops_core._claim_lock(ctx["cfg"]):  # another process (the scheduler's job) is inside its claim
        thread = threading.Thread(target=write, daemon=True)
        thread.start()
        assert not done.wait(0.5), "the cursor was rewritten while another process held the claim lock"
    assert done.wait(10)
    assert ops_runs.refused_now(ctx) == {3: "refused", 4: "crashed"}


def lock_files(world) -> set:
    folder = os.path.join(ops_core.context(world["path"])["cfg"]["data_dir"], "locks")
    return {n for n in os.listdir(folder) if n.startswith("task-")} if os.path.isdir(folder) else set()


def test_a_task_lock_file_is_removed_when_its_task_is_done_or_cancelled_and_never_while_it_is_held(world):
    request = planned(world, "w-trio")
    one, two, three = sorted(t["id"] for t in tasks_of(world, request))
    ctx = ops_core.context(world["path"])
    cfg, store, conn = ctx["cfg"], ctx["store"], ctx["conn"]
    for task_id in (one, two, three):  # every task has run once: a lock file each
        os.close(ops_core._try_lock(cfg, f"task-{task_id}.lock"))
    assert lock_files(world) == {f"task-{i}.lock" for i in (one, two, three)}
    conn.execute("UPDATE tasks SET state = 'done' WHERE id = ?", (one,))
    conn.execute("UPDATE tasks SET state = 'cancelled' WHERE id = ?", (two,))
    conn.commit()
    held_fd = ops_core._try_lock(cfg, f"task-{one}.lock")  # a live process still holds the finished task's lock
    try:
        ops_runs._recover(ctx)
        assert lock_files(world) == {f"task-{one}.lock", f"task-{three}.lock"}  # the cancelled one went; the held one stays
    finally:
        os.close(held_fd)
    ops_runs._recover(ctx)
    assert lock_files(world) == {f"task-{three}.lock"}  # the live task's file stays


def test_a_task_released_by_the_person_loses_its_lock_file_at_the_next_round(world, monkeypatch):
    Lab(monkeypatch).release.set()
    request = planned(world, "w-pair")
    task_id = by_skill(world, "demo-writes", request)["id"]
    assert ops.run_task(world["path"], task_id)["ran"] is not None
    assert f"task-{task_id}.lock" in lock_files(world)  # it waits for the person: it may run again, the file stays
    review = [p for p in ops.pending(world["path"])["pending"] if p["kind"] == "review"][0]
    ops.release(world["path"], review["id"])
    assert by_skill(world, "demo-writes", request)["state"] == "done"
    ops.dispatch(world["path"], wait=False)
    assert f"task-{task_id}.lock" not in lock_files(world)


def test_a_lock_taken_on_a_file_that_was_deleted_meanwhile_is_not_a_lock(world, monkeypatch):
    cfg = ops_core.context(world["path"])["cfg"]
    os.close(ops_core._try_lock(cfg, "task-90.lock"))
    path = os.path.join(cfg["data_dir"], "locks", "task-90.lock")
    real, calls = ops_core.fcntl.flock, []

    def flock(fd, how):
        if not calls:  # the holder deletes the file between our open and our lock
            calls.append(1)
            os.unlink(path)
        return real(fd, how)

    monkeypatch.setattr(ops_core.fcntl, "flock", flock)
    fd = ops_core._try_lock(cfg, "task-90.lock")
    assert fd is not None and os.fstat(fd).st_ino == os.stat(path).st_ino
    os.close(fd)

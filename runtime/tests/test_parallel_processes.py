"""Tests of the dispatcher with real processes (PAR-4 review): the children are real `cli.py run-task` processes of this
checkout, kept from ever claiming by a lock the test holds (the claim lock) or made to refuse (their task is cancelled
meanwhile), so no model, no container and no task run is made. Every wait has a timeout, and every process the test
started is ended in a `finally`, so a failure cannot hang.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_parallel_processes.py
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

import pytest

import standin_tree as st

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_runs = st.load("ops_runs")

REPO = str(st.REPO)
SOON = "could not start, tried again shortly"


@pytest.fixture
def real(tmp_path, monkeypatch):
    """A project on this checkout with two floors and three ready tasks of real skills; the round's credential and image
    checks are answered (no model is called)."""
    project, data = tmp_path / "project", tmp_path / "data"
    (project / "docs" / "workbench").mkdir(parents=True)
    (project / "docs" / "workbench" / "state.md").write_text("# Workbench state\n", encoding="utf-8")
    agents = {name: {"pack": name, "mode": "autonomous", "max_runs_per_day": 50, "max_usd_per_day": 5.0, "max_parallel": 1}
              for name in ("business", "brand")}
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps({
        "workbench": REPO, "data_dir": str(data), "store_db": str(tmp_path / "store" / "tasks.sqlite"),
        "sources_dir": str(tmp_path / "sources"), "area_agents": agents, "max_running": 3}), encoding="utf-8")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    store, conn = ctx["store"], ctx["conn"]
    made = store.request_add(conn, title="Two jobs", text="Do two jobs.", flow="x", tasks=[
        {"key": "a", "skill": "biz-market-analysis", "title": "A", "text": "do a.", "agent": "business"},
        {"key": "b", "skill": "brand-voice", "title": "B", "text": "do b.", "agent": "brand"},
        {"key": "c", "skill": "biz-icp-positioning", "title": "C", "text": "do c.", "agent": "business"},
        {"key": "d", "skill": "brand-voice", "title": "D", "text": "do d.", "agent": "brand", "depends_on": ["b"]}])
    ids = {t["key"]: t["id"] for t in made["tasks"]}
    for name in model_variables():  # nothing a child inherits can reach a model, whatever the admission does
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep)
                                               if p and not os.path.exists(os.path.join(p, "docker"))))
    assert_cannot_reach_a_model(os.environ)
    monkeypatch.setattr(ops, "_credential_stop", lambda model=None: None)
    monkeypatch.setattr(ops, "_image_stop", lambda: None)
    monkeypatch.setattr(ops_runs, "SPAWNED", [])
    monkeypatch.setattr(ops_runs, "STOPPING", threading.Event())
    started = []
    yield {"path": path, "ctx": ctx, "cfg": ctx["cfg"], "ids": ids, "started": started, "tmp": tmp_path}
    for _where, _task, proc in list(ops_runs.SPAWNED):
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def model_variables() -> list:
    """Every variable the lab passes to a model's provider, for each model of the gate file, and the runtime's own key for it."""
    lab, core = st.load("lab"), st.load("ops_core")
    names = set()
    for model in lab.models():
        for variable in lab.reference(model)["pass_env"]:
            names |= {variable, core.own_key_name(variable)}
    return sorted(names)


def assert_cannot_reach_a_model(env) -> None:
    assert not [n for n in model_variables() if n in env], "a variable of a model's provider is in the environment"
    assert not any(os.path.exists(os.path.join(p, "docker")) for p in env.get("PATH", "").split(os.pathsep) if p), "docker is on PATH"


def until(condition, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def owner_of(real, task_id):
    return ops_core._lock_owner(real["cfg"], task_id)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


# --- a: real children --------------------------------------------------------------------------------------------------------


def test_real_children_hold_their_task_locks_with_their_pids_and_a_waiting_round_returns_after_they_exit(real):
    ids = real["ids"]
    assert_cannot_reach_a_model(os.environ)  # the children inherit it
    blocker = ops_core._try_lock(real["cfg"], "claim.lock")  # the children wait for the claim lock: they never claim
    result = {}
    try:
        runner = threading.Thread(target=lambda: result.update(out=ops.dispatch(real["path"], wait=True)), daemon=True)
        runner.start()
        until(lambda: len(ops_runs.SPAWNED) == 2, 60, "two children")
        children = {task: proc for _where, task, proc in list(ops_runs.SPAWNED)}
        assert sorted(children) == sorted([ids["a"], ids["b"]])
        for task, proc in children.items():
            until(lambda task=task, proc=proc: (owner_of(real, task) or (0, 0))[0] == proc.pid, 60, f"task {task}'s lock to carry its child's pid")
            assert owner_of(real, task) == (proc.pid, proc.pid)  # a child leads its own group
        # the tasks are cancelled meanwhile: when the claim lock is let go the children find them not ready and refuse
        store = real["ctx"]["store"]
        store.request_cancel(real["ctx"]["conn"], store.task_get(real["ctx"]["conn"], ids["a"])["parent_id"], by="user")
        os.close(blocker)
        blocker = None
        runner.join(60)
        assert not runner.is_alive() and all(proc.poll() is not None for proc in children.values())
        for proc in children.values():
            assert proc.returncode == ops_runs.EXIT_REFUSED
        recorded = json.loads(store.cursor_get(real["ctx"]["conn"], ops_runs.REFUSED_CURSOR))
        assert {int(k) for k in recorded} == set(children) and all(v["reason"] == "refused" for v in recorded.values())
        assert ops_core._lock_owner(real["cfg"], ids["a"]) is None  # emptied when the child let go
    finally:
        if blocker is not None:
            os.close(blocker)


# --- b: a signal on a waiting round ---------------------------------------------------------------------------------------------

ROUND = """
import json, sys, threading, time
sys.path.insert(0, %(runtime)r)
import ops, ops_runs
ops._credential_stop = lambda model=None: None
ops._image_stop = lambda: None
def watch():
    while len(ops_runs.SPAWNED) < 2:
        time.sleep(0.05)
    print("PIDS " + json.dumps([p.pid for _w, _t, p in ops_runs.SPAWNED]), flush=True)
threading.Thread(target=watch, daemon=True).start()
out = ops.dispatch(%(project)r, wait=True)
print("DONE " + json.dumps(out["stopped"]), flush=True)
"""


def test_a_waiting_round_that_gets_sigint_leaves_no_child_behind(real):
    blocker = ops_core._try_lock(real["cfg"], "claim.lock")
    assert_cannot_reach_a_model(os.environ)  # the round's process, and so its children, inherit this environment
    process = subprocess.Popen([sys.executable, "-c", ROUND % {"runtime": os.path.join(REPO, "runtime"), "project": real["path"]}],
                               stdout=subprocess.PIPE, text=True, env=dict(os.environ))
    pids = []
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            line = process.stdout.readline()
            if line.startswith("PIDS "):
                pids = json.loads(line[5:])
                break
            if not line and process.poll() is not None:
                break
        assert len(pids) == 2 and all(alive(p) for p in pids)
        process.send_signal(signal.SIGINT)
        process.wait(60)
        for pid in pids:
            until(lambda pid=pid: not alive(pid), 30, f"child {pid} to be gone")
    finally:
        if process.poll() is None:  # the round and every child first, the claim lock last: a child that gets it would claim
            process.kill()
            process.wait()
        for pid in pids:
            if alive(pid):
                os.kill(pid, signal.SIGKILL)
        os.close(blocker)


# --- c: a refusal ------------------------------------------------------------------------------------------------------------------


def test_run_task_on_a_planned_task_exits_4_and_a_held_child_is_held_retry_soon_by_the_next_round(real, monkeypatch):
    ids, cli = real["ids"], os.path.join(REPO, "runtime", "cli.py")
    assert_cannot_reach_a_model(os.environ)  # the CLI process and the child of the round inherit it
    done = subprocess.run([sys.executable, cli, "run-task", "--project", real["path"], "--task", str(ids["d"])],
                          capture_output=True, text=True, timeout=90)
    assert done.returncode == 4 and json.loads(done.stdout)["ran"] is None  # d depends on b: planned, not ready
    # a child that finds a held word under the claim lock exits 0 and leaves its task ready: the next round must not start it again
    store, conn = real["ctx"]["store"], real["ctx"]["conn"]
    config = os.path.join(real["path"], "docs", "workbench", "runtime.json")
    raw = json.loads(open(config, encoding="utf-8").read())
    raw["max_running"] = 1
    open(config, "w", encoding="utf-8").write(json.dumps(raw))
    ops.accept_config(real["path"], ops.project_config.load(real["path"])["sha256"])
    blocker = ops_core._try_lock(real["cfg"], "claim.lock")
    elsewhere = None
    try:
        out = ops.dispatch(real["path"], wait=False)  # nothing runs yet: both tasks of the first two floors... one slot of the project
        started = [s["task_id"] for s in out["started"]]
        assert started == [ids["a"]]
        child = next(proc for _w, task, proc in ops_runs.SPAWNED if task == ids["a"])
        until(lambda: (owner_of(real, ids["a"]) or (0, 0))[0] == child.pid, 60, "the child to hold its lock")
        store.task_claim(conn, ids["c"])  # another task runs now, and its process is alive
        elsewhere = ops_core._try_lock(real["cfg"], f"task-{ids['c']}.lock")
        os.close(blocker)
        blocker = None
        until(lambda: child.poll() is not None, 90, "the child to exit")
        assert child.returncode == 0  # held: the project is full
        again = ops.dispatch(real["path"], wait=False)  # reaps, records, and holds
        assert again["started"] == []
        assert {h["task_id"]: h["reason"] for h in ops.status(real["path"])["held"]}[ids["a"]] == SOON
    finally:
        if blocker is not None:
            os.close(blocker)
        if elsewhere is not None:
            os.close(elsewhere)


# --- d: the environment of a real child ----------------------------------------------------------------------------------------------


def test_a_real_child_does_not_see_a_key_a_router_call_injected(real, monkeypatch, tmp_path):
    dump = tmp_path / "env.json"
    real_popen = subprocess.Popen

    def printing(argv, **kwargs):  # the child is a stand-in that writes its environment, with the environment spawn built
        code = "import json, os, sys; json.dump(dict(os.environ), open(sys.argv[1], 'w'))"
        return real_popen([sys.executable, "-c", code, str(dump)], **kwargs)

    monkeypatch.setattr(ops_runs.subprocess, "Popen", printing)
    monkeypatch.setenv("EXPORTED_BY_THE_PERSON", "kept")
    monkeypatch.setenv("INJECTED_BY_A_ROUTER_CALL", "secret")
    monkeypatch.setitem(ops_core.ENV_INJECTED, "INJECTED_BY_A_ROUTER_CALL", None)
    proc = ops_runs.spawn(real["cfg"], real["path"], real["ids"]["a"])
    try:
        until(lambda: proc.poll() is not None, 60, "the stand-in child to exit")
        seen = json.loads(dump.read_text(encoding="utf-8"))
    finally:
        if proc.poll() is None:
            proc.kill()
    assert_cannot_reach_a_model(seen)  # what the child got
    assert seen["EXPORTED_BY_THE_PERSON"] == "kept" and "INJECTED_BY_A_ROUTER_CALL" not in seen
    assert os.environ["INJECTED_BY_A_ROUTER_CALL"] == "secret"  # the parent's own environment is untouched

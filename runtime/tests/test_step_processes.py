"""Tests of the step task with real processes (P5): a child that runs a step task holds the task's lock; a child that is killed is
detected by its lock and the task ends `failed`, never left `running`; `stop-runs --all` ends a running step (the child turns the TERM
into a clean end of the task); the dispatcher starts a step task as a real `cli.py run-step` process; and `run-step` exits as `run-task`
does. A kind that sleeps stands in for a long step: a small driver script registers it in the child and calls the real run_step. No
model, no container, no network; every wait has a timeout and every process is ended in a `finally`.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_processes.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import pytest

import standin_tree as st

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_runs = st.load("ops_runs")
steps = st.load("steps")

REPO = str(st.REPO)

DRIVER = '''\
import os, sys, time
sys.path.insert(0, os.path.join({repo!r}, "runtime"))
import steps
import ops_steps


def sleepy(ctx, state):
    with open({ready!r}, "w") as f:       # the step has begun
        f.write("up")
    time.sleep(600)
    return {{}}


steps.register(steps.Kind(name="sleeper", order=("sleep", "after"), executors={{"sleep": sleepy, "after": lambda c, s: {{"done": True}}}}))
print(ops_steps.run_step({project!r}, int(sys.argv[1])))
'''


@pytest.fixture
def real(tmp_path, monkeypatch):
    """A project on this checkout (no area agent), a step task of a kind that sleeps, and the driver that runs it in a child."""
    project = tmp_path / "project"
    (project / "docs" / "workbench").mkdir(parents=True)
    (project / "docs" / "workbench" / "state.md").write_text("# Workbench state\n", encoding="utf-8")
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps({
        "workbench": REPO, "data_dir": str(tmp_path / "data"), "store_db": str(tmp_path / "store" / "tasks.sqlite"),
        "sources_dir": str(tmp_path / "sources")}), encoding="utf-8")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    made = ctx["store"].step_task_add(ctx["conn"], key="sleepy", title="Sleep", text="Sleeps.", step="sleeper")
    ready = tmp_path / "ready"
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER.format(repo=REPO, ready=str(ready), project=path), encoding="utf-8")
    monkeypatch.setattr(ops_runs, "SPAWNED", [])
    monkeypatch.setattr(ops_runs, "STOPPING", threading.Event())
    children = []
    yield {"path": path, "ctx": ctx, "cfg": ctx["cfg"], "task": made["task"], "request": made["request"], "ready": ready,
           "driver": driver, "children": children, "tmp": tmp_path}
    for proc in children + [p for _w, _t, p in list(ops_runs.SPAWNED)]:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def start_child(real) -> subprocess.Popen:
    """The driver as a child in a session of its own, as the dispatcher starts a run (its pid is its group id)."""
    proc = subprocess.Popen([sys.executable, str(real["driver"]), str(real["task"])], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, start_new_session=True, text=True)
    real["children"].append(proc)
    return proc


def until(condition, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = condition()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def row(real):
    return real["ctx"]["store"].task_get(real["ctx"]["conn"], real["task"])


def lock_held(real) -> bool:
    fd = ops_core._try_lock(real["cfg"], f"task-{real['task']}.lock")
    if fd is None:
        return True
    os.close(fd)
    return False


def running(real):
    """The child has begun the step: the task is running and its lock is held by a live process."""
    return real["ready"].exists() and row(real)["state"] == "running" and lock_held(real)


def test_a_child_that_runs_a_step_holds_the_tasks_lock_with_its_pid_and_group_and_the_task_is_running(real):
    child = start_child(real)
    until(lambda: running(real), 60, "the step to begin")
    owner = ops_core._lock_owner(real["cfg"], real["task"])
    assert owner == (child.pid, child.pid)                  # a session leader: its pid is its group
    held = row(real)
    assert held["state"] == "running" and held["agent"] == "runtime" and real["ctx"]["store"].task_runs_list(real["ctx"]["conn"], real["task"]) == []
    assert [h["id"] for h in real["ctx"]["store"].task_slot_holders(real["ctx"]["conn"])] == [real["task"]]
    child.kill()
    child.wait(timeout=30)


def test_a_killed_child_is_detected_by_its_lock_and_the_task_is_failed_not_left_running(real):
    child = start_child(real)
    until(lambda: running(real), 60, "the step to begin")
    child.kill()                                             # nothing of the child's own runs: no clean end
    child.wait(timeout=30)
    assert row(real)["state"] == "running"                   # the store has not been told
    assert lock_held(real) is False                          # but nobody holds the lock: the proof the task is dead
    recovered = ops_runs._recover(real["ctx"])
    assert recovered["tasks"] == [real["task"]]
    after = row(real)
    assert after["state"] == "failed" and after["note"] == ops_runs.ORPHAN_NOTE
    assert after["step_state"] is None or after["step_state"].get("failure") is None
    assert ops_runs._recover(real["ctx"]) == {"tasks": [], "runs": []}      # once


def test_run_next_and_a_dispatch_end_a_killed_step_before_they_decide_anything(real):
    child = start_child(real)
    until(lambda: running(real), 60, "the step to begin")
    child.kill()
    child.wait(timeout=30)
    out = ops.run_next(real["path"])
    assert out["ran"] is None and out["recovered"] == [real["task"]]
    assert row(real)["state"] == "failed"
    assert real["ctx"]["store"].task_retry(real["ctx"]["conn"], real["task"])["state"] == "ready"


def test_stop_runs_all_ends_a_running_step_and_the_task_is_failed_with_the_note_that_says_it_was_stopped(real):
    child = start_child(real)
    until(lambda: running(real), 60, "the step to begin")
    out = ops.stop_runs(real["path"], every=True)
    assert out["tasks"] == [real["task"]]
    child.wait(timeout=60)                                   # the TERM ended it
    assert child.returncode is not None
    ended = row(real)
    assert ended["state"] == "failed" and ended["note"] == "stopped: the run was ended by stop-runs; retry the task"
    assert lock_held(real) is False
    assert ops.run_next(real["path"])["ran"] is None         # nothing is left to recover or to run
    assert real["ctx"]["store"].task_retry(real["ctx"]["conn"], real["task"])["state"] == "ready"


def test_the_dispatcher_starts_ready_step_tasks_as_real_run_step_processes_and_each_ends_its_task(real):
    ctx = real["ctx"]
    made = ctx["store"].step_task_add(ctx["conn"], key="ingest-late", title="Ingest", text="Ingest.", step="ingest",
                                      args={"source": "late", "file": str(real["tmp"] / "never.csv")})
    out = ops.dispatch(real["path"])                           # waits for its children; no area agent is configured
    assert sorted(s["task_id"] for s in out["started"]) == sorted([real["task"], made["task"]])
    ingest = ctx["store"].task_get(ctx["conn"], made["task"])
    assert ingest["state"] == "failed" and ingest["note"].startswith("ingest: usage source")
    assert ingest["step_state"]["failure"]["code"] == "usage" and ingest["step_state"]["failure"]["step"] == "ingest"
    unknown = row(real)        # the child is a fresh process of this checkout: the kind the driver registered is not in it
    assert unknown["state"] == "failed" and unknown["note"] == "start: unknown_kind step"
    assert [t for _w, t, p in ops_runs.SPAWNED if p.poll() is None] == []


def test_run_step_on_the_terminal_prints_the_engines_result_and_exits_like_run_task(real):
    ctx = real["ctx"]
    cli = [sys.executable, os.path.join(REPO, "runtime", "cli.py")]
    refused = subprocess.run(cli + ["run-step", "--project", real["path"], "--task", "9999"], capture_output=True, text=True, timeout=120)
    assert refused.returncode == 4 and json.loads(refused.stdout)["ran"] is None
    made = ctx["store"].step_task_add(ctx["conn"], key="ingest-late", title="Ingest", text="Ingest.", step="ingest",
                                      args={"source": "late", "file": str(real["tmp"] / "never.csv")}, request_id=real["request"])
    done = subprocess.run(cli + ["run-step", "--project", real["path"], "--task", str(made["task"])], capture_output=True, text=True, timeout=120)
    out = json.loads(done.stdout)
    assert done.returncode == 0 and out["ran"] == made["task"] and out["ok"] is False and out["code"] == "usage" and out["task_state"] == "failed"
    held = ctx["store"].step_task_add(ctx["conn"], key="held", title="Held", text="Held.", step="ingest", args={"source": "late"},
                                      request_id=real["request"], depends_on=["ingest-late"])
    waiting = subprocess.run(cli + ["run-step", "--project", real["path"], "--task", str(held["task"])], capture_output=True, text=True, timeout=120)
    assert waiting.returncode == 4 and "no task is ready" in json.loads(waiting.stdout)["reason"]
    skill = ctx["store"].request_add(ctx["conn"], title="S", text="Skill.", flow="f", tasks=[
        {"key": "market", "skill": "biz-market-analysis", "title": "M", "text": "x"}])["tasks"][0]["id"]
    wrong = subprocess.run(cli + ["run-step", "--project", real["path"], "--task", str(skill)], capture_output=True, text=True, timeout=120)
    assert wrong.returncode == 4 and "not a step task" in json.loads(wrong.stdout)["reason"]

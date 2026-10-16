"""R18: cancel a request or stop a task at any moment, even while a run is in progress (limit L41). Offline, no model, no real container:

  - the holders of the task locks are real child processes that sleep (and one that ignores TERM), started by this test, which ends
    every one in a `finally`; the lock is the one a real run-task takes, with "<pid> <pgid>" in it;
  - the container tool is a FAKE (the names of the lab's objects, as runtime/orphans.py knows them): no docker is run, and no real
    container is named or touched;
  - the router's run is the stand-in router of the chat tree, in a thread, stopped from another thread through the watcher.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_cancel_running.py
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
from test_task_ops import tree as task_tree  # noqa: F401  (the stand-in project of the task runtime)

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_cancel = st.load("ops_cancel")
run_stop = st.load("run_stop")
orphans = st.load("orphans")
autonomy = st.load("autonomy")
board = st.load("board")
operations = st.load("operations")

REPO = str(st.REPO)
RUN = "0123456789abcdef"
TAG = "a1b2c3d4e5f6"

HOLDER = r'''
import fcntl, os, signal, subprocess, sys, time
fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o600)
fcntl.flock(fd, fcntl.LOCK_EX)
os.ftruncate(fd, 0)
os.write(fd, ("%d %d\n" % (os.getpid(), os.getpgrp())).encode())
if sys.argv[2] == "ignore":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
for name in sys.argv[3:]:
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "--name", name])
print("ready", flush=True)
time.sleep(120)
'''


class FakeDocker:
    """A container client that knows a list of containers and networks and records every command it is given."""

    def __init__(self, containers=(), networks=()):
        self.containers, self.networks, self.calls = list(containers), list(networks), []

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "ps":
            return 0, "\n".join(json.dumps({"Names": n, "Labels": "wb.eval=1", "CreatedAt": "2027-01-15 07:00:00 +0000 UTC", "State": "running"})
                                for n in self.containers)
        if args[:2] == ("network", "ls"):
            return 0, "\n".join(json.dumps({"Name": n, "Labels": "wb.eval=1", "CreatedAt": "2027-01-15 07:00:00 +0000 UTC"}) for n in self.networks)
        if args[0] == "rm":
            self.containers.remove(args[-1])
            return 0, ""
        if args[:2] == ("network", "rm"):
            self.networks.remove(args[-1])
            return 0, ""
        raise AssertionError(f"the stop ran a command it should not: {args}")

    @property
    def removals(self):
        return [c for c in self.calls if c[0] == "rm" or c[:2] == ("network", "rm")]


@pytest.fixture
def real(tmp_path, monkeypatch):
    """A project on this checkout (the store, the locks, the configuration accepted) and the children the test started."""
    project, data = tmp_path / "project", tmp_path / "data"
    (project / "docs" / "workbench").mkdir(parents=True)
    (project / "docs" / "workbench" / "state.md").write_text("# Workbench state\n", encoding="utf-8")
    (project / "docs" / "workbench" / "runtime.json").write_text(json.dumps({
        "workbench": REPO, "data_dir": str(data), "store_db": str(tmp_path / "store" / "tasks.sqlite"),
        "sources_dir": str(tmp_path / "sources"), "area_agents": {}}), encoding="utf-8")
    path = str(project)
    ops.accept_config(path, ops.project_config.load(path)["sha256"])
    ctx = ops_core.context(path)
    children = []
    # no stop of this file may reach a real container tool, whatever happens
    boom = FakeDocker()
    monkeypatch.setattr(lab, "container_tool", boom)
    yield {"path": path, "ctx": ctx, "cfg": ctx["cfg"], "store": ctx["store"], "conn": ctx["conn"], "children": children, "docker": boom,
           "tmp": tmp_path}
    for proc in children:
        for pid in (proc.pid,):
            for kill in (lambda: os.killpg(pid, signal.SIGKILL), lambda: os.kill(pid, signal.SIGKILL)):
                try:
                    kill()
                except (ProcessLookupError, PermissionError):
                    pass
        proc.wait()


def make_request(real, count=2):
    store, conn = real["store"], real["conn"]
    tasks = [{"key": "a", "skill": "biz-market-analysis", "title": "A", "text": "do a."},
             {"key": "b", "skill": "biz-icp-positioning", "title": "B", "text": "do b.", "depends_on": ["a"]}][:count]
    made = store.request_add(real["conn"], title="Two jobs", text="Do two jobs.", flow="x", tasks=tasks)
    return made["request"], {t["key"]: t["id"] for t in made["tasks"]}


def running(real, task_id, tokens=100, cost=0.01):
    """The task claimed and its run row open, with the usage the run's folder reports."""
    store, conn = real["store"], real["conn"]
    assert store.task_claim(conn, task_id)["task"]["state"] == "running"
    run = store.task_run_start(conn, task_id, skill="biz-market-analysis", model="m", adapter="h", billing="metered")["run_id"]
    folder = os.path.join(real["cfg"]["data_dir"], ops_core.RUNS_DIR, str(run), "outputs")
    os.makedirs(folder)
    with open(os.path.join(folder, "timing.json"), "w", encoding="utf-8") as f:
        json.dump({"total_tokens": tokens, "cost_usd": cost}, f)
    return run


def holder(real, task_id, mode="obey", names=()):
    """A child that holds the task's lock as a run-task does, leads its own group, and (names) has a child whose command line names
    objects of the lab. Returns the process once it said it is ready."""
    path = os.path.join(ops_core._locks_dir(real["cfg"]), f"task-{task_id}.lock")
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, path, mode, *names], stdout=subprocess.PIPE, text=True, start_new_session=True)
    real["children"].append(proc)
    assert proc.stdout.readline().strip() == "ready"
    return proc


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie is not alive
        return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()[:1] not in ("", "Z")
    except OSError:
        return True


def until(condition, seconds=20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        found = condition()
        if found:
            return found
        time.sleep(0.05)
    raise AssertionError("the condition did not hold in time")


# --- a running task run is stopped by cancel -------------------------------------------------------------------------------


def test_cancel_ends_a_running_task_run_records_it_cancelled_with_its_usage_and_the_caps_count_it(real):
    rid, ids = make_request(real)
    run = running(real, ids["a"])
    child = holder(real, ids["a"])
    out = ops.cancel(real["path"], rid, channel="page")
    assert out["request"] == rid and out["already"] is False and out["stopped"] == [{"task": ids["a"], "run": run, "state": "cancelled"}]
    assert sorted(out["cancelled"]) == sorted([rid, *ids.values()])
    until(lambda: child.poll() is not None)
    store, conn = real["store"], real["conn"]
    row = store.task_run_get(conn, run)
    assert (row["status"], row["failure"], row["ending"]) == ("cancelled", None, None)
    assert row["error"] == "cancelled by user from page" and row["tokens"] == 100 and row["cost_usd"] == 0.01
    assert {t["state"] for t in store.tasks_list(conn, rid)} == {"cancelled"}
    assert not autonomy.never_reached_the_model(row), "a cancelled run may have spent: it keeps its place in the caps"
    assert autonomy.never_reached_the_model({**row, "cost_usd": None, "tokens": None, "attempts": 0}) is False
    assert real["docker"].calls == [], "no snapshot named a lab run: the container tool was not asked"
    assert ops.cancel(real["path"], rid)["already"] is True


def test_a_child_that_ignores_term_is_killed_after_the_grace_and_a_second_cancel_says_already(real, monkeypatch):
    monkeypatch.setattr(run_stop, "STOP_GRACE", 0.6)
    rid, ids = make_request(real, 1)
    running(real, ids["a"])
    child = holder(real, ids["a"], "ignore")
    began = time.monotonic()
    out = ops.cancel(real["path"], rid)
    assert time.monotonic() - began >= 0.6 and out["stopped"][0]["state"] == "cancelled"
    until(lambda: child.poll() is not None)
    assert child.returncode == -signal.SIGKILL, "TERM was ignored: the same holder got KILL"
    assert real["store"].task_get(real["conn"], rid)["state"] == "cancelled"
    assert ops.cancel(real["path"], rid) == {**ops.cancel(real["path"], rid), "already": True, "cancelled": [], "stopped": [], "pending": []}


def test_a_stale_lock_is_never_signalled(real):
    rid, ids = make_request(real, 1)
    running(real, ids["a"])
    innocent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    real["children"].append(innocent)
    path = os.path.join(ops_core._locks_dir(real["cfg"]), f"task-{ids['a']}.lock")
    with open(path, "w", encoding="ascii") as f:   # the holder died and left its text: nobody holds the lock
        f.write(f"{innocent.pid} {innocent.pid}\n")
    out = ops.cancel(real["path"], rid)
    assert out["stopped"] == [{"task": ids["a"], "run": 1, "state": "cancelled"}]
    time.sleep(0.3)
    assert innocent.poll() is None and alive(innocent.pid), "a lock nobody holds is never signalled"
    assert real["store"].task_run_get(real["conn"], 1)["status"] == "cancelled"


def test_the_run_container_key_proxy_and_network_the_snapshot_named_are_removed_after_a_kill_and_a_shared_name_is_never_touched(real, monkeypatch):
    monkeypatch.setattr(run_stop, "STOP_GRACE", 0.6)
    fake = FakeDocker(containers=[f"wb-eval-run-{RUN}", f"wb-eval-keys-{RUN}", f"wb-eval-keys-{TAG}", f"wb-eval-proxy-{TAG}",
                                  "wb-eval-run-fedcba9876543210"],
                      networks=[f"wb-eval-held-{RUN}", f"wb-eval-net-{TAG}"])
    monkeypatch.setattr(lab, "container_tool", fake)
    rid, ids = make_request(real, 1)
    running(real, ids["a"])
    child = holder(real, ids["a"], "ignore", names=[f"wb-eval-run-{RUN}", f"wb-eval-keys-{RUN}", f"wb-eval-held-{RUN}", f"wb-eval-keys-{TAG}"])
    shot = run_stop.snapshot(child.pid)
    assert shot["runs"] == [RUN] and len(shot["pids"]) == 4          # the shared holder's tag is 12 characters: it is no run's name
    ops.cancel(real["path"], rid)
    until(lambda: child.poll() is not None)
    assert sorted(fake.removals) == sorted([("rm", "-f", f"wb-eval-run-{RUN}"), ("rm", "-f", f"wb-eval-keys-{RUN}"),
                                            ("network", "rm", f"wb-eval-held-{RUN}")])
    assert fake.removals[-1] == ("network", "rm", f"wb-eval-held-{RUN}"), "the network goes after the containers on it"
    assert sorted(fake.containers) == sorted([f"wb-eval-keys-{TAG}", f"wb-eval-proxy-{TAG}", "wb-eval-run-fedcba9876543210"])
    assert sorted(fake.networks) == [f"wb-eval-net-{TAG}"]
    assert all(c[0] in ("ps", "rm", "network") for c in fake.calls)


def test_the_sweep_checks_for_a_shared_object_again_just_before_removing_it():
    fake = FakeDocker(containers=[f"wb-eval-keys-{TAG}"])
    # a name that is a run's own by the listing but shared by the rule is never removed (the listing already leaves it out)
    assert orphans.remove_runs(fake, [RUN])["removed"] == [] and fake.removals == []
    assert orphans.remove_runs(fake, ["nothex"]) == {"removed": [], "kept": [], "problem": None}


def test_a_holder_this_process_cannot_signal_is_reported_stopping_and_its_rows_are_left_to_it(real, monkeypatch):
    monkeypatch.setattr(run_stop, "STOP_GRACE", 0.3)
    rid, ids = make_request(real, 1)
    run = running(real, ids["a"])
    fd = ops_core._try_lock(real["cfg"], f"task-{ids['a']}.lock")     # this process holds the lock: it is never signalled
    try:
        os.write(fd, f"{os.getpid()} {os.getpgrp()}\n".encode("ascii"))
        out = ops.cancel(real["path"], rid)
    finally:
        os.close(fd)
    assert out["stopped"] == [{"task": ids["a"], "run": run, "state": "stopping"}]
    assert real["store"].task_run_get(real["conn"], run)["status"] == "running"
    assert real["store"].task_get(real["conn"], rid)["state"] == "planned"        # the request keeps its stop request until the run ends
    assert ops.cancel(real["path"], rid)["already"] is True


# --- stop-task --------------------------------------------------------------------------------------------------------------


def test_stop_task_blocks_the_task_keeps_the_dependents_planned_and_retry_makes_it_ready(real):
    rid, ids = make_request(real)
    run = running(real, ids["a"])
    child = holder(real, ids["a"])
    out = ops.stop_task(real["path"], ids["a"], channel="terminal")
    assert out["request"] == rid and out["already"] is False and out["cancelled"] == []
    assert out["stopped"] == [{"task": ids["a"], "run": run, "state": "cancelled"}]
    until(lambda: child.poll() is not None)
    store, conn = real["store"], real["conn"]
    task = store.task_get(conn, ids["a"])
    assert task["state"] == "blocked" and task["note"] == "stopped by user from terminal: retry it or cancel the request"
    assert store.task_run_get(conn, run)["status"] == "cancelled" and store.task_get(conn, ids["b"])["state"] == "planned"
    assert store.task_get(conn, rid)["state"] == "planned"
    assert ops.stop_task(real["path"], ids["a"])["already"] is True
    assert ops.retry(real["path"], ids["a"])["state"] == "ready"
    assert store.task_get(conn, ids["a"])["stop_requested_at"] is None
    with pytest.raises(ops.OpsError, match="only a running task is stopped"):
        ops.stop_task(real["path"], ids["b"])


# --- the races, and limit L41 ---------------------------------------------------------------------------------------------


def test_limit_41_a_cancel_while_an_effect_of_the_request_executes_signals_nothing_and_writes_nothing(real, monkeypatch):
    monkeypatch.setattr(ops_core, "ROUTE_LOCK_WAIT", 0.3)
    rid, ids = make_request(real, 1)
    run = running(real, ids["a"])
    child = holder(real, ids["a"])
    fd = ops_core._try_lock(real["cfg"], f"effect-{rid}.lock")      # an approved effect is executing: it holds this lock
    try:
        with pytest.raises(ops.OpsError, match=f"an effect of request {rid} is executing; nothing was stopped; cancel again when it ends"):
            ops.cancel(real["path"], rid)
        with pytest.raises(ops.OpsError, match="nothing was stopped"):
            ops.stop_task(real["path"], ids["a"])
        time.sleep(0.2)
        assert child.poll() is None and alive(child.pid), "no process was signalled"
        store, conn = real["store"], real["conn"]
        assert store.task_get(conn, rid)["stop_requested_at"] is None and store.task_get(conn, ids["a"])["stop_requested_at"] is None
        assert store.task_run_get(conn, run)["status"] == "running" and store.task_get(conn, ids["a"])["state"] == "running"
    finally:
        os.close(fd)
    assert ops.cancel(real["path"], rid)["request"] == rid                   # when the effect ends, the cancel goes through
    until(lambda: child.poll() is not None)


def test_limit_41_a_stopped_run_returns_nothing_it_made_and_opens_nothing(task_tree, monkeypatch):
    """A run whose request is cancelled while the model works: the lab returns files, and none of them reaches the project."""
    tree = task_tree
    path = str(tree["project"])
    made = ops.request(path, "Tell me which market to go after first.", "demo")
    first = ops.run_next(path)
    ops.answer(path, first["pending_id"], "Portugal, remote.")          # the next run writes docs/business/market.md
    real_run = lab.run_skill
    monkeypatch.setattr(run_stop, "STOP_GRACE", 0.3)

    def stopped_meanwhile(*args, **kwargs):
        result = real_run(*args, **kwargs)
        ops.cancel(path, made["request"])                                # the person cancels from another process, while the run returns
        return result
    monkeypatch.setattr(lab, "run_skill", stopped_meanwhile)
    out = ops.run_next(path)
    assert out["status"] == "cancelled" and out["pending_id"] is None and out["returned"] == [] and out["task_state"] == "cancelled"
    assert not (tree["project"] / "docs" / "business" / "market.md").exists(), "a stopped run returns nothing"
    ctx = ops_core.context(path)
    row = ctx["store"].task_run_get(ctx["conn"], out["run_id"])
    assert row["status"] == "cancelled" and row["error"] == "cancelled by user" and row["tokens"] == 100
    assert ctx["store"].task_get(ctx["conn"], made["request"])["state"] == "cancelled"
    assert [p for p in ctx["store"].pending_list(ctx["conn"], "open")] == []


def test_a_run_that_finished_before_the_cancel_keeps_its_result_and_the_cancel_cancels_its_review(task_tree):
    path = str(task_tree["project"])
    made = ops.request(path, "Tell me which market to go after first.", "demo")
    first = ops.run_next(path)
    assert first["status"] == "ok" and first["pending_id"]
    out = ops.cancel(path, made["request"])
    assert out["pending"] == [first["pending_id"]] and out["stopped"] == []
    ctx = ops_core.context(path)
    assert ctx["store"].pending_get(ctx["conn"], first["pending_id"])["status"] == "cancelled"
    assert ctx["store"].task_run_get(ctx["conn"], first["run_id"])["status"] == "ok"


# --- the router's run ---------------------------------------------------------------------------------------------------


def test_a_dead_routers_row_is_finished_by_the_canceller(real):
    made = real["store"].request_add(real["conn"], title="Ask", text="Which market?")["request"]
    run = real["store"].route_run_start(real["conn"], made, skill="core-orchestrator", model="m", adapter="h", billing="metered")["run_id"]
    out = ops.cancel(real["path"], made)       # nobody holds the route lock: its owner is dead
    assert out["stopped"] == [{"run": run, "state": "cancelled"}] and out["cancelled"] == [made]
    row = real["store"].task_run_get(real["conn"], run)
    assert row["status"] == "cancelled" and row["error"] == "cancelled by user"


# --- who may cancel, and from where -------------------------------------------------------------------------------------------


def test_the_board_cancels_through_the_same_operation_and_stops_a_running_task(real):
    rid, ids = make_request(real, 1)
    run = running(real, ids["a"])
    child = holder(real, ids["a"])
    request = real["store"].task_get(real["conn"], rid)
    assert board._take_state(real["ctx"], request, "cancelled") is None
    until(lambda: child.poll() is not None)
    row = real["store"].task_run_get(real["conn"], run)
    assert row["status"] == "cancelled" and row["error"] == "cancelled by board"
    assert real["store"].task_get(real["conn"], rid)["state"] == "cancelled"


def test_messaging_can_cancel_and_stop_with_the_default_policy_and_the_mcp_mode_cannot(real):
    rid, ids = make_request(real)
    running(real, ids["a"])
    child = holder(real, ids["a"])
    mcp_reply = ops.say(real["path"], f"/stop-task {ids['a']}", channel="mcp")["reply"]
    assert "stop-task is done in the terminal or on the page" in mcp_reply
    assert "cancel is done in the terminal or on the page" in ops.say(real["path"], f"/cancel {rid}", channel="mcp")["reply"]
    assert child.poll() is None
    assert operations.permitted("stop-task", "messaging", None) and operations.permitted("cancel", "messaging", None)
    stopped = json.loads(ops.say(real["path"], f"/stop-task {ids['a']}", channel="messaging")["reply"])
    assert stopped["stopped"][0]["state"] == "cancelled"
    until(lambda: child.poll() is not None)
    assert real["store"].task_get(real["conn"], ids["a"])["state"] == "blocked"
    assert "mcp" not in operations.by_name("cancel")["channels"] and "mcp" not in operations.by_name("stop-task")["channels"]
    assert "stop-task" in operations.BRAKES and "cancel" in operations.BRAKES
    assert operations.permitted("stop-task", "page", {"page": ["read"]})


def test_cancel_and_stop_task_are_terminal_commands_with_the_flags_the_table_gives(real, tmp_path):
    rid, ids = make_request(real, 1)
    running(real, ids["a"])
    done = subprocess.run([sys.executable, str(st.RUNTIME / "cli.py"), "stop-task", "--project", real["path"], "--task", str(ids["a"])],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["stopped"] == [{"task": ids["a"], "run": 1, "state": "cancelled"}]
    done = subprocess.run([sys.executable, str(st.RUNTIME / "cli.py"), "cancel", "--project", real["path"], "--request", str(rid)],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and json.loads(done.stdout)["request"] == rid


# --- the watcher ----------------------------------------------------------------------------------------------------------------


def test_watch_ends_the_labs_runs_when_the_stop_request_is_set_and_never_before(real):
    rid, _ = make_request(real, 1)
    calls = []
    cfg, store = real["cfg"], real["store"]
    with run_stop.watch(real["ctx"], rid, poll=0.05, stop=lambda: calls.append(time.monotonic())):
        time.sleep(0.3)
        assert calls == []
        store.request_stop(real["conn"], rid, by="user")
        until(lambda: calls)
    assert len(calls) >= 1

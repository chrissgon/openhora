"""R4-L1 (A-51): a request that the router is working on says so in `status` and in the project list.

The router's run holds a row of `task_runs` whose task is the request; the request itself stays `requested` and no task
of the plan exists, so no read said a run was in progress and the page offered `Route it` again. `status` now carries
`routing` on each request: null, or {"run_id", "skill", "started_at"} while a run of the router holds that request, and
the project list carries `routing_request`, the number of that request or null. Offline, on the stand-in tree with a stand-in
router that waits for a file before it answers.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_routing_read.py
"""
from __future__ import annotations

import threading
import time
import types

import pytest

import standin_tree as st
from test_chat import FLOW, reply, tree as chat_tree  # noqa: F401  (the conversation's stand-in project)

kit = st.load("shell_kit")
ops = st.load("ops")
ops_core = st.load("ops_core")
ops_reads = st.load("ops_reads")
router = st.load("router")

WAIT = 'while [ ! -f "$here/release" ]; do sleep 0.05; done\n'


@pytest.fixture
def tree(chat_tree):
    """The chat tree whose stand-in router waits for the file `release` beside the adapter before it answers."""
    script = chat_tree["adapter"] / "run-prompt.sh"
    text = script.read_text(encoding="utf-8")
    assert text.count('  cp "$prompt" "$here/last-router-prompt.md"\n') == 1
    script.write_text(text.replace('  cp "$prompt" "$here/last-router-prompt.md"\n',
                                   '  cp "$prompt" "$here/last-router-prompt.md"\n  ' + WAIT, 1), encoding="utf-8")
    return chat_tree


def project(tree) -> str:
    return str(tree["project"])


def request_row(tree, request_id: int) -> dict:
    return next(r for r in ops.status(project(tree))["requests"] if r["id"] == request_id)


def routed_in_thread(tree, request_id: int) -> tuple:
    """Start ops.route in a thread; the thread and the list that receives its result or its error."""
    box: list = []

    def run():
        try:
            box.append(ops.route(project(tree), request_id))
        except Exception as e:  # noqa: BLE001  (the test reads it)
            box.append(e)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, box


def until(condition, seconds: float = 20.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = condition()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("the condition did not hold in time")


def release(tree) -> None:
    (tree["adapter"] / "release").write_text("go", encoding="utf-8")


# --- the discriminating experiment: a real router run in progress ----------------------------------------------------------


def test_while_the_router_works_on_a_request_status_says_so_and_the_request_and_its_tasks_say_nothing_else(tree):
    path = project(tree)
    other = ops.request(path, "Another invented request.", title="Other")["request"]
    made = ops.request(path, "Which market should the invented studio go after first?", title="Market")["request"]
    thread, box = routed_in_thread(tree, made)
    try:
        row = until(lambda: (r := request_row(tree, made))["routing"] and r)
        assert row["state"] == "requested" and row["tasks"] == [], "the cause: nothing but the run row says a run is in progress"
        assert set(row["routing"]) == {"run_id", "skill", "started_at"}
        assert row["routing"]["skill"] == router.ROUTER_SKILL and isinstance(row["routing"]["run_id"], int)
        assert row["routing"]["started_at"].endswith("Z") or "T" in row["routing"]["started_at"]
        assert request_row(tree, other)["routing"] is None, "only the request the run holds"
        listed = kit.Jobs(ops, [{"id": "1", "name": "invented", "path": path}]).projects_list()["projects"][0]
        assert listed["routing_request"] == made and listed["running_task"] is None
    finally:
        release(tree)
        thread.join(30)
    assert isinstance(box[0], dict) and box[0]["routed"] is True and box[0]["pending_id"]
    done = request_row(tree, made)
    assert done["routing"] is None and done["state"] == "requested", "the run ended: the plan card shows, not the routing line"
    assert kit.Jobs(ops, [{"id": "1", "name": "invented", "path": path}]).projects_list()["projects"][0]["routing_request"] is None


def test_the_runtime_refuses_to_cancel_or_route_again_while_the_router_works_so_the_page_offers_neither(tree):
    path = project(tree)
    made = ops.request(path, "Which market should the invented studio go after first?", title="Market")["request"]
    thread, box = routed_in_thread(tree, made)
    try:
        until(lambda: request_row(tree, made)["routing"])
        with pytest.raises(ops.OpsError, match="is running: wait for its run to end"):
            ops.cancel(path, made)
        with pytest.raises(ops_core.RunBusy):
            ops.route(path, made)
    finally:
        release(tree)
        thread.join(30)
    assert box[0]["routed"] is True


def test_a_router_run_that_failed_is_not_a_run_in_progress(tree):
    path = project(tree)
    made = ops.request(path, "Which market should the invented studio go after first?", title="Market")["request"]
    ctx = ops_core.context(path)
    store, conn = ctx["store"], ctx["conn"]
    run = store.route_run_start(conn, made, skill=router.ROUTER_SKILL, model="m", adapter="h")["run_id"]
    assert request_row(tree, made)["routing"]["run_id"] == run
    store.route_run_finish(conn, run, status="failed", failure="internal", error="stopped")
    assert request_row(tree, made)["routing"] is None


def test_a_run_of_a_task_of_a_plan_is_not_a_routing_run(tree):
    path = project(tree)
    release(tree)    # the router answers at once: this test needs its plan, not its run
    said = ops.say(path, "Which market should the invented studio go after first?")
    ops.approve(path, said["pending_id"])
    ctx = ops_core.context(path)
    store, conn = ctx["store"], ctx["conn"]
    task = store.task_claim(conn, conn.execute(store.NEXT_READY_TASK).fetchone()["id"])["task"]
    assert task is not None and task["parent_id"] == said["request_id"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")["run_id"]
    row = request_row(tree, said["request_id"])
    assert row["routing"] is None and any(t["state"] == "running" for t in row["tasks"])
    listed = kit.Jobs(ops, [{"id": "1", "name": "invented", "path": path}]).projects_list()["projects"][0]
    assert listed["running_task"] == task["id"] and listed["routing_request"] is None
    store.task_run_finish(conn, run, status="failed", task_state="failed", failure="internal", error="stopped")


def test_a_cancelled_request_never_has_a_run_and_a_task_run_matches_no_request():
    live = [{"id": 9, "task_id": 4, "skill": "r", "started_at": "t"}]
    ctx = {"conn": None, "store": types.SimpleNamespace(task_runs_running=lambda _conn: live, StoreError=Exception)}
    rows = ops_reads.with_routing(ctx, [{"id": 4, "state": "cancelled"}, {"id": 5, "state": "requested"}])
    assert [r["routing"] for r in rows] == [None, None], "a cancelled request has none; request 5 is not task 4's"
    live[0]["task_id"] = 5
    assert ops_reads.with_routing(ctx, [{"id": 5, "state": "requested"}])[0]["routing"] == {"run_id": 9, "skill": "r", "started_at": "t"}


def test_a_delivery_routed_again_marks_its_planned_request_as_routing(tree):
    path = project(tree)
    release(tree)
    said = ops.say(path, "Which market should the invented studio go after first?")
    ops.approve(path, said["pending_id"])
    request = said["request_id"]
    assert request_row(tree, request)["state"] == "planned" and request_row(tree, request)["routing"] is None
    ctx = ops_core.context(path)
    run = ctx["store"].route_run_start(ctx["conn"], request, skill=router.ROUTER_SKILL, model="m", adapter="h", reroute=True)["run_id"]
    row = request_row(tree, request)
    assert row["state"] == "planned" and row["routing"]["run_id"] == run, "the request keeps its state; the run is the one record"
    ctx["store"].route_run_finish(ctx["conn"], run, status="failed", failure="internal", error="stopped")
    assert request_row(tree, request)["routing"] is None


def count_task_run_reads(tree, requests: int) -> int:
    """How many statements on task_runs one `status` makes with this many requests."""
    path = project(tree)
    for n in range(requests):
        ops.request(path, f"Invented request number {n}.", title=f"R{n}")
    ctx = ops_core.context(path)
    seen: list = []
    ctx["conn"].set_trace_callback(lambda sql: seen.append(sql) if "task_runs" in sql else None)
    try:
        listed = ops_reads.with_routing(ctx, ops.status(path)["requests"])
    finally:
        ctx["conn"].set_trace_callback(None)
    assert len(listed) >= requests
    return len(seen)


def test_status_reads_the_live_run_once_whatever_the_number_of_requests(tree):
    one = count_task_run_reads(tree, 1)
    many = count_task_run_reads(tree, 8)
    assert one == many and one >= 1, f"the reads of task_runs do not grow with the requests: {one} for 1, {many} for 9"


# --- the shell's list, on a stand-in ----------------------------------------------------------------------------------------


class Stand(object):
    OpsError = ops.OpsError

    def __init__(self, requests):
        self.requests = requests

    def config(self, path):
        return {"sha256": "a" * 64, "accepted": 1}

    def status(self, path):
        return {"pending": [], "requests": self.requests}


def test_the_project_list_names_the_request_a_router_run_holds_and_null_when_none():
    held = [{"id": 4, "tasks": [], "routing": None}, {"id": 6, "tasks": [], "routing": {"run_id": 9, "skill": "r", "started_at": "t"}}]
    listed = kit.Jobs(Stand(held), [{"id": "1", "name": "p", "path": "/p"}]).projects_list()["projects"][0]
    assert listed["routing_request"] == 6 and listed["running_task"] is None
    none = kit.Jobs(Stand([{"id": 4, "tasks": []}]), [{"id": "1", "name": "p", "path": "/p"}]).projects_list()["projects"][0]
    assert none["routing_request"] is None, "a stand-in status with no `routing` key is a request nobody routes"

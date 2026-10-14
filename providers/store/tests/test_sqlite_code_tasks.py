"""Offline tests for the code task of the media pipeline (providers/store/sqlite.py, code_task_add and code_task_move): a task of a
request with no skill and no run row, which code moves and no model can pick up. Every name and text is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_code_tasks.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_code_tasks", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

KEY = "media:0123456789abcdef"
DECISION = {"kind": "question", "title": "Check the captions", "body": "Recording 0123456789abcdef: ready.", "payload": {"media_pipeline": {"step": "review"}}}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def add(conn, **kw):
    return store.code_task_add(conn, key=KEY, title="Edit the recording 01234567", text="Take the recording through the pipeline.", **kw)


def test_a_code_task_is_made_under_a_planned_request_with_no_skill_and_no_agent(conn):
    made = add(conn)
    task, request = store.task_get(conn, made["task"]), store.task_get(conn, made["request"])
    assert made["state"] == task["state"] == "running" and task["skill"] is None and task["agent"] is None and task["parent_id"] == made["request"]
    assert task["key"] == KEY and request["state"] == "planned" and request["parent_id"] is None and store.is_code_task(task)
    assert store.task_runs_list(conn, made["task"]) == []


def test_it_joins_a_planned_or_done_request_and_a_key_is_once_per_request(conn):
    first = store.request_add(conn, title="idea", text="x", flow="demo", tasks=[{"key": "script", "skill": "writer", "title": "t", "text": "x"}])
    request = first["request"]
    made = add(conn, request_id=request)
    assert made["request"] == request and store.task_get(conn, request)["state"] == "planned"
    with pytest.raises(store.StoreError, match="already has a task"):
        add(conn, request_id=request)
    requested = store.request_add(conn, title="waits", text="x")["request"]
    with pytest.raises(store.StoreError, match="planned or a done request"):
        add(conn, request_id=requested)
    with pytest.raises(store.StoreError, match="not a request"):
        add(conn, request_id=made["task"])
    for bad in ("Media:1", "media_1", "-media", "media:", "media::1", ":media", ""):
        with pytest.raises(store.StoreError):
            store.code_task_add(conn, key=bad, title="t", text="x")


def test_no_model_path_can_pick_it_up_whatever_its_state(conn):
    made = add(conn)
    task = made["task"]
    for state in ("failed", "running"):
        store.code_task_move(conn, task, state=state, note="renderer: browser_failed" if state == "failed" else None)
        assert conn.execute(store.NEXT_READY_TASK).fetchone() is None
        assert store.task_claim(conn, task) == {"task": None, "reason": "not-ready"}
    conn.execute("UPDATE tasks SET state = 'ready' WHERE id = ?", (task,))   # even a ready row, set by hand, is not given out
    assert conn.execute(store.NEXT_READY_TASK).fetchone() is None
    assert store.task_claim(conn, task) == {"task": None, "reason": "not-ready"}
    conn.execute("UPDATE tasks SET state = 'failed' WHERE id = ?", (task,))
    with pytest.raises(store.StoreError, match=f"media pipeline task.*media-pipeline --recording 0123456789abcdef"):
        store.task_retry(conn, task)


def test_moving_to_waiting_opens_its_decision_and_the_decision_is_resolved_by_the_pipeline_alone(conn):
    task = add(conn)["task"]
    moved = store.code_task_move(conn, task, state="waiting", pending=DECISION)
    pid = moved["pending_id"]
    item = store.pending_get(conn, pid)
    assert item["status"] == "open" and item["run_id"] is None and item["kind"] == "question" and store.task_get(conn, task)["state"] == "waiting"
    for resolution in ("answered", "released"):
        with pytest.raises(store.StoreError, match="belongs to a media pipeline task"):
            store.pending_resolve(conn, pid, resolution=resolution, by="user", answer="yes")
    assert store.pending_get(conn, pid)["status"] == "open"
    done = store.code_task_move(conn, task, state="running", resolve={"id": pid, "answer": "The captions were checked."})
    assert done["state"] == "running" and store.pending_get(conn, pid)["status"] == "resolved"
    assert store.pending_get(conn, pid)["answer"] == "The captions were checked." and store.pending_get(conn, pid)["resolved_by"] == "code"


def test_the_decisions_still_open_when_the_task_leaves_waiting_are_cancelled_and_a_new_one_replaces_them(conn):
    task = add(conn)["task"]
    first = store.code_task_move(conn, task, state="waiting", pending=DECISION)["pending_id"]
    second = store.code_task_move(conn, task, state="waiting", pending={**DECISION, "title": "Approve the rendered video"})["pending_id"]
    assert store.pending_get(conn, first)["status"] == "cancelled" and store.pending_get(conn, second)["status"] == "open"
    store.code_task_move(conn, task, state="failed", note="render: browser_failed")
    assert store.pending_get(conn, second)["status"] == "cancelled" and store.task_get(conn, task)["note"] == "render: browser_failed"


def test_a_move_is_checked_and_a_done_or_cancelled_task_does_not_move(conn):
    made = add(conn)
    task = made["task"]
    with pytest.raises(store.StoreError):
        store.code_task_move(conn, task, state="waiting")                 # a waiting task has a decision
    with pytest.raises(store.StoreError):
        store.code_task_move(conn, task, state="failed", pending=DECISION)  # and no other has
    with pytest.raises(store.StoreError):
        store.code_task_move(conn, task, state="ready")
    with pytest.raises(store.StoreError, match="open on task"):
        store.code_task_move(conn, task, state="running", resolve={"id": 999, "answer": "x"})
    store.code_task_move(conn, task, state="done")
    assert store.task_get(conn, made["request"])["state"] == "done"
    with pytest.raises(store.StoreError, match="does not move"):
        store.code_task_move(conn, task, state="running")
    other = store.request_add(conn, title="x", text="x", flow="demo", tasks=[{"key": "k", "skill": "writer", "title": "t", "text": "x"}])
    with pytest.raises(store.StoreError, match="not a media pipeline task"):
        store.code_task_move(conn, other["tasks"][0]["id"], state="running")


def test_a_cancelled_request_cancels_the_code_task_and_the_move_is_refused_afterwards(conn):
    made = add(conn)
    pid = store.code_task_move(conn, made["task"], state="waiting", pending=DECISION)["pending_id"]
    store.request_cancel(conn, made["request"], by="user")
    assert store.task_get(conn, made["task"])["state"] == "cancelled" and store.pending_get(conn, pid)["status"] == "cancelled"
    with pytest.raises(store.StoreError, match="cancelled"):
        store.code_task_move(conn, made["task"], state="running")


def test_a_code_task_holds_no_slot_of_an_agent_and_a_running_one_is_listed_as_running(conn):
    task = add(conn)["task"]
    assert [r["task"]["id"] for r in store.task_running_list(conn)] == [task] and store.task_slot_holders(conn) == []
    store.code_task_move(conn, task, state="waiting", pending=DECISION)
    assert store.task_slot_holders(conn) == []

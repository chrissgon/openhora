"""Offline tests for providers/store/sqlite.py `_refresh` and `pending_resolve`: a planned request whose tasks are all
cancelled, at least one by a rejected `effect`, becomes `cancelled` (finding 1 of the phone test of 2026-11-02:
every rejected or replaced card left its request `planned` for ever). Every name and text below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_reject_ends_request.py

The functions are called in process, the way runtime/ops.py calls them; each test has its own database.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_reject_ends_request", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

HASH = "a" * 64
NOTE = "replaced by a revised card"
ONE = [{"key": "send", "skill": "ops-pull-request", "title": "Send", "text": "open it.", "depends_on": []}]
TWO = [{"key": "write", "skill": "eng-implement", "title": "Write", "text": "make the change.", "depends_on": []},
       {"key": "send", "skill": "ops-pull-request", "title": "Send", "text": "open it.", "depends_on": []}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def claim(conn, task_id):
    task = store.task_claim(conn, task_id)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")["run_id"]
    return task, run


def tasks_of(conn, request_id):
    return [t["id"] for t in conn.execute("SELECT id FROM tasks WHERE parent_id = ? ORDER BY id", (request_id,))]


def state(conn, task_id):
    return conn.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()["state"]


def effect_for(conn, title="Carry the providers", plan=ONE, which=-1):
    """A request, planned from `plan`, whose task `which` ran to a gate and waits on one open effect."""
    request = store.request_add(conn, title=title, text="The installer of Lumen Desk.", flow="code-change",
                                tasks=plan)["request"]
    ids = tasks_of(conn, request)
    task, run = claim(conn, ids[which])
    out = store.task_run_finish(conn, run, status="ok", ending="gate", task_state="waiting",
                                pending={"kind": "effect", "title": "Pull request", "body": "Repository, base, head.",
                                         "payload_sha256": HASH})
    return {"request": request, "tasks": ids, "task": task["id"], "pending": out["pending_id"]}


def test_a_rejected_effect_ends_a_one_step_request_cancelled(conn):
    case = effect_for(conn)
    out = store.pending_resolve(conn, case["pending"], resolution="rejected", by="user")
    assert out["task_state"] == "cancelled" and out["completed"] == [], "cancelled is not done"
    assert state(conn, case["task"]) == "cancelled" and state(conn, case["request"]) == "cancelled"


def test_the_same_with_the_note_of_a_revised_card(conn):
    case = effect_for(conn)
    store.pending_resolve(conn, case["pending"], resolution="rejected", by="user", answer=NOTE)
    assert state(conn, case["task"]) == "cancelled" and state(conn, case["request"]) == "cancelled"
    row = store.pending_get(conn, case["pending"])
    assert row["status"] == "resolved" and row["resolution"] == "rejected" and row["answer"] == NOTE


def test_a_request_with_a_done_task_and_a_rejected_effect_stays_as_it_is(conn):
    request = store.request_add(conn, title="Two steps", text="Write, then send.", flow="code-change", tasks=TWO)["request"]
    first, second = tasks_of(conn, request)
    task, run = claim(conn, first)
    review = store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting",
                                   pending={"kind": "review", "title": "Review", "body": "Changed two files."})
    store.pending_resolve(conn, review["pending_id"], resolution="released", by="user")
    task, run = claim(conn, second)
    out = store.task_run_finish(conn, run, status="ok", ending="gate", task_state="waiting",
                                pending={"kind": "effect", "title": "Send", "body": "Repository.", "payload_sha256": HASH})
    resolved = store.pending_resolve(conn, out["pending_id"], resolution="rejected", by="user")
    assert resolved["completed"] == []
    assert state(conn, first) == "done" and state(conn, second) == "cancelled"
    assert state(conn, request) == "planned", "OPEN-2: left as it is today"


def test_a_request_whose_only_task_was_stopped_stays_planned(conn):
    request = store.request_add(conn, title="Stopped", text="One step.", flow="code-change", tasks=ONE)["request"]
    (only,) = tasks_of(conn, request)
    task, run = claim(conn, only)
    store.task_stop(conn, only, by="user")
    store.task_stopped(conn, only)
    assert state(conn, only) == "blocked"
    # the shape the spec names: the task settled `cancelled` (a request-wide stop does it) with no rejected effect anywhere
    conn.execute("UPDATE tasks SET state = 'cancelled' WHERE id = ?", (only,))
    other = effect_for(conn, title="Another request")
    store.pending_resolve(conn, other["pending"], resolution="rejected", by="user")
    assert state(conn, request) == "planned", "no rejected effect: the stop alone ends nothing"
    assert state(conn, other["request"]) == "cancelled"


def leak(conn, title):
    """The shape the live store holds: a planned request whose one task is cancelled, its effect resolved rejected,
    written by direct SQL (what the old code left behind)."""
    case = effect_for(conn, title=title)
    conn.execute("UPDATE pending_decisions SET status = 'resolved', resolution = 'rejected', answer = ? WHERE id = ?",
                 (NOTE, case["pending"]))
    conn.execute("UPDATE tasks SET state = 'cancelled' WHERE id = ?", (case["task"],))
    assert state(conn, case["request"]) == "planned"
    return case


def test_a_leaked_request_is_healed_by_the_next_resolution_of_another_request(conn):
    old = leak(conn, "Leaked one")
    fresh = effect_for(conn, title="Fresh")
    store.pending_resolve(conn, fresh["pending"], resolution="answered", by="user", answer="Name the flag.")
    assert state(conn, old["request"]) == "cancelled", "the heal"
    assert state(conn, fresh["request"]) == "planned", "a request that is not over is not touched"


def test_a_leaked_request_is_healed_by_the_cancel_of_another_request(conn):
    old = leak(conn, "Leaked two")
    fresh = effect_for(conn, title="Fresh")
    store.request_cancel(conn, fresh["request"], by="user")
    assert state(conn, old["request"]) == "cancelled" and state(conn, fresh["request"]) == "cancelled"

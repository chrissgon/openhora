"""Offline tests for cancel and stop at any moment in providers/store/sqlite.py (R18, migration 15): a store at 14 migrating (the
task_runs table rebuilt for the new status, every row, id, index, trigger and reference kept, the foreign keys checked), the stop
request written first and read by every finish, and the race rules: a finish committed before the stop request wins, a finish after
it opens nothing. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_cancel.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_cancel", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

SHA = "a" * 64
TASKS = [{"key": "a", "skill": "demo-a", "title": "A", "text": "do a."}, {"key": "b", "skill": "demo-b", "title": "B", "text": "do b.",
                                                                          "depends_on": ["a"]},
         {"key": "c", "skill": "demo-c", "title": "C", "text": "do c."}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def request(conn, tasks=TASKS):
    made = store.request_add(conn, title="Two jobs", text="Do the jobs.", flow="x", tasks=tasks)
    return made["request"], {t["key"]: t["id"] for t in made["tasks"]}


def start(conn, task_id, billing="metered"):
    assert store.task_claim(conn, task_id)["task"]["state"] == "running"
    return store.task_run_start(conn, task_id, skill="demo-a", model="m", adapter="h", billing=billing)["run_id"]


def review():
    return {"kind": "review", "title": "A: done", "body": "Done.", "payload": {}}


# --- migration 15 ---------------------------------------------------------------------------------------------------------


def test_a_store_at_14_migrates_to_15_keeps_every_row_and_admits_the_cancelled_status(tmp_path):
    path = tmp_path / "fourteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 15):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO tasks (parent_id, title, text, state, created_at, updated_at) VALUES (1, 'T', 'T.', 'waiting', 'a', 'a')")
    for n, status in enumerate(("ok", "failed", "running"), 1):
        old.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, status, failure, tokens, billing) "
                    "VALUES (2, 's', 'm', 'h', ?, ?, ?, ?, 'metered')", (f"2026-10-15T00:00:0{n}Z", status, "stopped" if status == "failed" else None, n * 10))
    old.execute("INSERT INTO pending_decisions (task_id, run_id, kind, title, body, created_at) VALUES (2, 1, 'review', 't', 'b', 'a')")
    old.execute("INSERT INTO conversation_messages (conversation, role, text, task_id, run_id, created_at) VALUES ('c', 'user', 'x', 2, 3, 'a')")
    old.execute("INSERT INTO sources VALUES ('s', 'file', 'x.csv', NULL, 'a', 'a')")
    old.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 18) + ")",
                ("s", 1, "import", "runtime", "csv", "x.csv", SHA, 1, "x.md", SHA, 1, "c", None, None, "[]", "{}", "v", "a"))
    old.execute("INSERT INTO task_sources VALUES (2, 2, 's', 1, ?, 'a')", (SHA,))
    old.commit()
    before = {t: [tuple(r) for r in old.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in ("task_runs", "pending_decisions", "conversation_messages", "task_sources")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 14 and out["applied"] == [15, 16, 17] and out["schema_version"] == 17
    conn = store.open_db(path)
    for name, rows in before.items():   # migration 17 adds a trailing column (the actor) to pending_decisions: the earlier columns are the same, the new one empty
        kept = [tuple(r)[:len(rows[0])] for r in conn.execute(f"SELECT * FROM {name} ORDER BY 1")]
        assert kept == rows, name
        assert name != "pending_decisions" or [r[-1] for r in conn.execute(f"SELECT * FROM {name} ORDER BY 1")] == [None] * len(rows)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert [r["name"] for r in conn.execute("PRAGMA table_info(task_runs)")][-4:] == ["error", "redactions", "billing", "autonomy"]
    assert [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")][-3:] == ["stop_requested_at", "stop_requested_by", "language"]
    assert conn.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'task_runs'").fetchone()[0] == "task_runs_by_task"
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM task_runs WHERE id = 1")
    conn.execute("UPDATE task_runs SET status = 'cancelled', failure = NULL WHERE id = 3")                       # the new status
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE task_runs SET status = 'paused' WHERE id = 1")
    new = conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at) VALUES (2, 's', 'm', 'h', 'a')").lastrowid
    assert new == 4, "a run id is never reused"
    conn.execute("INSERT INTO pending_decisions (task_id, run_id, kind, title, body, created_at) VALUES (2, 4, 'review', 't', 'b', 'a')")  # the reference holds
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO pending_decisions (task_id, run_id, kind, title, body, created_at) VALUES (2, 99, 'review', 't', 'b', 'a')")


# --- the stop request ---------------------------------------------------------------------------------------------------


def test_a_cancel_with_nothing_running_is_the_old_cancel_and_a_second_one_says_already(conn):
    rid, ids = request(conn)
    first = store.request_stop(conn, rid, by="user")
    assert first["already"] is False and first["running"] == [] and first["router_run"] is None
    assert sorted(first["cancelled"]) == sorted([rid, *ids.values()])
    assert {t["state"] for t in store.tasks_list(conn, rid)} == {"cancelled"}
    again = store.request_stop(conn, rid, by="user")
    assert again == {"request": rid, "cancelled": [], "pending": [], "running": [], "router_run": None, "already": True}


def test_a_cancel_with_a_task_running_cancels_the_rest_at_once_and_waits_for_the_run(conn):
    rid, ids = request(conn)
    run = start(conn, ids["a"])
    out = store.request_stop(conn, rid, by="user from page")
    assert out["running"] == [{"task": ids["a"], "run": run, "step": False}] and out["already"] is False
    assert sorted(out["cancelled"]) == sorted([ids["b"], ids["c"]])           # nothing new is claimed; the request waits for the run
    states = {t["id"]: t["state"] for t in store.tasks_list(conn, rid)}
    assert states[ids["a"]] == "running" and states[rid] == "planned" and states[ids["b"]] == states[ids["c"]] == "cancelled"
    assert store.task_claim(conn, ids["c"])["task"] is None
    assert store.request_stop(conn, rid, by="user")["already"] is True
    done = store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting", pending=review(), tokens=70, cost_usd=0.5)
    assert done["cancelled"] is True and done["pending_id"] is None and done["task_state"] == "cancelled"
    row = store.task_run_get(conn, run)
    assert (row["status"], row["failure"], row["ending"], row["tokens"], row["cost_usd"]) == ("cancelled", None, None, 70, 0.5)
    assert row["error"] == "cancelled by user from page" and row["ended_at"]
    assert store.pending_list(conn, "all") == []                               # nothing was opened
    assert store.task_get(conn, rid)["state"] == "cancelled"                   # the request ends when its last run does


def test_a_finish_that_committed_before_the_stop_keeps_its_result_and_the_cancel_cancels_its_pending_decision(conn):
    rid, ids = request(conn)
    run = start(conn, ids["a"])
    done = store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting", pending=review())
    assert done["cancelled"] is False and store.task_run_get(conn, run)["status"] == "ok"
    out = store.request_stop(conn, rid, by="user")
    assert out["running"] == [] and out["pending"] == [done["pending_id"]]
    assert store.pending_get(conn, done["pending_id"])["status"] == "cancelled"
    assert store.task_run_get(conn, run)["status"] == "ok"                      # its result stands
    assert store.task_get(conn, rid)["state"] == "cancelled"


def test_a_failed_finish_after_the_stop_is_cancelled_too_and_a_dead_holders_rows_are_ended_by_the_orphan_rule(conn):
    rid, ids = request(conn)
    run = start(conn, ids["a"])
    store.request_stop(conn, rid, by="user")
    ended = store.task_fail_orphans(conn, [ids["a"]], [], "the run was interrupted", usage={run: {"tokens": 33}})
    assert ended["tasks"] == [ids["a"]] and ended["cancelled"] == [run]
    row = store.task_run_get(conn, run)
    assert (row["status"], row["failure"], row["tokens"], row["error"]) == ("cancelled", None, 33, "cancelled by user")
    assert store.task_get(conn, ids["a"])["state"] == "cancelled" and store.task_get(conn, rid)["state"] == "cancelled"


def test_a_router_run_on_a_request_being_cancelled_is_recorded_cancelled_and_opens_nothing(conn):
    made = store.request_add(conn, title="Ask", text="Which market?")
    rid = made["request"]
    run = store.route_run_start(conn, rid, skill="router", model="m", adapter="h")["run_id"]
    out = store.request_stop(conn, rid, by="user")
    assert out["router_run"] == run and out["cancelled"] == [] and store.task_get(conn, rid)["state"] == "requested"
    with pytest.raises(store.StoreError, match="being cancelled"):
        store.route_run_start(conn, rid, skill="router", model="m", adapter="h")
    done = store.route_run_finish(conn, run, status="ok", ending="done", pending={"kind": "question", "title": "Q", "body": "b"}, tokens=5)
    assert done["cancelled"] is True and done["pending_id"] is None
    assert store.task_run_get(conn, run)["status"] == "cancelled" and store.task_get(conn, rid)["state"] == "cancelled"
    assert store.pending_list(conn, "all") == []


def test_a_dead_routers_row_is_ended_cancelled_by_run_id(conn):
    made = store.request_add(conn, title="Ask", text="Which market?")
    run = store.route_run_start(conn, made["request"], skill="router", model="m", adapter="h")["run_id"]
    store.request_stop(conn, made["request"], by="user")
    assert store.task_fail_orphans(conn, [], [run], "interrupted", usage={run: {"tokens": 9}}) == {"tasks": [], "runs": [run], "cancelled": [run]}
    assert store.task_run_get(conn, run)["status"] == "cancelled" and store.task_get(conn, made["request"])["state"] == "cancelled"


# --- stop one task ------------------------------------------------------------------------------------------------------


def test_stop_task_blocks_the_task_leaves_its_dependents_planned_and_retry_resumes_it(conn):
    rid, ids = request(conn)
    run = start(conn, ids["a"])
    first = store.task_stop(conn, ids["a"], by="user from page")
    assert first == {"task": ids["a"], "run": run, "step": False, "already": False, "scope": "task"}
    assert store.task_stop(conn, ids["a"], by="user")["already"] is True
    done = store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting", pending=review(), tokens=4)
    assert done["cancelled"] is True and done["task_state"] == "blocked" and done["pending_id"] is None
    task = store.task_get(conn, ids["a"])
    assert task["state"] == "blocked" and task["note"] == "stopped by user from page: retry it or cancel the request"
    assert store.task_run_get(conn, run)["status"] == "cancelled"
    states = {t["key"]: t["state"] for t in store.tasks_list(conn, rid) if t["parent_id"]}
    assert states["b"] == "planned" and states["c"] == "ready" and store.task_get(conn, rid)["state"] == "planned"   # the request and the others go on
    assert store.task_stop(conn, ids["a"], by="user")["already"] is True and store.task_stop(conn, ids["a"], by="user")["run"] is None
    retried = store.task_retry(conn, ids["a"])
    assert retried["state"] == "ready" and store.task_get(conn, ids["a"])["stop_requested_at"] is None
    run2 = start(conn, ids["a"])
    ok = store.task_run_finish(conn, run2, status="ok", ending="done", task_state="waiting", pending=review())
    assert ok["cancelled"] is False and store.task_get(conn, ids["a"])["state"] == "waiting"    # the stop ended with the retry
    with pytest.raises(store.StoreError, match="only a running task is stopped"):
        store.task_stop(conn, ids["c"], by="user")
    with pytest.raises(store.StoreError, match="is a request"):
        store.task_stop(conn, rid, by="user")


def test_a_task_stopped_whose_holder_is_gone_ends_blocked_and_its_run_cancelled_with_its_usage(conn):
    rid, ids = request(conn)
    run = start(conn, ids["a"])
    store.task_stop(conn, ids["a"], by="user")
    out = store.task_stopped(conn, ids["a"], usage={run: {"tokens": 12, "cost_usd": 0.25}})
    assert out == {"task": ids["a"], "state": "blocked", "runs": [run]}
    row = store.task_run_get(conn, run)
    assert (row["status"], row["tokens"], row["cost_usd"]) == ("cancelled", 12, 0.25)
    assert store.task_stopped(conn, ids["a"]) == {"task": ids["a"], "state": "blocked", "runs": []}          # idempotent


def test_a_step_task_with_a_stop_request_does_not_move_and_ends_through_task_stopped(conn):
    made = store.step_task_add(conn, key="ingest-a", title="Ingest", text="Ingest.", step="ingest")
    task = made["task"]
    store.task_claim(conn, task)
    store.step_task_move(conn, task, state="running")
    assert store.task_stop(conn, task, by="user")["step"] is True
    with pytest.raises(store.StoreError, match="has a stop request"):
        store.step_task_move(conn, task, state="done")
    assert store.task_stopped(conn, task)["state"] == "blocked"
    assert store.task_retry(conn, task)["state"] == "ready"


def test_a_request_being_cancelled_takes_no_task_and_no_retry(conn):
    rid, ids = request(conn)
    start(conn, ids["a"])
    store.request_stop(conn, rid, by="user")
    with pytest.raises(store.StoreError, match="being cancelled"):
        store.tasks_add(conn, rid, [{"key": "d", "skill": "demo-d", "title": "D", "text": "do d."}])


def test_a_done_request_whose_delivery_is_routed_again_is_refused_as_running_and_a_cancelled_one_says_already(conn):
    rid, ids = request(conn, tasks=[TASKS[0]])
    run = start(conn, ids["a"])
    store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting", pending=review())
    pending = store.pending_list(conn, "open")[0]["id"]
    store.pending_resolve(conn, pending, resolution="released", by="user")
    assert store.task_get(conn, rid)["state"] == "done"
    store.route_run_start(conn, rid, skill="router", model="m", adapter="h", reroute=True)
    with pytest.raises(store.StoreError, match="is running: wait for its run to end"):
        store.request_stop(conn, rid, by="user")
    assert store.task_get(conn, rid)["stop_requested_at"] is None


def test_request_stop_keeps_a_decision_it_was_told_to_keep_and_the_end_of_the_request_keeps_it_too(conn):
    rid, ids = request(conn, tasks=[TASKS[0], TASKS[2]])
    run_c = start(conn, ids["c"])
    effect = {"kind": "effect", "title": "Write", "body": "Write it.", "payload": {}, "payload_sha256": SHA}
    store.task_run_finish(conn, run_c, status="ok", ending="done", task_state="waiting", pending=effect)
    kept = store.pending_list(conn, "open", ids["c"])[0]["id"]
    run_a = start(conn, ids["a"])
    out = store.request_stop(conn, rid, by="user", keep=[kept])
    assert out["kept"] == [kept] and out["running"] == [{"task": ids["a"], "run": run_a, "step": False}]
    assert store.task_get(conn, ids["c"])["state"] == "waiting" and store.pending_get(conn, kept)["status"] == "open"
    assert store.task_get(conn, rid)["state"] == "planned", "a run of the request is still running"
    done = store.task_run_finish(conn, run_a, status="ok", ending="done", task_state="waiting", pending=review())
    assert done["cancelled"] is True
    assert store.task_get(conn, rid)["state"] == "cancelled", "the request ends when its last run does"
    assert store.task_get(conn, ids["c"])["state"] == "waiting" and store.pending_get(conn, kept)["status"] == "open", "the end keeps the decision too"
    assert store.request_stop(conn, rid, by="user")["already"] is True

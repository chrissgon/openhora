"""Offline tests for the task runtime's tables in providers/store/sqlite.py (migration 2) and the functions that
are their contract. Every name and text below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_tasks.py

The functions are called in process, the way runtime/ops.py calls them; each test has its own database.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_tasks", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


def claim_oldest(conn):
    """Claim the oldest ready task, as the first claim of a database once did, with the store's own query and task_claim."""
    row = conn.execute(store.NEXT_READY_TASK).fetchone()
    return store.task_claim(conn, row["id"]) if row else {"task": None}

PLAN = [{"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do the market analysis."},
        {"key": "positioning", "skill": "biz-icp-positioning", "title": "Positioning", "text": "Choose the profile.",
         "depends_on": ["market"], "milestone": True}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def planned(conn):
    out = store.request_add(conn, title="Which market first", text="Tell me which market to go after.",
                            flow="market-positioning", tasks=PLAN)
    return out["request"], out["tasks"][0]["id"], out["tasks"][1]["id"]


def run_to_waiting(conn, kind="question", body="1. Which country? Recommended: yours."):
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    done = store.task_run_finish(conn, run["run_id"], status="ok", ending="question" if kind == "question" else "done",
                                 task_state="waiting", pending={"kind": kind, "title": "t", "body": body})
    return task["id"], run["run_id"], done["pending_id"]


def test_init_db_creates_a_private_database_at_the_current_version_and_puts_the_umask_back(tmp_path):
    before = os.umask(0o022)
    try:
        path = tmp_path / "new" / "tasks.sqlite"
        out = store.init_db(path)
        assert out["created"] is True and out["applied"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19] and out["schema_version"] == 19
        assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert os.umask(0o022) == 0o022  # the caller's umask is what it was
    finally:
        os.umask(before)


def test_a_version_1_database_keeps_its_rows_and_gains_the_three_tables(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, "
                "description TEXT NOT NULL)")
    for statement in store.MIGRATIONS[1][1]:
        old.execute(statement)
    old.execute("INSERT INTO schema_version VALUES (1, '2026-10-01T00:00:00.000000Z', 'first')")
    old.execute("INSERT INTO cursors VALUES ('since', 'v1', '2026-10-01T00:00:00.000000Z')")
    old.commit()
    old.close()
    with pytest.raises(store.StoreError) as refused:
        store.open_db(path)
    assert refused.value.code == store.EXIT_NOT_CONFIGURED and "run init" in str(refused.value)
    out = store.init_db(path)
    assert out["migrated_from"] == 1 and out["applied"] == [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    conn = store.open_db(path)
    assert conn.execute("SELECT value FROM cursors WHERE name = 'since'").fetchone()[0] == "v1"
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"tasks", "task_runs", "pending_decisions", "cursors", "events", "runs", "inbox", "actions"} <= names


def test_a_request_with_its_plan_is_one_transaction_and_only_the_task_without_dependency_is_ready(conn):
    request, market, positioning = planned(conn)
    rows = {t["id"]: t for t in store.tasks_list(conn, request)}
    assert rows[request]["state"] == "planned" and rows[request]["parent_id"] is None and rows[request]["skill"] is None
    assert rows[market]["state"] == "ready" and rows[market]["depends_on"] == []
    assert rows[positioning]["state"] == "planned" and rows[positioning]["depends_on"] == [market]
    assert rows[positioning]["milestone"] == 1 and rows[positioning]["key"] == "positioning"


def test_a_request_without_a_plan_stays_requested(conn):
    out = store.request_add(conn, title="t", text="x")
    assert out["state"] == "requested" and out["tasks"] == []
    assert claim_oldest(conn) == {"task": None}


@pytest.mark.parametrize("tasks", [
    [{"key": "a", "skill": "s", "title": "t", "text": "x", "depends_on": ["b"]},
     {"key": "b", "skill": "s", "title": "t", "text": "x"}],            # a dependency on a later task
    [{"key": "a", "skill": "s", "title": "t", "text": "x"}, {"key": "a", "skill": "s", "title": "t", "text": "x"}],
    [{"key": "Not A Key", "skill": "s", "title": "t", "text": "x"}],
    [{"key": "a", "skill": "s", "title": "t", "text": ""}],
])
def test_a_plan_that_is_not_well_formed_adds_nothing(conn, tasks):
    with pytest.raises(store.StoreError):
        store.request_add(conn, title="t", text="x", flow="f", tasks=tasks)
    assert store.tasks_list(conn) == []


def test_a_claim_is_not_refused_by_another_running_task(conn):
    planned(conn)
    _, second_market, _ = planned(conn)  # a second request: its first task is ready too
    first = claim_oldest(conn)
    assert first["task"]["state"] == "running" and "running" not in first
    second = store.task_claim(conn, second_market)  # the other request's task is claimed while the first runs
    assert second["task"]["state"] == "running" and "running" not in second


def test_two_tasks_of_one_database_may_run_at_once(conn):
    first_request, first_market, _ = planned(conn)
    second_request, second_market, _ = planned(conn)
    one = store.task_claim(conn, first_market)
    two = store.task_claim(conn, second_market)
    assert one["task"]["state"] == "running" and two["task"]["state"] == "running"
    run_one = store.task_run_start(conn, first_market, skill="biz-market-analysis", model="m", adapter="h")
    run_two = store.task_run_start(conn, second_market, skill="biz-market-analysis", model="m", adapter="h")
    assert run_one["run_id"] != run_two["run_id"]
    assert [r["task_id"] for r in store.task_runs_running(conn)] == [first_market, second_market]


def test_a_claim_names_why_a_task_is_not_given_out(conn):
    request = store.request_add(conn, title="Market and positioning", text="For Lantern Notes.",
                                flow="market-positioning", tasks=PLAN)
    market, positioning = [t["id"] for t in request["tasks"]]
    assert store.task_claim(conn, 999) == {"task": None, "reason": "unknown"}
    assert store.task_claim(conn, request["request"])["reason"] == "not-ready"  # a request is never given out
    assert store.task_claim(conn, positioning)["reason"] == "not-ready"  # planned, not ready
    store.task_claim(conn, market)
    assert store.task_claim(conn, market)["reason"] == "not-ready"  # running already
    store.task_run_start(conn, market, skill="biz-market-analysis", model="m", adapter="h")
    conn.execute("UPDATE tasks SET state = 'ready' WHERE id = ?", (positioning,))
    conn.execute("INSERT INTO task_waits (task_id, kind, awaited_id, path, reason, status, created_at) "
                 "VALUES (?, 'input', ?, 'docs/x.md', 'r', 'open', 't0')", (positioning, market))
    assert store.task_claim(conn, positioning) == {"task": None, "reason": "waiting"}


def test_only_the_orphans_named_are_failed_and_their_runs_ended(conn):
    _, a, _ = planned(conn)
    _, b, _ = planned(conn)
    _, c, _ = planned(conn)
    for task_id in (a, b, c):
        store.task_claim(conn, task_id)
    run_a = store.task_run_start(conn, a, skill="biz-market-analysis", model="m", adapter="h")["run_id"]
    run_b = store.task_run_start(conn, b, skill="biz-market-analysis", model="m", adapter="h")["run_id"]
    run_c = store.task_run_start(conn, c, skill="biz-market-analysis", model="m", adapter="h")["run_id"]
    out = store.task_fail_orphans(conn, [a, 999], [run_c], "the process died")
    assert out == {"tasks": [a], "runs": sorted([run_a, run_c])}
    assert store.task_get(conn, a)["state"] == "failed" and store.task_get(conn, a)["note"] == "the process died"
    assert store.task_get(conn, b)["state"] == "running" and store.task_get(conn, c)["state"] == "running"
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM task_runs")}
    assert rows[run_a]["status"] == "failed" and rows[run_a]["failure"] == "stopped" and rows[run_a]["ended_at"]
    assert rows[run_a]["error"] == "the process died" and rows[run_c]["status"] == "failed"
    assert rows[run_b]["status"] == "running"
    again = store.task_fail_orphans(conn, [a], [run_a, run_c], "x")  # nothing is running any more: skipped silently
    assert again == {"tasks": [], "runs": []}


def test_the_running_list_gives_each_task_with_its_live_run(conn):
    _, a, _ = planned(conn)
    _, b, _ = planned(conn)
    assert store.task_running_list(conn) == []
    store.task_claim(conn, b)
    store.task_claim(conn, a)
    run_a = store.task_run_start(conn, a, skill="biz-market-analysis", model="m", adapter="h", billing="metered")
    listed = store.task_running_list(conn)
    assert [item["task"]["id"] for item in listed] == [a, b]  # oldest task first
    assert listed[0]["task"]["state"] == "running"
    assert listed[0]["run"] == {"id": run_a["run_id"], "started_at": run_a["started_at"],
                                "skill": "biz-market-analysis", "billing": "metered"}
    assert listed[1]["run"] is None  # claimed, its run row not written yet


def test_slot_holders_are_running_waiting_and_answered(conn):
    _, a, a2 = planned(conn)  # a: never run and ready
    _, b, _ = planned(conn)  # b: running
    _, c, _ = planned(conn)  # c: waiting
    _, d, _ = planned(conn)  # d: ready after an answer
    _, e, _ = planned(conn)  # e: answered, then ran and failed, then retried
    _, f, _ = planned(conn)  # f: failed
    _, g, _ = planned(conn)  # g: blocked
    _, h, _ = planned(conn)  # h: done
    _, i, _ = planned(conn)  # i: cancelled
    assert store.task_slot_holders(conn) == []
    store.task_claim(conn, b)

    def ask(task_id):
        store.task_claim(conn, task_id)
        run = store.task_run_start(conn, task_id, skill="biz-market-analysis", model="m", adapter="h")
        return store.task_run_finish(conn, run["run_id"], status="ok", ending="question", task_state="waiting",
                                     pending={"kind": "question", "title": "t", "body": "1. Which?"})["pending_id"]

    ask(c)
    store.pending_resolve(conn, ask(d), resolution="answered", by="user", answer="this one")
    store.pending_resolve(conn, ask(e), resolution="answered", by="user", answer="that one")
    store.task_claim(conn, e)
    run = store.task_run_start(conn, e, skill="biz-market-analysis", model="m", adapter="h")
    store.task_run_finish(conn, run["run_id"], status="failed", failure="adapter", task_state="failed")
    store.task_retry(conn, e)
    assert store.task_get(conn, e)["state"] == "ready"
    for task_id, state in ((f, "failed"), (g, "blocked"), (h, "done"), (i, "cancelled")):
        conn.execute("UPDATE tasks SET state = ? WHERE id = ?", (state, task_id))
    holders = store.task_slot_holders(conn)
    conn.execute("UPDATE tasks SET agent = 'business' WHERE id = ?", (c,))
    assert store.task_slot_holders(conn) == [{"id": b, "agent": None}, {"id": c, "agent": "business"},
                                             {"id": d, "agent": None}]
    assert a not in [x["id"] for x in holders] and a2 not in [x["id"] for x in holders]  # a request's tasks only


def test_runs_since_lists_task_runs_from_the_low_water_mark(conn):
    request, a, _ = planned(conn)
    _, b, _ = planned(conn)
    store.task_claim(conn, a)
    store.task_claim(conn, b)
    run_a = store.task_run_start(conn, a, skill="biz-market-analysis", model="m", adapter="h")["run_id"]
    run_b = store.task_run_start(conn, b, skill="biz-market-analysis", model="m", adapter="h")["run_id"]
    conn.execute("UPDATE tasks SET state = 'cancelled' WHERE id = ?", (request,))
    conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at) "
                 "VALUES (?, 'core-orchestrator', 'm', 'h', 't0')", (request,))  # a router run: not a task run
    assert [r["id"] for r in store.task_runs_since(conn, 0)] == [run_a, run_b]
    rows = store.task_runs_since(conn, run_b)
    assert [r["id"] for r in rows] == [run_b] and rows[0]["task_id"] == b and rows[0]["status"] == "running"
    assert "skill_sha256" in rows[0] and store.task_runs_since(conn, run_b + 10) == []


def test_a_waiting_task_always_points_to_an_open_pending_decision(conn):
    planned(conn)
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", web=True,
                               skill_version="1.0.0", skill_sha256="a" * 64)
    with pytest.raises(store.StoreError):  # waiting without a pending decision is refused, and nothing moved
        store.task_run_finish(conn, run["run_id"], status="ok", ending="question", task_state="waiting")
    with pytest.raises(store.StoreError):  # and a failed task takes none
        store.task_run_finish(conn, run["run_id"], status="failed", failure="timeout", task_state="failed",
                              pending={"kind": "question", "title": "t", "body": "b"})
    assert store.task_get(conn, task["id"])["state"] == "running"
    done = store.task_run_finish(conn, run["run_id"], status="ok", ending="question", task_state="waiting", attempts=1,
                                 cost_usd=0.07, tokens=1200, duration_ms=11000, skill_loaded=True,
                                 image_digest="sha256:" + "1" * 64, run_dir="/tmp/run-1",
                                 pending={"kind": "question", "title": "biz-market-analysis asks", "body": "1. Where?",
                                          "payload": {"ending": "question"}})
    assert store.task_get(conn, task["id"])["state"] == "waiting"
    item = store.pending_get(conn, done["pending_id"])
    assert (item["task_id"], item["run_id"], item["status"], item["payload"]) == (task["id"], run["run_id"], "open",
                                                                                 {"ending": "question"})
    row = store.task_runs_list(conn, task["id"])[0]
    assert (row["status"], row["ending"], row["web"], row["skill_loaded"], row["cost_usd"]) == ("ok", "question", 1, 1, 0.07)
    with pytest.raises(store.StoreError):  # a run ends once
        store.task_run_finish(conn, run["run_id"], status="failed", failure="timeout", task_state="failed")


def test_an_answer_makes_the_task_ready_again_and_keeps_the_answer(conn):
    planned(conn)
    task_id, _, pending_id = run_to_waiting(conn)
    out = store.pending_resolve(conn, pending_id, resolution="answered", by="user", answer="Portugal.\nRemote.")
    assert out["task_state"] == "ready" and out["ready"] == [] and out["completed"] == []
    item = store.pending_get(conn, pending_id)
    assert (item["status"], item["resolution"], item["answer"], item["resolved_by"]) == ("resolved", "answered",
                                                                                         "Portugal.\nRemote.", "user")
    assert claim_oldest(conn)["task"]["id"] == task_id  # the same task runs again
    with pytest.raises(store.StoreError):
        store.pending_resolve(conn, pending_id, resolution="answered", by="user", answer="again")


def test_a_question_is_answered_never_released_and_an_answer_needs_its_text(conn):
    planned(conn)
    task_id, _, pending_id = run_to_waiting(conn)
    with pytest.raises(store.StoreError) as e:
        store.pending_resolve(conn, pending_id, resolution="released", by="user")
    assert "answered, not released" in str(e.value)
    with pytest.raises(store.StoreError):
        store.pending_resolve(conn, pending_id, resolution="answered", by="user")
    assert store.task_get(conn, task_id)["state"] == "waiting" and store.pending_get(conn, pending_id)["status"] == "open"


def test_releasing_a_review_makes_the_next_task_ready_and_the_last_one_completes_the_request(conn):
    request, market, positioning = planned(conn)
    _, _, review = run_to_waiting(conn, kind="review", body="Done: docs/business/market.md")
    out = store.pending_resolve(conn, review, resolution="released", by="user")
    assert (out["task_state"], out["ready"], out["completed"]) == ("done", [positioning], [])
    _, _, review = run_to_waiting(conn, kind="review", body="Done: docs/business/icp.md")
    out = store.pending_resolve(conn, review, resolution="released", by="user")
    assert (out["task_state"], out["ready"], out["completed"]) == ("done", [], [request])
    assert [t["state"] for t in store.tasks_list(conn, request)] == ["done", "done", "done"]


def test_a_failed_run_fails_the_task_and_retry_makes_it_ready(conn):
    planned(conn)
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    store.task_run_finish(conn, run["run_id"], status="failed", failure="timeout", task_state="failed",
                          error="timeout: stopped after 1800s", task_note="timeout: stopped after 1800s")
    assert store.task_get(conn, task["id"])["note"] == "timeout: stopped after 1800s"
    assert store.task_retry(conn, task["id"]) == {"task_id": task["id"], "state": "ready", "previous": "failed"}
    with pytest.raises(store.StoreError):
        store.task_retry(conn, task["id"])  # ready already


def test_what_an_interrupted_run_left_is_ended_as_stopped(conn):
    planned(conn)
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    assert store.task_fail_orphans(conn, [task["id"]], [], "the run was interrupted") == {"tasks": [task["id"]], "runs": [run["run_id"]]}
    assert store.task_get(conn, task["id"])["state"] == "failed"
    assert (store.task_runs_list(conn, task["id"])[0]["status"], store.task_runs_list(conn, task["id"])[0]["failure"]) == ("failed", "stopped")
    assert store.task_fail_orphans(conn, [task["id"]], [], "again") == {"tasks": [], "runs": []}


def test_cancelling_a_request_cancels_its_open_tasks_and_pending_decisions_and_is_refused_while_one_runs(conn):
    request, market, positioning = planned(conn)
    claim_oldest(conn)
    with pytest.raises(store.StoreError):
        store.request_cancel(conn, request, by="user")
    store.task_fail_orphans(conn, [market], [], "stopped")
    store.task_retry(conn, market)
    _, _, pending_id = run_to_waiting(conn)
    with pytest.raises(store.StoreError):
        store.request_cancel(conn, market, by="user")  # a task is not a request
    out = store.request_cancel(conn, request, by="user")
    assert out == {"request": request, "cancelled": [request, market, positioning], "pending": [pending_id]}
    assert store.pending_list(conn) == [] and store.pending_list(conn, "cancelled")[0]["id"] == pending_id


def test_a_value_outside_a_closed_list_is_refused_by_the_function_and_by_the_table(conn):
    planned(conn)
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    for bad in ({"kind": "note", "title": "t", "body": "b"}, {"kind": "review", "title": "t", "body": 5},
                {"kind": "review", "title": "t", "body": "b", "payload_sha256": "abc"}):
        with pytest.raises(store.StoreError):
            store.task_run_finish(conn, run["run_id"], status="ok", ending="done", task_state="waiting", pending=bad)
    with pytest.raises(store.StoreError):
        store.task_run_finish(conn, run["run_id"], status="ok", ending="finished", task_state="waiting",
                              pending={"kind": "review", "title": "t", "body": "b"})
    for statement in ("UPDATE tasks SET state = 'paused'", "UPDATE task_runs SET ending = 'finished'",
                      "INSERT INTO pending_decisions (task_id, kind, title, body, created_at) VALUES (1, 'note', 't', 'b', 'now')"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(statement)


def test_export_prints_the_three_tables_and_the_verbs_of_version_1_still_work(tmp_path):
    path = tmp_path / "s.sqlite"
    store.init_db(path)
    conn = store.open_db(path)
    planned(conn)
    run_to_waiting(conn)
    cli = lambda *args: subprocess.run([sys.executable, str(SCRIPT), *args, "--db", str(path)], capture_output=True,
                                       text=True, timeout=60)
    out = json.loads(cli("export", "--format", "json").stdout)
    assert (len(out["tasks"]), len(out["task_runs"]), len(out["pending_decisions"])) == (3, 1, 1)
    assert out["tasks"][2]["depends_on"] == [out["tasks"][1]["id"]] and out["pending_decisions"][0]["payload"] == {}
    assert cli("cursor-set", "--name", "since", "--value", "v").returncode == 0
    assert json.loads(cli("--check").stdout)["schema_version"] == 19


def test_a_cursor_written_in_process_is_the_one_the_verb_reads(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    conn = store.open_db(path)
    out = store.cursor_set(conn, "config:accepted-sha256", "ab" * 32)
    assert out["name"] == "config:accepted-sha256" and out["value"] == "ab" * 32 and out["updated_at"]
    read = subprocess.run([sys.executable, str(SCRIPT), "cursor-get", "--name", "config:accepted-sha256", "--db", str(path)],
                          capture_output=True, text=True, timeout=60)
    assert read.returncode == 0 and json.loads(read.stdout)["value"] == "ab" * 32
    store.cursor_set(conn, "config:accepted-sha256", "cd" * 32)  # replaced, not added
    assert store.cursor_get(conn, "config:accepted-sha256") == "cd" * 32
    assert conn.execute("SELECT COUNT(*) FROM cursors").fetchone()[0] == 1
    with pytest.raises(store.StoreError):
        store.cursor_set(conn, "config:accepted-sha256", "x" * (store.VALUE_MAX + 1))


def test_a_cursor_that_was_never_written_reads_as_none(conn):
    assert store.cursor_get(conn, "config:accepted-sha256") is None
    with pytest.raises(store.StoreError):
        store.cursor_get(conn, " ")


def test_a_run_keeps_the_number_of_redactions_the_lab_reported(conn):
    planned(conn)
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    with pytest.raises(store.StoreError):
        store.task_run_finish(conn, run["run_id"], status="failed", failure="auth", task_state="failed", redactions=-1)
    store.task_run_finish(conn, run["run_id"], status="failed", failure="auth", task_state="failed", redactions=2)
    assert store.task_runs_list(conn, task["id"])[0]["redactions"] == 2
    store.task_retry(conn, task["id"])
    task = claim_oldest(conn)["task"]
    again = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    store.task_run_finish(conn, again["run_id"], status="failed", failure="adapter", task_state="failed")
    assert store.task_runs_list(conn, task["id"])[1]["redactions"] is None  # not reported is not zero


def test_a_run_is_read_by_its_id(conn):
    planned(conn)
    task = claim_oldest(conn)["task"]
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    got = store.task_run_get(conn, run["run_id"])
    assert (got["id"], got["task_id"], got["model"], got["status"]) == (run["run_id"], task["id"], "m", "running")
    with pytest.raises(store.StoreError):
        store.task_run_get(conn, run["run_id"] + 1)


def test_a_task_a_run_and_a_pending_decision_are_never_deleted(conn, tmp_path, monkeypatch):
    """Limit L13 for the task runtime's records (migration 7): the database refuses to delete a task, a run or a
    pending decision, whoever writes the SQL; their state, status and resolution still move."""
    request, market, _ = planned(conn)
    task, run, pending = run_to_waiting(conn)
    assert task == market
    for statement, args in (("DELETE FROM pending_decisions WHERE id = ?", (pending,)),
                            ("DELETE FROM task_runs WHERE id = ?", (run,)),
                            ("DELETE FROM tasks WHERE id = ?", (task,)),
                            ("DELETE FROM tasks", ())):
        with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
            with conn:
                conn.execute(statement, args)
    store.pending_resolve(conn, pending, resolution="answered", by="user", answer="Ours.")
    assert store.task_get(conn, task)["state"] == "ready"
    assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM task_runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pending_decisions").fetchone()[0] == 1
    # A database at version 6 keeps its rows and gains the triggers with init.
    path = tmp_path / "six.sqlite"
    monkeypatch.setattr(store, "SCHEMA_VERSION", 6)
    monkeypatch.setattr(store, "MIGRATIONS", {k: v for k, v in store.MIGRATIONS.items() if k <= 6})
    store.init_db(path)
    older = sqlite3.connect(path)  # written with SQL of version 6: request_add knows the columns of the current version
    for _ in range(3):  # a request and the two tasks of its plan, as planned() makes them
        older.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('Old', 'Old.', 'planned', 't0', 't0')")
    older.commit()
    older.close()
    monkeypatch.undo()
    assert store.init_db(path)["applied"] == [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    six = store.open_db(path)
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        with six:
            six.execute("DELETE FROM tasks")
    assert six.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 3


def test_task_runs_running_lists_only_the_live_run_in_one_query(conn):
    request = store.request_add(conn, title="A", text="Do it.", flow=None, tasks=[])["request"]
    other = store.request_add(conn, title="B", text="Do it too.", flow=None, tasks=[])["request"]
    assert store.task_runs_running(conn) == []
    run = store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")["run_id"]
    [live] = store.task_runs_running(conn)
    assert set(live) == {"id", "task_id", "skill", "started_at"} and live["id"] == run and live["task_id"] == request
    store.route_run_finish(conn, run, status="failed", failure="internal", error="stopped")
    assert store.task_runs_running(conn) == []
    assert other != request

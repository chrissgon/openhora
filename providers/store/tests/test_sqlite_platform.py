"""Offline tests for migration 4 of providers/store/sqlite.py and its functions: a task's item on the task board, a
request written there and its acceptance, the router's run and the plan a person approves, the records of mirrored
documents and the comments saved from a platform. Every name and text below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_platform.py

The functions are called in process, the way runtime/ops.py calls them; each test has its own database.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_platform", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

PLAN = [{"key": "strategy", "skill": "brand-strategy", "title": "Strategy", "text": "write the brand strategy.",
         "depends_on": [], "milestone": True},
        {"key": "name", "skill": "brand-name", "title": "Name", "text": "check the name.", "depends_on": ["strategy"]},
        {"key": "identity", "skill": "brand-identity", "title": "Identity", "text": "design the look.",
         "depends_on": ["strategy"]}]
PAYLOAD = {"source": "named", "flow": "brand", "tasks": PLAN, "plan_sha256": "a" * 64}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def a_request(conn) -> int:
    return store.request_add(conn, title="A brand for Lumen Desk", text="We need a brand for Lumen Desk.")["request"]


def a_plan(conn, request_id: int, payload=None) -> int:
    return store.plan_open(conn, request_id, title="Plan: brand", body="strategy, name, identity",
                           payload=payload or PAYLOAD)["pending_id"]


def test_migration_4_adds_the_columns_and_the_two_tables_and_keeps_every_row_of_version_3(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, "
                "description TEXT NOT NULL)")
    for version in (1, 2, 3):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-01T00:00:00.000000Z', 'before')", (version,))
    old.execute("INSERT INTO tasks (id, title, text, state, created_at, updated_at) "
                "VALUES (1, 'Request', 'Old request.', 'planned', 't0', 't0')")
    old.execute("INSERT INTO tasks (id, parent_id, flow, key, skill, title, text, state, created_at, updated_at) "
                "VALUES (2, 1, 'demo', 'market', 'demo-asks', 'Market', 'Old task.', 'ready', 't0', 't0')")
    old.commit()
    before = [tuple(r) for r in old.execute("SELECT * FROM tasks ORDER BY id")]
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 3 and out["applied"] == [4, 5, 6, 7, 8, 9] and out["schema_version"] == 9
    conn = store.open_db(path)
    rows = conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
    assert [tuple(r)[:len(before[0])] for r in rows] == before
    assert all(r["remote_id"] is None and r["remote_version"] is None and r["remote_written_sha256"] is None for r in rows)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"document_records", "platform_comments"} <= names


def test_a_database_of_version_4_is_refused_by_a_script_of_version_3(tmp_path, monkeypatch):
    path = tmp_path / "new.sqlite"
    store.init_db(path)
    monkeypatch.setattr(store, "SCHEMA_VERSION", 3)
    with pytest.raises(store.StoreError) as refused:
        store.open_db(path)
    assert refused.value.code == store.EXIT_ERROR and "newer than this script (3)" in str(refused.value)


def test_an_item_written_on_the_board_becomes_a_request_that_waits_for_acceptance_once(conn):
    first = store.request_from_board(conn, title="Fix the logo", text="The logo is blurry.", remote_id="t7",
                                     remote_version="v1", by="board")
    assert first["existing"] is False
    request = store.task_get(conn, first["request"])
    assert (request["state"], request["remote_id"], request["remote_version"], request["parent_id"]) == (
        "requested", "t7", "v1", None)
    item = store.pending_get(conn, first["pending_id"])
    assert (item["kind"], item["status"], item["body"]) == ("acceptance", "open", "The logo is blurry.")
    again = store.request_from_board(conn, title="Fix the logo", text="Edited.", remote_id="t7", remote_version="v2",
                                     by="board")
    assert again == {"request": first["request"], "pending_id": first["pending_id"], "existing": True}
    assert len(store.tasks_list(conn)) == 1 and len(store.pending_list(conn)) == 1
    with pytest.raises(store.StoreError):
        store.route_run_start(conn, first["request"], skill="core-orchestrator", model="m", adapter="h")
    with pytest.raises(store.StoreError):
        store.pending_resolve(conn, first["pending_id"], resolution="answered", by="user", answer="yes")


def test_a_rejected_acceptance_cancels_the_request_and_an_accepted_one_leaves_it_requested(conn):
    kept = store.request_from_board(conn, title="One", text="One.", remote_id="t1", remote_version=None, by="board")
    dropped = store.request_from_board(conn, title="Two", text="Two.", remote_id="t2", remote_version=None, by="board")
    out = store.acceptance_resolve(conn, kept["pending_id"], resolution="accepted", by="user")
    assert out["task_state"] == "requested" and store.pending_get(conn, kept["pending_id"])["resolution"] == "accepted"
    out = store.acceptance_resolve(conn, dropped["pending_id"], resolution="rejected", by="user")
    assert out["task_state"] == "cancelled"
    assert store.pending_get(conn, dropped["pending_id"])["resolution"] == "rejected"
    for wrong in ("approved", "answered"):
        with pytest.raises(store.StoreError):
            store.acceptance_resolve(conn, kept["pending_id"], resolution=wrong, by="user")
    plan_id = a_plan(conn, a_request(conn))
    with pytest.raises(store.StoreError):
        store.acceptance_resolve(conn, plan_id, resolution="accepted", by="user")  # not an acceptance
    run = store.route_run_start(conn, kept["request"], skill="core-orchestrator", model="m", adapter="h")
    assert run["request_id"] == kept["request"]


def test_a_route_run_is_refused_while_a_task_runs_or_a_plan_is_open(conn):
    planned = store.request_add(conn, title="Market", text="Which market?", flow="demo",
                                tasks=[{"key": "market", "skill": "demo-asks", "title": "Market", "text": "go."}])
    request = a_request(conn)
    task = store.task_claim_next(conn)["task"]
    assert task["parent_id"] == planned["request"]
    with pytest.raises(store.StoreError) as refused:
        store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")
    assert "one run at a time" in str(refused.value)
    run = store.task_run_start(conn, task["id"], skill="demo-asks", model="m", adapter="h")
    store.task_run_finish(conn, run["run_id"], status="failed", failure="adapter", task_state="failed")
    started = store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")
    with pytest.raises(store.StoreError):
        store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")  # a run row runs
    with pytest.raises(store.StoreError):
        store.request_cancel(conn, request, by="user")  # the router runs on it
    done = store.route_run_finish(conn, started["run_id"], status="ok", ending="done",
                                  pending={"kind": "plan", "title": "Plan", "body": "b", "payload": PAYLOAD})
    assert done["request_id"] == request and store.task_get(conn, request)["state"] == "requested"
    with pytest.raises(store.StoreError):
        store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")  # a plan is open
    with pytest.raises(store.StoreError):
        a_plan(conn, request)  # a second plan
    with pytest.raises(store.StoreError):
        store.route_run_start(conn, task["id"], skill="core-orchestrator", model="m", adapter="h")  # not a request


def test_approving_a_plan_creates_its_tasks_and_only_those_with_no_dependency_are_ready(conn):
    request = a_request(conn)
    pending_id = a_plan(conn, request)
    assert store.task_peek_next(conn) == {"task": None, "running": None}
    with pytest.raises(store.StoreError):
        store.pending_resolve(conn, pending_id, resolution="answered", by="user", answer="go")  # approved, not answered
    out = store.plan_approve(conn, pending_id, by="user")
    assert [(t["key"], t["skill"], t["state"]) for t in out["tasks"]] == [
        ("strategy", "brand-strategy", "ready"), ("name", "brand-name", "planned"), ("identity", "brand-identity", "planned")]
    assert out["ready"] == [out["tasks"][0]["id"]]
    root = store.task_get(conn, request)
    assert (root["state"], root["flow"]) == ("planned", "brand")
    tasks = store.tasks_list(conn, request)[1:]
    assert tasks[1]["depends_on"] == [tasks[0]["id"]] and tasks[0]["milestone"] == 1 and tasks[1]["milestone"] == 0
    assert store.pending_get(conn, pending_id)["resolution"] == "approved"
    peeked = store.task_peek_next(conn)
    assert peeked["task"]["key"] == "strategy" and store.task_get(conn, peeked["task"]["id"])["state"] == "ready"
    with pytest.raises(store.StoreError):
        store.plan_approve(conn, pending_id, by="user")  # resolved already
    one = a_request(conn)
    single = a_plan(conn, one, {"source": "router", "flow": None, "plan_sha256": "b" * 64,
                                "tasks": [{"key": "core-critique", "skill": "core-critique", "title": "Critique",
                                           "text": "", "depends_on": []}]})
    out = store.plan_approve(conn, single, by="user")
    assert out["tasks"][0]["state"] == "ready" and store.task_get(conn, out["tasks"][0]["id"])["text"] == ""


def test_rejecting_a_plan_cancels_the_request(conn):
    request = a_request(conn)
    question = store.route_run_finish(
        conn, store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")["run_id"],
        status="ok", ending="question", pending={"kind": "question", "title": "The router asks", "body": "Q1: which?"})
    opened = store.plan_open(conn, request, title="Plan", body="b", payload=PAYLOAD)
    assert opened["cancelled"] == [question["pending_id"]]
    assert store.pending_get(conn, question["pending_id"])["status"] == "cancelled"
    out = store.plan_reject(conn, opened["pending_id"], by="user", note="Not now.")
    assert out["request"] == request and store.task_get(conn, request)["state"] == "cancelled"
    item = store.pending_get(conn, opened["pending_id"])
    assert (item["status"], item["resolution"], item["answer"]) == ("resolved", "rejected", "Not now.")
    assert store.tasks_list(conn, request) == [store.task_get(conn, request)]  # no task was created


def test_an_answer_to_a_question_of_a_request_never_makes_the_request_ready(conn):
    request = a_request(conn)
    run = store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")
    asked = store.route_run_finish(conn, run["run_id"], status="ok", ending="question",
                                   pending={"kind": "question", "title": "The router asks", "body": "Q1: where?"})
    with pytest.raises(store.StoreError):
        store.pending_resolve(conn, asked["pending_id"], resolution="released", by="user")
    out = store.pending_resolve(conn, asked["pending_id"], resolution="answered", by="user", answer="Here.")
    assert out["task_state"] == "requested" and store.task_get(conn, request)["state"] == "requested"
    assert store.task_claim_next(conn) == {"task": None, "running": None}
    assert store.pending_get(conn, asked["pending_id"])["answer"] == "Here."
    failed = store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h")
    store.route_run_finish(conn, failed["run_id"], status="failed", failure="timeout", error="slow")
    assert store.task_get(conn, request)["state"] == "requested" and store.task_run_get(conn, failed["run_id"])["status"] == "failed"
    assert [r["id"] for r in store.task_runs_of_skill(conn, "core-orchestrator")] == [run["run_id"], failed["run_id"]]


def test_a_document_record_keeps_the_fields_a_put_does_not_name(conn):
    first = store.document_put(conn, "docs/brand/strategy.md", provider="local", remote_id="p1",
                               written_sha256="c" * 64, remote_version="v1")
    assert first["status"] == "mirrored" and first["read_sha256"] is None
    second = store.document_put(conn, "docs/brand/strategy.md", provider="local", read_sha256="d" * 64,
                                remote_version="v2")
    assert (second["remote_id"], second["written_sha256"], second["read_sha256"], second["remote_version"]) == (
        "p1", "c" * 64, "d" * 64, "v2")
    assert store.document_get(conn, "docs/brand/strategy.md") == second and store.document_get(conn, "docs/x.md") is None
    assert [d["path"] for d in store.documents_list(conn)] == ["docs/brand/strategy.md"]
    for bad in ({"status": "lost"}, {"colour": "red"}, {"written_sha256": "short"}):
        with pytest.raises(store.StoreError):
            store.document_put(conn, "docs/brand/strategy.md", provider="local", **bad)
    for path in ("/etc/passwd", "../out.md", "docs//x.md"):
        with pytest.raises(store.StoreError):
            store.document_put(conn, path, provider="local")
    assert store.document_get(conn, "docs/brand/strategy.md") == second


def test_a_comment_is_saved_once_and_used_by_one_pending_decision(conn):
    request = a_request(conn)
    comments = [{"id": "c1", "author": "Ana", "created_at": "2026-10-05T10:00:00Z", "text": "Warmer, please."},
                {"id": "c2", "author": None, "created_at": None, "text": "Shorter."}]
    assert store.comments_save(conn, comments, provider="local", subject="document",
                               document_path="docs/brand/strategy.md") == {"saved": 2}
    assert store.comments_save(conn, comments, provider="local", subject="document",
                               document_path="docs/brand/strategy.md") == {"saved": 0}
    with pytest.raises(store.StoreError):
        store.comments_save(conn, comments, provider="local", subject="task")  # a task's comment names the task
    saved = store.comments_list(conn, document_path="docs/brand/strategy.md")
    assert [c["text"] for c in saved] == ["Warmer, please.", "Shorter."] and saved[0]["status"] == "open"
    pending_id = a_plan(conn, request)
    out = store.comments_use(conn, [saved[0]["id"]], pending_id=pending_id)
    assert out["used"] == [saved[0]["id"]]
    assert [c["id"] for c in store.comments_list(conn)] == [saved[1]["id"]]
    used = store.comments_list(conn, status="used")
    assert used[0]["used_by_pending"] == pending_id
    with pytest.raises(store.StoreError):
        store.comments_use(conn, [saved[1]["id"], saved[0]["id"]], pending_id=pending_id)  # one is used already
    assert store.comments_list(conn)[0]["status"] == "open"  # all or none


def test_a_persons_edit_is_refused_on_a_running_a_done_and_a_cancelled_task(conn):
    out = store.request_add(conn, title="Market", text="Which market?", flow="demo", tasks=[
        {"key": "a", "skill": "demo-asks", "title": "A", "text": "go."},
        {"key": "b", "skill": "demo-writes", "title": "B", "text": "then.", "depends_on": ["a"]}])
    first, second = out["tasks"][0]["id"], out["tasks"][1]["id"]
    edited = store.task_edit(conn, second, by="user", title="B, renamed", text="then, edited.")
    assert (edited["title"], edited["text"]) == ("B, renamed", "then, edited.")
    assert store.task_edit(conn, second, by="user", text="only the text.")["title"] == "B, renamed"
    remote = store.task_remote_set(conn, second, remote_id="t2", remote_version="v1", written_sha256="e" * 64)
    assert (remote["remote_id"], remote["remote_version"], remote["remote_written_sha256"]) == ("t2", "v1", "e" * 64)
    for bad in ({"title": ""}, {"text": "x" * (store.TEXT_MAX + 1)}, {}):
        with pytest.raises(store.StoreError):
            store.task_edit(conn, second, by="user", **bad)
    task = store.task_claim_next(conn)["task"]
    assert task["id"] == first
    with pytest.raises(store.StoreError):
        store.task_edit(conn, first, by="user", title="while it runs")
    run = store.task_run_start(conn, first, skill="demo-asks", model="m", adapter="h")
    done = store.task_run_finish(conn, run["run_id"], status="ok", ending="done", task_state="waiting",
                                 pending={"kind": "review", "title": "t", "body": "b"})
    store.pending_resolve(conn, done["pending_id"], resolution="released", by="user")
    with pytest.raises(store.StoreError):
        store.task_edit(conn, first, by="user", title="when done")
    store.request_cancel(conn, out["request"], by="user")
    with pytest.raises(store.StoreError):
        store.task_edit(conn, second, by="user", title="when cancelled")

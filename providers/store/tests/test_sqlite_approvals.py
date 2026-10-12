"""Offline tests for migration 5 of providers/store/sqlite.py: the approvals table and the resolutions of an `effect`
(limits L13 and L17 of the platform plan). Every name and text below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_approvals.py

The functions are called in process, the way runtime/ops.py calls them; each test has its own database.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_approvals", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

HASH = "a" * 64
OTHER = "b" * 64
PLAN = [{"key": "implement", "skill": "eng-implement", "title": "Implement", "text": "make the change.",
         "depends_on": []},
        {"key": "pull-request", "skill": "ops-pull-request", "title": "Pull request", "text": "open it.",
         "depends_on": ["implement"], "milestone": True}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def run_to(conn, kind: str, digest: str | None = HASH) -> dict:
    """A request of two tasks whose first task is done and whose second waits on one pending decision of `kind`."""
    request = store.request_add(conn, title="Carry the providers", text="The installer of Lumen Desk.", flow="code-change",
                                tasks=PLAN)
    first = store.task_claim_next(conn)["task"]
    run = store.task_run_start(conn, first["id"], skill=first["skill"], model="m", adapter="h")["run_id"]
    done = store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting",
                                 pending={"kind": "review", "title": "Review", "body": "Changed two files."})
    store.pending_resolve(conn, done["pending_id"], resolution="released", by="user")
    second = store.task_claim_next(conn)["task"]
    run = store.task_run_start(conn, second["id"], skill=second["skill"], model="m", adapter="h")["run_id"]
    pending = {"kind": kind, "title": "Pull request: carry the providers", "body": "Repository, base, head, files."}
    if digest is not None:
        pending["payload_sha256"] = digest
    out = store.task_run_finish(conn, run, status="ok", ending="gate", task_state="waiting", pending=pending)
    return {"request": request["request"], "task": second["id"], "pending": out["pending_id"]}


def approve(conn, case: dict, digest: str = HASH) -> dict:
    return store.approval_add(conn, scope="action", what="pull request wb/request-1 into main", by="user",
                              payload_sha256=digest, pending_id=case["pending"])


def open_pending_of(conn, task_id: int) -> list:
    return [p for p in store.pending_list(conn, "open") if p["task_id"] == task_id]


def kept(now, before):
    """Migration 8 adds a column to tasks: every earlier column of every earlier row is what it was, the new one is empty."""
    assert len(now) == len(before)
    return all(row[:len(old)] == old and all(v is None for v in row[len(old):]) for row, old in zip(now, before))


def test_migration_5_adds_the_approvals_table_and_keeps_every_earlier_row(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, "
                "description TEXT NOT NULL)")
    for version in (1, 2, 3, 4):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-01T00:00:00.000000Z', 'before')", (version,))
    old.execute("INSERT INTO tasks (id, title, text, state, created_at, updated_at, remote_id) "
                "VALUES (1, 'Request', 'Old request.', 'planned', 't0', 't0', 'r1')")
    old.execute("INSERT INTO document_records (path, provider, status, updated_at) "
                "VALUES ('docs/brand/strategy.md', 'local', 'mirrored', 't0')")
    old.commit()
    before = {table: [tuple(r) for r in old.execute(f"SELECT * FROM {table} ORDER BY id")]
              for table in ("tasks", "document_records")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 4 and out["applied"] == [5, 6, 7, 8, 9] and out["schema_version"] == 9
    conn = store.open_db(path)
    for table, rows in before.items():
        assert kept([tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY id")], rows)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "approvals" in names and store.approvals_list(conn) == []


def test_an_action_approval_binds_the_open_effect_by_its_hash(conn):
    case = run_to(conn, "effect")
    row = approve(conn, case)
    assert row["existing"] is False
    assert (row["scope"], row["status"], row["payload_sha256"], row["pending_id"], row["task_id"]) == (
        "action", "pending-execution", HASH, case["pending"], case["task"])
    assert row["approved_by"] == "user" and row["executed_at"] is None and row["bounds"] is None
    assert store.approval_get(conn, row["id"]) == {k: v for k, v in row.items() if k != "existing"}
    assert store.approvals_list(conn, status="pending-execution", task_id=case["task"])[0]["id"] == row["id"]
    # The approval alone moves nothing: the task still waits on its one open effect until code executed it.
    assert store.task_get(conn, case["task"])["state"] == "waiting"
    assert store.pending_get(conn, case["pending"])["status"] == "open"


def test_an_approval_with_another_hash_or_for_a_closed_pending_decision_is_refused(conn):
    case = run_to(conn, "effect")
    with pytest.raises(store.StoreError, match="nothing was approved"):
        approve(conn, case, OTHER)
    with pytest.raises(store.StoreError, match="needs pending_id"):
        store.approval_add(conn, scope="action", what="x", by="user", payload_sha256=HASH)
    with pytest.raises(store.StoreError):
        store.approval_add(conn, scope="standing", what="x", by="user", bounds={"branch": "wb/*"})
    store.pending_resolve(conn, case["pending"], resolution="rejected", by="user")
    with pytest.raises(store.StoreError, match="open effect"):
        approve(conn, case)
    review = run_to(conn, "review", None)
    with pytest.raises(store.StoreError, match="open effect"):
        approve(conn, review)
    assert store.approvals_list(conn) == []


def test_approving_twice_returns_the_same_row(conn):
    case = run_to(conn, "effect")
    first = approve(conn, case)
    again = approve(conn, case)
    assert again["existing"] is True and again["id"] == first["id"]
    assert len(store.approvals_list(conn)) == 1


def test_effect_done_resolves_the_pending_decision_marks_the_approval_executed_and_completes_the_task_all_or_nothing(conn):
    case = run_to(conn, "effect")
    row = approve(conn, case)
    other = run_to(conn, "effect")
    foreign = approve(conn, other)
    result = {"commit": "c" * 40, "pull_request": {"number": 7, "url": "https://example.test/pull/7"}}
    with pytest.raises(store.StoreError, match="not the approval"):
        store.effect_done(conn, case["pending"], foreign["id"], by="user", result=result)
    # Refused, so nothing moved: the effect is open, both approvals wait, the task waits.
    assert store.pending_get(conn, case["pending"])["status"] == "open"
    assert {a["status"] for a in store.approvals_list(conn)} == {"pending-execution"}
    assert store.task_get(conn, case["task"])["state"] == "waiting"
    out = store.effect_done(conn, case["pending"], row["id"], by="user", result=result)
    assert out["task_state"] == "done" and out["completed"] == [case["request"]]
    item = store.pending_get(conn, case["pending"])
    assert (item["status"], item["resolution"], item["payload"]["result"]) == ("resolved", "approved", result)
    executed = store.approval_get(conn, row["id"])
    assert executed["status"] == "executed" and executed["executed_at"]
    assert store.task_get(conn, case["request"])["state"] == "done"
    with pytest.raises(store.StoreError):
        store.effect_done(conn, case["pending"], row["id"], by="user", result=result)


def test_answering_or_rejecting_an_effect_revokes_its_approval(conn):
    answered = run_to(conn, "effect")
    first = approve(conn, answered)
    out = store.pending_resolve(conn, answered["pending"], resolution="answered", by="user",
                                answer="Name the new flag in the body.")
    assert out["task_state"] == "ready" and store.approval_get(conn, first["id"])["status"] == "revoked"
    rejected = run_to(conn, "effect")
    second = approve(conn, rejected)
    out = store.pending_resolve(conn, rejected["pending"], resolution="rejected", by="user")
    assert out["task_state"] == "cancelled" and store.approval_get(conn, second["id"])["status"] == "revoked"
    cancelled = run_to(conn, "effect")
    third = approve(conn, cancelled)
    store.request_cancel(conn, cancelled["request"], by="user")
    assert store.approval_get(conn, third["id"])["status"] == "revoked"
    for wrong in ("approved", "released"):
        effect = run_to(conn, "effect")
        with pytest.raises(store.StoreError):
            store.pending_resolve(conn, effect["pending"], resolution=wrong, by="user")
    review = run_to(conn, "review", None)
    with pytest.raises(store.StoreError, match="only an effect is rejected"):
        store.pending_resolve(conn, review["pending"], resolution="rejected", by="user")


def test_limit_13_an_approval_is_never_deleted_and_its_status_only_moves_forward(conn):
    case = run_to(conn, "effect")
    action = approve(conn, case)
    standing = store.approval_add(conn, scope="standing", what="push wb/* and open their pull requests", by="user",
                                  bounds={"branches": "wb/*"}, policy_sha256=OTHER, expires_at="2027-01-01T00:00:00Z")
    plan = store.approval_add(conn, scope="plan", what="the posts of one week", by="user", payload_sha256=OTHER)
    assert (standing["status"], plan["status"], standing["bounds"]) == ("active", "pending-execution", {"branches": "wb/*"})
    assert store.approvals_expire(conn, "2026-12-31T23:59:59Z") == 0
    assert store.approvals_expire(conn, "2027-01-02") == 1
    assert store.approval_get(conn, standing["id"])["status"] == "expired"
    for frozen in (standing["id"],):
        with pytest.raises(store.StoreError, match="only moves forward"):
            store.approval_revoke(conn, frozen, by="user")
    assert store.approval_revoke(conn, plan["id"], by="user")["status"] == "revoked"
    with pytest.raises(store.StoreError, match="only moves forward"):
        store.approval_revoke(conn, plan["id"], by="user")
    # The database refuses a deletion, a change of content and a backward move, whoever writes the SQL.
    for statement, args in (("DELETE FROM approvals WHERE id = ?", (action["id"],)),
                            ("UPDATE approvals SET payload_sha256 = ? WHERE id = ?", (OTHER, action["id"])),
                            ("UPDATE approvals SET status = 'active' WHERE id = ?", (plan["id"],)),
                            ("UPDATE approvals SET status = 'pending-execution' WHERE id = ?", (standing["id"],))):
        with pytest.raises(sqlite3.DatabaseError):
            with conn:
                conn.execute(statement, args)
    assert len(store.approvals_list(conn)) == 3
    assert store.approval_get(conn, action["id"])["payload_sha256"] == HASH


def test_a_waiting_task_has_exactly_one_open_pending_decision_on_every_path_of_an_effect(conn):
    def check(case):
        task = store.task_get(conn, case["task"])
        assert len(open_pending_of(conn, case["task"])) == (1 if task["state"] == "waiting" else 0), task["state"]

    executed = run_to(conn, "effect")
    check(executed)
    row = approve(conn, executed)
    check(executed)
    store.effect_done(conn, executed["pending"], row["id"], by="user", result={"commit": "c" * 40})
    check(executed)
    answered = run_to(conn, "effect")
    approve(conn, answered)
    store.pending_resolve(conn, answered["pending"], resolution="answered", by="user", answer="Shorter title.")
    check(answered)
    rejected = run_to(conn, "effect")
    store.pending_resolve(conn, rejected["pending"], resolution="rejected", by="user")
    check(rejected)
    cancelled = run_to(conn, "effect")
    store.request_cancel(conn, cancelled["request"], by="user")
    check(cancelled)


def test_a_database_at_the_earlier_version_is_refused_until_init_migrates_it(tmp_path, monkeypatch):
    path = tmp_path / "earlier.sqlite"
    monkeypatch.setattr(store, "SCHEMA_VERSION", 4)
    monkeypatch.setattr(store, "MIGRATIONS", {k: v for k, v in store.MIGRATIONS.items() if k <= 4})
    store.init_db(path)
    monkeypatch.undo()
    with pytest.raises(store.StoreError) as refused:
        store.open_db(path)
    assert refused.value.code == store.EXIT_NOT_CONFIGURED
    assert store.init_db(path)["applied"] == [5, 6, 7, 8, 9]
    assert store.approvals_list(store.open_db(path)) == []

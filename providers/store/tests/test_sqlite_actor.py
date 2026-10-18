"""Offline tests for migration 17 of providers/store/sqlite.py (package POL-2): the `actor` column of pending_decisions and of approvals. A store at 16
migrating with every row kept and no other table touched, the actor recorded by every function that resolves a decision or makes an approval, the
approvals trigger that now refuses to change it, and the cap of the text. Every name and id below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_actor.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_actor", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

HASH = "a" * 64
ACTOR = "messaging:whatsapp-cloud:staff:55119000000002"
PLAN = [{"key": "implement", "skill": "eng-implement", "title": "Implement", "text": "make the change.", "depends_on": []},
        {"key": "pull-request", "skill": "ops-pull-request", "title": "Pull request", "text": "open it.", "depends_on": ["implement"], "milestone": True}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def claim(conn):
    row = conn.execute(store.NEXT_READY_TASK).fetchone()
    return store.task_claim(conn, row["id"])["task"]


def effect_case(conn, digest=HASH):
    """A request whose second task waits on one open effect."""
    request = store.request_add(conn, title="Carry the providers", text="The installer of Lumen Desk.", flow="code-change", tasks=PLAN)
    first = claim(conn)
    run = store.task_run_start(conn, first["id"], skill=first["skill"], model="m", adapter="h")["run_id"]
    done = store.task_run_finish(conn, run, status="ok", ending="done", task_state="waiting", pending={"kind": "review", "title": "Review", "body": "Two files."})
    store.pending_resolve(conn, done["pending_id"], resolution="released", by="user")
    second = claim(conn)
    run = store.task_run_start(conn, second["id"], skill=second["skill"], model="m", adapter="h")["run_id"]
    out = store.task_run_finish(conn, run, status="ok", ending="gate", task_state="waiting",
                                pending={"kind": "effect", "title": "Pull request", "body": "Files.", "payload_sha256": digest})
    return {"request": request["request"], "pending": out["pending_id"], "review": done["pending_id"]}


def test_a_store_at_16_migrates_to_17_keeps_every_row_adds_two_columns_and_touches_no_other_table(tmp_path):
    path = tmp_path / "sixteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 17):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO tasks (parent_id, title, text, state, created_at, updated_at) VALUES (1, 'T', 'T.', 'waiting', 'a', 'a')")
    old.execute("INSERT INTO pending_decisions (task_id, kind, title, body, payload_sha256, created_at) VALUES (2, 'effect', 't', 'b', ?, 'a')", (HASH,))
    old.execute("INSERT INTO approvals (scope, what, payload_sha256, task_id, pending_id, approved_at, approved_by, status) "
                "VALUES ('action', 'w', ?, 2, 1, 'a', 'user', 'pending-execution')", (HASH,))
    old.commit()
    tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = {t: [r[1] for r in old.execute(f"PRAGMA table_info({t})")] for t in tables}
    before = {t: [tuple(r) for r in old.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in ("tasks", "pending_decisions", "approvals")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 16 and out["applied"] == [17, 18, 19, 21] and out["schema_version"] == 21
    conn = store.open_db(path)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables | {"attachments"}, "migration 18 adds its one table and drops none"
    for table, names in columns.items():
        now = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        assert now == names + (["actor"] if table in ("pending_decisions", "approvals") else []) + (["provenance"] if table == "source_versions" else []), table     # only these gain a column
    for table, rows in before.items():
        after = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
        assert [row[:len(old_row)] for row, old_row in zip(after, rows)] == rows, table
        assert table not in ("pending_decisions", "approvals") or all(row[-1] is None for row in after), "a row older than the column has no actor"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.init_db(path)["applied"] == []


def test_the_approvals_trigger_refuses_to_change_the_actor_as_it_refuses_every_column_but_the_status(conn):
    case = effect_case(conn)
    row = store.approval_add(conn, scope="action", what="pull request", by="user", payload_sha256=HASH, pending_id=case["pending"], actor=ACTOR)
    assert row["actor"] == ACTOR and row["approved_by"] == "user"
    with pytest.raises(sqlite3.DatabaseError, match="only moves forward"):
        conn.execute("UPDATE approvals SET actor = 'page' WHERE id = ?", (row["id"],))
    with pytest.raises(sqlite3.DatabaseError, match="only moves forward"):
        conn.execute("UPDATE approvals SET actor = NULL WHERE id = ?", (row["id"],))
    with pytest.raises(sqlite3.DatabaseError, match="only moves forward"):
        conn.execute("UPDATE approvals SET approved_by = 'someone' WHERE id = ?", (row["id"],))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM approvals WHERE id = ?", (row["id"],))
    store.effect_done(conn, case["pending"], row["id"], by="user", result={"commit": "c" * 40}, actor=ACTOR)     # the status moves; the actor stays
    assert store.approval_get(conn, row["id"])["actor"] == ACTOR and store.approval_get(conn, row["id"])["status"] == "executed"


def test_every_resolution_records_the_actor_beside_the_kind_of_actor_it_always_recorded(conn):
    case = effect_case(conn)
    row = store.approval_add(conn, scope="action", what="pull request", by="user", payload_sha256=HASH, pending_id=case["pending"], actor=ACTOR)
    done = store.effect_done(conn, case["pending"], row["id"], by="user", result={"commit": "c" * 40}, actor=ACTOR)
    got = store.pending_get(conn, case["pending"])
    assert done["task_state"] == "done" and got["actor"] == ACTOR and got["resolved_by"] == "user" and got["resolution"] == "approved"
    review = store.pending_get(conn, case["review"])
    assert review["actor"] is None and review["resolved_by"] == "user", "a call that names no actor records none"
    # a plan approved, a plan rejected, an acceptance accepted and rejected, a question answered, a review released, an effect rejected
    plan = store.plan_open(conn, store.request_add(conn, title="P", text="P.")["request"], title="Plan", body="b",
                           payload={"tasks": PLAN[:1], "plan_sha256": "p" * 64, "flow": None})["pending_id"]
    store.plan_approve(conn, plan, by="user", actor=ACTOR)
    assert store.pending_get(conn, plan)["actor"] == ACTOR
    plan = store.plan_open(conn, store.request_add(conn, title="Q", text="Q.")["request"], title="Plan", body="b",
                           payload={"tasks": PLAN[:1], "plan_sha256": "q" * 64, "flow": None})["pending_id"]
    store.plan_reject(conn, plan, by="user", note="no", actor="page")
    assert store.pending_get(conn, plan)["actor"] == "page" and store.pending_get(conn, plan)["answer"] == "no"
    for resolution, actor in (("accepted", "terminal"), ("rejected", ACTOR)):
        task = store.request_add(conn, title="R", text="R.")["request"]
        item = store.acceptance_open(conn, task_id=task, what="deliveries", title="Accept", body="b", payload={})["pending_id"]
        store.acceptance_resolve(conn, item, resolution=resolution, by="user", actor=actor)
        assert store.pending_get(conn, item)["actor"] == actor
    other = effect_case(conn, "b" * 64)
    store.pending_resolve(conn, other["pending"], resolution="rejected", by="user", answer="no", actor="mcp")
    assert store.pending_get(conn, other["pending"])["actor"] == "mcp"


def test_the_actor_is_a_bounded_text_and_a_store_that_is_asked_nothing_records_none(conn):
    case = effect_case(conn)
    for bad in ("x" * (store.ACTOR_MAX + 1), "line\nbreak"):
        with pytest.raises(store.StoreError):
            store.pending_resolve(conn, case["pending"], resolution="rejected", by="user", answer="no", actor=bad)
        with pytest.raises(store.StoreError):
            store.approval_add(conn, scope="action", what="w", by="user", payload_sha256=HASH, pending_id=case["pending"], actor=bad)
    assert store.pending_get(conn, case["pending"])["status"] == "open", "a refusal records nothing"
    store.pending_resolve(conn, case["pending"], resolution="rejected", by="user", answer="no")
    assert store.pending_get(conn, case["pending"])["actor"] is None
    assert store.ACTOR_MAX >= len("messaging:") + 32 + 1 + 32 + 1 + 64, "a platform, a profile and an id at their longest fit"


def test_the_rebuilt_trigger_keeps_every_rule_of_the_old_one_for_a_row_that_was_there_before_the_migration(tmp_path):
    path = tmp_path / "sixteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 17):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO approvals (scope, what, policy_sha256, bounds, approved_at, approved_by, status) "
                "VALUES ('standing', 'x', ?, '{}', '2026-01-01T00:00:00Z', 'user', 'active')", (HASH,))
    old.commit()
    old.close()
    store.init_db(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT actor FROM approvals").fetchall() == [(None,)], "a row older than the column has no actor"
    for statement in ("UPDATE approvals SET actor = 'messaging:telegram:owner:1' WHERE id = 1", "UPDATE approvals SET what = 'y' WHERE id = 1"):
        with pytest.raises(sqlite3.DatabaseError, match="only moves forward"):
            conn.execute(statement)
    conn.execute("UPDATE approvals SET status = 'revoked' WHERE id = 1")          # a status still moves forward
    with pytest.raises(sqlite3.DatabaseError, match="only moves forward"):
        conn.execute("UPDATE approvals SET status = 'active' WHERE id = 1")
    assert [r[1] for r in conn.execute("PRAGMA table_info(pending_decisions)")][-1] == "actor"

"""Offline tests for migration 10 of providers/store/sqlite.py (package P3, decisions D3 and D38): a request and a task carry
the model that was chosen for them, and a run carries how its pair was released (proven, by consent, or supervised). Every
name is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_model_choice.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_model_choice", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

PLAN = [{"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do the market analysis."}]


def claim_oldest(conn):
    row = conn.execute(store.NEXT_READY_TASK).fetchone()
    return store.task_claim(conn, row["id"]) if row else {"task": None}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def test_a_database_made_today_has_both_columns_and_the_closed_set_of_autonomies(tmp_path):
    out = store.init_db(tmp_path / "fresh.sqlite")
    assert out["schema_version"] == 19 and out["applied"][-1] == 19
    conn = store.open_db(tmp_path / "fresh.sqlite")
    tasks = {row[1]: row for row in conn.execute("PRAGMA table_info(tasks)")}
    runs = {row[1]: row for row in conn.execute("PRAGMA table_info(task_runs)")}
    assert tasks["model"][2] == "TEXT" and tasks["model"][3] == 0, "text, and null is allowed"
    assert runs["autonomy"][2] == "TEXT" and runs["autonomy"][3] == 0
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'task_runs'").fetchone()[0]
    for word in store.RUN_AUTONOMIES:
        assert f"'{word}'" in sql, "the column is checked against the closed set"
    assert store.RUN_AUTONOMIES == ("proven", "consent", "supervised")


def test_migration_10_keeps_every_earlier_row_and_leaves_the_new_columns_empty(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 10):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-01T00:00:00.000000Z', 'before')", (version,))
    old.execute("INSERT INTO tasks (id, title, text, state, created_at, updated_at) VALUES (1, 'Request', 'Old.', 'planned', 't0', 't0')")
    old.execute("INSERT INTO task_runs (id, task_id, skill, model, adapter, status, started_at, cost_usd, billing) "
                "VALUES (1, 1, 'biz-market-analysis', 'm', 'h', 'ok', '2026-10-09T10:00:00.000000Z', 0.25, 'metered')")
    old.commit()
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 9 and out["applied"] == [10, 11, 12, 13, 14, 15, 16, 17, 18, 19] and out["schema_version"] == 19
    conn = store.open_db(path)
    task = conn.execute("SELECT id, title, model FROM tasks").fetchone()
    assert tuple(task) == (1, "Request", None), "an old request names no model"
    run = conn.execute("SELECT id, model, cost_usd, billing, autonomy FROM task_runs").fetchone()
    assert tuple(run) == (1, "m", 0.25, "metered", None), "an old run keeps its row and has no autonomy"
    assert store.init_db(path)["applied"] == [], "idempotent"


def test_a_database_of_version_9_is_refused_by_every_verb_until_init_migrates_it(tmp_path):
    path = tmp_path / "old.sqlite"
    store.init_db(path)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE tasks DROP COLUMN model")
    conn.execute("DROP TABLE task_runs")
    conn.execute("DELETE FROM schema_version WHERE version >= 10")
    conn.commit()
    conn.close()
    with pytest.raises(store.StoreError) as refused:
        store.open_db(path)
    assert "schema version 9" in str(refused.value)


def test_a_request_carries_its_model_and_its_tasks_start_without_one(conn):
    with_model = store.request_add(conn, title="A", text="Invented request.", flow="demo", tasks=PLAN, model="acme-model-1")
    without = store.request_add(conn, title="B", text="Another invented request.")
    assert store.task_get(conn, with_model["request"])["model"] == "acme-model-1"
    assert store.task_get(conn, without["request"])["model"] is None
    assert store.request_add(conn, title="C", text="Invented.", model="auto")["request"]
    with pytest.raises(store.StoreError):
        store.request_add(conn, title="D", text="Invented.", model="x" * 600)


def test_a_run_records_how_its_pair_was_released(conn):
    store.request_add(conn, title="A", text="Invented request.", flow="demo", tasks=PLAN)
    task = claim_oldest(conn)["task"]
    store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", autonomy="consent")
    assert store.task_runs_list(conn, task["id"])[0]["autonomy"] == "consent"


@pytest.mark.parametrize("word", ["proven", "consent", "supervised", None])
def test_every_word_of_the_closed_set_and_none_is_accepted(conn, word):
    store.request_add(conn, title="A", text="Invented request.", flow="demo", tasks=PLAN)
    task = claim_oldest(conn)["task"]
    store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", autonomy=word)
    assert store.task_runs_list(conn, task["id"])[0]["autonomy"] == word


def test_a_word_outside_the_set_is_refused_before_anything_is_written_and_by_the_column_itself(conn):
    store.request_add(conn, title="A", text="Invented request.", flow="demo", tasks=PLAN)
    task = claim_oldest(conn)["task"]
    with pytest.raises(store.StoreError):
        store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", autonomy="trusted")
    assert store.task_runs_list(conn, task["id"]) == []
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, autonomy) "
                     "VALUES (?, 's', 'm', 'h', '2026-10-15T10:00:00.000000Z', 'trusted')", (task["id"],))

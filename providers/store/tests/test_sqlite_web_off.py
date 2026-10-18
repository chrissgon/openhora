"""Offline tests for the task that runs its skill without the web (providers/store/sqlite.py, P6a, migration 13): the column, a store at
12 migrating with every row kept, the word travelling from a plan to the task row, and a step task refusing it. Every name and text
below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_web_off.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_web_off", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def plan(**extra):
    return [{"key": "research", "skill": "core-research", "title": "Research", "text": "Research it."},
            {"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Size it.", "depends_on": ["research"], **extra}]


def test_a_store_at_12_migrates_to_13_keeps_every_row_and_the_new_column_is_empty(tmp_path):
    path = tmp_path / "twelve.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 13):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('Old', 'An old request.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO tasks (parent_id, key, skill, agent, title, text, state, created_at, updated_at) "
                "VALUES (1, 'market', 'biz-market-analysis', 'business', 'Market', 'x', 'ready', 'a', 'a')")
    old.commit()
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 12 and out["applied"] == [13, 14, 15, 16, 17, 18, 19, 20, 21] and out["schema_version"] == 21
    conn = store.open_db(path)
    task = store.task_get(conn, 2)
    assert task["skill"] == "biz-market-analysis" and task["title"] == "Market" and task["state"] == "ready" and task["web_off"] is None
    assert store.task_get(conn, 1)["web_off"] is None


def test_the_column_takes_one_or_nothing_and_nothing_else(conn):
    made = store.request_add(conn, title="R", text="R.", flow="demo", tasks=plan())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tasks SET web_off = 0 WHERE id = ?", (made["tasks"][0]["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE tasks SET web_off = 2 WHERE id = ?", (made["tasks"][0]["id"],))


def test_the_word_web_off_of_a_plan_task_is_kept_on_its_row_through_a_request_and_through_an_approved_plan(conn):
    made = store.request_add(conn, title="R", text="R.", flow="demo", tasks=plan(web_off=True))
    rows = {t["key"]: t for t in store.tasks_list(conn) if t["parent_id"] == made["request"]}
    assert rows["market"]["web_off"] == 1 and rows["research"]["web_off"] is None
    request = store.request_add(conn, title="Q", text="Q.")["request"]
    opened = store.plan_open(conn, request, title="Plan", body="b", payload={"flow": "demo", "tasks": plan(web_off=True)})
    store.plan_approve(conn, opened["pending_id"], by="user")
    rows = {t["key"]: t for t in store.tasks_list(conn) if t["parent_id"] == request}
    assert rows["market"]["web_off"] == 1 and rows["research"]["web_off"] is None
    assert [t["web_off"] for t in store.tasks_list(conn) if t["parent_id"] is None] == [None, None]


def test_a_step_task_has_no_web_to_switch_off(conn):
    item = {"key": "ingest-survey", "step": "ingest", "args": {"source": "survey"}, "footprint": [], "title": "Ingest",
            "text": "Bring it in.", "web_off": True}
    with pytest.raises(store.StoreError, match="a step task has no web to switch off"):
        store.request_add(conn, title="R", text="R.", flow="demo", tasks=[item])

"""Offline tests for migration 9 of providers/store/sqlite.py (package ADJ-R3, row A-38): the billing of the credential a
run used is a column of task_runs, written when the run starts, and the day's runs carry it. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_billing.py
"""
from __future__ import annotations

import datetime
import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_billing", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

WORDS = ("subscription", "metered", "free", "unknown")
PLAN = [{"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do the market analysis."}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def claimed(conn):
    store.request_add(conn, title="Request", text="Invented request.", flow="demo", tasks=PLAN)
    return store.task_claim_next(conn)["task"]


def test_migration_9_adds_the_billing_column_and_a_database_made_today_has_it(tmp_path):
    out = store.init_db(tmp_path / "fresh.sqlite")
    assert out["schema_version"] == 9 and out["applied"][-1] == 9
    conn = store.open_db(tmp_path / "fresh.sqlite")
    columns = {row[1]: row for row in conn.execute("PRAGMA table_info(task_runs)")}
    assert "billing" in columns and columns["billing"][2] == "TEXT" and columns["billing"][3] == 0, "text, and null is allowed"


def test_migration_9_keeps_every_earlier_run_and_leaves_its_billing_empty(tmp_path):
    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 9):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-01T00:00:00.000000Z', 'before')", (version,))
    old.execute("INSERT INTO tasks (id, title, text, state, created_at, updated_at) VALUES (1, 'Request', 'Old.', 'planned', 't0', 't0')")
    old.execute("INSERT INTO task_runs (id, task_id, skill, model, adapter, status, started_at, cost_usd) "
                "VALUES (1, 1, 'biz-market-analysis', 'm', 'h', 'ok', '2026-10-09T10:00:00.000000Z', 0.25)")
    old.commit()
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 8 and out["applied"] == [9] and out["schema_version"] == 9
    conn = store.open_db(path)
    row = conn.execute("SELECT id, model, cost_usd, billing FROM task_runs").fetchone()
    assert tuple(row) == (1, "m", 0.25, None)
    assert store.init_db(path)["applied"] == [], "idempotent"


@pytest.mark.parametrize("word", WORDS)
def test_a_run_starts_with_the_billing_it_is_given(conn, word):
    task = claimed(conn)
    run = store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", billing=word)
    assert store.task_runs_list(conn, task["id"])[0]["billing"] == word
    assert run["run_id"] == store.task_runs_list(conn, task["id"])[0]["id"]


def test_a_run_started_without_a_billing_has_none_and_a_word_outside_the_three_is_refused(conn):
    task = claimed(conn)
    store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h")
    assert store.task_runs_list(conn, task["id"])[0]["billing"] is None
    for bad in ("prepaid", "", "Metered", 3):
        with pytest.raises(store.StoreError) as refused:
            store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", billing=bad)
        assert refused.value.code == store.EXIT_USAGE and "billing" in str(refused.value)


def test_the_column_itself_refuses_a_word_outside_the_three(conn):
    task = claimed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, billing) "
                     "VALUES (?, 's', 'm', 'h', 't0', 'prepaid')", (task["id"],))
    conn.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, billing) VALUES (?, 's', 'm', 'h', 't0', NULL)",
                 (task["id"],))   # null is the run that is older than the column


def test_a_router_run_records_its_billing_the_same_way(conn):
    request = store.request_add(conn, title="Request", text="Invented request.")["request"]
    run = store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h", billing="metered")
    assert store.task_runs_list(conn, request)[0]["billing"] == "metered" and run["run_id"]
    with pytest.raises(store.StoreError):
        store.route_run_start(conn, request, skill="core-orchestrator", model="m", adapter="h", billing="prepaid")


def test_the_runs_of_the_day_carry_the_billing(conn):
    task = claimed(conn)
    store.task_run_start(conn, task["id"], skill=task["skill"], model="m", adapter="h", billing="subscription")
    start = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    [row] = store.runs_since(conn, start)
    assert row["billing"] == "subscription" and {"id", "agent", "model", "cost_usd", "billing"} <= set(row)

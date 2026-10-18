"""Offline tests for the language a request or a task asks its deliverable in, in providers/store/sqlite.py (package LANGUAGE, migration 16):
a store at 15 migrating with every row kept, the column and the check that guards it, the request that records the person's choice, and
the plan whose tasks carry their own language to the task rows when the plan is approved. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_language.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_language", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

TASKS = [{"key": "a", "skill": "demo-a", "title": "A", "text": "do a."}, {"key": "b", "skill": "demo-b", "title": "B", "text": "do b.",
                                                                          "depends_on": ["a"]}]


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def languages(conn, parent=None):
    return [r["language"] for r in store.tasks_list(conn) if r["parent_id"] == parent]


# --- migration 16 ---------------------------------------------------------------------------------------------------------


def test_a_store_at_15_migrates_to_16_keeps_every_row_and_adds_the_language_column(tmp_path):
    path = tmp_path / "fifteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 16):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO tasks (title, text, state, model, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'auto', 'a', 'a')")
    old.execute("INSERT INTO tasks (parent_id, title, text, state, created_at, updated_at) VALUES (1, 'T', 'T.', 'ready', 'a', 'a')")
    old.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, status, billing) VALUES (2, 's', 'm', 'h', 'a', 'ok', 'metered')")
    old.commit()
    before = {t: [tuple(r) for r in old.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in ("tasks", "task_runs")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 15 and out["applied"] == [16, 17, 18, 19] and out["schema_version"] == 19
    conn = store.open_db(path)
    after = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1")] for t in ("tasks", "task_runs")}
    assert after["task_runs"] == before["task_runs"]
    assert [row[:-1] for row in after["tasks"]] == before["tasks"], "every task row is as it was, with the one new column last"
    assert [r["name"] for r in conn.execute("PRAGMA table_info(tasks)")][-1] == "language"
    assert [r["language"] for r in conn.execute("SELECT language FROM tasks")] == [None, None], "a row older than the column asked for no language"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.init_db(path)["applied"] == []


def test_the_column_admits_a_tag_or_nothing_and_the_store_refuses_the_rest_before_the_database_does(conn):
    for tag in ("en", "pt-BR", "en-US"):
        made = store.request_add(conn, title="R", text="Do it.", language=tag)
        assert store.task_get(conn, made["request"])["language"] == tag
    for bad in ("pt_BR", "pt-br", "portuguese", "es-419", "zh-Hant-TW", "e", " en", "EN"):
        with pytest.raises(store.StoreError, match="language must be a language tag"):
            store.request_add(conn, title="R", text="Do it.", language=bad)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO tasks (title, text, state, language, created_at, updated_at) VALUES ('R', 'R.', 'requested', ?, 'a', 'a')", (bad,))
    made = store.request_add(conn, title="R", text="Do it.")
    assert store.task_get(conn, made["request"])["language"] is None


def test_the_stores_rule_is_the_runtimes_written_again():
    runtime = Path(__file__).resolve().parents[3] / "runtime" / "language.py"
    text = runtime.read_text(encoding="utf-8")
    assert 'RULE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")' in text
    assert store.LANGUAGE_RE.pattern == "[a-z]{2}(?:-[A-Z]{2})?"


# --- the request and the plan ----------------------------------------------------------------------------------------------


def test_a_request_with_a_plan_of_its_own_languages_gives_each_task_its_own(conn):
    plan = [dict(TASKS[0], language="en"), dict(TASKS[1])]
    made = store.request_add(conn, title="Two jobs", text="Do the jobs.", flow="x", tasks=plan, language="pt-BR")
    assert store.task_get(conn, made["request"])["language"] == "pt-BR"
    assert languages(conn, made["request"]) == ["en", None], "a task carries the language its plan item names; the request's own does not spread by itself"
    with pytest.raises(store.StoreError, match="language must be a language tag"):
        store.request_add(conn, title="R", text="Do it.", flow="x", tasks=[dict(TASKS[0], language="pt_BR")])


def test_approving_a_plan_copies_the_language_of_its_tasks_onto_the_task_rows(conn):
    made = store.request_add(conn, title="Two jobs", text="Do the jobs.", language="en")
    opened = store.plan_open(conn, made["request"], title="Plan", body="Plan.",
                             payload={"flow": "x", "tasks": [dict(t, language="en") for t in TASKS]})
    store.plan_approve(conn, opened["pending_id"], by="user")
    assert languages(conn, made["request"]) == ["en", "en"]
    other = store.request_add(conn, title="Two more", text="Do the jobs.")
    opened = store.plan_open(conn, other["request"], title="Plan", body="Plan.", payload={"flow": "x", "tasks": TASKS})
    store.plan_approve(conn, opened["pending_id"], by="user")
    assert languages(conn, other["request"]) == [None, None]


def test_a_task_added_later_to_a_request_keeps_the_language_it_is_given(conn):
    made = store.request_add(conn, title="Two jobs", text="Do the jobs.", flow="x", tasks=TASKS[:1])
    store.tasks_add(conn, made["request"], [dict(TASKS[1], depends_on=[], language="fr")])
    assert languages(conn, made["request"]) == [None, "fr"]

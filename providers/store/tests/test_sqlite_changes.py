"""Offline tests for the store's change counter (WP-9.13): a number in the database file's header that grows on every write
transaction that changed a row, so that a reader can tell with one cheap read whether anything was written since it last
looked. Every name and text below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_changes.py

The functions are called in process, the way runtime/ops.py calls them; each test has its own database.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_changes", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


@pytest.fixture
def path(tmp_path):
    db = tmp_path / "state" / "tasks.sqlite"
    store.init_db(db)
    return db


@pytest.fixture
def conn(path):
    return store.open_db(path)


def test_a_write_that_changes_a_row_raises_the_counter_by_one(conn):
    before = store.change_counter(conn)
    store.request_add(conn, title="Sale page", text="Add a sale page.")
    assert store.change_counter(conn) == before + 1
    store.message_add(conn, conversation="project", role="user", text="hello")
    assert store.change_counter(conn) == before + 2


def test_every_kind_of_write_of_the_task_runtime_raises_it(conn):
    seen = [store.change_counter(conn)]

    def moved(label):
        seen.append(store.change_counter(conn))
        assert seen[-1] > seen[-2], f"{label} did not raise the counter"

    request = store.request_add(conn, title="Sale page", text="Add a sale page.", flow="single", tasks=[
        {"key": "a", "skill": "eng-implement", "title": "Build", "text": "build it.", "depends_on": []}])
    moved("a request with its plan")
    store.cursor_set(conn, "x", "y")
    moved("a cursor")
    task = store.task_claim_next(conn)["task"]
    moved("a claim (the task runs)")
    run = store.task_run_start(conn, task["id"], skill="eng-implement", model="m", adapter="h")["run_id"]
    moved("the start of a run")
    done = store.task_run_finish(conn, run, status="ok", ending="question", task_state="waiting",
                                 pending={"kind": "question", "title": "Which colour?", "body": "Which?"})
    moved("the end of a run")
    store.pending_resolve(conn, done["pending_id"], resolution="answered", by="user", answer="blue")
    moved("an answer")


def test_a_transaction_that_changes_nothing_leaves_the_counter_alone(conn):
    before = store.change_counter(conn)
    assert store.task_claim_next(conn)["task"] is None      # a dispatcher tick with nothing ready opens a write transaction
    store.tasks_list(conn)
    store.pending_list(conn)
    assert store.change_counter(conn) == before


def test_a_transaction_that_is_rolled_back_leaves_it_alone(conn):
    before = store.change_counter(conn)
    with pytest.raises(RuntimeError):
        with store.write(conn):
            conn.execute("INSERT INTO cursors (name, value, updated_at) VALUES ('a', 'b', 'c')")
            raise RuntimeError("the step failed")
    assert store.change_counter(conn) == before


def test_another_connection_reads_the_number_the_writer_committed(path):
    writer, reader = store.open_db(path), store.open_db(path)
    before = store.change_counter(reader)
    store.request_add(writer, title="Sale page", text="Add a sale page.")
    assert store.change_counter(reader) == before + 1


def test_the_number_wraps_to_one_after_the_largest_value_the_header_holds(conn):
    conn.execute("PRAGMA user_version = 2147483647")
    store.request_add(conn, title="Sale page", text="Add a sale page.")
    assert store.change_counter(conn) == 1


def test_a_database_that_never_had_a_counter_reads_zero_and_still_works(tmp_path):
    db = tmp_path / "old.sqlite"
    plain = sqlite3.connect(db)
    plain.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    plain.commit()
    plain.close()
    assert store.change_counter(store.connect(db)) == 0


def test_cursor_peek_reads_a_cursor_without_a_write_lock_and_raises_nothing(path):
    writer, reader = store.open_db(path), store.open_db(path)
    store.cursor_set(writer, "seen", "abc")
    before = store.change_counter(reader)
    writer.execute("BEGIN IMMEDIATE")                  # a writer that holds the lock: cursor_get would wait for it, cursor_peek does not
    try:
        assert store.cursor_peek(reader, "seen") == "abc" and store.cursor_peek(reader, "never") is None
    finally:
        writer.execute("ROLLBACK")
    assert store.cursor_get(reader, "seen") == "abc" and store.change_counter(reader) == before

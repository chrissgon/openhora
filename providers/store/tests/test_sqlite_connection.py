"""Offline tests for `Connection`, the object `connect` returns (providers/store/sqlite.py): one sqlite3 connection that is closed
when the last reference to the object goes. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_connection.py

The service-level proof (the real operations leave no connection open, on 3.9 and on 3.12) is runtime/tests/test_store_connections_close.py;
this file pins the object itself and the guard that `connect` is the one door to a connection.
"""
from __future__ import annotations

import ast
import gc
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
ROOT = SCRIPT.parents[2]
spec = importlib.util.spec_from_file_location("store_sqlite_connection", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return path


class PlainProxy:
    """What a proxy without `execute` and a held cursor would be: the shape the hazard is about."""
    def __init__(self, real):
        self._real = real

    def execute(self, *args):
        return self._real.execute(*args)

    def __del__(self):
        self._real.close()


def test_a_read_chained_on_a_temporary_connection_works(db):
    assert tuple(store.open_db(db).execute("SELECT 1").fetchone()) == (1,)
    assert [r[0] for r in store.connect(db).execute("PRAGMA foreign_keys")] == [1]


def test_a_plain_proxy_would_meet_a_closed_database_on_the_same_chain(db):
    with pytest.raises(sqlite3.ProgrammingError):
        PlainProxy(sqlite3.connect(str(db))).execute("SELECT 1").fetchone()


def test_a_cursor_keeps_its_connection_open(db):
    cursor = store.open_db(db).execute("SELECT 1 UNION SELECT 2 ORDER BY 1")
    gc.collect()
    assert [tuple(r) for r in cursor.fetchall()] == [(1,), (2,)]


def test_the_connection_closes_at_its_last_reference(db):
    conn = store.open_db(db)
    real = conn._real
    assert real.execute("SELECT 1").fetchone()[0] == 1
    del conn
    with pytest.raises(sqlite3.ProgrammingError):
        real.execute("SELECT 1")


def test_a_holder_keeps_the_connection_open_as_long_as_it_holds(db):
    held = [store.open_db(db)]
    real = held[0]._real
    gc.collect()
    assert real.execute("SELECT 1").fetchone()[0] == 1
    held.clear()
    with pytest.raises(sqlite3.ProgrammingError):
        real.execute("SELECT 1")


def test_with_a_connection_returns_it_and_lets_an_exception_through(db):
    conn = store.open_db(db)
    with conn as inside:
        assert inside is conn
    with pytest.raises(ValueError, match="a planted fault"):
        with conn:
            raise ValueError("a planted fault")
    assert conn.execute("SELECT 1").fetchone()[0] == 1


def test_attributes_are_read_and_set_on_the_real_connection(db):
    conn = store.open_db(db)
    assert conn.row_factory is sqlite3.Row
    conn.row_factory = None
    assert conn.row_factory is None and conn._real.row_factory is None
    before = conn.total_changes
    with store.write(conn):
        conn.execute("INSERT OR REPLACE INTO cursors (name, value, updated_at) VALUES ('a-word', 'kept', 'x')")
    assert conn.total_changes == before + 1
    assert conn.in_transaction is False


def test_close_twice_raises_nothing_and_a_read_after_close_raises(db):
    conn = store.open_db(db)
    conn.close()
    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_a_half_built_object_is_dropped_in_silence(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "unraisablehook", lambda info: seen.append(repr(info.exc_value)))
    half = store.Connection.__new__(store.Connection)
    with pytest.raises(AttributeError):
        half.total_changes  # noqa: B018      (goes through __getattr__; the slot is unset)
    del half
    gc.collect()
    assert seen == []


# --- connect is the one door ---------------------------------------------------------------------------------------------------

def sqlite_connect_calls(source: str):
    """The functions (by name, '' at module level) that call sqlite3.connect in this source."""
    found = []

    stack: list = []

    class Walker(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "connect" and isinstance(f.value, ast.Name) and f.value.id == "sqlite3":
                found.append(stack[-1] if stack else "")
            self.generic_visit(node)
    Walker().visit(ast.parse(source))
    return found


def production_files():
    for folder in ("runtime", "providers", "scripts", "evals"):
        for path in sorted((ROOT / folder).rglob("*.py")):
            if "tests" not in path.relative_to(ROOT).parts:
                yield path


def test_sqlite_connect_is_called_in_one_place_only():
    calls = []
    for path in production_files():
        try:
            tree_source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "sqlite3" not in tree_source:
            continue
        calls.extend((str(path.relative_to(ROOT)), name) for name in sqlite_connect_calls(tree_source))
    assert calls == [("providers/store/sqlite.py", "connect")]


def test_the_walker_counts_a_second_call():
    source = ("import sqlite3\n"
              "def connect(path):\n    return sqlite3.connect(path)\n"
              "def other(path):\n    return sqlite3.connect(path)\n"
              "x = sqlite3.connect('a')\n"
              "y = connection.connect('a')\n")
    assert sqlite_connect_calls(source) == ["connect", "other", ""]

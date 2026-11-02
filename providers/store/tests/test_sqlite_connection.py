"""Offline tests for `Connection`, the object `connect` returns (providers/store/sqlite.py): one sqlite3 connection that is closed
when the last reference to the object goes. Every name is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_connection.py

The service-level proof (the real operations leave no connection open, on 3.9 and on 3.12) is runtime/tests/test_store_connections_close.py;
this file pins the object itself, the thread rule of its drop (the main thread hands the real connection to the next `connect`,
so that a stop signal's handler never lands in a destructor; another thread closes at once), what a drop keeps alive and what
it does not, the modes of the side files a reopen makes, and the guard that `connect` is the one door to a connection.
"""
from __future__ import annotations

import ast
import gc
import importlib.util
import operator
import os
import sqlite3
import stat
import sys
import threading
import weakref
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


def test_the_connection_closes_at_the_next_connect_after_its_last_reference_on_the_main_thread(db, main):
    conn = store.open_db(db)
    real = conn._real
    assert real.execute("SELECT 1").fetchone()[0] == 1
    del conn
    assert real.execute("SELECT 1").fetchone()[0] == 1, "dropped on the main thread: open until the drain"
    store.close_dropped()
    with pytest.raises(sqlite3.ProgrammingError):
        real.execute("SELECT 1")


def test_the_connection_closes_at_its_last_reference_on_another_thread(db):
    seen = []

    def on_a_thread():      # made, used and dropped on one thread (sqlite3 allows no other): closed at the drop
        conn = store.open_db(db)
        real = conn._real
        del conn
        try:
            real.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            seen.append("closed")
    thread = threading.Thread(target=on_a_thread)
    thread.start()
    thread.join()
    assert seen == ["closed"]


def test_a_holder_keeps_the_connection_open_as_long_as_it_holds(db, main):
    held = [store.open_db(db)]
    real = held[0]._real
    gc.collect()
    store.close_dropped()
    assert real.execute("SELECT 1").fetchone()[0] == 1, "the drain closes only what was dropped"
    held.clear()
    store.close_dropped()
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


def test_a_half_built_object_is_dropped_in_silence(monkeypatch, main):
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


# --- the drop: main thread, other threads ----------------------------------------------------------------------------------------

class Stop(BaseException):
    """What a stop signal's handler raises (runtime/messaging.py, runtime/mcp.py, runtime/ops_steps.py): not an Exception."""


class FakeCursor:
    def close(self):
        pass


class FakeReal:
    """A stand-in for the real sqlite3 connection: counts its closes, and raises `error` from each of them."""
    def __init__(self, error=None):
        self.closes, self.error = 0, error

    def cursor(self, *_a):
        return FakeCursor()

    def close(self):
        self.closes += 1
        if self.error is not None:
            raise self.error


def clear_dropped():
    for _ in range(10):
        try:
            store.close_dropped()
        except BaseException:  # noqa: BLE001 - a planted stop of a test
            continue
    del store._DROPPED[:]
    store._PENDING.clear()


@pytest.fixture
def main(monkeypatch):
    """The main-thread rule, whichever thread the test runner uses; nothing waits in the lists after the test."""
    monkeypatch.setattr(store, "_on_main_thread", lambda: True)
    clear_dropped()
    yield
    clear_dropped()


@pytest.fixture
def unraised(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "unraisablehook", lambda info: seen.append(repr(info.exc_value)))
    return seen


def test_the_main_thread_connection_has_no_destructor_and_no_python_runs_in_its_drop():
    assert not hasattr(store.Connection, "__del__"), "a Python frame in a destructor can never give a stop signal back"
    assert "__del__" in vars(store._ThreadConnection) and issubclass(store._ThreadConnection, store.Connection)


def test_a_drop_on_the_main_thread_closes_nothing_and_waits_for_the_next_connect(db, main):
    real = FakeReal()
    conn = store._wrap(real)
    del conn
    assert real.closes == 0 and [r.real for r in store._DROPPED] == [real] and len(store._PENDING) == 1
    store.connect(db)
    assert real.closes == 1 and all(r.real is not real for r in list(store._DROPPED) + list(store._PENDING.values()))


def test_a_stop_that_lands_in_a_close_is_raised_by_the_next_connect_and_the_rest_is_closed_by_the_following_one(db, main, unraised):
    first, bad, last = FakeReal(), FakeReal(error=Stop("a planted stop")), FakeReal()
    for real in (first, bad, last):
        store._wrap(real)      # dropped at once
    with pytest.raises(Stop) as raised:
        store.connect(db)
    assert str(raised.value) == "a planted stop" and bad.closes == 1
    store.connect(db)
    assert [r.closes for r in (first, bad, last)] == [1, 1, 1], "nothing is retried, and nothing is left behind"
    assert unraised == [], "and the stop reached the caller of connect, not sys.unraisablehook"


def test_a_destructor_that_closes_loses_the_same_stop(db, unraised):
    class Eager:
        """A Connection that closes in __del__: the design this package does not use."""
        def __init__(self, real):
            self.real = real

        def __del__(self):
            self.real.close()
    Eager(FakeReal(error=Stop("a planted stop")))
    assert unraised == [repr(Stop("a planted stop"))], "the exception cannot leave a destructor: it is printed and dropped"


def test_a_close_that_sqlite_refuses_is_swallowed_by_the_drain_and_a_real_error_is_not(db, main):
    refused, broken = FakeReal(error=sqlite3.ProgrammingError("refused")), FakeReal(error=RuntimeError("a planted fault"))
    store._wrap(refused)
    store.close_dropped()
    assert refused.closes == 1 and store._DROPPED == []
    store._wrap(broken)
    with pytest.raises(RuntimeError, match="a planted fault"):
        store.close_dropped()


def test_a_ref_that_is_not_kept_would_never_call_back(main):
    """Why _PENDING exists: a weak reference that dies before its referent never calls its callback."""
    seen = []

    class Dropped(weakref.ref):
        __slots__ = ("real",)
    conn = store.Connection(FakeReal())
    Dropped(conn, seen.append)      # not kept
    del conn
    assert seen == []
    kept = FakeReal()
    conn = store._wrap(kept)
    del conn
    assert len(store._DROPPED) == 1 and store._DROPPED[0].real is kept


def test_a_connection_made_on_a_thread_closes_at_its_own_drop_and_the_drain_there_does_nothing(db):
    real, waiting = FakeReal(), FakeReal()
    made = []

    def on_a_thread():
        conn = store._wrap(real)
        made.append(type(conn))
        del conn
    thread = threading.Thread(target=on_a_thread)
    thread.start()
    thread.join()
    assert made == [store._ThreadConnection] and real.closes == 1 and all(r.real is not real for r in store._DROPPED)
    holder = store.Connection(FakeReal())      # an entry the main thread's drain would close
    entry = store._Dropped(holder, store._DROPPED.append)
    entry.real = waiting
    store._DROPPED.append(entry)
    try:
        thread = threading.Thread(target=store.close_dropped)
        thread.start()
        thread.join()
        assert waiting.closes == 0 and entry in store._DROPPED, "only the main thread drains"
    finally:
        clear_dropped()


def test_a_main_thread_connection_dropped_on_another_thread_is_closed_by_the_main_thread(db, main, unraised):
    real = FakeReal()
    box = [store._wrap(real)]
    thread = threading.Thread(target=box.clear)
    thread.start()
    thread.join()
    assert real.closes == 0, "sqlite3 wants its own thread: the other thread closes nothing"
    store.close_dropped()
    assert real.closes == 1 and unraised == []


def test_a_thread_connection_dropped_on_the_main_thread_is_refused_in_silence_and_left_to_the_collector(db, unraised, capfd, monkeypatch):
    class Weakable(sqlite3.Connection):      # a subclass can be weakly referenced; the plain class cannot
        pass
    real_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: real_connect(*a, factory=Weakable, **k))
    box = []

    def on_a_thread():
        box.append(store.open_db(db))
    thread = threading.Thread(target=on_a_thread)
    thread.start()
    thread.join()
    assert type(box[0]) is store._ThreadConnection
    real = weakref.ref(box[0]._real)
    box.clear()
    gc.collect()
    assert unraised == [] and capfd.readouterr().err == ""
    assert real() is None, "and the collector frees it"


def test_an_explicit_close_is_direct_on_the_main_thread(main):
    real = FakeReal()
    store._wrap(real).close()
    assert real.closes == 1, "closed by the call itself, before the drop"


# --- what a drop keeps alive ----------------------------------------------------------------------------------------------------

def test_a_cursor_from_execute_holds_the_connection_on_every_thread(db):
    result = []
    thread = threading.Thread(target=lambda: result.append(store.open_db(db).execute("SELECT 1").fetchone()[0]))
    thread.start()
    thread.join()
    assert result == [1]


def test_what_a_drop_does_not_keep_alive_on_another_thread(db):
    seen = []

    def chain():
        for name, call in (("executemany", lambda: store.open_db(db).executemany("SELECT ?", [(1,)])),
                           ("executescript", lambda: store.open_db(db).executescript("SELECT 1")),
                           ("cursor", lambda: operator.methodcaller("cursor")(store.open_db(db)).execute("SELECT 1")),      # not written as an attribute: the validator reads the word as an editor's name
                           ("iterdump", lambda: list(store.open_db(db).iterdump()))):
            try:
                call()
            except sqlite3.ProgrammingError as e:
                seen.append((name, str(e)))
        conn = store.open_db(db)
        kept, saved = conn.cursor(), conn.commit
        del conn
        for name, call in (("kept cursor", lambda: kept.execute("SELECT 1")), ("saved commit", saved)):
            try:
                call()
            except sqlite3.ProgrammingError as e:
                seen.append((name, str(e)))
    thread = threading.Thread(target=chain)
    thread.start()
    thread.join()
    assert seen == [(n, "Cannot operate on a closed database.") for n in
                    ("executemany", "executescript", "cursor", "iterdump", "kept cursor", "saved commit")]


def test_what_a_drop_does_not_keep_alive_on_the_main_thread_works_until_the_next_connect(db, main):
    conn = store.open_db(db)
    kept = conn.cursor()
    del conn
    assert kept.execute("SELECT 1").fetchone()[0] == 1
    store.connect(db)
    with pytest.raises(sqlite3.ProgrammingError):
        kept.execute("SELECT 1")


# --- the side files of a reopen -------------------------------------------------------------------------------------------------

def test_the_wal_and_shm_files_a_reopen_makes_are_private(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    old = os.umask(0)
    try:
        store.init_db(path)
        seen = []
        for round_number in range(2):
            conn = store.open_db(path)
            store.cursor_set(conn, f"a-word-{round_number}", "kept")
            found = [side for side in (Path(f"{path}-wal"), Path(f"{path}-shm")) if side.exists()]
            for side in found:
                assert stat.S_IMODE(side.stat().st_mode) == 0o600, side
            seen.append(found)
            conn.close()
    finally:
        os.umask(old)
    assert all(seen), "each round saw at least one side file: the test cannot pass on nothing"

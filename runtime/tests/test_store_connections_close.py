"""A store connection closes when its last reference goes (CONN-LEAK; providers/store/sqlite.py `Connection`, runtime/ops_core.py `context()`).

The defect: `context()` opens two connections (`store.init_db` and `store.open_db`) and nothing closed either. From Python 3.11 a
sqlite3.Connection refers to itself through its statement cache, so a connection dropped without `close()` stays open, with its file
and its -wal descriptor, until the cyclic collector reaches it. `store.connect` now returns an object outside that cycle that closes
the real connection at its own last drop, so no caller changes. These tests run the real operations over the stand-in tree and the
real messaging bridge over the stand-in messenger, and count the connections the store opened, the ones still open, and the
descriptors the process holds. Offline; every name and word is invented.

Two oracles. The first holds on every interpreter: `sqlite3.connect` is replaced by a wrapper that passes `factory=Counted`, a
sqlite3.Connection subclass whose `close` counts once per object after the real close returned. Reference counting at 3.9 and the
collector both close without calling a Python `close`, so the unfixed code shows 0 closes on every interpreter, and that is the right
reason. The second is the descriptor count, which bites from 3.11 (`CYCLE`). It is bounded by `FD_BOUND` and not by 0: with another
connection of the same file open in the process, SQLite may keep a closed connection's descriptor for its next open.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_store_connections_close.py
"""
from __future__ import annotations

import gc
import os
import sqlite3
import sys
import threading

import pytest

import standin_tree as st
from test_commands_in_words import OWNER, closed_heads, docs, rig, tier1_forms, world  # noqa: F401
from test_dispatcher import configure, planned, tree  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")

N_TICK = 100
N_LINE = 20
FD_BOUND = 3      # descriptors a path may leave after its N calls: SQLite may keep a closed connection's descriptor for its next open
CYCLE = sys.version_info >= (3, 11)      # the interpreters on which a connection dropped without a close stays open until a collection


class Tally:
    def __init__(self):
        self.opened, self.closed = 0, 0


@pytest.fixture
def tally(monkeypatch):
    t, real = Tally(), sqlite3.connect

    class Counted(sqlite3.Connection):
        done = False

        def close(self):
            super().close()      # a close from another thread raises here: it is not counted
            if not self.done:
                self.done = True
                t.closed += 1

    def connect(*args, **kwargs):
        t.opened += 1
        return real(*args, factory=Counted, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", connect)
    return t


def fds():
    return len(os.listdir("/dev/fd")) - 1


def run(tally, call, n):
    """(connections opened, of them not closed, descriptors more than before) for n calls, with the collector off."""
    gc.collect()
    gc.disable()
    try:
        opened, closed, before = tally.opened, tally.closed, fds()
        for _ in range(n):
            call()
        return tally.opened - opened, (tally.opened - opened) - (tally.closed - closed), fds() - before
    finally:
        gc.enable()


def old_connect(store):
    """The body connect had before this package: the connection itself, closed by nobody."""
    def connect(path):
        conn = sqlite3.connect(str(path), timeout=store.BUSY_TIMEOUT_SECONDS, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    return connect


TICKS = [("dispatch", lambda p: ops.dispatch(p, wait=False), 2), ("route_queued", lambda p: ops.route_queued(p), 2), ("poll", lambda p: ops.poll(p), 2),
         ("config", lambda p: ops.config(p), 2), ("pending", lambda p: ops.pending(p), 2), ("status", lambda p: ops.status(p), 2), ("version", lambda p: ops.version(p), 1)]


@pytest.mark.parametrize("name,call,each", TICKS, ids=[t[0] for t in TICKS])
def test_a_service_path_leaves_no_connection_open(tree, tally, name, call, each):
    path = str(tree["project"])
    call(path)      # the first call's own work (a migration, a lazy import) is outside the count
    opened, left, extra = run(tally, lambda: call(path), N_TICK)
    # `opened` is exact: it proves the path was reached and pins the two connections of context() (one is a read of the file's time).
    assert (opened, left) == (N_TICK * each, 0)
    assert extra <= FD_BOUND


@pytest.mark.parametrize("rig", ["en"], indirect=True)
def test_the_bridge_tick_and_a_typed_line_leave_no_connection_open(rig, tally):
    rig.bridge.tick()
    opened, left, extra = run(tally, rig.bridge.tick, N_LINE)
    assert opened >= N_LINE and left == 0 and extra <= FD_BOUND
    opened, left, extra = run(tally, lambda: rig.line(OWNER, "/status", confirm=False), N_LINE)
    assert opened >= N_LINE and left == 0 and extra <= FD_BOUND


def test_a_raised_exception_inside_an_operation_closes_its_connection_and_reaches_the_caller(tree, tally, monkeypatch):
    path = str(tree["project"])
    store = ops_core.store_module()

    def breaks(*_a, **_k):
        raise RuntimeError("a planted fault")
    monkeypatch.setattr(store, "pending_list", breaks)
    seen = []

    def call():
        try:
            ops.pending(path)
        except RuntimeError as e:
            seen.append(str(e))
    opened, left, extra = run(tally, call, N_LINE)
    assert seen == ["a planted fault"] * N_LINE
    assert (opened, left) == (N_LINE * 2, 0) and extra <= FD_BOUND


def test_a_refusal_closes_its_connection_too(tree, tally):
    path = str(tree["project"])
    codes = []

    def call():
        try:
            ops.pending(path, pending_id=99999)
        except ops.OpsError as e:
            codes.append(e.code)
    opened, left, extra = run(tally, call, N_LINE)
    assert len(codes) == N_LINE and all(codes), "every call was refused, with its code"
    assert (opened, left) == (N_LINE * 2, 0) and extra <= FD_BOUND


def test_a_commit_stays_and_a_rollback_stays_after_the_close(tree):
    path = str(tree["project"])
    store = ops_core.store_module()
    db = ops_core.context(path)["cfg"]["store_db"]

    def committed():
        store.cursor_set(ops_core.context(path)["conn"], "a-word", "kept")      # a temporary: closed as soon as the call returns

    def rolled_back():
        ctx = ops_core.context(path)
        with store.write(ctx["conn"]):
            ctx["conn"].execute("INSERT OR REPLACE INTO cursors (name, value, updated_at) VALUES ('another-word', 'lost', 'x')")
            raise ValueError("a planted fault")
    committed()
    with pytest.raises(ValueError):
        rolled_back()
    raw = sqlite3.connect(db)
    try:
        rows = dict(raw.execute("SELECT name, value FROM cursors WHERE name IN ('a-word', 'another-word')").fetchall())
    finally:
        raw.close()
    assert rows == {"a-word": "kept"}


# --- the oracle fails where it must --------------------------------------------------------------------------------------------

def test_the_oracle_fails_on_the_old_connect(tree, tally, monkeypatch):
    path = str(tree["project"])
    monkeypatch.setattr(ops_core.store_module(), "connect", old_connect(ops_core.store_module()))
    opened, left, extra = run(tally, lambda: ops.route_queued(path), N_TICK)
    assert (opened, left) == (N_TICK * 2, N_TICK * 2), "no connection was closed, on any interpreter"
    if CYCLE:
        assert extra >= N_TICK, "and each stays open until a collection"
    gc.collect()


def test_the_oracle_catches_one_path_that_keeps_its_connection(tree, tally, monkeypatch):
    path = str(tree["project"])
    real, held = ops_core.context, []
    monkeypatch.setattr(ops_core, "context", lambda project, **k: held.append(real(project, **k)) or held[-1])
    opened, left, extra = run(tally, lambda: ops.route_queued(path), N_TICK)
    assert (opened, left) == (N_TICK * 2, N_TICK), "the connection of each context() stays; the one of init_db is closed"
    assert extra >= N_TICK
    del held[:]


# --- the other thread (a close sqlite3 refuses) --------------------------------------------------------------------------------

def drop_on_another_thread(holder):
    thread = threading.Thread(target=holder.clear)
    thread.start()
    thread.join()


@pytest.fixture
def unraised(monkeypatch):
    """Everything the interpreter reports as an exception ignored in a destructor, while the test runs."""
    seen = []
    monkeypatch.setattr(sys, "unraisablehook", lambda info: seen.append(repr(info.exc_value)))
    return seen


def test_a_last_reference_dropped_on_another_thread_says_nothing_and_a_collection_closes_it(tree, tally, capfd, unraised):
    path = str(tree["project"])
    box = [ops_core.context(path)]
    gc.collect()
    before, closed = fds(), tally.closed
    drop_on_another_thread(box)
    assert tally.closed == closed, "the close is refused on the other thread, as sqlite3 refuses any use there"
    assert capfd.readouterr().err == ""
    assert unraised == [], "and the refusal is swallowed in __del__, not reported as an ignored exception"
    gc.collect()
    assert fds() <= before


def test_the_unraised_oracle_sees_a_destructor_that_does_not_swallow(tree, unraised):
    class Loud:
        """A Connection whose __del__ does not swallow: what the other-thread test must catch."""
        def __init__(self, real):
            self.real = real

        def __del__(self):
            self.real.close()
    db = ops_core.context(str(tree["project"]))["cfg"]["store_db"]
    box = [Loud(sqlite3.connect(db))]
    drop_on_another_thread(box)
    assert len(unraised) == 1 and "ProgrammingError" in unraised[0]

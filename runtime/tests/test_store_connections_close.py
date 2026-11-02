"""A store connection closes when its last reference goes (CONN-LEAK; providers/store/sqlite.py `Connection`, runtime/ops_core.py `context()`).

The defect: `context()` opens two connections (`store.init_db` and `store.open_db`) and nothing closed either. From Python 3.11 a
sqlite3.Connection refers to itself through its statement cache, so a connection dropped without `close()` stays open, with its file
and its -wal descriptor, until the cyclic collector reaches it. `store.connect` now returns an object outside that cycle that closes
the real connection at its own last drop, so no caller changes. These tests run the real operations over the stand-in tree and the
real messaging bridge over the stand-in messenger, and count the connections the store opened, the ones still open, and the
descriptors the process holds. Offline; every name and word is invented.

On the main thread a dropped connection is closed by the NEXT connect (or by `store.close_dropped()`, the named drain), not at the drop:
a stop signal's handler that raises must not land inside a destructor. So a path on the main thread is counted twice: `left` at once
(at most `DROP_BOUND`, what the last operation dropped: 2 for a context()) and `left_drained` after the drain (0). A path on another
thread closes at the drop, and must show 0 left at once. The tests that force the main-thread rule do it with `main_thread`, since a
test runner may run a test on a thread that is not the main one.

Two oracles. The first holds on every interpreter: `sqlite3.connect` is replaced by a wrapper that passes `factory=Counted`, a
sqlite3.Connection subclass whose `close` counts once per object after the real close returned. Reference counting at 3.9 and the
collector both close without calling a Python `close`, so the unfixed code shows 0 closes on every interpreter, and that is the right
reason. The second is the descriptor count, which bites from 3.11 (`CYCLE`). It is bounded by `FD_BOUND` and not by 0: with another
connection of the same file open in the process, SQLite may keep a closed connection's descriptor for its next open.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_store_connections_close.py
"""
from __future__ import annotations

import collections
import datetime
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
DROP_BOUND = 2      # connections a path may leave open at once on the main thread: what its last operation dropped (a context() opens 2)
FD_BOUND = 3      # descriptors a path may leave after its N calls and the drain: SQLite may keep a closed connection's descriptor for its next open
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


Run = collections.namedtuple("Run", "opened left extra left_drained extra_drained")


def run(tally, call, n):
    """For n calls with the collector off: connections opened, of them still open at once, descriptors more than before at once,
    and the same two after the named drain (`store.close_dropped()`)."""
    drain = getattr(ops_core.store_module(), "close_dropped", lambda: None)      # the base has no drain: nothing waits there
    gc.collect()
    drain()      # what the call before left: it belongs to that call, not to this count
    gc.disable()
    try:
        opened, closed, before = tally.opened, tally.closed, fds()
        for _ in range(n):
            call()
        now = (tally.opened - opened) - (tally.closed - closed), fds() - before
        drain()
        return Run(tally.opened - opened, now[0], now[1], (tally.opened - opened) - (tally.closed - closed), fds() - before)
    finally:
        gc.enable()


@pytest.fixture
def main_thread(monkeypatch):
    """The drop rule of the main thread (close at the next connect), whichever thread the test runner uses."""
    monkeypatch.setattr(ops_core.store_module(), "_on_main_thread", lambda: True, raising=False)      # raising=False: the base has no such rule


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
def test_a_service_path_leaves_no_connection_open(tree, tally, main_thread, name, call, each):
    path = str(tree["project"])
    call(path)      # the first call's own work (a migration, a lazy import) is outside the count
    r = run(tally, lambda: call(path), N_TICK)
    # `opened` is exact: it proves the path was reached and pins the two connections of context() (one is a read of the file's time).
    assert r.opened == N_TICK * each
    assert r.left <= DROP_BOUND and r.extra <= FD_BOUND + 2 * DROP_BOUND, "at once: only what the last operation dropped"
    assert (r.left_drained, r.extra_drained <= FD_BOUND) == (0, True), "after the drain: nothing"


@pytest.mark.parametrize("rig", ["en"], indirect=True)
def test_the_bridge_tick_and_a_typed_line_leave_no_connection_open(rig, tally):
    rig.bridge.tick()
    for call in (rig.bridge.tick, lambda: rig.line(OWNER, "/status", confirm=False)):
        r = run(tally, call, N_LINE)
        assert r.opened >= N_LINE
        assert r.left <= DROP_BOUND and r.extra <= FD_BOUND + 2 * DROP_BOUND
        assert (r.left_drained, r.extra_drained <= FD_BOUND) == (0, True)


def test_a_raised_exception_inside_an_operation_closes_its_connection_and_reaches_the_caller(tree, tally, main_thread, monkeypatch):
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
    r = run(tally, call, N_LINE)
    assert seen == ["a planted fault"] * N_LINE
    assert r.opened == N_LINE * 2 and r.left <= DROP_BOUND
    assert (r.left_drained, r.extra_drained <= FD_BOUND) == (0, True)


def test_a_refusal_closes_its_connection_too(tree, tally, main_thread):
    path = str(tree["project"])
    codes = []

    def call():
        try:
            ops.pending(path, pending_id=99999)
        except ops.OpsError as e:
            codes.append(e.code)
    r = run(tally, call, N_LINE)
    assert len(codes) == N_LINE and all(codes), "every call was refused, with its code"
    assert r.opened == N_LINE * 2 and r.left <= DROP_BOUND
    assert (r.left_drained, r.extra_drained <= FD_BOUND) == (0, True)


def test_a_commit_stays_and_a_rollback_stays_after_the_close(tree, main_thread):
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

def test_the_oracle_fails_on_the_old_connect(tree, tally, main_thread, monkeypatch):
    path = str(tree["project"])
    monkeypatch.setattr(ops_core.store_module(), "connect", old_connect(ops_core.store_module()))
    r = run(tally, lambda: ops.route_queued(path), N_TICK)
    assert (r.opened, r.left, r.left_drained) == (N_TICK * 2, N_TICK * 2, N_TICK * 2), "no connection was closed, not even by the drain, on any interpreter"
    if CYCLE:
        assert r.extra_drained >= N_TICK, "and each stays open until a collection"
    gc.collect()


def test_the_oracle_catches_one_path_that_keeps_its_connection(tree, tally, main_thread, monkeypatch):
    path = str(tree["project"])
    real, held = ops_core.context, []
    monkeypatch.setattr(ops_core, "context", lambda project, **k: held.append(real(project, **k)) or held[-1])
    r = run(tally, lambda: ops.route_queued(path), N_TICK)
    assert (r.opened, r.left_drained) == (N_TICK * 2, N_TICK), "the connection of each context() stays; the one of init_db is closed"
    assert r.left >= N_TICK and r.extra_drained >= N_TICK
    del held[:]


# --- another thread: closed at the drop ---------------------------------------------------------------------------------------

def on_a_thread(call):
    """Run call on a thread of its own, wait for it, and raise what it raised."""
    box = []

    def target():
        try:
            call()
        except BaseException as e:  # noqa: BLE001 - handed to the test
            box.append(e)
    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if box:
        raise box[0]


def test_a_path_on_another_thread_leaves_nothing_open_at_once(tree, tally):
    path = str(tree["project"])
    ops.pending(path)

    def many():
        for _ in range(N_LINE):
            ops.pending(path)
    r = run(tally, lambda: on_a_thread(many), 1)
    assert r.opened == N_LINE * 2
    assert (r.left, r.extra <= FD_BOUND) == (0, True), "no drain: the drop of a thread that is not the main one closes"


def test_a_last_reference_dropped_on_another_thread_says_nothing_and_the_main_thread_closes_it(tree, tally, main_thread, capfd, unraised):
    path = str(tree["project"])
    store = ops_core.store_module()
    store.close_dropped()
    box = [ops_core.context(path)]
    real = box[0]["conn"]._real
    closed = tally.closed
    drop_on_another_thread(box)
    assert tally.closed == closed, "the other thread closes nothing: sqlite3 wants the thread that made the connection"
    assert capfd.readouterr().err == "" and unraised == [], "and says nothing"
    assert real.execute("SELECT 1").fetchone()[0] == 1, "the connection is still open, waiting for the main thread"
    store.close_dropped()
    assert tally.closed > closed, "the main thread's next drain closes it"
    with pytest.raises(sqlite3.ProgrammingError):
        real.execute("SELECT 1")


# --- the signal that lands in a drop is not lost: the deterministic proof is test_sqlite_connection.py ---------------------------

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


# --- version: the -wal can go between the check and the stat -------------------------------------------------------------------

def test_version_survives_the_removal_of_the_wal_between_a_check_and_a_stat(tree, monkeypatch):
    path = str(tree["project"])
    db = ops_core.context(path)["cfg"]["store_db"]
    real_stat, real_exists = os.stat, os.path.exists

    def stat(p, *a, **k):
        if str(p).endswith("-wal"):
            raise FileNotFoundError(p)      # another process's last close removed it
        return real_stat(p, *a, **k)
    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(os.path, "exists", lambda p: True if str(p).endswith("-wal") else real_exists(p))
    answered = ops.version(path)
    assert isinstance(answered["version"], int) and answered["changed_at"].endswith("Z")
    assert answered["changed_at"] == datetime.datetime.fromtimestamp(real_stat(db).st_mtime, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "the store file's time"
    with pytest.raises(FileNotFoundError):
        old = [os.stat(p).st_mtime for p in (db, db + "-wal") if os.path.exists(p)]      # the code before this package, under the same race

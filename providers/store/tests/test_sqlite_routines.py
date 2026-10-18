"""Offline tests for the routines and the Drive source type in providers/store/sqlite.py (P6b, migration 14): a store at 13 migrating with a
Drive row (its versions and the record of what a run received untouched), the routine's life (a draft, the approval by a hash, a change
that clears it, the brakes), and the fire keyed by (routine, slot) that creates its request in the same transaction. Every name below is
invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_routines.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_routines", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

DOC = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
SHA = "a" * 64
SCHEDULE = {"every": "day", "at": "08:00"}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def version_row(source, version=1):
    return (source, version, "import", "runtime", "markdown", "notes.md", SHA, 10, "converted.md", SHA, 10, "markitdown", None, None, "[]",
            "{}", "v1", "2026-10-15T00:00:00.000000Z")


def test_a_store_at_13_with_a_drive_row_migrates_to_the_type_and_the_bare_id_and_keeps_its_versions_and_its_records(tmp_path):
    path = tmp_path / "thirteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 14):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-15T00:00:00.000000Z', 'x')", (version,))
    for source, kind, origin in (("notes", "file", "drive:" + DOC), ("plain", "file", "survey.csv"), ("page", "notion", "a" * 32),
                                 ("trick", "file", "drive-notes.md")):
        old.execute("INSERT INTO sources VALUES (?, ?, ?, 'a description', '2026-10-15T00:00:00.000000Z', '2026-10-15T00:00:00.000000Z')",
                    (source, kind, origin))
    for source in ("notes", "plain"):
        old.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 18) + ")", version_row(source))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, status) VALUES (1, 's', 'm', 'h', 'a', 'ok')")
    old.execute("INSERT INTO task_sources VALUES (1, 1, 'notes', 1, ?, '2026-10-15T00:00:00.000000Z')", (SHA,))
    old.commit()
    before = {t: old.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("source_versions", "task_sources")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 13 and out["applied"] == [14, 15, 16, 17, 18, 20] and out["schema_version"] == 20
    conn = store.open_db(path)
    rows = {r["id"]: r for r in store.sources_list(conn)}
    assert (rows["notes"]["type"], rows["notes"]["origin"]) == ("drive", DOC)
    assert (rows["plain"]["type"], rows["plain"]["origin"]) == ("file", "survey.csv")
    assert (rows["page"]["type"], rows["page"]["origin"]) == ("notion", "a" * 32)
    assert (rows["trick"]["type"], rows["trick"]["origin"]) == ("file", "drive-notes.md"), "only the prefix `drive:` marks a Drive row"
    assert rows["notes"]["description"] == "a description" and rows["notes"]["created_at"] == "2026-10-15T00:00:00.000000Z"
    after = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("source_versions", "task_sources")}
    assert [tuple(r)[:18] for r in after["source_versions"]] == [tuple(r) for r in before["source_versions"]] and all(r[18] is None for r in after["source_versions"]), "migration 18 adds a trailing provenance, empty on an older version"
    assert [tuple(r) for r in after["task_sources"]] == [tuple(r) for r in before["task_sources"]]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.source_latest(conn, "notes")["version"] == 1
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM sources WHERE id = 'notes'")
    with pytest.raises(sqlite3.DatabaseError, match="only its description changes"):
        conn.execute("UPDATE sources SET origin = 'x' WHERE id = 'notes'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE sources SET type = 'ftp' WHERE id = 'plain'")
    conn.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", (*version_row("notes", 2), None))     # the foreign key still holds
    assert store.source_add(conn, source_id="more", source_type="drive", origin=DOC)["type"] == "drive"


def test_a_store_made_at_14_admits_the_drive_type_at_once(conn):
    assert store.source_add(conn, source_id="notes", source_type="drive", origin=DOC)["origin"] == DOC
    with pytest.raises(store.StoreError, match="type is one of file, notion, drive"):
        store.source_add(conn, source_id="x", source_type="ftp", origin="y")


def add(conn, **extra):
    base = dict(name="morning", flow="demo", params={"topic": "dental"}, schedule=SCHEDULE, model="m", consent=False, providers=[],
                window_seconds=None)
    return store.routine_add(conn, **{**base, **extra})


def test_a_routine_is_a_draft_approved_by_a_hash_changed_into_a_draft_again_and_never_deleted(conn):
    made = add(conn, providers=["b", "a", "a"])
    assert made["state"] == "draft" and made["approved_sha256"] is None and made["providers"] == ["a", "b"] and made["params"] == {"topic": "dental"}
    with pytest.raises(store.StoreError, match="there is a routine named morning"):
        add(conn)
    with pytest.raises(store.StoreError, match="lowercase words"):
        add(conn, name="Not A Name")
    with pytest.raises(store.StoreError, match="at least 60"):
        add(conn, name="x", window_seconds=30)
    approved = store.routine_approve(conn, made["id"], sha256=SHA, by="user", content={"model": "m"})
    assert approved["state"] == "active" and approved["approved_sha256"] == SHA and approved["approved_content"] == {"model": "m"}
    changed = store.routine_change(conn, made["id"], model="fm", consent=True)
    assert changed["state"] == "draft" and changed["approved_sha256"] is None and changed["approved_content"] is None
    assert changed["model"] == "fm" and changed["consent"] == 1 and changed["flow"] == "demo"
    with pytest.raises(store.StoreError, match="no field"):
        store.routine_change(conn, made["id"], state="active")
    store.routine_approve(conn, made["id"], sha256=SHA, by="user")
    assert store.routine_move(conn, made["id"], "pause")["state"] == "paused"
    with pytest.raises(store.StoreError, match="is paused: it is paused only from active"):
        store.routine_move(conn, made["id"], "pause")
    assert store.routine_move(conn, made["id"], "resume")["approved_sha256"] == SHA
    assert store.routine_move(conn, made["id"], "cancel")["state"] == "cancelled"
    with pytest.raises(store.StoreError, match="cancelled"):
        store.routine_change(conn, made["id"], model="m")
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM routines WHERE id = ?", (made["id"],))


def test_a_fire_is_keyed_by_the_routine_and_the_slot_and_makes_its_request_in_the_same_transaction(conn):
    made = add(conn)
    store.routine_approve(conn, made["id"], sha256=SHA, by="user")
    request = {"title": "morning · 2026-10-15T08:00", "text": "Routine morning.", "flow": "demo", "model": "m", "waits": [],
               "tasks": [{"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do it.", "depends_on": []}]}
    first = store.routine_fire(conn, routine_id=made["id"], slot="2026-10-15T08:00", status="created", request=request)
    assert first["fired"] is True and first["fire"]["status"] == "created" and first["request"] == first["fire"]["request_id"]
    assert [t["state"] for t in first["tasks"]] == ["ready"]
    again = store.routine_fire(conn, routine_id=made["id"], slot="2026-10-15T08:00", status="created", request=request)
    assert again == {"fired": False, "duplicate": True}
    requests = [t for t in store.tasks_list(conn) if t["parent_id"] is None]
    assert len(requests) == 1 and requests[0]["model"] == "m" and requests[0]["flow"] == "demo"
    assert store.routine_of_request(conn, first["request"])["routine"]["name"] == "morning"
    assert store.routine_of_request(conn, 999) is None
    # a request that cannot be made leaves no fire row behind: one transaction
    bad = dict(request, tasks=[{"key": "x", "skill": "s", "title": "T", "text": "t", "depends_on": ["nothing"]}])
    with pytest.raises(store.StoreError):
        store.routine_fire(conn, routine_id=made["id"], slot="2026-10-16T08:00", status="created", request=bad)
    assert [f["slot"] for f in store.routine_fires_list(conn, made["id"])] == ["2026-10-15T08:00"]
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        conn.execute("UPDATE routine_fires SET status = 'skipped'")
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM routine_fires")


def test_a_skipped_fire_has_no_request_and_an_asked_one_has_a_request_with_a_question_and_stops_the_routine(conn):
    made = add(conn)
    store.routine_approve(conn, made["id"], sha256=SHA, by="user")
    skipped = store.routine_fire(conn, routine_id=made["id"], slot="2026-10-14T08:00", status="skipped", reason="missed")
    assert skipped["request"] is None and skipped["pending_id"] is None
    asked = store.routine_fire(conn, routine_id=made["id"], slot="2026-10-15T08:00", status="asked", reason="its content changed",
                               question={"title": "Routine morning stopped", "body": "Approve it again.", "payload": {"routine": made["id"]}},
                               state="stopped")
    assert asked["pending_id"] and asked["request"]
    [pending] = store.pending_list(conn, "open")
    assert pending["kind"] == "question" and pending["task_id"] == asked["request"] and pending["payload"] == {"routine": made["id"]}
    assert store.task_get(conn, asked["request"])["state"] == "requested"
    assert store.routine_get(conn, made["id"])["state"] == "stopped"
    last = store.routines_list(conn)[0]["last_fire"]
    assert last["slot"] == "2026-10-15T08:00" and last["status"] == "asked"
    with pytest.raises(store.StoreError, match="carries a request"):
        store.routine_fire(conn, routine_id=made["id"], slot="2026-10-17T08:00", status="created")
    with pytest.raises(store.StoreError, match="status is one of"):
        store.routine_fire(conn, routine_id=made["id"], slot="2026-10-18T08:00", status="done")
    assert store.routine_move(conn, made["id"], "cancel")["state"] == "cancelled"


def test_a_resume_records_when_it_happened_and_a_fire_of_a_routine_no_longer_active_or_approved_otherwise_writes_nothing(conn):
    made = add(conn)
    assert made["resumed_at"] is None
    store.routine_approve(conn, made["id"], sha256=SHA, by="user")
    store.routine_move(conn, made["id"], "pause")
    resumed = store.routine_move(conn, made["id"], "resume")
    assert resumed["resumed_at"] and resumed["resumed_at"] >= resumed["approved_at"]
    request = {"title": "morning", "text": "Routine morning.", "flow": "demo", "model": "m", "waits": [],
               "tasks": [{"key": "market", "skill": "biz-market-analysis", "title": "Market", "text": "Do it.", "depends_on": []}]}
    # the caller read the routine as active with SHA; a pause, a change or another approval since wins
    store.routine_move(conn, made["id"], "pause")
    assert store.routine_fire(conn, routine_id=made["id"], slot="2026-10-15T08:00", status="created", request=request, approved_sha256=SHA) == \
        {"fired": False, "inactive": True}
    store.routine_move(conn, made["id"], "resume")
    assert store.routine_fire(conn, routine_id=made["id"], slot="2026-10-15T08:00", status="skipped", reason="x", approved_sha256="b" * 64) == \
        {"fired": False, "inactive": True}, "the approval changed since the caller read it"
    store.routine_change(conn, made["id"], model="fm")
    assert store.routine_fire(conn, routine_id=made["id"], slot="2026-10-15T08:00", status="skipped", reason="x") == {"fired": False, "inactive": True}
    assert store.routine_fires_list(conn, made["id"]) == [] and [t for t in store.tasks_list(conn) if t["parent_id"] is None] == []

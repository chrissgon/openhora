"""Offline tests for migration 19 of providers/store/sqlite.py (package O2): the sources table is rebuilt to admit the type `onedrive`.
A store at 18 migrating with every source of every type (no row rewritten), the versions and the record of what a run received
untouched, both triggers still in force, the foreign key still holding, and a type outside the closed list still refused. Every name
and id below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_onedrive.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_onedrive", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

ITEM = "b!Fake-Drive_1/ITEM1!101"
DOC = "1AbCdEfGhIjKlMnOpQrStUvWxYz"
SHA = "a" * 64
STAMP = "2026-10-17T00:00:00.000000Z"


def version_row(source, version=1):
    return (source, version, "import", "runtime", "pdf", "original.pdf", SHA, 10, "converted.md", SHA, 10, "standin", None, None, "[]",
            "{}", "v1", STAMP, None)


def test_a_store_at_18_migrates_to_19_keeps_every_source_and_version_and_admits_onedrive(tmp_path):
    path = tmp_path / "eighteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 19):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, ?, 'x')", (version, STAMP))
    for source, kind, origin, description in (("plain", "file", "survey.csv", "a description"), ("page", "notion", "a" * 32, None),
                                              ("notes", "drive", DOC, "from Drive"), ("trick", "file", "drive-notes.md", None)):
        old.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)", (source, kind, origin, description, STAMP, STAMP))
    for source in ("plain", "notes"):
        old.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", version_row(source))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, status) VALUES (1, 's', 'm', 'h', 'a', 'ok')")
    old.execute("INSERT INTO task_sources VALUES (1, 1, 'notes', 1, ?, ?)", (SHA, STAMP))
    old.commit()
    tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = [r[1] for r in old.execute("PRAGMA table_info(sources)")]
    triggers = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'sources'")}
    before = {t: old.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("sources", "source_versions", "task_sources")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 18 and out["applied"] == [19, 20] and out["schema_version"] == 20
    conn = store.open_db(path)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables | {"reminders"}, "migration 19 adds no table and leaves none over (migration 20 adds the reminders)"
    assert [r[1] for r in conn.execute("PRAGMA table_info(sources)")] == columns
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'sources'")} == triggers
    after = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("sources", "source_versions", "task_sources")}
    for table in before:
        assert [tuple(r) for r in after[table]] == [tuple(r) for r in before[table]], f"{table}: no row is rewritten"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.source_latest(conn, "notes")["version"] == 1
    assert store.init_db(path)["applied"] == []
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM sources WHERE id = 'notes'")
    with pytest.raises(sqlite3.DatabaseError, match="only its description changes"):
        conn.execute("UPDATE sources SET origin = 'x' WHERE id = 'notes'")
    with pytest.raises(sqlite3.DatabaseError, match="only its description changes"):
        conn.execute("UPDATE sources SET type = 'onedrive' WHERE id = 'plain'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sources VALUES ('odd', 'ftp', 'x', NULL, 'a', 'a')")
    conn.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", version_row("notes", 2))     # the foreign key still holds
    row = store.source_add(conn, source_id="weekly", source_type="onedrive", origin=ITEM)
    assert (row["type"], row["origin"]) == ("onedrive", ITEM)
    conn.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", version_row("weekly"))


def test_a_store_made_at_19_admits_the_onedrive_type_and_refuses_one_outside_the_list(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    conn = store.open_db(path)
    assert store.SOURCE_TYPES == ("file", "notion", "drive", "onedrive")
    assert store.source_add(conn, source_id="weekly", source_type="onedrive", origin=ITEM, description="The weekly note.")["origin"] == ITEM
    with pytest.raises(store.StoreError, match="type is one of file, notion, drive, onedrive"):
        store.source_add(conn, source_id="x", source_type="ftp", origin="y")
    assert "'onedrive'" in conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sources'").fetchone()[0], "the CHECK holds the same words"

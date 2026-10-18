"""Offline tests for migration 21 of providers/store/sqlite.py (package RT-1): the sources table is rebuilt to admit the types `mail` and
`calendar`. A store at the version before it (built through the real migrations, 20 in it when the reminders package is on the branch) migrating
with every source of every type (no row rewritten), the versions and the record of what a run received untouched, both triggers still in force,
the foreign key still holding, and a type outside the closed list still refused. Every name and id below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_mail.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_mail", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

GMAIL = "gmail:box=inbox;days=7;max=50"
OUTLOOK = "outlook:box=unread;days=3;max=20"
GOOGLE = "google:calendar=primary;past=0;ahead=14"
ITEM = "b!Fake-Drive_1/ITEM1!101"
SHA = "a" * 64
STAMP = "2026-10-17T00:00:00.000000Z"
BEFORE = [v for v in sorted(store.MIGRATIONS) if v < 21]


def version_row(source, version=1):
    return (source, version, "import", "runtime", "mail", "original.md", SHA, 10, "converted.md", SHA, 10, "mail", None, None, "[]",
            "{}", "v1", STAMP, None)


def store_before(path, up_to=None):
    """A store made by the real migrations below 21 (or up to `up_to`), the way a store of that version is."""
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in [v for v in BEFORE if up_to is None or v <= up_to]:
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, ?, 'x')", (version, STAMP))
    return old


def test_a_store_at_the_version_before_migrates_to_21_keeps_every_source_and_version_and_admits_mail_and_calendar(tmp_path):
    path = tmp_path / "before.sqlite"
    old = store_before(path)
    assert BEFORE[-1] in (19, 20) and 21 not in BEFORE
    for source, kind, origin, description in (("plain", "file", "survey.csv", "a description"), ("page", "notion", "a" * 32, None),
                                              ("notes", "drive", "1AbCdEfGhIjKlMnOpQrStUvWxYz", "from Drive"), ("weekly", "onedrive", ITEM, None),
                                              ("trick", "file", "gmail:box=inbox;days=7;max=50", None)):
        old.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?)", (source, kind, origin, description, STAMP, STAMP))
    for source in ("plain", "weekly"):
        old.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", version_row(source))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'a', 'a')")
    old.execute("INSERT INTO task_runs (task_id, skill, model, adapter, started_at, status) VALUES (1, 's', 'm', 'h', 'a', 'ok')")
    old.execute("INSERT INTO task_sources VALUES (1, 1, 'weekly', 1, ?, ?)", (SHA, STAMP))
    old.commit()
    tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = [r[1] for r in old.execute("PRAGMA table_info(sources)")]
    triggers = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'sources'")}
    before = {t: old.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("sources", "source_versions", "task_sources")}
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == BEFORE[-1] and out["applied"] == [21] and out["schema_version"] == 21 == store.SCHEMA_VERSION
    conn = store.open_db(path)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables, "no table is added and none is left over"
    assert [r[1] for r in conn.execute("PRAGMA table_info(sources)")] == columns
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'sources'")} == triggers
    after = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall() for t in ("sources", "source_versions", "task_sources")}
    for table in before:
        assert [tuple(r) for r in after[table]] == [tuple(r) for r in before[table]], f"{table}: no row is rewritten"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.source_latest(conn, "weekly")["version"] == 1
    assert store.init_db(path)["applied"] == []
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM sources WHERE id = 'weekly'")
    with pytest.raises(sqlite3.DatabaseError, match="only its description changes"):
        conn.execute("UPDATE sources SET origin = 'x' WHERE id = 'weekly'")
    with pytest.raises(sqlite3.DatabaseError, match="only its description changes"):
        conn.execute("UPDATE sources SET type = 'mail' WHERE id = 'trick'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sources VALUES ('odd', 'ftp', 'x', NULL, 'a', 'a')")
    conn.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", version_row("weekly", 2))     # the foreign key still holds
    for source, kind, origin in (("inbox", "mail", GMAIL), ("work-inbox", "mail", OUTLOOK), ("agenda", "calendar", GOOGLE)):
        row = store.source_add(conn, source_id=source, source_type=kind, origin=origin, description="A window.")
        assert (row["type"], row["origin"], row["description"]) == (kind, origin, "A window.")
    conn.execute("INSERT INTO source_versions VALUES (" + ", ".join("?" * 19) + ")", version_row("inbox"))
    assert store.source_latest(conn, "inbox")["kind"] == "mail"


def test_a_store_from_an_older_version_reaches_21_through_every_migration_and_keeps_its_sources(tmp_path):
    path = tmp_path / "eighteen.sqlite"
    old = store_before(path, up_to=18)
    old.execute("INSERT INTO sources VALUES ('plain', 'file', 'survey.csv', NULL, ?, ?)", (STAMP, STAMP))
    old.commit()
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 18 and out["applied"][-1] == 21 and out["applied"][0] == 19 and out["schema_version"] == 21
    conn = store.open_db(path)
    assert [tuple(r) for r in conn.execute("SELECT id, type, origin FROM sources")] == [("plain", "file", "survey.csv")]
    assert store.source_add(conn, source_id="agenda", source_type="calendar", origin=GOOGLE)["type"] == "calendar"


def test_a_store_made_today_has_the_two_types_in_its_check_and_in_the_list_and_refuses_any_other(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    conn = store.open_db(path)
    assert store.SOURCE_TYPES == ("file", "notion", "drive", "onedrive", "mail", "calendar")
    assert "mail, calendar" in store.MIGRATIONS[21][0] or "mail and calendar" in store.MIGRATIONS[21][0]
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'sources'").fetchone()[0]
    assert all(f"'{word}'" in sql for word in store.SOURCE_TYPES), "the CHECK holds the same words"
    with pytest.raises(store.StoreError, match="type is one of file, notion, drive, onedrive, mail, calendar"):
        store.source_add(conn, source_id="x", source_type="imap", origin="y")
    assert store.source_add(conn, source_id="inbox", source_type="mail", origin=GMAIL)["origin"] == GMAIL
    with pytest.raises(store.StoreError, match="already registered"):
        store.source_add(conn, source_id="inbox", source_type="mail", origin=GMAIL)

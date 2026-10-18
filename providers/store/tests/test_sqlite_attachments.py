"""Offline tests for migration 18 of providers/store/sqlite.py (package ATT-1): the `attachments` table and the `provenance` column of
`source_versions`. A store at 17 migrating with every row kept, the one record of a held file (its platform reference only as a hash), the
duplicate that delivery at least once brings, the decision that is final, the table that is never deleted from, the day's count and the
provenance a version keeps. Every name and id below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_attachments.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_attachments", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

REF = "b" * 64
FILE = "c" * 64


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def held(conn, **over):
    fields = dict(platform="telegram", ref_sha256=REF, sender="1234", profile="staff", name="Q3 plan.pdf", declared_type="application/pdf",
                  declared_bytes=2048, kind="pdf", sha256=FILE, size=2048, target="q3-plan", label="import")
    fields.update(over)
    return store.attachment_add(conn, **fields)


def test_a_store_at_17_migrates_to_18_keeps_every_row_adds_one_table_and_one_column(tmp_path):
    path = tmp_path / "seventeen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 18):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-16T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO sources VALUES ('notes', 'file', 'notes.md', NULL, 'a', 'a')")
    old.execute("INSERT INTO source_versions VALUES ('notes', 1, 'import', 'runtime', 'text', 'original.txt', ?, 10, 'converted.md', ?, 10, "
                "'standin', NULL, 0, '[]', '{}', NULL, 'a')", (FILE, FILE))
    old.commit()
    tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = [r[1] for r in old.execute("PRAGMA table_info(source_versions)")]
    before = [tuple(r) for r in old.execute("SELECT * FROM source_versions")]
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 17 and out["applied"] == [18, 19, 20] and out["schema_version"] == 20
    conn = store.open_db(path)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables | {"attachments", "reminders"}
    assert [r[1] for r in conn.execute("PRAGMA table_info(source_versions)")] == columns + ["provenance"]
    after = [tuple(r) for r in conn.execute("SELECT * FROM source_versions")]
    assert [row[:-1] for row in after] == before and after[0][-1] is None, "a version older than the column has no provenance"
    assert store.source_latest(conn, "notes")["provenance"] is None
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.init_db(path)["applied"] == []


def test_a_held_file_is_one_row_with_the_hash_of_its_reference_and_the_sender_who_sent_it(conn):
    row = held(conn)
    assert row["id"] == 1 and row["status"] == "held" and row["direct"] is False and row["decided_at"] is None
    assert row["ref_sha256"] == REF and "ref" not in row, "the platform's reference is never stored, only its hash"
    assert (row["platform"], row["sender"], row["profile"], row["kind"], row["target"], row["label"]) == ("telegram", "1234", "staff", "pdf", "q3-plan", "import")
    assert store.attachment_get(conn, 1) == row and store.attachment_held_by_ref(conn, "telegram", REF)["id"] == 1
    assert store.attachment_held_by_ref(conn, "discord", REF) is None and store.attachment_held_by_ref(conn, "telegram", "d" * 64) is None
    with pytest.raises(store.StoreError, match="no attachment 9"):
        store.attachment_get(conn, 9)


def test_the_same_reference_cannot_be_held_twice_but_can_again_once_it_was_decided(conn):
    held(conn)
    with pytest.raises(store.StoreError, match="already held"):
        held(conn)
    assert held(conn, platform="discord")["id"] == 2, "another platform's reference is another file"
    store.attachment_decide(conn, 1, "discarded")
    assert held(conn)["id"] == 3
    with pytest.raises(sqlite3.IntegrityError):    # the database holds the rule too, not only the function
        conn.execute("INSERT INTO attachments (platform, ref_sha256, sender, name, bytes, status, created_at) "
                     "VALUES ('telegram', ?, 's', 'n', 1, 'held', 'a')", (REF,))


def test_a_decision_is_final_and_the_rest_of_the_row_never_changes(conn):
    held(conn)
    done = store.attachment_decide(conn, 1, "added", source_id="q3-plan", version=1)
    assert done["status"] == "added" and (done["source_id"], done["version"]) == ("q3-plan", 1) and done["decided_at"]
    with pytest.raises(store.StoreError, match="is added, not held"):
        store.attachment_decide(conn, 1, "discarded")
    for statement in ("UPDATE attachments SET status = 'held' WHERE id = 1", "UPDATE attachments SET sender = 'x' WHERE id = 1",
                      "UPDATE attachments SET status = 'discarded' WHERE id = 1"):
        with pytest.raises(sqlite3.DatabaseError, match="leaves held once"):
            conn.execute(statement)
    second = held(conn, ref_sha256="e" * 64)
    for statement in ("UPDATE attachments SET sender = 'x' WHERE id = ?", "UPDATE attachments SET sha256 = NULL WHERE id = ?",
                      "UPDATE attachments SET bytes = 1 WHERE id = ?", "UPDATE attachments SET name = 'other' WHERE id = ?"):
        with pytest.raises(sqlite3.DatabaseError, match="leaves held once"):
            conn.execute(statement, (second["id"],))
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM attachments WHERE id = 1")


def test_each_decision_records_what_it_needs_and_an_unknown_one_is_refused(conn):
    held(conn)
    with pytest.raises(store.StoreError, match="names the source and the version"):
        store.attachment_decide(conn, 1, "added")
    with pytest.raises(store.StoreError, match="code of its refusal"):
        store.attachment_decide(conn, 1, "refused")
    with pytest.raises(store.StoreError, match="one of"):
        store.attachment_decide(conn, 1, "held")
    with pytest.raises(store.StoreError, match="no attachment 7"):
        store.attachment_decide(conn, 7, "expired")
    assert store.attachment_decide(conn, 1, "refused", code="credential")["code"] == "credential"
    other = held(conn, ref_sha256="e" * 64)
    assert store.attachment_decide(conn, other["id"], "expired")["status"] == "expired"


def test_a_file_refused_when_its_bytes_arrived_is_recorded_decided_and_still_counts_for_the_day(conn):
    row = held(conn, status="refused", code="mismatch", size=4096)
    assert row["status"] == "refused" and row["code"] == "mismatch" and row["decided_at"] == row["created_at"]
    assert store.attachment_held_by_ref(conn, "telegram", REF) is None, "a refused file is not held"
    held(conn, ref_sha256="e" * 64, size=1000)
    assert store.attachments_since(conn, "1970-01-01T00:00:00.000000Z") == {"files": 2, "bytes": 5096}
    assert store.attachments_since(conn, "2999-01-01T00:00:00.000000Z") == {"files": 0, "bytes": 0}
    with pytest.raises(store.StoreError, match="code of its refusal"):
        held(conn, ref_sha256="f" * 64, status="refused")
    with pytest.raises(store.StoreError, match="held or refused"):
        held(conn, ref_sha256="f" * 64, status="added")


def test_the_day_counts_from_a_time_and_the_list_is_filtered_by_status_and_age(conn):
    for n, day in enumerate(("2026-10-01", "2026-10-02", "2026-10-03"), 1):
        held(conn, ref_sha256=f"{n}" * 64, created_at=f"{day}T10:00:00.000000Z", size=100 * n)
    assert store.attachments_since(conn, "2026-10-02T00:00:00.000000Z") == {"files": 2, "bytes": 500}
    assert [r["id"] for r in store.attachments_list(conn)] == [1, 2, 3]
    assert [r["id"] for r in store.attachments_list(conn, older_than="2026-10-03T00:00:00.000000Z")] == [1, 2]
    store.attachment_decide(conn, 2, "discarded")
    assert [r["id"] for r in store.attachments_list(conn, statuses=["held"])] == [1, 3]
    assert [r["id"] for r in store.attachments_list(conn, statuses=("discarded", "added"))] == [2]
    assert [r["id"] for r in store.attachments_list(conn, limit=1)] == [3], "the newest `limit`, oldest first"
    with pytest.raises(store.StoreError, match="one of"):
        store.attachments_list(conn, statuses=["lost"])


@pytest.mark.parametrize("field,value", [("ref_sha256", "nothex"), ("sha256", "short"), ("platform", ""), ("sender", ""), ("target", "Bad Id"),
                                         ("label", "mine"), ("name", "x" * 600), ("kind", "a\nb")])
def test_a_field_that_is_not_shaped_as_the_store_takes_it_is_refused_and_nothing_is_written(conn, field, value):
    with pytest.raises(store.StoreError):
        held(conn, **{field: value})
    assert store.attachments_list(conn) == []


def test_a_source_version_keeps_the_provenance_it_was_given_and_none_otherwise(conn):
    store.source_add(conn, source_id="q3-plan", source_type="file", origin="Q3 plan.pdf")
    common = dict(source_id="q3-plan", label="import", by="runtime", kind="pdf", original_name="original.pdf", original_sha256=FILE, original_bytes=10,
                  converted_name="converted.md", converted_sha256=FILE, converted_bytes=10, converter="standin", converter_version=None,
                  warnings=[], catalog={}, origin_version=None, imported_at="2026-10-16T00:00:00.000000Z")
    plain = store.source_version_add(conn, version=1, **common)
    assert plain["provenance"] is None
    came = {"channel": "messaging", "platform": "telegram", "profile": "staff", "attachment": 7}
    second = store.source_version_add(conn, version=2, provenance=came, **common)
    assert second["provenance"] == came and store.source_latest(conn, "q3-plan")["provenance"] == came
    assert [v["provenance"] for v in store.source_versions(conn, "q3-plan")] == [None, came]
    with pytest.raises(store.StoreError, match="small object"):
        store.source_version_add(conn, version=3, provenance=["a"], **common)
    with pytest.raises(store.StoreError, match="small object"):
        store.source_version_add(conn, version=3, provenance={"x": "y" * 5000}, **common)
    with pytest.raises(sqlite3.DatabaseError, match="never changed"):
        conn.execute("UPDATE source_versions SET provenance = NULL WHERE version = 2")

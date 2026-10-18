"""Offline tests for migration 20 of providers/store/sqlite.py (package RM-1): the `reminders` table. A store at 18 migrating with every row kept, the caps
counted in the transaction that writes, the claim that one caller wins, the late and stale rules' building blocks, the words that never change, the
ended reminder that stays as it ended, the table that is never deleted from and that the export does not carry. Every name and id below is invented.

Run: uv run --with pytest==9.1.1 pytest providers/store/tests/test_sqlite_reminders.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "sqlite.py"
spec = importlib.util.spec_from_file_location("store_sqlite_reminders", SCRIPT)
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

DAY = "2026-10-18T03:00:00.000000Z"
DUE = "2026-10-18T18:00:00.000000Z"


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "state" / "tasks.sqlite"
    store.init_db(path)
    return store.open_db(path)


def add(conn, **over):
    fields = dict(text="Call the dentist", due_local="2026-10-18T15:00", due_utc=DUE, zone="BRT", platform="telegram", chat="1234", created_by="terminal",
                  max_open=100, max_day=30, day_since=DAY, created_at="2026-10-18T17:00:00.000000Z")
    fields.update(over)
    return store.reminder_add(conn, **fields)


def test_a_store_at_18_migrates_to_20_keeps_every_row_and_adds_one_table(tmp_path):
    path = tmp_path / "eighteen.sqlite"
    old = sqlite3.connect(path)
    old.execute("PRAGMA foreign_keys = ON")
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in range(1, 19):
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-17T00:00:00.000000Z', 'x')", (version,))
    old.execute("INSERT INTO tasks (title, text, state, created_at, updated_at) VALUES ('R', 'R.', 'planned', 'a', 'a')")
    old.commit()
    tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    before = [tuple(r) for r in old.execute("SELECT * FROM tasks")]
    old.close()
    out = store.init_db(path)
    assert out["migrated_from"] == 18 and out["applied"] == [19, 20] and out["schema_version"] == 20 == store.SCHEMA_VERSION
    conn = store.open_db(path)
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables | {"reminders"}
    assert [tuple(r) for r in conn.execute("SELECT * FROM tasks")] == before
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == [] and conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.init_db(path)["applied"] == []
    assert "reminders" in store.MIGRATIONS[20][0]


def test_a_reminder_is_one_row_with_its_words_its_moment_and_the_one_chat_it_goes_to(conn):
    row = add(conn)
    assert row["id"] == 1 and row["status"] == "open" and row["why"] is None and row["claimed_at"] is None and row["ended_at"] is None
    assert (row["text"], row["due_local"], row["due_utc"], row["zone"], row["platform"], row["chat"], row["created_by"]) == (
        "Call the dentist", "2026-10-18T15:00", DUE, "BRT", "telegram", "1234", "terminal")
    assert store.reminder_get(conn, 1) == row
    with pytest.raises(store.StoreError, match="no reminder 9"):
        store.reminder_get(conn, 9)
    for over in ({"text": "   "}, {"chat": ""}, {"due_utc": "2026-10-18 18:00"}, {"due_utc": "2026-10-18T18:00:00Z"}, {"text": "a\x00b"}, {"text": "é" * 700}):
        with pytest.raises(store.StoreError):
            add(conn, **over)
    assert len(store.reminders_list(conn)) == 1


def test_the_caps_are_counted_in_the_transaction_that_writes(conn):
    for n in range(3):
        add(conn, max_open=3, text=f"line {n}", chat=str(n))
    with pytest.raises(store.StoreError) as e:
        add(conn, max_open=3)
    assert str(e.value) == store.REMINDER_OPEN_FULL
    store.reminder_claim(conn, 1)
    with pytest.raises(store.StoreError) as e:
        add(conn, max_open=3)
    assert str(e.value) == store.REMINDER_OPEN_FULL, "a reminder being sent still waits"
    store.reminder_end(conn, 1, "sent")
    assert add(conn, max_open=3, chat="9")["id"] == 4, "a sent one makes room"
    for n in range(2):
        add(conn, max_open=100, max_day=3, chat="77", text=f"x{n}")
    assert add(conn, max_open=100, max_day=3, chat="77")["id"] == 7
    with pytest.raises(store.StoreError) as e:
        add(conn, max_open=100, max_day=3, chat="77")
    assert str(e.value) == store.REMINDER_DAY_FULL
    assert add(conn, max_open=100, max_day=3, chat="78")["chat"] == "78", "another chat has its own day"
    assert add(conn, max_open=100, max_day=3, chat="77", day_since="2026-10-19T03:00:00.000000Z")["id"] == 9, "a new day counts from its start"
    assert add(conn, max_open=100, max_day=3, platform="chirp", chat="77")["platform"] == "chirp", "and so does another platform"


def test_listing_the_waiting_ones_by_their_time_and_the_ended_ones_newest_first(conn):
    add(conn, due_utc="2026-10-18T20:00:00.000000Z", text="later", chat="1")
    add(conn, due_utc="2026-10-18T18:00:00.000000Z", text="sooner", chat="2")
    add(conn, due_utc="2026-10-18T19:00:00.000000Z", text="middle", chat="1", platform="chirp")
    assert [r["text"] for r in store.reminders_list(conn, ["open"])] == ["sooner", "middle", "later"]
    assert [r["text"] for r in store.reminders_list(conn, ["open"], "telegram")] == ["sooner", "later"]
    assert [r["text"] for r in store.reminders_list(conn, ["open"], "telegram", "1")] == ["later"]
    store.reminder_end(conn, 1, "cancelled", at="2026-10-18T10:00:00.000000Z")
    store.reminder_end(conn, 2, "dropped", why="sender removed", at="2026-10-18T11:00:00.000000Z")
    assert [r["id"] for r in store.reminders_list(conn, ["cancelled", "dropped"])] == [2, 1]
    assert [r["id"] for r in store.reminders_list(conn, ["cancelled", "dropped"], ended_since="2026-10-18T10:30:00.000000Z")] == [2]
    assert [r["id"] for r in store.reminders_list(conn, ["open"], ended_since="2026-10-30T00:00:00.000000Z")] == [3], "a waiting one has not ended"
    with pytest.raises(store.StoreError):
        store.reminders_list(conn, ["nothing"])


def test_the_due_ones_of_a_platform_are_the_open_ones_at_or_before_the_moment(conn):
    add(conn, due_utc="2026-10-18T18:00:00.000000Z", text="a")
    add(conn, due_utc="2026-10-18T18:00:01.000000Z", text="b")
    add(conn, due_utc="2026-10-18T17:00:00.000000Z", text="c", platform="chirp")
    add(conn, due_utc="2026-10-18T16:00:00.000000Z", text="d")
    store.reminder_claim(conn, 4)
    assert [r["text"] for r in store.reminders_due(conn, "telegram", "2026-10-18T18:00:00.000000Z")] == ["a"]
    assert [r["text"] for r in store.reminders_due(conn, "telegram", "2026-10-18T18:00:01.000000Z")] == ["a", "b"]
    assert [r["text"] for r in store.reminders_due(conn, "chirp", "2026-10-19T00:00:00.000000Z")] == ["c"]


def test_one_caller_wins_the_claim_and_a_failed_send_gives_it_back(conn):
    add(conn)
    assert store.reminder_claim(conn, 1, "2026-10-18T18:00:00.000000Z") is True
    assert store.reminder_claim(conn, 1) is False, "the second caller finds it taken"
    row = store.reminder_get(conn, 1)
    assert row["status"] == "sending" and row["claimed_at"] == "2026-10-18T18:00:00.000000Z"
    assert store.reminder_release(conn, 1) is True and store.reminder_release(conn, 1) is False
    assert store.reminder_get(conn, 1)["status"] == "open" and store.reminder_get(conn, 1)["claimed_at"] is None
    assert store.reminder_claim(conn, 1) is True
    done = store.reminder_end(conn, 1, "sent", at="2026-10-18T18:00:05.000000Z")
    assert (done["status"], done["ended_at"], done["why"]) == ("sent", "2026-10-18T18:00:05.000000Z", None)
    assert store.reminder_claim(conn, 1) is False and store.reminder_release(conn, 1) is False


def test_a_claim_of_a_bridge_that_stopped_is_open_again_after_the_time_given(conn):
    add(conn, chat="1")
    add(conn, chat="2")
    store.reminder_claim(conn, 1, "2026-10-18T18:00:00.000000Z")
    store.reminder_claim(conn, 2, "2026-10-18T18:09:00.000000Z")
    assert store.reminders_reclaim(conn, "2026-10-18T17:59:59.000000Z") == 0
    assert store.reminders_reclaim(conn, "2026-10-18T18:00:00.000000Z") == 1
    assert [r["status"] for r in store.reminders_list(conn, ["open", "sending"])] == ["open", "sending"]
    assert store.reminders_reclaim(conn, "2026-10-18T18:10:00.000000Z") == 1


def test_a_reminder_ends_in_one_of_four_ways_each_from_the_state_it_may_come_from(conn):
    for n in range(5):
        add(conn, chat=str(n))
    assert store.reminder_end(conn, 1, "cancelled")["status"] == "cancelled"
    assert store.reminder_end(conn, 2, "missed", why="late")["why"] == "late"
    assert store.reminder_end(conn, 3, "dropped", why="not permitted")["why"] == "not permitted"
    with pytest.raises(store.StoreError, match="not sending"):
        store.reminder_end(conn, 4, "sent")                    # only a claimed reminder is sent
    store.reminder_claim(conn, 4)
    with pytest.raises(store.StoreError, match="not open"):
        store.reminder_end(conn, 4, "cancelled")               # and a reminder being sent is not forgotten
    assert store.reminder_end(conn, 4, "dropped", why="sender removed")["status"] == "dropped", "a claimed one may be given up"
    for bad in ({"status": "open"}, {"status": "missed"}, {"status": "dropped", "why": "late "}, {"status": "dropped", "why": "somehow"},
                {"status": "sent", "why": "late"}, {"status": "cancelled", "why": "late"}):
        with pytest.raises(store.StoreError):
            store.reminder_end(conn, 5, **bad)
    for status in ("cancelled", "sent", "missed", "dropped"):
        with pytest.raises(store.StoreError):
            store.reminder_end(conn, 1, status, **({"why": "late"} if status in ("missed", "dropped") else {}))      # an ended reminder is final
    with pytest.raises(store.StoreError, match="no reminder 9"):
        store.reminder_end(conn, 9, "cancelled")


def test_the_table_itself_refuses_a_delete_a_change_of_what_it_says_and_a_move_out_of_an_end(conn):
    add(conn)
    with pytest.raises(sqlite3.DatabaseError, match="never deleted"):
        conn.execute("DELETE FROM reminders")
    for column, value in (("text", "other words"), ("due_utc", DAY), ("due_local", "x"), ("zone", "UTC"), ("platform", "chirp"), ("chat", "9"),
                          ("created_by", "page"), ("created_at", DAY), ("id", 5)):
        with pytest.raises(sqlite3.DatabaseError, match="never changes"):
            conn.execute(f"UPDATE reminders SET {column} = ?", (value,))
    with pytest.raises(sqlite3.DatabaseError, match="sent only after it was claimed"):
        conn.execute("UPDATE reminders SET status = 'sent'")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE reminders SET status = 'dropped'")                       # a dropped reminder says why
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE reminders SET status = 'bogus'")
    store.reminder_end(conn, 1, "cancelled")
    for status in ("open", "sending", "sent"):
        with pytest.raises(sqlite3.DatabaseError, match="stays as it ended"):
            conn.execute("UPDATE reminders SET status = ?", (status,))
    with pytest.raises(sqlite3.DatabaseError, match="stays as it ended"):
        conn.execute("UPDATE reminders SET ended_at = 'x'")


def test_the_export_does_not_carry_the_words_of_a_reminder(conn):
    add(conn, text="Call the dentist about Thursday")
    assert "reminders" not in {name for name, *_ in store.EXPORT_QUERIES}
    import json
    import subprocess
    import sys
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    out = subprocess.run([sys.executable, str(SCRIPT), "--db", path, "export", "--format", "json"], capture_output=True, text=True, check=True).stdout
    assert "dentist" not in out and "reminders" not in json.loads(out)


# --- review of RM-1 ----------------------------------------------------------------------------------------------------------------------------


def test_one_chat_cannot_hold_more_than_its_share_of_the_open_ones(conn):
    for n in range(3):
        add(conn, max_open_chat=3, text=f"line {n}", chat="1")
    with pytest.raises(store.StoreError) as e:
        add(conn, max_open_chat=3, chat="1")
    assert str(e.value) == store.REMINDER_CHAT_FULL
    assert add(conn, max_open_chat=3, chat="2")["chat"] == "2", "another chat is not blocked"
    assert add(conn, max_open_chat=3, chat="1", platform="chirp")["platform"] == "chirp", "nor the same id on another platform"
    store.reminder_claim(conn, 1)
    with pytest.raises(store.StoreError):
        add(conn, max_open_chat=3, chat="1")                  # being sent still waits
    store.reminder_end(conn, 1, "sent")
    assert add(conn, max_open_chat=3, chat="1")["id"] == 6


def test_a_failed_send_counts_and_waits_before_it_is_offered_again(conn):
    add(conn)
    until = "2026-10-18T18:30:00.000000Z"
    store.reminder_claim(conn, 1)
    assert store.reminder_release(conn, 1, "2026-10-18T18:10:00.000000Z") is True
    row = store.reminder_get(conn, 1)
    assert (row["status"], row["attempts"], row["retry_after"]) == ("open", 1, "2026-10-18T18:10:00.000000Z")
    assert store.reminders_due(conn, "telegram", "2026-10-18T18:09:59.000000Z") == []
    assert [r["id"] for r in store.reminders_due(conn, "telegram", "2026-10-18T18:10:00.000000Z")] == [1]
    store.reminder_claim(conn, 1)
    store.reminder_release(conn, 1, "2026-10-18T18:12:00.000000Z")
    assert store.reminder_get(conn, 1)["attempts"] == 2 and store.reminders_due(conn, "telegram", until)
    store.reminder_claim(conn, 1)
    assert store.reminder_release(conn, 1) is True and store.reminder_get(conn, 1)["retry_after"] is None, "no time given: offered at once"
    with pytest.raises(store.StoreError):
        store.reminder_release(conn, 1, "soon")
    assert store.reminder_get(conn, 1)["attempts"] == 3


def test_a_store_that_reached_20_without_19_gets_19_applied_and_is_refused_until_then(tmp_path, monkeypatch):
    """Two packages took neighbouring numbers and 20 was merged before 19: init applies every number the store lacks, not only those above its highest."""
    monkeypatch.setitem(store.MIGRATIONS, 19, ("a probe table", ["CREATE TABLE gap_probe (x INTEGER)"]))
    path = tmp_path / "gap.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL, description TEXT NOT NULL)")
    for version in sorted(store.MIGRATIONS):
        if version == 19:
            continue
        for statement in store.MIGRATIONS[version][1]:
            old.execute(statement)
        old.execute("INSERT INTO schema_version VALUES (?, '2026-10-17T00:00:00.000000Z', 'x')", (version,))
    old.commit()
    assert [r[0] for r in old.execute("SELECT version FROM schema_version ORDER BY 1")][-3:] == [17, 18, 20]
    old.close()
    plain = sqlite3.connect(path)
    assert store.missing_migrations(plain) == [19]
    plain.close()
    with pytest.raises(store.StoreError) as e:
        store.open_db(path)
    assert "migration 19" in str(e.value) and "run init" in str(e.value) and e.value.code == store.EXIT_NOT_CONFIGURED
    out = store.init_db(path)
    assert out["applied"] == [19] and out["migrated_from"] == 20 and out["schema_version"] == store.SCHEMA_VERSION
    conn = store.open_db(path)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'gap_probe'").fetchone() is not None
    assert [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY 1")][-3:] == [18, 19, 20]
    assert store.init_db(path)["applied"] == []


def test_a_store_with_no_version_table_is_refused_by_open_ready_and_missing_lists_everything(tmp_path):
    path = tmp_path / "empty.sqlite"
    sqlite3.connect(path).close()
    plain = sqlite3.connect(path)
    assert store.missing_migrations(plain) == sorted(store.MIGRATIONS)
    plain.close()
    with pytest.raises(store.StoreError):
        store.open_db(path)

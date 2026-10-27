"""The unread flag of the mail index (package CB-2; runtime/sources_mail.py, item_refs.py, ops_items.py).

Both readers print `unread` for each message (providers/mailbox/gmail.py from `labelIds`, outlook.py from `isRead`). The mail snapshot's index keeps it as a closed boolean or null for each
message, beside `received`; the index digest covers it for a new snapshot, an index written before the key reads as null and still passes its digest, and a list for a phone puts a closed mark
before a message whose flag is true and nothing before a message whose flag is false or not known. The flag is code's own record of what the provider printed, never a word of the message.

Every expectation is a literal of this file; wording is asserted by phrase key plus values (T8). Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_unread.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_item_refs import desk  # noqa: F401  (the fixture: a desk with a real mail snapshot and its index)
from test_items_fresh import ask, project  # noqa: F401
from test_items_useful import clock, snaps  # noqa: F401  (fixtures)

item_refs = st.load("item_refs")
sources_mail = st.load("sources_mail")
snapshot_text = st.load("snapshot_text")
ops_items = st.load("ops_items")
ops_sources = st.load("ops_sources")
phrases = st.load("phrases")

MARK = "•"


def entry_of(desk_, source="inbox", n=1):
    return item_refs.resolve(desk_.ctx, f"{source}#{n}", channel="terminal", clock=lambda: desk_.now)["entry"]


def flagged(*flags):
    """Provider messages (the stand-in readers' shape) whose `unread` is each of `flags`; a flag of the word `absent` leaves the key out."""
    out = []
    for n, flag in enumerate(flags, 1):
        extra = {} if flag == "absent" else {"unread": flag}
        out.append(tsm.message(n, f"2026-10-17T0{n}:00:00Z", sender=f"Pessoa {n} <pessoa{n}@clinic.example>", subject=f"Assunto {n}", **extra))
    return out


# --- the index keeps the provider's flag ---------------------------------------------------------------------------------------------------------


def test_the_index_entry_holds_true_false_or_null_as_the_provider_printed_it(tmp_path, monkeypatch):
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = flagged(True, False, None, "absent", "yes", 1, 0)
    d.mail("inbox")
    entries = item_refs.read_index(d.ctx, "inbox", channel="terminal", clock=lambda: d.now)["entries"]
    by_subject = {e["subject"]: e["unread"] for e in entries}      # newest first: the numbers follow the time, so the flags are read back by subject
    assert len(entries) == 7
    assert by_subject == {"Assunto 1": True, "Assunto 2": False, "Assunto 3": None, "Assunto 4": None, "Assunto 5": None, "Assunto 6": None, "Assunto 7": None}


def test_the_manifest_index_entry_has_the_key_and_the_keys_stay_closed(desk):  # noqa: F811
    stored = desk.manifest("inbox")["index"]
    assert all("unread" in e and e["unread"] is None for e in stored), "the stand-in readers print none: null, and the key is there"
    assert item_refs.INDEX_KEYS["mail"][-1] == "unread" and set(sources_mail.mail_index_entry(1, tsm.message(1, unread=True))) == set(item_refs.INDEX_KEYS["mail"])


def test_the_index_digest_covers_the_flag(tmp_path, monkeypatch):
    digests = []
    for flag in (True, False):
        d = tsm.Desk(tmp_path / str(flag), monkeypatch)
        d.providers.mail["gmail"] = flagged(flag)
        d.mail("inbox")
        line = snapshot_text.digest_of_text(d.text("inbox"))
        assert line == snapshot_text.index_digest(d.manifest("inbox")["index"]), "the text's digest line is the index's"
        digests.append(line)
    assert digests[0] != digests[1], "two snapshots that differ only in the flag have two digests"


def test_a_credential_hit_empties_the_words_and_leaves_the_flag_and_the_number():
    entry = sources_mail.mail_index_entry(3, tsm.message(3, unread=True), scan=lambda data: True)
    assert entry["n"] == 3 and entry["subject"] == "" and entry["from_address"] is None and entry["received"] is None
    assert entry["unread"] is True, "a closed boolean holds no text"


# --- the read-back ------------------------------------------------------------------------------------------------------------------------------


def raw_entry(**change):
    base = {"n": 1, "id": "m1", "thread_id": "t1", "message_id": "<a1@clinic.example>", "from_address": "ana@clinic.example", "reply_to_address": None,
            "subject": "Appointment confirmed", "change_key": None, "received": "2026-10-22T17:05:00Z", "unread": True}
    base.update(change)
    return base


def test_the_read_back_keeps_a_boolean_and_drops_any_other_value():
    assert item_refs._entry("mail", 1, raw_entry())["unread"] is True
    assert item_refs._entry("mail", 1, raw_entry(unread=False))["unread"] is False
    for value in (None, "true", "false", 1, 0, [], {}, "UNREAD"):
        assert item_refs._entry("mail", 1, raw_entry(unread=value))["unread"] is None, repr(value)
    without = {k: v for k, v in raw_entry().items() if k != "unread"}
    assert item_refs._entry("mail", 1, without)["unread"] is None, "an entry written before the key had none"
    assert set(item_refs._entry("mail", 1, raw_entry(extra="x"))) == set(item_refs.INDEX_KEYS["mail"]), "the keys are closed"


def test_an_index_written_before_the_key_still_passes_its_digest_and_reads_null(tmp_path, monkeypatch):
    real = sources_mail.mail_index_entry

    def old(n, message, scan=None, moment=None):      # the entry as it was written before the key
        entry = real(n, message, scan, moment)
        entry.pop("unread")
        return entry
    monkeypatch.setattr(sources_mail, "mail_index_entry", old)
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = flagged(True)
    d.mail("inbox")
    assert "unread" not in d.manifest("inbox")["index"][0]
    got = item_refs.resolve(d.ctx, "inbox#1", channel="terminal", clock=lambda: d.now)      # an index that does not match its digest is refused: it does match
    assert got["entry"]["unread"] is None and got["entry"]["subject"] == "Assunto 1" and got["entry"]["id"] == "m1"


def test_the_other_fields_of_an_entry_are_unchanged_by_the_flag(desk):  # noqa: F811
    entry = entry_of(desk)
    assert (entry["id"], entry["thread_id"], entry["from_address"], entry["subject"], entry["received"]) == ("m1", "t1", "ana@clinic.example", "Appointment confirmed", "2026-10-17T09:00:00Z")


# --- the list: the rows and the phone's mark ------------------------------------------------------------------------------------------------------


def inbox(world, snaps, messages, language="en"):  # noqa: F811
    project(world, language)
    snaps.providers.mail["gmail"] = messages
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    del snaps.providers.calls[:]


def test_a_row_has_the_flag_only_when_the_index_knows_it(world, snaps, clock):  # noqa: F811
    inbox(world, snaps, flagged(True, False, None))
    ops = st.load("ops")
    rows = {r["line"].split(" · ")[1]: r for r in ops.items(world["path"], kind="mail", channel="terminal")["sources"][0]["items"]}
    assert rows["Assunto 1"]["unread"] is True and rows["Assunto 2"]["unread"] is False and "unread" not in rows["Assunto 3"]


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_a_phone_marks_the_unread_messages_and_only_those(world, snaps, clock, language):  # noqa: F811
    inbox(world, snaps, flagged(True, False, None, "absent"), language)
    reply = ask(world, "list my emails" if language == "en" else "lista meus emails")
    cfg = {"language": language}
    assert phrases.text("NW_ITEMS_UNREAD_MARK", cfg) == MARK
    lines = [line for line in reply.splitlines() if line[:1].isdigit()]
    marked = [line for line in lines if f". {MARK} " in line]
    assert len(lines) == 4 and len(marked) == 1 and "Pessoa 1" in marked[0], reply
    assert all(MARK not in line for line in lines if "Pessoa 1" not in line)


def test_the_terminal_list_keeps_its_form(world, snaps, clock):  # noqa: F811
    inbox(world, snaps, flagged(True, False))
    ops = st.load("ops")
    out = ops.items(world["path"], kind="mail", channel="terminal")
    assert MARK not in ops_items.render(out, {"language": "en"}), "the mark is the phone's"


def test_a_phone_list_with_no_flag_anywhere_is_the_list_it_was(world, snaps, clock):  # noqa: F811
    inbox(world, snaps, flagged("absent", "absent"))
    reply = ask(world, "list my emails")
    assert MARK not in reply and "Pessoa 1" in reply and "Pessoa 2" in reply


# --- vacuity: a planted wrong result fails the oracles above ---------------------------------------------------------------------------------------


def test_vacuity_an_index_that_drops_the_flag_is_seen_by_the_oracles(tmp_path, monkeypatch):
    real = sources_mail.mail_index_entry

    def dropping(n, message, scan=None, moment=None):
        entry = real(n, message, scan, moment)
        entry["unread"] = None
        return entry
    monkeypatch.setattr(sources_mail, "mail_index_entry", dropping)
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = flagged(True)
    d.mail("inbox")
    assert entry_of(d)["unread"] is None and entry_of(d)["unread"] is not True


def test_vacuity_a_read_back_that_trusts_any_value_is_seen_by_the_oracle():
    wrong = lambda raw: raw.get("unread")      # noqa: E731  (a read-back with no shape check)
    assert wrong(raw_entry(unread="true")) == "true" and item_refs._entry("mail", 1, raw_entry(unread="true"))["unread"] is None


def test_vacuity_the_phone_render_follows_the_flag_and_a_flipped_flag_moves_the_mark():
    def listing(first, second):
        row = lambda n, flag: {"n": n, "line": f"x{n}", "received": None, "unread": flag, "mail": {"who": f"Pessoa {n}", "subject": f"Assunto {n}"}}      # noqa: E731
        return {"sources": [{"source": "inbox", "type": "mail", "account": "google", "read_at": "2026-10-19T09:00:00Z", "items": [row(1, first), row(2, second)]}], "refused": []}
    cfg = {"language": "en"}
    right = ops_items.render(listing(True, False), cfg, phone=True, names={"inbox": "Gmail"}).splitlines()
    assert right[1].startswith(f"1. {MARK} Pessoa 1") and right[2].startswith("2. Pessoa 2"), right
    planted = ops_items.render(listing(False, True), cfg, phone=True, names={"inbox": "Gmail"}).splitlines()
    assert planted[1].startswith("1. Pessoa 1") and planted[2].startswith(f"2. {MARK} Pessoa 2") and planted != right, "the oracle tells the two apart"


# --- the reading's signature: a message read on the phone makes a new version ---------------------------------------------------------------------


def test_a_flag_that_flips_makes_a_new_version_and_the_same_flag_makes_none(tmp_path, monkeypatch):
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = flagged(True)
    d.mail("inbox")
    assert d.count("inbox") == 1
    d.refresh("inbox")
    assert d.count("inbox") == 1, "the listing did not change: no new version"
    d.providers.mail["gmail"] = flagged(False)      # the same message, read in the meantime: no id and no change key moved
    d.refresh("inbox")
    assert d.count("inbox") == 2 and entry_of(d)["unread"] is False, "the snapshot says what the mailbox says now"


def test_a_provider_that_prints_no_flag_keeps_the_signature_it_had(tmp_path, monkeypatch):
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = flagged("absent", "absent")
    snap = sources_mail.read_snapshot(d.cfg, "mail", "gmail:box=inbox;days=7;max=50", call=d.providers, clock=lambda: d.now)
    pairs = [(m["id"], "") for m in d.providers.mail["gmail"]]
    assert snap["signature"] == sources_mail._signature(pairs, snap["label"], d.now.astimezone(sources_mail.ZONE).date().isoformat())
    d.providers.mail["gmail"] = flagged(True, "absent")
    changed = sources_mail.read_snapshot(d.cfg, "mail", "gmail:box=inbox;days=7;max=50", call=d.providers, clock=lambda: d.now)
    assert changed["signature"] != snap["signature"], "a flag that appears is a change"


def test_vacuity_a_signature_blind_to_the_flag_keeps_the_stale_version(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_mail, "_unread_mark", lambda source_type, item: "")      # the planted fault
    d = tsm.Desk(tmp_path, monkeypatch)
    d.providers.mail["gmail"] = flagged(True)
    d.mail("inbox")
    d.providers.mail["gmail"] = flagged(False)
    d.refresh("inbox")
    assert d.count("inbox") == 1 and entry_of(d)["unread"] is True, "what the oracle above would catch: the old flag is kept"

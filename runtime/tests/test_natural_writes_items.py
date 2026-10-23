"""The numbered items of the mail and calendar snapshots (package NR-5a, Q6; runtime/ops_items.py, the row `items`): the read that gives "the e-mail 3" and "event 2" something to
point to on a phone. It reads only what a reference reads and with the same rights (the terminal, the page and a messaging sender with `ask-mail`; never the MCP mode), writes
a message by its sender and subject and an event by its line, refuses a snapshot older than 26 hours, and its reply is private: stored as a neutral word. Real snapshots behind
the real runtime/item_refs.py (test_calendar_write.py's world and the stand-in providers of test_sources_mail.py); no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_items.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import SEEDED, Snapshots, install_item_refs, world  # noqa: F401  (the calendar world and its real snapshots)
from test_ops_natural_writes import PLAIN, READER, SENDER, forget, policy  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_sources = st.load("ops_sources")
ops_items = st.load("ops_items")
operations = st.load("operations")
phrases = st.load("phrases")
natural_writes = st.load("natural_writes")


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    s.providers.mail["gmail"] = [tsm.message(1, sender="Bia Costa <bia@clinic.example>", subject="Appointment confirmed"),
                                 tsm.message(2, sender="Banco Exemplo <avisos@bank.example>", subject="Your statement is ready")]
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    install_item_refs(world, monkeypatch, {"agenda#1": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"}})
    return s


def test_the_row_is_private_never_on_the_mcp_mode_and_in_the_group_read():
    row = operations.by_name("items")
    assert set(row["channels"]) == {"terminal", "page", "messaging"} and row["model"] is False and row.get("channel_arg") is True
    assert "items" in operations.GROUPS["read"]["operations"] and "items" not in operations.GROUPS["read-limited"]["operations"]


def test_the_terminal_lists_each_message_by_its_sender_and_subject_and_each_event_by_its_line(world, snaps, clock):
    out = ops.items(world["path"], channel="terminal")
    kinds = {entry["source"]: entry["type"] for entry in out["sources"]}
    assert kinds == {"inbox": "mail", "agenda": "calendar"} and out["refused"] == []
    mail = next(e for e in out["sources"] if e["source"] == "inbox")
    assert [i["n"] for i in mail["items"]] == [1, 2] and all("·" in i["line"] for i in mail["items"])
    assert any("bia@clinic.example · Appointment confirmed" == i["line"] for i in mail["items"])
    calendar = next(e for e in out["sources"] if e["source"] == "agenda")
    assert calendar["items"][0]["n"] == 1 and "Dentist" in calendar["items"][0]["line"]
    narrowed = ops.items(world["path"], kind="calendar", channel="terminal")
    assert [e["source"] for e in narrowed["sources"]] == ["agenda"]
    assert [e["source"] for e in ops.items(world["path"], source="inbox", channel="terminal")["sources"]] == ["inbox"]


def test_a_snapshot_older_than_the_reference_limit_is_not_listed_and_says_to_refresh_it(world, snaps, clock):
    snaps.later(hours=30)
    out = ops.items(world["path"], kind="mail", channel="terminal")
    assert out["sources"] == [] and "refresh inbox first" in out["refused"][0]["why"]


def test_a_messaging_sender_reads_them_only_with_ask_mail_and_the_mcp_mode_never(world, snaps, clock):
    policy(world)
    with pytest.raises(ops.OpsError) as no:
        ops.items(world["path"], channel="messaging", sender=SENDER)
    assert str(no.value) == phrases.en("NW_REF_NOT_READABLE")
    assert ops.items(world["path"], channel="messaging", sender=READER)["sources"]
    with pytest.raises(ops.OpsError):
        ops.items(world["path"], channel="mcp")
    with pytest.raises(ops.OpsError):
        ops.items(world["path"], channel="messaging", sender=PLAIN)


def test_the_lines_in_words_list_the_mail_or_the_events_and_the_conversation_stores_a_neutral_word(world, snaps, clock):
    policy(world)
    mail = ops.say(world["path"], "lista os e-mails", channel="messaging", sender=READER)["reply"]
    assert "inbox" in mail and "Bia Costa · Appointment confirmed · today 06:00" in mail and "Dentist" not in mail
    events = ops.say(world["path"], "meus eventos", channel="messaging", sender=READER)["reply"]
    assert "Google calendar" in events and "agenda" not in events and "Dentist" in events and "bia@clinic" not in events
    english = ops.say(world["path"], "my emails", channel="messaging", sender=READER)["reply"]
    assert "Appointment confirmed" in english
    ctx = ops_core.context(world["path"])
    stored = [m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500) if m["role"] == "assistant"]
    assert set(stored) == {phrases.en("NAT_READ_REPLY")}, "the reply shows another person's words: the conversation keeps a word"
    refused = ops.say(world["path"], "lista os e-mails", channel="messaging", sender=SENDER)["reply"]
    assert refused == "error: " + phrases.en("NW_REF_NOT_READABLE")


def test_which_items_a_line_means_is_the_noun_it_uses():
    for line, kind in [("meus eventos", "calendar"), ("lista os compromissos", "calendar"), ("lista os e-mails", "mail"), ("my emails", "mail"), ("list my events", "calendar"),
                       ("show my appointments", "calendar")]:
        assert natural_writes.items_kind(line) == kind, line

"""`<source id>#<n>` end to end for the calendar write path (package W1 on SNAP-IDX): a calendar source is registered and refreshed with the runtime's own operations
over the stand-in providers of test_sources_mail.py, and an event is changed or removed by the number the snapshot's text prints, resolved through the real
runtime/item_refs.py. The account is the one the SOURCE ROW's origin names, the calendar id is the origin's, and both must equal what the project's `accounts`
names; a messaging sender needs the group `ask-mail` to use a reference into a snapshot, and needs nothing for `created:<decision>`; a stale, missing or foreign
snapshot is refused with a sentence of the phrase table. The services are stand-ins on loopback; no host of Google or Microsoft is called.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_calendar_refs.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import (GRAPH_SEEDED, SEEDED, approve, create, effect_doc, fgc, fgw, install_item_refs, item_of, item_refs, made_event, ops, ops_core,  # noqa: F401
                                 ops_sources, ops_step_seams, phrases, seed_google, seed_graph, snapshot_event, world)
from test_channel_grants import accept

SENDER = "telegram:4242"


def test_a_change_by_a_reference_into_a_refreshed_calendar_snapshot_is_made_to_the_event_the_snapshot_numbered(world, monkeypatch):
    seed_google(world)
    world["google"].add_event("evother0002", "Lunch", {"dateTime": "2026-10-20T12:00:00-03:00"}, {"dateTime": "2026-10-20T13:00:00-03:00"})
    install_item_refs(world, monkeypatch, {"agenda#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"},
                                           "agenda#2": {"id": "evother0002", "calendar": fgw.CALENDAR, "account": "google"}})
    started = ops.event_change(world["path"], "google", "agenda#2", title="Lunch with Pat")
    doc = effect_doc(world, started)
    assert doc["event_id"] == "evother0002" and doc["reference"] == {"source": "agenda", "n": 2, "read_at": "2026-10-17T10:12:00Z"} and doc["before"]["title"] == "Lunch"
    lines = item_of(world, started)["body"].splitlines()
    assert "The event now: Lunch (Tue 20/10/2026 12:00-13:00 (America/Sao_Paulo))" in lines
    assert "Named as agenda#2, from the snapshot read at 2026-10-17T10:12:00Z." in lines
    world["google"].requests.clear()
    assert approve(world, started)["task_state"] == "done"
    assert world["google"].events["evother0002"]["summary"] == "Lunch with Pat" and world["google"].events[SEEDED]["summary"] == "Dentist"
    removal = ops.event_cancel(world["path"], "google", "agenda#1")
    assert effect_doc(world, removal)["event_id"] == SEEDED and effect_doc(world, removal)["reference"]["n"] == 1


def test_a_renumbered_snapshot_cannot_make_the_person_approve_another_event_because_the_card_names_the_title_and_the_reading_time(world, monkeypatch):
    seed_google(world)
    world["google"].add_event("evother0002", "Lunch", {"dateTime": "2026-10-20T12:00:00-03:00"}, {"dateTime": "2026-10-20T13:00:00-03:00"})
    snaps = install_item_refs(world, monkeypatch, {"agenda#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    snaps.later(hours=2)
    snaps.providers.events[("google", fgw.CALENDAR)] = [snapshot_event(1, "evother0002", "Lunch"), snapshot_event(2, SEEDED, "Dentist")]      # the provider lists them in another order
    snaps.refresh("agenda")
    again = ops.event_cancel(world["path"], "google", "agenda#1")      # the same words, another event: the card says which, and when the snapshot was read
    lines = item_of(world, again)["body"].splitlines()
    assert "The event now: Lunch (Tue 20/10/2026 12:00-13:00 (America/Sao_Paulo))" in lines and "Named as agenda#1, from the snapshot read at 2026-10-17T12:12:00Z." in lines
    assert effect_doc(world, again)["event_id"] == "evother0002"


def test_a_snapshot_older_than_26_hours_and_a_source_that_is_not_a_calendar_are_refused_with_their_sentences(world, monkeypatch):
    seed_google(world)
    snaps = install_item_refs(world, monkeypatch, {"agenda#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    snaps.later(hours=27)
    with pytest.raises(ops.OpsError) as old:
        ops.event_change(world["path"], "google", "agenda#1", title="X")
    assert "more than 26 hours old" in str(old.value) and "refresh agenda first" in str(old.value)
    snaps.refresh("agenda")
    assert ops.event_change(world["path"], "google", "agenda#1", title="X")["pending"]
    snaps.providers.mail["gmail"] = [tsm.message(1, "2026-10-17T09:00:00Z")]
    ops_sources.source_mail(world["path"], "inbox", tsm.GMAIL)
    with pytest.raises(ops.OpsError) as mail:
        ops.event_change(world["path"], "google", "inbox#1", title="X")
    assert "is not a calendar source" in str(mail.value)


def test_a_reference_takes_the_account_from_the_source_rows_origin_never_from_the_index(world, monkeypatch):
    seed_graph(world)
    install_item_refs(world, monkeypatch, {"outl#1": {"id": GRAPH_SEEDED, "calendar": "default", "account": "microsoft"}})
    started = ops.event_change(world["path"], "microsoft", "outl#1", title="Dentist (moved)")
    assert effect_doc(world, started)["account"] == "microsoft" and effect_doc(world, started)["reference"]["source"] == "outl"
    assert approve(world, started)["task_state"] == "done" and world["graph"].events[GRAPH_SEEDED]["subject"] == "Dentist (moved)"
    got = item_refs.resolve(ops_core.context(world["path"]), "outl#1", channel="terminal", clock=lambda: tsm.NOW)
    assert got["implementation"] == "outlook" and got["calendar"] == "default" and "account" not in got["entry"]


def test_a_messaging_sender_reads_a_snapshot_reference_only_with_ask_mail_and_a_created_reference_with_nothing(world, monkeypatch):
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    made = made_event(world)
    accept(world["path"], {"messaging": ["read", "calendar-write"]})
    with pytest.raises(ops.OpsError) as no:
        ops.event_change(world["path"], "google", "agenda#1", title="X", channel="messaging", sender=SENDER)
    assert "this channel may not read it" in str(no.value) and "ask-mail" in str(no.value)
    assert world["google"].requests == [] and not [r for r in world["google"].requests if r["method"] != "GET"]
    started = ops.event_change(world["path"], "google", f"created:{made['pending']}", title="Haircut with Pat", channel="messaging", sender=SENDER)
    assert effect_doc(world, started)["reference"] is None and "The event now: Haircut with Joe" in item_of(world, started)["body"]
    for channel in ("page", None, "terminal"):
        assert ops.event_change(world["path"], "google", "agenda#1", title="X", channel=channel)["pending"] if channel != "page" else True


def test_a_messaging_sender_with_ask_mail_uses_a_snapshot_reference(world, monkeypatch):
    from test_calendar_write import operations
    monkeypatch.setitem(operations.GROUPS, "ask-mail", {"operations": ("ask",), "kind": None})      # NR-2's group, as item_refs.may_read names it, until it is in the table
    monkeypatch.setitem(operations.GROUP_TEXT, "ask-mail", "asks about the person's mail and calendar")
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda#1": {"id": SEEDED, "calendar": fgw.CALENDAR, "account": "google"}})
    accept(world["path"], {"messaging": ["read", "calendar-write", "ask-mail"]})
    started = ops.event_change(world["path"], "google", "agenda#1", title="X", channel="messaging", sender=SENDER)
    assert effect_doc(world, started)["reference"]["source"] == "agenda"


def test_the_calendar_and_the_caller_are_args_a_person_cannot_forge_by_words(world):
    from test_calendar_write import step_calendar_event
    check = step_calendar_event.check
    base = {"account": "google", "operation": "change", "event": "agenda#1", "title": "X"}
    assert check({**base, "channel": "terminal"})["channel"] == "terminal"
    assert check({**base, "channel": "messaging", "sender": SENDER})["sender"] == SENDER
    for bad in ({"channel": "mcp"}, {"channel": "chat"}, {"sender": SENDER}, {"channel": "messaging", "sender": "no colon"}, {"channel": "messaging", "sender": "x:" + "y" * 200}):
        with pytest.raises(Exception):
            check({**base, **bad})
    assert "channel" not in check({"account": "google", "operation": "create", "title": "X", "start": "2026-10-19T13:00", "channel": "terminal"}), "a new event reads no snapshot"

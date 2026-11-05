"""The read `agenda` of catalog version 4 (package P5, SPEC-P5-CATALOG-V4 section 1): the calendar alone. A line the interpreter reads as `agenda` is run by `ops_natural.run` as `items` with the kind
`calendar`, so the policy, the plan, its hash, the "Posso?" sentence and the list are the ones of `items`; the typed `/agenda` is `items --kind calendar`. Here the real snapshots behind the real
runtime/item_refs.py (test_calendar_write.py's world and the stand-in providers of test_sources_mail.py) and the real natural-request path. Each oracle that lists has a vacuity case that fails on a
planted wrong result. The clock is Monday 19/10 at 09:00 in the world's zone, so tomorrow is 20/10 and the events and the message below are dated by it. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_agenda_dispatch.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, world  # noqa: F401  (the calendar world and its real snapshots)
from test_items_fresh import project  # noqa: F401
from test_ops_natural_writes import PLAIN, READER, policy  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_items = st.load("ops_items")
ops_natural = st.load("ops_natural")
ops_sources = st.load("ops_sources")
operations = st.load("operations")
phrases = st.load("phrases")
plan_confirm = st.load("plan_confirm")

TODAY, TOMORROW = "2026-10-19", "2026-10-20"
EN = {"language": "en"}


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    ops_items._CHECKED.clear()
    s.providers.mail["gmail"] = [tsm.message(1, sender="Bia Costa <bia@clinic.example>", subject="Appointment confirmed")]
    return s


def calendar_and_mail(world, snaps):
    """One Google calendar with an event today and two tomorrow, and one mailbox with one message."""
    project(world, "en")
    snaps.calendar("agenda-google", "google", "pat@example.com", [
        tsm.event(1, f"{TODAY}T16:00:00-03:00", f"{TODAY}T17:00:00-03:00", "Standup", id="ev1"),
        tsm.event(2, f"{TOMORROW}T09:00:00-03:00", f"{TOMORROW}T10:00:00-03:00", "Dentist", id="ev2"),
        tsm.event(3, f"{TOMORROW}T14:00:00-03:00", f"{TOMORROW}T15:00:00-03:00", "Budget review", id="ev3")])
    ops_sources.source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")


def run_line(world, name, args, line, sender=READER, extras=None, confirmed=False):
    ctx = ops_core.context(world["path"])
    return ops_natural.run(world["path"], ctx, name, dict(args), line, "messaging", sender, extras if extras is not None else {}, confirmed=confirmed)


def test_the_row_is_a_read_of_the_group_read_with_the_channels_of_items():
    row, items = operations.by_name("agenda"), operations.by_name("items")
    assert (row["channels"], row["model"], row.get("channel_arg")) == (items["channels"], False, True) and "agenda" in operations.GROUPS["read"]["operations"]
    assert "agenda" not in operations.GROUPS["read-limited"]["operations"], "as `items`: a limited reader does not list the person's mail and calendar"
    assert [a["name"] for a in row["args"]] == ["source", "match"]
    assert row["natural"]["class"] == "R" and row["natural"]["since"] == 4 and set(row["natural"]["slots"]) == {"target", "day"}


def test_an_agenda_decision_with_a_day_lists_the_events_of_that_day_and_no_mail(world, snaps, clock):
    calendar_and_mail(world, snaps)
    reply = run_line(world, "agenda", {"day_span": "tomorrow"}, "what do I have tomorrow?", confirmed=True)
    assert "Dentist" in reply and "Budget review" in reply, "the two events of tomorrow"
    assert "Standup" not in reply, "not today's event"
    assert "Appointment confirmed" not in reply and "Bia Costa" not in reply, "the calendar alone: no message of the mail source"


def test_vacuity_an_items_decision_on_the_same_words_lists_the_mail_so_the_oracle_sees_the_calendar(world, snaps, clock):
    calendar_and_mail(world, snaps)
    reply = run_line(world, "items", {"day_span": "tomorrow"}, "what do I have tomorrow?", confirmed=True)
    assert "Dentist" not in reply and "Budget review" not in reply, "`items` is the mail from catalog version 4 when the line names no calendar noun (unchanged)"
    assert reply.startswith("Your e-mails on Tue 20/10"), "the header of a mail list for that day (the literal English snapshot of the header)"
    assert reply != run_line(world, "agenda", {"day_span": "tomorrow"}, "what do I have tomorrow?", confirmed=True)


def test_the_plan_of_an_agenda_decision_is_the_plan_of_a_calendar_list_and_a_yes_lists_the_events(world, snaps, clock):
    calendar_and_mail(world, snaps)
    policy(world)      # no `confirm-reads-off`: a read of the mail and calendar on a phone asks "Posso?" first
    cfg = ops_core.context(world["path"])["cfg"]
    extras = {}
    asked = run_line(world, "agenda", {"day_span": "tomorrow"}, "what do I have tomorrow?", extras=extras)
    assert "plan_confirm" in extras and phrases.text("UNDERSTOOD_ITEMS_CALENDAR", cfg) in asked, "the sentence of a calendar list, written by code from the arguments it checked"
    assert phrases.text("UNDERSTOOD_ITEMS_MAIL", cfg) not in asked
    listed = run_line(world, "agenda", {"day_span": "tomorrow"}, "what do I have tomorrow?", confirmed=True)
    assert "Dentist" in listed
    again = {}
    other = run_line(world, "items", {"day_span": "tomorrow"}, "what do I have tomorrow?", extras=again)
    assert phrases.text("UNDERSTOOD_ITEMS_MAIL", cfg) in other and "plan_confirm" in again, "control: the same words as `items` ask about the mail"


def test_a_correction_that_names_the_emails_lists_mail_and_one_that_names_nothing_keeps_the_calendar(world, snaps, clock):
    calendar_and_mail(world, snaps)
    now = ops_natural._clock()
    calendar = {"kind": "calendar", "first": TOMORROW, "last": TOMORROW}
    assert ops_items.items_args("no, the emails", now, calendar, {"day": "tomorrow"}, default_kind="calendar")["kind"] == "mail", "a line that names e-mails wins over an agenda decision"
    assert ops_items.items_args("no, the one for Friday", now, calendar, {"day": "Friday"}, default_kind="calendar")["kind"] == "calendar"
    assert ops_items.items_args("no, the one for Friday", now, calendar, {"day": "Friday"})["kind"] == "calendar", "the plan the line corrects keeps its kind"
    assert ops_items.items_args("what do I have tomorrow?", now, None, {"day": "tomorrow"}, default_kind="calendar")["kind"] == "calendar"
    corrected = run_line(world, "items", {}, "no, the emails", extras={"plan_previous": calendar}, confirmed=True)
    assert "Dentist" not in corrected and "Budget review" not in corrected, "the correction lists the mail"


def test_the_typed_agenda_is_the_items_of_the_calendar(world, snaps, clock):
    calendar_and_mail(world, snaps)
    typed = ops.agenda(world["path"], channel="terminal")
    assert typed == ops.items(world["path"], kind="calendar", channel="terminal")
    assert [e["type"] for e in typed["sources"]] == ["calendar"] and any("Dentist" in i["line"] for e in typed["sources"] for i in e["items"])
    narrowed = ops.agenda(world["path"], match="dentist", channel="terminal")
    assert narrowed == ops.items(world["path"], kind="calendar", match="dentist", channel="terminal")
    assert [i["line"].split(" · ")[1] for e in narrowed["sources"] for i in e["items"]] == ["Dentist"]
    with pytest.raises(TypeError):
        ops.agenda(world["path"], kind="mail", channel="terminal")      # the kind is not an argument of `agenda`: it is always the calendar

"""AF-3 (EVENT-FRESH): an event named by its words is searched in snapshots that are fresh, and the by-name list numbers its rows by position (runtime/event_lookup.py, runtime/ops_items.py).

The acceptance run of 2026-11-04 (row 38): the search read snapshots up to 26 hours old, so an event added in the calendar's own app was no candidate, one removed through a card still
was, and two sources whose matching rows were both their snapshot's number 1 printed two "1."s, a dead end for the answer. Here the real calendar snapshots (test_calendar_write.py's world,
the stand-in providers of test_sources_mail.py), the real family path and the real card, a stand-in clock (Wednesday 2026-10-21 15:00 at -03:00; a snapshot's age is the stand-in
snapshot clock's). Every expectation is a literal of this file, the events and the sentences included; each oracle reads the card's own lines, the list's rows or the provider's call
log, never the code under test, and the vacuity tests plant a wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup_fresh.py
"""
from __future__ import annotations

import pytest

import phrase_kit as pk
import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import CANCEL, CFG, OWNER, PT, alone, build, calendar_reads, card, carry
from test_event_lookup_number_account import Model, add_outlook, say, says, CARD_1  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_items = st.load("ops_items")
ops_sources = st.load("ops_sources")
event_lookup = st.load("event_lookup")
ops_interpret = st.load("ops_interpret")

# Tomorrow, Thursday 22/10: the old event A (two words, so the line "yoga" fits it by half its words) and, read later, the exact B and B'.
OLD = [("22", "08:00", "09:00", "Yoga avancada", "evold")]
NEW = [("22", "13:00", "14:00", "Yoga", "evb1"), ("22", "18:00", "19:00", "Yoga", "evb2")]
LINE = "Cancela o yoga de amanha"      # validate: allow english-only -- the Portuguese line under test


@pytest.fixture(autouse=True)
def fresh_state():
    event_lookup.forget_lists()
    ops_interpret.forget_all()
    ops_items._CHECKED.clear()          # the module keeps the times of its last reads and the sources marked changed, in memory
    ops_items._DIRTY.clear()
    yield
    event_lookup.forget_lists()
    ops_items._CHECKED.clear()
    ops_items._DIRTY.clear()


def provide_later(world, rows_):
    """Events the calendar holds now and the snapshot does not: the provider answers them at the next read."""
    for day, start, end, title, ident in rows_:
        s, e = f"2026-10-{day}T{start}:00-03:00", f"2026-10-{day}T{end}:00-03:00"
        world["snaps"].providers.events[("google", fgw.CALENDAR)].append(tsm.event(9, s, e, title, id=ident))
        world["google"].add_event(ident, title, {"dateTime": s}, {"dateTime": e})


class Reads:
    """A spy on the one function every read of a source goes through: the sources a line read, in order, and the real read goes on."""

    def __init__(self, monkeypatch):
        self.sources = []
        real = ops_items.ops_sources.source_refresh

        def spy(project, source_id, *rest, **more):
            self.sources.append(source_id)
            return real(project, source_id, *rest, **more)
        monkeypatch.setattr(ops_items.ops_sources, "source_refresh", spy)


# --- a snapshot older than FRESH_S is read again before the search ------------------------------------------------------------------------------------


def test_a_snapshot_eleven_minutes_old_is_read_again_and_the_new_events_are_listed_not_the_old_one_opened(world, monkeypatch):
    build(world, monkeypatch, events=OLD)
    provide_later(world, NEW)
    world["snaps"].later(minutes=11)
    before = len(calendar_reads(world))
    reply, extras = carry(world, LINE, CANCEL)
    lines = reply.splitlines()
    assert len(lines) == 4 and alone(lines[0], "EV_MANY_CANCEL", PT) and alone(lines[3], "EV_MANY_CANCEL_HOW", PT, n=2), reply
    assert lines[1:3] == ["2. Thu 22/10/2026 13:00-14:00 · Yoga", "3. Thu 22/10/2026 18:00-19:00 · Yoga"], reply          # no clash: the snapshot's own numbers (A, at 08:00, is 1)
    assert "resend" not in extras and rows(world) == ([], []), "a list asks before anything opens"
    assert len(calendar_reads(world)) - before == 1, "one read of the one source"


def test_a_snapshot_one_minute_old_but_marked_changed_by_a_calendar_effect_is_read_again(world, monkeypatch):
    build(world, monkeypatch, events=OLD)
    provide_later(world, NEW[:1])
    world["snaps"].later(minutes=1)
    ops_items.mark_changed(ops_core.context(world["path"]), {"effect": "calendar", "account": "google"})
    reply, extras = carry(world, LINE, CANCEL)
    item = card(world, extras)
    assert alone(reply, "ACCT_CARD_SENT", PT, pending=1), reply
    assert pk.said(item["body"], "CARD_CAL_EVENT", CFG, event_id="evb1"), "the exact B beats the half-fit old A that the stale snapshot alone held"
    assert not pk.said(item["body"], "CARD_CAL_EVENT", CFG, event_id="evold")


def test_a_snapshot_one_minute_old_and_not_marked_is_not_read_again(world, monkeypatch):
    build(world, monkeypatch, events=OLD)
    provide_later(world, NEW[:1])
    world["snaps"].later(minutes=1)
    reads, before = Reads(monkeypatch), len(calendar_reads(world))
    reply, extras = carry(world, LINE, CANCEL)
    item = card(world, extras)
    assert alone(reply.splitlines()[-1], "ACCT_CARD_SENT", PT, pending=1) and pk.said(item["body"], "CARD_CAL_EVENT", CFG, event_id="evold"), "the snapshot answers as it is: the cost guard"
    assert reads.sources == [] and len(calendar_reads(world)) == before


def test_a_source_is_read_once_for_a_line_even_when_the_search_then_misses(world, monkeypatch):
    build(world, monkeypatch, events=OLD)
    world["snaps"].later(minutes=11)
    reads = Reads(monkeypatch)
    reply, extras = carry(world, "Cancela a aula de natação", CANCEL)      # validate: allow english-only -- the Portuguese line under test
    assert alone(reply, "EV_NAME_NONE", PT, days=30) and "resend" not in extras, reply
    assert reads.sources == ["agenda"], "the read before the search spent the line's budget; the read of a miss does not make a second one"


def test_a_sender_who_may_not_read_a_snapshot_gets_no_read(world, monkeypatch):
    build(world, monkeypatch, events=OLD)
    world["snaps"].later(minutes=11)
    reads = Reads(monkeypatch)
    reply, _ = carry(world, LINE, CANCEL, sender="telegram:5151")
    assert alone(reply, "NW_REF_NOT_READABLE", PT) and reads.sources == []


def test_a_failed_read_leaves_the_old_snapshot_and_says_nothing_of_it(world, monkeypatch, capfd):
    build(world, monkeypatch, events=OLD)
    world["snaps"].later(minutes=11)
    world["snaps"].providers.fail = tsm.Failure(reason="the provider said ZEBRA-SECRET")
    reply, extras = carry(world, LINE, CANCEL)
    item = card(world, extras)
    assert alone(reply.splitlines()[-1], "ACCT_CARD_SENT", PT, pending=1) and pk.said(item["body"], "CARD_CAL_EVENT", CFG, event_id="evold"), "the old snapshot is the answer, as in the items list"
    assert "ZEBRA" not in reply + " ".join(capfd.readouterr())


def test_vacuity_without_the_read_before_the_search_the_old_event_opens(world, monkeypatch):
    build(world, monkeypatch, events=OLD)
    provide_later(world, NEW)
    world["snaps"].later(minutes=11)
    monkeypatch.setattr(ops_items, "refresh_for_line", lambda project, ctx, source_id: False)
    reply, extras = carry(world, LINE, CANCEL)
    assert alone(reply.splitlines()[-1], "ACCT_CARD_SENT", PT, pending=1) and pk.said(card(world, extras)["body"], "CARD_CAL_EVENT", CFG, event_id="evold"), "the oracle sees the wrong card"


# --- two sources, two snapshots that both number their row 1 ------------------------------------------------------------------------------------------


TWO = [("22", "13:00", "14:00", "corte de cabelo", "evhair22"), ("25", "08:00", "09:00", "Yoga", "evyoga")]


def two_sources(world, monkeypatch):
    build(world, monkeypatch, events=TWO)
    add_outlook(world)
    event_lookup.forget_lists()


def test_two_sources_whose_rows_are_both_number_1_print_1_and_2_and_the_2_opens_the_second_source(world, monkeypatch):
    two_sources(world, monkeypatch)
    model = Model(monkeypatch)
    reply, extras = carry(world, "Cancela o corte de cabelo", CANCEL)
    lines = reply.splitlines()
    assert len(lines) == 4 and alone(lines[3], "EV_POS_CANCEL_HOW", PT, n=1), reply
    assert lines[1].startswith("1. Thu 22/10/2026 13:00-14:00 · corte de cabelo (") and lines[2].startswith("2. Thu 22/10/2026 13:00-14:00 · corte de cabelo ("), reply
    assert lines[1] != lines[2] and "resend" not in extras
    assert says(say(world, "2"), CARD_1) and model.calls == 0
    body = ops.pending(world["path"], 1)["body"]
    assert pk.said(body, "CARD_CAL_SNAPSHOT", CFG, reference="outlook#1", read_at="2026-10-21T17:00:00Z"), body
    assert not pk.said(body, "CARD_CAL_SNAPSHOT", CFG, reference="agenda#1", read_at="2026-10-21T17:00:00Z")


def test_a_list_whose_numbers_are_all_different_keeps_the_snapshot_numbers_and_the_old_how_line(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch)
    reply, extras = carry(world, "Cancela o corte de cabelo", CANCEL)
    lines = reply.splitlines()
    assert alone(lines[3], "EV_MANY_CANCEL_HOW", PT, n=2) and lines[1:3] == ["2. Thu 22/10/2026 13:00-14:00 · corte de cabelo", "4. Fri 23/10/2026 13:00-14:00 · corte de cabelo"], reply
    assert says(say(world, "cancela o 4"), CARD_1) and model.calls == 0
    assert pk.said(ops.pending(world["path"], 1)["body"], "CARD_CAL_SNAPSHOT", CFG, reference="agenda#4", read_at="2026-10-21T17:00:00Z")


def test_cancela_o_2_with_a_verb_does_the_same(world, monkeypatch):
    two_sources(world, monkeypatch)
    model = Model(monkeypatch)
    carry(world, "Cancela o corte de cabelo", CANCEL)
    assert says(say(world, "cancela o 2"), CARD_1) and model.calls == 0
    assert pk.said(ops.pending(world["path"], 1)["body"], "CARD_CAL_SNAPSHOT", CFG, reference="outlook#1", read_at="2026-10-21T17:00:00Z")


def test_cancela_o_1_with_a_verb_opens_the_first_source_bound_to_its_own_snapshot_number(world, monkeypatch):
    two_sources(world, monkeypatch)
    model = Model(monkeypatch)
    carry(world, "Cancela o corte de cabelo", CANCEL)
    assert says(say(world, "cancela o 1"), CARD_1) and model.calls == 0
    assert pk.said(ops.pending(world["path"], 1)["body"], "CARD_CAL_SNAPSHOT", CFG, reference="agenda#1", read_at="2026-10-21T17:00:00Z")


def test_a_number_beyond_the_rows_listed_is_no_form_of_the_list(world, monkeypatch):
    two_sources(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    carry(world, "Cancela o corte de cabelo", CANCEL)
    say(world, "cancela o 3")
    assert model.calls == 1 and rows(world) == ([], []), "3 is not a position of a list of two"


def test_a_pick_by_account_still_opens_that_accounts_row_and_several_names_positions(world, monkeypatch):
    two_sources(world, monkeypatch)
    model = Model(monkeypatch)
    carry(world, "Cancela o corte de cabelo", CANCEL)
    assert say(world, "a das 13h") == st.load("phrases").text("LP_SEVERAL", PT, value=st.load("phrases").text("LP_VALUE_CLOCK", PT, time="13:00"), rows="1 " + st.load("phrases").text("LP_AND", PT) + " 2"), "both rows are at 13:00: the question names positions"
    assert rows(world) == ([], [])
    assert says(say(world, "a do outlook"), CARD_1) and model.calls == 0
    assert pk.said(ops.pending(world["path"], 1)["body"], "CARD_CAL_SNAPSHOT", CFG, reference="outlook#1", read_at="2026-10-21T17:00:00Z")

"""A calendar list that never shows what the person has just changed, and that keeps to the day asked (slice S15c, runtime/ops_items.py).

The live case (2026-10-23, pt-BR, Telegram): "mostra minha agenda de amanha" listed a haircut that had already been moved and then removed through approved cards, because the snapshot read
at 09:51 was younger than FRESH_S and so was not read again; and it listed every day, with a bare heading for the empty Google calendar. Here the real approvals of test_calendar_write.py's
world (a created, a changed and a cancelled event on the stand-in Google and Graph calendars), the stand-in snapshot providers of test_sources_mail.py, which the test keeps equal to what the
writer did, a stand-in clock (Saturday 2026-10-17 07:12 at -03:00), literal sentences, and a vacuity case for each oracle that counts or filters. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_items_changed.py
"""
from __future__ import annotations

import datetime

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, approve, create, fgc, fgw, world  # noqa: F401  (the calendar world and its real approvals)
from test_items_fresh import ask, project  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_items = st.load("ops_items")


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-17 07:12")          # Saturday; the snapshots are read at 10:12 UTC, the same minute


@pytest.fixture
def snaps(world, monkeypatch):  # noqa: F811
    s = Snapshots(world, monkeypatch)
    monkeypatch.setattr(ops_items, "SNAPSHOT_CLOCK", lambda: s.now)
    ops_items._CHECKED.clear()
    ops_items._DIRTY.clear()
    return s


def reads(snaps, implementation=None):
    """The calendar reads the stand-in provider has answered so far (optionally of one implementation)."""
    return [c for c in snaps.providers.calls if c["cls"] != "reader:email" and (implementation is None or c["implementation"] == implementation)]


def timed(n, day, start, end, title, **more):
    return tsm.event(n, f"2026-10-{day}T{start}:00-03:00", f"2026-10-{day}T{end}:00-03:00", title, id=f"ev{n}", etag=f'"etag{n}-{day}-{start}"', **more)          # a change moves the etag, as a provider's does


# --- a write the person approved is on the next list --------------------------------------------------------------------------------------------------


def test_an_event_created_changed_and_cancelled_through_cards_is_on_the_very_next_list_each_time(world, snaps, clock):
    project(world)
    snaps.calendar("agenda", "google", fgw.CALENDAR, [])
    stand_in = snaps.providers.events[("google", fgw.CALENDAR)]
    del snaps.providers.calls[:]
    assert ask(world, "list my events") == "No event in the Google calendar between 17/10 and 31/10 (read at 07:12)." and reads(snaps) == [], "fresh and nothing written: no read"
    made = create(world, title="Haircut", start="2026-10-19T13:00")
    approve(world, made)
    stand_in[:] = [timed(1, "19", "13:00", "14:00", "Haircut")]          # what the provider holds now
    listed = ask(world, "list my events")
    assert len(reads(snaps)) == 1 and "Mon 19/10 13:00–14:00 · Haircut" in listed, "created: one read, and the list holds it"
    assert ask(world, "list my events") == listed and len(reads(snaps)) == 1, "no write in between: the snapshot is fresh and nothing is read"
    moved = ops.event_change(world["path"], "google", f"created:{made['pending']}", start="2026-10-19T14:00")
    approve(world, moved)
    stand_in[:] = [timed(1, "19", "14:00", "15:00", "Haircut")]
    listed = ask(world, "list my events")
    assert len(reads(snaps)) == 2 and "Mon 19/10 14:00–15:00 · Haircut" in listed and "13:00" not in listed, "changed: one more read, the new time"
    removed = ops.event_cancel(world["path"], "google", f"created:{made['pending']}")
    approve(world, removed)
    stand_in[:] = []
    listed = ask(world, "list my events")
    assert len(reads(snaps)) == 3 and "Haircut" not in listed and listed.startswith("No event in the Google calendar"), "cancelled: one more read, gone"


def test_without_the_mark_the_same_list_is_the_old_snapshot_so_the_oracle_can_fail(world, snaps, clock, monkeypatch):
    project(world)
    snaps.calendar("agenda", "google", fgw.CALENDAR, [])
    snaps.providers.events[("google", fgw.CALENDAR)][:] = []
    monkeypatch.setattr(ops_items, "mark_changed", lambda ctx, doc: None)
    del snaps.providers.calls[:]
    approve(world, create(world, title="Haircut", start="2026-10-19T13:00"))
    snaps.providers.events[("google", fgw.CALENDAR)][:] = [timed(1, "19", "13:00", "14:00", "Haircut")]
    listed = ask(world, "list my events")
    assert reads(snaps) == [] and "Haircut" not in listed, "vacuity: with no mark the list is the stale snapshot"


def test_an_outlook_write_marks_only_the_outlook_sources(world, snaps, clock):
    project(world)
    snaps.calendar("agenda-google", "google", fgw.CALENDAR, [])
    snaps.calendar("agenda-outlook", "outlook", "default", [])
    del snaps.providers.calls[:]
    approve(world, create(world, account="microsoft", title="Review", start="2026-10-19T13:00"))
    snaps.providers.events[("outlook", "default")][:] = [timed(1, "19", "13:00", "14:00", "Review")]
    listed = ask(world, "list my events")
    assert [c["implementation"] for c in reads(snaps)] == ["outlook"] and "Review" in listed, "the Google calendar was not touched, so it is not read"


def test_a_mailbox_effect_that_changes_the_listing_marks_the_mail_sources_of_its_account(world, snaps, clock):
    project(world)
    snaps.providers.mail["gmail"] = [tsm.message(1, sender="Bia <bia@clinic.example>", subject="Hello")]
    st.load("ops_sources").source_mail(world["path"], "inbox", "gmail:box=inbox;days=7;max=50")
    ctx = ops_core.context(world["path"])
    del snaps.providers.calls[:]

    def mail_reads():
        return len([c for c in snaps.providers.calls if c["cls"] == "reader:email"])
    ops_items.mark_changed(ctx, {"effect": "mailbox", "account": "google", "action": "draft"})
    ops_items.mark_changed(ctx, {"effect": "mailbox", "account": "microsoft", "action": "archive"})
    ops_items.mark_changed(ctx, {"effect": "send", "account": "google"})
    ask(world, "list my emails")
    assert mail_reads() == 0, "a draft, another account and a send change no listing of this mailbox"
    for action in ("archive", "trash", "move"):
        before = mail_reads()
        ops_items.mark_changed(ctx, {"effect": "mailbox", "account": "google", "action": action})
        ask(world, "list my emails")
        assert mail_reads() == before + 1, action


# --- the day or the week asked for --------------------------------------------------------------------------------------------------------------------


def week(world, snaps, language="pt-BR"):
    """A Google calendar with: today 17/10 Dentist, tomorrow 18/10 Haircut, Tuesday 20/10 Yoga, Friday 23/10 Lunch (the snapshot numbers them 1 to 4)."""
    project(world, language)
    snaps.calendar("agenda", "google", fgw.CALENDAR, [timed(1, "17", "09:00", "10:00", "Dentist"), timed(2, "18", "14:00", "15:00", "Haircut"),
                                                       timed(3, "20", "08:00", "09:00", "Yoga"), timed(4, "23", "12:00", "13:00", "Lunch")])


def titles(reply):
    return [line.split(" · ")[1] for line in reply.splitlines() if line[:1].isdigit()]


def test_tomorrow_keeps_that_day_only_with_the_snapshots_own_number_and_a_header(world, snaps, clock):
    week(world, snaps)
    reply = ask(world, "mostra minha agenda de amanhã")      # validate: allow english-only -- the Portuguese line under test
    assert reply.splitlines() == ["Agenda de amanhã, dom 18/10:", "Agenda do Google (lido às 07:12):",      # validate: allow english-only -- the Portuguese sentence under test
                                  "2. dom 18/10 14:00–15:00 · Haircut · você aceitou"]      # validate: allow english-only -- the Portuguese sentence under test
    assert titles(ask(world, "meus eventos")) == ["Dentist", "Haircut", "Yoga", "Lunch"], "vacuity: with no day in the line every event is listed"


@pytest.mark.parametrize("line, header, shown", [
    ("minha agenda de hoje", "Agenda de hoje, sáb 17/10:", ["Dentist"]),      # validate: allow english-only -- the Portuguese line under test
    ("minha agenda de sexta", "Agenda de sex 23/10:", ["Lunch"]),
    ("minha agenda dia 20", "Agenda de ter 20/10:", ["Yoga"]),
    ("minha agenda desta semana", "Agenda da semana, seg 12/10 a dom 18/10:", ["Dentist", "Haircut"]),
    ("minha agenda da semana que vem", "Agenda da semana, seg 19/10 a dom 25/10:", ["Yoga", "Lunch"]),
])
def test_today_a_weekday_a_date_this_week_and_next_week(world, snaps, clock, line, header, shown):
    week(world, snaps)
    reply = ask(world, line)
    assert reply.splitlines()[0] == header and titles(reply) == shown, line


def test_in_english(world, snaps, clock):
    week(world, snaps, "en")
    reply = ask(world, "show my calendar for tomorrow")
    assert reply.splitlines()[:2] == ["Calendar for tomorrow, Sun 18/10:", "Google calendar (read at 07:12):"] and titles(reply) == ["Haircut"]


def test_a_day_with_nothing_is_the_empty_sentence_for_that_day_and_not_a_bare_heading(world, snaps, clock):
    week(world, snaps)
    assert ask(world, "minha agenda de quarta").splitlines() == ["Agenda de qua 21/10:", "Nenhum evento na Agenda do Google em qua 21/10 (lido às 07:12)."]      # validate: allow english-only -- the Portuguese sentence under test
    snaps.calendar("empty-outlook", "outlook", "default", [])
    out = ask(world, "minha agenda de amanhã").splitlines()      # validate: allow english-only -- the Portuguese line under test
    assert out == ["Agenda de amanhã, dom 18/10:", "Agenda do Google (lido às 07:12):", "2. dom 18/10 14:00–15:00 · Haircut · você aceitou",      # validate: allow english-only -- the Portuguese sentence under test
                   "Nenhum evento na Agenda do Outlook amanhã (lido às 07:12)."]      # validate: allow english-only -- the Portuguese sentence under test


def test_an_empty_source_with_a_day_in_english(world, snaps, clock):
    project(world, "en")
    snaps.calendar("agenda", "google", fgw.CALENDAR, [])
    assert ask(world, "my calendar for tomorrow").splitlines() == ["Calendar for tomorrow, Sun 18/10:", "No event in the Google calendar tomorrow (read at 07:12)."]


NOW = datetime.datetime(2026, 10, 17, 7, 12, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))


@pytest.mark.parametrize("line, first, last", [
    ("agenda de amanhã", "2026-10-18", "2026-10-18"), ("agenda de hoje", "2026-10-17", "2026-10-17"), ("agenda de sexta", "2026-10-23", "2026-10-23"),      # validate: allow english-only -- the Portuguese lines under test
    ("agenda desta semana", "2026-10-12", "2026-10-18"), ("my calendar this week", "2026-10-12", "2026-10-18"), ("my calendar next week", "2026-10-19", "2026-10-25"),
    ("mi agenda de esta semana", "2026-10-12", "2026-10-18"), ("diese Woche", "2026-10-12", "2026-10-18"), ("la semaine prochaine", "2026-10-19", "2026-10-25"),      # validate: allow english-only -- the lines of the languages a line may be written in
    ("la settimana prossima", "2026-10-19", "2026-10-25"),
])
def test_the_range_a_line_names_is_read_with_the_time_engine_and_the_week_words_of_six_languages(line, first, last):
    assert ops_items._range_args(line, NOW) == {"first": first, "last": last}, line


def test_a_line_with_no_day_names_no_range_and_the_oracle_can_fail():
    assert ops_items._range_args("meus eventos", NOW) == {} and ops_items._range_args("my calendar", NOW) == {}
    assert ops_items._range_args("agenda de amanhã", NOW) != ops_items._range_args("agenda de hoje", NOW)      # validate: allow english-only -- the Portuguese line under test

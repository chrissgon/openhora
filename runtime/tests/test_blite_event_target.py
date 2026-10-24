"""An event named by its words, found by code (B''-lite, runtime/event_lookup.py `_by_target`).

The live failure (2026-10-23): "Remova o corte de cabelo de amanha da agenda" was asked again, while "Remova o evento corte de cabelo da agenda" opened the card. The interpreter now
gives the event's name (`target`) and its day (`day`) as spans of the line, and code searches the person's own calendar with them: the closest name over the rows of the snapshot
and the events created here, in the window or on the named day. Held here, with the test's own rows, a stand-in `writes` that records the seeds it is given, and a stand-in clock
(Tuesday 2026-10-27 09:30 in America/Sao_Paulo): one row is one card, several rows are the numbered list, none is one plain sentence, a number written in the line is the numbered
form as before, and a day that code cannot read is a question; the target names no mail, file or address; the calendar is read again at most once. Every sentence is compared with
the phrase table by its key and its values (T8); every name is invented. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_blite_event_target.py
"""
from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

import standin_tree as st

event_lookup = st.load("event_lookup")
event_created = st.load("event_created")
phrases = st.load("phrases")

ZONE = ZoneInfo("America/Sao_Paulo")
NOW = datetime.datetime(2026, 10, 27, 9, 30, tzinfo=ZONE)      # a Tuesday
CFG = {"language": "pt-BR"}
SENDER = "telegram:830461975213"
LINE = "Remova o corte de cabelo de amanhã da agenda"      # validate: allow english-only -- the Portuguese line under test
DAY = "de amanhã"      # validate: allow english-only -- the Portuguese line under test


def row(n, day, title, source="agenda"):
    return {"source": source, "n": n, "day": day, "time": "13:00-14:00", "title": title, "read_at": "2026-10-27T11:00:00Z"}


WED, THU = datetime.date(2026, 10, 28), datetime.date(2026, 10, 29)
HAIR = [row(5, WED, "Corte de cabelo"), row(6, THU, "Corte de cabelo"), row(7, WED, "Yoga")]


class Writes:
    """The stand-in of runtime/ops_natural_writes.py: it records every call and opens nothing."""

    def __init__(self):
        self.calls = []

    def open_line(self, project, ctx, said, channel, sender, extras, *, seed=None, hint=None):
        self.calls.append({"seed": seed, "hint": hint})
        extras["resend"] = 99
        if seed is not None:
            return "OPENED"
        return "NUMBERED" if any(c.isdigit() for c in said) else None          # the family reads a numbered form, and nothing else of a line

    @property
    def seeds(self):
        return [c["seed"] for c in self.calls if c["seed"] is not None]


class Spies:
    """The calendar, as the stand-in the search reads: the rows, how often they were read and read again, the created events, the lists remembered."""

    def __init__(self, monkeypatch, rows, own=None):
        self.rows, self.log, self.lists = rows, [], []
        monkeypatch.setattr(event_lookup, "events", self._events)
        monkeypatch.setattr(event_lookup, "refresh", lambda project, ctx: self.log.append("refresh"))
        monkeypatch.setattr(event_lookup, "_own", lambda ctx, *a, **k: (self.log.append("own"), (own or [], None, 0, False))[1])
        monkeypatch.setattr(event_lookup, "remember_list", lambda ctx, sender, op, found, start: self.lists.append((op, [r["n"] for r in found], start)))

    def _events(self, ctx, sender):
        self.log.append("events")
        return self.rows, None


def said(op, line, spans, time=None, args=None, rows=HAIR, monkeypatch=None, own=None):
    """(reply, extras, writes, spies) of `open_event` for a decision whose spans the check verified."""
    spies, writes, extras = Spies(monkeypatch, rows, own), Writes(), {}
    decision = {"op": op, "spans": spans, "args": args or {}, "time": time}
    reply = event_lookup.open_event("project", {"cfg": CFG}, decision, line, SENDER, extras, writes, NOW)
    return reply, extras, writes, spies


def phrase(key, **fields):
    return phrases.text(key, CFG, **fields)


def test_the_live_line_names_the_event_by_its_words_and_its_day_and_opens_the_one_card(monkeypatch):
    reply, extras, writes, spies = said("event-cancel", LINE, {"target": "corte de cabelo", "day": DAY}, monkeypatch=monkeypatch)
    assert reply == "OPENED" and writes.seeds == [{"op": "event-cancel", "slots": {"event": 5, "source": "agenda"}}], "tomorrow is Wed 28/10: the number of that row, no other"
    assert spies.log == ["events"] and extras["stored"] == phrase("NW_PRIVATE_REPLY") and "lead" not in extras


def test_a_long_line_is_found_by_the_target_alone_and_the_whole_line_would_not(monkeypatch):
    long = "Remova o corte de cabelo de amanhã porque preciso viajar cedo com a Joana Pereira Silva"      # validate: allow english-only -- the Portuguese line under test
    spans = {"target": "corte de cabelo", "day": DAY}
    reply, _, writes, _ = said("event-cancel", long, spans, monkeypatch=monkeypatch)
    assert reply == "OPENED" and writes.seeds == [{"op": "event-cancel", "slots": {"event": 5, "source": "agenda"}}]
    # the same search with the whole line as the words of the event finds nothing: the words that name no event drown the name (the failure this fixes)
    real = event_lookup._by_target

    def whole_line(project, ctx, decision, line, sender, extras, writes, now):          # the planted fault: the line, not the target
        spans = decision["spans"]
        kind, value = event_lookup._day_named(spans["day"], now)
        return event_lookup._found(project, ctx, decision["op"], None, spans, line, sender, extras, writes, now, " ".join(line.split()), kind, value)

    monkeypatch.setattr(event_lookup, "_by_target", whole_line)
    reply, _, writes, _ = said("event-cancel", long, spans, monkeypatch=monkeypatch)
    assert writes.seeds == [] and reply == phrase("EV_NAME_NONE_DAY", days=30), "vacuity: the plant fails the oracle of the long line"
    monkeypatch.setattr(event_lookup, "_by_target", real)
    assert said("event-cancel", long, spans, monkeypatch=monkeypatch)[0] == "OPENED"


def test_with_no_day_the_events_that_fit_are_listed_by_the_numbers_of_the_snapshot_and_remembered(monkeypatch):
    reply, extras, writes, spies = said("event-cancel", "Remova o corte de cabelo da agenda", {"target": "corte de cabelo"}, monkeypatch=monkeypatch)
    assert writes.seeds == [] and spies.lists == [("event-cancel", [5, 6], None)]
    assert reply == "\n".join([phrase("EV_MANY_CANCEL"), "5. Wed 28/10/2026 13:00-14:00 · Corte de cabelo", "6. Thu 29/10/2026 13:00-14:00 · Corte de cabelo",
                               phrase("EV_MANY_CANCEL_HOW", n=5)])
    assert extras["stored"] == phrase("NW_PRIVATE_REPLY")


def test_a_near_name_opens_the_card_and_says_which_event_it_is(monkeypatch):
    reply, extras, writes, _ = said("event-cancel", "Remova o corte cabelo de amanhã da agenda", {"target": "corte cabelo", "day": DAY}, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    lead = phrase("EV_FOUND", title="Corte de cabelo", when="Wed 28/10/2026 13:00-14:00")
    assert writes.seeds == [{"op": "event-cancel", "slots": {"event": 5, "source": "agenda"}}] and extras["lead"] == lead and reply == lead + "\nOPENED"


@pytest.mark.parametrize("target", ["o e-mail da Ana", "a pasta de fotos", "ana@exemplo.example"])
def test_a_target_that_names_another_object_is_no_event_and_opens_nothing(monkeypatch, target):
    reply, extras, writes, spies = said("event-cancel", "Remova " + target + " de amanhã", {"target": target, "day": DAY}, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    assert reply == phrase("IX_CANNOT_WRITE") and writes.calls == [] and spies.log == [] and extras["stored"] == phrase("NW_PRIVATE_REPLY"), target


@pytest.mark.parametrize("day", ["semana que vem talvez", "dia 40", "31/02", "hoje ou amanhã", "de manhã"])      # validate: allow english-only -- the Portuguese line under test
def test_a_day_code_cannot_read_is_asked_and_nothing_is_opened(monkeypatch, day):
    reply, _, writes, spies = said("event-cancel", f"Remova o corte de cabelo {day}", {"target": "corte de cabelo", "day": day}, monkeypatch=monkeypatch)
    assert reply == phrase("EV_ASK_DAY") and writes.calls == [] and spies.log == [], day


def test_a_target_with_no_words_and_a_day_alone_are_asked_again(monkeypatch):
    for spans in ({"day": DAY}, {"target": "  ", "day": DAY}):
        reply, extras, writes, spies = said("event-cancel", "Remova de amanhã", spans, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
        assert reply == phrase("IX_ASK_AGAIN") and writes.calls == [] and spies.log == [] and extras["stored"] == phrase("NW_PRIVATE_REPLY")


def test_no_row_fits_the_calendar_is_read_again_once_then_the_events_created_here_are_searched_then_one_plain_sentence(monkeypatch):
    reply, _, writes, spies = said("event-cancel", "Remova o dentista de amanhã", {"target": "dentista", "day": DAY}, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    assert spies.log == ["events", "refresh", "events", "own"], "one refresh, never two, then the events created here"
    assert reply == phrase("EV_NAME_NONE_DAY", days=30) and writes.calls == []


def test_the_events_created_here_are_found_when_the_snapshot_has_none(monkeypatch):
    own = [dict(row(1, WED, "Dentista"), source=event_created.SOURCE, pending=41, account="google", read_at="41:sig")]
    reply, _, writes, spies = said("event-cancel", "Remova o dentista de amanhã", {"target": "dentista", "day": DAY}, rows=[], own=own, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    assert reply == "OPENED" and writes.seeds == [{"op": "event-cancel", "slots": {"created": 41, "account": "google"}}] and spies.log.count("refresh") == 1


def test_a_number_written_in_the_line_is_the_numbered_form_and_the_target_is_ignored(monkeypatch):
    reply, _, writes, spies = said("event-cancel", "cancela o evento 7", {"target": "Dentista"}, args={"event": 7}, monkeypatch=monkeypatch)
    assert reply == "NUMBERED" and writes.calls == [{"seed": None, "hint": "event-cancel"}], "today's numbered path: the call as before, with the operation as its hint"
    assert spies.log == [], "no search: the number names the event"


def test_a_change_takes_the_new_time_from_the_verified_time_and_the_event_from_the_target(monkeypatch):
    line = "Muda o corte de cabelo de amanhã para as 15h"      # validate: allow english-only -- the Portuguese line under test
    spans = {"target": "corte de cabelo", "day": DAY, "time": "para as 15h"}
    reply, _, writes, _ = said("event-change", line, spans, time={"local": "2026-10-28T15:00", "dated": False}, monkeypatch=monkeypatch)
    assert reply == "OPENED" and writes.seeds == [{"op": "event-change", "slots": {"event": 5, "source": "agenda", "start": "2026-10-28T15:00"}}], "the clock is the event's own day"
    # a title equal to the event's own and no time: there is nothing to change
    again = said("event-change", "Muda o corte de cabelo de amanhã", dict(spans, title="corte de cabelo", time=None), monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    assert again[0] == phrase("EV_CHANGE_WHAT") and again[2].calls == []
    # a new title is the span, and the target is not cut from it
    renamed = said("event-change", "Renomeia o corte de cabelo de amanhã para Barbearia", {"target": "corte de cabelo", "day": DAY, "title": "Barbearia"}, monkeypatch=monkeypatch)      # validate: allow english-only -- the Portuguese line under test
    assert renamed[2].seeds == [{"op": "event-change", "slots": {"event": 5, "source": "agenda", "title": "Barbearia"}}]


def test_a_sender_who_may_not_read_the_calendar_learns_nothing_from_the_target(monkeypatch):
    spies, writes = Spies(monkeypatch, HAIR), Writes()
    monkeypatch.setattr(event_lookup, "events", lambda ctx, sender: ([], "not-readable"))
    decision = {"op": "event-cancel", "spans": {"target": "corte de cabelo", "day": DAY}, "args": {}, "time": None}
    reply = event_lookup.open_event("project", {"cfg": CFG}, decision, LINE, SENDER, {}, writes, NOW)
    assert reply == phrase("NW_REF_NOT_READABLE") and writes.calls == [] and spies.log == []


def test_the_whole_line_path_is_as_before_when_the_decision_has_no_target_and_no_day(monkeypatch):
    reply, _, writes, _ = said("event-cancel", LINE, {}, monkeypatch=monkeypatch)
    assert reply == "OPENED" and writes.seeds == [{"op": "event-cancel", "slots": {"event": 5, "source": "agenda"}}]

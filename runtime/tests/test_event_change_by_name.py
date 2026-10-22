"""Change or cancel an event by the closest name, never by its number (slice S16b, runtime/event_lookup.py, runtime/natural_writes_calendar.py, runtime/ops_natural_writes.py,
runtime/ops_interpret.py).

The live case (2026-10-22, a pt-BR project): right after the platform created "corte de cabelo" on Friday 23/10 at 14:00 on the Outlook calendar, the person sent "mude o corte de
cabelo para as 10h" and was answered with the hint for the typed numbered form ("Para mudar um evento, diga o número dele ..."). The hint came from the tier-1 grammar of the calendar
family (runtime/natural_writes_calendar.py `_change`: a change verb, no event noun and a time that NR-1 reads as a reminder), before any model and before the lookup by name.
The maintainer's rule: the person knows the name, not the number; find the event with the closest name and ask whether it is the one. Here the real family path, the real cards and the real
ledger of approved cards (test_calendar_write.py's world, the stand-in services), a stand-in clock (Wednesday 2026-10-21 15:00 at -03:00) and a model that is stood in (and counted).
Every expectation is a literal of this file; each oracle reads the card's own lines, the provider's recorded requests or the sentence, never the code under test, and each test has a vacuity
case that plants a wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_change_by_name.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_calendar_write import approve, create, rows, world  # noqa: F401  (the calendar world and its stand-in providers)
from test_event_lookup import OWNER, build as build_with_source, op_text
from test_event_lookup_own_events import CARD_2, NO_SOURCE, Model, build, cards, fresh, made, pending, say, writes  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401

event_lookup = st.load("event_lookup")
ops = st.load("ops")
ops_core = st.load("ops_core")

TITLE = "corte de cabelo"
HINT = "Para mudar um evento, diga o número dele e o novo horário, por exemplo: remarca o evento 2 para sexta às 15h. Peça a sua agenda para ver os números."      # validate: allow english-only -- the Portuguese line or sentence under test
FOUND = "Encontrei: corte de cabelo, Fri 23/10/2026 14:00-15:00. É este?"      # validate: allow english-only -- the Portuguese line or sentence under test
NONE = "Não encontrei nenhum evento com nome parecido nos próximos 30 dias. Peça a sua agenda para ver os eventos."      # validate: allow english-only -- the Portuguese line or sentence under test
LIVE = "mude o corte de cabelo para as 10h"
OUTLOOK_ID = "Event: AAMkEvent0001="
BEFORE = "Before: When: Fri 23/10/2026 14:00-15:00 (America/Sao_Paulo)"
AFTER = "After: When: Fri 23/10/2026 10:00-11:00 (America/Sao_Paulo)"


def the_event(world, monkeypatch, account="microsoft", **more):
    """The project of the live case: no calendar source, and an event the platform created on the Outlook calendar for Friday 23/10 at 14:00 (the card approved)."""
    build(world, monkeypatch)
    n = made(world, start="2026-10-23T14:00", account=account, **more)
    world["graph"].requests.clear()
    world["google"].requests.clear()
    return n


def card_lines(world, n=2):
    return pending(world, n)["body"].splitlines()


def problems(lines, wanted):
    return [w for w in wanted if w not in lines]


def test_the_live_line_opens_the_change_card_of_that_event_at_ten_on_its_own_day_and_asks_no_model(world, monkeypatch):
    the_event(world, monkeypatch)
    model = Model(monkeypatch)
    reply = say(world, LIVE)
    assert reply == CARD_2 and reply != HINT and model.calls == 0, reply
    lines = card_lines(world)
    assert problems(lines, [OUTLOOK_ID, BEFORE, AFTER, "Unchanged: Title: corte de cabelo"]) == [], lines
    assert pending(world, 2)["status"] == "open" and cards(world) == [1, 2], "the card waits for its approval"
    assert writes(world) == [], "nothing was written to a calendar"
    wrong = problems(lines, ["After: When: Thu 22/10/2026 10:00-11:00 (America/Sao_Paulo)"])
    assert wrong != [], "vacuity: the next 10h (Thursday) is not the event's day"


@pytest.mark.parametrize("line", ["mude o corte de cabelos para as 10h", "mude o corte cabelo para as 10h", "Muda o CORTE de cabelo pra as 10h"])      # validate: allow english-only -- the Portuguese line or sentence under test
def test_a_typo_or_a_missing_word_still_finds_the_event_and_shows_which_one_it_found(world, monkeypatch, line):
    the_event(world, monkeypatch)
    reply = say(world, line)
    exact = line == "Muda o CORTE de cabelo pra as 10h"          # every word of the title is in the line as typed; the others are near or lack a word      # validate: allow english-only -- the Portuguese line or sentence under test
    assert reply == (CARD_2 if exact else FOUND + "\n" + CARD_2), reply
    assert problems(card_lines(world), [OUTLOOK_ID, AFTER]) == []


def test_the_ranking_rule_on_the_names(world):
    """Vacuity of the test above: the whole-word rule of S6 would have found nothing for the typo; the ranked rule finds it and says it is not exact."""
    import datetime
    row = {"source": "agenda", "n": 1, "day": datetime.date(2026, 10, 23), "time": "14:00-15:00", "title": TITLE}
    today = datetime.date(2026, 10, 21)
    got = event_lookup.ranked([row], "mude o corte de cabelos para as 10h", "none", None, today)
    assert [(r["title"], r["exact"]) for r in got] == [(TITLE, False)]
    got = event_lookup.ranked([row], "mude o corte de cabelo para as 10h", "none", None, today)
    assert [(r["title"], r["exact"]) for r in got] == [(TITLE, True)]
    assert event_lookup.ranked([row], "mude o dentista para as 10h", "none", None, today) == []
    assert event_lookup.ranked([row], "mude o corte de cabelo para as 10h", "none", None, datetime.date(2026, 12, 1)) == [], "the window is thirty days"


def test_two_close_names_are_listed_and_a_number_picks_with_the_clock_of_the_line_on_that_events_day(world, monkeypatch):
    build(world, monkeypatch)
    made(world, start="2026-10-23T14:00")
    made(world, title="corte de barba", start="2026-10-24T09:00")
    model = Model(monkeypatch)
    reply = say(world, "mude o corte para as 10h")
    assert reply == ("Mais de um evento combina. Qual deles você quer mudar?\n"      # validate: allow english-only -- the Portuguese line or sentence under test
                     "1. Fri 23/10/2026 14:00-15:00 · corte de cabelo\n2. Sat 24/10/2026 09:00-10:00 · corte de barba\n"
                     "Diga o número e o novo horário, por exemplo: remarca o evento 1 para sexta às 15h."), reply      # validate: allow english-only -- the Portuguese line or sentence under test
    assert cards(world) == [1, 2] and model.calls == 0
    assert say(world, "o 2") == "O card #3 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
    lines = card_lines(world, 3)
    assert problems(lines, ["Before: When: Sat 24/10/2026 09:00-10:00 (America/Sao_Paulo)", "After: When: Sat 24/10/2026 10:00-11:00 (America/Sao_Paulo)"]) == [], lines
    assert "After: When: Fri 23/10/2026 10:00-11:00 (America/Sao_Paulo)" not in lines, "vacuity: the first event's day is not the second's"


def test_an_unrelated_name_says_that_no_event_with_a_similar_name_was_found_and_offers_the_agenda(world, monkeypatch):
    build_with_source(world, monkeypatch)
    model = Model(monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"))          # a line the code does not claim goes to the model
    reply = say(world, "mude o passeio com o cachorro para as 10h")
    assert reply == NONE and model.calls == 1 and rows(world) == ([], []), reply
    assert "/" not in reply and "--" not in reply, "no command on a phone"
    assert say(world, "mude o corte de cabelo para as 10h").startswith("Mais de um evento combina. Qual deles você quer mudar?"), "control: a name the calendar has is found there (two haircuts: listed)"      # validate: allow english-only -- the Portuguese line or sentence under test


def test_with_no_calendar_at_all_an_unrelated_name_says_what_is_searched(world, monkeypatch):
    the_event(world, monkeypatch)
    assert say(world, "mude o dentista para as 10h") == NO_SOURCE
    assert cards(world) == [1]


@pytest.mark.parametrize("line", ["remarca o evento 0 para as 10h", "remarca o evento para as 10h", "mude o evento dois para as 10h"])
def test_a_typed_number_form_with_a_bad_number_still_gets_the_hint(world, monkeypatch, line):
    the_event(world, monkeypatch)
    model = Model(monkeypatch)
    assert say(world, line) == HINT and model.calls == 0 and cards(world) == [1], line


def test_cancel_by_name_works_the_same_through_the_model_and_without_it(world, monkeypatch):
    the_event(world, monkeypatch, account="google")
    model = Model(monkeypatch, op_text("event-cancel"), "Sure! not json", op_text("event-cancel", {"title": TITLE}))
    reply = say(world, "cancela o corte de cabelos")
    assert reply == FOUND + "\n" + CARD_2 and model.calls == 1, reply
    assert problems(card_lines(world), ["Event: ev0001", "Removing, title: corte de cabelo", "When: Fri 23/10/2026 14:00-15:00 (America/Sao_Paulo)"]) == []
    reply = say(world, "cancele o corte de cabelo")          # the model's text is no JSON: the line's own verb and the name decide
    assert reply == "O card #3 espera a sua aprovação." and model.calls == 2, reply      # validate: allow english-only -- the Portuguese line or sentence under test
    reply = say(world, "cancela o corte de cabelo")          # a slot the removal does not have
    assert reply == "O card #4 espera a sua aprovação." and model.calls == 3      # validate: allow english-only -- the Portuguese line or sentence under test
    assert pending(world, 4)["status"] == "open" and writes(world) == []


def test_nothing_is_approved_or_written_by_any_of_these_paths(world, monkeypatch):
    the_event(world, monkeypatch)
    Model(monkeypatch, op_text("event-cancel"))
    for line in (LIVE, "mude o corte de cabelos para as 10h", "cancela o corte de cabelo", "mude o dentista para as 10h"):
        say(world, line)
    assert writes(world) == []
    assert [pending(world, n)["status"] for n in cards(world)[1:]] == ["open"] * (len(cards(world)) - 1)
    stored = json.dumps([pending(world, n) for n in cards(world)], ensure_ascii=False)
    assert "mude o" not in stored.lower() and "cancela o" not in stored.lower(), "no word of the lines is stored"

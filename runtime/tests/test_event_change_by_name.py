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

import phrase_kit as pk
import standin_tree as st
from test_calendar_write import approve, create, rows, world  # noqa: F401  (the calendar world and its stand-in providers)
from test_event_lookup import CFG, OWNER, PT, alone, says
from test_event_lookup import build as build_with_source, op_text
from test_event_lookup_own_events import ASK_AGAIN, CARD_2, NO_SOURCE, Model, build, cards, fresh, made, pending, say, writes  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401
from closed_heads import closed_heads, tier1_forms, words_interpreted  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms", "words_interpreted")      # S41-11: every closed form claims a line in this file, as it did

event_lookup = st.load("event_lookup")
ops = st.load("ops")
ops_core = st.load("ops_core")

TITLE = "corte de cabelo"
# The sentences a reply says, as a phrase key and the values of its fields (`says(reply, SENTENCE)` is the whole reply and nothing else).
HINT = ("NW_CHANGE_BY_NUMBER", {})
FOUND = ("EV_FOUND", {"title": "corte de cabelo", "when": "Fri 23/10/2026 14:00-15:00"})
NONE = ("EV_NAME_NONE", {"days": 30})
LIVE = "mude o corte de cabelo para as 10h"
OUTLOOK_ID = ("CARD_CAL_EVENT", {"event_id": "AAMkEvent0001="})      # the lines of a card the oracle looks for: a phrase key and its fields
BEFORE = ("CARD_CAL_BEFORE_WHEN", {"when": "Fri 23/10/2026 14:00-15:00 (America/Sao_Paulo)"})
AFTER = ("CARD_CAL_AFTER_WHEN", {"when": "Fri 23/10/2026 10:00-11:00 (America/Sao_Paulo)"})


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
    """The `(key, fields)` pairs of `wanted` that no line of the card says."""
    body = "\n".join(lines)
    return [w for w in wanted if not pk.said(body, w[0], CFG, **w[1])]


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


def test_with_no_calendar_at_all_an_unrelated_name_says_what_is_searched(world, monkeypatch):
    the_event(world, monkeypatch)
    assert says(say(world, "mude o dentista para as 10h"), NO_SOURCE)
    assert cards(world) == [1]


def test_cancel_by_name_works_the_same_through_the_model_and_without_it(world, monkeypatch):
    the_event(world, monkeypatch, account="google")
    model = Model(monkeypatch, op_text("event-cancel"), "Sure! not json", op_text("event-cancel", {"title": TITLE}))
    reply = say(world, "cancela o corte de cabelos")
    assert len(reply.splitlines()) == 2 and says(reply.splitlines()[0], FOUND) and says(reply.splitlines()[1], CARD_2) and model.calls == 1, reply
    assert problems(card_lines(world), [("CARD_CAL_EVENT", {"event_id": "ev0001"}), ("CARD_CAL_DROP_TITLE", {"title": "corte de cabelo"}), ("CARD_CAL_WHEN", {"when": "Fri 23/10/2026 14:00-15:00 (America/Sao_Paulo)"})]) == []
    reply = say(world, "cancele o corte de cabelo")          # the model's text is no JSON: the line's own verb and the name decide
    assert alone(reply, "ACCT_CARD_SENT", PT, pending=3) and model.calls == 2, reply
    reply = say(world, "cancela o corte de cabelo")          # a slot the removal does not have
    assert alone(reply, "ACCT_CARD_SENT", PT, pending=4) and model.calls == 3
    assert pending(world, 4)["status"] == "open" and writes(world) == []


# --- the review round: the object of the line, two verbs, the clock on the event's day, all-day events -----------------------------------------------------------

CANNOT = ("IX_CANNOT_WRITE", {})
PAST = ("IX_ASK_PAST", {})
ALL_DAY = ("EV_ALLDAY_CLOCK", {})
GARBAGE = "Sure! not json"
CLARIFY = '{"v":1,"kind":"clarify","slot":"%s"}'


@pytest.mark.parametrize("line, answer", [
    ("cancela a rotina do relatorio", CLARIFY % "id"),
    ("apaga o email da Ana", CLARIFY % "messages"),
    ("apaga o email da Ana", GARBAGE),
    ("move o email da Ana para a pasta Clientes", CLARIFY % "folder"),
    ("cancela o lembrete de pagar a conta", CLARIFY % "id"),
    ("remove o arquivo relatorio", CLARIFY % "file"),
    ("delete the email from Ana", GARBAGE),
    ("cancela o relatorio mensal da ana@example.com", GARBAGE),
])
def test_a_line_that_names_another_object_never_becomes_an_event_card_through_the_verb(world, monkeypatch, line, answer):
    build(world, monkeypatch)
    made(world, title="relatorio mensal", start="2026-10-23T14:00")
    made(world, title="Ana", start="2026-10-23T16:00")
    world["google"].requests.clear()
    Model(monkeypatch, answer)
    reply = say(world, line)
    assert not pk.said(reply, "ACCT_CARD_SENT", PT) and not pk.said(reply, "EV_FOUND", PT), (line, reply)
    assert cards(world) == [1, 2] and writes(world) == [], "no event card was opened"


@pytest.mark.parametrize("line, answer", [("cancela o relatorio mensal", GARBAGE), ("cancela o relatorio mensal", CLARIFY % "event"), ("Cancela o relatorio mensal", op_text("event-cancel", {"event": "relatorio"}))])
def test_the_same_garbage_for_a_line_with_no_other_object_does_open_the_card(world, monkeypatch, line, answer):
    """Vacuity of the test above: only the object of the line differs."""
    build(world, monkeypatch)
    made(world, title="relatorio mensal", start="2026-10-23T14:00")
    Model(monkeypatch, answer)
    assert says(say(world, line), CARD_2), line


def test_a_reminder_line_never_opens_an_event_card_with_or_without_the_model(world, monkeypatch):
    the_event(world, monkeypatch)
    model = Model(monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"), op_text("event-change"))
    assert says(say(world, "mude o lembrete de pagar a conta para as 10h"), CANNOT) and cards(world) == [1], "whoever read the line: code or model"
    assert says(say(world, "mude o lembrete de pagar a conta"), CANNOT) and cards(world) == [1], "the model's valid event operation does not make it an event"
    assert model.calls <= 2


@pytest.mark.parametrize("line, answer", [
    ("cancela o corte e marca de novo para as 10h", op_text("event-change", {"event": TITLE})),
    ("muda o corte, ou melhor cancela", op_text("event-cancel", {"event": TITLE})),
    ("muda o corte, ou melhor cancela", op_text("event-cancel")),
    ("cancela o corte de cabelo e cancela o outro", op_text("event-cancel")),
])
def test_a_line_with_the_other_kind_or_two_change_verbs_asks_again(world, monkeypatch, line, answer):
    the_event(world, monkeypatch, account="google")
    Model(monkeypatch, answer)
    assert says(say(world, line), ASK_AGAIN) and cards(world) == [1], line


@pytest.mark.parametrize("line", ["cancela o corte de cabelo?", "cancela o corte de cabelo se chover", "cancela o corte de cabelo, caso chova", "muda o corte de cabelo para as 10h?",
                                  "muda o corte de cabelo para as 10h se der"])
def test_a_question_or_a_trailing_condition_asks_again(world, monkeypatch, line):
    the_event(world, monkeypatch, account="google")
    Model(monkeypatch, op_text("event-cancel"), op_text("event-cancel"))
    assert says(say(world, line), ASK_AGAIN) and cards(world) == [1], line
    Model(monkeypatch, op_text("event-cancel"))
    assert alone(say(world, "cancela o corte de cabelo"), "ACCT_CARD_SENT", PT, pending=2), "vacuity: the same line without the question or the condition opens"


def test_the_model_path_does_not_replace_a_time_the_check_accepted_with_a_past_one(world, monkeypatch):
    build(world, monkeypatch)
    made(world, start="2026-10-21T16:00", account="microsoft")
    ctx = ops_core.context(world["path"])
    writes_module = st.load("ops_natural_writes")
    now = st.load("ops_natural")._clock()
    # the model read "as 10h" as tomorrow's 10:00, which the check accepts; on the event's own day (today, 16:00) it is in the past
    decision = {"op": "event-change", "time": {"local": "2026-10-22T10:00", "source": "model"}, "spans": {"time": "as 10h"}, "args": {}}
    assert says(event_lookup.open_event(world["path"], ctx, decision, "mude o corte de cabelo as 10h", OWNER, {}, writes_module, now), PAST) and cards(world) == [1]
    decision["time"]["local"], decision["spans"]["time"] = "2026-10-22T18:00", "as 18h"
    assert says(event_lookup.open_event(world["path"], ctx, decision, "mude o corte de cabelo as 18h", OWNER, {}, writes_module, now), CARD_2), "vacuity: a clock still ahead opens"


def test_exact_means_the_title_is_the_line_title_span_and_an_exact_name_wins_a_tie():
    import datetime
    today = datetime.date(2026, 10, 21)

    def row(title, n=1):
        return {"source": "agenda", "n": n, "day": datetime.date(2026, 10, 23), "time": "14:00-15:00", "title": title}
    got = event_lookup.ranked([row("Ana")], "cancela o almoço com a Ana", "none", None, today)      # validate: allow english-only -- the Portuguese line or sentence under test
    assert [(r["title"], r["exact"]) for r in got] == [("Ana", False)], "the title is only part of what the line says"
    got = event_lookup.ranked([row("Ana")], "cancela a Ana", "none", None, today)
    assert [(r["title"], r["exact"]) for r in got] == [("Ana", True)]
    got = event_lookup.ranked([row("corte", 1), row("cortes", 2)], "cancela o corte", "none", None, today)
    assert [(r["title"], r["exact"]) for r in got] == [("corte", True)], "the exact name wins alone over the near one"
    got = event_lookup.ranked([row("corte", 1), row("cortes", 2)], "cancela os cortess", "none", None, today)
    assert sorted(r["title"] for r in got) == ["corte", "cortes"], "vacuity: with no exact name the near ones are listed together"

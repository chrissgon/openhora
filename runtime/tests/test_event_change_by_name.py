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
from test_event_lookup_own_events import ASK_AGAIN, CARD_2, NO_SOURCE, Model, build, cards, fresh, made, pending, say, writes  # noqa: F401
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


# --- the review round: the object of the line, two verbs, the clock on the event's day, all-day events -----------------------------------------------------------

CANNOT = "Entendi que você quer mudar algo nas suas contas, mas não consegui montar o cartão, então não fiz nada. Diga o que é, qual item e quando."      # validate: allow english-only -- the Portuguese line or sentence under test
PAST = "Esse horário já passou. Diga um horário que ainda vem pela frente."      # validate: allow english-only -- the Portuguese line or sentence under test
ALL_DAY = "Esse evento é de dia inteiro, então não o mudei: um horário não diz quanto tempo ele dura. Diga a hora de início e a de fim, por exemplo: das 10h às 11h."      # validate: allow english-only -- the Portuguese line or sentence under test
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
    assert not reply.startswith("O card") and not reply.startswith("Encontrei"), (line, reply)      # validate: allow english-only -- the Portuguese line or sentence under test
    assert cards(world) == [1, 2] and writes(world) == [], "no event card was opened"


@pytest.mark.parametrize("line, answer", [("cancela o relatorio mensal", GARBAGE), ("cancela o relatorio mensal", CLARIFY % "event"), ("Cancela o relatorio mensal", op_text("event-cancel", {"event": "relatorio"}))])
def test_the_same_garbage_for_a_line_with_no_other_object_does_open_the_card(world, monkeypatch, line, answer):
    """Vacuity of the test above: only the object of the line differs."""
    build(world, monkeypatch)
    made(world, title="relatorio mensal", start="2026-10-23T14:00")
    Model(monkeypatch, answer)
    assert say(world, line) == CARD_2, line


def test_a_reminder_line_never_opens_an_event_card_with_or_without_the_model(world, monkeypatch):
    the_event(world, monkeypatch)
    model = Model(monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"), op_text("event-change"))
    assert say(world, "mude o lembrete de pagar a conta para as 10h") == CANNOT and cards(world) == [1], "whoever read the line: code or model"
    assert say(world, "mude o lembrete de pagar a conta") == CANNOT and cards(world) == [1], "the model's valid event operation does not make it an event"
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
    assert say(world, line) == ASK_AGAIN and cards(world) == [1], line


@pytest.mark.parametrize("line", ["cancela o corte de cabelo?", "cancela o corte de cabelo se chover", "cancela o corte de cabelo, caso chova", "muda o corte de cabelo para as 10h?",
                                  "muda o corte de cabelo para as 10h se der"])
def test_a_question_or_a_trailing_condition_asks_again(world, monkeypatch, line):
    the_event(world, monkeypatch, account="google")
    Model(monkeypatch, op_text("event-cancel"), op_text("event-cancel"))
    assert say(world, line) == ASK_AGAIN and cards(world) == [1], line
    Model(monkeypatch, op_text("event-cancel"))
    assert say(world, "cancela o corte de cabelo") == "O card #2 espera a sua aprovação.", "vacuity: the same line without the question or the condition opens"      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_clock_that_has_passed_on_the_events_own_day_is_asked_never_opened(world, monkeypatch):
    build(world, monkeypatch)
    made(world, start="2026-10-21T16:00", account="microsoft")          # today, an hour after the clock of the test (15:00)
    Model(monkeypatch)
    assert say(world, "mude o corte de cabelo para as 10h") == PAST and cards(world) == [1]
    assert say(world, "mude o corte de cabelo para as 18h") == CARD_2, "vacuity: a clock still ahead on the same day opens"      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "After: When: Wed 21/10/2026 18:00-19:00 (America/Sao_Paulo)" in card_lines(world)


def test_the_model_path_does_not_replace_a_time_the_check_accepted_with_a_past_one(world, monkeypatch):
    build(world, monkeypatch)
    made(world, start="2026-10-21T16:00", account="microsoft")
    ctx = ops_core.context(world["path"])
    writes_module = st.load("ops_natural_writes")
    now = st.load("ops_natural")._clock()
    # the model read "as 10h" as tomorrow's 10:00, which the check accepts; on the event's own day (today, 16:00) it is in the past
    decision = {"op": "event-change", "time": {"local": "2026-10-22T10:00", "source": "model"}, "spans": {"time": "as 10h"}, "args": {}}
    assert event_lookup.open_event(world["path"], ctx, decision, "mude o corte de cabelo as 10h", OWNER, {}, writes_module, now) == PAST and cards(world) == [1]
    decision["time"]["local"], decision["spans"]["time"] = "2026-10-22T18:00", "as 18h"
    assert event_lookup.open_event(world["path"], ctx, decision, "mude o corte de cabelo as 18h", OWNER, {}, writes_module, now) == CARD_2, "vacuity: a clock still ahead opens"


def test_after_a_list_the_clock_on_the_picked_entrys_day_is_checked_too(world, monkeypatch):
    build(world, monkeypatch)
    made(world, start="2026-10-21T16:00")
    made(world, start="2026-10-23T14:00")
    Model(monkeypatch)
    assert say(world, "mude o corte de cabelo para as 10h").startswith("Mais de um evento combina.")      # validate: allow english-only -- the Portuguese line or sentence under test
    assert say(world, "o 1") == PAST and cards(world) == [1, 2]
    assert say(world, "mude o corte de cabelo para as 10h").startswith("Mais de um evento combina.")      # validate: allow english-only -- the Portuguese line or sentence under test
    assert say(world, "o 2") == "O card #3 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test


def test_a_clock_change_of_an_all_day_event_is_refused_in_a_sentence_and_a_cancel_is_not(world, monkeypatch):
    build(world, monkeypatch)
    made(world, start="2026-10-23", account="google")
    Model(monkeypatch, op_text("event-cancel"))
    assert say(world, "mude o corte de cabelo para as 10h") == ALL_DAY and cards(world) == [1]
    assert say(world, "cancela o corte de cabelo") == CARD_2, "vacuity: the all-day event is found, only the clock is refused"


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

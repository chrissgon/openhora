"""A number after a list of events, and the account a line names (slice S11, runtime/event_lookup.py with the seams in runtime/ops_interpret.py, ops_natural.py and
ops_natural_writes.py).

The live cases (2026-10-21): after the list "2. ... corte de cabelo / 4. ... corte de cabelo" the answer "cancela o 2" went to the model and got nothing; and "Agende corte de cabelo
amanha as 14h no outlook" with two calendar accounts was asked "Em qual conta?" although the line had said which. Here the real calendar snapshots (test_calendar_write.py's world, the
stand-in providers of test_sources_mail.py), the real family path and the real card, a stand-in clock (Wednesday 2026-10-21 15:00 at -03:00) and a model that is never asked (or counted
when it is). Every expectation is a literal of this file, the events and the sentences included; each oracle reads the card's own lines or the sentence, never the code under test, and
the vacuity tests plant a wrong result. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup_number_account.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
import test_sources_mail as tsm
from test_calendar_write import Snapshots, fgc, fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import CANCEL, OWNER, TALKER, build, card, card_problems, carry, op_text, reads_only  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
ops_interpret = st.load("ops_interpret")
event_lookup = st.load("event_lookup")
interpreter_route = st.load("interpreter_route")

CARD_SENT = "O card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
AGAIN = "Essa lista ficou desatualizada, ou o número não está mais claro. Diga o evento pelo nome e pelo dia."      # validate: allow english-only -- the Portuguese line or sentence under test
WHAT = "O que você quer fazer com o evento 2? Diga, por exemplo: cancela o evento 2, ou remarca o evento 2 para sexta às 15h."      # validate: allow english-only -- the Portuguese line or sentence under test
NO_MICROSOFT = "Não há agenda configurada para Microsoft aqui, então não fiz nada. Diga outra conta, ou deixe a conta de fora."      # validate: allow english-only -- the Portuguese line or sentence under test
HAIR_2 = ("agenda#2", "corte de cabelo", "Thu 22/10/2026 13:00-14:00")
HAIR_4 = ("agenda#4", "corte de cabelo", "Fri 23/10/2026 13:00-14:00")


@pytest.fixture(autouse=True)
def fresh_lists():
    event_lookup.forget_lists()
    ops_interpret.forget_all()
    yield
    event_lookup.forget_lists()


class Model:
    """The daily route, stood in: it answers the queued texts and counts the calls, so that a test can say the model was (not) asked."""

    def __init__(self, monkeypatch, *texts):
        self.texts, self.calls = list(texts), 0
        monkeypatch.setattr(interpreter_route, "complete", self.complete)

    def complete(self, route_id, system, user, **kw):
        self.calls += 1
        return {"ok": True, "text": self.texts.pop(0), "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}


def say(world, line, sender=OWNER):
    return ops.say(world["path"], line, channel="messaging", sender=sender)["reply"]


def numbered_card_body(world, line):
    """The body of the card the numbered form `line` opens (the form the person is told to say)."""
    got = ops.natural_write(world["path"], line, channel="messaging", sender=OWNER)
    return ops.pending(world["path"], got["resend"])["body"]


def listed(world, line="Cancela o corte de cabelo", text=CANCEL):
    """The S6 list of the two haircuts (2 and 4), carried out through the real seam."""
    reply, extras = carry(world, line, text)
    assert reply.startswith("Mais de um evento combina.") and "resend" not in extras      # validate: allow english-only -- the Portuguese line or sentence under test
    return reply


# --- item 1: a number after a list ------------------------------------------------------------------------------------------------------------------


def test_cancela_o_2_after_the_list_opens_the_card_of_item_2_exactly_as_cancela_o_evento_2_and_asks_no_model(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch)
    listed(world)
    reply = say(world, "cancela o 2")
    item = ops.pending(world["path"], 1)
    assert reply == CARD_SENT and item["status"] == "open" and model.calls == 0
    assert card_problems(item, *HAIR_2) == [] and "Event: evhair22" in item["body"].splitlines()
    assert item["body"].splitlines()[1:] == numbered_card_body(world, "cancela o evento 2").splitlines()[1:], "the same card, line for line (the first line holds the read's clock), as the numbered form"
    assert reads_only(world) == [], "nothing is approved or written by this path"
    assert card_problems(item, *HAIR_4) != [], "vacuity: the card of item 4 reads differently"


@pytest.mark.parametrize("line", ["o 2", "2", "#2", "the 2nd", "Cancela o evento 2", "por favor, cancela o 2", "2."])
def test_every_short_form_of_the_number_opens_the_card_of_that_item(world, monkeypatch, line):
    build(world, monkeypatch)
    model = Model(monkeypatch)
    listed(world)
    assert say(world, line) == CARD_SENT and model.calls == 0, line
    assert card_problems(ops.pending(world["path"], 1), *HAIR_2) == [], line


def test_the_other_number_of_the_list_opens_the_other_card(world, monkeypatch):
    build(world, monkeypatch)
    Model(monkeypatch)
    listed(world)
    assert say(world, "o 4") == CARD_SENT
    assert card_problems(ops.pending(world["path"], 1), *HAIR_4) == []


def test_a_change_form_with_the_number_reads_the_time_as_the_numbered_form_does(world, monkeypatch):
    build(world, monkeypatch)
    Model(monkeypatch)
    listed(world)
    got = say(world, "muda o 2 para as 15h")
    numbered = say_numbered(world, "muda o evento 2 para as 15h")
    assert got == "15:00 de hoje já passou: amanhã, qui 22/10, às 15:00\nO card #1 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert numbered == got.replace("#1", "#2"), "the same sentences as the numbered form"
    assert ops.pending(world["path"], 1)["body"].splitlines()[1:] == ops.pending(world["path"], 2)["body"].splitlines()[1:], "the same card, line for line (but the first line's clock second)"
    lines = ops.pending(world["path"], 1)["body"].splitlines()
    assert "Named as agenda#2, from the snapshot read at 2026-10-21T17:00:00Z." in lines and "After: When: Thu 22/10/2026 15:00-16:00 (America/Sao_Paulo)" in lines, lines


def say_numbered(world, line):
    return ops.natural_write(world["path"], line, channel="messaging", sender=OWNER)["reply"]


def test_a_bare_number_after_a_change_list_carries_the_new_time_the_person_gave(world, monkeypatch):
    build(world, monkeypatch)
    Model(monkeypatch)
    reply, _ = carry(world, "Muda o corte de cabelo para as 10h", op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-23T10:00", weekday="fri"))
    assert reply.startswith("Mais de um evento combina. Qual deles você quer mudar?")      # validate: allow english-only -- the Portuguese line or sentence under test
    assert say(world, "o 2") == CARD_SENT
    lines = ops.pending(world["path"], 1)["body"].splitlines()
    assert "Named as agenda#2, from the snapshot read at 2026-10-21T17:00:00Z." in lines, lines
    assert "Before: When: Thu 22/10/2026 13:00-14:00 (America/Sao_Paulo)" in lines and "After: When: Thu 22/10/2026 10:00-11:00 (America/Sao_Paulo)" in lines, "10h is the next 10h: tomorrow morning"
    assert "Unchanged: Title: corte de cabelo" in lines


def test_a_change_list_asked_by_a_rename_cannot_carry_the_title_so_a_bare_number_asks_what_to_change(world, monkeypatch):
    build(world, monkeypatch)
    Model(monkeypatch)
    carry(world, "Renomeia o corte de cabelo para Barbeiro", op_text("event-change", {"title": "Barbeiro"}))
    assert say(world, "o 2") == "Achei o evento, mas não entendi o que mudar. Diga o novo dia e horário, ou o novo nome."      # validate: allow english-only -- the Portuguese line or sentence under test
    assert rows(world) == ([], [])


# --- the context of the number: no list, another sender, after the window --------------------------------------------------------------------------


def test_with_no_list_a_number_is_today_the_model_and_opens_nothing(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    say(world, "cancela o 2")
    assert model.calls == 1 and rows(world) == ([], [])


def test_another_sender_gets_nothing_special_from_a_list_that_is_not_theirs(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    listed(world)
    say(world, "cancela o 2", sender=TALKER)
    assert model.calls == 1 and rows(world) == ([], []), "the talker has no list of their own"
    assert say(world, "cancela o 2") == CARD_SENT and model.calls == 1, "control: the owner, whose list it is, is understood without the model"


def test_after_the_window_a_number_is_a_new_line_and_before_it_the_list_still_holds(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    listed(world)
    world["clock"].set("2026-10-21 15:09")
    assert say(world, "cancela o 2") == CARD_SENT and model.calls == 0, "nine minutes later the list still holds"
    world["clock"].set("2026-10-21 15:11")
    say(world, "cancela o 4")
    assert model.calls == 1 and len(rows(world)[1]) == 1, "eleven minutes later it does not: the model is asked and no second card opens"


def test_a_number_the_list_did_not_show_is_no_form_of_the_list(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    listed(world)
    say(world, "cancela o 5")
    assert model.calls == 1 and rows(world) == ([], []), "5 is an event of the calendar, not an entry of the list"


def test_the_answer_to_an_open_question_of_the_family_is_taken_before_a_number_of_the_list(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, TEXT)
    listed(world)
    asked = say(world, "Agende corte de cabelo amanha as 14h")
    assert asked.startswith("Em qual conta?") and model.calls == 1, asked      # validate: allow english-only -- the Portuguese line or sentence under test
    assert say(world, "2") == CARD_SENT
    assert account_line(ops.pending(world["path"], 1)) == [f"Account: microsoft ({fgc.ADDRESS})"], "the 2 answered the question (option 2 is Microsoft), it did not cancel item 2"
    assert "Removing" not in ops.pending(world["path"], 1)["body"]


# --- a list is valid for the line right after it ------------------------------------------------------------------------------------------------------


def test_a_list_does_not_survive_an_unrelated_reply(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}', '{"v":1,"kind":"none"}')
    listed(world)
    say(world, "lista os pendentes")
    before = model.calls
    say(world, "o 2")
    assert rows(world) == ([], []) and model.calls == before + 1, "the pending list was said after the events: the 2 is no longer an event of that list"


def test_a_list_does_not_survive_a_line_that_is_not_a_number(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}', '{"v":1,"kind":"none"}')
    listed(world)
    say(world, "obrigado")
    say(world, "cancela o 2")
    assert rows(world) == ([], []) and model.calls == 2


def test_a_list_does_not_survive_a_greeting_the_natural_path_never_saw(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    listed(world)
    say(world, "oi")
    say(world, "cancela o 2")
    assert rows(world) == ([], []) and model.calls == 1


def test_a_card_made_after_the_list_ends_it_so_a_number_for_that_card_opens_no_event_card(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    listed(world)
    ops.event_create(world["path"], "google", "Haircut with Joe", "2026-10-23T13:00")          # a decision card exists now (the bridge sends it, and may list it)
    say(world, "cancela o 2")
    assert model.calls == 1 and [i["title"] for i in rows(world)[1]] == ["Calendar: new event"], "no event cancel card was opened"


def reads_at_once(world):
    """D5 is tested in test_plan_confirm*.py and test_messaging_plan_confirm.py: the tests below are about the numbered list and the form that follows it, so the senders hold `confirm-reads-off` (accepted with --widen)."""
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw["policies"] = {name: [*groups, "confirm-reads-off"] for name, groups in raw["policies"].items()}
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def test_a_question_about_the_entry_keeps_the_list_for_the_answer(world, monkeypatch):
    build(world, monkeypatch)
    reads_at_once(world)
    Model(monkeypatch)
    say(world, "lista os eventos")
    assert say(world, "2") == WHAT
    assert say(world, "cancela o 2") == CARD_SENT


@pytest.mark.parametrize("line", ["cancela os 2", "apaga as 2", "os 2", "as 2", "cancelar los 2", "annule les 2", "ambos 2"])
def test_a_plural_article_before_the_number_is_a_group_and_not_the_second(world, monkeypatch, line):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    listed(world)
    say(world, line)
    assert rows(world) == ([], []) and model.calls == 1, line
    assert event_lookup._number_form("cancela o 2") is not None, "control: the singular is a form"


# --- the snapshot the number means -------------------------------------------------------------------------------------------------------------------


def test_a_snapshot_refreshed_with_other_events_since_the_list_is_asked_again_and_nothing_opens(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch)
    listed(world)
    world["snaps"].providers.events[("google", fgw.CALENDAR)].insert(0, tsm.event(9, "2026-10-21T08:00:00-03:00", "2026-10-21T08:30:00-03:00", "Breakfast", id="evnew"))
    world["snaps"].later(minutes=5)
    world["snaps"].refresh("agenda")
    assert say(world, "cancela o 2") == AGAIN and model.calls == 0
    assert rows(world) == ([], []), "the number would now be another event: nothing is guessed"
    assert AGAIN != CARD_SENT


def test_a_refresh_that_changed_nothing_keeps_the_numbers_of_the_list(world, monkeypatch):
    build(world, monkeypatch)
    Model(monkeypatch)
    listed(world)
    world["snaps"].later(minutes=5)
    world["snaps"].refresh("agenda")
    assert say(world, "cancela o 2") == CARD_SENT
    assert card_problems(ops.pending(world["path"], 1), *HAIR_2) == []


# --- the items list of the calendar ------------------------------------------------------------------------------------------------------------------


def test_after_the_items_list_a_verb_and_a_number_open_the_card_and_a_bare_number_asks_what_to_do(world, monkeypatch):
    build(world, monkeypatch)
    reads_at_once(world)
    model = Model(monkeypatch)
    shown = say(world, "lista os eventos")
    assert "2. " in shown and "corte de cabelo" in shown, shown
    assert say(world, "2") == WHAT and rows(world) == ([], [])
    assert say(world, "cancela o 2") == CARD_SENT and model.calls == 0
    assert card_problems(ops.pending(world["path"], 1), *HAIR_2) == []


def test_a_list_of_mail_clears_the_record_of_the_events(world, monkeypatch):
    build(world, monkeypatch)
    model = Model(monkeypatch, '{"v":1,"kind":"none"}')
    say(world, "lista os eventos")
    say(world, "lista os emails")
    say(world, "cancela o 2")
    assert model.calls >= 1 and rows(world) == ([], [])


def test_the_record_holds_no_line_title_or_text(world, monkeypatch):
    build(world, monkeypatch)
    Model(monkeypatch)
    listed(world)
    kept = repr(event_lookup._LISTS)
    for piece in ("corte", "cabelo", "Cancela", "Yoga", "Dentist"):
        assert piece.lower() not in kept.lower(), piece
    assert "agenda" in kept and "evhair" not in kept


# --- item 2: the account the line names --------------------------------------------------------------------------------------------------------------

CREATE = "Agende corte de cabelo amanha as 14h {where}"
TEXT = op_text("event-create", {"time": "amanha as 14h", "title": "corte de cabelo"}, time_iso="2026-10-22T14:00", weekday="thu")


def create_with(world, where, text=TEXT):
    return carry(world, CREATE.format(where=where), text)


def account_line(item):
    return [line for line in item["body"].splitlines() if line.startswith("Account: ")]


def test_no_outlook_with_two_accounts_opens_the_card_of_the_microsoft_account_and_asks_nothing(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = create_with(world, "no outlook")
    assert reply == CARD_SENT and account_line(card(world, extras)) == [f"Account: microsoft ({fgc.ADDRESS})"]
    assert "Title: corte de cabelo" in card(world, extras)["body"].splitlines()
    assert reads_only(world) == [] and card(world, extras)["status"] == "open"


@pytest.mark.parametrize("where, account", [("no google", fgw.ACCOUNT), ("na agenda do google", fgw.ACCOUNT), ("no google agenda", fgw.ACCOUNT), ("pelo gmail", fgw.ACCOUNT),
                                              ("na agenda do outlook", fgc.ADDRESS), ("no meu outlook", fgc.ADDRESS), ("na microsoft", fgc.ADDRESS), ("no hotmail", fgc.ADDRESS),
                                              ("on my outlook calendar", fgc.ADDRESS), ("in google calendar", fgw.ACCOUNT)])
def test_an_account_word_of_the_closed_list_chooses_the_account(world, monkeypatch, where, account):
    build(world, monkeypatch)
    reply, extras = create_with(world, where)
    assert reply == CARD_SENT, where
    assert account_line(card(world, extras)) == [f"Account: {'google' if account == fgw.ACCOUNT else 'microsoft'} ({account})"], where


def test_a_line_with_no_account_word_still_asks_which_account(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = create_with(world, "")
    assert reply.startswith("Em qual conta?") and "resend" not in extras and rows(world) == ([], [])      # validate: allow english-only -- the Portuguese line or sentence under test
    assert reply != CARD_SENT


@pytest.mark.parametrize("line, title", [("Agende corte de cabelo com o Google amanha as 14h", "corte de cabelo"), ("Agende corte de cabelo amanha as 14h no google e no outlook", "corte de cabelo"),
                                          ("Agende corte de cabelo amanha as 14h outlook", "corte de cabelo"), ("Agende almoco no google amanha as 14h", "almoco no google")])
def test_a_brand_with_no_lead_in_a_title_or_beside_the_other_account_names_none(world, monkeypatch, line, title):
    build(world, monkeypatch)
    text = op_text("event-create", {"time": "amanha as 14h", "title": title}, time_iso="2026-10-22T14:00", weekday="thu")
    reply, extras = carry(world, line, text)
    assert reply.startswith("Em qual conta?") and "resend" not in extras, (line, reply)      # validate: allow english-only -- the Portuguese line or sentence under test


def test_the_model_service_word_counts_only_when_it_is_a_brand_and_stands_in_the_line(world, monkeypatch):
    build(world, monkeypatch)
    text = op_text("event-create", {"time": "amanha as 14h", "title": "corte de cabelo", "service": "outlook"}, time_iso="2026-10-22T14:00", weekday="thu")
    reply, extras = carry(world, "Agende corte de cabelo amanha as 14h outlook", text)
    assert reply == CARD_SENT and account_line(card(world, extras)) == [f"Account: microsoft ({fgc.ADDRESS})"]
    other = op_text("event-create", {"time": "amanha as 14h", "title": "corte de cabelo", "service": "agenda"}, time_iso="2026-10-22T14:00", weekday="thu")
    reply, extras = carry(world, "Agende corte de cabelo amanha as 14h agenda", other)
    assert reply.startswith("Em qual conta?") and "resend" not in extras, "a word that is not a brand names no account"      # validate: allow english-only -- the Portuguese line or sentence under test


def test_no_outlook_when_no_microsoft_calendar_is_configured_says_so_and_opens_no_card_of_another_account(world, monkeypatch):
    build(world, monkeypatch)
    raw_path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(raw_path).read())
    raw["accounts"]["microsoft"]["calendars"] = {}
    open(raw_path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    try:
        ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    except ops_core.OpsError:
        ops.accept_config(world["path"], shown["sha256"], widen=ops.config(world["path"])["widening_sha256"])
    reply, extras = create_with(world, "no outlook")
    assert reply == NO_MICROSOFT and "resend" not in extras and rows(world) == ([], [])
    reply, extras = create_with(world, "no google")
    assert reply == CARD_SENT and account_line(card(world, extras)) == [f"Account: google ({fgw.ACCOUNT})"], "control: the configured account is still served"


# --- the same account word narrows an event to change or cancel -----------------------------------------------------------------------------------


def add_outlook(world):
    world["snaps"].calendar("outlook", "outlook", "default", [tsm.event(1, "2026-10-22T13:00:00-03:00", "2026-10-22T14:00:00-03:00", "corte de cabelo", id="AAMkOut=")])
    world["graph"].add_event("AAMkOut=", "corte de cabelo", "2026-10-22T16:00:00", "2026-10-22T17:00:00")


def test_without_an_account_word_both_calendars_are_listed_with_the_account_word_each_is_alone(world, monkeypatch):
    build(world, monkeypatch)
    add_outlook(world)
    reply, _ = carry(world, "Cancela o corte de cabelo", CANCEL)
    assert reply.count(" · corte de cabelo") == 3 and "(Agenda do Google)" in reply and "(Agenda do Outlook)" in reply, reply
    reply, _ = carry(world, "Cancela o corte de cabelo no google", CANCEL)
    assert reply.count(" · corte de cabelo") == 2 and "(outlook)" not in reply and "2. Thu 22/10/2026" in reply and "4. Fri 23/10/2026" in reply, reply
    changed = op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu")
    reply, extras = carry(world, "Muda o corte de cabelo no outlook para as 10h", changed)
    assert reply == CARD_SENT
    lines = card(world, extras)["body"].splitlines()
    assert "Named as outlook#1, from the snapshot read at 2026-10-21T17:00:00Z." in lines and account_line(card(world, extras)) == [f"Account: microsoft ({fgc.ADDRESS})"], lines


def test_an_account_with_no_calendar_source_is_one_plain_sentence_for_a_lookup(world, monkeypatch):
    build(world, monkeypatch)
    reply, extras = carry(world, "Cancela o corte de cabelo no outlook", CANCEL)
    assert reply == NO_MICROSOFT and "resend" not in extras and rows(world) == ([], [])


class Writes:
    """Stands in for the card-opening family: the numbered attempt finds nothing, the seed it is handed is recorded."""

    def __init__(self):
        self.seeds = []

    def open_line(self, project, ctx, said, channel, sender, extras, hint=None, seed=None):
        if seed is not None:
            self.seeds.append(seed)
        return "opened" if seed is not None else None


def two_titles(world, monkeypatch, google_title, outlook_title):
    build(world, monkeypatch, events=[("22", "10:00", "11:00", google_title, "evg")])
    world["snaps"].calendar("outlook", "outlook", "default", [tsm.event(1, "2026-10-22T13:00:00-03:00", "2026-10-22T14:00:00-03:00", outlook_title, id="AAMkO=")])


def open_event(world, line, op="event-cancel"):
    writes, ctx = Writes(), ops_core.context(world["path"])
    decision = {"op": op, "spans": {}, "args": {}, "time": None}
    reply = event_lookup.open_event(world["path"], ctx, decision, line, OWNER, {}, writes, ops_natural._clock())
    return reply, writes.seeds


def test_an_account_word_inside_the_title_of_an_event_that_fits_is_not_an_account(world, monkeypatch):
    two_titles(world, monkeypatch, "Reuniao", "Reuniao do Google")
    reply, seeds = open_event(world, "Cancela a reuniao do google amanha")
    assert reply == "opened" and [s["slots"]["source"] for s in seeds] == ["outlook"], "the event named Reuniao do Google, in Outlook, is the one the line names"
    assert "account" not in seeds[0]["slots"]
    reply, seeds = open_event(world, "Cancela a reuniao amanha no google")
    assert reply == "opened" and [(s["slots"]["source"], s["slots"]["account"]) for s in seeds] == [("agenda", "google")], "control: a word outside every title narrows"


def test_an_account_word_in_the_titles_of_both_accounts_lists_both_and_asks(world, monkeypatch):
    two_titles(world, monkeypatch, "Reuniao do Google", "Reuniao do Google")
    reply, seeds = open_event(world, "Cancela a reuniao do google amanha")
    assert seeds == [] and reply.startswith("Mais de um evento combina.") and "(Agenda do Google)" in reply and "(Agenda do Outlook)" in reply, reply      # validate: allow english-only -- the Portuguese line or sentence under test


def test_the_model_word_that_is_only_in_the_title_names_no_account_and_the_create_asks(world, monkeypatch):
    assert event_lookup.account_named("agende almoco no google amanha", "almoco no google", "google") is None
    assert event_lookup.account_named("agende almoco no google amanha", "almoco", "google") == "google", "control: outside the title it is the account"
    build(world, monkeypatch)
    text = op_text("event-create", {"time": "amanha as 14h", "title": "almoco no google", "service": "google"}, time_iso="2026-10-22T14:00", weekday="thu")
    reply, extras = carry(world, "Agende almoco no google amanha as 14h", text)
    assert reply.startswith("Em qual conta?") and "resend" not in extras, reply      # validate: allow english-only -- the Portuguese line or sentence under test


# --- the pure rule: which account a line names ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("line, title, hint, expected", [
    ("Agende corte amanha no outlook", None, None, "microsoft"), ("Agende corte na agenda do outlook", None, None, "microsoft"),                                  # pt
    ("Marca dentista pelo gmail", None, None, "google"), ("Marca dentista no Google Agenda", None, None, "google"),
    ("book a haircut on my google calendar", None, None, "google"), ("book a haircut in outlook", None, None, "microsoft"),                                       # en
    ("reservar corte en mi gmail", None, None, "google"), ("reservar corte en el calendario de outlook", None, None, "microsoft"),                            # es
    ("ajouter un rendez-vous sur outlook", None, None, "microsoft"), ("ajouter un rendez-vous dans google agenda", None, None, "google"),                       # fr
    ("Termin im Outlook Kalender anlegen", None, None, "microsoft"), ("Termin bei Google eintragen", None, None, "google"),                                     # de
    ("aggiungi un appuntamento su Google Calendar", None, None, "google"), ("aggiungi un appuntamento nel calendario di Hotmail", None, None, "microsoft"),   # it
    ("almoco com o google amanha", None, None, None), ("reuniao outlook amanha", None, None, None), ("no google e no outlook", None, None, None),
    ("agende almoco no google", "almoco no google", None, None), ("agende almoco no google", "almoco", None, "google"),
    ("agende almoco outlook", None, "outlook", "microsoft"), ("agende almoco", None, "outlook", None), ("agende almoco outlook", None, "agenda", None),
    ("agende almoco", None, None, None), ("", None, None, None),
])
def test_the_account_a_line_names(line, title, hint, expected):
    assert event_lookup.account_named(line, title, hint) == expected, line


def test_vacuity_the_oracle_of_the_account_fails_for_the_other_account():
    assert event_lookup.account_named("Agende corte amanha no outlook") != "google"

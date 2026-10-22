"""The card of an event that waits is changed by words (slice S13, runtime/ops_card_revise.py, runtime/ops_event_revise.py, limits L55 and L64).

The live test of 2026-10-22: after the card of a new event ("Title: evento social ... Sat 24/10/2026 08:00-09:00") the maintainer wrote `Mude o título do evento para "Evento Coders 26K"` and the line
went to the lookup of an event of the calendar, which has no such event. Here the real calendar world of test_event_lookup.py (the real snapshots, the real family path, the real cards), a stand-in
clock (Wednesday 2026-10-21 15:00 at -03:00) and a stand-in model that answers the interpreter's call by a hand-written text, which the real checks of the interpreter then believe or not. Every
expectation is a literal of this file: the cards' lines, the sentences. Every name is invented.

Held here:
  * the live line on the card of a new event: a NEW card, the title "Evento Coders 26K", the same day, the same hours, the same account and calendar; the old card is never approvable; the calendar is
    not searched and no event of it is touched;
  * "muda para as 10h" on the card of a new event: the new hour on the card's day, the length of the event kept; a time that needs a question is asked as it is asked for any line;
  * the card of a change of an event found in a snapshot is changed the same way (the event is the same, the part named is replaced); the card of a cancel gets the sentence that it cannot be;
  * a decision that is not a change of an event goes on (once: the model is not asked a second time); a sender who is not read by the interpreter, a card that changed, and a line that is a word that
    decides a card are not touched; nothing is written to a calendar.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_revise_flow.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
import test_event_lookup as tel
from test_calendar_write import rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import OWNER, carry, op_text, reads_only  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_card_revise = st.load("ops_card_revise")
interpreter_route = st.load("interpreter_route")
phrases = st.load("phrases")

LIVE = 'Mude o título do evento para "Evento Coders 26K"'      # validate: allow english-only -- the live line, Portuguese
FAILED = "Não consegui fazer esse ajuste. Diga de outro jeito ou rejeite o card."      # validate: allow english-only -- the Portuguese sentence under test
NOT_REVISABLE = "Para mudar este card, rejeite e peça de novo."      # validate: allow english-only -- the Portuguese sentence under test
PROFILES = {"owner": ["read", "talk", "calendar-write", "ask-mail", "interpret", "reject-cancel"], "talker": ["read", "talk", "calendar-write", "reject-cancel"]}


class Model:
    """The stand-in for the daily route: the text it answers to the interpreter's call (or None for a failed call); `calls` lists what was asked."""

    def __init__(self, monkeypatch, text):
        self.text, self.calls = text, []
        monkeypatch.setattr(interpreter_route, "complete", self.complete)

    def complete(self, route_id, system, user, **kw):
        self.calls.append(user)
        if self.text is None:
            return {"ok": False, "code": "E_TIMEOUT"}
        return {"ok": True, "text": self.text, "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}


@pytest.fixture(autouse=True)
def fresh():
    ops_interpret.forget_all()
    ops_card_revise.forget_all()
    yield
    ops_interpret.forget_all()
    ops_card_revise.forget_all()


def build(world, monkeypatch, text=None):
    monkeypatch.setattr(tel, "PROFILES", PROFILES)
    monkeypatch.setattr(tel, "IDS", {"owner": "4242", "talker": "5151"})
    tel.build(world, monkeypatch)
    return Model(monkeypatch, text)


def create(world, title="evento social", start="2026-10-24T08:00", end="2026-10-24T09:00", account="google", **more):
    started = ops.event_create(world["path"], account, title, start, end=end, channel="messaging", sender=OWNER, **more)
    return started["pending"], ops.pending(world["path"], started["pending"])["payload_sha256"]


def check(world, number, sha, line, sender=OWNER):
    return ops.card_revise_check(world["path"], number, sha, line, channel="messaging", sender=sender)


def revise(world, number, sha, line, sender=OWNER):
    return ops.card_revise(world["path"], number, sha, line, channel="messaging", sender=sender)


def body(world, number):
    return ops.pending(world["path"], number)["body"].splitlines()


def status(world, number):
    ctx = ops_core.context(world["path"])
    return ctx["store"].pending_get(ctx["conn"], number)["status"]


def open_cards(world):
    return [p["id"] for p in rows(world)[1]]


def refused_for_good(world, number, sha):
    with pytest.raises(ops.OpsError):
        ops.approve(world["path"], number, sha256=sha, channel="terminal")


OLD = ["Code creates this event after your approval, and nothing else.", "Account: google (pat@example.com)", "Calendar: personal", "Title: evento social",
       "When: Sat 24/10/2026 08:00-09:00 (America/Sao_Paulo)", "No one is invited: no e-mail is sent."]


def test_the_live_line_on_the_card_of_a_new_event_opens_a_new_card_with_the_new_title_and_the_old_one_is_never_approvable(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = create(world)
    assert body(world, old) == OLD
    assert check(world, old, sha, LIVE) == "event"
    got = revise(world, old, sha, LIVE)
    new = got["resend"]
    assert isinstance(new, int) and new != old
    assert got["say"] == "Pronto: aqui está o e-mail com o seu ajuste. O card anterior não vale mais; aprove ou rejeite este."      # validate: allow english-only -- the Portuguese sentence under test
    assert body(world, new) == [line.replace("Title: evento social", "Title: Evento Coders 26K") for line in OLD], "only the title moved"
    assert status(world, old) != "open" and open_cards(world) == [new]
    refused_for_good(world, old, sha)
    assert reads_only(world) == [] and len(model.calls) == 1, "nothing is written to a calendar, and the line is read by the model once"
    assert [r for r in world["google"].requests if r["method"] == "GET" and "events" in r["path"]] == [], "the calendar is not searched"


def test_a_title_the_model_quotes_is_taken_without_its_quotation_marks(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"title": '"Evento Coders 26K"'}))
    old, sha = create(world)
    assert "Title: Evento Coders 26K" in body(world, revise(world, old, sha, LIVE)["resend"])


def test_vacuity_the_title_oracle_fails_for_a_card_that_kept_the_old_title(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = create(world)
    assert "Title: Evento Coders 26K" not in body(world, old)
    assert "Title: Evento Coders 26K" in body(world, revise(world, old, sha, LIVE)["resend"])


def test_muda_para_as_10h_moves_the_hour_on_the_cards_day_and_keeps_the_length(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"))
    old, sha = create(world)
    line = "muda para as 10h"
    assert check(world, old, sha, line) == "event"
    new = revise(world, old, sha, line)["resend"]
    assert body(world, new) == [l.replace("08:00-09:00", "10:00-11:00") for l in OLD]
    assert status(world, old) != "open"
    refused_for_good(world, old, sha)
    assert reads_only(world) == []


def test_a_day_the_line_names_is_taken_and_a_longer_event_keeps_its_length(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"time": "as 15h do dia 23"}, time_iso="2026-10-23T15:00", weekday="fri"))
    old, sha = create(world, start="2026-10-24T08:00", end="2026-10-24T10:30")
    new = revise(world, old, sha, "muda para as 15h do dia 23")["resend"]
    assert "When: Fri 23/10/2026 15:00-17:30 (America/Sao_Paulo)" in body(world, new)


def test_title_and_hour_in_one_line_change_both(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"title": "yoga", "time": "as 10h do dia 23"}, time_iso="2026-10-23T10:00", weekday="fri"))
    old, sha = create(world)
    new = revise(world, old, sha, "Muda o yoga para as 10h do dia 23")["resend"]      # validate: allow english-only -- the Portuguese line under test
    assert body(world, new)[3:5] == ["Title: yoga", "When: Fri 23/10/2026 10:00-11:00 (America/Sao_Paulo)"]


def test_the_account_word_changes_the_account_of_a_card_that_creates_an_event_and_nothing_else(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"))
    old, sha = create(world)
    new = revise(world, old, sha, "muda para as 10h no outlook")["resend"]
    lines = body(world, new)
    assert lines[1].startswith("Account: microsoft") and "When: Sat 24/10/2026 10:00-11:00 (America/Sao_Paulo)" in lines and "Title: evento social" in lines


def test_a_time_that_needs_a_question_is_asked_as_it_is_for_any_line_and_nothing_changes(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-change", {"time": "as 10"}, time_iso="2026-10-22T10:00", weekday="thu"))
    old, sha = create(world)
    got = revise(world, old, sha, "muda para as 10")
    assert got["resend"] is None and got["say"] and open_cards(world) == [old] and status(world, old) == "open"
    assert len(model.calls) == 1


def test_a_decision_that_is_not_a_change_of_an_event_goes_on_and_is_not_read_twice(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-create", {"title": "Dentista", "time": "amanha as 9h"}, time_iso="2026-10-22T09:00", weekday="thu"))
    old, sha = create(world)
    line = "Agende dentista amanha as 9h"
    assert revise(world, old, sha, line) == {"pass": True}
    assert open_cards(world) == [old] and status(world, old) == "open"
    ctx = ops_core.context(world["path"])
    got = ops_interpret.turn(world["path"], ctx, line, OWNER, {})      # the turn that follows reads the decision that was kept
    assert len(model.calls) == 1 and got is not None
    assert ops_card_revise.decided(OWNER, line) is None, "once"


def test_a_failed_model_call_goes_on_and_a_change_with_nothing_named_asks_what(world, monkeypatch):
    model = build(world, monkeypatch, None)
    old, sha = create(world)
    assert revise(world, old, sha, LIVE) == {"pass": True} and open_cards(world) == [old]
    ops_interpret.forget_all()
    model.text = op_text("event-change")
    got = revise(world, old, sha, "muda o evento")
    assert got["resend"] is None and got["say"] == phrases.text("EV_CHANGE_WHAT", ops_core.context(world["path"])["cfg"]) and open_cards(world) == [old]


def test_the_card_of_a_change_of_an_event_found_in_a_snapshot_is_changed_with_the_same_event(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-23T10:00", weekday="fri"))
    _, extras = carry(world, "Muda o yoga para as 10h do dia 23", op_text("event-change", {"time": "as 10h do dia 23"}, time_iso="2026-10-23T10:00", weekday="fri"))
    old = extras["resend"]
    sha = ops.pending(world["path"], old)["payload_sha256"]
    before = body(world, old)
    assert any("Named as agenda#3" in l for l in before) and check(world, old, sha, "muda o título para Barbeiro") == "event"
    model.text = op_text("event-change", {"title": "Barbeiro"})
    ops_interpret.forget_all()
    new = revise(world, old, sha, "muda o título para Barbeiro")["resend"]
    after = body(world, new)
    assert any("Named as agenda#3" in l for l in after) and any("Barbeiro" in l for l in after)
    assert [l for l in before if "When" in l] == [l for l in after if "When" in l], "the new time of the first change is kept"
    assert status(world, old) != "open"
    assert reads_only(world) == []


def test_the_card_of_a_cancel_gets_the_sentence_that_it_cannot_be_changed_by_words_and_a_line_that_asks_for_nothing_goes_on(world, monkeypatch):
    model = build(world, monkeypatch, None)
    _, extras = carry(world, "Remova o corte de cabelo dia 23", tel.CANCEL)
    number = extras["resend"]
    sha = ops.pending(world["path"], number)["payload_sha256"]
    assert check(world, number, sha, "muda o título para Barbeiro") == "sentence"
    assert revise(world, number, sha, "muda o título para Barbeiro") == {"say": NOT_REVISABLE, "resend": None}
    assert check(world, number, sha, "e o dentista?") is None, "no word that asks for a change: it goes on"
    assert status(world, number) == "open" and model.calls == []


@pytest.mark.parametrize("line", ["aprovo", "sim", "não", "/pending", "oi", "o que está pendente?", "me lembra de ligar amanhã às 9h"])      # validate: allow english-only -- the Portuguese lines under test
def test_a_word_that_decides_a_card_a_command_and_a_request_code_recognises_are_not_a_change(world, monkeypatch, line):
    model = build(world, monkeypatch, op_text("event-change", {"title": "X"}))
    old, sha = create(world)
    assert check(world, old, sha, line) is None and model.calls == []


def test_a_card_that_changed_a_sender_not_read_by_the_interpreter_and_one_who_cannot_reject_are_not_touched(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = create(world)
    assert check(world, old, "0" * 64, LIVE) is None and check(world, old + 50, sha, LIVE) is None
    assert check(world, old, sha, LIVE, sender=tel.TALKER) is None, "the talker holds no `interpret`"
    assert revise(world, old, sha, LIVE, sender=tel.TALKER) == {"pass": True} and model.calls == []
    assert check(world, old, sha, LIVE) == "event", "vacuity: the owner's line is one"

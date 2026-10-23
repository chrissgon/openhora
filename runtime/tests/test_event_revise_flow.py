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
import test_sources_mail as tsm
from test_calendar_write import fgw, rows, world  # noqa: F401  (the calendar world and its real snapshots)
from test_event_lookup import OWNER, carry, op_text, reads_only  # noqa: F401
from test_ops_natural_writes import forget  # noqa: F401

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_card_revise = st.load("ops_card_revise")
event_revise = st.load("ops_event_revise")
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
    assert got["say"] == "Pronto: aqui está o evento com o seu ajuste. O card anterior não vale mais; aprove ou rejeite este." and "e-mail" not in got["say"]      # validate: allow english-only -- the Portuguese sentence under test
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
    assert got["resend"] == old and got["say"] and open_cards(world) == [old] and status(world, old) == "open", "the question, and the old card sent once more after it"
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
    assert ops_card_revise.decided(world["path"], "messaging", OWNER, line) is None, "once"


def test_a_failed_model_call_goes_on_and_a_change_with_nothing_named_asks_what(world, monkeypatch):
    model = build(world, monkeypatch, None)
    old, sha = create(world)
    assert revise(world, old, sha, LIVE) == {"pass": True} and open_cards(world) == [old]
    ops_interpret.forget_all()
    model.text = op_text("event-change")
    got = revise(world, old, sha, "muda o evento")
    assert got["resend"] == old and got["say"] == phrases.text("EV_CHANGE_WHAT", ops_core.context(world["path"])["cfg"]) and open_cards(world) == [old]


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


# --- the fixes of the review: the event, the other event, the moment, the parts the line did not name, no two open cards ------------------------------------------


def snapshot_cards(world, monkeypatch, text):
    """The calendar world with a change card for the yoga (agenda#3) and a model that answers `text`."""
    build(world, monkeypatch, text)
    _, extras = carry(world, "Muda o yoga para as 10h do dia 23", op_text("event-change", {"time": "as 10h do dia 23"}, time_iso="2026-10-23T10:00", weekday="fri"))
    return extras["resend"], ops.pending(world["path"], extras["resend"])["payload_sha256"]


def test_a_snapshot_refreshed_meanwhile_never_makes_the_new_card_move_another_event(world, monkeypatch):
    old, sha = snapshot_cards(world, monkeypatch, op_text("event-change", {"title": "Barbeiro"}))
    assert any("Named as agenda#3" in l for l in body(world, old))
    provided = [tsm.event(i + 1, f"2026-10-{day}T{start}:00-03:00", f"2026-10-{day}T{end}:00-03:00", title, id=ident)
                for i, (day, start, end, title, ident) in enumerate([("20", "09:00", "10:00", "Early", "evearly")] + tel.EVENTS)]      # an earlier event: every number after it moves by one
    world["google"].add_event("evearly", "Early", {"dateTime": "2026-10-20T09:00:00-03:00"}, {"dateTime": "2026-10-20T10:00:00-03:00"})
    world["snaps"].providers.events[("google", fgw.CALENDAR)] = provided
    world["snaps"].later(minutes=1)
    world["snaps"].refresh("agenda")
    got = revise(world, old, sha, "muda o título para Barbeiro")      # validate: allow english-only -- the Portuguese line under test
    assert got["resend"] is None and got["say"].endswith("Peça de novo.")      # validate: allow english-only -- the Portuguese sentence under test
    assert open_cards(world) == [], "no card stays open, and none names the event that the old number points to now"
    assert reads_only(world) == []


def test_a_line_that_names_another_event_leaves_the_card_alone_and_goes_on(world, monkeypatch):
    model = build(world, monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"))
    old, sha = create(world)
    assert revise(world, old, sha, "muda o dentista para as 10h") == {"pass": True}      # validate: allow english-only -- the Portuguese line under test
    assert open_cards(world) == [old] and status(world, old) == "open" and len(model.calls) == 1
    assert ops_card_revise.decided(world["path"], "messaging", OWNER, "muda o dentista para as 10h") is not None, "the decision is kept for the turn that follows"      # validate: allow english-only -- the Portuguese line under test


@pytest.mark.parametrize("line", ["muda para as 10h", "muda o evento social para as 10h", "muda o horario do evento para as 10h"])      # validate: allow english-only -- the Portuguese lines under test
def test_a_line_that_names_the_cards_own_event_or_none_still_revises_it(world, monkeypatch, line):
    build(world, monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"))
    old, sha = create(world)
    new = revise(world, old, sha, line)["resend"]
    assert "When: Sat 24/10/2026 10:00-11:00 (America/Sao_Paulo)" in body(world, new)


def test_a_moment_in_the_past_is_asked_as_a_typed_line_would_be(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"time": "as 10h"}, time_iso="2026-10-22T10:00", weekday="thu"))
    old, sha = create(world, start="2026-10-21T08:00", end="2026-10-21T09:00")      # the card's day is today, 15:00 has passed: 10h on that day is past
    got = revise(world, old, sha, "muda para as 10h")
    assert got == {"say": phrases.text("IX_ASK_PAST", ops_core.context(world["path"])["cfg"]), "resend": old} and open_cards(world) == [old]


def test_the_parts_the_line_did_not_name_are_copied_and_a_card_that_lost_one_is_ended(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = create(world, location="Main Street", reminder_minutes=30, notes="Bring cash")
    kept = [l for l in body(world, old) if l.startswith(("Where", "Calendar reminder", "Notes"))]
    assert len(kept) == 3
    real = ops.event_create
    monkeypatch.setattr(ops, "event_create", lambda project, **kw: real(project, **dict(kw, location="Elsewhere")))
    lost = revise(world, old, sha, LIVE)
    assert lost["resend"] is None and open_cards(world) == [], "a card that does not keep the location is ended, and none stays open"
    monkeypatch.setattr(ops, "event_create", real)
    old2, sha2 = create(world, location="Main Street", reminder_minutes=30, notes="Bring cash")
    new = revise(world, old2, sha2, LIVE)["resend"]
    assert [l for l in body(world, new) if l.startswith(("Where", "Calendar reminder", "Notes"))] == kept


def test_a_card_that_cannot_be_ended_or_a_new_card_that_cannot_be_opened_never_leaves_two_open_cards(world, monkeypatch):
    build(world, monkeypatch, op_text("event-change", {"title": "Evento Coders 26K"}))
    old, sha = create(world)
    real = ops.reject
    monkeypatch.setattr(ops, "reject", lambda project, number, **kw: (_ for _ in ()).throw(ops.OpsError("busy", 1)))
    got = revise(world, old, sha, LIVE)
    monkeypatch.setattr(ops, "reject", real)
    assert got["resend"] == old and open_cards(world) == [old]
    monkeypatch.setattr(ops, "event_create", lambda project, **kw: (_ for _ in ()).throw(ops.OpsError("no card", 1)))
    got = revise(world, old, sha, LIVE)
    assert got["resend"] is None and got["say"].endswith("Peça de novo.") and open_cards(world) == []      # validate: allow english-only -- the Portuguese sentence under test


# --- the live case of 17:01: "muda para as 10h" on the card of a new event, and a model answer of a shape the check refuses -------------------------------------


MUDA = "muda para as 10h"      # validate: allow english-only -- the live line, Portuguese
TIME10 = {"time": "as 10h"}
SHAPES = {
    "event-slot-title": op_text("event-change", {"event": "corte de cabelo", **TIME10}, time_iso="2026-10-22T10:00", weekday="thu"),
    "event-slot-day": op_text("event-change", {"event": "amanhã", **TIME10}, time_iso="2026-10-22T10:00", weekday="thu"),      # validate: allow english-only -- the stand-in model's answer
    "event-slot-number": op_text("event-change", {"event": "7", **TIME10}, time_iso="2026-10-22T10:00", weekday="thu"),
    "clarify-event": json.dumps({"v": 1, "kind": "clarify", "slot": "event"}),
    "extra-slots": op_text("event-change", {**TIME10, "calendar": "pessoal", "service": "outlook"}, time_iso="2026-10-22T10:00", weekday="thu"),
    "event-create": op_text("event-create", {"title": "corte", **TIME10}, time_iso="2026-10-22T10:00", weekday="thu"),
    "event-create-time-only": op_text("event-create", TIME10, time_iso="2026-10-22T10:00", weekday="thu"),
    "invalid-json": "this is not json",
    "empty-object": "{}",
}


def haircut_card(world):
    return create(world, account="microsoft", title="corte de cabelo", start="2026-10-23T14:00", end="2026-10-23T15:00")


@pytest.mark.parametrize("shape", list(SHAPES))
def test_muda_para_as_10h_revises_the_event_card_whatever_the_shape_of_the_model_answer(world, monkeypatch, shape):
    model = build(world, monkeypatch, SHAPES[shape])
    old, sha = haircut_card(world)
    before = body(world, old)
    assert "Account: microsoft" in before[1] and "Title: corte de cabelo" in before and "When: Fri 23/10/2026 14:00-15:00 (America/Sao_Paulo)" in before
    assert check(world, old, sha, MUDA) == "event"
    got = revise(world, old, sha, MUDA)
    new = got["resend"]
    assert isinstance(new, int) and new != old, got
    after = body(world, new)
    assert after == [l.replace("14:00-15:00", "10:00-11:00") for l in before], "the new hour on the card's day, the length kept, the account and the calendar kept"
    assert status(world, old) != "open" and open_cards(world) == [new] and len(model.calls) == 1
    refused_for_good(world, old, sha)
    assert all(r["method"] == "GET" or r["path"].endswith("/token") for r in world["graph"].requests), "nothing is written to the calendar"
    assert reads_only(world) == []


@pytest.mark.parametrize("shape", ["event-create", "event-create-time-only"])      # S16b made the interpreter read an unreadable answer by the line's own verb (invalid JSON, `{}`) too; an event-create answer is still not a change
def test_vacuity_the_interpreter_alone_refuses_these_shapes_so_the_card_is_not_revised_without_the_card_reading(world, monkeypatch, shape):
    build(world, monkeypatch, SHAPES[shape])
    ctx = ops_core.context(world["path"])
    entry = ops_card_revise.entry_of(ctx, "messaging", OWNER, False)
    old = ops_interpret._ask_model(ctx, entry, MUDA, OWNER)
    assert old.get("op") != "event-change", "the answer, read as any line is read, is not a change of an event: it was asked again before"


@pytest.mark.parametrize("shape", ["event-create", "invalid-json", "clarify-event", "event-slot-title"])
def test_a_line_that_names_another_event_still_leaves_the_card_alone_in_every_shape(world, monkeypatch, shape):
    build(world, monkeypatch, SHAPES[shape])
    old, sha = haircut_card(world)
    got = revise(world, old, sha, "muda o dentista para as 10h")      # validate: allow english-only -- the Portuguese line under test
    assert got == {"pass": True} and open_cards(world) == [old] and status(world, old) == "open"


def test_a_line_with_a_change_verb_and_nothing_code_can_read_asks_again_and_sends_the_card_again(world, monkeypatch):
    build(world, monkeypatch, "this is not json")
    old, sha = haircut_card(world)
    got = revise(world, old, sha, "muda o evento")      # validate: allow english-only -- the Portuguese line under test
    assert got["resend"] == old and got["say"] and open_cards(world) == [old]


def test_an_hour_the_engine_cannot_decide_alone_is_asked_and_a_moment_in_the_past_is_asked_in_every_shape(world, monkeypatch):
    build(world, monkeypatch, "this is not json")
    old, sha = haircut_card(world)
    got = revise(world, old, sha, "muda para as 9")      # validate: allow english-only -- the Portuguese line under test
    assert got["resend"] == old and open_cards(world) == [old], "9 may be the morning or the evening: asked, nothing changed"
    past, past_sha = create(world, account="microsoft", title="corte de cabelo", start="2026-10-21T08:00", end="2026-10-21T09:00")
    asked = revise(world, past, past_sha, MUDA)
    assert asked == {"say": phrases.text("IX_ASK_PAST", ops_core.context(world["path"])["cfg"]), "resend": past}


# --- the review round: a route or none is never answered for the card; a distance from now never takes the card's day; the name of another event ---------------------


NOT_FOR_THE_CARD = ["lista o email do João", "resume o texto do contrato", "traduz o texto para inglês", "me manda o evento de ontem", "o card de ontem foi aprovado?"]      # validate: allow english-only -- lines under test


@pytest.mark.parametrize("answer", ['{"v": 1, "kind": "route"}', '{"v": 1, "kind": "none"}'])
@pytest.mark.parametrize("line", NOT_FOR_THE_CARD)
def test_a_line_the_interpreter_answers_with_a_route_or_none_goes_on_to_its_own_path_and_the_card_is_not_touched(world, monkeypatch, answer, line):
    build(world, monkeypatch, answer)
    old, sha = haircut_card(world)
    assert revise(world, old, sha, line) == {"pass": True}
    assert open_cards(world) == [old] and status(world, old) == "open"


@pytest.mark.parametrize("shape", ["invalid-json", "empty-object", "event-change-relative"])
@pytest.mark.parametrize("line", ["muda para daqui 2 horas", "muda para em 30 minutos", "muda para in 2 hours", "muda para dentro de uma hora"])      # validate: allow english-only -- lines under test
def test_a_distance_from_now_never_takes_the_day_of_the_card_and_is_asked(world, monkeypatch, shape, line):
    answers = dict(SHAPES, **{"event-change-relative": op_text("event-change", {"time": line[len("muda para "):]}, time_iso="2026-10-21T17:00", weekday="wed")})
    build(world, monkeypatch, answers[shape])
    old, sha = haircut_card(world)      # Fri 23/10 14:00-15:00, now Wed 21/10 15:00
    got = revise(world, old, sha, line)
    assert got["resend"] == old and got["say"] and open_cards(world) == [old] and status(world, old) == "open"
    assert "14:00-15:00" in " ".join(body(world, old)), "the card is as it was"


@pytest.mark.parametrize("shape", ["invalid-json", "empty-object"])
def test_the_fallback_from_the_line_refuses_a_question(world, monkeypatch, shape):
    build(world, monkeypatch, SHAPES[shape])
    old, sha = haircut_card(world)
    got = revise(world, old, sha, "muda para as 10h?")      # validate: allow english-only -- the Portuguese line under test
    assert got["resend"] == old and open_cards(world) == [old]
    assert revise(world, old, sha, MUDA)["resend"] != old, "vacuity: without the question mark the same line is a change"


def test_the_fallback_is_not_used_when_the_model_answered_a_route_or_none(world, monkeypatch):
    for answer in ('{"v": 1, "kind": "route"}', '{"v": 1, "kind": "none"}'):
        build(world, monkeypatch, answer)
        old, sha = haircut_card(world)
        got = revise(world, old, sha, MUDA)      # a private line the model routes is asked again, as any line is: the fallback of the card does not read it
        assert (got == {"pass": True} or got["resend"] == old) and "Pronto" not in str(got.get("say")) and open_cards(world) == [old]
        ops_interpret.forget_all()
        ops_card_revise.forget_all()
        ops.reject(world["path"], old, channel="terminal")


def test_a_word_that_is_a_verb_of_the_gate_in_the_name_of_another_event_still_counts_as_a_name():
    doc = {"event": {"title": "evento social"}, "before": None}
    assert event_revise.names_another("muda o sign day para as 10h", {"time": "as 10h"}, doc) is True      # validate: allow english-only -- the Portuguese line under test
    assert event_revise.names_another("muda o evento social para as 10h", {"time": "as 10h"}, doc) is False      # validate: allow english-only -- the Portuguese line under test

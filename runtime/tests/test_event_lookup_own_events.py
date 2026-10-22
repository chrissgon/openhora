"""An event the platform itself created, found with no calendar source; and an event slot the model got wrong (slice S16, runtime/event_lookup.py, runtime/event_created.py, runtime/ops_interpret.py).

The live cases (2026-10-22, a pt-BR project whose accounts were Google and Microsoft but that had no calendar source): after the platform created a haircut through an approved card,
"Remova o corte de cabelo de amanha da agenda" was answered with the interpreter's ask-again sentence and, naming the Outlook agenda, with "no calendar of yours is a source of this project". Here the real family path, the real cards and the real ledger of approved cards (test_calendar_write.py's world, the stand-in Google and Graph services), a stand-in
clock (Wednesday 2026-10-21 15:00 at -03:00) and a model that is stood in: the texts below are what a model may plausibly answer for the line, each checked by the real `check`. Every expectation is a
literal of this file, the events and the sentences included; each oracle reads the card's own lines, the provider's recorded requests or the sentence, never the code under test, and the vacuity
tests plant a wrong result to show the oracle can fail. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_event_lookup_own_events.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_calendar_write import EVENTS, approve, create, fgc, fgw, rows, world  # noqa: F401  (the calendar world and its stand-in providers)
from test_event_lookup import ALLOWED, CANCEL, LIVE, OWNER, PROFILES, IDS, TALKER, ZONE, carry, op_text
from test_ops_natural_writes import forget  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
ops_natural = st.load("ops_natural")
event_lookup = st.load("event_lookup")
event_created = st.load("event_created")
interpreter_route = st.load("interpreter_route")

TITLE = "corte de cabelo"
CARD_2 = "O card #2 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test
NO_SOURCE = ("Não encontrei esse evento. Nenhuma agenda sua foi adicionada a este projeto ainda, então só consigo achar os eventos que eu mesmo criei aqui. "      # validate: allow english-only -- the Portuguese line or sentence under test
             "Adicione a sua agenda para achar os outros.")      # validate: allow english-only -- the Portuguese line or sentence under test
LIVE_ACCENTED = "Remova o corte de cabelo de amanhã da agenda"      # validate: allow english-only -- the Portuguese line or sentence under test, as the maintainer typed it
ASK_AGAIN = "Não tive certeza do que você quis dizer, então não fiz nada. Pode dizer de outro jeito?"      # validate: allow english-only -- the Portuguese line or sentence under test
NOT_READABLE = ("As mensagens e os eventos são numerados num retrato da sua caixa de e-mail ou agenda, e este canal não pode ler: peça na página da plataforma, "      # validate: allow english-only -- the Portuguese line or sentence under test
                "ou configure no projeto o grupo ask-mail para você.")      # validate: allow english-only -- the Portuguese line or sentence under test      # validate: allow english-only -- the Portuguese line or sentence under test


@pytest.fixture(autouse=True)
def fresh():
    event_lookup.forget_lists()
    ops_interpret.forget_all()
    yield
    event_lookup.forget_lists()


def build(world, monkeypatch):
    """The language, the two listed senders (the owner may read the calendar, the talker may not) and the clock. No calendar source is registered: the project has accounts only."""
    path = world["path"] + "/docs/workbench/runtime.json"
    raw = json.loads(open(path).read())
    raw.update(language="pt-BR", policies=PROFILES, channels={"page": ["read", "calendar-write"]},
               messaging={"senders": {"telegram": [{"id": IDS[name], "policy": name} for name in PROFILES]}})
    open(path, "w").write(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])
    world["clock"] = Clock(monkeypatch, wall="2026-10-21 15:00")
    monkeypatch.setattr(ops_interpret, "_zone", lambda now: ZONE)
    return world


def made(world, title=TITLE, start="2026-10-22T13:00", account="google", **more):
    """An event the platform created: the card is prepared and approved (by the terminal), so the ledger holds it. Returns the card's number."""
    started = create(world, account=account, title=title, start=start, **more)
    approve(world, started)
    return started["pending"]


class Model:
    """The daily route, stood in: it answers the queued texts and counts the calls."""

    def __init__(self, monkeypatch, *texts):
        self.texts, self.calls = list(texts), 0
        monkeypatch.setattr(interpreter_route, "complete", self.complete)

    def complete(self, route_id, system, user, **kw):
        self.calls += 1
        return {"ok": True, "text": self.texts.pop(0), "finish": "stop", "usage": {}, "latency_ms": 5, "upstream": "deepinfra"}


def say(world, line, sender=OWNER):
    return ops.say(world["path"], line, channel="messaging", sender=sender)["reply"]


def pending(world, n):
    return ops.pending(world["path"], n)


def writes(world):
    """The requests a stand-in service got that are not reads (the token exchange is no write)."""
    return [r for service in ("google", "graph") for r in world[service].requests if r["method"] != "GET" and not r["path"].endswith("/token")]


def event_reads(world, event_id):
    return [r for r in world["google"].requests if r["method"] == "GET" and r["path"] == f"{EVENTS}/{event_id}"]


def card_problems(item, event, title, when, account):
    """What is wrong with a removal card, read from its own lines."""
    lines = item["body"].splitlines()
    wanted = [f"Event: {event}", f"Removing, title: {title}", f"When: {when} (America/Sao_Paulo)", f"Account: {account}"]
    return [w for w in wanted if w not in lines]


def cards(world):
    return [p["id"] for p in ops_core.context(world["path"])["store"].pending_list(ops_core.context(world["path"])["conn"], "all")]


GOOGLE = "google (pat@example.com)"
HAIR_22 = ("ev0001", TITLE, "Thu 22/10/2026 13:00-14:00", GOOGLE)
HAIR_23 = ("ev0002", TITLE, "Fri 23/10/2026 13:00-14:00", GOOGLE)


# --- the cause of the live ask-again, with the model's plausible answers -----------------------------------------------------------------------------------


MODEL_TEXTS = {
    "no slots": CANCEL,
    "the event's name in the number slot": op_text("event-cancel", {"event": TITLE}),
    "the day in the number slot": op_text("event-cancel", {"event": "amanha"}),
    "a number the line does not hold": op_text("event-cancel", {"event": "2"}),
    "the title in a slot the removal does not have": op_text("event-cancel", {"title": TITLE}),
    "a time the removal does not have": op_text("event-cancel", {"time": "amanha"}, time_iso="2026-10-22T00:00", weekday="thu"),
    "the name and a title": op_text("event-cancel", {"event": TITLE, "title": TITLE}),
    "a clarification of the slot event": '{"v":1,"kind":"clarify","slot":"event"}',
}


@pytest.mark.parametrize("label", sorted(MODEL_TEXTS))
def test_every_plausible_answer_for_the_live_line_reaches_the_lookup_and_opens_the_card_of_the_one_event(world, monkeypatch, label):
    build(world, monkeypatch)
    made(world)
    model = Model(monkeypatch, MODEL_TEXTS[label])
    reply = say(world, LIVE)
    assert reply == CARD_2 and model.calls == 1, (label, reply)
    assert card_problems(pending(world, 2), *HAIR_22) == [], label
    assert reply != ASK_AGAIN


def test_the_strict_check_refuses_those_answers_so_the_lookup_is_what_changed(world, monkeypatch):
    """The cause: before this slice the check refused each of these texts as a whole, and the line got the ask-again sentence before any lookup."""
    build(world, monkeypatch)
    now = ops_natural._clock()
    got = {label: ops_interpret.decide(LIVE, text, now, ZONE, ALLOWED) for label, text in MODEL_TEXTS.items()}
    refused = {label: (d["kind"], d.get("error"), d.get("why"), d.get("slot")) for label, d in got.items() if d["kind"] != "op"}
    assert refused == {
        "the event's name in the number slot": ("clarify", "E_INT", "invalid", None),
        "the day in the number slot": ("clarify", "E_INT", "invalid", None),
        "a number the line does not hold": ("clarify", "E_INT", "invalid", None),
        "the title in a slot the removal does not have": ("clarify", "E_SLOT_UNKNOWN", "invalid", None),
        "a time the removal does not have": ("clarify", "E_SLOT_UNKNOWN", "invalid", None),
        "the name and a title": ("clarify", "E_SLOT_UNKNOWN", "invalid", None),
        "a clarification of the slot event": ("clarify", None, "model", "event"),
    }, "the pure check is the measured pipeline's own and is unchanged; `lenient` is the step after it"
    assert got["no slots"]["kind"] == "op", "control: a removal with no slot passes the strict check"


def test_an_answer_that_is_still_wrong_keeps_the_ask_again_and_says_why_in_the_log_without_the_line(world, monkeypatch, capsys):
    build(world, monkeypatch)
    made(world)
    cases = [("Sure! ZEBRA-MODEL-TEXT I will do it", "parse invalid"),
             (op_text("event-change", {"time": "zzz"}, time_iso="2026-10-22T15:00", weekday="thu"), "span not in the line"),
             (op_text("task", {"id": "x9"}), "slot not a number written in the line"),
             (op_text("event-change", {"calendar": "x"}), "slot the op does not have"),
             ('{"v":1,"kind":"clarify","slot":"to"}', "model asked for a slot"),
             ('{"v":1,"kind":"clarify","ops":["event-cancel","event-change"]}', "model asked between ops")]
    for text, why in cases:
        capsys.readouterr()
        Model(monkeypatch, text)
        assert say(world, LIVE) == ASK_AGAIN, text
        err = capsys.readouterr().err
        assert err.splitlines()[-1:] == [f"interpreter: ask-again ({why})"], (text, err)
        for secret in ("corte", "cabelo", "Remova", "amanh", "ZEBRA", "zzz", "x9", "pat@example.com"):
            assert secret not in err, (secret, err)
    assert event_lookup is not None and len(cards(world)) == 1, "no card was opened by any of them"


def test_the_log_oracle_fails_for_a_line_that_names_the_text(capsys):
    """Vacuity: the same check would see a leak."""
    print("interpreter: ask-again (parse invalid) corte de cabelo", file=__import__("sys").stderr)
    assert "cabelo" in capsys.readouterr().err


def test_an_invalid_slot_of_a_change_other_than_the_event_stays_refused(world, monkeypatch):
    build(world, monkeypatch)
    now = ops_natural._clock()
    line = "Muda o corte de cabelo para as 18h"
    bad = op_text("event-change", {"event": TITLE, "time": "zzz"}, time_iso="2026-10-21T18:00", weekday="wed")
    strict = ops_interpret.decide(line, bad, now, ZONE, ALLOWED)
    assert ops_interpret.lenient(line, bad, strict, now, ZONE, ALLOWED) is strict, "a time that is not a span of the line is still refused, with the event's name beside it or not"
    wrong_event = op_text("event-change", {"event": TITLE, "time": "as 18h"}, time_iso="2026-10-21T18:00", weekday="wed")
    strict = ops_interpret.decide(line, wrong_event, now, ZONE, ALLOWED)
    assert (strict["kind"], strict["error"]) == ("clarify", "E_INT")
    fixed = ops_interpret.lenient(line, wrong_event, strict, now, ZONE, ALLOWED)
    assert (fixed["kind"], fixed["op"], fixed["args"], fixed["time"]["local"]) == ("op", "event-change", {}, "2026-10-21T18:00")
    assert fixed["spans"] == {"time": "as 18h"}, "the event's name is dropped, the time the model read is kept"


def test_a_clarification_of_the_event_slot_follows_the_verb_of_the_line_and_the_policy(world, monkeypatch):
    build(world, monkeypatch)
    now = ops_natural._clock()
    text = '{"v":1,"kind":"clarify","slot":"event"}'
    for line, op in (("Remova o corte de cabelo de amanha da agenda", "event-cancel"), ("Cancele o corte de cabelo", "event-cancel"), ("Remarque o corte de cabelo", "event-change")):
        strict = ops_interpret.decide(line, text, now, ZONE, ALLOWED)
        assert ops_interpret.lenient(line, text, strict, now, ZONE, ALLOWED)["op"] == op, line
    line = "Qual evento de amanha"          # no verb: the model's question stands
    strict = ops_interpret.decide(line, text, now, ZONE, ALLOWED)
    assert ops_interpret.lenient(line, text, strict, now, ZONE, ALLOWED) is strict
    strict = ops_interpret.decide(LIVE, text, now, ZONE, ALLOWED - {"event-cancel"})
    assert ops_interpret.lenient(LIVE, text, strict, now, ZONE, ALLOWED - {"event-cancel"})["kind"] == "refuse_policy", "an operation the sender may not ask is refused, not opened"


# --- the events the platform created, with no calendar source -----------------------------------------------------------------------------------------------


def test_the_live_line_opens_the_cancel_card_of_the_event_the_platform_created_read_from_the_provider(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    world["google"].requests.clear()
    reply, extras = carry(world, LIVE, CANCEL)
    item = pending(world, 2)
    assert reply == CARD_2 and item["status"] == "open" and item["resolution"] is None, "the card waits for its approval: nothing is approved by this path"
    assert card_problems(item, *HAIR_22) == [], item["body"]
    assert len(event_reads(world, "ev0001")) >= 2, "the event is read live to be named, and again by the card's own preparation"
    assert writes(world) == [], "only reads"
    assert extras["stored"] == "(pedido para as suas contas)"      # validate: allow english-only -- the Portuguese line or sentence under test
    dump = json.dumps([pending(world, n) for n in (1, 2)], ensure_ascii=False)
    assert "Remova" not in dump and "amanha" not in dump.lower(), "no word of the line is stored"
    wrong = card_problems(item, "ev0002", TITLE, "Fri 23/10/2026 13:00-14:00", GOOGLE)
    assert wrong != [], "vacuity: the oracle sees another event"


def test_the_live_line_as_typed_with_its_accent_opens_the_same_card(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    model = Model(monkeypatch, MODEL_TEXTS["the event's name in the number slot"])
    assert say(world, LIVE_ACCENTED) == CARD_2 and model.calls == 1
    assert card_problems(pending(world, 2), *HAIR_22) == []


def test_a_removal_card_is_the_same_card_the_reference_created_opens(world, monkeypatch):
    build(world, monkeypatch)
    n = made(world)
    carry(world, LIVE, CANCEL)
    direct = ops.event_cancel(world["path"], "google", f"created:{n}", channel="messaging", sender=OWNER)
    assert pending(world, 2)["body"].splitlines()[1:] == pending(world, direct["pending"])["body"].splitlines()[1:]


def test_an_event_deleted_at_the_provider_is_not_named_and_no_card_opens(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    world["google"].events.pop("ev0001")
    world["google"].requests.clear()
    reply, extras = carry(world, LIVE, CANCEL)
    assert reply == NO_SOURCE and "resend" not in extras and cards(world) == [1], "deleted there: refused, no card"
    assert writes(world) == []


def test_an_event_moved_at_the_provider_is_not_named_either(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    world["google"].events["ev0001"]["start"] = {"dateTime": "2026-10-25T13:00:00-03:00"}
    world["google"].events["ev0001"]["end"] = {"dateTime": "2026-10-25T14:00:00-03:00"}
    reply, extras = carry(world, LIVE, CANCEL)
    assert reply == NO_SOURCE and cards(world) == [1]


def test_an_event_the_platform_removed_since_is_not_named(world, monkeypatch):
    build(world, monkeypatch)
    n = made(world)
    gone = ops.event_cancel(world["path"], "google", f"created:{n}")
    approve(world, gone)
    reply, extras = carry(world, LIVE, CANCEL)
    assert reply == NO_SOURCE and cards(world) == [1, 2]


def test_an_event_the_platform_did_not_create_is_not_found_and_the_person_is_told_what_is_searched(world, monkeypatch):
    build(world, monkeypatch)
    world["google"].add_event("evother", TITLE, {"dateTime": "2026-10-22T13:00:00-03:00"}, {"dateTime": "2026-10-22T14:00:00-03:00"})
    reply, extras = carry(world, LIVE, CANCEL)
    assert reply == NO_SOURCE and cards(world) == [] and writes(world) == []
    assert "/" not in reply and "ops " not in reply, "no command on a phone"


def test_two_created_events_with_the_title_are_listed_and_a_number_opens_the_card_of_that_one(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    made(world, start="2026-10-23T13:00")
    model = Model(monkeypatch)
    reply, extras = carry(world, "Cancela o corte de cabelo", CANCEL)
    assert reply == ("Mais de um evento combina. Qual deles você quer cancelar?\n"      # validate: allow english-only -- the Portuguese line or sentence under test
                     "1. Thu 22/10/2026 13:00-14:00 · corte de cabelo\n2. Fri 23/10/2026 13:00-14:00 · corte de cabelo\n"
                     "Diga, por exemplo: cancela o evento 1."), reply      # validate: allow english-only -- the Portuguese line or sentence under test
    assert "resend" not in extras and cards(world) == [1, 2]
    assert say(world, "cancela o 2") == "O card #3 espera a sua aprovação." and model.calls == 0      # validate: allow english-only -- the Portuguese line or sentence under test
    assert card_problems(pending(world, 3), *HAIR_23) == [], pending(world, 3)["body"]
    assert card_problems(pending(world, 3), *HAIR_22) != [], "vacuity: the card of the first one reads differently"
    assert pending(world, 3)["status"] == "open"


def test_a_day_named_in_the_line_chooses_among_the_created_events(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    made(world, start="2026-10-23T13:00")
    reply, _ = carry(world, "Cancela o corte de cabelo dia 23", CANCEL)
    assert reply == "O card #3 espera a sua aprovação." and card_problems(pending(world, 3), *HAIR_23) == []      # validate: allow english-only -- the Portuguese line or sentence under test


def test_the_account_a_line_names_narrows_the_search_to_the_events_created_there(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    made(world, start="2026-10-22T14:00", account="microsoft")
    reply, _ = carry(world, "Cancela o corte de cabelo de amanha", CANCEL)
    assert reply.startswith("Mais de um evento combina."), "control: with no account word both fit"      # validate: allow english-only -- the Portuguese line or sentence under test
    reply, _ = carry(world, "Cancela o corte de cabelo de amanha na agenda do google", CANCEL)
    assert reply == "O card #3 espera a sua aprovação." and card_problems(pending(world, 3), *HAIR_22) == [], reply      # validate: allow english-only -- the Portuguese line or sentence under test
    change = op_text("event-change", {"time": "as 18h"}, time_iso="2026-10-21T18:00", weekday="wed")
    reply, _ = carry(world, "Muda o corte de cabelo do outlook para as 18h", change)
    assert reply.endswith("O card #4 espera a sua aprovação."), reply      # validate: allow english-only -- the Portuguese line or sentence under test
    lines = pending(world, 4)["body"].splitlines()
    assert any(l.startswith("Account: microsoft (") for l in lines) and "Event: AAMkEvent0001=" in lines, lines
    assert "After: When: Wed 21/10/2026 18:00-19:00 (America/Sao_Paulo)" in lines, lines


def test_an_account_with_no_event_created_there_is_one_plain_sentence(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    reply, _ = carry(world, "Cancela o corte de cabelo de amanha na agenda do outlook", CANCEL)
    assert reply == NO_SOURCE and cards(world) == [1], "the Microsoft calendar has no event of the platform's, and no source: the same plain sentence"


def test_a_sender_who_may_not_read_the_calendar_is_told_so_and_nothing_is_named(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    world["google"].requests.clear()
    reply, extras = carry(world, LIVE, CANCEL, sender=TALKER)
    assert reply == NOT_READABLE and cards(world) == [1] and world["google"].requests == [], "no provider read for a sender with no right to read"


def test_the_title_must_be_whole_words_of_the_line_and_the_window_is_thirty_days(world, monkeypatch):
    build(world, monkeypatch)
    made(world, title="Yoga", start="2026-10-22T18:00")
    made(world, title="Dentist", start="2026-12-30T09:00")
    for line in ("Cancela o yogurt de amanha", "Cancela o dentista", "Cancela o Dentist"):
        reply, _ = carry(world, line, CANCEL)
        assert reply == NO_SOURCE, line
    assert cards(world) == [1, 2], "nothing was opened by any of them"
    reply, _ = carry(world, "Cancela o Yoga de amanha", CANCEL)
    assert reply == "O card #3 espera a sua aprovação."      # validate: allow english-only -- the Portuguese line or sentence under test


def test_the_ledger_read_returns_the_created_events_in_the_order_of_their_start_and_drops_the_removed(world, monkeypatch):
    build(world, monkeypatch)
    late = made(world, title="Late", start="2026-10-24T09:00")
    made(world, title="Early", start="2026-10-22T09:00")
    ctx = ops_core.context(world["path"])
    got = [(r["title"], r["start"], r["time"], r["account"], r["event_id"]) for r in event_created.created(ctx)]
    assert got == [("Early", "2026-10-22T09:00", "09:00-10:00", "google", "ev0002"), ("Late", "2026-10-24T09:00", "09:00-10:00", "google", "ev0001")]
    approve(world, ops.event_cancel(world["path"], "google", f"created:{late}"))
    got = [r["title"] for r in event_created.created(ops_core.context(world["path"]))]
    assert got == ["Early"]
    assert [r["title"] for r in event_created.created(ops_core.context(world["path"])) if r["title"] == "Late"] == [], "vacuity: the removed one is the one that went"


def test_a_change_the_platform_made_moves_the_event_in_the_ledger(world, monkeypatch):
    build(world, monkeypatch)
    n = made(world)
    moved = ops.event_change(world["path"], "google", f"created:{n}", start="2026-10-27T10:00")
    approve(world, moved)
    ctx = ops_core.context(world["path"])
    assert [(r["title"], r["start"], r["end"], r["pending"]) for r in event_created.created(ctx)] == [(TITLE, "2026-10-27T10:00", "2026-10-27T11:00", n)]
    reply, _ = carry(world, "Cancela o corte de cabelo dia 22", CANCEL)
    assert reply == NO_SOURCE, "it is no longer on the 22nd"
    reply, _ = carry(world, "Cancela o corte de cabelo dia 27", CANCEL)
    assert reply.endswith("espera a sua aprovação."), reply      # validate: allow english-only -- the Portuguese line or sentence under test


def test_nothing_in_this_path_approves_or_writes(world, monkeypatch):
    build(world, monkeypatch)
    made(world)
    world["google"].requests.clear()
    for line in (LIVE, "Cancela o corte de cabelo", "Cancela o corte de cabelo dia 25"):
        carry(world, line, CANCEL)
    assert writes(world) == []
    assert all(pending(world, n)["status"] != "resolved" for n in cards(world)[1:]), "every card this path opened is open"

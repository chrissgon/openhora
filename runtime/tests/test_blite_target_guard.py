"""A write is never opened with a guessed slot (B''-lite; limits L55, L61 of contracts/runtime.md).

The interpreter's model names an item to change, remove, answer or move by words it takes out of the person's line (`target`, `day`, `body`). The check (runtime/interpreter.py
`_check_slots`, `_check_op`) refuses every such span that is not a piece of the line as written, every number slot that is not a number written in it, and an `inherit` that has no
earlier line of the same operation to take from. Here the whole turn runs over the real operations layer with a stand-in model: a model object whose `target`, `day`, `body`, `title`
or number is NOT in the line, or whose `inherit` has nothing to inherit from, is a clarify, and the three ways a card is opened (`ops_natural_writes.open_line`,
`event_lookup.open_event`, `account_start.start`) record no call. Then 200 spans drawn at random (a fixed seed) from words that are not in the line. The vacuity test patches the
check to accept any span and the spies see a call. Every name is invented. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_blite_target_guard.py
"""
from __future__ import annotations

import datetime
import random
from zoneinfo import ZoneInfo

import pytest

import standin_tree as st
from test_ask import accept, write_config
from test_ops_interpret_dispatch import IX_PROFILES, IX_SENDERS, ZONE, op, phone, prepare
from test_ops_natural import world  # noqa: F401  (the real-operations world fixture)

account_start = st.load("account_start")
event_lookup = st.load("event_lookup")
interpreter = st.load("interpreter")
natural = st.load("natural")
ops_core = st.load("ops_core")
ops_interpret = st.load("ops_interpret")
phrases = st.load("phrases")

NOW = datetime.datetime(2026, 10, 18, 14, 0, tzinfo=ZoneInfo(ZONE))
OPS = ("event-cancel", "event-change", "mail-reply", "mail-archive")
ALLOWED = set(OPS)
LINES = {"event-cancel": "cancela o corte de cabelo de amanha",
         "event-change": "muda o corte de cabelo de amanha pra barbearia",      # validate: allow english-only -- the Portuguese line under test
         "mail-reply": "olha, aquele email da Carla, responde que assino",      # the verb is not at the start: the closed forms read a head at the start of a line only, so the interpreter gets it
         "mail-archive": "olha, aquele email da Carla de ontem, arquiva"}
GOOD = {"event-cancel": {"target": "corte de cabelo", "day": "de amanha"}, "event-change": {"target": "corte de cabelo", "day": "de amanha", "title": "barbearia"},
        "mail-reply": {"target": "email da Carla", "body": "assino"}, "mail-archive": {"target": "email da Carla", "day": "de ontem"}}
# a slot filled with words the line does not hold, by operation and slot: the span is not the person's
BAD = [(name, slot) for name, slots in GOOD.items() for slot in slots]
FRAME_LAST = {"op": "mail-reply", "words": {"target": "email da Carla"}, "age_s": 5}
VOCAB = ("dentista mercado fatura viagem aniversario reuniao projeto contrato escola farmacia padaria oficina cinema academia banco seguro mudanca cartorio hospital igreja "
         "futebol pizzaria livraria conserto encontro almoco jantar relatorio planilha orcamento entrega pedido boleto consulta vacina passaporte reserva hotel aviao").split()


class Spies:
    """Every way a card is opened after a decision: the family path, the event search, the account write."""

    def __init__(self, world, monkeypatch, text):
        self.calls, self.answer = [], {"text": text, "card": "CARD-REPLY"}
        prepare(world, monkeypatch, self.calls, self.answer)
        accept(world["path"], policies=dict(IX_PROFILES, owner=IX_PROFILES["owner"] + ["mail-send"]), messaging={"senders": IX_SENDERS})      # the owner may reply to mail: the policy is not what refuses
        self.events, self.starts = [], []
        monkeypatch.setattr(event_lookup, "open_event", lambda *a, **k: (self.events.append(a[2]), "EVENT-REPLY")[1])
        monkeypatch.setattr(account_start, "start", lambda *a, **k: (self.starts.append(a[1]), {"pending": 1})[1])
        self.world, self.cfg = world, ops_core.context(world["path"])["cfg"]

    def say(self, line):
        ops_interpret.forget_all()          # the rate limit counts the lines of a sender: each draw is a fresh minute
        return phone(self.world, line)["reply"]

    @property
    def opened(self):
        return [c for c in self.calls if "open_line" in c or "run" in c] + self.events + self.starts

    def unguessed(self, name, reply):
        """True when the model's refused object opened nothing, or opened only what the S16b rescue of an event opens: the line read by code with every slot the check
        refused left out (no target, no day, no number, no inherit in the decision), never a mail, never an account write."""
        if reply == phrases.text("IX_ASK_AGAIN", self.cfg):
            return self.opened == []
        rescued = name in ("event-cancel", "event-change") and len(self.events) == 1 and len(self.opened) == 1 and reply == "EVENT-REPLY"
        return rescued and self.events[0]["args"] == {} and self.events[0]["spans"] == {} and not self.events[0].get("inherited")


def model_text(name, slot, span, inherit=None):
    slots = {k: v for k, v in GOOD[name].items() if k != slot}
    if span is not None:
        slots[slot] = span
    return op(name, slots, **({"inherit": inherit} if inherit else {}))


def decide(line, text, frame=None):
    return ops_interpret.decide(line, text, NOW, ZONE, ALLOWED, frame)


def a_frame():
    return interpreter.typed_frame([], FRAME_LAST, {})


@pytest.mark.parametrize("name, slot", BAD)
def test_a_span_that_is_not_a_piece_of_the_line_is_a_clarify_and_no_card_is_opened(world, monkeypatch, name, slot):
    line, text = LINES[name], model_text(name, slot, "dentista na quarta")
    got = decide(line, text)
    assert got["kind"] == "clarify" and got["error"] == "E_SPAN" and got["why"] == "invalid", (name, slot)
    spies = Spies(world, monkeypatch, text)
    assert spies.unguessed(name, spies.say(line)), (name, slot)
    if name not in ("event-cancel", "event-change"):
        assert spies.opened == [], "only the rescue of an event (S16b) reads the line again, and only without the refused slots"


@pytest.mark.parametrize("name, slot", BAD)
def test_the_good_object_of_the_same_shape_is_believed_so_the_refusals_are_the_slot_and_nothing_else(name, slot):
    got = decide(LINES[name], op(name, GOOD[name]))
    assert got["kind"] == "op" and got["op"] == name and got["spans"] == GOOD[name], "the control: the same object with every span in the line passes the check"


@pytest.mark.parametrize("name", OPS)
def test_an_inherit_with_no_earlier_line_or_with_another_operations_is_refused(world, monkeypatch, name):
    line = LINES[name]
    text = op(name, {k: v for k, v in GOOD[name].items() if k != "target"}, inherit={"target": GOOD[name]["target"]})
    assert decide(line, text)["error"] == "E_INHERIT", "no frame: nothing to inherit from"
    other = decide(line, text, a_frame())
    assert other["kind"] == "clarify" and other["error"] == "E_INHERIT" and other["why"] == "invalid", "the last line was another operation's (or other words)"
    spies = Spies(world, monkeypatch, text)
    assert spies.unguessed(name, spies.say(line))


@pytest.mark.parametrize("name, slot, number", [("event-cancel", "event", "7"), ("event-change", "event", "7"), ("mail-reply", "message", "4"), ("mail-archive", "messages", "3,7")])
def test_a_number_the_line_does_not_write_is_never_the_item(world, monkeypatch, name, slot, number):
    line = LINES[name]
    text = op(name, {slot: number})
    got = decide(line, text)
    assert got["kind"] == "clarify" and got["error"] == "E_INT", (name, slot)
    spies = Spies(world, monkeypatch, text)
    assert spies.unguessed(name, spies.say(line))
    written = decide(line + f" {number.split(',')[0]}", op(name, {slot: number.split(",")[0]}))
    assert written["kind"] == "op" and written["spans"] == {slot: number.split(",")[0]}, "the control: a number written in the line is the item's exact form"


def test_two_hundred_spans_drawn_from_words_that_are_not_in_the_line_open_nothing(world, monkeypatch):
    rng = random.Random(20261024)
    spies = Spies(world, monkeypatch, "{}")
    for i in range(200):
        name = OPS[i % len(OPS)]
        slot = rng.choice(sorted(GOOD[name]))
        line = LINES[name]
        words = [w for w in rng.sample(VOCAB, 3) if w not in line.split()]
        span = " ".join(words[: rng.randint(1, 3)])
        assert span and span not in line
        text = model_text(name, slot, span)
        got = decide(line, text)
        assert got["kind"] == "clarify" and got["error"] == "E_SPAN", (name, slot, span)
        spies.calls.clear()
        spies.events.clear()
        spies.answer["text"] = text
        assert spies.unguessed(name, spies.say(line)), (name, slot, span)


@pytest.mark.parametrize("name", ["event-cancel", "mail-archive"])
def test_vacuity_a_check_that_accepts_any_span_lets_a_call_through(world, monkeypatch, name):
    text = model_text(name, "target", "dentista na quarta")
    assert decide(LINES[name], text)["error"] == "E_SPAN", "the real check refuses it"

    def accept_any(op_name, slots, line):          # the planted fault: no slot is checked against the line
        return {natural.NATURAL[op_name]["slots"][slot][1]: value for slot, value in slots.items()}, None

    spies = Spies(world, monkeypatch, text)
    monkeypatch.setattr(interpreter, "_check_slots", accept_any)
    assert decide(LINES[name], text)["kind"] == "op", "the plant accepts the span"
    spies.say(LINES[name])
    assert spies.opened != [] and not spies.unguessed(name, "CARD-REPLY"), f"vacuity: with the plant the oracle sees a call for {name}"


def test_a_believed_decision_reaches_its_path_the_words_for_a_message_the_number_for_an_exact_form_and_a_language_with_no_tables_keeps_its_sentence(world, monkeypatch):
    line = LINES["mail-archive"]
    spies = Spies(world, monkeypatch, op("mail-archive", GOOD["mail-archive"]))
    assert spies.say(line) == "CARD-REPLY"
    assert [c for c in spies.calls if "open_line" in c] == [{"open_line": True, "said": line, "channel": "messaging", "sender": spies.calls[-1]["sender"],
                                                             "seed": {"op": "mail-archive", "by": "target", "slots": {"words": ["carla"],
                                                                      "day_read": {"kind": "none", "value": None, "today": "2026-10-18", "zone": ZONE}}},
                                                             "hint": None}]
    # a number written in the line is the exact form: the call is the one of before B''-lite (the operation as the hint, no seed)
    numbered = "olha, aquele email da Carla, arquiva 3 e 7"
    spies.calls.clear()
    spies.answer["text"] = op("mail-archive", {"messages": "3,7", "target": "email da Carla"})
    assert spies.say(numbered) == "CARD-REPLY"
    assert [(c["seed"], c["hint"]) for c in spies.calls if "open_line" in c] == [(None, "mail-archive")]
    # a project in a language whose tables read no write form (es) never gets the words path: the call is the one of before B''-lite, and the real family says IX_WRITE_LANGUAGE
    write_config(world["path"], language="es")
    accept(world["path"], policies=dict(IX_PROFILES, owner=IX_PROFILES["owner"] + ["mail-send"]), messaging={"senders": IX_SENDERS})
    spies.calls.clear()
    spies.answer["text"] = op("mail-archive", GOOD["mail-archive"])
    spies.say(line)
    assert [(c["seed"], c["hint"]) for c in spies.calls if "open_line" in c] == [(None, "mail-archive")]

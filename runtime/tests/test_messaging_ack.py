"""One short acknowledgement when a reply takes time (slice S19; runtime/messaging_ack.py, runtime/line_stage.py, `Bridge.line`, `Bridge.write_now`, `Bridge.acknowledge`), over the
stand-in operations object and the stand-in messenger of test_messaging.py (its verb `send` records each message in sent.jsonl). Offline, no model, no network; every name is
invented, every expected sentence is a literal of this file (never read from the phrase table, so a wrong table fails here).

THE ORACLE counts and orders the messages of sent.jsonl, which the stand-in writes (the test's own count, never the bridge's). The vacuity cases plant what the rest reads: a slow
line over a short delay does get one acknowledgement before its reply (so a count of zero elsewhere means something), the order oracle flags a planted list that has the
acknowledgement after the reply, and a handle that is not stopped does send.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_ack.py
"""
from __future__ import annotations

import threading
import time

import pytest

import standin_tree as st
from test_messaging import SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

ack = st.load("messaging_ack")
line_stage = st.load("line_stage")
providers = st.load("messaging_provider")

REPLY = "Noted."
# the stage -> the sentence in pt-BR and in English, literal (the test's own list)
PT_BR = {
    "think": "Deixa eu ver...",
    "mail": "Vou ver seus e-mails...",
    "calendar": "Vou ver sua agenda...",
    "file": "Procurando o arquivo...",
    "compose": "Redigindo o e-mail...",
    "card": "Preparando o card...",
    "research": "Pesquisando...",
    "plan": "Vou trabalhar nisso...",
    None: "Um momento, estou vendo isso...",      # validate: allow english-only -- the pt-BR sentence under test
}
EN = {
    "think": "Let me see...",
    "mail": "Let me check your e-mails...",
    "calendar": "Let me check your calendar...",
    "file": "Looking for the file...",
    "compose": "Writing the e-mail...",
    "card": "Preparing the card...",
    "research": "Searching...",
    "plan": "I will work on that...",
    None: "One moment, I am looking into it...",
}
EVERY_ACK = set(PT_BR.values()) | set(EN.values())


def quick(monkeypatch, delay=0.3):
    monkeypatch.setattr(ack, "ACK_DELAY", delay)


def slow_say(world, seconds, stage=None, then=None):
    """A job that publishes `stage` as the operations layer would, works for `seconds` and answers; `then` is a second stage published half way."""
    def answer(project, **fields):
        if stage is not None:
            line_stage.publish(stage)
        time.sleep(seconds / 2)
        if then is not None:
            line_stage.publish(then)
        time.sleep(seconds / 2)
        return {"reply": REPLY, "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    world.fake.answers["say"] = answer


def acks_in(texts):
    return [t for t in texts if t in EVERY_ACK]


def ack_after_reply(texts):
    """The order oracle: True when an acknowledgement is listed after the reply."""
    return REPLY in texts and any(t in EVERY_ACK for t in texts[texts.index(REPLY):])


# --- the bridge: a slow line -----------------------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("stage", ["think", "mail", "calendar", "file", "compose", "card", "research", "plan", None])
def test_a_slow_line_gets_exactly_one_acknowledgement_of_its_stage_before_the_reply_in_portuguese(world, monkeypatch, stage):      # also the vacuity case
    quick(monkeypatch)
    world.config["language"] = "pt-BR"
    slow_say(world, 1.0, stage)
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    assert world.texts() == [PT_BR[stage], REPLY]
    time.sleep(0.4)
    assert world.texts() == [PT_BR[stage], REPLY]      # nothing else follows


def test_the_same_stages_are_said_in_english_when_the_project_speaks_english(world, monkeypatch):
    quick(monkeypatch)
    slow_say(world, 0.9, "mail")
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    assert world.texts() == [EN["mail"], REPLY]


def test_every_stage_of_the_closed_list_has_a_sentence_in_both_languages_and_the_list_is_the_one_the_test_knows(world):
    assert set(line_stage.STAGES) == {s for s in PT_BR if s is not None} == {s for s in EN if s is not None}      # a stage added without a sentence here fails
    phrases = st.load("phrases")
    for stage in line_stage.STAGES:
        assert phrases.text(ack.key(stage), {"language": "pt-BR"}) == PT_BR[stage] and phrases.text(ack.key(stage), {}) == EN[stage]
    assert ack.key(None) == "ACK_GENERIC" and ack.key("unknown") == "ACK_GENERIC" and ack.key("mail") == "ACK_MAIL"
    assert phrases.text("ACK_GENERIC", {"language": "pt-BR"}) == PT_BR[None] and phrases.text("ACK_GENERIC", {}) == EN[None]
    assert phrases.text("ACK_GENERIC", {"language": "de"}) == EN[None]      # a language with no table falls back to English as every phrase does


def test_the_stage_current_when_the_time_runs_out_is_the_one_said_and_a_later_stage_adds_nothing(world, monkeypatch):
    quick(monkeypatch)
    world.config["language"] = "pt-BR"

    def answer(project, **fields):
        line_stage.publish("think")
        time.sleep(0.1)
        line_stage.publish("mail")      # replaces the first before the time runs out
        time.sleep(0.6)
        line_stage.publish("file")      # after the acknowledgement went out: it changes nothing
        time.sleep(0.5)
        return {"reply": REPLY, "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    world.fake.answers["say"] = answer
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    assert world.texts() == [PT_BR["mail"], REPLY]


def test_a_very_slow_line_still_gets_one_acknowledgement_only(world, monkeypatch):
    quick(monkeypatch, 0.2)
    slow_say(world, 1.6, "plan")
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    assert world.texts() == [EN["plan"], REPLY]


# --- the bridge: what gets none --------------------------------------------------------------------------------------------------------------------------


def test_a_line_answered_within_the_delay_gets_none(world, monkeypatch):
    quick(monkeypatch, 0.5)
    slow_say(world, 0.1, "mail")
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    time.sleep(0.9)      # well past the delay
    assert world.texts() == [REPLY]


@pytest.mark.parametrize("line", ["/new tell me about the shop", "  /status", "aprovo", "Sim", "Aprovo o 2", "no"])
def test_a_slash_command_and_an_approval_word_get_none_whatever_the_stage(world, monkeypatch, line):
    quick(monkeypatch)
    slow_say(world, 1.0, "mail")
    world.say(line)
    assert wait_for(lambda: len(world.texts()) >= 1, 10)
    time.sleep(1.3)
    assert acks_in(world.texts()) == []      # whatever else the bridge said to this line, no acknowledgement


def test_the_acknowledgement_never_comes_after_the_reply(world, monkeypatch):
    quick(monkeypatch, 0.5)
    slow_say(world, 0.3, "mail")      # the reply is ready before the time runs out
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    time.sleep(1.0)
    assert world.texts() == [REPLY]
    quick(monkeypatch, 0.2)
    slow_say(world, 0.9, "mail")      # and when it is sent, it is the first message
    world.say("tell me about the shop again")
    assert wait_for(lambda: world.texts().count(REPLY) == 2, 10)
    time.sleep(0.5)
    texts = world.texts()
    assert texts == [REPLY, EN["mail"], REPLY] and not ack_after_reply(texts[1:])


def test_the_order_oracle_flags_an_acknowledgement_after_the_reply():      # vacuity
    assert ack_after_reply([REPLY, EN["mail"]]) is True
    assert ack_after_reply([EN["mail"], REPLY]) is False
    assert ack_after_reply([REPLY]) is False


def test_a_failing_acknowledgement_send_changes_nothing_of_the_reply(world, monkeypatch):
    quick(monkeypatch)
    slow_say(world, 0.9, "mail")
    real = world.bridge.messenger.send
    tried = []

    def send(chat, message):
        if message.get("text") in EVERY_ACK:
            tried.append(message["text"])
            raise providers.MessengerError("refused", "the platform said no")
        return real(chat, message)
    monkeypatch.setattr(world.bridge.messenger, "send", send)
    world.say("tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    assert tried == [EN["mail"]] and world.texts() == [REPLY] and world.log == []      # it was tried, the reply went out, nothing was logged


def test_the_reply_does_not_wait_for_an_acknowledgement_send_that_is_in_flight(world, monkeypatch):
    quick(monkeypatch, 0.2)
    slow_say(world, 0.6, "mail")
    real = world.bridge.messenger.send
    release, started = threading.Event(), threading.Event()

    def send(chat, message):
        if message.get("text") in EVERY_ACK:
            started.set()
            release.wait(5)
        return real(chat, message)
    monkeypatch.setattr(world.bridge.messenger, "send", send)
    world.say("tell me about the shop")
    assert started.wait(10)
    assert wait_for(lambda: REPLY in world.texts(), 10)      # the reply went out while the acknowledgement was still being sent
    release.set()
    assert wait_for(lambda: len(world.texts()) == 2, 10)


# --- a write: the card of a write may wait for a read or for the model --------------------------------------------------------------------------------------


def test_a_slow_write_gets_one_acknowledgement_of_its_stage_before_its_card_sentence(world, monkeypatch):
    quick(monkeypatch)
    world.config["language"] = "pt-BR"

    def natural_write(project, text, **fields):
        line_stage.publish("card")
        time.sleep(0.1)
        line_stage.publish("compose")      # the later stage is the one current when the time runs out
        time.sleep(0.7)
        return {"reply": "Card ready.", "resend": None}
    world.fake.natural_write = natural_write
    world.bridge.write_now(world.projects[0], SENDER, "write to the clinic")      # the stand-in has no card to send: the sentence only
    assert world.texts() == [PT_BR["compose"], "Card ready."]


def test_a_write_that_turns_out_to_be_a_plain_line_is_acknowledged_once(world, monkeypatch):
    quick(monkeypatch)

    def natural_write(project, text, **fields):
        time.sleep(0.6)
        return {"reply": None}
    world.fake.natural_write = natural_write
    slow_say(world, 0.8, "plan")      # the same line then goes to the job of a plain line, which is slow too
    world.bridge.write_now(world.projects[0], SENDER, "tell me about the shop")
    assert wait_for(lambda: REPLY in world.texts(), 10)
    time.sleep(0.4)
    assert world.texts() == [EN[None], REPLY]


def test_a_write_answered_within_the_delay_gets_none(world, monkeypatch):
    quick(monkeypatch, 0.5)
    world.fake.natural_write = lambda project, text, **fields: {"reply": "Card ready.", "resend": None}
    world.bridge.write_now(world.projects[0], SENDER, "write to the clinic")
    time.sleep(0.9)
    assert world.texts() == ["Card ready."]


# --- the helper over a fake send (no subprocess) -----------------------------------------------------------------------------------------------------------


class Sink:
    def __init__(self, fail=False, block=None):
        self.calls, self.fail, self.block = [], fail, block

    def __call__(self, chat, stage):
        self.calls.append((chat, stage))
        if self.block is not None:
            self.block.wait(5)
        if self.fail:
            raise RuntimeError("boom")


def test_an_unstopped_handle_sends_once_with_the_stage_it_reached_and_a_stopped_one_never_does():      # also a vacuity case
    sink = Sink()
    handle = ack.Ack(sink, delay=0.1).begin("1", "hello")
    line_stage.publish("file")
    assert wait_for(lambda: len(sink.calls) == 1, 5)
    time.sleep(0.4)
    assert sink.calls == [("1", "file")]      # once, with the stage published from the thread that began it
    handle.stop()
    stopped = Sink()
    early = ack.Ack(stopped, delay=0.3).begin("1", "hello")
    early.stop()
    early.stop()      # idempotent
    time.sleep(0.6)
    assert stopped.calls == []


def test_a_line_that_publishes_nothing_is_acknowledged_with_no_stage():
    sink = Sink()
    handle = ack.Ack(sink, delay=0.05).begin("1", "hello")
    assert wait_for(lambda: sink.calls == [("1", None)], 5)
    handle.stop()


def test_stop_does_not_wait_for_a_send_in_flight_and_nothing_starts_after_it():
    release = threading.Event()
    sink = Sink(block=release)
    handle = ack.Ack(sink, delay=0.05).begin("1", "hello")
    assert wait_for(lambda: len(sink.calls) == 1, 5)
    began = time.monotonic()
    handle.stop()
    assert time.monotonic() - began < 0.5      # it did not join the send that is still running
    release.set()
    time.sleep(0.3)
    assert len(sink.calls) == 1


def test_a_failing_send_is_ignored():
    sink = Sink(fail=True)
    handle = ack.Ack(sink, delay=0.05).begin("1", "hello")
    assert wait_for(lambda: len(sink.calls) == 1, 5)
    handle.stop()


def test_wanted_reads_the_line_alone():
    asker = ack.Ack(Sink())
    for line in ("hello", "tell me about the shop", "pesquise a previsao para amanha"):
        assert asker.wanted(line) is True
    for line in ("/ask hello", "  /status", "", "   ", None, "aprovo", "Sim", "yes", "no", "rejeito", "aprovo o 2"):
        assert asker.wanted(line) is False
    threads = threading.active_count()
    ack.Ack(Sink()).begin("1", "/ask x").stop()
    ack.Ack(Sink()).begin("1", "aprovo").stop()
    assert threading.active_count() == threads      # a command and a word start no thread

"""A running search is stopped by its asker's stop word on the messaging bridge, and the research acknowledgement names that word (package BL2b, limits L41, L64 and L65; runtime/messaging_turn.py
the kind `research-run` of the frame, runtime/phrases.py `ACK_RESEARCH`).

The real bridge over the real operations layer, a stand-in messenger, a stand-in model, a stand-in clock, and a stand-in search that blocks until it is stopped (test_research.py's `FakeRun`); the search
is asked in words, answered "sim" to the question "Shall I go ahead?" (a search always asks), and stopped with "pare". The stop word is read AFTER the card words (the kind `decision-card-word`) and BEFORE the change of a
card, so "nao" with a decision card as the last message still rejects the card (L64), and only the asker's own run is touched (the operations layer checks the key). Every count is the test's own
literal; wording is by phrase key. The vacuity cases plant the brake before the card words and a stop that ignores whose run it is. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_research_brake.py
"""
from __future__ import annotations

import threading
import time

import pytest

import standin_tree as st
from plan_bridge_kit import build, finish, wait_for
from test_ask import accept
from test_research import (ASKER, ASKER_KEY, LINE_1, RESEARCH_PROFILES, RESEARCH_SENDERS, FakeRun, lab, ops, ops_interpret, ops_research, research, world)  # noqa: F401
from test_service import WAIT
from test_messaging import SENDER, world as card_world  # noqa: F401  (the stand-in bridge world of test_messaging.py, under another name: this module's `world` is the real one)
from test_messaging_card_words import GRANTED, decided, plan
from closed_heads import words_interpreted  # noqa: F401  (S41-11: the line "mostra minha agenda" that asks the plan question is read by the interpreter's stand-in)

pytestmark = pytest.mark.usefixtures("words_interpreted")

ack = st.load("messaging_ack")
bridge = st.load("messaging_bridge")
turn_order = st.load("turn_order")
natural = st.load("natural")
phrases = st.load("phrases")
plan_confirm = st.load("plan_confirm")

HELD = 120.0      # how long a held search waits to be released, and how long a test waits for it to begin: bounds against a hung test, never a timing of the scenario (the stop releases it)
SENDER_KEY = "telegram:" + SENDER
OTHER = "55119000000033"
OTHER_KEY = f"telegram:{OTHER}"
CFG = {"language": "pt-BR"}
PROFILES = dict(RESEARCH_PROFILES, researcher=[*RESEARCH_PROFILES["researcher"], "approve-plans", "reject-cancel"], second=["read", "talk", "interpret", "research"])
SENDERS = {"telegram": [*RESEARCH_SENDERS["telegram"], {"id": OTHER, "policy": "second"}]}


def t(key, **fields):
    return phrases.text(key, CFG, **fields)


class Search:
    """The search in progress: `started` is set when the stand-in run begins, `release` ends it (a stop does, as `lab.stop_runs` ends the lab's runs)."""

    def __init__(self, monkeypatch):
        self.started, self.release, self.stops, self.monkeypatch = threading.Event(), threading.Event(), [], monkeypatch
        real = ops.research_stop

        def stop(project, sender):
            found = real(project, sender)
            self.stops.append((sender, found))
            return found
        monkeypatch.setattr(ops, "research_stop", stop)

    def ack_soon(self):
        """From here a line that runs longer than 0.2 s sends the research acknowledgement (the word that stops the search). The fixture sets it off (3600 s) while the question is asked: on a loaded
        machine the line that asks the question outlasted 0.2 s, its acknowledgement send began, and it reached the chat AFTER the question, which was then not the last message, so the yes was
        answered "to confirm, reply yes" and no search began (FLAKY-RESEARCH-PRESTATE-2 found the same in the entry kit). The yes is the line the acknowledgement is for."""
        self.monkeypatch.setattr(ack, "ACK_DELAY", 0.2)

    def arm(self):
        """From here the stand-in run blocks until it is stopped (a router's run made before this is made by the stand-in of the world)."""
        started, release = self.started, self.release

        class Run(FakeRun):
            def __call__(self, *args, **kwargs):
                started.set()
                release.wait(HELD)      # a deadline: no wait of a test is unbounded; the bound of WAIT was reached on a loaded machine and the search answered before the stop
                return super().__call__(*args, **kwargs)

        self.monkeypatch.setattr(lab, "run_skill", Run())
        self.monkeypatch.setattr(lab, "stop_runs", lambda *a, **k: release.set())


@pytest.fixture
def brig(research, tmp_path, monkeypatch):
    """The research world with three listed senders (the asker, one with no search, one with a search of their own) and the bridge for it."""
    accept(research["path"], policies=PROFILES, messaging={"senders": SENDERS}, language="pt-BR")
    ops_interpret.forget_all()
    monkeypatch.setattr(ack, "ACK_DELAY", 3600.0)      # no line is acknowledged until the test says so (`Search.ack_soon`, before the yes that starts the search)
    b = build(research, tmp_path, monkeypatch)
    b.search = Search(monkeypatch)
    yield b
    b.search.release.set()
    finish(b)


def start_search(b):
    """The asker asks for a search in words, says "sim" to the question, and the stand-in search begins; the acknowledgement that names the stop word is sent after ACK_DELAY."""
    b.search.arm()
    b.ask(LINE_1, sender=ASKER)
    b.search.ack_soon()
    b.say("sim", sender=ASKER)
    assert b.search.started.wait(HELD), "the search began after the OK"
    assert wait_for(lambda: t("ACK_RESEARCH") in b.texts(ASKER)), "the acknowledgement was sent"


def stand_in_calls(b, monkeypatch):
    """The calls of `ops.say` the bridge makes for a line (the test's own count of what reached the conversation)."""
    seen = []
    real = ops.say

    def spy(project, text, **kwargs):
        seen.append(text)
        return real(project, text, **kwargs)
    monkeypatch.setattr(ops, "say", spy)
    return seen


# --- the kit: a yes after the question is answered only once the job that sent the question has ended ---------------------------------------------------


def slow_to_end(monkeypatch, seconds=0.5):
    """The job that sends a question ends `seconds` after the question is bound: a loaded machine, made deterministic."""
    import time
    real = bridge.Bridge.ask_plan

    def slow(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        time.sleep(seconds)
        return result
    monkeypatch.setattr(bridge.Bridge, "ask_plan", slow)


def test_a_yes_that_follows_the_kit_ask_starts_the_search_even_when_the_job_that_sent_the_question_is_slow_to_end(brig, monkeypatch):
    slow_to_end(monkeypatch)
    brig.search.arm()
    brig.ask(LINE_1, sender=ASKER)
    brig.say("sim", sender=ASKER)
    assert brig.search.started.wait(HELD), "the search began after the OK"
    assert t("STILL_WORKING") not in brig.texts(ASKER)


def test_a_yes_sent_the_moment_the_question_is_bound_is_not_refused_as_still_working_when_the_line_was_decided_without_a_slot(brig, monkeypatch):
    """S41-11 (A11-2): the line of a sender the interpreter reads is decided in a job that takes no model slot, so a yes that comes while that job has not ended meets no busy project: the search begins."""
    slow_to_end(monkeypatch)
    brig.search.arm()
    brig.say(LINE_1, sender=ASKER)
    assert wait_for(lambda: brig.question_id(ASKER) is not None), "the question was bound"
    brig.say("sim", sender=ASKER)
    assert brig.search.started.wait(HELD), "the search began after the OK"
    assert t("STILL_WORKING") not in brig.texts(ASKER)


def test_vacuity_a_yes_sent_the_moment_the_question_is_bound_is_refused_as_still_working_and_no_search_begins(brig, monkeypatch):
    """The sensitivity of the test above: with the row `decide-without-slot` out of the table the line takes the project's slot as it did, and the yes sent as soon as the ledger holds the question
    (what `ask` did before it waited) meets the job that has not ended."""
    import closed_heads
    turn_order = st.load("turn_order")
    monkeypatch.setattr(turn_order, "names", lambda stage, real=turn_order.names: tuple(n for n in real(stage) if n != "decide-without-slot"))
    monkeypatch.setattr(bridge.Bridge, "handle", closed_heads.REAL_HANDLE[-1])      # the bridge is not waited for after a line: this test is about the moment
    slow_to_end(monkeypatch)
    brig.search.arm()
    brig.say(LINE_1, sender=ASKER)
    assert wait_for(lambda: brig.question_id(ASKER) is not None), "the question was bound"
    brig.say("sim", sender=ASKER)
    assert wait_for(lambda: t("STILL_WORKING") in brig.texts(ASKER)), "the yes met the job that had not ended"
    assert not brig.search.started.wait(1)


def slow_acknowledgement(monkeypatch):
    """A loaded machine, made deterministic: the call that answers the first line (the question's) takes 0.3 s, longer than a 0.2 s acknowledgement delay, and an acknowledgement takes 0.5 s to send."""
    real_run, real_ack, said = bridge.Bridge.run_op, bridge.Bridge.acknowledge, []

    def run_op(self, project, op, *args, **kwargs):
        if op == "say" and not said:
            said.append(True)
            time.sleep(0.3)
        return real_run(self, project, op, *args, **kwargs)

    def acknowledge(self, project, chat, stage):
        time.sleep(0.5)
        return real_ack(self, project, chat, stage)
    monkeypatch.setattr(bridge.Bridge, "run_op", run_op)
    monkeypatch.setattr(bridge.Bridge, "acknowledge", acknowledge)


def test_an_acknowledgement_that_is_slow_to_send_does_not_keep_the_yes_from_starting_the_search(brig, monkeypatch):
    """The line that asks the question is never acknowledged, so a slow line and a slow send cannot put an acknowledgement after the question: the yes is the question's answer, the search begins and
    names the stop word."""
    slow_acknowledgement(monkeypatch)
    start_search(brig)
    assert t("ACK_GENERIC") not in brig.texts(ASKER) and brig.texts(ASKER).count(t("ACK_RESEARCH")) == 1


def test_vacuity_an_acknowledgement_asked_for_before_the_question_lands_after_it_and_the_yes_starts_no_search(brig, monkeypatch):
    """The sensitivity of the test above: the same slowness with the acknowledgement delay of 0.2 s from the first line (what the fixture did) puts an acknowledgement in the chat after the question; the
    yes that comes after it (on a loaded machine, the person's reply always does) is not the answer to the last message, and no search begins."""
    slow_acknowledgement(monkeypatch)
    brig.search.arm()
    brig.search.ack_soon()
    brig.ask(LINE_1, sender=ASKER)
    assert wait_for(lambda: t("ACK_GENERIC") in brig.texts(ASKER)), "the acknowledgement of the slow line reached the chat after the question"
    brig.say("sim", sender=ASKER)
    assert not brig.search.started.wait(2), "the yes met an acknowledgement as the last message"


# --- the stop word -------------------------------------------------------------------------------------------------------------------------------


def test_a_stop_word_stops_the_askers_search_says_nothing_and_the_run_answers_that_it_was_stopped(brig):
    start_search(brig)
    sent = len(brig.sent())
    brig.say("pare", sender=ASKER)
    assert wait_for(lambda: brig.texts(ASKER)[-1] == t("RS_CANCELLED")), "the run answers when it ends"
    assert brig.search.stops == [(ASKER_KEY, True)], "the brake was asked once and stopped one run"
    assert brig.texts(ASKER)[sent:] == [t("RS_CANCELLED")], "the line itself said nothing: only the run's own sentence follows the acknowledgement"
    assert brig.idle() and brig.texts(ASKER)[-2:] == [t("ACK_RESEARCH"), t("RS_CANCELLED")]


def test_a_no_word_stops_it_too_and_the_stop_word_is_read_in_any_of_the_languages(brig):
    start_search(brig)
    brig.say("n\u00e3o", sender=ASKER)
    assert wait_for(lambda: brig.texts(ASKER)[-1] == t("RS_CANCELLED")) and brig.search.stops == [(ASKER_KEY, True)]


def test_the_stop_word_of_another_sender_stops_nothing(brig):
    start_search(brig)
    brig.say("pare", sender=OTHER)      # listed, holds the search, but it is not their run
    assert wait_for(lambda: brig.search.stops == [(OTHER_KEY, False)])
    assert not brig.search.release.is_set(), "the asker's run is still going"
    brig.search.release.set()
    assert wait_for(lambda: brig.texts(ASKER)[-1].startswith("Amanh")) and t("RS_CANCELLED") not in brig.texts(ASKER)


def test_a_stop_word_with_no_search_running_goes_on_to_the_conversation(brig, monkeypatch):
    seen = stand_in_calls(brig, monkeypatch)
    brig.say("pare", sender=ASKER)
    assert wait_for(lambda: seen == ["pare"]) and brig.search.stops == [(ASKER_KEY, False)]


def test_a_stop_word_replying_to_nothing_the_bridge_sent_does_not_stop_a_search_on_e_mail(brig):
    brig.caps(buttons=False, actions_need_reply=True)
    brig.search.arm()
    brig.ask(LINE_1, sender=ASKER)
    question = brig.question_id(ASKER)
    brig.search.ack_soon()
    brig.say("sim", sender=ASKER, reply_to=question)
    assert brig.search.started.wait(HELD) and wait_for(lambda: t("ACK_RESEARCH") in brig.texts(ASKER))
    brig.say("pare", sender=ASKER)      # not a reply
    brig.say("pare", sender=ASKER, reply_to="999999")      # a reply to a message this bridge never sent
    assert brig.search.stops == [] and not brig.search.release.is_set()
    shown = [s["message"]["text"] for s in brig.sent()]
    acknowledgement = str(100 + shown.index(t("ACK_RESEARCH")) + 1)      # the stand-in messenger numbers its messages from 101, in the order it was sent them
    brig.say("pare\n\n-- \nAna", sender=ASKER, reply_to=acknowledgement)      # a reply to the acknowledgement
    assert wait_for(lambda: t("RS_CANCELLED") in brig.texts(ASKER)) and brig.search.stops == [(ASKER_KEY, True)], "the reply to the acknowledgement stopped the run"


# --- the order: after the card words ---------------------------------------------------------------------------------------------------------


@pytest.fixture
def stand(card_world):
    """The stand-in bridge world of test_messaging.py (the decision cards the tick sends are its own), with a `research_stop` the test answers: `stand.stops` are the senders it was asked for."""
    w = card_world
    w.config["channels"]["messaging"] = GRANTED
    w.stops, w.running = [], [True]
    w.fake.research_stop = lambda project, sender: w.stops.append(sender) or w.running[0]
    w.items[1] = plan(1)
    w.bridge.tick()
    return w


def test_a_no_with_a_decision_card_as_the_last_message_rejects_the_card_and_leaves_the_search_alone(stand):
    stand.say("n\u00e3o")
    assert decided(stand) == ([], [1]) and stand.stops == [], "L64 first: the card was rejected, and the brake was never asked"


def test_the_same_no_with_no_card_as_the_last_message_goes_to_the_brake(stand):
    stand.items[1]["status"] = "resolved"      # nothing waits: no card to decide
    stand.say("n\u00e3o")
    assert stand.stops == [SENDER_KEY] and decided(stand) == ([], []) and stand.calls("say") == [], "the brake took it and said nothing"


def test_a_stop_word_with_no_search_running_goes_on_to_the_conversation(stand):
    stand.items[1]["status"] = "resolved"
    stand.running[0] = False
    stand.say("pare")
    assert wait_for(lambda: stand.calls("say")) and stand.stops == [SENDER_KEY] and stand.calls("say")[0][2]["text"] == "pare"


def test_the_brake_is_never_asked_for_a_slash_line_a_forwarded_line_or_a_line_that_is_no_stop_word(stand):
    stand.items[1]["status"] = "resolved"
    stand.say("/pare")
    stand.say("pare", forwarded=True)
    stand.say("pare a tarefa 3 e depois o resto")
    assert wait_for(lambda: len(stand.calls("say")) == 2) and stand.stops == [], "a command, a forwarded message and a longer line are never a stop word"


def test_vacuity_the_brake_placed_before_the_card_words_stops_the_search_and_leaves_the_card_open(stand, monkeypatch):
    order = list(turn_order.kinds())
    a, b = order.index("decision-card-word"), order.index("research-run")
    order[a], order[b] = order[b], order[a]
    monkeypatch.setattr(turn_order, "kinds", lambda: tuple(order))      # the brake placed before the card words
    stand.say("n\u00e3o")
    assert stand.stops == [SENDER_KEY] and decided(stand) == ([], []), "the same counters see the wrong order: the card stays open"


def test_vacuity_a_stop_that_ignores_whose_run_it_is_stops_the_askers_search_for_another_sender(brig, monkeypatch):
    start_search(brig)
    ctx_key = lambda sender: (st.load("ops_natural").project_key(brig.world["path"]), "messaging", sender)
    monkeypatch.setattr(ops_research, "_binding", lambda project, sender: ctx_key(ASKER_KEY))      # the planted fault: whoever asks reaches the one search
    brig.say("pare", sender=OTHER)
    assert wait_for(lambda: brig.search.stops == [(OTHER_KEY, True)]), "the assertion of the test of another sender can fail"


# --- the acknowledgement names the word ------------------------------------------------------------------------------------------------------


def quoted(sentence):
    """The word between the two single quotes of a sentence."""
    first = sentence.index("'")
    return sentence[first + 1:sentence.index("'", first + 1)]


@pytest.mark.parametrize("tag", ["pt-BR", "en", "es", "fr", "de", "it"])
def test_the_word_the_research_acknowledgement_names_is_in_the_stop_list_of_its_language(tag):
    shown = phrases.text("ACK_RESEARCH", {"language": tag})
    word = quoted(shown)
    lists = plan_confirm.STOP_WORDS
    assert natural.ascii_normal(word) in lists["pt-BR" if tag == "pt-BR" else tag] or (tag in ("es", "fr", "de", "it") and natural.ascii_normal(word) in lists[tag])
    assert plan_confirm.stop_form(word) is True, "the word, as the person types it, is a stop word"
    if tag not in ("pt-BR", "en"):
        assert shown == phrases.text("ACK_RESEARCH", {"language": "en"}) and natural.ascii_normal(word) in lists["en"], "es, fr, de and it get the English sentence, whose word is in the English list"


def test_the_acknowledgements_literal_words_are_pare_and_stop_and_the_sentences_are_the_makers_wording():
    # literal: the stop word the acknowledgement shows is in the closed list of stop words (the text is the limit)
    assert phrases.text("ACK_RESEARCH", {"language": "en"}) == "Searching... Send 'Stop' to cancel."
    assert phrases.text("ACK_RESEARCH", {"language": "pt-BR"}) == "Pesquisando... Digite 'Pare' para cancelar."


def test_vacuity_a_sentence_that_names_a_word_no_list_holds_is_noticed(monkeypatch):
    table = phrases.TABLE["en"]
    monkeypatch.setitem(table, "ACK_RESEARCH", "Searching... Send 'Halt' to cancel.")
    word = quoted(phrases.text("ACK_RESEARCH", {"language": "en"}))
    assert natural.ascii_normal(word) not in plan_confirm.STOP_WORDS["en"] and plan_confirm.stop_form(word) is False, "the check of the test above fails for 'Halt'"

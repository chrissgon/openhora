"""The research brake, operations side (package BL2a, runtime/ops_research.py `stop`): a web search that a messaging sender asked is stopped by THAT sender's stop word.

A stand-in run (the seam `lab.run_skill` of test_research.py) that blocks until it is stopped, as a run does; the search is started by a line in a thread and stopped from the test. Only the
operations side is here: the stop word itself is read by the messaging bridge under L64's conditions (the package that owns the bridge). Offline; invented names. The cancel is the real
cancel path (`ops_cancel.cancel_request`), wrapped to record the request it was asked to stop.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_research_brake.py
"""
from __future__ import annotations

import threading

import pytest

import standin_tree as st
from test_ask import accept
from test_research import (ASKER_KEY, LINE_1, PLAIN_KEY, RESEARCH_PROFILES, RESEARCH_SENDERS, FakeRun, lab, ops, ops_core, ops_research, phone, research, world)  # noqa: F401

ops_cancel = st.load("ops_cancel")
phrases = st.load("phrases")
pending_items = st.load("pending_items")
OTHER = "55119000000033"
OTHER_KEY = f"telegram:{OTHER}"


class Blocked:
    """The search in progress: `started` is set when the run begins, `release` ends it (a stop does, as `lab.stop_runs` ends the lab's runs)."""

    def __init__(self, research, monkeypatch):
        self.started, self.release, self.cancelled, self.reply = threading.Event(), threading.Event(), [], []
        started, release = self.started, self.release

        class Run(FakeRun):
            def __call__(self, *args, **kwargs):
                started.set()
                release.wait(20)      # a deadline: no wait of a test is unbounded
                return super().__call__(*args, **kwargs)

        monkeypatch.setattr(lab, "run_skill", Run())
        monkeypatch.setattr(lab, "stop_runs", lambda *a, **k: release.set())
        real = ops_cancel.cancel_request

        def cancel(ctx, request_id, **kwargs):
            self.cancelled.append((request_id, kwargs))
            return real(ctx, request_id, **kwargs)

        monkeypatch.setattr(ops_cancel, "cancel_request", cancel)
        self.world = research
        self.thread = threading.Thread(target=lambda: self.reply.append(phone(research, LINE_1, ASKER_KEY)), daemon=True)      # the question, then the sender's OK of it (D5): the search begins after the OK
        self.thread.start()
        assert self.started.wait(20), "the stand-in run began"

    def end(self):
        self.release.set()
        self.thread.join(30)
        assert not self.thread.is_alive()
        return self.reply[0]


def key(world, sender=ASKER_KEY):
    return (st.load("ops_natural").project_key(world["path"]), "messaging", sender)


def two_researchers(world):
    senders = {"telegram": [*RESEARCH_SENDERS["telegram"], {"id": OTHER, "policy": "second"}]}      # a profile of its own: a profile with `ask-mail` belongs to one sender
    accept(world["path"], policies=dict(RESEARCH_PROFILES, second=["read", "talk", "interpret", "research"]), messaging={"senders": senders}, language="pt-BR")


def test_the_senders_own_search_is_cancelled_by_their_stop_and_its_reply_says_it_was_stopped(research, monkeypatch):
    run = Blocked(research, monkeypatch)
    item = pending_items.find(key(research), "research-run")
    assert item is not None and set(item["state"]) == {"request_id"}, "the record holds the request id and nothing of the question"
    assert ops_research.stop(research["path"], ASKER_KEY) is True
    assert [id_ for id_, _ in run.cancelled] == [item["state"]["request_id"]]
    cfg = ops_core.context(research["path"])["cfg"]
    assert run.end() == phrases.text("RS_CANCELLED", cfg)
    assert pending_items.find(key(research), "research-run") is None, "the record goes with the run"
    ctx = ops_core.context(research["path"])
    label = ctx["store"].task_get(ctx["conn"], item["state"]["request_id"])["stop_requested_by"]
    assert label == "user from messaging, profile researcher" and ASKER_KEY not in label, "the label carries the sender's profile as R18's does, never the sender"


def test_a_search_cancelled_by_any_other_path_keeps_its_own_sentence(research, monkeypatch):
    """RS_CANCELLED says "as you asked": it is the reply only to a stop that came through `stop`; a cancel from the page, the terminal or the board gets ASK_CANCELLED as before."""
    run = Blocked(research, monkeypatch)
    item = pending_items.find(key(research), "research-run")
    ctx = ops_core.context(research["path"])
    ops_cancel.cancel_request(ctx, item["state"]["request_id"], by="user", channel="page")
    cfg = ctx["cfg"]
    reply = run.end()
    assert reply == phrases.text("ASK_CANCELLED", cfg) and reply != phrases.text("RS_CANCELLED", cfg)


def test_the_stop_of_another_sender_cancels_nothing_and_the_search_goes_on(research, monkeypatch):
    two_researchers(research)
    run = Blocked(research, monkeypatch)
    assert ops_research.stop(research["path"], OTHER_KEY) is False and run.cancelled == []
    assert run.end().startswith("Amanhã em São Paulo")  # validate: allow english-only -- the answer under test is Portuguese


def test_a_sender_without_the_group_research_stops_nothing_and_no_run_means_false(research, monkeypatch):
    assert ops_research.stop(research["path"], ASKER_KEY) is False, "no search is running"
    run = Blocked(research, monkeypatch)
    assert ops_research.stop(research["path"], PLAIN_KEY) is False and run.cancelled == []
    narrower = dict(RESEARCH_PROFILES, researcher=["read", "talk", "interpret"])      # the asker lost `research` while the search runs
    accept(research["path"], policies=narrower, messaging={"senders": RESEARCH_SENDERS}, language="pt-BR")
    assert ops_research.stop(research["path"], ASKER_KEY) is False and run.cancelled == []
    run.end()


def test_ops_exposes_the_brake_and_it_is_not_an_operation_of_the_table():
    assert ops.research_stop is ops_research.stop
    assert "research_stop" not in {row["call"] for row in st.load("operations").OPERATIONS}


def test_vacuity_a_stop_that_ignores_the_key_cancels_another_senders_search(research, monkeypatch):
    two_researchers(research)
    run = Blocked(research, monkeypatch)
    monkeypatch.setattr(ops_research, "_binding", lambda project, sender: key(research, ASKER_KEY))      # the planted fault: whoever asks reaches the one search
    assert ops_research.stop(research["path"], OTHER_KEY) is True and len(run.cancelled) == 1, "the assertion of the test above can fail"
    run.end()

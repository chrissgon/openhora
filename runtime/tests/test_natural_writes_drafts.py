"""The questions a write in words leaves open (package NR-5; runtime/ops_natural_writes.py, runtime/drafts.py owner `write`): one per channel and sender in the one store, ten
minutes, memory only, bound to the project, never logged and never written to a file; each question of the table of SPEC-NATURAL-WRITES 4 with the answers it takes; a reply
that fits nothing is asked once more, and any other line drops the question and is a new line. Over the real operations layer and the W1 stand-in writers (test_calendar_write.py's
world); no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_drafts.py
"""
from __future__ import annotations

import json
import os

import pytest

import standin_tree as st
from test_calendar_write import world  # noqa: F401  (the calendar world)
from test_ops_natural_writes import BLIND, GROUPS, OPEN, PLAIN, READER, SENDER, body, forget, phone, policy  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")
drafts = st.load("drafts")
phrases = st.load("phrases")

SENTINEL = "Zorbablax"


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


def live(sender=SENDER):
    return drafts.get("messaging", sender, "write")


def test_write_is_an_owner_of_the_one_store_and_a_draft_is_one_per_sender(world, clock):
    assert "write" in drafts.OWNERS
    policy(world)
    phone(world, "marca quinta às 10h no google")
    first = live()
    assert first["kind"] == "write" and first["need"] == "title" and first["op"] == "event-create" and drafts.count() == 1
    phone(world, "marca sexta às 15h no google")
    assert live()["slots"]["start"].startswith("2026-10-23") and drafts.count() == 1, "a new question replaces the old one"
    phone(world, "marca sábado às 15h no google", READER)
    assert drafts.count() == 2, "another sender has a question of their own"


def test_a_write_question_replaces_a_reminder_question_and_says_so_and_the_other_way_round(world, clock):
    policy(world)
    drafts.put("messaging", SENDER, {"need": "confirm", "how": "trigger", "line": "x", "text": "x", "readings": [], "project": "p"}, "remind")
    out = phone(world, "marca quinta às 10h no google")
    assert out["reply"].startswith("The previous question was discarded. ") and live() is not None
    drafts.put("messaging", SENDER, {"need": "confirm", "how": "trigger", "line": "y", "text": "y", "readings": [], "project": "p"}, "remind")
    assert live() is None, "the reminder's question took the slot"


def test_the_question_waits_ten_minutes_and_is_then_gone(world, clock, monkeypatch):
    policy(world)
    now = [1000.0]
    monkeypatch.setattr(drafts, "clock", lambda: now[0])
    phone(world, "marca quinta às 10h no google")
    now[0] += 599
    assert live() is not None
    now[0] += 2
    assert live() is None
    late = phone(world, "Dentista")
    assert late["reply"] is None or "waits for your approval" not in late["reply"], "a late answer is a plain line, never the title of an event"


def test_the_question_is_bound_to_the_project_it_was_asked_in(world, clock):
    policy(world)
    phone(world, "marca quinta às 10h no google")
    ctx = ops_core.context(world["path"])
    state = live()
    assert state["project"] == ops_natural.project_key(ctx["cfg"]["project"])
    state["project"] = "000000000000"
    assert ops_natural_writes.answers(ctx, state, "Dentista") is False


def test_the_words_of_a_question_are_never_written_to_a_file_the_store_the_log_or_the_conversation(world, clock, monkeypatch, caplog):
    policy(world)
    opened = []
    real_open = open

    def watching(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+") and SENTINEL in str(file):
            opened.append(file)
        return real_open(file, mode, *a, **k)
    monkeypatch.setattr("builtins.open", watching)
    asked = phone(world, f"cria um evento {SENTINEL} sexta no google")
    assert asked["asked"] and SENTINEL in live()["slots"]["title"]
    ops.say(world["path"], f"cria um evento {SENTINEL} sábado no google", channel="messaging", sender=SENDER)
    assert opened == [] and SENTINEL not in caplog.text
    ctx = ops_core.context(world["path"])
    stored = json.dumps([m["text"] for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)])
    assert SENTINEL not in stored and "(a request to your accounts)" in stored
    needle = SENTINEL.encode()
    leaks = [os.path.join(d, f) for d, _, fs in os.walk(world["tmp"]) for f in fs if f.endswith((".sqlite", ".json", ".log", ".jsonl", ".md", ".txt"))
             and needle in open(os.path.join(d, f), "rb").read()]
    assert leaks == [], "the words of a question leave memory with the question"


@pytest.mark.parametrize("answer, expected", [("1", "Google"), ("google", "Google"), ("2", "Microsoft"), ("outlook", None), ("Microsoft", "Microsoft")])
def test_the_account_question_takes_the_number_or_the_word_of_an_option_and_nothing_else(world, clock, answer, expected):
    policy(world)
    phone(world, "marca dentista quinta às 10h")
    out = phone(world, answer)
    if expected:
        assert f"Account: {expected.lower()}" in body(world, out)
    else:
        assert out["asked"] is True and out["reply"].startswith("Which account?") or "reply" in out


def test_a_short_reply_that_fits_nothing_is_asked_once_more_and_a_second_one_gives_the_question_up_in_a_sentence(world, clock):
    policy(world)
    phone(world, "marca dentista quinta às 10h")
    again = phone(world, "hmm")
    assert again["asked"] and again["reply"].startswith("Which account?") and live()["retries"] == 1
    dropped = phone(world, "talvez")
    assert dropped["reply"] == phrases.text("NW_GIVE_UP", None) and live() is None and not dropped["asked"], "given up in a plain sentence, nothing opened"
    assert phone(world, "hmm")["reply"] is None, "and the next short line is a plain line"


@pytest.mark.parametrize("word", ["não", "cancela", "no", "never mind", "deixa pra lá"])
def test_a_no_or_a_cancel_drops_the_question_and_nothing_is_opened(world, clock, spy, word):
    policy(world)
    phone(world, "marca dentista quinta às 10h")
    out = phone(world, word)
    assert out["reply"] == "Nothing was opened." and live() is None and spy == []


def test_a_line_that_is_a_new_request_drops_the_question_and_is_that_request(world, clock):
    policy(world)
    phone(world, "marca dentista quinta às 10h")
    out = phone(world, "marca almoço sexta às 12h no google")
    assert out["reply"].startswith("The previous question was discarded.") is False and OPEN in out["reply"] and live() is None
    phone(world, "marca dentista quinta às 10h")
    slash = phone(world, "/status")
    assert slash["reply"] is None and live() is None


def test_a_title_or_a_subject_is_one_line_and_a_body_or_a_content_may_have_several(world, clock):
    policy(world)
    phone(world, "marca quinta às 10h no google")
    state = live()
    ctx = ops_core.context(world["path"])
    assert (ops_natural_writes._classify(ctx, state, "uma linha\noutra linha") or {}).get("kind") != "slots", "a title is one line"
    assert (ops_natural_writes._classify(ctx, state, "x" * 201) or {}).get("kind") != "slots", "a title is at most 200 characters"
    assert ops_natural_writes._classify(ops_core.context(world["path"]), dict(state, need="body", slot="body"), "um\ndois")["slots"] == {"body": "um\ndois"}


@pytest.fixture
def spy(monkeypatch):
    seen = []
    start = st.load("account_start").start
    monkeypatch.setattr(st.load("account_start"), "start", lambda *a, **k: (seen.append(a), start(*a, **k))[1])
    return seen

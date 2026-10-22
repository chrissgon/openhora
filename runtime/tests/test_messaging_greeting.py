"""A greeting, or a help line in words, on a phone through the messaging bridge (slice S5: runtime/messaging_bridge.py `greets` and `needs`, runtime/greeting.py).

The help lines the bridge used to answer with the fixed list of commands ("ajuda", "help", "what can you do") are, from a sender who holds `talk`, a greeting: `say` answers them with the
summary of what that sender may do, with no model. A sender who may not talk keeps the fixed list. Over the real operations layer and a stand-in messenger, as
test_messaging_natural_writes.py; no model, no network; invented sender ids. Every expected text is a literal of this file.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_greeting.py
"""
from __future__ import annotations

import json

import standin_tree as st
from test_messaging_natural_writes import OWNER, READER, PLAIN, day, forget  # noqa: F401  (the calendar world, the stand-in messenger and their senders)
from test_calendar_write import world  # noqa: F401

ops = st.load("ops")

SILENT = "7171"
HEAD = "Hello! Here is what I can do for you now:"
OWNER_REPLY = "\n".join([HEAD, "- set reminders", "- create, change or cancel events on your calendar, after you approve", "- save files to your Drive or OneDrive, after you approve"])
READER_REPLY = "\n".join([HEAD, "- read and summarise your e-mails", "- create, change or cancel events on your calendar, after you approve"])
PLAIN_REPLY = "\n".join([HEAD, "- send me a request in a sentence and I will pass it to the planning agent"])


def with_silent_sender(day):
    file = day.path + "/docs/workbench/runtime.json"
    raw = json.loads(open(file).read())
    raw["policies"]["silent"] = ["read"]
    raw["messaging"]["senders"]["telegram"].append({"id": SILENT, "policy": "silent"})
    open(file, "w").write(json.dumps(raw))
    shown = ops.config(day.path)
    ops.accept_config(day.path, shown["sha256"], widen=shown["widening_sha256"])


def test_a_greeting_or_a_help_line_from_a_sender_who_talks_gets_the_summary_of_that_senders_policy(day):
    for line in ("oi", "Ajuda", "what can you do?", "Bom dia, tudo bem?"):      # validate: allow english-only -- the lines under test
        day.say(OWNER, line)
        assert day.texts(OWNER)[-1] == OWNER_REPLY, line
    day.say(READER, "hello")
    day.say(PLAIN, "help")
    assert day.texts(READER)[-1] == READER_REPLY and day.texts(PLAIN)[-1] == PLAIN_REPLY


def test_no_help_line_of_the_summary_carries_a_slash_command(day):
    day.say(OWNER, "help")
    assert "/" not in day.texts(OWNER)[-1] and "Commands:" not in day.texts(OWNER)[-1]


def test_a_sender_who_may_not_talk_keeps_the_fixed_help_and_gets_no_reply_to_a_greeting(day):
    with_silent_sender(day)
    day.say(SILENT, "ajuda")      # validate: allow english-only -- the line under test
    assert day.texts(SILENT)[-1].startswith("Commands:\n/pending")
    count = len(day.texts(SILENT))
    day.say(SILENT, "oi")      # validate: allow english-only -- the line under test
    assert HEAD not in "".join(day.texts(SILENT)[count:]), "the summary is for a sender who may talk"


def test_vacuity_a_request_after_the_greeting_is_not_answered_with_the_summary(day):
    day.say(OWNER, "oi, me lembra amanha as 9 de regar as plantas")      # validate: allow english-only -- the line under test: a reminder
    assert HEAD not in "".join(day.texts(OWNER))

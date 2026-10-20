"""The interface of a family of the natural writes (package NR-5; runtime/natural_writes.py, runtime/ops_natural_writes.py): what a family module that plugs in with one line of the
registry is promised, held with stand-in modules for the mail family so that the contract is tested apart from any real family. A family reads a line (`HEADS`, `read`), resolves
it with the project (`resolve`: arguments, a question or a final sentence), may answer a need of its own (`NEEDS`, `answer` with the options the question stored), and every
question and answer is stored as a neutral word. Over the real operations layer and a stand-in project; no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_family.py
"""
from __future__ import annotations

import sys
import types

import pytest

import standin_tree as st
from test_calendar_write import world  # noqa: F401  (a real project to read the configuration of)
from test_ops_natural_writes import SENDER, forget, phone, policy  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
ops_natural_writes = st.load("ops_natural_writes")
natural_writes = st.load("natural_writes")
drafts = st.load("drafts")
phrases = st.load("phrases")
account_start = st.load("account_start")


@pytest.fixture
def stand_in(monkeypatch):
    """A family `mail` that archives "arquiva o e-mail <n>": it asks which snapshot with two options, answers a number the person was SHOWN, and says a final sentence for 99."""
    seen = {"resolve": [], "answer": []}
    pure = types.ModuleType("natural_writes_stubmail")
    pure.HEADS = lambda tables: ["arquiva", "archive"]
    pure.NEEDS = ("message",)

    def read(line, tables, now=None, op=None):
        shaped = natural_writes.Line(line)
        found = shaped.find(["arquiva o e mail", "archive email"])
        if not found:
            return None
        number = natural_writes.numbers(shaped, found[1], len(shaped.norm), tables)
        if not number:
            return None
        return {"op": "mail-archive", "slots": {"numbers": number}, "spans": {}, "ranges": {}, "need": [], "engine": None, "doubt": False}
    pure.read = read

    def answer(need, line, slots, tables, now, options=None):
        seen["answer"].append((need, line, [o["value"] for o in options]))
        shown = [o["value"] for o in options]
        return {"slots": {"source": line.strip()}} if line.strip() in shown else None
    pure.answer = answer
    resolver = types.ModuleType("ops_natural_stubmail")

    def resolve(ctx, op, slots, channel, sender, said):
        seen["resolve"].append((op, dict(slots), channel, sender, list(said)))
        if slots["numbers"] == [99]:
            return {"say": {"sentence_key": "NW_NO_CALENDAR_SOURCE", "fields": {}}}
        if "source" not in slots:
            return {"ask": {"need": "message", "slot": "source", "sentence_key": "NW_ASK_SOURCE", "fields": {}, "multi": False, "engine": None,
                            "options": [{"value": "inbox", "label": "Bia · Appointment"}, {"value": "bills", "label": "Bank · Statement"}]}}
        return {"args": {"account": "google", "messages": ",".join(f"{slots['source']}#{n}" for n in slots["numbers"])}}
    resolver.resolve = resolve
    monkeypatch.setitem(sys.modules, "natural_writes_stubmail", pure)
    monkeypatch.setitem(sys.modules, "ops_natural_mail", resolver)
    monkeypatch.setitem(natural_writes.FAMILIES, "mail", "natural_writes_stubmail")
    return seen


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


def test_a_registered_family_is_recognised_by_its_heads_and_read_before_the_calendar_verb(stand_in):
    assert natural_writes.candidate("arquiva o e-mail 3") == {"family": "mail", "op": "mail-archive"}
    assert natural_writes.candidate("archive email 3") == {"family": "mail", "op": "mail-archive"}
    assert natural_writes.read("arquiva o e-mail 2, 4 e 7")["slots"] == {"numbers": [2, 4, 7]}
    assert natural_writes.candidate("arquiva os arquivos antigos") is None


def test_the_resolver_gets_the_line_the_channel_the_sender_and_the_lines_said_so_far(world, clock, stand_in):
    policy(world)
    ctx = ops_core.context(world["path"])
    from test_ops_natural_writes import OPEN  # noqa: F401
    ops_natural_writes.open_line(world["path"], ctx, "arquiva o e-mail 3", "terminal", None, {})
    [(op, slots, channel, sender, said)] = stand_in["resolve"]
    assert (op, slots, channel, sender, said) == ("mail-archive", {"numbers": [3]}, "terminal", None, ["arquiva o e-mail 3"])


def test_a_need_the_family_declares_is_answered_by_the_family_with_the_options_the_question_stored_before_any_generic_answer(world, clock, stand_in, monkeypatch):
    policy(world)
    calls = []
    monkeypatch.setattr(ops_natural_writes, "_call_operation", lambda project, op, args, channel, sender: (calls.append((op, args, channel, sender)),
                        {"request": 1, "task": 1, "pending": 7, "word": "mailbox", "on_cards": True})[1])
    asked = ops.natural_write(world["path"], "arquiva o e-mail 3", channel="messaging", sender=SENDER)
    assert asked["asked"] and asked["reply"].endswith("1. Bia · Appointment\n2. Bank · Statement") and calls == []
    wrong = ops.natural_write(world["path"], "1", channel="messaging", sender=SENDER)
    assert wrong["asked"] is True, "the family answers with what the person was shown (the values), not with the place in the list"
    done = ops.natural_write(world["path"], "bills", channel="messaging", sender=SENDER)
    assert calls == [("mail-archive", {"account": "google", "messages": "bills#3"}, "messaging", SENDER)] and done["resend"] == 7
    assert [a[0] for a in stand_in["answer"]] == ["message", "message"] and stand_in["answer"][0][2] == ["inbox", "bills"]


def test_a_final_sentence_of_the_resolver_is_the_reply_and_stores_no_draft(world, clock, stand_in):
    policy(world)
    out = ops.natural_write(world["path"], "arquiva o e-mail 99", channel="messaging", sender=SENDER)
    assert out["reply"] == phrases.text("NW_NO_CALENDAR_SOURCE", None) and not drafts.count() and out["asked"] is False


def test_every_question_and_answer_of_a_family_is_stored_as_a_neutral_word_in_the_conversation(world, clock, stand_in):
    policy(world)
    policy(world, page=("read", "calendar-write", "mail-organize"))
    ops.say(world["path"], "arquiva o e-mail 3", channel="page")
    ops.say(world["path"], "inbox", channel="page")
    ctx = ops_core.context(world["path"])
    rows = [(m["role"], m["text"]) for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=100)]
    assert rows[:2] == [("user", "(a request to your accounts)"), ("assistant", "(request to your accounts)")]
    assert "Bia" not in str(rows) and "Bank" not in str(rows)


def test_a_comma_after_a_polite_word_does_not_hide_the_head():
    for line in ("por favor, arquiva o e-mail 3", "please, archive email 3", "por favor arquiva o e-mail 3"):
        assert natural_writes.Line(line).lead(["arquiva", "archive"], natural_writes._tables()) is not None, line

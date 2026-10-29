"""What a write asked in words keeps private (package NR-5, limit L61; runtime/ops_natural.py `stored_line` and `private_ids`, runtime/ops_natural_writes.py): the conversation,
which the MCP mode reads, stores a neutral word for the line, for each question and for each answer, on the page and the terminal; a line that only the router recognised is
shown as the neutral word to every reader but the person's own shells; and the decision a line opens is read by the MCP mode and by a messaging reader without `ask-mail`
through `private_view` and `task_view` exactly as a typed one is. Over the real operations layer and the W1 stand-in writers (test_calendar_write.py's world); no model;
invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_privacy.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st
from closed_heads import closed_heads  # noqa: F401  (S41-11: the claim of the write families, as a fixture: these tests are about the readers and resolvers, not the claim)
from test_calendar_write import SEEDED, install_item_refs, seed_google, world  # noqa: F401  (the calendar world)
from test_ops_natural_writes import OPEN, PLAIN, READER, SENDER, body, forget, phone, policy  # noqa: F401
from test_reminders import Clock

ops = st.load("ops")
ops_core = st.load("ops_core")
ops_natural = st.load("ops_natural")
drafts = st.load("drafts")
phrases = st.load("phrases")

LINE, REPLY = "(a request to your accounts)", "(request to your accounts)"


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


def same(text: str) -> str:
    """A card's body without the moment the event was read (two cards made a second apart differ in it and in nothing else)."""
    return re.sub(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z", "<read>", text)


def stored(world):
    ctx = ops_core.context(world["path"])
    return [(m["role"], m["text"]) for m in ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)]


@pytest.mark.parametrize("channel", [None, "page"])
def test_a_write_line_said_on_the_terminal_or_the_page_is_stored_as_the_neutral_word_before_it_reaches_the_planning_agent(world, clock, monkeypatch, channel):
    """S41-11: no plain line is claimed on a shell any more (a write form said on the page or the terminal reaches the planning agent); the conversation, which the MCP mode reads, still keeps the
    neutral word for the line, stored before the agent is asked. The planning agent is a stand-in here (`_say_route`): what is checked is what the store keeps and what the MCP mode reads."""
    policy(world)
    ops_say = st.load("ops_say")
    monkeypatch.setattr(ops_say, "_say_route", lambda *a, **k: ("an answer of the agent", None, None, False, None))
    ops.say(world["path"], "cria um evento Zorbablax sexta no google", channel=channel)
    rows = stored(world)
    assert rows[0] == ("user", LINE), "the line is stored as the neutral word"
    seen = ops.conversation(world["path"], channel="mcp")["messages"]
    assert "Zorbablax" not in str(seen)


def test_the_neutral_words_are_in_both_columns_and_the_router_memory_leaves_them_out(world, clock):
    for key in ("NW_PRIVATE_LINE", "NW_PRIVATE_REPLY"):
        assert all(phrases.every(key)) and len(phrases.every(key)) == 2
    assert ops_natural.is_placeholder(LINE) and ops_natural.is_placeholder(REPLY)
    policy(world)
    ctx = ops_core.context(world["path"])
    ops_core._stored(ctx, ctx["store"].message_add, conversation=ops.CONVERSATION, role="user", text=ops_natural.stored_line(ctx, "marca dentista quinta às 10h no google"))
    ops_core._stored(ctx, ctx["store"].message_add, conversation=ops.CONVERSATION, role="assistant", text=REPLY)
    messages = ctx["store"].messages_list(ctx["conn"], ops.CONVERSATION, limit=500)
    assert [m["text"] for m in messages] == [LINE, REPLY]
    assert ops.chat_memory(messages, set()) == ""


def test_a_write_line_that_only_the_router_recognised_is_shown_as_the_neutral_word_to_every_reader_but_the_persons_shells(world, clock):
    rows = [{"id": 1, "role": "user", "text": "pon al dentista en mi calendario el jueves"}, {"id": 2, "role": "assistant", "text": REPLY},
            {"id": 3, "role": "user", "text": "hello"}, {"id": 4, "role": "assistant", "text": "Hi."}]
    assert set(ops_natural.private_ids(rows)) == {1} and ops_natural.private_ids(rows)[1] == "NW_PRIVATE_LINE"


def test_the_decision_a_line_opens_is_read_by_the_mcp_mode_and_a_reader_without_ask_mail_exactly_as_a_typed_one_is(world, clock, monkeypatch):
    policy(world)
    seed_google(world)
    install_item_refs(world, monkeypatch, {"agenda#2": {"id": SEEDED, "calendar": "pat@example.com", "account": "google"}})
    natural = phone(world, "remarca o evento 2 para sexta às 15h", READER)
    typed = ops.event_change(world["path"], "google", "agenda#2", start="2026-10-23T15:00", channel="messaging", sender=READER)
    for kwargs in ({"channel": "mcp"}, {"channel": "messaging", "sender": SENDER}, {"channel": "messaging", "sender": READER}, {"channel": "page"}):
        a = ops.pending(world["path"], natural["resend"], **kwargs)
        b = ops.pending(world["path"], typed["pending"], **kwargs)
        assert (a["title"], same(a["body"])) == (b["title"], same(b["body"])), kwargs
    hidden = ops.pending(world["path"], natural["resend"], channel="mcp")["body"]
    assert "Dentist" not in hidden, "the event's current title is another kind of private line: drawn only for a holder of ask-mail"
    assert "Dentist" in ops.pending(world["path"], natural["resend"], channel="messaging", sender=READER)["body"]


def test_a_question_that_shows_the_persons_words_is_sent_only_to_the_chat_that_asked(world, clock):
    policy(world)
    phone(world, "cria um evento Zorbablax sexta no google")
    ctx = ops_core.context(world["path"])
    assert "Zorbablax" not in str(ops.conversation(world["path"], channel="mcp")) and not stored(world)
    assert ops_natural.stored_line(ctx, "cria um evento Zorbablax sexta no google") == LINE
    assert ops_natural.stored_line(ctx, "bom dia") == "bom dia"

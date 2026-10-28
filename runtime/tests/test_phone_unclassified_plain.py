"""A reply of the router that names no route, on a phone (slice S1, limits L62 and L63): one plain sentence, no command, no number, and nothing left open.

Before this slice the sentence was the router's own "did not name a flow" line and a tail of two commands (`/cancel 8`, `/new <text>`), and the request stayed open and took the
person's next line for its answer. On a messaging app the reply is now the one sentence PHONE_NOT_UNDERSTOOD, the request is cancelled by code right after, and the next
plain line is a new line. The page and the terminal keep the question with its actions. Over the REAL operations layer with a stand-in router; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_unclassified_plain.py
"""
from __future__ import annotations

import re

import phone_said as ps
import phrase_kit as pk
import standin_tree as st
from test_ask import accept
from test_ops_natural import FLOW, KEY, docs, router_says, with_senders, world  # noqa: F401  (the real-operations world fixture)

ops = st.load("ops")
ops_cancel = st.load("ops_cancel")
phrases = st.load("phrases")
PT = {"language": "pt-BR"}

PROSE = "I looked around and I am not sure what you want.\n"
SENTENCE = phrases.text("PHONE_NOT_UNDERSTOOD", None)      # the sentence of the table: the oracle `problems` reads it as a text
COMMAND = re.compile(r"(^|\s)/[a-z]+")
FORBIDDEN = ("route --flow", "python3", "uv run", "pedido 8", "/cancel", "/new", "did not name a flow")


def problems(reply: str) -> list:
    """What is wrong with a phone's reply to an unclassified route: a command, a terminal fragment, a request number, the router's own line."""
    return ([f"command {m.group(0)!r}" for m in COMMAND.finditer(reply)] + [f"fragment {piece!r}" for piece in FORBIDDEN if piece in reply]
            + (["the router's prose"] if PROSE.strip() in reply else []))


def phone(world, line):
    return ops.say(world["path"], line, channel="messaging", sender=KEY["owner"])


def test_a_phone_gets_one_plain_sentence_and_the_request_is_cancelled_by_code(world, monkeypatch):
    with_senders(world)
    router_says(world, PROSE)
    cancelled = []
    real = ops_cancel.request_cancel
    monkeypatch.setattr(ops_cancel, "request_cancel", lambda conn, request_id, *, by, context: cancelled.append(by) or real(conn, request_id, by=by, context=context))
    out = phone(world, "Something unclear.")
    assert ps.alone(out["reply"], "PHONE_NOT_UNDERSTOOD", {}) and problems(out["reply"]) == []
    assert out["pending_id"] is None and out["ran"] is True
    assert cancelled == ["code:unclassified-phone"]
    assert ops.status(world["path"])["requests"][0]["state"] == "cancelled" and ops.pending(world["path"])["pending"] == []


def test_the_next_plain_line_is_a_new_line_and_not_the_answer_to_the_old_question(world):
    with_senders(world)
    router_says(world, PROSE)
    phone(world, "Something unclear.")
    router_says(world, FLOW)
    out = phone(world, "Which market first?")
    assert "I took that as the answer" not in out["reply"] and out["request_id"] is not None
    assert [r["state"] for r in ops.status(world["path"])["requests"]][:2] == ["cancelled", "requested"]


def test_a_project_in_portuguese_gets_the_sentence_in_portuguese(world):
    with_senders(world)
    accept(world["path"], language="pt-BR")
    router_says(world, PROSE)
    out = phone(world, "Algo sem sentido.")
    assert ps.alone(out["reply"], "PHONE_NOT_UNDERSTOOD", PT) and problems(out["reply"]) == []


def test_the_page_keeps_the_question_with_its_actions_and_the_request_waits(world):
    router_says(world, PROSE)
    out = ops.say(world["path"], "Something unclear.", channel="page")
    request = out["request_id"]
    assert pk.said(out["reply"].split("\n")[0], "BODY_NOT_NAMED", request=request)
    assert f"/cancel {request}" in out["reply"] and out["pending_id"] is not None
    assert ops.status(world["path"])["requests"][0]["state"] == "requested"


def test_vacuity_the_old_phone_reply_is_noticed_by_the_check():
    old = "The planning agent did not name a flow or a skill for request 8\n\nCancel it with /cancel 8, name a flow on the platform's page, or start again with /new <text>"
    assert any(p.startswith("command") for p in problems(old)) and any("did not name a flow" in p for p in problems(old))
    assert problems(PROSE.strip()) == ["the router's prose"] and problems(SENTENCE) == []

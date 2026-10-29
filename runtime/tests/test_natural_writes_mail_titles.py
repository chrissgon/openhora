"""The title of an event that begins with a word the mail family uses as a verb (package NR-5b, review of #485): "Passa no banco", "Envia proposta", "Send flowers", "Reply to
Ana" are titles, not new requests. The foundation drops an open question when the next line is a request of its own (runtime/ops_natural_writes.py `_another_request`); the mail
family names its CLOSED heads (verb, articles, object: `natural_writes_mail.is_head`) so that a bare verb at the start of a title does not count as one. Over the real operations
layer and the W1 stand-in writers (test_calendar_write.py's world); no model; invented words.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_natural_writes_mail_titles.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from closed_heads import closed_heads  # noqa: F401  (S41-11: the claim of the write families, as a fixture: these tests are about the readers and resolvers, not the claim)
from test_calendar_write import world  # noqa: F401  (the calendar world)
from test_ops_natural_writes import forget, phone, policy  # noqa: F401
from test_reminders import Clock

drafts = st.load("drafts")


@pytest.fixture
def clock(monkeypatch):
    return Clock(monkeypatch, wall="2026-10-19 09:00")


@pytest.mark.parametrize("title", ["Passa no banco", "Envia proposta", "Send flowers", "Reply to Ana", "Archive old photos", "Marca presença"])      # validate: allow english-only -- a Portuguese line is the input under test
def test_a_title_that_begins_with_a_bare_mail_verb_is_the_title_of_the_event_and_opens_its_card(world, clock, title):
    policy(world)
    asked = phone(world, "marca quinta às 10h no google")      # validate: allow english-only -- a Portuguese line is the input under test
    assert asked["asked"] is True and drafts.count() == 1
    done = phone(world, title)
    assert done["reply"] and "waits for your approval" in done["reply"] and done["resend"] and drafts.count() == 0, done


@pytest.mark.parametrize("request_line", ["manda um e-mail pra bia@exemplo.example dizendo oi", "arquiva os e-mails 2 e 4", "responde o e-mail 3 dizendo ok", "send an email to bia@example.example saying hi"])      # validate: allow english-only -- a Portuguese line is the input under test
def test_a_closed_mail_request_offered_as_a_title_is_a_request_of_its_own_and_is_never_the_title(world, clock, request_line):
    policy(world)
    phone(world, "marca quinta às 10h no google")      # validate: allow english-only -- a Portuguese line is the input under test
    out = phone(world, request_line)
    assert "waits for your approval" not in (out["reply"] or ""), "the request was not taken as the title of the event, whose card would have opened"
    left = drafts.get("messaging", "telegram:830461975213", "write")
    assert left is None or left["op"] != "event-create", "the question about the event was dropped: the line is a request of its own"

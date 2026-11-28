"""The question for the recipient of a new e-mail when the person named no one (package P5B-MAIL-ASK-TO-EMPTY, chrissgon/openhora#972): the sentence NW_MAIL_ASK_TO is
asked with a default name, "the recipient" / "quem vai receber", never with an empty one, and a named recipient is asked as before. Offline.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_mail_ask_to_unnamed.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from closed_heads import closed_heads  # noqa: F401
from test_natural_writes_mail import Desk, onm, resolve, settle

phrases = st.load("phrases")

LINE_UNNAMED = "manda um e-mail"      # the family reads no line with no recipient (its containment negative), so the open slot is reached with the slots a seed or an answer leaves
LINE_NAMED = "manda um e-mail pra Bia dizendo que o contrato segue amanhã"      # validate: allow english-only -- a Portuguese line is the input under test


def unnamed(desk):
    """The family's resolution of a new e-mail with a body and no recipient, name or address."""
    return settle(onm.resolve(desk.ctx, "mail-send", {"body": "o contrato segue amanhã"}, "chat", None, [LINE_UNNAMED]))      # validate: allow english-only -- a Portuguese line is the input under test


@pytest.mark.parametrize("tag", ["en", "pt-BR"])
def test_an_unnamed_recipient_is_asked_with_the_default_name(monkeypatch, tag):
    desk = Desk(monkeypatch, accounts=("google",))
    desk.cfg["language"] = tag
    ask = unnamed(desk)["ask"]
    assert ask["need"] == "to"
    assert (ask["sentence_key"], ask["fields"]) == ("NW_MAIL_ASK_TO_UNNAMED", {})
    asked = phrases.text(ask["sentence_key"], desk.cfg, **ask["fields"])
    assert asked == {"en": "What is the e-mail address of the recipient?", "pt-BR": "Qual o e-mail de quem vai receber?"}[tag]


def test_a_named_recipient_is_asked_as_before(monkeypatch):
    desk = Desk(monkeypatch, accounts=("google",))
    assert resolve(desk, LINE_NAMED)["ask"]["fields"] == {"name": "Bia"}


def test_the_question_is_said_in_the_language_it_is_shown_in(monkeypatch):
    """No translated text is stored in a field: the same pending question reads whole in each language scope."""
    desk = Desk(monkeypatch, accounts=("google",))
    desk.cfg["language"] = "en"
    ask = unnamed(desk)["ask"]
    assert ask["fields"] == {}
    with phrases.scope("pt-BR"):
        assert phrases.text(ask["sentence_key"], desk.cfg, **ask["fields"]) == "Qual o e-mail de quem vai receber?"
    assert phrases.text(ask["sentence_key"], desk.cfg, **ask["fields"]) == "What is the e-mail address of the recipient?"

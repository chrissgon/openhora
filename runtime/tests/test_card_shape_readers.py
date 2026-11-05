"""ACEITE-37: the two readers that keep a line away from something other than the card words read the SHAPE of a card word, `card_words.card_shape`, not `card_word` (runtime/card_words.py). A line
in question form ("sim?") is no card word, but it is not the change of an effect card on e-mail (runtime/ops_card_revise.py `_recognised` and `_taken`) and not a claim of a research answer
(runtime/research_reply.py `_claim`) either. Each reader has a vacuity case that gives it `card_word` in place of `card_shape`. Offline; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_card_shape_readers.py
"""
from __future__ import annotations

import pytest

import standin_tree as st

card_words = st.load("card_words")
ops_card_revise = st.load("ops_card_revise")
research_reply = st.load("research_reply")

QUESTIONS = ["sim?", "pode?", "nao?", "can you approve", "poderia aprovar", "sim❓"]


@pytest.fixture
def only_the_card_words(monkeypatch):
    """The other reasons `_recognised` has to say yes are made false, so that only the card words decide."""
    monkeypatch.setattr(ops_card_revise.ops_natural, "peek", lambda *args, **kwargs: False)
    monkeypatch.setattr(ops_card_revise.turn_gate, "new_request", lambda line: None)
    monkeypatch.setattr(ops_card_revise.ops_say, "state_question", lambda line: False)
    monkeypatch.setattr(ops_card_revise.greeting, "is_greeting", lambda line, helps=False: False)


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_question_is_recognised_as_card_shaped_so_it_is_no_change_of_a_card(only_the_card_words, line):
    assert ops_card_revise._recognised({}, line, "me") is True
    assert ops_card_revise._recognised({}, "move it to ten", "me") is False      # the oracle can say no


def as_card_word(monkeypatch, module):
    """Give the reader `card_word` in place of `card_shape`: the shape without the question rule, with the rule put back (the planted wrong reader)."""
    shape = card_words.card_shape
    monkeypatch.setattr(module.card_words, "card_shape", lambda line: None if card_words.question_form(line) else shape(line))


def test_vacuity_with_the_reader_given_card_word_the_question_is_not_recognised(only_the_card_words, monkeypatch):
    as_card_word(monkeypatch, ops_card_revise)
    assert ops_card_revise._recognised({}, "sim?", "me") is False


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_question_on_an_effect_card_is_taken_as_no_change_before_the_store_is_read(line):
    """`_taken` returns None before it reads the decision: a context with no store would fail the read."""
    assert ops_card_revise._taken({}, 1, "a" * 64, line, ops_card_revise.CHANNEL, "me") is None


def test_vacuity_with_the_reader_given_card_word_the_question_reaches_the_store(monkeypatch):
    as_card_word(monkeypatch, ops_card_revise)
    with pytest.raises(Exception):
        ops_card_revise._taken({}, 1, "a" * 64, "sim?", ops_card_revise.CHANNEL, "me")


@pytest.mark.parametrize("line", ["sim?", "nao?", "sim❓", "sim", "ok"])
def test_a_card_word_or_a_question_is_no_claim_of_a_research_answer(line):
    assert research_reply._claim(line) is None


def test_vacuity_with_the_reader_given_card_word_the_question_becomes_a_claim(monkeypatch):
    as_card_word(monkeypatch, research_reply)
    assert research_reply._claim("sim?") is not None
    assert research_reply._claim("sim") is None      # a plain word is still no claim: the vacuity changes only the question

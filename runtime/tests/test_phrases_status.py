"""The store's status words, said at the reading layer (package LR-1, runtime/phrases.py `status` and `heading`): the words stay English in the store, the
operations layer, the logs, the terminal, the MCP mode and the API; only a sentence rendered for a person in a project whose language has a table shows the
translated word. A closed list, read from the store's own CHECK lists and state machines, so that a status the store gains cannot reach a phone without a word
here. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phrases_status.py
"""
from __future__ import annotations

import re

import phrase_kit as pk
import standin_tree as st

phrases = st.load("phrases")
PT_CFG = {"language": "pt-BR"}


def store_words() -> set:
    """Every status and state word the store admits: the CHECK lists of its tables and the lists of its state machines, read from its source."""
    source = (st.REPO / "providers" / "store" / "sqlite.py").read_text(encoding="utf-8")
    words = set()
    for body in re.findall(r"\b(?:status|state) IN \(([^)]*)\)", source, re.S):
        words |= set(re.findall(r"'([a-z_-]+)'", body))
    for name in re.findall(r"^([A-Z_]+_(?:STATES|STATUSES)) = \(", source, re.M):         # every tuple of the kind, so that a new one is read too
        body = re.search(rf"^{name} = \(([^)]*)\)", source, re.M)
        words |= set(re.findall(r'"([a-z_-]+)"', body.group(1)))
    return words


def test_every_status_word_the_store_admits_has_a_word_in_each_language_and_the_table_holds_no_other():
    words = store_words()
    assert re.findall(r"^([A-Z_]+_(?:STATES|STATUSES)) = \(", (st.REPO / "providers" / "store" / "sqlite.py").read_text(encoding="utf-8"), re.M).count("REMINDER_STATUSES") == 1
    assert phrases.STATUS["pt-BR"]["dropped"] != phrases.STATUS["pt-BR"]["discarded"], "two words of the store are two words"
    assert len(words) >= 40 and {"approved", "cancelled", "pending-execution", "read_only", "to_inbox", "requested"} <= words
    assert set(phrases.STATUS["en"]) == set(phrases.STATUS["pt-BR"]) == words, sorted(words ^ set(phrases.STATUS["pt-BR"]))
    assert all(phrases.STATUS["en"][w] == w for w in words), "English is the store's own word"
    assert all(phrases.STATUS["pt-BR"][w].strip() for w in words) and phrases.STATUS["pt-BR"]["approved"] == "aprovado"


def test_a_status_word_is_said_in_the_language_and_an_unknown_one_or_a_language_with_no_table_leaves_it_as_it_is():
    assert [phrases.status(w, PT_CFG) for w in ("approved", "cancelled", "sent", "missed", "added", "failed", "pending-execution")] == [
        "aprovado", "cancelado", "enviado", "perdido", "adicionado", "com falha", "aguardando execução"]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    for cfg in (None, {}, {"language": "en"}, {"language": "fr"}):
        assert phrases.status("approved", cfg) == "approved", cfg
    assert phrases.status("on hold", PT_CFG) == "on hold" and phrases.status("", PT_CFG) == "" and phrases.status(None, PT_CFG) is None and phrases.status(7, PT_CFG) == 7
    pk.assert_said(phrases.text("NOT_OPEN", PT_CFG, number=3, status=phrases.status("approved", PT_CFG)), "NOT_OPEN", PT_CFG, number=3, status="aprovado")
    pk.assert_said(phrases.text("NOT_OPEN", None, number=3, status=phrases.status("approved", None)), "NOT_OPEN", None, number=3, status="approved")


def test_a_sentence_an_operation_raised_with_a_status_word_says_the_word_in_the_language_and_an_unknown_word_stays():
    reminder = phrases.text("RM_NOT_WAITING", None, n=2, status="cancelled")
    pk.assert_said(phrases.localize(reminder, PT_CFG), "RM_NOT_WAITING", PT_CFG, n=2, status="cancelado")
    added = phrases.text("ATT_NOT_HELD", None, status="added")
    pk.assert_said(phrases.localize(added, PT_CFG), "ATT_NOT_HELD", PT_CFG, status="adicionado")
    held = phrases.text("ATT_NOT_HELD", None, status="on hold")
    pk.assert_said(phrases.localize(held, PT_CFG), "ATT_NOT_HELD", PT_CFG, status="on hold")
    pk.assert_said(phrases.localize(reminder, None), "RM_NOT_WAITING", None, n=2, status="cancelled")


def test_a_heading_code_wrote_whole_is_said_in_the_language_and_any_other_heading_is_not_touched():
    def english(key, **fields):
        return phrases.text(key, None, **fields)

    pk.assert_said(phrases.heading(english("TITLE_ROUTER_ASKS"), PT_CFG), "TITLE_ROUTER_ASKS", PT_CFG)
    pk.assert_said(phrases.heading(english("TITLE_ROUTE_UNRECOGNISED"), PT_CFG), "TITLE_ROUTE_UNRECOGNISED", PT_CFG)
    pk.assert_said(phrases.heading(english("TITLE_NO_DELIVERY_ROUTED"), PT_CFG), "TITLE_NO_DELIVERY_ROUTED", PT_CFG)
    pk.assert_said(phrases.heading(english("TITLE_REROUTE_FAILED", k=2), PT_CFG), "TITLE_REROUTE_FAILED", PT_CFG, k=2)
    pk.assert_said(phrases.heading(english("TITLE_REROUTE_ACCEPT", k=3), PT_CFG), "TITLE_REROUTE_ACCEPT", PT_CFG, k=3)
    for title in ("Plan: flow-demo (3 tasks)", "demo-asks: question", "Pull request: Carry the providers", "The router asks about the budget", "", None):
        assert phrases.heading(title, PT_CFG) == title, title
    for cfg in (None, {"language": "en"}, {"language": "fr"}):
        pk.assert_said(phrases.heading(english("TITLE_ROUTER_ASKS"), cfg), "TITLE_ROUTER_ASKS", None)

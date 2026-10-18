"""The store's status words, said at the reading layer (package LR-1, runtime/phrases.py `status` and `heading`): the words stay English in the store, the
operations layer, the logs, the terminal, the MCP mode and the API; only a sentence rendered for a person in a project whose language has a table shows the
translated word. A closed list, read from the store's own CHECK lists and state machines, so that a status the store gains cannot reach a phone without a word
here. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phrases_status.py
"""
from __future__ import annotations

import re

import standin_tree as st

phrases = st.load("phrases")
PT_CFG = {"language": "pt-BR"}


def store_words() -> set:
    """Every status and state word the store admits: the CHECK lists of its tables and the lists of its state machines, read from its source."""
    source = (st.REPO / "providers" / "store" / "sqlite.py").read_text(encoding="utf-8")
    words = set()
    for body in re.findall(r"\b(?:status|state) IN \(([^)]*)\)", source, re.S):
        words |= set(re.findall(r"'([a-z_-]+)'", body))
    for name in ("TASK_STATES", "STEP_STATES", "PENDING_STATUSES", "APPROVAL_STATUSES", "WAIT_STATUSES", "DOCUMENT_STATUSES", "COMMENT_STATUSES", "ROUTINE_STATES",
                 "FIRE_STATUSES", "RUN_END_STATUSES", "EVENT_DONE_STATUSES", "INBOX_STATUSES", "REROUTE_STATES"):
        body = re.search(rf"^{name} = \(([^)]*)\)", source, re.M)
        assert body, name
        words |= set(re.findall(r'"([a-z_-]+)"', body.group(1)))
    return words


def test_every_status_word_the_store_admits_has_a_word_in_each_language_and_the_table_holds_no_other():
    words = store_words()
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
    assert phrases.text("NOT_OPEN", PT_CFG, number=3, status=phrases.status("approved", PT_CFG)) == "A decisão pendente 3 tem o status aprovado: não está aberta."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.text("NOT_OPEN", None, number=3, status=phrases.status("approved", None)) == "Pending decision 3 is approved, not open."


def test_a_sentence_an_operation_raised_with_a_status_word_says_the_word_in_the_language_and_an_unknown_word_stays():
    assert phrases.localize("Reminder 2 is cancelled, not waiting.", PT_CFG) == "O lembrete 2 tem o status cancelado: não está esperando."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.localize("That file is added, not waiting for your answer.", PT_CFG) == "Esse arquivo tem o status adicionado: não está esperando pela sua resposta."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.localize("That file is on hold, not waiting for your answer.", PT_CFG) == "Esse arquivo tem o status on hold: não está esperando pela sua resposta."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.localize("Reminder 2 is cancelled, not waiting.", None) == "Reminder 2 is cancelled, not waiting."


def test_a_heading_code_wrote_whole_is_said_in_the_language_and_any_other_heading_is_not_touched():
    assert phrases.heading("The router asks", PT_CFG) == "O roteador pergunta"
    assert phrases.heading("The route was not recognised", PT_CFG) == "A rota não foi reconhecida"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.heading("No delivery was routed", PT_CFG) == "Nenhuma entrega foi encaminhada"
    assert phrases.heading("Delivery 2 was not routed after its brief", PT_CFG) == "A entrega 2 não foi encaminhada depois do briefing"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert phrases.heading("Accept the tasks of delivery 3, routed after its brief", PT_CFG) == "Aceitar as tarefas da entrega 3, encaminhadas depois do briefing"
    for title in ("Plan: flow-demo (3 tasks)", "demo-asks: question", "Pull request: Carry the providers", "The router asks about the budget", "", None):
        assert phrases.heading(title, PT_CFG) == title, title
    for cfg in (None, {"language": "en"}, {"language": "fr"}):
        assert phrases.heading("The router asks", cfg) == "The router asks"

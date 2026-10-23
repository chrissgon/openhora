"""The answer from sources and the conversation in the project's language (package LR-1, runtime/phrases.py): the refusals and the checked answer of `ask`
(AQ-1), the hint to send `/ask`, the answer to a question about the state, the refusal to start the planning agent, the line of a router that could not
run, and the placeholder a reader that did not ask is shown. A project with no `language`, and a project whose tag has no table, gets the English
sentences it always got. The stand-in tree and adapter of test_ask.py; no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_runtime_language_ask.py
"""
from __future__ import annotations

from test_ask import (OWNER_KEY, PROFILES, SENDERS, accept, add_source, ask, direct_router, ops, ops_core, ops_say, roles,  # noqa: F401
                      tree, two)


def speak(tree_, tag):
    accept(tree_["path"], language=tag)


def test_the_configuration_read_carries_the_language_the_bridge_says_its_sentences_in(tree):
    assert ops.config(tree["path"])["language"] is None
    speak(tree, "pt-BR")
    assert ops.config(tree["path"])["language"] == "pt-BR"


# --- what `ask` answers when it cannot ------------------------------------------------------------------------------------------------------------------


def test_the_refusals_of_ask_are_in_the_projects_language(tree, monkeypatch):
    speak(tree, "pt-BR")
    assert ask(tree)["reply"] == "Este projeto não tem nenhuma fonte com versão para usar na resposta. Importe uma primeiro."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    for n in range(6):
        add_source(tree, f"doc-{n}", f"# Document {n}\n\nSome text about topic {n}.\n")
    assert ask(tree, "qual o prazo do contrato?")["reply"] == ("Nenhuma fonte deste projeto parece tratar disso. Indique uma com @<id>: "
                                                               "@doc-0, @doc-1, @doc-2, @doc-3, @doc-4, @doc-5.")
    assert ask(tree, " ".join(f"@doc-{n}" for n in range(6)) + " what is in them?")["reply"] == "Uma pergunta lê no máximo 5 fontes, e você indicou 6."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    add_source(tree, "ledger-a", "# Ledger\n" + "x" * (200 * 1024))
    add_source(tree, "ledger-b", "# Ledger\n" + "y" * (100 * 1024))
    assert ask(tree, "compare @ledger-a and @ledger-b")["reply"] == ("O texto destas fontes é grande demais para uma pergunta (no máximo 256 KiB no total): "
                                                                     "ledger-a (200 KiB), ledger-b (100 KiB). Indique menos fontes ou fontes menores.")
    monkeypatch.setattr(roles, "answer", lambda root=None, file=None: None)
    assert ask(tree)["reply"] == "Nenhuma skill desta instalação responde a partir das fontes ainda (asst-answer está planejada)."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_same_refusals_in_a_project_with_no_language_are_the_english_ones(tree, monkeypatch):
    assert ask(tree)["reply"] == "This project has no source with a version to answer from. Import one first."
    for tag in ("fr", "en"):
        speak(tree, tag)
        assert ask(tree)["reply"] == "This project has no source with a version to answer from. Import one first.", tag
    monkeypatch.setattr(roles, "answer", lambda root=None, file=None: None)
    assert ask(tree)["reply"] == "No skill answers from the sources in this checkout yet (asst-answer is planned)."


def test_a_checked_answer_has_its_frame_in_the_language_and_the_skills_own_words_are_not_touched(two):
    english = ask(two)
    assert english["answer"] == "found" and "Checked quote [" in english["reply"] and "\n\nRead: lease-contract (version 1), meeting-notes (version 1)" in english["reply"]
    speak(two, "pt-BR")
    portuguese = ask(two)
    assert portuguese["answer"] == "found" and portuguese["flags"] == []
    assert "Citação verificada [" in portuguese["reply"] and "Checked quote" not in portuguese["reply"]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert "\n\nLidas: lease-contract (versão 1), meeting-notes (versão 1)" in portuguese["reply"] and "Read:" not in portuguese["reply"]  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert "O prazo do contrato e de 12 meses" in portuguese["reply"], "the answer is the skill's own text, in the language of the question"
    speak(two, "fr")
    assert "Checked quote [" in ask(two)["reply"]


# --- the conversation ---------------------------------------------------------------------------------------------------------------------------------


def test_the_answer_to_a_question_about_the_state_is_in_the_projects_language(two):
    ask(two)
    english = ops_say.state_reply(two["path"])
    assert english == "No request is open. 1 finished.\nWhat waits for you: nothing."
    speak(two, "pt-BR")
    assert ops_say.state_reply(two["path"]) == "Nenhum pedido aberto. Concluídos: 1.\nO que espera por você: nada."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    said = ops.say(two["path"], "how are we doing?", channel="terminal")["reply"]
    assert said == "Nenhum pedido aberto. Concluídos: 1.\nO que espera por você: nada."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    speak(two, "fr")
    assert ops_say.state_reply(two["path"]) == english


def test_the_state_of_a_project_with_work_open_names_every_part_in_portuguese(two, monkeypatch):
    """Each line of the answer, from a status and a progress read that hold one of every kind of row."""
    state = {"requests": [{"id": 4, "title": "Launch", "state": "planned", "tasks": [
        {"id": 5, "title": "Copy", "state": "done"}, {"id": 6, "title": "Images", "state": "running"}, {"id": 7, "title": "Review", "state": "waiting"},
        {"id": 8, "title": "Post", "state": "ready"}, {"id": 9, "title": "Send", "state": "blocked", "note": "needs a key"},
        {"id": 10, "title": "Tidy", "state": "failed"}]}, {"id": 11, "title": "Later", "state": "requested", "tasks": []}],
        "held": [{"task_id": 8, "reason": "paused"}]}
    progress = {"progress": {"waiting_for_you": [{"kind": "plan", "title": "Launch", "pending_id": 12}, {"kind": "effect", "title": "Post", "pending_id": 13}]}}
    fake = type("Ops", (), {"status": staticmethod(lambda project: state), "progress": staticmethod(lambda project: progress)})
    monkeypatch.setattr(ops_say, "_ops", lambda: fake)
    expected = {
        None: ['Request 4, "Launch": 1 of 6 tasks done (Copy).', "Running now: Images.", "Waiting for you: Review.", 'Ready: task 8, "Post" (held: paused).',
               'Stuck: task 9, "Send", is blocked: needs a key.', 'Stuck: task 10, "Tidy", is failed.',
               'Request 11, "Later": recorded; it waits for its route.', 'What waits for you: plan "Launch" (decision 12); request "Post" (decision 13).'],
        "pt-BR": ['Pedido 4, "Launch": 1 de 6 tarefas concluídas (Copy).', "Rodando agora: Images.", "Esperando você: Review.", 'Pronta: tarefa 8, "Post" (retida: paused).',  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
                  'Travada: tarefa 9, "Send", status bloqueado: needs a key.', 'Travada: tarefa 10, "Tidy", status com falha.',
                  'Pedido 11, "Later": registrado; espera pelo encaminhamento.', 'O que espera por você: plano "Launch" (decisão 12); pedido "Post" (decisão 13).'],  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    }
    for tag, lines in expected.items():
        assert ops_say.state_reply(two["path"], cfg={"language": tag}).splitlines() == lines, tag
    assert ops_say.state_reply(two["path"], "Say hello.", {"language": "pt-BR"}).endswith("\n\nO agente de planejamento propõe: Say hello.")  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    assert ops_say.state_reply(two["path"], "Say hello.", {}).endswith("\n\nThe planning agent proposes: Say hello.")
    many = [{"id": n, "title": f"T{n}", "state": "done"} for n in range(20, 28)]
    state["requests"] = [{"id": 4, "title": "Big", "state": "planned", "tasks": many}]
    assert "(T20, T21, T22, T23, T24 and 3 more)" in ops_say.state_reply(two["path"], cfg={})
    assert "(T20, T21, T22, T23, T24 e mais 3)" in ops_say.state_reply(two["path"], cfg={"language": "pt-BR"})


def test_a_direct_turn_ends_with_the_hint_in_the_language(two, monkeypatch):
    direct_router(two, monkeypatch)
    speak(two, "pt-BR")
    said = ops.say(two["path"], "thanks, nothing else", channel="terminal")["reply"]
    assert said.startswith("Nenhum pedido aberto.") and said.endswith("\n\nPara responder a partir das suas fontes, envie /ask <question>.")
    assert "Proposes" not in said and "O agente de planejamento propõe: nothing to do." in said  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    speak(two, None)
    assert ops.say(two["path"], "thanks again", channel="terminal")["reply"].endswith("\n\nTo answer from your sources, send /ask <question>.")


def test_the_planning_agent_that_may_not_start_is_told_in_the_language(two, monkeypatch):
    monkeypatch.setattr(ops_say, "_planning_may_start", lambda ctx: (False, "its day is spent"))
    assert ops.say(two["path"], "plan the launch", channel="terminal")["reply"] == "The planning agent may not start now: its day is spent. Nothing was run."
    speak(two, "pt-BR")
    assert ops.say(two["path"], "plan the launch", channel="terminal")["reply"] == "O agente de planejamento não pode começar agora: its day is spent. Nada foi executado."  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_line_of_a_router_that_could_not_run_and_the_queued_request_are_in_the_language(two, monkeypatch):
    ctx = ops_core.context(two["path"])
    fake = type("Ops", (), {"request": staticmethod(lambda project, text, **kw: {"request": 3}),
                            "route": staticmethod(lambda project, request_id, channel=None: {"failure": {"reason": "boom"}, "run_id": None})})
    monkeypatch.setattr(ops_say, "_ops", lambda: fake)
    monkeypatch.setattr(ops_say, "_planning_may_start", lambda ctx: (True, ""))
    assert ops_say._say_route(two["path"], ctx, "plan it", 10 ** 9, "terminal")[0] == "The router could not run: boom"
    speak(two, "pt-BR")
    ctx = ops_core.context(two["path"])
    assert ops_say._say_route(two["path"], ctx, "plan it", 10 ** 9, "terminal")[0] == "O roteador não pôde rodar: boom"  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column
    fake.route = staticmethod(lambda project, request_id, channel=None: {"queued": True})
    assert ops_say._say_route(two["path"], ctx, "plan it", 10 ** 9, "terminal")[0] == (
        "Registrado como pedido 3. O agente de planejamento o encaminha quando a execução terminar.")  # validate: allow english-only -- the expected Portuguese sentence of the phrase table's pt-BR column


def test_the_placeholder_a_reader_that_did_not_ask_is_shown_is_in_the_language(two):
    accept(two["path"], policies=PROFILES, messaging={"senders": SENDERS})
    speak(two, "pt-BR")
    ops.say(two["path"], "/ask qual o prazo do contrato?", channel="messaging", sender=OWNER_KEY)
    request = ops.conversation(two["path"], channel="mcp")["messages"][-1]
    assert request["text"].startswith("(respondido com base nas fontes: pedido ")
    speak(two, None)
    assert ops.conversation(two["path"], channel="mcp")["messages"][-1]["text"].startswith("(answered from the sources: request ")


def test_what_a_shell_reads_keeps_the_english_status_word_in_a_portuguese_project(two):
    speak(two, "pt-BR")
    out = ask(two)
    state = ops.status(two["path"])
    [row] = [r for r in state["requests"] if r["id"] == out["request_id"]]
    assert row["state"] == "done", "status, the API and the MCP mode read the operations layer: the store's word"
    store, conn = two["ctx"]["store"], two["ctx"]["conn"]
    assert store.task_get(conn, out["request_id"])["state"] == "done" and store.task_run_get(conn, out["run_id"])["status"] == "ok"
    assert "done" in repr(ops.status(two["path"])["requests"]) and "concluído" not in repr(ops.status(two["path"]))

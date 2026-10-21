"""A table command typed on a phone is answered with a sentence, never the operation's JSON (package S2; runtime/messaging_bridge.py `command_sentence`, limits L62 and the
live case "/cancel 8" that answered {"request": 8, "cancelled": [8], ...}). Over the stand-in operations object, which answers `say` with the JSON the real operations layer
writes for a command (`json.dumps(result, ensure_ascii=False, indent=1)`), and the stand-in messenger. Offline, no model; the sentences are this file's own literals, in both
languages of the phrase table. The oracle is the raw text of what the stand-in messenger was sent: no JSON character, no key of the operation's result, and the literal
sentence. The vacuity case removes the conversion and shows the same oracle sees the JSON.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_command_sentences.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_messaging import wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

bridge = st.load("messaging_bridge")

CANCEL = {"request": 8, "cancelled": [8], "stopped": [], "pending": [12], "already": False}
CASES = [
    # (line, the result the operation returns, the English sentence, the Portuguese sentence)
    ("/cancel 8", CANCEL, "Request 8 cancelled.", "Pedido 8 cancelado."),
    ("/cancel 8", dict(CANCEL, cancelled=[], pending=[], already=True), "Request 8 was already cancelled.", "O pedido 8 j\u00e1 estava cancelado."),
    ("/stop-task 5", {"request": 2, "task": 5, "cancelled": [], "stopped": [5], "pending": [], "already": False}, "Task 5 stopped.", "Tarefa 5 parada."),
    ("/stop-task 5", {"request": 2, "task": 5, "cancelled": [], "stopped": [], "pending": [], "already": True}, "Task 5 was not running.", "A tarefa 5 n\u00e3o estava em execu\u00e7\u00e3o."),
    ("/retry 5", {"id": 5, "state": "ready", "note": None}, "Task 5 is ready to run again.", "A tarefa 5 est\u00e1 pronta para rodar de novo."),
    ("/status", {"config": {"file": "runtime.json", "sha256": "a" * 64}, "requests": [{"id": 1, "state": "running", "tasks": []}, {"id": 2, "state": "done", "tasks": []},
                                                                                   {"id": 3, "state": "planned", "tasks": []}, {"id": 4, "state": "cancelled", "tasks": []}],
                 "pending": [{"id": 9, "kind": "plan"}], "documents": [], "board": None, "held": []},
     "Open requests: 2. Waiting for you: 1.", "Pedidos abertos: 2. Esperando voc\u00ea: 1."),
    ("/status", {"requests": [{"id": 1, "state": "running", "tasks": []}], "pending": [], "held": [{"task_id": 5, "agent": None, "reason": "dispatch off", "at": "2026-10-21T10:00:00Z",
                                                                                                "next": "python3 runtime/cli.py dispatch --project /x"}]},
     "Open requests: 1. Waiting for you: 0.\nTask 5 is held: dispatch off.", "Pedidos abertos: 1. Esperando voc\u00ea: 0.\nA tarefa 5 est\u00e1 retida: dispatch off."),
    ("/attachments", {"held": [{"id": 1}, {"id": 2}], "recent": [], "limits": {}}, "Files waiting for your answer: 2.", "Arquivos esperando sua resposta: 2."),
    ("/attachments", {"held": [], "recent": []}, "Files waiting for your answer: 0.", "Arquivos esperando sua resposta: 0."),
    ("/status", {"unexpected": True}, "Open requests: 0. Waiting for you: 0.", "Pedidos abertos: 0. Esperando voc\u00ea: 0."),
]
KEYS = ("next", "request", "cancelled", "stopped", "pending", "already", "task", "requests", "held", "recent", "config", "sha256", "state", "id")
JSON_CHARACTERS = '{}[]"'


def as_the_operations_layer_writes_it(result):
    return json.dumps(result, ensure_ascii=False, indent=1, default=str)


def ask(world, line, result, language=None):
    if language:
        world.config["language"] = language
    world.fake.answers["say"] = lambda project, text=None, **k: {"reply": as_the_operations_layer_writes_it(result), "request_id": None, "pending_id": None, "ran": False, "queued": False}
    before = len(world.texts())
    world.say(line)
    assert wait_for(lambda: len(world.texts()) > before)
    return world.texts()[before:]


def leaks_json(text):
    """The test's own oracle: a JSON character, or a key of an operation's result, in what a phone was sent."""
    return any(c in text for c in JSON_CHARACTERS) or any(f"{k}\"" in text or f"\"{k}" in text for k in KEYS)


@pytest.mark.parametrize("line, result, english, portuguese", CASES)
def test_a_table_command_on_a_phone_is_answered_with_a_sentence_in_english(world, line, result, english, portuguese):
    sent = ask(world, line, result)
    assert sent == [english] and not leaks_json(sent[0]) and "cli.py" not in sent[0]


@pytest.mark.parametrize("line, result, english, portuguese", CASES)
def test_a_table_command_on_a_phone_is_answered_with_a_sentence_in_the_projects_language(world, line, result, english, portuguese):
    sent = ask(world, line, result, "pt-BR")
    assert sent == [portuguese] and not leaks_json(sent[0])


def test_a_result_the_table_has_no_sentence_for_is_done_and_never_json(world):
    sent = ask(world, "/retry 7", ["a", "list"])      # not even a dict
    assert sent != [] and not leaks_json(sent[0])
    sent = ask(world, "/attachments", {"held": "x"})
    assert not leaks_json(sent[0])


@pytest.mark.parametrize("line, reply", [("/progress", "Nothing new since yesterday."), ("/new write the plan", "The plan is ready."), ("hello there", "{\"a\": 1}"), ("/status", "error: nope")])
def test_what_is_not_the_json_of_a_table_command_is_left_as_it_was(world, line, reply):
    world.fake.answers["say"] = {"reply": reply, "request_id": None, "pending_id": None, "ran": False, "queued": False}
    world.say(line)
    assert wait_for(lambda: world.texts()) and world.texts() == [reply]


def test_the_checker_sees_the_json_when_the_conversion_is_taken_away(world, monkeypatch):
    """The vacuity case: with the conversion planted away the raw JSON reaches the phone, and the same oracle reports it."""
    monkeypatch.setattr(bridge.Bridge, "command_sentence", lambda self, project, text, said: said)
    sent = ask(world, "/cancel 8", CANCEL)
    assert leaks_json(sent[0]) and '"request": 8' in sent[0]

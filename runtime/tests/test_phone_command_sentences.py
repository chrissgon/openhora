"""A table command typed on a phone is answered with a sentence, never the operation's JSON (package S2; runtime/messaging_bridge.py `command_sentence`, limits L62 and the
live case "/cancel 8" that answered {"request": 8, "cancelled": [8], ...}). Over the stand-in operations object, which answers `say` with the JSON the real operations layer
writes for a command (`json.dumps(result, ensure_ascii=False, indent=1)`), and the stand-in messenger. Offline, no model; the sentences are phrase keys with their fields (runtime/tests/phrase_kit.py), in both
languages of the phrase table. The oracle is the raw text of what the stand-in messenger was sent: no JSON character, no key of the operation's result, and the sentence of the key. The vacuity case removes the conversion and shows the same oracle sees the JSON.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_phone_command_sentences.py
"""
from __future__ import annotations

import json

import pytest

import phrase_kit as pk
import standin_tree as st
from test_messaging import wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

bridge = st.load("messaging_bridge")
PT = {"language": "pt-BR"}

CANCEL = {"request": 8, "cancelled": [8], "stopped": [], "pending": [12], "already": False}
CASES = [
    # (line, the result the operation returns, the lines said: (phrase key, its fields), one per line of the sentence)
    ("/cancel 8", CANCEL, [("CMD_CANCELLED", {"n": 8})]),
    ("/cancel 8", dict(CANCEL, cancelled=[], pending=[], already=True), [("CMD_CANCEL_ALREADY", {"n": 8})]),
    ("/stop-task 5", {"request": 2, "task": 5, "cancelled": [], "stopped": [5], "pending": [], "already": False}, [("CMD_TASK_STOPPED", {"n": 5})]),
    ("/stop-task 5", {"request": 2, "task": 5, "cancelled": [], "stopped": [], "pending": [], "already": True}, [("CMD_TASK_NOT_RUNNING", {"n": 5})]),
    ("/retry 5", {"id": 5, "state": "ready", "note": None}, [("CMD_TASK_RETRY", {"n": 5})]),
    ("/status", {"config": {"file": "runtime.json", "sha256": "a" * 64}, "requests": [{"id": 1, "state": "running", "tasks": []}, {"id": 2, "state": "done", "tasks": []},
                                                                                   {"id": 3, "state": "planned", "tasks": []}, {"id": 4, "state": "cancelled", "tasks": []}],
                 "pending": [{"id": 9, "kind": "plan"}], "documents": [], "board": None, "held": []},
     [("CMD_STATUS", {"open": 2, "waiting": 1})]),
    ("/status", {"requests": [{"id": 1, "state": "running", "tasks": []}], "pending": [], "held": [{"task_id": 5, "agent": None, "reason": "dispatch off", "at": "2026-10-21T10:00:00Z",
                                                                                                "next": "python3 runtime/cli.py dispatch --project /x"}]},
     [("CMD_STATUS", {"open": 1, "waiting": 0}), ("CMD_STATUS_HELD", {"n": 5, "reason": "dispatch off"})]),
    ("/attachments", {"held": [{"id": 1}, {"id": 2}], "recent": [], "limits": {}}, [("CMD_ATTACHMENTS", {"n": 2})]),
    ("/attachments", {"held": [], "recent": []}, [("CMD_ATTACHMENTS", {"n": 0})]),
    ("/status", {"unexpected": True}, [("CMD_STATUS", {"open": 0, "waiting": 0})]),
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
    for thread in list(world.bridge.threads):      # the job that sent the reply has ended: the next line meets a free slot
        thread.join(10)
    return world.texts()[before:]


def says(sent, lines, cfg=None):
    """True when `sent` (what the phone was sent) is one text whose lines are, in order, the sentences of `lines` ((key, fields) pairs) in the language of `cfg`."""
    if len(sent) != 1:
        return False
    texts = sent[0].split("\n")
    return len(texts) == len(lines) and all(pk.said(text, key, cfg, **fields) for text, (key, fields) in zip(texts, lines))


def leaks_json(text):
    """The test's own oracle: a JSON character, or a key of an operation's result, in what a phone was sent."""
    return any(c in text for c in JSON_CHARACTERS) or any(f"{k}\"" in text or f"\"{k}" in text for k in KEYS)


@pytest.mark.parametrize("line, result, lines", CASES)
def test_a_table_command_on_a_phone_is_answered_with_a_sentence_in_english(world, line, result, lines):
    sent = ask(world, line, result)
    assert says(sent, lines), sent
    assert not leaks_json(sent[0]) and "cli.py" not in sent[0]


@pytest.mark.parametrize("line, result, lines", CASES)
def test_a_table_command_on_a_phone_is_answered_with_a_sentence_in_the_projects_language(world, line, result, lines):
    sent = ask(world, line, result, "pt-BR")
    assert says(sent, lines, PT), sent
    assert not leaks_json(sent[0])


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


def test_a_held_tasks_reason_that_carries_a_command_or_a_path_is_cut_by_the_net_and_never_reaches_the_phone(world):
    held = {"task_id": 5, "reason": "waiting: run python3 runtime/cli.py dispatch --project /Users/zed/proj --sha256 abc", "next": "uv run python3 runtime/cli.py dispatch"}
    sent = ask(world, "/status", {"requests": [], "pending": [], "held": [held]})
    text = " ".join(sent)
    assert "cli.py" not in text and "--project" not in text and "/Users/zed" not in text and "uv run" not in text and "Task 5 is held" in text      # literal: the net cuts the reason, so the held line is no longer the whole sentence of CMD_STATUS_HELD


@pytest.mark.parametrize("result", [
    {"request": ["a", "list"], "cancelled": [8], "already": False},      # a result field that is not a whole number: the number the person typed
    {"request": {"x": 1}, "already": False},
    {"request": True, "already": False},
    {"request": "8; rm -rf /", "already": False},
])
def test_the_number_in_a_sentence_is_a_whole_number_of_the_result_or_the_one_typed_and_never_anything_else(world, result):
    sent = ask(world, "/cancel 8", result)
    assert says(sent, [("CMD_CANCELLED", {"n": 8})]), sent


def test_a_held_task_without_a_whole_number_is_not_listed(world):
    sent = ask(world, "/status", {"requests": [], "pending": [], "held": [{"task_id": ["x"], "reason": {"a": 1}}]})
    assert says(sent, [("CMD_STATUS", {"open": 0, "waiting": 0})]), sent


def test_a_result_of_the_wrong_shape_is_still_a_sentence_and_never_an_error(world):
    sent = ask(world, "/status", {"requests": [1, "x", None], "pending": 5, "held": "x"})
    assert says(sent, [("CMD_STATUS", {"open": 0, "waiting": 0})]), sent
    sent = ask(world, "/attachments", {"held": 7})
    assert says(sent, [("CMD_ATTACHMENTS", {"n": 0})]), sent

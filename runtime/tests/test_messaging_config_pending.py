"""A line that arrives while the project's configuration is not accepted gets one plain sentence, once per chat and per hash of the file (slice S12, runtime/messaging_bridge.py
`config_pending`; limit L62). Live: the maintainer's "Ola" got no reply after runtime.json changed and before accept-config; the only trace was a line in the service log.

Over the stand-in operations object and the stand-in messenger of test_messaging.py. Every expectation is a literal of this file; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_config_pending.py
"""
from __future__ import annotations

import re

import pytest

import phrase_kit as pk
import standin_tree as st
from test_messaging import OPEN_POLICY, SENDER, wait_for, world  # noqa: F401  (the stand-in bridge)

PT = {"language": "pt-BR"}
FIRST, SECOND = "a" * 64, "b" * 64


def pending(world, sha=FIRST, language=None, senders=(SENDER,)):
    """The configuration is a file nobody accepted, listing `senders` for telegram."""
    world.config = {"messaging": {"senders": {"telegram": list(senders)}, "notices": "text", "page_url": None}, "channels": {"messaging": OPEN_POLICY}}
    world.fake.config_answer = lambda project: {"path": "/work/northwind-shop/docs/workbench/runtime.json", "sha256": sha, "accepted": False,
                                                "data_dir": str(world.tmp / "data"), "language": language, **world.config}


def on_the_phone_violations(texts) -> list:
    """What a sentence on a phone must not hold, from the test's own patterns: a hash, a path, a command, an operation's name, a slash command."""
    found = []
    for text in texts:
        if re.search(r"[0-9a-f]{12,}", text):
            found.append("hash")
        if re.search(r"/work/|runtime\.json|docs/workbench|\.py\b", text):
            found.append("path")
        if re.search(r"accept-config|--sha256|--widen|python3|uv run", text):
            found.append("command")
        if re.search(r"(^|\s)/[a-z]", text):
            found.append("slash")
        if text.startswith("error:"):
            found.append("error")
    return sorted(set(found))


def told(world, count, cfg=None):
    """True when the chat was sent the sentence `count` times and nothing else."""
    texts = world.texts()
    return len(texts) == count and all(pk.said(t, "CONFIG_PENDING", cfg) for t in texts)


def test_a_line_while_the_configuration_is_not_accepted_gets_one_plain_sentence_and_is_not_acted_on(world):
    pending(world)
    world.say("Ola")
    assert told(world, 1), world.texts()
    assert world.calls("say") == [] and world.calls("pending") == [] and world.fake.named("route_queued") == []
    assert on_the_phone_violations(world.texts()) == []


def test_the_sentence_is_said_once_per_chat_and_per_hash_of_the_file(world):
    pending(world)
    world.say("Ola")
    world.say("Are you there?")
    world.say(None, action="7:approve")
    assert told(world, 1), "the same hash: once"
    pending(world, sha=SECOND)
    world.say("Ola again")
    world.say("and again")
    assert told(world, 2), "a changed file is told once more"
    pending(world, sha=FIRST)
    world.say("back")
    assert told(world, 2), "a hash told before is not told again"
    assert world.calls("say") == []


def test_the_sentence_is_in_the_projects_language(world):
    pending(world, language="pt-BR")
    world.say("Ola")
    assert told(world, 1, PT), world.texts()
    assert on_the_phone_violations(world.texts()) == []


def test_a_sender_the_file_does_not_list_and_a_group_chat_are_told_nothing(world):
    pending(world, senders=("9999",))
    world.say("Ola")
    assert world.sent() == []
    pending(world)
    world.say("Ola", chat="-100123", private=False)
    world.say("   ")
    assert world.sent() == [] and world.calls("say") == []


def test_an_accepted_configuration_is_served_as_before_and_tells_nothing(world):
    world.say("hello")
    assert wait_for(lambda: world.texts() == ["Noted."])
    assert len(world.calls("say")) == 1


def test_the_log_still_says_the_update_was_dropped_and_holds_no_sentence_of_the_phone(world):
    pending(world)
    world.say("Ola")
    assert world.log.count("dropped an update from an unlisted sender") == 1 and not [line for line in world.log if "configuration changed" in line]


def test_vacuity_the_oracle_flags_a_sentence_with_a_hash_a_path_or_a_command():
    for bad, kind in ((f"The configuration {FIRST} changed", "hash"), ("Edit /work/northwind-shop/docs/workbench/runtime.json", "path"),
                      ("Run accept-config --sha256 now", "command"), ("Send /pending", "slash"), ("error: the configuration changed", "error")):
        assert kind in on_the_phone_violations([bad]), bad

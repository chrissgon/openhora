"""The "typing..." indicator while a reply is prepared (slice S10; runtime/messaging_typing.py, `Bridge.line`, `Messenger.typing`), over the stand-in messenger of test_messaging.py
(its verb `typing` records each call in typing.jsonl; fail_typing.json makes it fail). Offline, no model, no network; every name is invented.

THE ORACLE counts the lines of typing.jsonl and the messages of sent.jsonl, which the stand-in writes (the test's own count, never the bridge's). The vacuity cases plant the
two facts the rest reads: a plain line over a slow job does show the indicator (so a count of zero elsewhere means something), and an indicator that is not stopped goes on
(so "it stopped" means something).

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_typing.py
"""
from __future__ import annotations

import json
import threading
import time

import standin_tree as st
from test_messaging import SENDER, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

indicator = st.load("messaging_typing")


def typed(world):
    path = world.standin / "typing.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.is_file() else []


def quick(monkeypatch, delay=0.0, interval=0.15):
    monkeypatch.setattr(indicator, "START_DELAY", delay)
    monkeypatch.setattr(indicator, "INTERVAL", interval)


def slow_say(world, seconds):
    def answer(project, **fields):
        time.sleep(seconds)
        return {"reply": "Noted.", "request_id": 1, "pending_id": None, "ran": True, "queued": False}
    world.fake.answers["say"] = answer


# --- the bridge --------------------------------------------------------------------------------------------------------------------------------------------


def test_a_plain_line_over_a_slow_job_shows_the_indicator_again_and_again_and_stops_before_the_reply(world, monkeypatch):      # also the vacuity case
    quick(monkeypatch)
    world.caps(typing=True)
    slow_say(world, 0.9)
    world.say("tell me about the shop")
    assert wait_for(lambda: world.texts() == ["Noted."], 10)
    count = len(typed(world))
    assert count >= 3 and {t["chat"] for t in typed(world)} == {SENDER}      # once at the start, then refreshed
    time.sleep(0.6)
    assert len(typed(world)) == count      # nothing after the reply went out


def test_a_typed_command_never_shows_the_indicator(world, monkeypatch):
    quick(monkeypatch)
    world.caps(typing=True)
    slow_say(world, 0.8)
    world.say("/new tell me about the shop")
    assert wait_for(lambda: world.texts() == ["Noted."], 10)
    assert typed(world) == []


def test_a_job_that_ends_at_once_shows_nothing(world):
    world.caps(typing=True)      # the default start delay: an answer of code is not announced
    world.say("tell me about the shop")
    assert wait_for(lambda: world.texts() == ["Noted."])
    time.sleep(0.7)
    assert typed(world) == []


def test_a_platform_that_does_not_declare_typing_is_not_asked(world, monkeypatch):
    quick(monkeypatch)
    slow_say(world, 0.6)
    world.say("tell me about the shop")
    assert wait_for(lambda: world.texts() == ["Noted."], 10)
    assert typed(world) == []


def test_a_failure_of_the_indicator_changes_nothing_of_the_reply(world, monkeypatch):
    quick(monkeypatch)
    world.caps(typing=True)
    (world.standin / "fail_typing.json").write_text("true")
    slow_say(world, 0.6)
    world.say("tell me about the shop")
    assert wait_for(lambda: world.texts() == ["Noted."], 10)
    assert len(typed(world)) >= 1 and world.log == []      # it was tried, and nothing was logged for it


# --- the helper over a fake messenger (no subprocess) -------------------------------------------------------------------------------------------------------


class Fake:
    def __init__(self, typing=True, fail=False):
        self.calls, self.flag, self.fail = [], typing, fail

    def capabilities(self):
        return {"typing": self.flag}

    def typing(self, chat):
        self.calls.append(chat)
        if self.fail:
            raise RuntimeError("boom")


def test_the_indicator_is_asked_again_every_interval_until_the_limit(world):
    fake = Fake()
    handle = indicator.Typing(fake, interval=0.05, limit=0.3, delay=0.0).begin("1", "hello")
    assert wait_for(lambda: len(fake.calls) >= 3, 5)
    time.sleep(0.5)      # past the limit
    stopped_at = len(fake.calls)
    time.sleep(0.3)
    assert len(fake.calls) == stopped_at and 3 <= stopped_at <= 8
    handle.stop()


def test_stop_ends_the_indicator_and_is_idempotent_and_an_unstopped_one_goes_on(world):
    fake = Fake()
    handle = indicator.Typing(fake, interval=0.05, limit=60, delay=0.0).begin("1", "hello")
    assert wait_for(lambda: len(fake.calls) >= 2, 5)
    handle.stop()
    handle.stop()
    done = len(fake.calls)
    time.sleep(0.3)
    assert len(fake.calls) == done
    other = Fake()
    kept = indicator.Typing(other, interval=0.05, limit=60, delay=0.0).begin("1", "hello")      # vacuity: the same oracle sees an indicator that is not stopped
    assert wait_for(lambda: len(other.calls) >= 4, 5)
    kept.stop()


def test_a_failing_messenger_and_a_messenger_without_the_verb_are_ignored(world):
    failing = Fake(fail=True)
    handle = indicator.Typing(failing, interval=0.05, limit=60, delay=0.0).begin("1", "hello")
    assert wait_for(lambda: len(failing.calls) >= 2, 5)      # it is asked again after a failure
    handle.stop()

    class Bare:
        def capabilities(self):
            return {"typing": True}
    bare = indicator.Typing(Bare(), delay=0.0).begin("1", "hello")
    assert bare.thread is None
    bare.stop()


def test_wanted_reads_the_line_and_the_capability():
    kinds = indicator.Typing(Fake())
    assert kinds.wanted("hello") and not kinds.wanted("/ask hello") and not kinds.wanted("  /status") and not kinds.wanted("") and not kinds.wanted(None)
    assert not indicator.Typing(Fake(typing=False)).wanted("hello")
    threads = threading.active_count()
    indicator.Typing(Fake()).begin("1", "/ask x").stop()
    assert threading.active_count() == threads      # a command starts no thread

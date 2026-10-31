"""A greeting in question form is never the OK of a plan, and a plan's yes reads the last message again (package L64H, limits L64 and L65; the kind `plan-confirm` of runtime/messaging_turn.py,
`greeting.as_question`, `Bridge.plan_decide`, `Bridge.still_last`).

The maintainer's decision (2026-10-26): a greeting written as a question ("oi, tudo bem?", "tudo bem?") is not the yes to a "Shall I go ahead?"; "beleza", "tudo bem" and "ok, beleza" stay yes
words. The rule is in the kind `plan-confirm` and nowhere else, so the reminders, the writes and the interpreter read `natural.confirm_kind` as they did. The line goes on as any other line and
gets the greeting; no read runs and no model is asked. The second part: with the question the last message, a message another thread sends between the reading of the word and the start of the
confirmed call (here, inside the read of the live plan) ends the yes: `PLAN_NOT_LAST`, the plan waits; a reply to the question names it and needs no last message. The real bridge over the real
operations layer and the stand-in messenger (plan_bridge_kit.py); each test reads the one place a read runs (its own literal count). Wording is by phrase key. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_plan_greeting.py
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import standin_tree as st
from plan_bridge_kit import OWNER_ID, OWNER_KEY, brig, bridge, ops, phrases, rig, wait_for, world  # noqa: F401
from test_service import WAIT  # noqa: F401  (named here as test_messaging_plan_confirm.py does: the selector follows the importers of a changed test file, and the kit between them hides this file)
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

QUESTIONS = ["oi, tudo bem?", "tudo bem?", "beleza?", "oi tudo bem? \U0001f642", "tudo bem\uff1f"]
YES_WORDS = ["tudo bem", "beleza", "ok, beleza", "oi, tudo bem"]      # "tudo bem? sim" left on 2026-10-30: a question glyph anywhere makes a line a question form, and that is no OK (test_plan_question_form.py)


def t(brig, key, **fields):
    return phrases.text(key, brig.rig.cfg, **fields)


def reads(brig):
    return [r["name"] for r in brig.reads]


def greeted(brig, before):
    """True when the chat was sent the greeting after `before` messages."""
    return wait_for(lambda: len(brig.texts()) > before and brig.texts()[-1].startswith(t(brig, "GREET_HEAD")))


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_greeting_question_is_the_greeting_and_never_the_ok_of_the_plan_that_is_last(brig, line):
    brig.ask()
    before = len(brig.texts())
    brig.say(line)
    assert greeted(brig, before) and brig.idle()
    assert reads(brig) == [] and brig.rig.calls == [], "no read ran and no model was asked"


@pytest.mark.parametrize("line", QUESTIONS)
def test_a_greeting_question_sent_as_a_reply_to_the_question_is_the_greeting_too(brig, line):
    brig.ask()
    before = len(brig.texts())
    brig.say(line, reply_to=brig.question_id())
    assert greeted(brig, before) and brig.idle()
    assert reads(brig) == [] and brig.rig.calls == []


@pytest.mark.parametrize("line", YES_WORDS)
def test_a_greeting_word_that_is_no_question_stays_the_yes_of_the_plan_that_is_last(brig, line):
    brig.ask()
    brig.say(line)
    assert wait_for(lambda: reads(brig) == ["items"]) and brig.idle()
    assert reads(brig) == ["items"], "the confirmed call ran once"


def test_vacuity_without_the_rule_a_greeting_question_runs_the_read(brig, monkeypatch):
    brig.ask()
    messaging_turn = st.load("messaging_turn")
    monkeypatch.setattr(messaging_turn.greeting, "as_question", lambda *args, **kwargs: False)
    monkeypatch.setattr(messaging_turn, "card_words", SimpleNamespace(question_form=lambda line: False))      # the other rule that keeps a question from being the OK (PLAN-QUESTION-FORM)
    brig.say("tudo bem?")
    assert wait_for(lambda: reads(brig) == ["items"]), "the same counter that is empty above sees the read when the rule is gone"


# --- the yes reads the last message again ------------------------------------------------------------------------------------------------------------


def test_a_message_sent_while_the_live_plan_is_read_ends_the_yes_and_the_plan_waits(brig, monkeypatch):
    brig.ask()
    real = ops.plan_live
    once = []

    def plan_live(*args, **kwargs):
        if not once:
            once.append(True)
            brig.bridge.reply(OWNER_ID, "A reminder: water the plants.")      # a job thread delivers a reminder inside the read
        return real(*args, **kwargs)
    monkeypatch.setattr(ops, "plan_live", plan_live)
    brig.say("sim")
    assert wait_for(lambda: brig.texts()[-1] == t(brig, "PLAN_NOT_LAST")) and brig.idle()
    assert reads(brig) == [] and brig.rig.calls == []
    assert ops.plan_live(brig.rig.world["path"], OWNER_KEY) is not None, "the plan waits"
    monkeypatch.setattr(ops, "plan_live", real)
    brig.say("sim", reply_to=brig.question_id())      # a reply names the question: it needs no last message
    assert wait_for(lambda: reads(brig) == ["items"]) and brig.idle()


def test_vacuity_with_the_last_message_not_read_again_the_same_yes_runs_the_read(brig, monkeypatch):
    brig.ask()
    real = ops.plan_live
    once = []

    def plan_live(*args, **kwargs):
        if not once:
            once.append(True)
            brig.bridge.reply(OWNER_ID, "A reminder: water the plants.")
        return real(*args, **kwargs)
    monkeypatch.setattr(ops, "plan_live", plan_live)
    monkeypatch.setattr(bridge.Bridge, "still_last", lambda self, chat, last: True)
    brig.say("sim")
    assert wait_for(lambda: reads(brig) == ["items"]), "the counter sees the read when the second read of the last message is gone"

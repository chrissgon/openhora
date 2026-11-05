"""The live case of 2026-10-20, end to end (package S2): "Agende ... no google" opens the card of an event on the person's own calendar, the person types "Aprovo", and the event is
written exactly as the card's button would write it. Over the real operations layer, the W1 stand-in writers (test_calendar_write.py's world) and the stand-in messenger of
test_messaging.py; no model, no network. A sender whose profile lacks the grant `approve-effect-calendar` writes nothing with the word, as with the button.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_card_words_live.py
"""
from __future__ import annotations

import json

import phrase_kit as pk
import standin_tree as st
from test_messaging_natural_writes import OWNER, day, forget  # noqa: F401  (the day fixture and its project)
from test_calendar_write import world  # noqa: F401  (the calendar world `day` is built on)
import pytest
from closed_heads import closed_heads, tier1_forms  # noqa: F401  (S41-11: the claim of the write families and of every closed form, as fixtures: these tests are about the readers and resolvers, not the claim)

pytestmark = pytest.mark.usefixtures("tier1_forms")      # S41-11: every closed form claims a line in this file, as it did

ops = st.load("ops")

LINE = "marca dentista quinta \u00e0s 10h no google"      # the invented line of test_messaging_natural_writes.py


def grant_the_calendar(day):
    file = day.path + "/docs/workbench/runtime.json"
    raw = json.loads(open(file).read())
    raw["policies"]["owner"] = [*raw["policies"]["owner"], "approve-effect-calendar"]
    open(file, "w").write(json.dumps(raw))
    shown = ops.config(day.path)
    ops.accept_config(day.path, shown["sha256"], widen=shown["widening_sha256"])


def writes(day):
    return [r for r in day.world["google"].requests if r["method"] == "POST" and r["path"] != "/token"]


def test_the_same_word_writes_nothing_for_a_profile_without_the_calendar_grant(day):
    day.say(OWNER, LINE)
    day.say(OWNER, "Aprovo")
    assert writes(day) == [] and not day.world["google"].events


def test_a_word_after_another_message_has_no_card_to_decide_and_writes_nothing(day):
    grant_the_calendar(day)
    day.say(OWNER, LINE)
    day.say(OWNER, "/help")      # any other message the bridge sends is the last one now
    assert day.texts(OWNER)[-1].startswith("Commands:")
    day.say(OWNER, "Aprovo")
    assert writes(day) == []



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


def test_a_typed_aprovo_writes_the_event_of_the_card_that_is_the_last_message(day):
    grant_the_calendar(day)
    day.say(OWNER, LINE)
    assert writes(day) == [] and any(pk.said(t, "TITLE_CAL_CREATE") for t in day.texts(OWNER))
    day.say(OWNER, "Aprovo")
    assert len(writes(day)) == 1 and len(day.world["google"].events) == 1
    assert day.texts(OWNER)[-1] != "Aprovo" and "{" not in day.texts(OWNER)[-1]


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


def test_a_rolled_day_said_with_the_card_in_the_same_turn_does_not_end_the_word(day):
    grant_the_calendar(day)
    day.say(OWNER, "marca dentista \u00e0s 8h no google")      # 08:00 has passed on the test's clock (09:00): the day rolls, and the bridge says so after the card
    texts = day.texts(OWNER)
    assert pk.said(texts[0], "TITLE_CAL_CREATE") and len(texts) == 2 and pk.said(texts[1], "NT_ROLLED", time="08:00")
    day.say(OWNER, "Aprovo")
    assert len(writes(day)) == 1

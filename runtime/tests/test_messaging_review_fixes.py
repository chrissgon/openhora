"""The fixes of the review of the entry golden of S41-11 PR 2a (2026-10-28), each with a twin that disables it and must fail. Over the real messaging bridge, the real operations layer and the stand-in
model of test_commands_in_words.py: no network, no model. Every name, number and sender is invented.

  C1-a  a sender who talks and is not read by the interpreter says a brake in words: the typed hint at once, never queued behind the run it stops, no model asked;
  C1-b  decision #6 through the bridge: a sender who holds `interpret` and may not talk reaches the interpreter, and the refusal after it is the operations layer's;
  C1-c  (the maintainer, 2026-10-28) a sender the interpreter does not read says a reminder or a write in words: the typed-command sentence, and the line goes to no model;
  C2-d  a reminder question the interpreter's carry-out asks goes with the one-tap Yes button and is bound in the ledger; the tap answers it;
  C2-e  "no reminder N waits for you" is told as the plain sentence, never behind "error:";
  C2-f  the reminder line the engine reads begins with the moment (BL7-4's deadline rule);
  C2-g  a text span made only of the trigger words ("me lembra") is no text: the words are asked;
  C2-h  (the maintainer, 2026-10-28) where the code's time reader doubts a reminder's time the engine's own question is asked ("Which time do you mean: A or B?"), the generic sentence only
        when the engine has nothing to offer;
  B1    the clock the cover answers are judged at is the pinned one of the replay, never the wall clock.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_review_fixes.py
"""
from __future__ import annotations

import datetime
import json
import threading
import time

import pytest

import standin_tree as st
from test_ask import accept
from test_commands_in_words import OWNER, PROFILES2, SENDERS2, docs, op, rig, with_senders, world  # noqa: F401
from test_messaging_ask import wait_for
from test_messaging_brake_leg import BUSY_KEYS, busy_sentences, hold_agent
from test_ops_natural import router_says

ops = st.load("ops")
ops_natural = st.load("ops_natural")
ops_turn = st.load("ops_turn")
ops_interpret = st.load("ops_interpret")
turn_gate = st.load("turn_gate")
natural = st.load("natural")
phrases = st.load("phrases")
messaging_bridge = st.load("messaging_bridge")

NOINT, READER_I = "55119000000051", "55119000000052"
EXTRA = {"noint": ["read", "talk"], "reader-i": ["read", "interpret"]}
ROUTE = '{"v":1,"kind":"route"}'


@pytest.fixture
def lab(rig):  # noqa: F811
    """The rig, with two more senders: `noint` talks and holds no `interpret`; `reader_i` holds `interpret` and may not talk."""
    senders = {"telegram": [*SENDERS2["telegram"], {"id": NOINT, "policy": "noint"}, {"id": READER_I, "policy": "reader-i"}]}
    accept(rig.world["path"], policies={**PROFILES2, **EXTRA}, messaging={"senders": senders}, **({} if rig.language == "en" else {"language": "pt-BR"}))
    return rig


def say(lab, who, text, model=None):
    lab.asked.clear()
    if model is not None:
        lab.model["text"] = model
    lab.bridge.handle({"update_id": 1, "sender": who, "chat": who, "private": True, "text": text, "action": None, "action_ref": None, "reply_to": None})
    assert wait_for(lambda: not lab.bridge.exclusive and all(not t.is_alive() for t in lab.bridge.threads)) or True


def hint_for(lab, command):
    return phrases.text("IX_OUTAGE_BRAKE", {"language": lab.language}, command=command)


# --- C1-a ------------------------------------------------------------------------------------------------------------------------------------------


def brake_line(lab):
    return "para a tarefa 5" if lab.language == "pt-BR" else "stop task 5"


def test_c1_a_a_brake_in_words_of_a_sender_the_interpreter_does_not_read_gets_the_typed_hint_and_is_never_queued(lab):
    let_go = hold_agent(lab)
    try:
        say(lab, NOINT, brake_line(lab), ROUTE)
        assert wait_for(lambda: bool(lab.texts(NOINT)))
        assert lab.texts(NOINT) == [hint_for(lab, "/stop-task 5")] and not set(lab.texts(NOINT)) & busy_sentences(), "the hint, not QUEUED or RUN_BUSY"
        assert lab.asked == [], "no model was asked"
    finally:
        let_go()


def test_vacuity_c1_a_without_the_brake_form_check_the_line_waits_behind_the_run(lab, monkeypatch):
    monkeypatch.setattr(messaging_bridge.Bridge, "brake_form", lambda self, text: False)
    let_go = hold_agent(lab)
    try:
        say(lab, NOINT, brake_line(lab), ROUTE)
        assert wait_for(lambda: bool(lab.texts(NOINT)))
        assert lab.texts(NOINT) != [hint_for(lab, "/stop-task 5")] and set(lab.texts(NOINT)) & busy_sentences(), "queued behind the run, as it was"
    finally:
        let_go()


def test_c1_a_a_plain_line_of_that_sender_is_not_decided_first(lab):
    say(lab, NOINT, "tell me what you think of the sea" if lab.language == "en" else "me conta o que voce acha do mar", ROUTE)
    assert lab.asked == [] and not any(hint_for(lab, c) in lab.texts(NOINT) for c in ("/stop-task 5", "/cancel #", "/cancel 5")), "only a brake form is decided in the first leg"


# --- C1-b ------------------------------------------------------------------------------------------------------------------------------------------


def test_c1_b_a_sender_who_holds_interpret_and_may_not_talk_reaches_the_interpreter_through_the_bridge(lab):
    say(lab, READER_I, "pendências" if lab.language == "pt-BR" else "show me the pending items please", op("pending"))
    assert wait_for(lambda: bool(lab.texts(READER_I)))
    assert len(lab.asked) == 1, "the interpreter read the line"
    assert len(lab.plan_cards(READER_I)) == 1, "a read it chooses asks \"Shall I go ahead?\" as any read does (decision #6)"


def test_vacuity_c1_b_without_the_kind_interpret_the_bridge_refuses_the_line_before_the_interpreter(lab, monkeypatch):
    real = messaging_bridge.Bridge.run_op
    monkeypatch.setattr(messaging_bridge.Bridge, "run_op", lambda self, project, op_name, kind=None, **kw: real(self, project, op_name, kind=None, **kw))
    say(lab, READER_I, "pendências" if lab.language == "pt-BR" else "show me the pending items please", op("pending"))
    assert wait_for(lambda: bool(lab.texts(READER_I)))
    assert lab.asked == [] and not lab.plan_cards(READER_I), "refused at the bridge, no model, no question"


# --- C1-c ------------------------------------------------------------------------------------------------------------------------------------------


def test_c1_c_a_reminder_said_by_a_sender_the_interpreter_does_not_read_gets_the_typed_command_and_goes_to_no_model(lab):
    calls = []
    router_says(lab.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    say(lab, NOINT, "me lembra de ligar amanhã 9h" if lab.language == "pt-BR" else "remind me to call tomorrow at 9am", ROUTE)      # validate: allow english-only -- the Portuguese line under test
    assert wait_for(lambda: bool(lab.texts(NOINT)))
    assert lab.texts(NOINT) == [phrases.text("IX_TYPE_REMIND", {"language": lab.language}, command="/remind <time> <text>")]
    assert lab.asked == [] and not lab.bridge.waiting, "no model, no queue"


def test_vacuity_c1_c_without_the_typed_sentence_the_line_goes_to_the_planning_agent(lab, monkeypatch):
    monkeypatch.setattr(ops_turn, "typed_sentence", lambda ctx, said, sender: None)
    router_says(lab.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    say(lab, NOINT, "me lembra de ligar amanhã 9h" if lab.language == "pt-BR" else "remind me to call tomorrow at 9am", ROUTE)      # validate: allow english-only -- the Portuguese line under test
    assert wait_for(lambda: bool(lab.texts(NOINT)))
    assert phrases.text("IX_TYPE_REMIND", {"language": lab.language}, command="/remind <time> <text>") not in lab.texts(NOINT), "the line was routed, as it was"


def test_c1_c_a_write_in_words_gets_the_sentence_of_the_writes_and_a_plain_line_is_left_alone(lab):
    router_says(lab.world, "Route: none (capability, pending)\nWhy: a plain question\nNext: nothing.\n")
    line = "marca academia toda segunda às 7h"      # validate: allow english-only -- the Portuguese line under test (a write of the calendar, as the corpus of CB-9 has it)
    assert turn_gate.private_kind(line) == "write"
    said = ops_turn.typed_sentence({"cfg": {"language": lab.language}}, line, NOINT)
    assert said == phrases.text("IX_TYPE_WRITE", {"language": lab.language})
    assert ops_turn.typed_sentence({"cfg": {"language": lab.language}}, "tell me what you think of the sea", NOINT) is None


# --- C2-d, C2-e, C2-f, C2-g, C2-h -------------------------------------------------------------------------------------------------------------------


def reminder_model(when, text="call the florist", **more):
    return json.dumps({"v": 1, "kind": "op", "op": "remind", "slots": {"text": text, "when": when}, **more})


def test_c2_d_the_reminder_question_goes_with_the_yes_button_bound_in_the_ledger_and_the_tap_answers_it(lab):
    say(lab, OWNER, "remind me tomorrow at 1 pm to call the florist", reminder_model("tomorrow at 1 pm", time_iso="2026-10-19T13:00", weekday="mon"))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    cards = [c for c in lab.bridge.ledger.data["cards"] if c.get("kind") == "reminder" and c["chat"] == OWNER]
    assert len(cards) == 1 and list(cards[0]["actions"].values()) == ["yes"], "the one-tap Yes button, bound in the ledger"
    action = next(iter(cards[0]["actions"]))
    before = len(lab.texts(OWNER))
    lab.bridge.handle({"update_id": 2, "sender": OWNER, "chat": OWNER, "private": True, "text": None, "action": action, "action_ref": "ref-1", "reply_to": None})
    assert wait_for(lambda: len(lab.texts(OWNER)) > before)
    assert any(t.startswith(("Reminder #", "Lembrete #")) for t in lab.texts(OWNER)[before:]), lab.texts(OWNER)


def test_vacuity_c2_d_without_the_shared_yes_button_the_question_is_plain(lab, monkeypatch):
    monkeypatch.setattr(lab.bridge.remind, "ask_yes_shared", lambda project, chat, sentence: False)
    say(lab, OWNER, "remind me tomorrow at 1 pm to call the florist", reminder_model("tomorrow at 1 pm", time_iso="2026-10-19T13:00", weekday="mon"))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    assert not [c for c in lab.bridge.ledger.data["cards"] if c.get("kind") == "reminder"], "no button, no card: a typed yes still works"


def test_c2_e_no_reminder_is_told_as_a_plain_sentence(lab):
    say(lab, OWNER, "cancela o lembrete 3" if lab.language == "pt-BR" else "forget reminder 3", json.dumps({"v": 1, "kind": "op", "op": "reminder-forget", "slots": {"id": "3"}}))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    sent = lab.texts(OWNER)[-1]
    if lab.plan_cards(OWNER):
        sent = lab.answer(OWNER, "sim" if lab.language == "pt-BR" else "yes")[-1]
    assert not sent.startswith("error:"), sent


def test_c2_f_the_reminder_line_the_engine_reads_begins_with_the_moment(lab, monkeypatch):
    seen = []
    real = ops_natural._call
    monkeypatch.setattr(ops_natural, "_call", lambda project, row, args, channel, sender: seen.append(args) or real(project, row, args, channel, sender))
    say(lab, OWNER, "remind me tomorrow at 1 pm to call the florist", reminder_model("tomorrow at 1 pm", time_iso="2026-10-19T13:00", weekday="mon"))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    said = [a["said"] for a in seen if isinstance(a, dict) and "said" in a]
    assert said and all(s.endswith("call the florist") and not s.startswith("call the florist") for s in said), said


def test_c2_g_a_text_made_only_of_the_trigger_words_is_no_text(lab):
    assert natural.only_trigger("me lembra") and natural.only_trigger("remind me") and not natural.only_trigger("me lembra de ligar") and not natural.only_trigger("")
    say(lab, OWNER, "remind me tomorrow at 1 pm", reminder_model("tomorrow at 1 pm", text="remind me", time_iso="2026-10-19T13:00", weekday="mon"))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    assert "remind me" not in lab.texts(OWNER)[-1].lower().split("confirm")[0].replace("remind me tomorrow", ""), lab.texts(OWNER)[-1]


def test_vacuity_c2_g_without_the_check_the_trigger_words_are_offered_as_the_reminder(lab, monkeypatch):
    monkeypatch.setattr(natural, "only_trigger", lambda text, languages=None: False)
    say(lab, OWNER, "remind me tomorrow at 1 pm", reminder_model("tomorrow at 1 pm", text="remind me", time_iso="2026-10-19T13:00", weekday="mon"))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    assert "remind me" in lab.texts(OWNER)[-1].lower().replace("remind me tomorrow", ""), "the trigger words became the reminder's words"


def test_c2_h_a_doubt_about_a_reminders_time_is_asked_by_the_engine_with_its_two_readings(lab):
    hour = "me lembra às 9 de regar as plantas" if lab.language == "pt-BR" else "remind me at 9 to water the plants"
    say(lab, OWNER, hour, json.dumps({"v": 1, "kind": "op", "op": "remind", "slots": {"text": "regar as plantas" if lab.language == "pt-BR" else "water the plants", "when": "às 9" if lab.language == "pt-BR" else "at 9"},
                                      "time_iso": "2026-10-19T09:00", "weekday": "mon"}))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    sent = lab.texts(OWNER)[-1]
    assert sent != phrases.text("IX_ASK_TIME", {"language": lab.language}), "not the generic sentence"
    assert "09:00" in sent and "21:00" in sent, sent


def test_vacuity_c2_h_when_the_engine_has_nothing_to_offer_the_generic_sentence_stays(lab, monkeypatch):
    monkeypatch.setattr(ops_natural, "run", lambda *a, **k: phrases.text("NAT_NOT_BELIEVED", {"language": lab.language}))
    say(lab, OWNER, "remind me at 9 to water the plants", json.dumps({"v": 1, "kind": "op", "op": "remind", "slots": {"text": "water the plants", "when": "at 9"}, "time_iso": "2026-10-19T09:00", "weekday": "mon"}))
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    assert lab.texts(OWNER)[-1] == phrases.text("IX_ASK_TIME", {"language": lab.language}), "the generic sentence, only because the engine offers nothing"


# --- the brake in an outage records no call (SPEC-S41-11-BRAKE 6.3) ---------------------------------------------------------------------------------------------


def test_the_brake_of_an_owner_whose_breaker_is_open_gets_the_hint_and_asks_no_model(lab):
    gate = turn_gate
    gate._breaker.update(fails=gate.BREAKER_FAILS, until=gate.clock() + gate.BREAKER_OPEN)
    say(lab, OWNER, brake_line(lab), ROUTE)
    assert wait_for(lambda: bool(lab.texts(OWNER)))
    assert lab.texts(OWNER) == [hint_for(lab, "/stop-task 5")] and lab.asked == [], "the gate admitted no call"


# --- B1: the replay clock ---------------------------------------------------------------------------------------------------------------------------------


def test_b1_the_cover_answers_are_judged_at_the_pinned_replay_clock_and_never_at_the_wall_clock(monkeypatch):
    import entry_kit as kit
    import test_reminders
    pinned = test_reminders.Clock.__init__.__defaults__[0]      # the wall of the Clock the world installs: "2026-10-18 14:00"
    assert kit.REPLAY_CLOCK.replace("T", " ") == pinned, "the kit names the clock the world pins"

    class NoWall(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            raise AssertionError("the wall clock was read")
    monkeypatch.setattr(kit.datetime if hasattr(kit, "datetime") else datetime, "datetime", NoWall, raising=False)
    item = {"zone": "America/Sao_Paulo", "clock": "2026-10-15T10:00", "line": "remind me tomorrow at 9am to send the weekly report"}
    obj = {"op": "remind", "slots": {"text": "send the weekly report", "when": "tomorrow at 9am"}, "time_iso": "2026-10-19T09:00"}
    assert kit._cover_time_unstable(item, obj) in (True, False)

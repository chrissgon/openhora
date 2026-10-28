"""The OK of a plan on the messaging bridge (package BL2b, limits L64 and L65; runtime/messaging_bridge.py `ask_plan`, `plan_decide`, `plan_tapped` and the kind `plan-confirm` of runtime/messaging_turn.py).

A read or an act asked in words is answered by the operations layer with the question "I understood: ... Shall I go ahead?" (BL2a). The bridge sends it with a Yes and a No button (a line on
e-mail), binds it in the ledger as a record of kind `plan-confirm`, and takes the person's OK under the conditions of L64: a private line of a listed sender, not forwarded, a yes or no word code
reads, the question the LAST message the platform sent to the chat or the line a reply to it, on e-mail only a reply. The real bridge, the real operations layer, a stand-in messenger, a stand-in
model and a stand-in clock (plan_bridge_kit.py). THE GUARDS COME FIRST; each negative test reads the one place a read runs (its own literal count), never the bridge's; the vacuity case plants
the one fact the guard reads (the last message) and shows the same counter sees the read. Wording is by phrase key and value. Offline; invented names.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_plan_confirm.py
"""
from __future__ import annotations

import threading

import standin_tree as st
from frame_kit import claims
from plan_bridge_kit import ASKER_ID, OWNER_ID, OWNER_KEY, brig, bridge, ops, phrases, question_text, rig, wait_for, world  # noqa: F401
from plan_confirm_kit import PROF, SENDER_LIST, accept, op, ops_say
from test_service import WAIT

DAY = "Mon 19/10/2026"      # "de amanha" on the clock of the world of test_ops_natural.py


def t(brig, key, **fields):
    return phrases.text(key, brig.rig.cfg, **fields)


def live(brig, sender=OWNER_KEY):
    return ops.plan_live(brig.rig.world["path"], sender)


def reads(brig):
    """The calls of the one place a read runs: [name, ...] (the test's own count)."""
    return [r["name"] for r in brig.reads]


def last_text(brig, chat=OWNER_ID):
    return brig.texts(chat)[-1]


# --- the guards: what is NOT an OK ---------------------------------------------------------------------------------------------------------------


def test_a_sim_in_a_group_or_from_another_sender_does_not_confirm(brig):
    brig.ask()
    plan = live(brig)
    sent = len(brig.sent())
    brig.say("sim", sender=OWNER_ID, chat="-1001234", private=False)      # the owner's words in a group chat
    brig.say("sim", sender=OWNER_ID, chat="-1001234")      # a chat that is not the sender's own private one
    assert bridge.DROPPED in brig.log and len(brig.sent()) == sent, "dropped with no reply and no operation"
    brig.say("sim", sender=ASKER_ID)      # another listed sender, in their own chat: the question was never theirs
    assert wait_for(lambda: len(brig.sent()) > sent) and brig.idle()
    assert reads(brig) == [] and live(brig) == plan, "nothing was read and the owner's plan still waits for its OK"
    assert ops.plan_live(brig.rig.world["path"], f"telegram:{ASKER_ID}") is None


def test_a_forwarded_sim_does_not_confirm(brig):
    brig.ask()
    plan = live(brig)
    brig.say("sim", forwarded=True)
    assert wait_for(lambda: last_text(brig) == t(brig, "FWD_NOT_A_REQUEST")) and reads(brig) == [] and live(brig) == plan
    update = {"sender": OWNER_ID, "chat": OWNER_ID, "private": True, "text": "sim", "forwarded": True}      # the check is made again where the OK is read (the kind `plan-confirm` of the frame, as the card words' kind does)
    assert claims(brig.bridge, "plan-confirm", update, {"kind": "text", "text": "sim"}, "text", brig.project, [brig.project], OWNER_ID) is False
    assert reads(brig) == [] and live(brig) == plan


def test_a_sim_that_is_not_the_last_message_does_not_confirm_and_says_so(brig):
    brig.ask()
    brig.bridge.reply(OWNER_ID, "A reminder: water the plants.")      # a delivered reminder is a message: the question is no longer the last one
    brig.say("sim")
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_NOT_LAST")) and brig.idle()
    assert reads(brig) == [] and brig.rig.calls == [] and live(brig) is not None, "no read, no model, and the plan waits for a yes that is the question's"


def test_vacuity_a_bridge_that_does_not_check_the_last_message_confirms_the_same_sim(brig):
    brig.ask()
    question = brig.question_id()
    brig.bridge.reply(OWNER_ID, "A reminder: water the plants.")

    class Always(dict):      # the one fact the kind `plan-confirm` reads, planted: the question is the last message
        def get(self, chat, default=None):
            return question
    brig.bridge.last_sent = Always()
    brig.say("sim")
    assert wait_for(lambda: reads(brig) == ["items"]), "the same counter that is empty in the test above sees the read"


def test_a_send_in_flight_clears_the_last_message_and_a_sim_in_that_moment_decides_nothing(brig, monkeypatch):
    brig.ask()
    gate, entered, first = threading.Event(), threading.Event(), [True]
    real = brig.bridge.messenger.send

    def slow(chat, message, *args, **kwargs):
        if first[0]:
            first[0] = False
            entered.set()
            gate.wait(WAIT)
        return real(chat, message, *args, **kwargs)
    monkeypatch.setattr(brig.bridge.messenger, "send", slow)
    sender = threading.Thread(target=lambda: brig.bridge.reply(OWNER_ID, "A reminder: water the plants."), daemon=True)
    sender.start()
    assert entered.wait(WAIT) and brig.bridge.last_sent[OWNER_ID] is None, "the platform has not confirmed the send: nothing is the last message"
    brig.say("sim")
    gate.set()
    sender.join(WAIT)
    assert wait_for(lambda: t(brig, "PLAN_NOT_LAST") in brig.texts()) and brig.idle() and reads(brig) == []


def test_after_a_restart_the_last_message_is_forgotten_and_a_sim_decides_nothing(brig):
    brig.ask()
    brig.bridge.last_sent.clear()      # a new process knows no last message (and no plan in memory either)
    brig.say("sim")
    assert wait_for(lambda: len(brig.texts()) >= 2) and brig.idle() and reads(brig) == []


def test_a_plain_sim_on_e_mail_is_no_ok_and_a_reply_to_the_question_is(brig):
    brig.caps(buttons=False, actions_need_reply=True)
    brig.ask()
    [question] = brig.sent()
    assert question["message"]["actions"] == [] and question["message"]["text"].endswith("\n" + t(brig, "PLAN_REPLY_HOW_EMAIL")), "one line says how to answer"
    assert question["message"]["text"].startswith(question_text(brig.rig, "UNDERSTOOD_ITEMS_CALENDAR"))
    brig.say("sim")      # not a reply: on e-mail an OK is a reply (rule 50)
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_NOT_LAST")) and brig.idle() and reads(brig) == []
    brig.say("sim\n\n-- \nAna", reply_to=brig.question_id())      # the signature is not words
    assert wait_for(lambda: reads(brig) == ["items"]) and wait_for(lambda: last_text(brig) == "READ-REPLY")


def test_a_correction_after_the_question_is_not_taken_as_an_ok_it_revises_the_plan(brig):
    brig.ask()
    first = live(brig)
    brig.rig.says["text"] = op("items")
    brig.say("nao, de amanha")      # neither word: it reaches `say`, where the model reads it with the plan as a typed frame item
    day = phrases.localize_dates(t(brig, "UNDERSTOOD_ON_DAY", day=DAY), brig.rig.cfg)
    revised = phrases.text("PLAN_HEAD", brig.rig.cfg, what=phrases.text("UNDERSTOOD_ITEMS_CALENDAR", brig.rig.cfg) + day) + " " + t(brig, "PLAN_ASK")      # BL5B: the correction names no events, so it keeps the kind of the plan it corrects (the agenda)
    assert wait_for(lambda: last_text(brig) == revised)
    assert reads(brig) == [] and live(brig)["item"] != first["item"], "a NEW question; the first plan is gone"
    assert ops.say(brig.rig.world["path"], "sim", channel="messaging", sender=OWNER_KEY, plan_ok={"item": first["item"], "sha256": first["sha256"]})["reply"] == t(brig, "PLAN_GONE")
    brig.say("sim")      # the new question is the last message
    assert wait_for(lambda: reads(brig) == ["items"]) and brig.idle()


# --- the OK, the refusal, the buttons ---------------------------------------------------------------------------------------------------------------


def test_a_read_in_words_asks_with_yes_and_no_buttons_and_the_sim_runs_it_once(brig):
    brig.ask()
    [question] = brig.sent()
    shown = question["message"]
    assert shown["text"] == question_text(brig.rig, "UNDERSTOOD_ITEMS_CALENDAR")
    assert [a["label"] for a in shown["actions"]] == [t(brig, "NT_BTN_YES"), t(brig, "PLAN_BTN_NO")]
    assert brig.bridge.last_sent[OWNER_ID] == brig.question_id() and reads(brig) == [], "the question is the last message and nothing was read"
    brig.say("sim")
    assert wait_for(lambda: last_text(brig) == "READ-REPLY") and brig.idle()
    assert reads(brig) == ["items"] and live(brig) is None
    brig.say("sim", reply_to=brig.question_id())      # a second OK for the same question: the plan was taken once
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_GONE")) and reads(brig) == ["items"]


def test_a_reply_to_the_question_confirms_even_after_another_message_came(brig):
    brig.ask()
    brig.bridge.reply(OWNER_ID, "A reminder: water the plants.")
    brig.say("sim", reply_to=brig.question_id())
    assert wait_for(lambda: reads(brig) == ["items"]) and wait_for(lambda: last_text(brig) == "READ-REPLY")


def test_a_nao_drops_the_plan_and_so_does_the_no_button(brig):
    brig.ask()
    brig.say("n\u00e3o")
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_DROPPED")) and live(brig) is None and reads(brig) == []
    brig.ask("mostra meus emails")
    brig.tap(brig.question_actions()["no"])
    assert wait_for(lambda: brig.texts().count(t(brig, "PLAN_DROPPED")) == 2) and live(brig) is None and reads(brig) == []
    brig.ask("mostra meus emails")
    brig.rig.now[0] += 601      # the plan expired; its question is still the last message
    brig.say("n\u00e3o")      # nothing waits: the same sentence, and nothing happens
    assert wait_for(lambda: brig.texts().count(t(brig, "PLAN_DROPPED")) == 3) and reads(brig) == []


def test_the_yes_button_runs_the_plan_once_after_600_seconds_it_is_gone_and_a_second_tap_too(brig):
    brig.ask()
    yes = brig.question_actions()["yes"]
    brig.tap(yes)
    assert wait_for(lambda: reads(brig) == ["items"]) and wait_for(lambda: last_text(brig) == "READ-REPLY")
    brig.tap(yes)      # a second tap: the plan was taken
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_GONE")) and reads(brig) == ["items"]
    brig.ask("mostra meus emails")
    stale = brig.question_actions()["yes"]
    brig.rig.now[0] += 601      # PLAN_TTL, on the stand-in clock
    brig.tap(stale)
    assert wait_for(lambda: brig.texts().count(t(brig, "PLAN_GONE")) == 2) and reads(brig) == ["items"]


def test_the_button_of_an_older_question_is_gone_once_a_newer_one_replaced_its_plan(brig):
    brig.ask()
    older = brig.question_actions()["yes"]
    brig.ask("mostra meus emails")
    brig.tap(older)
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_GONE")) and reads(brig) == [] and live(brig) is not None, "the newer plan still waits"


def test_the_no_of_an_older_question_leaves_the_newer_plan_to_its_own_question(brig):
    brig.ask()
    older = brig.question_actions()["no"]
    brig.ask("mostra meus emails")
    newer = live(brig)
    brig.tap(older)
    assert wait_for(lambda: last_text(brig) == t(brig, "PLAN_DROPPED")) and live(brig) == newer, "the sentence is the same, and the newer plan still waits"
    brig.tap(brig.question_actions()["no"])
    assert wait_for(lambda: live(brig) is None)


def test_a_button_acts_only_in_the_chat_it_was_sent_to_and_for_its_listed_sender(brig):
    brig.ask()
    yes = brig.question_actions()["yes"]
    brig.say(None, sender=ASKER_ID, action=yes, action_ref="ref-2")      # another listed sender taps the owner's button
    assert wait_for(lambda: len(brig.texts(ASKER_ID)) == 1) and brig.texts(ASKER_ID)[0] == t(brig, "STALE") and reads(brig) == [] and live(brig) is not None
    brig.say(None, sender=OWNER_ID, chat="-1001234", private=False, action=yes, action_ref="ref-3")
    assert bridge.DROPPED in brig.log and reads(brig) == []


def test_a_sim_after_the_policy_changed_runs_nothing_and_says_so(brig):
    brig.ask()
    accept(brig.rig.world["path"], policies=dict(PROF, owner=[g for g in PROF["owner"] if g != "read"]), messaging={"senders": SENDER_LIST})      # the owner lost the right to read between the question and the OK
    brig.say("sim")
    assert wait_for(lambda: len(brig.texts()) == 2) and brig.idle() and reads(brig) == [], "the policy is asked again when the OK runs: the sender is refused and nothing is read"


# --- the plan's operation: the job's label, the model slot -----------------------------------------------------------------------------------------


def test_the_confirmed_call_is_labelled_with_the_plans_operation_and_a_read_takes_no_model_slot(brig, monkeypatch):
    labels = []
    real = brig.bridge.start
    monkeypatch.setattr(brig.bridge, "start", lambda project, chat, label, call: labels.append(label) or real(project, chat, label, call))
    brig.ask()
    brig.bridge.exclusive[brig.project["id"]] = "job 99"      # the project's model slot is held by another job
    brig.say("sim")
    assert wait_for(lambda: reads(brig) == ["items"]) and "items" in labels, "a read that calls no model runs while a model job holds the slot"
    del brig.bridge.exclusive[brig.project["id"]]


def test_a_research_ok_takes_the_model_slot_and_a_busy_project_answers_still_working_and_runs_nothing(brig, monkeypatch):
    research = []
    ops_research = st.load("ops_research")
    monkeypatch.setattr(ops_research, "reply", lambda project, ctx, args, said, channel, sender, extras: research.append(args) or "SEARCH-REPLY")
    brig.rig.says["text"] = op("research", {"question": "weather in Lisbon tomorrow"})
    before = len(brig.sent())
    brig.say("will it rain in Lisbon, weather in Lisbon tomorrow")
    assert wait_for(lambda: len(brig.sent()) > before and brig.question_id() is not None) and brig.idle()
    assert live(brig)["op"] == "research" and research == []
    brig.bridge.exclusive[brig.project["id"]] = "job 99"
    brig.say("sim")
    assert wait_for(lambda: last_text(brig) == t(brig, "STILL_WORKING")) and research == [] and live(brig) is not None, "busy: nothing ran and the plan was not spent"
    del brig.bridge.exclusive[brig.project["id"]]
    brig.say("sim", reply_to=brig.question_id())
    assert wait_for(lambda: last_text(brig) == "SEARCH-REPLY") and research == [{"question": "weather in Lisbon tomorrow"}], "it ran once"


def test_a_cancel_the_model_chose_asks_and_the_ok_hands_the_typed_command_over(brig, monkeypatch):
    done = []
    monkeypatch.setattr(ops_say, "_say_command", lambda project, ctx, line, channel, line_id, sender=None: done.append(line) or ("COMMAND-REPLY", None, None, False, None))
    brig.rig.says["text"] = op("cancel", {"id": "3"})
    before = len(brig.sent())
    brig.say("quero cancelar o pedido 3")
    assert wait_for(lambda: len(brig.sent()) > before and brig.question_id() is not None) and brig.idle()
    assert last_text(brig) == question_text(brig.rig, "UNDERSTOOD_CANCEL", id=3) and done == []
    brig.say("sim")
    assert wait_for(lambda: done == ["/cancel 3"]) and wait_for(lambda: last_text(brig) == "COMMAND-REPLY")


# --- what the ledger holds -----------------------------------------------------------------------------------------------------------------------


def test_the_ledger_record_of_a_question_holds_ids_a_hash_and_an_operation_and_never_a_word(brig):
    brig.ask()
    [rec] = [c for c in brig.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"]
    plan = live(brig)
    assert set(rec) == {"project", "pending_id", "kind", "content_sha256", "chat", "message_id", "actions", "sent_at", "whole", "approvable", "blocked", "effect_word", "plan_item", "plan_sha256",
                        "plan_op", "platform"}
    assert (rec["plan_item"], rec["plan_sha256"], rec["plan_op"]) == (plan["item"], plan["sha256"], "items") and rec["pending_id"] is None and rec["approvable"] is False
    assert sorted(rec["actions"].values()) == ["no", "yes"] and rec["message_id"] == brig.question_id()
    shown = repr(rec).lower()
    for word in ("agenda", "understood", "shall", "calendar", "mostra"):      # neither the person's line nor the sentence code wrote from it
        assert word not in shown, word


def test_a_question_that_could_not_be_sent_leaves_no_plan_that_waits(brig, monkeypatch):
    monkeypatch.setattr(brig.bridge, "reply", lambda *a, **k: False)      # the platform refused the text
    brig.caps(buttons=False)
    brig.say("mostra minha agenda")
    assert wait_for(lambda: live(brig) is None) and brig.idle() and not [c for c in brig.bridge.ledger.data["cards"] if c.get("kind") == "plan-confirm"]


def test_a_question_too_long_for_one_message_is_sent_as_text_with_no_buttons_and_is_still_bound(brig):
    brig.caps(max_text=40)
    brig.ask()
    assert all(not s["message"]["actions"] for s in brig.sent()) and len(brig.sent()) > 1
    brig.say("sim")      # the last piece is the last message; the ledger names it
    assert wait_for(lambda: reads(brig) == ["items"])

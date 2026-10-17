"""The one change the e-mail channel makes to the messaging bridge (package EMAIL-CHANNEL; runtime/messaging_provider.py, runtime/messaging_bridge.py):
a platform that declares the optional capability `actions_need_reply` acts on a typed approve, reject, release or answer only when the update is a reply to
the ledger's card of that very decision in that chat, and binds the action to the card replied to. The card's Message-ID is random and went only to
the listed mailbox, so a message that is not a reply to it, or is a reply to another card, cannot act; and the reply is also the proof that the card
reached the person. Offline, over the stand-in operations object and the stand-in messenger of test_messaging.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_email_reply.py
"""
from __future__ import annotations

import importlib.util
import sys

import pytest

import standin_tree as st
from test_channel_grants_cards import GRANTED, HASH, approve_calls, effect, grant  # noqa: F401
from test_messaging import OPEN_POLICY, SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

bridge = st.load("messaging_bridge")
providers = st.load("messaging_provider")

EMAIL = st.REPO / "providers" / "messenger" / "email-imap.py"
EMAIL_HELPERS = st.REPO / "providers" / "_email.py"
EMAIL_CAPS = {"max_text": 20000, "buttons": False, "max_buttons": 0, "documents": False, "reply_context": True, "actions_need_reply": True}


def card_id(world, pending_id=7, index=-1):
    found = [c for c in world.bridge.ledger.data["cards"] if c["pending_id"] == pending_id]
    return found[index]["message_id"]


def only_refused(world, text=bridge.REPLY_TO_CARD):
    return world.texts()[-1] == text and approve_calls(world) == [] and not world.calls("reject") and not world.calls("release")


def test_the_capability_is_optional_checked_and_false_when_a_provider_leaves_it_out(world):
    assert world.bridge.messenger.capabilities()["actions_need_reply"] is False
    world.caps(actions_need_reply=True)
    assert world.bridge.messenger.capabilities()["actions_need_reply"] is True
    world.caps(actions_need_reply="yes")
    with pytest.raises(providers.MessengerError):
        world.bridge.messenger.capabilities()
    assert providers.OPTIONAL_KEYS["actions_need_reply"] is bool and "actions_need_reply" not in providers.CAPABILITY_KEYS


def test_a_typed_approve_that_is_not_a_reply_to_the_card_is_refused_and_nothing_runs(world):
    grant(world)
    world.caps(**EMAIL_CAPS)
    world.items[7] = effect()
    world.bridge.tick()
    for text in ("/approve 7", f"/approve 7 {HASH}", "/reject 7", "/release 7"):
        world.say(text)
        assert only_refused(world), text
    world.say("/approve 7", reply_to=None)
    world.say("/approve 7", reply_to="")
    world.say("/approve 7", reply_to="<forged-guess@office.example>")
    assert only_refused(world)


def test_a_reply_to_the_card_of_another_decision_cannot_act_on_this_one(world):
    grant(world)
    world.caps(**EMAIL_CAPS)
    world.items[7] = effect()
    world.items[8] = effect(number=8, sha="8" * 64, body="Replace another page.")
    world.bridge.tick()
    world.say("/approve 7", reply_to=card_id(world, 8))
    world.say("/reject 8", reply_to=card_id(world, 7))
    assert only_refused(world)
    assert world.bridge.ledger.last_card(world.projects[0]["id"], 7, "4242")["message_id"] == card_id(world, 7)


def test_a_typed_approve_in_reply_to_its_card_is_bound_to_that_card_and_runs_once_with_its_hash(world):
    grant(world)
    world.caps(**EMAIL_CAPS)
    world.items[7] = effect()
    world.bridge.tick()
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("/approve 7", reply_to=card_id(world))
    assert wait_for(lambda: len(approve_calls(world)) == 1)
    assert approve_calls(world)[0][2] == {"pending_id": 7, "sha256": HASH, "channel": "messaging"}
    assert wait_for(lambda: world.texts()[-1] == "Approved #7.")
    world.say(f"/approve 7 {'d' * 64}", reply_to=card_id(world))
    assert world.texts()[-1] == bridge.WRONG_HASH and len(approve_calls(world)) == 1


def test_a_reply_to_an_older_card_of_the_decision_acts_on_that_card_and_a_changed_decision_is_refused(world):
    grant(world)
    world.caps(**EMAIL_CAPS)
    world.items[7] = effect()
    world.bridge.tick()
    old = card_id(world)
    world.items[7] = effect(sha="9" * 64)              # the effect was opened again with other content: a new card
    world.bridge.tick()
    assert card_id(world) != old
    world.say("/approve 7", reply_to=old)
    assert approve_calls(world) == [] and bridge.CHANGED in world.texts()
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("/approve 7", reply_to=card_id(world))
    assert wait_for(lambda: approve_calls(world)) and approve_calls(world)[0][2]["sha256"] == "9" * 64


def test_a_reply_to_the_card_can_reject_a_plan_and_release_and_a_plan_needs_its_hash_as_before(world):
    world.caps(**EMAIL_CAPS)
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    world.say("/reject 1", reply_to=card_id(world, 1))
    assert world.calls("reject") and world.texts()[-1] == "Rejected #1."
    world.items[2] = decision("review", 2, title="A delivery waits", body="Release it?")
    world.fake.answers["release"] = {"released": True}
    world.bridge.tick()
    world.say("/release 2")
    assert world.texts()[-1] == bridge.REPLY_TO_CARD and not world.calls("release")
    world.say("/release 2", reply_to=card_id(world, 2))
    assert wait_for(lambda: world.calls("release"))


def test_a_typed_answer_needs_the_reply_to_its_question_card_too(world):
    world.caps(**EMAIL_CAPS)
    world.items[1] = decision("question", 1)
    world.items[2] = decision("question", 2, title="Another question")
    world.bridge.tick()
    world.say("/answer 1 yes, all of them")
    world.say("/answer 1 yes", reply_to=card_id(world, 2))
    assert world.texts()[-1] == bridge.REPLY_TO_CARD and not world.calls("answer_proposing")
    world.say("/answer 1 yes, all of them", reply_to=card_id(world, 1))
    assert wait_for(lambda: world.calls("answer_proposing"))
    assert world.calls("answer_proposing")[0][2]["text"] == "yes, all of them"
    world.caps(actions_need_reply=False)
    world.say("/answer 2 a plain platform needs no reply")
    assert wait_for(lambda: len(world.calls("answer_proposing")) == 2)


def test_everything_that_is_not_an_action_needs_no_reply_and_a_platform_without_the_capability_is_as_before(world):
    world.caps(**EMAIL_CAPS)
    world.items[1] = decision("question", 1)
    world.bridge.tick()
    world.say("/pending")
    world.say("/help")
    world.say("how is the launch going?")
    assert wait_for(lambda: world.calls("say"))
    assert world.calls("pending") and bridge.REPLY_TO_CARD not in world.texts()
    world.say("an answer", reply_to=card_id(world, 1))      # a reply to a question card is an answer, as on every platform
    assert wait_for(lambda: world.calls("answer_proposing"))
    world.caps(actions_need_reply=False)
    world.items[2] = decision("plan", 2, plan_sha256="q" * 64)
    world.bridge.tick()                                    # a decision is acted on from the card the sender was sent (POL-2)
    world.say("/reject 2")
    assert world.calls("reject") and bridge.REPLY_TO_CARD not in world.texts()


def load_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def message(auth, to="assistant@office.example", extra=""):
    head = (f"Authentication-Results: {auth}\r\n" if auth else "") + (
        "Received: from mail.office.example by mx.office.example\r\nFrom: owner@office.example\r\n"
        f"To: {to}\r\nSubject: Re: card\r\nMIME-Version: 1.0\r\n{extra}Content-Type: text/plain; charset=utf-8\r\n\r\n/approve 7\r\n")
    return head.encode()


def test_limit_45_an_e_mail_update_is_served_only_when_the_receiving_servers_authentication_passes_for_its_from_domain_and_a_typed_action_only_in_reply_to_its_card(world):
    """The provider half in miniature (the full set is providers/messenger/tests/test_messenger_email.py) and the bridge half."""
    provider = load_path("messenger_email_for_limit_45", EMAIL)
    mail = load_path("providers_email", EMAIL_HELPERS)
    good = "mx.office.example; dkim=pass header.d=office.example; dmarc=pass header.from=office.example"

    def admit(data):
        return provider.inspect_message(data, "assistant@office.example", "mx.office.example", lambda chat: set(), mail)

    assert admit(message(good))[0]["sender"] == "owner@office.example"
    for forged in (None, "elsewhere.example; dmarc=pass", "mx.office.example; dmarc=fail", "mx.office.example; spf=pass",
                   "mx.office.example; dkim=pass header.d=evil.example; dmarc=none"):
        assert admit(message(forged)) == (None, "unauthenticated"), forged
    assert admit(message(good, to="assistant@office.example, other@office.example")) == (None, "not-private")
    assert admit(message(good, extra="Auto-Submitted: auto-replied\r\n")) == (None, "automatic")
    assert admit(message(good).replace(b"/approve 7", b"> /approve 7")) == (None, "empty")
    # the bridge half: a typed approve that does not name the card acts on nothing
    grant(world)
    world.caps(**EMAIL_CAPS)
    world.items[7] = effect()
    world.bridge.tick()
    world.say("/approve 7")
    world.say("/approve 7", reply_to="<oh.00000000000000000000000000000000@office.example>")
    assert only_refused(world)
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("/approve 7", reply_to=card_id(world))
    assert wait_for(lambda: len(approve_calls(world)) == 1)


def test_a_listed_sender_cannot_act_with_the_card_that_went_to_another_listed_sender(world):
    """Two listed senders each get their own card of the decision, with their own Message-ID: B's reply to A's card names no card of B's chat."""
    other = "555"
    world.config["messaging"]["senders"]["telegram"] = [SENDER, other]
    grant(world)
    world.caps(**EMAIL_CAPS)
    world.items[7] = effect()
    world.bridge.tick()
    mine = next(c["message_id"] for c in world.bridge.ledger.data["cards"] if c["chat"] == SENDER)
    theirs = next(c["message_id"] for c in world.bridge.ledger.data["cards"] if c["chat"] == other)
    assert mine != theirs
    world.say("/approve 7", sender=other, chat=other, reply_to=mine)
    assert approve_calls(world) == [] and world.texts()[-1] == bridge.REPLY_TO_CARD
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("/approve 7", sender=other, chat=other, reply_to=theirs)
    assert wait_for(lambda: len(approve_calls(world)) == 1)


def test_the_footer_is_handed_over_by_the_cards_for_a_platform_that_replies_to_act_and_only_for_it():
    cards = st.load("messaging_cards")
    operations = st.load("operations")
    item = {"id": 7, "kind": "effect", "title": "Send", "body": "Text.\n\nSend /approve 7", "status": "open", "actions": ["approved", "rejected"],
            "effect_word": "send", "effect_on_cards": True, "payload_sha256": "e" * 64}
    caps = {"max_text": 8000, "buttons": False, "max_buttons": 0, "documents": False, "reply_context": True, "url_buttons": False}
    policy = {"messaging": ["read", "approve-effect-send"]}
    plain = cards.build("northwind", item, caps, policy, "text", None, operations=operations, effect_command="cmd")
    assert "footer" not in plain["message"]
    asked = cards.build("northwind", item, {**caps, "actions_need_reply": True}, policy, "text", None, operations=operations, effect_command="cmd")
    message = asked["message"]
    assert message["footer"] and message["text"].endswith("\n\n" + "\n".join(message["footer"]))
    assert message["footer"][0] == "Send /approve 7" and message["text"].count("Send /approve 7") == 2      # the decision's own line and the footer's
    body = load_path("messenger_email_for_footer", EMAIL).render_body(message)
    assert "Text.\n\nSend /approve 7" in body and body.split("\n")[2] == "Reply to this e-mail with: /approve 7"

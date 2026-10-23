"""The card and the bridge of a granted effect (package POL-1; runtime/messaging_cards.py, runtime/messaging_bridge.py), over the stand-in
operations object and the stand-in messenger of test_messaging.py. What the policy layer decides is in test_channel_grants.py; here is what the
messaging channel does with it: an effect card carries the approve button only when the project's accepted policy grants the effect's word,
the notices carry text, the decision says the whole effect fits on a card, and the card carried the whole text (inline, or as the attached
document); a tap or a typed line is bound to the card the person saw, by its hash, which must be the decision's own; and an old card, a stale
one, a cut one and one of a narrowed policy approve nothing. Offline, no model.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants_cards.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_messaging import OPEN_POLICY, SECRET_TEXT, SENDER, decision, wait_for, world  # noqa: F401  (the bridge world of test_messaging.py)

ops = st.load("ops")
operations = st.load("operations")
bridge = st.load("messaging_bridge")
cards = st.load("messaging_cards")
inbound = st.load("messaging_inbound")
providers = st.load("messaging_provider")

HASH = "e" * 64
GRANTED = [*OPEN_POLICY, "approve-effect-write"]
LABEL = "Approve this exact content"


def effect(number=7, sha=HASH, word="write", on_cards=True, body="Replace the page with:\n\nOpen at nine.", **more):
    return decision("effect", number, title="Write to the plan page", body=body, payload_sha256=sha,
                    effect_word=word, effect_on_cards=on_cards, **more)


def fresh_bridge(world):
    """A bridge with an empty ledger and nothing sent: a new start of the same world."""
    (world.tmp / "data" / "messaging-telegram.json").unlink(missing_ok=True)
    world.standin.joinpath("sent.jsonl").unlink(missing_ok=True)
    world.bridge = world.make()


def grant(world, groups=GRANTED, notices="text"):
    world.config["channels"] = {"messaging": groups}
    world.config["messaging"]["notices"] = notices


def approve_calls(world):
    return world.calls("approve")


def approve_action(world, index=-1):
    message = world.sent()[index]["message"]
    return next(a["id"] for a in message["actions"] if a["label"] == LABEL)


# --- the card -------------------------------------------------------------------------------------------------------------------


def test_a_granted_whole_card_has_the_approve_button_the_hash_line_and_the_ledger_records_it(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    [card] = world.sent()
    message = card["message"]
    assert [a["label"] for a in message["actions"]] == [LABEL, "Reject"] or [a["label"] for a in message["actions"]] == ["Reject", LABEL]
    assert "Open at nine." in message["text"] and cards.APPROVES_LINE in message["text"] and "sha256" not in message["text"] and "terminal" not in message["text"]      # the hash binds the button, it is not printed (LIVE-2)
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is True and entry["approvable"] is True and entry["effect_word"] == "write" and entry["content_sha256"] == HASH
    assert "Open at nine" not in open(world.tmp / "data" / "messaging-telegram.json", encoding="utf-8").read(), "the ledger holds no project text"
    again = world.make()      # a restart sends nothing twice
    again.tick()
    assert len(world.sent()) == 1


def test_the_default_and_a_wrong_word_and_notices_of_count_draw_no_button_and_keep_the_command(world):
    world.items[7] = effect()
    command = bridge.scrub(operations.command_line("approve", world.projects[0]["path"], checkout=bridge.ROOT, pending_id=7, sha256=HASH))   # the card spells the home folder as ~
    for groups, notices in ((OPEN_POLICY, "text"), ([*OPEN_POLICY, "approve-effect-create", "approve-effect-send"], "text"), (GRANTED, "count")):
        grant(world, groups, notices)
        fresh_bridge(world)
        world.bridge.tick()
        [card] = world.sent()
        assert [a["label"] for a in card["message"]["actions"]] == ["Reject"], (groups, notices)
        assert cards.EFFECT_LINE in card["message"]["text"] and "cli.py" not in card["message"]["text"] and command not in card["message"]["text"]
        world.say("/approve 7")
        assert approve_calls(world) == [] and command not in world.texts()[-1] and "cli.py" not in world.texts()[-1] and world.texts()[-1].startswith(bridge.EFFECT_REPLY), (groups, notices)
    assert approve_calls(world) == []


def test_a_card_cut_on_a_platform_without_documents_draws_no_approve_and_says_so_with_the_command(world):
    grant(world)
    world.caps(max_text=1600, documents=False)          # Twilio's limit and no documents
    world.items[7] = effect(body="y" * 2500)
    world.bridge.tick()
    [card] = world.sent()
    message = card["message"]
    assert [a["label"] for a in message["actions"]] == ["Reject"] and message["document"] is None
    assert cards.TOO_LONG_LINE in message["text"] and cards.EFFECT_LINE in message["text"] and len(message["text"]) <= 1600
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is False and entry["approvable"] is False
    world.say("/approve 7")
    assert approve_calls(world) == [] and world.texts()[-1].startswith(bridge.TOO_LONG) and HASH not in world.texts()[-1] and "cli.py" not in world.texts()[-1]


def test_the_same_long_effect_on_a_platform_with_documents_sends_the_file_first_and_the_card_after_it_is_confirmed(world):
    grant(world)
    world.caps(max_text=300, documents=True)
    world.items[7] = effect(body="y" * 2000)
    world.bridge.tick()
    first, second = world.sent()
    assert first["message"]["document"]["text"].endswith("y" * 2000) and first["message"]["document"]["name"] == "effect-7.txt"
    assert first["message"]["actions"] == [] and cards.DOCUMENT_NOTE in first["message"]["text"], "the file goes alone, with no button"
    message = second["message"]
    assert message["document"] is None and cards.WHOLE_ABOVE in message["text"] and len(message["text"]) <= 300
    assert LABEL in [a["label"] for a in message["actions"]]
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is True and entry["approvable"] is True
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say(None, action=approve_action(world))
    assert wait_for(lambda: approve_calls(world))
    assert approve_calls(world)[0][2] == {"pending_id": 7, "sha256": HASH, "channel": "messaging"}


def test_a_file_that_the_provider_says_did_not_arrive_makes_a_card_with_no_approval_that_says_so(world):
    grant(world)
    world.caps(max_text=300, documents=True)
    world.standin.joinpath("document_fail.json").write_text("true")
    world.items[7] = effect(body="y" * 2000)
    world.bridge.tick()
    first, second = world.sent()
    assert first["message"]["document"] is not None
    message = second["message"]
    assert [a["label"] for a in message["actions"]] == ["Reject"] and message["document"] is None
    assert cards.DOCUMENT_LINE in message["text"] and cards.EFFECT_LINE in message["text"]
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is False and entry["approvable"] is False
    world.say("/approve 7")
    world.say(f"/approve 7 {HASH}")
    assert approve_calls(world) == [] and any(t.startswith(bridge.TOO_LONG) for t in world.texts()), "the reply is split to the platform's 300 characters"
    assert any("not delivered" in line for line in world.log)


def test_a_file_that_cannot_be_sent_or_cannot_be_told_to_have_arrived_is_not_delivered_and_a_deferred_one_is_tried_again(world, monkeypatch):
    grant(world)
    world.caps(max_text=300, documents=True)
    world.items[7] = effect(body="y" * 2000)
    real = world.bridge.messenger.send

    def raising(kind):
        def send(chat, message):
            if message.get("document"):
                raise providers.MessengerError(kind, "refused")
            return real(chat, message)
        return send

    monkeypatch.setattr(world.bridge.messenger, "send", raising("failed"))
    world.bridge.tick()
    [card] = world.sent()
    assert [a["label"] for a in card["message"]["actions"]] == ["Reject"] and cards.DOCUMENT_LINE in card["message"]["text"]
    fresh_bridge(world)
    monkeypatch.setattr(world.bridge.messenger, "send", raising("deferred"))
    world.bridge.tick()
    assert world.sent() == [] and world.bridge.ledger.data["cards"] == [], "nothing is recorded: the card is tried again"
    # a provider that answers with a plain id (it never reported the file) is treated as a file not delivered
    fresh_bridge(world)
    monkeypatch.setattr(world.bridge.messenger, "send", lambda chat, message: str(real(chat, message)))      # a plain str: no status came with it
    world.bridge.tick()
    assert [a["label"] for a in world.sent()[-1]["message"]["actions"]] == ["Reject"]


def test_a_plan_with_a_networked_step_is_approved_off_the_terminal_only_from_a_whole_card_and_with_the_cards_hash(world):
    grant(world, [*OPEN_POLICY, "approve-networked-plans"])
    world.items[1] = decision("plan", 1, plan_networked=True)
    world.bridge.tick()
    [card] = world.sent()
    assert "Approve" in [a["label"] for a in card["message"]["actions"]]
    action = card["message"]["actions"][0]["id"]
    world.say(f"/approve 1 {'f' * 64}")
    assert world.texts()[-1] == bridge.WRONG_HASH and approve_calls(world) == [], "a typed hash is the card's, for a plan as for an effect"
    world.fake.answers["approve"] = {"approved": True}
    world.say(None, action=action)
    assert approve_calls(world)[0][2] == {"pending_id": 1, "sha256": "p" * 64, "channel": "messaging"}
    # without the grant the card has no button: it says where to approve
    grant(world, OPEN_POLICY)
    fresh_bridge(world)
    world.bridge.tick()
    assert [a["label"] for a in world.sent()[0]["message"]["actions"]] == ["Reject"] and cards.PAGE_LINE in world.sent()[0]["message"]["text"]


def test_a_networked_plan_card_that_was_cut_or_whose_file_failed_approves_nothing(world):
    grant(world, [*OPEN_POLICY, "approve-networked-plans"])
    world.caps(max_text=1600, documents=False)
    world.items[1] = decision("plan", 1, body="z" * 3000, plan_networked=True)
    world.bridge.tick()
    [card] = world.sent()
    assert [a["label"] for a in card["message"]["actions"]] == ["Reject"] and cards.TOO_LONG_LINE in card["message"]["text"]
    world.say("/approve 1")
    assert approve_calls(world) == [] and world.texts()[-1].startswith(bridge.TOO_LONG)
    fresh_bridge(world)
    world.caps(max_text=300, documents=True)
    world.standin.joinpath("document_fail.json").write_text("true")
    world.bridge.tick()
    assert [a["label"] for a in world.sent()[-1]["message"]["actions"]] == ["Reject"] and cards.DOCUMENT_LINE in world.sent()[-1]["message"]["text"]
    world.say("/approve 1")
    assert approve_calls(world) == []
    # a card of before the flag, forced whole in the ledger by an old entry: a plan that reaches the network still needs `whole`
    for entry in world.bridge.ledger.data["cards"]:
        entry.pop("whole", None)
    world.say("/approve 1")
    assert approve_calls(world) == []
    # and a plan that reaches no network is as it always was, a cut card included
    world.items[2] = decision("plan", 2, body="z" * 3000, plan_networked=False, plan_sha256="s" * 64)
    world.caps(max_text=1600, documents=False)
    world.bridge.tick()
    assert "Approve" in [a["label"] for a in world.sent()[-1]["message"]["actions"]]


def test_an_effect_that_cannot_be_on_a_card_draws_no_button_and_no_card_or_typed_line_approves_it_even_with_the_group_granted(world):
    for word in ("send", "publish"):
        groups = [*OPEN_POLICY, f"approve-effect-{word}"]
        grant(world, groups)
        fresh_bridge(world)
        world.items[7] = effect(word=word, on_cards=False)         # an attachment, an image: the hash covers a file the card cannot carry
        world.bridge.tick()
        [card] = world.sent()
        assert [a["label"] for a in card["message"]["actions"]] == ["Reject"], word
        assert cards.EFFECT_LINE in card["message"]["text"] and cards.APPROVES_LINE not in card["message"]["text"]
        # forced: even a card the ledger calls whole, whatever the bridge was told, the decision says it does not fit
        for entry in world.bridge.ledger.data["cards"]:
            entry["whole"], entry["approvable"] = True, True
        world.say("/approve 7")
        world.say(f"/approve 7 {HASH}")
        world.say(None, action="1:approve")
        assert approve_calls(world) == [], word
        assert world.texts()[-2].startswith(bridge.TOO_LONG)
    # the same words with a text-only message or post are approvable
    grant(world, [*OPEN_POLICY, "approve-effect-send"])
    fresh_bridge(world)
    world.items[7] = effect(word="send", on_cards=True)
    world.bridge.tick()
    assert LABEL in [a["label"] for a in world.sent()[-1]["message"]["actions"]]


# --- the tap and the typed line -------------------------------------------------------------------------------------------------


def test_a_tap_approves_with_the_cards_hash_in_the_channel_messaging_and_replies(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say(None, action=approve_action(world))
    assert wait_for(lambda: world.texts()[-1] == "Approved #7.")
    [(_, _, kwargs)] = approve_calls(world)
    assert kwargs == {"pending_id": 7, "sha256": HASH, "channel": "messaging"}
    assert world.standin.joinpath("acks.jsonl").read_text().strip() == '{"ref": "ref-1"}'


def test_a_refusal_of_the_operations_layer_is_replied_and_nothing_else_is_said(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    world.fake.answers["approve"] = ops.OpsError("nothing was written: the page changed; the effect stays open", 1)
    world.say(None, action=approve_action(world))
    assert wait_for(lambda: world.texts()[-1] == "It was not done, and nothing was written. Try again in a moment, or check it on the platform's page.")      # plain words (LIVE-2); the full text is the terminal's
    assert len(approve_calls(world)) == 1 and "Approved" not in " ".join(world.texts()) and "the page changed" not in " ".join(world.texts())


def test_a_typed_approve_binds_to_the_newest_whole_card_and_a_typed_hash_must_be_the_cards(world):
    grant(world)
    world.items[7] = effect()
    world.say("/approve 7")      # no card yet: the person has seen nothing
    assert world.texts() == [bridge.NO_CARD] and approve_calls(world) == []
    world.bridge.tick()
    other = "d" * 64
    world.say(f"/approve 7 {other}")
    assert world.texts()[-1] == bridge.WRONG_HASH and approve_calls(world) == []
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("/approve 7")
    assert wait_for(lambda: len(approve_calls(world)) == 1) and approve_calls(world)[0][2] == {"pending_id": 7, "sha256": HASH, "channel": "messaging"}
    assert wait_for(lambda: world.texts()[-1] == "Approved #7.")
    world.say(f"/approve 7 {HASH.upper()}")
    assert wait_for(lambda: len(approve_calls(world)) == 2), "the typed hash is compared as a hash, in either case"
    assert inbound.parse({"text": f"/approve 7 {HASH}"}) == {"kind": "approve", "id": 7, "sha256": HASH}
    assert inbound.parse({"text": "/approve 7"}) == {"kind": "approve", "id": 7}


def test_a_stale_card_is_refused_with_the_decision_changed_and_a_new_card_with_the_new_hash_is_sent(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    old = approve_action(world)
    new_hash = "9" * 64
    world.items[7] = effect(sha=new_hash)              # the effect was opened again with other content
    world.say(None, action=old)
    assert approve_calls(world) == [] and bridge.CHANGED in world.texts()
    fresh = world.sent()[-1]["message"]
    assert "sha256" not in fresh["text"] and world.bridge.ledger.data["cards"][-1]["content_sha256"] == new_hash and LABEL in [a["label"] for a in fresh["actions"]]
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say(None, action=approve_action(world))
    assert wait_for(lambda: approve_calls(world)) and approve_calls(world)[0][2]["sha256"] == new_hash
    world.say(None, action=old)           # and the old button never works again
    assert len(approve_calls(world)) == 1


def test_a_card_of_before_the_whole_flag_and_a_decision_no_longer_open_approve_nothing(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    action = approve_action(world)
    for entry in world.bridge.ledger.data["cards"]:
        entry.pop("whole")                                  # a ledger entry of an earlier bridge: not whole (fails closed)
    world.say(None, action=action)
    world.say("/approve 7")
    assert approve_calls(world) == [] and world.texts()[-1].startswith(bridge.TOO_LONG)
    for entry in world.bridge.ledger.data["cards"]:
        entry["whole"] = True
    world.items[7] = {**effect(), "status": "resolved"}
    world.say(None, action=action)
    assert approve_calls(world) == [] and world.texts()[-1] == bridge.NOT_OPEN.format(number=7, status="resolved")


def test_the_policy_is_read_when_the_person_taps_so_a_grant_taken_back_approves_nothing(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    action = approve_action(world)
    grant(world, OPEN_POLICY)                 # the person narrowed the policy and accepted it after the card was sent
    world.say(None, action=action)
    assert approve_calls(world) == [] and world.texts()[-1].startswith(bridge.EFFECT_REPLY)
    grant(world)
    said = len(world.texts())
    world.fake.config_answer = lambda project: {"path": project, "sha256": "a" * 64, "accepted": False, "data_dir": "x", **world.config}
    world.say(None, action=action)       # a configuration that is not accepted refuses everything: the tap is not acted on, and (S12) the person is told once, in one plain sentence
    assert approve_calls(world) == [] and world.texts()[said:] == ["The project's configuration changed and must be accepted in the terminal before I can go on."]
    world.say(None, action=action)
    assert approve_calls(world) == [] and len(world.texts()) == said + 1, "the same file is told once"


def test_an_effect_card_sent_before_the_word_was_granted_is_sent_again_once_it_can_be_approved(world):
    world.items[7] = effect()
    world.config["channels"] = {"messaging": OPEN_POLICY}
    world.bridge.tick()
    assert len(world.sent()) == 1 and [a["label"] for a in world.sent()[0]["message"]["actions"]] == ["Reject"]
    world.bridge.tick()
    assert len(world.sent()) == 1, "nothing changed: nothing is sent again"
    grant(world)                                # the person accepted a configuration that grants the word
    world.bridge.tick()
    assert len(world.sent()) == 2 and LABEL in [a["label"] for a in world.sent()[1]["message"]["actions"]]
    world.bridge.tick()
    assert len(world.sent()) == 2, "and once"
    grant(world, GRANTED, notices="count")      # a card that cannot carry the text is not sent again for a grant it cannot use
    world.items[8] = effect(number=8, sha="8" * 64)
    world.bridge.tick()
    assert len(world.sent()) == 3 and [a["label"] for a in world.sent()[2]["message"]["actions"]] == ["Reject"]
    world.bridge.tick()
    assert len(world.sent()) == 3


def test_the_other_kinds_are_unchanged_a_plan_is_approved_with_its_hash_and_an_effect_word_changes_none_of_it(world):
    grant(world, [*GRANTED, "approve-networked-plans"])
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    world.fake.answers["approve"] = {"approved": True}
    world.say(None, action=world.sent()[0]["message"]["actions"][0]["id"])
    [(_, _, kwargs)] = approve_calls(world)
    assert kwargs == {"pending_id": 1, "sha256": "p" * 64, "channel": "messaging"} and world.texts()[-1] == "Approved #1."


def test_a_listed_sender_only_a_card_is_acted_on_in_its_own_chat_and_by_its_projects_senders(world):
    grant(world)
    world.items[7] = effect()
    world.bridge.tick()
    action = approve_action(world)
    world.say(None, action=action, sender="9999", chat="9999")        # another account: dropped with no reply and no call
    world.say(None, action=action, chat="4243")                       # the sender's own id in a chat that is not theirs: dropped too
    assert approve_calls(world) == [] and len(world.sent()) == 1


# --- the holes of the second review (regressions): a typed line approves only a card whose file arrived and that offered the approval --------


def test_a_card_sent_before_the_grant_with_a_file_the_provider_did_not_confirm_is_not_whole_and_a_typed_line_approves_nothing(world):
    grant(world, OPEN_POLICY)                           # not approvable now: the file travels inside the card's own message
    world.caps(max_text=300, documents=True)
    world.standin.joinpath("document_fail.json").write_text("true")
    world.items[7] = effect(body="y" * 2000)
    world.bridge.tick()
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is False and entry["approvable"] is False, "the file did not arrive, so the text is not whole"
    grant(world, GRANTED)                               # the person accepts the grant; before the next tick re-sends, they type /approve
    world.fake.answers["approve"] = {"task_state": "done"}
    world.say("/approve 7")
    world.say(f"/approve 7 {HASH}")
    assert approve_calls(world) == [] and any(t.startswith(bridge.TOO_LONG) for t in world.texts())


def test_a_provider_that_never_says_whether_the_file_arrived_is_no_confirmation(world, monkeypatch):
    grant(world, OPEN_POLICY)
    world.caps(max_text=300, documents=True)
    world.items[7] = effect(body="y" * 2000)
    real = world.bridge.messenger.send
    monkeypatch.setattr(world.bridge.messenger, "send", lambda chat, message: str(real(chat, message)))      # a plain str
    world.bridge.tick()
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is False
    monkeypatch.setattr(world.bridge.messenger, "send", real)       # a provider that confirms: the same inline card is whole
    fresh_bridge(world)
    world.bridge.tick()
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is True and entry["approvable"] is False


def test_a_whole_card_that_did_not_offer_the_approval_is_not_approved_by_a_typed_line(world):
    grant(world, OPEN_POLICY)
    world.items[7] = effect()                           # short: whole, but no approval was offered
    world.bridge.tick()
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is True and entry["approvable"] is False
    grant(world, GRANTED)
    world.say("/approve 7")
    assert approve_calls(world) == [] and world.texts()[-1] == bridge.NOT_OFFERED
    # a plain plan or an acceptance is not gated: the permission is read when the person acts, whatever the entry of its card says
    world.items[1] = decision("plan", 1)
    world.bridge.tick()
    for entry in world.bridge.ledger.data["cards"]:
        if entry["pending_id"] == 1:
            entry["approvable"] = False
    world.fake.answers["approve"] = {"approved": True}
    world.say("/approve 1")
    assert approve_calls(world)[0][2] == {"pending_id": 1, "sha256": "p" * 64, "channel": "messaging"}


def test_an_acceptance_card_sent_before_the_policy_allowed_it_is_approved_by_a_typed_line_after_the_policy_widens(world):
    grant(world, ["read", "talk", "answer"])                 # messaging lacks approve-acceptances: the card offers no approval
    world.items[3] = decision("acceptance", 3, body="Accept 2 deliveries.")
    world.bridge.tick()
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["approvable"] is False
    grant(world, OPEN_POLICY)                                # the person widens the policy (a group of the ceiling, accepted as ever)
    world.fake.answers["approve"] = {"accepted": True}
    world.say("/approve 3")
    assert approve_calls(world)[0][2] == {"pending_id": 3, "channel": "messaging"}, "as before POL-1: the permission is read when the person acts"
    assert bridge.NOT_OFFERED not in world.texts()


def test_a_networked_plan_card_from_before_the_grant_with_an_unconfirmed_file_approves_nothing_and_is_not_resent_for_ever(world):
    grant(world, OPEN_POLICY)
    world.caps(max_text=300, documents=True)
    world.standin.joinpath("document_fail.json").write_text("true")
    world.items[1] = decision("plan", 1, body="z" * 3000, plan_networked=True)
    world.bridge.tick()
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["whole"] is False
    grant(world, [*OPEN_POLICY, "approve-networked-plans"])
    world.fake.answers["approve"] = {"approved": True}
    world.bridge.tick()          # the grant is there: the plan gets a card that offers the approval, file first
    world.say("/approve 1")
    assert approve_calls(world) == [], "its file failed again: nothing is approved"
    sent = len(world.sent())
    for _ in range(4):
        world.bridge.tick()
    assert len(world.sent()) == sent, "and nothing is sent again"


def test_a_file_that_keeps_failing_is_sent_once_with_its_card_and_not_again_on_every_tick(world):
    grant(world)
    world.caps(max_text=300, documents=True)
    world.standin.joinpath("document_fail.json").write_text("true")
    world.items[7] = effect(body="y" * 2000)
    for _ in range(5):
        world.bridge.tick()
    assert len(world.sent()) == 2, "the file and the card without an approval, once"
    [entry] = world.bridge.ledger.data["cards"]
    assert entry["blocked"] == "document" and entry["approvable"] is False and entry["whole"] is False
    world.items[7] = effect(sha="9" * 64, body="y" * 2000)      # a changed content is a new card, with a new try
    world.bridge.tick()
    assert len(world.sent()) == 4
    world.standin.joinpath("document_fail.json").unlink()
    world.items[8] = effect(number=8, sha="8" * 64, body="y" * 2000)
    world.bridge.tick()
    assert LABEL in [a["label"] for a in world.sent()[-1]["message"]["actions"]], "a file that arrives gives the card its button"


def test_a_hash_typed_with_approve_must_be_the_cards_for_an_acceptance_too(world):
    grant(world)
    world.items[3] = decision("acceptance", 3, body="Accept 2 deliveries.")
    world.bridge.tick()
    world.fake.answers["approve"] = {"accepted": True}
    world.say(f"/approve 3 {'f' * 64}")
    assert approve_calls(world) == [] and world.texts()[-1] == bridge.WRONG_HASH
    card_hash = world.bridge.ledger.data["cards"][0]["content_sha256"]
    world.say(f"/approve 3 {card_hash}")
    assert approve_calls(world)[0][2] == {"pending_id": 3, "channel": "messaging"}


def test_the_persons_own_pending_tries_a_card_whose_file_failed_once_per_request_and_a_tick_never_does(world):
    grant(world)
    world.caps(max_text=300, documents=True)
    world.standin.joinpath("document_fail.json").write_text("true")
    world.items[7] = effect(body="y" * 2000)
    world.bridge.tick()
    assert len(world.sent()) == 2 and cards.DOCUMENT_LINE in world.sent()[1]["message"]["text"] and "/pending" in cards.DOCUMENT_LINE
    for _ in range(3):
        world.bridge.tick()
    assert len(world.sent()) == 2, "a tick never retries it"
    world.say("/pending")                                     # one request: the file first, then the card (the reply that lists comes first)
    after = len(world.sent())
    assert after == 5 and world.sent()[after - 2]["message"]["document"] is not None, "the list, the file, the card"
    [entry] = [e for e in world.bridge.ledger.data["cards"] if e["pending_id"] == 7][-1:]
    assert entry["blocked"] == "document" and entry["whole"] is False, "it failed again: the same confirmation rules, the same card"
    for _ in range(3):
        world.bridge.tick()
    assert len(world.sent()) == after
    world.standin.joinpath("document_fail.json").unlink()      # the file arrives this time
    world.say("/pending")
    last = world.sent()[-1]["message"]
    assert LABEL in [a["label"] for a in last["actions"]] and last["document"] is None
    entry = [e for e in world.bridge.ledger.data["cards"] if e["pending_id"] == 7][-1]
    assert entry["whole"] is True and entry["approvable"] is True and not entry.get("blocked")

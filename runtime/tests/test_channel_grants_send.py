"""A granted e-mail on the messaging channel (package POL-1; the seam EMAIL-SEND named: runtime/effect_send.py `APPROVAL_GROUP` and `on_cards`). The
world is test_send_email.py's: a fake SMTP and IMAP server on loopback, the real provider, a stand-in tree. What is held here:

  * a plain e-mail is approved on a messaging app once the accepted configuration grants `approve-effect-send`, with the hash of the exact message,
    and is sent once to exactly the recipients of the document;
  * an e-mail with an attachment is never approvable from a card, the group granted or not: the hash covers a file the card cannot carry; the
    operations layer refuses it, the card draws no approve action, and the terminal still sends it;
  * the grant of another word covers nothing here.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants_send.py
"""
from __future__ import annotations

import pytest

import standin_tree as st
from test_channel_grants import accept
from test_send_email import ARGS, PATH, approve, effect_doc, opened, sent, world  # noqa: F401  (the e-mail world of test_send_email.py)

ops = st.load("ops")
operations = st.load("operations")
cards = st.load("messaging_cards")


def card_of(world, item, notices="text"):
    """The messaging card the bridge would build for this decision, from what the operations layer reports and the policy it accepted."""
    full = ops.pending(world["path"], item["id"])
    found = ops.config(world["path"])
    return cards.build("office", full, {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True},
                       found["channels"], notices, None, operations=operations)


def labels(card):
    return [a["label"] for a in card["message"]["actions"]]


def test_a_plain_e_mail_is_approved_on_messaging_after_the_grant_with_its_hash_and_sent_once(world):  # noqa: F811
    task, item = opened(world)
    full = ops.pending(world["path"], item["id"])
    assert full["effect_word"] == "send" and full["effect_on_cards"] is True
    with pytest.raises(ops.OpsError) as no:
        approve(world, item, "messaging")
    assert "an effect is approved in the terminal, with its hash" in str(no.value) and sent(world) == []
    assert "Approve this exact content" not in labels(card_of(world, item)) and cards.EFFECT_LINE in card_of(world, item)["message"]["text"]
    accept(world["path"], {"messaging": ["read", "approve-effect-write"]})         # another word: nothing for an e-mail
    with pytest.raises(ops.OpsError):
        approve(world, item, "messaging")
    assert sent(world) == []
    accepted = accept(world["path"], {"messaging": ["read", "approve-effect-send"]})
    assert [w["group"] for w in accepted["widened"]] == ["approve-effect-send"] and "e-mail" in accepted["widened"][0]["means"]
    card = card_of(world, item)
    assert "Approve this exact content" in labels(card) and card["whole"] is True and card["approvable"] is True
    with pytest.raises(ops.OpsError) as wrong:
        ops.approve(world["path"], item["id"], "0" * 64, channel="messaging")
    assert "nothing was approved" in str(wrong.value) and sent(world) == []
    done = approve(world, item, "messaging")
    assert done["task_state"] == "done" and done["result"]["sent"] is True and len(sent(world)) == 1
    [taken] = sent(world)
    assert taken["to"] == ["ana@client.example"] and effect_doc(world, task)["effect"] == "send"
    with pytest.raises(ops.OpsError):
        approve(world, item, "messaging")
    assert len(sent(world)) == 1, "sent once"


def test_an_e_mail_with_an_attachment_is_not_approvable_on_messaging_even_with_the_group_granted(world):  # noqa: F811
    task, item = opened(world, attach=[PATH])
    full = ops.pending(world["path"], item["id"])
    assert full["effect_word"] == "send" and full["effect_on_cards"] is False, "the document says it has an attachment, so it is not on a card"
    accept(world["path"], {"messaging": ["read", "approve-effect-send"]})
    assert ops.config(world["path"])["accepted"] is True
    # the card: no approve action, the command and the page are the way
    card = card_of(world, item)
    assert "Approve this exact content" not in labels(card) and card["approvable"] is False and cards.EFFECT_LINE in card["message"]["text"]
    # the operations layer: refused before anything is sent, with the hash right and the group granted
    with pytest.raises(ops.OpsError) as no:
        approve(world, item, "messaging")
    assert "more than a card can show" in str(no.value) and sent(world) == []
    for channel in ("chat", "mcp", None):
        with pytest.raises(ops.OpsError):
            approve(world, item, channel)
    # a line typed into say never approves it, on any channel
    for channel in ("messaging", "chat"):
        assert ops.say(world["path"], f"/approve {item['id']} {item['payload_sha256']}", channel=channel)["reply"].startswith("error: ")
    assert sent(world) == [] and ops.pending(world["path"], item["id"])["status"] == "open"
    # the terminal sends it, with its hash
    done = approve(world, item, "terminal")
    assert done["result"]["sent"] is True and len(sent(world)) == 1
    import email
    import email.policy
    [attached] = list(email.message_from_bytes(sent(world)[0]["data"], policy=email.policy.default).iter_attachments())
    assert attached.get_filename() == "invoice.pdf"


def test_the_same_grant_with_the_notices_of_count_draws_no_approve_action_for_a_plain_e_mail(world):  # noqa: F811
    task, item = opened(world)
    accept(world["path"], {"messaging": ["read", "approve-effect-send"]})
    assert "Approve this exact content" in labels(card_of(world, item))
    assert "Approve this exact content" not in labels(card_of(world, item, "count")) and ARGS["subject"] not in card_of(world, item, "count")["message"]["text"]

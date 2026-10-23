"""A granted post on the messaging channel (package POL-1; the seam PUBLISH-EFFECT named: runtime/effect_publish.py `APPROVAL_GROUP` and `on_cards`).
The world is test_publish_post.py's: a stand-in publisher provider and a stand-in tree. What is held here:

  * a post without an image is approved on a messaging app once the accepted configuration grants `approve-effect-publish`, with the hash of the
    exact text, and is published once;
  * a post with an image is never approvable from a card, the group granted or not: the hash covers the image, which the card cannot carry; the
    operations layer refuses it, the card draws no approve action, and the terminal still publishes it.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_channel_grants_publish.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

import standin_tree as st
from test_channel_grants import accept
from test_publish_post import CONTENT, approve, confirmed, content_file, opened, posts, world  # noqa: F401  (the post world of test_publish_post.py)

ops = st.load("ops")
operations = st.load("operations")
cards = st.load("messaging_cards")

LABEL = "Approve this exact content"


def card_of(world, item, notices="text"):
    full = ops.pending(world["path"], item["id"])
    found = ops.config(world["path"])
    return cards.build("studio", full, {"buttons": True, "max_buttons": 6, "max_text": 4096, "documents": False, "url_buttons": True, "reply_context": True},
                       found["channels"], notices, None, operations=operations)


def labels(card):
    return [a["label"] for a in card["message"]["actions"]]


def test_a_post_without_an_image_is_approved_on_messaging_after_the_grant_with_its_hash_and_published_once(world):  # noqa: F811
    Path(world["path"], CONTENT).write_text(content_file(image=None), encoding="utf-8")
    task, item = opened(world)
    full = ops.pending(world["path"], item["id"])
    assert full["effect_word"] == "publish" and full["effect_on_cards"] is True
    with pytest.raises(ops.OpsError) as no:
        approve(world, item, "messaging")
    assert "an effect is approved in the terminal, with its hash" in str(no.value) and confirmed(world) == []
    accept(world["path"], {"messaging": ["read", "approve-effect-send"]})            # the e-mail's word covers no post
    with pytest.raises(ops.OpsError):
        approve(world, item, "messaging")
    assert confirmed(world) == []
    accepted = accept(world["path"], {"messaging": ["read", "approve-effect-publish"]})
    assert [w["group"] for w in accepted["widened"]] == ["approve-effect-publish"] and "post" in accepted["widened"][0]["means"]
    assert LABEL in labels(card_of(world, item))
    done = approve(world, item, "messaging")
    assert done["task_state"] == "done" and len(confirmed(world)) == 1 and len(posts(world)) == 1
    with pytest.raises(ops.OpsError):
        approve(world, item, "messaging")
    assert len(posts(world)) == 1, "published once"


def test_a_post_with_an_image_is_not_approvable_on_messaging_even_with_the_group_granted(world):  # noqa: F811
    task, item = opened(world)                                       # the default content file has an image
    full = ops.pending(world["path"], item["id"])
    assert full["effect_word"] == "publish" and full["effect_on_cards"] is False
    accept(world["path"], {"messaging": ["read", "approve-effect-publish"]})
    card = card_of(world, item)
    assert LABEL not in labels(card) and card["approvable"] is False and cards.EFFECT_LINE in card["message"]["text"]
    with pytest.raises(ops.OpsError) as no:
        approve(world, item, "messaging")
    assert "more than a card can show" in str(no.value) and confirmed(world) == [] and posts(world) == []
    for channel in ("chat", "mcp", None):
        with pytest.raises(ops.OpsError):
            approve(world, item, channel)
    for channel in ("messaging", "chat"):
        assert ops.say(world["path"], f"/approve {item['id']} {item['payload_sha256']}", channel=channel, sender=("telegram:4242" if channel == "messaging" else None))["reply"].startswith("error: ")
    assert posts(world) == [] and ops.pending(world["path"], item["id"])["status"] == "open"
    done = approve(world, item, "terminal")
    assert done["task_state"] == "done" and len(posts(world)) == 1

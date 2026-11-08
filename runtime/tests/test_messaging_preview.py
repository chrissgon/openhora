"""The preview of a delivery on a messaging app (package V1d-2, decision 14; runtime/messaging_preview.py, `Bridge._send_card`): the deliver card offers its approval
only after the provider confirmed the preview video in that chat. The bridge world, the stand-in operations object and the stand-in messenger are those of
test_messaging.py; `video_preview` is a helper of the operations layer and not a row, so each test gives the stand-in its own. Offline, no model, no network;
every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_messaging_preview.py
"""
from __future__ import annotations

import json

import pytest

import standin_tree as st
from test_messaging import OPEN_POLICY, SENDER, decision, world  # noqa: F401  (the bridge world of test_messaging.py)

ops = st.load("ops")
providers = st.load("messaging_provider")
messaging_preview = st.load("messaging_preview")

HASH = "d" * 64
GRANTED = [*OPEN_POLICY, "approve-effect-deliver"]
APPROVE = "Approve this exact content"      # the label of the approve button of an effect card (messaging_cards EFFECT_LABEL)
MP4 = b"\x00\x00\x00\x18ftypmp42" + bytes(64)
VIDEO_CAPS = {"send_files": True, "max_send_bytes": 1 << 20, "video_types": ["mp4"], "max_video_bytes": 1 << 20}


def deliver(number=7, **more):
    fields = {"payload_sha256": HASH, "effect_word": "deliver", "effect_on_cards": True, **more}
    return decision("effect", number, title="Deliver the video", body="Platform: instagram\nVideo: render.mp4", **fields)


def given(world, data=MP4, caps=VIDEO_CAPS, policy=GRANTED):
    """The world with a granted sender, a provider with `caps`, and a preview the operations layer answers with `data` (None: refuses)."""
    world.config["channels"]["messaging"] = list(policy)
    world.caps(**caps)
    world.asked = []

    def video_preview(project, pending_id, channel=None, sender=None):
        world.asked.append((pending_id, channel, sender))
        if data is None:
            raise ops.OpsError("this video has no preview: approve it in the terminal or on the page", 1)
        return {"name": "video-0123456789ab.mp4", "kind": "video", "data": data, "size": len(data), "sha256": "e" * 64}
    world.fake.video_preview = video_preview
    world.items[7] = deliver()


def files(world):
    return [s["message"] for s in world.sent() if s["message"].get("file")]


def the_card(world):
    return [s["message"] for s in world.sent() if not s["message"].get("file")][-1]


def ledger_card(world):
    return world.bridge.ledger.data["cards"][-1]


def approvals(world):
    return [c[2] for c in world.calls("approve")]


def test_the_preview_goes_first_as_a_video_then_the_card_with_an_approve_button_and_the_ledger_is_whole(world):
    given(world)
    world.bridge.tick()
    [video] = files(world)
    assert video["file"]["kind"] == "video" and video["file"]["name"] == "video-0123456789ab.mp4" and bytes.fromhex(video["file"]["bytes_hex"]) == MP4
    assert world.asked == [(7, "messaging", "telegram:" + SENDER)]
    sent = world.sent()
    assert sent[0]["message"] is not sent[-1]["message"] and not sent[-1]["message"].get("file"), "the card follows the video"
    assert [a["label"] for a in the_card(world)["actions"]][0] == APPROVE
    assert ledger_card(world)["whole"] is True and ledger_card(world)["approvable"] is True


def test_a_provider_without_video_types_gets_no_video_and_a_card_with_no_approval_that_says_so(world):
    given(world, caps={"send_files": True, "max_send_bytes": 1 << 20})
    world.bridge.tick()
    assert files(world) == [] and world.asked == []
    card = the_card(world)
    assert all(a["label"] != APPROVE for a in card["actions"]) and "approves" not in card["text"].lower().replace("approving", "")
    assert ledger_card(world)["whole"] is False and not any(v == "approve" for v in ledger_card(world)["actions"].values())


def test_a_provider_that_answers_the_file_failed_or_cannot_tell_gives_a_card_with_no_approval(world):
    given(world)
    (world.standin / "file_fail.json").write_text("true")
    world.bridge.tick()
    assert len(files(world)) == 1
    assert ledger_card(world)["whole"] is False and not any(v == "approve" for v in ledger_card(world)["actions"].values())
    # a plain str is no confirmation either
    sent = providers.Sent("1", False)
    assert getattr(sent, "document_failed") is False and getattr(str("1"), "document_failed", True) is True


def test_a_preview_over_what_the_app_takes_is_not_sent(world):
    given(world, caps=dict(VIDEO_CAPS, max_video_bytes=10))
    world.bridge.tick()
    assert files(world) == [] and world.asked == [(7, "messaging", "telegram:" + SENDER)]
    assert ledger_card(world)["whole"] is False and not any(v == "approve" for v in ledger_card(world)["actions"].values())


def test_the_operations_layer_refusing_the_preview_gives_a_card_with_no_approval(world):
    given(world, data=None)
    world.bridge.tick()
    assert files(world) == [] and ledger_card(world)["whole"] is False
    assert not any(v == "approve" for v in ledger_card(world)["actions"].values())


def test_a_send_that_raises_deferred_keeps_the_card_and_sends_nothing(world, monkeypatch):
    given(world)
    deferred = []

    def refuse(chat, message, guard_text=False):
        raise providers.MessengerError("deferred", "not now")
    monkeypatch.setattr(world.bridge, "deliver", refuse)
    monkeypatch.setattr(world.bridge, "defer", lambda project, item, chat: deferred.append(item["id"]))
    assert world.bridge._send_card(world.projects[0], world.bridge.settings(world.projects[0]), world.items[7], SENDER) is False
    assert deferred == [7] and world.sent() == [] and world.bridge.ledger.data["cards"] == []


def test_a_card_that_is_not_a_deliver_effect_is_sent_as_before_with_no_call_to_the_preview(world):
    given(world)
    world.items[7] = decision("effect", 7, title="Write to the page", body="Replace the page.", payload_sha256=HASH, effect_word="write", effect_on_cards=True)
    world.config["channels"]["messaging"] = [*OPEN_POLICY, "approve-effect-write"]
    world.bridge.tick()
    assert world.asked == [] and files(world) == [] and len(world.sent()) == 1
    assert messaging_preview.applies(world.items[7]) is False
    assert messaging_preview.applies(deliver()) is True and messaging_preview.applies(deliver(effect_on_cards=False)) is False


def test_the_tap_on_the_approve_button_of_the_confirmed_card_approves_with_the_hash_and_a_card_with_no_approval_cannot_be_tapped(world):
    given(world)
    world.bridge.tick()
    [button] = [a["id"] for a in the_card(world)["actions"] if a["label"] == APPROVE]
    world.say(None, action=button)
    assert [(c["pending_id"], c.get("sha256")) for c in approvals(world)] == [(7, HASH)]
    # the same decision, the preview not confirmed: the card has no button, and a tap made up from its sequence number approves nothing
    world.fake.calls.clear()
    world.items[7]["status"] = "resolved"
    (world.standin / "file_fail.json").write_text("true")
    world.items[8] = deliver(8, payload_sha256="c" * 64)
    world.bridge.tick()
    card = ledger_card(world)
    assert card["pending_id"] == 8 and card["whole"] is False
    seq = card["message_id"]
    world.say(None, action=f"{int(seq) - 100}:approve")
    assert approvals(world) == []

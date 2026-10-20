"""Offline tests for the forward flag of the WhatsApp Cloud provider (providers/messenger/whatsapp-cloud.py, shared code in whatsapp_meta.py) (FWD): a
webhook message whose `context` holds `forwarded` or `frequently_forwarded` (developers.facebook.com, "Incoming message webhooks": the first only when
forwarded five times or fewer, the second only when more) is an update with `forwarded: true`; a reply (`context.id` alone) is the person's own text and
never is one. The oracle is this file's literal list of context objects. No network, no Meta.

Run: uv run --with pytest pytest providers/messenger/tests/test_forward_whatsapp_cloud.py
"""
from __future__ import annotations

import pytest

from whatsapp_cloud_kit import PERSON, TEXT, Rig, envelope, media_message, text_message, wc

FORWARDS = {
    "forwarded": {"forwarded": True},
    "frequently forwarded": {"frequently_forwarded": True},
    "both": {"forwarded": True, "frequently_forwarded": True},
    "forwarded with a reply id": {"forwarded": True, "id": "wamid.CARD"},
}
NOT_FORWARDS = {
    "no context": None,
    "a reply": {"id": "wamid.CARD"},
    "a button on a business message": {"from": "15550000000", "id": "wamid.AD"},
    "forwarded false": {"forwarded": False},
    "frequently forwarded false": {"frequently_forwarded": False},
    "an empty context": {},
}


def message(wamid, context, kind="text"):
    made = text_message(wamid=wamid) if kind == "text" else media_message("document", wamid=wamid)
    if context is not None:
        made["context"] = context
    return made


def problems(flagged) -> list:
    """What `flagged` (context object -> bool) gets wrong against the literal lists."""
    found = [f"{name}: not flagged" for name, context in FORWARDS.items() if not flagged(context)]
    found += [f"{name}: flagged" for name, context in NOT_FORWARDS.items() if flagged(context)]
    return found


@pytest.fixture
def rig(tmp_path):
    made = Rig(tmp_path / "r")
    yield made.start()
    made.stop()


def test_the_flag_function_follows_the_literal_lists_and_a_null_value_fails_closed():
    assert problems(lambda c: wc.meta.forwarded_context({"context": c} if c is not None else {})) == []
    assert wc.meta.forwarded_context({"context": {"forwarded": None, "id": "x"}}) is False
    assert wc.meta.forwarded_context({"context": {"forwarded": "yes"}}) is True
    assert wc.meta.forwarded_context({"context": "not an object"}) is False


def test_a_text_webhook_becomes_an_update_flagged_exactly_when_its_context_says_forwarded(rig):
    for n, context in enumerate({**FORWARDS, **NOT_FORWARDS}.values()):
        assert rig.post(envelope([message(f"wamid.T{n}", context)]))[0] == 200
    updates = rig.out.updates()
    assert len(updates) == len(FORWARDS) + len(NOT_FORWARDS)
    by_id = {u["update_id"]: u for u in updates}
    for n, (name, context) in enumerate({**FORWARDS, **NOT_FORWARDS}.items()):
        update = by_id[f"wamid.T{n}"]
        assert update["text"] == TEXT and update["sender"] == PERSON, name
        if name in FORWARDS:
            assert update["forwarded"] is True, name
        else:
            assert "forwarded" not in update, name
        if context and context.get("id") and name == "a reply":
            assert update["reply_to"] == "wamid.CARD"


def test_a_forwarded_file_keeps_its_attachment_and_is_flagged(rig):
    assert rig.post(envelope([message("wamid.D1", {"forwarded": True}, kind="document"), message("wamid.D2", {"id": "wamid.CARD"}, kind="document")]))[0] == 200
    first, second = rig.out.updates()
    assert first["forwarded"] is True and first["attachments"][0]["type"] == "application/pdf"
    assert "forwarded" not in second and second["attachments"]


def test_a_tap_on_a_button_is_never_flagged_even_with_a_forwarded_context(rig):
    from whatsapp_cloud_kit import button_reply
    tap = button_reply()
    tap["context"]["forwarded"] = True
    assert rig.post(envelope([tap]))[0] == 200
    [update] = rig.out.updates()
    assert update["action"] == "7:approve" and "forwarded" not in update


def test_vacuity_the_oracle_catches_a_function_that_never_flags_and_one_that_flags_a_reply():
    assert problems(lambda c: False) and problems(lambda c: bool(c))

"""Offline tests for the forward flag of the WhatsApp provider of Twilio (providers/messenger/whatsapp-twilio.py, shared code in whatsapp_meta.py) (FWD).
Twilio's inbound webhook has two WhatsApp fields, `Forwarded` ("true" if the message has been forwarded once) and `FrequentlyForwarded` (frequently
forwarded, by WhatsApp's forwarding limits), documented at twilio.com/docs/messaging/guides/webhook-request: a message that carries one is an update with
`forwarded: true`, so this provider is NOT forward-blind and declares no `forward_blind`. The oracle is this file's literal lists of field sets. No network.

Run: uv run --with pytest pytest providers/messenger/tests/test_forward_twilio.py
"""
from __future__ import annotations

import pytest

import whatsapp_twilio_kit as kit
from whatsapp_twilio_kit import PERSON, TEXT, card_tap, inbound, with_media, wt

FORWARDS = {
    "forwarded": {"Forwarded": "true"},
    "forwarded, capitalised": {"Forwarded": "True"},
    "frequently forwarded": {"FrequentlyForwarded": "true"},
    "both": {"Forwarded": "true", "FrequentlyForwarded": "true"},
    "an unreadable value fails closed": {"Forwarded": "yes"},
}
NOT_FORWARDS = {
    "no field": {},
    "forwarded false": {"Forwarded": "false"},
    "forwarded empty": {"Forwarded": ""},
    "frequently forwarded false": {"FrequentlyForwarded": "False"},
    "a reply": {"OriginalRepliedMessageSid": "SM" + "0" * 32},
}


def problems(flagged) -> list:
    found = [f"{name}: not flagged" for name, fields in FORWARDS.items() if not flagged(fields)]
    found += [f"{name}: flagged" for name, fields in NOT_FORWARDS.items() if flagged(fields)]
    return found


@pytest.fixture
def rig(tmp_path):
    made = kit.Rig(tmp_path).start()
    yield made
    made.stop()


def test_the_flag_function_follows_the_literal_lists():
    assert problems(wt.meta.forwarded_field) == []


def test_a_text_webhook_becomes_an_update_flagged_exactly_when_a_forward_field_says_so(rig):
    every = {**FORWARDS, **NOT_FORWARDS}
    for n, fields in enumerate(every.values(), start=1):
        assert rig.post(inbound(n, **fields))[0] == 200
    by_id = {u["update_id"]: u for u in rig.out.updates()}
    assert len(by_id) == len(every)
    for n, name in enumerate(every, start=1):
        update = by_id[kit.sid(n)]
        assert update["text"] == TEXT and update["sender"] == PERSON, name
        assert (update.get("forwarded") is True) == (name in FORWARDS), name
        assert "forwarded" not in update or update["forwarded"] is True


def test_a_forwarded_file_keeps_its_attachment_and_is_flagged(rig):
    assert rig.post(with_media(1, Forwarded="true"))[0] == 200
    assert rig.post(with_media(2))[0] == 200
    first, second = rig.out.updates()
    assert first["forwarded"] is True and first["attachments"] and "forwarded" not in second and second["attachments"]


def test_a_tap_is_never_flagged(rig):
    assert rig.post(card_tap(3, Forwarded="true"))[0] == 200
    [update] = rig.out.updates()
    assert update["action"] == "7:approve" and "forwarded" not in update


def test_the_provider_declares_it_sees_forwards():
    assert "forward_blind" not in wt.capabilities() and "forward_blind" not in wt.capabilities({"buttons": True})


def test_vacuity_the_oracle_catches_a_function_that_never_flags_and_one_that_flags_a_reply():
    assert problems(lambda fields: False) and problems(lambda fields: bool(fields))

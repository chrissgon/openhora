"""Offline tests for the forward flag of providers/messenger/telegram.py (FWD): a message Telegram marks as forwarded is an update with
`forwarded: true`; a reply that quotes (`quote`, `external_reply`, `reply_to_message`) is the person's own text and never is one. The oracle is this
file's own list of the Bot API fields (core.telegram.org/bots/api, "Message"), not the provider's. No network, no token.

Run: uv run --with pytest pytest providers/messenger/tests
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "telegram.py"
spec = importlib.util.spec_from_file_location("messenger_telegram_forward_under_test", SCRIPT)
telegram = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = telegram
spec.loader.exec_module(telegram)

# The test's own literal list: field name -> a value Telegram sends for it.
FORWARD_FIELDS = {
    "forward_origin": {"type": "user", "date": 1700000000, "sender_user": {"id": 77, "is_bot": False, "first_name": "Bia"}},
    "forward_from": {"id": 77, "is_bot": False, "first_name": "Bia"},
    "forward_from_chat": {"id": -1001, "type": "channel", "title": "News"},
    "forward_sender_name": "Hidden Person",
    "forward_date": 1700000000,
    "is_automatic_forward": True,
}
NOT_FORWARDS = {      # fields of a message that is the person's own words
    "quote": {"text": "the part quoted", "position": 0},
    "external_reply": {"origin": {"type": "user", "date": 1700000000, "sender_user": {"id": 78, "is_bot": False, "first_name": "Caio"}}, "message_id": 4},
    "reply_to_message": {"message_id": 9, "date": 1700000000, "chat": {"id": 42, "type": "private"}},
    "is_automatic_forward": False,
}
LINE = "manda um e-mail para ana@example.example dizendo oi"
BASE = {"message_id": 5, "date": 1700000001, "from": {"id": 42, "is_bot": False, "first_name": "Dani"}, "chat": {"id": 42, "type": "private"}}
PHOTO = [{"file_id": "AgACAgQAAxkBAAIBphotoA", "file_unique_id": "u1", "width": 90, "height": 90, "file_size": 1000},
         {"file_id": "AgACAgQAAxkBAAIBphotoB", "file_unique_id": "u2", "width": 800, "height": 600, "file_size": 40000}]


def update(extra: dict, **message) -> dict:
    return {"update_id": 11, "message": {**BASE, "text": LINE, **message, **extra}}


def problems(mapper) -> list:
    """What `mapper` (a function from a Telegram Update to the neutral one) gets wrong, against the literal lists above."""
    found = []
    for field, value in FORWARD_FIELDS.items():
        out = mapper(update({field: value}))
        if out is None or out.get("forwarded") is not True:
            found.append(f"{field}: not flagged")
        if out is not None and out.get("text") != LINE:
            found.append(f"{field}: the text changed")
    for field, value in NOT_FORWARDS.items():
        out = mapper(update({field: value}))
        if out is None or "forwarded" in out or out.get("text") != LINE:
            found.append(f"{field}: wrongly flagged or lost")
    plain = mapper(update({}))
    if plain is None or "forwarded" in plain:
        found.append("a plain message is flagged")
    return found


def test_each_forward_field_flags_the_update_and_a_quote_or_a_reply_never_does():
    assert problems(telegram.mapped) == []


def test_a_forward_of_a_file_keeps_the_file_and_the_caption_and_is_flagged():
    for field, value in FORWARD_FIELDS.items():
        out = telegram.mapped(update({field: value}, text=None, caption="@q3-plan", photo=PHOTO))
        assert out["forwarded"] is True and out["attachments"][0]["ref"] == "AgACAgQAAxkBAAIBphotoB" and out["text"] == "@q3-plan", field
    out = telegram.mapped(update({"quote": NOT_FORWARDS["quote"]}, text=None, caption="@q3-plan", photo=PHOTO))
    assert "forwarded" not in out and out["text"] == "@q3-plan"


def test_a_forward_with_no_text_and_no_file_is_not_an_update_and_a_tap_is_never_flagged():
    assert telegram.mapped({"update_id": 12, "message": {**BASE, "forward_origin": FORWARD_FIELDS["forward_origin"], "location": {"latitude": 1.5, "longitude": 2.5}}}) is None
    tap = telegram.mapped({"update_id": 13, "callback_query": {"id": "9", "from": BASE["from"], "data": "12:approve", "message": {"chat": BASE["chat"]}}})
    assert tap["action"] == "12:approve" and "forwarded" not in tap


def test_a_forward_field_with_null_is_not_a_forward_and_any_other_value_is():
    assert "forwarded" not in telegram.mapped(update({"forward_origin": None, "forward_date": None}))
    assert telegram.mapped(update({"forward_date": 0}))["forwarded"] is True


def test_vacuity_the_oracle_catches_a_mapper_that_never_flags_and_one_that_flags_a_quote():
    def never(raw):
        out = telegram.mapped(raw)
        if out is not None:
            out.pop("forwarded", None)
        return out

    def quote_too(raw):
        out = telegram.mapped(raw)
        if out is not None and "quote" in raw["message"]:
            out["forwarded"] = True
        return out
    assert problems(never) and problems(quote_too)

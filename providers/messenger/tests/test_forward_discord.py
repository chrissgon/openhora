"""Offline tests for the forward flag of providers/messenger/discord.py (FWD): a direct message whose `message_reference` has `type` 1 (FORWARD), that holds
`message_snapshots`, or that carries the HAS_SNAPSHOT flag (1 << 14) is an update with `forwarded: true` (Discord's message resource, "Message Reference
Types" and "Message Snapshot Structure"); a reply (`type` 0, or no type) is the person's own text and never is one. The words of a forward are in its
snapshot, which is never read. The oracle is this file's literal lists. No network, no websockets library.

Run: uv run --with pytest pytest providers/messenger/tests/test_forward_discord.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "discord.py"
spec = importlib.util.spec_from_file_location("messenger_discord_forward_under_test", SCRIPT)
discord = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discord
spec.loader.exec_module(discord)

USER = "3001"
LINE = "manda um e-mail para ana@example.example dizendo oi"
SNAPSHOT = [{"message": {"type": 0, "content": "an e-mail someone else wrote", "attachments": [], "timestamp": "2026-10-20T10:00:00+00:00"}}]
FORWARDS = {
    "reference type 1": {"message_reference": {"type": 1, "message_id": "4001", "channel_id": "7002"}},
    "snapshots": {"message_snapshots": SNAPSHOT},
    "flag": {"flags": 1 << 14},
    "flag among others": {"flags": (1 << 14) | 4},
    "reference and snapshots": {"message_reference": {"type": 1, "message_id": "4001", "channel_id": "7002"}, "message_snapshots": SNAPSHOT},
}
NOT_FORWARDS = {
    "no reference": {},
    "a reply, typed": {"message_reference": {"type": 0, "message_id": "4001", "channel_id": "7001"}},
    "a reply, untyped": {"message_reference": {"message_id": "4001", "channel_id": "7001"}},
    "no snapshots": {"message_snapshots": []},
    "other flags": {"flags": 4},
    "the flag as text": {"flags": "16384"},
}


def dm(content=LINE, **extra) -> dict:
    d = {"id": "5001", "type": 0, "channel_id": "7001", "author": {"id": USER}, "content": content}
    d.update(extra)
    return d


def problems(mapper) -> list:
    found = []
    for name, extra in FORWARDS.items():
        out = mapper(dm(**extra))
        if out is None or out.get("forwarded") is not True:
            found.append(f"{name}: not flagged")
    for name, extra in NOT_FORWARDS.items():
        out = mapper(dm(**extra))
        if out is None or "forwarded" in out or out["text"] != LINE:
            found.append(f"{name}: flagged or lost")
    return found


def test_each_forward_form_flags_the_update_and_a_reply_never_does():
    assert problems(discord.message_update) == []


def test_a_forward_has_no_content_and_is_still_an_update_so_that_the_person_is_told():
    out = discord.message_update(dm(content="", **FORWARDS["snapshots"]))
    assert out["forwarded"] is True and out["text"] is None and out["sender"] == USER and out["chat"] == USER and "attachments" not in out
    out = discord.message_update(dm(content=None, **FORWARDS["reference type 1"]))
    assert out["forwarded"] is True and out["text"] is None
    # a forward is never a reply to a card, whatever its reference says
    assert out["reply_to"] is None


def test_an_empty_message_that_is_not_a_forward_is_still_ignored_and_so_is_a_bot_or_a_server():
    assert discord.message_update(dm(content="")) is None
    assert discord.message_update(dm(content="  ", **NOT_FORWARDS["a reply, typed"])) is None
    assert discord.message_update(dm(author="x", **FORWARDS["flag"]) | {"author": {"id": "9", "bot": True}}) is None
    assert discord.message_update(dm(guild_id="1", **FORWARDS["flag"])) is None


def test_a_forward_with_a_file_of_its_own_keeps_the_attachment_and_is_flagged():
    files = [{"id": "9001", "filename": "plan.pdf", "size": 4096, "content_type": "application/pdf"}]
    out = discord.message_update(dm(content="", attachments=files, **FORWARDS["reference type 1"]))
    assert out["forwarded"] is True and out["attachments"][0]["ref"] == "7001:5001:9001"


def test_vacuity_the_oracle_catches_a_mapper_that_never_flags_and_one_that_flags_a_reply():
    def never(d):
        out = discord.message_update(d)
        if out is not None:
            out.pop("forwarded", None)
        return out

    def replies_too(d):
        out = discord.message_update(d)
        if out is not None and d.get("message_reference"):
            out["forwarded"] = True
        return out
    assert problems(never) and problems(replies_too)

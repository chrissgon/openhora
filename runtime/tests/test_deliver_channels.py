"""Tests of who may approve the delivery of a rendered video (decision 14, limit L67): the terminal and the loopback page by default, a messaging
app only under the grant `approve-effect-deliver` and from a card that carried the whole preview (which no channel sends yet, so the grant approves
nothing), never the MCP mode, and never an approval that arrives on the `--lan` socket. Offline: the service is the stand-in of test_service.py, the
policy is read as data, and the names are invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_deliver_channels.py
"""
from __future__ import annotations

import hashlib
import json

import pytest

import standin_tree as st
from test_service import PORT, TOKEN, Standin, api, call, wait_job, world  # noqa: F401  (the service fixtures)

operations = st.load("operations")
effects = st.load("effects")
effect_deliver = st.load("effect_deliver")
deliver_document = st.load("deliver_document")
ops_grants = st.load("ops_grants")
service = st.load("service")

WORD = "effect:deliver"
GRANTED = {"messaging": ["read", "approve-effect-deliver"]}
LAN = "192.168.1.20"
DIGEST = hashlib.sha256(b"the render").hexdigest()


def document(preview=None):
    video = {"name": f"render-{DIGEST[:12]}.mp4", "sha256": DIGEST, "size": 9, "duration_ms": 9000}
    return deliver_document.build(task=3, recording="0123456789abcdef", platform="reels", post="docs/marketing/content/2027-11-02-aster-lane.md",
                                  video=video, cover=None, verify_platform="reels", preview=preview)


def test_by_default_the_terminal_and_the_page_may_approve_a_delivery_and_a_messaging_app_may_not():
    assert operations.permitted("approve", "terminal", None, WORD) and operations.permitted("approve", "page", None, WORD)
    assert not operations.permitted("approve", "messaging", None, WORD)
    assert not operations.permitted("approve", "messaging", {"messaging": ["read", "approve-effects", "approve-effect-write"]}, WORD)
    assert operations.EFFECT_CHANNELS == ("terminal", "page"), "the default does not widen"


def test_the_grant_lets_a_messaging_app_through_the_policy_and_the_card_rule_still_refuses_a_document_with_no_preview(tmp_path):
    assert operations.permitted("approve", "messaging", GRANTED, WORD)
    assert operations.permitted("approve", "messaging", GRANTED, "effect:write") is False, "the grant covers its own word only"
    doc = document()
    path, digest = effects.write(str(tmp_path), doc)
    item = {"id": 9, "kind": "effect", "payload": {"effect_file": path}, "payload_sha256": digest}
    facts = ops_grants.effect_facts({}, item)
    assert facts == {"word": "deliver", "on_cards": False}
    ctx = {"cfg": {"project": str(tmp_path), "channels": GRANTED}}
    sentence = ops_grants.effect_refusal(ctx, item, "messaging", facts)
    assert sentence and "more than a card can show" in sentence, "until a channel sends a preview the grant approves nothing"
    preview = {"sha256": hashlib.sha256(b"preview").hexdigest(), "size": 7, "from_sha256": DIGEST}
    (tmp_path / "p").mkdir()
    made = effects.write(str(tmp_path / "p"), document(preview))
    assert ops_grants.effect_facts({}, {"id": 10, "kind": "effect", "payload": {"effect_file": made[0]}, "payload_sha256": made[1]}) == {"word": "deliver", "on_cards": True}
    for channel in ("terminal", "page"):
        assert ops_grants.effect_refusal(ctx, item, channel, facts) is None


def test_the_mcp_mode_is_granted_no_effect_whatever_the_policy_lists():
    assert "approve-effect-deliver" not in operations.GRANTS["mcp"] and "approve-effect-deliver" in operations.GRANTS["messaging"]
    for channel in ("mcp", "chat"):
        listing = {channel: ["read", "approve-effect-deliver", *operations.GRANTS["mcp"]]}
        assert not operations.permitted("approve", channel, listing, WORD), channel
    assert "deliver" in operations.EFFECT_APPROVAL_WORDS and operations.GROUPS["approve-effect-deliver"] == {"operations": ("approve",), "kind": WORD}
    assert "approve-effect-deliver" in operations.IMPLIED["approve-effects"]


def test_the_grant_text_names_the_provider_servers_and_says_it_approves_nothing_until_a_preview_is_sent():
    text = operations.GRANT_TEXT["messaging:approve-effect-deliver"]
    assert "provider's servers" in text and "approves nothing" in text
    assert operations.GROUP_TEXT["approve-effect-deliver"].startswith("approves the delivery of a rendered video")


# --- the page opened over the local network ----------------------------------------------------------------------------------------


def lan_headers(host=None):
    return {"Host": host or f"{LAN}:{PORT}", "Origin": f"http://{LAN}:{PORT}", "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "Content-Length": "70"}


def approve_on_lan(world, lan):
    world.svc.lan_ip = LAN
    body = json.dumps({"sha256": "a" * 64}).encode("utf-8")
    headers = lan_headers() if lan else {**lan_headers(f"127.0.0.1:{PORT}"), "Origin": f"http://127.0.0.1:{PORT}"}
    headers["Content-Length"] = str(len(body))
    return service.handle(world.svc, "POST", api(world, "/pending/7/approve"), headers, body, lan=lan)


def pending(word, kind="effect"):
    return {"kind": kind, "effect_word": word} if word else {"kind": kind}


def test_limit_67_an_approval_that_arrives_on_the_lan_socket_is_refused_before_any_configuration_check(world):
    world.fake.answers["pending"] = pending("deliver")
    status, _, body = approve_on_lan(world, lan=True)
    assert status == 409 and operations.LAN_REFUSED in body.decode("utf-8")
    assert world.fake.named("approve") == [], "the operation was not called"
    # the rule comes before the `accepted` early return: a configuration that is not accepted does not skip it
    world.fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": False, "data_dir": world.fake.data_dir}
    status, _, body = approve_on_lan(world, lan=True)
    assert status == 409 and operations.LAN_REFUSED in body.decode("utf-8") and world.fake.named("approve") == []


def test_the_same_approval_on_the_loopback_socket_reaches_the_operation(world):
    world.fake.answers["pending"] = pending("deliver")
    status, _, body = approve_on_lan(world, lan=False)
    assert status == 202, body
    wait_job(world, json.loads(body)["job"] if isinstance(body, bytes) else body["job"])
    assert len(world.fake.named("approve")) == 1


def test_the_rule_is_about_the_effect_words_it_names_and_not_about_the_lan_or_about_approving(world):
    assert operations.LAN_REFUSED_EFFECTS == ("deliver",)
    for answer in (pending("publish"), pending(None), pending(None, kind="plan")):
        world.fake.answers["pending"] = answer
        status, _, body = approve_on_lan(world, lan=True)
        assert status == 202, (answer, body)
        wait_job(world, json.loads(body)["job"] if isinstance(body, bytes) else body["job"])
    assert len(world.fake.named("approve")) == 3


def test_the_sentence_names_the_places_that_may_approve():
    assert "this computer's page" in operations.LAN_REFUSED and "terminal" in operations.LAN_REFUSED

"""Contract tests between the two official WhatsApp providers and the bridge's own checks (ATT-3): what a provider writes for a file is what
`runtime/messaging_provider.py` accepts. The bridge's functions are loaded by path (a provider may not import runtime/; a test may); the providers
run in their rigs with a fake Graph, a fake Twilio and fake media hosts. Nothing here reaches a network.

Run: uv run --with pytest pytest providers/messenger/tests/test_whatsapp_official_attachments_bridge.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import whatsapp_cloud_kit as ck
import whatsapp_twilio_kit as tk

REPO = Path(__file__).resolve().parents[3]
BODY = b"%PDF-1.4 a small fake document " * 40


def bridge():
    spec = importlib.util.spec_from_file_location("messaging_provider_for_official_attachments", REPO / "runtime" / "messaging_provider.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mp = bridge()


def test_both_providers_declare_capabilities_the_bridge_accepts_with_the_two_optional_keys_typed():
    for caps in (ck.wc.CAPABILITIES, tk.wt.capabilities(None), tk.wt.capabilities(tk.settings(buttons=tk.BUTTONS))):
        for key, kind in mp.CAPABILITY_KEYS.items():
            assert type(caps.get(key)) is kind, key
        for key, kind in mp.OPTIONAL_KEYS.items():
            assert key not in caps or type(caps[key]) is kind, key
        assert caps["attachments"] is True and type(caps["max_attachment_bytes"]) is int and caps["max_attachment_bytes"] > 0


def test_a_cloud_document_update_is_valid_for_the_bridge_and_its_ref_is_what_the_fetch_op_takes(tmp_path):
    r = ck.Rig(tmp_path / "c", opener=ck.Opener([(f"GET /{ck.MEDIA_ID}", ck.lookup())]), media=ck.MediaOpener(payload=BODY)).start()
    folder = tmp_path / "in"
    folder.mkdir(mode=0o700)
    try:
        r.post(ck.envelope([ck.media_message("document", {"id": ck.MEDIA_ID, "mime_type": "application/pdf", "filename": "plan.pdf", "caption": "the plan"})]))
        assert ck.wait_for(lambda: len(r.out.updates()) == 1)
        update = r.out.updates()[0]
        valid = mp.valid_update(update)
        assert valid is not None and valid["attachments"] == update["attachments"] and valid["text"] == "the plan"
        request = json.loads(mp.line_of({"id": 1, "op": "fetch", "ref": valid["attachments"][0]["ref"], "out": str(folder), "max_bytes": 1_000_000}))
        r.pipe.send(request)
        assert ck.wait_for(lambda: any(a["id"] == 1 for a in r.out.answers()))
        answer = next(a for a in r.out.answers() if a["id"] == 1)
        assert answer["ok"] is True and type(answer["bytes"]) is int and len(answer["sha256"]) == 64
    finally:
        r.stop()


@pytest.mark.parametrize("kind, media", [
    ("image", {"id": ck.MEDIA_ID, "mime_type": "image/jpeg"}), ("audio", {"id": ck.MEDIA_ID, "voice": True}), ("video", {"id": ck.MEDIA_ID}),
    ("sticker", {"id": ck.MEDIA_ID}), ("document", {"id": ck.MEDIA_ID}),
])
def test_every_cloud_update_with_a_file_passes_the_bridges_check(tmp_path, kind, media):
    r = ck.Rig(tmp_path / "c").start()
    try:
        r.post(ck.envelope([ck.media_message(kind, media)]))
        assert ck.wait_for(lambda: len(r.out.updates()) == 1)
        assert mp.valid_update(r.out.updates()[0])["attachments"] == r.out.updates()[0]["attachments"]
    finally:
        r.stop()


def test_a_twilio_update_with_files_is_valid_for_the_bridge_and_its_ref_is_what_the_fetch_op_takes(tmp_path):
    r = tk.Rig(tmp_path / "t", media=tk.MediaOpener(payload=BODY)).start()
    folder = tmp_path / "in"
    folder.mkdir(mode=0o700)
    try:
        r.post(tk.with_media(1, ("application/pdf", "image/jpeg"), body="the plan"))
        assert tk.wait_for(lambda: len(r.out.updates()) == 1)
        update = r.out.updates()[0]
        valid = mp.valid_update(update)
        assert valid is not None and valid["attachments"] == update["attachments"] and len(valid["attachments"]) == 2
        assert [a["type"] for a in valid["attachments"]] == ["application/pdf", "photo"] and valid["text"] == "the plan"
        request = json.loads(mp.line_of({"id": 1, "op": "fetch", "ref": valid["attachments"][0]["ref"], "out": str(folder), "max_bytes": 1_000_000}))
        r.pipe.send(request)
        assert tk.wait_for(lambda: any(a["id"] == 1 for a in r.out.answers()))
        answer = next(a for a in r.out.answers() if a["id"] == 1)
        assert answer["ok"] is True and type(answer["bytes"]) is int and len(answer["sha256"]) == 64
    finally:
        r.stop()


def test_a_gone_answer_carries_a_kind_the_bridge_knows(tmp_path):
    from whatsapp_cloud_kit import http_error
    r = ck.Rig(tmp_path / "c", opener=ck.Opener([(f"GET /{ck.MEDIA_ID}", lambda c: http_error(404))])).start()
    folder = tmp_path / "in"
    folder.mkdir(mode=0o700)
    try:
        answer = r.fetch(1, ck.MEDIA_ID, folder, 1000)
        assert answer["kind"] in mp.ANSWER_KINDS and answer["kind"] == "gone" and isinstance(answer["reason"], str)
    finally:
        r.stop()

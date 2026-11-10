"""The preview of a delivery for a messaging app (package V1d-2, decision 14; runtime/ops_media_preview.py `video_preview`): a real project at the delivery gate,
the real operations layer and store, the engine of media_kit. The render is its own preview; the helper hands its bytes to the bridge only for a sender whose profile
approves a delivery, for the open deliver decision, when the document holds a preview made from this render and the file still hashes to it. Offline, no model, no
network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_media_preview.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import (ops, ops_core, open_items, ops_step_seams, sha, steps, to_gate, to_review, work_file, world)  # noqa: F401  (world is a fixture)

preview = st.load("ops_media_preview")
dd = st.load("deliver_document")
cards = st.load("messaging_cards")
RUNTIME = st.RUNTIME

IDENT = "4242424242"
SENDER = f"telegram:{IDENT}"
READER = "5151515151"
POLICIES = {"approver": ["read", "approve-effect-deliver"], "reader": ["read"]}


def accept(world, **keys):
    """Write the keys into the project's runtime.json and accept the file as the person does, widening included."""
    file = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.update(keys)
    file.write_text(json.dumps(raw))
    shown = ops.config(world["path"])
    ops.accept_config(world["path"], shown["sha256"], widen=shown["widening_sha256"])


def grant(world):
    accept(world, policies=POLICIES, channels={"messaging": "approver"},
           messaging={"senders": {"telegram": [IDENT, {"id": READER, "policy": "reader"}]}})


def refused(call, *args, **kwargs):
    with pytest.raises(ops.OpsError) as caught:
        call(*args, **kwargs)
    return caught.value


def test_at_the_gate_the_preview_is_the_render_with_its_bytes_its_name_and_its_hash(world):
    grant(world)
    task, gate = to_gate(world)
    got = ops.video_preview(world["path"], gate["id"], channel="messaging", sender=SENDER)
    ctx = ops_core.context(world["path"])
    doc = ops_step_seams.EffectFiles(ctx["cfg"]).read(task, 0, gate["payload_sha256"])
    data = work_file(world, doc["video"]["name"]).read_bytes()
    assert got["data"] == data and got["kind"] == "video" and got["size"] == len(data)
    assert got["sha256"] == doc["preview"]["sha256"] == sha(data) and got["name"] == f"video-{sha(data)[:12]}.mp4"
    assert set(got) == {"name", "kind", "data", "size", "sha256"}


def test_the_effect_kind_the_helper_asks_the_policy_about_is_the_one_the_card_asks(world):
    assert preview.KIND == cards.effect_kind({"effect_word": "deliver"}) == "effect:deliver"


@pytest.mark.parametrize("channel", [None, "page", "terminal", "mcp"])
def test_any_channel_but_messaging_is_refused(world, channel):
    grant(world)
    _, gate = to_gate(world)
    assert refused(ops.video_preview, world["path"], gate["id"], channel=channel, sender=SENDER).code == 1


def test_a_sender_whose_profile_does_not_approve_a_delivery_is_refused_and_so_is_a_call_naming_no_sender(world):
    grant(world)
    _, gate = to_gate(world)
    assert refused(ops.video_preview, world["path"], gate["id"], channel="messaging", sender=f"telegram:{READER}").code == 1
    assert refused(ops.video_preview, world["path"], gate["id"], channel="messaging", sender=None).code == 1


def test_a_decision_that_is_a_question_is_refused(world):
    grant(world)
    task = to_review(world)
    [review] = open_items(world, task)
    error = refused(ops.video_preview, world["path"], review["id"], channel="messaging", sender=SENDER)
    assert error.code == 1 and "not the delivery of a video" in str(error)


def test_an_unknown_decision_is_refused(world):
    grant(world)
    assert refused(ops.video_preview, world["path"], 999, channel="messaging", sender=SENDER).code == 1


def test_a_render_that_changed_on_disk_after_the_document_was_written_is_refused_and_nothing_is_returned(world):
    grant(world)
    task, gate = to_gate(world)
    ctx = ops_core.context(world["path"])
    doc = ops_step_seams.EffectFiles(ctx["cfg"]).read(task, 0, gate["payload_sha256"])
    path = work_file(world, doc["video"]["name"])
    original = path.read_bytes()
    path.write_bytes(bytes(b ^ 1 for b in original))      # the same length, other bytes
    error = refused(ops.video_preview, world["path"], gate["id"], channel="messaging", sender=SENDER)
    assert error.code == 1 and "changed" in str(error)
    path.write_bytes(original + b"more")      # longer: the read stops at the preview's size and the hash differs
    assert refused(ops.video_preview, world["path"], gate["id"], channel="messaging", sender=SENDER).code == 1


def test_a_render_over_the_limit_has_no_preview_and_the_sentence_names_the_terminal_and_the_page(world, monkeypatch):
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 1)
    grant(world)
    task, gate = to_gate(world)
    ctx = ops_core.context(world["path"])
    doc = ops_step_seams.EffectFiles(ctx["cfg"]).read(task, 0, gate["payload_sha256"])
    assert doc["preview"] is None and dd.on_cards(doc) is False
    error = refused(ops.video_preview, world["path"], gate["id"], channel="messaging", sender=SENDER)
    assert error.code == 1 and "no preview" in str(error) and "terminal" in str(error) and "page" in str(error)


def test_the_helper_is_not_a_row_of_the_table_of_operations(world):
    operations = st.load("operations")
    assert "video_preview" not in {row["call"] for row in operations.OPERATIONS}


def test_the_module_prints_its_text_on_help_and_exits_2_otherwise():
    flags = ["--help"]
    argv = [sys.executable, "-I", str(RUNTIME / "ops_media_preview.py")]
    helped = subprocess.run(argv + flags, capture_output=True, text=True, env={})
    assert helped.returncode == 0 and helped.stdout.startswith("The preview of a delivery on a messaging app")
    assert subprocess.run(argv, capture_output=True, text=True, env={}).returncode == 2

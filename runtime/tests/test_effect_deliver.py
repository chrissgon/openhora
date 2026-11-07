"""Tests of the effect kind `deliver` (runtime/effect_deliver.py, package V1b1-3; limit L67): approving a delivery document marks that exact render
downloadable through the media store, after the file is hashed again. Offline: the store is a real one in a temporary folder, every recording is
a synthetic head, and nothing is called, sent or published. The approval path (runtime/ops_step_effects.py `approve`) is driven with a stand-in
store of decisions; the names are invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_effect_deliver.py
"""
from __future__ import annotations

import hashlib
import types
from pathlib import Path

import pytest

import standin_tree as st
from media_fixtures import Body, mp4_head

media = st.load("media")
effects = st.load("effects")
effect_deliver = st.load("effect_deliver")
deliver_document = st.load("deliver_document")
ops_step_effects = st.load("ops_step_effects")
ops_core = st.load("ops_core")

POST = "docs/marketing/content/2027-11-02-aster-lane.md"
PAYLOAD = b"the rendered video of Aster Lane"
TASK = 4
PENDING = 11


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def data(tmp_path):
    return str(tmp_path / "data")


def recording(data, payload=PAYLOAD):
    """A taken recording with a render of `payload` beside it; returns (record id, render sha256)."""
    record = media.receive(data, Body(64, mp4_head()), 64)
    digest = sha(payload)
    Path(media.folder_of(data, record["id"]), f"render-{digest[:12]}.mp4").write_bytes(payload)
    return record["id"], digest


def document(rid, digest, size=len(PAYLOAD), preview=None, task=TASK):
    video = {"name": f"render-{digest[:12]}.mp4", "sha256": digest, "size": size, "duration_ms": 12_000}
    return deliver_document.build(task=task, recording=rid, platform="reels", post=POST, video=video, cover=None, verify_platform="reels", preview=preview)


def approval(pending=PENDING):
    return {"id": 1, "scope": "action", "status": "pending-execution", "pending_id": pending}


def delivered(data, rid):
    return media.load(data, rid)["delivered"]


def test_the_module_is_a_step_kind_of_no_gate_and_no_policy_with_no_provider_and_its_group_is_named():
    assert effect_deliver.STEP is True and effect_deliver.GATE is False and effect_deliver.POLICY is False
    assert effect_deliver.APPROVAL_GROUP == "approve-effect-deliver" and isinstance(effect_deliver.PROVIDER_CLASS, str)
    assert effects.module_for("deliver") is effect_deliver and effect_deliver.WORD == "deliver"
    assert "deliver" in effects.step_only_words() and "deliver" not in effects.policy_kinds()
    assert effect_deliver.caller({}, "") is None and effect_deliver.idempotency_key({}, "wb-key") == "wb-key"


def test_check_turns_a_document_that_is_not_well_formed_into_a_deviation_and_never_echoes_it(data):
    rid, digest = recording(data)
    doc = document(rid, digest)
    assert effect_deliver.check(doc) == doc
    for bad in ({**doc, "extra": 1}, {**doc, "task": 0}, "text", None):
        with pytest.raises(effects.EffectError) as refused:
            effect_deliver.check(bad)
        assert refused.value.kind == "deviation" and refused.value.reason == "the delivery document is not well formed"


def test_the_pure_half_is_the_one_of_the_delivery_document(data):
    rid, digest = recording(data)
    doc = document(rid, digest)
    for name in ("title", "body", "describe", "summary", "on_cards"):
        assert getattr(effect_deliver, name) is getattr(deliver_document, name), name
    assert effect_deliver.WORD == deliver_document.WORD


def test_execute_marks_the_record_with_the_hash_the_task_and_the_decision_and_a_second_execute_changes_nothing(data):
    rid, digest = recording(data)
    doc = document(rid, digest)
    done = effect_deliver.execute(doc, approval(), None, "wb-key", data)
    assert done == {"delivered": digest, "recording": rid}
    mark = delivered(data, rid)
    assert mark["sha256"] == digest and mark["task"] == TASK and mark["pending"] == PENDING
    assert effect_deliver.execute(doc, approval(), None, "wb-key", data) == done
    assert delivered(data, rid) == mark
    assert media.delivered_file(data, rid)["sha256"] == digest


def test_limit_67_a_changed_render_is_stale_answered_by_code_and_never_delivered(data):
    rid, digest = recording(data)
    doc = document(rid, digest)
    Path(media.folder_of(data, rid), doc["video"]["name"]).write_bytes(b"swapped after it was shown")
    with pytest.raises(effects.EffectError) as refused:
        effect_deliver.execute(doc, approval(), None, "wb-key", data)
    assert refused.value.kind == "stale" and refused.value.reason == "the render changed after it was shown"
    assert "rendered again" in refused.value.answer and "new approval" in refused.value.answer
    assert delivered(data, rid) is None
    with pytest.raises(media.MediaError):
        media.delivered_file(data, rid)


def test_another_render_of_a_delivered_recording_is_a_deviation_and_a_missing_one_is_stale(data):
    rid, digest = recording(data)
    effect_deliver.execute(document(rid, digest), approval(), None, "wb-key", data)
    other = sha(b"a second render")
    Path(media.folder_of(data, rid), f"render-{other[:12]}.mp4").write_bytes(b"a second render")
    with pytest.raises(effects.EffectError) as refused:
        effect_deliver.execute(document(rid, other, size=15), approval(), None, "wb-key", data)
    assert refused.value.kind == "deviation" and "delivered already" in refused.value.reason
    rid2, digest2 = recording(data, b"gone")
    Path(media.folder_of(data, rid2), f"render-{digest2[:12]}.mp4").unlink()
    with pytest.raises(effects.EffectError) as gone:
        effect_deliver.execute(document(rid2, digest2, size=4), approval(), None, "wb-key", data)
    assert gone.value.kind == "stale" and delivered(data, rid2) is None


def test_preflight_is_none_while_the_render_is_kept_and_refuses_after_the_retention_removed_it(data):
    rid, digest = recording(data)
    doc = document(rid, digest)
    cfg = {"data_dir": data}
    assert effect_deliver.preflight(cfg, doc, "") is None
    Path(media.folder_of(data, rid), doc["video"]["name"]).unlink()
    code, sentence = effect_deliver.preflight(cfg, doc, "")
    assert code == 1 and sentence == "nothing was delivered: the render is no longer kept (the retention removed it); start the task again"


def test_on_cards_is_false_for_a_document_with_no_preview_and_true_only_for_a_preview_made_from_that_render(data):
    rid, digest = recording(data)
    assert effect_deliver.on_cards(document(rid, digest)) is False
    preview = {"sha256": sha(b"preview"), "size": 7, "from_sha256": digest}
    assert effect_deliver.on_cards(document(rid, digest, preview=preview)) is True
    assert effect_deliver.on_cards({"video": {"sha256": digest}, "preview": {**preview, "from_sha256": sha(b"another")}}) is False


# --- the approval path: ops_step_effects.approve ----------------------------------------------------------------------------------


class Store:
    """The decisions' store of one approval, reduced to the calls `approve` makes for a delivery that succeeds."""

    class StoreError(Exception):
        code = 1

    def __init__(self):
        self.approvals, self.done = [], []

    def approval_add(self, conn, **row):
        self.approvals.append(row)
        return {"id": len(self.approvals), **row}

    def effect_done(self, conn, pending_id, approval_id, by=None, result=None, actor=None):
        self.done.append((pending_id, approval_id, result))
        return {"pending_id": pending_id, "status": "resolved"}


def approving(data, doc, tmp_path):
    """The context, the decision and the written effect document of a delivery waiting at the gate; returns (ctx, item, digest, found)."""
    cfg = {"data_dir": data, "store_db": str(tmp_path / "store.db"), "project": str(tmp_path / "project")}
    folder = ops_step_effects.make_effect_dir(cfg, TASK, 0)
    path, digest = effects.write(folder, doc)
    ctx = {"store": Store(), "conn": None, "cfg": cfg, "root": str(tmp_path / "project")}
    item = {"id": PENDING, "task_id": TASK, "payload": {"cycle": 0}}
    found = ({"id": TASK}, None, types.SimpleNamespace(word="deliver"))
    return ctx, item, digest, found, path


def test_the_approval_of_the_hash_of_the_document_marks_the_render_delivered_once(data, tmp_path):
    rid, digest = recording(data)
    doc = document(rid, digest)
    ctx, item, sha256, found, _ = approving(data, doc, tmp_path)
    done = ops_step_effects.approve(ctx, item, sha256, found)
    assert done["result"] == {"delivered": digest, "recording": rid} and done["doc"] == doc
    assert ctx["store"].done == [(PENDING, 1, done["result"])]
    assert delivered(data, rid)["sha256"] == digest and delivered(data, rid)["pending"] == PENDING


def test_a_document_whose_bytes_differ_from_the_approved_hash_is_a_deviation_and_the_record_is_not_delivered(data, tmp_path):
    rid, digest = recording(data)
    doc = document(rid, digest)
    ctx, item, sha256, found, path = approving(data, doc, tmp_path)
    other = document(rid, digest)
    other["platform"], other["verify"]["platform"] = "shorts", "shorts"
    Path(path).write_bytes(effects._text(other))      # the file is edited after the hash was shown
    with pytest.raises(ops_core.OpsError) as refused:
        ops_step_effects.approve(ctx, item, sha256, found)
    assert "nothing was delivered" in str(refused.value) and "not the one approved" in str(refused.value)
    assert delivered(data, rid) is None and ctx["store"].approvals == [] and ctx["store"].done == []


def test_a_render_that_the_retention_removed_is_refused_before_any_approval_is_recorded(data, tmp_path):
    rid, digest = recording(data)
    doc = document(rid, digest)
    ctx, item, sha256, found, _ = approving(data, doc, tmp_path)
    Path(media.folder_of(data, rid), doc["video"]["name"]).unlink()
    with pytest.raises(ops_core.OpsError) as refused:
        ops_step_effects.approve(ctx, item, sha256, found)
    assert "no longer kept" in str(refused.value) and ctx["store"].approvals == [] and delivered(data, rid) is None

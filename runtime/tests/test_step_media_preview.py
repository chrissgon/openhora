"""The side step `preview` of the step kind `media` (package V3d, runtime/step_media.py): a render larger than a messaging card carries gets a copy from the
renderer's `preview` verb, which the delivery document records as its preview; a small render is its own preview and the renderer is not asked; a failed or
doubtful copy is skipped and never fails the task. The engine is the fake of media_kit, the store is the real one; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_step_media_preview.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import standin_tree as st
from media_kit import (media, open_items, ops, ops_core, ops_step_seams, ops_steps, sha, step_media, steps, task_row, to_gate, work_file,
                       world)  # noqa: F401  (world is a fixture)

dd = st.load("deliver_document")
cards = st.load("messaging_cards")
RUNTIME = st.RUNTIME

IDENT = "4242424242"
SENDER = f"telegram:{IDENT}"
READER = "5151515151"
POLICIES = {"approver": ["read", "approve-effect-deliver"], "reader": ["read"]}
PREVIEW_ONE = b"preview one"


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


def document(world, task, gate):
    ctx = ops_core.context(world["path"])
    return ops_step_seams.EffectFiles(ctx["cfg"]).read(task, 0, gate["payload_sha256"])


def render_sha() -> str:
    return sha(b"the rendered video of Aster Lane " + b"one")


def folder(world) -> Path:
    return Path(media.folder_of(world["data"], world["rid"]))


def test_the_preview_is_a_side_step_between_verify_and_document():
    kind = steps.kind_of("media")
    assert kind.order == ("take", "transcribe", "analyse", "still", "retakes", "align-proposal", "review", "remap", "base", "align", "check",
                          "render", "cover", "verify", "preview", "document", "deliver")
    assert set(kind.side_steps) == {"still", "preview"} and step_media.TIMEOUTS["preview"] == 1200
    assert step_media.CLEANUP["preview"] == (step_media.PREVIEW_PATTERN,) and step_media.PREVIEW_PATTERN == media.PREVIEW.pattern


def test_a_small_render_is_its_own_preview_and_the_renderer_is_not_asked(world):
    task, gate = to_gate(world)
    assert world["engine"].of("preview") == []
    doc = document(world, task, gate)
    assert doc["preview"] == {"sha256": doc["video"]["sha256"], "size": doc["video"]["size"], "from_sha256": doc["video"]["sha256"]}
    assert (task_row(world, task)["step_state"]["steps"].get("preview") or {}).get("status") != "done"


def test_a_render_over_the_limit_gets_the_renderers_copy_as_its_preview(world, monkeypatch):
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 20)
    task, gate = to_gate(world)
    calls = world["engine"].calls
    [call] = world["engine"].of("preview")
    assert [c["verb"] for c in calls].index("preview") > [c["verb"] for c in calls].index("verify")
    render_path = str(work_file(world, "render-%s.mp4" % render_sha()[:12]))
    assert call["args"] == ["--in", render_path, "--sha256", render_sha(), "--out", str(folder(world))] and call["timeout"] == 1200
    doc = document(world, task, gate)
    assert doc["preview"] == {"sha256": sha(PREVIEW_ONE), "size": 11, "from_sha256": render_sha()}
    assert dd.on_cards(doc) is True and dd.preview_name(doc) == "preview-%s.mp4" % sha(PREVIEW_ONE)[:12]
    assert work_file(world, dd.preview_name(doc)).read_bytes() == PREVIEW_ONE
    assert ["CARD_VIDEO_PREVIEW", {"sha": sha(PREVIEW_ONE), "origin": render_sha()}] in gate["payload"]["card"]


def test_a_preview_that_fails_never_fails_the_task_and_leaves_no_preview(world, monkeypatch):
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 20)
    world["engine"].fail["preview"] = RuntimeError()
    task, gate = to_gate(world)
    state = task_row(world, task)["step_state"]
    skipped = state["steps"]["preview"]
    assert skipped["status"] == "skipped" and skipped["result"]["code"]
    doc = document(world, task, gate)
    assert doc["preview"] is None and dd.on_cards(doc) is False
    again = {**state, "steps": {k: v for k, v in state["steps"].items() if k != "document"}}
    assert step_media._preview_due(again) is False


def changed(**over):
    """The kit's answer, changed in one way."""
    def make(engine):
        original = type(engine)._preview

        def preview(a):
            done = original(engine, a)
            name = over.get("name", done["name"])
            if over.get("disk"):
                (Path(a[a.index("--out") + 1]) / done["name"]).write_bytes(b"other bytes")
            return {**done, **{k: v for k, v in over.items() if k not in ("disk", "name")}, "name": name}
        return preview
    return make


@pytest.mark.parametrize("over,code", [({"name": "preview-000000000000.mp4"}, "provider_output_invalid"),
                                       ({"from_sha256": "f" * 64}, "provider_output_invalid"),
                                       ({"bytes": 0}, "provider_output_invalid"),
                                       ({"bytes": 21}, "preview_too_large"),
                                       ({"disk": True}, "preview_differs")])
def test_an_engine_answer_that_does_not_hold_is_skipped(world, monkeypatch, over, code):
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 20)
    world["engine"]._preview = changed(**over)(world["engine"])
    task, gate = to_gate(world)
    skipped = task_row(world, task)["step_state"]["steps"]["preview"]
    assert skipped["status"] == "skipped" and skipped["result"]["code"] == code
    assert document(world, task, gate)["preview"] is None


def test_the_bridges_helper_hands_the_preview_file_not_the_render(world, monkeypatch):
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 20)
    grant(world)
    task, gate = to_gate(world)
    doc = document(world, task, gate)
    got = ops.video_preview(world["path"], gate["id"], channel="messaging", sender=SENDER)
    assert got["data"] == PREVIEW_ONE and got["sha256"] == doc["preview"]["sha256"] and got["name"] == "video-%s.mp4" % sha(PREVIEW_ONE)[:12]
    work_file(world, dd.preview_name(doc)).write_bytes(b"PREVIEW ONE")        # the same length, other bytes
    error = refused(ops.video_preview, world["path"], gate["id"], channel="messaging", sender=SENDER)
    assert error.code == 1 and "changed" in str(error)


def test_preparing_the_render_again_removes_the_preview(world, monkeypatch):
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 20)
    task, gate = to_gate(world)
    assert [p for p in folder(world).iterdir() if p.name.startswith("preview-")]
    ctx = ops_core.context(world["path"])
    pctx = ops_steps._context(ctx, task_row(world, task))
    kind = steps.kind_of("media")
    state = steps.state_of(kind, task_row(world, task)["step_state"])
    steps.prepare_again(pctx, kind, state, "render")
    left = [p.name for p in folder(world).iterdir()]
    assert not [n for n in left if n.startswith(("preview-", "render-"))], left
    assert "preview" not in state["steps"]


def test_the_store_and_the_engine_know_the_preview(world):
    assert media._check_name("preview-0123456789ab.mp4") == "preview-0123456789ab.mp4"
    with pytest.raises(media.MediaError):
        media._check_name("preview-0123456789ab.mov")
    assert "preview" in ops_step_seams.MediaEngine.CLASSES["renderer:video"]
    ctx = {"cfg": {"data_dir": world["data"], "project": world["path"]}, "store": None, "conn": None}
    store = ops_step_seams.MediaStore(ctx)
    for name in ("preview-0123456789ab.mp4", "still-0123456789ab.png"):
        with open(store.path(world["rid"], name, must_exist=False), "wb") as f:
            f.write(b"x")
    assert store.remove(world["rid"], [step_media.PREVIEW_PATTERN]) == 1
    left = [p.name for p in folder(world).iterdir()]
    assert "still-0123456789ab.png" in left and "preview-0123456789ab.mp4" not in left


def test_the_preview_name_and_the_check_of_a_document(world):
    task, gate = to_gate(world)
    doc = document(world, task, gate)
    assert dd.preview_name(doc) == doc["video"]["name"]
    other = {**doc, "preview": {"sha256": "ab" * 32, "size": 11, "from_sha256": doc["video"]["sha256"]}}
    assert dd.preview_name(other) == "preview-%s.mp4" % ("ab" * 6)
    dd.check(other)
    wrong = {**doc, "preview": {"sha256": doc["video"]["sha256"], "size": doc["video"]["size"] + 1, "from_sha256": doc["video"]["sha256"]}}
    with pytest.raises(ValueError) as bad:
        dd.check(wrong)
    assert str(bad.value) == "preview.size"
    assert dd.PREVIEW_MAX_BYTES == 15 * 1024 * 1024


def test_the_module_still_starts_on_its_own():
    flags = ["--help"]
    argv = [sys.executable, "-I", str(RUNTIME / "step_media.py")]
    helped = subprocess.run(argv + flags, capture_output=True, text=True, env={})
    assert helped.returncode == 0

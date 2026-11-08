"""Tests of the caption edit and the way back from the delivery approval (runtime/ops_media_edit.py, package V1b1-4): the three paths of the plan's first
goal (approve; edit at the gate, render again, approve again; an edit that changes nothing is refused) and the edit at the review. The engine is a fake,
the store of recordings and the approval path are the real ones; nothing is called and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_edit.py
"""
from __future__ import annotations

import json

import pytest

from media_kit import (add, media, open_items, ops, ops_core, post_text, run_task, sha, steps, task_row, to_gate, to_review, work_file, world)  # noqa: F401
import standin_tree as st

ops_media_edit = st.load("ops_media_edit")
EDIT = [{"op": "edit", "index": 0, "text": "Welcomes"}]
SAME = [{"op": "edit", "index": 0, "text": "Welcome"}]


def edit(world, task, edits=EDIT, revision=0):
    return ops_media_edit.edit(ops_core.context(world["path"]), task, revision, edits)


def approve(world, item):
    return ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")


def test_path_one_approving_the_hash_delivers_the_render_and_the_task_is_done(world):
    task, gate = to_gate(world)
    done = approve(world, gate)
    assert done["task_state"] == "done" and task_row(world, task)["state"] == "done"
    delivered = media.delivered_file(world["data"], world["rid"])
    assert delivered["sha256"] == sha(b"the rendered video of Aster Lane one") and delivered["path"].endswith(f"render-{delivered['sha256'][:12]}.mp4")
    assert media.load(world["data"], world["rid"])["delivered"]["pending"] == gate["id"]


def test_path_two_an_edit_at_the_gate_answers_the_delivery_by_code_renders_again_and_only_the_new_hash_can_be_approved(world):
    task, gate = to_gate(world)
    done = edit(world, task)
    assert done["mode"] == "gate" and done["answered"] == gate["id"] and done["applied"]["edited"] == 1
    ctx = ops_core.context(world["path"])
    old = ctx["store"].pending_get(ctx["conn"], gate["id"])
    assert old["status"] == "resolved" and old["resolution"] == "answered" and "rendered again" in old["answer"]
    assert open_items(world, task) == [] and task_row(world, task)["state"] == "ready"      # the store makes it ready; the kind is not unattended, so only the person starts it
    assert json.loads(work_file(world, "transcript.edited.json").read_text())["words"][0]["text"] == "Welcomes"
    assert json.loads(work_file(world, "review.json").read_text())["revision"] == 1
    world["engine"].salt = b"two"
    out = run_task(world, task)
    assert out["ok"] is True and out["stopped"] == "deliver"
    [fresh] = open_items(world, task)
    assert fresh["payload_sha256"] != gate["payload_sha256"] and fresh["id"] != gate["id"]
    assert [c["verb"] for c in world["engine"].calls].count("render") == 2 and [c["verb"] for c in world["engine"].calls].count("transcribe") == 1
    with pytest.raises(ops_core.OpsError):
        approve(world, gate)
    assert media.load(world["data"], world["rid"])["delivered"] is None
    done = approve(world, fresh)
    assert done["task_state"] == "done"
    assert media.delivered_file(world["data"], world["rid"])["sha256"] == sha(b"the rendered video of Aster Lane two")


def test_path_three_an_edit_that_changes_nothing_is_refused_and_the_decision_is_still_pending(world):
    task, gate = to_gate(world)
    with pytest.raises(ops_core.OpsError) as refused:
        edit(world, task, SAME)
    assert "nothing changed" in str(refused.value)
    assert [i["id"] for i in open_items(world, task)] == [gate["id"]] and task_row(world, task)["state"] == "waiting"
    assert not work_file(world, "review.json").exists() or json.loads(work_file(world, "review.json").read_text())["revision"] == 0


def test_an_edit_while_the_video_waits_at_the_review_writes_and_answers_nothing_else(world):
    task = to_review(world)
    [review] = open_items(world, task)
    done = edit(world, task)
    assert done["mode"] == "review" and done["answered"] is None
    assert [i["id"] for i in open_items(world, task)] == [review["id"]]
    assert json.loads(work_file(world, "transcript.edited.json").read_text())["words"][0]["text"] == "Welcomes"
    ops.answer(world["path"], review["id"], "continue")
    assert run_task(world, task)["stopped"] == "deliver"
    base = world["engine"].of("base")[-1]["args"]
    assert "transcript.edited.json" in base[1]


def test_an_edit_is_refused_while_the_task_runs_or_has_not_started_or_is_not_a_new_video_or_has_a_stale_revision(world):
    task = add(world)
    for state in ("ready", "running"):
        ctx = ops_core.context(world["path"])
        if state == "running":
            ctx["store"].step_task_move(ctx["conn"], task, state="running", note=None, by="code")
        with pytest.raises(ops_core.OpsError) as refused:
            edit(world, task)
        assert "only while the video waits" in str(refused.value)
    other = ops_core.context(world["path"])["store"]
    with pytest.raises(ops_core.OpsError):
        ops_media_edit.edit(ops_core.context(world["path"]), 99999, 0, EDIT)
    ctx = ops_core.context(world["path"])
    plain = ctx["store"].step_task_add(ctx["conn"], key="x", title="X", text="X.", step="publish-post")["task"]
    with pytest.raises(ops_core.OpsError) as refused:
        ops_media_edit.edit(ctx, plain, 0, EDIT)
    assert "not a new video" in str(refused.value)


def test_a_stale_revision_a_credential_and_a_time_key_are_refused_with_nothing_written_and_nothing_answered(world):
    task, gate = to_gate(world)
    for edits, revision, word in ((EDIT, 5, "stale_revision"), ([{"op": "edit", "index": 0, "text": "AKIA" + "IOSFODNN7EXAMPLE"}], 0, "credential"),
                                  ([{"op": "edit", "index": 0, "text": "Hi", "start": 1.0}], 0, "time_not_accepted")):
        with pytest.raises(ops_core.OpsError) as refused:
            edit(world, task, edits, revision)
        assert word in str(refused.value) or word == "credential"
    assert [i["id"] for i in open_items(world, task)] == [gate["id"]]
    assert not work_file(world, "review.json").exists()

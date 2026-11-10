"""Tests of the media operations (runtime/ops_media.py, package V1b2-1): a recording in, the list, the start, the run, the caption review and edit, the
download and the still, from the terminal. The engine is a fake, the store of recordings and the approval path are the real ones; nothing is called and
every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_ops_media.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from media_fixtures import Body, body_of, mp4_head, png_head
from media_kit import (POST, add, media, open_items, ops, ops_core, run_task, sha, steps, task_row, to_gate, to_review, work_file, world)  # noqa: F401
import standin_tree as st

ops_media = st.load("ops_media")
phrases = st.load("phrases")
cli = st.load("cli")
EDIT = [{"op": "edit", "index": 0, "text": "Welcomes"}]
REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
FRESH = "0123456789abcdef"


def approve(world, item):
    return ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")


def task_count(world) -> int:
    ctx = ops_core.context(world["path"])
    return len(ctx["conn"].execute("SELECT id FROM tasks WHERE key = 'video'").fetchall())


def folders(world) -> list:
    return sorted(p.name for p in Path(media.root_of(world["data"])).iterdir() if media.ID.fullmatch(p.name))


def mp4_file(world, name="take.mp4", total=64) -> Path:
    path = world["tmp"] / name
    path.write_bytes(body_of(mp4_head(), total))
    return path


def set_page(world, groups):
    """Write the page's policy (channels.page) into the project's runtime.json and accept the new hash, as the person does; None removes the entry."""
    file = Path(world["path"]) / "docs" / "workbench" / "runtime.json"
    raw = json.loads(file.read_text())
    raw.pop("channels", None)
    if groups is not None:
        raw["channels"] = {"page": groups}
    file.write_text(json.dumps(raw))
    ops.accept_config(world["path"], ops.project_config.load(world["path"])["sha256"], widen=ops.config(world["path"])["widening_sha256"])


def refused(call, *args, **kwargs):
    with pytest.raises(ops_core.OpsError) as caught:
        call(*args, **kwargs)
    return caught.value


# 1. media_in from a file


def test_media_in_takes_a_file_and_never_answers_a_path(world):
    before = folders(world)
    got = ops_media.media_in(world["path"], str(mp4_file(world)), "terminal")
    assert set(got) == {"media", "size", "type", "created_at"} and got["type"] == "mp4" and got["size"] == 64 and media.ID.fullmatch(got["media"])
    assert str(world["tmp"]) not in json.dumps(got) and len(folders(world)) == len(before) + 1
    assert media.load(world["data"], got["media"])["raw"]["size"] == 64


def test_media_in_refuses_a_link_a_folder_a_missing_path_and_a_png_and_keeps_nothing(world):
    before = folders(world)
    real = mp4_file(world)
    link = world["tmp"] / "link.mp4"
    link.symlink_to(real)
    png = world["tmp"] / "pic.png"
    png.write_bytes(body_of(png_head(), 64))
    for path in (link, world["tmp"], world["tmp"] / "none.mp4"):
        assert refused(ops_media.media_in, world["path"], str(path)).code == 2
    err = refused(ops_media.media_in, world["path"], str(png))
    assert err.code == 2 and str(err).endswith("(type)")
    assert folders(world) == before


# 2. media_in from a stream


def test_media_in_takes_a_stream_of_the_declared_length_only_through_the_page_path(world, monkeypatch):
    set_page(world, ["read"])                          # a page policy that does not list `media` refuses it
    err = refused(ops_media.media_in, world["path"], stream=Body(64, mp4_head()), length=64, channel="page")
    assert err.code == 1
    set_page(world, None)                              # no page policy: the page keeps its ceiling, which lists the group
    got = ops_media.media_in(world["path"], stream=Body(64, mp4_head()), length=64, channel="page")
    assert got["size"] == 64 and got["type"] == "mp4"
    assert refused(ops_media.media_in, world["path"], stream=Body(64, mp4_head()), length=64).code == 2
    assert refused(ops_media.media_in, world["path"], str(mp4_file(world)), stream=Body(64, mp4_head()), length=64, channel="page").code == 2
    assert refused(ops_media.media_in, world["path"], channel="page").code == 2
    for bad in (0, True, None):
        assert refused(ops_media.media_in, world["path"], stream=Body(64, mp4_head()), length=bad, channel="page").code == 2


def test_media_in_a_short_stream_is_refused_and_the_new_folder_is_removed(world):
    before = folders(world)
    for body in (Body(4096, mp4_head(), fail_after=0), Body(64, mp4_head())):      # a dropped connection, and a body that ends before its length
        err = refused(ops_media.media_in, world["path"], stream=body, length=4096, channel="page")
        assert err.code == 2
    assert folders(world) == before


# 3. the quota


def test_media_in_refuses_when_the_store_is_full_and_does_not_point_at_an_operation_that_does_not_exist(world, monkeypatch):
    monkeypatch.setattr(media, "QUOTA_BYTES", 10)
    err = refused(ops_media.media_in, world["path"], str(mp4_file(world)))
    assert err.code == 1 and str(err).endswith("(quota)") and "must be removed first" not in str(err)


# 4. media_list


def test_media_list_shows_the_recording_with_no_task_then_its_task_and_state(world):
    first = ops_media.media_list(world["path"])
    [row] = first["recordings"]
    assert row["media"] == world["rid"] and row["task"] is None and row["task_state"] is None and row["raw_kept"] is True and row["delivered_at"] is None
    assert row["size"] == 64 and row["type"] == "mp4"
    assert isinstance(first["used_bytes"], int) and isinstance(first["quota_bytes"], int)
    started = ops_media.video_new(world["path"], world["rid"], POST)
    [row] = ops_media.media_list(world["path"])["recordings"]
    assert row["task"] == started["task"] and row["task_state"] == "waiting"


# 5. video_new


def test_video_new_runs_to_the_review_with_the_flows_words(world):
    got = ops_media.video_new(world["path"], world["rid"], POST, "terminal")
    assert got["started"] is True and got["stopped"] == "review" and got["media"] == world["rid"] and "detail" not in got
    [item] = open_items(world, got["task"])
    assert item["id"] == got["pending"] and item["title"] == phrases.en("TITLE_VIDEO_REVIEW")
    row = task_row(world, got["task"])
    assert row["title"] == "Make the video" and row["key"] == "video"
    flow = json.loads((REPO / "flows" / "new-video.json").read_text(encoding="utf-8"))["tasks"][0]
    assert ops_media.TASK_TEXT == flow["text"] and ops_media.TASK_KEY == flow["key"] and phrases.en(ops_media.TITLE_KEY) == flow["title"]


def test_video_new_refusals_leave_no_new_task(world):
    before = task_count(world)
    assert refused(ops_media.video_new, world["path"], "not-an-id", POST).code == 2
    assert refused(ops_media.video_new, world["path"], FRESH, POST).code == 1
    assert refused(ops_media.video_new, world["path"], world["rid"], "docs/elsewhere/post.md").code == 2
    assert task_count(world) == before
    ops_media.video_new(world["path"], world["rid"], POST)
    after = task_count(world)
    assert after == before + 1
    err = refused(ops_media.video_new, world["path"], world["rid"], POST)
    assert err.code == 1 and "waiting" in str(err) and task_count(world) == after


def test_video_new_refuses_a_delivered_recording(world):
    task, gate = to_gate(world)
    approve(world, gate)
    before = task_count(world)
    err = refused(ops_media.video_new, world["path"], world["rid"], POST)
    assert err.code == 1 and "delivered" in str(err) and task_count(world) == before


def test_video_new_again_after_the_task_failed_takes_the_recording_over(world):
    world["engine"].fail["transcribe"] = RuntimeError("down")
    failed = ops_media.video_new(world["path"], world["rid"], POST)
    assert failed["started"] is True and failed.get("ok") is False
    assert task_row(world, failed["task"])["state"] == "failed"
    world["engine"].fail.clear()
    again = ops_media.video_new(world["path"], world["rid"], POST)
    assert again["task"] != failed["task"] and again["stopped"] == "review"


# 7. video_run


def test_video_run_continues_after_the_answer_and_refuses_what_is_not_a_video(world):
    started = ops_media.video_new(world["path"], world["rid"], POST)
    ops.answer(world["path"], started["pending"], "continue")
    got = ops_media.video_run(world["path"], started["task"], "terminal")
    assert got["started"] is True and got["stopped"] == "deliver" and got["task"] == started["task"] and "request" not in got
    assert str(refused(ops_media.video_run, world["path"], 999999)).strip()


def test_video_run_on_a_waiting_task_reports_the_reason_and_changes_nothing(world):
    started = ops_media.video_new(world["path"], world["rid"], POST)
    before = task_row(world, started["task"])
    got = ops_media.video_run(world["path"], started["task"])
    assert got["started"] is False and got["reason"] and "stopped" not in got
    assert task_row(world, started["task"])["state"] == before["state"]


def test_every_task_operation_refuses_a_task_that_is_not_a_new_video(world):
    ctx = ops_core.context(world["path"])
    made = steps.add_task(ctx["store"], ctx["conn"], "ingest", {"source": "notes"}, key="ingest", title="Ingest", text="Ingest it.")
    other = made["task"]
    for call, args in ((ops_media.video_run, ()), (ops_media.captions_read, ()), (ops_media.captions_edit, (0, "[]")), (ops_media.video_download, ("/x/y",)),
                       (ops_media.video_still, ("/x/y",))):
        err = refused(call, world["path"], other, *args)
        assert str(err) == ops_media.NOT_A_VIDEO and err.code == 1


# 8. captions_read


def test_captions_read_at_the_review_at_the_gate_and_after_the_approval(world):
    task = add(world)
    err = refused(ops_media.captions_read, world["path"], task)
    assert err.code == 1 and str(err) == ops_media_edit_not_ready()
    run_task(world, task)
    got = ops_media.captions_read(world["path"], task, "terminal")
    assert got["mode"] == "review" and got["view"]["revision"] == 0 and got["media"] == world["rid"]
    assert re.fullmatch(r"still-[0-9a-f]{12}\.png", got["still"])
    [item] = open_items(world, task)
    ops.answer(world["path"], item["id"], "continue")
    run_task(world, task)
    assert ops_media.captions_read(world["path"], task)["mode"] == "gate"
    [gate] = open_items(world, task)
    approve(world, gate)
    done = ops_media.captions_read(world["path"], task)
    assert done["mode"] is None and done["view"]["revision"] == 0


def ops_media_edit_not_ready() -> str:
    return st.load("ops_media_edit").NOT_READY


# 9. captions_edit


def test_captions_edit_at_the_review_from_text_and_from_a_file_text(world):
    task = to_review(world)
    got = ops_media.captions_edit(world["path"], task, 0, edits=json.dumps(EDIT), channel="terminal")
    assert got["mode"] == "review" and got["answered"] is None
    again = ops_media.captions_edit(world["path"], task, 1, edits_file=json.dumps([{"op": "edit", "index": 1, "text": "Tos"}]))
    assert again["mode"] == "review"
    view = ops_media.captions_read(world["path"], task)
    assert view["view"]["revision"] == 2


def test_captions_edit_refuses_both_neither_and_what_is_not_a_json_list(world):
    task = to_review(world)
    text = json.dumps(EDIT)
    for kwargs in ({"edits": text, "edits_file": text}, {}, {"edits": "{}"}, {"edits": "not json"}, {"edits": "[" * 100000}, {"edits": "[" + "0," * (1 << 20) + "0]"}):
        assert refused(ops_media.captions_edit, world["path"], task, 0, **kwargs).code == 2
    assert not work_file(world, "review.json").exists() or json.loads(work_file(world, "review.json").read_text())["revision"] == 0


def test_captions_edit_at_the_gate_answers_the_delivery_and_a_run_renders_again(world):
    task, gate = to_gate(world)
    got = ops_media.captions_edit(world["path"], task, 0, edits=json.dumps(EDIT))
    assert got["mode"] == "gate" and got["answered"] == gate["id"] and task_row(world, task)["state"] == "ready"
    world["engine"].salt = b"two"
    run = ops_media.video_run(world["path"], task)
    assert run["stopped"] == "deliver" and run["pending"] != gate["id"]


# 10. video_download


def test_video_download_before_and_after_the_approval(world):
    task, gate = to_gate(world)
    out = world["tmp"] / "out" / "video.mp4"
    out.parent.mkdir()
    err = refused(ops_media.video_download, world["path"], task, str(out))
    assert err.code == 1 and "not_found" in str(err) and not out.exists()
    approve(world, gate)
    got = ops_media.video_download(world["path"], task, str(out), "terminal")
    data = b"the rendered video of Aster Lane one"
    assert out.read_bytes() == data and oct(out.stat().st_mode & 0o777) == "0o600"
    assert got["sha256"] == media.delivered_file(world["data"], world["rid"])["sha256"] == sha(data) and got["size"] == len(data)
    assert got["name"] == f"video-{sha(data)[:12]}.mp4" and got["path"] == str(out) and got["task"] == task
    assert refused(ops_media.video_download, world["path"], task, str(out)).code == 1 and out.read_bytes() == data


def test_video_download_never_writes_inside_the_project_and_needs_a_name_outside_the_page(world):
    task, gate = to_gate(world)
    approve(world, gate)
    inside = Path(world["path"]) / "video.mp4"
    err = refused(ops_media.video_download, world["path"], task, str(inside))
    assert str(err) == ops_media.OUT_INSIDE and not inside.exists()
    link = world["tmp"] / "into-project"
    link.symlink_to(world["path"])
    assert str(refused(ops_media.video_download, world["path"], task, str(link / "video.mp4"))) == ops_media.OUT_INSIDE
    assert refused(ops_media.video_download, world["path"], task, str(world["tmp"] / "nodir" / "video.mp4")).code == 1
    assert refused(ops_media.video_download, world["path"], task).code == 2


def test_video_download_without_out_hands_an_open_file_through_the_page_path(world):
    task, gate = to_gate(world)
    approve(world, gate)
    got = ops_media.video_download(world["path"], task, channel="page")
    try:
        assert got["stream"].read() == b"the rendered video of Aster Lane one" and got["size"] == len(b"the rendered video of Aster Lane one")
    finally:
        got["stream"].close()


def test_video_download_refuses_a_render_that_changed_after_the_approval_on_both_paths(world):
    task, gate = to_gate(world)
    approve(world, gate)
    path = media.delivered_file(world["data"], world["rid"])["path"]
    with open(path, "ab") as f:
        f.write(b"x")
    out = world["tmp"] / "video.mp4"
    assert refused(ops_media.video_download, world["path"], task, str(out)).code == 1 and not out.exists()
    assert refused(ops_media.video_download, world["path"], task, channel="page").code == 1


def test_video_download_rehashes_from_the_descriptor_it_copies_from(world, monkeypatch):
    task, gate = to_gate(world)
    approve(world, gate)
    real = media.delivered_file

    def swapped(data_dir, rid):
        found = real(data_dir, rid)
        with open(found["path"], "ab") as f:      # the file changes between the store's hash and the copy's own
            f.write(b"y")
        return found
    monkeypatch.setattr(media, "delivered_file", swapped)
    err = refused(ops_media.video_download, world["path"], task, str(world["tmp"] / "video.mp4"))
    assert "stale" in str(err)


# 11. video_still


def test_video_still_to_a_file_and_through_the_page_path(world):
    task = to_review(world)
    out = world["tmp"] / "still.png"
    got = ops_media.video_still(world["path"], task, str(out), "terminal")
    data = b"\x89PNG\r\n\x1a\nstill"
    assert out.read_bytes() == data and got["sha256"] == sha(data) and got["size"] == len(data) and re.fullmatch(r"still-[0-9a-f]{12}\.png", got["name"])
    assert ops_media.video_still(world["path"], task, channel="page") == {"media_type": "image/png", "data": data}
    assert refused(ops_media.video_still, world["path"], task, str(out)).code == 1
    assert refused(ops_media.video_still, world["path"], task).code == 2
    assert str(refused(ops_media.video_still, world["path"], task, str(Path(world["path"]) / "still.png"))) == ops_media.OUT_INSIDE


def test_video_still_refuses_a_task_with_no_still(world):
    task = add(world)
    err = refused(ops_media.video_still, world["path"], task, str(world["tmp"] / "still.png"))
    assert str(err) == "no still was made for this video"


# 12. the channel rule


CALLS = [(ops_media.media_in, ("/nope.mp4",)), (ops_media.media_list, ()), (ops_media.video_new, (FRESH, POST)), (ops_media.video_run, (999999,)),
         (ops_media.captions_read, (999999,)), (ops_media.captions_edit, (999999, 0, "[]")), (ops_media.video_download, (999999, "/x/y")),
         (ops_media.video_still, (999999, "/x/y"))]


@pytest.mark.parametrize("channel", ["mcp", "messaging", "other"])
def test_every_operation_refuses_any_channel_but_the_terminal_and_the_page_before_it_reads_anything(world, channel):
    for call, args in CALLS:
        assert refused(call, world["path"], *args, channel=channel).code == 1


def test_every_operation_refuses_a_page_whose_policy_does_not_list_the_group_media_before_it_reads_anything(world):
    set_page(world, ["read"])
    for call, args in CALLS:
        assert refused(call, world["path"], *args, channel="page").code == 1


# 13. the module starts on its own


def test_the_module_prints_its_text_on_help_and_exits_2_otherwise():
    flags = ["--help"]
    argv = [sys.executable, "-I", str(RUNTIME / "ops_media.py")]
    helped = subprocess.run(argv + flags, capture_output=True, text=True, env={})
    assert helped.returncode == 0 and helped.stdout.startswith("The operations of a new video")
    assert subprocess.run(argv, capture_output=True, text=True, env={}).returncode == 2


# 14. the terminal


def test_the_terminal_calls_the_operations(world):
    got = cli.run(["media-list", "--project", world["path"]])
    assert [r["media"] for r in got["recordings"]] == [world["rid"]]
    task = to_review(world)
    edits = world["tmp"] / "edits.json"
    edits.write_text(json.dumps(EDIT), encoding="utf-8")
    done = cli.run(["captions-edit", "--project", world["path"], "--task", str(task), "--revision", "0", "--edits-file", str(edits)])
    assert done["mode"] == "review"
    assert json.loads(work_file(world, "transcript.edited.json").read_text())["words"][0]["text"] == "Welcomes"

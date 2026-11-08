"""Tests of `media-remove` (runtime/ops_media_remove.py and the removal of runtime/media.py, package media-remove): the preview that removes nothing, the
removal of the folder whole, the refusal while a task that has not ended works on the recording or holds its lock, the guard of the record, the links that
are never followed, a removal cut short and swept by the retention, the channel rule, the route, the terminal, the quota sentence and the row. The engine is
a fake, the store of recordings and the approval path are the real ones; nothing is called and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_remove.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import standin_tree as st
from media_fixtures import Body, body_of, mp4_head
from media_kit import POST, add, media, ops, ops_core, task_row, to_gate, to_review, work_file, world  # noqa: F401
from test_service import PORT, STATUS, TOKEN, Standin

ops_media_remove = st.load("ops_media_remove")
ops_media = st.load("ops_media")
service = st.load("service")
operations = st.load("operations")
cli = st.load("cli")
guard = st.load("messaging_guard")
REPO = Path(__file__).resolve().parents[2]
RUNTIME = REPO / "runtime"
LAN = "192.168.1.20"
FRESH = "0123456789abcdef"


def approve(world, item):
    return ops.approve(world["path"], item["id"], sha256=item["payload_sha256"], channel="terminal")


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


def folder(world) -> Path:
    return Path(media.folder_of(world["data"], world["rid"]))


def whole(world) -> bool:
    return (folder(world) / "record.json").is_file() and any(p.name.startswith("raw.") for p in folder(world).iterdir())


def leftovers(world) -> list:
    return sorted(p.name for p in Path(media.root_of(world["data"])).iterdir() if p.name.startswith(".removed-"))


def remove(world, **kwargs):
    return ops_media_remove.media_remove(world["path"], world["rid"], **kwargs)


# 1. the preview


def test_the_preview_removes_nothing(world):
    got = remove(world)
    assert got["removed"] is False and got["bytes"] == media.footprint(world["data"], world["rid"])["bytes"] and got["files"] >= 2
    assert got["tasks"] == [] and got["warning"] == ops_media_remove.WARNING and got["delivered_at"] is None and got["created_at"]
    assert whole(world) and world["rid"] in [r["media"] for r in ops_media.media_list(world["path"])["recordings"]]


# 2. a recording with no task


def test_a_recording_with_no_task_is_removed_whole(world):
    before = media.usage(world["data"])
    got = remove(world, confirm=True)
    assert got["removed"] is True and got["left"] is False and got["tasks"] == [] and got["files"] >= 2
    assert not folder(world).exists() and leftovers(world) == []
    assert world["rid"] not in [r["media"] for r in ops_media.media_list(world["path"])["recordings"]]
    assert media.usage(world["data"]) == before - got["bytes"]


# 3. refused while a task works on it


def test_refused_while_a_task_that_has_not_ended_works_on_it(world):
    task = add(world)                                    # ready, and not bound in the record yet
    assert media.load(world["data"], world["rid"])["task"] is None
    for confirm in (False, True):
        err = refused(remove, world, confirm=confirm)
        assert err.code == 1 and f"task {task}" in str(err) and "ready" in str(err) and f"request {task_row(world, task)['parent_id']}" in str(err)
        assert whole(world)


@pytest.mark.parametrize("stage", ["review", "gate"])
def test_refused_at_the_caption_review_and_at_the_delivery_approval(world, stage):
    if stage == "review":
        task = to_review(world)
    else:
        task, _ = to_gate(world)
    assert task_row(world, task)["state"] == "waiting"
    for confirm in (False, True):
        err = refused(remove, world, confirm=confirm)
        assert err.code == 1 and f"task {task}" in str(err) and "waiting" in str(err)
        assert whole(world)
    assert (folder(world) / "record.json").is_file()


# 4. allowed once the task has ended


def test_allowed_after_the_request_was_cancelled(world):
    task = to_review(world)
    ops.cancel(world["path"], task_row(world, task)["parent_id"])
    assert task_row(world, task)["state"] == "cancelled"
    got = remove(world, confirm=True)
    assert got["removed"] is True and got["tasks"] == [task] and not folder(world).exists()


def test_allowed_after_a_step_failed(world):
    world["engine"].fail["transcribe"] = RuntimeError("down")
    failed = ops_media.video_new(world["path"], world["rid"], POST)
    assert task_row(world, failed["task"])["state"] == "failed"
    got = remove(world, confirm=True)
    assert got["removed"] is True and got["tasks"] == [failed["task"]] and not folder(world).exists()


def test_allowed_after_the_delivery_was_approved_and_the_video_goes_with_it(world):
    task, gate = to_gate(world)
    approve(world, gate)
    assert task_row(world, task)["state"] == "done"
    assert any(p.name.startswith("render-") for p in folder(world).iterdir())
    got = remove(world, confirm=True)
    assert got["removed"] is True and got["delivered_at"] and got["tasks"] == [task] and not folder(world).exists()
    out = world["tmp"] / "video.mp4"
    err = refused(ops_media.video_download, world["path"], task, str(out))
    assert err.code == 1 and not out.exists()


# 5. a running task's lock


def test_a_task_lock_that_is_held_refuses_the_removal(world):
    task = to_review(world)
    ops.cancel(world["path"], task_row(world, task)["parent_id"])
    cfg = ops_core.context(world["path"])["cfg"]
    fd = ops_core._try_lock(cfg, f"task-{task}.lock")
    assert fd is not None
    try:
        err = refused(remove, world, confirm=True)
        assert err.code == 1 and "running now" in str(err) and f"task {task}" in str(err)
        assert whole(world)
    finally:
        os.close(fd)
    assert remove(world, confirm=True)["removed"] is True


# 6. the record changed between the check and the removal


def test_the_record_changed_since_the_check(world):
    err = pytest.raises(media.MediaError, media.remove, world["data"], world["rid"], task=7).value
    assert err.code == "taken"
    assert whole(world) and leftovers(world) == []
    assert pytest.raises(media.MediaError, media.remove, world["data"], world["rid"], task=True).value.code == "usage"
    assert pytest.raises(media.MediaError, media.remove, world["data"], world["rid"], task=-1).value.code == "usage"


# 7. no link is followed


def test_a_link_named_like_a_recording_is_not_followed(world, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("kept")
    link = Path(media.root_of(world["data"])) / "fedcba9876543210"
    os.symlink(outside, link)
    with pytest.raises(media.MediaError) as caught:
        media.remove(world["data"], "fedcba9876543210", task=None)
    assert caught.value.code in ("unreadable", "not_found")
    with pytest.raises(media.MediaError) as caught:
        media.footprint(world["data"], "fedcba9876543210")
    assert caught.value.code in ("unreadable", "not_found")
    assert (outside / "keep.txt").read_text() == "kept" and link.is_symlink()


def test_a_link_inside_the_folder_is_removed_as_a_link(world, tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("kept")
    os.symlink(target, folder(world) / "extra.txt")
    counted = media.footprint(world["data"], world["rid"])
    assert counted["files"] == len([p for p in folder(world).iterdir() if p.is_file() and not p.is_symlink()])
    got = remove(world, confirm=True)
    assert got["removed"] is True and not folder(world).exists() and target.read_text() == "kept"


# 8. a removal cut short


def test_a_removal_cut_short_is_swept_by_the_retention(world, monkeypatch):
    real = media._remove_tree
    calls = []

    def once(parent_fd, name):
        calls.append(name)
        return False if len(calls) == 1 else real(parent_fd, name)

    monkeypatch.setattr(media, "_remove_tree", once)
    got = remove(world, confirm=True)
    assert got["left"] is True and leftovers(world) == [f".removed-{world['rid']}"] and not folder(world).exists()
    swept = media.purge(world["data"], now=time.time())
    assert swept["stray"] == 1 and leftovers(world) == []


# 9. the channel rule


def test_the_channel_rule(world):
    assert remove(world, channel="page")["removed"] is False
    set_page(world, ["read"])
    assert refused(remove, world, channel="page").code == 1
    set_page(world, ["read", "media"])
    assert remove(world, channel="page")["removed"] is False
    assert remove(world, channel="terminal")["removed"] is False
    for channel in ("mcp", "messaging"):
        assert refused(ops_media_remove.media_remove, world["path"], FRESH, channel=channel).code == 1


# 10. the arguments


def test_the_arguments(world):
    for bad in ("short", "ABCDEF0123456789", 7, None):
        assert refused(ops_media_remove.media_remove, world["path"], bad).code == 2
    err = refused(ops_media_remove.media_remove, world["path"], FRESH)
    assert err.code == 1 and "not_found" in str(err)
    assert refused(remove, world, confirm="yes").code == 2
    assert whole(world)


# 11. the route, against the stand-in


def headers_of(length, lan=False):
    host = f"{LAN}:{PORT}" if lan else f"127.0.0.1:{PORT}"
    return {"Host": host, "Authorization": f"Bearer {TOKEN}", "Origin": f"http://{host}", "Content-Type": "application/json", "Content-Length": str(length)}


@pytest.fixture
def stand(tmp_path):
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    place = tmp_path / "alpha"
    place.mkdir()
    projects = [{"id": service.project_id(str(place)), "name": "alpha", "path": str(place)}]
    svc = service.Service(fake, projects, TOKEN, PORT, str(tmp_path), log=lambda line: None)
    return types.SimpleNamespace(svc=svc, fake=fake, projects=projects)


def post_remove(stand, body, lan=False):
    data = json.dumps(body).encode("utf-8")
    path = f"/api/v1/projects/{stand.projects[0]['id']}/media/remove"
    return service.handle(stand.svc, "POST", path, headers_of(len(data), lan), data, lan=lan)


def test_the_route_carries_the_id_and_the_flag(stand):
    status, _, _ = post_remove(stand, {"media_id": FRESH, "confirm": True})
    assert status == 200
    assert stand.fake.named("media_remove")[0][2] == {"media_id": FRESH, "confirm": True, "channel": "page"}
    stand.svc.lan_ip = LAN
    status, _, _ = post_remove(stand, {"media_id": FRESH}, lan=True)
    assert status == 200 and len(stand.fake.named("media_remove")) == 2
    status, _, payload = post_remove(stand, {"media_id": FRESH, "confirm": "yes"})
    assert status == 400 and json.loads(payload)["error"] == "usage" and len(stand.fake.named("media_remove")) == 2


# 12. end to end, with the real operations


def test_the_preview_and_the_removal_through_the_service(world):
    projects = [{"id": service.project_id(world["path"]), "name": "alpha", "path": world["path"]}]
    svc = service.Service(ops, projects, TOKEN, PORT, str(world["tmp"] / "svc"), log=lambda line: None)
    stage = types.SimpleNamespace(svc=svc, projects=projects)
    status, _, payload = post_remove(stage, {"media_id": world["rid"]})
    assert status == 200 and json.loads(payload)["removed"] is False and whole(world)
    status, _, payload = post_remove(stage, {"media_id": world["rid"], "confirm": True})
    assert status == 200 and json.loads(payload)["removed"] is True and not folder(world).exists()
    status, _, payload = post_remove(stage, {"media_id": world["rid"], "confirm": True})
    assert status == 409 and json.loads(payload)["error"] == "refused"


# 13. the terminal


def test_the_terminal_previews_then_removes(world, capsys):
    args = ["media-remove", "--project", world["path"], "--media", world["rid"]]
    cli.run(args)
    assert whole(world)
    sure = args + ["--confirm"]
    cli.run(sure)
    assert not folder(world).exists()


# 14. the quota sentence


def test_the_quota_sentence_names_no_command_and_reaches_a_phone(world, monkeypatch):
    text = ops_media.QUOTA_TEXT
    assert guard.find(text) == [] and "no operation removes" not in text and "must be removed first" not in text and "--" not in text
    monkeypatch.setattr(media, "QUOTA_BYTES", 10)
    source = world["tmp"] / "take.mp4"
    source.write_bytes(body_of(mp4_head(), 64))
    err = refused(ops_media.media_in, world["path"], str(source))
    assert err.code == 1 and str(err).endswith("(quota)")


# 15. the row and the group


def test_the_row_and_the_group():
    row = operations.by_name("media-remove")
    assert row["channels"] == ("terminal", "page") and not row.get("job") and row["natural"]["class"] == "G" and row["natural"]["order"] == 176
    assert "media-remove" in operations.GROUPS["media"]["operations"] and "media-remove" not in operations.LAN_REFUSED_OPS
    assert len(operations.GROUP_TEXT["media"]) < 220 and "removes recordings" in operations.GROUP_TEXT["media"]


# 16. the module starts on its own


def test_the_module_starts_on_its_own():
    argv = [sys.executable, "-I", str(RUNTIME / "ops_media_remove.py"), "--help"]
    done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and done.stdout.startswith("The operation `media-remove`")

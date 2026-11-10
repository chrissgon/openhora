"""Tests of runtime/media.py, the store of the recordings a `media` task works on (decision 12, VD8): the intake of an MP4 or a MOV, the
record, the binding of a task, the work files by closed names, the delivery (the one writer and the one reader that hands a render out),
and the retention. Offline: every recording is a synthetic head and zeros made by the test; nothing is downloaded and no tool is run.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_store.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

import pytest

import standin_tree as st
from media_fixtures import Body, Forbidden, body_of, mov_head, mp4_head, png_head

media = st.load("media")
intake = st.load("intake")
DAY = 86400.0


@pytest.fixture
def data(tmp_path):
    return str(tmp_path / "data")


def take(data, total=64, head=None, now=None):
    return media.receive(data, Body(total, head or mp4_head()), total, now=now)


def add_render(data, rid, payload=b"rendered bytes"):
    sha = hashlib.sha256(payload).hexdigest()
    Path(media.folder_of(data, rid), f"render-{sha[:12]}.mp4").write_bytes(payload)
    return sha


def code_of(call, *args, **kwargs):
    with pytest.raises(media.MediaError) as e:
        call(*args, **kwargs)
    return e.value.code


def folders(data):
    root = Path(media.root_of(data))
    return sorted(p.name for p in root.iterdir() if media.ID.fullmatch(p.name)) if root.exists() else []


# --- taking a recording ----------------------------------------------------------------------------------------------------------


def test_an_mp4_is_taken_with_its_record_its_name_and_its_hash(data):
    payload = body_of(mp4_head(), 200)
    record = media.receive(data, Body(200, mp4_head()), 200, now=1_700_000_000)
    assert media.ID.fullmatch(record["id"]) and record["created_at"] == "2023-11-14T22:13:20Z" == record["updated_at"]
    assert record["raw"] == {"name": "raw.mp4", "sha256": hashlib.sha256(payload).hexdigest(), "size": 200, "type": "mp4"}
    assert record["task"] is None and record["delivered"] is None and record["purged"] == {"raw": None}
    folder = Path(media.folder_of(data, record["id"]))
    assert (folder / "raw.mp4").read_bytes() == payload
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and stat.S_IMODE((folder / "record.json").stat().st_mode) == 0o600
    assert media.load(data, record["id"]) == record
    assert [r["id"] for r in media.records(data)] == [record["id"]]
    assert not [n for n in os.listdir(folder) if n.startswith(".incoming-")], "no temporary file is left"


def test_a_mov_is_taken_as_raw_mov(data):
    record = take(data, 100, mov_head())
    assert record["raw"]["name"] == "raw.mov" and record["raw"]["type"] == "mov"
    assert Path(media.folder_of(data, record["id"]), "raw.mov").is_file()


def test_a_png_is_refused_by_its_bytes_and_no_folder_is_left(data):
    assert code_of(take, data, 100, png_head()) == "type"
    assert folders(data) == []


def test_a_length_above_the_cap_is_refused_before_a_byte_is_read(data):
    assert code_of(media.receive, data, Forbidden(), media.MEDIA_MAX_BYTES + 1) == "size"
    assert code_of(media.receive, data, Forbidden(), None) == "size"
    assert folders(data) == []


def test_the_quota_refuses_a_file_that_would_not_fit(data, monkeypatch):
    monkeypatch.setattr(media, "QUOTA_BYTES", 1000)
    root = Path(media.root_of(data))
    root.mkdir(parents=True, mode=0o700)
    (root / "filler").write_bytes(b"x" * 990)               # usage is QUOTA_BYTES - 10
    assert media.usage(data) == 990
    assert code_of(media.receive, data, Forbidden(), 11) == "quota"
    assert folders(data) == []


def test_the_cap_is_the_renderers_own_cap_for_a_recording():
    text = (st.REPO / "providers" / "renderer" / "_host.py").read_text(encoding="utf-8")
    found = re.search(r"^MAX_RECORDING_BYTES = 1 << (\d+)$", text, re.M)
    assert found and media.MEDIA_MAX_BYTES == 1 << int(found.group(1))


def test_a_dropped_connection_leaves_nothing(data):
    assert code_of(media.receive, data, Body(5000, mp4_head(), fail_after=100), 5000) == "size"
    assert folders(data) == []


def test_an_upload_that_is_running_refuses_another_as_busy(data):
    root = Path(media.root_of(data))
    root.mkdir(parents=True, mode=0o700)
    with intake.Lock(str(root / media.UPLOAD_LOCK), blocking=False):
        assert code_of(take, data) == "busy"
    assert folders(data) == []


def test_a_file_is_taken_but_a_link_and_a_folder_are_not(data, tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(body_of(mp4_head(), 90))
    link = tmp_path / "link.mp4"
    link.symlink_to(source)
    folder = tmp_path / "folder"
    folder.mkdir()
    assert media.receive_file(data, str(source))["raw"]["size"] == 90
    assert code_of(media.receive_file, data, str(link)) == "usage"
    assert code_of(media.receive_file, data, str(folder)) == "usage"
    assert code_of(media.receive_file, data, str(tmp_path / "missing.mp4")) == "usage"
    assert len(folders(data)) == 1


def test_a_damaged_or_missing_record_is_told_apart(data):
    record = take(data)
    assert code_of(media.load, data, "0" * 16) == "not_found"
    assert code_of(media.load, data, "../x") == "usage"
    Path(media.folder_of(data, record["id"]), "record.json").write_text('{"version": 1}', encoding="utf-8")
    assert code_of(media.load, data, record["id"]) == "unreadable"
    assert media.records(data) == []


# --- binding a task --------------------------------------------------------------------------------------------------------------


def test_a_task_is_bound_once_and_another_replaces_it_only_when_the_old_one_may_go(data):
    rid = take(data)["id"]
    never, always = (lambda old: False), (lambda old: True)
    assert media.bind_task(data, rid, 7, may_replace=never)["task"] == 7
    assert media.bind_task(data, rid, 7, may_replace=never)["task"] == 7, "the same task again is not a conflict"
    assert code_of(media.bind_task, data, rid, 8, may_replace=never) == "taken"
    seen = []
    assert media.bind_task(data, rid, 8, may_replace=lambda old: seen.append(old) or True)["task"] == 8 and seen == [7]
    assert media.bind_task(data, rid, 9, may_replace=always)["task"] == 9
    assert code_of(media.bind_task, data, rid, True, may_replace=always) == "usage"


def test_a_delivered_recording_is_not_bound_again(data):
    rid = take(data)["id"]
    sha = add_render(data, rid)
    media.mark_delivered(data, rid, sha256=sha, task_id=1, pending_id=2)
    assert code_of(media.bind_task, data, rid, 1, may_replace=lambda old: True) == "delivered"


def test_a_purged_recording_cannot_be_bound(data):
    rid = take(data, now=1_700_000_000)["id"]
    media.update(data, rid, lambda r: r.update(raw=None, purged={"raw": "2023-11-15T00:00:00Z"}))
    assert code_of(media.bind_task, data, rid, 1, may_replace=lambda old: True) == "stale"


# --- the work files --------------------------------------------------------------------------------------------------------------


def test_work_files_are_read_and_written_by_closed_names_only(data):
    rid = take(data)["id"]
    sha = media.write_work(data, rid, "review.json", b'{"a": 1}')
    assert sha == hashlib.sha256(b'{"a": 1}').hexdigest()
    assert media.read_work(data, rid, "review.json") == b'{"a": 1}'
    assert stat.S_IMODE(os.stat(media.path_of(data, rid, "review.json")).st_mode) == 0o600
    media.write_work(data, rid, "review.json", b"{}")                    # replaced whole
    assert media.read_work(data, rid, "review.json") == b"{}"
    for name in ("../x", "record.json", "notes.txt", "render-abc.mp4", "", "raw.avi"):
        assert code_of(media.path_of, data, rid, name) == "usage", name
        assert code_of(media.read_work, data, rid, name) == "usage", name
        assert code_of(media.write_work, data, rid, name, b"x") == "usage", name
    assert code_of(media.write_work, data, rid, "raw.mp4", b"x") == "usage", "the recording is never written by a step"
    assert code_of(media.write_work, data, rid, "review.json", "text") == "usage"
    assert code_of(media.path_of, data, rid, "edl.json") == "not_found"
    assert media.path_of(data, rid, "edl.json", must_exist=False).endswith(f"{rid}/edl.json")
    assert code_of(media.read_work, data, rid, "edl.json") == "not_found"


def test_a_write_touches_the_record_and_a_big_file_is_refused_by_the_limit(data):
    rid = take(data, now=1_700_000_000)["id"]
    media.write_work(data, rid, "edl.json", b"x" * 100)
    assert media.load(data, rid)["updated_at"] > "2023-11-14T22:13:20Z"
    assert code_of(media.read_work, data, rid, "edl.json", 10) == "unreadable"
    assert media.read_work(data, rid, "edl.json", 100) == b"x" * 100


def test_a_link_planted_in_the_folder_is_never_followed(data, tmp_path):
    rid = take(data)["id"]
    secret = tmp_path / "secret.json"
    secret.write_text("{}", encoding="utf-8")
    folder = Path(media.folder_of(data, rid))
    (folder / "analysis.json").symlink_to(secret)
    assert code_of(media.read_work, data, rid, "analysis.json") == "unreadable"
    assert code_of(media.path_of, data, rid, "analysis.json") == "unreadable"
    (folder / "..edl.json.part").symlink_to(secret)
    (folder / ".edl.json.part").symlink_to(secret)
    assert code_of(media.write_work, data, rid, "edl.json", b"x") == "unreadable"
    assert secret.read_text(encoding="utf-8") == "{}", "the link's target was not written"
    (folder / "beats.json").write_bytes(b"{}")
    os.link(folder / "beats.json", tmp_path / "second-name")
    assert code_of(media.read_work, data, rid, "beats.json") == "unreadable", "a file with two names is refused"


def test_the_folder_of_a_recording_that_is_a_link_is_not_followed(data, tmp_path):
    rid = take(data)["id"]
    real = Path(media.folder_of(data, rid))
    moved = tmp_path / "elsewhere"
    real.rename(moved)
    real.symlink_to(moved)
    assert code_of(media.load, data, rid) == "unreadable"
    assert code_of(media.read_work, data, rid, "edl.json") == "unreadable"


def test_remove_work_removes_the_matches_and_never_the_record_or_the_recording(data):
    rid = take(data)["id"]
    sha = add_render(data, rid)
    media.write_work(data, rid, "edl.json", b"{}")
    media.write_work(data, rid, "beats.json", b"{}")
    (Path(media.folder_of(data, rid)) / "cover-0123456789ab.png").write_bytes(b"png")
    count = media.remove_work(data, rid, ["edl.json", "record.json", "raw.mp4", media.RENDER, media.COVER])
    assert count == 3
    assert sorted(os.listdir(media.folder_of(data, rid))) == [".record.lock", "beats.json", "raw.mp4", "record.json"]
    assert code_of(media.remove_work, data, rid, ["notes.txt"]) == "usage"
    assert sha and media.load(data, rid)["raw"]["name"] == "raw.mp4"


# --- the delivery ----------------------------------------------------------------------------------------------------------------


def test_a_render_is_marked_delivered_once_and_the_same_mark_again_changes_nothing(data):
    rid = take(data)["id"]
    sha = add_render(data, rid)
    first = media.mark_delivered(data, rid, sha256=sha, task_id=12, pending_id=34, now=1_700_000_000)
    assert first["delivered"] == {"at": "2023-11-14T22:13:20Z", "sha256": sha, "task": 12, "pending": 34}
    again = media.mark_delivered(data, rid, sha256=sha, task_id=12, pending_id=34, now=1_700_009_999)
    assert again == first == media.load(data, rid), "the second call writes nothing"


def test_another_render_after_a_delivery_is_refused_as_delivered(data):
    rid = take(data)["id"]
    sha = add_render(data, rid, b"one")
    other = add_render(data, rid, b"two")
    media.mark_delivered(data, rid, sha256=sha, task_id=1, pending_id=None)
    assert code_of(media.mark_delivered, data, rid, sha256=other, task_id=1, pending_id=None) == "delivered"
    assert media.load(data, rid)["delivered"]["sha256"] == sha


def test_a_render_that_changed_or_is_missing_is_stale_and_nothing_is_written(data):
    rid = take(data)["id"]
    sha = add_render(data, rid, b"as shown")
    Path(media.folder_of(data, rid), f"render-{sha[:12]}.mp4").write_bytes(b"changed after it was shown")
    assert code_of(media.mark_delivered, data, rid, sha256=sha, task_id=1, pending_id=None) == "stale"
    assert code_of(media.mark_delivered, data, rid, sha256="a" * 64, task_id=1, pending_id=None) == "stale"
    assert media.load(data, rid)["delivered"] is None
    assert code_of(media.mark_delivered, data, rid, sha256="nope", task_id=1, pending_id=None) == "usage"


def test_only_a_delivered_render_that_still_hashes_to_its_mark_is_handed_out(data):
    rid = take(data)["id"]
    sha = add_render(data, rid, b"final render")
    assert code_of(media.delivered_file, data, rid) == "not_found"
    media.mark_delivered(data, rid, sha256=sha, task_id=1, pending_id=2)
    found = media.delivered_file(data, rid)
    assert found == {"path": media.path_of(data, rid, f"render-{sha[:12]}.mp4"), "sha256": sha, "size": len(b"final render")}
    Path(found["path"]).write_bytes(b"swapped")
    assert code_of(media.delivered_file, data, rid) == "stale"
    os.unlink(found["path"])
    assert code_of(media.delivered_file, data, rid) == "not_found"


def test_the_render_is_the_one_writer_of_a_delivery_among_the_modules_of_runtime():
    """`mark_delivered(` is written in the module that defines it and in the effect module that approves a delivery, and nowhere else."""
    holders = {p.name for p in (st.REPO / "runtime").glob("*.py") if "mark_delivered(" in p.read_text(encoding="utf-8")}
    assert holders == {"media.py", "effect_deliver.py"}


def test_a_delivery_is_written_by_one_function_in_the_store_itself():
    text = (st.REPO / "runtime" / "media.py").read_text(encoding="utf-8")
    assert len(re.findall(r'\["delivered"\]\s*=', text)) == 1 and text.count("def mark_delivered(") == 1


# --- the retention ---------------------------------------------------------------------------------------------------------------


def _record(updated, delivered=None, purged=None):
    return {"updated_at": updated, "delivered": None if delivered is None else {"at": delivered},
            "purged": {"raw": purged}}


def _stamp(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def test_due_reads_the_five_rows_at_the_day_edges():
    now = 1_700_000_000.0
    old = lambda days, hours=0: _stamp(now - days * DAY - hours * 3600)   # noqa: E731
    assert media.due(_record(old(29, 23)), now) == "" and media.due(_record(old(30)), now) == "all"       # not delivered
    delivered = lambda days, hours=0, purged=None: _record(old(0), old(days, hours), purged)   # noqa: E731
    assert media.due(delivered(6, 23), now) == "" and media.due(delivered(7), now) == "raw"
    assert media.due(delivered(7, purged="2023-11-14T00:00:00Z"), now) == "", "the recording was purged already"
    assert media.due(delivered(29, 23, purged="x"), now) == "" and media.due(delivered(30), now) == "all"
    assert media.due(delivered(30, purged="2023-11-14T00:00:00Z"), now) == "all"
    assert media.due(_record("not a time"), now) == "" and media.due(_record(old(0), "garbage"), now) == ""
    assert media.due({}, now) == ""


def test_an_undelivered_recording_untouched_for_a_month_is_removed_and_a_younger_one_stays(data):
    now = 1_700_000_000.0
    old = take(data, now=now - 31 * DAY)["id"]
    young = take(data, now=now - 29 * DAY)["id"]
    out = media.purge(data, now=now)
    assert out == {"removed": [{"recording": old, "what": "all"}], "kept": [], "stray": 0, "skipped": []}
    assert folders(data) == [young]


def test_seven_days_after_the_delivery_the_recording_goes_and_the_render_and_its_records_stay(data):
    now = 1_700_000_000.0
    rid = take(data, now=now - 8 * DAY)["id"]
    sha = add_render(data, rid)
    cover = Path(media.folder_of(data, rid), "cover-0123456789ab.png")
    cover.write_bytes(b"png")
    for name in ("transcript.json", "analysis.json", "review.json", "edl.json", "render.json", "verify.json"):
        media.write_work(data, rid, name, b"{}")
    media.mark_delivered(data, rid, sha256=sha, task_id=1, pending_id=2, now=now - 7 * DAY)
    out = media.purge(data, now=now)
    assert out["removed"] == [{"recording": rid, "what": "raw"}] and out["kept"] == []
    kept = sorted(n for n in os.listdir(media.folder_of(data, rid)) if not n.startswith(".record.lock"))
    assert kept == sorted(["record.json", "render.json", "verify.json", f"render-{sha[:12]}.mp4", "cover-0123456789ab.png"])
    record = media.load(data, rid)
    assert record["raw"] is None and record["purged"] == {"raw": _stamp(now)} and record["delivered"]["sha256"] == sha
    assert media.delivered_file(data, rid)["sha256"] == sha, "the delivered render is still handed out"
    assert media.purge(data, now=now + 1)["removed"] == [], "a purged recording is not purged twice"


def test_thirty_days_after_the_delivery_the_whole_folder_goes(data):
    now = 1_700_000_000.0
    rid = take(data, now=now - 40 * DAY)["id"]
    sha = add_render(data, rid)
    media.mark_delivered(data, rid, sha256=sha, task_id=1, pending_id=2, now=now - 30 * DAY)
    assert media.purge(data, now=now)["removed"] == [{"recording": rid, "what": "all"}]
    assert folders(data) == []


def test_a_recording_whose_task_is_running_is_kept_whatever_its_age(data):
    now = 1_700_000_000.0
    rid = take(data, now=now - 90 * DAY)["id"]
    media.bind_task(data, rid, 5, may_replace=lambda old: False, now=now - 90 * DAY)
    asked = []
    out = media.purge(data, now=now, busy=lambda task: asked.append(task) or True)
    assert out["kept"] == [rid] and out["removed"] == [] and asked == [5]
    assert folders(data) == [rid]
    assert media.purge(data, now=now, busy=lambda task: False)["removed"] == [{"recording": rid, "what": "all"}]


def test_a_stray_folder_goes_after_a_day_and_a_younger_one_stays(data):
    now = time.time()
    root = Path(media.root_of(data))
    root.mkdir(parents=True, mode=0o700)
    stale, fresh = root / ("a" * 16), root / ("b" * 16)
    for folder, age in ((stale, 2 * DAY), (fresh, 3600)):
        folder.mkdir(mode=0o700)
        (folder / ".incoming-0123456789abcdef.part").write_bytes(b"half")
        for item in (folder / ".incoming-0123456789abcdef.part", folder):
            os.utime(item, (now - age, now - age))
    part = root / ".incoming-fedcba9876543210.part"
    part.write_bytes(b"half")
    os.utime(part, (now - 2 * DAY, now - 2 * DAY))
    other = root / "notes"
    other.write_text("not ours", encoding="utf-8")
    os.utime(other, (now - 90 * DAY, now - 90 * DAY))
    out = media.purge(data, now=now)
    assert out["stray"] == 2 and out["removed"] == []
    assert not stale.exists() and fresh.exists() and not part.exists() and other.exists()


def test_a_purge_skips_everything_while_an_upload_holds_the_upload_lock(data):
    now = 1_700_000_000.0
    rid = take(data, now=now - 90 * DAY)["id"]
    with intake.Lock(str(Path(media.root_of(data), media.UPLOAD_LOCK)), blocking=False):
        out = media.purge(data, now=now)
    assert out == {"removed": [], "kept": [], "stray": 0, "skipped": ["an upload is running"]}
    assert folders(data) == [rid]


def test_a_purge_of_a_store_that_does_not_exist_yet_is_empty(data):
    assert media.purge(data, now=time.time()) == {"removed": [], "kept": [], "stray": 0, "skipped": []}
    assert media.records(data) == [] and media.usage(data) == 0


def test_a_link_in_place_of_a_recording_folder_is_not_followed_by_the_purge(data, tmp_path):
    now = time.time()
    root = Path(media.root_of(data))
    root.mkdir(parents=True, mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    link = root / ("c" * 16)
    link.symlink_to(outside)
    os.utime(link, (now - 5 * DAY, now - 5 * DAY), follow_symlinks=False)
    media.purge(data, now=now)
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not os.path.lexists(link), "the link itself was removed as a stray"


def test_usage_counts_the_regular_files_and_follows_no_link(data, tmp_path):
    rid = take(data, 100)["id"]
    outside = tmp_path / "big"
    outside.write_bytes(b"x" * 5000)
    (Path(media.folder_of(data, rid)) / "analysis.json").symlink_to(outside)
    assert 100 <= media.usage(data) < 5000

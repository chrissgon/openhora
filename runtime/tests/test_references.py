"""Tests of the reference store (runtime/references.py, package V7b): the names, the marker, the bounds, the descriptors that never follow a link, the closed shape of
the facts, the video deleted right after `measure` (after it succeeds and after it fails), the retention on a fake clock, the media store that refuses a reference's
path, and the upkeep part. Nothing is fetched and every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_references.py
"""
from __future__ import annotations

import copy
import os
import re
import stat
import time
from pathlib import Path

import pytest

import standin_tree as st
from media_fixtures import Body, mp4_head
from reference_kit import LINK, VIDEO_BYTES, add_one, good_facts, ops_core, ops_references, refs, references, world  # noqa: F401

media = st.load("media")
upkeep = st.load("upkeep")
REPO = Path(__file__).resolve().parents[2]
DAY = 86400.0
HOUR = 3600.0
RID = "0123456789abcdef"


@pytest.fixture
def data(tmp_path):
    return str(tmp_path / "data")


def age(path, seconds, now):
    stamp = now - seconds
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def refused(call, *args, **kwargs):
    with pytest.raises(references.RefError) as caught:
        call(*args, **kwargs)
    return caught.value


# 1. the names and the marker


def test_the_root_has_a_read_only_marker_written_once(data):
    root = references.root_of(data)
    marker = Path(root, ".openhora-reference")
    assert Path(root).name == "references" and stat.S_IMODE(os.stat(root).st_mode) == 0o700
    assert marker.is_file() and stat.S_IMODE(marker.stat().st_mode) == 0o400
    stamp = marker.stat().st_mtime_ns
    assert references.root_of(data) == root and marker.stat().st_mtime_ns == stamp, "written once"
    assert references.root_path(str(Path(data) / "other")) == str(Path(data, "other", "references")) and not Path(data, "other").exists()


def test_the_marker_name_is_the_one_the_provider_side_checks():
    side = REPO / "providers" / "_container.py"
    text = side.read_text(encoding="utf-8") if side.is_file() else ""
    if ".openhora-reference" not in text:
        pytest.skip("the provider side's check has not landed in this tree (package V7a)")
    assert references.MARKER == ".openhora-reference" and f'"{references.MARKER}"' in text


def test_ids_and_names_are_closed(data):
    assert references.check_id(RID) == RID
    for bad in ("", "abc", RID.upper(), RID + "0", "../" + RID[3:], None, 5):
        assert refused(references.check_id, bad).code == "usage"
    assert references.folder_of(data, RID) == os.path.join(data, "references", RID)
    for name in ("info.json", "proxy.json", "facts.json", "subs.pt.vtt", "subs.eng.vtt"):
        assert references._check_name(name) == name
    for name in ("record.json", "video.mp4", "subs.PT.vtt", "../facts.json", "subs.p.vtt", "facts.json.bak"):
        assert refused(references._check_name, name).code == "usage"


def test_a_record_has_these_keys_and_these_modes(data):
    record = references.create(data, "clipsite", LINK)
    folder = Path(references.folder_of(data, record["id"]))
    assert set(record) == {"version", "id", "platform", "link", "created_at", "stage", "video_measured_at", "duration", "sizes", "purged"}
    assert record["stage"] == "meta" and record["sizes"] == {"video": None} and record["purged"] == {"video": None}
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and stat.S_IMODE((folder / "record.json").stat().st_mode) == 0o600
    assert references.load(data, record["id"]) == record and references.records(data) == [record]
    for bad in ("Clip Site", "", "x" * 40):
        assert refused(references.create, data, bad, LINK).code == "usage"
    assert refused(references.create, data, "clipsite", "x" * 2049).code == "usage"


def test_a_damaged_record_is_unreadable_and_a_missing_one_is_not_found(data):
    record = references.create(data, "clipsite", LINK)
    path = Path(references.folder_of(data, record["id"]), "record.json")
    path.write_text("{not json", encoding="utf-8")
    assert refused(references.load, data, record["id"]).code == "unreadable" and references.records(data) == []
    path.write_text(path.read_text().replace("{not json", '{"version": 1}'), encoding="utf-8")
    assert refused(references.load, data, record["id"]).code == "unreadable"
    path.unlink()
    assert refused(references.load, data, record["id"]).code == "not_found"
    assert refused(references.load, data, RID).code == "not_found"


def test_a_link_in_place_of_a_folder_is_never_followed(data, tmp_path):
    record = references.create(data, "clipsite", LINK)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "record.json").write_text("{}")
    target = Path(references.folder_of(data, record["id"]))
    os.rename(target, tmp_path / "moved")
    os.symlink(elsewhere, target)
    assert refused(references.load, data, record["id"]).code == "unreadable"
    assert references.delete_video(data, record["id"]) is False
    assert (elsewhere / "record.json").exists()


# 2. the bounds


def test_fifty_references_and_the_quota_are_checked_before_a_folder_is_made(data, monkeypatch):
    for _ in range(references.MAX_REFERENCES):
        references.create(data, "clipsite", LINK)
    assert refused(references.create, data, "clipsite", LINK).code == "limit"
    assert len(references.records(data)) == 50
    monkeypatch.setattr(references, "MAX_REFERENCES", 1000)
    monkeypatch.setattr(references, "QUOTA_BYTES", references.usage(data))
    assert refused(references.create, data, "clipsite", LINK).code == "quota" and len(references.records(data)) == 50


def test_free_bytes_is_the_quota_less_what_the_store_holds(data, monkeypatch):
    record = references.create(data, "clipsite", LINK)
    Path(references.folder_of(data, record["id"]), "info.json").write_bytes(b"x" * 1000)
    held = references.usage(data)
    assert held >= 1000 and references.free_bytes(data) == references.QUOTA_BYTES - held
    monkeypatch.setattr(references, "QUOTA_BYTES", 10)
    assert references.free_bytes(data) == 0
    assert references.QUOTA_BYTES == 10 and references.MAX_REFERENCES == 50 and references.VIDEO_SECONDS_MAX == 300 and references.VIDEO_FILE_CAP == 200 << 20


# 3. the reference-only check


def test_in_reference_is_true_inside_the_store_and_false_elsewhere(data, tmp_path):
    record = references.create(data, "clipsite", LINK)
    folder = Path(references.folder_of(data, record["id"]))
    inside = folder / "video.mp4"
    inside.write_bytes(b"x")
    assert references.in_reference(str(inside)) and references.in_reference(str(folder)) and references.in_reference(references.root_path(data))
    assert references.in_reference(str(folder / "not-made-yet.mp4")), "a path that does not exist yet is read by its folders"
    link = tmp_path / "pointer.mp4"
    os.symlink(inside, link)
    assert references.in_reference(str(link)), "the real path is read, not the name"
    outside = tmp_path / "recording.mp4"
    outside.write_bytes(b"x")
    assert not references.in_reference(str(outside)) and not references.in_reference(str(tmp_path)) and not references.in_reference("/")
    assert not references.in_reference(str(Path(data, "media")))
    Path(tmp_path, ".openhora-reference").mkdir()
    assert not references.in_reference(str(outside)), "a folder of that name is not the marker file"


def test_the_media_store_refuses_a_path_in_a_reference_store(refs):
    rid = add_one(refs)["reference"]
    inside = Path(references.folder_of(refs["data"], rid), "info.json")
    with pytest.raises(media.MediaError) as caught:
        media.receive_file(str(Path(refs["data"]).parent / "media-data"), str(inside))
    assert caught.value.code == "usage" and "a reference is never a recording" in str(caught.value)
    assert not (Path(refs["data"]).parent / "media-data").exists(), "nothing was made"
    fine = Path(refs["tmp"]) / "fine.mp4"
    fine.write_bytes(mp4_head() + b"\0" * 64)
    assert media.receive_file(str(Path(refs["tmp"]) / "media-data"), str(fine))["raw"]["type"] == "mp4"


# 4. the closed shape of the facts


def test_the_facts_of_the_closed_shape_are_accepted(data):
    for frames in (False, True):
        facts = good_facts(RID, "clipsite", frames=frames)
        assert references.check_facts(copy.deepcopy(facts), RID, "clipsite") == facts


@pytest.mark.parametrize("edit", [
    lambda f: f.update(uploader="Bram Hollow"), lambda f: f.pop("speech"), lambda f: f.update(version=2), lambda f: f.update(reference="f" * 16),
    lambda f: f.update(platform="other"), lambda f: f["source"].update(link=LINK), lambda f: f["source"].pop("fps"), lambda f: f["source"].update(aspect="3:2"),
    lambda f: f["source"].update(subtitles="yes"), lambda f: f["source"].update(frames_measured=None), lambda f: f["tool"].update(path="/x"),
    lambda f: f["cuts"].update(times_s=[0.0] * 601), lambda f: f["motion"].update(series_1s=[0.0] * 301), lambda f: f["format"].update(beats=[{"start_s": 0, "end_s": 1, "words": 1}] * 301),
    lambda f: f["format"].update(pauses=[{"at_s": 0, "length_s": 1}] * 301), lambda f: f["external_text"]["cues"].extend([{"start_s": 0, "end_s": 1, "text": "x"}] * 601),
    lambda f: f["external_text"]["cues"].append({"start_s": 0, "end_s": 1, "text": "x" * 201}), lambda f: f["external_text"].update(title="x" * 301),
    lambda f: f["external_text"].update(description="x" * 2001), lambda f: f["external_text"].update(note="read this"), lambda f: f["external_text"].update(extra=1),
    lambda f: f["colour"].update(palette=["#112233"] * 9), lambda f: f["colour"].update(palette=["red"]), lambda f: f["zoom"].update(method="made-up"),
    lambda f: f["captions_on_screen"].update(size="large"), lambda f: f["captions_on_screen"].update(bands=[0.0] * 11), lambda f: f["speech"].update(words=-1),
    lambda f: f["speech"].update(wpm=float("nan")), lambda f: f["speech"].update(words=True), lambda f: f["transitions"].update(method="Has Spaces"),
    lambda f: f["external_text"]["cues"].append({"start_s": 0, "end_s": 1}), lambda f: f.update(measured_at="yesterday"),
])
def test_facts_outside_the_closed_shape_are_refused(edit):
    facts = good_facts(RID, "clipsite", frames=True)
    edit(facts)
    assert refused(references.check_facts, facts, RID, "clipsite").code == "unreadable"
    assert refused(references.check_facts, [], RID, "clipsite").code == "unreadable"


def test_the_third_party_text_is_quoted_line_by_line():
    assert references.quoted("one\ntwo") == ["> one", "> two"] and references.quoted("") == ["> "]
    out = references.quoted("a\x1b[31mb c")
    assert all(line.startswith("> ") for line in out) and not any(c in "".join(out) for c in "\x1b ")


# 5. the video goes right after measure, and the retention


def test_limit_73_the_video_is_deleted_after_measure_and_a_reference_path_is_refused(refs, tmp_path):
    rid = add_one(refs)["reference"]
    # after `measure` succeeds
    got = ops_references.reference_video(refs["path"], rid, confirm=True)
    assert got["video_deleted"] is True and refs["fake"].video_at_measure[-1] is True and not references.has_video(refs["data"], rid)
    # after `measure` fails
    def boom(facts):
        raise RuntimeError("the measure stopped half way")
    refs["fake"].facts_edit = boom                      # `measure` runs with the video in place, then fails
    with pytest.raises(RuntimeError):
        ops_references.reference_video(refs["path"], rid, confirm=True)
    assert refs["fake"].video_at_measure == [False, True, True], "the second measure saw the video too, and it was deleted after it failed"
    assert not references.has_video(refs["data"], rid)
    # the media store refuses a path in the store, and the renderer's own check reads the same marker
    folder = Path(references.folder_of(refs["data"], rid))
    (folder / "video.mp4").write_bytes(mp4_head() + b"\0" * 64)
    with pytest.raises(media.MediaError) as caught:
        media.receive_file(str(tmp_path / "media-data"), str(folder / "video.mp4"))
    assert caught.value.code == "usage" and references.in_reference(str(folder / "video.mp4"))
    assert references.delete_video(refs["data"], rid) is True and not references.has_video(refs["data"], rid)
    # nothing here hands out or copies a reference's bytes: the operations return no path and no bytes
    assert str(folder) not in str(ops_references.reference_list(refs["path"])) and str(folder) not in str(ops_references.reference_read(refs["path"], rid))


def test_a_stray_video_is_purged_after_an_hour_and_not_before(data):
    now = time.time()
    record = references.create(data, "clipsite", LINK, now=now)
    folder = Path(references.folder_of(data, record["id"]))
    (folder / "video.webm").write_bytes(VIDEO_BYTES)
    age(folder / "video.webm", 59 * 60, now)
    assert references.purge(data, now=now)["removed"] == [] and (folder / "video.webm").exists()
    age(folder / "video.webm", 61 * 60, now)
    out = references.purge(data, now=now)
    assert out["removed"] == [{"reference": record["id"], "what": "video"}] and not (folder / "video.webm").exists()
    assert references.load(data, record["id"])["purged"]["video"], "the record says it"
    assert references.load(data, record["id"])["stage"] == "meta"


def test_a_fetch_folder_a_crash_left_is_purged_after_an_hour(data):
    now = time.time()
    record = references.create(data, "clipsite", LINK, now=now)
    folder = Path(references.folder_of(data, record["id"]))
    stray = folder / ".fetch-0123456789ab"
    stray.mkdir(mode=0o700)
    (stray / "result.json").write_text("{}")
    for item in (stray / "result.json", stray):
        age(item, 30 * 60, now)
    assert references.purge(data, now=now)["removed"] == [] and stray.exists()
    for item in (stray / "result.json", stray):
        age(item, 2 * HOUR, now)
    assert references.purge(data, now=now)["removed"] == [{"reference": record["id"], "what": "fetch"}] and not stray.exists()
    assert references.load(data, record["id"])["id"] == record["id"]


def test_limit_74_reference_files_are_deleted_after_30_days(refs):
    rid = add_one(refs)["reference"]
    created = references._epoch(references.load(refs["data"], rid)["created_at"])
    ctx = ops_core.context(refs["path"])
    assert upkeep.run(ctx, now=created + 29 * DAY, force=True, tool=None)["references"] == {"removed": [], "kept": [], "stray": 0, "skipped": []}
    assert Path(references.folder_of(refs["data"], rid)).is_dir() and references.read_json(refs["data"], rid, references.FACTS)
    out = upkeep.run(ctx, now=created + 30 * DAY, force=True, tool=None)
    assert out["references"]["removed"] == [{"reference": rid, "what": "all"}]
    assert not Path(references.folder_of(refs["data"], rid)).exists() and references.records(refs["data"]) == []
    assert references.days_left({"created_at": "2026-11-01T00:00:00Z"}, references._epoch("2026-11-10T00:00:00Z")) == 21
    assert references.days_left({"created_at": "2026-11-01T00:00:00Z"}, references._epoch("2026-12-31T00:00:00Z")) == 0


def test_a_folder_with_no_record_goes_after_a_day_and_a_damaged_one_after_thirty(data):
    now = time.time()
    root = Path(references.root_of(data))
    for name in ("1" * 16, "2" * 16):
        (root / name).mkdir(mode=0o700)
        (root / name / "info.json").write_text("{}")
    (root / ("2" * 16) / "record.json").write_text("not json")
    tomb = root / (".removed-" + "3" * 16)
    tomb.mkdir()
    (tomb / "facts.json").write_text("{}")
    for name in ("1" * 16, "2" * 16):
        for item in (root / name / "info.json", root / name / "record.json", root / name):
            if item.exists():
                age(item, 2 * DAY, now)
    out = references.purge(data, now=now)
    assert out["stray"] == 2 and not (root / ("1" * 16)).exists() and not tomb.exists(), "the tomb of a cut-short removal goes at once"
    assert (root / ("2" * 16)).exists(), "a damaged record is kept for thirty days"
    for item in (root / ("2" * 16) / "info.json", root / ("2" * 16) / "record.json", root / ("2" * 16)):
        age(item, 31 * DAY, now)
    assert references.purge(data, now=now)["stray"] == 1 and not (root / ("2" * 16)).exists()
    assert (root / ".openhora-reference").is_file(), "the marker stays"


def test_a_project_with_no_reference_has_nothing_to_sweep(refs):
    assert upkeep.sweep_references(ops_core.context(refs["path"]), now=time.time()) == {"removed": [], "kept": [], "stray": 0, "skipped": []}
    assert references.purge(str(Path(refs["tmp"]) / "nowhere"), now=time.time()) == {"removed": [], "kept": [], "stray": 0, "skipped": []}


def test_enforce_names_keeps_only_the_closed_names(data):
    record = references.create(data, "clipsite", LINK)
    folder = Path(references.folder_of(data, record["id"]))
    for name in ("info.json", "proxy.json", "facts.json", "video.mp4", "subs.en.vtt", "subs.es.vtt", "subs.fr.vtt", "subs.pt.vtt", "subs.de.vtt", "cookies.txt", "result.json"):
        (folder / name).write_text("x")
    (folder / "extra").mkdir()
    (folder / ".fetch-0123456789ab").mkdir()
    removed = references.enforce_names(data, record["id"])
    assert sorted(removed) == ["cookies.txt", "extra", "result.json", "subs.pt.vtt"], "at most four subtitle files, in name order"
    kept = {p.name for p in folder.iterdir()}
    assert {"record.json", "info.json", "proxy.json", "facts.json", "video.mp4", ".fetch-0123456789ab"} <= kept and "cookies.txt" not in kept


def test_a_video_deleted_twice_and_a_reference_that_is_gone_have_none(data):
    record = references.create(data, "clipsite", LINK)
    folder = Path(references.folder_of(data, record["id"]))
    (folder / "video.mov").write_bytes(b"x")
    assert references.has_video(data, record["id"]) and references.video_size(data, record["id"]) == 1
    assert references.delete_video(data, record["id"]) is True and references.delete_video(data, record["id"]) is True
    assert references.video_size(data, record["id"]) is None and references.delete_video(data, RID) is True


def test_the_facts_are_written_whole_and_taken_back_whole(data):
    record = references.create(data, "clipsite", LINK)
    rid = record["id"]
    assert references.take_facts(data, rid) is None
    references.put_facts(data, rid, b'{"a": 1}')
    path = Path(references.folder_of(data, rid), "facts.json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and references.take_facts(data, rid) == b'{"a": 1}' and references.facts_path(data, rid) == str(path)
    references.drop_facts(data, rid)
    assert not path.exists() and references.take_facts(data, rid) is None


def test_a_reference_is_removed_whole_and_a_busy_one_is_not(data):
    record = references.create(data, "clipsite", LINK)
    Path(references.folder_of(data, record["id"]), "info.json").write_bytes(b"x" * 10)
    with references.operation(data, record["id"]):
        assert refused(references.operation(data, record["id"]).__enter__).code == "busy"
    done = references.remove(data, record["id"])
    assert done["left"] is False and done["bytes"] >= 10 and done["files"] >= 2 and references.records(data) == []
    assert refused(references.remove, data, record["id"]).code == "not_found"
    assert not any(p.name.startswith(".removed-") for p in Path(references.root_path(data)).iterdir())
    assert re.fullmatch(r"[0-9a-f]{16}", RID)

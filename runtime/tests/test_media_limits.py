"""The hard limits of the media store (runtime/media.py), each with a test named after it: the intake of a recording and of an
asset slot's file, its bounds, its type by bytes, its stream check, its hardening, and the retention. Offline: the video
fixtures are tiny synthetic files that ffmpeg makes (the tests that need ffmpeg and ffprobe are skipped with a reason
where they are not installed), the images are written byte by byte, and nothing calls a model or a network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_limits.py
"""
from __future__ import annotations

import datetime
import hashlib
import io
import os
import stat
import tracemalloc

import pytest

import standin_tree as st
from media_fixtures import (Body, Forbidden, FFPROBE, heic, jpeg, make_hdr, make_long, make_mov, make_mp4, make_two_audios,
                            make_two_videos, needs_ffmpeg, png, webp)

media = st.load("media")
UTC = datetime.timezone.utc


@pytest.fixture
def data(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    folder = tmp_path_factory.mktemp("clips")
    out = {}
    if FFPROBE:
        out = {"mov": make_mov(folder / "a.mov"), "mp4": make_mp4(folder / "a.mp4"), "hdr": make_hdr(folder / "h.mp4"),
               "long": make_long(folder / "long.mp4", media.MAX_SECONDS + 1), "edge": make_long(folder / "edge.mp4", media.MAX_SECONDS - 1),
               "two_videos": make_two_videos(folder / "v2.mp4"), "two_audios": make_two_audios(folder / "a2.mp4")}
    return {k: v.read_bytes() for k, v in out.items()}


def put(data, payload, **kwargs):
    return media.receive(data, io.BytesIO(payload), len(payload), **kwargs)


def refusal(data, payload=None, *, length=None, stream=None, **kwargs):
    stream = stream if stream is not None else io.BytesIO(payload)
    with pytest.raises(media.MediaError) as caught:
        media.receive(data, stream, len(payload) if length is None and payload is not None else length, **kwargs)
    return caught.value


def left_over(data):
    """Every file and folder under the store except its two lock files: what a refused upload must not leave."""
    found = []
    for folder, names, files in os.walk(os.path.join(data, "media")):
        found += [os.path.join(folder, n) for n in names + files if n not in (media.UPLOAD_LOCK, media.RECORD_LOCK)]
    return found


# --- the bound on the body, before it is read ----------------------------------------------------------------------------------


def test_media_limit_a_body_over_the_size_limit_is_refused_before_one_byte_is_read(data):
    error = refusal(data, stream=Forbidden(), length=media.MEDIA_MAX_BYTES + 1)
    assert error.kind == "too_large" and left_over(data) == []


def test_media_limit_a_missing_content_length_is_refused(data):
    error = refusal(data, stream=Forbidden(), length=None)
    assert error.kind == "length"


def test_media_limit_an_asset_over_the_largest_asset_limit_is_refused_before_it_is_read(data):
    record = media.create(data)
    error = refusal(data, stream=Forbidden(), length=media.CLIP_MAX_BYTES + 1, recording=record["id"], slot="0" * 12)
    assert error.kind == "too_large"


def test_media_limit_a_body_too_small_to_hold_a_header_is_refused(data):
    assert refusal(data, b"abc").kind == "type"


def test_media_limit_a_body_that_is_not_a_video_is_refused_and_leaves_nothing(data):
    for payload in (b"hello there, this is only text and not a video at all", png(), jpeg()):
        error = refusal(data, payload)
        assert error.kind == "type"
    assert left_over(data) == []


def test_media_limit_the_type_is_read_from_the_bytes_and_not_from_the_name(data, clips):
    if not clips:
        pytest.skip("ffmpeg and ffprobe are not installed")
    wrong = refusal(data, png(), name="holiday.mov")        # a PNG with a video's name
    assert wrong.kind == "type"
    done = put(data, clips["mp4"], name="notes.txt")        # a video with a text name
    assert done["kind"] == "recording" and done["type"] == "mp4"
    assert os.path.basename(os.listdir(os.path.join(data, "media", done["recording"]))[0]) in ("raw.mp4", "record.json")


def test_media_limit_a_heic_photo_is_refused_with_the_way_out(data):
    record = media.create(data)
    media.register_slots(data, record["id"], [{"key": "b1", "description": "a photo"}])
    sid = media.slot_id(record["id"], "b1")
    error = refusal(data, heic(), recording=record["id"], slot=sid)
    assert error.kind == "type" and "JPEG" in str(error)


# --- the bytes on disk ----------------------------------------------------------------------------------------------------------


@needs_ffmpeg
def test_media_limit_a_recording_is_stored_under_a_code_issued_id_with_private_modes_and_its_hash(data, clips):
    done = put(data, clips["mov"], name="My%20clip.mov")
    rid = done["recording"]
    assert media.ID.fullmatch(rid) and done["sha256"] == hashlib.sha256(clips["mov"]).hexdigest() and done["bytes"] == len(clips["mov"])
    folder = os.path.join(data, "media", rid)
    assert stat.S_IMODE(os.lstat(folder).st_mode) == 0o700 and stat.S_IMODE(os.lstat(os.path.join(data, "media")).st_mode) == 0o700
    raw = os.path.join(folder, "raw.mov")
    assert stat.S_IMODE(os.lstat(raw).st_mode) == 0o600 and stat.S_IMODE(os.lstat(os.path.join(folder, "record.json")).st_mode) == 0o600
    assert open(raw, "rb").read() == clips["mov"]
    record = media.load(data, rid)
    assert record["raw"]["name"] == "My clip.mov" and record["raw"]["file"] == "raw.mov" and record["status"] == "open"
    assert os.listdir(folder).count("raw.mov") == 1 and not [n for n in os.listdir(folder) if n.endswith(".part")]


def test_media_limit_the_store_path_is_outside_the_project_and_under_the_data_folder(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    data = tmp_path / "data"
    root = media.root_of(str(data))
    assert os.path.realpath(root).startswith(os.path.realpath(data) + os.sep)
    assert not os.path.realpath(root).startswith(os.path.realpath(project) + os.sep)
    assert media.root_of("/x/data") == "/x/data/media"


@needs_ffmpeg
def test_media_limit_a_pre_placed_link_at_the_temporary_name_is_refused_and_nothing_is_written_through_it(data, clips, tmp_path, monkeypatch):
    record = media.create(data)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    folder = os.path.join(data, "media", record["id"])
    os.symlink(victim, os.path.join(folder, ".incoming-" + "ab" * 8 + ".part"))
    monkeypatch.setattr(media.secrets, "token_hex", lambda n: "ab" * n)
    error = refusal(data, clips["mov"], recording=record["id"])
    assert error.kind == "refused" and victim.read_text() == "keep me"
    assert media.load(data, record["id"])["raw"] is None


@needs_ffmpeg
def test_media_limit_an_occupied_temporary_name_is_refused(data, clips, monkeypatch):
    record = media.create(data)
    folder = os.path.join(data, "media", record["id"])
    open(os.path.join(folder, ".incoming-" + "cd" * 8 + ".part"), "w").write("someone's")
    monkeypatch.setattr(media.secrets, "token_hex", lambda n: "cd" * n)
    assert refusal(data, clips["mov"], recording=record["id"]).kind == "refused"
    assert open(os.path.join(folder, ".incoming-" + "cd" * 8 + ".part")).read() == "someone's"


def test_media_limit_a_folder_that_is_a_link_or_open_to_others_is_refused(data, tmp_path):
    record = media.create(data)
    folder = os.path.join(data, "media", record["id"])
    os.chmod(folder, 0o755)
    with pytest.raises(media.MediaError):
        media._check_dir(folder, "the folder")
    os.chmod(folder, 0o700)
    link = tmp_path / "link"
    os.symlink(folder, link)
    with pytest.raises(media.MediaError):
        media._check_dir(str(link), "the folder")


@needs_ffmpeg
def test_media_limit_free_space_below_the_need_refuses_before_the_body_is_read(data, clips, monkeypatch):
    monkeypatch.setattr(media, "_free_bytes", lambda path: 1000)
    with pytest.raises(media.MediaError) as caught:
        media.receive(data, Forbidden(), len(clips["mov"]))
    assert caught.value.kind == "no_space" and left_over(data) == []


@needs_ffmpeg
def test_media_limit_a_second_upload_at_once_is_refused(data, clips):
    media.ensure_root(data)
    with media._Lock(os.path.join(data, "media", media.UPLOAD_LOCK), blocking=False):
        with pytest.raises(media.MediaError) as caught:
            media.receive(data, Forbidden(), len(clips["mov"]))
    assert caught.value.kind == "refused" and "another upload" in str(caught.value)
    assert put(data, clips["mov"])["kind"] == "recording"      # the lock was released: the next upload goes through


@needs_ffmpeg
def test_media_limit_the_quota_of_the_store_refuses(data, clips, monkeypatch):
    monkeypatch.setattr(media, "QUOTA_BYTES", len(clips["mov"]) * 2 - 1)
    put(data, clips["mov"])
    error = refusal(data, clips["mov"])
    assert error.kind == "refused" and "purge" in str(error)


@needs_ffmpeg
def test_media_limit_the_render_cap_refuses(data, clips):
    record = media.create(data)
    folder = os.path.join(data, "media", record["id"])
    for n in range(media.MAX_RENDERS):
        open(os.path.join(folder, f"render-{n:012x}.mp4"), "wb").write(b"x")
    assert media.renders_kept(data) == media.MAX_RENDERS
    error = refusal(data, clips["mov"])
    assert error.kind == "refused" and "renders" in str(error)


@needs_ffmpeg
def test_media_limit_a_dropped_connection_leaves_no_file_and_no_recording(data, clips):
    head = clips["mov"][:4096]
    for stream in (Body(len(clips["mov"]) + 10, head, fail_after=len(head)),     # the connection resets
                   Body(len(clips["mov"]) + 10, head, stop_after=len(head))):    # the client goes away: the body ends short
        with pytest.raises(media.MediaError) as caught:
            media.receive(data, stream, len(clips["mov"]) + 10)
        assert caught.value.kind == "usage"
    assert left_over(data) == []


@needs_ffmpeg
def test_media_limit_a_dropped_upload_to_an_existing_recording_leaves_its_folder_and_no_partial_file(data, clips):
    record = media.create(data)
    with pytest.raises(media.MediaError):
        media.receive(data, Body(10_000, clips["mov"][:4096], stop_after=4096), 10_000, recording=record["id"])
    assert sorted(os.listdir(os.path.join(data, "media", record["id"]))) == ["record.json"]
    assert media.load(data, record["id"])["raw"] is None


@needs_ffmpeg
def test_media_limit_an_upload_that_takes_too_long_is_refused_and_leaves_no_file(data, clips, monkeypatch):
    monkeypatch.setattr(media, "UPLOAD_MAX_SECONDS", -1)
    error = refusal(data, clips["mov"])
    assert error.kind == "refused" and "took more than" in str(error) and left_over(data) == []


def test_media_limit_streaming_a_large_body_stays_under_a_memory_bound(data, monkeypatch):
    size = 200 * 1024 * 1024
    head = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  "
    monkeypatch.setattr(media, "probe", lambda path: {"videos": 1, "audios": 1, "others": 0, "duration": 10.0, "width": 1920,
                                                      "height": 1080, "fps": 30.0, "video_codec": "h264", "audio_codec": "aac",
                                                      "hdr": False})
    monkeypatch.setattr(media, "ffprobe_path", lambda: "/stub/ffprobe")
    monkeypatch.setattr(media, "_free_bytes", lambda path: 10 * size)
    tracemalloc.start()
    try:
        done = media.receive(data, Body(size, head), size)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert done["bytes"] == size
    assert peak < 16 * 1024 * 1024, f"peak {peak} bytes while streaming {size}"
    os.unlink(os.path.join(data, "media", done["recording"], "raw.mov"))


# --- the checks of the video ----------------------------------------------------------------------------------------------------


@needs_ffmpeg
def test_media_limit_a_recording_over_the_duration_limit_is_refused_and_one_under_it_is_taken(data, clips):
    over = refusal(data, clips["long"])
    assert over.kind == "too_large" and f"at most {media.MAX_SECONDS} s" in str(over) and left_over(data) == []
    assert put(data, clips["edge"])["facts"]["duration"] < media.MAX_SECONDS


@needs_ffmpeg
def test_media_limit_data_streams_are_ignored_by_the_stream_check(data, clips):
    facts = media.probe(_write(data, clips["mov"]))
    assert facts["videos"] == 1 and facts["audios"] == 1 and facts["others"] >= 1       # the timecode track an iPhone-style file carries
    assert put(data, clips["mov"])["facts"]["video_codec"] == "h264"


def _write(data, payload):
    os.makedirs(data, exist_ok=True)
    path = os.path.join(data, "probe.bin")
    open(path, "wb").write(payload)
    return path


@needs_ffmpeg
def test_media_limit_hdr_is_refused_with_the_way_to_record_again(data, clips):
    error = refusal(data, clips["hdr"])
    assert error.kind == "type" and "HDR" in str(error) and "Settings" in str(error) and left_over(data) == []


@needs_ffmpeg
def test_media_limit_exactly_one_video_and_at_most_one_audio_stream(data, clips):
    assert refusal(data, clips["two_videos"]).kind == "type"
    assert refusal(data, clips["two_audios"]).kind == "type"
    assert left_over(data) == []


@needs_ffmpeg
def test_media_limit_a_recording_is_never_replaced(data, clips):
    done = put(data, clips["mov"])
    error = refusal(data, clips["mp4"], recording=done["recording"])
    assert error.kind == "refused" and "never replaced" in str(error)
    assert media.load(data, done["recording"])["raw"]["sha256"] == done["sha256"]


def test_media_limit_an_unknown_recording_or_a_malformed_id_is_refused(data):
    assert refusal(data, b"x" * 64, recording="0" * 16).kind == "not_found"
    for bad in ("../etc", "ABCDEF0123456789", "0123", "0" * 17, "zz" * 8, ""):
        assert refusal(data, b"x" * 64, recording=bad).kind == "usage", bad
    record = media.create(data)
    assert refusal(data, b"x" * 64, recording=record["id"], slot="../x").kind == "usage"
    assert refusal(data, b"x" * 64, slot="a" * 12).kind == "usage"          # a slot needs its recording


# --- the file name ----------------------------------------------------------------------------------------------------------------


def test_media_limit_the_file_name_header_is_hardened():
    assert media.clean_name(None) is None
    assert media.clean_name("Caf%C3%A9.mov") == "Caf\u00e9.mov"
    assert media.clean_name("Cafe%CC%81.mov") == "Caf\u00e9.mov"                        # decomposed in, NFC out
    for hostile in ("a%00b.mov", "a%0Ab.mov", "evil%E2%80%AEvom.mov", "a%E2%80%8Bb.mov", "a%EF%BB%BFb", "a%2Fb", "a%5Cb",
                    "%E2%80%A8x", "%ED%A0%80", "%FF", "caf\u00e9.mov", "", "%20%20", "a" * 121, "%E2%82%AC" * 100):
        with pytest.raises(media.MediaError) as caught:
            media.clean_name(hostile)
        assert caught.value.kind == "usage", hostile
    with pytest.raises(media.MediaError):
        media.clean_name("a" * (media.HEADER_NAME_MAX + 1))


# --- the images and clips of the slots -----------------------------------------------------------------------------------------------


def slot_world(data, count=1):
    record = media.create(data)
    media.register_slots(data, record["id"], [{"key": f"beat-{n}", "description": f"image {n}"} for n in range(count)])
    return record["id"], [media.slot_id(record["id"], f"beat-{n}") for n in range(count)]


def test_media_limit_an_image_for_a_slot_is_taken_by_its_bytes_and_stored_under_the_recording(data):
    rid, (sid,) = slot_world(data)
    for payload, ext, kind in ((png(40, 30), "png", "png"), (jpeg(40, 30), "jpg", "jpeg"), (webp(40, 30), "webp", "webp")):
        done = put(data, payload, recording=rid, slot=sid, name="photo")
        assert done["kind"] == "asset" and done["type"] == kind and done["facts"] == {"width": 40, "height": 30}
        assert os.path.exists(os.path.join(data, "media", rid, "assets", f"{sid}.{ext}"))
    files = os.listdir(os.path.join(data, "media", rid, "assets"))
    assert files == [f"{sid}.webp"]                                              # one file per slot: the newest replaced the others
    assert media.load(data, rid)["slots"][sid]["asset"]["type"] == "webp"
    assert stat.S_IMODE(os.lstat(os.path.join(data, "media", rid, "assets")).st_mode) == 0o700


def test_media_limit_an_asset_needs_a_slot_the_code_issued(data):
    rid, _ = slot_world(data)
    assert refusal(data, png(), recording=rid, slot="f" * 12).kind == "not_found"


def test_media_limit_an_animated_image_is_refused(data):
    rid, (sid,) = slot_world(data)
    assert "animated" in str(refusal(data, png(animated=True), recording=rid, slot=sid))
    assert "animated" in str(refusal(data, webp(animated=True), recording=rid, slot=sid))
    assert media.load(data, rid)["slots"][sid]["asset"] is None


def test_media_limit_image_dimensions_are_bounded_from_the_header(data):
    rid, (sid,) = slot_world(data)
    assert refusal(data, png(media.IMAGE_MAX_SIDE + 1, 10), recording=rid, slot=sid).kind == "too_large"
    assert refusal(data, png(8000, 8000), recording=rid, slot=sid).kind == "too_large"          # 64 megapixels
    assert refusal(data, jpeg(9000, 10), recording=rid, slot=sid).kind == "too_large"
    assert os.listdir(os.path.join(data, "media", rid, "assets")) == []          # a refused file leaves nothing in the assets folder


def test_media_limit_an_image_over_the_image_limit_is_refused_after_its_type_is_known(data):
    rid, (sid,) = slot_world(data)
    big = png() + b"\x00" * (media.IMAGE_MAX_BYTES + 1)
    assert refusal(data, stream=io.BytesIO(big), length=len(big), recording=rid, slot=sid).kind == "too_large"


@needs_ffmpeg
def test_media_limit_a_clip_for_a_slot_is_checked_like_a_recording(data, clips):
    rid, (sid,) = slot_world(data)
    done = put(data, clips["mp4"], recording=rid, slot=sid)
    assert done["type"] == "mp4" and os.path.exists(os.path.join(data, "media", rid, "assets", f"{sid}.mp4"))
    assert "HDR" in str(refusal(data, clips["hdr"], recording=rid, slot=sid))
    over = refusal(data, clips["edge"], recording=rid, slot=sid)                  # 299 s: over the clip limit
    assert over.kind == "too_large" and f"at most {media.CLIP_MAX_SECONDS} s" in str(over)


def test_media_limit_a_slot_id_is_bound_to_its_description_and_assets_are_frozen_once_an_effect_is_open(data):
    rid, (sid,) = slot_world(data)
    put(data, png(), recording=rid, slot=sid)
    media.register_slots(data, rid, [{"key": "beat-0", "description": "image 0"}])
    assert media.load(data, rid)["slots"][sid]["asset"]["stale"] is False
    media.register_slots(data, rid, [{"key": "beat-0", "description": "a different image"}])        # same key, same id, new description
    assert media.load(data, rid)["slots"][sid]["asset"]["stale"] is True
    media.confirm_slot(data, rid, sid)
    assert media.load(data, rid)["slots"][sid]["asset"]["stale"] is False
    media.freeze(data, rid)
    assert refusal(data, png(), recording=rid, slot=sid).kind == "refused"
    with pytest.raises(media.MediaError):
        media.register_slots(data, rid, [])


def test_media_limit_the_record_maps_the_recording_id_to_the_post_files(data):
    record = media.create(data, posts={"instagram": "docs/marketing/posts/launch-reel.md", "tiktok": "docs/marketing/posts/launch-tiktok.md"},
                          tasks={"code": 12})
    assert media.ID.fullmatch(record["id"]) and record["posts"]["tiktok"].endswith("launch-tiktok.md") and record["tasks"] == {"code": 12}
    assert media.create(data)["id"] != record["id"]
    for bad in ("../outside.md", "/etc/passwd", "docs/../x.md", "docs/x.txt", "other/x.md", "docs//x.md"):
        with pytest.raises(media.MediaError):
            media.link_posts(data, record["id"], {"instagram": bad})
    with pytest.raises(media.MediaError):
        media.link_posts(data, record["id"], {"Instagram!": "docs/x.md"})
    with pytest.raises(media.MediaError):
        media.bind_tasks(data, record["id"], {"anything": 3})


# --- the retention (D7) ------------------------------------------------------------------------------------------------------------------


def aged(data, status, days, *, start=None):
    """A recording whose end (or last change, for an open one) was `days` days ago, with files of every class."""
    now = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    then = now - datetime.timedelta(days=days)
    record = media.create(data, now=then)
    folder = os.path.join(data, "media", record["id"])
    for name in ("raw.mov", "transcript.json", "beats.json", "annotations.json", "render-0123456789ab.mp4", "cover.png"):
        open(os.path.join(folder, name), "wb").write(b"x" * 10)
    os.makedirs(os.path.join(folder, "payload"))
    open(os.path.join(folder, "payload", "payload.json"), "w").write("{}")
    os.makedirs(os.path.join(folder, "assets"))
    open(os.path.join(folder, "assets", "s.png"), "wb").write(b"x")
    if status != "open":
        media.mark(data, record["id"], status, now=then)
    return record["id"], folder, now


def test_media_limit_purge_removes_the_raw_after_seven_days_and_the_renders_after_thirty(data):
    rid, folder, now = aged(data, "published", 6)
    assert media.purge(data, now)["removed"] == [] and os.path.exists(os.path.join(folder, "raw.mov"))
    rid, folder, now = aged(data, "published", 8)
    done = media.purge(data, now)
    assert done["removed"] == [{"recording": rid, "what": "raw", "run_dirs": 0}]
    assert sorted(os.listdir(folder)) == ["cover.png", "payload", "record.json", "render-0123456789ab.mp4"]
    record = media.load(data, rid)
    assert record["raw"] is None and record["purged"]["raw"]
    assert media.purge(data, now)["removed"] == []                                             # once only
    later = now + datetime.timedelta(days=23)
    assert media.purge(data, later)["removed"][0]["what"] == "all" and not os.path.exists(folder)


def test_media_limit_purge_removes_a_cancelled_recording_after_seven_days_whole(data):
    rid, folder, now = aged(data, "cancelled", 8)
    assert media.purge(data, now)["removed"][0] == {"recording": rid, "what": "all", "run_dirs": 0} and not os.path.exists(folder)


def test_media_limit_purge_removes_an_abandoned_post_past_its_maximum_age_and_never_a_scheduled_one(data):
    young, young_folder, now = aged(data, "open", media.ABANDONED_DAYS - 1)
    old, old_folder, now = aged(data, "open", media.ABANDONED_DAYS)
    scheduled, scheduled_folder, now = aged(data, "scheduled", 400)
    done = media.purge(data, now)
    assert [r["recording"] for r in done["removed"]] == [old]
    assert os.path.exists(young_folder) and os.path.exists(scheduled_folder) and not os.path.exists(old_folder)


def test_media_limit_purge_removes_the_edit_tasks_run_folders_with_every_attempt_and_waits_for_a_running_one(data, tmp_path):
    rid, folder, now = aged(data, "cancelled", 8)
    runs = tmp_path / "data" / "task-runs" / "41"
    for sub in ("outputs", "cwd/docs", "failed-1/outputs", "early-end-2"):
        (runs / sub).mkdir(parents=True)
    (runs / "prompt.md").write_text("transcript words")
    (runs / "outputs" / "response.md").write_text("transcript words")
    (runs / "failed-1" / "outputs" / "stream.jsonl").write_text("transcript words")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    media.bind_tasks(data, rid, {"edit": 7})
    assert media.run_dirs_inside(data, [str(runs), str(outside), "/", None]) == [str(runs)]       # only a folder under task-runs/
    held = media.purge(data, now, run_dirs_of=lambda record: None)
    assert held["removed"] == [] and "still going" in held["skipped"][0] and runs.exists() and os.path.exists(folder)
    done = media.purge(data, now, run_dirs_of=lambda record: [str(runs)])
    assert done["removed"][0]["run_dirs"] == 1 and not runs.exists() and not os.path.exists(folder)


def test_media_limit_purge_removes_a_stray_partial_file_and_a_folder_with_no_record_and_not_while_an_upload_runs(data):
    now = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    record = media.create(data, now=now)
    folder = os.path.join(data, "media", record["id"])
    part = os.path.join(folder, ".incoming-" + "ef" * 8 + ".part")
    open(part, "wb").write(b"x")
    orphan = os.path.join(data, "media", "1" * 16)
    os.mkdir(orphan, 0o700)
    old = now.timestamp() - 3 * 86400
    os.utime(part, (old, old))
    os.utime(orphan, (old, old))
    with media._Lock(os.path.join(data, "media", media.UPLOAD_LOCK), blocking=False):
        assert media.purge(data, now)["skipped"] == ["an upload is running"] and os.path.exists(part) and os.path.exists(orphan)
    done = media.purge(data, now)
    assert done["stray"] == 2 and not os.path.exists(part) and not os.path.exists(orphan) and os.path.exists(folder)


def test_media_limit_purge_of_one_recording_by_id_ignores_its_age(data):
    rid, folder, now = aged(data, "open", 1)
    other, other_folder, _ = aged(data, "open", 1)
    assert media.purge(data, now, only=rid)["removed"][0]["recording"] == rid
    assert not os.path.exists(folder) and os.path.exists(other_folder)

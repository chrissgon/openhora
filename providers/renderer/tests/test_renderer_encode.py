"""The common image's two new media verbs, `proxy` and `encode`, on synthetic inputs (the container entry point run on the host, as the
other verb tests do), the closed result rows, and the extra mounts of the box. Every media file is a generated test pattern and tone."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

import renderer_kit as K
import _docker as D
import _edl
import _host
import _media
import _output
from _text import Refusal
from _vocab import load_data

needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
DATA = load_data()
INSTAGRAM = json.loads(K.INSTAGRAM.read_text())


def ffmpeg(*args):
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True, timeout=300)


def prores(path, seconds, size="1080x1920", rate=30, audio=True):
    argv = ["-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d:duration=%s" % (size, rate, seconds)]
    if audio:
        argv += ["-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=%s" % seconds]
    argv += ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"] + (["-c:a", "pcm_s16le"] if audio else [])
    ffmpeg(*argv, path)


@pytest.fixture
def world(tmp_path):
    transcript = K.build_transcript(K.SHORT_SENTENCES)
    src = tmp_path / "source.mp4"
    K.make_source(src, transcript)
    rc, out, err = K.run_verb("analyse", "--in", src, "--out", tmp_path / "analysis.json")
    assert rc == 0, err
    rc, out, err = K.run_verb("base", "--transcript", K.write_json(tmp_path / "transcript.json", transcript), "--analysis", tmp_path / "analysis.json",
                              "--out", tmp_path / "edl.json")
    assert rc == 0, err
    edl = json.loads((tmp_path / "edl.json").read_text())
    return tmp_path, src, edl


def sha(path):
    return _media.sha256_file(str(path))


def encode(tmp, intermediate, edl_path, out, digest=None, *more):
    return K.run_verb("encode", "--in", intermediate, "--sha256", digest or sha(intermediate), "--edl", edl_path, "--platform-file", K.INSTAGRAM,
                      "--out", out, *more)


# ---------------------------------------------------------------- proxy

@needs_ffmpeg
def test_the_proxy_is_1080x1920_at_the_edit_lists_fps_and_keeps_the_whole_timeline(world):
    tmp, src, edl = world
    rc, out, err = K.run_verb("proxy", "--edl", tmp / "edl.json", "--in", src, "--out", tmp / "proxy.mp4")
    assert rc == 0, err
    clean = D.sanitise(out, D.RESULT_SCHEMAS["proxy"], "proxy")
    assert (clean["width"], clean["height"], clean["fps"], clean["has_audio"]) == (1080, 1920, edl["fps"], True)
    facts = _media.probe(K.FFPROBE, str(tmp / "proxy.mp4"))
    assert abs(facts["duration"] - edl["source"]["duration"]) <= 2.0 / edl["fps"] and clean["sha256"] == sha(tmp / "proxy.mp4")


@needs_ffmpeg
def test_a_recording_that_is_not_the_edit_lists_is_refused_before_a_proxy_is_made(world):
    tmp, src, edl = world
    edl["source"]["sha256"] = "0" * 64
    K.write_json(tmp / "other.json", edl)
    rc, out, err = K.run_verb("proxy", "--edl", tmp / "other.json", "--in", src, "--out", tmp / "proxy.mp4")
    assert rc == 1 and out["code"] == "recording_changed" and not (tmp / "proxy.mp4").exists()


@needs_ffmpeg
def test_a_proxy_shorter_than_the_recording_is_refused_as_truncated(world, monkeypatch):
    tmp, src, edl = world
    import _inner
    real = _media.probe

    def short(ffprobe, path, *a, **k):
        facts = real(ffprobe, path, *a, **k)
        return dict(facts, duration=facts["duration"] - 1.0) if path.endswith("proxy.mp4") else facts

    monkeypatch.setattr(_media, "probe", short)
    args = _inner.parser().parse_args(["proxy", "--edl", str(tmp / "edl.json"), "--in", str(src), "--out", str(tmp / "proxy.mp4")])
    with pytest.raises(Refusal) as caught:
        _inner.verb_proxy(args)
    assert caught.value.code == "proxy_truncated"


# ---------------------------------------------------------------- encode

@needs_ffmpeg
def test_the_encode_writes_one_named_file_and_its_result_passes_the_closed_schema(world):
    tmp, src, edl = world
    mov = tmp / "hf.mov"
    prores(mov, edl["out_frames"] / edl["fps"])
    rc, out, err = encode(tmp, mov, tmp / "edl.json", tmp / "out")
    assert rc == 0, err
    clean = D.sanitise(out, D.RESULT_SCHEMAS["encode"], "encode")
    assert clean["intermediate_sha256"] == sha(mov) and clean["out_frames"] == edl["out_frames"]
    assert sorted(os.listdir(tmp / "out")) == ["render-%s.mp4" % clean["sha256"][:12]]
    assert sha(tmp / "out" / ("render-%s.mp4" % clean["sha256"][:12])) == clean["sha256"]


@needs_ffmpeg
def test_one_intermediate_encoded_twice_gives_one_sha256(world):
    tmp, src, edl = world
    mov = tmp / "hf.mov"
    prores(mov, edl["out_frames"] / edl["fps"])
    first = encode(tmp, mov, tmp / "edl.json", tmp / "o1")[1]["sha256"]
    second = encode(tmp, mov, tmp / "edl.json", tmp / "o2")[1]["sha256"]
    assert first == second


@needs_ffmpeg
def test_an_intermediate_that_is_not_the_one_the_host_hashed_is_refused(world):
    tmp, src, edl = world
    mov = tmp / "hf.mov"
    prores(mov, edl["out_frames"] / edl["fps"])
    rc, out, err = encode(tmp, mov, tmp / "edl.json", tmp / "out", "0" * 64)
    assert rc == 1 and out["code"] == "intermediate_differs" and not os.path.exists(tmp / "out")


@needs_ffmpeg
def test_an_intermediate_of_another_size_is_refused(world):
    tmp, src, edl = world
    mov = tmp / "small.mov"
    prores(mov, edl["out_frames"] / edl["fps"], size="720x1280")
    rc, out, err = encode(tmp, mov, tmp / "edl.json", tmp / "out")
    assert rc == 1 and out["code"] == "intermediate_mismatch"


@needs_ffmpeg
def test_an_intermediate_of_another_length_or_rate_is_refused(world):
    tmp, src, edl = world
    long = tmp / "long.mov"
    prores(long, edl["out_frames"] / edl["fps"] + 2)
    assert encode(tmp, long, tmp / "edl.json", tmp / "o1")[1]["code"] == "intermediate_mismatch"
    slow = tmp / "slow.mov"
    prores(slow, edl["out_frames"] / edl["fps"], rate=25)
    assert encode(tmp, slow, tmp / "edl.json", tmp / "o2")[1]["code"] == "intermediate_mismatch"


@needs_ffmpeg
def test_an_intermediate_without_the_audio_the_edit_list_has_is_refused(world):
    tmp, src, edl = world
    assert edl["source"]["has_audio"] is True
    mov = tmp / "mute.mov"
    prores(mov, edl["out_frames"] / edl["fps"], audio=False)
    rc, out, err = encode(tmp, mov, tmp / "edl.json", tmp / "out")
    assert rc == 1 and out["code"] == "intermediate_no_audio"


@needs_ffmpeg
def test_a_video_that_is_not_prores_is_not_an_intermediate(world):
    tmp, src, edl = world
    rc, out, err = encode(tmp, src, tmp / "edl.json", tmp / "out")
    assert rc == 1 and out["code"] == "video_codec"


# ---------------------------------------------------------------- the recording checks moved to _output

@needs_ffmpeg
def test_the_recording_check_returns_its_probe_and_refuses_in_the_order_the_render_did(world):
    tmp, src, edl = world
    limits = DATA["limits"]
    facts = _output.check_recording(K.FFPROBE, str(src), edl, limits)
    assert facts["has_audio"] is True and facts["width"] == 1080
    for change, code in ((lambda e: e["source"].update(duration=edl["source"]["duration"] + 1), "recording_changed"),
                         (lambda e: e["source"].update(sha256="1" * 64), "recording_changed"),
                         (lambda e: e["source"].update(has_audio=False), "recording_changed")):
        other = json.loads(json.dumps(edl))
        change(other)
        with pytest.raises(Refusal) as caught:
            _output.check_recording(K.FFPROBE, str(src), other, limits)
        assert caught.value.code == code
    with pytest.raises(Refusal) as caught:
        _output.check_recording(K.FFPROBE, str(src), edl, dict(limits, input_seconds_max=1))
    assert caught.value.code == "input_too_long"


def test_the_three_moved_names_are_still_found_where_they_were():
    import _render
    assert _render.time_limit_for is _output.time_limit_for and _render.check_documents is _output.check_documents
    assert _render.check_recording is _output.check_recording


# ---------------------------------------------------------------- the box: extra mounts and the cpu set

def argv_with(**more):
    return D.container_argv("n", "sha256:" + "ab" * 32, ["selfcheck"], job_dir="/s/job/in", out_dir="/s/job/out", recording=None, memory_mb=4096,
                            cpus=4, scratch_mb=64, deadline=5, platform="linux", **more)


def test_extra_mounts_come_after_the_four_fixed_ones_in_order(tmp_path):
    base = argv_with()
    command = argv_with(extra_mounts=[("/s/work", "/work", "rw"), ("/s/blocks", "/blocks", "ro")])
    assert command[:len(base) - 2] == base[:len(base) - 2]
    mounts = [command[i + 1] for i, a in enumerate(command) if a == "-v"]
    assert mounts[-2:] == ["/s/work:/work:rw", "/s/blocks:/blocks:ro"] and mounts[:2] == ["/s/job/in:/job:ro", "/s/job/out:/out:rw"]


@pytest.mark.parametrize("inside", ["/in", "/in/x", "/in/recording", "/job", "/job/sub", "/out", "/out/y", "/scratch", "/scratch/z"])
def test_an_extra_mount_under_a_fixed_mount_point_is_refused(inside):
    with pytest.raises(Refusal) as caught:
        argv_with(extra_mounts=[("/s/x", inside, "ro")])
    assert caught.value.code == "bad_mount"


def test_a_mount_point_that_only_starts_like_a_fixed_one_is_allowed():
    assert any(a.endswith(":/jobs:ro") for a in argv_with(extra_mounts=[("/s/x", "/jobs", "ro")]))


def test_the_cpuset_reaches_the_box():
    command = argv_with(cpuset="0-3")
    assert command[command.index("--cpus") + 2:command.index("--cpus") + 4] == ["--cpuset-cpus", "0-3"]
    with pytest.raises(Refusal):
        argv_with(cpuset="3-1")
    assert "--cpuset-cpus" not in argv_with()


def test_add_mount_takes_an_existing_folder_that_is_not_a_link_and_returns_the_inside_path(tmp_path):
    job = _host.Job(None, 60, "x")
    (tmp_path / "d").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "d")
    (tmp_path / "f").write_text("x")
    assert job.add_mount(str(tmp_path / "d"), "/work", "rw") == "/work" and job.extra_mounts == [(str(tmp_path / "d"), "/work", "rw")]
    for host, mode in ((str(tmp_path / "link"), "ro"), (str(tmp_path / "f"), "ro"), (str(tmp_path / "gone"), "ro"), (str(tmp_path / "d"), "rwx")):
        with pytest.raises(Refusal) as caught:
            job.add_mount(host, "/other", mode)
        assert caught.value.code == "bad_mount"
    assert len(job.extra_mounts) == 1

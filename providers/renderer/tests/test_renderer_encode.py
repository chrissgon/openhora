"""The recording check that moved to `_output`, the closed result rows and the extra mounts of the box, on synthetic inputs (the container entry point run on
the host, as the other verb tests do). The `proxy` and `encode` verbs' tests went with the HyperFrames engine (PF-b). Every media file is a generated test pattern and tone."""
from __future__ import annotations

import json

import pytest

import renderer_kit as K
import _docker as D
import _host
import _output
from _text import Refusal
from _vocab import load_data

needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
DATA = load_data()


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

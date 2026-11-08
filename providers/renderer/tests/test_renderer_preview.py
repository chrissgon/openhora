"""The preview (`preview`): a smaller copy of a finished render for a phone, at most 15 MiB, 720x1280, the same length, its index first. The
container verb runs on the host here (ffmpeg only); the host side runs against the fake docker. Every recording is a synthetic test pattern."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import struct
import subprocess
from pathlib import Path

import pytest

import renderer_kit as K
import docker_kit as DK
import _docker as D
import _host
import _media

needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
SPEC = json.loads((K.RENDERER / "renderer-presets.json").read_text())["preview"]
KEYS = {"ok", "sha256", "from_sha256", "bytes", "width", "height", "duration", "has_audio", "video_kbps", "audio_kbps", "seconds"}
CAP = 15 * 1024 * 1024


@pytest.fixture
def world(tmp_path):
    (tmp_path / "home").mkdir()
    return DK.World(tmp_path)


def sha(data_or_path) -> str:
    if isinstance(data_or_path, (bytes, bytearray)):
        return hashlib.sha256(data_or_path).hexdigest()
    return hashlib.sha256(Path(data_or_path).read_bytes()).hexdigest()


def pattern(path, size="1920x1080", seconds=4, rate=30, audio=True) -> None:
    argv = [K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d:duration=%d" % (size, rate, seconds)]
    if audio:
        argv += ["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=%d" % seconds, "-c:a", "aac"]
    argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
             "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(path)]
    subprocess.run(argv, check=True, timeout=120)


def box(kind: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def fake_mp4(order=(b"ftyp", b"moov", b"mdat")) -> bytes:
    """The top-level boxes of an MP4 with no real media: what the host's own checks read."""
    return b"".join(box(k, b"isom\x00\x00\x02\x00" if k == b"ftyp" else b"x" * 24) for k in order)


def run_with_mp4(world, folder, data, render=b"a finished render", claimed_sha=None, **result):
    """A container that writes `preview.mp4` (these bytes) and a result that says what it wants; returns the host's answer."""
    body = {"ok": True, "sha256": claimed_sha or hashlib.sha256(data).hexdigest(), "from_sha256": hashlib.sha256(render).hexdigest(),
            "bytes": len(data), "width": 720, "height": 1280, "duration": 4.0, "has_audio": True, "video_kbps": 2500, "audio_kbps": 96, "seconds": 1.0}
    body.update(result)
    world.cfg.update(run="files", files={"result.json": {"kind": "text", "text": json.dumps(body)}, "preview.mp4": {"kind": "bytes", "hex": data.hex()}})
    world.save()
    folder.mkdir(exist_ok=True)
    src = folder / "render.mp4"
    src.write_bytes(render)
    return world.host("preview", "--in", src, "--out", folder / "out")


def probe(path) -> list:
    return subprocess.run([K.FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True, timeout=60).stdout.strip().split(",")


# ---------------------------------------------------------------- the rate and the command

def test_the_rate_fits_the_cap_from_the_renders_length():
    assert _media.preview_rate(60, SPEC, True) == 1843
    assert _media.preview_rate(300, SPEC, True) == 296
    assert _media.preview_rate(10, SPEC, True) == 2500
    assert _media.preview_rate(400, SPEC, True) is None
    assert _media.preview_rate(60, SPEC, False) == 1939
    for t in range(1, 302):
        rate = _media.preview_rate(t, SPEC, True)
        assert (rate * 1000 + 96000) * (t + 1) / 8 <= SPEC["max_bytes"], t


def test_the_preview_command_is_pinned_like_the_final_encode():
    argv = _media.preview_argv("ffmpeg", "in.mp4", "out.mp4", SPEC, video_kbps=1843, has_audio=True)
    at = argv.index("-i")
    assert argv[at - len(_media.RECORDING_IN):at] == list(_media.RECORDING_IN)
    assert argv[argv.index("-threads") + 1] == "1" and argv.index("-threads") < at

    def after(flag):
        return argv[argv.index(flag) + 1]
    assert after("-filter_threads") == "1"
    assert after("-x264-params") == "threads=1:lookahead_threads=1:sliced-threads=0"
    assert after("-maxrate") == "1843k" and after("-bufsize") == "1843k"
    assert after("-crf") == "23" and after("-preset") == "medium"
    assert after("-vf") == "scale=720:1280:flags=lanczos+accurate_rnd+bitexact,format=yuv420p," + _media.TAGS
    assert after("-b:a") == "96k" and after("-map_metadata") == "-1" and after("-movflags") == "+faststart"
    assert argv[-1] == "out.mp4"
    silent = _media.preview_argv("ffmpeg", "in.mp4", "out.mp4", SPEC, video_kbps=1843, has_audio=False)
    assert "-an" in silent and "-c:a" not in silent


# ---------------------------------------------------------------- the container's verb

@needs_media
def test_a_preview_is_720_by_1280_under_the_cap_with_a_closed_result_and_the_same_bytes_twice(tmp_path):
    src = tmp_path / "render.mp4"
    pattern(src, "1080x1920", seconds=4)
    out = tmp_path / "p.mp4"
    rc, result, err = K.run_verb("preview", "--in", src, "--sha256", sha(src), "--out", out)
    assert rc == 0, err
    assert set(result) == KEYS
    assert (result["width"], result["height"]) == (720, 1280) and result["has_audio"] is True
    assert result["audio_kbps"] == 96 and result["video_kbps"] == 2500 and result["from_sha256"] == sha(src)
    assert result["bytes"] == out.stat().st_size <= CAP and result["sha256"] == sha(out)
    assert stat.S_IMODE(out.stat().st_mode) == 0o600 and _media.faststart(str(out))
    assert not any(p.name.startswith(".preview-") for p in tmp_path.iterdir())
    again = K.run_verb("preview", "--in", src, "--sha256", sha(src), "--out", tmp_path / "again.mp4")
    assert again[0] == 0 and again[1]["sha256"] == result["sha256"]
    assert probe(out) == ["720", "1280"]


@needs_media
def test_a_render_with_no_audio_has_a_preview_with_no_audio(tmp_path):
    src = tmp_path / "render.mp4"
    pattern(src, "1080x1920", seconds=3, audio=False)
    rc, result, err = K.run_verb("preview", "--in", src, "--sha256", sha(src), "--out", tmp_path / "p.mp4")
    assert rc == 0, err
    assert result["has_audio"] is False and result["audio_kbps"] == 0


@needs_media
def test_a_render_whose_hash_is_not_the_one_named_is_not_decoded(tmp_path):
    src = tmp_path / "render.mp4"
    pattern(src, "1080x1920", seconds=2)
    out = tmp_path / "p.mp4"
    rc, result, err = K.run_verb("preview", "--in", src, "--sha256", "ab" * 32, "--out", out)
    assert rc == 1 and err.startswith("refused: render_differs render") and not out.exists()


# ---------------------------------------------------------------- the host side, through the fake docker

def test_the_host_stores_a_preview_content_addressed_read_only_and_never_rewrites_it(world, tmp_path):
    data = fake_mp4()
    render = b"a finished render"
    rc, out, err = run_with_mp4(world, tmp_path / "w", data)
    assert rc == 0, err
    assert out["name"] == "preview-%s.mp4" % sha(data)[:12]
    stored = tmp_path / "w" / "out" / out["name"]
    assert stat.S_IMODE(stored.stat().st_mode) == 0o400 and stored.read_bytes() == data
    assert out["replayed"] is False and set(out) == KEYS | {"path", "name", "replayed", "image"}
    run = world.runs()[0]["argv"]
    assert run[run.index("--network") + 1] == "none" and [run[i + 1] for i, a in enumerate(run) if a == "-v"][0] == "%s:/in/recording:ro" % (tmp_path / "w" / "render.mp4")
    for item in ("preview", "--sha256", sha(render), "--out", "/out/preview.mp4"):
        assert item in run, item
    assert [p.name for p in (tmp_path / "w" / "out").iterdir()] == [out["name"]]
    again = world.host("preview", "--in", tmp_path / "w" / "render.mp4", "--out", tmp_path / "w" / "out")
    assert again[0] == 0 and again[1]["replayed"] is True
    work = world.state / "renderer" / "work"
    assert not [p for p in work.iterdir() if p.name.startswith(D.JOB_PREFIX)]
    other = tmp_path / "other"
    other.mkdir()
    (other / out["name"]).write_bytes(b"not the same")
    rc, out2, err = world.host("preview", "--in", tmp_path / "w" / "render.mp4", "--out", other)
    assert rc == 1 and err.startswith("refused: name_collision") and (other / out["name"]).read_bytes() == b"not the same"


def test_the_host_hashes_the_render_itself_when_no_hash_is_given_and_refuses_a_bad_one(world, tmp_path):
    rc, out, err = run_with_mp4(world, tmp_path / "w", fake_mp4())
    assert rc == 0 and out["from_sha256"] == sha(b"a finished render"), err           # no --sha256 was given: the file's own was used
    before = len(world.runs())
    rc, out, err = world.host("preview", "--in", tmp_path / "w" / "render.mp4", "--sha256", "XYZ", "--out", tmp_path / "o")
    assert rc == 2 and len(world.runs()) == before


@pytest.mark.parametrize("over", [{"from_sha256": "cd" * 32}, {"bytes": 1}, {"width": 1080}, {"height": 1920}])
def test_a_container_that_names_another_render_or_lies_about_the_file_is_refused(world, tmp_path, over):
    data = fake_mp4()
    if "bytes" in over:
        over = {"bytes": len(data) + 1}
    rc, out, err = run_with_mp4(world, tmp_path / "w", data, **over)
    assert rc == 1 and err.startswith("refused: container_result_invalid preview"), err
    assert not (tmp_path / "w" / "out").exists() or list((tmp_path / "w" / "out").iterdir()) == []


def test_a_container_that_claims_another_hash_than_the_file_it_wrote_is_refused(world, tmp_path):
    rc, out, err = run_with_mp4(world, tmp_path / "w", fake_mp4(), claimed_sha="ab" * 32)
    assert rc == 1 and err.startswith("refused: container_file_differs"), err
    assert not (tmp_path / "w" / "out").exists() or list((tmp_path / "w" / "out").iterdir()) == []


def test_a_file_that_is_not_an_mp4_with_its_index_first_is_refused_even_when_the_hash_matches(world, tmp_path):
    for n, data in enumerate((fake_mp4((b"ftyp", b"mdat", b"moov")), fake_mp4((b"moov", b"ftyp", b"mdat")), b"<html>" + b"x" * 40)):
        rc, out, err = run_with_mp4(world, tmp_path / ("w%d" % n), data)
        assert rc == 1 and err.startswith("refused: container_result_invalid preview"), err
        assert not (tmp_path / ("w%d" % n) / "out").exists() or list((tmp_path / ("w%d" % n) / "out").iterdir()) == []


def test_a_preview_larger_than_the_cap_is_refused(world, tmp_path):
    rc, out, err = run_with_mp4(world, tmp_path / "w", fake_mp4() + b"x" * CAP)
    assert rc == 1 and err.startswith("refused: container_file_"), err
    assert not (tmp_path / "w" / "out").exists() or list((tmp_path / "w" / "out").iterdir()) == []


def test_a_refusal_inside_the_container_is_the_same_refusal_outside(world, tmp_path):
    world.cfg.update(run="files", rc=1, files={"result.json": {"kind": "text", "text": json.dumps({"ok": False, "code": "preview_too_long", "field": "render", "problems": []})}})
    world.save()
    src = tmp_path / "render.mp4"
    src.write_bytes(b"x")
    rc, out, err = world.host("preview", "--in", src, "--out", tmp_path / "out")
    assert rc == 1 and err.startswith("refused: preview_too_long render") and out["code"] == "preview_too_long"


def test_a_render_that_is_a_link_or_a_folder_is_not_mounted(world, tmp_path):
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "link.mp4"
    os.symlink(real, link)
    for bad in (link, tmp_path, tmp_path / "missing.mp4"):
        rc, out, err = world.host("preview", "--in", bad, "--sha256", "ab" * 32, "--out", tmp_path / "o")
        assert rc == 1 and err.startswith("refused: input_unreadable recording"), (bad, err)
    assert world.runs() == []


# ---------------------------------------------------------------- the verb's place

def test_the_preview_verb_is_common_to_both_engines_and_listed_by_the_contract():
    import ffmpeg
    import hyperframes as H
    assert _host.COMMON_HANDLERS["preview"] is _host.verb_preview
    assert ffmpeg.VERBS["preview"] is _host.verb_preview and H.VERBS["preview"] is _host.verb_preview
    contract = (K.REPO / "providers" / "CONTRACT.md").read_text()
    assert "`preview --in <mp4> [--sha256 <hex>] --out <dir>`" in contract and "preview-<sha12>.mp4" in contract
    assert D.RESULT_SCHEMAS["preview"][1].keys() == KEYS


def test_the_presets_preview_block_and_the_runtimes_limit_agree():
    assert set(SPEC) == {"note", "width", "height", "crf", "preset", "max_bytes", "margin", "audio_kbps", "max_video_kbps", "min_video_kbps",
                         "duration_tolerance_seconds", "encode_seconds", "time_limit_seconds"}
    assert SPEC["max_bytes"] == 15 * 1024 * 1024
    assert SPEC["time_limit_seconds"] - SPEC["encode_seconds"] >= 60
    assert "PREVIEW_MAX_BYTES = 15 << 20" in (K.REPO / "runtime" / "deliver_document.py").read_text()

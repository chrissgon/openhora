"""The still frame (`still`): one PNG of a recording at a time, framed exactly as the render frames it into 1080x1920, so that a
face box drawn on it is the face box the render uses. The container verb runs on the host here (ffmpeg only, no browser); the
host side runs against the fake docker. Every recording is a synthetic test pattern."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

import renderer_kit as K
import docker_kit as DK
import _docker as D
import _media

needs_media = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def world(tmp_path):
    (tmp_path / "home").mkdir()
    return DK.World(tmp_path)


def pattern(path, size="1920x1080", seconds=4, rate=30, audio=True) -> None:
    argv = [K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=%d:duration=%d" % (size, rate, seconds)]
    if audio:
        argv += ["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=%d" % seconds, "-c:a", "aac"]
    argv += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
             "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(path)]
    subprocess.run(argv, check=True, timeout=120)


def raw_rgb(path, first_frame_of=None) -> bytes:
    done = subprocess.run([K.FFMPEG, "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=60)
    return done.stdout


def mean_abs_diff(a: bytes, b: bytes) -> float:
    assert len(a) == len(b)
    return sum(abs(x - y) for x, y in zip(a[::97], b[::97])) / len(a[::97])


# ---------------------------------------------------------------- the container's verb

@needs_media
@pytest.mark.parametrize("size", ["1920x1080", "1080x1920", "3840x2160"])
def test_a_still_is_a_1080_by_1920_png_whatever_the_recordings_shape_with_a_closed_result(tmp_path, size):
    src = tmp_path / "rec.mp4"
    pattern(src, size, seconds=3)
    out = tmp_path / "still.png"
    rc, result, err = K.run_verb("still", "--in", src, "--at-ms", "1500", "--out", out)
    assert rc == 0, err
    data = out.read_bytes()
    assert data[:8] == PNG_MAGIC and stat.S_IMODE(out.stat().st_mode) == 0o600
    assert set(result) == {"ok", "at_ms", "sha256", "width", "height", "bytes"}
    assert (result["width"], result["height"], result["at_ms"], result["bytes"]) == (1080, 1920, 1500, len(data))
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    assert not any(p.name.startswith(".still-") for p in tmp_path.iterdir())          # the work folder is gone
    assert K.run_verb("still", "--in", src, "--at-ms", "1500", "--out", tmp_path / "again.png")[1]["sha256"] == result["sha256"]   # the same bytes every time
    assert subprocess.run([K.FFPROBE, "-v", "error", "-show_entries", "stream=width,height,pix_fmt", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.split(",")[:2] == ["1080", "1920"]


@needs_media
def test_a_still_has_the_pixels_the_renders_own_graph_gives_an_unzoomed_range_of_the_same_recording(tmp_path):
    """The face box is placed on the still and read by the render: the still of frame N is the render's first picture of a range
    that starts at frame N, drawn at zoom 1, within what H.264 loses. A landscape recording makes the crop matter."""
    src = tmp_path / "wide.mp4"
    pattern(src, "1920x1080", seconds=4, audio=False)
    frame = 45                                                   # 1.5 s at 30 fps
    still = tmp_path / "still.png"
    rc, result, err = K.run_verb("still", "--in", src, "--at-ms", str(int(frame / 30 * 1000)), "--out", still)
    assert rc == 0, err
    plan = {"zoom": {"mode": "none", "factor": 1.1, "push_in": 0.0}, "face": {"cx": 540, "cy": 600, "w": 300, "h": 400}, "anchor": (540.0, 500.0),
            "fade": 0.015, "src": str(src), "fps": 30, "size": [1080, 1920], "has_audio": False, "src_matrix": "bt709", "kept": [[frame, frame + 8]],
            "layers": [], "frames_dir": "frames", "pips": [], "pip_size": 380, "out_frames": 8, "max_bytes": 50_000_000, "out_name": "out.mp4"}
    _media.run(_media.compose_argv(K.FFMPEG, plan), 120, cwd=str(tmp_path))
    render_frame = raw_rgb(tmp_path / "out.mp4")
    still_frame = raw_rgb(still)
    assert len(still_frame) == 1080 * 1920 * 3 and mean_abs_diff(render_frame, still_frame) < 1.0   # measured 0.21; a picture at another time differs by 4.6
    # a different time is a different picture: the offset is read, not ignored
    other = tmp_path / "other.png"
    assert K.run_verb("still", "--in", src, "--at-ms", "3000", "--out", other)[0] == 0
    assert mean_abs_diff(raw_rgb(other), render_frame) > 10 * mean_abs_diff(render_frame, still_frame)


@needs_media
def test_the_still_reads_the_recording_under_the_same_input_rules_as_every_other_read():
    argv = _media.still_argv("ffmpeg", "/in/recording", 1.5, (1080, 1920), "bt709", "still.png")
    at = argv.index("-i")
    assert argv[at - 6:at] == ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file"] and argv[at + 1] == "/in/recording"
    assert "-ss" in argv[:at] and argv[argv.index("-frames:v") + 1] == "1" and "-an" in argv and "-map_metadata" in argv
    assert _media.framing_filter(1080, 1920, "bt709") in argv[argv.index("-vf") + 1]            # the render's own framing text


@needs_media
def test_an_offset_outside_the_recording_a_bad_number_or_a_recording_that_is_too_long_is_refused(tmp_path):
    src = tmp_path / "rec.mp4"
    pattern(src, seconds=2)
    for offset in ("2000", "999999", "-5"):
        rc, out, err = K.run_verb("still", "--in", src, "--at-ms", offset, "--out", tmp_path / "x.png")
        assert rc == 1 and err.startswith("refused: bad_still_offset at-ms") and not (tmp_path / "x.png").exists(), offset
    assert K.run_verb("still", "--in", src, "--at-ms", "abc", "--out", tmp_path / "x.png")[0] == 2
    rc, out, err = K.run_verb("still", "--in", tmp_path / "missing.mp4", "--at-ms", "0", "--out", tmp_path / "x.png")
    assert rc == 1 and not (tmp_path / "x.png").exists()


@needs_media
def test_a_file_that_is_not_a_mov_family_recording_is_not_decoded(tmp_path):
    odd = tmp_path / "odd.mp4"
    odd.write_bytes(b"not a recording at all" * 50)
    rc, out, err = K.run_verb("still", "--in", odd, "--at-ms", "0", "--out", tmp_path / "x.png")
    assert rc == 1 and not (tmp_path / "x.png").exists() and "Traceback" not in err


# ---------------------------------------------------------------- the host side, through the fake docker

@needs_media
def test_the_host_stores_a_still_content_addressed_read_only_and_never_rewrites_it(world, tmp_path):
    src = tmp_path / "rec.mp4"
    pattern(src, seconds=3)
    out_dir = tmp_path / "out"
    before = len(world.runs())
    rc, out, err = world.host("still", "--in", src, "--at-ms", "1500", "--out", out_dir)
    assert rc == 0, err
    path = Path(out["path"])
    assert path.parent == out_dir and path.name == "still-%s.png" % out["sha256"][:12] == out["name"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o400 and path.read_bytes()[:8] == PNG_MAGIC and hashlib.sha256(path.read_bytes()).hexdigest() == out["sha256"]
    assert (out["width"], out["height"], out["at_ms"], out["bytes"], out["replayed"]) == (1080, 1920, 1500, path.stat().st_size, False)
    assert out["image"]["id"] == "sha256:" + "cd" * 32 and set(out) == {"ok", "at_ms", "sha256", "width", "height", "bytes", "path", "name", "replayed", "image"}
    run = world.runs()[before]["argv"]
    assert run[run.index("--network") + 1] == "none" and [run[i + 1] for i, a in enumerate(run) if a == "-v"][0] == "%s:/in/recording:ro" % src
    assert [p.name for p in out_dir.iterdir()] == [path.name]                                    # no candidate, no temporary name left
    again = world.host("still", "--in", src, "--at-ms", "1500", "--out", out_dir)
    assert again[0] == 0 and again[1]["sha256"] == out["sha256"] and again[1]["replayed"] is True
    work = world.state / "renderer" / "work"
    assert not [p for p in work.iterdir() if p.name.startswith(D.JOB_PREFIX)]
    # a file of that name with other bytes is refused and left alone
    other = tmp_path / "other"
    other.mkdir()
    (other / path.name).write_bytes(b"not the same")
    rc, out2, err = world.host("still", "--in", src, "--at-ms", "1500", "--out", other)
    assert rc == 1 and err.startswith("refused: name_collision") and (other / path.name).read_bytes() == b"not the same"


def test_a_recording_that_is_a_link_or_a_folder_or_has_a_colon_in_its_path_is_not_mounted_for_a_still(world, tmp_path):
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "link.mp4"
    os.symlink(real, link)
    for bad in (link, tmp_path, tmp_path / "missing.mp4"):
        rc, out, err = world.host("still", "--in", bad, "--at-ms", "0", "--out", tmp_path / "o")
        assert rc == 1 and err.startswith("refused: input_unreadable recording"), (bad, err)
    odd = tmp_path / "a:b.mp4"
    odd.write_bytes(b"x")
    rc, out, err = world.host("still", "--in", odd, "--at-ms", "0", "--out", tmp_path / "o")
    assert rc == 2 and err.startswith("refused: bad_mount_path")
    assert world.runs() == [] and not (tmp_path / "o").exists()
    assert world.host("still", "--in", real, "--at-ms", "-1", "--out", tmp_path / "o")[0] == 2


def png_header(w=1080, h=1920) -> bytes:
    import struct
    import zlib
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return PNG_MAGIC + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF)


def run_with_png(world, folder: Path, png: bytes, claimed_sha=None, **result):
    """A container that writes `still.png` (these bytes) and a result that says what it wants; returns the host's answer."""
    body = {"ok": True, "at_ms": 0, "sha256": claimed_sha or hashlib.sha256(png).hexdigest(), "width": 1080, "height": 1920, "bytes": len(png)}
    body.update(result)
    world.cfg.update(run="files", files={"result.json": {"kind": "text", "text": json.dumps(body)}, "still.png": {"kind": "bytes", "hex": png.hex()}})
    world.save()
    folder.mkdir(exist_ok=True)
    src = folder / "rec.mp4"
    src.write_bytes(b"x")
    return world.host("still", "--in", src, "--at-ms", "0", "--out", folder / "out")


def test_a_container_that_claims_another_hash_than_the_file_it_wrote_is_refused_and_nothing_is_stored(world, tmp_path):
    rc, out, err = run_with_png(world, tmp_path / "w", png_header() + b"x" * 40, claimed_sha="ab" * 32)
    assert rc == 1 and err.startswith("refused: container_file_differs") and not (tmp_path / "w" / "out").exists()


def test_a_still_that_is_not_a_png_of_the_frame_size_is_refused_even_when_the_hash_matches(world, tmp_path):
    for png in (b"GIF89a" + b"x" * 60, png_header(100, 100) + b"x" * 40, b"<html>" + b"x" * 40):
        rc, out, err = run_with_png(world, tmp_path / "w", png)
        assert rc == 1 and err.startswith("refused: container_result_invalid still"), err
        assert not (tmp_path / "w" / "out").exists() or list((tmp_path / "out").iterdir()) == []


def test_a_still_larger_than_the_cap_is_refused(world, tmp_path):
    rc, out, err = run_with_png(world, tmp_path / "w", png_header() + b"x" * (8 * 1024 * 1024))
    assert rc == 1 and err.startswith("refused: container_file_not_regular") and not (tmp_path / "w" / "out").exists()


def test_a_result_with_other_fields_or_a_wrong_type_is_rebuilt_from_the_closed_schema(world, tmp_path):
    png = png_header() + b"x" * 40
    rc, out, err = run_with_png(world, tmp_path / "w", png, extra="a word of the transcript")
    assert rc == 0 and "extra" not in out, err
    rc, out, err = run_with_png(world, tmp_path / "v", png, at_ms="soon")
    assert rc == 1 and err.startswith("refused: container_result_invalid")


def test_a_refusal_inside_the_container_is_the_same_refusal_outside(world, tmp_path):
    world.cfg.update(run="files", rc=1, files={"result.json": {"kind": "text", "text": json.dumps({"ok": False, "code": "bad_still_offset", "field": "at-ms", "problems": []})}})
    world.save()
    src = tmp_path / "rec.mp4"
    src.write_bytes(b"x")
    rc, out, err = world.host("still", "--in", src, "--at-ms", "999999", "--out", tmp_path / "out")
    assert rc == 1 and err.startswith("refused: bad_still_offset at-ms") and out["code"] == "bad_still_offset" and not (tmp_path / "w" / "out").exists()


def test_the_still_verb_is_listed_by_the_providers_contract_and_the_modules_that_name_it_agree():
    contract = (K.REPO / "providers" / "CONTRACT.md").read_text()
    assert "`still --in <video> --at-ms <n> --out <dir>`" in contract and "still-<sha12>.png" in contract
    assert "still" in D.RESULT_SCHEMAS and D.RESULT_SCHEMAS["still"][1].keys() == {"ok": 0, "at_ms": 0, "sha256": 0, "width": 0, "height": 0, "bytes": 0}.keys()


def test_a_container_whose_account_differs_from_the_request_or_the_file_is_refused(world, tmp_path):
    png = png_header() + b"x" * 40
    for name, over in (("at", {"at_ms": 5}), ("bytes", {"bytes": len(png) + 1})):
        rc, out, err = run_with_png(world, tmp_path / name, png, **over)
        assert rc == 1 and err.startswith("refused: container_result_invalid still"), (name, err)
        assert not (tmp_path / name / "out").exists()

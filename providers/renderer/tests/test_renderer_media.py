"""ffprobe and ffmpeg: the facts of a recording, the argv of the render (golden files), and the platform's video spec."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile

import pytest

import renderer_kit as K
import _media
from _text import Refusal

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
FACE = {"cx": 540, "cy": 900, "w": 600, "h": 560}
needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
INSTAGRAM = json.loads(K.INSTAGRAM.read_text())


def plain_plan():
    return {"src": "/in/recording", "fps": 30, "size": [1080, 1920], "has_audio": True, "src_matrix": "bt709", "kept": [[25, 94], [121, 226], [249, 306]],
            "layers": ["beat", "caption"], "frames_dir": "frames", "pips": [], "pip_size": 380, "out_frames": 231, "max_bytes": 300000000,
            "out_name": "out.mp4", "zoom": {"mode": "alternate", "factor": 1.1, "push_in": 0.02, "anchor_y": 0.25}, "face": FACE, "anchor": (540.0, 760.0), "fade": 0.015}


def pip_plan():
    p = plain_plan()
    p.update(has_audio=False, src_matrix="auto", layers=["caption"], zoom={"mode": "alternate", "factor": 1.25, "push_in": 0.03, "anchor_y": 0.25},
             pips=[{"asset": "assets/beat8.png", "kind": "png", "start_frame": 60, "end_frame": 120, "x": 350, "y": 285},
                   {"asset": "assets/beat9.jpg", "kind": "jpg", "start_frame": 150, "end_frame": 200, "x": 350, "y": 868}])
    return p


@pytest.mark.parametrize("name, make", [("compose-plain", plain_plan), ("compose-pip", pip_plan)])
def test_a_resolved_plan_gives_exactly_this_argv(name, make):
    argv = _media.compose_argv("/usr/bin/ffmpeg", make())
    path = os.path.join(GOLDEN, name + ".json")
    if os.environ.get("UPDATE_GOLDEN") == "1":
        with open(path, "w") as fh:
            json.dump(argv, fh, indent=1)
            fh.write("\n")
    assert argv == json.load(open(path))


def test_the_encoder_thread_count_is_pinned_so_the_bytes_do_not_depend_on_the_machine():
    """x264's output depends on its thread count, and its automatic count follows the cores the machine shows: a pinned count is what
    makes the same render the same bytes on another machine (measured: identical under a 4 and an 8 CPU limit)."""
    for make in (plain_plan, pip_plan):
        argv = _media.compose_argv("ffmpeg", make())
        i = argv.index("libx264")
        assert argv[i + 1:i + 3] == ["-threads", "4"] and argv.count("-threads") == 1


def test_the_recording_is_always_read_as_mov_with_a_file_whitelist_and_the_render_is_capped():
    for make in (plain_plan, pip_plan):
        argv = _media.compose_argv("ffmpeg", make())
        i = argv.index("-i")
        assert argv[i - 6:i] == ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file"]
        assert argv[argv.index("-fs") + 1] == "300000000"
        assert "-shell" not in argv and all(isinstance(a, str) for a in argv)
    cover = _media.cover_argv("ffmpeg", "/in/recording", 1.5, "cover.png")
    assert cover[cover.index("-i") - 6:cover.index("-i")] == ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file"]


def test_no_path_is_inside_the_filter_graph_and_every_asset_is_read_with_its_forced_demuxer():
    argv = _media.compose_argv("ffmpeg", pip_plan())
    graph = argv[argv.index("-filter_complex") + 1]
    for needle in ("assets/", "/in/recording", ".png", ".jpg", "frames/"):
        assert needle not in graph, needle
    assert argv[argv.index("png_pipe") - 1] == "-f" and argv[argv.index("png_pipe") + 1:argv.index("png_pipe") + 3] == ["-c:v", "png"]
    assert argv[argv.index("jpeg_pipe") + 1:argv.index("jpeg_pipe") + 3] == ["-c:v", "mjpeg"]
    assert argv[argv.index("-map_metadata") + 1] == "-1"                 # nothing of the recording's metadata (a location) is kept


def test_the_render_is_tagged_bt709_and_composed_in_rgb():
    graph = _media.compose_argv("ffmpeg", plain_plan())
    graph = graph[graph.index("-filter_complex") + 1]
    assert "out_color_matrix=bt709" in graph and "format=gbrp" in graph and "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv" in graph


# ---------------------------------------------------------------- probe

def make(tmp, name, args, size="320x568"):
    path = os.path.join(tmp, name)
    subprocess.run([K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", *args, path], check=True, timeout=120)
    return path


V = ["-f", "lavfi", "-i", "testsrc2=size=320x568:rate=30:duration=1"]
A = ["-f", "lavfi", "-i", "sine=frequency=220:duration=1"]


@needs_ffmpeg
def test_the_facts_of_a_recording_and_the_refusals(tmp_path):
    tmp = str(tmp_path)
    ok = make(tmp, "ok.mp4", [*V, *A, "-c:v", "libx264", "-c:a", "aac", "-shortest"])
    facts = _media.probe(K.FFPROBE, ok)
    assert (facts["width"], facts["height"], facts["codec"], facts["has_audio"]) == (320, 568, "h264", True)
    two_v = make(tmp, "two-v.mov", [*V, *V, "-map", "0:v", "-map", "1:v", "-c:v", "libx264"])
    two_a = make(tmp, "two-a.mov", [*V, *A, *A, "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "libx264", "-c:a", "aac", "-shortest"])
    for path, code in ((two_v, "video_streams"), (two_a, "audio_streams")):
        with pytest.raises(Refusal) as e:
            _media.probe(K.FFPROBE, path)
        assert e.value.code == code
    vp9 = make(tmp, "mpeg4.mov", [*V, "-c:v", "mpeg4"])
    with pytest.raises(Refusal) as e:
        _media.probe(K.FFPROBE, vp9)
    assert e.value.code == "video_codec"
    with pytest.raises(Refusal):                                          # a file that is not a mov or mp4 at all
        _media.probe(K.FFPROBE, str(tmp_path / "nope.txt"))


@needs_ffmpeg
def test_data_streams_of_an_iphone_mov_are_ignored_and_a_subtitle_stream_is_not(tmp_path):
    tmp = str(tmp_path)
    tc = make(tmp, "tc.mov", [*V, *A, "-c:v", "libx264", "-c:a", "aac", "-shortest", "-timecode", "01:00:00:00"])
    kinds = json.loads(subprocess.run([K.FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", tc], capture_output=True, text=True).stdout)
    assert "data" in [s["codec_type"] for s in kinds["streams"]]           # the fixture really carries a data stream
    assert _media.probe(K.FFPROBE, tc)["has_audio"] is True
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:00,900\nhi\n")
    sub = make(tmp, "sub.mov", [*V, "-i", str(srt), "-map", "0:v", "-map", "1:0", "-c:v", "libx264", "-c:s", "mov_text"])
    with pytest.raises(Refusal) as e:
        _media.probe(K.FFPROBE, sub)
    assert e.value.code == "other_streams"


@needs_ffmpeg
def test_hdr_is_refused_and_a_4k_60fps_hevc_clip_is_read(tmp_path):
    tmp = str(tmp_path)
    hdr = make(tmp, "hdr.mov", [*V, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc", "-color_primaries", "bt2020"])
    with pytest.raises(Refusal) as e:
        _media.probe(K.FFPROBE, hdr)
    assert e.value.code == "hdr_input"
    big = make(tmp, "4k.mov", ["-f", "lavfi", "-i", "testsrc2=size=3840x2160:rate=60:duration=1", "-c:v", "libx265", "-preset", "ultrafast", "-tag:v", "hvc1",
                               "-pix_fmt", "yuv420p"])
    facts = _media.probe(K.FFPROBE, big)
    assert (facts["width"], facts["height"], facts["codec"], round(facts["fps"])) == (3840, 2160, "hevc", 60)


@needs_ffmpeg
def test_silencedetect_finds_the_gaps_and_the_open_one_closes_at_the_end(tmp_path):
    tone = ["-f", "lavfi", "-i", "aevalsrc='between(t,0.5,1.0)*0.3*sin(2*PI*220*t)+between(t,2.0,2.5)*0.3*sin(2*PI*220*t)':s=48000:d=3"]
    path = make(str(tmp_path), "gaps.mp4", [*V[:3], "testsrc2=size=320x568:rate=30:duration=3", *tone, "-c:v", "libx264", "-c:a", "aac", "-shortest"])
    out = _media.silencedetect(K.FFMPEG, path, 3.0, -35, 0.3)
    assert len(out) == 3 and out[0]["start"] == 0 and out[1]["start"] == pytest.approx(1.0, abs=0.1) and out[2]["end"] == pytest.approx(3.0, abs=0.1)


# ---------------------------------------------------------------- the platform's video spec

@needs_ffmpeg
def test_the_output_is_checked_against_the_platform_file_and_each_failure_has_a_code(tmp_path):
    tmp = str(tmp_path)
    good = make(tmp, "good.mp4", ["-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=4", *A[:3], "sine=frequency=220:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                                   "-c:a", "aac", "-shortest", "-movflags", "+faststart"])
    assert _media.check_output(K.FFPROBE, good, INSTAGRAM)["failures"] == []
    assert _media.faststart(good)
    slow = make(tmp, "slow.mp4", ["-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=15:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    assert "fps_min" in _media.check_output(K.FFPROBE, slow, INSTAGRAM)["failures"]
    late = make(tmp, "late.mp4", ["-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    assert "faststart" in _media.check_output(K.FFPROBE, late, INSTAGRAM)["failures"] and not _media.faststart(late)
    tight = json.loads(json.dumps(INSTAGRAM))
    tight["video"].update(max_seconds=2, max_width=720, codecs=["h265"], audio_codecs=["opus"], max_bytes=1000)
    failures = _media.check_output(K.FFPROBE, good, tight)["failures"]
    assert {"max_seconds", "max_width", "codec", "audio_codec", "max_bytes"} <= set(failures)
    assert _media.byte_limit(INSTAGRAM) == 300000000 and _media.byte_limit(tight) == 1000


def test_top_level_boxes_are_read_in_order(tmp_path):
    p = tmp_path / "x.mp4"
    p.write_bytes((24).to_bytes(4, "big") + b"ftyp" + b"\0" * 16 + (16).to_bytes(4, "big") + b"moov" + b"\0" * 8 + (16).to_bytes(4, "big") + b"mdat" + b"\0" * 8)
    assert _media.top_level_boxes(str(p)) == ["ftyp", "moov", "mdat"] and _media.faststart(str(p))


def test_a_command_past_its_time_limit_is_killed_with_its_group(tmp_path):
    marker = tmp_path / "alive"
    with pytest.raises(Refusal) as e:
        _media.run(["/bin/sh", "-c", "sleep 30 & echo $! > %s; wait" % marker], 1)  # security-scan: allow shell-string -- a fixed test command: a sleep, its pid in a temporary file
    assert e.value.code == "time_limit"
    pid = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)

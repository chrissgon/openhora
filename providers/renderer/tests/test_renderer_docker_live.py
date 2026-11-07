"""The ffmpeg engine in a real container: the image `build --confirmed` made, no network, no mock. Gated: the tests run only with

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/renderer/tests/test_renderer_docker_live.py

and they never build: the CI job builds the image first (OPENHORA_STATE_DIR=<folder> python3 providers/renderer/ffmpeg.py build --confirmed
--platform linux64, the same folder as the pytest command) and these tests use what it left. The recording is made by the image's own ffmpeg from a generated test card and a generated tone, the transcript is a
synthetic one of fictional words, and the verbs the other tests drive through the fake docker (`analyse`, `base`, `align`, `render`) are
driven through the real one. Everything the renderer starts carries the label org.openhora.renderer and is removed by name.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import renderer_kit as K
import _docker as D
import _host

pytestmark = pytest.mark.skipif(os.environ.get("WB_RENDERER_DOCKER_TESTS") != "1",
                                reason="a real container: set WB_RENDERER_DOCKER_TESTS=1 (the renderer image must be built first)")

# The state folder the build wrote its record into, named by OPENHORA_STATE_DIR. Only that variable is read, at collection: the root
# conftest replaces XDG_STATE_HOME with a temporary folder before this module is imported, so it cannot name the build's folder.
REAL_STATE_DIR = os.environ.get("OPENHORA_STATE_DIR")
HOST = str(K.HOST)


@pytest.fixture
def real_state(monkeypatch):
    if not REAL_STATE_DIR:
        pytest.fail("the build and the tests must share one OPENHORA_STATE_DIR: set it to the same folder for %s and for pytest "
                    "(the root conftest replaces XDG_STATE_HOME, so that variable cannot carry it)" % "`OPENHORA_STATE_DIR=<folder> python3 providers/renderer/ffmpeg.py build --confirmed --platform linux64`")
    monkeypatch.setenv("OPENHORA_STATE_DIR", REAL_STATE_DIR)


@pytest.fixture
def image(real_state):
    return D.check_image()


def host(*args, timeout=1500):
    """The provider's host side, as a person runs it: (returncode, parsed stdout or None, stderr)."""
    done = subprocess.run([sys.executable, HOST, *map(str, args)], capture_output=True, text=True, timeout=timeout)
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stderr


def in_image(image, args, folder, mode="rw", entrypoint="ffmpeg"):
    """One command of the image's own tools, with no network, on a folder mounted at /out."""
    argv = ["docker", "run", "--rm", "--network", "none", "--entrypoint", entrypoint, "-v", "%s:/out:%s" % (folder, mode)]
    if sys.platform.startswith("linux"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    done = subprocess.run([*argv, image["id"], *args], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout


def leftovers():
    done = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "label=org.openhora.renderer=1"], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.split()


def test_the_host_check_finds_docker_local_the_image_unchanged_and_its_tools_starting(real_state):
    rc, out, err = host("--check", timeout=300)
    assert rc == 0, err
    assert out["ok"] is True and out["image"]["tag"] == D.image_tag() and out["image"]["id"].startswith("sha256:")
    assert out["selfcheck"]["ffmpeg"].startswith("ffmpeg") and out["selfcheck"]["browser"]
    assert leftovers() == []


def test_a_synthetic_recording_is_cut_captioned_and_composed_in_real_containers_and_leaves_none(image, tmp_path):
    transcript = K.build_transcript(K.SHORT_SENTENCES)
    folder = tmp_path / "media"
    folder.mkdir()
    in_image(image, ["-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=%.3f" % transcript["duration"],
                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=%.3f" % transcript["duration"],
                     "-vf", "format=yuv420p", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "16",
                     "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                     "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "/out/in.mp4"], folder)
    in_image(image, ["-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x14213D:size=1080x1920:rate=1",
                     "-frames:v", "1", "/out/asset.png"], folder)
    recording, asset = folder / "in.mp4", folder / "asset.png"
    assert recording.stat().st_size > 0 and asset.stat().st_size > 0
    (tmp_path / "post.md").write_text(K.SHORT_POST, encoding="utf-8")
    transcript_file = K.write_json(tmp_path / "transcript.json", transcript)

    assert host("analyse", "--in", recording, "--out", tmp_path / "analysis.json")[0] == 0
    rc, out, err = host("base", "--transcript", transcript_file, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json")
    assert rc == 0, err
    rc, out, err = host("align", "--post", tmp_path / "post.md", "--transcript", transcript_file, "--checker", K.CHECKER,
                        "--vocabulary", K.VOCABULARY, "--out", tmp_path / "beats.json")
    assert rc == 0, err
    rc, out, err = host("render", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", recording, "--out", tmp_path / "out",
                        "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY, "--asset", "3=%s" % asset, "--asset", "4=%s" % asset,
                        "--jobs", "2")
    assert rc == 0, err[-2000:]
    rendered = Path(out["path"])
    assert rendered.is_file() and rendered.suffix == ".mp4" and rendered.name == "render-%s.mp4" % out["sha256"][:12]
    assert (out["output"]["width"], out["output"]["height"]) == (1080, 1920) and out["verified"] is True

    probe = in_image(image, ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", "/out/" + rendered.name],
                     rendered.parent, mode="ro", entrypoint="ffprobe")
    stream = json.loads(probe)["streams"][0]
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert leftovers() == []


# ---------------------------------------------------------------- the two-stage encode and the proxy (V3a-1)


def require_prores(image, folder):
    """The two-stage encode needs `prores_ks` in the image's ffmpeg: a fact about the image, so its absence is a failure, not a skip."""
    encoders = in_image(image, ["-hide_banner", "-encoders"], folder, mode="ro")
    if " prores_ks " not in encoders:
        pytest.fail("the image's ffmpeg has no prores_ks encoder: the HyperFrames engine's intermediate cannot be made or tested")


def job_args(cpus, cpuset=None):
    return argparse.Namespace(memory_mb=D.DEFAULT_MEMORY_MB, cpus=cpus, scratch_mb=512, timeout=None, cpuset=cpuset)


def short_edl(image, tmp_path, size="1080x1920", sentences=((0.4, "Short test line."),)):
    """A recording of about three seconds made by the image's ffmpeg from a test card and a tone, and the edit list the host's own
    `analyse` and `base` verbs make for it: (recording, edit list file, edit list)."""
    transcript = K.build_transcript(list(sentences), tail=0.4)
    folder = tmp_path / "media"
    folder.mkdir()
    in_image(image, ["-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=%s:rate=30:duration=%.3f" % (size, transcript["duration"]),
                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=%.3f" % transcript["duration"],
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "16",
                     "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                     "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "/out/in.mp4"], folder)
    recording = folder / "in.mp4"
    assert host("analyse", "--in", recording, "--out", tmp_path / "analysis.json")[0] == 0
    rc, out, err = host("base", "--transcript", K.write_json(tmp_path / "transcript.json", transcript), "--analysis", tmp_path / "analysis.json",
                        "--out", tmp_path / "edl.json")
    assert rc == 0, err
    return recording, tmp_path / "edl.json", json.loads((tmp_path / "edl.json").read_text())


def encode_once(image, edl_file, intermediate, digest, cpus, dest, cpuset=None):
    """The `encode` verb in a container with `cpus` cores, as the HyperFrames engine will run it; returns the result and the file it wrote."""
    with _host.Job(job_args(cpus, cpuset), 600, "encode") as job:
        result = job.run(["encode", "--in", job.mount_recording(str(intermediate)), "--sha256", digest, "--edl", job.stage("edl.json", str(edl_file)),
                          "--platform-file", job.stage("platform.json", str(K.INSTAGRAM)), "--out", D.MOUNT_OUT], "encode")
        job.collect("render-%s.mp4" % result["sha256"][:12], str(dest), max_bytes=D.MAX_OUT_BYTES, mode=0o400, expect_sha256=result["sha256"])
    return result


def streams_report(image, path):
    """Where two outputs differ, if they do: for each stream the packet count and a hash of the packets' own checksums (`-c copy`, so what
    the encoder wrote, not what a decoder makes of it), and the same for the decoded frames."""
    import hashlib
    report = {}
    for stream, name in (("0:v:0", "video"), ("0:a:0", "audio")):
        for mode, extra in (("packets", ["-c", "copy"]), ("decoded", [])):
            text = in_image(image, ["-v", "error", "-i", "/out/" + Path(path).name, "-map", stream, *extra, "-f", "framemd5", "-"], Path(path).parent, mode="ro")
            lines = [x for x in text.splitlines() if x and not x.startswith("#")]
            report["%s %s" % (name, mode)] = {"count": len(lines), "hash": hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16],
                                             "first": lines[0] if lines else "", "last": lines[-1] if lines else ""}
    return report


def test_the_two_stage_encode_gives_one_sha256_at_two_and_four_cpus(image, tmp_path):
    require_prores(image, tmp_path)
    minimum = json.loads(K.INSTAGRAM.read_text())["video"]["min_seconds"]     # the encode refuses an output the platform would refuse
    recording, edl_file, edl = short_edl(image, tmp_path, sentences=((0.4, "Short test line."), (0.4, "A second short line follows here.")))
    assert edl["out_frames"] / float(edl["fps"]) >= minimum + 0.5, "the leg's edit list is shorter than the platform's minimum"
    work = tmp_path / "work"
    work.mkdir()
    seconds = edl["out_frames"] / float(edl["fps"])
    in_image(image, ["-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=%d:duration=%.6f" % (edl["fps"], seconds),
                     "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=%.6f" % seconds,
                     "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", "-c:a", "pcm_s16le", "/out/hf.mov"], work)
    intermediate = work / "hf.mov"
    digest = _sha256(intermediate)
    # --cpus is a quota (the container still sees every core); the cpu set is what changes the cores it sees, which is what 4 against 8
    # cores meant in S2. The two vary together, in turn, from one intermediate.
    settings = [(2, "0-1"), (4, "0-3"), (4, "0-1"), (2, "0-3")] * 2
    runs = []
    for n, (cpus, cpuset) in enumerate(settings):
        dest = tmp_path / ("render-%d.mp4" % n)
        result = encode_once(image, edl_file, intermediate, digest, cpus, dest, cpuset)
        assert result["intermediate_sha256"] == digest and _sha256(dest) == result["sha256"]
        runs.append((cpus, cpuset, dest, result["sha256"]))
    if len({r[3] for r in runs}) != 1:
        first = runs[0]
        other = next(r for r in runs if r[3] != first[3])
        report = {"cpus %s cpuset %s" % (r[0], r[1]): streams_report(image, r[2]) for r in (first, other)}
        pytest.fail("the encode is not independent of the cpu count: %s" % json.dumps({"sha256": [r[3] for r in runs], "streams": report}, indent=1))
    render = runs[0][2]
    rc, out, err = host("verify", "--in", render, "--platform-file", K.INSTAGRAM, "--edl", edl_file)
    assert rc == 0 and out["ok"] is True, err[-2000:]
    assert leftovers() == []


def test_the_proxy_is_1080x1920_at_the_edit_lists_fps(image, tmp_path):
    recording, edl_file, edl = short_edl(image, tmp_path, size="1920x1080")
    with _host.Job(job_args(2), 600, "proxy") as job:
        result = job.run(["proxy", "--edl", job.stage("edl.json", str(edl_file)), "--in", job.mount_recording(str(recording)),
                          "--out", D.MOUNT_OUT + "/proxy.mp4"], "proxy")
        job.collect("proxy.mp4", str(tmp_path / "proxy.mp4"), max_bytes=D.MAX_OUT_BYTES, mode=0o400)
    assert (result["width"], result["height"], result["fps"]) == (1080, 1920, edl["fps"]) and result["has_audio"] is True
    probe = in_image(image, ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate:format=duration", "-of", "json",
                             "/out/proxy.mp4"], tmp_path, mode="ro", entrypoint="ffprobe")
    info = json.loads(probe)
    assert (info["streams"][0]["width"], info["streams"][0]["height"]) == (1080, 1920) and info["streams"][0]["avg_frame_rate"] == "%d/1" % edl["fps"]
    assert abs(float(info["format"]["duration"]) - edl["source"]["duration"]) <= 2.0 / edl["fps"]
    assert leftovers() == []


def _sha256(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

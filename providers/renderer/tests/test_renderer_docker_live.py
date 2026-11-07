"""The ffmpeg engine in a real container: the image `build --confirmed` made, no network, no mock. Gated: the tests run only with

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest providers/renderer/tests/test_renderer_docker_live.py

and they never build: the CI job builds the image first (OPENHORA_STATE_DIR=<folder> python3 providers/renderer/ffmpeg.py build --confirmed
--platform linux64, the same folder as the pytest command) and these tests use what it left. The recording is made by the image's own ffmpeg from a generated test card and a generated tone, the transcript is a
synthetic one of fictional words, and the verbs the other tests drive through the fake docker (`analyse`, `base`, `align`, `render`) are
driven through the real one. Everything the renderer starts carries the label org.openhora.renderer and is removed by name.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import renderer_kit as K
import _docker as D

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

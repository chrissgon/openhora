"""The HyperFrames engine in real containers (V3a-2): both images built here and recorded, no network, no mock. Gated by its own variable,
which CI sets only in the job that builds the HyperFrames image (V3c-2). The composed render and the planted blocks of this engine are tested
by the engine contract's one live file (`test_engine_contract_live.py`, V3c-1), for both engines; this file keeps the base-only render at
4 and at 8 cores, which needs the machine's 8 cores:

    OPENHORA_STATE_DIR=<folder> WB_HYPERFRAMES_DOCKER_TESTS=1 uv run --with pytest==9.1.1 pytest -q providers/renderer/tests/test_hf_docker_live.py

with no `-n`: it needs the machine to itself. The tests never build: the person builds the two images first, into the same folder
(`OPENHORA_STATE_DIR=<folder> python3 providers/renderer/ffmpeg.py build --confirmed`, then the same with `providers/renderer/hyperframes.py`)
and these tests use what the builds left. The recording is made by the common image's own ffmpeg from a generated test card and a generated
tone; the words are the kit's fictional ones.
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
import hyperframes as H

pytestmark = pytest.mark.skipif(os.environ.get("WB_HYPERFRAMES_DOCKER_TESTS") != "1",
                                reason="real containers: set WB_HYPERFRAMES_DOCKER_TESTS=1 (the common image and the HyperFrames image must be built and recorded first)")

REAL_STATE_DIR = os.environ.get("OPENHORA_STATE_DIR")
HF_HOST = str(K.RENDERER / "hyperframes.py")
MIN_CPUS = 8


@pytest.fixture
def real_state(monkeypatch):
    if not REAL_STATE_DIR:
        pytest.fail("the builds and the tests must share one OPENHORA_STATE_DIR: set it to the same folder for the two `build --confirmed` commands and for pytest")
    monkeypatch.setenv("OPENHORA_STATE_DIR", REAL_STATE_DIR)


@pytest.fixture
def images(real_state):
    """Both images, as the provider would find them: built from the current definitions and recorded. Not being so is a failure, not a skip."""
    try:
        return D.check_image(), H.check_hf_image()
    except D.NotConfigured as err:
        pytest.fail("an image is not ready (%s %s): build both, see the top of this file" % (err.code, err.field))


@pytest.fixture
def eight_cpus(real_state):
    done = subprocess.run(["docker", "info", "--format", "{{.NCPU}}"], capture_output=True, text=True, timeout=60)
    if done.returncode != 0 or not done.stdout.strip().isdigit() or int(done.stdout) < MIN_CPUS:
        pytest.skip("the docker daemon has fewer than %d CPUs (%s): the second run needs cores 0-7" % (MIN_CPUS, done.stdout.strip() or "unknown"))


def host(*args, timeout=2400, env=None):
    done = subprocess.run([sys.executable, HF_HOST, *map(str, args)], capture_output=True, text=True, timeout=timeout, env=env)
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stderr


def ffmpeg_host(*args, timeout=900):
    done = subprocess.run([sys.executable, str(K.HOST), *map(str, args)], capture_output=True, text=True, timeout=timeout)
    return done.returncode, (json.loads(done.stdout) if done.stdout.strip() else None), done.stderr


def in_image(image, args, folder):
    argv = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "ffmpeg", "-v", "%s:/out:rw" % folder]
    if sys.platform.startswith("linux"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    done = subprocess.run([*argv, image["id"], *args], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-2000:]


def leftovers():
    found = []
    for label in ("org.openhora.renderer=1", "org.openhora.renderer-hyperframes=1"):
        done = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "label=" + label], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        found += done.stdout.split()
    return found


def run_folders():
    return [p.name for p in Path(D.work_root()).iterdir() if p.name.startswith(H.RUN_PREFIX)]


def test_the_same_recording_gives_one_final_sha256_at_four_and_at_eight_cpus_and_leaves_nothing(images, eight_cpus, tmp_path):
    common = images[0]
    transcript = K.build_transcript(K.SHORT_SENTENCES)
    media = tmp_path / "media"
    media.mkdir()
    in_image(common, ["-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=%.3f" % transcript["duration"],
                      "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=%.3f" % transcript["duration"],
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "16",
                      "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                      "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", "/out/in.mp4"], media)
    recording = media / "in.mp4"
    (tmp_path / "post.md").write_text(K.SHORT_POST, encoding="utf-8")
    transcript_file = K.write_json(tmp_path / "transcript.json", transcript)
    assert host("analyse", "--in", recording, "--out", tmp_path / "analysis.json")[0] == 0
    rc, out, err = host("base", "--transcript", transcript_file, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json")
    assert rc == 0, err
    rc, out, err = host("align", "--post", tmp_path / "post.md", "--transcript", transcript_file, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY,
                        "--out", tmp_path / "beats.json")
    assert rc == 0, err
    shas = {}
    for cpus, cpuset in ((4, "0-3"), (8, "0-7")):
        rc, out, err = host("render", "--base-only", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", recording,
                            "--out", tmp_path / ("out%d" % cpus), "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY,
                            "--cpus", cpus, "--cpuset", cpuset)
        assert rc == 0, err[-2000:]
        assert out["engine"] == "hyperframes" and out["verified"] is True and out["layers"] == ["cuts", "zoom"]
        assert Path(out["path"]).is_file() and out["intermediate_bytes"] > 0 and set(out["stage_seconds"]) == {"page", "proxy", "hf", "encode"}
        shas[cpus] = out["sha256"]
        assert leftovers() == [] and run_folders() == []
    assert shas[4] == shas[8]
    rc, out, err = ffmpeg_host("verify", "--in", next((tmp_path / "out4").glob("render-*.mp4")), "--platform-file", K.INSTAGRAM, "--edl", tmp_path / "edl.json")
    assert rc == 0 and out["ok"] is True, err[-2000:]

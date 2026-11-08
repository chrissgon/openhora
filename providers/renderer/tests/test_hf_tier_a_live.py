"""Step 7.8, the dynamic run of tier A, in real containers (the supervisor runs it; no network, nothing downloaded, nothing added to the allowlist).

    OPENHORA_STATE_DIR=<folder> WB_HYPERFRAMES_DOCKER_TESTS=1 \
    WB_TIER_A_SURVEY=<the survey folder: <component>/<file>> WB_TIER_A_REPORT=<compat-report.json> WB_TIER_A_OUT=<the dynamic report to write> \
    uv run --with pytest==9.1.1 pytest -q providers/renderer/tests/test_hf_tier_a_live.py

with no `-n`. `WB_TIER_A_ONLY=name,name` limits the candidates. Test 1 draws each `admit-candidate` of the report on one keyword beat of the synthetic
recording (the component as a test allowlist entry, its files mounted from the survey over the image's registry folder, every file checked by the report's
sha256), twice, through both gates, and writes the verdict (`fit` or `refuse:<code>`). Test 2 draws a planted run-time escape that the text lint admits
and the guard stops, through the full render path, and asserts that the render is refused `block_escaped`. Both write the one closed report. A refused
candidate is a result, not a test failure."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import renderer_kit as K
import tier_a_kit as T
import _docker as D
import hyperframes as H

pytestmark = pytest.mark.skipif(os.environ.get("WB_HYPERFRAMES_DOCKER_TESTS") != "1",
                                reason="real containers: set WB_HYPERFRAMES_DOCKER_TESTS=1 (both images built and recorded first), see the top of this file")
HF_HOST = str(K.RENDERER / "hyperframes.py")


def need(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail("set %s (see the top of this file)" % name)
    return value


@pytest.fixture
def images(monkeypatch):
    monkeypatch.setenv("OPENHORA_STATE_DIR", need("OPENHORA_STATE_DIR"))
    try:
        return D.check_image(), H.check_hf_image()
    except D.NotConfigured as err:
        pytest.fail("an image is not ready (%s %s): build both first" % (err.code, err.field))


@pytest.fixture
def four_cpus(images):
    done = subprocess.run(["docker", "info", "--format", "{{.NCPU}}"], capture_output=True, text=True, timeout=60)
    if done.returncode != 0 or not done.stdout.strip().isdigit() or int(done.stdout) < 4:
        pytest.skip("the docker daemon has fewer than 4 CPUs")


def host(*args, env=None, timeout=2400):
    done = subprocess.run([sys.executable, HF_HOST, *map(str, args)], capture_output=True, text=True, timeout=timeout, env=env)
    try:
        out = json.loads(done.stdout) if done.stdout.strip() else None
    except ValueError:
        out = None
    return done.returncode, out, done.stderr


def leftovers():
    found = []
    for label in ("org.openhora.renderer=1", "org.openhora.renderer-hyperframes=1"):
        done = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "label=" + label], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        found += done.stdout.split()
    return found


def run_folders():
    return [p.name for p in Path(D.work_root()).iterdir() if p.name.startswith(H.RUN_PREFIX)]


def prepare(images, tmp_path):
    """The synthetic recording (made by the common image's own ffmpeg), its edit list and its beats (the kit's fictional post: a keyword, a number,
    a list and a quote)."""
    transcript = K.build_transcript(K.SHORT_SENTENCES)
    media = tmp_path / "media"
    media.mkdir()
    argv = ["docker", "run", "--rm", "--network", "none", "--entrypoint", "ffmpeg", "-v", "%s:/out:rw" % media]
    if sys.platform.startswith("linux"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    done = subprocess.run([*argv, images[0]["id"], "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                           "testsrc2=size=1080x1920:rate=30:duration=%.3f" % transcript["duration"], "-f", "lavfi", "-i",
                           "sine=frequency=440:sample_rate=48000:duration=%.3f" % transcript["duration"], "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
                           "-crf", "16", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-c:a", "aac", "-b:a", "128k",
                           "-movflags", "+faststart", "/out/in.mp4"], capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-1500:]
    (tmp_path / "post.md").write_text(K.HF_POST, encoding="utf-8")
    transcript_file = K.write_json(tmp_path / "transcript.json", transcript)
    assert host("analyse", "--in", media / "in.mp4", "--out", tmp_path / "analysis.json")[0] == 0
    rc, out, err = host("base", "--transcript", transcript_file, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json")
    assert rc == 0, err
    rc, out, err = host("align", "--post", tmp_path / "post.md", "--transcript", transcript_file, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY,
                        "--out", tmp_path / "beats.json")
    assert rc == 0, err
    return media / "in.mp4"


def render(tmp_path, recording, blocks, registry, label):
    env = dict(os.environ, RENDERER_TEST="1", RENDERER_BLOCKS_DIR=blocks, RENDERER_REGISTRY_DIR=registry)
    rc, out, err = host("render", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", recording, "--out", tmp_path / ("out-" + label),
                        "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY, "--cpus", 4, "--cpuset", "0-3", env=env)
    return rc, out, err


def test_each_admit_candidate_is_drawn_twice_through_the_gates_and_gets_a_verdict(images, four_cpus, tmp_path):
    report = json.loads(Path(need("WB_TIER_A_REPORT")).read_text(encoding="utf-8"))
    survey, out_path = need("WB_TIER_A_SURVEY"), need("WB_TIER_A_OUT")
    only = [n for n in os.environ.get("WB_TIER_A_ONLY", "").split(",") if n]
    comps = [c for c in report["components"] if c["verdict"] == "admit-candidate" and (not only or c["name"] in only)]
    assert comps, "the report has no admit-candidate (or WB_TIER_A_ONLY names none)"
    recording = prepare(images, tmp_path)
    rows = []
    for comp in comps:
        blocks = T.blocks_folder(tmp_path, comp)
        registry = T.registry_folder(tmp_path, survey, [comp])
        runs = []
        for label in ("a", "b"):
            rc, out, err = render(tmp_path, recording, blocks, registry, comp["name"] + label)
            runs.append((rc, out))
            if rc != 0:
                break
        rows.append(T.candidate_row(comp, runs))
        T.update_report(out_path, candidates=rows)
        assert leftovers() == [] and run_folders() == []
        print("%s: %s" % (comp["name"], rows[-1]["dynamic"]))
    assert len(rows) == len(comps) and all(r["dynamic"] for r in rows)


def test_a_planted_escape_the_lint_admits_is_refused_block_escaped_by_the_full_render_path(images, four_cpus, tmp_path):
    out_path = need("WB_TIER_A_OUT")
    recording = prepare(images, tmp_path)
    comp = T.planted_component()
    blocks = T.blocks_folder(tmp_path, comp)
    registry = T.registry_folder(tmp_path, T.planted_survey(tmp_path), [comp])
    rc, out, err = render(tmp_path, recording, blocks, registry, "planted")
    assert rc == 1 and out["code"] == "block_escaped" and out["field"].startswith("frame "), (out, err[-2000:])
    assert not (tmp_path / "out-planted").exists() or list((tmp_path / "out-planted").iterdir()) == []
    assert leftovers() == [] and run_folders() == []
    T.update_report(out_path, planted={"name": T.PLANTED_NAME, "code": out["code"], "field": out["field"]})

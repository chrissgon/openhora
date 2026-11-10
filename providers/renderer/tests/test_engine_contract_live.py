"""The engine contract (V3c) in real containers: the same synthetic inputs through both renderer engines, the same assertions. Never builds, no
network, no real recording: the recordings are test patterns that the common image's own ffmpeg makes, each carrying its own frame number as a
band of black and white cells at the top of the picture (contract_kit), so what every output frame is can be read from the pixels.

Gated by the variable of each image, as the other live files are (the parameter of an engine is skipped without its variable):

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 [WB_HYPERFRAMES_DOCKER_TESTS=1] \\
    uv run --with pytest==9.1.1 pytest -q providers/renderer/tests/test_engine_contract_live.py

with no `-n`. The builds come first, into the same folder (the `build` verb of each host, the common image first).

Two kinds of leg. The functional legs (F1-F8, short inputs) run in CI's docker jobs and on the Mac. The machine legs (M1-M3, `test_mac_*`) need
8 cores, a long run or the real size, so they run only with `WB_ENGINE_MAC_LEGS=1` (the maintainer's machine), one after another, and write the
committed report when `WB_ENGINE_REPORT=<a new file>` is set (a file that exists is refused):

    ... WB_ENGINE_MAC_LEGS=1 WB_ENGINE_REPORT=<folder>/engine-contract-<date>-<arch>.json pytest -q <this file> -k mac_

Memory in the report is what `docker stats` reports once a second (usage less the inactive file cache on cgroup v2) and the OOM kills `docker
events` counts; the HyperFrames drawing container's `memory.peak` is the render's own figure and counts page cache.
"""
from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

import renderer_kit as K
import contract_kit as C
import _docker as D
import _host
import _media
import hyperframes as H

FFMPEG_ON = os.environ.get("WB_RENDERER_DOCKER_TESTS") == "1"
HF_ON = os.environ.get("WB_HYPERFRAMES_DOCKER_TESTS") == "1"
MAC_ON = os.environ.get("WB_ENGINE_MAC_LEGS") == "1"
REPORT_PATH = os.environ.get("WB_ENGINE_REPORT")
REAL_STATE_DIR = os.environ.get("OPENHORA_STATE_DIR")
HOSTS = {"ffmpeg": str(K.HOST), "hyperframes": str(K.RENDERER / "hyperframes.py")}
ENV_VARIABLE = {"ffmpeg": "WB_RENDERER_DOCKER_TESTS", "hyperframes": "WB_HYPERFRAMES_DOCKER_TESTS"}
CAPS = {"ffmpeg": FFMPEG_ON, "hyperframes": HF_ON}
LABELS = ("org.openhora.renderer=1", "org.openhora.renderer-hyperframes=1")
SAMPLED_CAP_MIB = 5530                          # 90 percent of the 6144 MiB memory limit: stop rule 4
LIMIT_CODES = ("render_timeout", "no_space", "intermediate_too_large")
LIVE_LEGS = {}                                  # leg name -> the engines it runs on (the offline test reads it)
BOTH = ("ffmpeg", "hyperframes")


def legs(name: str, engines=BOTH):
    """The parametrisation of one leg over its engines; an engine is skipped without its image's variable."""
    LIVE_LEGS[name] = tuple(engines)
    params = [pytest.param(e, marks=pytest.mark.skipif(not CAPS[e], reason="real containers: set %s=1 (the images must be built and recorded first)" % ENV_VARIABLE[e]))
              for e in engines]
    return pytest.mark.parametrize("engine", params)


mac_only = pytest.mark.skipif(not MAC_ON, reason="a machine leg: set WB_ENGINE_MAC_LEGS=1 (8 cores, hours, the maintainer's machine)")


# ---------------------------------------------------------------- docker and the host's verbs

def parse(text: str):
    try:
        return json.loads(text) if text.strip() else None
    except ValueError:
        return None


def host(engine, *args, timeout=2400, env=None):
    done = subprocess.run([sys.executable, HOSTS[engine], *map(str, args)], capture_output=True, text=True, timeout=timeout, env=env)
    return done.returncode, parse(done.stdout), done.stderr


def code_of(out, err: str):
    """The closed code of a refusal: from the JSON the host printed, else from the first line of its stderr (`refused: <code> <field>`)."""
    if isinstance(out, dict) and isinstance(out.get("code"), str):
        return out["code"]
    m = re.match(r"refused: (\S+)", err or "")
    return m.group(1) if m else None


def in_image(image, args, folder, mode="rw", entrypoint="ffmpeg", timeout=1800):
    """One command of the image's own tools, with no network, on a folder mounted at /out. Returns its stdout."""
    argv = ["docker", "run", "--rm", "--network", "none", "--entrypoint", entrypoint, "-v", "%s:/out:%s" % (folder, mode)]
    if sys.platform.startswith("linux"):
        argv += ["--user", "%d:%d" % (os.getuid(), os.getgid())]
    done = subprocess.run([*argv, image["id"], *args], capture_output=True, text=True, timeout=timeout)
    assert done.returncode == 0, done.stderr[-2000:]
    return done.stdout


def docker_info(fmt: str) -> str:
    done = subprocess.run(["docker", "info", "--format", fmt], capture_output=True, text=True, timeout=60)
    return done.stdout.strip() if done.returncode == 0 else ""


def leftovers():
    found = []
    for label in LABELS:
        done = subprocess.run(["docker", "ps", "-a", "-q", "--filter", "label=" + label], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, done.stderr
        found += done.stdout.split()
    return found


def run_folders():
    root = Path(D.work_root())
    return [p.name for p in root.iterdir() if p.name.startswith(H.RUN_PREFIX)] if root.is_dir() else []


def assert_clean(out_dir=None, passed=False):
    """C11: a refusal leaves nothing (no file in its out folder, no container, no run folder); every run, passed or not, leaves no container and no run folder."""
    if not passed and out_dir is not None:
        assert not Path(out_dir).exists() or list(Path(out_dir).iterdir()) == [], "a refused render left files in %s" % out_dir
    assert leftovers() == [] and run_folders() == []


# ---------------------------------------------------------------- the lab: images, recordings, documents, renders

@pytest.fixture(autouse=True)
def real_state(monkeypatch):
    """A conftest fixture of function scope points OPENHORA_STATE_DIR at a temporary folder before every test, so the person's folder is put back here,
    for every test (the variable is read at import, above, and never inside a function: inside one it would be that temporary folder). A
    module-scoped fixture cannot do this: the lab and its host subprocesses read the state during the test, not when the lab is made."""
    if not REAL_STATE_DIR:
        pytest.fail("the builds and the tests must share one OPENHORA_STATE_DIR: set it to the same folder for the two image builds and for pytest")
    monkeypatch.setenv("OPENHORA_STATE_DIR", REAL_STATE_DIR)


def fresh(path: Path) -> Path:
    """An empty folder at `path`: what a failed earlier attempt left there is removed, so one failure reports itself once and does not cascade."""
    if path.exists():
        shutil.rmtree(str(path))
    path.mkdir(parents=True)
    return path


class Render:
    def __init__(self, rc, out, err, wall, out_dir, seconds_started, memory=None):
        self.rc, self.out, self.err, self.wall, self.out_dir = rc, out, err, wall, out_dir
        self.code = None if rc == 0 else code_of(out, err)
        self.memory = memory


class Lab:
    """The images found, a folder, and what the legs share: recordings (made once each), documents (made by the host's verbs), renders (cached by tag)."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.common = D.check_image()
        self.hf = None
        self.cache = {}
        self.counter = 0
        self.blocks_hf = folder / "blocks-hf"
        shutil.copytree(K.BLOCKS, self.blocks_hf)
        K.write_hf_compose_blocks(self.blocks_hf)
        self.platform = json.loads(K.INSTAGRAM.read_text())

    def need(self, engine):
        """The engine's images, or a failure (an image that is not ready is a failure, not a skip)."""
        if engine == "hyperframes" and self.hf is None:
            try:
                self.hf = H.check_hf_image()
            except D.NotConfigured as err:
                pytest.fail("the HyperFrames image is not ready (%s %s): build both images first, see the top of this file" % (err.code, err.field))
        return self

    def cached(self, key, make):
        if key not in self.cache:
            self.cache[key] = make()
        return self.cache[key]

    def runner(self, mode="ro"):
        return lambda args, folder: in_image(self.common, args, folder, mode=mode)

    def recording(self, name: str, transcript: dict) -> Path:
        def make():
            folder = fresh(self.folder / ("media-" + name))
            in_image(self.common, C.source_args(transcript, "/out/in.mp4"), folder)
            assert (folder / "in.mp4").stat().st_size > 0
            return folder / "in.mp4"
        return self.cached(("recording", name), make)

    def long_recording(self) -> Path:
        def make():
            folder = fresh(self.folder / "media-long")
            in_image(self.common, C.long_recording_args("/out/long.mp4"), folder)
            return folder / "long.mp4"
        return self.cached(("recording", "long"), make)

    def band(self, path: Path) -> list:
        """The frame number of every frame of a video, read from its band, by one command in the common image."""
        self.counter += 1
        folder = fresh(self.folder / ("band-%d" % self.counter))
        shutil.copy(str(path), str(folder / "v.mp4"))
        in_image(self.common, C.band_read_args("/out/v.mp4", "/out/band.raw"), folder)
        return C.read_band((folder / "band.raw").read_bytes())

    def documents(self, name, recording: Path, transcript: dict, post: str, base_flags=()):
        """(edl file, beats file, edit list) made by the host's `analyse`, `base` and `align` on `recording`."""
        def make():
            d = fresh(self.folder / ("docs-" + name))
            (d / "post.md").write_text(post, encoding="utf-8")
            tfile = K.write_json(d / "transcript.json", transcript)
            assert host("ffmpeg", "analyse", "--in", recording, "--out", d / "analysis.json")[0] == 0
            rc, out, err = host("ffmpeg", "base", "--transcript", tfile, "--analysis", d / "analysis.json", "--out", d / "edl.json", *base_flags)
            assert rc == 0, err
            rc, out, err = host("ffmpeg", "align", "--post", d / "post.md", "--transcript", tfile, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY,
                                "--out", d / "beats.json")
            assert rc == 0, err
            return d / "edl.json", d / "beats.json", json.loads((d / "edl.json").read_text())
        return self.cached(("docs", name), make)

    def render(self, engine, tag, recording, edl, beats, cpus=4, cpuset="0-3", blocks=None, memory=False, timeout=3600, passed_ok=True):
        """One render through the engine's host, the way a person runs it. `blocks` is a test blocks folder (RENDERER_TEST=1); the HyperFrames
        engine otherwise draws from the oh: pages on the renderat runtime (the test folder of this lab). `memory` samples both containers and
        counts OOM kills. Leaves nothing: the run is checked clean before it returns."""
        self.need(engine)
        folder = blocks or (self.blocks_hf if engine == "hyperframes" else None)
        env = dict(os.environ)
        if folder is not None:
            env.update(RENDERER_TEST="1", RENDERER_BLOCKS_DIR=str(folder))
        out_dir = self.folder / ("out-" + tag)
        args = ["render", "--edl", edl, "--beats", beats, "--in", recording, "--out", out_dir, "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY,
                "--cpus", cpus, "--cpuset", cpuset]
        if engine == "ffmpeg":
            args += ["--jobs", 2]
        figures, started = None, time.monotonic()
        if memory:
            with C.Sampler() as sampler:
                rc, out, err = host(engine, *args, timeout=timeout, env=env)
            wall = time.monotonic() - started
            try:
                ooms = C.count_oom(subprocess.run, sampler.started, int(time.time()) + 1)
            except (RuntimeError, OSError, subprocess.SubprocessError):
                ooms = None
            figures = dict(sampler.figures(), oom_events=ooms)
        else:
            rc, out, err = host(engine, *args, timeout=timeout, env=env)
            wall = time.monotonic() - started
        result = Render(rc, out, err, wall, out_dir, started, figures)
        assert_clean(out_dir, passed=rc == 0)
        return result

    def f1(self, engine, label):
        """The F1 inputs through `engine` at the cpus of `label` (a: 4 cores, b: the same again, c: 2 cores), cached: F1, F3 and F8 share the renders."""
        settings = {"a": (4, "0-3"), "b": (4, "0-3"), "c": (2, "0-1")}[label]
        rec, edl, beats, doc = self.short()
        return self.cached(("f1", engine, label), lambda: self.render(engine, "f1-%s-%s" % (engine, label), rec, edl, beats, *settings))

    def short(self):
        """(recording, edl file, beats file, edit list) of the F1 inputs: the short case, the zoom of the base, the post of four overlays."""
        transcript = C.short_transcript()
        rec = self.recording("short", transcript)
        edl, beats, doc = self.documents("short", rec, transcript, K.HF_POST)
        return rec, edl, beats, doc

    def plain(self):
        """The F2 inputs: the same recording, no zoom and no push-in, beats with no overlay (captions only)."""
        transcript = C.short_transcript()
        rec = self.recording("short", transcript)
        edl, beats, doc = self.documents("plain", rec, transcript, C.PLAIN_POST, ("--zoom", "none", "--push-in", "0"))
        return rec, edl, beats, doc


LABS = []                                       # the one lab of the session: made inside the first test that needs it, with the person's state folder in place


@pytest.fixture
def lab(real_state, tmp_path_factory):
    if not LABS:
        LABS.append(Lab(tmp_path_factory.mktemp("engine-contract")))
    return LABS[0]


# ---------------------------------------------------------------- F1 shape

def check_shape(lab, engine, run, edl_doc):
    assert run.rc == 0, (run.out, run.err[-2000:])
    out = run.out
    assert out["verified"] is True
    path = Path(out["path"])
    assert path.is_file() and path.name == "render-%s.mp4" % out["sha256"][:12] and stat.S_IMODE(path.stat().st_mode) == 0o400
    o = out["output"]
    assert (o["width"], o["height"]) == (1080, 1920) and o["fps"] == edl_doc["fps"]
    assert int(o["frames"]) == edl_doc["out_frames"], (o["frames"], edl_doc["out_frames"])
    assert o["audio_codec"] == "aac"                                              # C3: the audio is kept
    assert o["color"] == ["bt709", "bt709", "bt709", "tv"] and o["faststart"] is True
    assert out["bytes"] <= _media.byte_limit(lab.platform)


@legs("F1")
def test_f1_the_output_is_named_by_its_hash_read_only_the_platforms_shape_and_has_audio(engine, lab):
    lab.need(engine)
    rec, edl, beats, doc = lab.short()
    run = lab.f1(engine, "a")
    check_shape(lab, engine, run, doc)
    out = run.out
    if engine == "hyperframes":                                                  # what the composed render of V3b-1 and V3b-2 asserted
        assert out["engine"] == "hyperframes" and out["layers"] == ["cuts", "zoom", "captions", "beats"]
        pins = C.pins_sha256(lab.blocks_hf)
        assert out["blocks_sha256"] == pins and out["beats_drawn"] == 4 and out["captions_drawn"] > 0 and set(out["runtimes"].values()) == {"renderat"}
        assert out["fonts_used"] == {"display": "inter-800.woff2", "mono": "jetbrains-mono-500.woff2", "text": "inter-500.woff2"}
        assert {"measure", "pixel"} <= set(out["stage_seconds"]) and out["gate"]["boxes"] > 0 and out["gate"]["frames"] == out["out_frames"]
        gate = out["gate"]
        assert gate["lowest_caption_bottom"] <= 1560 and gate["pixel_ranges"] > 0 and gate["pixel_min_psnr_db"] >= 33.0, gate


# ---------------------------------------------------------------- F2 frames

@legs("F2")
def test_f2_every_output_frame_is_the_source_frame_the_kept_ranges_name(engine, lab):
    lab.need(engine)
    rec, edl_file, beats, doc = lab.plain()
    source = lab.band(rec)
    assert len(source) >= int(doc["source"]["duration"] * doc["fps"]) - 1 and source == list(range(len(source))), "the band cannot be read from the source itself"
    run = lab.render(engine, "f2-" + engine, rec, edl_file, beats)
    check_shape(lab, engine, run, doc)
    got = lab.band(Path(run.out["path"]))
    verdict = C.compare_frames(doc, got)
    assert verdict["frames"] == doc["out_frames"] and verdict["bad"] == 0, "the edit list is not what is drawn on %s: %s" % (engine, verdict)


# ---------------------------------------------------------------- F3 repeat

@legs("F3")
def test_f3_the_same_input_gives_one_sha256_twice_and_at_two_cpus(engine, lab):
    lab.need(engine)
    runs = [lab.f1(engine, label) for label in ("a", "b", "c")]
    for run in runs:
        assert run.rc == 0, (run.out, run.err[-2000:])
    shas = [r.out["sha256"] for r in runs]
    if len(set(shas)) != 1:
        listed = [("cpus %s" % s, r.out_dir, Path(r.out["path"]).name, r.out["sha256"]) for s, r in zip(("4 a", "4 b", "2"), runs)]
        pytest.fail("the render is not independent of the cpu count: %s" % json.dumps(C.mismatch_report(lab.runner(), listed), indent=1))
    if engine == "hyperframes":
        gates = [r.out["gate"] for r in runs]
        assert gates[0] == gates[1] == gates[2], gates


# ---------------------------------------------------------------- F4 proxy

LIVE_LEGS["F4"] = ("ffmpeg",)


@pytest.mark.skipif(not FFMPEG_ON, reason="real containers: set WB_RENDERER_DOCKER_TESTS=1")
def test_f4_the_proxy_of_the_recording_is_one_sha256_at_two_and_at_four_cpus(lab):
    rec, edl_file, beats, doc = lab.short()
    shas = []
    for n, (cpus, cpuset) in enumerate([(2, "0-1"), (4, "0-3"), (2, "0-1"), (4, "0-3")]):
        args = argparse.Namespace(memory_mb=D.DEFAULT_MEMORY_MB, cpus=cpus, scratch_mb=512, timeout=None, cpuset=cpuset)
        dest = lab.folder / ("proxy-%d.mp4" % n)
        with _host.Job(args, 900, "proxy") as job:
            result = job.run(["proxy", "--edl", job.stage("edl.json", str(edl_file)), "--in", job.mount_recording(str(rec)), "--out", D.MOUNT_OUT + "/proxy.mp4"], "proxy")
            job.collect("proxy.mp4", str(dest), max_bytes=D.MAX_OUT_BYTES, mode=0o400, expect_sha256=result["sha256"])
        assert (result["width"], result["height"], result["fps"]) == (1080, 1920, doc["fps"]) and result["has_audio"] is True
        assert hashlib.sha256(dest.read_bytes()).hexdigest() == result["sha256"]
        shas.append(result["sha256"])
    assert len(set(shas)) == 1, "the proxy is not independent of the cpu count: %s" % shas
    assert leftovers() == []


# ---------------------------------------------------------------- F5, F6 planted blocks

def planted_leg(lab, engine, which, code):
    lab.need(engine)
    rec, edl, beats, doc = lab.short()
    folder = C.planted_renderat(lab.folder, which)
    run = lab.render(engine, "planted-%s-%s" % (which, engine), rec, edl, beats, blocks=folder)
    assert run.rc == 1 and run.code == code, (run.rc, run.out, run.err[-2000:])
    assert_clean(run.out_dir)


@legs("F5")
def test_f5_a_card_over_the_face_box_is_refused_and_leaves_nothing(engine, lab):
    planted_leg(lab, engine, "cover", "overlay_hits_face")


@legs("F6")
def test_f6_a_caption_below_the_line_at_1560_is_refused_and_leaves_nothing(engine, lab):
    planted_leg(lab, engine, "low", "caption_below_line")


# ---------------------------------------------------------------- F7 refusals

def refused_with(lab, engine, tag, recording, edl, beats, code, **kwargs):
    run = lab.render(engine, tag, recording, edl, beats, **kwargs)
    assert run.rc == 1 and run.code == code, "%s: wanted %s, got rc %s code %s (%s)" % (tag, code, run.rc, run.code, run.err[-800:])
    assert_clean(run.out_dir)
    return run.code


@legs("F7")
def test_f7_what_the_engine_cannot_draw_and_a_recording_that_is_not_the_list_are_refused_with_the_same_codes(engine, lab):
    lab.need(engine)
    rec, edl_file, beats_file, doc = lab.short()
    work = fresh(lab.folder / ("f7-" + engine))
    beats = json.loads(Path(beats_file).read_text())
    # (a) a block that is not in the catalogue
    unknown = copy.deepcopy(beats)
    unknown["overlays"][0]["block"] = "oh:nope"
    a = refused_with(lab, engine, "f7a-" + engine, rec, edl_file, K.write_json(work / "beats-a.json", unknown), "block_unknown")
    # (b) the recording of another transcript with this edit list
    other = lab.recording("other", K.build_transcript(K.SENTENCES[4:8]))
    b = refused_with(lab, engine, "f7b-" + engine, other, edl_file, beats_file, "recording_changed")
    # (c) a 301 s recording, the edit list's source naming it
    long = lab.long_recording()
    edl = json.loads(Path(edl_file).read_text())
    edl["source"].update(duration=301.0, sha256=hashlib.sha256(long.read_bytes()).hexdigest(), has_audio=True)
    c = refused_with(lab, engine, "f7c-" + engine, long, K.write_json(work / "edl-long.json", edl), beats_file, "input_too_long")
    assert (a, b, c) == ("block_unknown", "recording_changed", "input_too_long")       # the same three on both engines (stop rule 6)
    # (d) what only the other engine draws
    if engine == "ffmpeg":
        spring = copy.deepcopy(beats)
        spring["overlays"][0]["block"] = "hf:spring-pop"
        refused_with(lab, engine, "f7d-" + engine, rec, edl_file, K.write_json(work / "beats-d.json", spring), "block_not_on_engine")
    else:
        tr = C.short_transcript()
        (work / "post.md").write_text(K.SHORT_POST, encoding="utf-8")
        tfile = K.write_json(work / "transcript.json", tr)
        rc, out, err = host("ffmpeg", "align", "--post", work / "post.md", "--transcript", tfile, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", work / "beats-cutaway.json")
        assert rc == 0, err
        refused_with(lab, engine, "f7d-" + engine, rec, edl_file, work / "beats-cutaway.json", "preset_not_on_engine")


# ---------------------------------------------------------------- F8 glyphs (HyperFrames)

@legs("F8", ("hyperframes",))
def test_f8_a_caption_whose_words_draw_no_glyph_is_refused_and_the_clean_render_passes_the_rule(engine, lab):
    lab.need(engine)
    clean = lab.f1(engine, "a")
    assert clean.rc == 0 and clean.out["captions_drawn"] > 0 and clean.out["gate"]["lowest_caption_bottom"] is not None, (clean.out, clean.err[-1000:])
    rec, edl, beats, doc = lab.short()
    run = lab.render(engine, "f8-blank", rec, edl, beats, blocks=C.planted_blank(lab.folder))
    assert run.rc == 1 and run.code == "caption_not_drawn", (run.rc, run.out, run.err[-2000:])
    assert_clean(run.out_dir)


# ---------------------------------------------------------------- the machine legs (the maintainer's Mac)

ROWS = {}                                       # case -> {"transcript", "edl", "runs": [row]}; the report is built from it at the end of the session


@pytest.fixture
def eight_cpus(real_state):
    count = docker_info("{{.NCPU}}")
    if not count.isdigit() or int(count) < 8:
        pytest.skip("the docker daemon has fewer than 8 CPUs (%s): the machine legs need cores 0-7" % (count or "unknown"))


@pytest.fixture(scope="module", autouse=True)
def write_report():
    yield
    if not REPORT_PATH or not ROWS:
        return
    doc = build_report()
    C.check_report(doc)
    with open(REPORT_PATH, "x", encoding="utf-8") as fh:                     # an existing file is refused
        fh.write(json.dumps(doc, indent=1) + "\n")


def build_report() -> dict:
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(K.REPO), capture_output=True, text=True, timeout=60).stdout.strip()
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(docker_info("{{.Architecture}}") or platform.machine(), "unknown")
    memory = docker_info("{{.MemTotal}}")
    cases = [C.case_row(name, row["transcript"], row["edl"], row["runs"]) for name, row in ROWS.items()]
    versions = [r["hyperframes"] for row in ROWS.values() for r in row.get("results", []) if isinstance(r.get("hyperframes"), str)]
    return {"schema": 1, "date": datetime.date.today().isoformat(), "commit": commit, "arch": arch,
            "machine": {"docker_cpus": int(docker_info("{{.NCPU}}") or 0), "docker_memory_mib": int(memory) // (1 << 20) if memory.isdigit() else 0},
            "images": {"common": D.image_tag().split(":")[1], "hyperframes": H.hf_image.image_tag().split(":")[1]},
            "hyperframes_version": versions[0] if versions and C.VERSION.fullmatch(versions[0]) else None, "cases": cases}


def record(case, transcript, edl, engine, cpus, cpuset, run, frames_ok=None):
    row = ROWS.setdefault(case, {"transcript": transcript, "edl": edl, "runs": [], "results": []})
    row["runs"].append(C.run_row(engine, cpus, cpuset, run.out if run.rc == 0 else None, run.code, run.wall, run.memory, frames_ok))
    if run.rc == 0:
        row["results"].append(run.out)
    return row["runs"][-1]


def stop_on_limits(row, run):
    """Stop rule 4: a limit broken at real size, or sampled memory at 90 percent of a cap, is a stop with the figures."""
    memory = row["memory"] or {}
    sampled = [v for v in (memory.get("hf_sampled_max_mib"), memory.get("common_sampled_max_mib")) if v is not None]
    broke = []
    if run.code in LIMIT_CODES:
        broke.append("refused %s" % run.code)
    if memory.get("oom_events"):
        broke.append("%s OOM kills" % memory["oom_events"])
    if sampled and max(sampled) >= SAMPLED_CAP_MIB:
        broke.append("sampled memory %s MiB" % max(sampled))
    if broke:
        pytest.fail("STOP RULE 4, a limit broken at real size (%s): %s" % (", ".join(broke), json.dumps(row, sort_keys=True)))


def assert_one_sha(case, engine):
    shas = {r["sha256"] for r in ROWS[case]["runs"] if r["engine"] == engine and r["outcome"] == "ok"}
    assert len(shas) == 1, "STOP RULE 3, a nondeterminism on %s in the %s case: %s" % (engine, case, sorted(shas))


@mac_only
@legs("M1")
def test_mac_m1_the_short_case_composed_is_one_sha256_at_four_and_at_eight_cores(engine, lab, eight_cpus):
    lab.need(engine)
    rec, edl_file, beats, doc = lab.short()
    for cpus, cpuset in ((4, "0-3"), (8, "0-7")):
        run = lab.render(engine, "m1-%s-%d" % (engine, cpus), rec, edl_file, beats, cpus, cpuset, memory=True, timeout=7200)
        record("short", C.short_transcript(), doc, engine, cpus, cpuset, run)
        assert run.rc == 0, (run.out, run.err[-2000:])
    assert_one_sha("short", engine)


REAL = {}


def real_inputs(lab):
    """The real-size case of 5.3 with the F1 post: the recording, the documents (the base edit list keeps the real shape, zoom included)."""
    def make():
        transcript = C.real_size_transcript()
        rec = lab.recording("real", transcript)
        edl, beats, doc = lab.documents("real", rec, transcript, K.HF_POST)
        return transcript, rec, edl, beats, doc
    return lab.cached(("real",), make)


@mac_only
@legs("M2")
def test_mac_m2_the_real_size_case_composed_is_one_sha256_at_four_and_at_eight_cores_within_the_limits(engine, lab, eight_cpus):
    lab.need(engine)
    transcript, rec, edl_file, beats, doc = real_inputs(lab)
    assert 32 <= len(doc["kept"]) <= 40 and doc["proposals"] == []
    last = None
    for cpus, cpuset in ((4, "0-3"), (8, "0-7")):
        run = lab.render(engine, "m2-%s-%d" % (engine, cpus), rec, edl_file, beats, cpus, cpuset, memory=True, timeout=7200)
        frames_ok = None
        if run.rc == 0 and cpus == 8:                                                         # F2's check on the 8-core output
            verdict = C.compare_frames(doc, lab.band(Path(run.out["path"])), only_unzoomed=True)
            frames_ok = verdict["bad"] == 0 and verdict["checked"] > 0 and verdict["frames"] == doc["out_frames"]
            print("M2 %s frames: %s" % (engine, verdict))
            last = verdict
        row = record("real", transcript, doc, engine, cpus, cpuset, run, frames_ok)
        stop_on_limits(row, run)
        assert run.rc == 0, (run.code, run.out, run.err[-2000:])
        if engine == "hyperframes":
            print("M2 hyperframes %d cores: stages %s, hf cgroup peak %s MiB, sampled %s, intermediate %s bytes" % (
                cpus, row["stage_seconds"], (row["memory"] or {}).get("hf_cgroup_peak_mib"), row["memory"], run.out.get("intermediate_bytes")))
    assert_one_sha("real", engine)
    assert last is not None and last["bad"] == 0 and last["checked"] > 0 and last["frames"] == doc["out_frames"], \
        "STOP RULE 7, a frame the kept ranges do not name on %s: %s" % (engine, last)


@mac_only
@legs("M3", ("hyperframes",))
def test_mac_m3_the_300_second_input_is_drawn_once_by_hyperframes_at_eight_cores(engine, lab, eight_cpus):
    lab.need(engine)
    transcript = C.max_transcript()
    rec = lab.recording("max", transcript)
    edl_file, beats, doc = lab.documents("max", rec, transcript, K.HF_POST)
    assert 60 <= len(doc["kept"]) <= 80
    run = lab.render(engine, "m3-hf", rec, edl_file, beats, 8, "0-7", memory=True, timeout=7200)
    row = record("max", transcript, doc, engine, 8, "0-7", run)
    print("M3 hyperframes: outcome %s code %s wall %s s, stages %s, memory %s, intermediate %s bytes" % (
        row["outcome"], row["code"], row["wall_seconds"], row["stage_seconds"], row["memory"], (run.out or {}).get("intermediate_bytes") if run.rc == 0 else None))
    # A limit broken here is the finding (OPEN-9): the row is already in the report, the test fails with its figures (stop rule 4) and nothing is raised.
    stop_on_limits(row, run)
    assert run.rc == 0, (run.code, run.out, run.err[-2000:])

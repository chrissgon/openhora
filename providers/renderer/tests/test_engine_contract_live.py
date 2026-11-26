"""The engine contract (V3c) in real containers: the synthetic inputs through the renderer engine, the contract's assertions (the HyperFrames
engine's legs were retired in PF-b). Never builds, no network, no real recording: the recordings are test patterns that the common image's own ffmpeg makes, each carrying its own frame number as a
band of black and white cells at the top of the picture (contract_kit), so what every output frame is can be read from the pixels.

Gated by the variable of the image, as the other live files are (the parameter of the engine is skipped without it):

    OPENHORA_STATE_DIR=<folder> WB_RENDERER_DOCKER_TESTS=1 \\
    uv run --with pytest==9.1.1 pytest -q providers/renderer/tests/test_engine_contract_live.py

with no `-n`. The build comes first, into the same folder (the `build` verb of the host).

Two kinds of leg. The functional legs (F1-F12, short inputs) run in CI's docker jobs and on the Mac. The machine legs (M1, M2, M4, M5, `test_mac_*`) need
8 cores, a long run or the real size, so they run only with `WB_ENGINE_MAC_LEGS=1` (the maintainer's machine), one after another, and write the
committed report when `WB_ENGINE_REPORT=<a new file>` is set (a file that exists is refused):

    ... WB_ENGINE_MAC_LEGS=1 WB_ENGINE_REPORT=<folder>/engine-contract-<date>-<arch>.json pytest -q <this file> -k mac_

Memory in the report is what `docker stats` reports once a second (usage less the inactive file cache on cgroup v2) and the OOM kills `docker
events` counts. A new report is schema 2 (the one engine); the two committed reports are schema 1 and are never edited.
"""
from __future__ import annotations

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
import hf_second_kit as S
import hf_port_kit as PK
import _docker as D
import _edl
import _media

FFMPEG_ON = os.environ.get("WB_RENDERER_DOCKER_TESTS") == "1"
MAC_ON = os.environ.get("WB_ENGINE_MAC_LEGS") == "1"
REPORT_PATH = os.environ.get("WB_ENGINE_REPORT")
REAL_STATE_DIR = os.environ.get("OPENHORA_STATE_DIR")
HOSTS = {"ffmpeg": str(K.HOST)}
ENV_VARIABLE = {"ffmpeg": "WB_RENDERER_DOCKER_TESTS"}
CAPS = {"ffmpeg": FFMPEG_ON}
LABELS = ("org.openhora.renderer=1",)
SAMPLED_CAP_MIB = 5530                          # 90 percent of the 6144 MiB memory limit: stop rule 4
LIMIT_CODES = ("render_timeout", "no_space", "intermediate_too_large")
LIVE_LEGS = {}                                  # leg name -> the engines it runs on (the offline test reads it)
BOTH = ("ffmpeg",)


def legs(name: str, engines=BOTH):
    """The parametrisation of one leg over its engines (the one, `ffmpeg`, so that the ids and `-k` stay); an engine is skipped without its image's variable."""
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
    return [p.name for p in root.iterdir() if p.name.startswith(D.JOB_PREFIX)] if root.is_dir() else []


def assert_clean(out_dir=None, passed=False):
    """C11: a refusal leaves nothing (no file in its out folder, no container, no job folder); every run, passed or not, leaves no container and no run folder."""
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
        self.cache = {}
        self.counter = 0
        self.platform = json.loads(K.INSTAGRAM.read_text())

    def need(self, engine):
        """The engine's image is the common image, checked when the lab was made (an image that is not ready is a failure, not a skip)."""
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

    def render(self, engine, tag, recording, edl, beats, cpus=4, cpuset="0-3", blocks=None, memory=False, timeout=3600, passed_ok=True, assets=None, extra_env=None):
        """One render through the engine's host, the way a person runs it. `blocks` is a test blocks folder (RENDERER_TEST=1); the
        committed blocks otherwise. `memory` samples the containers and counts OOM kills. Leaves nothing: the run is checked clean before it returns."""
        self.need(engine)
        env = dict(os.environ)
        if blocks is not None:
            env.update(RENDERER_TEST="1", RENDERER_BLOCKS_DIR=str(blocks))
        env.update(extra_env or {})
        out_dir = self.folder / ("out-" + tag)
        args = ["render", "--edl", edl, "--beats", beats, "--in", recording, "--out", out_dir, "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY,
                "--cpus", cpus, "--cpuset", cpuset]
        args += ["--jobs", 2]
        for slot, picture in sorted((assets or {}).items()):
            args += ["--asset", "%s=%s" % (slot, picture)]
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
        """The F1 inputs through `engine` at the cpus of `label` (a: 4 cores, b: the same again, c: 2 cores), cached: F1 and F3 share the renders."""
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


CUTAWAY_POST = """# Post: Money habits with a cutaway (a fictional fixture)

- Owner: mkt-social-copy
- Status: draft
- Network: instagram
- Format: reel

```script
beat: 1
line: Hey, quick story about money.
on-screen: Money story
preset: keyword
icon: coin

beat: 2
line: Here is what my dashboard looked like.
on-screen: My dashboard
preset: cutaway
asset: a screenshot of the budgeting dashboard
fit: cover

beat: 3
line: Last year I tracked every expense for ninety days.
```

```post
Money habits. What would you track first?
```
"""
CUTAWAY_SENTENCES = [K.SENTENCES[0], K.SENTENCES[6], K.SENTENCES[1]]


def cutaway_picture(folder: Path) -> Path:
    """A landscape picture of two flat colours, made with zlib (never a real picture): the cutaway draws it in the glass layout."""
    import struct
    import zlib

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    w, h = 1200, 675
    row = b"\x00" + bytes((200, 40, 40)) * (w // 2) + bytes((40, 60, 200)) * (w - w // 2)
    path = folder / "cutaway.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(row * h, 9)) + chunk(b"IEND", b""))
    return path


def cutaway_leg(lab, engine, label, cpus, cpuset):
    """The cutaway case through `engine` at `cpus`, cached: a post with one cutaway beat (slot beat2) and its picture."""
    transcript = K.build_transcript(CUTAWAY_SENTENCES)

    def make():
        rec = lab.recording("cutaway", transcript)
        edl, beats, doc = lab.documents("cutaway", rec, transcript, CUTAWAY_POST)
        picture = cutaway_picture(lab.folder)
        return lab.render(engine, "cutaway-%s-%s" % (engine, label), rec, edl, beats, cpus, cpuset, assets={"beat2": picture})
    return lab.cached(("cutaway", engine, label), make)


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


@legs("F9")
def test_f9_the_cutaway_case_is_one_sha256_at_four_and_at_two_cpus(engine, lab):
    lab.need(engine)
    runs = [cutaway_leg(lab, engine, "a", 4, "0-3"), cutaway_leg(lab, engine, "b", 2, "0-1")]
    for run in runs:
        assert run.rc == 0, (run.out, run.err[-2000:])
    assert runs[0].out["sha256"] == runs[1].out["sha256"], [r.out["sha256"] for r in runs]


# ---------------------------------------------------------------- F12 transitions at joins (P1a, C5)

TRANSITION_KINDS_F12 = ("glitch", "bloom", "zoom_blur", "blur_to_card", "dip")


def with_transitions(lab, beats_file: Path, name: str, rows: list) -> Path:
    """A copy of the beats file with `transitions` set to `rows`."""
    doc = json.loads(Path(beats_file).read_text())
    doc["transitions"] = rows
    return K.write_json(lab.folder / name, doc)


@legs("F12", ("ffmpeg",))
def test_f12_the_transitions_are_drawn_twice_identically_and_the_speaker_changes_only_where_the_edit_list_says(engine, lab):
    """P1a, C5. One transition of each ffmpeg kind at five spread words of the F2 inputs (no zoom, so the band is read exactly), and one `glitch` on the beat of the
    cutaway case. Each is rendered at 4 and at 2 cpus: one sha256 (C9). The answer's `transitions_drawn` is what `_edl.resolve_transitions` makes of the rows, and
    the band of every output frame outside the frames of the rows is the source frame the kept ranges name (the frames inside are drawn on). The offline test of
    `test_transitions_compose.py` proves the same on every frame's md5 on the host's ffmpeg; this leg is the image's ffmpeg 5.1."""
    lab.need(engine)
    rec, edl_file, beats_file, doc = lab.plain()
    words = doc["words"]
    rows = [{"id": "t%d" % (k + 1), "kind": kind, "word": words[len(words) * (k + 1) // 6]["index"]} for k, kind in enumerate(TRANSITION_KINDS_F12)]
    beats = with_transitions(lab, beats_file, "beats-f12.json", rows)
    runs = [lab.render(engine, "f12-a-" + engine, rec, edl_file, beats, 4, "0-3"), lab.render(engine, "f12-b-" + engine, rec, edl_file, beats, 2, "0-1")]
    for run in runs:
        assert run.rc == 0, (run.out, run.err[-2000:])
    if runs[0].out["sha256"] != runs[1].out["sha256"]:
        listed = [("cpus %s" % s, r.out_dir, Path(r.out["path"]).name, r.out["sha256"]) for s, r in zip(("4", "2"), runs)]
        pytest.fail("a transition is not independent of the cpu count: %s" % json.dumps(C.mismatch_report(lab.runner(), listed), indent=1))
    from _vocab import load_data
    kept, dropped = _edl.resolve_transitions(doc, {"transitions": rows}, [], load_data())
    assert dropped == [] and [(t["id"], t["kind"], t["start_frame"], t["end_frame"]) for t in kept] == \
        [(r["id"], r["kind"], r["start_frame"], r["end_frame"]) for r in runs[0].out["transitions_drawn"]] == \
        [(r["id"], r["kind"], r["start_frame"], r["end_frame"]) for r in runs[1].out["transitions_drawn"]]
    inside = {f for t in kept for f, _ in t["frames"]}
    got, want = lab.band(Path(runs[0].out["path"])), C.expected_sources(doc["kept"])
    assert len(got) == doc["out_frames"] and inside
    assert [f for f in range(len(got)) if f not in inside and got[f] != want[f]] == []

    transcript = K.build_transcript(CUTAWAY_SENTENCES)
    crec = lab.recording("cutaway", transcript)
    cedl, cbeats, cdoc = lab.documents("cutaway", crec, transcript, CUTAWAY_POST)
    layout = next(e for e in json.loads(Path(cbeats).read_text())["layouts"] if e["preset"] == "cutaway")
    cwith = with_transitions(lab, cbeats, "beats-f12-cutaway.json", [{"id": "t1", "kind": "glitch", "beat": layout["id"]}])
    picture = cutaway_picture(lab.folder)
    cruns = [lab.render(engine, "f12-c-" + engine, crec, cedl, cwith, 4, "0-3", assets={"beat2": picture}),
             lab.render(engine, "f12-d-" + engine, crec, cedl, cwith, 2, "0-1", assets={"beat2": picture})]
    for run in cruns:
        assert run.rc == 0, (run.out, run.err[-2000:])
        assert [t["kind"] for t in run.out["transitions_drawn"]] == ["glitch"]
    assert cruns[0].out["sha256"] == cruns[1].out["sha256"], [r.out["sha256"] for r in cruns]


# ---------------------------------------------------------------- F5, F6 planted blocks

def planted_advice_leg(lab, engine, which, code):
    """Video P0b: the planted block renders (rc 0, one file) and the answer reports `code` as advice; nothing is refused."""
    lab.need(engine)
    rec, edl, beats, doc = lab.short()
    folder = C.planted_renderat(lab.folder, which)
    run = lab.render(engine, "planted-%s-%s" % (which, engine), rec, edl, beats, blocks=folder)
    assert run.rc == 0, (run.rc, run.out, run.err[-2000:])
    assert code in [row["code"] for row in run.out.get("advice") or []], (run.out.get("advice"), run.err[-1000:])
    return run


def image_runtime_sha256(lab, folder: Path) -> str:
    """The runtime hash the image computes for itself (`_hf_host.load_runtime` over its own vendor files, shims and browser, at 30 fps): what a recorded
    determinism test names, read in the image so that it is the image's, never a guess."""
    code = ("import os, sys; sys.path.insert(0, '/opt/renderer'); import _cdp, _hf_host; "
            "print(_hf_host.load_runtime('/opt/renderer/vendor', '/opt/renderer/hf-runtime/shims', 30, _cdp.browser_version(os.environ['RENDERER_BROWSER']))['runtime_sha256'])")
    out = in_image(lab.common, ["-I", "-c", code], folder, entrypoint="python3").strip()
    assert re.fullmatch(r"[0-9a-f]{64}", out), out
    return out


@legs("F10", ("ffmpeg",))
def test_f10_the_second_page_contract_draws_the_clean_control_twice_identically_and_refuses_every_planted_variant_with_its_code(engine, lab):
    """The real runtime and GSAP of the image, a fictional HF-shaped component (hf_second_kit) as the only entry of a test allowlist, mounted from a test
    registry folder over the image's. The clean control twice is one sha256; each planted variant is refused with its code and leaves nothing."""
    transcript = K.build_transcript(K.SHORT_SENTENCES[:2])
    rec = lab.recording("pfa2", transcript)
    edl, beats, doc = lab.documents("pfa2", rec, transcript, S.POST, ("--face-box", K.PIP_FACE_BOX))
    from _vocab import load_data, load_vocabulary
    data, vocab = load_data(), load_vocabulary(str(K.VOCABULARY))
    timeline = _edl.resolve_timeline(doc, json.loads(Path(beats).read_text()), vocab, data)
    start = [e for e in timeline["beats"] if e["preset"] == "keyword"][0]["start_frame"]
    probe = fresh(lab.folder / "pfa2-probe")
    runtime_sha = image_runtime_sha256(lab, probe)

    def make(variant, tag=None, **over):
        tmp = fresh(lab.folder / ("pfa2-" + (tag or variant)))
        registry = tmp / "registry"
        html = S.component(variant)
        files = S.write_component(registry, html)
        entry = S.entry(files, S.served_of({S.FILE: html}), runtime_sha, **over)
        blocks = S.blocks_folder(tmp, entry)
        return blocks, {"RENDERER_HF_REGISTRY_DIR": str(registry)}

    def run(variant, tag=None, **over):
        blocks, env = make(variant, tag, **over)
        return lab.render(engine, "pfa2-" + (tag or variant), rec, edl, beats, blocks=blocks, extra_env=env)

    one, two = run("clean", "clean1"), run("clean", "clean2")
    assert one.rc == 0 and two.rc == 0, (one.err, two.err)
    assert one.out["sha256"] == two.out["sha256"] and one.out["hf_proofs"][S.NAME]["runtime_sha256"] == runtime_sha
    # `opaque` (a full-frame layer, the 1-pixel corner cut so that it is RGBA) now proves the line gate: it is below the line from frame 3 (it was the face gate's
    # until 2026-11-24, when the face rule was removed); `face_dot` (alpha 1/255 in the face box) is no longer refused: it is drawn twice, one sha256
    # video P0b: the line and the drawn floor of the exact gates are advice, so these variants are drawn and reported (rc 0, one file, the advice row)
    expected = {"below_line": "drawn_below_line", "nothing": "block_not_drawn", "opaque": "drawn_below_line"}
    for variant, code in expected.items():
        r = run(variant)
        assert r.rc == 0, (variant, r.err[-400:])
        assert code in [row["code"] for row in r.out.get("advice") or []], (variant, r.out.get("advice"))
    for variant, code in (("opaque_no_clip", "frame_not_rgba"), ("computed_fetch", "blocked_request"), ("system_font", "font_not_allowed"),
                          ("fontface", "block_lint"), ("lint_storage", "block_lint")):
        r = run(variant)
        assert (r.rc, r.code) == (1, code), (variant, r.err[-400:])
    on_face_one, on_face_two = run("face_dot", "face1"), run("face_dot", "face2")
    assert on_face_one.rc == 0 and on_face_two.rc == 0, (on_face_one.err[-400:], on_face_two.err[-400:])
    assert on_face_one.out["sha256"] == on_face_two.out["sha256"]
    r = run("clean", "unproven", determinism=dict(S.entry({}, "a" * 64, "b" * 64)["determinism"]))
    assert (r.rc, r.code) == (1, "block_not_proven"), r.err[-300:]


@legs("F11", ("ffmpeg",))
def test_f11_one_of_our_own_ports_is_drawn_under_the_second_contract_by_the_real_runtime_twice_identically(engine, lab):
    """PF-a4a. A FICTIONAL tier-B card port and caption port (hf_port_kit) in a test blocks folder, each with a provisional determinism record at the image's own
    runtime hash. No file is requested at mount (a request would be `blocked_request`), the pages draw, every gate passes (the line and drawn as advice, the RGBA check) and the
    render twice is one sha256; the caption chunks are written as `cap_*` frames by the same path. The five real ports are PF-a4b's records."""
    transcript = K.build_transcript(K.SHORT_SENTENCES[:2])
    rec = lab.recording("pfa4", transcript)
    edl, beats, doc = lab.documents("pfa4", rec, transcript, S.POST, ("--face-box", K.PIP_FACE_BOX))
    runtime_sha = image_runtime_sha256(lab, fresh(lab.folder / "pfa4-probe"))

    def run(tag):
        tmp = fresh(lab.folder / ("pfa4-" + tag))
        blocks = PK.blocks_folder(tmp, ("card", "caption"), runtime_sha)
        return lab.render(engine, "pfa4-" + tag, rec, edl, beats, blocks=blocks)

    one, two = run("one"), run("two")
    assert one.rc == 0 and two.rc == 0, (one.err[-600:], two.err[-600:])
    assert one.out["sha256"] == two.out["sha256"] and set(one.out["hf_proofs"]) == {PK.CARD, PK.CAPTION}
    assert one.out["hf_proofs"][PK.CARD]["runtime_sha256"] == runtime_sha and "caption" in one.out["layers"]


@legs("F5")
def test_f5_a_card_over_the_face_box_is_drawn(engine, lab):
    """The face rule was removed on 2026-11-24 (nothing is refused for touching the face): the engine draws the card. The old engine's pixel advice
    `face_pixels_changed` went with the engine (PF-b, B3)."""
    lab.need(engine)
    rec, edl, beats, doc = lab.short()
    run = lab.render(engine, "planted-cover-%s" % engine, rec, edl, beats, blocks=C.planted_renderat(lab.folder, "cover"))
    assert run.rc == 0, (run.rc, run.out, run.err[-2000:])


@legs("F6")
def test_f6_a_caption_below_the_line_at_1560_renders_and_is_reported_as_advice(engine, lab):
    run = planted_advice_leg(lab, engine, "low", "caption_below_line")
    assert [row for row in run.out["advice"] if row["code"] == "caption_below_line"][0]["value"] > 1560


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
    assert (a, b, c) == ("block_unknown", "recording_changed", "input_too_long")       # the contract's three codes (stop rule 6)
    # (d) a port with no determinism record is on no engine (the committed ports all have one since PF-a4e): planted by removing the record
    spring = copy.deepcopy(beats)
    spring["overlays"][0]["block"] = "hf:spring-pop"
    beats_d = K.write_json(work / "beats-d.json", spring)
    refused_with(lab, engine, "f7d-" + engine, rec, edl_file, beats_d, "block_not_on_engine", blocks=C.planted_unproven_port(work))
    # and the committed spring-pop, with its record, is drawn by the engine under the second contract
    drawn = lab.render(engine, "f7d-drawn-" + engine, rec, edl_file, beats_d)
    assert drawn.rc == 0 and "hf:spring-pop" in drawn.out["hf_proofs"], (drawn.rc, drawn.out, drawn.err[-800:])


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
    cases = [C.case_row(name, row["transcript"], row["edl"], row["runs"], schema=2) for name, row in ROWS.items()]
    return {"schema": 2, "date": datetime.date.today().isoformat(), "commit": commit, "arch": arch,
            "machine": {"docker_cpus": int(docker_info("{{.NCPU}}") or 0), "docker_memory_mib": int(memory) // (1 << 20) if memory.isdigit() else 0},
            "images": {"common": D.image_tag().split(":")[1]}, "cases": cases}


def record(case, transcript, edl, engine, cpus, cpuset, run, frames_ok=None):
    row = ROWS.setdefault(case, {"transcript": transcript, "edl": edl, "runs": [], "results": []})
    row["runs"].append(C.run_row(engine, cpus, cpuset, run.out if run.rc == 0 else None, run.code, run.wall, run.memory, frames_ok, schema=2))
    if run.rc == 0:
        row["results"].append(run.out)
    return row["runs"][-1]


def stop_on_limits(row, run):
    """Stop rule 4: a limit broken at real size, or sampled memory at 90 percent of a cap, is a stop with the figures."""
    memory = row["memory"] or {}
    sampled = [v for v in (memory.get("common_sampled_max_mib"),) if v is not None]
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


@mac_only
@legs("M4")
def test_mac_m4_the_cutaway_case_is_one_sha256_at_four_and_at_eight_cores(engine, lab, eight_cpus):
    lab.need(engine)
    runs = [cutaway_leg(lab, engine, "m4-4", 4, "0-3"), cutaway_leg(lab, engine, "m4-8", 8, "0-7")]
    for run in runs:
        assert run.rc == 0, (run.out, run.err[-2000:])
    shas = {r.out["sha256"] for r in runs}
    assert len(shas) == 1, "STOP RULE 3, a nondeterminism on %s in the cutaway case: %s" % (engine, sorted(shas))


def clip_cutaway_leg(lab, label, cpus, cpuset, shape, engine="ffmpeg"):
    """The cutaway case on `engine` with a clip on its beat (slot beat2): a synthetic moving clip (a gradient carrying its own frame number, made by the host's
    ffmpeg), normalised by the common image's own `asset-sheet` verb, `shape` "cover" (1080x1920) or "glass" (1920x1080). Cached."""
    import clip_kit as CK
    transcript = K.build_transcript(CUTAWAY_SENTENCES)

    def make():
        rec = lab.recording("cutaway", transcript)
        edl, beats, doc = lab.documents("cutaway", rec, transcript, CUTAWAY_POST)
        raw = CK.counter_clip(lab.folder / ("clip-%s-raw.mp4" % shape), *((1080, 1920) if shape == "cover" else (1920, 1080)), 90)
        sheet = lab.folder / ("clip-%s-sheet" % shape)
        if not sheet.exists():
            rc, out, err = host("ffmpeg", "asset-sheet", "--asset", "slot-1:1=%s" % raw, "--mode", "full", "--out", sheet)
            assert rc == 0 and out["assets"][0]["kind"] == "clip", (out, err[-2000:])
        clip = next(sheet.glob("asset-*.mp4"))
        return lab.render(engine, "clip-%s-%s" % (shape, label), rec, edl, beats, cpus, cpuset, assets={"beat2": clip})
    return lab.cached(("clip-cutaway", shape, label), make)


@mac_only
@legs("M5", ("ffmpeg",))
def test_mac_m5_the_clip_cutaway_is_one_sha256_at_four_and_at_eight_cores_in_cover_and_in_glass(engine, lab, eight_cpus):
    """V9b-5a: a normalised moving clip under a cover cutaway and under a glass cutaway, composed by the common image's ffmpeg, the same sha256 at 4 and 8 cores."""
    lab.need(engine)
    for shape in ("cover", "glass"):
        runs = [clip_cutaway_leg(lab, "m5-4", 4, "0-3", shape), clip_cutaway_leg(lab, "m5-8", 8, "0-7", shape)]
        for run in runs:
            assert run.rc == 0, (shape, run.out, run.err[-2000:])
        shas = {r.out["sha256"] for r in runs}
        assert len(shas) == 1, "STOP RULE 3, a nondeterminism on the ffmpeg engine in the %s clip cutaway: %s" % (shape, sorted(shas))


def counter_numbers(video: str, first: int, count: int) -> list:
    """The frame number the clip's counter blocks show in each of `count` frames of `video` from frame `first`, drawn at 1:1 at the top-left corner (the cover
    layout): one ffmpeg call reads the one-pixel row through the middle of the blocks, and a block is white when its green channel is over 128."""
    import clip_kit as CK
    import subprocess
    raw = subprocess.run([K.FFMPEG, "-loglevel", "error", "-i", video, "-vf", "select=between(n\\,%d\\,%d),format=rgb24,crop=%d:1:0:%d" % (first, first + count - 1, CK.BLOCK * CK.BITS, CK.BLOCK // 2),
                          "-fps_mode", "passthrough", "-f", "rawvideo", "-"], capture_output=True, check=True, timeout=600).stdout
    width = CK.BLOCK * CK.BITS
    assert len(raw) == count * width * 3, (len(raw), count)
    numbers = []
    for i in range(count):
        row = raw[i * width * 3:(i + 1) * width * 3]
        numbers.append(sum(1 << k for k in range(CK.BITS) if row[(CK.BLOCK * k + CK.BLOCK // 2) * 3 + 1] > 128))
    return numbers


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
    assert_one_sha("real", engine)
    assert last is not None and last["bad"] == 0 and last["checked"] > 0 and last["frames"] == doc["out_frames"], \
        "STOP RULE 7, a frame the kept ranges do not name on %s: %s" % (engine, last)

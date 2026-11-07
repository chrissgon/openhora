"""The review of the first version: a render checked outside the container that made it, the face box under zoom, bounded and
sanitised reads of what the container wrote, and the small hardening items."""
from __future__ import annotations

import errno
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import renderer_kit as K
import docker_kit as DK
import _browser as B
import _cdp
import _docker as D
import _edl
import _frames
import _media
import _render
import _timeline as T
from _text import Refusal
from _vocab import load_data, load_vocabulary

DATA = load_data()
VOCAB = load_vocabulary(str(K.VOCABULARY))
INSTAGRAM = json.loads(K.INSTAGRAM.read_text())
needs_ffmpeg = pytest.mark.skipif(not K.HAVE_FFMPEG, reason=K.SKIP_MEDIA)
needs_all = pytest.mark.skipif(not (K.HAVE_FFMPEG and K.BROWSER), reason=K.SKIP_MEDIA + "; " + K.SKIP_BROWSER)


def refused(fn, *a, **k):
    with pytest.raises(Refusal) as e:
        fn(*a, **k)
    return e.value


# ---------------------------------------------------------------- 1. a render is checked outside the container that made it

def good_render(tmp_path, name="good.mp4", seconds=4, tags=True, codec="libx264"):
    path = tmp_path / name
    args = [K.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=%d" % seconds,
            "-f", "lavfi", "-i", "sine=frequency=220:duration=%d" % seconds, "-c:v", codec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", "-movflags", "+faststart"]
    if tags:
        args += ["-vf", _media.TAGS, "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    subprocess.run(args + [str(path)], check=True, timeout=120)
    return path


def verify(path, platform=K.INSTAGRAM, sha=None, seconds=None):
    args = ["verify", "--in", path, "--platform-file", platform, "--sha256", sha or _media.sha256_file(str(path))]
    if seconds is not None:
        args += ["--expect-seconds", str(seconds)]
    return K.run_verb(*args)


@needs_ffmpeg
def test_verify_passes_a_render_that_meets_the_platforms_spec_and_its_tags_and_length(tmp_path):
    path = good_render(tmp_path)
    rc, out, err = verify(path, seconds=4.0)
    assert rc == 0, err
    assert out["ok"] and out["sha256"] == _media.sha256_file(str(path)) and out["output"]["codec"] == "h264" and out["output"]["faststart"] is True


@needs_ffmpeg
def test_verify_refuses_other_bytes_than_the_ones_reported(tmp_path):
    path = good_render(tmp_path)
    rc, out, err = verify(path, sha="0" * 64)
    assert rc == 1 and err.startswith("refused: render_differs")


@needs_ffmpeg
def test_verify_refuses_a_render_outside_the_spec_naming_each_failure(tmp_path):
    path = good_render(tmp_path)
    tight = json.loads(K.INSTAGRAM.read_text())
    tight["video"].update(codecs=["h265"], max_seconds=2, fps_min=40)
    pf = tmp_path / "p.json"
    pf.write_text(json.dumps(tight))
    rc, out, err = verify(path, platform=pf)
    first = err.splitlines()[0]
    assert rc == 1 and first.startswith("refused: platform_spec") and all(c in first for c in ("codec", "max_seconds", "fps_min"))
    untagged = good_render(tmp_path, "untagged.mp4", tags=False)
    rc, out, err = verify(untagged)
    assert rc == 1 and "color_tags" in err.splitlines()[0]
    rc, out, err = verify(path, seconds=9.0)
    assert rc == 1 and "duration_mismatch" in err.splitlines()[0]
    late = tmp_path / "late.mp4"
    subprocess.run([K.FFMPEG, "-y", "-loglevel", "error", "-i", str(path), "-c", "copy", str(late)], check=True)           # moov at the end
    rc, out, err = verify(late)
    assert rc == 1 and "faststart" in err.splitlines()[0]


@pytest.fixture
def world(tmp_path):
    (tmp_path / "home").mkdir()
    return DK.World(tmp_path)


@needs_all
def test_the_host_stores_a_render_only_after_a_fresh_container_has_verified_it(world, tmp_path):
    tr = K.build_transcript(K.SHORT_SENTENCES)
    src, asset = tmp_path / "rec.mp4", tmp_path / "asset.png"
    K.make_source(src, tr)
    K.make_asset(asset)
    (tmp_path / "post.md").write_text(K.SHORT_POST)
    t = K.write_json(tmp_path / "t.json", tr)
    assert world.host("analyse", "--in", src, "--out", tmp_path / "analysis.json")[0] == 0
    assert world.host("base", "--transcript", t, "--analysis", tmp_path / "analysis.json", "--out", tmp_path / "edl.json")[0] == 0
    assert world.host("align", "--post", tmp_path / "post.md", "--transcript", t, "--checker", K.CHECKER, "--vocabulary", K.VOCABULARY, "--out", tmp_path / "beats.json")[0] == 0
    render = ["render", "--edl", tmp_path / "edl.json", "--beats", tmp_path / "beats.json", "--in", src, "--platform-file", K.INSTAGRAM, "--vocabulary", K.VOCABULARY,
              "--asset", "3=%s" % asset, "--asset", "4=%s" % asset, "--jobs", "2"]
    before = len(world.runs())
    rc, out, err = world.host(*render, "--out", tmp_path / "out")
    assert rc == 0, err
    runs = [r["argv"] for r in world.runs()[before:]]
    assert len(runs) == 2 and runs[0][runs[0].index("render") if "render" in runs[0] else 0] and "verify" in runs[1] and "render" not in runs[1][runs[1].index("sha256:" + "cd" * 32):]
    verify_mounts = [runs[1][i + 1] for i, a in enumerate(runs[1]) if a == "-v"]
    assert verify_mounts[0].endswith("candidate.mp4:/in/recording:ro") and verify_mounts[1].endswith(":/job:ro") and verify_mounts[2].endswith(":/out:rw")
    for argv in runs:
        assert argv[argv.index("--network") + 1] == "none" and "--read-only" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert out["verified"] is True and Path(out["path"]).name == "render-%s.mp4" % out["sha256"][:12] and out["output"]["codec"] == "h264"
    # a render the fresh container finds outside the spec is never stored
    world.cfg["verify_platform"] = {**json.loads(K.INSTAGRAM.read_text()), "video": {**INSTAGRAM["video"], "codecs": ["h265"]}}
    world.save()
    rc, out, err = world.host(*render, "--out", tmp_path / "out2")
    assert rc == 1 and err.splitlines()[0].startswith("refused: platform_spec codec")
    assert not (tmp_path / "out2").exists() or not list((tmp_path / "out2").glob("render-*"))
    assert not [p for p in (world.state / "renderer" / "work").iterdir() if p.name.startswith(D.JOB_PREFIX)]


# ---------------------------------------------------------------- 2. the face box under zoom

CENTRE = {"x": 240, "y": 620, "w": 600, "h": 560}


def test_the_zoomed_face_box_grows_about_the_anchor_and_stays_inside_the_frame():
    anchor = _media.anchor_point(CENTRE, 0.25)
    assert _media.zoomed_box(CENTRE, 1.0, 1.0, anchor, 1080, 1920) == CENTRE
    box = _media.zoomed_box(CENTRE, 1.1, 1.1, anchor, 1080, 1920)
    assert box["w"] == pytest.approx(600 * 1.1, abs=3) and box["h"] == pytest.approx(560 * 1.1, abs=3)
    assert box["y"] < CENTRE["y"] + 10 and box["y"] + box["h"] > CENTRE["y"] + CENTRE["h"]        # the anchor is high on the face: the box grows mostly downwards
    big = _media.zoomed_box(CENTRE, 1.25, 1.25 * 1.03, anchor, 1080, 1920)
    assert big["w"] > box["w"] and big["h"] > box["h"] and big["h"] == pytest.approx(560 * 1.25 * 1.03, abs=4)
    for z0, z1 in ((1.1, 1.1), (1.25, 1.25), (1.25, 1.2875), (1.0, 1.03)):
        b = _media.zoomed_box(CENTRE, z0, z1, anchor, 1080, 1920)
        assert 0 <= b["x"] and b["x"] + b["w"] <= 1080 and 0 <= b["y"] and b["y"] + b["h"] <= 1920
    edge = {"x": 0, "y": 100, "w": 300, "h": 300}                          # a face at the edge: the box is cut at the frame's edge, not pushed out
    b = _media.zoomed_box(edge, 1.25, 1.25, _media.anchor_point(edge, 0.25), 1080, 1920)
    assert b["x"] == 0


def zoom_edl(factor, push, mode="alternate"):
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    edl, _ = _edl.build_base(doc, analysis, DATA, {}, zoom_mode=mode, zoom_factor=factor, push_in=push)
    return edl


def test_a_face_box_that_leaves_room_unzoomed_but_not_zoomed_is_refused():
    face = {"x": 240, "y": 500, "w": 600, "h": 850}
    _edl.check_face(DATA, face)                                            # fits as it is
    zoomed = {"mode": "alternate", "factor": 1.25, "push_in": 0.03, "anchor_y": 0.25}
    assert refused(_edl.check_face, DATA, face, "face_box", zoomed).code == "face_box_leaves_no_room"
    _edl.check_face(DATA, face, "face_box", {"mode": "none", "factor": 1.25, "push_in": 0.0, "anchor_y": 0.25})
    doc = K.build_transcript()
    analysis = {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    assert refused(_edl.build_base, doc, analysis, DATA, {}, face_box=face, zoom_factor=1.25, push_in=0.03).code == "face_box_leaves_no_room"
    _edl.check_face(DATA, CENTRE, "face_box", zoomed)                      # the default box fits the largest zoom


@pytest.mark.parametrize("factor, push", [(1.1, 0.0), (1.25, 0.0), (1.25, 0.03)])
def test_a_card_or_caption_spans_the_face_of_every_range_it_lives_through(factor, push):
    edl = zoom_edl(factor, push)
    _edl.check_edl(edl, DATA, VOCAB, {})
    boxes = _edl.range_faces(edl, DATA)
    assert len(boxes) == len(edl["kept"]) and boxes[0][2]["h"] <= boxes[1][2]["h"] + 1             # an even range is unzoomed (but for the push-in), an odd one is zoomed
    beats = {"schema_version": 1, "threshold": 0.6, "slots": [], "report": [], "unmatched": [], "fallbacks": [], "layouts": [],
             "overlays": [{"id": "b1", "beat": 1, "preset": "list", "params": {"items": "One | Two | Three"}, "word_from": 0, "word_to": 25, "score": 1.0}]}
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    entry = timeline["beats"][0]
    touched = [box for a, b, box in boxes if a < entry["end_frame"] and entry["start_frame"] < b]
    assert len(touched) > 1
    for box in touched:                                                    # the entry's face covers each range's box
        assert entry["face"]["x"] <= box["x"] and entry["face"]["y"] <= box["y"]
        assert entry["face"]["x"] + entry["face"]["w"] >= box["x"] + box["w"] and entry["face"]["y"] + entry["face"]["h"] >= box["y"] + box["h"]
    assert all("face" in c for c in timeline["captions"])


@needs_all
@pytest.mark.parametrize("factor, push", [(1.25, 0.03), (1.1, 0.02)])
def test_no_card_and_no_caption_touches_the_zoomed_face_through_a_whole_render_of_frames(tmp_path, factor, push):
    edl = zoom_edl(factor, push)
    words = {w["index"]: w for w in edl["words"]}
    entries = [("keyword", {"text": "Name every dollar", "icon": "coin"}), ("list", {"items": "Review | Adjust | Celebrate | Repeat every week"}),
               ("number", {"value": "1.234,56", "label": "euros saved in one month"}), ("quote", {"text": "Small steps beat big plans, every single time.", "author": "A friend"})]
    n = len(edl["words"])
    step = max(2, n // len(entries))
    overlays = [{"id": "b%d" % (k + 1), "beat": k + 1, "preset": name, "params": params, "word_from": k * step, "word_to": min(n - 1, k * step + step - 1), "score": 1.0}
                for k, (name, params) in enumerate(entries)]
    beats = {"schema_version": 1, "threshold": 0.6, "slots": [], "report": [], "unmatched": [], "fallbacks": [], "layouts": [], "overlays": overlays}
    _edl.check_beats(beats, edl, VOCAB)
    timeline = _edl.resolve_timeline(edl, beats, VOCAB, DATA)
    names = [DATA["caption"]["template"]] + [DATA["presets"][e["preset"]]["template"] for e in timeline["beats"]]
    serve, _ = _frames.load_templates(names)
    templates = {"caption": DATA["caption"]["template"], **{n: DATA["presets"][n]["template"] for n, _ in entries}}
    layers, facts = _frames.draw_frames(data=DATA, edl=edl, timeline=timeline, serve=serve, theme_fonts_urls={}, assets={}, browser=K.BROWSER, jobs_n=3,
                                        frames_dir=str(tmp_path / "frames"), workdir=str(tmp_path / "w"), time_limit=300, templates=templates, png_blank=_render.blank_png)
    assert layers == {"beat", "caption"} and facts["frames_rendered"] > 100


# ---------------------------------------------------------------- 3. the input bound and the memory

def test_the_input_bound_is_the_intake_limit_of_the_plan_and_a_longer_recording_is_refused():
    assert DATA["limits"]["input_seconds_max"] == 300
    doc = K.build_transcript()
    analysis = {"facts": {"duration": 400.0, "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": None}
    assert refused(_edl.build_base, doc, analysis, DATA, {}).code == "analysis_schema"


def host_module():
    spec = importlib.util.spec_from_file_location("renderer_host_under_test", K.HOST)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(K.RENDERER))
    spec.loader.exec_module(mod)
    return mod


def test_the_scratch_never_exceeds_the_memory_less_a_margin(world, tmp_path, monkeypatch):
    host = host_module()
    for k, v in world.env().items():
        monkeypatch.setenv(k, v)
    args = lambda memory, scratch: type("A", (), {"memory_mb": memory, "scratch_mb": scratch, "cpus": 4, "timeout": None})()
    with host.Job(args(6144, 2048), 60, "x") as job:
        assert job.limits()[1:3] == (6144, 2048)
    with host.Job(args(6144, 4096), 60, "x") as job:                        # 4096 is exactly the memory less the margin: allowed
        assert job.limits()[2] == 4096
    for memory, scratch in ((6144, 4200), (3072, 2048), (100, 2048), (8000, 8192)):
        with host.Job(args(memory, scratch), 60, "x") as job:
            with pytest.raises(Refusal) as e:
                job.limits()
            assert e.value.code == "scratch_exceeds_memory", (memory, scratch)
    assert D.MIN_MEMORY_MB == 3072 and D.MEMORY_MARGIN_MB == 2048


def test_a_scratch_that_is_too_big_is_a_clean_refusal_on_the_command_line_and_no_container_starts(world, tmp_path):
    rc, out, err = world.host("check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}), "--vocabulary", K.VOCABULARY,
                              "--memory-mb", "4000", "--scratch-mb", "3000")
    assert rc == 1 and err.startswith("refused: scratch_exceeds_memory") and world.runs() == []


# ---------------------------------------------------------------- 4. hardening

def test_the_recording_is_read_without_external_data_references():
    assert _media.RECORDING_IN == ["-f", "mov", "-enable_drefs", "0", "-protocol_whitelist", "file"]


def test_what_the_host_prints_is_rebuilt_from_a_closed_schema():
    clean = D.sanitise({"ok": True, "ffmpeg": "ffmpeg 9", "ffprobe": "ffprobe 9", "missing": [], "python": "3.11", "browser": "Chrome 155", "libass": False,
                        "container": True, "templates": ["a.html"], "extra": "ignored", "another": {"x": 1}}, D.RESULT_SCHEMAS["selfcheck"])
    assert set(clean) == {"ok", "ffmpeg", "ffprobe", "missing", "python", "browser", "libass", "container", "templates"}
    bad_values = [("ffmpeg", "line\nbreak"), ("ffmpeg", "x" * 300), ("ffmpeg", "ansi\x1b[31m"), ("ffmpeg", "bidi\u202e"), ("ffmpeg", 5), ("ok", "yes"),
                  ("missing", "not a list"), ("templates", [1]), ("libass", 1)]
    for key, value in bad_values:
        doc = {"ok": True, "ffmpeg": "f", "ffprobe": "p", "missing": [], "python": "3", "browser": "b", "libass": False, "container": True, "templates": []}
        doc[key] = value
        assert refused(D.sanitise, doc, D.RESULT_SCHEMAS["selfcheck"]).code == "container_result_invalid", (key, value)
    nan = float("nan")
    assert refused(D.sanitise, {"ok": True, "duration": nan, "sha256": "a", "has_audio": True}, D.RESULT_SCHEMAS["analyse"]).code == "container_result_invalid"
    assert refused(D.sanitise, {"ok": True, "duration": float("inf"), "sha256": "a", "has_audio": True}, D.RESULT_SCHEMAS["analyse"]).code == "container_result_invalid"


def test_problems_hold_an_integer_beat_and_closed_words_only():
    ok = D.sanitise([{"beat": 3, "field": "on-screen", "code": "text_too_long", "extra": "x"}], D.PROBLEMS)
    assert ok == [{"beat": 3, "field": "on-screen", "code": "text_too_long"}]
    for bad in ({"beat": "3; rm -rf /", "field": "f", "code": "c"}, {"beat": True, "field": "f", "code": "c"}, {"beat": 1, "field": "a\\nb", "code": "c"},
                {"beat": 1, "field": "f", "code": "Not Closed"}, {"beat": 1, "field": "f", "code": "ghp_" + "x" * 40 + " text"}):
        assert refused(D.sanitise, [bad], D.PROBLEMS).code == "container_result_invalid"


def test_a_container_result_with_hostile_text_never_reaches_the_hosts_output(world, tmp_path):
    hostile = {"ok": True, "ffmpeg": "ffmpeg\nforged line", "ffprobe": "p", "missing": [], "python": "3", "browser": "b", "libass": False, "container": True, "templates": []}
    world.cfg.update(run="files", files={"result.json": {"text": json.dumps(hostile)}}, rc=0)
    world.save()
    rc, out, err = world.host("--check")
    assert rc == 1 and err.startswith("refused: container_result_invalid") and "forged" not in err and (out is None or "forged" not in json.dumps(out))
    refusal = {"ok": False, "code": "credential_shaped", "field": "edl.words[3]", "problems": [{"beat": "7 and a secret", "field": "f", "code": "c"}]}
    world.cfg.update(files={"result.json": {"text": json.dumps(refusal)}}, rc=1)
    world.save()
    rc, out, err = world.host("check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}), "--vocabulary", K.VOCABULARY)
    assert rc == 1 and err.splitlines()[0] == "refused: credential_shaped edl.words[3]" and "secret" not in err and out["problems"] == []


def test_the_containers_stderr_is_read_up_to_a_cap_and_never_printed(world, tmp_path, monkeypatch):
    flood = D.MAX_STDERR * 40
    world.cfg.update(run="files", files={"result.json": {"text": json.dumps({"ok": True, "ffmpeg": "f", "ffprobe": "p", "missing": [], "python": "3", "browser": "b", "libass": False,
                                                                           "container": True, "templates": []})}}, rc=0, flood=flood,
                     stderr="Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: the words of the transcript\n")
    world.save()
    rc, out, err = world.host("--check", timeout=120)
    assert rc == 0 and "Traceback" not in err and "transcript" not in err and len(err) < 2000
    argv = ["docker", "run"]
    import time
    world.cfg["run"] = "files"
    world.save()
    # monkeypatch, not os.environ: the change must end with the test, or every later test of the process (under xdist,
    # a different set of them on each run) would run with a fake docker first on its PATH
    monkeypatch.setenv("DOCKER_CONFIG", str(world.config))
    monkeypatch.setenv("PATH", "%s:%s" % (world.bin, os.environ["PATH"]))
    folder = tmp_path / "o"
    folder.mkdir()
    rc, stderr = D.run_container(["docker", "run", "--name", "n", "-v", "%s:/out:rw" % folder, "image"], "n", 60)
    assert len(stderr) <= D.MAX_STDERR


def test_a_container_that_crashed_prints_no_traceback_only_a_closed_code(world, tmp_path):
    world.cfg.update(run="files", files={}, rc=1, stderr="Traceback (most recent call last):\nKeyError: 'secret words'\n")
    world.save()
    rc, out, err = world.host("check", "--edl", K.write_json(tmp_path / "e.json", {}), "--beats", K.write_json(tmp_path / "b.json", {}), "--vocabulary", K.VOCABULARY)
    assert rc == 1 and err.splitlines()[0] == "refused: container_failed container" and "Traceback" not in err and "secret" not in err
    for rc_code, expected in ((125, "docker_run_failed"), (137, "container_killed")):
        world.cfg.update(rc=rc_code)
        world.save()
        rc, out, err = world.host("check", "--edl", tmp_path / "e.json", "--beats", tmp_path / "b.json", "--vocabulary", K.VOCABULARY)
        assert err.startswith("refused: " + expected)


def test_an_unforeseen_error_in_the_container_writes_a_closed_internal_result(tmp_path, monkeypatch):
    sys.path.insert(0, str(K.RENDERER))
    import _inner
    def boom(args):
        raise KeyError("a word of the transcript")
    monkeypatch.setitem(_inner.VERBS, "check", boom)
    result = tmp_path / "result.json"
    assert _inner.main(["--result", str(result), "check", "--edl", "e", "--beats", "b", "--vocabulary", "v"]) == 1
    assert json.loads(result.read_text()) == {"ok": False, "code": "internal", "field": "", "problems": []}
    assert "transcript" not in result.read_text()


def test_numbers_that_are_not_finite_are_refused_in_a_transcript_and_an_analysis(tmp_path):
    import _timeline
    for key, value in (("duration", float("nan")), ("duration", float("inf"))):
        doc = K.build_transcript()
        doc[key] = value
        assert refused(_timeline.check_transcript, doc, DATA["limits"]).code == "transcript_duration"
    for field, value in (("start", float("nan")), ("end", float("inf")), ("start", float("-inf"))):
        doc = K.build_transcript()
        doc["words"][3][field] = value
        assert refused(_timeline.check_transcript, doc, DATA["limits"]).code == "word_time"
    doc = K.build_transcript()
    base = {"facts": {"duration": doc["duration"], "sha256": "d" * 64, "width": 1080, "height": 1920, "has_audio": True}, "silences": []}
    for bad in (float("nan"), float("inf"), -1.0):
        analysis = json.loads(json.dumps(base))
        analysis["silences"] = [{"start": bad, "end": 1.0}]
        assert refused(_edl.build_base, doc, analysis, DATA, {}).code == "analysis_schema"
    analysis = json.loads(json.dumps(base))
    analysis["facts"]["duration"] = float("nan")
    assert refused(_edl.build_base, doc, analysis, DATA, {}).code == "analysis_schema"
    analysis = json.loads(json.dumps(base))
    analysis["facts"]["width"] = 1080.5
    assert refused(_edl.build_base, doc, analysis, DATA, {}).code == "analysis_schema"
    # NaN written as JSON text (Python reads it) is refused through the verb
    path = tmp_path / "t.json"
    text = json.dumps(K.build_transcript()).replace('"start": 1.0', '"start": NaN', 1)
    path.write_text(text)
    analysis_path = K.write_json(tmp_path / "a.json", base)
    rc, out, err = K.run_verb("base", "--transcript", path, "--analysis", analysis_path, "--out", tmp_path / "e.json")
    assert rc == 1 and err.startswith("refused: word_time")


def test_there_must_be_room_for_the_output_before_the_container_runs(world, tmp_path, monkeypatch):
    host = host_module()
    for k, v in world.env().items():
        monkeypatch.setenv(k, v)
    args = type("A", (), {"memory_mb": 6144, "scratch_mb": 2048, "cpus": 4, "timeout": None})()
    with host.Job(args, 60, "x") as job:
        monkeypatch.setattr(host.shutil, "disk_usage", lambda p: type("U", (), {"free": 1024})())
        with pytest.raises(Refusal) as e:
            job.run(["selfcheck"], "selfcheck")
        assert e.value.code == "no_space" and world.runs() == []


def test_a_file_system_without_hard_links_still_gets_a_named_never_rewritten_copy(tmp_path, monkeypatch):
    src = tmp_path / "a.bin"
    src.write_bytes(b"render bytes")
    digest = hashlib.sha256(b"render bytes").hexdigest()

    def no_links(a, b, **k):
        raise OSError(errno.EPERM, "no hard links here")

    monkeypatch.setattr(D.os, "link", no_links)
    fsynced = []
    real_fsync = os.fsync
    monkeypatch.setattr(D.os, "fsync", lambda fd: (fsynced.append(fd), real_fsync(fd))[1])
    dest = tmp_path / "out" / "render-x.mp4"
    assert D.copy_out(str(src), str(dest), max_bytes=1000, mode=0o400, expect_sha256=digest, exclusive=True) == "written"
    assert dest.read_bytes() == b"render bytes" and stat.S_IMODE(dest.stat().st_mode) == 0o400 and fsynced
    assert D.copy_out(str(src), str(dest), max_bytes=1000, mode=0o400, expect_sha256=digest, exclusive=True) == "replayed"
    other = tmp_path / "b.bin"
    other.write_bytes(b"other bytes!")
    assert refused(D.copy_out, str(other), str(dest), max_bytes=1000, mode=0o400, exclusive=True).code == "name_collision"
    assert dest.read_bytes() == b"render bytes"
    assert not [p for p in dest.parent.iterdir() if p.name.startswith(".copy-")]


def test_the_host_downloads_only_from_the_official_bucket_like_the_build():
    official = "https://storage.googleapis.com/chrome-for-testing-public/155.0.8059.39/linux64/x.zip"
    assert B.url_allowed(official, False)
    for bad in ("https://example.com/x.zip", "https://storage.googleapis.com/other-bucket/x.zip", "http://storage.googleapis.com/chrome-for-testing-public/x.zip",
                "https://storage.googleapis.com.evil.example/chrome-for-testing-public/x.zip", "http://127.0.0.1:1/x.zip"):
        assert not B.url_allowed(bad, False), bad
    assert B.url_allowed("http://127.0.0.1:1/x.zip", True) and not B.url_allowed("http://10.0.0.1/x.zip", True)


def test_the_page_policy_forbids_base_and_form_targets():
    assert "base-uri 'none'" in _cdp.CSP and "form-action 'none'" in _cdp.CSP and "connect-src 'none'" in _cdp.CSP


@needs_all
def test_a_base_element_in_a_page_is_a_csp_violation_that_fails_the_render(tmp_path):
    body = "var b=document.createElement('base');b.href='https://evil.example/';document.head.appendChild(b);window.renderAt=()=>{}"
    page = ("<!doctype html><meta charset=utf-8><body><script>%s</script>" % body).encode()
    with _cdp.Chrome(K.BROWSER, {"/t/x.html": (page, "text/html")}, str(tmp_path / "w")) as ch:
        pg = ch.new_page(200, 200)
        with pytest.raises(_cdp.RenderBlocked):
            pg.open("/t/x.html", {"colors": {}, "fonts": {}, "images": {}})


def test_every_change_of_the_edit_lists_schema_is_in_the_schema_file():
    schema = json.loads((K.RENDERER / "edl.schema.json").read_text())["$defs"]["edl"]["properties"]
    assert set(schema) == _edl.EDL_KEYS

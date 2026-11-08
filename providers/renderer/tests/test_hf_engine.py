"""The HyperFrames engine's host side, `providers/renderer/hyperframes.py` (V3a-2), against a fake docker client and a fake container run.

The docker client is the stand-in of `fake_docker.py` (version, info, image inspect); the five containers of a render are played by
`FakeRun`, which stands where `_container.run` stands and answers each verb the way the images would, from the mounts of the command it was
given, so the host side is tested whole: the command of every stage, the run folder, the checks of what a container left, the result. No
docker, no ffmpeg, no HyperFrames, no browser. Every input is synthetic.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from collections import namedtuple
from pathlib import Path

import pytest

import docker_kit
import renderer_kit as K
import _container as box
import _docker as D
import _host
import _blocks
import _media
import hyperframes as H
from _text import Refusal
from _browser import NotConfigured

HF_ID = "sha256:" + "ef" * 32
COMMON_ID = "sha256:" + "cd" * 32
PROXY_BYTES, HF_BYTES, FINAL_BYTES = b"proxy" * 100, b"prores" * 200, b"final-mp4" * 50
BOXES_BYTES = b'{"fonts":[],"fps":30,"frames":90,"per_frame":[],"schema":1}'
GATE = {"gate_frames": 90, "gate_boxes": 12, "lowest_caption_bottom": 1544.5, "pixel_min_psnr_db": 41.25, "pixel_ranges": 3, "pixel_seconds": 6.5}
SHA = lambda raw: hashlib.sha256(raw).hexdigest()   # noqa: E731
OUTPUT = {"container": "mov,mp4,m4a,3gp,3g2,mj2", "codec": "h264", "profile": "High", "pix_fmt": "yuv420p", "width": 1080, "height": 1920, "fps": 30.0,
          "duration": 3.0, "bytes": len(FINAL_BYTES), "audio_codec": "aac", "faststart": True, "color": ["tv", "bt709", "bt709", "bt709"], "frames": "90"}
Usage = namedtuple("Usage", "total used free")


class FakeRun:
    """Stands where `_container.run` stands. `fail` maps a stage name to what to do instead: "refuse:<code>" (the drawing container writes a
    refusal row and exits 1), "raise" (the run itself fails), or a callable."""

    def __init__(self, fail=None, hf_bytes=HF_BYTES, hf_sha=None, memory_peak=5000, page_blocks_sha=None, boxes=BOXES_BYTES, boxes_sha=None, gate=GATE):
        self.commands, self.verbs, self.fail = [], [], fail or {}
        self.hf_bytes, self.hf_sha, self.memory_peak = hf_bytes, hf_sha, memory_peak
        self.page_blocks_sha = page_blocks_sha
        self.boxes, self.boxes_sha, self.gate = boxes, boxes_sha, gate     # boxes None: the drawing container writes no boxes.json
        self.seen = {}

    def __call__(self, command, name, timeout, **kw):
        self.commands.append(command)
        mounts = {}
        for i, word in enumerate(command):
            if word == "-v":
                host, inside, mode = command[i + 1].rsplit(":", 2)
                mounts[inside] = (host, mode)
        if HF_ID in command:
            return self.drawing(command, mounts, timeout)
        inner = command[command.index(COMMON_ID) + 1:]
        verb = inner[2]
        self.verbs.append(verb)
        if self.fail.get(verb) == "raise":
            raise RuntimeError("a stage failed")
        out = Path(mounts["/out"][0])
        rows = {
            "hf-page": {"ok": True, "page_sha256": "a" * 64, "vars_sha256": "b" * 64, "clips": 2, "zooms": 1, "duration": 3.0, "fps": 30, "layers": ["cuts", "zoom"]},
            "selfcheck": {"ok": True, "ffmpeg": "ffmpeg version fake", "ffprobe": "ffprobe version fake", "missing": [], "python": "3.11.2",
                          "browser": "HeadlessChrome/fake", "libass": True, "container": True},
        }
        if verb == "hf-page" and "--blocks-sha256" in inner:
            self.seen["page"] = inner
            rows["hf-page"] = dict(rows["hf-page"], layers=["cuts", "zoom", "captions", "beats"], blocks={"oh:caption": "c" * 64, "oh:keyword": "d" * 64},
                                   blocks_sha256=self.page_blocks_sha or inner[inner.index("--blocks-sha256") + 1], captions_drawn=4, beats_drawn=2,
                                   runtimes={"oh:caption": "renderat", "oh:keyword": "renderat"}, fonts_used={"display": "inter-800.woff2", "text": "inter-500.woff2"})
        if verb == "proxy":
            Path(mounts["/work/media"][0], "proxy.mp4").write_bytes(PROXY_BYTES)
            rows["proxy"] = {"ok": True, "sha256": SHA(PROXY_BYTES), "bytes": len(PROXY_BYTES), "seconds": 1.5, "width": 1080, "height": 1920, "fps": 30, "has_audio": True}
        elif verb == "encode":
            host, mode = mounts["/work/hf"]
            intermediate = Path(host, "intermediate.mov")
            assert mode == "ro" and SHA(intermediate.read_bytes()) == inner[inner.index("--sha256") + 1]
            self.seen["encode"], self.seen["encode_mounts"] = inner, mounts
            if str(self.fail.get("encode", "")).startswith("refuse:"):
                (out / "result.json").write_text(json.dumps({"ok": False, "code": self.fail["encode"].split(":", 1)[1], "field": "frame 3 hf-inst-1", "problems": []}))
                return box.Finished(1, "", False)
            (out / ("render-%s.mp4" % SHA(FINAL_BYTES)[:12])).write_bytes(FINAL_BYTES)
            rows["encode"] = {"ok": True, "sha256": SHA(FINAL_BYTES), "out_seconds": 3.0, "out_frames": 90, "intermediate_sha256": inner[inner.index("--sha256") + 1]}
            if "--boxes" in inner:
                assert mounts["/work/media"][1] == "ro" and SHA(Path(mounts["/work/media"][0], "proxy.mp4").read_bytes()) == inner[inner.index("--proxy-sha256") + 1]
                assert SHA(Path(host, "boxes.json").read_bytes()) == inner[inner.index("--boxes-sha256") + 1]
                rows["encode"].update(self.gate or {})
        elif verb == "verify":
            rows["verify"] = {"ok": True, "sha256": inner[inner.index("--sha256") + 1], "output": OUTPUT}
        (out / "result.json").write_text(json.dumps(rows[verb]))
        return box.Finished(0, "", False)

    def drawing(self, command, mounts, timeout):
        self.verbs.append("hf")
        self.seen["mounts"] = {k: v for k, v in mounts.items()}
        self.seen["timeout"] = timeout
        project = Path(mounts["/work/project"][0])
        assert (project / "media" / "proxy.mp4").read_bytes() == PROXY_BYTES      # the proxy is in the project before the drawing starts
        if self.fail.get("hf") == "raise":
            raise RuntimeError("a stage failed")
        out = Path(mounts["/work/out"][0])
        if str(self.fail.get("hf", "")).startswith("refuse:"):
            (out / "result.json").write_text(json.dumps({"ok": False, "code": self.fail["hf"].split(":", 1)[1], "field": "index.html"}))
            return box.Finished(1, "", False)
        (out / "intermediate.mov").write_bytes(self.hf_bytes)
        row = {"ok": True, "sha256": self.hf_sha or SHA(self.hf_bytes), "bytes": len(self.hf_bytes), "seconds": 4.2, "hyperframes": "0.9.19",
               "memory_peak_bytes": self.memory_peak}
        self.seen["hf_inner"] = command[command.index(HF_ID) + 1:]
        if "--measure" in self.seen["hf_inner"] and self.boxes is not None:
            (out / "boxes.json").write_bytes(self.boxes)
            row.update(boxes_sha256=self.boxes_sha or SHA(self.boxes), measure_seconds=2.5)
        (out / "result.json").write_text(json.dumps(row))
        return box.Finished(0, "", False)


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = docker_kit.World(tmp_path)
    tag = H.hf_image.image_tag()
    w.cfg["images"][tag] = {"Id": HF_ID, "Labels": {D.LABEL_DEFINITION: H.hf_image.definition_hash()}}
    w.save()
    (w.state / "renderer" / H.HF_RECORD).write_text(json.dumps({"image_id": HF_ID, "tag": tag}))
    for key, value in w.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(box.shutil, "disk_usage", lambda path: Usage(10 ** 12, 0, 10 ** 12))
    (tmp_path / "work").mkdir()
    (tmp_path / "edl.json").write_text(json.dumps({"out_frames": 90, "fps": 30}))
    (tmp_path / "beats.json").write_text("{}")
    (tmp_path / "recording.mp4").write_bytes(b"recording")
    return w


def args_for(w, *more, base_only=True):
    t = w.tmp
    words = ["render", "--edl", t / "edl.json", "--beats", t / "beats.json", "--in", t / "recording.mp4", "--out", t / "out", "--platform-file", K.INSTAGRAM,
             "--vocabulary", K.VOCABULARY, "--work-dir", t / "work"] + (["--base-only"] if base_only else []) + list(more)
    return H.parser().parse_args([str(x) for x in words])


def run(w, monkeypatch, *more, fake=None, **kw):
    fake = fake or FakeRun()
    monkeypatch.setattr(box, "run", fake)
    return H.verb_render(args_for(w, *more, **kw)), fake


def run_folders(w):
    return [p.name for p in (w.tmp / "work").iterdir() if p.name.startswith("hf-")]


def option(command, flag):
    return command[command.index(flag) + 1]


# ---------------------------------------------------------------- the limits are in code, and the command says them

def test_the_drawing_containers_command_carries_every_limit_and_the_three_work_mounts(world, monkeypatch):
    result, fake = run(world, monkeypatch, "--dry-run", "--cpuset", "0-3", "--cpus", "4")
    command = result["commands"]["hf"]
    assert option(command, "--pids-limit") == "1024" and option(command, "--memory") == "6144m" and option(command, "--memory-swap") == "6144m"
    assert option(command, "--network") == "none" and option(command, "--cpus") == "4" and option(command, "--cpuset-cpus") == "0-3"
    assert "--shm-size" not in command and "--read-only" in command and option(command, "--cap-drop") == "ALL"
    assert option(command, "--label") == "%s=1" % H.HF_LABEL
    assert any(w.startswith("/scratch:") and "size=256m" in w for w in command) and any(w.startswith("/tmp:") and "size=512m" in w for w in command)
    mounts = [w.rsplit(":", 2)[1:] for i, w in enumerate(command) if command[i - 1] == "-v"]
    assert sorted(m[0] for m in mounts) == ["/work/out", "/work/project", "/work/tmp"] and all(m[1] == "rw" for m in mounts)
    inner = command[command.index(HF_ID) + 1:]
    assert inner[:3] == ["python3", "-I", "/opt/hf-run/hf_render.py"] and option(inner, "--fps") == "30" and option(inner, "--project") == "/work/project"
    assert fake.commands == [] and run_folders(world) == []


def test_the_cpu_set_reaches_every_stage_and_is_left_out_when_not_asked_for(world, monkeypatch):
    with_set, _ = run(world, monkeypatch, "--dry-run", "--cpuset", "0-3")
    assert all(option(with_set["commands"][s], "--cpuset-cpus") == "0-3" for s in H.STAGES)
    without, _ = run(world, monkeypatch, "--dry-run")
    assert all("--cpuset-cpus" not in without["commands"][s] for s in H.STAGES)
    assert without["limits"]["memory_mb"] == 6144 and without["limits"]["pids"] == 1024 and without["limits"]["workers"] == 4


def test_the_common_stages_mount_the_run_folders_pieces_where_the_spec_says(world, monkeypatch):
    result, _ = run(world, monkeypatch, "--dry-run")
    mounts = {s: [w.rsplit(":", 2)[1:] for i, w in enumerate(c) if c[i - 1] == "-v"] for s, c in result["commands"].items()}
    assert ["/work/project", "rw"] in mounts["page"] and ["/work/media", "rw"] in mounts["proxy"] and ["/work/hf", "ro"] in mounts["encode"]
    assert all(option(c, "--network") == "none" for c in result["commands"].values())


@pytest.mark.parametrize("memory", [4095, 4000, 1024])
def test_a_memory_below_the_least_the_proxied_render_passed_at_is_refused_before_docker(world, monkeypatch, memory):
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, "--memory-mb", str(memory))
    assert caught.value.code == "memory_too_small" and world.calls() == []


def test_the_least_memory_passes_and_one_above_the_boxs_maximum_is_refused(world, monkeypatch):
    run(world, monkeypatch, "--dry-run", "--memory-mb", "4096")
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, "--memory-mb", str(D.MAX_MEMORY_MB + 1))
    assert caught.value.code == "memory_too_large"


def test_a_render_without_base_only_and_without_an_engines_file_is_refused_engine_unknown_before_any_docker_call(world, monkeypatch, tmp_path):
    bare = tmp_path / "bare-blocks"
    shutil.copytree(K.BLOCKS, bare)
    os.unlink(bare / "engines" / "hyperframes.json")
    _blocks.write_pins(str(bare))
    monkeypatch.setenv("RENDERER_TEST", "1")
    monkeypatch.setenv("RENDERER_BLOCKS_DIR", str(bare))
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, base_only=False)
    assert (caught.value.code, caught.value.field) == ("engine_unknown", "hyperframes") and world.calls() == []


def test_there_is_no_gates_not_built_refusal_and_no_constant_that_turns_a_gate_off():
    source = (K.RENDERER / "hyperframes.py").read_text(encoding="utf-8")
    assert not hasattr(H, "GATES_BUILT") and "gates_not_built" not in source
    assert not any(word in source for word in ("--no-gate", "--skip-gate", "--no-gates", "RENDERER_NO_GATE"))


def test_a_render_that_draws_on_the_committed_blocks_is_not_refused_before_docker_and_runs_the_gates(world, monkeypatch):
    monkeypatch.delenv("RENDERER_TEST", raising=False)
    result, fake = run(world, monkeypatch, base_only=False)
    assert fake.verbs == ["hf-page", "proxy", "hf", "encode", "verify"] and "--boxes" in fake.seen["encode"] and "--measure" in fake.seen["hf_inner"]
    assert result["gate"]["pixel_ranges"] == 3


def test_a_bad_cpu_set_is_refused_before_docker(world, monkeypatch):
    for bad in ("", "3-1", "0;rm", "a"):
        with pytest.raises(Refusal) as caught:
            run(world, monkeypatch, "--dry-run", "--cpuset", bad)
        assert (caught.value.code, caught.value.field) == ("bad_cpuset", "cpuset")
    assert world.calls() == []


# ---------------------------------------------------------------- disk, time and the work folder

def test_a_work_folder_without_room_is_refused_before_any_container_runs(world, monkeypatch):
    monkeypatch.setattr(box.shutil, "disk_usage", lambda path: Usage(10 ** 9, 0, 10 ** 9))
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch)
    assert (caught.value.code, caught.value.field) == ("no_space", "work-dir")
    assert run_folders(world) == [] and world.runs() == []


def test_the_space_needed_is_the_proxy_the_intermediate_the_output_and_the_margin(world):
    assert H.space_needed(300.0) == _media.PROXY_MAX_BYTES + int(28 * 1024 ** 2 * 300) + 64 * 1024 ** 2 + D.MAX_OUT_BYTES + 1024 ** 3
    assert 11 * 1024 ** 3 < H.space_needed(300.0) < 12 * 1024 ** 3


def test_a_stage_that_would_get_under_thirty_seconds_is_refused_as_render_timeout(world, monkeypatch):
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, "--time-limit", "10")
    assert (caught.value.code, caught.value.field) == ("render_timeout", "page") and run_folders(world) == []
    with pytest.raises(Refusal) as late:
        H.left_for(time.monotonic() + 29, "encode")
    assert (late.value.code, late.value.field) == ("render_timeout", "encode")
    assert H.left_for(time.monotonic() + 100, "hf") >= 99


@pytest.mark.parametrize("make", ["relative", "missing", "link"])
def test_a_work_dir_that_is_not_an_absolute_real_folder_of_this_user_is_refused(world, monkeypatch, make):
    t = world.tmp
    (t / "link").symlink_to(t / "work")
    chosen = {"relative": "work", "missing": str(t / "nowhere"), "link": str(t / "link")}[make]
    with pytest.raises(Refusal) as caught:
        H.work_folder(chosen)
    assert (caught.value.code, caught.value.field) == ("bad_work_dir", "work-dir")
    assert H.work_folder(str(t / "work")) == str(t / "work")


# ---------------------------------------------------------------- a render, whole

def test_a_render_runs_five_containers_in_order_and_adds_what_the_engine_knows(world, monkeypatch):
    result, fake = run(world, monkeypatch)
    assert fake.verbs == ["hf-page", "proxy", "hf", "encode", "verify"] and len(fake.commands) == 5
    assert result["engine"] == "hyperframes" and result["layers"] == ["cuts", "zoom"] and result["verified"] is True
    assert set(result["stage_seconds"]) == {"page", "proxy", "hf", "encode"}
    assert result["proxy_sha256"] == SHA(PROXY_BYTES) and result["intermediate_sha256"] == SHA(HF_BYTES) and result["intermediate_bytes"] == len(HF_BYTES)
    assert result["memory_peak_bytes"] == 5000 and result["hyperframes"] == "0.9.19" and result["hf_image"] == {"id": HF_ID, "tag": H.hf_image.image_tag()}
    assert result["image"]["id"] == COMMON_ID and result["sha256"] == SHA(FINAL_BYTES) and result["replayed"] is False
    final = Path(result["path"])
    assert final == world.tmp / "out" / ("render-%s.mp4" % SHA(FINAL_BYTES)[:12]) and final.read_bytes() == FINAL_BYTES and stat.S_IMODE(final.stat().st_mode) == 0o400
    assert run_folders(world) == [] and fake.seen["timeout"] >= 30


def test_the_run_folder_is_gone_after_a_refusal_and_after_an_exception(world, monkeypatch):
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=FakeRun(fail={"hf": "refuse:font_not_allowed"}))
    assert (caught.value.code, caught.value.field) == ("font_not_allowed", "index.html") and run_folders(world) == []
    for stage in ("proxy", "hf"):
        with pytest.raises(RuntimeError):
            run(world, monkeypatch, fake=FakeRun(fail={stage: "raise"}))
        assert run_folders(world) == []
    assert not (world.tmp / "out").exists()


def test_an_intermediate_that_is_too_large_or_is_not_the_one_named_is_refused(world, monkeypatch):
    monkeypatch.setattr(H, "INTERMEDIATE_SLACK", 10)
    monkeypatch.setattr(H, "PRORES_BYTES_PER_SECOND", 1)
    with pytest.raises(Refusal) as large:
        run(world, monkeypatch)
    assert (large.value.code, large.value.field) == ("intermediate_too_large", "intermediate") and run_folders(world) == []
    monkeypatch.undo()
    for key, value in world.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(box.shutil, "disk_usage", lambda path: Usage(10 ** 12, 0, 10 ** 12))
    with pytest.raises(Refusal) as differs:
        run(world, monkeypatch, fake=FakeRun(hf_sha="0" * 64))
    assert (differs.value.code, differs.value.field) == ("intermediate_differs", "intermediate") and run_folders(world) == []


def test_a_proxy_over_its_cap_is_refused(world, monkeypatch):
    monkeypatch.setattr(_media, "PROXY_MAX_BYTES", 10)
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch)
    assert caught.value.code == "container_file_too_large" and caught.value.field == "proxy"


def test_a_drawing_container_that_left_a_link_or_an_unknown_file_is_refused(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "result.json").write_text(json.dumps({"ok": True, "sha256": "a" * 64, "bytes": 1, "seconds": 1, "hyperframes": "0.9.19", "memory_peak_bytes": None}))
    assert H.read_hf_result(str(out), 0)["bytes"] == 1
    (out / "extra.txt").write_text("x")
    with pytest.raises(Refusal) as unknown:
        H.read_hf_result(str(out), 0)
    assert unknown.value.code == "container_left_non_regular_file"
    (out / "extra.txt").unlink()
    (out / "hf.log").symlink_to(tmp_path)
    with pytest.raises(Refusal) as link:
        H.read_hf_result(str(out), 0)
    assert link.value.code == "container_left_non_regular_file"


def test_a_result_that_does_not_fit_its_schema_or_a_container_that_died_without_one_is_a_closed_failure(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(Refusal) as dead:
        H.read_hf_result(str(out), 137)
    assert (dead.value.code, dead.value.field) == ("container_killed", "container")
    (out / "result.json").write_text(json.dumps({"ok": True, "sha256": "not hex", "bytes": 1, "seconds": 1, "hyperframes": "0.9.19"}))
    with pytest.raises(Refusal) as bad:
        H.read_hf_result(str(out), 0)
    assert bad.value.code == "container_result_invalid"
    (out / "result.json").write_text(json.dumps({"ok": False, "code": "hf timeout!", "field": "render"}))
    with pytest.raises(Refusal) as row:
        H.read_hf_result(str(out), 1)
    assert row.value.code == "container_result_invalid"


# ---------------------------------------------------------------- a render that draws (V3b-1)

@pytest.fixture
def test_blocks(world, monkeypatch, tmp_path):
    """A copy of the committed blocks plus the HyperFrames engine's own file (renderat runtime, the oh: pages), used in test mode."""
    folder = tmp_path / "test-blocks"
    shutil.copytree(K.BLOCKS, folder)
    K.write_hf_compose_blocks(folder)
    monkeypatch.setenv("RENDERER_TEST", "1")
    monkeypatch.setenv("RENDERER_BLOCKS_DIR", str(folder))
    return folder


def pins_sha(folder) -> str:
    return SHA(Path(folder, "pins.json").read_bytes())


def test_the_blocks_folder_is_the_committed_one_unless_test_mode_names_another(tmp_path, monkeypatch):
    monkeypatch.delenv("RENDERER_TEST", raising=False)
    monkeypatch.setenv("RENDERER_BLOCKS_DIR", str(tmp_path))
    assert _blocks.blocks_dir() == _blocks.BLOCKS_DIR
    monkeypatch.setenv("RENDERER_TEST", "0")
    assert _blocks.blocks_dir() == _blocks.BLOCKS_DIR
    monkeypatch.setenv("RENDERER_TEST", "1")
    assert _blocks.blocks_dir() == str(tmp_path)
    monkeypatch.delenv("RENDERER_BLOCKS_DIR")
    assert _blocks.blocks_dir() == _blocks.BLOCKS_DIR


def test_a_composed_render_stages_the_blocks_and_passes_their_hash_to_the_page_stage(world, monkeypatch, test_blocks):
    result, _ = run(world, monkeypatch, "--dry-run", base_only=False)
    page = result["commands"]["page"]
    inner = page[page.index(COMMON_ID) + 1:]
    assert "--base-only" not in inner and option(inner, "--blocks") == "/job/blocks" and option(inner, "--blocks-sha256") == pins_sha(test_blocks)
    assert inner[2] == "hf-page" and option(inner, "--out") == "/work/project"
    assert run_folders(world) == []


def test_a_base_only_render_still_passes_base_only_and_no_blocks(world, monkeypatch, test_blocks):
    result, _ = run(world, monkeypatch, "--dry-run")
    inner = result["commands"]["page"][result["commands"]["page"].index(COMMON_ID) + 1:]
    assert inner[-1] == "--base-only" and "--blocks" not in inner and "--blocks-sha256" not in inner


def test_a_composed_render_returns_what_the_page_stage_drew(world, monkeypatch, test_blocks):
    result, fake = run(world, monkeypatch, base_only=False)
    assert fake.verbs == ["hf-page", "proxy", "hf", "encode", "verify"]
    assert result["layers"] == ["cuts", "zoom", "captions", "beats"] and result["engine"] == "hyperframes"
    assert result["blocks_sha256"] == pins_sha(test_blocks) and result["blocks"] == {"oh:caption": "c" * 64, "oh:keyword": "d" * 64}
    assert result["captions_drawn"] == 4 and result["beats_drawn"] == 2 and result["runtimes"] == {"oh:caption": "renderat", "oh:keyword": "renderat"}
    assert result["fonts_used"] == {"display": "inter-800.woff2", "text": "inter-500.woff2"} and result["verified"] is True
    assert run_folders(world) == []


def test_a_base_only_render_adds_none_of_the_composed_fields(world, monkeypatch, test_blocks):
    result, _ = run(world, monkeypatch)
    assert result["layers"] == ["cuts", "zoom"] and not set(H.COMPOSED_FIELDS) & set(result)


GATE_FLAGS = ("--boxes", "--boxes-sha256", "--beats", "--vocabulary", "--proxy", "--proxy-sha256")


def test_a_composed_renders_dry_run_has_the_measure_flag_the_gates_flags_and_the_media_mount(world, monkeypatch, test_blocks):
    result, fake = run(world, monkeypatch, "--dry-run", base_only=False)
    hf_inner = result["commands"]["hf"][result["commands"]["hf"].index(HF_ID) + 1:]
    assert hf_inner[-1] == "--measure" and fake.commands == []
    encode = result["commands"]["encode"]
    inner = encode[encode.index(COMMON_ID) + 1:]
    assert inner[2] == "encode" and all(flag in inner for flag in GATE_FLAGS)
    assert option(inner, "--boxes") == "/work/hf/boxes.json" and option(inner, "--proxy") == "/work/media/proxy.mp4"
    assert option(inner, "--beats").startswith("/job/") and option(inner, "--vocabulary").startswith("/job/")
    mounts = [w.rsplit(":", 2)[1:] for i, w in enumerate(encode) if encode[i - 1] == "-v"]
    assert ["/work/hf", "ro"] in mounts and ["/work/media", "ro"] in mounts and option(encode, "--network") == "none"
    assert run_folders(world) == []


def test_a_base_only_renders_dry_run_has_no_measure_flag_no_gates_flags_and_no_media_mount(world, monkeypatch, test_blocks):
    result, _ = run(world, monkeypatch, "--dry-run")
    assert "--measure" not in result["commands"]["hf"]
    encode = result["commands"]["encode"]
    assert not any(flag in encode for flag in GATE_FLAGS) and ["/work/media", "ro"] not in [w.rsplit(":", 2)[1:] for i, w in enumerate(encode) if encode[i - 1] == "-v"]


def test_a_composed_render_hands_the_encode_the_boxes_and_proxy_hashes_the_host_computed(world, monkeypatch, test_blocks):
    result, fake = run(world, monkeypatch, base_only=False)
    inner = fake.seen["encode"]
    assert option(inner, "--boxes-sha256") == SHA(BOXES_BYTES) and option(inner, "--proxy-sha256") == SHA(PROXY_BYTES) == result["proxy_sha256"]
    assert fake.seen["encode_mounts"]["/work/media"][1] == "ro" and fake.seen["encode_mounts"]["/work/hf"][1] == "ro"


def test_a_composed_render_reports_the_gate_and_the_two_new_stage_seconds_and_nothing_loose(world, monkeypatch, test_blocks):
    result, _ = run(world, monkeypatch, base_only=False)
    assert result["gate"] == {"frames": 90, "boxes": 12, "lowest_caption_bottom": 1544.5, "pixel_min_psnr_db": 41.25, "pixel_ranges": 3}
    assert set(result["stage_seconds"]) == {"page", "proxy", "hf", "encode", "measure", "pixel"}
    assert result["stage_seconds"]["measure"] == 2.5 and result["stage_seconds"]["pixel"] == 6.5
    assert not {"gate_frames", "gate_boxes", "pixel_min_psnr_db", "pixel_ranges", "pixel_seconds", "lowest_caption_bottom", "boxes_sha256"} & set(result)


def test_a_composed_render_with_no_caption_box_has_no_lowest_caption_bottom(world, monkeypatch, test_blocks):
    gate = {k: v for k, v in GATE.items() if k != "lowest_caption_bottom"}
    result, _ = run(world, monkeypatch, fake=FakeRun(gate=gate), base_only=False)
    assert "lowest_caption_bottom" not in result["gate"] and result["gate"]["boxes"] == 12


def test_a_base_only_render_has_no_gate_and_the_two_old_stage_seconds_only(world, monkeypatch, test_blocks):
    result, fake = run(world, monkeypatch)
    assert "gate" not in result and set(result["stage_seconds"]) == {"page", "proxy", "hf", "encode"}
    assert "--measure" not in fake.seen["hf_inner"] and "--boxes" not in fake.seen["encode"]


def test_a_composed_render_whose_drawing_container_left_no_boxes_is_refused_and_nothing_is_encoded(world, monkeypatch, test_blocks):
    fake = FakeRun(boxes=None)
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=fake, base_only=False)
    assert (caught.value.code, caught.value.field) == ("container_wrote_no_file", "boxes") and fake.verbs == ["hf-page", "proxy", "hf"] and run_folders(world) == []


def test_boxes_that_are_not_the_ones_the_container_named_or_not_a_regular_file_or_too_large_are_refused(world, monkeypatch, test_blocks):
    with pytest.raises(Refusal) as differs:
        run(world, monkeypatch, fake=FakeRun(boxes_sha="0" * 64), base_only=False)
    assert (differs.value.code, differs.value.field) == ("container_file_differs", "boxes")
    monkeypatch.setattr(H, "BOXES_MAX_BYTES", 10)
    with pytest.raises(Refusal) as large:
        run(world, monkeypatch, base_only=False)
    assert (large.value.code, large.value.field) == ("container_file_too_large", "boxes") and run_folders(world) == []


def test_a_boxes_file_that_is_a_link_is_refused(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (tmp_path / "elsewhere").write_bytes(BOXES_BYTES)
    (out / "boxes.json").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(Refusal) as caught:
        H.check_boxes_file(str(out), {"boxes_sha256": SHA(BOXES_BYTES), "measure_seconds": 1.0})
    assert (caught.value.code, caught.value.field) == ("container_file_not_regular", "boxes")


def test_a_drawing_result_with_no_measure_seconds_is_refused_for_a_composed_render(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "boxes.json").write_bytes(BOXES_BYTES)
    assert H.check_boxes_file(str(out), {"boxes_sha256": SHA(BOXES_BYTES), "measure_seconds": 0.0}) == SHA(BOXES_BYTES)
    with pytest.raises(Refusal) as caught:
        H.check_boxes_file(str(out), {"boxes_sha256": SHA(BOXES_BYTES)})
    assert caught.value.code == "container_file_differs"


def test_an_encode_stage_that_reports_no_gate_for_a_render_that_draws_is_a_closed_failure(world, monkeypatch, test_blocks):
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=FakeRun(gate={"gate_frames": 90}), base_only=False)
    assert (caught.value.code, caught.value.field) == ("container_result_invalid", "encode") and run_folders(world) == []
    with pytest.raises(Refusal) as none:
        run(world, monkeypatch, fake=FakeRun(gate=None), base_only=False)
    assert (none.value.code, none.value.field) == ("container_result_invalid", "encode")


@pytest.mark.parametrize("code", ["overlay_hits_face", "caption_below_line", "face_pixels_changed", "boxes_changed"])
def test_a_refusal_of_the_gates_in_the_encode_container_is_the_same_refusal_here_and_leaves_no_run_folder(world, monkeypatch, test_blocks, code):
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=FakeRun(fail={"encode": "refuse:" + code}), base_only=False)
    assert (caught.value.code, caught.value.field) == (code, "frame 3 hf-inst-1") and run_folders(world) == [] and not (world.tmp / "out").exists()


def test_a_refusal_of_the_measure_step_comes_through_the_drawing_containers_result(world, monkeypatch, test_blocks):
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=FakeRun(fail={"hf": "refuse:font_not_allowed"}), base_only=False)
    assert caught.value.code == "font_not_allowed" and run_folders(world) == []


def test_boxes_json_is_a_name_the_drawing_container_may_leave_and_any_other_is_still_refused(tmp_path):
    assert "boxes.json" in H.HF_OUT_NAMES and H.HF_OUT_NAMES == ("intermediate.mov", "result.json", "hf.log", "boxes.json")
    out = tmp_path / "out"
    out.mkdir()
    (out / "result.json").write_text(json.dumps({"ok": True, "sha256": "a" * 64, "bytes": 1, "seconds": 1, "hyperframes": "0.9.19", "memory_peak_bytes": None,
                                                 "boxes_sha256": "b" * 64, "measure_seconds": 2.0}))
    (out / "boxes.json").write_bytes(BOXES_BYTES)
    result = H.read_hf_result(str(out), 0)
    assert result["boxes_sha256"] == "b" * 64 and result["measure_seconds"] == 2.0
    (out / "boxes2.json").write_bytes(b"{}")
    with pytest.raises(Refusal) as caught:
        H.read_hf_result(str(out), 0)
    assert caught.value.code == "container_left_non_regular_file"


def test_the_hf_result_schema_has_the_two_optional_measure_fields():
    keys = H.HF_SCHEMA[1]
    assert {"boxes_sha256", "measure_seconds"} <= set(keys)
    base = D.sanitise({"ok": True, "sha256": "a" * 64, "bytes": 1, "seconds": 1.0, "hyperframes": "0.9.19"}, H.HF_SCHEMA, "hf")
    assert "boxes_sha256" not in base and "measure_seconds" not in base


def test_a_page_stage_that_reports_other_blocks_than_the_ones_staged_is_refused_and_nothing_else_runs(world, monkeypatch, test_blocks):
    fake = FakeRun(page_blocks_sha="0" * 64)
    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=fake, base_only=False)
    assert (caught.value.code, caught.value.field) == ("blocks_changed", "blocks") and fake.verbs == ["hf-page"] and run_folders(world) == []


def test_a_page_stage_that_leaves_out_a_composed_field_is_a_closed_failure(world, monkeypatch, test_blocks):
    class Short(FakeRun):
        def __call__(self, command, name, timeout, **kw):
            done = super().__call__(command, name, timeout, **kw)
            if self.verbs[-1] == "hf-page":
                out = Path([c.rsplit(":", 2)[0] for i, c in enumerate(command) if command[i - 1] == "-v" and c.endswith(":/out:rw")][0], "result.json")
                row = json.loads(out.read_text())
                del row["fonts_used"]
                out.write_text(json.dumps(row))
            return done

    with pytest.raises(Refusal) as caught:
        run(world, monkeypatch, fake=Short(), base_only=False)
    assert (caught.value.code, caught.value.field) == ("container_result_invalid", "hf-page") and run_folders(world) == []


def test_a_render_that_draws_outside_test_mode_runs_the_gates_whatever_the_blocks_folder_is(world, monkeypatch, test_blocks):
    monkeypatch.delenv("RENDERER_TEST")
    monkeypatch.setattr(_blocks, "BLOCKS_DIR", str(test_blocks))
    result, fake = run(world, monkeypatch, base_only=False)
    assert result["gate"]["boxes"] == 12 and "--boxes" in fake.seen["encode"]


def test_the_composed_page_stage_result_has_the_closed_schema():
    keys = D.RESULT_SCHEMAS["hf-page"][1]
    assert {"blocks", "blocks_sha256", "captions_drawn", "beats_drawn", "runtimes", "fonts_used"} <= set(keys)
    base = D.sanitise({"ok": True, "page_sha256": "a" * 64, "vars_sha256": "b" * 64, "clips": 1, "zooms": 0, "duration": 1.0, "fps": 30, "layers": ["cuts"]},
                      D.RESULT_SCHEMAS["hf-page"], "hf-page")
    assert set(base) == {"ok", "page_sha256", "vars_sha256", "clips", "zooms", "duration", "fps", "layers"}


# ---------------------------------------------------------------- the HyperFrames image: check, build, record, reap

def test_check_hf_image_names_the_three_ways_the_image_is_not_ready_and_the_command_that_fixes_them(world):
    tag, own = H.hf_image.image_tag(), world.state / "renderer" / H.HF_RECORD
    assert H.check_hf_image()["id"] == HF_ID
    own.write_text(json.dumps({"image_id": "sha256:" + "00" * 32}))
    with pytest.raises(NotConfigured) as unrecorded:
        H.check_hf_image()
    assert (unrecorded.value.code, unrecorded.value.field) == ("hf_image_not_recorded", tag)
    own.unlink()
    with pytest.raises(NotConfigured) as missing_record:
        H.check_hf_image()
    assert missing_record.value.code == "hf_image_not_recorded"
    own.write_text(json.dumps({"image_id": HF_ID}))
    world.cfg["images"][tag]["Labels"][D.LABEL_DEFINITION] = "0" * 64
    world.save()
    with pytest.raises(NotConfigured) as stale:
        H.check_hf_image()
    assert stale.value.code == "hf_image_stale"
    del world.cfg["images"][tag]
    world.save()
    with pytest.raises(NotConfigured) as absent:
        H.check_hf_image()
    assert absent.value.code == "hf_image_not_built"
    assert all("hyperframes.py build --confirmed" in H.HINTS[c] for c in ("hf_image_not_built", "hf_image_stale", "hf_image_not_recorded"))


def test_a_render_with_no_hf_image_exits_3_with_the_hint_before_any_container_runs(world, monkeypatch, capsys):
    fake = FakeRun()
    monkeypatch.setattr(box, "run", fake)
    del world.cfg["images"][H.hf_image.image_tag()]
    world.save()
    t = world.tmp
    code = H.main(["render", "--edl", str(t / "edl.json"), "--beats", str(t / "beats.json"), "--in", str(t / "recording.mp4"), "--out", str(t / "out"),
                   "--platform-file", str(K.INSTAGRAM), "--vocabulary", str(K.VOCABULARY), "--base-only", "--work-dir", str(t / "work")])
    err = capsys.readouterr().err
    assert code == 3 and "refused: hf_image_not_built" in err and "hyperframes.py build --confirmed" in err and fake.commands == []


def test_build_dry_run_prints_the_command_and_confirmed_writes_the_record_mode_0600(world, monkeypatch, capsys):
    assert H.main(["build"]) == 2 and H.main(["build", "--dry-run", "--confirmed"]) == 2
    assert H.main(["build", "--dry-run", "--arch", "arm64"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["dry_run"] is True and printed["command"] == H.hf_image.build_command("arm64") and printed["arch"] == "arm64"
    built = {"image_id": HF_ID, "tag": H.hf_image.image_tag(), "definition": H.hf_image.definition_hash(), "arch": "arm64"}
    asked = []
    monkeypatch.setattr(H.hf_image, "daemon_arch", lambda: "arm64")
    monkeypatch.setattr(H.hf_image, "build_image", lambda arch: asked.append(arch) or dict(built))
    assert H.main(["build", "--confirmed"]) == 0
    path = world.state / "renderer" / H.HF_RECORD
    record = json.loads(path.read_text())
    assert asked == ["arm64"] and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert {k: record[k] for k in built} == built and record["built_at"].endswith("Z") and len(record["built_at"]) == 20
    assert H.main(["build", "--confirmed", "--arch", "amd64"]) == 2           # a build is for the daemon's own architecture
    assert asked == ["arm64"]


def test_a_failed_or_unconfigured_build_writes_no_record(world, monkeypatch, capsys):
    path = world.state / "renderer" / H.HF_RECORD
    path.unlink()
    monkeypatch.setattr(H.hf_image, "daemon_arch", lambda: "arm64")

    def failing(arch):
        raise H.hf_image.ProviderError("the build failed: step 7", 1)

    monkeypatch.setattr(H.hf_image, "build_image", failing)
    assert H.main(["build", "--confirmed"]) == 1 and not path.exists()
    monkeypatch.setattr(H.hf_image, "build_image", lambda arch: (_ for _ in ()).throw(H.hf_image.ProviderError("no sha256", 3)))
    assert H.main(["build", "--confirmed"]) == 3 and not path.exists()


def test_reap_removes_only_hf_run_folders_older_than_the_cutoff_and_never_follows_a_link(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    old, new = time.time() - (D.MAX_TIMEOUT + 3600), time.time()
    names = {"hf-0123456789ab": old, "hf-aaaaaaaaaaaa": new, "hf-0123456789a": old, "hf-0123456789abc": old, "hf-0123456789gh": old, "other": old, ".job-0123456789ab": old}
    for name, mtime in names.items():
        (root / name).mkdir()
        (root / name / "inside").write_text("x")
        os.utime(root / name, (mtime, mtime))
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / "keep").write_text("x")
    (root / "hf-bbbbbbbbbbbb").symlink_to(target)
    assert H.reap_hf_folders(str(root)) == 1
    assert sorted(p.name for p in root.iterdir()) == sorted(set(names) - {"hf-0123456789ab"} | {"hf-bbbbbbbbbbbb"}) and (target / "keep").exists()


def test_check_runs_both_images_selfchecks_and_fails_when_the_drawing_images_does(world, monkeypatch, capsys):
    fake = FakeRun()
    monkeypatch.setattr(box, "run", fake)
    good = {"ok": True, "image": HF_ID, "checks": []}
    monkeypatch.setattr(H.hf_image, "selfcheck", lambda image: dict(good))
    assert H.main(["--check"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and out["hf_image"]["id"] == HF_ID and out["image"]["id"] == COMMON_ID and out["selfcheck"]["ffmpeg"].startswith("ffmpeg")
    monkeypatch.setattr(H.hf_image, "selfcheck", lambda image: dict(good, ok=False))
    assert H.main(["--check"]) == 1 and json.loads(capsys.readouterr().out)["ok"] is False
    assert H.main(["--check", "extra"]) == 2


# ---------------------------------------------------------------- what the module may import

def test_hyperframes_py_imports_nothing_of_the_drawing_part_of_the_ffmpeg_engine():
    tree = ast.parse((K.RENDERER / "hyperframes.py").read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    assert not found & {"_frames", "_cdp", "_render", "_preview", "_browser", "_lint", "ffmpeg"}, sorted(found)
    assert {"_docker", "_host", "_container", "_media", "_output"} <= found


def test_the_class_default_stays_ffmpeg_and_the_two_engines_serve_the_same_common_verbs():
    assert set(_host.COMMON_HANDLERS) <= set(H.VERBS) and {"render", "build", "reap"} <= set(H.VERBS)


# ---------------------------------------------------------------- the scripts start on their own

@pytest.mark.parametrize("args", [["--help"], ["build", "--help"], ["render", "--help"]])
def test_hyperframes_py_starts_as_a_script_from_a_clean_environment(args):
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    done = subprocess.run([sys.executable, str(K.RENDERER / "hyperframes.py"), *args], capture_output=True, text=True, env=env, timeout=120, cwd="/")
    assert done.returncode == 0 and "usage" in (done.stdout + done.stderr).lower(), done.stderr[-800:]


def test_hf_render_py_starts_as_a_script_from_a_clean_environment():
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/nonexistent")}
    done = subprocess.run([sys.executable, "-I", str(K.RENDERER / "hyperframes-image" / "hf_render.py"), "--help"], capture_output=True, text=True, env=env,
                          timeout=60, cwd="/")
    assert done.returncode == 0 and "--project" in done.stdout, done.stderr[-800:]


def test_what_the_page_reported_comes_through_the_drawing_containers_refusal_as_problems(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "result.json").write_text(json.dumps({"ok": False, "code": "measure_failed", "field": "player", "problems": [
        {"code": "page_error", "field": "TypeError Cannot read properties of undefined"}, {"code": "state", "field": "player undefined timelines main"}]}))
    with pytest.raises(Refusal) as caught:
        H.read_hf_result(str(out), 1)
    assert (caught.value.code, caught.value.field) == ("measure_failed", "player")
    assert [p["code"] for p in caught.value.problems] == ["page_error", "state"] and caught.value.problems[1]["field"] == "player undefined timelines main"
    (out / "result.json").write_text(json.dumps({"ok": False, "code": "measure_failed", "field": "player", "problems": [{"code": "x y", "field": "z"}]}))
    with pytest.raises(Refusal) as bad:
        H.read_hf_result(str(out), 1)
    assert bad.value.code == "container_result_invalid"


def test_a_block_escaped_refusal_of_the_measure_step_reaches_the_host_as_the_renders_refusal(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "result.json").write_text(json.dumps({"ok": False, "code": "block_escaped", "field": "frame 7", "problems": []}))
    with pytest.raises(Refusal) as caught:
        H.read_hf_result(str(out), 1)
    assert (caught.value.code, caught.value.field) == ("block_escaped", "frame 7")


def test_the_pages_ready_time_is_in_the_drawing_result_schema_and_in_a_composed_renders_result(world, monkeypatch, test_blocks):
    assert "measure_ready_ms" in H.HF_SCHEMA[1]
    result, _ = run(world, monkeypatch, base_only=False)
    assert "measure_ready_ms" not in result                     # the fake container reports none

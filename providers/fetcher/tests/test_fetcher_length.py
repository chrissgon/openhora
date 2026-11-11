"""A video with no stated length (V7e): the caps are computed from the same inputs whatever the details say, the length is read from the file inside the
container, and a file that is too long or whose length is known from nowhere never enters the reference folder. Fake docker; fictional names."""
from __future__ import annotations

import json
import os
import re

import pytest

import fetcher_kit as K
import ytdlp


@pytest.fixture
def world(tmp_path, monkeypatch):
    return K.World(tmp_path, monkeypatch, fetch_files={"video.mp4": K.text("x" * 64)})


def stated(world, duration):
    (world.ref / "info.json").write_text(json.dumps(dict(K.INFO, duration=duration)))


def leftovers(world):
    return sorted(n for n in os.listdir(world.ref) if n.startswith(".fetch-") or n.startswith("video."))


def masked(argv):
    return [re.sub(r"[0-9a-f]{12}", "TOKEN", word) for word in argv]


def shape(world):
    """The proxy and fetch commands of the run, the run token masked and the deadline (a clock reading) removed."""
    out = []
    for argv in world.runs():
        words = masked(argv)
        out.append([w for w in words if not w.startswith("org.openhora.deadline") and not re.fullmatch(r"[0-9]{10}", w)])
    return out


def test_an_unknown_length_runs_under_the_same_caps(world, monkeypatch):
    monkeypatch.setattr(ytdlp.time, "time", lambda: 1_800_000_000.0)
    world.cfg["fetch_seconds"] = 120.0
    world.save()
    stated(world, 120)
    code, out, _ = world.fetch("--timeout", 200, stage="video")
    assert code == 0
    with_length = shape(world)
    (world.ref / "video.mp4").unlink()
    (world.config / "calls.jsonl").unlink()
    stated(world, None)
    code, out, _ = world.fetch("--timeout", 200, stage="video")
    assert code == 0 and out["duration"] == 120.0
    assert shape(world) == with_length and len(with_length) == 2, "the proxy and the fetch commands are equal word for word"
    flat = " ".join(with_length[1])
    assert "--max-bytes" in flat and "--timeout 190" in flat


@pytest.mark.parametrize("seconds,stated_value,code,duration", [(None, None, "no_duration", None), (301.0, None, "too_long", None), (301.0, 100, "too_long", None)])
def test_a_file_too_long_or_with_no_length_from_anywhere_is_never_kept(world, seconds, stated_value, code, duration):
    world.cfg["fetch_seconds"] = seconds
    world.save()
    stated(world, stated_value)
    exit_code, out, _ = world.fetch(stage="video")
    assert (exit_code, out) == (1, {"ok": False, "code": code})
    assert leftovers(world) == [] and sorted(os.listdir(world.ref)) == ["info.json"]


@pytest.mark.parametrize("seconds,stated_value,duration", [(None, 120, 120), (42.0, None, 42.0), (42.0, 120, 42.0)])
def test_a_length_from_the_file_or_from_the_platform_is_enough_and_the_file_wins(world, seconds, stated_value, duration):
    world.cfg["fetch_seconds"] = seconds
    world.save()
    stated(world, stated_value)
    exit_code, out, _ = world.fetch(stage="video")
    assert exit_code == 0 and out["duration"] == duration and (world.ref / "video.mp4").exists()


def test_a_container_that_reports_too_long_leaves_nothing(world):
    world.cfg["fetch_files"] = {}
    world.cfg["fetch_result"] = {"ok": False, "code": "too_long", "exit": 0, "seconds": 301.0}
    world.save()
    stated(world, None)
    assert world.fetch(stage="video")[1] == {"ok": False, "code": "too_long"} and leftovers(world) == []


@pytest.mark.parametrize("result", [{"ok": True, "code": None, "exit": 0, "seconds": None, "extra": 1}, {"ok": True, "code": None, "exit": 0, "seconds": "42"},
                                    {"ok": True, "code": None, "exit": 0, "seconds": -1}, {"ok": True, "code": None, "exit": 0, "seconds": 0},
                                    {"ok": True, "code": None, "exit": 0, "seconds": 90000}, {"ok": True, "code": None, "exit": 0, "seconds": True},
                                    {"ok": True, "code": None, "exit": 0}])
def test_a_result_that_is_not_the_closed_shape_is_not_trusted(world, result):
    world.cfg["fetch_result"] = result
    world.save()
    stated(world, 42)
    assert world.fetch(stage="video")[1] == {"ok": False, "code": "fetch_failed"} and leftovers(world) == []

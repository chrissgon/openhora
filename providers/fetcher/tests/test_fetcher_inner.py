"""The container's own code (`_inner.py` fetch and the host's collection of what it leaves), against a stand-in tool and the fake docker."""
from __future__ import annotations

import json
import os
import sys

import pytest

import fetcher_kit as K
import _inner
import ytdlp

RAW = {"id": "4242", "extractor_key": "AsterVideo", "duration": 42.5, "width": 720, "height": 1280, "fps": 30, "upload_date": "20990101",
       "title": "T" * 400, "description": "D" * 3000, "view_count": 10, "like_count": 2, "comment_count": None,
       "uploader": "Bram Hollow", "webpage_url": "https://www.aster.example/v/4242", "formats": [{"url": "https://cdn.aster.example/x"}],
       "subtitles": {"en": [{"ext": "vtt"}]}}


def test_the_info_file_is_cut_to_a_few_fields_and_holds_no_url_uploader_or_format_list():
    cut = _inner.sanitise_info(RAW, "manual")
    assert set(cut) == set(_inner.INFO_KEYS) | {"subtitles"}
    text = json.dumps(cut)
    for word in ("uploader", "Bram", "webpage_url", "formats", "cdn.aster"):
        assert word not in text
    assert len(cut["title"]) == 300 and len(cut["description"]) == 2000 and cut["subtitles"] == "manual" and cut["comment_count"] is None


def folder(tmp_path, files):
    for name, size in files.items():
        (tmp_path / name).write_bytes(b"x" * size)
    return str(tmp_path)


def test_more_than_four_subtitle_files_are_cut_to_four_and_an_oversized_one_is_removed(tmp_path):
    names = {"ref.%s.vtt" % lang: 10 for lang in ("en", "pt", "es", "fr", "de", "it")}
    names["ref.ja.vtt"] = (1 << 20) + 1
    names["ref.info.json"] = 0
    (tmp_path / "ref.info.json").write_text(json.dumps(RAW))
    for name, size in names.items():
        if name != "ref.info.json":
            (tmp_path / name).write_bytes(b"x" * size)
    assert _inner.tidy(str(tmp_path), "meta", 1 << 20) is None
    left = sorted(os.listdir(tmp_path))
    subs = [n for n in left if n.startswith("subs.")]
    assert len(subs) == 4 and "subs.ja.vtt" not in left and "info.json" in left and "ref.info.json" not in left
    assert json.loads((tmp_path / "info.json").read_text())["subtitles"] == "manual"


def test_a_second_track_of_one_language_is_not_kept_and_with_no_file_the_subtitles_are_none(tmp_path):
    (tmp_path / "ref.info.json").write_text(json.dumps(dict(RAW, subtitles={})))
    (tmp_path / "ref.en.vtt").write_bytes(b"x")
    (tmp_path / "ref.en-orig.vtt").write_bytes(b"y")
    _inner.tidy(str(tmp_path), "meta", 1 << 20)
    assert sorted(os.listdir(tmp_path)) == ["info.json", "subs.en.vtt"] and json.loads((tmp_path / "info.json").read_text())["subtitles"] == "auto"
    other = tmp_path / "b"
    other.mkdir()
    (other / "ref.info.json").write_text(json.dumps(RAW))
    _inner.tidy(str(other), "meta", 1 << 20)
    assert json.loads((other / "info.json").read_text())["subtitles"] == "none"


def test_the_video_stage_keeps_one_video_renamed_and_removes_everything_else(tmp_path):
    folder(tmp_path, {"ref.mp4": 100, "ref.mp4.part": 5, "ref.info.json": 3, "junk.txt": 1})
    assert _inner.tidy(str(tmp_path), "video", 1000) is None
    assert sorted(os.listdir(tmp_path)) == ["video.mp4"]


def test_a_video_over_its_cap_is_removed_and_reported_too_large(tmp_path):
    folder(tmp_path, {"ref.mp4": 2000})
    assert _inner.tidy(str(tmp_path), "video", 1000) == "too_large" and os.listdir(tmp_path) == []


def stand_in(tmp_path, body):
    script = tmp_path / "tool.py"
    script.write_text("import os, sys\nout = os.environ['FAKE_OUT']\n" + body)
    return str(script)


def inner_args(out, stage="meta"):
    return ["--result", os.path.join(out, "result.json"), "fetch", "--stage", stage, "--url", "https://www.aster.example/v/1", "--extractors", "AsterVideo",
            "--proxy-url", "http://openhora-fetch-proxy-0123456789ab:8888", "--max-seconds", "300", "--max-bytes", "100000", "--langs", "en.*", "--timeout", "20"]


def test_a_fetch_that_ends_well_writes_an_ok_result_and_the_kept_files(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("FAKE_OUT", str(out))
    monkeypatch.setattr(_inner, "TOOL", stand_in(tmp_path, "import json\nopen(os.path.join(out,'ref.info.json'),'w').write(json.dumps({'id':'1','duration':3}))\n"
                                                           "open(os.path.join(out,'ref.en.vtt'),'w').write('WEBVTT')\n"))
    assert _inner.main(inner_args(str(out))) == 0
    assert json.loads((out / "result.json").read_text()) == {"ok": True, "code": None, "exit": 0}
    assert sorted(os.listdir(out)) == ["info.json", "result.json", "subs.en.vtt"]


def test_a_tool_that_fails_or_writes_nothing_is_fetch_failed_and_one_that_hangs_is_time_limit(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("FAKE_OUT", str(out))
    monkeypatch.setattr(_inner, "TOOL", stand_in(tmp_path, "sys.exit(1)\n"))
    assert _inner.main(inner_args(str(out))) == 1 and json.loads((out / "result.json").read_text())["code"] == "fetch_failed"
    monkeypatch.setattr(_inner, "TOOL", stand_in(tmp_path, "sys.exit(0)\n"))
    assert _inner.main(inner_args(str(out))) == 1 and json.loads((out / "result.json").read_text())["code"] == "fetch_failed"
    monkeypatch.setattr(_inner, "TOOL", stand_in(tmp_path, "import time\ntime.sleep(30)\n"))
    args = inner_args(str(out))
    args[args.index("--timeout") + 1] = "1"
    assert _inner.main(args) == 1 and json.loads((out / "result.json").read_text())["code"] == "time_limit"


def test_the_tool_is_started_with_a_checked_argument_list_only(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("FAKE_OUT", str(out))
    monkeypatch.setattr(_inner, "TOOL", stand_in(tmp_path, "open(os.path.join(out,'argv.txt'),'w').write('\\n'.join(sys.argv[1:]))\nsys.exit(1)\n"))
    seen = []
    real = _inner.subprocess.run

    def spy(command, **kw):
        seen.append(list(command))
        return real(command, **kw)
    monkeypatch.setattr(_inner.subprocess, "run", spy)
    _inner.main(inner_args(str(out)))
    assert seen and seen[0][:2] == [sys.executable, "-I"] and "--ignore-config" in seen[0] and "--cookies" not in seen[0]


# --- the host's collection ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def world(tmp_path, monkeypatch):
    return K.World(tmp_path, monkeypatch, fetch_files={"info.json": K.text(dict(K.INFO)), "subs.en.vtt": K.text("WEBVTT\n")})


def leftovers(world):
    return [n for n in os.listdir(world.ref) if n.startswith(".fetch-")]


def test_the_kept_files_move_into_the_reference_folder_with_a_hard_link_and_the_run_folder_goes(world):
    code, out, _ = world.fetch()
    assert code == 0 and sorted(f["name"] for f in out["files"]) == ["info.json", "proxy.json", "subs.en.vtt"]
    assert sorted(os.listdir(world.ref)) == ["info.json", "proxy.json", "subs.en.vtt"]
    for entry in out["files"]:
        assert len(entry["sha256"]) == 64 and entry["size"] == os.path.getsize(world.ref / entry["name"])
    assert out["duration"] == 42.5 and out["width"] == 720 and out["subtitles"] == "auto" and out["tool"] == K.PIN["version"]
    assert out["refused_hosts"] == 0 and out["bytes"] == 1000
    assert (world.ref / "info.json").stat().st_nlink >= 1 and leftovers(world) == []
    text = json.dumps(out)
    for word in ("Aster", "Bram", "aster.example", "www."):
        assert word not in text, "the answer holds no link, title or host"


def test_a_name_that_is_taken_is_refused_and_nothing_moves(world):
    (world.ref / "subs.en.vtt").write_text("mine")
    code, out, _ = world.fetch()
    assert (code, out) == (2, {"ok": False, "code": "out_refused"})
    assert (world.ref / "subs.en.vtt").read_text() == "mine" and not (world.ref / "info.json").exists() and leftovers(world) == []


def test_the_run_folder_and_the_networks_are_gone_after_a_failure(world):
    world.cfg["fetch_rc"], world.cfg["fetch_result"] = 1, {"ok": False, "code": "fetch_failed", "exit": 1}
    world.save()
    code, out, err = world.fetch()
    assert (code, out) == (1, {"ok": False, "code": "fetch_failed"}) and "out of date" in err
    assert leftovers(world) == [] and os.listdir(world.ref) == []
    assert sum(1 for n in world.networks() if n[1] == "rm") == 2


@pytest.mark.parametrize("files", [{"extra.bin": {"kind": "text", "text": "x"}}, {"subs.en.vtt": {"kind": "link", "target": "/etc/passwd"}},
                                   {"subs.en.vtt": {"kind": "fifo"}}, {"subs.en.vtt": {"kind": "big", "size": (1 << 20) + 1}},
                                   {"info.json": {"kind": "big", "size": (1 << 20) + 1}}, {"video.mp4": {"kind": "text", "text": "x"}}])
def test_a_container_that_leaves_anything_but_the_files_it_may_leave_is_refused(world, files):
    world.cfg["fetch_files"] = dict(world.cfg["fetch_files"], **files)
    world.save()
    code, out, _ = world.fetch()
    assert (code, out) == (1, {"ok": False, "code": "fetch_failed"}) and os.listdir(world.ref) == []


def test_a_malformed_result_or_details_file_is_not_trusted(world):
    world.cfg["fetch_result"] = {"ok": True, "code": "anything", "exit": 0}
    world.save()
    assert world.fetch()[1] == {"ok": False, "code": "fetch_failed"}
    world.cfg["fetch_result"] = None
    world.save()
    assert world.fetch()[1] == {"ok": False, "code": "fetch_failed"}
    world.cfg["fetch_result"] = {"ok": True, "code": None, "exit": 0}
    world.cfg["fetch_files"]["info.json"] = K.text(dict(K.INFO, uploader="x"))
    world.save()
    assert world.fetch()[1] == {"ok": False, "code": "fetch_failed"}


def test_refused_hosts_with_no_file_are_the_network_code_and_a_spent_cap_is_too_large(world):
    world.cfg["fetch_files"] = {}
    world.cfg["fetch_result"] = {"ok": False, "code": "fetch_failed", "exit": 1}
    world.cfg["proxy_report"] = {"allowed": 0, "refused": 2, "refused_hosts": ["cdn.other.example"], "sni_refused": 0, "bytes": 0}
    world.save()
    assert world.fetch()[1] == {"ok": False, "code": "network"}
    world.cfg["proxy_report"] = {"allowed": 1, "refused": 0, "refused_hosts": [], "sni_refused": 0, "bytes": 10 ** 9}
    world.save()
    assert world.fetch()[1] == {"ok": False, "code": "too_large"}
    world.cfg["fetch_result"] = {"ok": False, "code": "time_limit", "exit": None}
    world.save()
    assert world.fetch()[1] == {"ok": False, "code": "time_limit"}


def test_a_container_that_runs_over_its_time_ends_time_limit_and_leaves_nothing(world, monkeypatch):
    monkeypatch.setattr(ytdlp, "MIN_TIMEOUT", 1)
    world.cfg["fetch_sleep"] = 20
    world.save()
    code, out, _ = world.fetch("--timeout", 1, **{})
    assert out == {"ok": False, "code": "time_limit"} and leftovers(world) == []

"""The link, the platform's fetch file and the folder a fetch writes into, all checked before any container. Planted `.example` hosts."""
from __future__ import annotations

import copy
import json
import os

import pytest

import fetcher_kit as K
import ytdlp


@pytest.fixture
def world(tmp_path, monkeypatch):
    return K.World(tmp_path, monkeypatch, fetch_files={"info.json": K.text(dict(K.INFO))})


def refused(world, code, **kw):
    exit_code, out, _ = world.fetch(**kw)
    assert out == {"ok": False, "code": code} and exit_code == (2 if code in ("link_refused", "platform_not_ready", "out_refused", "bad_arguments") else 1)
    assert world.calls() == [], "refused before any docker call"


@pytest.mark.parametrize("url", ["http://www.aster.example/v/1", "https://www.aster.example:8443/v/1", "https://user:pw@www.aster.example/v/1",
                                 "https://evil.www.aster.example/v/1", "https://aster.example/v/1", "https://www.aster.example.evil.example/v/1",
                                 "https://www.aster.example/other/1", "https://www.aster.example/v/1/extra", "https://www.aster.example/v/1 x",
                                 "ftp://www.aster.example/v/1", "https://www.aster.example/v/\x07", "", "https://" + "a" * 2050])
def test_a_link_that_is_not_a_plain_public_https_link_of_a_listed_host_is_refused(world, url):
    refused(world, "link_refused", url=url)


def test_2049_characters_are_refused_and_2048_are_not_too_long_by_themselves():
    fetch = K.FETCH_FILE
    base = "https://www.aster.example/v/1"
    long_query = base + "?t=" + "1" * (2049 - len(base) - 3)
    assert len(long_query) == 2049
    with pytest.raises(ytdlp.Refusal) as caught:
        ytdlp.check_link(long_query, fetch)
    assert caught.value.code == "link_refused"
    ok = base + "?t=" + "1" * (2048 - len(base) - 3)
    assert len(ok) == 2048 and ytdlp.check_link(ok, fetch).startswith(base)


def test_the_host_is_lowercased_then_matched_and_the_query_is_cut_to_the_listed_keys():
    assert ytdlp.check_link("https://WWW.Aster.Example/v/9?utm=x&t=5&a=b#frag", K.FETCH_FILE) == "https://www.aster.example/v/9?t=5"
    assert ytdlp.check_link("https://www.aster.example/v/9", K.FETCH_FILE) == "https://www.aster.example/v/9"


def plant(world, edit):
    data = copy.deepcopy(K.FETCH_FILE)
    edit(data)
    world.platform_file.write_text(json.dumps(data))


@pytest.mark.parametrize("edit", [lambda d: d.update(extractors=None), lambda d: d.update(extractors=[]),
                                  lambda d: d["link"].update(path_pattern=None), lambda d: d["link"].update(path_pattern=""),
                                  lambda d: d.update(platform="other"), lambda d: d.update(fetch_hosts=[], fetch_suffixes=[]),
                                  lambda d: d.update(extractors=["--cookies"]), lambda d: d.update(extra=1),
                                  lambda d: d["subtitles"].update(original="-live"), lambda d: d.update(fetch_suffixes=["no-dot.example"])])
def test_a_fetch_file_that_is_not_ready_is_refused_with_platform_not_ready(world, edit):
    plant(world, edit)
    refused(world, "platform_not_ready")


def test_a_missing_or_unreadable_fetch_file_is_platform_not_ready(world):
    world.platform_file.write_text("{")
    refused(world, "platform_not_ready")
    world.platform_file.unlink()
    refused(world, "platform_not_ready")


def test_the_committed_fetch_files_are_not_ready_so_nothing_is_fetched_before_a_person_fills_them():
    folder = K.PROVIDERS.parent / "shared" / "references" / "platforms"
    files = sorted(folder.glob("*.fetch.json"))
    assert files
    for path in files:
        name = path.name[: -len(".fetch.json")]
        if json.loads(path.read_text(encoding="utf-8"))["checked"] != "not checked":   # filled from a live run and approved by a person (STOP 4)
            assert ytdlp.load_fetch_file(str(path), name)["extractors"]
            continue
        with pytest.raises(ytdlp.Refusal) as caught:
            ytdlp.load_fetch_file(str(path), name)
        assert caught.value.code == "platform_not_ready"
    assert any(json.loads(p.read_text(encoding="utf-8"))["checked"] == "not checked" for p in files), "a platform still waits for its live run"


def test_the_out_folder_must_be_a_private_folder_of_this_user_inside_a_reference_store(world, tmp_path):
    outside = K.private_folder(tmp_path / "plain")
    refused(world, "out_refused", out=outside)
    (world.refs / ".openhora-reference").chmod(0o600)
    os.chmod(world.ref, 0o750)
    refused(world, "out_refused")
    os.chmod(world.ref, 0o700)
    link = tmp_path / "link"
    link.symlink_to(world.ref)
    refused(world, "out_refused", out=link)
    refused(world, "out_refused", out=world.ref / "missing")
    refused(world, "out_refused", out="relative/path")


@pytest.mark.parametrize("language", ["EN", "e", "english", "en-US", "", "../x"])
def test_a_language_outside_the_closed_shape_is_refused(world, language):
    refused(world, "bad_arguments", language=language)


def test_a_stage_that_is_not_meta_or_video_is_refused(world):
    refused(world, "bad_arguments", stage="both")


def test_auto_gives_the_original_pattern_alone_and_a_language_gives_both():
    assert ytdlp.subtitle_languages(K.FETCH_FILE, "auto") == ["aster-orig"]
    assert ytdlp.subtitle_languages(K.FETCH_FILE, "pt") == ["pt.*", "aster-orig"]
    both_null = copy.deepcopy(K.FETCH_FILE)
    both_null["subtitles"] = {"by_language": None, "original": None}
    assert ytdlp.subtitle_languages(both_null, "en") == []


def test_the_video_stage_checks_a_stated_length_before_any_container_and_starts_one_when_none_is_stated(world):
    # Changed by the maintainer's decision of 2026-11-10: a missing length is no longer refused before a container; it is measured from the file.
    world.cfg["fetch_files"] = {"video.mp4": K.text("x")}
    world.cfg["fetch_seconds"] = 20.0
    world.save()
    (world.ref / "info.json").write_text(json.dumps(dict(K.INFO, duration=None)))
    code, out, _ = world.fetch(stage="video")
    assert code == 0 and out["duration"] == 20.0 and any("fetch" in run for run in world.runs()), "the containers started with no stated length"
    (world.ref / "video.mp4").unlink()
    (world.config / "calls.jsonl").unlink()
    (world.ref / "info.json").write_text(json.dumps(dict(K.INFO, duration=301)))
    refused(world, "too_long", stage="video")
    refused(world, "too_long", stage="video", **{})


def test_the_max_seconds_flag_lowers_the_bound_and_cannot_raise_it_over_300(world):
    (world.ref / "info.json").write_text(json.dumps(dict(K.INFO, duration=120)))
    code, out, _ = world.fetch("--max-seconds", 60, stage="video")
    assert out == {"ok": False, "code": "too_long"}
    (world.ref / "info.json").write_text(json.dumps(dict(K.INFO, duration=400)))
    code, out, _ = world.fetch("--max-seconds", 999, stage="video")
    assert out == {"ok": False, "code": "too_long"}


def test_a_null_pin_refuses_before_any_docker_call(tmp_path, monkeypatch):
    world = K.World(tmp_path, monkeypatch, pin=False)
    code, out, err = world.fetch()
    assert (code, out) == (3, {"ok": False, "code": "pin_not_filled"}) and world.calls() == []

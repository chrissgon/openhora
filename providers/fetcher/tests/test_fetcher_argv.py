"""The three containers of a fetch, as the fake docker saw them, and the closed argument list of the tool. Offline: a fake docker, no image."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import fetcher_kit as K
import _fetcher_inner
import ytdlp

FORBIDDEN = ["--cookies", "--cookies-from-browser", "--username", "--password", "--netrc", "--video-password", "--ap-mso", "--config-location", "--exec",
             "--load-info-json", "--batch-file", "--no-check-certificates", "--write-comments", "--write-thumbnail", "--remote-components",
             "--plugin-dirs", "--downloader", "--external-downloader"]
PROXY = "http://openhora-fetch-proxy-0123456789ab:8888"


@pytest.fixture
def world(tmp_path, monkeypatch):
    return K.World(tmp_path, monkeypatch, fetch_files={"info.json": K.text(dict(K.INFO))})


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


def test_a_fetch_starts_the_proxy_on_the_out_network_and_the_fetch_on_the_internal_one_only(world):
    code, out, _ = world.fetch()
    assert code == 0 and out["ok"] is True
    proxy, fetch = world.runs()
    assert flag_value(proxy, "--network").startswith("openhora-fetch-out-") and flag_value(fetch, "--network").startswith("openhora-fetch-in-")
    token = flag_value(proxy, "--network").rsplit("-", 1)[1]
    assert flag_value(fetch, "--network") == "openhora-fetch-in-" + token
    created = [n for n in world.networks() if n[1] == "create"]
    assert len(created) == 2 and "--internal" not in created[0] and "--internal" in created[1] and created[0][-1].startswith("openhora-fetch-out-")
    assert ["network", "connect", "openhora-fetch-in-" + token, "openhora-fetch-proxy-" + token] in world.networks()
    assert [n[2] for n in world.networks() if n[1] == "rm"] == ["openhora-fetch-in-" + token, "openhora-fetch-out-" + token]
    assert not any("openhora-fetch-out-" in word for word in fetch), "the fetch container has no route to the outside network"


def test_every_container_is_closed_the_same_way_and_gets_no_environment_and_only_its_run_folders(world):
    world.fetch()
    for argv in world.runs():
        for word in ("--read-only", "--init", "--rm"):
            assert word in argv
        assert flag_value(argv, "--cap-drop") == "ALL" and flag_value(argv, "--security-opt") == "no-new-privileges"
        assert flag_value(argv, "--pull") == "never" and "-e" not in argv and "--env-file" not in argv
        mounts = [argv[i + 1] for i, w in enumerate(argv) if w == "-v"]
        assert len(mounts) == 1 and "/.fetch-" in mounts[0]
        assert flag_value(argv, "--memory") == flag_value(argv, "--memory-swap")
    proxy, fetch = world.runs()
    assert (flag_value(proxy, "--memory"), flag_value(proxy, "--cpus"), flag_value(proxy, "--pids-limit")) == ("128m", "1", "64")
    assert (flag_value(fetch, "--memory"), flag_value(fetch, "--cpus"), flag_value(fetch, "--pids-limit")) == ("512m", "2", "128")
    assert "size=256m" in " ".join(fetch) and fetch[fetch.index("--tmpfs") + 1].startswith("/tmp:rw,noexec")
    assert flag_value(proxy, "--out") == "/out" and "proxy" in proxy and flag_value(proxy, "--allow-host") == "media.aster.example" and flag_value(proxy, "--allow-suffix") == ".cdn.aster.example"


def test_the_fetch_command_carries_the_checked_link_the_extractors_and_the_subtitle_patterns(world):
    world.fetch(url=K.LINK + "?t=3&session=secret")
    fetch = world.runs()[1]
    inner = fetch[fetch.index("--result"):]
    assert flag_value(inner, "--url") == "https://www.aster.example/v/4242?t=3" and flag_value(inner, "--extractors") == "AsterVideo"
    assert flag_value(inner, "--langs") == "en.*,aster-orig" and flag_value(inner, "--stage") == "meta"
    assert flag_value(inner, "--proxy-url").startswith("http://openhora-fetch-proxy-") and flag_value(inner, "--proxy-url").endswith(":8888")
    assert "secret" not in " ".join(fetch)


def test_the_limits_are_the_documented_numbers():
    assert ytdlp.STAGES == {"meta": {"timeout": 120, "file_cap": 16 << 20}, "video": {"timeout": 600, "file_cap": 200 << 20}}
    assert ytdlp.MAX_LINK == 2048 and ytdlp.VIDEO_MAX_SECONDS == 300 and ytdlp.INFO_MAX_BYTES == 1 << 20 and ytdlp.MAX_SUBTITLE_FILES == 4
    assert ytdlp.MEASURE_LIMITS == {"memory_mb": 1024, "cpus": 2, "pids": 128, "scratch_mb": 256, "tmp_mb": 64, "timeout": 300, "input_bytes": 200 << 20}
    assert ytdlp.FETCH_LIMITS["scratch_mb"] == 256 and ytdlp.PROXY_MARGIN == 1.10


def test_the_proxy_cap_is_the_files_cap_plus_ten_percent_and_the_least_of_the_three_bounds_is_used(world):
    world.fetch("--max-bytes", 1000)
    proxy = world.runs()[0]
    assert flag_value(proxy, "--max-bytes") == "1100"
    fetch = world.runs()[1]
    assert flag_value(fetch, "--max-bytes") == "1000"


def test_the_measure_container_has_no_network_and_reads_the_reference_read_only(world):
    world.cfg["measure_files"] = {}
    world.save()
    code, _, _ = run(world)
    assert code == 1     # the fake wrote no facts: the point here is the command
    (argv,) = world.runs()
    assert flag_value(argv, "--network") == "none"
    mounts = [argv[i + 1] for i, w in enumerate(argv) if w == "-v"]
    assert mounts[0].endswith(":/in:ro") and mounts[1].endswith(":/out:rw") and "/.fetch-" in mounts[1]
    assert flag_value(argv, "--memory") == "1024m" and flag_value(argv, "--cpus") == "2"


def run(world):
    return K.run_main(["measure", "--in", str(world.ref), "--out", str(world.ref / "facts.json"), "--reference", K.REFERENCE, "--platform", "asterlane"])


@pytest.mark.parametrize("stage", ["meta", "video"])
def test_every_word_of_the_tool_argument_list_that_starts_with_a_dash_is_allowed(stage):
    argv = _fetcher_inner.ytdlp_argv(stage, "https://www.aster.example/v/1", ["AsterVideo", "AsterLive"], PROXY, 300, 1000, ["en.*", "aster-orig"])
    dashed = [w for w in argv if w.startswith("-")]
    assert dashed and set(dashed) <= set(_fetcher_inner.ALLOWED)
    assert flag_value(argv, "--use-extractors") == "AsterVideo,AsterLive" and flag_value(argv, "--proxy") == PROXY
    assert "--paths" in argv and flag_value(argv, "-o") == "/out/ref.%(ext)s" and argv[-1].startswith("https://")


def test_the_two_stages_differ_where_the_documentation_says():
    meta = _fetcher_inner.ytdlp_argv("meta", "https://www.aster.example/v/1", ["A"], PROXY, 300, 1000, ["en.*"])
    video = _fetcher_inner.ytdlp_argv("video", "https://www.aster.example/v/1", ["A"], PROXY, 300, 1000, ["en.*"])
    assert "--skip-download" in meta and "--write-subs" in meta and flag_value(meta, "--sub-langs") == "en.*" and flag_value(meta, "--match-filter") == "!is_live"
    assert "-S" not in meta and "--max-filesize" not in meta
    assert flag_value(video, "-S") == "res:720" and flag_value(video, "--max-filesize") == "1000" and "--skip-download" not in video
    assert flag_value(video, "-f") == "bv*[filesize<?1000]+ba/b[filesize<?1000]" and flag_value(video, "--merge-output-format") == "mp4/webm" and flag_value(video, "--match-filter") == "!is_live & duration <=? 300"
    assert "--write-subs" not in video and "--write-info-json" not in video


def test_with_no_subtitle_pattern_the_meta_stage_asks_for_no_subtitle():
    argv = _fetcher_inner.ytdlp_argv("meta", "https://www.aster.example/v/1", ["A"], PROXY, 300, 1000, [])
    assert "--write-subs" not in argv and "--sub-langs" not in argv and "--write-info-json" in argv


@pytest.mark.parametrize("option", FORBIDDEN)
def test_a_forbidden_option_is_refused_by_the_final_check_even_when_planted(option):
    argv = _fetcher_inner.ytdlp_argv("meta", "https://www.aster.example/v/1", ["A"], PROXY, 300, 1000, ["en.*"])
    assert option not in _fetcher_inner.ALLOWED
    for planted in (argv + [option], [option] + argv, argv[:-1] + [option, "x"] + argv[-1:]):
        with pytest.raises(_fetcher_inner.Refusal) as caught:
            _fetcher_inner.check_argv(planted)
        assert caught.value.code == "option_refused"


def test_a_value_that_would_pass_an_option_through_a_fetch_file_is_refused():
    for bad in (["--cookies"], ["a,b"], [""], ["A B"], ["A;B"]):
        with pytest.raises(_fetcher_inner.Refusal):
            _fetcher_inner.ytdlp_argv("meta", "https://www.aster.example/v/1", bad, PROXY, 300, 1000, [])
    with pytest.raises(_fetcher_inner.Refusal):
        _fetcher_inner.ytdlp_argv("meta", "https://www.aster.example/v/1", ["A"], PROXY, 300, 1000, ["-live_chat"])
    with pytest.raises(_fetcher_inner.Refusal):
        _fetcher_inner.ytdlp_argv("meta", "http://www.aster.example/v/1", ["A"], PROXY, 300, 1000, [])
    with pytest.raises(_fetcher_inner.Refusal):
        _fetcher_inner.ytdlp_argv("meta", "https://www.aster.example/v/1", ["A"], "http://example.com:8888", 300, 1000, [])


def test_the_argument_list_never_names_the_provider_a_cookie_or_an_account_in_the_source():
    text = Path(_fetcher_inner.__file__).read_text(encoding="utf-8")
    allowed_line = re.search(r"ALLOWED = \((.*?)\)\n", text, re.S).group(1)
    for option in FORBIDDEN:
        assert '"%s"' % option not in allowed_line

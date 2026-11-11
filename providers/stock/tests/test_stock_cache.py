"""The answer cache (providers/stock/_stock.py): an answer is kept for `cache_seconds`, used before any request, and holds no key and no URL with one."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import stock_kit as kit
from stock_kit import API, Run, photo, source

import _stock


def cached_source(seconds=86400, **over):
    return source(cache_seconds=seconds, **over)


def test_an_answer_is_kept_until_it_is_old_enough(tmp_path):
    env = {"OPENHORA_STATE_DIR": str(tmp_path / "state")}
    key = _stock.cache_key("search", "image", "/v1/search", [["query", "lake"]])
    assert _stock.cache_get("aster", key, 100, env, now=1000.0) is None
    assert _stock.cache_put("aster", key, {"photos": [1]}, 100, environ=env, now=1000.0) is True
    assert _stock.cache_get("aster", key, 100, env, now=1099.0) == {"photos": [1]}
    assert _stock.cache_get("aster", key, 100, env, now=1100.0) is None
    assert _stock.cache_get("aster", key, 100, env, now=900.0) is None        # a clock that went back does not make it fresh
    assert _stock.cache_get("aster", key, 0, env, now=1000.0) is None


def test_zero_seconds_writes_nothing(tmp_path):
    env = {"OPENHORA_STATE_DIR": str(tmp_path / "state")}
    assert _stock.cache_put("aster", "k" * 64, {"a": 1}, 0, environ=env, now=1.0) is False
    assert not (tmp_path / "state").exists()


def test_the_cache_folder_and_file_are_private_and_under_the_state_folder(tmp_path):
    env = {"OPENHORA_STATE_DIR": str(tmp_path / "state")}
    _stock.cache_put("aster", "a" * 64, {"a": 1}, 60, environ=env, now=1.0)
    folder = tmp_path / "state" / "stock" / "cache" / "aster"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700 and stat.S_IMODE(folder.parent.stat().st_mode) == 0o700
    files = list(folder.iterdir())
    assert [f.name for f in files] == ["a" * 64 + ".json"] and stat.S_IMODE(files[0].stat().st_mode) == 0o600


def test_an_answer_that_holds_the_key_is_never_written(tmp_path):
    env = {"OPENHORA_STATE_DIR": str(tmp_path / "state")}
    assert _stock.cache_put("aster", "b" * 64, {"url": "https://x.example/?key=%s" % kit.KEY}, 60, secret=kit.KEY, environ=env, now=1.0) is False
    assert not (tmp_path / "state").exists()


def test_a_damaged_or_foreign_cache_file_is_a_miss(tmp_path):
    env = {"OPENHORA_STATE_DIR": str(tmp_path / "state")}
    folder = tmp_path / "state" / "stock" / "cache" / "aster"
    folder.mkdir(parents=True, mode=0o700)
    (folder / ("c" * 64 + ".json")).write_text("{not json")
    (folder / ("d" * 64 + ".json")).write_text(json.dumps({"at": "yesterday", "answer": 1}))
    (folder / ("e" * 64 + ".json")).write_text(json.dumps({"answer": 1}))
    (folder / ("f" * 64 + ".json")).symlink_to(folder / ("e" * 64 + ".json"))
    for name in "cdef":
        assert _stock.cache_get("aster", name * 64, 60, env, now=5.0) is None


def test_the_state_folder_is_the_fetchers_rule():
    assert _stock.state_dir({"OPENHORA_STATE_DIR": "/a/b"}) == "/a/b"
    assert _stock.state_dir({"XDG_STATE_HOME": "/x"}) == "/x/openhora"
    assert _stock.state_dir({"OPENHORA_STATE_DIR": "relative", "XDG_STATE_HOME": "also/relative"}).endswith("/.local/state/openhora")


def test_a_cached_search_makes_no_api_request_and_a_stale_one_makes_one(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch, cached_source(3600))
    r.serve_search_image([photo(1001), photo(1002)])
    code, first = r.search()
    assert code == 0 and first["cached"] is False and first["requests"] == 1 and len(r.net.api_requests()) == 1
    code, again = r.search()
    assert code == 0 and again["cached"] is True and again["requests"] == 0 and len(r.net.api_requests()) == 1
    assert [c["item"] for c in again["candidates"]] == [c["item"] for c in first["candidates"]]
    r.clock[0] += 3599
    assert r.search()[1]["cached"] is True
    r.clock[0] += 2
    code, later = r.search()
    assert later["cached"] is False and len(r.net.api_requests()) == 2


def test_a_search_for_other_words_or_another_kind_is_not_served_from_the_cache(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch, cached_source(3600))
    r.serve_search_image([photo(1001)])
    r.serve_search_clip([kit.video(2001)])
    r.search("image", "mountain lake")
    r.search("image", "river bank")
    r.search("clip", "mountain lake")
    assert len(r.net.api_requests()) == 3


def test_a_source_with_no_cache_time_asks_every_time(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch, cached_source(0))
    r.serve_search_image([photo(1001)])
    r.search()
    r.search()
    assert len(r.net.api_requests()) == 2 and not Path(r.state, "stock").exists()


def test_the_cache_holds_no_key_and_no_url_with_a_key(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch, cached_source(3600, secret_in="query"), impl=kit.query_impl())
    r.serve_search_image([photo(1001)])
    code, _ = r.search()
    assert code == 0
    cached = [p for p in Path(r.state, "stock", "cache", "pexels").iterdir()]
    assert cached and all(kit.KEY not in p.read_text() and "key=" not in p.read_text() for p in cached)
    assert kit.KEY not in r.everything()


def test_a_cached_item_answer_is_used_by_fetch(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch, cached_source(3600))
    r.net.add(API, "/v1/photos/1001", kit.json_response(photo(1001)))
    r.net.add(kit.IMG, "/p/1001/original.jpg", kit.image_response())
    assert r.fetch("image", "1001")[0] == 0 and r.fetch("image", "1001")[0] == 0
    assert len(r.net.api_requests()) == 1 and r.net.count(kit.IMG) == 2

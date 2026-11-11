"""The review's findings for providers/stock/: a pinned source file and secret, non-finite numbers, unexpected exceptions, addresses, the item asked,
ids, the cache cap, one deadline, and the real connection path."""
from __future__ import annotations

import io
import json
import os
import socket
import ssl
from pathlib import Path

import pytest
import stock_kit as kit
from stock_kit import API, IMG, Run, Response, photo, source, video

import _net
import _stock

DEFAULT_SOURCES = str(Path(_stock.__file__).resolve().parent / "sources")


# --- 1: the source file and the secret are the implementation's own ----------------------------------------------------------------------

def test_a_source_file_outside_the_implementations_own_is_refused_before_any_request(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    _stock.SEAMS["sources"] = None                       # the real rule: providers/stock/sources/pexels.json only
    for verb in (("--check",), ("search", "--kind", "image", "--query", "old barn", "--out", r.out),
                 ("fetch", "--kind", "image", "--item", "1", "--max-bytes", "9", "--out", r.out)):
        out, err = io.StringIO(), io.StringIO()
        code = _stock.run(r.impl, ["--source-file", r.source_file, "--today", kit.TODAY, *verb], r.environ, out, err)
        got = json.loads(out.getvalue())
        assert code == 3 and got["code"] == "source_not_ready" and got["fields"] == ["source_file"]
    assert r.net.count() == 0 and r.resolver.asked == []


def test_a_link_to_the_real_source_file_is_accepted_and_a_lookalike_name_is_not(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    impl = r.impl
    _stock.SEAMS["sources"] = None
    (tmp_path / "ln").mkdir()
    link = tmp_path / "ln" / "pexels.json"
    link.symlink_to(Path(DEFAULT_SOURCES) / "pexels.json")
    _stock.pin_source(str(link), impl)                    # the same real file
    for bad in (str(tmp_path / "pexels.json.bak"), DEFAULT_SOURCES + "/../sources/other.json", None, 5):
        with pytest.raises(_stock.Refusal):
            _stock.pin_source(bad, impl)


def test_a_source_file_that_names_another_secret_or_other_hosts_never_sends_a_credential(tmp_path, monkeypatch):
    evil = source(secret="STOCK_OTHER_API_KEY", api={"host": "evil.example", "search_image": "/v1/search", "search_clip": "/v1/videos/search",
                                              "item_image": "/v1/photos/{item}", "item_clip": "/v1/videos/videos/{item}"}, media_hosts=["evil.example"])
    other = kit.KEY[::-1]
    r = Run(tmp_path, monkeypatch, evil, resolver=kit.FakeResolver({"STOCK_OTHER_API_KEY": other, "STOCK_PEXELS_API_KEY": kit.KEY}))
    r.net.add("evil.example", "/v1/search", kit.json_response({"photos": []}))
    code, got = r.search()
    assert code == 3 and got["code"] == "source_not_ready" and got["fields"] == ["secret"]
    assert r.net.count() == 0 and r.resolver.asked == [] and other not in r.everything()


def test_the_implementation_names_its_secret_and_it_is_the_recommended_one():
    import pexels
    assert pexels.SECRET == "STOCK_PEXELS_API_KEY"


# --- 2: non-finite numbers ------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_number_in_an_answer_is_a_bad_answer(tmp_path, monkeypatch, text):
    r = Run(tmp_path, monkeypatch)
    body = ('{"videos": [{"id": 2001, "duration": %s, "width": 2160, "height": 3840}]}' % text).encode()
    r.net.add(API, "/v1/videos/search", Response(200, body, {"Content-Type": "application/json"}))
    code, got = r.search("clip")
    assert code == 1 and got["code"] == "status" and "NaN" not in r.stdout and "Infinity" not in r.stdout


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), -float("inf")])
def test_a_candidate_with_a_non_finite_duration_is_dropped(seconds):
    import re
    import pexels
    data = dict(source())
    data["_patterns"] = {k: re.compile(v) for k, v in source()["path_patterns"].items()}
    raw = pexels._clip(data, video(1, 12))
    raw["seconds"] = seconds
    assert _stock.candidate(raw, data, "clip", pexels, False)[0] is None


def test_output_is_written_with_no_nan_allowed(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    monkeypatch.setattr(r.impl, "read_search", lambda *a: [{"item": "1", "width": 2000, "height": 3000, "seconds": None, "author": "x",
                                                            "preview_url": "https://%s/p/1/medium.jpg" % IMG, "file_url": "https://%s/p/1/original.jpg" % IMG,
                                                            "title": float("nan")}])
    r.net.add(API, "/v1/search", kit.json_response({"photos": []}))
    r.net.add(IMG, "/p/1/medium.jpg", kit.image_response())
    code, got = r.search()
    assert "NaN" not in r.stdout


# --- 3: no traceback, no exception text --------------------------------------------------------------------------------------------------

def test_a_deeply_nested_answer_is_a_bad_answer_not_a_traceback(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    r.net.add(API, "/v1/search", Response(200, b"[" * 100_000 + b"]" * 100_000, {"Content-Type": "application/json"}))
    code, got = r.search()
    assert code == 1 and got["code"] == "status"


def test_brackets_inside_strings_do_not_count_as_nesting():
    assert _net._deep(b'{"a": "' + b"[" * 500 + b'"}') is False and _net._deep(b"[" * 33 + b"]" * 33) is True and _net._deep(b"[" * 32 + b"]" * 32) is False


def test_an_unexpected_exception_prints_a_fixed_refusal_with_no_text(tmp_path, monkeypatch):
    for exc, code in ((OSError("disk path /x " + kit.KEY), "network"), (RuntimeError("boom " + kit.KEY), "network"), (ValueError(kit.KEY), "status"),
                      (RecursionError(kit.KEY), "status")):
        (tmp_path / code).mkdir(exist_ok=True)
        folder = tmp_path / code / type(exc).__name__
        folder.mkdir()
        r = Run(folder, monkeypatch)
        monkeypatch.setattr(r.impl, "read_search", lambda *a, _e=exc: (_ for _ in ()).throw(_e))
        r.net.add(API, "/v1/search", kit.json_response({"photos": []}))
        got_code, got = r.search()
        assert got_code == 1 and got["code"] == code and kit.KEY not in r.stdout + r.stderr


def test_a_resolver_that_raises_is_no_key_with_no_text(tmp_path, monkeypatch):
    class Locked:
        def resolve(self, name, **_):
            raise RuntimeError("keychain says " + kit.KEY)
    r = Run(tmp_path, monkeypatch, resolver=Locked())
    r.serve_search_image([photo(1)])
    code, got = r.search()
    assert code == 3 and got["code"] == "no_key" and kit.KEY not in r.stdout + r.stderr and r.net.count() == 0


def test_a_malformed_redirect_location_is_a_refusal(tmp_path, monkeypatch):
    net = kit.FakeNet().install(monkeypatch)
    net.add(IMG, "/a", Response(302, b"", {"Location": "https://[::1/x"}))
    folder = kit.out_dir(tmp_path)
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/a" % IMG, 100, os.path.join(folder, "x"), ("image/jpeg",), allowed_hosts=[IMG], redirect_hosts=[kit.CDN])
    assert stop.value.code == "redirect_refused"


def test_a_failed_rename_is_out_refused_and_leaves_no_partial_file(tmp_path, monkeypatch):
    net = kit.FakeNet().install(monkeypatch)
    net.add(IMG, "/a", kit.image_response())
    folder = kit.out_dir(tmp_path)

    def broken(*a):
        raise OSError("no")
    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/a" % IMG, 9000, os.path.join(folder, "x"), ("image/jpeg",), allowed_hosts=[IMG])
    assert stop.value.code == "out_refused" and os.listdir(folder) == []


# --- 5, 6: the item asked, ids and floors ------------------------------------------------------------------------------------------------

def test_fetch_refuses_an_answer_for_another_item(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    r.net.add(API, "/v1/photos/1001", kit.json_response(photo(5555)))
    r.net.add(IMG, "/p/5555/original.jpg", kit.image_response())
    code, got = r.fetch("image", "1001")
    assert code == 1 and got["code"] == "status" and r.net.count(IMG) == 0 and os.listdir(r.out) == []


def test_fetch_applies_the_size_and_length_floors_of_a_search(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    r.net.add(API, "/v1/photos/1001", kit.json_response(photo(1001, 100, 100)))
    r.net.add(API, "/v1/videos/videos/2001", kit.json_response(video(2001, 61)))
    r.net.add(API, "/v1/videos/videos/2002", kit.json_response(video(2002, 1)))
    for kind, item in (("image", "1001"), ("clip", "2001"), ("clip", "2002")):
        code, got = r.fetch(kind, item)
        assert code == 1 and got["code"] == "status", (kind, item)
    assert r.net.count(IMG) == 0 and r.net.count(kit.VID) == 0


def test_an_item_with_no_valid_id_is_dropped(tmp_path, monkeypatch):
    r = Run(tmp_path, monkeypatch)
    none_id, str_id, zero, neg, flag = photo(1), photo(2), photo(3), photo(4), photo(5)
    del none_id["id"]
    str_id["id"], zero["id"], neg["id"], flag["id"] = "12", 0, -4, True
    ok = photo(6)
    r.serve_search_image([ok])
    r.net.add(API, "/v1/search", kit.json_response({"photos": [none_id, str_id, zero, neg, flag, ok]}))
    code, got = r.search("image", "old barn", 6)
    assert code == 0 and [c["item"] for c in got["candidates"]] == ["6"] and "None" not in r.stdout


# --- 4: addresses (the table is in test_stock_net) and 8: one deadline -------------------------------------------------------------------

def test_get_json_has_one_deadline_across_its_reads(monkeypatch):
    net = kit.FakeNet().install(monkeypatch)
    now = [0.0]
    monkeypatch.setitem(_net.SEAMS, "clock", lambda: now[0])

    class Slow(Response):
        def read(self, amount=None):
            now[0] += 6.0                 # each read takes 6 s: three reads pass 15 s
            return b" " * 10

    net.add(API, "/slow", Slow(200, b"", {}, length=False))
    with pytest.raises(_net.NetError) as stop:
        _net.get_json("https://%s/slow" % API, {}, 10_000, allowed_hosts=[API], timeout=15)
    assert stop.value.code == "network"


# --- 7: the cache cap ----------------------------------------------------------------------------------------------------------------------

def test_the_cache_reads_what_it_writes_and_refuses_to_write_past_its_cap(tmp_path):
    env = {"OPENHORA_STATE_DIR": str(tmp_path)}
    fits = {"photos": [{"photographer": "é" * 400_000}]}          # about 0.8 MiB as UTF-8, 2.4 MiB as ASCII escapes: the cap counts what is written
    assert _stock.cache_put("pexels", "a" * 64, fits, 3600, environ=env, now=1.0) is True
    assert _stock.cache_get("pexels", "a" * 64, 3600, environ=env, now=2.0) == fits
    too_big = {"photos": ["x" * (_stock.CACHE_MAX_BYTES + 1)]}
    assert _stock.cache_put("pexels", "b" * 64, too_big, 3600, environ=env, now=1.0) is False
    assert _stock.cache_put("pexels", "c" * 64, {"n": float("nan")}, 3600, environ=env, now=1.0) is False
    assert not (Path(env["OPENHORA_STATE_DIR"]) / "stock" / "cache" / "pexels" / ("b" * 64 + ".json")).exists()
    assert _stock.CACHE_MAX_BYTES >= _stock.CAPS["search_bytes"]


# --- 10: the real connection path ---------------------------------------------------------------------------------------------------------

def test_the_real_connection_path_opens_the_checked_address_and_reads_no_proxy_variable(monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://proxy.example:3128")
    answer = b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 8\r\n\r\n{"a": 1}'
    seen = {}

    class Sock:
        def __init__(self):
            self.sent = b""

        def sendall(self, data):
            self.sent += data

        def makefile(self, *a, **k):
            return io.BytesIO(answer)

        def settimeout(self, t):
            pass

        def close(self):
            pass

    sock = Sock()

    class Ctx:
        def wrap_socket(self, s, server_hostname=None):
            seen["hostname"] = server_hostname
            return sock

    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: Ctx())
    monkeypatch.setattr(socket, "create_connection", lambda address, timeout=None: seen.setdefault("address", address) and None or object())
    monkeypatch.setitem(_net.SEAMS, "resolve", kit.FakeNet().resolve)
    monkeypatch.setitem(_net.SEAMS, "opener", None)
    got = _net.get_json("https://%s/v1/x?q=1" % API, {"Authorization": kit.KEY}, 1000, allowed_hosts=[API])
    assert got == {"a": 1} and seen["address"] == (kit.PUBLIC, 443) and seen["hostname"] == API
    assert sock.sent.startswith(b"GET /v1/x?q=1 HTTP/1.1\r\n") and b"proxy" not in sock.sent.lower()

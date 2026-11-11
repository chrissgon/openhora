"""The closed-host fetch (providers/stock/_net.py): hosts, addresses, redirects, caps, the partial file and the output folder."""
from __future__ import annotations

import os
import re
import socket
from pathlib import Path

import pytest
import stock_kit as kit
from stock_kit import API, CDN, IMG, FakeNet, Response

import _net

REPO = Path(__file__).resolve().parents[3]
HOSTS = [IMG, API, CDN]


def raises(code, fn, *a, **kw):
    with pytest.raises(_net.NetError) as stop:
        fn(*a, **kw)
    assert stop.value.code == code and str(stop.value) == code
    return stop.value


@pytest.fixture
def net(monkeypatch):
    return FakeNet().install(monkeypatch)


def never(*a, **kw):
    raise AssertionError("a lookup or a connection was made")


@pytest.mark.parametrize("host", ["evil.example", "img.stock.example.evil.example", "10.0.0.1", "[::1]", "img.stock.example.", "", "a" * 260 + ".example",
                                  "img_stock.example", None, 5])
def test_a_host_off_the_list_is_refused_before_any_lookup(host, monkeypatch):
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    raises("host_refused", _net.check_host, host, HOSTS)
    if isinstance(host, str):
        raises("host_refused", _net.get_json, "https://%s/x" % host, {}, 1000, allowed_hosts=HOSTS)
        raises("host_refused", _net.download, "https://%s/x" % host, 1000, "x", ("image/jpeg",), allowed_hosts=HOSTS)


def test_a_listed_host_is_lower_cased_and_accepted():
    assert _net.check_host("IMG.Stock.Example", HOSTS) == IMG


@pytest.mark.parametrize("url", ["http://img.stock.example/x", "ftp://img.stock.example/x", "https://img.stock.example:8443/x", "https://u:p@img.stock.example/x",
                                 "https://img.stock.example@evil.example/x", "//img.stock.example/x", "img.stock.example/x"])
def test_only_https_on_443_without_user_info_is_opened(url, monkeypatch):
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    raises("host_refused", _net.get_json, url, {}, 1000, allowed_hosts=HOSTS)


@pytest.mark.parametrize("address", ["10.1.2.3", "172.16.0.9", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",
                                     "::1", "fe80::1", "fc00::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1", "2002:c0a8:101::1",
                                     "2002:7f00:1::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "198.51.100.7", "not an address"])
def test_a_host_that_resolves_to_a_non_global_address_is_refused(address):
    resolve = lambda host, port, type=None: [(2, 1, 6, "", (address, port))]
    raises("address_refused", _net.check_address, IMG, resolve)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700::1111", "64:ff9b::808:808", "::ffff:8.8.8.8"])
def test_a_global_address_is_accepted(address):
    resolve = lambda host, port, type=None: [(2, 1, 6, "", (address, port))]
    assert _net.check_address(IMG, resolve) == address


def test_one_private_address_among_several_refuses_the_host_and_an_empty_answer_too():
    mixed = lambda host, port, type=None: [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.1", port))]
    raises("address_refused", _net.check_address, IMG, mixed)
    raises("address_refused", _net.check_address, IMG, lambda *a, **k: [])
    raises("address_refused", _net.check_address, IMG, lambda *a, **k: [(2, 1, 6, "", ())])

    def broken(*a, **k):
        raise socket.gaierror("no such host")
    raises("network", _net.check_address, IMG, broken)


def test_the_connection_opens_the_address_that_was_checked_and_names_the_host(monkeypatch):
    seen = {}

    class Ctx:
        def wrap_socket(self, sock, server_hostname=None):
            seen["hostname"] = server_hostname
            return sock

    class Sock:
        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(socket, "create_connection", lambda address, timeout=None: seen.update(address=address) or Sock())
    conn = _net._Pinned(IMG, "93.184.216.34", 5, context=Ctx())
    conn.connect()
    assert seen["address"] == ("93.184.216.34", 443) and seen["hostname"] == IMG and conn.sock is not None


def test_a_failed_handshake_closes_the_socket(monkeypatch):
    seen = {}

    class Ctx:
        def wrap_socket(self, sock, server_hostname=None):
            raise OSError("handshake")

    class Sock:
        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(socket, "create_connection", lambda address, timeout=None: Sock())
    with pytest.raises(OSError):
        _net._Pinned(IMG, "93.184.216.34", 5, context=Ctx()).connect()
    assert seen["closed"]


def test_the_request_goes_to_the_address_checked_and_proxy_variables_are_not_read(net, monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://proxy.example:3128")
    net.add(API, "/v1/search", kit.json_response({"ok": 1}))
    assert _net.get_json("https://%s/v1/search?query=lake" % API, {"Authorization": kit.KEY}, 1000, allowed_hosts=HOSTS) == {"ok": 1}
    assert net.requests[0]["host"] == API and net.requests[0]["address"] == kit.PUBLIC and net.resolved == [API]
    assert net.requests[0]["headers"]["Authorization"] == kit.KEY and net.requests[0]["headers"]["Accept-Encoding"] == "identity"
    assert "Cookie" not in net.requests[0]["headers"]


def test_a_request_with_a_credential_follows_no_redirect(net):
    net.add(API, "/v1/search", Response(302, b"", {"Location": "https://%s/elsewhere" % CDN}))
    raises("redirect_refused", _net.get_json, "https://%s/v1/search" % API, {"Authorization": kit.KEY}, 1000, allowed_hosts=HOSTS)
    assert net.count() == 1 and all(kit.KEY not in str(r["target"]) for r in net.requests)


def test_a_rate_limit_is_one_request_and_no_retry(net):
    net.add(API, "/v1/search", Response(429, b"slow down", {}))
    raises("rate_limited", _net.get_json, "https://%s/v1/search" % API, {}, 1000, allowed_hosts=HOSTS)
    assert net.count() == 1


def test_other_statuses_and_unreadable_answers_are_refused(net):
    net.add(API, "/a", Response(500, b"", {}))
    raises("status", _net.get_json, "https://%s/a" % API, {}, 1000, allowed_hosts=HOSTS)
    net.add(API, "/b", Response(200, b"<html>", {}))
    raises("status", _net.get_json, "https://%s/b" % API, {}, 1000, allowed_hosts=HOSTS)
    net.add(API, "/c", Response(200, b"{" + b" " * 2000 + b"}", {}))
    raises("too_large", _net.get_json, "https://%s/c" % API, {}, 1000, allowed_hosts=HOSTS)
    net.add(API, "/d", Response(200, b"{" + b" " * 2000 + b"}", {}, length=False))
    raises("too_large", _net.get_json, "https://%s/d" % API, {}, 1000, allowed_hosts=HOSTS)


def test_a_json_answer_needs_no_content_length(net):
    net.add(API, "/e", Response(200, b'{"a": 1}', {}, length=False))
    assert _net.get_json("https://%s/e" % API, {}, 1000, allowed_hosts=HOSTS) == {"a": 1}


def test_the_deadline_stops_a_slow_answer(net, monkeypatch):
    ticks = iter([0.0, 0.0, 99.0, 99.0, 99.0])
    monkeypatch.setitem(_net.SEAMS, "clock", lambda: next(ticks))
    net.add(API, "/f", kit.json_response({"a": 1}))
    raises("network", _net.get_json, "https://%s/f" % API, {}, 1000, allowed_hosts=HOSTS, timeout=5)


COUNTER = iter(range(10_000))


def fetch_file(tmp_path, url, cap=10_000, types=("image/jpeg",), name=None, **kw):
    folder = kit.out_dir(tmp_path, name or "out%d" % next(COUNTER))
    return folder, _net.download(url, cap, os.path.join(folder, "full-x"), types, allowed_hosts=[IMG, CDN], redirect_hosts=[CDN], **kw)


def test_a_download_writes_one_private_file_with_its_hash(net, tmp_path):
    net.add(IMG, "/p/1/original.jpg", kit.image_response())
    folder, got = fetch_file(tmp_path, "https://%s/p/1/original.jpg" % IMG)
    path = Path(got["file"])
    assert path.name == "full-x.jpg" and got["bytes"] == path.stat().st_size and got["type"] == "image/jpeg"
    import hashlib
    assert got["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest() and path.stat().st_mode & 0o777 == 0o600
    assert sorted(os.listdir(folder)) == ["full-x.jpg"]
    assert "Authorization" not in net.requests[0]["headers"]


def test_a_png_and_an_mp4_get_their_own_extensions(net, tmp_path):
    net.add(IMG, "/a", kit.image_response(kit.png(), "image/png"))
    assert fetch_file(tmp_path, "https://%s/a" % IMG, types=("image/png",))[1]["file"].endswith("full-x.png")
    net.add(IMG, "/b", kit.clip_response())
    assert fetch_file(tmp_path, "https://%s/b" % IMG, types=("video/mp4",), name="second")[1]["file"].endswith("full-x.mp4")


def test_zero_redirects_make_one_request_and_two_are_refused(net, tmp_path):
    net.add(IMG, "/zero", kit.image_response())
    assert fetch_file(tmp_path, "https://%s/zero" % IMG)[1]["bytes"] > 0 and net.count() == 1
    net.add(IMG, "/two", Response(302, b"", {"Location": "https://%s/hop" % CDN}))
    net.add(CDN, "/hop", Response(302, b"", {"Location": "https://%s/final" % CDN}))
    net.add(CDN, "/final", kit.image_response())
    raises("redirect_refused", fetch_file, tmp_path, "https://%s/two" % IMG)


def test_one_redirect_to_a_listed_host_is_followed_and_one_to_an_unlisted_host_is_not(net, tmp_path):
    net.add(IMG, "/one", Response(302, b"", {"Location": "https://%s/final" % CDN}))
    net.add(CDN, "/final", kit.image_response())
    folder, got = fetch_file(tmp_path, "https://%s/one" % IMG)
    assert got["bytes"] > 0 and [r["host"] for r in net.requests] == [IMG, CDN]
    net.add(IMG, "/bad", Response(302, b"", {"Location": "https://evil.example/final"}))
    before = net.count()
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/bad" % IMG, 10_000, os.path.join(folder, "other"), ("image/jpeg",), allowed_hosts=[IMG, CDN], redirect_hosts=[CDN])
    assert stop.value.code == "redirect_refused" and net.count() == before + 1 and "evil.example" not in net.resolved


def test_a_redirect_with_no_location_or_to_http_is_refused(net, tmp_path):
    net.add(IMG, "/a", Response(301, b"", {}))
    raises("redirect_refused", fetch_file, tmp_path, "https://%s/a" % IMG)
    net.add(IMG, "/b", Response(301, b"", {"Location": "http://%s/final" % CDN}))
    raises("redirect_refused", fetch_file, tmp_path, "https://%s/b" % IMG)


def test_no_content_length_or_one_over_the_cap_is_refused_before_a_byte_is_read(net, tmp_path):
    net.add(IMG, "/nolen", kit.image_response(length=False))
    raises("no_length", fetch_file, tmp_path, "https://%s/nolen" % IMG)
    class NoRead(Response):
        def read(self, amount=None):
            raise AssertionError("a byte was read before the length was checked")

    net.add(IMG, "/big", NoRead(200, kit.jpeg(5000), {"Content-Type": "image/jpeg"}))
    raises("too_large", fetch_file, tmp_path, "https://%s/big" % IMG, cap=1000)


def test_a_body_longer_than_its_length_or_the_cap_is_refused_and_the_partial_file_removed(net, tmp_path):
    body = kit.jpeg(3000)
    liar = Response(200, body, {"Content-Type": "image/jpeg", "Content-Length": "1000"})
    net.add(IMG, "/liar", liar)
    folder = kit.out_dir(tmp_path)
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/liar" % IMG, 2000, os.path.join(folder, "full-x"), ("image/jpeg",), allowed_hosts=[IMG])
    assert stop.value.code == "too_large" and os.listdir(folder) == []


def test_a_short_body_is_a_network_failure_with_no_file_left(net, tmp_path):
    short = Response(200, kit.jpeg(100), {"Content-Type": "image/jpeg", "Content-Length": "5000"})
    net.add(IMG, "/short", short)
    folder = kit.out_dir(tmp_path)
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/short" % IMG, 9000, os.path.join(folder, "full-x"), ("image/jpeg",), allowed_hosts=[IMG])
    assert stop.value.code == "network" and os.listdir(folder) == []


def test_another_content_type_or_bytes_that_do_not_match_the_type_are_refused(net, tmp_path):
    net.add(IMG, "/html", Response(200, b"<html>", {"Content-Type": "text/html"}))
    raises("type_refused", fetch_file, tmp_path, "https://%s/html" % IMG)
    net.add(IMG, "/gif", Response(200, b"GIF89a....", {"Content-Type": "image/gif"}))
    raises("type_refused", fetch_file, tmp_path, "https://%s/gif" % IMG)
    net.add(IMG, "/lie", Response(200, b"<html>hello</html>", {"Content-Type": "image/jpeg"}))
    folder = kit.out_dir(tmp_path)
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/lie" % IMG, 9000, os.path.join(folder, "full-x"), ("image/jpeg",), allowed_hosts=[IMG])
    assert stop.value.code == "type_refused" and os.listdir(folder) == []
    net.add(IMG, "/ct", Response(200, kit.jpeg(), {"Content-Type": "IMAGE/JPEG; charset=binary"}))
    assert fetch_file(tmp_path, "https://%s/ct" % IMG)[1]["type"] == "image/jpeg"


def test_a_status_other_than_200_and_a_rate_limit_are_refused(net, tmp_path):
    net.add(IMG, "/gone", Response(404, b"", {}))
    raises("status", fetch_file, tmp_path, "https://%s/gone" % IMG)
    net.add(IMG, "/slow", Response(429, b"", {}))
    raises("rate_limited", fetch_file, tmp_path, "https://%s/slow" % IMG)
    assert net.count() == 2


def test_a_path_that_does_not_match_the_pattern_is_refused_before_any_request(net, tmp_path):
    folder = kit.out_dir(tmp_path)
    pattern = re.compile(r"/p/[0-9]+/original\.jpg")
    with pytest.raises(_net.NetError) as stop:
        _net.download("https://%s/other/path.jpg" % IMG, 100, os.path.join(folder, "x"), ("image/jpeg",), allowed_hosts=[IMG], path_pattern=pattern)
    assert stop.value.code == "host_refused" and net.count() == 0


def test_an_existing_file_is_replaced_whole(net, tmp_path):
    folder = kit.out_dir(tmp_path)
    Path(folder, "full-x.jpg").write_bytes(b"old")
    net.add(IMG, "/n", kit.image_response())
    got = _net.download("https://%s/n" % IMG, 9000, os.path.join(folder, "full-x"), ("image/jpeg",), allowed_hosts=[IMG])
    assert Path(got["file"]).read_bytes()[:3] == b"\xff\xd8\xff" and os.listdir(folder) == ["full-x.jpg"]


def test_an_error_never_holds_a_url_an_address_or_a_key(net, tmp_path):
    net.add(API, "/v1/search", Response(500, b"", {}))
    err = raises("status", _net.get_json, "https://%s/v1/search?key=%s" % (API, kit.KEY), {}, 1000, True, allowed_hosts=HOSTS)
    assert kit.KEY not in str(err) and API not in str(err) and kit.PUBLIC not in repr(err)


def test_an_invalid_header_value_does_not_leak_through_the_http_library(monkeypatch):
    class Bad:
        def request(self, *a, **k):
            raise ValueError("Invalid header value %r" % kit.KEY)

        def close(self):
            pass

    monkeypatch.setitem(_net.SEAMS, "resolve", FakeNet().resolve)
    monkeypatch.setitem(_net.SEAMS, "opener", lambda *a: Bad())
    err = raises("network", _net.get_json, "https://%s/x" % API, {"Authorization": kit.KEY}, 1000, allowed_hosts=HOSTS)
    assert kit.KEY not in str(err) and err.__cause__ is None


def test_the_output_folder_must_be_a_real_private_folder_of_this_user(tmp_path):
    good = kit.out_dir(tmp_path)
    assert _net.check_out(good) == os.path.abspath(good)
    loose = tmp_path / "loose"
    loose.mkdir()
    os.chmod(loose, 0o755)
    raises("out_refused", _net.check_out, str(loose))
    group = tmp_path / "group"
    group.mkdir()
    os.chmod(group, 0o770)
    raises("out_refused", _net.check_out, str(group))
    link = tmp_path / "link"
    link.symlink_to(good)
    raises("out_refused", _net.check_out, str(link))
    afile = tmp_path / "file"
    afile.write_text("x")
    raises("out_refused", _net.check_out, str(afile))
    raises("out_refused", _net.check_out, str(tmp_path / "missing"))
    for odd in ("", None, 5):
        raises("out_refused", _net.check_out, odd)


def test_a_folder_inside_a_reference_store_is_refused(tmp_path):
    store = tmp_path / "references"
    store.mkdir(mode=0o700)
    (store / _net.MARKER).write_bytes(b"x")
    inner = store / "ref1" / "deep"
    inner.mkdir(parents=True, mode=0o700)
    os.chmod(inner, 0o700)
    raises("out_refused", _net.check_out, str(inner))
    marker_dir = tmp_path / "references2"
    marker_dir.mkdir(mode=0o700)
    (marker_dir / _net.MARKER).mkdir()          # a folder of that name is not the marker
    assert _net.check_out(str(marker_dir)) == str(marker_dir)


def test_the_marker_name_equals_the_reference_stores():
    text = (REPO / "runtime" / "references.py").read_text(encoding="utf-8")
    found = re.search(r'^MARKER = "([^"\n]+)"', text, re.M)
    assert found and found.group(1) == _net.MARKER
    assert _net.MARKER in (REPO / "providers" / "_container.py").read_text(encoding="utf-8")


def test_no_module_of_the_class_reads_a_proxy_variable_or_a_cookie_jar():
    for path in sorted(Path(_net.__file__).parent.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for word in ("getproxies", "CookieJar", "HTTPCookieProcessor", "ProxyHandler", "HTTPS_PROXY", "http_proxy"):
            assert word not in text, (path.name, word)

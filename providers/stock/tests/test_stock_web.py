"""stock:media on the open web (providers/stock/web.py and `_net.fetch_open`): the one place a URL a model wrote is opened. Every rule of the spec's
section 4.8 has a test: the URL, the addresses, the redirects, the headers, the size, the sniffed type, the quarantine file and what is printed.
Every host is `.example`, every name is made up, and the media are generated; the network is the kit's fake."""
from __future__ import annotations

import io
import json
import os
import stat
from pathlib import Path

import pytest
import stock_kit as kit
from stock_kit import FakeNet, Response, jpeg, mp4, png

import _net
import _stock
import web

COMMITTED = Path(web.__file__).resolve().parent / "sources" / "web.json"
HOST, OTHER = "pics.example", "files.example"
MARK = "mark-planted-9b2e41"                              # planted in a path, a query and a Location: it must never be printed
IMAGE, CLIP = ("image/png", "image/jpeg"), ("video/mp4", "video/webm")
WEBM = b"\x1a\x45\xdf\xa3" + b"\x01" * 400
SOURCE = {"source": "web", "licence_tier": "unverified", "secret_in": "none", "kinds": ["image", "clip"], "terms_read_on": None}


def raises(code, fn, *a, **kw):
    with pytest.raises(_net.NetError) as stop:
        fn(*a, **kw)
    assert stop.value.code == code and str(stop.value) == code
    return stop.value


def never(*a, **kw):
    raise AssertionError("a lookup or a connection was made")


class Open:
    """A task's stock folder with its quarantine, a fake network and the web source file in a folder of its own."""

    def __init__(self, tmp_path, monkeypatch, source=None):
        self.tmp = Path(tmp_path)
        self.net = FakeNet().install(monkeypatch)
        folder = self.tmp / "sources"
        folder.mkdir()
        (folder / "web.json").write_text(json.dumps(SOURCE if source is None else source), encoding="utf-8")
        self.source_file = str(folder / "web.json")
        monkeypatch.setitem(_stock.SEAMS, "sources", str(folder))
        self.quarantine = self.tmp / "media" / "t1" / "stock" / "quarantine"
        self.quarantine.mkdir(parents=True)
        os.chmod(self.quarantine, 0o700)
        self.q = str(self.quarantine)

    def serve(self, path, response, host=HOST):
        self.net.add(host, path, response)
        return self

    def fetch(self, url, cap=10_000, types=IMAGE, **kw):
        return _net.fetch_open(url, cap, self.q, types, **kw)

    def files(self):
        return sorted(os.listdir(self.q))

    def verb(self, verb, url, kind="image", *extra, max_bytes=10_000_000, allow=True, out=None, today=kit.TODAY, source_file=None):
        argv = ["--source-file", source_file or self.source_file, "--today", today, verb, "--kind", kind, "--url", url, "--out", out or self.q,
                "--max-bytes", str(max_bytes)]
        if allow:
            argv.append("--allow-unverified")
        out_io, err_io = io.StringIO(), io.StringIO()
        code = web.main(argv + list(extra), out_io, err_io)
        self.stdout, self.stderr = out_io.getvalue(), err_io.getvalue()
        return code, (json.loads(self.stdout) if self.stdout.strip() else None)

    def everything(self):
        names = [os.path.join(b, n) for b, dirs, files in os.walk(self.tmp) for n in dirs + files]
        return "\n".join([self.stdout, self.stderr] + names)


def hops(o, count, final=None, host=HOST):
    """/r0 redirects to /r1 ... and /r<count> answers `final` (a PNG by default): `count` redirects."""
    for i in range(count):
        o.serve("/r%d" % i, Response(302, b"", {"Location": "https://%s/r%d" % (host, i + 1)}), host)
    o.serve("/r%d" % count, final or Response(200, png(), {"Content-Type": "image/png"}), host)


# --- the URL ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://pics.example/a.png", "ftp://pics.example/a.png", "https://pics.example:8443/a.png", "https://pics.example:80/a.png",
    "https://user@pics.example/a.png", "https://user:pw@pics.example/a.png", "https://pics.example@files.example/a.png", "https:///a.png",
    "https://93.184.216.34/a.png", "https://[2606:4700::1111]/a.png", "https://[::1]/a.png", "https://0x5db8d822/a.png", "https://2130706433/a.png",
    "https://pics.example./a.png", "https://pics.example/a b.png", "https://pics.example/a\\b.png", "https://pics.example/a\nb.png", "https://pics.example/é.png",
    "https://localhost/a.png", "https://pics/a.png", "//pics.example/a.png", "pics.example/a.png", "", None, 5, "https://pics.example/" + "a" * 2030])
def test_each_url_rule_is_refused_before_any_lookup(url, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    raises("host_refused", o.fetch, url)
    assert o.files() == []


def test_a_url_of_2048_characters_is_accepted_and_one_more_is_not(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    head = "https://%s/" % HOST
    ok, long = head + "a" * (2048 - len(head)), head + "a" * (2049 - len(head))
    assert len(ok) == 2048 and len(long) == 2049
    o.serve("/" + "a" * (2048 - len(head)), Response(200, png(), {"Content-Type": "image/png"}))
    assert o.fetch(ok)["type"] == "image/png"
    raises("host_refused", o.fetch, long)


def test_port_443_the_query_and_an_upper_case_scheme_are_fine(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Response(200, png(), {"Content-Type": "image/png"}))
    for url in ("https://pics.example:443/a.png", "HTTPS://PICS.EXAMPLE/a.png?w=1&h=2#frag"):
        assert o.fetch(url)["host"] == HOST
    assert o.net.requests[1]["target"] == "/a.png?w=1&h=2"           # the fragment never leaves


@pytest.mark.parametrize("refuse", [[HOST], ["example"], ["PICS.example"]])
def test_a_refused_host_and_its_suffixes_are_refused(refuse, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    raises("host_refused", o.fetch, "https://%s/a.png" % HOST, refuse_hosts=refuse)
    raises("host_refused", o.fetch, "https://cdn.%s/a.png" % HOST, refuse_hosts=refuse[:1] if refuse != ["example"] else refuse)


def test_a_refused_name_is_not_a_prefix_match(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Response(200, png(), {"Content-Type": "image/png"}), "notpics.example")
    assert o.fetch("https://notpics.example/a.png", refuse_hosts=[HOST])["host"] == "notpics.example"


def test_an_allow_list_that_excludes_the_host_refuses_and_one_that_includes_it_accepts(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Response(200, png(), {"Content-Type": "image/png"}))
    o.serve("/a.png", Response(200, png(), {"Content-Type": "image/png"}), "cdn." + HOST)
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    raises("host_refused", o.fetch, "https://%s/a.png" % HOST, allow_hosts=[OTHER])
    monkeypatch.setitem(_net.SEAMS, "resolve", o.net.resolve)
    assert o.fetch("https://%s/a.png" % HOST, allow_hosts=[HOST])["host"] == HOST
    assert o.fetch("https://cdn.%s/a.png" % HOST, allow_hosts=[HOST])["host"] == "cdn." + HOST
    assert o.fetch("https://%s/a.png" % HOST, allow_hosts=[])["host"] == HOST          # an empty list allows every public host


def test_a_refused_host_wins_over_an_allowed_one(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    raises("host_refused", o.fetch, "https://cdn.%s/a.png" % HOST, allow_hosts=[HOST], refuse_hosts=["cdn." + HOST])


# --- addresses -------------------------------------------------------------------------------------------------------------------------

BAD = ["10.0.0.5", "172.16.0.9", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1",
       "::ffff:10.0.0.1", "::ffff:127.0.0.1", "64:ff9b::a00:1", "64:ff9b:1::a00:1", "::7f00:1", "2002:c0a8:101::1", "2002:7f00:1::1", "100::1", "2001:db8::1",
       "198.51.100.7", "not an address"]


@pytest.mark.parametrize("address", BAD)
def test_a_public_name_that_resolves_to_a_non_global_address_is_refused(address, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.net.address = address
    monkeypatch.setitem(_net.SEAMS, "opener", never)
    assert raises("address_refused", o.fetch, "https://%s/a.png" % HOST).host == HOST
    assert o.files() == []


def test_one_bad_address_among_good_ones_refuses_the_host(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    monkeypatch.setitem(_net.SEAMS, "resolve", lambda h, p, type=None: [(2, 1, 6, "", (kit.PUBLIC, p)), (2, 1, 6, "", ("10.0.0.5", p))])
    monkeypatch.setitem(_net.SEAMS, "opener", never)
    raises("address_refused", o.fetch, "https://%s/a.png" % HOST)


def test_the_connection_opens_the_address_that_was_checked_for_each_hop(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    book = {HOST: "93.184.216.34", OTHER: "93.184.216.35"}
    monkeypatch.setitem(_net.SEAMS, "resolve", lambda h, p, type=None: [(2, 1, 6, "", (book[h], p))])
    o.serve("/a", Response(302, b"", {"Location": "https://%s/b.png" % OTHER}))
    o.serve("/b.png", Response(200, png(), {"Content-Type": "image/png"}), OTHER)
    got = o.fetch("https://%s/a" % HOST)
    assert got["host"] == OTHER and [(r["host"], r["address"]) for r in o.net.requests] == [(HOST, "93.184.216.34"), (OTHER, "93.184.216.35")]


# --- redirects -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("count", [0, 1, 2])
def test_zero_one_and_two_redirects_are_followed(count, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    hops(o, count)
    got = o.fetch("https://%s/r0" % HOST)
    assert got["type"] == "image/png" and got["redirects"] == count and o.net.count() == count + 1


def test_a_third_redirect_is_refused_and_nothing_is_kept(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    hops(o, 3)
    raises("redirect_refused", o.fetch, "https://%s/r0" % HOST)
    assert o.net.count() == 3 and o.files() == []


def test_the_limit_is_the_callers(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    hops(o, 1)
    raises("redirect_refused", o.fetch, "https://%s/r0" % HOST, max_redirects=0)


def test_a_redirect_to_http_or_a_port_or_user_info_or_a_literal_is_refused_without_a_request(monkeypatch, tmp_path):
    for n, location in enumerate(("http://pics.example/x.png", "https://pics.example:8443/x.png", "https://u@pics.example/x.png", "https://10.0.0.5/x.png",
                                  "https://[::1]/x.png", "ftp://pics.example/x.png", "https://pics.example/x y.png")):
        sub = tmp_path / str(n)
        sub.mkdir()
        o = Open(sub, monkeypatch)
        o.serve("/a", Response(302, b"", {"Location": location}))
        raises("redirect_refused", o.fetch, "https://%s/a" % HOST)
        assert o.net.count() == 1


def test_a_redirect_to_a_host_that_resolves_privately_is_refused_and_no_connection_is_made_to_it(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    book = {HOST: kit.PUBLIC, OTHER: "10.0.0.5"}
    monkeypatch.setitem(_net.SEAMS, "resolve", lambda h, p, type=None: [(2, 1, 6, "", (book[h], p))])
    o.serve("/a", Response(302, b"", {"Location": "https://%s/b.png" % OTHER}))
    o.serve("/b.png", Response(200, png(), {"Content-Type": "image/png"}), OTHER)
    err = raises("address_refused", o.fetch, "https://%s/a" % HOST)
    assert err.host == OTHER and o.net.count(OTHER) == 0 and o.files() == []


def test_a_redirect_is_checked_against_the_refused_and_allowed_lists(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a", Response(302, b"", {"Location": "https://%s/b.png" % OTHER}))
    raises("redirect_refused", o.fetch, "https://%s/a" % HOST, refuse_hosts=[OTHER])
    raises("redirect_refused", o.fetch, "https://%s/a" % HOST, allow_hosts=[HOST])
    assert o.net.count(OTHER) == 0


def test_a_redirect_without_a_location_is_refused_and_a_relative_one_is_joined(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/none", Response(301, b"", {}))
    o.serve("/rel", Response(302, b"", {"Location": "/dir/b.png"}))
    o.serve("/dir/b.png", Response(200, png(), {"Content-Type": "image/png"}))
    raises("redirect_refused", o.fetch, "https://%s/none" % HOST)
    assert o.fetch("https://%s/rel" % HOST)["host"] == HOST


# --- what is sent ----------------------------------------------------------------------------------------------------------------------

def test_no_cookie_authorization_or_referer_is_ever_sent_and_a_set_cookie_is_ignored(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/r0", Response(302, b"", {"Location": "https://%s/r1" % HOST, "Set-Cookie": "session=abc; Path=/", "WWW-Authenticate": "Basic realm=x"}))
    o.serve("/r1", Response(200, png(), {"Content-Type": "image/png", "Set-Cookie": "again=1"}))
    o.fetch("https://%s/r0" % HOST)
    assert len(o.net.requests) == 2
    for request in o.net.requests:
        assert {k.lower(): v for k, v in request["headers"].items()} == {
            "user-agent": _net.USER_AGENT, "accept": "image/png, image/jpeg, video/mp4, video/webm", "accept-encoding": "identity"}


# --- status and size -------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status,code", [(404, "status"), (500, "status"), (204, "status"), (206, "status"), (403, "status"), (429, "rate_limited")])
def test_only_a_200_is_accepted(status, code, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Response(status, png(), {"Content-Type": "image/png"}))
    raises(code, o.fetch, "https://%s/a.png" % HOST)
    assert o.files() == []


class Unread(Response):
    def read(self, amount=None):
        raise AssertionError("a byte was read")


def test_a_content_length_over_the_cap_is_refused_before_a_byte_is_read(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Unread(200, b"", {"Content-Type": "image/png", "Content-Length": "101"}, length=False))
    raises("too_large", o.fetch, "https://%s/a.png" % HOST, cap=100)
    assert o.files() == []


def test_a_content_length_that_is_not_a_number_is_refused(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    for n, text in enumerate(("12abc", "-5", "1e3", "١٢")):
        o.serve("/a%d.png" % n, Unread(200, b"", {"Content-Length": text}, length=False))
        raises("status", o.fetch, "https://%s/a%d.png" % (HOST, n))


def test_a_body_one_byte_over_the_cap_with_no_length_is_refused_and_removed_and_exactly_the_cap_is_kept(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    body = (png() + b"\x00" * 2000)
    o.serve("/over.png", Response(200, body[:1001], {"Content-Type": "image/png"}, length=False))
    o.serve("/exact.png", Response(200, body[:1000], {"Content-Type": "image/png"}, length=False))
    raises("too_large", o.fetch, "https://%s/over.png" % HOST, cap=1000)
    assert o.files() == []
    got = o.fetch("https://%s/exact.png" % HOST, cap=1000)
    assert got["bytes"] == 1000 and o.files() == [os.path.basename(got["file"])]


def test_a_body_longer_than_its_length_is_refused_and_a_shorter_one_is_a_network_failure(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    body = png() + b"\x00" * 300
    o.serve("/long.png", Response(200, body, {"Content-Type": "image/png", "Content-Length": str(len(body) - 10)}, length=False))
    o.serve("/short.png", Response(200, body, {"Content-Type": "image/png", "Content-Length": str(len(body) + 10)}, length=False))
    raises("too_large", o.fetch, "https://%s/long.png" % HOST)
    raises("network", o.fetch, "https://%s/short.png" % HOST)
    assert o.files() == []


def test_a_body_that_dribbles_in_small_blocks_is_still_sniffed_and_counted(monkeypatch, tmp_path):
    class Slow(Response):
        def read(self, amount=None):
            return super().read(min(amount or 3, 3))
    o = Open(tmp_path, monkeypatch)
    body = png(8, 8)
    o.serve("/a.png", Slow(200, body, {"Content-Type": "image/png"}))
    got = o.fetch("https://%s/a.png" % HOST)
    assert (Path(got["file"]).read_bytes()) == body and got["bytes"] == len(body)
    o.serve("/b.html", Slow(200, b"<html>" + b"x" * 50, {"Content-Type": "image/png"}))
    raises("type_refused", o.fetch, "https://%s/b.html" % HOST)


def test_the_deadline_covers_every_read(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    clock = [100.0]
    monkeypatch.setitem(_net.SEAMS, "clock", lambda: clock[0])

    class Late(Response):
        def read(self, amount=None):
            clock[0] += 31
            return super().read(amount)
    o.serve("/a.png", Late(200, png() + b"\x00" * 500, {"Content-Type": "image/png"}))
    raises("network", o.fetch, "https://%s/a.png" % HOST, timeout=30.0)
    assert o.files() == []


# --- the type is read from the bytes ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("body", [b"<!doctype html><html><body>no</body></html>", b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'/>", b"<svg/>",
                                  b"RIFF\x24\x00\x00\x00WEBPVP8 ", b"GIF89a\x01\x00\x01\x00", b"GIF87a\x01\x00", b"BM\x00\x00\x00\x00", b"%PDF-1.7\n", b"PK\x03\x04",
                                  b"\x00" * 64, b"", b"\x89PNG", b"\xff\xd8", b"\x00\x00\x00\x18ftyp"[:7]])
def test_html_webp_gif_svg_and_the_rest_are_refused_whatever_the_header_says_and_nothing_is_kept(body, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    for n, kind in enumerate(("image/png", "image/jpeg", "video/mp4", "text/html")):
        o.serve("/a%d" % n, Response(200, body, {"Content-Type": kind}))
        raises("type_refused", o.fetch, "https://%s/a%d" % (HOST, n), types=IMAGE + CLIP)
    assert o.files() == []


@pytest.mark.parametrize("body,kind,extension", [(png(), "image/png", "png"), (jpeg(), "image/jpeg", "jpg"), (mp4(), "video/mp4", "mp4"),
                                                 (WEBM, "video/webm", "webm")])
def test_each_accepted_signature_is_kept_0600_in_quarantine_under_its_hash(body, kind, extension, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a", Response(200, body, {"Content-Type": "text/plain"}))             # the Content-Type is not trusted either way
    got = o.fetch("https://%s/a" % HOST, cap=100_000, types=IMAGE + CLIP)
    import hashlib
    digest = hashlib.sha256(body).hexdigest()
    assert got["type"] == kind and got["sha256"] == digest and got["bytes"] == len(body) and got["host"] == HOST
    assert got["file"] == os.path.join(o.q, "q-%s.%s" % (digest[:12], extension))
    assert Path(got["file"]).read_bytes() == body and stat.S_IMODE(os.stat(got["file"]).st_mode) == 0o600
    assert o.files() == ["q-%s.%s" % (digest[:12], extension)]


def test_a_type_outside_the_ones_asked_for_is_refused_and_a_clip_is_not_an_image(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.mp4", Response(200, mp4(), {"Content-Type": "image/png"}))
    o.serve("/a.png", Response(200, png(), {"Content-Type": "video/mp4"}))
    raises("type_refused", o.fetch, "https://%s/a.mp4" % HOST, types=IMAGE)
    raises("type_refused", o.fetch, "https://%s/a.png" % HOST, types=CLIP)
    assert o.fetch("https://%s/a.png" % HOST, types=IMAGE)["type"] == "image/png"


def test_the_first_bytes_are_sniffed_before_anything_is_written(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    seen = []
    real = os.open

    def spy(path, *a, **kw):
        seen.append(os.path.basename(str(path)))
        return real(path, *a, **kw)
    monkeypatch.setattr(os, "open", spy)
    o.serve("/a.html", Response(200, b"<html>" + b"x" * 400, {"Content-Type": "image/png"}))
    raises("type_refused", o.fetch, "https://%s/a.html" % HOST)
    assert not [n for n in seen if n.startswith(".part-") or n.startswith("q-")]


def test_a_failure_while_writing_removes_the_partial_file(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Response(200, png() + b"\x00" * 3000, {"Content-Type": "image/png"}, length=False))
    raises("too_large", o.fetch, "https://%s/a.png" % HOST, cap=1000)
    assert o.files() == []


# --- the quarantine folder -------------------------------------------------------------------------------------------------------------

def test_a_folder_that_is_not_the_quarantine_of_a_stock_folder_is_refused_before_any_lookup(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    monkeypatch.setitem(_net.SEAMS, "resolve", never)

    def folder(*parts, mode=0o700):
        path = tmp_path.joinpath(*parts)
        path.mkdir(parents=True)
        os.chmod(path, mode)
        return str(path)
    bad = [folder("a", "stock", "quarantined"), folder("b", "stock", "inbox"), folder("c", "other", "quarantine"), folder("d", "quarantine"),
           folder("e", "stock", "quarantine", mode=0o750), folder("f", "stock", "quarantine", mode=0o755), folder("g", "stock", "quarantine", mode=0o770),
           str(tmp_path / "missing" / "stock" / "quarantine"), "", None, 5]
    for dest in bad:
        raises("out_refused", _net.fetch_open, "https://%s/a.png" % HOST, 100, dest, IMAGE)
    link = tmp_path / "link"
    link.symlink_to(o.q)
    raises("out_refused", _net.fetch_open, "https://%s/a.png" % HOST, 100, str(link), IMAGE)


def test_a_quarantine_inside_a_reference_store_is_refused(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    marker = tmp_path / "media" / _net.MARKER
    marker.write_text("x")
    raises("out_refused", _net.fetch_open, "https://%s/a.png" % HOST, 100, o.q, IMAGE)
    code, got = o.verb("fetch", "https://%s/a.png" % HOST)
    assert code == 2 and got["code"] == "out_refused"


# --- the verbs -------------------------------------------------------------------------------------------------------------------------

def test_the_constants_are_the_specs_table():
    assert web.CAPS == {"preview_bytes": 4 * 1024 * 1024, "image_bytes": 16 * 1024 * 1024, "clip_bytes": 120 * 1024 * 1024, "preview_seconds": 30,
                        "image_seconds": 60, "clip_seconds": 180, "host_list": 100}
    assert web.PER_VIDEO == {"previews": 18, "files": 6} and (web.SERVES, web.SOURCE, web.VERBS) == ("stock:media", "web", ("preview", "fetch"))
    assert _net.OPEN_REDIRECTS == 2 and _net.OPEN_URL_MAX == 2048


def test_fetch_prints_the_file_and_the_hash_but_never_the_url(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/dir-%s/pic.png" % MARK, Response(200, png(), {"Content-Type": "image/png"}))
    url = "https://%s/dir-%s/pic.png?k=%s" % (HOST, MARK, MARK)
    code, got = o.verb("fetch", url)
    assert code == 0 and sorted(got) == ["bytes", "file", "host", "ok", "sha256", "type"] and got["host"] == HOST and got["type"] == "image/png"
    assert got["file"] == "q-%s.png" % got["sha256"][:12] and (Path(o.q) / got["file"]).is_file()
    assert o.stderr == "web: ok host=%s redirects=0\n" % HOST and MARK not in o.everything()


def test_preview_is_always_an_image_with_the_preview_cap_and_the_thumbnail_of_a_clip_is_one(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/t.jpg", Response(200, jpeg(), {"Content-Type": "image/jpeg"}))
    o.serve("/c.mp4", Response(200, mp4(), {"Content-Type": "video/mp4"}))
    o.serve("/w.webm", Response(200, WEBM, {"Content-Type": "video/webm"}))
    for kind in ("image", "clip"):
        code, got = o.verb("preview", "https://%s/t.jpg" % HOST, kind)
        assert code == 0 and got["type"] == "image/jpeg"
    for path in ("c.mp4", "w.webm"):
        code, got = o.verb("preview", "https://%s/%s" % (HOST, path), "clip")
        assert code == 1 and got["code"] == "type_refused"


def test_the_verb_caps_are_the_lower_of_the_named_cap_and_max_bytes(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    body = png() + b"\x00" * 5000
    o.serve("/a.png", Response(200, body, {"Content-Type": "image/png"}))
    assert o.verb("fetch", "https://%s/a.png" % HOST, "image", max_bytes=len(body))[0] == 0
    code, got = o.verb("fetch", "https://%s/a.png" % HOST, "image", max_bytes=len(body) - 1)
    assert code == 1 and got["code"] == "too_large"
    monkeypatch.setitem(web.CAPS, "preview_bytes", 100)
    code, got = o.verb("preview", "https://%s/a.png" % HOST, "image")
    assert code == 1 and got["code"] == "too_large"
    monkeypatch.setitem(web.CAPS, "image_bytes", 100)
    code, got = o.verb("fetch", "https://%s/a.png" % HOST, "image")
    assert code == 1 and got["code"] == "too_large"
    monkeypatch.setitem(web.CAPS, "clip_bytes", 100)
    o.serve("/c.mp4", Response(200, mp4(), {"Content-Type": "video/mp4"}))
    code, got = o.verb("fetch", "https://%s/c.mp4" % HOST, "clip")
    assert code == 1 and got["code"] == "too_large"


def test_the_deadlines_of_the_verbs_are_the_named_ones(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    seen = []
    real = _net.fetch_open
    monkeypatch.setattr(_net, "fetch_open", lambda *a, **kw: (seen.append(kw["timeout"]), real(*a, **kw))[1])
    o.serve("/a.png", Response(200, png(), {"Content-Type": "image/png"}))
    o.serve("/c.mp4", Response(200, mp4(), {"Content-Type": "video/mp4"}))
    o.verb("preview", "https://%s/a.png" % HOST)
    o.verb("fetch", "https://%s/a.png" % HOST)
    o.verb("fetch", "https://%s/c.mp4" % HOST, "clip")
    assert seen == [30, 60, 180]


def test_a_clip_is_fetched_as_mp4_or_webm_and_the_person_s_lists_reach_the_check(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/c.mp4", Response(200, mp4(), {"Content-Type": "video/mp4"}))
    o.serve("/w.webm", Response(200, WEBM, {"Content-Type": "video/webm"}))
    assert o.verb("fetch", "https://%s/c.mp4" % HOST, "clip")[1]["type"] == "video/mp4"
    assert o.verb("fetch", "https://%s/w.webm" % HOST, "clip", "--allow-host", HOST, "--allow-host", OTHER)[1]["type"] == "video/webm"
    before = o.net.count()
    code, got = o.verb("fetch", "https://%s/c.mp4" % HOST, "clip", "--refuse-host", HOST)
    assert code == 1 and got["code"] == "host_refused"
    code, got = o.verb("fetch", "https://%s/c.mp4" % HOST, "clip", "--allow-host", OTHER)
    assert code == 1 and got["code"] == "host_refused" and o.net.count() == before


@pytest.mark.parametrize("flag,value", [("--refuse-host", "Pics.Example"), ("--refuse-host", "10.0.0.1"), ("--allow-host", "https://pics.example"), ("--allow-host", ""),
                                        ("--allow-host", "pics.example.")])
def test_a_host_list_entry_that_is_not_a_host_name_is_a_usage_refusal(flag, value, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    code, got = o.verb("fetch", "https://%s/a.png" % HOST, "image", flag, value)
    assert code == 2 and got["code"] == "query_refused" and o.net.count() == 0


def test_a_host_list_of_more_than_the_cap_is_refused(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    extra = []
    for i in range(web.CAPS["host_list"] + 1):
        extra += ["--refuse-host", "h%d.example" % i]
    code, got = o.verb("fetch", "https://%s/a.png" % HOST, "image", *extra)
    assert code == 2 and got["code"] == "query_refused" and o.net.count() == 0


def test_the_unverified_tier_is_refused_unless_the_caller_says_the_project_turned_it_on(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a.png", Response(200, png(), {"Content-Type": "image/png"}))
    for verb in ("preview", "fetch"):
        code, got = o.verb(verb, "https://%s/a.png" % HOST, allow=False)
        assert code == 1 and got["code"] == "licence_refused"
    assert o.net.count() == 0 and o.files() == []
    assert o.verb("fetch", "https://%s/a.png" % HOST)[0] == 0


def test_a_kind_the_source_file_does_not_serve_is_refused(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch, dict(SOURCE, kinds=["image"]))
    code, got = o.verb("fetch", "https://%s/c.mp4" % HOST, "clip")
    assert code == 2 and got["code"] == "query_refused" and o.net.count() == 0


@pytest.mark.parametrize("max_bytes", [0, -1])
def test_max_bytes_is_a_positive_number(max_bytes, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    code, got = o.verb("fetch", "https://%s/a.png" % HOST, "image", max_bytes=max_bytes)
    assert code == 2 and got["code"] == "query_refused" and o.net.count() == 0


def test_the_source_file_is_the_implementations_own_and_nothing_else(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    other = tmp_path / "web.json"
    other.write_text(json.dumps(SOURCE))
    code, got = o.verb("fetch", "https://%s/a.png" % HOST, source_file=str(other))
    assert code == 3 and got["code"] == "source_not_ready" and got["fields"] == ["source_file"] and o.net.count() == 0


@pytest.mark.parametrize("change", [{"licence_tier": "library"}, {"licence_tier": "per-item"}, {"secret_in": "header"}, {"terms_read_on": "2026-11-10"},
                                    {"kinds": []}, {"kinds": ["audio"]}, {"kinds": ["image", "image"]}, {"source": "other"}, {"source": "Web"}])
def test_a_source_file_that_is_not_the_open_web_one_is_not_ready(change, monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch, dict(SOURCE, **change))
    code, got = o.verb("fetch", "https://%s/a.png" % HOST)
    assert code == 3 and got["code"] == "source_not_ready" and got["fields"] and o.net.count() == 0


def test_a_source_file_with_extra_keys_is_not_ready(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch, dict(SOURCE, api={"host": "evil.example"}))
    code, got = o.verb("fetch", "https://%s/a.png" % HOST)
    assert code == 3 and got["code"] == "source_not_ready" and o.net.count() == 0


def test_the_committed_source_file_is_the_one_in_the_spec_and_is_ready_with_no_terms_date():
    data = json.loads(COMMITTED.read_text(encoding="utf-8"))
    assert data == SOURCE and list(data) == list(_stock.OPEN_KEYS)
    got = _stock.read_source(str(COMMITTED), kit.TODAY, "web", None)
    assert got["licence_tier"] == "unverified" and got["media_hosts"] == [] and got["terms_read_on"] is None
    assert set(got) - set(_stock.SOURCE_KEYS) == {"_patterns"} and set(_stock.SOURCE_KEYS) <= set(got)
    _stock.read_source(str(COMMITTED), "2099-01-01", "web", None)                 # exempt from the 365-day rule: it has no terms date


def test_a_usage_error_never_echoes_an_argument(monkeypatch, tmp_path, capsys):
    o = Open(tmp_path, monkeypatch)
    url = "https://%s/p-%s?k=%s" % (HOST, MARK, MARK)
    for argv in (["fetch", "--kind", "image", "--url", url, "--out", o.q, "--max-bytes", "5", url], ["fetch", "--kind", url], ["fetch", "--url", url],
                 ["--bogus", url], [url], ["fetch", "--kind", "image", "--url", url, "--out", o.q, "--max-bytes", url]):
        with pytest.raises(SystemExit) as stop:
            web.main(["--source-file", o.source_file, "--today", kit.TODAY] + argv)
        assert stop.value.code == 2
    seen = capsys.readouterr()
    assert MARK not in seen.out + seen.err and "usage error" in seen.err


def test_a_run_without_a_verb_is_a_usage_error(monkeypatch, tmp_path):
    out, err = io.StringIO(), io.StringIO()
    assert web.main(["--source-file", "x", "--today", kit.TODAY], out, err) == 2 and out.getvalue() == ""


# --- what is printed -------------------------------------------------------------------------------------------------------------------

def test_no_output_holds_a_path_or_a_query_of_the_url_on_success_or_on_any_refusal(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    secret_path, secret_query = "/deep-%s/a.png" % MARK, "?token=%s" % MARK
    o.serve("/deep-%s/a.png" % MARK, Response(200, png(), {"Content-Type": "image/png"}))
    o.serve("/html-%s" % MARK, Response(200, b"<html>%s</html>" % MARK.encode(), {"Content-Type": "image/png"}))
    o.serve("/loop-%s" % MARK, Response(302, b"", {"Location": "https://%s/loop-%s" % (HOST, MARK)}))
    o.serve("/to-http-%s" % MARK, Response(302, b"", {"Location": "http://%s/x-%s?k=%s" % (HOST, MARK, MARK)}))
    o.serve("/to-bad-%s" % MARK, Response(302, b"", {"Location": "https://%s/x-%s" % ("evil.example", MARK)}))
    o.serve("/big-%s" % MARK, Response(200, png() + b"\x00" * 600, {"Content-Type": "image/png"}))
    o.serve("/missing-%s" % MARK, Response(404, b"", {}))
    o.serve("/rate-%s" % MARK, Response(429, b"", {}))
    urls = ["https://%s%s%s" % (HOST, secret_path, secret_query), "https://%s/html-%s?x=%s" % (HOST, MARK, MARK), "https://%s/loop-%s?x=%s" % (HOST, MARK, MARK),
            "https://%s/to-http-%s?x=%s" % (HOST, MARK, MARK), "https://%s/to-bad-%s" % (HOST, MARK), "https://%s/big-%s?x=%s" % (HOST, MARK, MARK),
            "https://%s/missing-%s?x=%s" % (HOST, MARK, MARK), "https://%s/rate-%s" % (HOST, MARK), "http://%s/p-%s?x=%s" % (HOST, MARK, MARK),
            "https://user:%s@%s/p-%s" % (MARK, HOST, MARK), "https://10.0.0.5/p-%s?x=%s" % (MARK, MARK), "https://%s:%s/p" % (HOST, 9999)]
    log = []
    for url in urls:
        for verb in ("preview", "fetch"):
            code, got = o.verb(verb, url, max_bytes=400 if "big-" in url else 10_000_000)
            log.append(o.everything())
            assert code in (0, 1, 2, 3)
            assert (got["ok"] is True) == (code == 0)
    blob = "\n".join(log)
    for word in (MARK, "deep-", "token=", "loop-", "/p-"):
        assert word not in blob, word
    assert "web: " in blob and ("host=" + HOST) in blob


def test_a_refusal_names_the_code_and_the_host_that_was_reached(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    o.serve("/a", Response(302, b"", {"Location": "https://%s/b" % OTHER}))
    o.serve("/b", Response(404, b"", {}), OTHER)
    code, got = o.verb("fetch", "https://%s/a" % HOST)
    assert code == 1 and got == {"ok": False, "code": "status", "fields": []} and o.stderr == "web: status host=%s\n" % OTHER
    code, got = o.verb("fetch", "http://%s/a" % HOST)
    assert code == 1 and got["code"] == "host_refused" and o.stderr == "web: host_refused\n"


def test_an_exception_nobody_foresaw_is_a_fixed_refusal_with_no_text(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("https://%s/boom-%s" % (HOST, MARK))
    monkeypatch.setattr(_net, "fetch_open", boom)
    code, got = o.verb("fetch", "https://%s/a.png" % HOST)
    assert code == 1 and got["code"] == "network" and MARK not in o.stdout + o.stderr


def test_the_fake_network_is_never_reached_by_a_refused_verb(monkeypatch, tmp_path):
    o = Open(tmp_path, monkeypatch)
    monkeypatch.setitem(_net.SEAMS, "resolve", never)
    monkeypatch.setitem(_net.SEAMS, "opener", never)
    for url in ("http://%s/a.png" % HOST, "https://10.0.0.5/a.png", "https://%s:81/a.png" % HOST):
        assert o.verb("fetch", url)[0] == 1
    assert o.verb("fetch", "https://%s/a.png" % HOST, out=str(tmp_path))[0] == 2

"""Tests of the link reader and the fetch of a shared Google Drive file (runtime/cloud_fetch.py, package V1d-3, limit L70): the forms of a link that count, the
addresses that are never connected to, and every scheme, host, redirect and size rule of the fetch. No socket is opened: `resolve` and `opener` are fakes, and the
fake connection answers scripted responses with headers and a body stream. Every host that is not on the closed list is a `.example` name, every id is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_cloud_fetch.py
"""
from __future__ import annotations

import io
import socket
import ssl
import subprocess
import sys

import pytest

import standin_tree as st
from media_fixtures import body_of, mp4_head

cloud_fetch = st.load("cloud_fetch")
sources = st.load("sources")
FID = "FAKEfileID0123456789"
URL = cloud_fetch.download_url(FID)
GLOBAL = "8.8.8.8"
MP4 = body_of(mp4_head(), 64)


def refused(call, *args, **kwargs) -> str:
    with pytest.raises(cloud_fetch.CloudError) as caught:
        call(*args, **kwargs)
    return caught.value.code


class Response:
    def __init__(self, status, headers=None, body=b""):
        self.status = status
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.stream = io.BytesIO(body)

    def getheader(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def read(self, n=-1):
        return self.stream.read(n)


def ok(body=MP4, **headers):
    return Response(200, {"Content-Type": "video/mp4", "Content-Length": str(len(body)), **headers}, body)


def moved(location, status=302):
    return Response(status, {"Location": location})


class Fake:
    """The seams of `fetch`: `resolve` answers the addresses of a host (global by default), `opener` the scripted responses in order."""

    def __init__(self, *script, addresses=None, opener_error=None):
        self.script, self.addresses, self.opener_error = list(script), addresses or {}, opener_error
        self.resolved, self.opened, self.requests, self.closed = [], [], [], 0

    def resolve(self, host, port, type=0):
        self.resolved.append((host, port, type))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in self.addresses.get(host, [GLOBAL])]

    def opener(self, host, address, timeout):
        if self.opener_error:
            raise self.opener_error
        self.opened.append((host, address, timeout))
        return Connection(self)


class Connection:
    def __init__(self, fake):
        self.fake = fake

    def request(self, method, target, headers=None):
        self.fake.requests.append((self.fake.opened[-1][0], method, target, dict(headers or {})))

    def getresponse(self):
        return self.fake.script.pop(0)

    def close(self):
        self.fake.closed += 1


def run(fake, url=URL, cap=1 << 30):
    taken = []

    def receive(response, length):
        taken.append((response.read(), length))
        return {"length": length}
    got = cloud_fetch.fetch(url, receive, cap, resolve=fake.resolve, opener=fake.opener)
    return got, taken


# 1. the link


def test_the_three_forms_of_a_drive_link_give_the_id():
    forms = [f"https://drive.google.com/file/d/{FID}/view?usp=sharing", f"https://drive.google.com/file/d/{FID}",
             f"https://docs.google.com/file/d/{FID}/edit", f"https://drive.google.com/open?id={FID}",
             f"https://drive.google.com/uc?export=download&id={FID}", f"https://docs.google.com/open?id={FID}"]
    for link in forms:
        assert cloud_fetch.file_id(link) == FID, link
        assert cloud_fetch.file_id(f"Here it is: {link} thanks") == FID
    assert cloud_fetch.file_id(f"(see https://drive.google.com/file/d/{FID}/view)") == FID, "a sentence's closing mark is not part of the link"
    assert cloud_fetch.file_id(f"https://drive.google.com/file/d/{FID.lower()}-x_Y") == FID.lower() + "-x_Y"
    assert cloud_fetch.file_id(f"first https://drive.google.com/file/d/{FID}/view then https://drive.google.com/file/d/OTHERfileID0123456789/view") == FID


def test_every_other_text_gives_no_id():
    for text in (f"http://drive.google.com/file/d/{FID}/view", f"https://drive.google.com.example/file/d/{FID}/view",
                 f"https://evil.example/file/d/{FID}/view", f"https://x@drive.google.com/file/d/{FID}/view",
                 f"https://user:pw@drive.google.com/file/d/{FID}/view", f"https://drive.google.com:8443/file/d/{FID}/view",
                 f"https://drive.usercontent.google.com/file/d/{FID}/view", f"https://notdrive.google.com/file/d/{FID}/view",
                 "https://drive.google.com/file/d/short/view", f"https://drive.google.com/file/d/{'a' * 101}/view",
                 f"https://drive.google.com/drive/folders/{FID}", f"https://drive.google.com/open?id={FID}&id=OTHERfileID0123456789",
                 "https://drive.google.com/open", "https://drive.google.com/uc?export=download", "no link here", "", None, 5, FID):
        assert cloud_fetch.file_id(text) is None, text
    assert cloud_fetch.file_id(f"http://drive.google.com/file/d/{FID}/view and later https://drive.google.com/file/d/{FID}/view") == FID, "the first https link"
    assert cloud_fetch.file_id(f"https://evil.example/x then https://drive.google.com/file/d/{FID}/view") is None, "only the first link counts"


def test_the_id_pattern_is_the_one_of_the_sources_and_the_list_is_closed():
    assert cloud_fetch.FILE_ID.pattern == sources.DRIVE_FILE_ID.pattern
    assert cloud_fetch.HOSTS == ("drive.google.com", "docs.google.com", "drive.usercontent.google.com")
    assert cloud_fetch.MAX_REDIRECTS == 3
    assert cloud_fetch.download_url(FID) == f"https://drive.google.com/uc?export=download&id={FID}"
    assert set(cloud_fetch.CODES) == {"address", "redirect", "status", "no_length", "too_large", "not_shared", "network"}


# 2. the addresses


def test_a_host_with_any_address_that_is_not_global_is_refused():
    def resolve(addresses):
        return lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]
    for bad in (["127.0.0.1"], ["10.0.0.1"], ["192.168.1.9"], ["172.16.0.4"], ["169.254.169.254"], ["0.0.0.0"], ["100.64.0.1"], ["::1"], ["fc00::1"],
                ["fe80::1"], ["::ffff:127.0.0.1"], ["::ffff:10.0.0.1"], ["224.0.0.1"], ["93.184.216.34", "10.0.0.1"], ["10.0.0.1", "8.8.8.8"], ["not-an-address"], []):
        assert refused(cloud_fetch.check_address, "drive.google.com", resolve(bad)) == "address", bad
    assert refused(cloud_fetch.check_address, "drive.google.com", lambda h, p, type=0: None) == "address"
    assert cloud_fetch.check_address("drive.google.com", resolve(["8.8.8.8", "8.8.4.4"])) == "8.8.8.8", "the first address"
    assert cloud_fetch.check_address("drive.google.com", resolve(["2001:4860:4860::8888"])) == "2001:4860:4860::8888"


def test_the_resolver_is_asked_for_port_443_streams():
    fake = Fake(ok())
    run(fake)
    assert fake.resolved == [("drive.google.com", 443, socket.SOCK_STREAM)]


# 3. the fetch


def test_limit_70_a_recording_is_fetched_only_from_a_listed_host_over_https_from_a_global_address_within_its_size():
    """The whole rule in one place: the link, the host, the scheme, the address, the redirect and the size each refuse before a byte is kept."""
    assert cloud_fetch.file_id("https://evil.example/file/d/" + FID) is None and cloud_fetch.file_id("http://drive.google.com/file/d/" + FID) is None
    assert refused(run, Fake(ok()), "https://evil.example/uc") == "address" and refused(run, Fake(ok()), "http://drive.google.com/uc") == "address"
    assert refused(run, Fake(ok(), addresses={"drive.google.com": ["169.254.169.254"]})) == "address"
    assert refused(run, Fake(moved("https://evil.example/"))) == "redirect"
    assert refused(run, Fake(ok(body=MP4 + b"x"), opener_error=None), URL, 63) == "too_large"
    kept = []
    fake = Fake(moved("https://drive.usercontent.google.com/x"), ok())
    cloud_fetch.fetch(URL, lambda r, n: kept.append((r.read(), n)), 64, resolve=fake.resolve, opener=fake.opener)
    assert kept == [(MP4, 64)]



def test_a_200_with_a_length_hands_the_stream_and_the_length_to_receive():
    fake = Fake(ok())
    got, taken = run(fake)
    assert got == {"length": 64} and taken == [(MP4, 64)]
    assert fake.opened == [("drive.google.com", GLOBAL, cloud_fetch.TIMEOUT)], "the address checked is the address opened"
    [(host, method, target, headers)] = fake.requests
    assert (host, method, target) == ("drive.google.com", "GET", f"/uc?export=download&id={FID}")
    assert headers["User-Agent"] == cloud_fetch.USER_AGENT and headers["Accept"] == "*/*"
    assert fake.closed == 1


def test_the_opener_gets_the_address_the_check_returned_not_a_second_lookup():
    fake = Fake(ok(), addresses={"drive.google.com": ["8.8.4.4", "8.8.8.8"]})
    run(fake)
    assert fake.opened[0][1] == "8.8.4.4" and len(fake.resolved) == 1


def test_a_redirect_to_the_download_host_is_followed_and_each_hop_is_checked():
    fake = Fake(moved(f"https://drive.usercontent.google.com/download?id={FID}&export=download"), moved("/final?x=1", 303), ok())
    got, taken = run(fake)
    assert got == {"length": 64}
    assert [o[0] for o in fake.opened] == ["drive.google.com", "drive.usercontent.google.com", "drive.usercontent.google.com"]
    assert [r[2] for r in fake.requests] == [f"/uc?export=download&id={FID}", f"/download?id={FID}&export=download", "/final?x=1"]
    assert [h[0] for h in fake.resolved] == ["drive.google.com", "drive.usercontent.google.com", "drive.usercontent.google.com"]
    assert fake.closed == 3


def test_three_redirects_are_followed_and_a_fourth_is_refused():
    hop = "https://docs.google.com/next"
    fake = Fake(moved(hop), moved(hop, 307), moved(hop, 308), ok())
    assert run(fake)[0] == {"length": 64} and len(fake.opened) == 4
    fake = Fake(moved(hop), moved(hop), moved(hop), moved(hop), ok())
    assert refused(run, fake) == "redirect" and len(fake.opened) == 4 and fake.closed == 4
    for status in (301, 302, 303, 307, 308):
        assert run(Fake(moved(hop, status), ok()))[0] == {"length": 64}, status


def test_a_redirect_off_the_list_or_off_https_or_with_user_info_or_a_port_is_refused_and_never_opened():
    for where in ("https://evil.example/", "http://drive.google.com/", "https://drive.google.com.example/x", "https://x@drive.google.com/",
                  "https://drive.google.com:8443/x", "ftp://drive.google.com/x", "//evil.example/x", "https://127.0.0.1/", "https://localhost/",
                  "https://accounts.google.com/ServiceLogin"):
        fake = Fake(moved(where))
        assert refused(run, fake) == "redirect", where
        assert len(fake.opened) == 1 and fake.closed == 1, where
    fake = Fake(Response(302, {}))
    assert refused(run, fake) == "redirect", "a redirect with no Location"
    fake = Fake(moved("https://drive.google.com:443/ok"), ok())
    assert run(fake)[0] == {"length": 64}, "port 443 is the https port"


def test_a_redirect_to_a_host_on_the_list_that_resolves_to_a_private_address_is_refused():
    fake = Fake(moved("https://drive.usercontent.google.com/x"), ok(), addresses={"drive.usercontent.google.com": ["10.0.0.5"]})
    assert refused(run, fake) == "address" and len(fake.opened) == 1


def test_the_first_link_must_pass_the_same_rules_and_gives_address():
    for url in ("http://drive.google.com/uc?id=x", "https://evil.example/uc", "https://x@drive.google.com/uc", "https://drive.google.com:8443/uc", "not a url", ""):
        fake = Fake(ok())
        assert refused(run, fake, url) == "address", url
        assert fake.opened == [] and fake.resolved == []


def test_an_address_that_is_not_global_is_refused_before_anything_is_opened():
    fake = Fake(ok(), addresses={"drive.google.com": ["127.0.0.1"]})
    assert refused(run, fake) == "address" and fake.opened == [] and fake.requests == []


def test_an_html_answer_is_a_file_that_is_not_shared():
    for kind in ("text/html", "text/html; charset=utf-8", "TEXT/HTML"):
        fake = Fake(Response(200, {"Content-Type": kind, "Content-Length": "10"}, b"<html></html>"))
        assert refused(run, fake) == "not_shared"
        assert fake.closed == 1


def test_no_length_or_a_length_that_is_not_a_number_is_refused_and_nothing_is_read():
    for length in (None, "", "abc", "-5", "1.5", "0x10", "²"):
        headers = {"Content-Type": "video/mp4"}
        if length is not None:
            headers["Content-Length"] = length
        resp = Response(200, headers, MP4)
        assert refused(run, Fake(resp)) == "no_length", length
        assert resp.stream.tell() == 0, "no byte was read"


def test_a_length_over_the_cap_is_refused_before_receive_is_called():
    fake = Fake(Response(200, {"Content-Type": "video/mp4", "Content-Length": "65"}, MP4 + b"x"))
    called = []
    code = refused(cloud_fetch.fetch, URL, lambda *a: called.append(a), 64, resolve=fake.resolve, opener=fake.opener)
    assert code == "too_large" and called == []
    fake = Fake(ok())
    cloud_fetch.fetch(URL, lambda r, n: called.append(n), 64, resolve=fake.resolve, opener=fake.opener)
    assert called == [64], "a length equal to the cap is within it"


def test_any_other_status_is_refused():
    for status in (204, 400, 401, 403, 404, 429, 500, 503):
        assert refused(run, Fake(Response(status))) == "status", status


def test_network_failures_are_one_code_and_the_connection_is_closed():
    assert refused(run, Fake(opener_error=OSError("down"))) == "network"
    assert refused(run, Fake(opener_error=ssl.SSLError("bad certificate"))) == "network"
    import http.client
    assert refused(run, Fake(opener_error=http.client.HTTPException("odd"))) == "network"

    def resolve_fails(host, port, type=0):
        raise socket.gaierror("no such host")
    fake = Fake(ok())
    assert refused(cloud_fetch.fetch, URL, lambda *a: None, 1 << 30, resolve=resolve_fails, opener=fake.opener) == "network" and fake.opened == []

    class Breaks(Connection):
        def getresponse(self):
            raise ConnectionResetError("reset")
    fake = Fake()
    fake.opener = lambda host, address, timeout: (fake.opened.append((host, address, timeout)), Breaks(fake))[1]
    assert refused(run, fake) == "network" and fake.closed == 1

    class Odd(Response):
        def read(self, n=-1):
            raise http.client.IncompleteRead(b"", 5)
    fake = Fake(Odd(200, {"Content-Type": "video/mp4", "Content-Length": "64"}))
    assert refused(run, fake) == "network"


def test_a_failure_of_receive_itself_passes_through_and_the_connection_is_closed():
    fake = Fake(ok())

    def receive(response, length):
        raise ValueError("the store refused")
    with pytest.raises(ValueError):
        cloud_fetch.fetch(URL, receive, 1 << 30, resolve=fake.resolve, opener=fake.opener)
    assert fake.closed == 1


def test_the_error_names_only_its_code():
    for code in cloud_fetch.CODES:
        error = cloud_fetch.CloudError(code)
        assert str(error) == code and error.code == code


# 4. the connection


def test_connect_opens_the_checked_address_and_checks_the_host_name(monkeypatch):
    seen = {}
    sock = object()

    class Context:
        verify_mode = ssl.CERT_REQUIRED          # what HTTPSConnection reads when it is built (Python 3.9 reads it)
        check_hostname = True
        post_handshake_auth = None

        def wrap_socket(self, s, server_hostname=None):
            seen["wrapped"] = (s, server_hostname)
            return "wrapped"
    monkeypatch.setattr(cloud_fetch.socket, "create_connection", lambda address, timeout=None: (seen.__setitem__("opened", (address, timeout)), sock)[1])
    monkeypatch.setattr(cloud_fetch.ssl, "create_default_context", lambda: Context())
    conn = cloud_fetch.connect("drive.google.com", GLOBAL, 7)
    conn.connect()
    assert seen["opened"] == ((GLOBAL, 443), 7), "the address given, never a second lookup"
    assert seen["wrapped"] == (sock, "drive.google.com") and conn.sock == "wrapped"
    assert conn.host == "drive.google.com" and conn.port == 443


def test_connect_uses_the_default_context_that_checks_certificates():
    conn = cloud_fetch.connect("drive.google.com", GLOBAL, 5)
    assert conn._context.verify_mode == ssl.CERT_REQUIRED and conn._context.check_hostname is True


def test_the_module_starts_on_its_own():
    flags = ["--help"]
    done = subprocess.run([sys.executable, "-I", str(st.RUNTIME / "cloud_fetch.py"), *flags], capture_output=True, text=True, timeout=60, env={})
    assert done.returncode == 0 and "global" in done.stdout
    other = ["--nope"]
    assert subprocess.run([sys.executable, "-I", str(st.RUNTIME / "cloud_fetch.py"), *other], capture_output=True, text=True, timeout=60, env={}).returncode == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))

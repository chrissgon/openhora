"""The proxy on loopback, with seams for the resolver and the upstream connection. No outside address is ever reached."""
from __future__ import annotations

import json
import socket
import struct
import threading
import time

import pytest

import fetcher_kit  # noqa: F401  (puts providers/fetcher on the path)
import _proxy


def client_hello(name):
    """A minimal TLS ClientHello record whose server_name is `name` (None: no extension)."""
    ext = b""
    if name is not None:
        raw = name.encode()
        entry = b"\x00" + struct.pack(">H", len(raw)) + raw
        body = struct.pack(">H", len(entry)) + entry
        ext = struct.pack(">HH", 0, len(body)) + body
    hello = b"\x03\x03" + b"\x11" * 32 + b"\x00" + struct.pack(">H", 2) + b"\x13\x01" + b"\x01\x00" + struct.pack(">H", len(ext)) + ext
    handshake = b"\x01" + struct.pack(">I", len(hello))[1:] + hello
    return b"\x16\x03\x01" + struct.pack(">H", len(handshake)) + handshake


class Echo:
    """An upstream stand-in on loopback that answers each byte string with the same bytes."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.seen = []
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self.serve, args=(conn,), daemon=True).start()

    def serve(self, conn):
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    return
                self.seen.append(data)
                conn.sendall(data)
        except OSError:
            pass


@pytest.fixture
def run(tmp_path):
    echo = Echo()
    made = []

    def start(addresses=("8.8.8.8",), max_bytes=1 << 20, deadline=None, hosts=("media.aster.example",), suffixes=(".cdn.aster.example",)):
        out = tmp_path / ("out%d" % len(made))
        out.mkdir()
        proxy = _proxy.Proxy(hosts, suffixes, max_bytes, deadline or time.time() + 30, str(out), port=0, bind="127.0.0.1",
                             resolve=lambda host: list(addresses), connect=lambda a, p, t: socket.create_connection(("127.0.0.1", echo.port), 5))
        thread = threading.Thread(target=proxy.serve, daemon=True)
        thread.start()
        made.append((proxy, thread, out))
        return proxy, thread, out

    yield start
    for proxy, thread, out in made:
        (out / "stop").write_text("")
        thread.join(5)
    echo.server.close()


def ask(proxy, line, hello=None, read=1, wait=1.0):
    s = socket.create_connection(("127.0.0.1", proxy.port), 5)
    s.settimeout(wait)
    s.sendall(line)
    try:
        answer = s.recv(4096)
    except socket.timeout:
        answer = b""
    echoed = b""
    if hello is not None and answer.startswith(b"HTTP/1.1 200"):
        s.sendall(hello)
        try:
            echoed = s.recv(65536)
        except (socket.timeout, OSError):    # a reset is a close too
            echoed = b""
    s.close()
    return answer, echoed


def connect(host, port=443):
    return ("CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n" % (host, port, host, port)).encode()


def report(out, thread):
    (out / "stop").write_text("")
    thread.join(5)
    return json.loads((out / "proxy.json").read_text())


def test_an_allowed_name_tunnels_and_the_hello_is_forwarded(run):
    proxy, thread, out = run()
    answer, echoed = ask(proxy, connect("media.aster.example"), client_hello("media.aster.example"))
    assert answer.startswith(b"HTTP/1.1 200") and echoed == client_hello("media.aster.example")
    assert report(out, thread)["allowed"] == 1


def test_a_name_under_an_allowed_suffix_tunnels_and_the_suffix_alone_does_not(run):
    proxy, thread, out = run()
    assert ask(proxy, connect("v1.cdn.aster.example"), client_hello("v1.cdn.aster.example"))[0].startswith(b"HTTP/1.1 200")
    assert ask(proxy, connect("cdn.aster.example"))[0].startswith(b"HTTP/1.1 403")


@pytest.mark.parametrize("host", ["Media.Aster.Example.", "evil.example", "1.1.1.1", "media.aster.example.evil.example", "xn--.example", "a" * 64 + ".example",
                                  "media aster.example", "-media.aster.example", "localhost", "10.0.0.1"])
def test_a_name_off_the_closed_shape_or_the_list_is_refused_with_403(run, host):
    proxy, thread, out = run()
    assert ask(proxy, connect(host))[0].startswith((b"HTTP/1.1 403", b"HTTP/1.1 405"))
    r = report(out, thread)
    assert r["refused"] >= 1 and r["allowed"] == 0


def test_an_ip_literal_in_brackets_port_80_and_a_get_are_refused(run):
    proxy, thread, out = run()
    assert ask(proxy, b"CONNECT [2001:db8::1]:443 HTTP/1.1\r\n\r\n")[0].startswith(b"HTTP/1.1 40")
    assert ask(proxy, connect("media.aster.example", 80))[0].startswith(b"HTTP/1.1 403")
    assert ask(proxy, b"GET http://media.aster.example/ HTTP/1.1\r\n\r\n")[0].startswith(b"HTTP/1.1 405")
    assert report(out, thread)["allowed"] == 0


@pytest.mark.parametrize("address", ["10.0.0.5", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "224.0.0.1", "0.0.0.0", "::1", "fe80::1", "fc00::1",
                                     "64:ff9b::a00:1", "64:ff9b:1::1", "2002:a00:1::1", "::ffff:10.0.0.1", "ff02::1", "not-an-address"])
def test_a_name_that_resolves_to_an_address_that_is_not_global_is_refused(run, address):
    proxy, thread, out = run(addresses=(address,))
    assert ask(proxy, connect("media.aster.example"))[0].startswith(b"HTTP/1.1 403")
    assert report(out, thread)["allowed"] == 0


def test_one_bad_address_among_good_ones_refuses_the_name(run):
    proxy, thread, out = run(addresses=("8.8.8.8", "10.0.0.5"))
    assert ask(proxy, connect("media.aster.example"))[0].startswith(b"HTTP/1.1 403")


def test_global_addresses_pass_the_check():
    for address in ("8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "::ffff:8.8.8.8"):
        assert _proxy.address_ok(address) is True


def test_a_hello_with_another_name_and_one_with_none_close_the_tunnel(run):
    proxy, thread, out = run()
    answer, echoed = ask(proxy, connect("media.aster.example"), client_hello("other.aster.example"))
    assert answer.startswith(b"HTTP/1.1 200") and echoed == b""
    answer, echoed = ask(proxy, connect("media.aster.example"), client_hello(None))
    assert echoed == b""
    answer, echoed = ask(proxy, connect("media.aster.example"), b"GET / HTTP/1.1\r\n\r\n")
    assert echoed == b""
    r = report(out, thread)
    assert r["sni_refused"] == 3 and r["allowed"] == 0


def test_the_sni_is_compared_after_lowercasing():
    assert _proxy.parse_sni(client_hello("Media.Aster.Example")) == "media.aster.example"
    assert _proxy.parse_sni(client_hello(None)) is None and _proxy.parse_sni(b"\x16\x03\x01\x00\x01\x01") is None and _proxy.parse_sni(b"") is None


def test_the_byte_cap_cuts_a_tunnel_and_ends_the_run(run):
    proxy, thread, out = run(max_bytes=3000)
    s = socket.create_connection(("127.0.0.1", proxy.port), 5)
    s.settimeout(3)
    s.sendall(connect("media.aster.example"))
    assert s.recv(1024).startswith(b"HTTP/1.1 200")
    s.sendall(client_hello("media.aster.example"))
    s.recv(65536)
    try:
        for _ in range(20):
            s.sendall(b"x" * 1000)
            time.sleep(0.02)
    except OSError:
        pass
    thread.join(5)
    assert not thread.is_alive()
    r = json.loads((out / "proxy.json").read_text())
    assert r["bytes"] >= 3000


def test_the_deadline_ends_the_run(run):
    proxy, thread, out = run(deadline=time.time() + 0.5)
    thread.join(5)
    assert not thread.is_alive() and (out / "proxy.json").is_file()


def test_the_report_holds_names_and_counts_only(run):
    proxy, thread, out = run()
    ask(proxy, connect("secret-path.example"))
    ask(proxy, b"CONNECT media.aster.example:443/path?token=abc HTTP/1.1\r\n\r\n")
    r = report(out, thread)
    assert set(r) == {"allowed", "refused", "refused_hosts", "sni_refused", "bytes"}
    assert r["refused_hosts"] == ["secret-path.example"] and "token" not in json.dumps(r)


def test_at_most_eight_tunnels_are_open_at_once(run):
    proxy, thread, out = run()
    held = []
    for _ in range(8):
        s = socket.create_connection(("127.0.0.1", proxy.port), 5)
        s.sendall(connect("media.aster.example"))
        assert s.recv(1024).startswith(b"HTTP/1.1 200")
        held.append(s)
    s = socket.create_connection(("127.0.0.1", proxy.port), 5)
    s.settimeout(2)
    try:
        refused = s.recv(1024) == b""
    except (socket.timeout, OSError):
        refused = True
    assert refused
    for h in held:
        h.close()
    s.close()


def test_the_proxy_writes_ready_when_it_listens(run):
    proxy, thread, out = run()
    for _ in range(50):
        if (out / "ready").exists():
            break
        time.sleep(0.05)
    assert (out / "ready").exists()


def test_host_and_suffix_helpers():
    assert _proxy.host_ok("media.aster.example") and not _proxy.host_ok("1.2.3.4") and not _proxy.host_ok("a") and not _proxy.host_ok("a." * 130 + "ex")
    assert _proxy.host_listed("a.cdn.aster.example", {"x.example"}, [".cdn.aster.example"]) and not _proxy.host_listed("cdn.aster.example", set(), [".cdn.aster.example"])

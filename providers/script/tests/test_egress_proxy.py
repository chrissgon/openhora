"""Tests of the per-step egress proxy (providers/script/egress_proxy.py): which CONNECT it serves and which it refuses, by name and by
address, on real loopback sockets with a stand-in target; how it freezes the declared names; the budget; the refusals at its start.
The same proxy inside the real image, on a real internal network, is tested in test_script_docker.py (opt-in). Offline: no network but
loopback, no docker.

Run: uv run --with pytest==9.1.1 pytest providers/script/tests/test_egress_proxy.py
"""
from __future__ import annotations

import importlib.util
import socket
import threading
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("egress_proxy_under_test", HERE.parent / "egress_proxy.py")
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class Target:
    """A stand-in remote service on loopback that counts the connections it gets and answers each with one line."""

    def __init__(self):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.port, self.accepted = self.listener.getsockname()[1], 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            self.accepted += 1
            try:
                conn.sendall(b"hello from the target\n")
                conn.shutdown(socket.SHUT_WR)
            except OSError:
                pass
            conn.close()


@pytest.fixture
def target():
    found = Target()
    yield found
    found.listener.close()


def serve(frozen, cap=10 ** 9):
    logs = []
    handler = proxy.make_handler(frozen, proxy.Budget(cap), threading.Semaphore(8), logs.append)
    server = proxy.Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, logs


@pytest.fixture
def running(target):
    frozen = proxy.freeze({("allowed.example", target.port)}, allow_private=True, resolver=lambda host, port: ["127.0.0.1"])
    server, logs = serve(frozen)
    yield server.server_address[1], logs, target
    server.shutdown()
    server.server_close()


def ask(port, request: bytes, read=4096):
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(request)
        s.settimeout(5)
        data = b""
        try:
            while True:
                chunk = s.recv(read)
                if not chunk:
                    break
                data += chunk
        except socket.timeout:
            pass
        return data


def connect(port, authority):
    return ask(port, f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode())


def status(reply: bytes) -> int:
    return int(reply.split(b" ")[1])


def test_a_declared_name_and_port_is_served_and_the_bytes_of_the_target_come_through(running):
    port, logs, target = running
    reply = connect(port, f"allowed.example:{target.port}")
    assert status(reply) == 200 and reply.endswith(b"hello from the target\n")
    assert logs == [f"allow allowed.example:{target.port}"] and target.accepted == 1


def test_the_name_is_compared_after_lowercasing_and_dropping_one_trailing_dot(running):
    port, _, target = running
    assert status(connect(port, f"ALLOWED.Example.:{target.port}")) == 200


@pytest.mark.parametrize("authority,reason", [
    ("other.example:{p}", "undeclared"), ("allowed.example:1", "undeclared"), ("allowed.example.evil.example:{p}", "undeclared"),
    ("evil-allowed.example:{p}", "undeclared"), ("allowed.example..:{p}", "undeclared"),
    ("127.0.0.2:{p}", "address"), ("10.0.0.5:{p}", "address"), ("169.254.169.254:80", "address"), ("[::1]:{p}", "address"),
    ("[fe80::1]:80", "address"), ("0.0.0.0:{p}", "address"), ("127.0.0.1:1", "address"),
    ("2130706433:{p}", "undeclared"), ("0x7f000001:{p}", "undeclared"), ("017700000001:{p}", "undeclared"), ("127.1:{p}", "undeclared"),
    ("localhost:{p}", "undeclared")])
def test_everything_not_declared_is_refused_by_name_or_by_address_and_the_target_is_never_called(running, authority, reason):
    port, logs, target = running
    reply = connect(port, authority.format(p=target.port))
    assert status(reply) == 403, authority
    assert logs == [f"deny {reason}"] and target.accepted == 0


def test_an_ip_literal_that_is_in_the_resolution_of_a_declared_name_is_served(running):
    port, logs, target = running
    assert status(connect(port, f"127.0.0.1:{target.port}")) == 200 and logs == [f"allow 127.0.0.1:{target.port}"]


def test_the_literal_of_a_declared_address_with_another_port_is_refused(running):
    port, logs, target = running
    assert status(connect(port, f"127.0.0.1:{target.port + 1}")) == 403 and logs == ["deny address"] and target.accepted == 0


MALFORMED = [
    (b"GET http://allowed.example/ HTTP/1.1\r\nHost: allowed.example\r\n\r\n", 405),
    (b"POST / HTTP/1.1\r\n\r\n", 405),
    (b"nonsense\r\n\r\n", 400),
    (b"CONNECT allowed.example HTTP/1.1\r\n\r\n", 403),
    (b"CONNECT allowed.example:xx HTTP/1.1\r\n\r\n", 403),
    (b"CONNECT  HTTP/1.1\r\n\r\n", 400),
    (b"CONNECT a b HTTP/1.1\r\n\r\n", 400),
    (b"CONNECT allowed.example:1 HTTP/2\r\n\r\n", 400),
    (b"CONNECT " + b"a" * 400 + b":80 HTTP/1.1\r\n\r\n", 400),
    (b"CONNECT allowed.example:1 HTTP/1.1\r\n\r\nGET / HTTP/1.1\r\n\r\n", 400),
    (b"CONNECT allowed.example:1 HTTP/1.1\r\n" + b"X: " + b"y" * 9000 + b"\r\n\r\n", 400)]
def test_only_a_well_formed_connect_is_looked_at_and_anything_else_is_refused(running):
    port, _, target = running
    for request_bytes, code in MALFORMED:
        assert status(ask(port, request_bytes)) == code, request_bytes[:60]
    assert target.accepted == 0


def test_a_connection_to_a_declared_address_that_does_not_answer_is_a_bad_gateway(target):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    free = dead.getsockname()[1]
    dead.close()
    frozen = proxy.freeze({("allowed.example", free)}, allow_private=True, resolver=lambda host, port: ["127.0.0.1"])
    server, logs = serve(frozen)
    try:
        assert status(connect(server.server_address[1], f"allowed.example:{free}")) == 502 and logs == ["deny unreachable"]
    finally:
        server.shutdown()
        server.server_close()


def test_the_proxy_dials_the_frozen_address_and_never_looks_a_name_up_again(target):
    calls = []

    def resolver(host, port):
        calls.append(host)
        return ["127.0.0.1"]

    frozen = proxy.freeze({("allowed.example", target.port)}, allow_private=True, resolver=resolver)
    server, _ = serve(frozen)
    try:
        for _ in range(3):
            assert status(connect(server.server_address[1], f"allowed.example:{target.port}")) == 200
    finally:
        server.shutdown()
        server.server_close()
    assert calls == ["allowed.example"], "the name was resolved once, at the start, and the answer kept"


def test_the_byte_budget_of_the_step_ends_a_tunnel(target):
    frozen = proxy.freeze({("allowed.example", target.port)}, allow_private=True, resolver=lambda host, port: ["127.0.0.1"])
    server, _ = serve(frozen, cap=5)
    try:
        reply = connect(server.server_address[1], f"allowed.example:{target.port}")
        assert status(reply) == 200 and b"hello from the target" not in reply
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("address", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "::1", "fc00::1", "fe80::1", "100.64.0.1", "192.168.1.1",
                                     "172.16.0.1", "0.0.0.0", "224.0.0.1", "192.0.2.1", "255.255.255.255", "::ffff:10.0.0.1", "::ffff:127.0.0.1",
                                     "ff02::1", "::"])
def test_a_declared_name_that_resolves_to_an_address_that_is_not_public_is_refused_at_the_start(address):
    with pytest.raises(proxy.Refused) as refused:
        proxy.freeze({("api.example", 443)}, resolver=lambda host, port: [address])
    assert (refused.value.code, refused.value.what) == ("not_public", "api.example")


def test_one_private_address_among_public_ones_refuses_the_whole_name():
    with pytest.raises(proxy.Refused) as refused:
        proxy.freeze({("api.example", 443)}, resolver=lambda host, port: ["8.8.8.8", "10.0.0.1"])
    assert refused.value.code == "not_public"


def test_public_addresses_are_frozen_sorted_and_a_name_that_does_not_resolve_is_refused():
    frozen = proxy.freeze({("api.example", 443)}, resolver=lambda host, port: ["8.8.4.4", "8.8.8.8", "8.8.8.8"])
    assert frozen == {("api.example", 443): ["8.8.4.4", "8.8.8.8"]}
    for answer in ([], OSError("no")):
        def resolver(host, port, answer=answer):
            if isinstance(answer, Exception):
                raise answer
            return answer
        with pytest.raises(proxy.Refused) as refused:
            proxy.freeze({("api.example", 443)}, resolver=resolver)
        assert refused.value.code == "unresolvable"


def test_the_decisions_as_a_table():
    frozen = {("api.example", 443): ["8.8.8.8", "2001:4860:4860::8888"]}
    table = {
        "api.example:443": (True, "declared"), "API.EXAMPLE.:443": (True, "declared"), "8.8.8.8:443": (True, "address_declared"),
        "[2001:4860:4860::8888]:443": (True, "address_declared"), "8.8.8.8:80": (False, "address"), "9.9.9.9:443": (False, "address"),
        "api.example:80": (False, "undeclared"), "x.example:443": (False, "undeclared"), "api.example": (False, "malformed"),
        "api.example:": (False, "malformed"), ":443": (False, "malformed"), "api.example:0": (False, "malformed"),
        "api.example:99999": (False, "malformed"), "api.example:-1": (False, "malformed")}
    for authority, (allowed, reason) in table.items():
        got = proxy.decide(authority, frozen)
        assert (got[0], got[1]) == (allowed, reason), authority


def test_declarations_are_names_with_a_dot_and_a_port_and_nothing_else():
    assert proxy.parse_declared(["Api.Example.:443", "api.example:443"]) == {("api.example", 443)}
    for bad in ("api.example", "api.example:0", "api.example:70000", "localhost:80", "127.0.0.1:80", "[::1]:80", "a.b.1:80", "0x7f.0x0.0x0.0x1:80",
                "*.example:80", "a_b.example:80", "", ":80"):
        with pytest.raises(proxy.Refused):
            proxy.parse_declared([bad])
    with pytest.raises(proxy.Refused):
        proxy.parse_declared([])


def test_a_refused_declaration_ends_the_proxy_before_it_listens(monkeypatch, capsys):
    monkeypatch.setattr(proxy.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 0))])
    assert proxy.main(["--allow", "api.example:443"]) == proxy.EXIT_REFUSED
    assert capsys.readouterr().out.strip() == "refused not_public api.example"
    assert proxy.main(["--allow", "10.0.0.1:443"]) == proxy.EXIT_REFUSED
    assert capsys.readouterr().out.strip().startswith("refused bad_declaration")
    assert proxy.main(["--listen", "0.0.0.0:3128"]) == proxy.EXIT_REFUSED       # nothing declared: nothing to serve
    assert proxy.main(["--bogus"]) == 2 and proxy.main(["--max-bytes", "x", "--allow", "a.example:1"]) == 2


def test_the_private_switch_is_in_the_proxy_and_in_no_verb_of_the_host(monkeypatch):
    text = (HERE.parent / "container.py").read_text(encoding="utf-8")
    # the host module passes it only where a caller of run_script / build_deps names allow_private; no verb, flag or argument reads it
    assert text.count("--allow-private") == 1 and "allow_private" in text
    for forbidden in ('"--allow-private"', "'--allow-private'"):
        assert forbidden not in text.split("def cmd_run", 1)[1]

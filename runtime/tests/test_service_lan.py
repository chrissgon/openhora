"""Tests of the opt-in `--lan` of the local service (R4-C4, A-63, M-22): off by default, and without it nothing changes; with
it the service also listens on one private LAN address (never 0.0.0.0, never a public address), accepts that Host and Origin
and no other, prints a warning before the address, and answers GET /token-file to the loopback only. Offline: no socket
is opened toward another host, the address detection is replaced, ports are 0 and every server is closed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service_lan.py
"""
from __future__ import annotations

import http.client
import inspect
import json
import os
import socket
import threading
import types

import pytest

import standin_tree as st
from test_service import (PORT, TOKEN, WAIT, Standin, STATUS, call, run_serve, world)  # noqa: F401  (the service fixtures)

service = st.load("service")

LAN = "192.168.1.20"
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def headers(host, origin=None, method="GET", auth=True):
    out = {"Host": host}
    if origin is not None:
        out["Origin"] = origin
    if auth:
        out["Authorization"] = f"Bearer {TOKEN}"
    if method == "POST":
        out.update({"Content-Type": "application/json", "Content-Length": "2"})
    return out


def check(host, origin=None, *, lan_ip=None, method="GET", path="/api/v1/projects", port=PORT):
    return service.check_request(method, path, headers(host, origin, method), port, TOKEN, lan_ip)


class Events:
    """Standard output and the log of one run in one list, in the order they were written."""

    def __init__(self):
        self.items = []

    def write(self, text):
        if text:
            self.items.append(("out", text))

    def flush(self):
        pass

    def log(self, line):
        self.items.append(("log", line))

    def logged(self):
        return "\n".join(t for kind, t in self.items if kind == "log")


class RecordingServer:
    """A server that opens no socket; remembers the address it was asked to bind, answers port 0 with a fixed port."""

    instances = []

    def __init__(self, address, handler):
        self.requested = address
        self.RequestHandlerClass = handler
        self.server_address = (address[0], address[1] or 4321)
        self.down = threading.Event()
        self.closed = False
        self.shut = False
        RecordingServer.instances.append(self)

    def serve_forever(self, poll_interval=0.5):
        self.down.wait(WAIT * 3)

    def shutdown(self):
        self.shut = True
        self.down.set()

    def server_close(self):
        self.closed = True


@pytest.fixture
def servers():
    RecordingServer.instances = []
    yield RecordingServer.instances
    RecordingServer.instances = []


@pytest.fixture
def project(tmp_path):
    folder = tmp_path / "alpha"
    folder.mkdir()
    return str(folder)


# --- the default is unchanged -------------------------------------------------------------------------------------------


def test_without_lan_the_default_is_off_and_the_service_binds_the_loopback_only(tmp_path, project, servers):
    assert "lan" not in service.parse(["--project", "a"]), "the parsed command is the one it always was"
    fake = Standin(tmp_path / "data")
    out = Events()
    run = run_serve(fake, [project], RecordingServer, out=out, log=out.log)
    try:
        assert [s.requested for s in servers] == [("127.0.0.1", 0)], "one socket, on the loopback"
        assert run.service.lan_ip is None
        printed = json.loads("".join(t for kind, t in out.items if kind == "out"))
        assert set(printed) == {"url", "token_file", "projects"} and printed["url"] == "http://127.0.0.1:4321/"
        assert "WARNING" not in out.logged() and "--lan" not in out.logged(), "no warning, no mention, unless asked"
    finally:
        assert run.finish() == 0
    assert servers[0].closed and servers[0].shut


def test_without_lan_main_calls_serve_exactly_as_before(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(service, "serve", lambda projects, port, poll_every, dispatch_every, token_file: seen.append(1) or 0)
    assert service.main(["--project", str(tmp_path)]) == 0 and seen == [1]


@pytest.mark.parametrize("host", [f"{LAN}:{PORT}", f"{LAN}", "10.0.0.5:8765", "localhost:9999", "evil.example:8765"])
def test_without_lan_another_host_is_refused_even_the_machines_lan_address(host):
    assert check(host) == (403, "host")
    assert check(f"127.0.0.1:{PORT}", f"http://{LAN}:{PORT}") == (403, "origin")
    assert check(f"127.0.0.1:{PORT}") is None and check(f"localhost:{PORT}") is None


def test_the_address_is_still_not_a_parameter_of_serve_and_the_old_flags_stay_refused():
    parameters = inspect.signature(service.serve).parameters
    assert "host" not in parameters and "bind" not in parameters and "lan" in parameters
    assert parameters["lan"].default is None
    for flag in ("--host", "--bind", "--address"):
        with pytest.raises(service.Refused):
            service.parse(["--project", "x", flag, "0.0.0.0"])
    assert service.HOST == "127.0.0.1"


# --- the flag -----------------------------------------------------------------------------------------------------------


def test_lan_alone_asks_for_detection_and_lan_with_an_address_names_it():
    assert service.parse(["--project", "a", "--lan"])["lan"] == "auto"
    assert service.parse(["--lan", "--project", "a"])["lan"] == "auto", "a flag after --lan is not its value"
    assert service.parse(["--project", "a", "--lan", LAN, "--port", "0"])["lan"] == LAN
    assert service.parse(["--project", "a", "--lan", "--no-dispatch"])["lan"] == "auto"


@pytest.mark.parametrize("address", ["10.0.0.1", "10.255.255.254", "172.16.0.5", "172.31.255.254", "192.168.0.9",
                                     "192.168.255.1", "169.254.3.4"])
def test_a_private_or_link_local_address_is_taken(address):
    assert service.parse(["--project", "a", "--lan", address])["lan"] == address
    assert service.check_lan_address(address) == address


@pytest.mark.parametrize("address", ["8.8.8.8", "172.32.0.1", "172.15.255.255", "192.169.0.1", "11.0.0.1", "100.64.0.1",
                                     "1.1.1.1", "127.0.0.1", "127.0.0.2", "0.0.0.0", "255.255.255.255", "224.0.0.1",
                                     "::1", "fe80::1", "example.com", "192.168.1", "192.168.1.256", "192.168.001.002", " 192.168.1.20",
                                     "8765", ""])
def test_a_public_unspecified_loopback_or_malformed_address_is_refused(address):
    with pytest.raises(service.Refused):
        service.parse(["--project", "a", "--lan", address])
    with pytest.raises(service.Refused):
        service.check_lan_address(address)


@pytest.mark.parametrize("address", ["192.168.1.0", "192.168.1.255", "10.0.0.0", "10.255.255.255", "172.16.0.0", "172.31.255.255", "169.254.0.255"])
def test_a_network_or_broadcast_address_is_refused(address):
    with pytest.raises(service.Refused, match="network or broadcast"):
        service.check_lan_address(address)
    with pytest.raises(service.Refused):
        service.parse(["--project", "a", "--lan", address])


def test_the_refusal_names_the_reason_for_an_unspecified_and_a_public_address():
    with pytest.raises(service.Refused, match="0.0.0.0"):
        service.check_lan_address("0.0.0.0")
    with pytest.raises(service.Refused, match="private"):
        service.check_lan_address("8.8.8.8")


def test_a_bad_lan_address_ends_the_command_with_the_usage_exit(capsys, tmp_path):
    assert service.main(["--project", str(tmp_path), "--lan", "8.8.8.8"]) == 2
    assert "error:" in capsys.readouterr().err
    assert service.main(["--project", str(tmp_path), "--lan", "0.0.0.0"]) == 2


def test_main_hands_serve_the_lan_choice_only_when_it_was_given(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(service, "serve", lambda projects, port, poll_every, dispatch_every, token_file, lan=None: seen.append(lan) or 0)
    assert service.main(["--project", str(tmp_path)]) == 0
    assert service.main(["--project", str(tmp_path), "--lan"]) == 0
    assert service.main(["--project", str(tmp_path), "--lan", LAN]) == 0
    assert seen == [None, "auto", LAN]


def test_the_detection_connects_a_udp_socket_and_sends_nothing(monkeypatch):
    log = []

    class FakeSocket:
        def __init__(self, family, kind, *rest):
            log.append(("socket", family, kind))

        def connect(self, address):
            log.append(("connect", address))

        def getsockname(self):
            return (LAN, 50000)

        def send(self, *a, **k):
            log.append("send")

        sendto = send

        def close(self):
            log.append("close")

    monkeypatch.setattr(service.socket, "socket", FakeSocket)
    assert service.detect_lan_ip() == LAN
    assert log[0] == ("socket", socket.AF_INET, socket.SOCK_DGRAM)
    assert "send" not in log and log[-1] == "close"
    target = [x for x in log if x[0] == "connect"][0][1][0]
    assert service.check_lan_address(target) == target, "the address it connects to is a private one: no host outside is asked"


def test_the_detection_gives_no_address_when_there_is_no_route(monkeypatch):
    class NoRoute:
        def __init__(self, *a):
            pass

        def connect(self, address):
            raise OSError("Network is unreachable")

        def close(self):
            pass

    monkeypatch.setattr(service.socket, "socket", NoRoute)
    assert service.detect_lan_ip() is None


# --- the serving --------------------------------------------------------------------------------------------------------


def test_lan_binds_the_one_private_address_and_the_loopback_on_the_same_port(tmp_path, project, servers):
    fake = Standin(tmp_path / "data")
    run = run_serve(fake, [project], RecordingServer, lan=LAN)
    try:
        assert [s.requested for s in servers] == [("127.0.0.1", 0), (LAN, 4321)]
        assert not [s for s in servers if s.requested[0] in ("0.0.0.0", "", "::")], "never every interface"
        assert run.service.lan_ip == LAN and run.service.port == 4321
    finally:
        assert run.finish() == 0
    assert all(s.closed and s.shut for s in servers), "both sockets are closed when the service stops"


def test_lan_without_an_address_detects_one_and_a_detected_public_address_is_refused(tmp_path, project, servers, monkeypatch, capsys):
    fake = Standin(tmp_path / "data")
    monkeypatch.setattr(service, "detect_lan_ip", lambda: "10.1.2.3")
    run = run_serve(fake, [project], RecordingServer, lan="auto")
    try:
        assert run.service.lan_ip == "10.1.2.3" and servers[1].requested == ("10.1.2.3", 4321)
    finally:
        assert run.finish() == 0
    servers.clear()
    for found in ("203.0.113.9", "0.0.0.0", "127.0.0.1", None):
        monkeypatch.setattr(service, "detect_lan_ip", lambda found=found: found)
        code = service.serve([project], port=0, poll_every=0, ops_module=fake, server_class=RecordingServer, lan="auto",
                             out=Events(), log=lambda line: None, interface_dir=None)
        assert code == 2, found
    assert servers == [], "nothing is bound when the address is refused"
    assert "--lan" in capsys.readouterr().err


def test_a_serve_given_a_public_address_directly_binds_nothing(tmp_path, project, servers, capsys):
    fake = Standin(tmp_path / "data")
    code = service.serve([project], port=0, poll_every=0, ops_module=fake, server_class=RecordingServer, lan="8.8.8.8",
                         out=Events(), log=lambda line: None, interface_dir=None)
    assert code == 2 and servers == []


def test_a_lan_address_that_cannot_be_bound_ends_the_start_and_closes_the_loopback_socket(tmp_path, project, servers, capsys):
    fake = Standin(tmp_path / "data")

    class OnlyLoopback(RecordingServer):
        def __init__(self, address, handler):
            if address[0] != "127.0.0.1":
                raise OSError(49, "Can't assign requested address")
            super().__init__(address, handler)

    out = Events()
    code = service.serve([project], port=0, poll_every=0, ops_module=fake, server_class=OnlyLoopback, lan=LAN,
                         out=out, log=out.log, interface_dir=None, token_file=str(tmp_path / "t.token"))
    assert code == 1 and servers[0].closed
    assert "cannot listen on 192.168.1.20" in capsys.readouterr().err
    assert not os.path.exists(tmp_path / "t.token") and not out.items, "no token written, no address printed"


# --- Host and Origin ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"{LAN}:{PORT}", f"{LAN.upper()}:{PORT}", f"LOCALHOST:{PORT}"])
def test_with_lan_the_host_is_the_loopback_the_name_or_the_lan_address_with_the_port(host):
    assert check(host, lan_ip=LAN) is None


@pytest.mark.parametrize("host", [
    "192.168.1.21:8765", "10.0.0.5:8765", f"{LAN}:9999", LAN, f"{LAN}:", f"{LAN}:08765", f" {LAN}:{PORT}", f"{LAN}:{PORT} ",
    f"{LAN}.evil.example:{PORT}", f"{LAN}:{PORT}.evil.example", f"evil.example:{PORT}", f"attacker.example:{PORT}",
    f"mybox.local:{PORT}", f"mybox:{PORT}", f"0.0.0.0:{PORT}", f"[::1]:{PORT}", f"[::ffff:{LAN}]:{PORT}", f"user@{LAN}:{PORT}",
    f"{LAN},127.0.0.1:{PORT}", "", None])
def test_with_lan_any_other_host_is_refused_including_a_dns_rebinding_name(host):
    broken = {"Authorization": f"Bearer {TOKEN}"}
    if host is not None:
        broken["Host"] = host
    assert service.check_request("GET", "/api/v1/projects", broken, PORT, TOKEN, LAN) == (403, "host")
    assert service.check_request("GET", "/", broken, PORT, TOKEN, LAN) == (403, "host"), "the static page too"
    assert service.check_request("GET", "/token-file", broken, PORT, TOKEN, LAN) == (403, "host")


@pytest.mark.parametrize("origin", [f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}", f"http://{LAN}:{PORT}"])
def test_with_lan_the_origin_is_one_of_the_three_http_origins(origin):
    assert check(f"{LAN}:{PORT}", origin, lan_ip=LAN) is None
    assert check(f"{LAN}:{PORT}", origin, lan_ip=LAN, method="POST", path="/api/v1/projects/x/pending") is None


@pytest.mark.parametrize("origin", [
    f"https://{LAN}:{PORT}", f"http://{LAN}:9999", f"http://{LAN}", f"http://192.168.1.21:{PORT}", f"http://evil.example:{PORT}",
    f"http://{LAN}.evil.example:{PORT}", f"http://attacker.example:{PORT}", "null", "http://", f"{LAN}:{PORT}", f"http://{LAN}:{PORT}/",
    f"http://0.0.0.0:{PORT}", f"file://{LAN}:{PORT}"])
def test_with_lan_any_other_origin_is_refused(origin):
    assert check(f"{LAN}:{PORT}", origin, lan_ip=LAN) == (403, "origin")
    assert check(f"127.0.0.1:{PORT}", origin, lan_ip=LAN) == (403, "origin")


def test_with_lan_a_post_without_an_origin_is_still_refused_and_the_token_is_still_needed():
    assert check(f"{LAN}:{PORT}", None, lan_ip=LAN, method="POST", path="/api/v1/projects/x/pending") == (403, "origin")
    bare = {"Host": f"{LAN}:{PORT}"}
    assert service.check_request("GET", "/api/v1/projects", bare, PORT, TOKEN, LAN) == (401, "token")
    assert service.check_request("GET", "/", bare, PORT, TOKEN, LAN) is None, "the static page holds no data"


def test_the_address_the_service_was_given_is_the_only_one_it_accepts_a_second_service_does_not_share_it():
    assert check(f"{LAN}:{PORT}", lan_ip="192.168.1.30") == (403, "host")
    assert check("192.168.1.30:8765", lan_ip="192.168.1.30") is None


@pytest.mark.parametrize("host,on_lan,expected", [
    (f"{LAN}:{PORT}", True, None), (f"127.0.0.1:{PORT}", True, (403, "host")), (f"localhost:{PORT}", True, (403, "host")),
    (f"{LAN}:{PORT}", False, (403, "host")), (f"127.0.0.1:{PORT}", False, None), (f"localhost:{PORT}", False, None),
    ("192.168.1.21:8765", True, (403, "host")), ("192.168.1.21:8765", False, (403, "host")), (f"{LAN}:9999", True, (403, "host"))])
def test_the_socket_a_request_came_in_on_decides_its_host(host, on_lan, expected):
    assert service.check_request("GET", "/", {"Host": host}, PORT, TOKEN, LAN, on_lan) == expected


@pytest.mark.parametrize("origin,on_lan,expected", [
    (f"http://{LAN}:{PORT}", True, None), (f"http://127.0.0.1:{PORT}", True, (403, "origin")), (f"http://localhost:{PORT}", True, (403, "origin")),
    (f"http://{LAN}:{PORT}", False, (403, "origin")), (f"http://127.0.0.1:{PORT}", False, None), (f"http://localhost:{PORT}", False, None)])
def test_the_socket_a_request_came_in_on_decides_its_origin(origin, on_lan, expected):
    host = f"{LAN}:{PORT}" if on_lan else f"127.0.0.1:{PORT}"
    assert service.check_request("GET", "/", {"Host": host, "Origin": origin}, PORT, TOKEN, LAN, on_lan) == expected


def test_a_lan_socket_of_a_service_without_an_address_accepts_nothing():
    assert service.check_request("GET", "/", {"Host": f"127.0.0.1:{PORT}"}, PORT, TOKEN, None, True) == (403, "host")


# --- end to end through the real handler --------------------------------------------------------------------------------


def request(port, path, host, *, origin=None, auth=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=WAIT)
    try:
        connection.putrequest("GET", path, skip_host=True)
        connection.putheader("Host", host)
        if origin:
            connection.putheader("Origin", origin)
        if auth:
            connection.putheader("Authorization", f"Bearer {auth}")
        connection.endheaders()
        answer = connection.getresponse()
        return answer.status, answer.read()
    finally:
        connection.close()


def test_the_lan_socket_is_told_from_the_loopback_one_by_the_address_it_was_reached_on():
    def conn(address):
        return types.SimpleNamespace(getsockname=lambda: address)

    assert service._on_lan(conn(("127.0.0.1", 1))) is False
    assert service._on_lan(conn(("127.0.0.2", 1))) is False
    assert service._on_lan(conn((LAN, 1))) is True
    assert service._on_lan(conn(("0.0.0.0", 1))) is True, "an address that is not the loopback is not trusted"
    assert service._on_lan(conn(("::1", 1, 0, 0))) is False
    assert service._on_lan(conn(("::ffff:127.0.0.1", 1, 0, 0))) is False
    assert service._on_lan(types.SimpleNamespace(getsockname=lambda: (_ for _ in ()).throw(OSError("closed")))) is True, "fails closed"
    assert service._on_lan(types.SimpleNamespace(getsockname=lambda: None)) is True
    assert service._on_lan(None) is True


def test_the_socket_decides_which_host_is_valid_on_a_real_service(tmp_path, project, monkeypatch):
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    interface = tmp_path / "interface"
    interface.mkdir()
    (interface / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")
    token_path = str(tmp_path / "t.token")
    served = {"lan": False}
    monkeypatch.setattr(service, "_on_lan", lambda connection: served["lan"])  # the second socket is not on this machine: stood in for
    created = []

    def factory(address, handler):
        # the LAN address is not on this machine: the second socket is a recording stub; the first is the real one.
        server = service.Server(address, handler) if address[0] == "127.0.0.1" else RecordingServer(address, handler)
        created.append(server)
        return server

    run = run_serve(fake, [project], factory, lan=LAN, token_file=token_path, interface_dir=str(interface))
    try:
        svc = run.service
        port = svc.port
        assert svc.lan_ip == LAN
        # a request on the loopback socket: the loopback Hosts only, the path of the token file is given
        status, body = request(port, "/token-file", f"127.0.0.1:{port}")
        assert status == 200 and json.loads(body)["token_file"] == os.path.abspath(token_path)
        assert request(port, "/", f"localhost:{port}")[0] == 200
        assert request(port, "/", f"{LAN}:{port}")[0] == 403, "the LAN Host is not valid on the loopback socket"
        assert request(port, "/", f"127.0.0.1:{port}", origin=f"http://{LAN}:{port}")[0] == 403
        assert request(port, "/", f"attacker.example:{port}")[0] == 403
        assert request(port, "/", f"127.0.0.1:{port + 1}")[0] == 403
        # a request on the LAN socket: that address and its origin only; no path of the token file; the page and the api work
        served["lan"] = True
        assert request(port, "/", f"{LAN}:{port}")[0] == 200
        assert request(port, "/", f"{LAN}:{port}", origin=f"http://{LAN}:{port}")[0] == 200
        assert request(port, "/api/v1/projects", f"{LAN}:{port}", auth=svc.token)[0] == 200
        assert request(port, "/api/v1/projects", f"{LAN}:{port}")[0] == 401
        status, body = request(port, "/token-file", f"{LAN}:{port}")
        assert status == 404 and token_path.encode() not in body and b"commands" not in body
        for host in (f"127.0.0.1:{port}", f"localhost:{port}", f"attacker.example:{port}", f"{LAN}:{port + 1}"):
            assert request(port, "/", host)[0] == 403, host
            assert request(port, "/token-file", host)[0] == 403, host
        assert request(port, "/", f"{LAN}:{port}", origin=f"http://127.0.0.1:{port}")[0] == 403
        assert request(port, "/", f"{LAN}:{port}", origin="http://attacker.example")[0] == 403
    finally:
        served["lan"] = False
        assert run.finish() == 0
    assert created[0].socket.fileno() == -1 and created[1].closed, "both sockets are closed"


def test_without_lan_the_handler_never_asks_which_socket_a_request_came_in_on(tmp_path, project, monkeypatch):
    fake = Standin(tmp_path / "data")
    interface = tmp_path / "interface"
    interface.mkdir()
    (interface / "index.html").write_text("<!doctype html><title>x</title>", encoding="utf-8")

    def boom(connection):
        raise AssertionError("the default path is the old one: it does not look at the socket")

    monkeypatch.setattr(service, "_on_lan", boom)
    run = run_serve(fake, [project], service.Server, interface_dir=str(interface), token_file=str(tmp_path / "t.token"))
    try:
        port = run.service.port
        assert run.service.lan_ip is None
        assert request(port, "/", f"127.0.0.1:{port}")[0] == 200
        assert request(port, "/token-file", f"localhost:{port}")[0] == 200
        assert request(port, "/", f"{LAN}:{port}")[0] == 403
    finally:
        assert run.finish() == 0


# --- /token-file ---------------------------------------------------------------------------------------------------------


def lan_service(world):
    world.svc.lan_ip = LAN
    world.svc.token_file = "/home/demo/shop/.workbench/service.token"
    return world


def test_token_file_answers_the_path_and_the_commands_to_the_loopback_only(world):
    lan_service(world)
    status, _, body = call(world, "GET", "/token-file", auth=False)
    assert status == 200 and body["token_file"] == "/home/demo/shop/.workbench/service.token" and "linux" in body["commands"]
    answer = service.handle(world.svc, "GET", "/token-file", headers(f"{LAN}:{PORT}", auth=False), b"", lan=True)
    assert answer[0] == 404
    assert b"/home/demo" not in answer[2] and b"commands" not in answer[2] and b"token_file" not in answer[2]


@pytest.mark.parametrize("host", [f"{LAN}:{PORT}", f"127.0.0.1:{PORT}", f"localhost:{PORT}"])
@pytest.mark.parametrize("auth", [False, True])
def test_a_request_from_the_lan_gets_no_path_with_or_without_the_token_and_whatever_the_host(world, host, auth):
    lan_service(world)
    answer = service.handle(world.svc, "GET", "/token-file", headers(host, auth=auth), b"", lan=True)
    assert answer[0] in (403, 404) and b"/home/demo" not in answer[2] and b"pbcopy" not in answer[2]
    assert json.loads(answer[2])["error"] in ("host", "not_found")
    assert world.fake.calls == []


def test_a_loopback_socket_with_a_lan_host_is_refused(world):
    lan_service(world)
    answer = service.handle(world.svc, "GET", "/token-file", headers(f"{LAN}:{PORT}", auth=False), b"")
    assert answer[0] == 403 and b"/home/demo" not in answer[2], "the LAN Host belongs to the LAN socket"


def test_the_lan_answer_is_the_answer_of_a_service_that_has_no_token_file(world):
    lan_service(world)
    from_lan = service.handle(world.svc, "GET", "/token-file", headers(f"{LAN}:{PORT}", auth=False), b"", lan=True)
    assert from_lan[0] == 404
    world.svc.token_file = None
    without = service.handle(world.svc, "GET", "/token-file", headers(f"127.0.0.1:{PORT}", auth=False), b"")
    assert from_lan[0] == without[0] == 404 and from_lan[2] == without[2]


def test_the_default_service_answers_the_token_file_path_as_before(world):
    world.svc.token_file = "/home/demo/shop/.workbench/service.token"
    assert world.svc.lan_ip is None
    status, _, body = call(world, "GET", "/token-file", auth=False)
    assert status == 200 and body["token_file"] == "/home/demo/shop/.workbench/service.token"


def test_the_api_and_the_static_files_are_served_with_the_lan_host_and_the_token(world):
    lan_service(world)
    for path, expect in (("/", 200), ("/api/v1/projects", 200)):
        answer = service.handle(world.svc, "GET", path, headers(f"{LAN}:{PORT}"), b"", lan=True)
        assert answer[0] == expect, path
    csp = service.handle(world.svc, "GET", "/", headers(f"{LAN}:{PORT}"), b"", lan=True)[1]["Content-Security-Policy"]
    assert csp == service.CSP, "the policy is not widened for the LAN"


# --- the warning --------------------------------------------------------------------------------------------------------


def test_the_warning_comes_first_then_the_address_then_the_json_line_and_never_holds_the_token(tmp_path, project, servers):
    fake = Standin(tmp_path / "data")
    out = Events()
    token_path = str(tmp_path / "svc.token")
    run = run_serve(fake, [project], RecordingServer, lan=LAN, out=out, log=out.log, token_file=token_path)
    try:
        kinds = [(kind, text) for kind, text in out.items]
        position = {}
        for number, (kind, text) in enumerate(kinds):
            if kind == "log" and "WARNING" in text:
                position.setdefault("warning", number)
            if kind == "log" and f"http://{LAN}:4321/" in text:
                position.setdefault("address", number)
            if kind == "out":
                position.setdefault("json", number)
        assert position["warning"] < position["address"] < position["json"], position
        logged = out.logged()
        for fact in ("unencrypted", "approve effects", "read the documents", "network you trust", "stop the service"):
            assert fact in logged, fact
        assert f"Open on the phone: http://{LAN}:4321/" in logged
        assert os.path.abspath(token_path) in logged, "the token file's path is printed, as it is in the JSON line"
        assert "paste" in logged
        assert run.service.token not in logged and run.service.token not in "".join(t for k, t in out.items if k == "out")
        for line in logged.splitlines():
            if "http://" in line:
                assert "?" not in line and "token=" not in line and "#" not in line, "the address carries nothing"
        printed = json.loads("".join(t for kind, t in out.items if kind == "out"))
        assert printed["url"] == "http://127.0.0.1:4321/" and printed["lan_url"] == f"http://{LAN}:4321/"
        assert set(printed) == {"url", "lan_url", "token_file", "projects"}
    finally:
        assert run.finish() == 0


def test_the_warning_is_logged_before_any_thread_listens(tmp_path, project, servers, monkeypatch):
    fake = Standin(tmp_path / "data")
    out = Events()
    real = RecordingServer.serve_forever

    def listening(self, poll_interval=0.5):
        out.items.append(("log", "LISTENING " + self.requested[0]))
        real(self, poll_interval)

    monkeypatch.setattr(RecordingServer, "serve_forever", listening)
    loops = []
    monkeypatch.setattr(service, "dispatch_loop", lambda svc, every, stop, op="dispatch": loops.append(op) or out.items.append(("log", "LOOP " + op)))
    run = run_serve(fake, [project], RecordingServer, lan=LAN, out=out, log=out.log, dispatch_every=30)
    try:
        deadline = __import__("time").monotonic() + WAIT
        while not [t for k, t in out.items if t.startswith("LISTENING") and LAN in t] and __import__("time").monotonic() < deadline:
            __import__("time").sleep(0.01)
        lines = [t for k, t in out.items]
        first = min(n for n, t in enumerate(lines) if t.startswith(("LISTENING", "LOOP")))
        warning = [n for n, t in enumerate(lines) if "WARNING" in t][0]
        address = [n for n, t in enumerate(lines) if "Open on the phone" in t][0]
        assert warning < address < first, (warning, address, first)
        assert loops, "the loops did start, after the warning"
    finally:
        assert run.finish() == 0


def test_the_warning_is_the_one_text_the_documents_quote():
    assert service.LAN_WARNING[0].startswith("WARNING")
    text = "\n".join(service.LAN_WARNING)
    for fact in ("plain HTTP", "unencrypted", "approve effects", "documents of the projects", "network you trust", "stop the service"):
        assert fact in text, fact
    assert "token=" not in text


def test_the_warning_is_on_standard_error_by_default(tmp_path, project, servers, capsys):
    fake = Standin(tmp_path / "data")
    out = Events()
    run = run_serve(fake, [project], RecordingServer, lan=LAN, out=out, log=service.shell_kit.default_log)
    try:
        err = capsys.readouterr().err
        assert "WARNING" in err and f"http://{LAN}:4321/" in err
        assert "WARNING" not in "".join(t for k, t in out.items if k == "out"), "standard output stays the one JSON line"
    finally:
        assert run.finish() == 0


# --- the documents ------------------------------------------------------------------------------------------------------


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_the_help_the_readmes_and_the_contract_state_the_option_the_risk_and_that_it_is_never_the_default(capsys):
    assert service.main(["--help"]) == 0
    helped = capsys.readouterr().out
    assert "--lan" in helped and "off by default" in helped and "unencrypted" in helped
    assert "There is no option for another address" not in helped
    for name in (("runtime", "README.md"), ("contracts", "runtime.md"), ("interface", "README.md")):
        text = read(*name)
        assert "--lan" in text, name
    contract = read("contracts", "runtime.md")
    assert "private" in contract and "never the default" in contract and "unencrypted" in contract
    assert "there is no option for another address" not in contract

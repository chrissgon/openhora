"""The streaming media route of the local service (POST /projects/<id>/media): rule 5's one exception, the refusals before the
body is read, the loopback socket only, the page's channel policy, the hardened headers, and an upload over a real socket.
The operations layer is the real one (the stand-in tree of standin_tree.py), so the route, the operation and the store are
tested together; ffmpeg makes the tiny synthetic videos, and the tests that need it are skipped where it is not installed.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_route.py
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import os
import socket
import threading
import time
import types
import urllib.parse

import pytest

import standin_tree as st
from media_fixtures import Body, Forbidden, needs_ffmpeg, make_mov, png
from test_channel_policy import set_channels
from test_service import PORT, TOKEN

lab = st.load("lab")
ops = st.load("ops")
ops_core = st.load("ops_core")
service = st.load("service")
media = st.load("media")

LAN = "192.168.1.20"


@pytest.fixture
def world(tmp_path, monkeypatch):
    built = st.build(tmp_path, monkeypatch, lab)
    monkeypatch.setattr(ops_core, "ROOT", str(built["tree"]))
    project = str(built["project"])
    ops.accept_config(project, ops.project_config.load(project)["sha256"])
    projects = [{"id": service.project_id(project), "name": "p", "path": project}]
    svc = service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None)
    return types.SimpleNamespace(svc=svc, project=project, pid=projects[0]["id"], data=str(built["data"]), tmp=tmp_path)


@pytest.fixture(scope="module")
def mov(tmp_path_factory):
    path = tmp_path_factory.mktemp("clip") / "a.mov"
    make_mov(path)
    return path.read_bytes()


def headers(length, *, host=f"127.0.0.1:{PORT}", content_type="application/octet-stream", origin="default", token=True, **extra):
    out = {"Host": host, "Content-Type": content_type}
    if length is not None:
        out["Content-Length"] = str(length)
    if origin == "default":
        out["Origin"] = f"http://{host}"
    elif origin is not None:
        out["Origin"] = origin
    if token:
        out["Authorization"] = f"Bearer {TOKEN}"
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def post(world, stream, length, *, lan=False, path=None, **kwargs):
    """What the socket's handler does: the rules of check_request, then the stream to handle_stream. (status, body)."""
    path = path or f"/api/v1/projects/{world.pid}/media"
    given = headers(length, **kwargs)
    refused = service.check_request("POST", path, given, world.svc.port, world.svc.token, world.svc.lan_ip, lan if world.svc.lan_ip else None)
    if refused:
        return refused[0], {"error": refused[1]}
    status, _, body = service.handle_stream(world.svc, "POST", path, given, stream, lan)
    return status, json.loads(body)


def left_over(data):
    found = []
    for folder, names, files in os.walk(os.path.join(data, "media")):
        found += [os.path.join(folder, n) for n in names + files if n not in (media.UPLOAD_LOCK, media.RECORD_LOCK)]
    return found


# --- the refusals, each before the body is read ----------------------------------------------------------------------------------------


def test_route_a_body_over_the_limit_is_refused_413_before_it_is_read(world):
    status, body = post(world, Forbidden(), media.MEDIA_MAX_BYTES + 1)
    assert (status, body["error"]) == (413, "too_large")
    assert left_over(world.data) == []


def test_route_a_missing_content_length_is_refused_411(world):
    status, body = post(world, Forbidden(), None)
    assert (status, body["error"]) == (411, "length")


def test_route_a_wrong_or_missing_origin_is_refused_403_and_a_wrong_token_401(world):
    assert post(world, Forbidden(), 100, origin="http://evil.example")[0] == 403
    assert post(world, Forbidden(), 100, origin=None)[0] == 403
    assert post(world, Forbidden(), 100, host="evil.example:80")[0] == 403
    assert post(world, Forbidden(), 100, token=False)[0] == 401


def test_route_the_octet_stream_exception_covers_this_route_only(world):
    other = f"/api/v1/projects/{world.pid}/requests"
    refused = service.check_request("POST", other, headers(10, content_type="application/octet-stream"), PORT, TOKEN)
    assert refused == (415, "content_type")
    assert service.check_request("POST", other, headers(10, content_type="application/json"), PORT, TOKEN) is None
    assert post(world, Forbidden(), 100, content_type="application/json") == (415, {"error": "content_type"})
    assert post(world, Forbidden(), 100, content_type="text/plain")[0] == 415
    assert [r["pattern"] for r in service.ROUTES if r["stream"]] == ["/projects/{p}/media"]


def test_route_a_type_that_is_not_video_is_refused_415_and_leaves_nothing(world):
    for payload in (b"this is plain text and not a video, though it is long enough", png()):
        status, body = post(world, io.BytesIO(payload), len(payload))
        assert (status, body["error"]) == (415, "media_type")
    assert left_over(world.data) == []


def test_route_a_request_on_the_lan_socket_is_not_a_route(world):
    world.svc.lan_ip = LAN
    ok = post(world, Forbidden(), 100, lan=False, content_type="application/json")        # the loopback socket reaches the rules
    assert ok[0] == 415
    status, body = post(world, Forbidden(), 100, lan=True, host=f"{LAN}:{PORT}")
    assert (status, body["error"]) == (404, "not_found")
    status, body = post(world, Forbidden(), 100, lan=True)                                  # the loopback host on the LAN socket: refused by Host
    assert status == 403
    assert left_over(world.data) == []


def test_route_a_non_loopback_host_never_reaches_the_store(world):
    path = f"/api/v1/projects/{world.pid}/media"
    status, _, body = service.handle_stream(world.svc, "POST", path, headers(100, host="10.0.0.5:8765"), Forbidden(), False)
    assert status == 404


def test_route_a_stream_with_a_query_or_an_unknown_project_is_refused(world):
    status, _, _ = service.handle_stream(world.svc, "POST", f"/api/v1/projects/{world.pid}/media?x=1", headers(100), Forbidden(), False)
    assert status == 400
    status, _, _ = service.handle_stream(world.svc, "POST", "/api/v1/projects/000000000000/media", headers(100), Forbidden(), False)
    assert status == 404


def test_route_the_pages_channel_policy_is_asked_before_the_body_is_read(world):
    set_channels(world.project, {"page": ["read"]})
    status, body = post(world, Forbidden(), 100)
    assert status == 409 and "/media-in is not enabled for this channel" in body["message"]
    set_channels(world.project, {"page": ["read", "media"]})
    status, body = post(world, io.BytesIO(b"x" * 64), 64)
    assert status == 415                                                                      # past the policy: the bytes are not a video


def test_route_hostile_headers_are_refused(world):
    pairs = [("Host", f"127.0.0.1:{PORT}"), ("X-Recording-Id", "0" * 16), ("X-Recording-Id", "1" * 16)]
    assert service.headers_of(pairs) is None                                                  # a header that must appear once, twice
    for name in ("X-Slot-Id", "X-File-Name"):
        assert service.headers_of([(name, "a"), (name, "b")]) is None
    for hostile in ("evil%E2%80%AEvom.mov", "a%00b", "caf\u00e9", "%FF", "a%2Fb"):      # a label is sanitised, never a reason to refuse
        status, body = post(world, io.BytesIO(b"x" * 64), 64, **{"X-File-Name": hostile})
        assert (status, body["error"]) == (415, "media_type"), hostile                  # past the name: the bytes are not a video
    status, body = post(world, Forbidden(), 64, **{"X-Recording-Id": "../../etc"})
    assert (status, body["error"]) == (400, "usage")
    status, body = post(world, Forbidden(), 64, **{"X-Recording-Id": "0" * 16})
    assert (status, body["error"]) == (404, "not_found")
    status, body = post(world, Forbidden(), 64, **{"X-Slot-Id": "a" * 12})
    assert (status, body["error"]) == (400, "usage")


# --- the list ------------------------------------------------------------------------------------------------------------------------


def test_route_media_list_answers_the_records_and_the_use_of_the_limits(world):
    record = media.create(world.data, posts={"instagram": "docs/marketing/posts/launch.md"})
    status, _, body = service.handle(world.svc, "GET", f"/api/v1/projects/{world.pid}/media", {"Host": f"127.0.0.1:{PORT}", "Authorization": f"Bearer {TOKEN}"}, b"")
    shown = json.loads(body)
    assert status == 200 and [r["id"] for r in shown["recordings"]] == [record["id"]]
    assert shown["limits"] == {"max_bytes": media.MEDIA_MAX_BYTES, "max_seconds": 300} and shown["usage"]["max_renders"] == media.MAX_RENDERS
    assert "path" not in json.dumps(shown["recordings"])


# --- over a real socket ----------------------------------------------------------------------------------------------------------------


class Running:
    def __init__(self, svc):
        self.server = service.Server(("127.0.0.1", 0), service.http.server.BaseHTTPRequestHandler)
        svc.port = self.server.server_address[1]
        self.server.RequestHandlerClass = service.make_handler(svc)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        self.port = svc.port

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def running(world):
    server = Running(world.svc)
    yield server
    server.stop()


def upload(port, pid, payload_chunks, length, **extra):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    head = {"Authorization": f"Bearer {TOKEN}", "Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/octet-stream",
            "Content-Length": str(length)}
    head.update(extra)
    connection.putrequest("POST", f"/api/v1/projects/{pid}/media", skip_accept_encoding=True)
    for key, value in head.items():
        connection.putheader(key, value)
    connection.endheaders()
    for chunk in payload_chunks:
        connection.send(chunk)
    response = connection.getresponse()
    return response.status, json.loads(response.read() or b"{}")


@needs_ffmpeg
def test_route_a_recording_uploads_in_chunks_over_the_loopback_socket_and_is_stored_and_hashed(world, running, mov):
    pieces = [mov[i:i + 4096] for i in range(0, len(mov), 4096)]
    status, body = upload(running.port, world.pid, pieces, len(mov), **{"X-File-Name": urllib.parse.quote("Clip 1 \u00e9.mov")})
    assert status == 200 and body["kind"] == "recording" and body["sha256"] == hashlib.sha256(mov).hexdigest() and body["name"] == "Clip 1 \u00e9.mov"
    stored = os.path.join(world.data, "media", body["recording"], "raw.mov")
    assert open(stored, "rb").read() == mov and (os.stat(stored).st_mode & 0o777) == 0o600
    assert body["facts"]["video_codec"] == "h264"
    # the same recording takes no second raw file; an asset needs its slot
    status, again = upload(running.port, world.pid, [mov], len(mov), **{"X-Recording-Id": body["recording"]})
    assert status == 409 and again["error"] == "refused"
    media.register_slots(world.data, body["recording"], [{"key": "b1", "description": "a still"}])
    sid = media.slot_id(body["recording"], "b1")
    still = png(30, 20)
    status, asset = upload(running.port, world.pid, [still], len(still), **{"X-Recording-Id": body["recording"], "X-Slot-Id": sid})
    assert status == 200 and asset["kind"] == "asset" and asset["facts"] == {"width": 30, "height": 20}
    assert os.path.exists(os.path.join(world.data, "media", body["recording"], "assets", media.load(world.data, body["recording"])["slots"][sid]["asset"]["file"]))


@needs_ffmpeg
def test_route_a_connection_dropped_mid_body_leaves_no_file(world, running, mov):
    connection = socket.create_connection(("127.0.0.1", running.port), timeout=10)
    connection.sendall((f"POST /api/v1/projects/{world.pid}/media HTTP/1.1\r\nHost: 127.0.0.1:{running.port}\r\n"
                        f"Origin: http://127.0.0.1:{running.port}\r\nAuthorization: Bearer {TOKEN}\r\n"
                        f"Content-Type: application/octet-stream\r\nContent-Length: {len(mov) + 5000}\r\n\r\n").encode("ascii") + mov[:3000])
    time.sleep(0.2)
    connection.close()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and left_over(world.data):
        time.sleep(0.05)
    assert left_over(world.data) == []
    assert media.records(world.data) == []


def test_route_an_oversize_declaration_is_answered_413_over_the_socket_and_nothing_is_stored(world, running):
    status, body = upload(running.port, world.pid, [], media.MEDIA_MAX_BYTES + 1)
    assert (status, body["error"]) == (413, "too_large") and left_over(world.data) == []


def test_route_the_handler_streams_and_never_holds_the_body(world):
    import inspect
    source = inspect.getsource(service.make_handler)
    assert "handle_stream(service, method, path, headers, SocketBody(self.rfile, self.connection), lan)" in source        # the socket, not bytes
    assert service.CSP == "default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'"   # the page's policy is unchanged here (P7 adds media-src)


def test_route_the_operation_is_for_the_terminal_and_the_page_never_the_model_clients_or_messaging():
    operations = st.load("operations")
    for name in ("media-in", "media-list", "media-purge"):
        row = operations.by_name(name)
        assert not {"mcp", "messaging", "chat"} & set(row["channels"]) and "terminal" in row["channels"], name
    assert "page" in operations.by_name("media-in")["channels"] and "page" in operations.by_name("media-list")["channels"]
    assert "page" not in operations.by_name("media-purge")["channels"]


# --- the review round: the drain, the deadline, a malformed length, a full disk ----------------------------------------------------------


def raw_post(port, pid, *, auth=True, origin=True, length="999999999999", token=TOKEN, extra=""):
    connection = socket.create_connection(("127.0.0.1", port), timeout=10)
    head = (f"POST /api/v1/projects/{pid}/media HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
            + (f"Origin: http://127.0.0.1:{port}\r\n" if origin else "")
            + (f"Authorization: Bearer {token}\r\n" if auth else "")
            + f"Content-Type: application/octet-stream\r\nContent-Length: {length}\r\n{extra}\r\n")
    connection.sendall(head.encode("ascii"))
    return connection


def until_closed(connection, limit):
    """(seconds until the server stopped reading, the bytes it sent): the client drips one byte every 0.1 s whatever it receives, and the
    server has stopped reading when a send fails (its socket is closed, so the unread bytes are answered with a reset). The server's
    FIN after its answer says nothing: the drain half-closes the socket and goes on reading."""
    started = time.monotonic()
    seen = b""
    while time.monotonic() - started < limit:
        try:
            connection.sendall(b"x")
            connection.settimeout(0.1)
            piece = connection.recv(65536)
            seen += piece
        except socket.timeout:
            continue
        except OSError:
            return time.monotonic() - started, seen
        if not piece:
            time.sleep(0.1)
    return None, seen


def test_route_a_request_that_failed_the_rules_is_closed_at_once_with_no_drain(world, running):
    for kwargs in ({"auth": False}, {"origin": False}, {"token": "wrong" * 10}):
        connection = raw_post(running.port, world.pid, **kwargs)
        closed, seen = until_closed(connection, 5)
        connection.close()
        assert closed is not None and closed < 1.5, (kwargs, closed)
        assert seen.startswith(b"HTTP/1.") and b" 40" in seen[:14], (kwargs, seen[:30])


def test_route_a_refusal_after_the_rules_drains_for_a_bounded_time_however_slowly_the_client_drips(world, running, monkeypatch):
    monkeypatch.setattr(service, "DRAIN_SECONDS", 1.0)
    connection = raw_post(running.port, world.pid, length=str(media.MEDIA_MAX_BYTES + 1))       # past the rules, then 413 before the body
    started = time.monotonic()
    closed, seen = until_closed(connection, 8)
    connection.close()
    assert b" 413 " in seen[:16] and closed is not None and 0.7 < closed < 3.5, (closed, seen[:30])      # it drained, for DRAIN_SECONDS and no longer


def test_route_a_request_on_the_lan_socket_is_not_drained(world, running):
    world.svc.lan_ip = LAN
    connection = raw_post(running.port, world.pid)                                              # the loopback socket of a service with --lan: still a route
    closed, _ = until_closed(connection, 5)
    connection.close()
    assert closed is not None


def test_route_a_content_length_with_thousands_of_digits_is_400_and_never_an_internal_error(world):
    for length in ("9" * 5000, "9" * (service.MAX_LENGTH_DIGITS + 1)):
        assert post(world, Forbidden(), length)[0] == 400
        assert post(world, Forbidden(), length, path=f"/api/v1/projects/{world.pid}/requests", content_type="application/json")[0] == 400
    assert post(world, Forbidden(), "1" + "0" * 20)[0] == 400
    assert post(world, Forbidden(), media.MEDIA_MAX_BYTES + 1)[0] == 413


def test_route_a_slow_sender_is_cut_at_the_uploads_deadline_and_the_lock_is_free_again(world, running, monkeypatch):
    monkeypatch.setattr(media, "UPLOAD_MAX_SECONDS", 1)
    monkeypatch.setattr(media, "ffprobe_path", lambda: "/stub/ffprobe")
    connection = raw_post(running.port, world.pid, length="5000000")
    connection.sendall(b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x00" * 40)
    started = time.monotonic()
    seen = b""
    while time.monotonic() - started < 8:                         # one byte now and then: each read1 returns, the total stays slow
        try:
            connection.sendall(b"x")
            connection.settimeout(0.3)
            piece = connection.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not piece:
            break
        seen += piece
        if b"took more than" in seen:      # the head and the body of the answer can arrive in two pieces
            break
    connection.close()
    assert b" 409 " in seen[:16] and b"took more than" in seen and time.monotonic() - started < 5
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:                            # the handler thread ends and frees the upload lock
        try:
            with media._Lock(os.path.join(world.data, "media", media.UPLOAD_LOCK), blocking=False):
                break
        except BlockingIOError:
            time.sleep(0.05)
    else:
        raise AssertionError("the upload lock was not released")
    assert left_over(world.data) == []


def test_route_a_full_disk_while_writing_is_507_no_space(world, monkeypatch):
    import errno
    monkeypatch.setattr(media, "ffprobe_path", lambda: "/stub/ffprobe")
    monkeypatch.setattr(media, "_write", lambda out, chunk: (_ for _ in ()).throw(OSError(errno.ENOSPC, "No space left on device")))
    body = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00qt  " + b"\x00" * 100
    status, answer = post(world, io.BytesIO(body), len(body))
    assert (status, answer["error"]) == (507, "no_space") and left_over(world.data) == []

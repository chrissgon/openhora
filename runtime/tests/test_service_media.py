"""Tests of the media routes of the local service (package V1b2-2, limit L68): the eight routes of a new video, the upload read as a stream and never held
whole, the download streamed as an attachment, and the refusal of the upload, the still and the download on the `--lan` socket before a byte of the body
is read or a file is opened. The routing is tested against the stand-in operations object of test_service.py; the end to end test uses the real operations
and the fake engine of media_kit.py. Every name is invented and every recording is synthetic.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_service_media.py
"""
from __future__ import annotations

import http.client
import io
import json
import socket
import threading
import types

import pytest

import standin_tree as st
from media_fixtures import Body, Forbidden, body_of, mp4_head
from media_kit import POST, media, ops, ops_core, to_gate, world  # noqa: F401  (the end to end fixture)
from test_service import PORT, STATUS, TOKEN, WAIT, Standin, call, wait_job

service = st.load("service")
operations = st.load("operations")

LAN = "192.168.1.20"
RENDER = b"the rendered video of Aster Lane one"
MEDIA_ROUTES = (
    ("GET", "/projects/{p}/media", "media-list"),
    ("POST", "/projects/{p}/media", "media-in"),
    ("POST", "/projects/{p}/videos", "video-new"),
    ("POST", "/projects/{p}/videos/{id}/run", "video-run"),
    ("GET", "/projects/{p}/videos/{id}/captions", "captions-read"),
    ("POST", "/projects/{p}/videos/{id}/captions", "captions-edit"),
    ("GET", "/projects/{p}/videos/{id}/download", "video-download"),
    ("GET", "/projects/{p}/videos/{id}/still", "video-still"),
)


@pytest.fixture
def stand(tmp_path):
    """The stand-in service of test_service.py (the fixture there is named `world`, which the end to end test of this file takes from media_kit)."""
    fake = Standin(tmp_path / "data")
    fake.answers["status"] = STATUS
    folder = tmp_path / "alpha"
    folder.mkdir()
    projects = [{"id": service.project_id(str(folder)), "name": "alpha", "path": str(folder)}]
    lines = []
    svc = service.Service(fake, projects, TOKEN, PORT, str(tmp_path), log=lines.append)
    return types.SimpleNamespace(svc=svc, fake=fake, projects=projects, lines=lines, tmp=tmp_path)


def url(world, tail):
    return f"/api/v1/projects/{world.projects[0]['id']}{tail}"


def headers_of(length, content_type="video/mp4", lan=False, method="POST"):
    host = f"{LAN}:{PORT}" if lan else f"127.0.0.1:{PORT}"
    out = {"Host": host, "Authorization": f"Bearer {TOKEN}"}
    if method == "POST":
        out.update({"Origin": f"http://{host}", "Content-Type": content_type, "Content-Length": str(length)})
    return out


def upload(world, stream, length, *, content_type="video/mp4", lan=False, path=None, headers=None):
    """The upload through handle_stream, as the socket's handler calls it; (status, headers, parsed body)."""
    sent = headers if headers is not None else headers_of(length, content_type, lan)
    status, out, payload = service.handle_stream(world.svc, "POST", path or url(world, "/media"), sent, stream, length, lan=lan)
    return status, out, json.loads(payload)


def get(world, tail, *, lan=False):
    status, out, payload = service.handle(world.svc, "GET", url(world, tail), headers_of(0, lan=lan, method="GET"), b"", lan=lan)
    return status, out, payload


def use_lan(world):
    world.svc.lan_ip = LAN


def media_calls(world):
    return [c for c in world.fake.calls if c[0] in {row["call"] for row in operations.OPERATIONS if row["name"] in operations.GROUPS["media"]["operations"]}]


# 1. limit L68


def test_limit_68_recorded_media_is_refused_on_the_lan_socket_before_a_byte_is_read(stand):
    use_lan(stand)
    status, _, body = upload(stand, Forbidden(), 64, lan=True)
    assert status == 409 and body["error"] == "refused" and body["message"] == operations.LAN_REFUSED_MEDIA
    assert media_calls(stand) == [], "the operation was not called"
    for tail in ("/videos/7/download", "/videos/7/still"):
        status, _, payload = get(stand, tail, lan=True)
        assert status == 409 and json.loads(payload)["message"] == operations.LAN_REFUSED_MEDIA, tail
    assert media_calls(stand) == [], "no file was opened"
    # the same three on the loopback socket reach the stand-in
    stand.fake.answers["media_in"] = {"media": "0" * 16}
    stand.fake.answers["video_download"] = lambda project, **kw: {"stream": io.BytesIO(b"x"), "name": "video-0123456789ab.mp4", "sha256": "a" * 64, "size": 1}
    stand.fake.answers["video_still"] = {"media_type": "image/png", "data": b"\x89PNG"}
    assert upload(stand, io.BytesIO(b"x" * 64), 64)[0] == 200
    for tail in ("/videos/7/download", "/videos/7/still"):
        status, _, payload = get(stand, tail)
        assert status == 200, tail
        getattr(payload, "close", lambda: None)()
    assert [c[0] for c in media_calls(stand)] == ["media_in", "video_download", "video_still"]
    # the text and the starts may cross the LAN socket (OPEN-5)
    stand.fake.calls.clear()
    for method, tail, body in (("GET", "/media", None), ("GET", "/videos/7/captions", None), ("POST", "/videos", {"media_id": "a", "post": "b"}),
                               ("POST", "/videos/7/run", {}), ("POST", "/videos/7/captions", {"revision": 1, "edits": "[]"})):
        data = json.dumps(body).encode("utf-8") if body is not None else b""
        sent = headers_of(len(data), "application/json", lan=True, method=method)
        status, _, payload = service.handle(stand.svc, method, url(stand, tail), sent, data, lan=True)
        assert status in (200, 202), (tail, status, payload)
        if status == 202:
            wait_job(stand, json.loads(payload)["job"])
    assert [c[0] for c in media_calls(stand)] == ["media_list", "captions_read", "video_new", "video_run", "captions_edit"]


def test_the_lan_refusal_of_media_holds_on_a_real_socket_before_the_body_is_sent(stand, monkeypatch):
    monkeypatch.setattr(service, "_on_lan", lambda connection: True)       # the loopback socket stands for the LAN one: the property is the handler's
    server, thread, svc, stop = start(stand)
    try:
        svc.lan_ip = LAN
        raw = socket.create_connection(("127.0.0.1", svc.port), timeout=5)
        head = (f"POST /api/v1/projects/{stand.projects[0]['id']}/media HTTP/1.1\r\nHost: {LAN}:{svc.port}\r\nOrigin: http://{LAN}:{svc.port}\r\n"
                f"Authorization: Bearer {svc.token}\r\nContent-Type: video/mp4\r\nContent-Length: 1000000\r\n\r\n")
        raw.sendall(head.encode("ascii"))                  # the headers only: a server that tried to read the body would wait for it
        answer = b""
        while True:
            piece = raw.recv(4096)
            if not piece:
                break
            answer += piece
        raw.close()
        assert answer.startswith(b"HTTP/1.0 409") or answer.startswith(b"HTTP/1.1 409"), answer[:80]
        assert operations.LAN_REFUSED_MEDIA.encode("utf-8") in answer
        assert media_calls(stand) == []
    finally:
        stop.set()
        thread.join(WAIT)


# 2. the checks before the body


def test_the_upload_is_checked_before_its_body_is_read(stand):
    forbidden = Forbidden()
    assert upload(stand, forbidden, 64, content_type="application/json")[0] == 415
    status, _, payload = service.handle(stand.svc, "POST", url(stand, "/videos"), headers_of(2, "video/mp4"), b"{}")
    assert status == 415
    assert upload(stand, forbidden, service.MEDIA_UPLOAD_BYTES + 1)[0] == 413
    assert upload(stand, forbidden, 0)[0] == 400
    assert upload(stand, forbidden, 64, path=url(stand, "/media?x=1"))[0] == 400
    assert upload(stand, forbidden, 64, path="/api/v1/projects/000000000000/media")[0] == 404
    stand.fake.answers["config"] = {"path": "x", "sha256": "a" * 64, "accepted": True, "channels": {"page": ["read"]}, "data_dir": stand.fake.data_dir}
    status, _, body = upload(stand, forbidden, 64)
    assert status == 409 and body["error"] == "refused"
    assert media_calls(stand) == []


# 3 and 4. the upload through handle and through a socket


def test_the_upload_through_handle_gives_the_operation_a_stream_and_its_length(stand):
    seen = {}

    def media_in(project, **kwargs):
        seen.update(kwargs)
        return {"read": len(kwargs["stream"].read())}

    stand.fake.answers["media_in"] = media_in
    data = body_of(mp4_head(), 4096)
    status, _, payload = service.handle(stand.svc, "POST", url(stand, "/media"), headers_of(len(data)), data)
    assert status == 200 and json.loads(payload) == {"read": 4096}
    assert set(seen) == {"stream", "length", "channel"} and seen["length"] == 4096 and seen["channel"] == "page"
    assert not isinstance(seen["stream"], (bytes, bytearray))


def start(world):
    """The real server on port 0 with the stand-in; (server thread's Server, thread, the Service, the stop event)."""
    started, ready, stop = {}, threading.Event(), threading.Event()

    def on_ready(svc):
        started["svc"] = svc
        ready.set()

    runner = threading.Thread(target=service.serve, args=([world.projects[0]["path"]],), kwargs={
        "port": 0, "poll_every": 0, "dispatch_every": 0, "ops_module": world.fake, "stop": stop, "ready": on_ready, "out": io.StringIO(),
        "log": world.lines.append, "interface_dir": str(world.tmp)})
    runner.start()
    assert ready.wait(WAIT)
    svc = started["svc"]
    world.svc = svc                                   # the routes of this service are the project's, found by its id
    world.projects[0]["id"] = service.project_id(world.projects[0]["path"])
    return None, runner, svc, stop


def test_the_upload_through_a_real_socket_is_read_in_chunks_and_never_whole(stand):
    total = 3 * 1024 * 1024
    seen = {"reads": 0, "bytes": 0, "biggest": 0, "kinds": set()}

    def media_in(project, **kwargs):
        stream = kwargs["stream"]
        seen["kinds"].add(type(stream).__name__)
        left = kwargs["length"]
        while left:
            piece = stream.read(min(1 << 20, left))
            assert piece
            seen["reads"] += 1
            seen["bytes"] += len(piece)
            seen["biggest"] = max(seen["biggest"], len(piece))
            left -= len(piece)
        return {"received": seen["bytes"]}

    stand.fake.answers["media_in"] = media_in
    _, thread, svc, stop = start(stand)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.putrequest("POST", url(stand, "/media"))
        for key, value in (("Authorization", f"Bearer {svc.token}"), ("Origin", f"http://127.0.0.1:{svc.port}"), ("Content-Type", "video/mp4"),
                           ("Content-Length", str(total))):
            connection.putheader(key, value)
        connection.endheaders()
        sent = 0
        data = body_of(mp4_head(), total)
        while sent < total:
            connection.send(data[sent:sent + 65536])
            sent += 65536
        answer = connection.getresponse()
        assert answer.status == 200 and json.loads(answer.read()) == {"received": total}
        connection.close()
        assert seen["bytes"] == total and seen["reads"] >= 3 and seen["biggest"] <= 1 << 20
        assert "bytes" not in seen["kinds"]
    finally:
        stop.set()
        thread.join(WAIT)


# 5 to 7. the download and the still


def test_the_download_is_an_attachment_streamed_from_the_open_file(stand):
    stand.fake.answers["video_download"] = lambda project, **kw: {"stream": io.BytesIO(b"the video"), "name": "video-0123456789ab.mp4", "sha256": "a" * 64, "size": 9}
    status, headers, body = get(stand, "/videos/7/download")
    assert status == 200 and headers["Content-Type"] == "video/mp4" and headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Content-Disposition"] == 'attachment; filename="video-0123456789ab.mp4"' and isinstance(body, service.Streamed)
    assert b"".join(body) == b"the video" and body.size == 9
    body.close()
    assert stand.fake.named("video_download") == [("video_download", stand.projects[0]["path"], {"task_id": 7, "channel": "page"})]
    closed = []

    class Tracked(io.BytesIO):
        def close(self):
            closed.append(True)
            super().close()

    stand.fake.answers["video_download"] = lambda project, **kw: {"stream": Tracked(b"x"), "name": "../escape.mp4", "sha256": "a" * 64, "size": 1}
    status, _, payload = get(stand, "/videos/7/download")
    assert status == 500 and json.loads(payload)["error"] == "internal" and closed == [True]


def test_the_download_through_a_real_socket_arrives_whole_and_the_file_is_closed_after_the_send(stand):
    closed = threading.Event()

    class Tracked(io.BytesIO):
        def close(self):
            closed.set()
            super().close()

    data = b"v" * (2 * 1024 * 1024 + 5)
    stand.fake.answers["video_download"] = lambda project, **kw: {"stream": Tracked(data), "name": "video-0123456789ab.mp4", "sha256": "a" * 64, "size": len(data)}
    _, thread, svc, stop = start(stand)
    try:
        connection = http.client.HTTPConnection("127.0.0.1", svc.port, timeout=WAIT)
        connection.request("GET", url(stand, "/videos/7/download"), headers={"Authorization": f"Bearer {svc.token}"})
        answer = connection.getresponse()
        assert answer.status == 200 and answer.getheader("Content-Length") == str(len(data))
        assert answer.getheader("Content-Disposition") == 'attachment; filename="video-0123456789ab.mp4"'
        assert answer.read() == data
        assert closed.wait(WAIT)
        connection.close()
    finally:
        stop.set()
        thread.join(WAIT)


def test_the_still_is_a_png_shown_inline(stand):
    png = b"\x89PNG\r\n\x1a\nstill"
    stand.fake.answers["video_still"] = {"media_type": "image/png", "data": png}
    status, headers, body = get(stand, "/videos/7/still")
    assert (status, body, headers["Content-Type"], headers["Content-Disposition"]) == (200, png, "image/png", "inline")
    assert stand.fake.named("video_still")[0][2] == {"task_id": 7, "channel": "page"}


# 8. the routes


def test_the_eight_routes_are_in_the_table_with_their_flags():
    found = {(r["method"], r["pattern"]): r for r in service.ROUTES}
    for method, pattern, op in MEDIA_ROUTES:
        route = found[(method, pattern)]
        assert route["op"] == op, pattern
        assert route["stream"] is (op == "media-in") and route["download"] is (op == "video-download") and route["raw"] is (op == "video-still")
    assert found[("POST", "/projects/{p}/media")]["limit"] == service.MEDIA_UPLOAD_BYTES
    assert found[("POST", "/projects/{p}/videos")]["limit"] == service.JSON_LIMIT
    assert all("path" not in (r["take"] or ()) and "out" not in (r["take"] or ()) for r in found.values() if r["op"] in {o for _, _, o in MEDIA_ROUTES})


def test_a_new_video_and_its_run_are_jobs_and_the_edit_binds_its_arguments(stand):
    sent = lambda body: json.dumps(body).encode("utf-8")  # noqa: E731
    data = sent({"media_id": "0123456789abcdef", "post": POST})
    status, _, payload = service.handle(stand.svc, "POST", url(stand, "/videos"), headers_of(len(data), "application/json"), data)
    assert status == 202 and json.loads(payload)["op"] == "video-new"
    wait_job(stand, json.loads(payload)["job"])
    status, _, payload = service.handle(stand.svc, "POST", url(stand, "/videos/7/run"), headers_of(2, "application/json"), b"{}")
    assert status == 202 and json.loads(payload)["op"] == "video-run"
    wait_job(stand, json.loads(payload)["job"])
    data = sent({"revision": 1, "edits": "[]"})
    status, _, payload = service.handle(stand.svc, "POST", url(stand, "/videos/7/captions"), headers_of(len(data), "application/json"), data)
    assert status == 200
    assert stand.fake.named("captions_edit")[0][2] == {"task_id": 7, "revision": 1, "edits": "[]", "channel": "page"}
    data = sent({"revision": 1, "edits_file": "[]"})
    status, _, payload = service.handle(stand.svc, "POST", url(stand, "/videos/7/captions"), headers_of(len(data), "application/json"), data)
    assert status == 400 and json.loads(payload)["error"] == "usage"


# 9. the constants


def test_the_constants_of_the_media_routes():
    assert service.MEDIA_UPLOAD_BYTES == media.MEDIA_MAX_BYTES
    assert operations.LAN_REFUSED_OPS == ("media-in", "video-download", "video-still", "video-watch")
    group = operations.GROUPS["media"]
    assert len(group["operations"]) == 11 and group["kind"] is None
    assert {op for _, _, op in MEDIA_ROUTES} | {"video-catalogue", "media-remove", "video-watch"} == set(group["operations"])
    for channel, listed in operations.GRANTS.items():
        assert "media" not in listed, channel
    assert operations.PAGE_ONLY_GROUPS == ("approve-effects",) and "media" not in operations.DEFAULT_POLICY.get("messaging", ())
    assert "local network" in operations.GROUP_TEXT["media"]
    for name in operations.GROUPS["media"]["operations"]:
        assert operations.by_name(name)["channels"] == (("page",) if name == "video-watch" else ("terminal", "page"))
        assert bool(operations.by_name(name).get("job")) is (name in ("video-new", "video-run"))


# 10. end to end, with the real operations


def test_a_new_video_from_the_page_to_the_download_with_the_real_operations(world):
    projects = [{"id": service.project_id(world["path"]), "name": "alpha", "path": world["path"]}]
    svc = service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None)
    stage = types.SimpleNamespace(svc=svc, projects=projects)
    data = body_of(mp4_head(), 64)
    status, _, payload = service.handle(svc, "POST", url(stage, "/media"), headers_of(len(data)), data)
    got = json.loads(payload)
    assert status == 200 and got["size"] == 64 and got["type"] == "mp4"
    status, _, payload = get_with(svc, url(stage, "/media"))
    assert status == 200 and got["media"] in [r["media"] for r in json.loads(payload)["recordings"]]
    sent = json.dumps({"media_id": got["media"], "post": POST}).encode("utf-8")
    status, _, payload = service.handle(svc, "POST", url(stage, "/videos"), headers_of(len(sent), "application/json"), sent)
    assert status == 202
    job = wait_job(stage, json.loads(payload)["job"])
    assert job["state"] == "done" and job["result"]["stopped"] == "review", job
    task = job["result"]["task"]
    status, _, payload = get_with(svc, url(stage, f"/videos/{task}/captions"))
    assert status == 200 and json.loads(payload)["task"] == task
    ctx = ops_core.context(world["path"])
    [item] = ctx["store"].pending_list(ctx["conn"], "open", task)
    ops.answer(world["path"], item["id"], "continue")
    status, _, payload = service.handle(svc, "POST", url(stage, f"/videos/{task}/run"), headers_of(2, "application/json"), b"{}")
    assert status == 202
    job = wait_job(stage, json.loads(payload)["job"])
    assert job["state"] == "done" and job["result"]["stopped"] == "deliver", job
    [gate] = ctx["store"].pending_list(ctx["conn"], "open", task)
    ops.approve(world["path"], gate["id"], sha256=gate["payload_sha256"], channel="terminal")
    status, headers, body = get_with(svc, url(stage, f"/videos/{task}/download"))
    assert status == 200 and isinstance(body, service.Streamed)
    try:
        assert b"".join(body) == RENDER and headers["Content-Disposition"].startswith('attachment; filename="video-')
    finally:
        body.close()
    svc.lan_ip = LAN
    status, _, payload = service.handle(svc, "GET", url(stage, f"/videos/{task}/download"), headers_of(0, lan=True, method="GET"), b"", lan=True)
    assert status == 409 and json.loads(payload)["message"] == operations.LAN_REFUSED_MEDIA


def get_with(svc, path):
    return service.handle(svc, "GET", path, headers_of(0, method="GET"), b"")


def test_a_body_that_ends_early_or_is_dropped_is_a_400_and_keeps_no_recording(world):
    projects = [{"id": service.project_id(world["path"]), "name": "alpha", "path": world["path"]}]
    svc = service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None)
    stage = types.SimpleNamespace(svc=svc, projects=projects)
    before = {r["id"] for r in media.records(world["data"])}
    for stream in (Body(64, mp4_head()), Body(4096, mp4_head(), fail_after=0)):      # ends before its length; a dropped connection
        status, _, body = upload(stage, stream, 4096)
        assert status == 400 and body["error"] == "usage", body
    big = Body(3 * 1024 * 1024, mp4_head())                                           # larger than the 1 MiB in-memory cap of a JSON body
    status, _, body = upload(stage, big, big.total)
    assert status == 200 and body["size"] == big.total and big.reads >= 3
    assert {r["id"] for r in media.records(world["data"])} == before | {body["media"]}

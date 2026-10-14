"""The routes of the rendered video (runtime/service.py, runtime/video.py, runtime/ops_video.py): the video, its cover and the download
streamed from an open descriptor in byte ranges, the file chosen by the recording id and the hash and never by a path, the hash of
the bytes checked before they are read, the loopback socket only, the token and origin rules, the one-read-at-a-time gate, and a
range request over a real socket. The operations layer is the real one (the stand-in tree of standin_tree.py) over a recording of the
media store written by video_fixtures.py: no ffmpeg, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_video_route.py
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import socket
import threading
import time

import pytest

import standin_tree as st
from test_channel_policy import set_channels
from test_service import PORT, TOKEN
from video_fixtures import CAPTION, LAN, caption_sha, headers, mp4_bytes, world, write_post, write_render  # noqa: F401

service = st.load("service")
media = st.load("media")
video = st.load("video")
operations = st.load("operations")


def get(world, path, *, lan=False, **kw):
    """(status, headers, body bytes) of one GET through the service's own request function. A streamed body is read whole and closed,
    the way the socket's handler sends it."""
    sent = headers(**{k: v for k, v in kw.items() if k in ("host", "origin", "token")})
    sent.update({k.replace("_", "-"): v for k, v in kw.items() if k not in ("host", "origin", "token") and v is not None})
    status, head, body = service.handle(world.svc, "GET", path, sent, b"", lan=lan)
    if isinstance(body, service.FileBody):
        try:
            return status, head, body.read_all()
        finally:
            body.close()
    return status, head, body


def render_path(world, sha, rid=None):
    return f"/api/v1/projects/{world.pid}/video/{rid or world.rid}/render/{sha}"


def error_of(body):
    return json.loads(body)["error"]


@pytest.fixture
def one(world):
    return write_render(world.data, world.rid, "one")


# --- the whole file and the ranges -----------------------------------------------------------------------------------------------------


def test_the_render_is_streamed_whole_with_its_hardening_headers(world, one):
    status, head, body = get(world, render_path(world, one["sha"]))
    assert status == 200 and body == one["bytes"] and hashlib.sha256(body).hexdigest() == one["sha"]
    assert head["Content-Type"] == "video/mp4" and head["Accept-Ranges"] == "bytes" and head["ETag"] == f'"{one["sha"]}"'
    assert head["Cache-Control"] == "no-store" and head["X-Content-Type-Options"] == "nosniff"
    assert head["Content-Disposition"] == "inline" and head["Content-Security-Policy"] == service.CSP and head["Referrer-Policy"] == "no-referrer"
    assert "Content-Range" not in head


def test_a_single_byte_range_is_answered_206_with_the_bytes_between_and_content_range(world, one):
    data, size = one["bytes"], len(one["bytes"])
    for spec, first, last in (("bytes=0-99", 0, 99), ("bytes=1000-", 1000, size - 1), ("bytes=-50", size - 50, size - 1),
                              ("bytes=5-5", 5, 5), (f"bytes=10-{size + 5000}", 10, size - 1), (f"bytes={size - 1}-{size - 1}", size - 1, size - 1),
                              ("bytes=-999999999", 0, size - 1), ("  bytes=7-9  ", 7, 9)):
        status, head, body = get(world, render_path(world, one["sha"]), range=spec)
        assert status == 206, spec
        assert head["Content-Range"] == f"bytes {first}-{last}/{size}" and body == data[first:last + 1], spec
        assert head["Accept-Ranges"] == "bytes" and head["Content-Type"] == "video/mp4"


def test_a_range_that_cannot_be_answered_is_416_with_the_size_and_a_header_with_another_unit_is_ignored(world, one):
    size = len(one["bytes"])
    for spec in (f"bytes={size}-", f"bytes={size + 10}-{size + 20}", "bytes=9-2", "bytes=-0", "bytes=abc", "bytes=", "bytes=-", "bytes=1-2,5-9",
                 "bytes=0-1,", "bytes=1 -2", "bytes=١-2", "bytes=99999999999999999-"):
        status, head, body = get(world, render_path(world, one["sha"]), range=spec)
        assert status == 416 and head["Content-Range"] == f"bytes */{size}" and error_of(body) == "range", spec
    status, head, body = get(world, render_path(world, one["sha"]), range="items=0-5")      # a unit this server does not know: the whole file
    assert status == 200 and body == one["bytes"] and "Content-Range" not in head


def test_a_repeated_range_header_is_a_malformed_request(world, one):
    sent = headers()
    pairs = list(sent.items()) + [("Range", "bytes=0-1"), ("Range", "bytes=2-3")]
    assert service.headers_of(pairs) is None


# --- the file is chosen by id and hash, never by a path ------------------------------------------------------------------------------------


def test_no_path_in_the_request_can_reach_a_file_outside_the_recordings_folder(world, one):
    secret = world.tmp / "secret.mp4"
    secret.write_bytes(mp4_bytes("secret"))
    base = f"/api/v1/projects/{world.pid}/video"
    for path in (f"{base}/..%2f..%2fsecret/render/{one['sha']}", f"{base}/{world.rid}/render/..%2f{one['sha']}", f"{base}/{world.rid}/render/{one['sha']}/../x",
                 f"{base}/{world.rid}/render/render-{one['sha'][:12]}.mp4", f"{base}/{world.rid}/render/{one['sha'][:12]}",
                 f"{base}/{world.rid}/render/{one['sha'].upper()}", f"{base}/{world.rid}/render/{one['sha']}?path=/etc/passwd",
                 f"{base}/{world.rid}/raw.mp4", f"{base}/{world.rid}/render/raw", f"{base}/ABCDEF0123456789/render/{one['sha']}",
                 f"{base}/{world.rid[:15]}/render/{one['sha']}"):
        status = get(world, path)[0]
        assert status in (400, 404), path
    status, _, body = get(world, render_path(world, one["sha"], rid="f" * 16))      # a well-formed id of a recording that does not exist
    assert status == 404 and error_of(body) == "not_found"


def test_the_raw_recording_an_asset_and_a_cover_are_not_served_as_a_render(world, one):
    with open(os.path.join(world.folder, "raw.mp4"), "wb") as f:
        f.write(mp4_bytes("raw recording"))
    raw_sha = hashlib.sha256(mp4_bytes("raw recording")).hexdigest()
    assert get(world, render_path(world, raw_sha))[0] == 404                         # raw.mp4 is no name this code builds
    # a file with a render's name whose bytes are not an MP4 is refused as a type
    bad = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400
    sha = hashlib.sha256(bad).hexdigest()
    with open(os.path.join(world.folder, f"render-{sha[:12]}.mp4"), "wb") as f:
        f.write(bad)
    status, _, body = get(world, render_path(world, sha))
    assert status == 415 and error_of(body) == "media_type"


def test_a_link_in_place_of_the_render_or_of_the_recordings_folder_is_not_followed(world, one):
    outside = world.tmp / "outside.mp4"
    payload = mp4_bytes("outside")
    outside.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    os.symlink(outside, os.path.join(world.folder, f"render-{sha[:12]}.mp4"))
    assert get(world, render_path(world, sha))[0] == 404
    # the whole recording folder replaced by a link to another folder that holds the file
    other = world.tmp / "other-folder"
    other.mkdir(mode=0o700)
    (other / f"render-{one['sha'][:12]}.mp4").write_bytes(one["bytes"])
    moved = world.folder + ".moved"
    os.rename(world.folder, moved)
    os.symlink(other, world.folder)
    assert get(world, render_path(world, one["sha"]))[0] == 404
    os.unlink(world.folder)
    os.rename(moved, world.folder)
    assert get(world, render_path(world, one["sha"]))[0] == 200


def test_a_hard_link_a_directory_and_an_empty_file_are_refused(world, one):
    payload = mp4_bytes("linked")
    sha = hashlib.sha256(payload).hexdigest()
    elsewhere = world.tmp / "elsewhere.mp4"
    elsewhere.write_bytes(payload)
    os.link(elsewhere, os.path.join(world.folder, f"render-{sha[:12]}.mp4"))
    assert get(world, render_path(world, sha))[0] == 409                                   # two names for one file: not a render this code wrote
    empty = hashlib.sha256(b"").hexdigest()
    open(os.path.join(world.folder, f"render-{empty[:12]}.mp4"), "wb").close()
    assert get(world, render_path(world, empty))[0] == 409
    other = "ab" * 32
    os.mkdir(os.path.join(world.folder, f"render-{other[:12]}.mp4"))
    assert get(world, render_path(world, other))[0] in (404, 409)


def test_bytes_that_do_not_hash_to_the_name_are_never_served_even_when_the_file_is_swapped_after_a_good_read(world, one):
    # a file whose bytes differ from the hash in the path (the name is the first twelve characters, so a prefix match is not enough)
    forged = mp4_bytes("forged")
    fake_sha = one["sha"][:12] + "0" * 52
    with open(os.path.join(world.folder, f"render-{fake_sha[:12]}.mp4.tmp"), "wb") as f:
        f.write(forged)
    os.chmod(world.folder, 0o700)
    os.unlink(one["path"])
    with open(os.path.join(world.folder, f"render-{one['sha'][:12]}.mp4"), "wb") as f:
        f.write(forged)
    status, _, body = get(world, render_path(world, one["sha"]))
    assert status == 409 and error_of(body) == "refused" and b"sha256" in body
    status, _, body = get(world, render_path(world, fake_sha))
    assert status == 409                                                                   # the file named by the 12 characters is not the file of that 64


def test_the_digest_kept_for_a_file_is_dropped_when_the_file_changes(world, one):
    assert get(world, render_path(world, one["sha"]))[0] == 200                           # hashed and remembered under the file's identity
    assert get(world, render_path(world, one["sha"]), range="bytes=0-9")[0] == 206         # served from the remembered digest
    os.chmod(one["path"], 0o600)
    with open(one["path"], "r+b") as f:
        f.seek(100)
        f.write(b"tampered")
    status, _, body = get(world, render_path(world, one["sha"]), range="bytes=0-9")
    assert status == 409 and error_of(body) == "refused"                                  # the times of the file moved: hashed again, differs


def test_an_oversize_file_is_refused_413(world, one, monkeypatch):
    monkeypatch.setattr(video, "VIDEO_MAX_BYTES", len(one["bytes"]) - 1)
    status, _, body = get(world, render_path(world, one["sha"]))
    assert status == 413 and error_of(body) == "too_large"


def test_a_query_is_refused_on_a_byte_route(world, one):
    assert get(world, render_path(world, one["sha"]) + "?path=/etc/hosts")[0] == 400


# --- the cover ---------------------------------------------------------------------------------------------------------------------------


def test_the_cover_is_a_png_chosen_by_the_renders_hash_and_checked_against_the_renderers_report(world, one):
    path = f"/api/v1/projects/{world.pid}/video/{world.rid}/cover/{one['sha']}"
    status, head, body = get(world, path)
    assert status == 200 and body == one["cover"] and head["Content-Type"] == "image/png" and head["Accept-Ranges"] == "bytes"
    assert get(world, path, range="bytes=0-7")[2] == b"\x89PNG\r\n\x1a\n"
    with open(os.path.join(world.folder, f"cover-{one['sha'][:12]}.png"), "ab") as f:
        f.write(b"x")                                                                       # no longer the PNG the renderer reported
    assert get(world, path)[0] == 409
    os.unlink(os.path.join(world.folder, f"cover-{one['sha'][:12]}.png"))
    assert get(world, path)[0] == 404


def test_the_cover_is_not_held_by_the_one_video_gate(world, one):
    gate_held = world.svc.video_gate.acquire(blocking=False)
    try:
        assert gate_held
        assert get(world, f"/api/v1/projects/{world.pid}/video/{world.rid}/cover/{one['sha']}")[0] == 200
    finally:
        world.svc.video_gate.release()


# --- the token, the origin, the host and the loopback socket ---------------------------------------------------------------------------------------


def test_the_byte_routes_need_the_token_the_origin_and_the_host_of_the_service(world, one):
    path = render_path(world, one["sha"])
    assert get(world, path, token=False)[0] == 401
    assert get(world, path, token="wrong" * 13)[0] == 401
    assert get(world, path, origin="http://evil.example")[0] == 403
    assert get(world, path, host="evil.example:80")[0] == 403
    assert get(world, path, host="localhost:8765", origin="default")[0] == 200
    assert get(world, path, origin=None)[0] == 200                                         # a GET without an Origin passes, as everywhere
    for method in ("POST", "PUT", "DELETE", "HEAD", "OPTIONS"):
        status = service.handle(world.svc, method, path, {**headers(), "Content-Type": "application/json", "Content-Length": "0"}, b"")[0]
        assert status in (405, 415), method


def test_a_request_on_the_lan_socket_is_no_route_for_the_video_and_a_name_that_is_not_a_loopbacks_is_refused(world, one):
    world.svc.lan_ip = LAN
    path = render_path(world, one["sha"])
    assert get(world, path, lan=False)[0] == 200                                           # the loopback socket of a service with --lan: still a route
    status, _, body = get(world, path, lan=True, host=f"{LAN}:{PORT}")
    assert status == 404 and error_of(body) == "not_found"
    assert get(world, f"/api/v1/projects/{world.pid}/video/{world.rid}/cover/{one['sha']}", lan=True, host=f"{LAN}:{PORT}")[0] == 404
    assert get(world, f"/api/v1/projects/{world.pid}/video/{world.rid}/download/instagram", lan=True, host=f"{LAN}:{PORT}")[0] == 404
    assert get(world, path, lan=True)[0] == 403                                            # the loopback host on the LAN socket: refused by Host
    # the card is data, not video: it is readable with the token on the LAN socket, like the other reads
    assert get(world, f"/api/v1/projects/{world.pid}/video/{world.rid}", lan=True, host=f"{LAN}:{PORT}")[0] == 200


def test_the_policy_group_read_keeps_the_byte_routes_and_a_project_without_it_loses_them_with_the_other_reads(world, one):
    # the byte routes are reads: the page's policy must list `read` anyway (operations.MUST_READ), so they are never switched off alone
    for name in ("video-card", "video-raw", "video-cover", "video-download"):
        assert name in operations.GROUPS["read"]["operations"] and operations.by_name(name)["channels"] in (("terminal", "page"), ("page",))
    for name in ("video-raw", "video-cover", "video-download"):
        assert operations.by_name(name)["channels"] == ("page",), "no terminal, mcp, chat or messaging channel for the bytes"
    for name in ("video-approve", "video-send-back"):
        assert set(operations.by_name(name)["channels"]) == {"terminal", "page"}


# --- one read of the video at a time -----------------------------------------------------------------------------------------------------------


def test_a_second_read_of_the_video_is_refused_while_the_first_is_open_and_allowed_when_it_closed(world, one):
    sent = headers()
    status, head, body = service.handle(world.svc, "GET", render_path(world, one["sha"]), sent, b"")
    assert status == 200 and isinstance(body, service.FileBody)
    second = service.handle(world.svc, "GET", render_path(world, one["sha"]), sent, b"")
    assert second[0] == 409 and error_of(second[2]) == "refused"
    body.close()
    body.close()                                                                            # closing twice gives the gate back once
    third = service.handle(world.svc, "GET", render_path(world, one["sha"]), sent, b"")
    assert third[0] == 200
    third[2].close()
    assert world.svc.video_gate.acquire(blocking=False)
    world.svc.video_gate.release()


def test_a_refusal_a_416_and_an_error_give_the_gate_and_the_file_back(world, one):
    sent = headers()
    for spec in ("bytes=999999999-", "bytes=oops"):
        status = service.handle(world.svc, "GET", render_path(world, one["sha"]), {**sent, "Range": spec}, b"")[0]
        assert status == 416
        assert world.svc.video_gate.acquire(blocking=False), spec
        world.svc.video_gate.release()
    assert service.handle(world.svc, "GET", render_path(world, "ab" * 32), sent, b"")[0] == 404
    assert world.svc.video_gate.acquire(blocking=False)
    world.svc.video_gate.release()


# --- the download -----------------------------------------------------------------------------------------------------------------------------


def download(world, platform="instagram", **kw):
    return get(world, f"/api/v1/projects/{world.pid}/video/{world.rid}/download/{platform}", **kw)


def approve(world, sha, caption=CAPTION):
    return world.svc.ops.video_approve(world.project, world.rid, sha, caption_sha(caption), "instagram", channel="page")


def test_the_download_serves_the_approved_file_as_an_attachment_with_a_plain_name(world, one):
    status, _, body = download(world)
    assert status == 409 and error_of(body) == "refused" and b"approve this video" in body                 # nothing is approved yet
    approve(world, one["sha"])
    status, head, body = download(world)
    assert status == 200 and body == one["bytes"] and hashlib.sha256(body).hexdigest() == one["sha"]
    disposition = head["Content-Disposition"]
    assert disposition == f'attachment; filename="short-video-instagram-{one["sha"][:12]}.mp4"'
    assert re.fullmatch(r'attachment; filename="short-video-[a-z0-9-]+-[0-9a-f]{12}\.mp4"', disposition)
    assert head["Content-Type"] == "video/mp4" and head["Accept-Ranges"] == "bytes" and head["ETag"] == f'"{one["sha"]}"'
    status, head, part = download(world, range="bytes=0-9")
    assert status == 206 and part == one["bytes"][:10] and head["Content-Disposition"].startswith("attachment")
    assert download(world, platform="tiktok")[0] == 404                                                      # no post of the recording for that platform


def test_the_download_is_refused_when_the_approval_no_longer_holds(world, one):
    approve(world, one["sha"])
    assert download(world)[0] == 200
    write_post(world.project, CAPTION + " edited")                                                           # a caption edit invalidates it
    status, _, body = download(world)
    assert status == 409 and b"caption changed" in body
    write_post(world.project, CAPTION)
    assert download(world)[0] == 200                                                                          # the same caption again: the approval holds again
    second = write_render(world.data, world.rid, "two")                                                       # a re-render invalidates it
    status, _, body = download(world)
    assert status == 409 and b"render changed" in body
    assert get(world, render_path(world, one["sha"]))[0] == 200                                                # the old render is still a file the page can play
    assert second["sha"] != one["sha"]


def test_a_file_changed_after_the_approval_is_not_delivered_because_its_identity_moved(world, one):
    approve(world, one["sha"])
    os.chmod(one["path"], 0o600)
    with open(one["path"], "r+b") as f:
        f.seek(50)
        f.write(b"swapped after the approval")
    status, _, body = download(world)
    assert status == 409 and error_of(body) == "refused"


# --- over a real socket -----------------------------------------------------------------------------------------------------------------------


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


def fetch(port, path, **extra):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    head = {"Authorization": f"Bearer {TOKEN}", **extra}
    connection.request("GET", path, headers=head)
    response = connection.getresponse()
    body = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), body


def test_over_a_real_socket_a_range_is_answered_206_with_exactly_the_bytes_and_the_gate_is_free_after(world, one, running):
    path = render_path(world, one["sha"])
    status, head, body = fetch(running.port, path, Range="bytes=1000-5999")
    assert status == 206 and body == one["bytes"][1000:6000] and head["Content-Range"] == f"bytes 1000-5999/{len(one['bytes'])}"
    assert head["Content-Length"] == "5000" and head["Accept-Ranges"] == "bytes" and head["Content-Type"] == "video/mp4"
    status, head, body = fetch(running.port, path)
    assert status == 200 and body == one["bytes"] and head["Content-Length"] == str(len(one["bytes"]))
    status, head, body = fetch(running.port, path, Range="bytes=900000000-")
    assert status == 416 and head["Content-Range"] == f"bytes */{len(one['bytes'])}"
    status, _, body = fetch(running.port, path, Range="bytes=-16")
    assert status == 206 and body == one["bytes"][-16:]
    assert world.svc.video_gate.acquire(timeout=2)
    world.svc.video_gate.release()


def test_over_a_real_socket_a_client_that_goes_away_mid_video_gives_the_gate_back(world, running, monkeypatch):
    big = write_render(world.data, world.rid, "big", size=6_000_000)
    monkeypatch.setattr(service, "SERVE_CHUNK", 16 * 1024)
    connection = socket.create_connection(("127.0.0.1", running.port), timeout=10)
    connection.sendall((f"GET {render_path(world, big['sha'])} HTTP/1.1\r\nHost: 127.0.0.1:{running.port}\r\nAuthorization: Bearer {TOKEN}\r\n\r\n").encode())
    seen = b""
    while b"\r\n\r\n" not in seen:
        seen += connection.recv(4096)
    assert seen.startswith(b"HTTP/1.0 200") or seen.startswith(b"HTTP/1.1 200")
    connection.close()                                                                      # gone, with most of the file unsent
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if world.svc.video_gate.acquire(blocking=False):
            world.svc.video_gate.release()
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the gate was not given back after the client went away")
    status, _, body = fetch(running.port, render_path(world, big["sha"]), Range="bytes=0-3")
    assert status == 206 and body == big["bytes"][:4]


def test_over_a_real_socket_without_the_token_nothing_is_streamed(world, one, running):
    connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=10)
    connection.request("GET", render_path(world, one["sha"]))
    response = connection.getresponse()
    assert response.status == 401 and one["bytes"][:16] not in response.read()


# --- the approval from the page ---------------------------------------------------------------------------------------------------------------


def post(world, path, body, *, lan=False, host=f"127.0.0.1:{PORT}", **kw):
    raw = json.dumps(body).encode()
    sent = headers(host=host, Content_Type="application/json", Content_Length=str(len(raw)), **kw)
    return service.handle(world.svc, "POST", path, sent, raw, lan=lan)


def test_approving_from_the_lan_socket_is_refused_by_code_and_says_to_approve_on_the_mac(world, one):
    world.svc.lan_ip = LAN
    path = f"/api/v1/projects/{world.pid}/video/{world.rid}/approve"
    body = {"video_sha256": one["sha"], "caption_sha256": caption_sha(), "platform": "instagram"}
    status, _, answer = post(world, path, body, lan=True, host=f"{LAN}:{PORT}")
    assert status == 409 and "approve on the Mac" in json.loads(answer)["message"]
    assert media.load(world.data, world.rid).get("approvals") in (None, {})
    status, _, answer = post(world, f"/api/v1/projects/{world.pid}/video/{world.rid}/send-back", {"comment": "shorter"}, lan=True, host=f"{LAN}:{PORT}")
    assert status == 409 and "approve on the Mac" in json.loads(answer)["message"]
    assert media.load(world.data, world.rid).get("sent_back") is None
    status, _, answer = post(world, path, body, lan=False)                                  # the loopback socket of the same service
    assert status == 200 and json.loads(answer)["approval"]["state"] == "approved"


def test_the_approval_routes_take_the_token_the_origin_and_json_and_name_no_other_key(world, one):
    path = f"/api/v1/projects/{world.pid}/video/{world.rid}/approve"
    body = {"video_sha256": one["sha"], "caption_sha256": caption_sha(), "platform": "instagram"}
    assert post(world, path, body, token=False)[0] == 401
    assert post(world, path, body, origin=None)[0] == 403
    assert post(world, path, body, origin="http://evil.example")[0] == 403
    status, _, answer = post(world, path, {**body, "channel": "terminal"})                  # the channel is the service's, a request cannot name one
    assert status == 400
    status, _, answer = post(world, path, {**body, "approved_at": "2020-01-01T00:00:00Z"})
    assert status == 400
    assert post(world, path, {"video_sha256": one["sha"]})[0] == 400
    assert media.load(world.data, world.rid).get("approvals") in (None, {})


def test_a_project_that_turns_the_video_group_off_for_the_page_cannot_approve_but_still_reads(world, one):
    set_channels(world.project, {"page": ["read"]})
    path = f"/api/v1/projects/{world.pid}/video/{world.rid}"
    assert get(world, path)[0] == 200 and get(world, render_path(world, one["sha"]))[0] == 200
    status, _, answer = post(world, path + "/approve", {"video_sha256": one["sha"], "caption_sha256": caption_sha(), "platform": "instagram"})
    assert status == 409 and "not enabled" in json.loads(answer)["message"]
    set_channels(world.project, {"page": ["read", "video"]})
    assert post(world, path + "/approve", {"video_sha256": one["sha"], "caption_sha256": caption_sha(), "platform": "instagram"})[0] == 200


# --- one hashing of a file at a time, the stream's total time, and HEAD ----------------------------------------------------------------------------------


def test_a_cold_cache_hashes_a_file_once_however_many_cards_ask_at_once(world, one, monkeypatch):
    video._VERIFIED.clear()
    count = []
    real = video._digest

    def counting(f):
        count.append(1)
        time.sleep(0.15)                       # long enough for every thread to be waiting for the first
        return real(f)

    monkeypatch.setattr(video, "_digest", counting)
    done = []
    threads = [threading.Thread(target=lambda: done.append(video.open_render(world.data, world.rid, one["sha"]).sha256)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert done == [one["sha"]] * 6 and len(count) == 1, "six readers, one pass over the file"
    video.open_render(world.data, world.rid, one["sha"]).close()
    assert len(count) == 1, "the next card finds the digest"
    video.open_render(world.data, world.rid, one["sha"], fresh=True).close()
    assert len(count) == 2, "an approval always hashes again"
    assert video._HASHING == {}, "no lock of a finished hashing is kept"


def test_a_stream_has_a_total_time_that_grows_with_its_length_and_stops_a_reader_that_is_too_slow(world, one, monkeypatch):
    assert service.STREAM_MAX_SECONDS >= 600 and service.STREAM_BASE_SECONDS > 0
    opened = video.open_render(world.data, world.rid, one["sha"])
    body = service.FileBody(opened, 0, opened.size)
    assert body.seconds == service.STREAM_BASE_SECONDS + opened.size / service.STREAM_MIN_BYTES_PER_SECOND
    opened.close()
    huge = types_namespace(size=10 ** 12)
    assert service.FileBody(huge, 0, huge.size).seconds == service.STREAM_MAX_SECONDS, "never more than the cap"
    monkeypatch.setattr(service, "STREAM_BASE_SECONDS", 0.2)
    monkeypatch.setattr(service, "STREAM_MIN_BYTES_PER_SECOND", 10 ** 12)
    opened = video.open_render(world.data, world.rid, one["sha"])
    body = service.FileBody(opened, 0, opened.size, on_close=lambda: gave.append(1))
    gave = []
    taken = 0
    with pytest.raises(TimeoutError):
        for block in body.chunks(1024):
            taken += len(block)
            time.sleep(0.05)                   # a reader that takes a chunk every 50 ms
    assert 0 < taken < opened.size
    body.close()
    assert gave == [1]


def types_namespace(**kw):
    import types
    return types.SimpleNamespace(file=None, close=lambda: None, **kw)


def test_a_reader_that_trickles_is_cut_at_the_deadline_the_file_is_closed_and_the_gate_is_free(world, monkeypatch):
    import io

    class Trickle(io.BytesIO):
        """The socket of a reader that takes a chunk every 0.15 s."""

        def write(self, block):
            time.sleep(0.15)
            return super().write(block)

    big = write_render(world.data, world.rid, "big", size=2_000_000)
    monkeypatch.setattr(service, "SERVE_CHUNK", 16 * 1024)
    monkeypatch.setattr(service, "STREAM_BASE_SECONDS", 0.5)
    monkeypatch.setattr(service, "STREAM_MIN_BYTES_PER_SECOND", 10 ** 12)
    status, head, body = service.handle(world.svc, "GET", render_path(world, big["sha"]), headers(), b"")
    assert status == 200 and isinstance(body, service.FileBody) and not world.svc.video_gate.acquire(blocking=False), "the read holds the gate"
    handler = service.make_handler(world.svc)
    instance = handler.__new__(handler)
    instance.command, instance.request_version, instance.requestline, instance.wfile = "GET", "HTTP/1.1", "GET /x HTTP/1.1", Trickle()
    instance.client_address, instance.close_connection = ("127.0.0.1", 1), True
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        instance._send(status, head, body)
    assert time.monotonic() - started < 3 and 0 < len(instance.wfile.getvalue()) < 2_000_000
    assert body.closed and world.svc.video_gate.acquire(blocking=False), "the file is closed and the gate is back, whatever the reader does"
    world.svc.video_gate.release()


def test_a_head_request_never_gets_a_streamed_body(world, one):
    import io
    handler = service.make_handler(world.svc)
    instance = handler.__new__(handler)
    instance.command, instance.request_version, instance.requestline, instance.wfile = "HEAD", "HTTP/1.1", "HEAD /x HTTP/1.1", io.BytesIO()
    instance.client_address, instance.close_connection = ("127.0.0.1", 1), True
    opened = video.open_render(world.data, world.rid, one["sha"])
    gave = []
    body = service.FileBody(opened, 0, opened.size, on_close=lambda: gave.append(1))
    instance._send(200, {"Content-Type": "video/mp4"}, body)
    written = instance.wfile.getvalue()
    assert b"Content-Length: %d" % opened.size in written and written.endswith(b"\r\n\r\n"), "the head says the length and nothing follows it"
    assert gave == [1] and body.closed, "the file and the gate are still given back"
    # and the service answers HEAD with 405 before any route: no file is opened for it
    assert service.handle(world.svc, "HEAD", render_path(world, one["sha"]), headers(), b"")[0] == 405


def test_the_gate_is_given_back_before_the_last_block_is_written_so_no_reader_can_hold_the_whole_body_first(world, one, monkeypatch):
    monkeypatch.setattr(service, "SERVE_CHUNK", 64 * 1024)
    status, head, body = service.handle(world.svc, "GET", render_path(world, one["sha"]), headers(), b"")
    assert status == 200 and not world.svc.video_gate.acquire(blocking=False)
    seen = []
    for block in body.chunks(64 * 1024):
        seen.append((len(block), body.closed))
    assert sum(n for n, _ in seen) == len(one["bytes"]) and len(seen) > 2
    assert [closed for _, closed in seen[:-1]] == [False] * (len(seen) - 1) and seen[-1][1] is True, "closed with the last block in hand"
    assert world.svc.video_gate.acquire(blocking=False), "the gate was free when the last block was handed to the socket"
    world.svc.video_gate.release()
    body.close()

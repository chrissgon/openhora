"""The route of the still frame of a recording (runtime/service.py `media-still`, runtime/video.py `open_still`, runtime/ops_video.py
`media_still`): `GET /projects/<id>/media/<recording>/still/<sha256>`, the PNG the pipeline's `still` step made for the face-box picker.
Built like the cover's route (test_video_route.py): the file is chosen by the recording id and the PNG's own hash, never by a path, opened
without following a link, a PNG of at most 8 MiB whose descriptor hashes to the hash asked for, on the loopback socket only, with the
token in the header (never in the URL), the origin and the host checked. The operations layer is the real one over a recording written by
video_fixtures.py; the bytes are small PNGs of a fictional picture: no ffmpeg, no model, no network.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_still_route.py
"""
from __future__ import annotations

import hashlib
import os

import pytest

import standin_tree as st
from media_fixtures import png
from test_service import PORT, TOKEN
from test_video_route import error_of, get
from video_fixtures import LAN, headers, mp4_bytes, world  # noqa: F401

service = st.load("service")
video = st.load("video")
operations = st.load("operations")
ops = st.load("ops")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def write_still(world, height=16, extra=b"") -> dict:
    """A still written the way the renderer writes it: `still-<sha12>.png`, mode 0400, its name the first 12 characters of its sha256."""
    payload = png(9, height) + extra
    sha = hashlib.sha256(payload).hexdigest()
    path = os.path.join(world.folder, f"still-{sha[:12]}.png")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, "wb") as f:
        f.write(payload)
    return {"sha": sha, "bytes": payload, "path": path}


def still_path(world, sha, rid=None):
    return f"/api/v1/projects/{world.pid}/media/{rid or world.rid}/still/{sha}"


@pytest.fixture
def one(world):
    return write_still(world)


# --- the picture ------------------------------------------------------------------------------------------------------------------------------


def test_the_still_is_a_png_streamed_with_the_hardening_headers_and_in_ranges(world, one):
    status, head, body = get(world, still_path(world, one["sha"]))
    assert status == 200 and body == one["bytes"] and body[:8] == PNG_MAGIC and hashlib.sha256(body).hexdigest() == one["sha"]
    assert head["Content-Type"] == "image/png" and head["Accept-Ranges"] == "bytes" and head["ETag"] == f'"{one["sha"]}"'
    assert head["Cache-Control"] == "no-store" and head["X-Content-Type-Options"] == "nosniff" and head["Content-Disposition"] == "inline"
    assert head["Content-Security-Policy"] == service.CSP and head["Referrer-Policy"] == "no-referrer"
    status, head, part = get(world, still_path(world, one["sha"]), range="bytes=0-7")
    assert status == 206 and part == PNG_MAGIC and head["Content-Range"] == f"bytes 0-7/{len(one['bytes'])}"
    assert get(world, still_path(world, one["sha"]), range="bytes=999999-")[0] == 416


def test_the_still_is_not_held_by_the_one_video_gate_and_gives_nothing_back_to_it(world, one):
    assert world.svc.video_gate.acquire(blocking=False)
    try:
        assert get(world, still_path(world, one["sha"]))[0] == 200
    finally:
        world.svc.video_gate.release()
    assert get(world, still_path(world, one["sha"]))[0] == 200
    assert world.svc.video_gate.acquire(blocking=False)                                    # the still read did not take it
    world.svc.video_gate.release()


# --- the file is chosen by id and hash, never by a path -------------------------------------------------------------------------------------------


def test_no_path_in_the_request_can_reach_a_file_outside_the_recordings_folder(world, one):
    secret = world.tmp / "secret.png"
    secret.write_bytes(png(3, 3))
    base = f"/api/v1/projects/{world.pid}/media"
    for path in (f"{base}/..%2f..%2fsecret/still/{one['sha']}", f"{base}/{world.rid}/still/..%2f{one['sha']}", f"{base}/{world.rid}/still/{one['sha']}/../x",
                 f"{base}/{world.rid}/still/still-{one['sha'][:12]}.png", f"{base}/{world.rid}/still/{one['sha'][:12]}",
                 f"{base}/{world.rid}/still/{one['sha'].upper()}", f"{base}/{world.rid}/still/raw", f"{base}/{world.rid}/still/../../secret.png",
                 f"{base}/ABCDEF0123456789/still/{one['sha']}", f"{base}/{world.rid[:15]}/still/{one['sha']}", f"{base}/{world.rid}/still",
                 f"/api/v1/projects/{world.pid}/video/{world.rid}/still/{one['sha']}"):
        assert get(world, path)[0] in (400, 404), path
    status, _, body = get(world, still_path(world, one["sha"], rid="f" * 16))              # a well-formed id of a recording that does not exist
    assert status == 404 and error_of(body) == "not_found"
    assert get(world, still_path(world, "ab" * 32))[0] == 404                              # a well-formed hash of a file that does not exist


def test_a_query_with_a_path_or_a_token_is_refused_and_the_token_is_only_ever_a_header(world, one):
    assert get(world, still_path(world, one["sha"]) + "?path=/etc/hosts")[0] == 400
    assert get(world, still_path(world, one["sha"]) + f"?token={TOKEN}")[0] == 400                      # a valid header and a token in the URL: refused
    assert get(world, still_path(world, one["sha"]) + f"?token={TOKEN}", token=False)[0] in (400, 401)  # the URL never stands in for the header
    assert get(world, still_path(world, one["sha"]), token=False)[0] == 401
    assert get(world, f"/api/v1/projects/{world.pid}/media/{world.rid}/still/{one['sha']}%3Ftoken%3D{TOKEN}", token=False)[0] in (400, 401, 404)


def test_other_files_of_the_recording_are_not_served_as_a_still(world, one):
    folder = world.folder
    for name, payload in (("raw.mp4", mp4_bytes("raw recording")), ("cover-%s.png" % ("1" * 12), png(5, 5)), ("render-%s.mp4" % ("2" * 12), mp4_bytes("render"))):
        with open(os.path.join(folder, name), "wb") as f:
            f.write(payload)
        assert get(world, still_path(world, hashlib.sha256(payload).hexdigest()))[0] == 404, name       # `still-<sha12>.png` is the only name built
    bad = mp4_bytes("not a png")                                                                           # a still's name over bytes that are not a PNG
    sha = hashlib.sha256(bad).hexdigest()
    with open(os.path.join(folder, f"still-{sha[:12]}.png"), "wb") as f:
        f.write(bad)
    status, _, body = get(world, still_path(world, sha))
    assert status == 415 and error_of(body) == "media_type"


def test_a_link_in_place_of_the_still_or_of_the_recordings_folder_is_not_followed(world, one):
    outside = world.tmp / "outside.png"
    payload = png(7, 7)
    outside.write_bytes(payload)
    sha = hashlib.sha256(payload).hexdigest()
    os.symlink(outside, os.path.join(world.folder, f"still-{sha[:12]}.png"))
    assert get(world, still_path(world, sha))[0] == 404                                                  # O_NOFOLLOW
    other = world.tmp / "other-folder"
    other.mkdir(mode=0o700)
    (other / f"still-{one['sha'][:12]}.png").write_bytes(one["bytes"])
    moved = world.folder + ".moved"
    os.rename(world.folder, moved)
    os.symlink(other, world.folder)
    assert get(world, still_path(world, one["sha"]))[0] == 404
    os.unlink(world.folder)
    os.rename(moved, world.folder)
    assert get(world, still_path(world, one["sha"]))[0] == 200


def test_a_hard_link_a_directory_and_an_empty_file_are_refused(world, one):
    payload = png(11, 11)
    sha = hashlib.sha256(payload).hexdigest()
    elsewhere = world.tmp / "elsewhere.png"
    elsewhere.write_bytes(payload)
    os.link(elsewhere, os.path.join(world.folder, f"still-{sha[:12]}.png"))
    assert get(world, still_path(world, sha))[0] == 409                                                  # two names for one file: not one this code wrote
    empty = hashlib.sha256(b"").hexdigest()
    open(os.path.join(world.folder, f"still-{empty[:12]}.png"), "wb").close()
    assert get(world, still_path(world, empty))[0] == 409
    other = "ab" * 32
    os.mkdir(os.path.join(world.folder, f"still-{other[:12]}.png"))
    assert get(world, still_path(world, other))[0] in (404, 409)


def test_bytes_that_do_not_hash_to_the_hash_in_the_path_are_never_served(world, one):
    wrong = one["sha"][:12] + "0" * 52                                                                   # the name matches, the 64 characters do not
    status, _, body = get(world, still_path(world, wrong))
    assert status == 409 and error_of(body) == "refused" and b"sha256" in body
    forged = png(9, 16) + b"changed after the hash was taken"
    os.chmod(one["path"], 0o600)
    with open(one["path"], "wb") as f:
        f.write(forged)
    status, _, body = get(world, still_path(world, one["sha"]))
    assert status == 409 and error_of(body) == "refused"


def test_the_digest_kept_for_a_still_is_dropped_when_the_file_changes(world, one):
    assert get(world, still_path(world, one["sha"]))[0] == 200
    assert get(world, still_path(world, one["sha"]), range="bytes=0-7")[0] == 206
    os.chmod(one["path"], 0o600)
    with open(one["path"], "r+b") as f:
        f.seek(20)
        f.write(b"tampered")
    assert get(world, still_path(world, one["sha"]), range="bytes=0-7")[0] == 409


def test_a_still_over_the_cap_is_refused_413_and_the_cap_is_8_mib(world, one, monkeypatch):
    assert video.STILL_MAX_BYTES == 8 * 1024 * 1024
    monkeypatch.setattr(video, "STILL_MAX_BYTES", len(one["bytes"]) - 1)
    status, _, body = get(world, still_path(world, one["sha"]))
    assert status == 413 and error_of(body) == "too_large"


# --- the token, the origin, the host and the loopback socket ----------------------------------------------------------------------------------------


def test_the_route_needs_the_token_the_origin_and_the_host_of_the_service_and_answers_only_get(world, one):
    path = still_path(world, one["sha"])
    assert get(world, path, token="wrong" * 13)[0] == 401
    assert get(world, path, origin="http://evil.example")[0] == 403
    assert get(world, path, host="evil.example:80")[0] == 403
    assert get(world, path, host="localhost:8765", origin="default")[0] == 200
    assert get(world, path, origin=None)[0] == 200
    for method in ("POST", "PUT", "DELETE", "HEAD", "OPTIONS"):
        status = service.handle(world.svc, method, path, {**headers(), "Content-Type": "application/json", "Content-Length": "0"}, b"")[0]
        assert status in (405, 415), method


def test_a_request_on_the_lan_socket_is_no_route_for_a_still_and_a_loopback_host_on_it_is_refused(world, one):
    world.svc.lan_ip = LAN
    path = still_path(world, one["sha"])
    assert get(world, path, lan=False)[0] == 200                                         # the loopback socket of a service with --lan: still a route
    status, _, body = get(world, path, lan=True, host=f"{LAN}:{PORT}")
    assert status == 404 and error_of(body) == "not_found"                               # a picture of the speaker must not cross the network as plain HTTP
    assert get(world, path, lan=True)[0] == 403                                          # the loopback host on the LAN socket: refused by Host
    assert get(world, path, lan=True, host=f"{LAN}:{PORT}", range="bytes=0-7")[0] == 404


# --- the operation: a row the page may call, in the read group, nothing else --------------------------------------------------------------------------


def test_the_operation_is_a_page_read_with_two_arguments_and_no_other_channel_or_group(world):
    row = operations.by_name("media-still")
    assert row["channels"] == ("page",) and row["call"] == "media_still" and row["model"] is False
    assert [a["name"] for a in row["args"]] == ["recording", "sha256"] and all(a["required"] for a in row["args"])
    assert "media-still" in operations.GROUPS["read"]["operations"]
    assert [g for g, spec in operations.GROUPS.items() if "media-still" in spec["operations"]] == ["read"]
    routes = [r for r in service.ROUTES if r["op"] == "media-still"]
    assert len(routes) == 1 and routes[0]["method"] == "GET" and routes[0]["file"] and routes[0]["loopback"] and routes[0]["bind"] == {"recording": "rid", "sha256": "sha"}
    assert "media-still" in operations.permissions("page", {"page": ["read"]})
    assert "media-still" not in operations.permissions("page", {"page": ["talk"]})


def test_the_operation_returns_an_opened_file_and_a_refusal_carries_its_kind(world, one):
    found = ops.media_still(world.project, world.rid, one["sha"])
    try:
        assert found["media_type"] == "image/png" and found["size"] == len(one["bytes"]) and found["sha256"] == one["sha"] and found["name"] == f"still-{one['sha'][:12]}.png"
        assert found["file"].read(8) == PNG_MAGIC
    finally:
        found["opened"].close()
    for bad, kind in (("short", "usage"), ("ab" * 32, "not_found")):
        with pytest.raises(ops.OpsError) as raised:
            ops.media_still(world.project, world.rid, bad)
        assert getattr(raised.value, "kind", None) == kind, bad
    with pytest.raises(ops.OpsError):
        ops.media_still(world.project, "not-an-id", one["sha"])


# --- the page's client: the bearer header, never a URL token, and the policy that lets a blob be shown ----------------------------------------------------

from test_interface_floor import INTERFACE, needs_node, run_node  # noqa: E402

CLIENT = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";
setToken("t".repeat(40));
const P = "0123456789ab", R = "0123456789abcdef", SHA = "a".repeat(64);
const seen = [];
let reply;
globalThis.fetch = async (url, init) => { seen.push({ url, init }); return reply(); };
const out = {};
reply = () => ({ ok: true, status: 200, headers: { get: () => "image/png" }, blob: async () => new Blob([new Uint8Array(6)], { type: "image/png" }), json: async () => { throw new Error("not json"); } });
const blob = await api.mediaStill(P, R, SHA);
out.ok = { url: seen[0].url, method: seen[0].init.method, accept: seen[0].init.headers.Accept, auth: seen[0].init.headers.Authorization === "Bearer " + "t".repeat(40),
           size: blob.size, type: blob.type, cred: seen[0].init.credentials, redirect: seen[0].init.redirect, mode: seen[0].init.mode };
const controller = new AbortController();
globalThis.fetch = async (url, init) => { seen.push({ url, init }); return reply(); };
await api.mediaStill(P, R, SHA, { signal: controller.signal });
out.signal = seen[1].init.signal === controller.signal;
reply = () => ({ ok: false, status: 404, json: async () => ({ error: "not_found", message: "there is no still for this recording" }) });
try { await api.mediaStill(P, R, SHA); out.refused = null; } catch (e) { out.refused = [e.status, e.word, e.message]; }
try { await api.mediaStill(P, R, "../x?token=1"); } catch (e) { out.odd = null; }
out.oddUrl = seen[seen.length - 1].url;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_client_fetches_the_still_as_a_blob_with_the_bearer_header_and_the_token_is_never_in_the_url(tmp_path):
    got = run_node(tmp_path, CLIENT)
    base = "/api/v1/projects/0123456789ab/media/0123456789abcdef"
    assert got["ok"] == {"url": f"{base}/still/{'a' * 64}", "method": "GET", "accept": "image/png", "auth": True, "size": 6, "type": "image/png",
                         "cred": "omit", "redirect": "error", "mode": "same-origin"}
    assert got["signal"] is True and got["refused"][:2] == [404, "not_found"]
    assert "%2F" in got["oddUrl"] and "%3F" in got["oddUrl"] and "?" not in got["oddUrl"]                                # a value is encoded, never a path or a query


def test_the_pages_policy_lets_a_blob_url_be_shown_as_an_image_and_nothing_loads_from_another_host():
    assert "img-src 'self' blob:" in service.CSP and "default-src 'self'" in service.CSP and "connect-src" not in service.CSP
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html

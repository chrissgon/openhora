"""Watching a video before its delivery (package V1c-3, limit L71; runtime/ops_media_watch.py `video_watch`, the route `GET .../videos/{id}/watch`): a real project at
the delivery gate, the real operations layer and store, the engine of media_kit. The page gets the bytes of the render the open deliver decision names, hashed
again; nothing is marked delivered; every other channel, every other state and a render that changed on disk are refused with their sentence; the LAN socket
refuses the route before the operation runs. Offline, no model, no network; every name is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_media_watch.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

import standin_tree as st
from media_kit import (ops, ops_core, open_items, ops_step_seams, task_row, to_gate, to_review, work_file, world)  # noqa: F401  (world is a fixture)
from test_service import PORT, TOKEN
from test_service_media import LAN, get_with, headers_of, url

watch = st.load("ops_media_watch")
operations = st.load("operations")
service = st.load("service")
media = st.load("media")
RUNTIME = st.RUNTIME


def refused(call, *args, **kwargs):
    with pytest.raises(ops.OpsError) as caught:
        call(*args, **kwargs)
    return caught.value


def document(world, task, gate):
    ctx = ops_core.context(world["path"])
    return ops_step_seams.EffectFiles(ctx["cfg"]).read(task, 0, gate["payload_sha256"])


def stage(world):
    projects = [{"id": service.project_id(world["path"]), "name": "alpha", "path": world["path"]}]
    svc = service.Service(ops, projects, TOKEN, PORT, None, log=lambda line: None)
    return svc, projects[0]["id"]


def test_at_the_gate_the_page_gets_the_render_and_it_hashes_to_the_document(world):
    task, gate = to_gate(world)
    doc = document(world, task, gate)
    got = ops.video_watch(world["path"], task, channel="page")
    assert set(got) == {"media_type", "data"} and got["media_type"] == "video/mp4"
    assert got["data"] == work_file(world, doc["video"]["name"]).read_bytes()
    assert hashlib.sha256(got["data"]).hexdigest() == doc["preview"]["sha256"]


def test_it_marks_nothing_and_writes_nothing(world):
    task, gate = to_gate(world)
    before = dict(media.load(world["data"], world["rid"]))
    for _ in range(2):
        ops.video_watch(world["path"], task, channel="page")
    assert media.load(world["data"], world["rid"]) == before and before["delivered"] is None
    assert [p["id"] for p in open_items(world, task)] == [gate["id"]] and task_row(world, task)["state"] == "waiting"


@pytest.mark.parametrize("channel", [None, "messaging", "terminal", "mcp"])
def test_any_channel_but_the_page_is_refused_with_its_sentence(world, channel):
    task, _ = to_gate(world)
    error = refused(ops.video_watch, world["path"], task, channel=channel)
    assert error.code == 1 and str(error) == watch.PAGE_ONLY


def test_at_the_review_with_no_open_deliver_decision_it_is_refused(world):
    task = to_review(world)
    error = refused(ops.video_watch, world["path"], task, channel="page")
    assert error.code == 1 and str(error) == watch.NOT_WAITING


def test_after_the_approval_it_is_refused(world):
    task, gate = to_gate(world)
    ops.approve(world["path"], gate["id"], sha256=gate["payload_sha256"], channel="terminal")
    assert refused(ops.video_watch, world["path"], task, channel="page").code == 1
    assert media.load(world["data"], world["rid"])["delivered"] is not None


@pytest.mark.parametrize("task", [999, True, "7", None])
def test_an_unknown_or_malformed_task_is_refused(world, task):
    to_gate(world)
    assert refused(ops.video_watch, world["path"], task, channel="page").code in (1, 2)


def test_a_render_that_changed_on_disk_is_refused_and_nothing_is_returned(world):
    task, gate = to_gate(world)
    path = work_file(world, document(world, task, gate)["video"]["name"])
    original = path.read_bytes()
    path.write_bytes(bytes(b ^ 1 for b in original))
    error = refused(ops.video_watch, world["path"], task, channel="page")
    assert error.code == 1 and str(error) == watch.CHANGED
    path.write_bytes(original + b"more")
    assert refused(ops.video_watch, world["path"], task, channel="page").code == 1


def test_a_render_over_the_preview_bound_is_not_shown_and_the_sentence_says_to_download_it_after_the_approval(world, monkeypatch):
    monkeypatch.setattr(st.load("deliver_document"), "PREVIEW_MAX_BYTES", 1)
    task, _ = to_gate(world)
    error = refused(ops.video_watch, world["path"], task, channel="page")
    assert error.code == 1 and str(error) == watch.TOO_LARGE and "after you approve" in str(error)


def test_a_render_over_the_limit_is_watched_through_the_renderers_preview_copy(world, monkeypatch):
    dd = st.load("deliver_document")
    monkeypatch.setattr(dd, "PREVIEW_MAX_BYTES", 20)
    task, gate = to_gate(world)
    doc = document(world, task, gate)
    assert doc["preview"]["sha256"] != doc["video"]["sha256"]
    path = work_file(world, dd.preview_name(doc))
    got = ops.video_watch(world["path"], task, channel="page")
    assert got["data"] == path.read_bytes() and hashlib.sha256(got["data"]).hexdigest() == doc["preview"]["sha256"]
    assert got["data"] != work_file(world, doc["video"]["name"]).read_bytes(), "the copy, not the render"
    path.write_bytes(bytes(b ^ 1 for b in got["data"]))      # the same length, other bytes
    error = refused(ops.video_watch, world["path"], task, channel="page")
    assert error.code == 1 and str(error) == watch.CHANGED
    assert media.load(world["data"], world["rid"])["delivered"] is None


def test_the_route_answers_the_bytes_inline_and_marks_nothing(world):
    task, gate = to_gate(world)
    svc, project = stage(world)
    status, headers, body = get_with(svc, f"/api/v1/projects/{project}/videos/{task}/watch")
    expected = work_file(world, document(world, task, gate)["video"]["name"]).read_bytes()
    assert (status, body, headers["Content-Type"], headers["Content-Disposition"]) == (200, expected, "video/mp4", "inline")
    assert media.load(world["data"], world["rid"])["delivered"] is None


def test_limit_71_a_video_is_watched_only_on_the_loopback_page_and_only_the_render_the_decision_names(world):
    task, gate = to_gate(world)
    svc, project = stage(world)
    path = f"/api/v1/projects/{project}/videos/{task}/watch"
    # the row is page only, in the group media, class G internal, and refused on the LAN socket
    row = next(r for r in operations.OPERATIONS if r["name"] == "video-watch")
    assert row["channels"] == ("page",) and "video-watch" in operations.GROUPS["media"]["operations"] and "video-watch" in operations.LAN_REFUSED_OPS
    svc.lan_ip = LAN
    status, _, payload = service.handle(svc, "GET", path, headers_of(0, lan=True, method="GET"), b"", lan=True)
    assert status == 409 and json.loads(payload)["message"] == operations.LAN_REFUSED_MEDIA
    # the loopback page gets exactly the render the open decision names; a changed render is refused
    expected = work_file(world, document(world, task, gate)["video"]["name"])
    status, _, body = get_with(svc, path)
    assert status == 200 and body == expected.read_bytes()
    expected.write_bytes(b"another render")
    assert get_with(svc, path)[0] != 200
    # the policy allows a blob: video and never data:
    assert "media-src 'self' blob:" in service.CSP and "data:" not in service.CSP


def test_the_route_is_in_the_table_raw_and_without_a_path_or_an_out():
    route = next(r for r in service.ROUTES if r["op"] == "video-watch")
    assert (route["method"], route["pattern"], route["raw"], route["download"], route["stream"]) == ("GET", "/projects/{p}/videos/{id}/watch", True, False, False)
    assert not route["take"]


def test_the_policy_is_four_directives_and_the_contract_says_so():
    assert [d.split()[0] for d in service.CSP.split("; ")] == ["default-src", "img-src", "media-src", "frame-ancestors"]
    assert "unsafe" not in service.CSP and "http" not in service.CSP
    contract = (st.REPO / "contracts" / "runtime.md").read_text(encoding="utf-8")
    assert f"`Content-Security-Policy: {service.CSP}`" in contract and "`media-src 'self' blob:`" in contract and "**L71.**" in contract


def test_the_module_prints_its_text_on_help_and_exits_2_otherwise():
    flags = ["--help"]
    argv = [sys.executable, "-I", str(RUNTIME / "ops_media_watch.py")]
    helped = subprocess.run(argv + flags, capture_output=True, text=True, env={})
    assert helped.returncode == 0 and helped.stdout.startswith("Watching a video before its delivery")
    assert subprocess.run(argv, capture_output=True, text=True, env={}).returncode == 2


# --- the page: the client's call and the Watch button ---------------------------------------------------------------------------------------

from test_interface_lobby import needs_node, run_node  # noqa: E402

CLIENT = r"""
import { setToken } from "@JS@/token.js";
const seen = [];
globalThis.fetch = async (url, init) => {
  seen.push({ method: init.method, url, accept: init.headers.Accept, body: init.body === undefined ? null : String(init.body) });
  return { ok: true, status: 200, headers: { get: () => null }, blob: async () => new Blob(["bytes"]), json: async () => ({}) };
};
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
const blob = await api.videoWatch("abcdef012345", 7);
console.log(JSON.stringify({ seen, size: blob.size, isBlob: blob instanceof Blob }));
"""


@needs_node
def test_the_client_asks_for_the_watch_route_as_video_and_gets_a_blob(tmp_path):
    got = run_node(tmp_path, CLIENT)
    assert got["seen"] == [{"method": "GET", "url": "/api/v1/projects/abcdef012345/videos/7/watch", "accept": "video/mp4", "body": None}]
    assert got["isBlob"] is True and got["size"] == 5


SECTION = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createVideos } from "@JS@/views/lobby-videos.js";

const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };
const made = [];
const revoked = [];
const makeUrl = URL.createObjectURL;
URL.createObjectURL = (blob) => { const url = makeUrl.call(URL, blob); made.push(url); return url; };
const dropUrl = URL.revokeObjectURL;
URL.revokeObjectURL = (url) => { revoked.push(url); return dropUrl.call(URL, url); };
const walk = (node, found, name) => {
  if (!node || typeof node.walk !== "function" || "hidden" in node.attrs) return found;
  if (node.tagName === name.toUpperCase()) found.push(node);
  node.children.forEach((child) => walk(child, found, name));
  return found;
};
const tag = (root, name) => walk(root, [], name);
const labelled = (root, text) => tag(root, "button").find((b) => textOf(b) === text);
const R = (media, task, task_state) => ({ media, created_at: "2026-10-03T09:00:00Z", size: 1234, type: "video/mp4", raw_kept: true, task, task_state, delivered_at: null });
let recs = [R("f3000000aaaaaaaa", 3, "waiting"), R("a4000000aaaaaaaa", 4, "waiting")];
const DETAIL = { status: { pending: [{ id: 51, kind: "effect", task_id: 3 }, { id: 52, kind: "effect", task_id: 4 }] } };
const calls = [];
let refuse = null;
const api = {
  mediaList: async () => ({ recordings: recs, used_bytes: 0, quota_bytes: 8589934592 }),
  artifacts: async () => ({ artifacts: [] }),
  videoWatch: async (p, id) => { calls.push([p, id]); if (refuse) throw Object.assign(new Error(refuse), { name: "ApiError", status: 409 }); return new Blob(["v"]); },
};
let host = "127.0.0.1";
let policy = null;
const section = createVideos({ api, project: "p", entry: () => policy, refresh: async () => {}, host: () => host });
const itemOf = (media) => byClass(section.el, "wb-vd-item").find((n) => n.attrs["data-media"] === media);
const buttons = (media) => tag(itemOf(media), "button").map(textOf);
const out = {};
section.update(DETAIL, true, 1); await settle();
out.before = { f3: buttons("f3000000aaaaaaaa"), a4: buttons("a4000000aaaaaaaa"), videos: tag(section.el, "video").length };
click(labelled(itemOf("f3000000aaaaaaaa"), "Watch the video")); await settle();
const video = tag(section.el, "video");
out.playing = { calls: calls.slice(), videos: video.length, src: video.length ? video[0].attrs.src === made[0] : null, blob: made[0] && made[0].startsWith("blob:"), controls: video.length ? "controls" in video[0].attrs : null,
  cls: video.length ? video[0].attrs.class : null, under: video.length ? byClass(section.el, "wb-vd-stage")[0].children.includes(video[0]) : null, f3: buttons("f3000000aaaaaaaa"), revoked: revoked.length };
// a redraw (a new reload stamp, a reread) keeps the very same video node attached, so it never pauses
for (const stamp of [5, 6]) { section.update(DETAIL, true, stamp); await settle(); }
const again = tag(section.el, "video");
out.kept = { same: again.length === 1 && again[0] === video[0], attached: byClass(section.el, "wb-vd-stage")[0].children.includes(video[0]), revoked: revoked.length, urls: made.length, buttons: buttons("f3000000aaaaaaaa") };
click(labelled(itemOf("f3000000aaaaaaaa"), "Close the video")); await settle();
out.closed = { videos: tag(section.el, "video").length, revoked: revoked.length === 1 && revoked[0] === made[0], f3: buttons("f3000000aaaaaaaa") };
// one at a time: the second replaces the first and gives its address back
click(labelled(itemOf("f3000000aaaaaaaa"), "Watch the video")); await settle();
click(labelled(itemOf("a4000000aaaaaaaa"), "Watch the video")); await settle();
out.replaced = { videos: tag(section.el, "video").length, revoked: revoked.length, made: made.length, stage: byClass(section.el, "wb-vd-stage")[0].children.length };
// the item leaves the delivery state: the video goes and its address is given back
recs = [R("f3000000aaaaaaaa", 3, "waiting"), { ...R("a4000000aaaaaaaa", 4, "done"), delivered_at: "2026-10-04T09:00:00Z" }];
section.update(DETAIL, true, 2); await settle();
out.left = { videos: tag(section.el, "video").length, revoked: revoked.length };
// a refusal shows as it came and plays nothing
refuse = "this video is not waiting for its delivery";
click(labelled(itemOf("f3000000aaaaaaaa"), "Watch the video")); await settle();
out.refused = { error: textOf(byClass(section.el, "wb-vd-error")[0]), videos: tag(section.el, "video").length, again: buttons("f3000000aaaaaaaa").includes("Watch the video") };
refuse = null;
// the local network: no button; the policy: no button without video-watch
host = "192.168.1.20";
section.update(DETAIL, true, 3); await settle();
out.lan = buttons("f3000000aaaaaaaa");
host = "127.0.0.1";
policy = { permissions: { allowed: ["media-list", "captions-read"] } };
section.update(DETAIL, true, 4); await settle();
out.policy = buttons("f3000000aaaaaaaa");
policy = null;
section.update(null, false);
out.hidden = { el: section.el.hidden, revoked: revoked.length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_watch_button_plays_one_video_from_a_blob_url_on_this_computer_only(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["before"] == {"f3": ["Watch the video"], "a4": ["Watch the video"], "videos": 0}
    assert got["playing"]["calls"] == [["p", 3]] and got["playing"]["videos"] == 1
    assert got["playing"]["src"] is True and got["playing"]["blob"] is True and got["playing"]["controls"] is True
    assert got["playing"]["cls"] == "wb-vd-video" and got["playing"]["under"] is True
    assert got["playing"]["f3"] == ["Close the video"] and got["playing"]["revoked"] == 0
    assert got["kept"] == {"same": True, "attached": True, "revoked": 0, "urls": 1, "buttons": ["Close the video"]}
    assert got["closed"] == {"videos": 0, "revoked": True, "f3": ["Watch the video"]}
    assert got["replaced"] == {"videos": 1, "revoked": 2, "made": 3, "stage": 2}
    assert got["left"] == {"videos": 0, "revoked": 3}
    assert got["refused"] == {"error": "this video is not waiting for its delivery", "videos": 0, "again": True}
    assert got["lan"] == [] and got["policy"] == []
    assert got["hidden"]["el"] is True

"""The page's part of a new video (package V1c-1): the client's nine calls and the service's routes for them, the pure model (the states of a recording, the
posts, the size limit, the loopback test), the Videos section of the Building (the list, the form, every result sentence, the local-network rule, the policy),
the deliver card (its rows, its hash, the approval that is not drawn or sent off this computer), the demo's answers compared with the real operations' keys, and
the text-only rule of the new modules. Run with Node over the real modules, a fake document and a stand-in client. No browser, no service, no model, no engine.
Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_videos.py
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys

import pytest

import standin_tree as st
from media_kit import to_review, world  # noqa: F401  (`world` is a fixture)
from test_interface_floor import run_node as run_floor_node
from test_interface_lobby import INTERFACE, NODE, needs_node, run_node  # noqa: F401  (the Node runners and the fake documents the Lobby's and the Floor's tests use)

service = st.load("service")
ops = st.load("ops")
media_animation = st.load("media_animation")
JS = INTERFACE / "js"
DEMO = INTERFACE / "demo"

LAN_MEDIA = "A recording, its still and the video are sent only through this computer's own page (127.0.0.1)."
LAN_APPROVE = "Approve the delivery on this computer's own page (127.0.0.1): a video is never approved over the local network."


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_under_videos", st.REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


demo_fixtures = load_script("demo_fixtures")

# --- the client ----------------------------------------------------------------------------------------------------------------------------

CLIENT = r"""
import { setToken } from "@JS@/token.js";

const seen = [];
let disposition = 'attachment; filename="video-0123456789ab.mp4"';
const headers = { get: (name) => (name === "Content-Disposition" ? disposition : null) };
globalThis.fetch = async (url, init) => {
  seen.push({ method: init.method, url, type: init.headers["Content-Type"] || null, accept: init.headers.Accept, blob: init.body instanceof Blob, text: typeof init.body === "string" ? init.body : null });
  if (url.endsWith("/download") || url.endsWith("/still")) return { ok: true, status: 200, headers, blob: async () => new Blob(["bytes"]), json: async () => ({}) };
  return { ok: true, status: 200, headers, json: async () => ({}) };
};
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
const out = {};
await api.mediaList("abcdef012345");
await api.mediaIn("abcdef012345", new Blob(["a"], { type: "video/mp4" }));
await api.mediaIn("abcdef012345", new Blob(["b"], { type: "video/quicktime" }));
await api.mediaIn("abcdef012345", new Blob(["c"], { type: "text/html" }));
await api.videoNew("abcdef012345", "a1b2c3d4e5f60718", "docs/marketing/content/launch-day.md");
await api.videoRun("abcdef012345", 7);
await api.captionsRead("abcdef012345", 7);
await api.captionsEdit("abcdef012345", 7, 3, [{ op: "edit", index: 3, text: "Northwind" }]);
const first = await api.videoDownload("abcdef012345", 7);
out.name = [first.name, first.blob.size];
disposition = 'attachment; filename="../x.mp4"';
out.other = (await api.videoDownload("abcdef012345", 7)).name;
disposition = 'attachment; filename="video-0123456789AB.mp4"';
out.upper = (await api.videoDownload("abcdef012345", 7)).name;
out.still = (await api.videoStill("abcdef012345", 7)).size;
await api.videoCatalogue("abcdef012345");
out.seen = seen;
console.log(JSON.stringify(out));
"""


@needs_node
def test_each_of_the_nine_calls_sends_its_method_and_path_and_only_the_upload_sends_bytes(tmp_path):
    got = run_node(tmp_path, CLIENT)
    base = "/api/v1/projects/abcdef012345"
    seen = got["seen"]
    assert [(c["method"], c["url"]) for c in seen] == [
        ("GET", base + "/media"), ("POST", base + "/media"), ("POST", base + "/media"), ("POST", base + "/media"), ("POST", base + "/videos"),
        ("POST", base + "/videos/7/run"), ("GET", base + "/videos/7/captions"), ("POST", base + "/videos/7/captions"), ("GET", base + "/videos/7/download"),
        ("GET", base + "/videos/7/download"), ("GET", base + "/videos/7/download"), ("GET", base + "/videos/7/still"), ("GET", base + "/video-catalogue")]
    assert [c["type"] for c in seen[1:4]] == ["video/mp4", "video/quicktime", "application/octet-stream"]
    assert all(c["blob"] and c["text"] is None for c in seen[1:4]), "the recording is the body itself, never JSON"
    assert json.loads(seen[4]["text"]) == {"media_id": "a1b2c3d4e5f60718", "post": "docs/marketing/content/launch-day.md"} and seen[4]["type"] == "application/json"
    assert json.loads(seen[5]["text"]) == {} and seen[5]["type"] == "application/json"
    body = json.loads(seen[7]["text"])
    assert body == {"revision": 3, "edits": '[{"op":"edit","index":3,"text":"Northwind"}]'} and isinstance(body["edits"], str)
    assert got["name"] == ["video-0123456789ab.mp4", 5] and got["other"] == "video.mp4" and got["upper"] == "video.mp4"
    assert seen[8]["accept"] == "video/mp4" and seen[11]["accept"] == "image/*" and seen[0]["accept"] == "application/json"
    assert got["still"] == 5


@needs_node
def test_every_call_is_a_route_of_the_service_with_the_same_method(tmp_path):
    got = run_node(tmp_path, CLIENT)
    ops_of = {}
    for call in got["seen"]:
        found = service.match(call["method"], call["url"])
        assert found is not None, call
        ops_of[(call["method"], found[0]["op"])] = True
    assert {op for _, op in ops_of} == {"media-list", "media-in", "video-new", "video-run", "captions-read", "captions-edit", "video-download", "video-still", "video-catalogue"}
    assert all(service.match("POST", "/api/v1/projects/abcdef012345" + tail) is not None for tail in ("/media", "/videos", "/videos/7/run", "/videos/7/captions"))


# --- the model -----------------------------------------------------------------------------------------------------------------------------

MODEL = r"""
import * as m from "@JS@/views/lobby-video-model.js";
import * as d from "@JS@/cards/deliver.js";

const out = {};
const pend = [{ id: 50, kind: "question", task_id: 5 }, { id: 51, kind: "effect", task_id: 6 }, { id: 52, kind: "plan", task_id: 8 }];
const rec = (extra) => ({ raw_kept: true, delivered_at: null, task: 1, task_state: "done", ...extra });
out.states = {
  done: m.stateOf(rec({ delivered_at: "2026-10-01T09:30:00Z" }), pend),
  doneAndRemoved: m.stateOf(rec({ delivered_at: "2026-10-01T09:30:00Z", raw_kept: false }), pend),
  removed: m.stateOf(rec({ raw_kept: false }), pend),
  none: m.stateOf(rec({ task: null, task_state: null }), pend),
  ready: m.stateOf(rec({ task_state: "ready" }), pend),
  running: m.stateOf(rec({ task_state: "running" }), pend),
  review: m.stateOf(rec({ task: 5, task_state: "waiting" }), pend),
  deliver: m.stateOf(rec({ task: 6, task_state: "waiting" }), pend),
  waiting: m.stateOf(rec({ task: 8, task_state: "waiting" }), pend),
  waitingNoRow: m.stateOf(rec({ task: 9, task_state: "waiting" }), []),
  finished: m.stateOf(rec({ task_state: "done" }), pend),
  failed: m.stateOf(rec({ task_state: "failed" }), pend),
  cancelled: m.stateOf(rec({ task_state: "cancelled" }), pend),
  unknown: m.stateOf(rec({ task_state: "weird" }), pend),
};
out.texts = Object.keys(m.STATE_TEXT);
out.posts = m.postChoices({ artifacts: ["docs/marketing/content/launch-day.md", "docs/marketing/content/Launch.md", "docs/marketing/x.md", "docs/marketing/content/a/b.md", "docs/marketing/content/aster-2.md"].map((path) => ({ path })) });
out.postsOther = [m.postChoices(null), m.postChoices({}), m.postChoices({ artifacts: [{ path: 7 }, null] })];
out.problem = [m.fileProblem({ size: 0 }), m.fileProblem({ size: 1 }), m.fileProblem({ size: 1073741824 }), m.fileProblem({ size: 1073741825 }), m.fileProblem(null)];
out.sizes = [m.sizeWords(0), m.sizeWords(812), m.sizeWords(3584), m.sizeWords(12 * 1048576), m.sizeWords(1288490188), m.sizeWords(-1), m.sizeWords("x")];
out.newest = [m.newestFirst([{ media: "a" }, { media: "b" }, { media: "c" }]).map((r) => r.media), m.newestFirst(null)];
out.loop = Object.fromEntries(["127.0.0.1", "localhost", "[::1]", "::1", "", null, undefined, "192.168.1.20", "127.0.0.2", "localhost.example", "LOCALHOST"].map((h) => [String(h), d.onLoopback(h)]));
out.hostNone = d.hostNow();
out.hostOf = [d.hostOf({ host: () => "localhost" }), d.hostOf({ host: () => null }), d.hostOf(null)];
out.deliver = [d.isDeliver({ kind: "effect", effect_word: "deliver" }), d.isDeliver({ kind: "effect", effect_word: "publish" }), d.isDeliver({ kind: "plan", effect_word: "deliver" }), d.isDeliver(null)];
out.rows = [d.deliverRows("a\n\nb\n"), d.deliverRows(null)];
out.consts = [d.LAN_MEDIA, d.LAN_APPROVE, m.MAX_BYTES, m.LIST_MAX];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_model_names_each_state_the_posts_the_size_limit_and_the_loopback_hosts(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["states"] == {"done": "done", "doneAndRemoved": "done", "removed": "removed", "none": "none", "ready": "ready", "running": "running", "review": "review", "deliver": "deliver",
                             "waiting": "waiting", "waitingNoRow": "waiting", "finished": "finished", "failed": "failed", "cancelled": "cancelled", "unknown": "unknown"}
    assert sorted(got["texts"]) == sorted(["none", "ready", "running", "review", "deliver", "waiting", "done", "finished", "failed", "cancelled", "removed", "unknown"])
    assert got["posts"] == ["docs/marketing/content/aster-2.md", "docs/marketing/content/launch-day.md"]
    assert got["postsOther"] == [[], [], []]
    assert got["problem"] == ["The file is empty.", None, None, "A recording is at most 1 GiB.", "The file is empty."]
    assert got["sizes"] == ["0 bytes", "812 bytes", "3.5 KiB", "12.0 MiB", "1.2 GiB", "", ""]
    assert got["newest"] == [["c", "b", "a"], []]
    assert [k for k, v in got["loop"].items() if v] == ["127.0.0.1", "localhost", "[::1]", "::1"]
    assert got["hostNone"] == "" and got["hostOf"] == ["localhost", "", ""]
    assert got["deliver"] == [True, False, False, False] and got["rows"] == [["a", "b"], []]
    assert got["consts"] == [LAN_MEDIA, LAN_APPROVE, 1073741824, 10]


# --- the section ---------------------------------------------------------------------------------------------------------------------------

SECTION = r"""
import { byClass, click, textOf } from "@FAKE@";
import { createVideos } from "@JS@/views/lobby-videos.js";

const realSet = globalThis.setTimeout;
const revokers = [];
globalThis.setTimeout = (fn, ms, ...rest) => { if (ms === 60000) { revokers.push(fn); return 0; } return realSet(fn, ms, ...rest); };
const settle = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => realSet(r, 0)); };
const created = [];
const revoked = [];
const makeUrl = URL.createObjectURL;
URL.createObjectURL = (blob) => { const url = makeUrl.call(URL, blob); created.push(url); return url; };
const dropUrl = URL.revokeObjectURL;
URL.revokeObjectURL = (url) => { revoked.push(url); return dropUrl.call(URL, url); };
const anchors = [];
const makeNode = document.createElement;
document.createElement = (name) => { const node = makeNode.call(document, name); if (name === "a") { node.click = () => { node.clicked = true; }; anchors.push(node); } return node; };

const walkShown = (node, found, name) => {
  if (!node || typeof node.walk !== "function" || "hidden" in node.attrs) return found;
  if (node.tagName === name.toUpperCase()) found.push(node);
  node.children.forEach((child) => walkShown(child, found, name));
  return found;
};
const tag = (root, name) => walkShown(root, [], name);
const fire = (node, type) => (node.listeners[type] || []).forEach((fn) => fn({ target: node }));
const labelled = (root, text) => tag(root, "button").find((b) => textOf(b) === text);

const R = (media, day, task, task_state, extra = {}) => ({ media, created_at: `2026-10-${day}T09:00:00Z`, updated_at: `2026-10-${day}T09:20:00Z`, size: 48234567, type: "video/mp4", raw_kept: true, task, task_state, delivered_at: null, ...extra });
const RECS = [R("d1000000aaaaaaaa", "01", 1, "done", { delivered_at: "2026-10-01T09:30:00Z" }), R("e2000000aaaaaaaa", "02", 2, "waiting"), R("f3000000aaaaaaaa", "03", 3, "waiting"), R("a4000000aaaaaaaa", "04", 4, "ready"),
  R("b5000000aaaaaaaa", "05", null, null), R("c6000000aaaaaaaa", "06", 6, "failed"), R("a7000000aaaaaaaa", "07", 7, "running")];
const DETAIL = { status: { pending: [{ id: 50, kind: "question", task_id: 2 }, { id: 51, kind: "effect", task_id: 3 }] } };
const calls = [];
let pollAnswer = { state: "done", result: { started: true } };
let refuse = null;
const api = {
  mediaList: async () => { calls.push(["mediaList"]); return { recordings: RECS, used_bytes: 1288490188, quota_bytes: 8589934592 }; },
  artifacts: async () => { calls.push(["artifacts"]); return { artifacts: ["docs/marketing/content/launch-day.md", "docs/marketing/content/Launch.md", "docs/marketing/x.md", "docs/marketing/content/a/b.md"].map((path) => ({ path })) }; },
  mediaIn: async (p, file) => { calls.push(["mediaIn", p, file.size]); return { media: "ee000000ffffffff" }; },
  videoNew: async (p, media, post) => { calls.push(["videoNew", p, media, post]); if (refuse) throw Object.assign(new Error(refuse), { name: "ApiError", status: 409 }); return { job: 11 }; },
  videoRun: async (p, id) => { calls.push(["videoRun", p, id]); return { job: 12 }; },
  pollJob: async (id) => { calls.push(["pollJob", id]); return pollAnswer; },
  videoDownload: async (p, id) => { calls.push(["videoDownload", p, id]); return { blob: new Blob(["v"]), name: "video-0123456789ab.mp4" }; },
};
let host = "127.0.0.1";
let policy = null;
let refreshed = 0;
const reviews = [];
const make = (extra = {}) => createVideos({ api, project: "p", entry: () => policy, refresh: async () => { refreshed += 1; }, host: () => host, openReview: (task, mode) => reviews.push([task, mode]), ...extra });
const itemOf = (section, media) => byClass(section.el, "wb-vd-item").find((n) => n.attrs["data-media"] === media);
const buttonsOf = (item) => tag(item, "button").map(textOf);
const linksOf = (item) => tag(item, "a").map((a) => [textOf(a), a.attrs.href]);
const count = (name) => calls.filter((c) => c[0] === name).length;
const out = {};

const section = make();
out.hiddenAtStart = section.el.hidden;
section.update(DETAIL, true, 1);
await settle();
const items = byClass(section.el, "wb-vd-item");
out.order = items.map((n) => n.attrs["data-media"]);
out.titles = items.slice(0, 2).map((n) => textOf(byClass(n, "wb-vd-name")[0]));
out.states = Object.fromEntries(items.map((n) => [n.attrs["data-media"].slice(0, 2), textOf(byClass(n, "wb-vd-state")[0])]));
out.buttons = Object.fromEntries(items.map((n) => [n.attrs["data-media"].slice(0, 2), buttonsOf(n)]));
out.links = { review: linksOf(itemOf(section, "e2000000aaaaaaaa")), deliver: linksOf(itemOf(section, "f3000000aaaaaaaa")) };
out.quota = textOf(byClass(section.el, "wb-vd-quota")[0]);
out.form = { options: tag(section.el, "option").map(textOf), file: tag(section.el, "input").length, upload: tag(section.el, "button").map(textOf).includes("Upload and start"), reads: [count("mediaList"), count("artifacts")] };
out.uploadOff = labelled(section.el, "Upload and start").disabled;

// Start with no post chosen: nothing is sent
click(labelled(itemOf(section, "b5000000aaaaaaaa"), "Start")); await settle();
out.noPost = { note: textOf(byClass(section.el, "wb-vd-note")[0]), sent: count("videoNew") };
const drawButton = () => labelled(section.el, "Draw the storyboard");
out.draw = { before: drawButton().disabled === true };      // V5-1: the storyboard's button needs a chosen post
// choose the post, then Start the failed one
const select = tag(section.el, "select")[0];
select.value = "docs/marketing/content/launch-day.md"; fire(select, "change");
out.draw.after = drawButton().disabled === true;      // enabled right after the post is chosen, with no other redraw in between
click(labelled(itemOf(section, "c6000000aaaaaaaa"), "Start")); await settle();
out.start = { calls: calls.filter((c) => ["videoNew", "pollJob"].includes(c[0])), note: textOf(byClass(section.el, "wb-vd-note")[0]), refreshed, lists: count("mediaList") };
// Run the ready one
calls.length = 0;
click(labelled(itemOf(section, "a4000000aaaaaaaa"), "Run")); await settle();
out.run = { calls: calls.filter((c) => ["videoRun", "pollJob"].includes(c[0])), note: textOf(byClass(section.el, "wb-vd-note")[0]) };
// the review opens: at the review, at the delivery card and read-only
click(labelled(itemOf(section, "e2000000aaaaaaaa"), "Check the captions"));
click(labelled(itemOf(section, "f3000000aaaaaaaa"), "Check the captions"));
click(labelled(itemOf(section, "d1000000aaaaaaaa"), "Check the captions"));
out.reviews = reviews.slice();

// Upload and start, with each sentence of the end
const uploadWith = async (size, answer) => {
  const input = tag(section.el, "input")[0];
  input.files = [{ size, type: "video/mp4" }]; fire(input, "change");
  if (answer) pollAnswer = answer;
  calls.length = 0;
  click(labelled(section.el, "Upload and start")); await settle();
  return { note: textOf(byClass(section.el, "wb-vd-note")[0]), error: textOf(byClass(section.el, "wb-vd-error")[0]), calls: calls.filter((c) => ["mediaIn", "videoNew", "pollJob"].includes(c[0])), off: labelled(section.el, "Upload and start").disabled, value: input.value };
};
out.up = await uploadWith(10, { state: "done", result: { started: true } });
out.upNotStarted = (await uploadWith(10, { state: "done", result: { started: false, reason: "a run is going" } })).note;
out.upFailedStep = (await uploadWith(10, { state: "done", result: { started: true, failed: true, code: "engine", field: "render" } })).note;
out.upFailedBare = (await uploadWith(10, { state: "done", result: { started: true, failed: true, code: "engine" } })).note;
out.upJobFailed = (await uploadWith(10, { state: "failed", error: { message: "the job broke" } })).note;
out.tooBig = await uploadWith(1073741825, { state: "done", result: { started: true } });
refuse = "that post has no script";
out.refused = await uploadWith(10, { state: "done", result: {} });
out.refusedStart = labelled(itemOf(section, "c6000000aaaaaaaa"), "Start").disabled;
refuse = null;

// Download
click(labelled(itemOf(section, "d1000000aaaaaaaa"), "Download")); await settle();
out.download = { calls: calls.filter((c) => c[0] === "videoDownload"), anchors: anchors.filter((a) => (a.attrs.href || "").startsWith("blob:")).map((a) => [a.clicked === true, a.attrs.download, a.parent === null]), revokers: revokers.length, revokedBefore: revoked.length };
if (revokers[0]) revokers[0](); out.download.revokedAfter = revoked.length === 1 && revoked[0] === created[0];

// more than ten recordings: the newest ten and "and N older"
const many = Array.from({ length: 13 }, (_, i) => R(`${String(i).padStart(2, "0")}000000aaaaaaaa`, "01", null, null));
const big = createVideos({ api: { ...api, mediaList: async () => ({ recordings: many, used_bytes: 0, quota_bytes: 8589934592 }) }, project: "p", entry: () => null, refresh: async () => {}, host: () => host });
big.update(DETAIL, true, 1); await settle();
out.many = { items: byClass(big.el, "wb-vd-item").length, first: byClass(big.el, "wb-vd-item")[0].attrs["data-media"], more: textOf(byClass(big.el, "wb-vd-more")[0]) };

// the local network: no file input, the line, no Download, Start still drawn
host = "192.168.1.20";
const lan = make();
lan.update(DETAIL, true, 1); await settle();
out.lan = { inputs: tag(lan.el, "input").length, lines: byClass(lan.el, "wb-vd-lan").map(textOf), upload: tag(lan.el, "button").map(textOf).includes("Upload and start"), done: buttonsOf(itemOf(lan, "d1000000aaaaaaaa")),
  doneLine: textOf(itemOf(lan, "d1000000aaaaaaaa")).includes("through this computer's own page"), failed: buttonsOf(itemOf(lan, "c6000000aaaaaaaa")), select: tag(lan.el, "select").length };
click(labelled(itemOf(lan, "c6000000aaaaaaaa"), "Start")); await settle();
out.lan.startNeedsPost = textOf(byClass(lan.el, "wb-vd-note")[0]);
host = "127.0.0.1";

// the policy: the list only, then no list at all, then Start without the upload
policy = { permissions: { allowed: ["media-list"] } };
const listOnly = make(); listOnly.update(DETAIL, true, 1); await settle();
out.listOnly = { hidden: listOnly.el.hidden, items: byClass(listOnly.el, "wb-vd-item").length, buttons: tag(listOnly.el, "button").length, inputs: tag(listOnly.el, "input").length, selects: tag(listOnly.el, "select").length };
policy = { permissions: { allowed: ["status"] } };
const none = make(); none.update(DETAIL, true, 1); await settle();
out.noList = none.el.hidden;
policy = { permissions: { allowed: ["media-list", "video-new", "captions-read"] } };
const startOnly = make(); startOnly.update(DETAIL, true, 1); await settle();
out.startOnly = { selects: tag(startOnly.el, "select").length, inputs: tag(startOnly.el, "input").length, upload: tag(startOnly.el, "button").map(textOf).includes("Upload and start"), failed: buttonsOf(itemOf(startOnly, "c6000000aaaaaaaa")), ready: buttonsOf(itemOf(startOnly, "a4000000aaaaaaaa")) };
policy = null;
// without openReview the review is not offered; a section that is not shown draws nothing
const bare = make({ openReview: undefined }); bare.update(DETAIL, true, 1); await settle();
out.bare = buttonsOf(itemOf(bare, "e2000000aaaaaaaa"));
bare.update(null, false);
out.notShown = bare.el.hidden;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_section_lists_newest_first_offers_each_state_its_action_and_says_each_result(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["hiddenAtStart"] is True
    assert got["order"] == ["a7000000aaaaaaaa", "c6000000aaaaaaaa", "b5000000aaaaaaaa", "a4000000aaaaaaaa", "f3000000aaaaaaaa", "e2000000aaaaaaaa", "d1000000aaaaaaaa"]
    assert got["titles"] == ["Recording a7000000 · 2026-10-07 · 46.0 MiB", "Recording c6000000 · 2026-10-06 · 46.0 MiB"]
    assert got["states"] == {"a7": "Working: transcribing, cutting or rendering.", "c6": "Failed.", "b5": "Not started.", "a4": "Ready to run.", "f3": "Waiting for you: approve the delivery.",
                             "e2": "Waiting for you: check the captions.", "d1": "Delivered."}
    assert got["buttons"] == {"a7": [], "c6": ["Start"], "b5": ["Start"], "a4": ["Run"], "f3": ["Check the captions", "Watch the video"], "e2": ["Check the captions"], "d1": ["Download", "Check the captions"]}
    assert got["links"] == {"review": [["Open the decision", "#/p/p/lobby/inbox/50"]], "deliver": [["Open the delivery card", "#/p/p/lobby/inbox/51"]]}
    assert got["quota"] == "Recordings use 1.2 GiB of 8.0 GiB."
    assert got["form"] == {"options": ["Choose a post", "docs/marketing/content/launch-day.md"], "file": 1, "upload": True, "reads": [1, 1]}
    assert got["uploadOff"] is True
    assert got["noPost"] == {"note": "Choose a post in the form above first.", "sent": 0}
    assert got["draw"] == {"before": True, "after": False}, "the storyboard's button is off with no post and on right after one is chosen"
    assert got["start"]["calls"] == [["videoNew", "p", "c6000000aaaaaaaa", "docs/marketing/content/launch-day.md"], ["pollJob", 11]]
    assert got["start"]["note"] == "The captions are ready to check." and got["start"]["refreshed"] == 1 and got["start"]["lists"] == 2
    assert got["run"] == {"calls": [["videoRun", "p", 4], ["pollJob", 12]], "note": "The captions are ready to check."}
    assert got["reviews"] == [[2, "review"], [3, "gate"], [1, None]]
    assert got["up"]["calls"] == [["mediaIn", "p", 10], ["videoNew", "p", "ee000000ffffffff", "docs/marketing/content/launch-day.md"], ["pollJob", 11]]
    assert got["up"]["note"] == "The captions are ready to check." and got["up"]["off"] is True and got["up"]["value"] == "", "the file is cleared: a second click uploads nothing"
    assert got["upNotStarted"] == "The video is ready to run: a run is going"
    assert got["upFailedStep"] == "The step failed: engine (render)" and got["upFailedBare"] == "The step failed: engine"
    assert got["upJobFailed"] == "the job broke"
    assert got["tooBig"]["calls"] == [] and got["tooBig"]["note"] == "A recording is at most 1 GiB."
    assert got["refused"]["error"] == "that post has no script" and got["refused"]["calls"][0][0] == "mediaIn" and got["refusedStart"] is False, "a refusal shows as it came and the buttons come back"
    assert got["download"]["calls"] == [["videoDownload", "p", 1]]
    assert got["download"]["anchors"] == [[True, "video-0123456789ab.mp4", True]], "an anchor with the blob address and the server's name, clicked and removed"
    assert got["download"]["revokers"] == 1 and got["download"]["revokedBefore"] == 0 and got["download"]["revokedAfter"] is True
    assert got["many"] == {"items": 10, "first": "12000000aaaaaaaa", "more": "and 3 older"}
    assert got["notShown"] is True


@needs_node
def test_on_the_local_network_no_file_is_asked_for_or_downloaded_and_the_page_says_why(tmp_path):
    got = run_node(tmp_path, SECTION)["lan"]
    assert got["inputs"] == 0 and got["upload"] is False
    assert got["lines"] == [LAN_MEDIA, LAN_MEDIA], "one line in the form, one in place of Download"
    assert got["done"] == ["Check the captions"] and got["doneLine"] is True
    assert got["failed"] == ["Start"] and got["select"] == 1
    assert got["startNeedsPost"] == "Choose a post in the form above first."


@needs_node
def test_the_policy_decides_which_controls_are_drawn(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["listOnly"] == {"hidden": False, "items": 7, "buttons": 0, "inputs": 0, "selects": 0}
    assert got["noList"] is True
    assert got["startOnly"] == {"selects": 1, "inputs": 0, "upload": False, "failed": ["Start"], "ready": []}
    assert got["bare"] == []


# --- the deliver card ----------------------------------------------------------------------------------------------------------------------

CARD = r"""
import { settle, find, all } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";

const calls = [];
let host = "127.0.0.1";
const client = () => ({
  approve: async (...args) => { calls.push(["approve", ...args.slice(0, 3)]); return { job: 1 }; },
  reject: async (...args) => { calls.push(["reject", ...args.slice(0, 3)]); return {}; },
  pollJob: async () => ({ state: "done", result: {} }),
});
const env = () => ({ project: "p", now: () => new Date("2026-10-12T12:00:00Z"), api: client(), requestIds: new Set([1]), links: { floor: (a) => `#/p/p/floor/${a}`, lobby: () => "#/p/p/lobby", open: () => "#/x", parent: () => "#/p/p" },
  reread: async () => null, changed() {}, gone() {}, host: () => host });
const HASH = "c".repeat(64);
const LINES = ["Platform: instagram", "Post: docs/marketing/content/launch-day.md", `Video: render-0123456789ab.mp4, 48.2 MB, 21.4 s, sha256 ${"d".repeat(64)}`, "Cover: no cover", "verified for instagram",
  "Animation block: a1 " + "e".repeat(64), "Animation block: a2 " + "f".repeat(64), "preview " + "1".repeat(64) + ", made from " + "2".repeat(64), "Delivery document sha256 " + HASH,
  "Approving marks this exact file downloadable. Nothing is published."];
const item = (extra = {}) => ({ id: 31, kind: "effect", effect_word: "deliver", title: "Deliver the video", body: LINES.join("\n"), payload: {}, payload_sha256: HASH, status: "open", actions: ["approved", "rejected"],
  agent: null, task_id: 9, run_id: null, created_at: "2026-10-12T09:00:00Z", ...extra });
const words = (card) => all(card.el, "button.wb-card-button").map((b) => b.attrs["data-word"]);
const hints = (card) => all(card.el, ".wb-card-hint").map((n) => n.textContent);
const out = {};

const home = createCard(item(), env());
out.home = { words: words(home), rows: all(home.el, "ul.wb-dl-rows li").map((n) => n.textContent), hints: hints(home), hash: find(home.el, "code.wb-hash").textContent, pre: all(home.el, "pre.wb-pre").length,
  line: find(home.el, "p.wb-card-line").textContent, note: all(home.el, "input.wb-field-input").length, tab: find(home.el, "ul.wb-dl-rows").attrs.tabindex };
all(home.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "approved").click();
await settle();
out.approved = calls.slice();

calls.length = 0;
host = "192.168.1.20";
const away = createCard(item(), env());
out.away = { words: words(away), line: find(away.el, "p.wb-card-line").textContent, hash: find(away.el, "code.wb-hash").textContent, withheld: find(away.el, "[data-key=withheld]") === null,
  rows: all(away.el, "ul.wb-dl-rows li").length };
host = "127.0.0.1";
const stale = createCard(item(), env());
const approve = all(stale.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "approved");
host = "192.168.1.20";
approve.click();
await settle();
out.stale = calls.slice();
all(away.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "rejected").click();
await settle();
out.reject = calls.slice();

host = "127.0.0.1";
const publish = createCard(item({ effect_word: "publish", title: "Publish the post", body: "Hello" }), env());
out.publish = { hints: hints(publish), pre: all(publish.el, "pre.wb-pre").length, rows: all(publish.el, "ul.wb-dl-rows").length, line: find(publish.el, "p.wb-card-line").textContent, words: words(publish) };
host = "192.168.1.20";
const publishAway = createCard(item({ effect_word: "publish", title: "Publish the post", body: "Hello" }), env());
out.publishAway = words(publishAway);
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_deliver_card_shows_the_documents_lines_and_hash_and_is_approved_only_on_this_computers_own_page(tmp_path):
    got = run_floor_node(tmp_path, CARD)
    home = got["home"]
    assert home["words"] == ["approved", "rejected"] and len(home["rows"]) == 10 and home["rows"][0] == "Platform: instagram" and home["rows"][-1].startswith("Approving marks this exact file")
    assert home["hints"] == ["The delivery: what your approval covers", "Hash of the delivery document"] and home["hash"] == "c" * 64 and home["pre"] == 0 and home["tab"] == "0"
    assert home["line"] == "Nothing is marked downloadable before you approve this exact content." and home["note"] == 1
    assert got["approved"] == [["approve", "p", 31, "c" * 64]]
    away = got["away"]
    assert away["words"] == ["rejected"] and away["line"] == LAN_APPROVE and away["hash"] == "c" * 64 and away["withheld"] is True and away["rows"] == 10
    assert got["stale"] == [], "the press path refuses too: a card drawn on this computer and pressed after the host changed sends nothing"
    assert got["reject"] == [["reject", "p", 31, None]]
    publish = got["publish"]
    assert publish["hints"] == ["Exact content of the publish (what will be sent):", "Hash of this content"] and publish["pre"] == 1 and publish["rows"] == 0
    assert publish["line"] == "Nothing is sent before you approve this exact content." and publish["words"] == ["approved", "rejected"]
    assert got["publishAway"] == ["approved", "rejected"], "only a delivery is held back off this computer"


# --- the demo ------------------------------------------------------------------------------------------------------------------------------

DEMO_SCRIPT = r"""
import { createWorld } from "@DEMO@/world.js";
import * as reads from "@DEMO@/world-reads.js";

const world = createWorld({ now: () => Date.UTC(2026, 9, 11, 12, 0, 0), later: () => 0, cancelLater: () => {} });
const get = async (path) => world.handle("GET", "/api/v1" + path, new URLSearchParams());
const post = async (path, body = {}) => world.handle("POST", "/api/v1" + path, new URLSearchParams(), body);
const projects = (await get("/projects")).body.projects;
const shop = projects.find((p) => p.name === "northwind-shop").id;
const other = projects.find((p) => p.name !== "northwind-shop").id;
const out = {};
out.list = (await get(`/projects/${shop}/media`)).body;
out.listOther = (await get(`/projects/${other}/media`)).body;
out.captions = (await get(`/projects/${shop}/videos/900/captions`)).body;
out.captionsOther = (await get(`/projects/${shop}/videos/901/captions`)).status;
out.catalogue = (await get(`/projects/${shop}/video-catalogue`)).body;
const refusals = {};
for (const [label, answer] of [["still", await get(`/projects/${shop}/videos/900/still`)], ["download", await get(`/projects/${shop}/videos/900/download`)], ["upload", await post(`/projects/${shop}/media`)],
  ["new", await post(`/projects/${shop}/videos`, { media_id: "a1b2c3d4e5f60718", post: "docs/marketing/content/x.md" })], ["run", await post(`/projects/${shop}/videos/900/run`)],
  ["edit", await post(`/projects/${shop}/videos/900/captions`, { revision: 3, edits: "[]" })]]) refusals[label] = [answer.status, answer.body.error, answer.body.message];
out.refusals = refusals;
console.log(JSON.stringify(out));
"""


def within(answer, allowed, where):
    """Every key of `answer`, at every depth, is a key of `allowed` (a skeleton of the real answer). A leaf or an empty list of the real answer ends the check."""
    if allowed is None or where.endswith((".params", ".presets")):
        return
    if isinstance(answer, dict):
        assert isinstance(allowed, dict), f"{where}: a table where the real answer has none"
        for key, value in answer.items():
            assert key in allowed, f"{where}: the key {key!r} is not one the operation gives"
            within(value, allowed[key], f"{where}.{key}")
    elif isinstance(answer, list) and answer and allowed:
        for element in answer:
            within(element, allowed[0], f"{where}[]")


@needs_node
def test_the_demos_three_answers_have_only_keys_the_real_operations_give_and_every_video_write_is_refused(world, tmp_path):
    script = tmp_path / "demo.mjs"
    script.write_text(DEMO_SCRIPT.replace("@DEMO@", DEMO.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    sk = demo_fixtures.skeleton
    path = world["path"]
    task = to_review(world)
    at_review = ops.captions_read(path, task)
    listed = ops.media_list(path)
    real = {"media": sk(listed), "captions": sk(at_review), "catalogue": sk(media_animation.listing(str(st.REPO)))}
    within(got["list"], real["media"], "media")
    within(got["listOther"], real["media"], "media")
    assert got["list"]["recordings"][0]["task_state"] == "done" and got["list"]["recordings"][0]["delivered_at"] and got["listOther"]["recordings"] == []
    within(got["captions"], real["captions"], "captions")
    assert got["captions"]["mode"] is None and got["captions"]["still"] is None and got["captionsOther"] == 404
    # the counts agree with the lists they count
    view = got["captions"]["view"]
    assert view["counts"] == {"words": len(view["words"]), "edited": 0, "estimated": 0, "timing_adjusted": 0, "unplaced": len(view["unplaced"]), "retakes": len(view["retakes"]),
                              "confirmed": sum(1 for r in view["retakes"] if r["confirmed"]), "beats": len(view["beats"]), "below_threshold": sum(1 for b in view["beats"] if b["below_threshold"]),
                              "animations": len(view["animations"])}
    assert sorted(w for c in view["chunks"] for w in c["words"]) == [w["index"] for w in view["words"]]
    within(got["catalogue"], real["catalogue"], "catalogue")
    assert [b["name"] for b in got["catalogue"]["blocks"] if not b["addable"]] == ["oh:cutaway"] and got["catalogue"]["blocks"][0]["why"] == "slot"
    for label, answer in got["refusals"].items():
        assert answer[:2] == [409, "refused"] and "not part of the demo" in answer[2], label


# --- text only -----------------------------------------------------------------------------------------------------------------------------

def test_the_new_modules_are_text_only_store_nothing_and_name_no_host():
    for name in ("views/lobby-videos.js", "views/lobby-video-model.js", "cards/deliver.js"):
        source = (JS / name).read_text(encoding="utf-8")
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|localStorage|sessionStorage|\.style\b|cssText|https?://", source), name
        assert not re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|\b(?:rgba?|hsla?)\(", source), name
        assert source.startswith("// "), f"{name} starts with a comment that says what it is"
    section = (JS / "views" / "lobby-videos.js").read_text(encoding="utf-8")
    assert "permissions.js" in section and re.search(r"\bmay\(", section) and "videoNew" in section and "mediaIn" in section


@needs_node
def test_node_check_passes_on_the_new_modules():
    for name in ("views/lobby-videos.js", "views/lobby-video-model.js", "cards/deliver.js", "api.js", "floor/cards.js"):
        done = subprocess.run([NODE, "--check", str(JS / name)], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"{name}: {done.stderr}"

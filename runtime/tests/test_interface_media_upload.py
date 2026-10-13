"""The page's way of taking a recording in (interface/js/floor/media-upload.js, the client function `uploadMedia` of js/api.js, its
progress transport, and the existing "Hand a file over" control that routes a video to it). Run under Node with a fake document and
a fake client: no browser, no service, no network. The media route itself is tested in test_media_route.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_media_upload.py
"""
from __future__ import annotations

import re

from test_interface_floor import INTERFACE, JS, needs_node, run_node  # noqa: F401

PURE = r"""
import { MEDIA_MAX_BYTES, NOT_ON_THE_MAC, MEDIA_OFF, asFileNote, isMediaFile, usesMedia, mediaRefusal, onLoopback, pickRefusal, storedLine, mediaHintText } from "@JS@/floor/media-upload.js";
import { fileRefusal, MAX_FILE_BYTES } from "@JS@/floor/hand-file.js";
const out = {};
const f = (name, size, type = "") => ({ name, size, type });
out.isMedia = [isMediaFile(f("a.mov", 10)), isMediaFile(f("b.MP4", 10)), isMediaFile(f("c.m4v", 10)), isMediaFile(f("d", 10, "video/quicktime")),
  isMediaFile(f("notes.txt", 10)), isMediaFile(f("big.bin", MAX_FILE_BYTES + 1)), isMediaFile(f("edge.bin", MAX_FILE_BYTES)), isMediaFile(null)];
out.uses = [usesMedia(f("a.mov", 10), true), usesMedia(f("a.mov", 10), false), usesMedia(f("big.bin", 10 * MAX_FILE_BYTES), true), asFileNote(f("a.mov", 10), false), asFileNote(f("a.mov", 10), true), asFileNote(f("a.txt", 10), false)];
out.loopback = [onLoopback("127.0.0.1"), onLoopback("localhost"), onLoopback("LOCALHOST"), onLoopback("[::1]"), onLoopback("192.168.1.20"), onLoopback("my-mac.local"), onLoopback(""), onLoopback(undefined)];
out.refusal = [mediaRefusal(f("a.mov", 544e6), { loopback: true }), mediaRefusal(f("a.mov", 544e6), { loopback: false }),
  mediaRefusal(f("a.mov", MEDIA_MAX_BYTES + 1), { loopback: true }), mediaRefusal(f("a.mov", 0), { loopback: true }),
  mediaRefusal(f("x".repeat(500) + ".mov", 10), { loopback: true }), mediaRefusal(f("a.mov", MEDIA_MAX_BYTES), { loopback: true })];
out.pick = [pickRefusal(f("notes.txt", MAX_FILE_BYTES + 0), fileRefusal, { loopback: false }), pickRefusal(f("a/b.txt", 10), fileRefusal, { loopback: false }),
  pickRefusal(f("a.mov", 10), fileRefusal, { loopback: true, may: false }), pickRefusal(f("a.mov", 10), fileRefusal, { loopback: true }), pickRefusal(f("a.mov", 10), fileRefusal, { loopback: false }),
  pickRefusal(f("big.bin", MAX_FILE_BYTES + 1), fileRefusal, { loopback: true }), pickRefusal(f("big.mov", MAX_FILE_BYTES + 1), fileRefusal, { loopback: true, may: false })];
out.hint = [mediaHintText(true), mediaHintText(false)];
out.stored = storedLine({ recording: "0123456789abcdef", bytes: 544 * 1024 * 1024, facts: { duration: 192.7 } });
out.words = [NOT_ON_THE_MAC, MEDIA_OFF];
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_video_or_a_file_over_the_hand_overs_limit_goes_to_the_media_route_and_only_on_the_mac(tmp_path):
    got = run_node(tmp_path, PURE)
    assert got["isMedia"] == [True, True, True, True, False, False, False, False], "only a video goes to the media route, whatever its size"
    assert got["uses"][:3] == [True, False, False] and got["uses"][3].startswith("It went as an ordinary file") and got["uses"][4:] == ["", ""]
    assert got["loopback"] == [True, True, True, True, False, False, False, False]
    assert got["refusal"][0] == "" and got["refusal"][1] == got["words"][0] and "1 GiB" in got["refusal"][2]
    assert got["refusal"][3] == "This file is empty." and got["refusal"][4] == "" and got["refusal"][5] == "", "a long file name is no reason to refuse: the service shortens a label"
    assert got["pick"][0] == "" and "letters, digits" in got["pick"][1], "a file that is not media keeps the hand-over's own rules, on any page"
    assert got["pick"][2] == "" and got["pick"][3] == "" and got["pick"][4] == got["words"][0], "with media-in off a small video keeps the hand-over's rules"
    assert got["pick"][5] == "A file handed to a task is at most 25 MiB." and got["pick"][6] == got["words"][1], "a large file that is not a video keeps the hand-over's message; a large video with the route off says why"
    assert "on the Mac" in got["hint"][0] and got["hint"][1] == got["words"][0]
    assert got["stored"] == "Recording stored: 0123456789abcdef (544.0 MiB, 192.7 s). It stays on this Mac until its post is done."


CLIENT = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";

setToken("t".repeat(40));
const seen = [];
class FakeRequest {
  constructor() { this.headers = {}; this.upload = {}; seen.push(this); }
  open(method, url) { this.method = method; this.url = url; }
  setRequestHeader(name, value) { this.headers[name] = value; }
  getResponseHeader(name) { return name.toLowerCase() === "content-type" ? "application/json; charset=utf-8" : null; }
  send(body) {
    this.body = body;
    if (this.reply.network) { queueMicrotask(() => this.onerror()); return; }
    queueMicrotask(() => {
      this.upload.onprogress({ lengthComputable: true, loaded: 5, total: 10 });
      this.upload.onprogress({ lengthComputable: false, loaded: 7, total: 0 });
      this.upload.onprogress({ lengthComputable: true, loaded: 10, total: 10 });
      this.status = this.reply.status;
      this.responseText = JSON.stringify(this.reply.body);
      this.onload();
    });
  }
  abort() { this.onabort(); }
}
globalThis.XMLHttpRequest = FakeRequest;
globalThis.fetch = () => { throw new Error("fetch must not be used for an upload"); };
const file = { name: "Clip 1 é.mov", size: 10, type: "video/quicktime" };
const progress = [];
FakeRequest.prototype.reply = { status: 200, body: { recording: "0123456789abcdef", kind: "recording", bytes: 10 } };
const done = await api.uploadMedia("0123456789ab", file, { recording: "fedcba9876543210", slot: "0123456789ab", onProgress: (sent, total) => progress.push([sent, total]) });
const request = seen[0];
const out = { done, progress, method: request.method, url: request.url, body: request.body === file, headers: request.headers };
FakeRequest.prototype.reply = { status: 413, body: { error: "too_large", message: "the body is larger" } };
try { await api.uploadMedia("0123456789ab", file); out.refused = null; } catch (e) { out.refused = [e.status, e.word, e.message]; }
FakeRequest.prototype.reply = { status: 507, body: {} };
try { await api.uploadMedia("0123456789ab", file); } catch (e) { out.noSpace = [e.status, e.word]; }
FakeRequest.prototype.reply = { network: true };
try { await api.uploadMedia("0123456789ab", file); } catch (e) { out.network = [e.status, e.word, e.message]; }
const controller = new AbortController();
const pending = api.uploadMedia("0123456789ab", file, { signal: controller.signal });
out.aborted = "pending";
controller.abort();
try { await pending; } catch (e) { out.aborted = e.name; }
out.list = typeof api.mediaList;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_client_streams_a_file_as_its_own_bytes_with_a_progress_report_and_the_headers_the_route_reads(tmp_path):
    got = run_node(tmp_path, CLIENT)
    assert got["done"]["recording"] == "0123456789abcdef" and got["method"] == "POST" and got["url"] == "/api/v1/projects/0123456789ab/media"
    assert got["body"] is True, "the body is the File itself, never base64 and never JSON"
    assert got["headers"]["Content-Type"] == "application/octet-stream" and got["headers"]["Authorization"].startswith("Bearer ")
    assert got["headers"]["X-Recording-Id"] == "fedcba9876543210" and got["headers"]["X-Slot-Id"] == "0123456789ab"
    assert got["headers"]["X-File-Name"] == "Clip%201%20%C3%A9.mov", "the name travels percent-encoded"
    assert "Content-Length" not in got["headers"], "the browser sets the length"
    assert got["progress"] == [[5, 10], [10, 10]], "only a computable progress is reported"
    assert got["refused"] == [413, "too_large", "the body is larger"] and got["noSpace"] == [507, "no_space"]
    assert got["aborted"] == "AbortError" and got["list"] == "function"
    assert got["network"] == [0, "network", "The upload was refused or the connection closed before the service answered."], "not 'could not be reached'"


def test_the_upload_transport_is_the_one_other_way_out_and_the_page_has_no_other_network_call():
    transport = (JS / "transport.js").read_text(encoding="utf-8")
    code = "\n".join(line for line in transport.splitlines() if not line.lstrip().startswith(("//", "*", "/*")))
    assert code.count("fetch(") == 1 and code.count("XMLHttpRequest") == 1 and "export function transportUpload(url, init, onProgress)" in code
    api = (JS / "api.js").read_text(encoding="utf-8")
    assert "XMLHttpRequest" not in api and "fetch(" not in api and len(re.findall(r"\btransport\(", api)) == 1
    demo = (INTERFACE / "demo" / "transport.js").read_text(encoding="utf-8")
    assert "export async function transportUpload" in demo and "XMLHttpRequest" not in demo


HAND = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";

globalThis.location = { hostname: "127.0.0.1" };
const calls = [];
let script = {};
let lastProgress = null;
const api = {
  handOver: async (...args) => { calls.push(["handOver", args[2]]); return { path: ".workbench-local/drop/5/notes.txt", bytes: 3 }; },
  uploadMedia: async (project, file, options) => {
    calls.push(["uploadMedia", project, file.name]);
    options.onProgress(50, 200);
    lastProgress = { value: find(tab.el, "progress.wb-media-progress").value, label: find(tab.el, ".wb-hand-result").textContent };
    options.onProgress(200, 200);
    lastProgress.after = find(tab.el, "progress.wb-media-progress").value;
    if (script.fail) throw Object.assign(new Error("the body is larger than this route takes"), { name: "ApiError", status: 413, word: "too_large" });
    return { recording: "0123456789abcdef", kind: "recording", bytes: 544 * 1024 * 1024, facts: { duration: 192.7 } };
  },
};
const tab = createAgentTab({ project: "p", agent: "engineering", api, refresh: () => {}, now: () => new Date() });
const P = "0123456789ab";
const agent = { name: "engineering", pack: "code", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 12, max_usd_per_day: 4, runs_today: 5, usd_today: 1.87, runs_without_cost: 0, queued: 0 };
const task = (id, state) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: "engineering" });
const snapshot = { projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks: [task(5, "failed")] }], pending: [] }, agents: [agent] } }, tasks: {}, loaded: true };
tab.update(fm.floor(snapshot, P, "engineering", {}));
const input = find(tab.el, "input.wb-file");
const out = { hint: find(tab.el, ".wb-hint").textContent, mediaHint: find(tab.el, ".wb-media-hint").textContent };
const choose = async (file) => { input.files = [file]; await input.listeners.change[0](); };
const unreadable = () => { throw new Error("a video must not be read whole into memory"); };

// a recording: held first (nothing is sent by choosing), then the button names what it does, and the upload reports its progress
await choose({ name: "reel.mov", size: 544 * 1024 * 1024, type: "video/quicktime", arrayBuffer: unreadable });
out.chosen = { calls: calls.length, name: find(tab.el, ".wb-hand-chosen").textContent, button: find(tab.el, "button.wb-hand-button").textContent };
find(tab.el, "button.wb-hand-button").click();
await settle();
out.sent = { calls: calls.map((c) => c.join(" ")), progress: lastProgress, result: find(tab.el, ".wb-hand-result").textContent };

// a file over 25 MiB that is not a video keeps the hand-over and its message
calls.length = 0;
await choose({ name: "big.bin", size: 30 * 1024 * 1024, type: "", arrayBuffer: unreadable });
out.big = { text: find(tab.el, ".wb-hand-result").textContent, held: all(tab.el, "button.wb-hand-button").length, calls: calls.length };

// a small ordinary file keeps the base64 hand-over
calls.length = 0;
await choose({ name: "notes.txt", size: 3, type: "text/plain", arrayBuffer: async () => new Uint8Array([97, 98, 99]).buffer });
out.small = { button: find(tab.el, "button.wb-hand-button").textContent };
find(tab.el, "button.wb-hand-button").click();
await settle();
out.smallCalls = calls.map((c) => c.join(" "));

// the project turns media-in off: a small video is handed over as an ordinary file, and the page says why; a large one is refused
const noMedia = createAgentTab({ project: "p", agent: "engineering", api, refresh: () => {}, now: () => new Date(), can: (op) => op !== "media-in" });
noMedia.update(fm.floor(snapshot, P, "engineering", {}));
calls.length = 0;
const offInput = find(noMedia.el, "input.wb-file");
offInput.files = [{ name: "short.mp4", size: 3, type: "video/mp4", arrayBuffer: async () => new Uint8Array([97, 98, 99]).buffer }];
await offInput.listeners.change[0]();
out.off = { button: find(noMedia.el, "button.wb-hand-button").textContent };
find(noMedia.el, "button.wb-hand-button").click();
await settle();
out.off.calls = calls.map((c) => c.join(" "));
out.off.text = find(noMedia.el, ".wb-hand-result").textContent;
offInput.files = [{ name: "long.mov", size: 40 * 1024 * 1024, type: "video/quicktime", arrayBuffer: unreadable }];
await offInput.listeners.change[0]();
out.off.large = find(noMedia.el, ".wb-hand-result").textContent;

// a failure leaves the file held and says why
calls.length = 0;
script = { fail: true };
await choose({ name: "reel.mov", size: 100, type: "video/quicktime", arrayBuffer: unreadable });
find(tab.el, "button.wb-hand-button").click();
await settle();
out.failed = { text: find(tab.el, ".wb-hand-result").textContent, held: all(tab.el, "button.wb-hand-button").length };

// a page that is not on the Mac: the video is refused where it is chosen and nothing is sent
globalThis.location = { hostname: "192.168.1.20" };
calls.length = 0;
await choose({ name: "reel.mov", size: 100, type: "video/quicktime", arrayBuffer: unreadable });
out.phone = { text: find(tab.el, ".wb-hand-result").textContent, held: all(tab.el, "button.wb-hand-button").length, calls: calls.length };
// above the size limit, on the Mac
globalThis.location = { hostname: "localhost" };
await choose({ name: "huge.mov", size: 2 * 1024 * 1024 * 1024, type: "video/quicktime", arrayBuffer: unreadable });
out.huge = { text: find(tab.el, ".wb-hand-result").textContent, calls: calls.length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_hand_a_file_over_control_sends_a_video_by_the_media_route_with_progress_and_other_files_as_before(tmp_path):
    got = run_node(tmp_path, HAND)
    assert got["hint"] == "To task #5. At most 25 MiB.", "the hand-over's own hint is unchanged"
    assert "on the Mac" in got["mediaHint"]
    assert got["chosen"] == {"calls": 0, "name": "reel.mov", "button": "Upload the recording"}, "choosing sends nothing; the button says what it does"
    assert got["sent"]["calls"] == ["uploadMedia p reel.mov"], "a video goes by the media route and handOver is not called"
    assert got["sent"]["progress"]["value"] == 25 and got["sent"]["progress"]["after"] == 100 and "Uploading" in got["sent"]["progress"]["label"]
    assert got["sent"]["result"].startswith("Recording stored: 0123456789abcdef (544.0 MiB, 192.7 s)")
    assert got["big"] == {"text": "A file handed to a task is at most 25 MiB.", "held": 0, "calls": 0}
    assert got["off"]["button"] == "Hand over to task #5" and got["off"]["calls"] == ["handOver short.mp4"]
    assert got["off"]["text"].endswith("It went as an ordinary file because attaching a video is turned off for the page (media-in).") and got["off"]["large"] == "Attaching a video is turned off for the page (media-in). Use the terminal: media-in."
    assert got["small"]["button"] == "Hand over to task #5" and got["smallCalls"] == ["handOver notes.txt"]
    assert got["failed"]["text"] == "the body is larger than this route takes" and got["failed"]["held"] == 1
    assert "on the Mac" in got["phone"]["text"] and got["phone"]["held"] == 0 and got["phone"]["calls"] == 0
    assert "at most 1 GiB" in got["huge"]["text"] and got["huge"]["calls"] == 0


CARD = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";

globalThis.location = { hostname: "127.0.0.1" };
const calls = [];
const client = {
  answer: async () => ({}), release: async () => ({}),
  handOver: async (...args) => { calls.push(["handOver", args[2]]); return { path: "docs/inputs/reel.mov", bytes: 3 }; },
  uploadMedia: async () => { calls.push(["uploadMedia"]); return {}; },
};
const env = { project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client, requestIds: new Set([6]), links: { floor: () => "#", lobby: () => "#/p/p/lobby", open: () => "#" }, reread: async () => null, changed() {}, gone() {}, task: async (id) => ({ task: { id }, runs: [], pending: [], drop: { web: false, takes: true, line: "" } }) };
const review = { id: 42, kind: "review", title: "R", body: "b", payload: { returned: [], kept: [] }, payload_sha256: null, status: "open", actions: ["released", "answered"], agent: "brand", task_id: 5, run_id: 4, created_at: "2026-10-09T09:00:00Z" };
const card = createCard(review, env);
await settle();
const input = () => find(card.el, "input.wb-file");
const out = { hint: find(card.el, ".wb-card-hand .wb-hint").textContent, media: all(card.el, ".wb-media-hint").length };
input().files = [{ name: "reel.mov", size: 3, type: "video/quicktime", arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer }];
input().listeners.change.forEach((fn) => fn());
await settle();
out.button = find(card.el, "button.wb-hand-button").textContent;
find(card.el, "button.wb-hand-button").click();
await settle();
out.calls = calls;
out.progress = all(card.el, "progress").length;
input().files = [{ name: "reel2.mov", size: 40 * 1024 * 1024, type: "video/quicktime", arrayBuffer: async () => { throw new Error("must not be read"); } }];
input().listeners.change.forEach((fn) => fn());
await settle();
out.large = { text: find(card.el, ".wb-card-hand .wb-notice-card").textContent, button: all(card.el, "button.wb-hand-button").length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_review_card_routes_no_video_to_the_media_route_a_recording_is_not_a_tasks_output(tmp_path):
    got = run_node(tmp_path, CARD)
    assert got["hint"] == "To task #5. At most 25 MiB." and got["media"] == 0, "the card offers the hand-over only"
    assert got["button"] == "Hand over to task #5", "no 'Upload the recording' button that names no task"
    assert got["calls"] == [["handOver", "reel.mov"]] and got["progress"] == 0
    assert got["large"] == {"text": "A file handed to a task is at most 25 MiB.", "button": 0}

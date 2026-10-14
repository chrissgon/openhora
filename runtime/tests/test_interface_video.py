"""The page's rendered-video card (interface/js/floor/video-card.js, the client functions of js/api.js that fetch and write it, and its row in
the Tasks tab): the video played from a blob URL fetched with the bearer header, its progress, the hashes and the caption it shows, the
approval that sends exactly the two hashes on the card, the stale approval, Send back with a comment, the download, the page that is not the Mac,
the policy that turns the writes off, and the blob lifecycle. Run under Node with a fake document and a fake client: no browser, no service, no
network. The service half is tested in test_video_route.py and test_video_ops.py. The layout at a phone's width is read from the stylesheet.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_video.py
"""
from __future__ import annotations

import re

import standin_tree as st
from interface_css import css_file, interface_css
from test_interface_floor import INTERFACE, JS, needs_node, run_node
from test_interface_phone_sheet import media_blocks

CARD = JS / "floor" / "video-card.js"

PURE = r"""
import { shortHash, factsLine, stateOf, phaseOf, staleLine, ON_THE_MAC } from "@JS@/floor/video-card.js";
const out = {};
out.short = [shortHash("ab".repeat(32)), shortHash(null), shortHash("abc")];
out.facts = [factsLine({ duration: 41.5, width: 1080, height: 1920, bytes: 14.2 * 1024 * 1024 }), factsLine({ duration: null, width: null, height: null, bytes: 2048 }), factsLine(null)];
const R = { sha256: "a" };
out.state = [stateOf({ approval: { state: "approved" }, render: R })[0], stateOf({ approval: { state: "stale" }, render: R })[0], stateOf({ approval: null, sent_back: { comment: "x" }, render: R })[0], stateOf({ approval: null, render: R })[0], stateOf({ approval: null, render: null })[0], stateOf(null)[0]];
const steps = (extra) => ({ steps: { transcribe: "done", review: "done", base: "done", check: "done", render: "done", cover: "done", approval: "waiting", ...extra }, failure: null });
out.stoppedPhases = [phaseOf({ render: null }, { ...steps({ render: "pending", cover: "pending" }), active: false }), phaseOf({ render: null }, { ...steps({ render: "pending", cover: "pending" }), active: true }), phaseOf({ render: null }, steps({ render: "pending", cover: "pending" })),
  phaseOf({ render: null }, { ...steps({ render: "failed", cover: "pending" }), failure: null, active: true }), phaseOf({ render: R }, { ...steps({}), active: false })];
out.phase = [phaseOf({ render: R }, null), phaseOf({ render: null }, null), phaseOf({ render: null }, steps({ render: "pending", cover: "pending" })), phaseOf({ render: R }, steps({})), phaseOf({ render: null }, steps({ review: "waiting", render: "pending" })),
  phaseOf({ render: R }, { ...steps({}), failure: { step: "cover", code: "cover_missing" } }), phaseOf({ render: R }, steps({ cover: "pending" }))];
out.pipelineState = [stateOf({ approval: { state: "approved" }, render: R }, steps({ render: "pending" }))[0], stateOf({ approval: null, render: null }, { ...steps({}), failure: { step: "render", code: "x" } })[0]];
out.stale = [staleLine({ approved_at: "2026-10-14T10:00:00Z", reasons: ["render_changed"] }), staleLine({ approved_at: "d", reasons: ["render_changed", "caption_changed"] }), staleLine({ approved_at: "d", reasons: [] })];
out.mac = ON_THE_MAC;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_pure_words_of_the_card(tmp_path):
    got = run_node(tmp_path, PURE)
    assert got["short"] == ["abababababab", "", "abc"]
    assert got["facts"][0] == "41.5 s, 1080 × 1920, 14.2 MB" and got["facts"][1].endswith("2.0 KB") and got["facts"][2] == ""
    assert got["state"] == ["Approved", "Approval no longer holds", "Sent back", "Waiting for your approval", "No video yet", "No video yet"], "waiting for approval only when a render exists"
    assert got["phase"] == ["ready", "none", "making", "ready", "none", "stopped", "making"], "the pipeline decides: making while render or cover is not done after the review, stopped on a failure"
    assert got["stoppedPhases"] == ["stopped", "making", "making", "stopped", "ready"], "no process running it (active false) or a failed step is stopped; a pipeline that does not say is taken as running; a finished one is ready"
    assert got["pipelineState"] == ["Making the video", "Stopped"], "making wins over an older approval; a failure wins over everything"
    assert got["stale"][0] == "You approved this post on 2026-10-14T10:00:00Z, but the video was rendered again since. Watch and read it again, then approve again."
    assert "the video was rendered again and the caption was edited" in got["stale"][1] and "it changed" in got["stale"][2]
    assert got["mac"].startswith("Watch and approve on the Mac")


CARD_RUN = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createVideoCard } from "@JS@/floor/video-card.js";

const SHA = "a".repeat(64), SHA2 = "b".repeat(64), CAP = "c".repeat(64);
const card = (extra = {}) => ({
  recording: "0123456789abcdef", status: "open", platforms: ["instagram"], platform: "instagram",
  render: { sha256: SHA, bytes: 3 * 1024 * 1024, duration: 41.5, width: 1080, height: 1920, fps: 30, codec: "h264", name: "render-aaaaaaaaaaaa.mp4", source: "result" },
  cover: { sha256: "d".repeat(64), bytes: 100, offset_ms: 1200 },
  caption: { text: "Three habits.\n#northwind <b>not markup</b>", sha256: CAP, chars: 40, post_file: "docs/marketing/content/x.md" },
  approval: null, sent_back: null, can_download: false, download_name: null, problems: [], ...extra,
});
const approved = (sha = SHA, extra = {}) => card({ render: { ...card().render, sha256: sha }, approval: { state: "approved", reasons: [], approved_at: "2026-10-14T10:00:00Z", approved_via: "page", video_sha256: sha, caption_sha256: CAP, platform: "instagram" }, can_download: true, download_name: "short-video-instagram-aaaaaaaaaaaa.mp4", ...extra });

let current = card();
const calls = [];
const made = [], revoked = [];
const objects = { create: (blob) => { made.push(blob.size); return `blob:test/${made.length}`; }, revoke: (url) => revoked.push(url) };
const saved = [];
let gate = null;          // a promise the next videoRaw waits for
let fail = null;
const api = {
  videoCard: async (p, rid, options) => { calls.push(["videoCard", p, rid, options.platform]); return current; },
  videoCover: async (p, rid, sha) => { calls.push(["videoCover", sha]); return new Blob([new Uint8Array(10)], { type: "image/png" }); },
  videoRaw: async (p, rid, sha, options) => {
    calls.push(["videoRaw", sha]);
    options.onBytes(1024 * 1024, 3 * 1024 * 1024);
    out.midProgress = { text: text(find(root, ".wb-video-loading")), value: find(root, "progress.wb-video-progress").value };
    if (gate) await gate;
    return new Blob([new Uint8Array(32)], { type: "video/mp4" });
  },
  videoApprove: async (p, rid, body) => { calls.push(["videoApprove", body]); if (fail) throw fail; current = approved(body.videoSha256); return current; },
  videoSendBack: async (p, rid, comment, options) => { calls.push(["videoSendBack", comment, options.platform]); current = card({ sent_back: { comment, at: "2026-10-14T11:00:00Z", render_sha256: SHA } }); return current; },
  videoDownload: async (p, rid, platform) => { calls.push(["videoDownload", platform]); return new Blob([new Uint8Array(32)], { type: "video/mp4" }); },
};
const text = (n) => n.textContent;
const off = (n) => (n ? "disabled" in n.attrs : null);
const out = {};
let root;
const make = (extra = {}) => createVideoCard({ project: "0123456789ab", recording: "0123456789abcdef", api, objects, save: (blob, name) => saved.push([blob.size, name]), now: () => new Date("2026-10-14T12:00:00Z"), loopback: true, ...extra });

// --- on the Mac: the video loads with a progress report, then plays from a blob URL; nothing is sent by looking
let view = make();
root = view.el;
const loading = view.load();
await settle();
out.afterLoad = {
  video: all(root, "video").length, src: find(root, "video") ? find(root, "video").attrs.src : null, poster: find(root, "video") ? find(root, "video").attrs.poster : null,
  controls: find(root, "video") && "controls" in find(root, "video").attrs, caption: text(find(root, "[data-key=caption]")), videoHash: text(find(root, "[data-key=hash-video]")), captionHash: text(find(root, "[data-key=hash-caption]")),
  facts: text(find(root, ".wb-video-facts")), approve: off(find(root, "[data-key=approve]")) === null ? null : !off(find(root, "[data-key=approve]")), chip: text(find(root, ".pui-badge")),
  calls: calls.map((c) => c[0]), made: made.length,
};
out.wrongHtml = text(find(root, "[data-key=caption]")).includes("<b>not markup</b>") && all(root, "b").length === 0;

// --- Approve sends the two hashes the card shows, the platform, and nothing else
find(root, "[data-key=approve]").click();
await settle();
const sent = calls.find((c) => c[0] === "videoApprove");
out.sent = sent && sent[1];
out.afterApprove = { chip: text(find(root, ".pui-badge")), line: text(find(root, ".wb-video-approved")), approveGone: find(root, "[data-key=approve]") === null, download: find(root, "[data-key=download]") ? text(find(root, "[data-key=download]")) : null };

// --- Download saves the exact file under the plain name the service gave
find(root, "[data-key=download]").click();
await settle();
out.download = { calls: calls.filter((c) => c[0] === "videoDownload"), saved: saved.map((x) => [...x]), message: text(root).includes("nothing was published") };

// --- a re-render makes the approval stale, the card says so, fetches the new render and revokes the old URLs
current = card({ render: { ...card().render, sha256: SHA2 }, approval: { state: "stale", reasons: ["render_changed"], approved_at: "2026-10-14T10:00:00Z", video_sha256: SHA, caption_sha256: CAP, platform: "instagram" } });
const revokedBefore = revoked.length;
await view.load({ quiet: true });
await settle();
out.stale = { chip: text(find(root, ".pui-badge")), notice: text(find(root, ".wb-notice-card")), approve: off(find(root, "[data-key=approve]")) === null ? null : !off(find(root, "[data-key=approve]")), download: find(root, "[data-key=download]") === null,
  rawFor: calls.filter((c) => c[0] === "videoRaw").map((c) => c[1]), revoked: revoked.length - revokedBefore };

// --- Send back needs a comment, sends exactly it, and leaves the post waiting
find(root, "[data-key=send-back]").click();
await settle();
out.emptyComment = { error: text(find(root, ".notice")).includes("comment is needed"), sends: calls.filter((c) => c[0] === "videoSendBack").length };
const area = find(root, "textarea");
area.value = "  Trim the second beat.  ";
area.listeners.input.forEach((fn) => fn());
find(root, "[data-key=send-back]").click();
await settle();
out.sendBack = { calls: calls.filter((c) => c[0] === "videoSendBack"), note: text(find(root, "[data-key=sent-back]")), chip: text(find(root, ".pui-badge")) };

// --- closing revokes every blob URL that was made
view.close();
out.closed = { made: made.length, revoked: revoked.length, all: made.every((_, i) => revoked.includes(`blob:test/${i + 1}`)) };

// --- a refusal of the approval is shown as text and the card stays
calls.length = 0; made.length = 0; revoked.length = 0; saved.length = 0;
current = card();
fail = Object.assign(new Error("the render changed since you watched it"), { name: "ApiError", status: 409, word: "refused" });
view = make(); root = view.el;
await view.load(); await settle();
find(root, "[data-key=approve]").click();
await settle();
out.refused = { text: text(find(root, ".notice")), chip: text(find(root, ".pui-badge")), approve: find(root, "[data-key=approve]") !== null };
fail = null;
view.close();

// --- the Approve button waits for the video: it is disabled while the video loads and a failed video cannot be approved
calls.length = 0; made.length = 0; revoked.length = 0;
let release; gate = new Promise((r) => { release = r; });
view = make(); root = view.el;
view.load(); await settle();
out.loadingState = { disabled: off(find(root, "[data-key=approve]")), hint: text(find(root, ".wb-video-approval")).includes("once the video has loaded"), video: all(root, "video").length };
find(root, "[data-key=approve]").click();
await settle();
out.loadingClick = calls.filter((c) => c[0] === "videoApprove").length;
release(); gate = null; await settle();
out.afterGate = { disabled: off(find(root, "[data-key=approve]")), video: all(root, "video").length };
view.close();

// --- a page that is not on the Mac: no video is fetched, the hashes and the caption show, nothing can be approved or sent back
calls.length = 0; made.length = 0; current = card();
view = make({ loopback: false }); root = view.el;
await view.load(); await settle();
out.lan = { calls: calls.map((c) => c[0]), video: all(root, "video").length, approve: find(root, "[data-key=approve]"), sendBack: find(root, "[data-key=send-back]"), notice: text(find(root, ".wb-notice-card")),
  caption: text(find(root, "[data-key=caption]")).length > 0, hash: text(find(root, "[data-key=hash-video]")) };
view.close();

// --- the project turns the writes off for the page: no button, and the line says which words
calls.length = 0; current = card();
view = make({ can: (op) => op !== "video-approve" && op !== "video-send-back" }); root = view.el;
await view.load(); await settle();
out.policy = { approve: find(root, "[data-key=approve]"), sendBack: find(root, "[data-key=send-back]"), line: text(find(root, "[data-key=withheld]")), video: all(root, "video").length };
view.close();

// --- no render yet; the problems of the card; several platforms get a picker that reads the other card
calls.length = 0; current = card({ render: null, cover: null, problems: ["there is no render yet"] });
view = make(); root = view.el;
await view.load(); await settle();
out.empty = { text: text(root).includes("There is no render yet."), approve: find(root, "[data-key=approve]") ? off(find(root, "[data-key=approve]")) : "none", raw: calls.filter((c) => c[0] === "videoRaw").length };
view.close();
current = card({ platforms: ["instagram", "tiktok"], platform: null, render: card().render });
view = make(); root = view.el; calls.length = 0;
await view.load(); await settle();
out.picker = { buttons: all(root, ".wb-video-platforms button").map((b) => text(b)) };

// --- a store change during playback: the same video node and the same comment box, with the typed text and the focus kept
calls.length = 0; made.length = 0; revoked.length = 0;
current = card();
view = make(); root = view.el;
await view.load(); await settle();
const player = find(root, "video");
const comment = find(root, "textarea");
comment.value = "Slow the second beat"; comment.listeners.input.forEach((fn) => fn()); comment.focus();
const rawBefore = calls.filter((c) => c[0] === "videoRaw").length;
current = card({ problems: [] });                                    // the store changed somewhere else: the same card comes back
await view.load({ quiet: true }); await settle();
out.kept = { sameVideo: find(root, "video") === player, sameComment: find(root, "textarea") === comment, value: comment.value, focused: comment.focused, active: globalThis.document.activeElement === comment,
  refetched: calls.filter((c) => c[0] === "videoRaw").length - rawBefore, revoked: revoked.length };
current = approved();                                                // the approval changed: the approval part is drawn again, the video is not
await view.load({ quiet: true }); await settle();
out.keptAfterApproval = { sameVideo: find(root, "video") === player, sameComment: find(root, "textarea") === comment, chip: text(find(root, ".pui-badge")), download: find(root, "[data-key=download]") !== null };
current = card({ render: { ...card().render, sha256: SHA2 } });      // another render: a new video
await view.load({ quiet: true }); await settle();
out.newRender = { sameVideo: find(root, "video") === player, videos: all(root, "video").length, src: find(root, "video").attrs.src, sameComment: find(root, "textarea") === comment };
view.close();

// --- Download saves the blob already held when it is the approved file's, and fetches the file when it is not
calls.length = 0; saved.length = 0; made.length = 0; revoked.length = 0;
current = approved();
view = make(); root = view.el;
await view.load(); await settle();
find(root, "[data-key=download]").click(); await settle();
out.heldDownload = { fetched: calls.filter((c) => c[0] === "videoDownload").length, saved: saved.map((x) => [...x]) };
view.close();
calls.length = 0; saved.length = 0;
current = approved(SHA, { approval: { state: "approved", reasons: [], approved_at: "2026-10-14T10:00:00Z", approved_via: "page", video_sha256: SHA2, caption_sha256: CAP, platform: "instagram" } });
view = make(); root = view.el;
await view.load(); await settle();
find(root, "[data-key=download]").click(); await settle();
out.otherDownload = { fetched: calls.filter((c) => c[0] === "videoDownload").length, saved: saved.map((x) => [...x]) };
view.close();

// --- the video on screen must be the render the card names before Approve sends anything
calls.length = 0;
current = card();
view = make(); root = view.el;
await view.load(); await settle();
let free; gate = new Promise((r) => { free = r; });
current = card({ render: { ...card().render, sha256: SHA2 } });      // another render appears: its video is loading, the old one is not its video
view.load({ quiet: true }); await settle();
out.otherRender = { disabled: off(find(root, "[data-key=approve]")), video: all(root, "video").length };
find(root, "[data-key=approve]").click(); await settle();
out.otherRenderClick = calls.filter((c) => c[0] === "videoApprove").length;
free(); gate = null; await settle();
out.otherRenderReady = off(find(root, "[data-key=approve]"));
view.close();

// --- a post that was sent back takes no Approve until it changes
calls.length = 0;
current = card({ sent_back: { comment: "Too fast.", at: "2026-10-14T11:00:00Z", render_sha256: SHA, blocks_approval: true } });
view = make(); root = view.el;
await view.load(); await settle();
out.heldBack = { approve: find(root, "[data-key=approve]"), note: text(find(root, "[data-key=held-back]")), note2: text(find(root, "[data-key=sent-back]")) };
current = card({ sent_back: { comment: "Too fast.", at: "2026-10-14T11:00:00Z", render_sha256: SHA, blocks_approval: false } });
await view.load({ quiet: true }); await settle();
out.liftedBack = { approve: find(root, "[data-key=approve]") !== null, note: find(root, "[data-key=held-back]") };
view.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_store_change_during_playback_keeps_the_video_node_and_the_comment_box(tmp_path):
    got = run_node(tmp_path, CARD_RUN)
    kept = got["kept"]
    assert kept == {"sameVideo": True, "sameComment": True, "value": "Slow the second beat", "focused": True, "active": True, "refetched": 0, "revoked": 0}, \
        "a read that changed nothing draws nothing: the playback position and the typed comment stay"
    assert got["keptAfterApproval"]["sameVideo"] is True and got["keptAfterApproval"]["sameComment"] is True, "an approval draws its own part only"
    assert got["keptAfterApproval"]["chip"] == "Approved" and got["keptAfterApproval"]["download"] is True
    assert got["newRender"]["sameVideo"] is False and got["newRender"]["videos"] == 1 and got["newRender"]["sameComment"] is True, "another render is another video; the comment stays"


@needs_node
def test_download_saves_the_held_bytes_of_the_approved_file_and_fetches_it_otherwise(tmp_path):
    got = run_node(tmp_path, CARD_RUN)
    assert got["heldDownload"] == {"fetched": 0, "saved": [[32, "short-video-instagram-aaaaaaaaaaaa.mp4"]]}
    assert got["otherDownload"] == {"fetched": 1, "saved": [[32, "short-video-instagram-aaaaaaaaaaaa.mp4"]]}


@needs_node
def test_approve_waits_for_the_video_of_the_render_the_card_names_and_a_sent_back_post_takes_none(tmp_path):
    got = run_node(tmp_path, CARD_RUN)
    assert got["otherRender"] == {"disabled": True, "video": 0} and got["otherRenderClick"] == 0 and got["otherRenderReady"] is False
    assert got["heldBack"]["approve"] is None and "sent back for review" in got["heldBack"]["note"] and "Too fast." in got["heldBack"]["note2"]
    assert got["liftedBack"] == {"approve": True, "note": None}


@needs_node
def test_the_card_plays_a_blob_approves_the_two_hashes_it_shows_and_downloads_the_approved_file(tmp_path):
    got = run_node(tmp_path, CARD_RUN)
    after = got["afterLoad"]
    assert after["video"] == 1 and after["src"] == "blob:test/2" and after["poster"] == "blob:test/1" and after["controls"] is True
    assert after["calls"] == ["videoCard", "videoCover", "videoRaw"] and after["made"] == 2
    assert after["caption"] == "Three habits.\n#northwind <b>not markup</b>" and got["wrongHtml"] is True, "the caption is text, never markup"
    assert after["videoHash"] == "a" * 64 and after["captionHash"] == "c" * 64
    assert "41.5 s" in after["facts"] and "1080" in after["facts"] and "3" in after["facts"] and after["approve"] is True and after["chip"] == "Waiting for your approval"
    assert got["midProgress"]["text"].startswith("Loading the video: 1") and got["midProgress"]["value"] == 33
    assert got["sent"] == {"videoSha256": "a" * 64, "captionSha256": "c" * 64, "platform": "instagram"}, "approve sends the two hashes the card shows, and nothing else"
    assert got["afterApprove"]["chip"] == "Approved" and "sha256 aaaaaaaaaaaa" in got["afterApprove"]["line"] and "sha256 cccccccccccc" in got["afterApprove"]["line"]
    assert got["afterApprove"]["approveGone"] is True and got["afterApprove"]["download"] == "Download short-video-instagram-aaaaaaaaaaaa.mp4"
    assert got["download"]["calls"] == [] and got["download"]["saved"] == [[32, "short-video-instagram-aaaaaaaaaaaa.mp4"]] and got["download"]["message"] is True
    stale = got["stale"]
    assert stale["chip"] == "Approval no longer holds" and "rendered again" in stale["notice"] and stale["approve"] is True and stale["download"] is True
    assert stale["rawFor"] == ["a" * 64, "b" * 64] and stale["revoked"] >= 2, "a new render is fetched and the old blob URLs are revoked"
    assert got["emptyComment"] == {"error": True, "sends": 0}, "sending back without a comment sends nothing"
    assert got["sendBack"]["calls"] == [["videoSendBack", "Trim the second beat.", "instagram"]]
    assert "Trim the second beat." in got["sendBack"]["note"] and got["sendBack"]["chip"] == "Sent back"
    assert got["closed"]["all"] is True and got["closed"]["revoked"] >= got["closed"]["made"]
    assert "render changed" in got["refused"]["text"] and got["refused"]["chip"] == "Waiting for your approval" and got["refused"]["approve"] is True


@needs_node
def test_the_approve_button_waits_for_the_video_and_a_page_that_is_not_the_mac_can_neither_watch_nor_approve(tmp_path):
    got = run_node(tmp_path, CARD_RUN)
    assert got["loadingState"] == {"disabled": True, "hint": True, "video": 0} and got["loadingClick"] == 0
    assert got["afterGate"] == {"disabled": False, "video": 1}
    lan = got["lan"]
    assert lan["calls"] == ["videoCard"] and lan["video"] == 0 and lan["approve"] is None and lan["sendBack"] is None
    assert "Watch and approve on the Mac" in lan["notice"] and lan["caption"] is True and lan["hash"] == "a" * 64
    assert got["policy"]["approve"] is None and got["policy"]["sendBack"] is None and got["policy"]["video"] == 1
    assert got["policy"]["line"] == "Turned off for the page: video-approve, video-send-back. Use the terminal."
    assert got["empty"]["text"] is True and got["empty"]["raw"] == 0
    assert got["picker"]["buttons"] == ["instagram", "tiktok"]


# --- the client functions ------------------------------------------------------------------------------------------------------------------

CLIENT = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";
setToken("t".repeat(40));
const P = "0123456789ab", R = "0123456789abcdef", SHA = "a".repeat(64);
const seen = [];
let reply;
globalThis.fetch = async (url, init) => { seen.push({ url, init }); return reply(); };
const bytes = (chunks, type = "video/mp4") => ({
  ok: true, status: 200, headers: { get: (n) => ({ "Content-Length": String(chunks.reduce((a, c) => a + c.length, 0)), "Content-Type": type })[n] || null },
  body: { getReader() { let i = 0; return { read: async () => (i < chunks.length ? { done: false, value: chunks[i++] } : { done: true }) }; } },
  blob: async () => new Blob(chunks, { type }), json: async () => { throw new Error("not json"); },
});
const out = {};
reply = () => bytes([new Uint8Array(5), new Uint8Array(7)]);
const progress = [];
const blob = await api.videoRaw(P, R, SHA, { onBytes: (a, b) => progress.push([a, b]) });
const first = seen[0];
out.raw = { url: first.url, method: first.init.method, accept: first.init.headers.Accept, auth: first.init.headers.Authorization.startsWith("Bearer "), size: blob.size, type: blob.type, progress, cred: first.init.credentials };
reply = () => bytes([new Uint8Array(4)], "image/png");
const cover = await api.videoCover(P, R, SHA);
out.cover = { url: seen[1].url, type: cover.type, accept: seen[1].init.headers.Accept };
reply = () => ({ ok: false, status: 409, json: async () => ({ error: "refused", message: "nothing is approved for download: approve this video and caption first" }) });
try { await api.videoDownload(P, R, "instagram"); out.refused = null; } catch (e) { out.refused = [e.status, e.word, e.message]; }
out.downloadUrl = seen[2].url;
reply = () => ({ ok: true, status: 200, json: async () => ({ ok: 1 }) });
await api.videoApprove(P, R, { videoSha256: SHA, captionSha256: "c".repeat(64), platform: "instagram" });
out.approve = { url: seen[3].url, method: seen[3].init.method, body: JSON.parse(seen[3].init.body), type: seen[3].init.headers["Content-Type"] };
await api.videoSendBack(P, R, "Trim it.", { platform: "instagram" });
out.sendBack = { url: seen[4].url, body: JSON.parse(seen[4].init.body) };
await api.videoCard(P, R, { platform: "instagram" });
out.card = { url: seen[5].url, method: seen[5].init.method };
await api.videoCard(P, R);
out.cardNoPlatform = seen[6].url;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_client_fetches_the_bytes_with_the_bearer_header_and_a_progress_report_and_writes_json(tmp_path):
    got = run_node(tmp_path, CLIENT)
    base = "/api/v1/projects/0123456789ab/video/0123456789abcdef"
    assert got["raw"] == {"url": f"{base}/render/{'a' * 64}", "method": "GET", "accept": "video/mp4", "auth": True, "size": 12, "type": "video/mp4",
                          "progress": [[5, 12], [12, 12]], "cred": "omit"}
    assert got["cover"] == {"url": f"{base}/cover/{'a' * 64}", "type": "image/png", "accept": "image/*"}
    assert got["refused"][:2] == [409, "refused"] and "approve this video" in got["refused"][2] and got["downloadUrl"] == f"{base}/download/instagram"
    assert got["approve"] == {"url": f"{base}/approve", "method": "POST", "body": {"video_sha256": "a" * 64, "caption_sha256": "c" * 64, "platform": "instagram"}, "type": "application/json"}
    assert got["sendBack"] == {"url": f"{base}/send-back", "body": {"comment": "Trim it.", "platform": "instagram"}}
    assert got["card"] == {"url": f"{base}?platform=instagram", "method": "GET"} and got["cardNoPlatform"] == base


# --- the row in the Tasks tab --------------------------------------------------------------------------------------------------------------

TAB_RUN = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createTasksTab } from "@JS@/floor/tasks-tab.js";

const P = "0123456789ab", R = "fedcba9876543210";
const NOW = new Date("2026-10-14T12:00:00Z");
const calls = [];
globalThis.fetch = async (url, init) => { calls.push(`${init.method} ${url}`); return { ok: false, status: 404, json: async () => ({ error: "not_found", message: "no" }) }; };
const api = {
  videoCard: async (p, rid) => { calls.push(`card ${rid}`); return { recording: rid, status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null, caption: null, approval: null, sent_back: null, can_download: false, download_name: null, problems: [] }; },
};
const task = (id, key, state = "waiting") => ({ id, key, title: `Task ${id}`, skill: null, state, note: null, agent: "engineering", requestId: 1 });
const env = { project: P, now: () => NOW, refresh: () => {}, api, links: { request: () => "#r", inbox: () => "#i", open: () => "#o" } };
const tab = createTasksTab(env);
const tasks = [task(1, `media:${R}`), task(2, "media:not-an-id"), task(3, "plain-key")];
const data = (extra = {}) => ({ tasks, requests: [{ id: 1, title: "R", state: "ready" }], pending: [], loading: false, reload: 1, ...extra });
tab.update(data());
await settle();
const out = {};
const toggle = (id) => find(tab.el, `[data-key=toggle-${id}]`);
out.closed = { cards: all(tab.el, "section.wb-video").length, reads: calls.filter((c) => c.startsWith("card")).length };
toggle(2).click(); await settle(); toggle(3).click(); await settle();
out.plain = { cards: all(tab.el, "section.wb-video").length, reads: calls.filter((c) => c.startsWith("card")).length };
toggle(1).click(); await settle();
out.opened = { cards: all(tab.el, "section.wb-video").length, reads: calls.filter((c) => c.startsWith("card")), text: find(tab.el, "section.wb-video").textContent.includes("There is no render yet.") };
tab.update(data({ reload: 2 })); await settle();
out.reread = calls.filter((c) => c.startsWith("card")).length;
toggle(1).click(); await settle();
out.collapsed = all(tab.el, "section.wb-video").length;
toggle(1).click(); await settle();
out.reopened = { cards: all(tab.el, "section.wb-video").length, reads: calls.filter((c) => c.startsWith("card")).length };
tab.update(data({ tasks: tasks.slice(1), reload: 3 })); await settle();
out.gone = all(tab.el, "section.wb-video").length;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_only_the_code_task_of_a_recording_gets_the_card_made_when_its_row_opens_and_dropped_when_it_closes(tmp_path):
    got = run_node(tmp_path, TAB_RUN)
    assert got["closed"] == {"cards": 0, "reads": 0}, "a closed row makes no card and reads nothing"
    assert got["plain"] == {"cards": 0, "reads": 0}, "a key that is not media:<16 hexadecimal characters> never gets one"
    assert got["opened"]["cards"] == 1 and got["opened"]["reads"] == ["card fedcba9876543210"] and got["opened"]["text"] is True
    assert got["reread"] == 2, "the card reads again when the store changed"
    assert got["collapsed"] == 0 and got["reopened"] == {"cards": 1, "reads": 3} and got["gone"] == 0


# --- what the files are allowed to do ---------------------------------------------------------------------------------------------------------


def test_the_card_calls_only_its_own_routes_builds_no_markup_and_touches_no_configuration():
    source = CARD.read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("//"))
    assert set(re.findall(r"\benv\.api\.(\w+)\(", code)) == {"videoCard", "videoCover", "videoRaw", "videoApprove", "videoSendBack", "videoDownload", "mediaList", "prepareAgain", "pollJob"}
    for forbidden in ("setMode", "acceptConfig", "accept-config", "mode:", "innerHTML", "insertAdjacentHTML", "outerHTML", "createContextualFragment", "fetch(", "XMLHttpRequest",
                      "localStorage", "sessionStorage", "window.open", "ev" + "al(", "new Func" + "tion", ".style"):
        assert forbidden not in code, forbidden
    assert "approved_at" not in code.split("function approve()")[1].split("function sendBack")[0], "approve sends no date: the service writes it"
    approve = code.split("function approve()")[1].split("function sendBack")[0]
    assert re.findall(r"videoSha256: card\.render\.sha256, captionSha256: card\.caption\.sha256, platform: card\.platform", approve), "the hashes come from the card on screen"
    tab = (JS / "floor" / "tasks-tab.js").read_text(encoding="utf-8")
    assert "createVideoCard" in tab and "MEDIA_KEY" in tab


def test_the_client_keeps_one_network_call_and_the_page_loads_nothing_from_another_host():
    api = (JS / "api.js").read_text(encoding="utf-8")
    assert len(re.findall(r"\btransport\(", api)) == 1 and "fetch(" not in api and "XMLHttpRequest" not in api
    html = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"https?://", html.replace("http://www.w3.org", "")), "nothing is loaded from another host"


# --- the layout at a phone's width ---------------------------------------------------------------------------------------------------------------


def test_the_card_fits_a_phone_its_video_and_buttons_take_the_width_and_nothing_scrolls_sideways():
    css = interface_css()
    floor = css_file("floor")
    phone = "\n".join(media_blocks(floor, "max-width: 899px"))
    assert ".wb-video-player { max-width: 100%; }" in phone, "on a phone the video is as wide as the card"
    assert ".wb-card-actions .pui-btn { flex: 1 1 100%; min-height: 44px; }" in phone, "the card's buttons are full width and tall enough to touch"
    assert ".wb-video-platforms .pui-btn { flex: 1 1 auto; min-height: 44px; }" in phone
    player = re.search(r"\.wb-video-player \{([^}]*)\}", floor).group(1)
    assert "width: 100%" in player and "max-height: 70vh" in player and "height: auto" in player
    caption = re.search(r"\.wb-video-caption \{([^}]*)\}", floor).group(1)
    assert "overflow" not in caption and "max-height" not in caption and "white-space: nowrap" not in caption, "the caption wraps, and it is no box that scrolls: floor/reply.js cuts it"
    pre = re.search(r"^\.wb-pre \{([^}]*)\}", floor, re.M).group(1)
    assert "overflow-wrap: anywhere" in pre and "white-space: pre-wrap" in pre
    assert "overflow-wrap: anywhere" in re.search(r"^\.wb-hash \{([^}]*)\}", floor, re.M).group(1), "a 64-character hash wraps"
    assert ".wb-video-loading, .wb-video-approved, .wb-video-heading, .wb-video-line { font-size: 16px; }" in phone
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", "\n".join(re.findall(r"[^\n]*wb-video[^\n]*", css))), "tokens only: no colour literal"
    assert "min-width: 0" in re.search(r"\.wb-video \{([^}]*)\}", floor).group(1)


PROBLEMS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createVideoCard } from "@JS@/floor/video-card.js";
const card = { recording: "0123456789abcdef", status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null, caption: null, approval: null, sent_back: null,
  can_download: false, download_name: null, problems: ["there is no render yet", "the post file has no single ```post block"] };
const api = { videoCard: async () => card };
const view = createVideoCard({ project: "0123456789ab", recording: "0123456789abcdef", api, loopback: true });
await view.load(); await settle();
const notices = all(view.el, ".wb-notice-card");
console.log(JSON.stringify({ count: notices.length, texts: notices.map((n) => n.textContent), stray: view.el.textContent.includes("object"), line: all(view.el, "[data-key=no-render]").length, said: (view.el.textContent.toLowerCase().match(/no render yet/g) || []).length }));
process.exit(0);
"""


@needs_node
def test_every_problem_of_the_card_is_a_notice_of_its_own_never_a_list_turned_into_text(tmp_path):
    got = run_node(tmp_path, PROBLEMS)
    assert got["count"] == 1 and got["texts"] == ["the post file has no single ```post block"] and got["stray"] is False, "the service's \"no render yet\" is the card's own line, not a second notice"
    assert got["line"] == 1 and got["said"] == 1, "and it is said once"


# --- the card's state comes from the pipeline ----------------------------------------------------------------------------------------------------

STATES = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createVideoCard } from "@JS@/floor/video-card.js";
const SHA = "a".repeat(64), CAP = "c".repeat(64);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const withRender = { sha256: SHA, bytes: 3, duration: 41.5, width: 1080, height: 1920, fps: 30, codec: "h264", name: "render-aaaaaaaaaaaa.mp4", source: "result" };
const base = { recording: "0123456789abcdef", status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null,
  caption: { text: "Three habits.", sha256: CAP, chars: 13, post_file: "docs/marketing/content/x.md" }, approval: null, sent_back: null, can_download: false, download_name: null, problems: ["there is no render yet"] };
const steps = (extra = {}) => ({ transcribe: "done", analyse: "done", retakes: "done", "align-proposal": "done", review: "done", remap: "done", base: "done", align: "done", check: "done", render: "pending", cover: "pending", approval: "pending", ...extra });
const script = { card: { ...base }, pipeline: { task: 2, steps: steps(), next: "render", failure: null }, mediaError: false };
const reads = { card: 0, media: 0 };
const api = {
  videoCard: async () => { reads.card += 1; return JSON.parse(JSON.stringify(script.card)); },
  mediaList: async () => { reads.media += 1; if (script.mediaError) throw new Error("no"); return { recordings: [{ id: "0123456789abcdef", pipeline: script.pipeline }] }; },
  videoRaw: async () => { reads.raw = (reads.raw || 0) + 1; return { size: 3 }; }, videoCover: async () => ({ size: 1 }),
  prepareAgain: async (p, rid, step) => { reads.again = [...(reads.again || []), step]; script.pipeline = { ...script.pipeline, active: true }; return { job: 9, state: "running" }; },
  pollJob: async () => { await new Promise((r) => setTimeout(r, 10)); script.card = { ...base, render: withRender, problems: [] }; script.pipeline = { task: 2, steps: steps({ render: "done", cover: "done", approval: "waiting" }), next: "approval", failure: null, active: false }; return { state: "done", result: { ok: true } }; },
};
const objects = { create: () => "blob:x", revoke: () => {} };
const make = (extra = {}) => createVideoCard({ project: "0123456789ab", recording: "0123456789abcdef", api, loopback: true, objects, pollEvery: 40, ...extra });
const text = (n) => n.textContent;
const look = (root) => ({
  chip: text(find(root, ".pui-badge")), approve: all(root, "[data-key=approve]").length, download: all(root, "[data-key=download]").length, sendBack: all(root, "[data-key=send-back]").length, video: all(root, "video").length,
  steps: all(root, "[data-key=steps] li").map((n) => n.attrs["data-step"] + ":" + n.cls().find((c) => c.startsWith("is-"))), making: all(root, "[data-key=making]").length, noRender: all(root, "[data-key=no-render]").length,
  notices: all(root, ".wb-notice-card").map(text), said: (text(root).toLowerCase().match(/no render yet/g) || []).length,
});
const out = {};

// the render is being made: the maintainer's case. One chip, the steps, a note, nothing to approve or download, and "no render yet" nowhere
{
  const view = make(); await view.load(); await settle();
  out.making = look(view.el);
  out.makingNote = text(find(view.el, "[data-key=making]"));
  // an older render and an older approval do not show beside a new render being made
  script.card = { ...base, render: withRender, problems: [], approval: { state: "approved", reasons: [], approved_at: "d", approved_via: "page", video_sha256: SHA, caption_sha256: CAP, platform: "instagram" }, can_download: true, download_name: "x.mp4" };
  await view.load({ quiet: true }); await settle();
  out.older = look(view.el);
  view.close();
}

// it reads again by itself while the video is made, and shows the approval once a render exists and the approval step is reached
{
  script.card = { ...base };
  script.pipeline = { task: 2, steps: steps(), next: "render", failure: null };
  reads.card = 0;
  const view = make(); await view.load(); await settle();
  await wait(150);
  out.polled = reads.card;
  script.card = { ...base, render: withRender, problems: [] };
  script.pipeline = { task: 2, steps: steps({ render: "done", cover: "done", approval: "waiting" }), next: "approval", failure: null };
  await wait(150);
  out.ready = look(view.el);
  const after = reads.card;
  await wait(150);
  out.stoppedPolling = reads.card === after;
  view.close();
}

// closing stops the reads
{
  script.card = { ...base };
  script.pipeline = { task: 2, steps: steps(), next: "render", failure: null };
  const view = make(); await view.load(); await settle();
  view.close();
  const at = reads.card;
  await wait(150);
  out.closedReads = reads.card - at;
}

// a failure: its sentence, its code and the command, as the review shows them; nothing to approve
{
  script.card = { ...base };
  script.pipeline = { task: 2, steps: steps({ render: "failed" }), next: "render", failure: { step: "render", code: "browser_failed", field: "render", next: "python3 providers/renderer/ffmpeg.py build --confirmed" } };
  const view = make(); await view.load(); await settle();
  out.failed = look(view.el);
  view.close();
}

// no pipeline and no render: one line; the pipeline before the review says when the video is made
{
  script.card = { ...base };
  script.pipeline = null;
  const view = make(); await view.load(); await settle();
  out.none = look(view.el);
  out.noneLine = text(find(view.el, "[data-key=no-render]"));
  view.close();
  script.pipeline = { task: 2, steps: steps({ review: "waiting", render: "pending", cover: "pending" }), next: "review", failure: null };
  const early = make(); await early.load(); await settle();
  out.early = look(early.el);
  out.earlyLine = text(find(early.el, "[data-key=no-render]"));
  early.close();
}

// the pipeline cannot be read: the card works as it did, with the render it has
{
  script.card = { ...base, render: withRender, problems: [] };
  script.pipeline = null;
  script.mediaError = true;
  const view = make(); await view.load(); await settle();
  out.unread = look(view.el);
  view.close();
  script.mediaError = false;
}
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_card_shows_making_the_video_while_the_pipeline_renders_and_hides_approve_and_download(tmp_path):
    got = run_node(tmp_path, STATES)
    m = got["making"]
    assert m["chip"] == "Making the video" and (m["approve"], m["download"], m["sendBack"], m["video"]) == (0, 0, 0, 0)
    assert m["noRender"] == 0 and m["said"] == 0 and m["notices"] == [], "no \"no render yet\" in any form while the video is made"
    assert m["making"] == 1 and "takes a few minutes" in got["makingNote"]
    assert m["steps"][-3:] == ["render:is-pending", "cover:is-pending", "approval:is-pending"] and "review:is-done" in m["steps"], "the steps are shown with where each stands"
    o = got["older"]
    assert o["chip"] == "Making the video" and (o["approve"], o["download"], o["video"]) == (0, 0, 0), "an older render and an older approval do not show beside a new render being made"
    assert got["polled"] >= 3, "the card reads again by itself while the video is made"
    r = got["ready"]
    assert r["chip"] == "Waiting for your approval" and r["approve"] == 1 and r["making"] == 0 and r["steps"] == [] and got["stoppedPolling"] is True
    assert got["closedReads"] == 0


@needs_node
def test_a_step_that_stopped_shows_its_sentence_and_command_and_a_card_with_no_render_says_so_once(tmp_path):
    got = run_node(tmp_path, STATES)
    f = got["failed"]
    assert f["chip"] == "Stopped" and (f["approve"], f["download"], f["sendBack"]) == (0, 0, 0) and f["making"] == 0
    assert len(f["notices"]) == 1 and "Run: python3 providers/renderer/ffmpeg.py build --confirmed" in f["notices"][0] and "browser_failed" in f["notices"][0] and "Render the video stopped" in f["notices"][0]
    assert "render:is-failed" in f["steps"]
    n = got["none"]
    assert n["chip"] == "No video yet" and n["noRender"] == 1 and n["said"] == 1 and n["notices"] == [] and n["approve"] == 0, "one line, no disabled Approve"
    assert got["noneLine"] == "There is no render yet."
    assert got["earlyLine"] == "There is no render yet: the video is made after you check the captions." and got["early"]["said"] == 1
    u = got["unread"]
    assert u["chip"] == "Waiting for your approval" and u["approve"] == 1, "a pipeline that cannot be read leaves the card as it was"


CAPTION = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createVideoCard, CAPTION_LINES } from "@JS@/floor/video-card.js";
const base = { recording: "0123456789abcdef", status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null,
  caption: { text: "A long caption.\n".repeat(30), sha256: "c".repeat(64), chars: 480, post_file: "docs/marketing/content/x.md" }, approval: null, sent_back: null, can_download: false, download_name: null, problems: [] };
const api = { videoCard: async () => base };
let tall = true;
const view = createVideoCard({ project: "0123456789ab", recording: "0123456789abcdef", api, loopback: true, measure: () => tall });
await view.load(); await settle();
const reply = () => find(view.el, ".wb-reply");
const button = () => find(view.el, ".wb-reply-toggle");
const out = {};
out.cut = { cls: reply().cls().includes("is-cut"), open: reply().cls().includes("is-open"), label: button().textContent, aria: button().attrs["aria-expanded"], lines: reply().cls().includes("is-lines-4"), lineConst: CAPTION_LINES, scrollBoxes: all(view.el, "[tabindex]").length };
button().click(); await settle();
out.open = { cls: reply().cls().includes("is-open"), label: button().textContent, aria: button().attrs["aria-expanded"] };
await view.load({ quiet: true }); await settle();
out.stays = { open: reply().cls().includes("is-open"), label: button().textContent };
button().click(); await settle();
out.closed = { open: reply().cls().includes("is-open"), label: button().textContent };
tall = false;
base.caption = { ...base.caption, text: "short", sha256: "d".repeat(64) };
await view.load({ quiet: true }); await settle();
out.short = { button: all(view.el, ".wb-reply-toggle").length, text: find(view.el, "[data-key=caption]").textContent };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_long_caption_is_cut_to_a_few_lines_and_opens_and_closes_and_a_short_one_has_no_button(tmp_path):
    got = run_node(tmp_path, CAPTION)
    assert got["cut"]["cls"] is True and got["cut"]["open"] is False and got["cut"]["label"] == "Show the whole caption" and got["cut"]["aria"] == "false"
    assert got["cut"]["lines"] is True and got["cut"]["lineConst"] == 4 and got["cut"]["scrollBoxes"] == 0, "four lines, and nothing in the card takes the keyboard focus to scroll"
    assert got["open"] == {"cls": True, "label": "Show less", "aria": "true"}
    assert got["stays"] == {"open": True, "label": "Show less"}, "a read that changed nothing keeps the caption open"
    assert got["closed"] == {"open": False, "label": "Show the whole caption"}
    assert got["short"] == {"button": 0, "text": "short"}


def test_no_block_of_the_card_or_the_review_scrolls_on_its_own_and_the_caption_uses_the_shared_reply_helper():
    floor = css_file("floor")
    for selector, body in re.findall(r"^([^{}@]*\.wb-(?:video|rev|card)[^{}]*)\{([^}]*)\}", floor, re.M):
        assert not re.search(r"overflow(-y|-x)?\s*:\s*(auto|scroll)", body), f"{selector.strip()} scrolls on its own: the panel is the only scroller"
    card = CARD.read_text(encoding="utf-8")
    assert 'from "./reply.js"' in card and "replyView(" in card
    assert "scrollTop" not in card


IDLE = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createVideoCard, STALLED_WORDS, IDLE_WORDS, MAX_POLLS } from "@JS@/floor/video-card.js";
const SHA = "a".repeat(64), CAP = "c".repeat(64);
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const withRender = { sha256: SHA, bytes: 3, duration: 41.5, width: 1080, height: 1920, fps: 30, codec: "h264", name: "render-aaaaaaaaaaaa.mp4", source: "result" };
const base = { recording: "0123456789abcdef", status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null,
  caption: { text: "Three habits.", sha256: CAP, chars: 13, post_file: "docs/marketing/content/x.md" }, approval: null, sent_back: null, can_download: false, download_name: null, problems: [] };
const steps = (extra = {}) => ({ transcribe: "done", review: "done", base: "done", check: "done", render: "pending", cover: "pending", approval: "pending", ...extra });
const script = { card: { ...base }, pipeline: { task: 2, steps: steps(), next: "render", failure: null, active: true } };
const reads = { card: 0, raw: 0, again: [] };
const api = {
  videoCard: async () => { reads.card += 1; return JSON.parse(JSON.stringify(script.card)); },
  mediaList: async () => ({ recordings: [{ id: "0123456789abcdef", pipeline: JSON.parse(JSON.stringify(script.pipeline)) }] }),
  videoRaw: async () => { reads.raw += 1; return { size: 3 }; }, videoCover: async () => ({ size: 1 }),
  prepareAgain: async (p, rid, step) => { reads.again.push(step); script.pipeline = { ...script.pipeline, active: true }; return { job: 9 }; },
  pollJob: async () => { await wait(10); script.card = { ...base, render: withRender }; script.pipeline = { task: 2, steps: steps({ render: "done", cover: "done", approval: "waiting" }), next: "approval", failure: null, active: false }; return { state: "done", result: { ok: true } }; },
};
const objects = { create: () => "blob:x", revoke: () => {} };
const make = (extra = {}) => createVideoCard({ project: "0123456789ab", recording: "0123456789abcdef", api, loopback: true, objects, pollEvery: 30, ...extra });
const text = (n) => n.textContent;
const key = (root, k) => find(root, `[data-key="${k}"]`);
const out = {};

// a hidden tab does not poll, and reads at once when it is shown again
{
  script.card = { ...base }; script.pipeline = { task: 2, steps: steps(), next: "render", failure: null, active: true };
  const view = make(); await view.load(); await settle();
  document.hidden = true;
  await wait(100);
  const hiddenAt = reads.card;
  await wait(150);
  out.hidden = { stable: reads.card === hiddenAt };
  document.hidden = false;
  (document.listeners.visibilitychange || []).forEach((fn) => fn());
  await wait(40);
  out.shown = reads.card > hiddenAt;
  view.close();
}

// loads that overlap make one chain of reads, not several
{
  reads.card = 0;
  const view = make(); await view.load();
  await Promise.all([view.load({ quiet: true }), view.load({ quiet: true }), view.load({ quiet: true })]);
  const at = reads.card;
  await wait(125);
  out.chain = reads.card - at;
  view.close();
}

// the pipeline stopped with nobody running it: "Stopped", the sentence, "Start again", and no polling
{
  script.card = { ...base, render: withRender }; reads.raw = 0; reads.again = [];
  script.pipeline = { task: 2, steps: steps(), next: "render", failure: null, active: false };
  const view = make(); await view.load(); await settle();
  const at = reads.card;
  await wait(120);
  out.idle = { chip: text(find(view.el, ".pui-badge")), note: text(key(view.el, "idle")), again: Boolean(key(view.el, "start-again")), approve: Boolean(key(view.el, "approve")), video: Boolean(find(view.el, "video")),
    steps: all(view.el, "[data-key=steps] li").length, polled: reads.card - at, raw: reads.raw };
  key(view.el, "start-again").click();
  await wait(150); await settle();
  out.restarted = { again: reads.again, chip: text(find(view.el, ".pui-badge")), approve: Boolean(key(view.el, "approve")), idle: Boolean(key(view.el, "idle")) };
  view.close();
}

// a failed step with no failure word is stopped too; the video of an older render is not fetched while one is made
{
  reads.raw = 0;
  script.card = { ...base, render: withRender };
  script.pipeline = { task: 2, steps: steps({ render: "failed" }), next: "render", failure: null, active: true };
  let view = make(); await view.load(); await settle();
  out.failedStep = { chip: text(find(view.el, ".pui-badge")), again: Boolean(key(view.el, "start-again")) };
  view.close();
  script.pipeline = { task: 2, steps: steps(), next: "render", failure: null, active: true };
  view = make(); await view.load(); await settle();
  out.noFetch = { chip: text(find(view.el, ".pui-badge")), raw: reads.raw };
  view.close();
  script.card = { ...base, render: withRender, problems: [] };
  script.pipeline = { task: 2, steps: steps({ render: "done", cover: "done", approval: "waiting" }), next: "approval", failure: null, active: false };
  view = make(); await view.load(); await settle(); await wait(20);
  out.ready = { chip: text(find(view.el, ".pui-badge")), raw: reads.raw };
  view.close();
}

// the polling is capped: the card says it stopped looking, and "Check again" looks again
{
  script.card = { ...base }; script.pipeline = { task: 2, steps: steps(), next: "render", failure: null, active: true };
  reads.card = 0;
  const view = make({ maxPolls: 3 }); await view.load(); await settle();
  await wait(250);
  const capped = reads.card;
  await wait(120);
  out.cap = { reads: capped, stable: reads.card === capped, note: text(key(view.el, "stalled")), constant: MAX_POLLS };
  key(view.el, "reload").click();
  await wait(60);
  out.again = { more: reads.card > capped, noteGone: key(view.el, "stalled") === null };
  view.close();
}
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_card_polls_only_while_the_tab_is_shown_in_one_chain_and_a_cap_and_says_when_it_stopped_looking(tmp_path):
    got = run_node(tmp_path, IDLE)
    assert got["hidden"] == {"stable": True} and got["shown"] is True, "no read while the tab is hidden; one at once when it is shown"
    assert 2 <= got["chain"] <= 5, "one chain: with a pause of 30 ms about four reads in 125 ms, not eight"
    c = got["cap"]
    assert c["reads"] <= 5 and c["stable"] is True and "stopped checking" in c["note"] and c["constant"] == 200, "capped, then silent, and it says so"
    assert got["again"] == {"more": True, "noteGone": True}, "Check again looks again"


@needs_node
def test_a_pipeline_that_nobody_runs_is_stopped_with_start_again_and_a_failed_step_is_stopped_and_an_older_render_is_not_fetched(tmp_path):
    got = run_node(tmp_path, IDLE)
    i = got["idle"]
    assert i["chip"] == "Stopped" and "Nothing is running" in i["note"] and i["again"] is True and i["approve"] is False and i["video"] is False and i["steps"] == 7, i
    assert i["polled"] == 0 and i["raw"] == 0, "no polling for a pipeline nobody runs, and no video fetched while it is not ready"
    assert got["restarted"] == {"again": ["render"], "chip": "Waiting for your approval", "approve": True, "idle": False}, "Start again runs prepare-again from the step it had reached, and the card follows"
    assert got["failedStep"] == {"chip": "Stopped", "again": False}, "a failed status is stopped (the failure's own sentence is the review's)"
    assert got["noFetch"] == {"chip": "Making the video", "raw": 0}
    assert got["ready"] == {"chip": "Waiting for your approval", "raw": 1}, "the video is fetched when the render is the card's"

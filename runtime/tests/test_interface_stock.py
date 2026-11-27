"""The page's part of the licensed pictures of a video (package V9b-3a): the pure model (the closed edits of the media set, the words rule, the layouts' fields) and the Pictures section of
the caption review dialog (views/lobby-captions-model.js, views/lobby-captions.js) under a fake document with a stand-in client: the words, the search that sends nothing until the
person confirms, the candidates with their licence and the page address as plain text, the picks, the fetch, the set to read and approve, the credits, a layout added with its words,
the local network and the policy. Run with Node over the real modules. No browser, no service, no library. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_stock.py
"""
from __future__ import annotations

import pytest

from test_interface_captions import PRELUDE
from test_interface_floor import run_node as run_floor_node
from test_interface_lobby import INTERFACE, needs_node, run_node  # noqa: F401

MODEL = r"""
import * as m from "@JS@/views/lobby-captions-model.js";
const out = {};
out.edits = [m.slotStockEdit("beat7"), m.slotSearchEdit("beat7", "shop front", "clip"), m.slotSearchEdit("beat7", "shop front", "video"), m.slotAssetEdit("beat7", "shelf:item-1"),
  m.clearPickEdit("beat7"), m.addLayout("oh:cutaway", { fit: "cover" }, { from: 1, to: 2 }, "a busy market", "market stall", "image"),
  m.addLayout("oh:cutaway", {}, { from: 1, to: 2 }, "", "", "clip")];
out.problems = ["shop front", "a", "", " shop", "shop ", "one two three four five six", "one two three four five six seven", "shop 2", "café", "http://x.example", "it's a dog-friendly cafe"].map(m.searchProblem);
const view = { slots: [{ slot: "beat7", description: "a shop", type: "image", choice: "stock", search: "shop front", want: "clip", pick: "shelf:item-1", file: null },
  { slot: "a1", description: "a market", type: "image|clip", search: null, want: null, pick: null, animation: "a1" }] };
out.slots = m.stockSlots(view).map((s) => [s.slot, s.kind, s.choice, s.search, s.want, s.pick, s.layout]);
out.none = m.stockSlots(null);
const entry = { name: "oh:cutaway", kind: "layout", params: { asset: { type: ["image", "clip"], required: true }, fit: { type: "choice", values: ["cover", "contain"] }, label: { type: "text", max: 40 } } };
out.fields = [m.layoutFieldsOf(entry).map((f) => f.name), m.layoutFieldsOf(entry).unsupported, m.fieldsOf(entry).unsupported, m.layoutFieldsOf(null).length];
out.text = [m.candidateText({ source: "shelf", licence: "cc-by-4.0", author: "Bram Hollow", width: 1600, height: 1200, seconds: null }),
  m.candidateText({ source: "lib", licence: "unverified", author: "", width: 1920, height: 1080, seconds: 8 })];
out.summary = [m.approvalSummary({ approved: true, sha256: "a".repeat(64), credits: ["x"], needs_own_approval: ["beat9"], set: { assets: [{ slot: "beat7" }] } }), m.approvalSummary(null)];
out.kinds = [m.WANT_KINDS, Object.isFrozen(m.WANT_KINDS), m.SEARCH_WORDS_MAX];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_model_builds_the_closed_edits_of_the_media_set_and_checks_the_words_as_the_service_does(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["edits"][0] == {"op": "slot", "slot": "beat7", "choice": "stock"} and got["edits"][1] == {"op": "slot_search", "slot": "beat7", "search": "shop front", "want": "clip"}
    assert got["edits"][2]["want"] == "image", "a kind the service does not know becomes the default"
    assert got["edits"][3] == {"op": "slot_asset", "slot": "beat7", "pick": "shelf:item-1"} and got["edits"][4] == {"op": "slot_asset", "slot": "beat7", "clear": True}
    assert got["edits"][5] == {"op": "animation", "block": "oh:cutaway", "params": {"fit": "cover"}, "word_from": 1, "word_to": 2, "show": "a busy market", "search": "market stall", "want": "image"}
    assert got["edits"][6] == {"op": "animation", "block": "oh:cutaway", "params": {}, "word_from": 1, "word_to": 2}, "no words, no search keys"
    ok, bad = "", "Write 1 to 6 English words, with letters only."
    assert got["problems"] == [ok, bad, bad, bad, bad, ok, bad, bad, bad, bad, ok]
    assert got["slots"] == [["beat7", "image", "stock", "shop front", "clip", "shelf:item-1", False], ["a1", "image|clip", None, "", "image", None, True]] and got["none"] == []
    assert got["fields"] == [["fit", "label"], False, True, 0], "the picture is chosen in the media set, so the form of a layout leaves it out"
    assert got["text"] == ["shelf: cc-by-4.0, by Bram Hollow, 1600x1200", "lib: licence not checked, 1920x1080, 8 s"]
    assert got["summary"][0] == {"approved": True, "hash": "a" * 64, "credits": ["x"], "own": ["beat9"], "assets": [{"slot": "beat7"}]}
    assert got["summary"][1] == {"approved": False, "hash": "", "credits": [], "own": [], "assets": []}
    assert got["kinds"] == [["image", "clip"], True, 6]


DIALOG = PRELUDE + r"""
import { MEDIA_LAN, MEDIA_CREDIT_LINE } from "@JS@/views/lobby-captions.js";
const HASH = "a".repeat(64);
const CAND = (n, extra) => ({ pick: `shelf:item-${n}`, source: "shelf", item: `item-${n}`, kind: "image", licence: "cc-by-4.0", author: "Bram Hollow", title: `A shop ${n}`,
  page: `https://shelf.example/p/item-${n}`, width: 1600, height: 1200, seconds: null, preview: true, col: n, ...extra });
const STOCK_VIEW = (slot) => ({ ...VIEW(), animations: [], beats: [], retakes: [], slots: [slot] });
const SLOT = { slot: "beat7", beat: 7, param: "asset", type: "image", description: "a shop front", file: null, choice: null, search: null, want: null, pick: null };
function makeStock(options = {}) {
  const calls = [];
  const o = { mode: "review", host: "127.0.0.1", view: STOCK_VIEW(SLOT), ...options };
  const state = { view: structuredClone(o.view) };
  const results = { jf: null, jp: null };
  const api = {
    captionsRead: async () => ({ task: 900, media: "a1b2c3d4", mode: o.mode, still: null, view: structuredClone(state.view) }),
    captionsEdit: async (p, t, rev, edits) => {
      calls.push(["edit", rev, edits]);
      for (const e of edits) {
        const row = state.view.slots.find((s) => s.slot === e.slot);
        if (e.op === "slot") row.choice = e.choice;
        if (e.op === "slot_search") { row.search = e.search; row.want = e.want; }
        if (e.op === "slot_asset") row.pick = e.clear ? null : e.pick;
      }
      state.view.revision += 1;
      return {};
    },
    videoCatalogue: async () => ({ engine: "ffmpeg", animations_max: 12, beats_max: 12, presets: {}, blocks: [
      { name: "oh:cutaway", kind: "layout", params: { asset: { type: ["image", "clip"], required: true }, fit: { type: "choice", values: ["cover", "contain"] }, label: { type: "text", max: 40 } },
        samples: [{}], use_when: "A picture over the speaker.", natural_duration: 2, engines: ["ffmpeg"], addable: true, why: null }] }),
    videoMediaFind: async (p, t, confirm) => {
      calls.push(["find", confirm]);
      results.jf = confirm ? { confirmed: true, found: 2, sheet: "sheet-preview.png", message: "2 candidates for 1 slots; pick one per slot, then fetch the picks.",
        slots: [{ slot: "beat7", show: "a shop front", search: "shop front", want: "image", candidates: [CAND(1), CAND(2, { licence: "cc0-1.0", author: "", page: "" })] }] }
        : { confirmed: false, sources: ["shelf"], slots: [], message: "These words will be sent to shelf: shop front." };
      return { job: "jf" };
    },
    videoMediaFetchPicks: async () => { calls.push(["fetch"]); results.jp = { assets: [{ slot: "beat7", source: "shelf", kind: "image", licence: "cc-by-4.0", width: 1080, height: 1920, pick: "shelf:item-1", file: "asset-" + "b".repeat(12) + ".png" }], sheet: "sheet.png", provided: ["Media provided by shelf (https://shelf.example/terms)"], message: "Check the pictures." }; return { job: "jp" }; },
    videoMediaApprove: async (p, t, hash) => {
      calls.push(["approve", hash || null]);
      return { approved: Boolean(hash), sha256: HASH, credits: ['"A shop 1" by Bram Hollow, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), via shelf'], needs_own_approval: o.own || [], provided: ["Media provided by shelf (https://shelf.example/terms)"],
        ...(o.scan ? { scan: o.scan } : {}), set: { assets: [{ slot: "beat7", source: "shelf", licence: "cc-by-4.0", width: 1080, height: 1920 }] } };
    },
    videoMediaFile: async (p, t, name) => { calls.push(["file", name]); return new Blob(["png"], { type: "image/png" }); },
    pollJob: async (id) => ({ id, state: o.failed ? "failed" : "done", result: results[id], error: o.failed ? { message: "refused: stock_not_accepted" } : null }),
    ...(o.extraApi ? o.extraApi(calls, results) : {}),      // V9b-3b: the web search and the approval of one file
  };
  const allowed = o.allowed || null;
  const review = createCaptionReview({ api, project: "proj", entry: () => (allowed ? { permissions: { allowed } } : null), host: () => o.host, refresh: async () => {} });
  return { review, calls, el: review.el, state };
}
"""

SECTION = DIALOG + r"""
const r = makeStock();
await r.review.open(900, "review"); await settle();
out.drawn = { headings: byClass(r.el, "wb-cr-head").map(textOf), slot: textOf(byClass(byClass(r.el, "wb-cr-media-slot")[0], "wb-cr-line")[0]), find: btn(r.el, "Find media").disabled, note: textOf(r.el).includes("nothing is sent until you confirm") };
// the words: a bad rule sends nothing, a good one sends the choice and the search in one call
const inputs = () => tag(byClass(r.el, "wb-cr-media-slot")[0], "input");
type(inputs()[0], "shop 2"); click(btn(r.el, "Use these words")); await settle();
out.bad = { problem: textOf(byClass(r.el, "wb-cr-problem")[0]), edits: r.calls.filter((c) => c[0] === "edit").length };
type(inputs()[0], "shop front");
type(tag(byClass(r.el, "wb-cr-media-slot")[0], "select")[0], "image");
click(btn(r.el, "Use these words")); await settle();
out.words = { sent: r.calls.filter((c) => c[0] === "edit"), revision: r.state.view.revision, find: btn(r.el, "Find media").disabled, kept: inputs()[0].value };
// the search sends nothing until it is confirmed
click(btn(r.el, "Find media")); await settle();
out.preview = { calls: r.calls.filter((c) => c[0] === "find"), line: textOf(byClass(r.el, "wb-cr-media-words")[0]), confirm: labels(r.el).includes("Send the words and search"), candidates: byClass(r.el, "wb-cr-candidate").length };
click(btn(r.el, "Send the words and search")); await settle();
const cands = byClass(r.el, "wb-cr-candidate");
out.found = { calls: r.calls.filter((c) => c[0] === "find"), lines: cands.map((c) => textOf(byClass(c, "wb-cr-line")[0])), pages: cands.map((c) => byClass(c, "wb-cr-page").map(textOf)),
  files: r.calls.filter((c) => c[0] === "file").map((c) => c[1]), imgs: tag(r.el, "img").map((i) => i.attrs.src.slice(0, 5)), anchors: tag(r.el, "a").length, fetchDisabled: btn(r.el, "Fetch the picks").disabled,
  notice: textOf(byClass(r.el, "wb-cr-notice").slice(-1)[0]) };
// a pick, then the fetch, then the set to read and approve
click(btn(cands[0], "Pick this")); await settle();
out.pick = { sent: r.calls.filter((c) => c[0] === "edit").slice(-1)[0][2], fetchDisabled: btn(r.el, "Fetch the picks").disabled, picked: textOf(byClass(r.el, "wb-cr-media-slot")[0]).includes("Picked: shelf:item-1"),
  button: labels(byClass(r.el, "wb-cr-candidate")[0]) };
click(btn(r.el, "Fetch the picks")); await settle();
out.fetched = { calls: r.calls.filter((c) => c[0] === "fetch").length, files: r.calls.filter((c) => c[0] === "file").map((c) => c[1]).slice(-2), imgs: tag(r.el, "img").length, provided: byClass(r.el, "wb-cr-provided").map(textOf), anchorsToo: tag(r.el, "a").length, read: labels(r.el).includes("Read the media set") };
click(btn(r.el, "Read the media set")); await settle();
out.read = { text: textOf(r.el).includes(`This set has the hash ${"a".repeat(64)}.`), credit: byClass(r.el, "wb-cr-credit").map(textOf), head: textOf(r.el).includes(MEDIA_CREDIT_LINE), approve: labels(r.el).includes("Approve the media"), calls: r.calls.filter((c) => c[0] === "approve") };
click(btn(r.el, "Approve the media")); await settle();
out.approved = { calls: r.calls.filter((c) => c[0] === "approve"), text: textOf(r.el).includes("This media set is approved."), button: labels(r.el).includes("Approve the media") };
// clearing the pick
click(btn(r.el, "Clear the pick")); await settle();
out.cleared = r.calls.filter((c) => c[0] === "edit").slice(-1)[0][2];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_pictures_section_sends_nothing_until_the_words_are_confirmed_and_walks_find_pick_fetch_approve(tmp_path):
    got = run_node(tmp_path, SECTION)
    assert got["drawn"]["slot"] == "Slot beat7: a shop front" and got["drawn"]["find"] is True and got["drawn"]["note"] is True
    assert got["drawn"]["headings"].index("Pictures") == got["drawn"]["headings"].index("Animations") + 1
    assert got["bad"] == {"problem": "Write 1 to 6 English words, with letters only.", "edits": 0}
    assert got["words"]["sent"] == [["edit", 4, [{"op": "slot", "slot": "beat7", "choice": "stock"}, {"op": "slot_search", "slot": "beat7", "search": "shop front", "want": "image"}]]]
    assert got["words"]["revision"] == 5 and got["words"]["find"] is False and got["words"]["kept"] == "shop front"
    assert got["preview"]["calls"] == [["find", False]] and got["preview"]["line"] == "These words will be sent to shelf: shop front." and got["preview"]["confirm"] is True
    assert got["preview"]["candidates"] == 0, "the words alone are shown first; nothing was searched"
    assert got["found"]["calls"] == [["find", False], ["find", True]]
    assert got["found"]["lines"] == ["Picture 1: shelf: cc-by-4.0, by Bram Hollow, 1600x1200, \"A shop 1\"", "Picture 2: shelf: cc0-1.0, 1600x1200, \"A shop 2\""]
    assert got["found"]["pages"] == [["Page: https://shelf.example/p/item-1"], []], "the page address is text"
    assert got["found"]["files"] == ["sheet-preview.png"] and got["found"]["imgs"] == ["blob:"] and got["found"]["anchors"] == 0, "no link and no image from another host"
    assert got["found"]["fetchDisabled"] is True and got["found"]["notice"].startswith("2 candidates for 1 slots")
    assert got["pick"]["sent"] == [{"op": "slot_asset", "slot": "beat7", "pick": "shelf:item-1"}] and got["pick"]["fetchDisabled"] is False and got["pick"]["picked"] is True
    assert got["pick"]["button"] == ["Picked"]
    assert got["fetched"]["provided"] == ["Media provided by shelf (https://shelf.example/terms)"] and got["fetched"]["anchorsToo"] == 0 and got["fetched"]["imgs"] == 2, "the sheet and the picture of the set load (the file name the answer sends)"
    assert got["fetched"]["calls"] == 1 and got["fetched"]["files"] == ["sheet.png", "asset-" + "b" * 12 + ".png"] and got["fetched"]["read"] is True
    assert got["read"]["text"] is True and got["read"]["approve"] is True and got["read"]["head"] is True
    assert got["read"]["credit"] == ['"A shop 1" by Bram Hollow, CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/), via shelf']
    assert got["read"]["calls"] == [["approve", None]] and got["approved"]["calls"] == [["approve", None], ["approve", "a" * 64]], "the approval names the hash that was read"
    assert got["approved"]["text"] is True and got["approved"]["button"] is False
    assert got["cleared"] == [{"op": "slot_asset", "slot": "beat7", "clear": True}]


SCAN_PAGE = DIALOG + r"""
const HOSTILE = '<img src=x onerror="window.pwned=1">';
const scan = { state: "done", reason: null, heading: "Checked on this computer for text and QR codes:", scope: "English, Portuguese and Spanish text is read; text in other alphabets is not.", quote_label: "As read:",
  rows: [{ slot: "beat7", code: "text_found", chars: 40, quote: ["SAMPLE PHOTO", HOSTILE], cut: false, sentence: "beat7: the picture shows text (40 characters). Read by the computer, not checked:" },
         { slot: "beat7", code: "qr_link", host: "shop.example", count: 1, sentence: "beat7: the picture shows a QR code that opens a link on shop.example. Anyone who points a phone at your video can open it." }],
  clean: ["beat8"], clean_lines: ["beat8: no text or QR code found."] };
const r = makeStock({ scan });
await r.review.open(900, "review"); await settle();
type(tag(byClass(r.el, "wb-cr-media-slot")[0], "input")[0], "shop front"); click(btn(r.el, "Use these words")); await settle();
click(btn(r.el, "Find media")); await settle(); click(btn(r.el, "Send the words and search")); await settle();
click(btn(byClass(r.el, "wb-cr-candidate")[0], "Pick this")); await settle(); click(btn(r.el, "Fetch the picks")); await settle();
out.beforeRead = byClass(r.el, "wb-cr-scan-row").length;
click(btn(r.el, "Read the media set")); await settle();
const quote = byClass(r.el, "wb-cr-scan-quote");
out.scan = { head: byClass(r.el, "wb-cr-scan-head").map(textOf), rows: byClass(r.el, "wb-cr-scan-row").map(textOf), quotes: quote.length, lines: byClass(r.el, "wb-cr-scan-line").map(textOf),
  tag: quote.map((q) => q.tagName), clean: byClass(r.el, "wb-cr-scan-clean").map(textOf), scope: byClass(r.el, "wb-cr-scan-scope").map(textOf), approve: !btn(r.el, "Approve the media").disabled,
  imgs: tag(r.el, "img").filter((i) => i.attrs && (i.attrs.onerror || i.attrs.src === "x")).length, pwned: globalThis.window ? globalThis.window.pwned || null : null };
const none = makeStock({ scan: { state: "done", reason: null, heading: "h", scope: "s", quote_label: "q", rows: [], clean: [], clean_lines: [] } });
await none.review.open(900, "review"); await settle();
type(tag(byClass(none.el, "wb-cr-media-slot")[0], "input")[0], "shop front"); click(btn(none.el, "Use these words")); await settle();
click(btn(none.el, "Find media")); await settle(); click(btn(none.el, "Send the words and search")); await settle();
click(btn(byClass(none.el, "wb-cr-candidate")[0], "Pick this")); await settle(); click(btn(none.el, "Fetch the picks")); await settle(); click(btn(none.el, "Read the media set")); await settle();
out.nothing = byClass(none.el, "wb-cr-scan-head").length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_scan_rows_are_drawn_as_text_the_quoted_lines_apart_and_the_approval_is_never_held_back(tmp_path):
    got = run_node(tmp_path, SCAN_PAGE)
    assert got["beforeRead"] == 0, "the warnings come with the set to read, before the approve button"
    s = got["scan"]
    assert s["head"] == ["Checked on this computer for text and QR codes:"] and len(s["rows"]) == 2 and s["rows"][0].endswith("Read by the computer, not checked:")
    assert s["quotes"] == 1 and s["tag"] == ["BLOCKQUOTE"] and s["lines"] == ["\u201cSAMPLE PHOTO\u201d", "\u201c" + '<img src=x onerror="window.pwned=1">' + "\u201d"], "each quoted line is text inside quotation marks"
    assert s["clean"] == ["beat8: no text or QR code found."] and s["scope"] == ["English, Portuguese and Spanish text is read; text in other alphabets is not."]
    assert s["approve"] is True and s["imgs"] == 0 and s["pwned"] is None
    assert got["nothing"] == 0, "a set with nothing found and no clean line draws nothing"


MODES = DIALOG + r"""
// a file that needs its own approval cannot be approved here
const own = makeStock({ own: ["beat9"] });
await own.review.open(900, "review"); await settle();
type(tag(byClass(own.el, "wb-cr-media-slot")[0], "input")[0], "shop front"); click(btn(own.el, "Use these words")); await settle();
click(btn(own.el, "Find media")); await settle(); click(btn(own.el, "Send the words and search")); await settle();
click(btn(byClass(own.el, "wb-cr-candidate")[0], "Pick this")); await settle(); click(btn(own.el, "Fetch the picks")); await settle(); click(btn(own.el, "Read the media set")); await settle();
out.own = { text: textOf(own.el).includes("These files need their own approval: beat9."), disabled: btn(own.el, "Approve the media").disabled };
// the local network: the section says so and draws no control and loads no picture
const lan = makeStock({ host: "192.168.1.20" });
await lan.review.open(900, "review"); await settle();
out.lan = { text: textOf(r_section(lan.el)).includes(MEDIA_LAN), find: labels(lan.el).includes("Find media"), files: lan.calls.filter((c) => c[0] === "file").length };
function r_section(root) { return byClass(root, "wb-cr-sec").find((s) => textOf(s).startsWith("Pictures")); }
// a read-only dialog (no review waiting) and a policy that does not allow the search draw no section
const ro = makeStock({ mode: null });
await ro.review.open(900, null); await settle();
out.readOnly = { section: Boolean(r_section(ro.el)), find: labels(ro.el).includes("Find media") };
const policy = makeStock({ allowed: ["captions-read", "captions-edit", "video-catalogue", "video-run", "answer"] });
await policy.review.open(900, "review"); await settle();
out.policy = Boolean(r_section(policy.el));
const gate = makeStock({ mode: "gate" });
await gate.review.open(900, "gate"); await settle();
out.gate = Boolean(r_section(gate.el));
// a view with no slot has no section
const empty = makeStock({ view: { ...STOCK_VIEW(SLOT), slots: [] } });
await empty.review.open(900, "review"); await settle();
out.empty = Boolean(r_section(empty.el));
// a refusal of the job is shown as it came and the dialog stays
const failed = makeStock({ failed: true });
await failed.review.open(900, "review"); await settle();
type(tag(byClass(failed.el, "wb-cr-media-slot")[0], "input")[0], "shop front"); click(btn(failed.el, "Use these words")); await settle();
click(btn(failed.el, "Find media")); await settle();
out.failed = { text: textOf(byClass(failed.el, "wb-notice-card")[0]), still: labels(failed.el).includes("Find media") };
// hostile text from a library is text
const evil = makeStock();
await evil.review.open(900, "review"); await settle();
out.sections = evil.calls.length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_pictures_section_is_drawn_only_where_the_search_is_allowed_and_a_refusal_is_shown_as_it_came(tmp_path):
    got = run_node(tmp_path, MODES)
    assert got["own"] == {"text": True, "disabled": False}, "V9b-3b: the set is approved first and each file found on the web after it, so the set's button is not held back by them"
    assert got["lan"] == {"text": True, "find": False, "files": 0}
    assert got["readOnly"] == {"section": False, "find": False} and got["policy"] is False and got["gate"] is False and got["empty"] is False
    assert got["failed"] == {"text": "refused: stock_not_accepted", "still": True}


LAYOUT = DIALOG + r"""
const r = makeStock({ view: { ...STOCK_VIEW(SLOT), animations: [], slots: [] } });
await r.review.open(900, "review"); await settle();
click(btn(r.el, "Add an animation")); await settle();
click(btn(byClass(r.el, "wb-cr-catalogue")[0], "Use this")); await settle();
click(word(r.el, "shop")); await settle();
const form = byClass(r.el, "wb-cr-form")[0];
out.form = { labels: tag(form, "label").map((l) => textOf(l).split("\n")[0]).slice(0, 8), text: textOf(form).includes("chosen below, in Pictures") };
const inputs = tag(form, "input");
const named = (aria) => tag(form, "input").concat(tag(form, "select")).find((n) => n.attrs["aria-label"] === aria);
type(named("What it shows"), "a busy market");
type(named("Search words (English)"), "market 7");
click(btn(r.el, "Add the animation")); await settle();
out.bad = { problem: textOf(byClass(r.el, "wb-cr-problem")[0]), edits: r.calls.filter((c) => c[0] === "edit").length };
type(named("Search words (English)"), "market stall");
type(named("Looking for"), "clip");
click(btn(r.el, "Add the animation")); await settle();
out.sent = r.calls.filter((c) => c[0] === "edit").map((c) => c[2]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_layout_is_added_with_its_words_and_no_picture_and_a_bad_search_sends_nothing(tmp_path):
    got = run_node(tmp_path, LAYOUT)
    assert got["form"]["text"] is True and "fit" in "".join(got["form"]["labels"]) and "asset" not in "".join(got["form"]["labels"])
    assert got["bad"] == {"problem": "Write 1 to 6 English words, with letters only.", "edits": 0}
    assert got["sent"] == [[{"op": "animation", "block": "oh:cutaway", "params": {}, "word_from": 5, "word_to": 5, "show": "a busy market", "search": "market stall", "want": "clip"}]]


WEB_MODEL = r"""
import * as m from "@JS@/views/lobby-captions-model.js";
const web = { pick: "web:q-1", source: "web", item: "q-1", kind: "image", licence: "unverified", author: "", title: "A stall", page: "https://pages.example/g/1", width: null, height: null, seconds: null,
  preview: true, col: 1, licence_claim: "free to use, says the page", site_terms: "Share with a credit.", resolution: "1200x800", screen_work: true, page_host: "pages.example" };
const out = {};
out.is = [m.isWebCandidate(web), m.isWebCandidate({ licence: "cc0-1.0" }), m.isWebCandidate(null), m.isWebCandidate({})];
out.lines = [m.webLines(web), m.webLines({ licence: "unverified", licence_claim: "", screen_work: false }), m.webLines({ licence: "unverified", licence_claim: "x", page_host: "h.example", screen_work: false })];
out.constants = [m.WEB_TILE, m.SCREEN_WORK_LINE];
out.noPreview = [m.webLines({ ...web, preview: false }), m.webLines({ ...web, preview: true }), m.NO_PREVIEW_LINE];
out.licensedText = m.candidateText({ source: "shelf", licence: "cc0-1.0", author: "", width: 10, height: 20, seconds: null });
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_model_says_what_a_web_candidate_claims_and_never_that_it_is_licensed(tmp_path):
    got = run_node(tmp_path, WEB_MODEL)
    assert got["is"] == [True, False, False, False]
    assert got["lines"][0] == ["Found on the web, licence not checked: pages.example", "Claimed by the page, not checked: free to use, says the page", "Site terms, as written: Share with a credit.",
                               "Size claimed: 1200x800", "A still of a film, series, anime, TV show, game or music video"]
    assert got["lines"][1] == ["Found on the web, licence not checked", "Claimed by the page, not checked: none stated"]
    assert got["lines"][2] == ["Found on the web, licence not checked: h.example", "Claimed by the page, not checked: x"]
    assert got["constants"] == ["Found on the web, licence not checked", "A still of a film, series, anime, TV show, game or music video"] and got["licensedText"] == "shelf: cc0-1.0, 10x20"


@needs_node
def test_a_web_clip_with_no_preview_says_so_on_its_tile_and_one_with_a_preview_does_not(tmp_path):
    got = run_node(tmp_path, WEB_MODEL)
    line = "No preview: this clip is drawn on the sheet after it is fetched, before you approve it"
    assert got["noPreview"][2] == line and got["noPreview"][0][-1] == line and line not in got["noPreview"][1]


WEB = DIALOG + r"""
const SHA = "b".repeat(64);
const WEBC = (n, extra) => ({ pick: `web:q-${n}`, source: "web", item: `q-${n}`, kind: "image", licence: "unverified", author: "", title: `A stall ${n}`, page: `https://pages.example/g/${n}`,
  width: null, height: null, seconds: null, preview: true, col: n, licence_claim: "free to use, says the page", site_terms: "", resolution: "1200x800", screen_work: n === 1, page_host: "pages.example", ...extra });
const SKIPPED = [{ slot: "beat8", want: "clip", message: "This engine cannot draw clips yet. Pick a picture for this slot." }];
const WARNING = "Copyright warning: this file was found on the open web, on pages.example. Source page: https://pages.example/g/1";
const extra = (calls, results) => ({
  videoMediaWebsearch: async (p, t, confirm) => {
    calls.push(["web", confirm]);
    results.jw = confirm ? { confirmed: true, found: 2, sheet: "sheet-preview.png", skipped: SKIPPED, message: "2 candidates for 1 slots; pick one per slot, then fetch the picks.",
      slots: [{ slot: "beat7", show: "a shop front", search: "shop front", want: "image", candidates: [WEBC(1), WEBC(2)] }] }
      : { confirmed: false, slots: [{ slot: "beat7" }], skipped: SKIPPED, message: "These words will be sent to the web search of the model that runs it, and this computer will then download small previews: shop front." };
    return { job: "jw" };
  },
  videoMediaApprove: async (p, t, hash) => {
    calls.push(["approve", hash || null]);
    return { approved: Boolean(hash), sha256: HASH, credits: [], needs_own_approval: ["beat7"], own_approved: [], provided: [], set: { assets: [{ slot: "beat7", source: "web", licence: "unverified", width: 1080, height: 1920, sha256: SHA }] } };
  },
  videoMediaApproveAsset: async (p, t, slot, sha256, confirm) => {
    calls.push(["own", slot, sha256, confirm || null]);
    return confirm ? { approved: true, slot, sha256 } : { approved: false, slot, sha256, file: `asset-${sha256.slice(0, 12)}.png`, host: "pages.example", page: "https://pages.example/g/1",
      licence_claim: "free to use, says the page", licence_claim_note: "claimed by the page, not checked", screen_work: true, warning: WARNING, confirm: `--confirm ${sha256.slice(0, 12)}` };
  },
});
const r = makeStock({ extraApi: extra, own: ["beat7"] });
await r.review.open(900, "review"); await settle();
const intro = textOf(r.el);
const inputs = () => tag(byClass(r.el, "wb-cr-media-slot")[0], "input");
type(inputs()[0], "shop front"); click(btn(r.el, "Use these words")); await settle();
out.buttons = [labels(r.el).includes("Search the web"), labels(r.el).includes("Send the words and search the web"), btn(r.el, "Search the web").disabled];
out.intro = [intro.includes("nothing is sent until you confirm"), intro.includes("They can also be searched on the web: no licence is checked")];
click(btn(r.el, "Search the web")); await settle();
out.preview = { calls: r.calls.filter((c) => c[0] === "web"), line: textOf(byClass(r.el, "wb-cr-web-words")[0]), confirm: labels(r.el).includes("Send the words and search the web"),
  skipped: byClass(r.el, "wb-cr-note").map(textOf).filter((t) => t.startsWith("Slot beat8")), candidates: byClass(r.el, "wb-cr-candidate").length };
click(btn(r.el, "Send the words and search the web")); await settle();
const cands = byClass(r.el, "wb-cr-candidate");
out.found = { calls: r.calls.filter((c) => c[0] === "web"), head: cands.map((c) => textOf(byClass(c, "wb-cr-line")[0])), notes: cands.map((c) => byClass(c, "wb-cr-web").map(textOf)),
  pages: cands.map((c) => byClass(c, "wb-cr-page").map(textOf)), anchors: tag(r.el, "a").length, imgs: tag(r.el, "img").map((i) => i.attrs.src.slice(0, 5)), files: r.calls.filter((c) => c[0] === "file").map((c) => c[1]),
  skipped: byClass(r.el, "wb-cr-note").map(textOf).filter((t) => t.startsWith("Slot beat8")).length, buttons: labels(r.el).includes("Send the words and search the web") };
click(btn(cands[0], "Pick this")); await settle();
click(btn(r.el, "Fetch the picks")); await settle();
click(btn(r.el, "Read the media set")); await settle();
out.read = { own: textOf(r.el).includes("These files need their own approval: beat7."), approveDisabled: btn(r.el, "Approve the media").disabled, panels: byClass(r.el, "wb-cr-own").length, calls: r.calls.filter((c) => c[0] === "own") };
click(btn(r.el, "Approve the media")); await settle();
const panels = byClass(r.el, "wb-cr-own");
out.approved = { calls: r.calls.filter((c) => c[0] === "approve"), own: r.calls.filter((c) => c[0] === "own"), panels: panels.length, warning: panels.length ? textOf(byClass(panels[0], "wb-cr-warning")[0]) : null,
  notes: panels.length ? byClass(panels[0], "wb-cr-note").map(textOf) : null, imgs: panels.length ? tag(panels[0], "img").length : 0, button: panels.length ? labels(panels[0]) : null,
  files: r.calls.filter((c) => c[0] === "file").map((c) => c[1]).slice(-1), anchors: tag(r.el, "a").length };
click(btn(panels[0], "Approve this file")); await settle();
out.own = { calls: r.calls.filter((c) => c[0] === "own"), panels: byClass(r.el, "wb-cr-own").length, notice: textOf(byClass(r.el, "wb-cr-notice").slice(-1)[0]), need: textOf(r.el).includes("These files need their own approval: .") || textOf(r.el).includes("need their own approval: ,") };
// a page whose policy does not allow the web search draws neither the button nor the sentence
const quiet = makeStock({ extraApi: extra, allowed: ["captions-read", "captions-edit", "video-catalogue", "video-run", "answer", "video-media-find", "video-media-fetch-picks", "video-media-approve", "video-media-sheet-file"] });
await quiet.review.open(900, "review"); await settle();
out.quiet = { button: labels(quiet.el).includes("Search the web"), sentence: textOf(quiet.el).includes("They can also be searched on the web"), find: labels(quiet.el).includes("Find media") };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_web_search_sends_nothing_until_the_words_are_confirmed_and_each_web_file_is_approved_after_the_set_with_its_warning(tmp_path):
    got = run_node(tmp_path, WEB)
    assert got["buttons"] == [True, False, False] and got["intro"] == [True, True]
    assert got["preview"]["calls"] == [["web", False]] and got["preview"]["confirm"] is True and got["preview"]["candidates"] == 0
    assert got["preview"]["line"].startswith("These words will be sent to the web search of the model that runs it") and "download small previews" in got["preview"]["line"]
    assert got["preview"]["skipped"] == ["Slot beat8: This engine cannot draw clips yet. Pick a picture for this slot."]
    assert got["found"]["calls"] == [["web", False], ["web", True]] and got["found"]["skipped"] == 1, "the skipped slot is said with the candidates too"
    assert got["found"]["head"] == ['Picture 1: Found on the web, licence not checked: pages.example, "A stall 1"', 'Picture 2: Found on the web, licence not checked: pages.example, "A stall 2"']
    assert got["found"]["notes"][0] == ["Claimed by the page, not checked: free to use, says the page", "Size claimed: 1200x800", "A still of a film, series, anime, TV show, game or music video"]
    assert got["found"]["notes"][1] == ["Claimed by the page, not checked: free to use, says the page", "Size claimed: 1200x800"]
    assert got["found"]["pages"] == [["Page: https://pages.example/g/1"], ["Page: https://pages.example/g/2"]], "the page address is text"
    assert got["found"]["anchors"] == 0 and got["found"]["imgs"] == ["blob:"] and got["found"]["files"] == ["sheet-preview.png"], "no link and no image from another host"
    assert got["read"] == {"own": True, "approveDisabled": False, "panels": 0, "calls": []}, "the set is approved first; the warning is asked after it"
    assert got["approved"]["calls"] == [["approve", None], ["approve", "a" * 64]]
    assert got["approved"]["own"] == [["own", "beat7", "b" * 64, None]] and got["approved"]["panels"] == 1
    assert got["approved"]["warning"] == "Copyright warning: this file was found on the open web, on pages.example. Source page: https://pages.example/g/1"
    assert got["approved"]["notes"] == ["Claimed by the page, not checked: free to use, says the page", "A still of a film, series, anime, TV show, game or music video"]
    assert got["approved"]["imgs"] == 1 and got["approved"]["button"] == ["Approve this file"] and got["approved"]["files"] == ["asset-" + "b" * 12 + ".png"] and got["approved"]["anchors"] == 0
    assert got["own"]["calls"] == [["own", "beat7", "b" * 64, None], ["own", "beat7", "b" * 64, "b" * 12]], "the confirm is the first 12 digits of the file's own sha256"
    assert got["own"]["panels"] == 0 and got["own"]["notice"] == "The file for slot beat7 is approved."
    assert got["quiet"] == {"button": False, "sentence": False, "find": True}


CARD = r"""
import { settle, find, all } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";
const HASH = "c".repeat(64);
const MARK = "ZQXAUTHORMARKER";
const calls = [];
let host = "127.0.0.1";
const env = () => ({ project: "p", now: () => new Date("2026-10-12T12:00:00Z"), requestIds: new Set([1]), links: { floor: (a) => `#/f/${a}`, lobby: () => "#/l", open: () => "#/x", parent: () => "#/p" },
  api: { videoCredits: async (p, id) => { calls.push(["credits", p, id]); return { credits: [`"A shop" by ${MARK}, CC BY 4.0`], provided: ["Media provided by shelf (https://shelf.example/terms)"], web: [] }; } },
  reread: async () => null, changed() {}, gone() {}, host: () => host });
const item = (assets) => ({ id: 31, kind: "effect", effect_word: "deliver", title: "Deliver the video", body: ["Platform: instagram", "1 pictures need a credit; the credit text is on this computer's page (sha256 " + "d".repeat(64) + ")",
  "Delivery document sha256 " + HASH].join("\n"), payload: { effect: { assets } }, payload_sha256: HASH, status: "open", actions: ["approved", "rejected"], agent: null, task_id: 9, run_id: null, created_at: "2026-10-12T09:00:00Z" });
const out = {};
const home = createCard(item(1), env()); await settle();
out.home = { text: home.el.textContent.includes(MARK), lines: all(home.el, "ul.wb-dl-rows")[1].children.map((n) => n.textContent), calls: calls.length, body: all(home.el, "ul.wb-dl-rows")[0].textContent.includes(MARK) };
host = "192.168.1.20";
const away = createCard(item(1), env()); await settle();
out.away = { text: away.el.textContent.includes(MARK), calls: calls.length };
host = "127.0.0.1";
const none = createCard(item(0), env()); await settle();
out.none = { text: none.el.textContent.includes(MARK), calls: calls.length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_deliver_card_reads_the_credits_for_this_computers_own_page_only_and_labels_them_text_from_the_library(tmp_path):
    got = run_floor_node(tmp_path, CARD)
    assert got["home"]["lines"] == ['Media provided by shelf (https://shelf.example/terms)', '"A shop" by ZQXAUTHORMARKER, CC BY 4.0'] and got["home"]["calls"] == 1
    assert got["home"]["body"] is False, "the delivery document's own rows never hold the text"
    assert got["away"] == {"text": False, "calls": 1} and got["none"] == {"text": False, "calls": 1}, "no read over the local network, none for a video with no picture"

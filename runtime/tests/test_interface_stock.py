"""The page's part of the licensed pictures of a video (package V9b-3a): the pure model (the closed edits of the media set, the words rule, the layouts' fields) and the Pictures section of
the caption review dialog (views/lobby-captions-model.js, views/lobby-captions.js) under a fake document with a stand-in client: the words, the search that sends nothing until the
person confirms, the candidates with their licence and the page address as plain text, the picks, the fetch, the set to read and approve, the credits, a layout added with its words,
the local network and the policy. Run with Node over the real modules. No browser, no service, no library. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_stock.py
"""
from __future__ import annotations

import pytest

from test_interface_captions import PRELUDE
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
        set: { assets: [{ slot: "beat7", source: "shelf", licence: "cc-by-4.0", width: 1080, height: 1920 }] } };
    },
    videoMediaFile: async (p, t, name) => { calls.push(["file", name]); return new Blob(["png"], { type: "image/png" }); },
    pollJob: async (id) => ({ id, state: o.failed ? "failed" : "done", result: results[id], error: o.failed ? { message: "refused: stock_not_accepted" } : null }),
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
    assert got["own"] == {"text": True, "disabled": True}, "a picture that needs its own approval is approved elsewhere, never with the set"
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

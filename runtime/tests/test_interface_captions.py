"""The page's part of the caption review of a new video (package V1c-2): the pure model (the selection, the closed edit objects, the parameter form's rules) and the
dialog (views/lobby-captions.js) under a fake document with a stand-in client: the words drawn by caption chunk, one exact edit per action, the stale revision, the
catalogue view and "Add an animation", Continue and Render again, the read-only mode, the local network, the policy. Run with Node over the real modules. No browser, no
service, no model. Every name below is invented.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_captions.py
"""
from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from test_interface_lobby import INTERFACE, needs_node, run_node  # noqa: F401  (the Node runner and the fake document the Lobby's tests use)

VIEWS = INTERFACE / "js" / "views"

MODEL = r"""
import * as m from "@JS@/views/lobby-captions-model.js";
const words = [
  { index: 0, text: "Aster", segment: 0 }, { index: 1, text: "Lane", segment: 0 }, { index: 2, text: "opens", segment: 0 },
  { index: 3, text: "a", segment: 1 }, { index: 4, text: "new", segment: 1 }, { index: 5, text: "shop", segment: 2 },
];
const out = {};
out.selection = [m.selection(null, 1, words), m.selection({ from: 0, to: 2 }, 4, words), m.selection({ from: 0, to: 0 }, 99, words), m.selection(null, 99, words)];
out.grow = [m.grow({ from: 0, to: 0 }, words), m.grow({ from: 0, to: 1 }, words), m.grow({ from: 0, to: 2 }, words), m.grow({ from: 4, to: 4 }, words), m.grow({ from: 5, to: 5 }, words)];
out.shrink = [m.shrink({ from: 0, to: 2 }), m.shrink({ from: 1, to: 1 })];
out.same = [m.sameSegment({ from: 0, to: 2 }, words), m.sameSegment({ from: 2, to: 3 }, words), m.sameSegment({ from: 0, to: 9 }, words)];
out.edits = {
  edit: m.editOf("edit", { from: 3, to: 3 }, words, "Northwind"), del: m.editOf("delete", { from: 3, to: 3 }, words, ""),
  merge: m.editOf("merge", { from: 0, to: 1 }, words, "Aster-Lane"), mergeAcross: m.editOf("merge", { from: 2, to: 3 }, words, "x"),
  editMany: m.editOf("edit", { from: 0, to: 1 }, words, "x"), mergeOne: m.editOf("merge", { from: 1, to: 1 }, words, "x"), unknown: m.editOf("split", { from: 1, to: 1 }, words, "x"), none: m.editOf("edit", null, words, "x"),
};
out.others = [m.retakeEdit("r1", true), m.anchorEdit(2, { from: 0, to: 1 }), m.clearAnchor(2), m.overlayEdit(3, true), m.removeAnimation("a1"),
  m.addAnimation("oh:keyword", { text: "Northwind" }, { from: 5, to: 5 })];
const entry = { name: "oh:list", params: { text: { type: "text", required: true, max: 12 }, items: { type: "text", max_items: 4, max: 80 }, size: { type: "number" },
  style: { type: "choice", values: ["plain", "bold"] }, icon: { type: "icon" }, tint: { type: "color" }, weird: { type: "thing" } } };
const fields = m.fieldsOf(entry);
out.fields = { names: fields.map((f) => [f.name, f.type, f.required, f.max, f.maxItems, f.values]), unsupported: fields.unsupported };
out.slot = { unsupported: m.fieldsOf({ params: { photo: { type: "image", required: true }, text: { type: "text" } } }).unsupported,
  length: m.fieldsOf({ params: { photo: { type: "clip", required: true } } }).length,
  optionalSlot: m.fieldsOf({ params: { photo: { type: "image" }, text: { type: "text" } } }).map((f) => f.name), none: m.fieldsOf(null).length };
out.params = {
  missing: m.paramsOf(fields, {}), tooLong: m.paramsOf(fields, { text: "x".repeat(13) }), five: m.paramsOf(fields, { text: "a", items: "1 | 2 | 3 | 4 | 5" }),
  four: m.paramsOf(fields, { text: "a", items: "1 | 2 | 3 | 4" }), number: m.paramsOf(fields, { text: "a", size: "2.5" }), notNumber: m.paramsOf(fields, { text: "a", size: "big" }),
  choice: m.paramsOf(fields, { text: "a", style: "bold" }), badChoice: m.paramsOf(fields, { text: "a", style: "fancy" }),
  optionalLeftOut: m.paramsOf(fields, { text: "  a  ", icon: "", tint: "   " }), withIcon: m.paramsOf(fields, { text: "a", icon: "star" }),
};
out.why = Object.keys(m.WHY_TEXT);
out.canEdit = [m.canEdit("review"), m.canEdit("gate"), m.canEdit(null), m.canEdit(undefined), m.canEdit("done")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_model_selects_words_and_builds_only_the_closed_edits(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["selection"] == [{"from": 1, "to": 1}, {"from": 4, "to": 4}, {"from": 0, "to": 0}, None]
    assert got["grow"] == [{"from": 0, "to": 1}, {"from": 0, "to": 2}, {"from": 0, "to": 2}, {"from": 4, "to": 4}, {"from": 5, "to": 5}], "grow stops at the end of a segment and of the list"
    assert got["shrink"] == [{"from": 0, "to": 1}, {"from": 1, "to": 1}], "shrink never goes below one word"
    assert got["same"] == [True, False, False]
    e = got["edits"]
    assert e["edit"] == {"op": "edit", "index": 3, "text": "Northwind"} and e["del"] == {"op": "delete", "index": 3}
    assert e["merge"] == {"op": "merge", "from": 0, "to": 1, "text": "Aster-Lane"}
    assert e["mergeAcross"] is None and e["editMany"] is None and e["mergeOne"] is None and e["unknown"] is None and e["none"] is None
    assert got["others"] == [{"op": "retake", "id": "r1", "confirmed": True}, {"op": "anchor", "beat": 2, "word_from": 0, "word_to": 1}, {"op": "anchor", "beat": 2, "clear": True},
                             {"op": "overlay", "beat": 3, "dropped": True}, {"op": "animation", "id": "a1", "remove": True},
                             {"op": "animation", "block": "oh:keyword", "params": {"text": "Northwind"}, "word_from": 5, "word_to": 5}]
    assert [f[0] for f in got["fields"]["names"]] == ["text", "items", "size", "style", "icon", "tint"], "a parameter of a type the form cannot draw is left out when it is optional"
    assert got["fields"]["names"][0] == ["text", "text", True, 12, None, []] and got["fields"]["names"][1] == ["items", "text", False, 80, 4, []]
    assert got["fields"]["names"][3] == ["style", "choice", False, None, None, ["plain", "bold"]] and got["fields"]["unsupported"] is False
    assert got["slot"] == {"unsupported": True, "length": 0, "optionalSlot": ["text"], "none": 0}, "a required image or clip cannot be typed"
    p = got["params"]
    assert p["missing"] == {"problem": "text is required."} and p["tooLong"] == {"problem": "text is at most 12 characters."}
    assert p["five"]["problem"].startswith("items has at most 4 parts") and p["four"] == {"params": {"text": "a", "items": "1 | 2 | 3 | 4"}}
    assert p["number"] == {"params": {"text": "a", "size": 2.5}} and p["notNumber"] == {"problem": "size must be a number."}
    assert p["choice"] == {"params": {"text": "a", "style": "bold"}} and p["badChoice"]["problem"].startswith("style must be one of")
    assert p["optionalLeftOut"] == {"params": {"text": "a"}} and p["withIcon"] == {"params": {"text": "a", "icon": "star"}}
    assert got["why"] == ["kind", "no_preset", "slot", "engine", "not_configured"], "the service's five words"
    assert got["canEdit"] == [True, True, False, False, False]


PRELUDE = r"""
import { byClass, click, textOf, find } from "@FAKE@";
import { createCaptionReview, STALE_TEXT, NO_REVIEW, GATE_LINE, READ_ONLY_LINE, TERMINAL_LINE } from "@JS@/views/lobby-captions.js";
import { LAN_MEDIA } from "@JS@/cards/deliver.js";
const proto = Object.getPrototypeOf(document.createElement("dialog"));
proto.showModal = function () { this.open = true; };
proto.close = function () { this.open = false; (this.listeners.close || []).forEach((fn) => fn({})); };
const settle = async () => { for (let i = 0; i < 12; i++) await new Promise((r) => setTimeout(r, 0)); };
const tag = (root, name) => [...root.walk()].filter((n) => n.tagName === name.toUpperCase());
const labels = (root) => tag(root, "button").map(textOf);
const btn = (root, label) => tag(root, "button").find((b) => textOf(b) === label);
const crow = (root, name) => byClass(byClass(root, "wb-cr-catalogue")[0], "wb-cr-item").find((li) => textOf(li).startsWith(name));
const item = (root, start) => byClass(root, "wb-cr-item").find((li) => textOf(li).startsWith(start));
const type = (node, value) => { node.value = value; (node.listeners.input || []).forEach((fn) => fn({})); (node.listeners.change || []).forEach((fn) => fn({})); };
const word = (root, text) => tag(root, "button").find((b) => (b.attrs.class || "").includes("wb-cr-word") && textOf(b) === text);

const WORDS = [
  [0, "Aster", 0], [1, "Lane", 0], [2, "opens", 0], [3, "a", 0], [4, "new", 1], [5, "shop", 1], [6, "in", 1], [7, "Northwynd", 1], [8, "aside", 2],
].map(([index, text, segment]) => ({ index, text, segment, start: index, end: index + 1, estimated: index === 6, edited: index === 5, origin: [index, index], timing_adjusted: false,
  chunk: index === 8 ? null : (index < 3 ? 0 : (index < 6 ? 1 : 2)), left_out: index === 8 ? "unplaced" : null }));
const VIEW = () => ({
  revision: 4, words: structuredClone(WORDS), chunks: [{ chunk: 0, words: [0, 1, 2] }, { chunk: 1, words: [3, 4, 5] }, { chunk: 2, words: [6, 7] }], segments: [], unplaced: [],
  retakes: [{ id: "r1", kind: "repeat", seconds: 1.4, word_from: 2, word_to: 3, keep_from: 3, confirmed: false }],
  beats: [{ beat: 1, preset: "keyword", score: 0.9, matched: true, anchored: false, below_threshold: false, reordered: false, fallback: null, word_from: 0, word_to: 1, dropped: false },
          { beat: 2, preset: "quote", score: 0.3, matched: false, anchored: false, below_threshold: true, reordered: false, fallback: null, word_from: null, word_to: null, dropped: false },
          { beat: 3, preset: "list", score: 1, matched: true, anchored: true, below_threshold: false, reordered: false, fallback: null, word_from: 5, word_to: 6, dropped: true }],
  slots: [], threshold: 0.5, face_box: { x: 1, y: 2, w: 3, h: 4 }, cover_offset_ms: 1200, theme: null,
  animations: [{ id: "a1", block: "oh:keyword", preset: "keyword", params: { text: "Aster" }, word_from: 0, word_to: 1, lost: false, overlaps_beat: true }],
  counts: { words: 9, edited: 1, estimated: 1, timing_adjusted: 0, unplaced: 1, retakes: 1, confirmed: 0, beats: 3, below_threshold: 1, animations: 1 },
});
const CATALOGUE = {
  engine: "ffmpeg", blocks_sha256: "0".repeat(64), animations_max: 12, beats_max: 12, presets: {},
  blocks: [
    { name: "oh:cutaway", kind: "overlay", params: { photo: { type: "image", required: true } }, samples: [{}], use_when: "A picture over the speaker.", natural_duration: 2, engines: ["ffmpeg"], addable: false, why: "slot" },
    { name: "oh:keyword", kind: "overlay", params: { text: { type: "text", required: true, max: 20 }, tint: { type: "color" } }, samples: [{ text: "Northwind", tint: "red" }], use_when: "Stress one word.", natural_duration: 1, engines: ["ffmpeg"], addable: true, why: null },
    { name: "oh:quote", kind: "overlay", params: { quote: { type: "text", required: true, max: 80 } }, samples: [{ quote: "Come and see us" }], use_when: "Show a short quote.", natural_duration: 2, engines: ["ffmpeg"], addable: true, why: null },
  ],
};
let policyList = null;
function make(options = {}) {
  const calls = [];
  const o = { mode: "review", still: null, host: "127.0.0.1", pendings: [{ id: 41, kind: "question", task_id: 900 }], view: VIEW(), ...options };
  let revision = o.view.revision;
  const api = {
    captionsRead: async (p, t) => { calls.push(["read", p, t]); return { task: t, media: "a1b2c3d4", mode: o.mode, still: o.still, view: { ...structuredClone(o.view), revision } }; },
    captionsEdit: async (p, t, rev, edits) => {
      calls.push(["edit", p, t, rev, edits]);
      if (o.refuse) throw Object.assign(new Error(o.refuse), { name: "ApiError", status: 409, word: "refused" });
      revision += 1;
      return { task: t, mode: o.mode, applied: 1, answered: false };
    },
    videoStill: async (p, t) => { calls.push(["still", p, t]); return new Blob(["png"], { type: "image/png" }); },
    videoCatalogue: async (p) => { calls.push(["catalogue", p]); return structuredClone(CATALOGUE); },
    pending: async () => ({ pending: structuredClone(o.pendings) }),
    answer: async (p, id, text) => { calls.push(["answer", p, id, text]); return {}; },
    videoRun: async (p, t) => { calls.push(["run", p, t]); return { job: "j1" }; },
    pollJob: async (id) => { calls.push(["poll", id]); return { id, state: "done", result: o.runResult || { started: true } }; },
  };
  const refreshed = { n: 0 };
  const review = createCaptionReview({ api, project: "proj", entry: () => (o.allowed ? { permissions: { allowed: o.allowed } } : null), host: () => o.host,
    refresh: async () => { refreshed.n += 1; } });
  return { review, calls, refreshed, el: review.el, o };
}
const ALL = ["captions-read", "captions-edit", "video-catalogue", "video-still", "video-run", "answer"];
const out = {};
"""

REVIEW = PRELUDE + r"""
// the words are drawn by caption chunk, a word left out is struck, an estimated or edited one carries its class and title
const r = make();
await r.review.open(900, "review"); await settle();
const rows = byClass(r.el, "wb-cr-words").map((row) => tag(row, "button").map(textOf));
out.rows = rows;
out.classes = { left: (word(r.el, "aside").attrs.class), estimated: word(r.el, "in").attrs.class, edited: word(r.el, "shop").attrs.title };
out.counts = textOf(byClass(r.el, "wb-cr-counts")[0]);
out.title = textOf(tag(r.el, "h3")[0]);
out.terminal = textOf(r.el).includes(TERMINAL_LINE);
out.openAfter = [r.el.open, r.calls[0]];

// edit one word: exactly one edit, the revision the page read, then a new read
click(word(r.el, "a")); await settle();
out.range = textOf(byClass(r.el, "wb-cr-range")[0]);
const field = tag(r.el, "input")[0];
out.prefill = field.value;
type(field, "Northwind");
click(btn(r.el, "Save the word")); await settle();
out.edit = { edit: r.calls.filter((c) => c[0] === "edit"), reads: r.calls.filter((c) => c[0] === "read").length };
out.keptSelection = textOf(byClass(r.el, "wb-cr-range")[0]);

// remove a word
click(btn(r.el, "Remove the word")); await settle();
out.remove = r.calls.filter((c) => c[0] === "edit").slice(-1)[0][4];

// grow, shrink, merge in one segment; the range stops at the end of the segment, so words of two segments cannot be merged by the dialog
click(word(r.el, "Aster")); await settle();
click(btn(r.el, "One more word")); await settle();
out.merge = { range: textOf(byClass(r.el, "wb-cr-range")[0]), buttons: labels(r.el).filter((l) => ["Merge the words", "Save the word", "Remove the word"].includes(l)), prefill: tag(r.el, "input")[0].value };
type(tag(r.el, "input")[0], "Aster-Lane");
click(btn(r.el, "Merge the words")); await settle();
out.merge.sent = r.calls.filter((c) => c[0] === "edit").slice(-1)[0][4];
click(word(r.el, "a")); await settle();
click(btn(r.el, "One more word")); await settle();
out.atSegmentEnd = { range: textOf(byClass(r.el, "wb-cr-range")[0]), merge: labels(r.el).includes("Merge the words") };
click(btn(r.el, "One word less")); click(btn(r.el, "One word less")); await settle();
out.shrunk = textOf(byClass(r.el, "wb-cr-range")[0]);

// retakes, beats and animations send the exact objects
click(btn(item(r.el, "Retake r1"), "Cut it")); await settle();
click(word(r.el, "Aster")); click(btn(r.el, "One more word")); await settle();
click(btn(item(r.el, "Beat 2"), "Anchor to the selected words")); await settle();
click(btn(item(r.el, "Beat 3"), "Clear the anchor")); await settle();
click(btn(item(r.el, "Beat 1"), "Drop the overlay")); await settle();
click(btn(item(r.el, "Beat 3"), "Keep the overlay")); await settle();
click(btn(item(r.el, "oh:keyword"), "Remove")); await settle();
out.sent = r.calls.filter((c) => c[0] === "edit").slice(-6).map((c) => { if (c[4].length !== 1) throw new Error("one edit per call"); return c[4][0]; });
out.lines = { retake: textOf(item(r.el, "Retake r1")), beat1: textOf(item(r.el, "Beat 1")), beat2: textOf(item(r.el, "Beat 2")), beat3: textOf(item(r.el, "Beat 3")), animation: textOf(item(r.el, "oh:keyword")) };
out.beat3Buttons = labels(item(r.el, "Beat 3"));
out.revisions = r.calls.filter((c) => c[0] === "edit").map((c) => c[3]);
out.refusedBefore = r.calls.filter((c) => c[0] === "edit").length;

// a view whose retake is already cut offers Keep it
const cut = make({ view: { ...VIEW(), retakes: [{ id: "r1", kind: "repeat", seconds: 1.4, word_from: 2, word_to: 3, keep_from: 3, confirmed: true }] } });
await cut.review.open(900, "review"); await settle();
click(btn(item(cut.el, "Retake r1"), "Keep it")); await settle();
out.keep = { text: textOf(item(cut.el, "Retake r1")), sent: cut.calls.filter((c) => c[0] === "edit")[0][4] };

// a refusal shows as it came and reads nothing again; the dialog stays
const refuse = make({ refuse: "refused: bad_text edits[0].text" });
await refuse.review.open(900, "review"); await settle();
click(word(refuse.el, "a")); await settle();
click(btn(refuse.el, "Save the word")); await settle();
out.refusal = { text: textOf(byClass(refuse.el, "wb-notice-card")[0]), reads: refuse.calls.filter((c) => c[0] === "read").length, buttonsBack: labels(refuse.el).includes("Save the word") };

// a stale revision is read again and said
const stale = make({ refuse: "refused: stale_revision revision" });
await stale.review.open(900, "review"); await settle();
click(word(stale.el, "a")); await settle();
click(btn(stale.el, "Save the word")); await settle();
out.stale = { reads: stale.calls.filter((c) => c[0] === "read").length, notice: textOf(byClass(stale.el, "wb-cr-notice")[0]), error: byClass(stale.el, "wb-notice-card").length, edits: stale.calls.filter((c) => c[0] === "edit").length, selection: byClass(stale.el, "wb-cr-range").length };
out.staleText = STALE_TEXT;

// a hostile word is text
const hostile = make({ view: { ...VIEW(), words: WORDS.map((w) => (w.index === 0 ? { ...w, text: "<img src=x onerror=alert(1)>" } : w)) } });
await hostile.review.open(900, "review"); await settle();
out.hostile = { elements: tag(hostile.el, "img").length + tag(hostile.el, "script").length, text: textOf(byClass(hostile.el, "wb-cr-words")[0]).startsWith("<img src=x onerror=alert(1)>") };

// a failed read shows its sentence and Close
const broken = createCaptionReview({ api: { captionsRead: async () => { throw Object.assign(new Error("That task is not a video."), { name: "ApiError", status: 409, word: "refused" }); } }, project: "proj", entry: () => null, host: () => "127.0.0.1" });
await broken.open(7, "review"); await settle();
out.failedRead = { text: textOf(byClass(broken.el, "wb-notice-card")[0]), buttons: labels(broken.el) };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_dialog_draws_the_words_by_chunk_and_sends_exactly_one_closed_edit_per_action(tmp_path):
    got = run_node(tmp_path, REVIEW)
    assert got["rows"] == [["Aster", "Lane", "opens"], ["a", "new", "shop"], ["in", "Northwynd"], ["aside"]], "the chunks, then the words left out of the captions"
    assert "wb-cr-left-out" in got["classes"]["left"] and "wb-cr-estimated" in got["classes"]["estimated"] and "edited" in got["classes"]["edited"]
    assert got["counts"] == "9 words, 1 edited, 1 retakes, 3 beats, 1 animations" and got["title"] == "Check the captions" and got["terminal"] is True
    assert got["openAfter"] == [True, ["read", "proj", 900]]
    assert got["range"] == "Words 3 to 3" and got["prefill"] == "a"
    assert got["edit"]["edit"] == [["edit", "proj", 900, 4, [{"op": "edit", "index": 3, "text": "Northwind"}]]] and got["edit"]["reads"] == 2, "one edit, then one new read"
    assert got["keptSelection"] == "Words 3 to 3", "the selection stays while its words still exist"
    assert got["remove"] == [{"op": "delete", "index": 3}]
    assert got["merge"]["range"] == "Words 0 to 1" and got["merge"]["buttons"] == ["Merge the words"] and got["merge"]["prefill"] == "Aster Lane"
    assert got["merge"]["sent"] == [{"op": "merge", "from": 0, "to": 1, "text": "Aster-Lane"}]
    assert got["atSegmentEnd"] == {"range": "Words 3 to 3", "merge": False}, "one more word stops at the end of the segment: no merge across two segments"
    assert got["shrunk"] == "Words 3 to 3", "never below one word"
    assert got["sent"] == [{"op": "retake", "id": "r1", "confirmed": True}, {"op": "anchor", "beat": 2, "word_from": 0, "word_to": 1}, {"op": "anchor", "beat": 3, "clear": True},
                           {"op": "overlay", "beat": 1, "dropped": True}, {"op": "overlay", "beat": 3, "dropped": False}, {"op": "animation", "id": "a1", "remove": True}]
    assert got["revisions"] == [4, 5, 6, 7, 8, 9, 10, 11, 12][: len(got["revisions"])] and len(got["revisions"]) == got["refusedBefore"], "each edit names the revision of the read before it"
    assert got["lines"]["retake"].startswith("Retake r1: repeat, 1.4 s, words 2 to 3, kept") and got["lines"]["animation"].startswith("oh:keyword over words 0 to 1, overlaps beat 1")
    assert "anchored over words 5 to 6" in got["lines"]["beat3"] and "overlay dropped" in got["lines"]["beat3"] and "below the threshold" in got["lines"]["beat2"] and "matched over words 0 to 1" in got["lines"]["beat1"]
    assert "Clear the anchor" in got["beat3Buttons"] and "Keep the overlay" in got["beat3Buttons"]
    assert ", cut" in got["keep"]["text"] and got["keep"]["sent"] == [{"op": "retake", "id": "r1", "confirmed": False}]
    assert got["refusal"] == {"text": "refused: bad_text edits[0].text", "reads": 1, "buttonsBack": True}, "a refusal is shown as it came and nothing is retried"
    assert got["stale"]["reads"] == 2 and got["stale"]["notice"] == got["staleText"] == "The captions changed; they were read again." and got["stale"]["error"] == 0
    assert got["stale"]["edits"] == 1 and got["stale"]["selection"] == 0, "a stale revision reads again once and drops the selection"
    assert got["hostile"] == {"elements": 0, "text": True}
    assert got["failedRead"] == {"text": "That task is not a video.", "buttons": ["Close"]}


ADD = PRELUDE + r"""
const r = make();
await r.review.open(900, "review"); await settle();
out.before = { buttons: labels(r.el).filter((l) => l.includes("animation")) };
click(btn(r.el, "Add an animation")); await settle();
out.catalogueCalls = r.calls.filter((c) => c[0] === "catalogue").length;
const rows = byClass(r.el, "wb-cr-catalogue")[0].children.filter((n) => n.tagName === "LI").map(textOf);
out.rows = rows;
out.useButtons = byClass(r.el, "wb-cr-catalogue")[0].children.filter((n) => n.tagName === "LI").map((li) => labels(li));
// no selection: the form says so and the button is disabled
click(btn(crow(r.el, "oh:keyword"), "Use this")); await settle();
out.noSelection = { text: textOf(byClass(r.el, "wb-cr-form")[0]).includes("Select the words first"), disabled: btn(r.el, "Add the animation").disabled };
// select words, then fill the form
click(word(r.el, "shop")); await settle();
out.formStillOpen = byClass(r.el, "wb-cr-form").length;
out.over = textOf(byClass(r.el, "wb-cr-form")[0]).includes("Over words 5 to 5");
const fields = tag(byClass(r.el, "wb-cr-form")[0], "input");
out.fieldCount = fields.length;
out.maxlength = fields[0].attrs.maxlength;
out.hint = textOf(byClass(r.el, "wb-cr-form")[0]).includes("Optional; the renderer checks it");
// a problem sends nothing
click(btn(r.el, "Add the animation")); await settle();
out.problem = { text: textOf(byClass(r.el, "wb-cr-problem")[0]), edits: r.calls.filter((c) => c[0] === "edit").length };
type(tag(byClass(r.el, "wb-cr-form")[0], "input")[0], "Northwind");
click(btn(r.el, "Add the animation")); await settle();
out.sent = r.calls.filter((c) => c[0] === "edit").map((c) => c[4]);
out.closedAfter = { form: byClass(r.el, "wb-cr-form").length, catalogue: byClass(r.el, "wb-cr-catalogue").length };
// the catalogue is read once per open
click(btn(r.el, "Add an animation")); await settle();
out.catalogueCallsAfter = r.calls.filter((c) => c[0] === "catalogue").length;
click(btn(r.el, "Hide the catalogue")); await settle();
click(btn(r.el, "Add an animation")); await settle();
out.catalogueCallsAgain = r.calls.filter((c) => c[0] === "catalogue").length;
// at the maximum the button gives way to a line
const full = make({ view: { ...VIEW(), counts: { ...VIEW().counts, animations: 12 } } });
await full.review.open(900, "review"); await settle();
click(btn(full.el, "Add an animation")); await settle();
out.full = { text: textOf(full.el).includes("the most animations it can have (12)"), uses: labels(full.el).includes("Use this") };
console.log(JSON.stringify(out));
"""


@needs_node
def test_add_an_animation_shows_the_catalogue_as_text_and_sends_one_animation_edit(tmp_path):
    got = run_node(tmp_path, ADD)
    assert got["before"]["buttons"] == ["Add an animation"]
    assert got["catalogueCalls"] == 1
    names = [re.match(r"oh:[a-z]+", r).group(0) for r in got["rows"]]
    assert names == ["oh:keyword", "oh:quote", "oh:cutaway"], "the addable blocks first"
    assert "Stress one word." in got["rows"][0] and "Sample: Northwind, red" in got["rows"][0] and "Show a short quote." in got["rows"][1] and "Sample: Come and see us" in got["rows"][1]
    assert "It needs a picture or a clip, which comes later." in got["rows"][2] and "Sample" not in got["rows"][2]
    assert got["useButtons"] == [["Use this"], ["Use this"], []], "a block that is not addable has no button"
    assert got["noSelection"] == {"text": True, "disabled": True}
    assert got["formStillOpen"] == 1 and got["over"] is True and got["fieldCount"] == 2 and got["maxlength"] == "20" and got["hint"] is True
    assert got["problem"] == {"text": "text is required.", "edits": 0}
    assert got["sent"] == [[{"op": "animation", "block": "oh:keyword", "params": {"text": "Northwind"}, "word_from": 5, "word_to": 5}]]
    assert got["closedAfter"] == {"form": 0, "catalogue": 0}
    assert got["catalogueCallsAfter"] == 1 and got["catalogueCallsAgain"] == 1, "the catalogue is read once per open"
    assert got["full"] == {"text": True, "uses": False}


FOOTER = PRELUDE + r"""
// Continue: answer, then run, then poll, in that order, then close and refresh
const a = make({ allowed: null });
await a.review.open(900, "review"); await settle();
click(btn(a.el, "Continue: render the video")); await settle();
out.continue = { order: a.calls.filter((c) => ["answer", "run", "poll"].includes(c[0])), refreshed: a.refreshed.n, open: a.el.open };
// with no open review decision nothing is sent
const none = make({ pendings: [{ id: 5, kind: "effect", task_id: 900 }, { id: 6, kind: "question", task_id: 901 }] });
await none.review.open(900, "review"); await settle();
click(btn(none.el, "Continue: render the video")); await settle();
out.none = { sent: none.calls.filter((c) => ["answer", "run", "poll"].includes(c[0])), text: textOf(byClass(none.el, "wb-cr-notice")[0]), open: none.el.open, noReview: NO_REVIEW };
// a run that did not start keeps the dialog open with the sentence, and the list is refreshed
const held = make();
held.o.runResult = { started: false, reason: "no post file" };
await held.review.open(900, "review"); await settle();
click(btn(held.el, "Continue: render the video")); await settle();
out.held = { open: held.el.open, text: textOf(byClass(held.el, "wb-cr-notice")[0]), refreshed: held.refreshed.n };
// mode gate: after an edit, the line and Render again; before an edit neither
const g = make({ mode: "gate" });
await g.review.open(900, "gate"); await settle();
out.gateBefore = { labels: labels(g.el).filter((l) => ["Continue: render the video", "Render again"].includes(l)), line: textOf(g.el).includes(GATE_LINE) };
click(word(g.el, "a")); await settle();
click(btn(g.el, "Save the word")); await settle();
out.gateAfter = { labels: labels(g.el).filter((l) => ["Continue: render the video", "Render again"].includes(l)), line: textOf(g.el).includes(GATE_LINE) };
click(btn(g.el, "Render again")); await settle();
out.render = g.calls.filter((c) => ["run", "poll"].includes(c[0]));
out.gateLine = GATE_LINE;
// mode null: read-only, no edit control at all
const ro = make({ mode: null });
await ro.review.open(900, "review"); await settle();
out.readOnly = { labels: labels(ro.el), line: textOf(ro.el).includes(READ_ONLY_LINE), words: tag(ro.el, "span").filter((n) => (n.attrs.class || "").includes("wb-cr-word")).length, mode: "answer wins" };
// the answer's mode wins over the argument
const wins = make({ mode: null });
await wins.review.open(900, "gate"); await settle();
out.winsLabels = labels(wins.el);
// the policy
const noEdit = make({ allowed: ALL.filter((x) => x !== "captions-edit") });
await noEdit.review.open(900, "review"); await settle();
out.noEdit = labels(noEdit.el);
const noAnswer = make({ allowed: ALL.filter((x) => x !== "answer") });
await noAnswer.review.open(900, "review"); await settle();
out.noAnswer = labels(noAnswer.el).filter((l) => l.startsWith("Continue"));
const noRun = make({ mode: "gate", allowed: ALL.filter((x) => x !== "video-run") });
await noRun.review.open(900, "gate"); await settle();
click(word(noRun.el, "a")); await settle();
click(btn(noRun.el, "Save the word")); await settle();
out.noRun = { labels: labels(noRun.el).filter((l) => l.startsWith("Render")), continues: labels(noRun.el).filter((l) => l.startsWith("Continue")) };
const noRunReview = make({ allowed: ALL.filter((x) => x !== "video-run") });
await noRunReview.review.open(900, "review"); await settle();
out.noRunReview = labels(noRunReview.el).filter((l) => l.startsWith("Continue"));
const editOnly = make({ allowed: ["captions-read", "captions-edit", "video-catalogue"] });
await editOnly.review.open(900, "review"); await settle();
click(word(editOnly.el, "a")); await settle();
out.editOnly = labels(editOnly.el).includes("Save the word");
// the click path asks again: the policy changes after the control was drawn
const ask = make({ allowed: ALL.slice() });
await ask.review.open(900, "review"); await settle();
click(word(ask.el, "a")); await settle();
ask.o.allowed = ALL.filter((x) => x !== "captions-edit");
click(btn(ask.el, "Save the word")); await settle();
out.askAgain = ask.calls.filter((c) => c[0] === "edit").length;
const askContinue = make({ allowed: ALL.slice() });
await askContinue.review.open(900, "review"); await settle();
askContinue.o.allowed = ALL.filter((x) => x !== "answer");
click(btn(askContinue.el, "Continue: render the video")); await settle();
out.askContinue = askContinue.calls.filter((c) => ["answer", "run"].includes(c[0])).length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_continue_answers_then_runs_the_gate_offers_render_again_and_a_null_mode_is_read_only(tmp_path):
    got = run_node(tmp_path, FOOTER)
    assert got["continue"]["order"] == [["answer", "proj", 41, "continue"], ["run", "proj", 900], ["poll", "j1"]], "answer, then run, then poll"
    assert got["continue"]["refreshed"] == 1 and got["continue"]["open"] is False
    assert got["none"]["sent"] == [] and got["none"]["text"] == got["none"]["noReview"] == "There is no review waiting for this video." and got["none"]["open"] is True
    assert got["gateBefore"] == {"labels": [], "line": False}, "at the delivery card neither Continue nor Render again before an edit"
    assert got["held"] == {"open": True, "text": "The video is ready to run: no post file", "refreshed": 1}
    assert got["gateAfter"] == {"labels": ["Render again"], "line": True}
    assert got["render"] == [["run", "proj", 900], ["poll", "j1"]]
    assert got["readOnly"]["labels"] == ["Close"] and got["readOnly"]["line"] is True and got["readOnly"]["words"] == 9, "a read-only review draws no button but Close and its words are plain text"
    assert got["winsLabels"] == ["Close"], "the service's mode wins over the one the page asked for"
    assert not any(l in got["noEdit"] for l in ("Cut it", "Keep it", "Remove", "Add an animation", "Drop the overlay", "Save the word")), "no edit control without captions-edit"
    assert "Continue: render the video" in got["noEdit"], "Continue needs answer and video-run, not captions-edit"
    assert got["noAnswer"] == [] and got["noRunReview"] == []
    assert got["noRun"] == {"labels": [], "continues": []}
    assert got["editOnly"] is True
    assert got["askAgain"] == 0 and got["askContinue"] == 0, "every click path asks the policy again"


STILL = PRELUDE + r"""
let revoked = 0;
const realRevoke = URL.revokeObjectURL.bind(URL);
URL.revokeObjectURL = (u) => { revoked += 1; realRevoke(u); };
const loop = make({ still: "still", host: "localhost" });
await loop.review.open(900, "review"); await settle();
const img = tag(loop.el, "img")[0];
out.loopback = { calls: loop.calls.filter((c) => c[0] === "still"), src: img && img.attrs.src.slice(0, 5), alt: img && img.attrs.alt };
click(word(loop.el, "a")); await settle();
click(btn(loop.el, "Save the word")); await settle();
out.reread = { stills: loop.calls.filter((c) => c[0] === "still").length, revoked };
click(btn(loop.el, "Close")); await settle();
out.closed = { revoked, open: loop.el.open };
// an IPv6 loopback with brackets counts too
const six = make({ still: "still", host: "[::1]" });
await six.review.open(900, "review"); await settle();
out.six = six.calls.filter((c) => c[0] === "still").length;
// the local network: no request for the still, the line says why, the edits still work
const lan = make({ still: "still", host: "192.168.1.20" });
await lan.review.open(900, "review"); await settle();
out.lan = { stills: lan.calls.filter((c) => c[0] === "still").length, images: tag(lan.el, "img").length, line: textOf(lan.el).includes(LAN_MEDIA) };
click(word(lan.el, "a")); await settle();
click(btn(lan.el, "Save the word")); await settle();
out.lan.edits = lan.calls.filter((c) => c[0] === "edit").length;
// an unknown host fails closed
const unknown = make({ still: "still", host: "" });
await unknown.review.open(900, "review"); await settle();
out.unknown = unknown.calls.filter((c) => c[0] === "still").length;
// no still in the answer: nothing is asked and no line
const bare = make({ still: null, host: "192.168.1.20" });
await bare.review.open(900, "review"); await settle();
out.bare = { stills: bare.calls.filter((c) => c[0] === "still").length, line: textOf(bare.el).includes(LAN_MEDIA) };
// without video-still: no request
const policy = make({ still: "still", allowed: ALL.filter((x) => x !== "video-still") });
await policy.review.open(900, "review"); await settle();
out.policy = policy.calls.filter((c) => c[0] === "still").length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_still_comes_only_from_this_computers_own_page_and_is_revoked(tmp_path):
    got = run_node(tmp_path, STILL)
    assert got["loopback"]["calls"] == [["still", "proj", 900]] and got["loopback"]["src"] == "blob:" and got["loopback"]["alt"] == "The still of the recording, with the face box"
    assert got["reread"]["stills"] == 2 and got["reread"]["revoked"] >= 1, "the still is read again with the captions and the earlier one is revoked"
    assert got["closed"]["revoked"] > got["reread"]["revoked"] and got["closed"]["open"] is False
    assert got["six"] == 1
    assert got["lan"] == {"stills": 0, "images": 0, "line": True, "edits": 1}
    assert got["unknown"] == 0 and got["bare"] == {"stills": 0, "line": False} and got["policy"] == 0


WIRE = r"""
import { setToken } from "@JS@/token.js";
const seen = [];
globalThis.fetch = async (url, init) => { seen.push([init.method, url, init.body ? JSON.parse(init.body) : null]); return { ok: true, status: 200, json: async () => ({}) }; };
setToken("t".repeat(40));
const api = await import("@JS@/api.js");
if (typeof api.captionsEdit !== "function") { console.log(JSON.stringify(null)); } else {
  await api.captionsEdit("abc", 900, 4, [{ op: "edit", index: 3, text: "Northwind" }]);
  console.log(JSON.stringify(seen));
}
"""


@needs_node
def test_the_client_sends_the_edit_as_a_json_text_when_the_client_has_the_call(tmp_path):
    """The client's `captionsEdit` is V1c-1's. Once it is in the page, the body is `{revision, edits}` with `edits` a JSON text, as the route takes it."""
    got = run_node(tmp_path, WIRE)
    if got is None:
        pytest.skip("js/api.js has no captionsEdit yet (V1c-1 not merged)")
    assert got == [["POST", "/api/v1/projects/abc/videos/900/captions", {"revision": 4, "edits": '[{"op":"edit","index":3,"text":"Northwind"}]'}]]


def test_the_modules_are_text_only_store_nothing_and_load_nothing_from_another_host():
    for name in ("lobby-captions.js", "lobby-captions-model.js"):
        source = (VIEWS / name).read_text(encoding="utf-8")
        assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|localStorage|sessionStorage|\.style\b|https?://|\bfetch\(", source), name
        assert not re.search(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b|\b(?:rgba?|hsla?)\(", source), name
        assert not re.search(r"\bdata:", source), f"{name}: an image is shown only from a blob URL"
    dialog = (VIEWS / "lobby-captions.js").read_text(encoding="utf-8")
    assert "permissions.js" in dialog and re.search(r"\bmay\(", dialog)
    for op in ("captions-edit", "video-run", "answer", "video-still", "video-catalogue"):
        assert f'may("{op}")' in dialog, op
    assert "createObjectURL" in dialog and "revokeObjectURL" in dialog
    assert "captionsEdit(" in dialog and "videoRun(" in dialog and "answer(" in dialog


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_node_check_passes_on_both_modules():
    for name in ("lobby-captions.js", "lobby-captions-model.js"):
        done = subprocess.run([shutil.which("node"), "--check", str(VIEWS / name)], capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"{name}: {done.stderr}"


def test_the_stylesheet_has_the_review_rules_in_tokens_with_the_phone_band():
    css = (INTERFACE / "css" / "lobby.css").read_text(encoding="utf-8")
    for selector in (".wb-cr-dialog", ".wb-cr-words", ".wb-cr-word", ".wb-cr-left-out", ".wb-cr-estimated", ".wb-cr-edited", ".wb-cr-list", ".wb-cr-catalogue", ".wb-cr-form", ".wb-cr-footer"):
        assert selector in css, selector
    rules = "\n".join(line for line in css.splitlines() if ".wb-cr-" in line)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", rules), "tokens only"
    assert re.search(r"width: 100vw; height: 100dvh; max-width: none; max-height: none; margin: 0", css), "the dialog fills the screen on a phone"
    assert re.search(r"\.wb-cr-word \{ min-height: 44px", css)
    assert not [n for n in re.findall(r"font-size: (\d+)px", rules) if int(n) < 12]

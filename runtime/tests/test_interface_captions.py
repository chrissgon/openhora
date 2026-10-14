"""The caption review page (interface/js/floor/captions-view.js and captions-model.js, the client functions of js/api.js that read and write it, and its place in
the Tasks tab row of a recording's code task). Run under Node with a fake document and a fake client: no browser, no service, no network. The view the page
draws is the real one of runtime/captions.py (`view`, over the fictional transcript of pipeline_kit.py), and every edit the page sends is applied to that same
state by the real `apply_edits`, so the page and the operation cannot drift apart. The routes themselves are tested in test_media_pipeline_channels.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_captions.py
"""
from __future__ import annotations

import copy
import json
import re

import pytest

import pipeline_kit as kit
import standin_tree as st
from interface_css import css_file
from test_interface_floor import INTERFACE, JS, needs_node, run_node
from test_interface_phone_sheet import media_blocks

cap = st.load("captions")
media = st.load("media")

VIEW_FILE = JS / "floor" / "captions-view.js"
MODEL_FILE = JS / "floor" / "captions-model.js"
RID = "0123456789abcdef"
PROJECT = "0123456789ab"


def documents():
    """(edited transcript, review, proposal edit list, proposal beats): the first four words are said inside the opening silence (timing adjusted),
    the tenth has no place, the repeated sentence is a retake proposal, beat 4 and beat 5 are below the threshold, beat 7 needs a picture."""
    transcript, _ = kit.build_transcript(misplace=True)
    n = len(transcript["words"])
    chunks = [[i, min(i + 3, n - 4)] for i in range(0, n - 3, 4)]       # the last three words are in no chunk
    edl = {"proposals": [{"id": "retake-1", "kind": "repeat", "word_from": 34, "word_to": 40, "keep_from": 41, "seconds": 2.4, "confirmed": False}],
           "captions": {"chunks": chunks},
           "normalisation": {"retimed_words": [{"index": 0, "from": [0.2, 0.45], "to": [1.4, 1.5]}, {"index": 1, "from": [0.5, 0.85], "to": [1.6, 1.7]}],
                             "unplaced_words": [{"index": 9, "start": 3.1, "end": 3.2}], "dropped_segments": []}}
    beats = {"threshold": 0.6,
             "slots": [{"slot": "beat7", "beat": 7, "param": "asset", "type": "image", "description": "a screenshot of the budgeting dashboard"}],
             "report": [{"beat": 1, "preset": None},
                        {"beat": 3, "preset": "keyword", "score": 0.95, "matched": True, "reordered": False, "word_from": 20, "word_to": 27},
                        {"beat": 4, "preset": "list", "score": 0.5, "matched": True, "reordered": False, "word_from": 42, "word_to": 50},
                        {"beat": 5, "preset": "number", "score": 0.3, "matched": False, "reordered": False, "word_from": None, "word_to": None},
                        {"beat": 6, "preset": "quote", "score": 0.9, "matched": True, "reordered": True, "word_from": 60, "word_to": 66},
                        {"beat": 7, "preset": "cutaway", "score": 0.88, "matched": True, "reordered": False, "word_from": 70, "word_to": 75}]}
    return cap.start_edited(transcript), cap.new_review(), edl, beats


def view_of(edited, review, edl, beats, assets=None):
    return cap.view(edited, review, edl, beats, assets or {"beat7": None})


def fixture_view():
    edited, review, edl, beats = documents()
    return {"recording": RID, "platform": "instagram", "task": 5, "steps": steps("review"), "editable": True, "language": "pt", "failure": None, "sent_back": None,
            **view_of(edited, review, edl, beats)}


def steps(at):
    names = ["transcribe", "analyse", "retakes", "align-proposal", "review", "remap", "base", "align", "check", "render", "cover", "approval"]
    out = {}
    for name in names:
        out[name] = "done" if names.index(name) < names.index(at) else ("waiting" if name == at else "pending")
    return out


def fixture_media(at="review", failure=None):
    sid = media.slot_id(RID, "beat7")
    return {"id": RID, "status": "open", "slots": {sid: {"key": "beat7", "asset": None}},
            "pipeline": {"task": 5, "request": 1, "platform": "instagram", "steps": steps(at), "next": at, "failure": failure}}, sid


PRELUDE = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createCaptionsView } from "@JS@/floor/captions-view.js";
import { ApiError } from "@JS@/api.js";

const VIEW = @VIEW@;
const MEDIA = @MEDIA@;
const SLOT_ID = "@SLOT@";
const clone = (v) => JSON.parse(JSON.stringify(v));
const text = (n) => n.textContent;
const off = (n) => (n ? "disabled" in n.attrs : null);
const calls = [];
const script = { view: clone(VIEW), media: clone(MEDIA), readError: null, editError: null, next: null, jobError: null };
const api = {
  captionsRead: async () => { calls.push(["read"]); if (script.readError) throw script.readError; return clone(script.view); },
  mediaList: async (p, o) => { calls.push(["media", o.recording]); return { recordings: [clone(script.media)] }; },
  captionsEdit: async (p, rid, o) => {
    calls.push(["edit", o.revision, clone(o.edits)]);
    if (script.editError) throw script.editError;
    return script.next ? script.next(o) : { ...clone(script.view), revision: o.revision + 1, applied: { edited: 0, split: 0, merged: 0, deleted: 0 } };
  },
  captionsDone: async (p, rid, o) => { calls.push(["done", clone(o)]); return { job: 7, state: "running", op: "captions-done" }; },
  prepareAgain: async (p, rid, step) => { calls.push(["again", rid, step]); return { job: 8, state: "running" }; },
  pollJob: async (id, every, o) => { calls.push(["poll", id]); if (o && o.onUpdate) o.onUpdate({ state: "running" }); await settle(); return { state: "done", result: { ok: true } }; },
  uploadMedia: async (p, file, o) => { calls.push(["upload", o.recording, o.slot, file.name]); o.onProgress(5, 10); return { recording: o.recording, kind: "asset", slot: o.slot, bytes: file.size }; },
};
const make = (extra = {}) => createCaptionsView({ project: "@PROJECT@", recording: "@RID@", api, loopback: true, pollEvery: 200, ...extra });
const typeInto = (node, value) => { node.value = value; (node.listeners.input || []).forEach((fn) => fn()); };
const word = (root, i) => find(root, `[data-index="${i}"]`);
const press = async (node) => { node.click(); await settle(); };
const out = {};
"""


def run(tmp_path, body, *, view=None, media_doc=None, at="review", failure=None):
    shown = view if view is not None else fixture_view()
    m, sid = fixture_media(at, failure)
    if media_doc is not None:
        m = media_doc
    script = (PRELUDE + body).replace("@VIEW@", json.dumps(shown)).replace("@MEDIA@", json.dumps(m)).replace("@SLOT@", sid)
    script = script.replace("@PROJECT@", PROJECT).replace("@RID@", RID)
    return run_node(tmp_path, script)


# --- the pure model: the words, the refusals, the closed edit objects ---------------------------------------------------------------------------

MODEL = r"""
import * as m from "@JS@/floor/captions-model.js";
const out = {};
const view = @VIEW@;
const groups = m.groups(view);
out.groups = { count: groups.length, first: groups[0].words.map((w) => w.index), last: groups[groups.length - 1], retakeWords: groups.flatMap((g) => g.words).filter((w) => w.retake).map((w) => w.index) };
out.marks = [m.marks({ retake: "confirmed" }), m.marks({ retake: "proposed", timing_adjusted: true }), m.marks({ estimated: true, edited: true, left_out: "unplaced" }), m.marks({})];
out.retakes = m.retakeRows(view);
out.beats = m.beatRows(view).map((b) => ({ beat: b.beat, flags: b.flags, needsLook: b.needsLook, span: b.span, text: b.text }));
const sel = (s, i, e) => m.selectionAfter(s, i, e);
out.selection = [sel(null, 3), sel({ from: 3, to: 3 }, 6), sel({ from: 3, to: 3 }, 3), sel({ from: 3, to: 6 }, 4), sel({ from: 3, to: 6 }, 9), sel({ from: 3, to: 3 }, 1, true), sel({ from: 3, to: 6 }, 9, true)];
out.within = [m.selectionWithin({ from: 3, to: 90 }, 85), m.selectionWithin({ from: 90, to: 91 }, 85), m.selectionWithin(null, 85)];
out.edits = [m.edit.word(3, "gonna"), m.edit.split(3, ["a", "b"]), m.edit.merge(3, 5), m.edit.merge(3, 5, "novo"), m.edit.remove(4, 6), m.edit.retake("retake-1", true), m.edit.anchor(5, 40, 44),
  m.edit.clearAnchor(5), m.edit.overlay(3, true), m.edit.slot("beat7", "none"), m.edit.slot("beat7", null), m.edit.faceBox({ x: 1, y: 2, w: 3, h: 4 }), m.edit.clearFaceBox(), m.edit.cover(1500)];
out.keys = m.EDIT_KEYS;
out.face = [m.faceBoxAt(0.5, 0.5, 420), m.faceBoxAt(0, 0, 420), m.faceBoxAt(1, 1, 420), m.faceBoxAt(0.5, 0.5, 5000)];
out.faceFields = [m.faceBoxFromFields({ x: "10", y: "20", w: "300", h: "300" }), m.faceBoxFromFields({ x: "10", y: "20", w: "0", h: "300" }), m.faceBoxFromFields({ x: "900", y: "20", w: "300", h: "300" }), m.faceBoxFromFields({ x: "a", y: "1", w: "1", h: "1" }), m.faceBoxFromFields({ x: "", y: "1", w: "1", h: "1" })];
out.cover = [m.coverFromSeconds("1.5"), m.coverFromSeconds("1,5"), m.coverFromSeconds("0"), m.coverFromSeconds("-1"), m.coverFromSeconds("abc"), m.coverFromSeconds(""), m.coverFromSeconds("700")];
out.texts = [m.faceBoxText(null), m.faceBoxText({ x: 10, y: 20, w: 300, h: 300 }), m.coverText(0), m.coverText(1500), m.seconds(12.34), m.clock(75.2), m.clock(-1), m.scoreText(0.7234), m.scoreText(null)];
const err = (message, status = 409) => ({ name: "ApiError", status, message });
out.reasons = [m.reasonOf(err("refused: stale_revision revision")), m.reasonOf(err("refused: merge_across_segments edits[0]")), m.reasonOf(err("refused: something_new edits[1]")), m.reasonOf(err("the pipeline is busy")),
  m.reasonOf({ name: "ApiError", status: 0, message: "x" }), m.reasonOf(err("no", 404)), m.reasonOf(new Error("boom")), m.reasonOf(null)];
out.steps = [m.stepRows({ transcribe: "done", review: "waiting", approval: "pending" }), m.isRunning(@STEPS_RUNNING@), m.isRunning(@STEPS_REVIEW@), m.isRunning(null)];
out.done = [m.doneBlock(view), m.doneBlock({ slots: [{ file: { stale: false }, choice: null }, { file: null, choice: "none" }] }), m.doneBlock({ slots: [{ file: null, choice: null }, { file: null, choice: null }] })];
console.log(JSON.stringify(out));
"""


def run_model(tmp_path):
    body = MODEL.replace("@STEPS_RUNNING@", json.dumps(steps("base"))).replace("@STEPS_REVIEW@", json.dumps(steps("review")))
    body = body.replace("@VIEW@", json.dumps(fixture_view()))
    return run_node(tmp_path, body)


@needs_node
def test_the_model_groups_the_words_marks_them_and_builds_the_rows_from_the_real_view(tmp_path):
    got = run_model(tmp_path)
    groups = got["groups"]
    assert groups["count"] > 10 and groups["first"] == [0, 1, 2, 3] and groups["last"]["chunk"] is None and len(groups["last"]["words"]) == 3, "the words in no chunk are their own group"
    assert groups["retakeWords"] == list(range(34, 41)), "the words a retake would drop are marked"
    assert got["marks"] == [["retake, cut"], ["retake proposed", "timing adjusted"], ["timing estimated", "edited", "no place in the video"], []]
    [retake] = got["retakes"]
    assert retake["id"] == "retake-1" and retake["confirmed"] is False and retake["gone"] is False and retake["span"].count(" s") == 2 and "to" in retake["span"]
    beats = {b["beat"]: b for b in got["beats"]}
    assert set(beats) == {3, 4, 5, 6, 7}, "a beat with no preset has no overlay"
    assert beats[3]["flags"] == [] and beats[3]["needsLook"] is False
    assert beats[4]["flags"] == ["below the threshold (0.6)"] and beats[4]["needsLook"] is True
    assert beats[5]["flags"] == ["no match in the words"] and beats[5]["span"] == "" and beats[5]["text"] == ""
    assert beats[6]["flags"] == ["said in another order"] and beats[6]["needsLook"] is False


@needs_node
def test_the_selection_the_closed_edit_objects_and_the_numbers_the_page_may_give(tmp_path):
    got = run_model(tmp_path)
    assert got["selection"] == [{"from": 3, "to": 3}, {"from": 3, "to": 6}, None, None, {"from": 9, "to": 9}, {"from": 1, "to": 3}, {"from": 3, "to": 9}]
    assert got["within"] == [{"from": 3, "to": 84}, None, None]
    assert got["edits"][0] == {"op": "edit", "index": 3, "text": "gonna"} and got["edits"][2] == {"op": "merge", "from": 3, "to": 5} and got["edits"][3]["text"] == "novo"
    assert got["edits"][4] == [{"op": "delete", "index": i} for i in (4, 5, 6)]
    assert got["edits"][9] == {"op": "slot", "slot": "beat7", "choice": "none"} and got["edits"][10]["choice"] is None and got["edits"][13] == {"op": "cover", "offset_ms": 1500}
    assert got["face"] == [{"x": 330, "y": 750, "w": 420, "h": 420}, {"x": 0, "y": 0, "w": 420, "h": 420}, {"x": 660, "y": 1500, "w": 420, "h": 420}, {"x": 0, "y": 420, "w": 1080, "h": 1080}]
    assert got["faceFields"][0] == {"box": {"x": 10, "y": 20, "w": 300, "h": 300}} and all("reason" in r for r in got["faceFields"][1:])
    assert got["cover"][:3] == [{"offsetMs": 1500}, {"offsetMs": 1500}, {"offsetMs": 0}] and all("reason" in r for r in got["cover"][3:])
    assert got["texts"][0].startswith("No face box chosen") and "300 × 300 px at 10, 20" in got["texts"][1] and got["texts"][2] == "Cover: the first frame of the finished video."
    assert got["texts"][3] == "Cover: the frame at 1.5 s of the finished video." and got["texts"][4:] == ["12.3 s", "1:15", "", "0.72", "none"]


@needs_node
def test_a_refusal_is_told_in_a_sentence_for_its_closed_code_and_a_new_code_is_shown_as_it_came(tmp_path):
    got = run_model(tmp_path)
    reasons = got["reasons"]
    assert reasons[0]["code"] == "stale_revision" and "Read them again" in reasons[0]["text"] and reasons[0]["field"] == "revision"
    assert reasons[1]["code"] == "merge_across_segments" and reasons[1]["field"] == "edits[0]"
    assert reasons[2] == {"text": "refused: something_new edits[1]", "code": "", "field": ""}, "a code the page does not know is shown whole"
    assert reasons[3]["text"] == "the pipeline is busy" and "could not be reached" in reasons[4]["text"] and "not here" in reasons[5]["text"]
    assert reasons[6]["text"] == "boom" and reasons[7]["text"] == "The request failed."
    rows = got["steps"][0]
    assert [r["label"] for r in rows] == ["Transcribe", "Check the captions", "Wait for your approval"] and [r["word"] for r in rows] == ["done", "waiting for you", "not yet"]
    assert got["steps"][1:] == [True, False, False]
    assert got["done"][0] == "An asset slot has no file and no choice yet." and got["done"][1] == "" and got["done"][2] == "2 asset slots have no file and no choice yet."


def test_the_pages_edit_objects_are_the_services_closed_lists_and_none_names_a_time():
    source = MODEL_FILE.read_text(encoding="utf-8")
    block = re.search(r"EDIT_KEYS = Object.freeze\(\{(.*?)\}\);", source, re.S).group(1)
    page = {op: set(re.findall(r'"(\w+)"', names)) for op, names in re.findall(r"(\w+): \[([^\]]*)\]", block)}
    assert page == {op: set(keys) for op, keys in cap.OPS.items()}, "the page offers exactly the keys runtime/captions.py takes"
    assert not set().union(*page.values()) & cap.TIME_KEYS, "no edit the page can make has a field for a time"


def test_every_reason_the_service_can_give_has_a_sentence_in_the_page():
    source = MODEL_FILE.read_text(encoding="utf-8")
    page = set(re.findall(r"^  ([a-z_]+): [\"`]", re.search(r"export const REASONS = Object.freeze\(\{(.*?)\n\}\);", source, re.S).group(1), re.M))
    raised = set(re.findall(r'CaptionError\("([a-z_]+)"', (st.REPO / "runtime" / "captions.py").read_text(encoding="utf-8")))
    raised |= set(re.findall(r'"refused: ([a-z_]+) ', (st.REPO / "runtime" / "ops_pipeline.py").read_text(encoding="utf-8")))
    raised |= {"credential_in_transcript", "slot_needs_a_choice"}
    assert raised - page == set(), f"codes with no sentence on the page: {sorted(raised - page)}"


# --- the view: reading ------------------------------------------------------------------------------------------------------------------------

READ = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
out.words = { chunks: all(root, ".wb-rev-chunk").length, first: text(find(root, ".wb-rev-chunk")), buttons: all(root, "button.wb-rev-word").length, outside: text(find(root, ".wb-rev-chunk.is-outside")) };
out.classes = { retake: all(root, ".wb-rev-word.is-retake").map((n) => n.attrs["data-index"]), adjusted: all(root, ".wb-rev-word.is-adjusted").map((n) => n.attrs["data-index"]),
  leftOut: all(root, ".wb-rev-word.is-left-out").map((n) => n.attrs["data-index"]) };
out.aria = word(root, 34).attrs["aria-label"] + " | " + word(root, 0).attrs["aria-label"] + " | " + word(root, 9).attrs["aria-label"];
out.counts = text(find(root, "[data-key=counts]"));
out.retakes = all(root, "[data-retake]").map((n) => ({ id: n.attrs["data-retake"], text: text(n), struck: text(find(n, ".wb-rev-struck")) }));
out.beats = all(root, "[data-beat]").map((n) => ({ beat: n.attrs["data-beat"], flagged: n.cls().includes("is-flagged"), text: text(n) }));
out.adjusted = text(find(root, "[data-key=adjusted]"));
out.unplaced = text(find(root, "[data-key=unplaced]"));
out.slots = all(root, "[data-slot-row]").map((n) => text(n));
out.frame = { lines: text(find(root, "[data-key=face-line]")) + " | " + text(find(root, "[data-key=cover-line]")), frame: all(root, "svg").length, facebox: all(root, "[data-key=facebox]").length };
out.steps = { shown: all(root, "[data-key=steps]").length };
out.chip = text(find(root, ".pui-chip"));
out.done = { button: find(root, "[data-key=done]") ? off(find(root, "[data-key=done]")) : "none", block: find(root, "[data-key=done-block]") ? text(find(root, "[data-key=done-block]")) : null };
out.sentBack = find(root, "[data-key=sent-back]");
out.calls = calls.map((c) => c[0]);
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_page_reads_the_transcript_in_chunks_with_the_retakes_the_beats_the_slots_and_the_counts(tmp_path):
    got = run(tmp_path, READ)
    assert got["calls"] == ["read", "media"] or got["calls"] == ["media", "read"] or sorted(got["calls"]) == ["media", "read"]
    assert got["words"]["chunks"] > 10 and got["words"]["buttons"] == 85 and got["words"]["first"].startswith("0:") and "Not in the captions" in got["words"]["outside"]
    assert got["classes"]["retake"] == [str(i) for i in range(34, 41)] and got["classes"]["adjusted"] == ["0", "1"] and got["classes"]["leftOut"] == ["9"]
    assert "retake proposed" in got["aria"] and "timing adjusted" in got["aria"] and "no place in the video" in got["aria"]
    assert "85 words" in got["counts"] and "2 with adjusted timing" in got["counts"] and "1 with no place" in got["counts"] and "0 of 1 retakes cut" in got["counts"] and "2 to look at" in got["counts"]
    [retake] = got["retakes"]
    assert retake["id"] == "retake-1" and "Confirm the cut" in retake["text"] and "2.4 s dropped" in retake["text"] and retake["struck"].startswith("Depois faz")
    beats = {b["beat"]: b for b in got["beats"]}
    assert set(beats) == {"3", "4", "5", "6", "7"}
    assert [beats[k]["flagged"] for k in "34567"] == [False, True, True, False, False], "a beat below the threshold, or with no match, is flagged"
    assert "below the threshold (0.6)" in beats["4"]["text"] and "no match in the words" in beats["5"]["text"] and "score 0.30" in beats["5"]["text"]
    assert "(2)" in got["adjusted"] and "(1)" in got["unplaced"]
    [slot] = got["slots"]
    assert "beat7" in slot and "a screenshot of the budgeting dashboard" in slot and "No file yet." in slot
    assert got["frame"]["frame"] == 1 and got["frame"]["facebox"] == 0 and "renderer's own default" in got["frame"]["lines"] and "first frame" in got["frame"]["lines"]
    assert got["steps"]["shown"] == 0, "the steps are for a pipeline that is not at the review"
    assert got["chip"] == "Waiting for you"
    assert got["done"] == {"button": True, "block": "An asset slot has no file and no choice yet."} and got["sentBack"] is None


TEXT_ONLY = r"""
const hostile = clone(VIEW);
hostile.words[3].text = "<b>x</b>";
hostile.words[4].text = "&amp;";
hostile.sent_back = { comment: "<img src=x onerror=alert(1)> too fast", at: "2026-10-14T11:00:00Z", render_sha256: null };
script.view = hostile;
const view = make();
const root = view.el;
await view.load(); await settle();
out.word = text(word(root, 3)) + "|" + text(word(root, 4));
out.markup = all(root, "b").length + all(root, "img").length;
out.sentBack = text(find(root, "[data-key=sent-back]"));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_words_and_the_send_back_comment_are_text_never_markup(tmp_path):
    got = run(tmp_path, TEXT_ONLY)
    assert got["word"] == "<b>x</b>|&amp;" and got["markup"] == 0
    assert "<img src=x onerror=alert(1)> too fast" in got["sentBack"] and "The video was sent back for review" in got["sentBack"]


# --- the view: editing --------------------------------------------------------------------------------------------------------------------------

EDIT = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
const sent = () => calls.filter((c) => c[0] === "edit");
const choose = async (a, b = a) => { const s = view.snapshot().selection; if (s) await press(word(root, s.from)); await press(word(root, a)); if (b !== a) await press(word(root, b)); };
// selecting: one click selects, a second extends, a click inside clears
await press(word(root, 3));
out.one = { line: text(find(root, "[data-key=selection-line]")), pressed: word(root, 3).attrs["aria-pressed"], input: find(root, "[data-key=word]") ? find(root, "[data-key=word]").value : null };
await press(word(root, 6));
out.range = { line: text(find(root, "[data-key=selection-line]")), pressed: [3, 4, 5, 6, 7].map((i) => word(root, i).attrs["aria-pressed"]), merge: find(root, "[data-key=merge-words]") !== null, del: text(find(root, "[data-key=delete-words]")) };
await press(word(root, 4));
out.cleared = { line: text(find(root, "[data-key=selection-line]")), pressed: word(root, 4).attrs["aria-pressed"], input: find(root, "[data-key=word]") };
// the selection can be cleared with a button
await press(word(root, 12));
out.clearButton = { before: text(find(root, "[data-key=selection-line]")).startsWith("Word 13") };
await press(find(root, "[data-key=clear-selection]"));
out.clearButton.after = text(find(root, "[data-key=selection-line]")).startsWith("Select a word");
// shift extends from one word
await press(word(root, 10));
word(root, 14).listeners.click[0]({ shiftKey: true });
await settle();
out.shift = text(find(root, "[data-key=selection-line]"));
await choose(3);
// edit one word: the text typed is sent with the revision on screen; the answer is what is shown, and the next edit carries the new revision
typeInto(find(root, "[data-key=word]"), "gonna");
const after = clone(VIEW); after.revision = 1; after.words[3].text = "gonna"; after.words[3].edited = true; after.counts.edited = 1;
script.next = () => ({ ...clone(after), applied: { edited: 1, split: 0, merged: 0, deleted: 0 } });
await press(find(root, "[data-key=save-word]"));
out.saved = { sent: sent().map((c) => [c[1], c[2]]), word: text(word(root, 3)), edited: word(root, 3).cls().includes("is-edited"), message: text(find(root, "[data-key=message]")), counts: text(find(root, "[data-key=counts]")), selected: word(root, 3).attrs["aria-pressed"] };
script.next = null;
await choose(8);
await press(find(root, "[data-key=delete-word]"));
out.secondRevision = sent()[1][1];
// split needs two parts: the page says so and sends nothing
await choose(5);
typeInto(find(root, "[data-key=word]"), "one");
const before = sent().length;
await press(find(root, "[data-key=split-word]"));
out.splitOne = { sent: sent().length - before, error: text(find(root, ".wb-notice-card")) };
typeInto(find(root, "[data-key=word]"), "um dois  tres");
await press(find(root, "[data-key=split-word]"));
out.split = sent()[sent().length - 1][2];
// merge a range (with and without a word), delete a range
await choose(20, 22);
typeInto(find(root, "[data-key=merge]"), " junto ");
await press(find(root, "[data-key=merge-words]"));
out.merge = sent()[sent().length - 1][2];
await choose(20, 22);
await press(find(root, "[data-key=merge-words]"));
out.mergePlain = sent()[sent().length - 1][2];
await choose(20, 22);
await press(find(root, "[data-key=delete-words]"));
out.deleteRange = sent()[sent().length - 1][2];
out.revisions = sent().map((c) => c[1]);
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_page_selects_words_and_changes_them_through_one_call_with_the_revision_it_read(tmp_path):
    got = run(tmp_path, EDIT)
    assert got["one"]["line"] == "Word 4 selected: Hoje" or got["one"]["line"].startswith("Word 4 selected:")
    assert got["one"]["pressed"] == "true" and got["one"]["input"] is not None
    assert got["range"]["line"].startswith("Words 4 to 7 selected:") and got["range"]["pressed"] == ["true"] * 4 + ["false"] and got["range"]["merge"] is True and got["range"]["del"] == "Delete these 4 words"
    assert got["clearButton"] == {"before": True, "after": True}
    assert got["cleared"]["pressed"] == "false" and got["cleared"]["input"] is None and got["cleared"]["line"].startswith("Select a word"), "a click inside the range clears it"
    assert got["shift"].startswith("Words 11 to 15 selected"), "shift extends from the word selected"
    assert got["saved"]["sent"] == [[0, [{"op": "edit", "index": 3, "text": "gonna"}]]], "the text typed and the revision on screen, nothing else"
    assert got["saved"]["word"] == "gonna" and got["saved"]["edited"] is True and got["saved"]["message"] == "Saved the spelling." and "1 changed by you" in got["saved"]["counts"]
    assert got["saved"]["selected"] == "false", "an accepted change ends the selection, so the next click cannot stretch an old range"
    assert got["secondRevision"] == 1, "the next edit carries the revision the last answer gave"
    assert got["splitOne"]["sent"] == 0 and "parts of the word" in got["splitOne"]["error"]
    assert got["split"] == [{"op": "split", "index": 5, "parts": ["um", "dois", "tres"]}]
    assert got["merge"] == [{"op": "merge", "from": 20, "to": 22, "text": "junto"}] and got["mergePlain"] == [{"op": "merge", "from": 20, "to": 22}]
    assert got["deleteRange"] == [{"op": "delete", "index": i} for i in (20, 21, 22)]


def accepted_by_the_service(edit_lists):
    """Every list the page sent is applied, from the same starting state, by the real `apply_edits`: none is refused."""
    edited, review, edl, beats = documents()
    for edits in edit_lists:
        out = cap.apply_edits(copy.deepcopy(edited), copy.deepcopy(review), edits, revision=0, proposals=cap.retake_ranges(edl),
                              beats={r["beat"] for r in beats["report"] if r.get("preset")}, slots={s["slot"] for s in beats["slots"]})
        assert out is not None


@needs_node
def test_what_the_page_sends_for_a_word_is_accepted_by_the_real_edit_operation(tmp_path):
    got = run(tmp_path, EDIT)
    accepted_by_the_service([[{"op": "edit", "index": 3, "text": "gonna"}], got["split"], got["merge"], got["mergePlain"], got["deleteRange"]])


REFUSED = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
await press(word(root, 3));
typeInto(find(root, "[data-key=word]"), "typed but refused");
const snapshot = () => JSON.stringify({ words: all(root, ".wb-rev-word").map((n) => text(n)), selected: all(root, ".wb-rev-word.is-selected").map((n) => n.attrs["data-index"]), typed: find(root, "[data-key=word]").value });
const before = snapshot();
const node = find(root, "[data-key=word]");
script.editError = new ApiError(409, "refused", "refused: forbidden_character edits[0].text");
await press(find(root, "[data-key=save-word]"));
out.refused = { text: text(find(root, ".wb-notice-card")), same: snapshot() === before, sameInput: find(root, "[data-key=word]") === node, busy: view.snapshot().busy, reads: calls.filter((c) => c[0] === "read").length };
script.editError = new ApiError(409, "refused", "refused: stale_revision revision");
await press(find(root, "[data-key=save-word]"));
out.stale = { text: text(find(root, ".wb-notice-card")), same: snapshot() === before, again: find(root, "[data-key=reread]") !== null };
await press(find(root, "[data-key=reread]"));
out.reread = { reads: calls.filter((c) => c[0] === "read").length, notice: find(root, ".wb-notice-card") };
script.editError = new ApiError(0, "network", "The service could not be reached. Is it still running?");
await press(find(root, "[data-key=save-word]"));
out.network = text(find(root, ".wb-notice-card"));
script.editError = null;
await press(find(root, "[data-key=save-word]"));
out.accepted = { notice: find(root, ".wb-notice-card"), sent: calls.filter((c) => c[0] === "edit").length };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_refused_edit_shows_its_reason_and_changes_nothing_on_screen(tmp_path):
    got = run(tmp_path, REFUSED)
    assert "control or invisible character" in got["refused"]["text"] and "forbidden_character" in got["refused"]["text"]
    assert got["refused"]["same"] is True and got["refused"]["sameInput"] is True and got["refused"]["busy"] is None, "the words, the selection and the typed text are as they were"
    assert "Read them again" in got["stale"]["text"] and got["stale"]["same"] is True and got["stale"]["again"] is True
    assert got["reread"]["notice"] is None and got["reread"]["reads"] == 2
    assert "could not be reached" in got["network"]
    assert got["accepted"]["notice"] is None and got["accepted"]["sent"] == 4, "an accepted edit clears the reason"


DECISIONS = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
const sent = () => calls.filter((c) => c[0] === "edit").map((c) => c[2]);
const last = () => sent()[sent().length - 1];
// a retake: confirm, then the answer shows it cut
const confirmed = clone(VIEW); confirmed.revision = 1; confirmed.retakes[0].confirmed = true; confirmed.counts.confirmed = 1;
script.next = () => ({ ...clone(confirmed), applied: {} });
await press(find(root, "[data-key=retake-retake-1]"));
out.retake = { sent: last(), button: text(find(root, "[data-key=retake-retake-1]")), cut: all(root, ".wb-rev-word.is-cut").length, retake: all(root, ".wb-rev-word.is-retake").length, row: find(root, "[data-retake]").cls().includes("is-confirmed"), counts: text(find(root, "[data-key=counts]")) };
script.next = () => ({ ...clone(VIEW), revision: 2 });
await press(find(root, "[data-key=retake-retake-1]"));
out.undo = { sent: last(), button: text(find(root, "[data-key=retake-retake-1]")), cut: all(root, ".wb-rev-word.is-cut").length };
// an anchor needs words selected
out.noSelection = off(find(root, "[data-key=anchor-4]"));
await press(word(root, 44)); await press(word(root, 47));
out.withSelection = { off: off(find(root, "[data-key=anchor-4]")), label: text(find(root, "[data-key=anchor-4]")) };
const anchored = clone(VIEW); anchored.revision = 3; anchored.beats = anchored.beats.map((b) => (b.beat === 4 ? { ...b, anchored: true, matched: true, score: 1, below_threshold: false, word_from: 44, word_to: 47 } : b));
script.next = () => ({ ...clone(anchored), applied: {} });
await press(find(root, "[data-key=anchor-4]"));
out.anchor = { sent: last(), row: text(find(root, '[data-beat="4"]')), flagged: find(root, '[data-beat="4"]').cls().includes("is-flagged"), clear: find(root, "[data-key=clear-anchor-4]") !== null, counts: text(find(root, "[data-key=counts]")) };
script.next = () => ({ ...clone(VIEW), revision: 4 });
await press(find(root, "[data-key=clear-anchor-4]"));
out.clear = last();
// drop and keep an overlay
const dropped = clone(VIEW); dropped.revision = 5; dropped.beats = dropped.beats.map((b) => (b.beat === 5 ? { ...b, dropped: true } : b));
script.next = () => ({ ...clone(dropped), applied: {} });
await press(find(root, "[data-key=overlay-5]"));
out.drop = { sent: last(), button: text(find(root, "[data-key=overlay-5]")), flags: text(find(root, '[data-beat="5"]')), cls: find(root, '[data-beat="5"]').cls().includes("is-dropped") };
script.next = () => ({ ...clone(VIEW), revision: 6 });
await press(find(root, "[data-key=overlay-5]"));
out.keep = last();
out.all = sent();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_retakes_are_confirmed_or_undone_and_beats_are_anchored_cleared_dropped_or_kept(tmp_path):
    got = run(tmp_path, DECISIONS)
    assert got["retake"]["sent"] == [{"op": "retake", "id": "retake-1", "confirmed": True}] and got["retake"]["button"] == "Undo" and got["retake"]["row"] is True
    assert got["retake"]["cut"] == 7 and got["retake"]["retake"] == 0 and "1 of 1 retakes cut" in got["retake"]["counts"]
    assert got["undo"]["sent"] == [{"op": "retake", "id": "retake-1", "confirmed": False}] and got["undo"]["button"] == "Confirm the cut" and got["undo"]["cut"] == 0
    assert got["noSelection"] is True and got["withSelection"]["off"] is False and got["withSelection"]["label"] == "Anchor to words 45 to 48"
    assert got["anchor"]["sent"] == [{"op": "anchor", "beat": 4, "word_from": 44, "word_to": 47}]
    assert "anchored by you" in got["anchor"]["row"] and got["anchor"]["flagged"] is False and got["anchor"]["clear"] is True and "below the threshold" not in got["anchor"]["row"]
    assert got["clear"] == [{"op": "anchor", "beat": 4, "clear": True}]
    assert got["drop"]["sent"] == [{"op": "overlay", "beat": 5, "dropped": True}] and got["drop"]["button"] == "Keep the overlay" and "overlay dropped" in got["drop"]["flags"] and got["drop"]["cls"] is True
    assert got["keep"] == [{"op": "overlay", "beat": 5, "dropped": False}]
    accepted_by_the_service(got["all"])


SLOTS = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
const sent = () => calls.filter((c) => c[0] === "edit").map((c) => c[2]);
// a choice for an empty slot
const chosen = clone(VIEW); chosen.revision = 1; chosen.slots[0].choice = "keyword";
script.next = () => ({ ...clone(chosen), applied: {} });
const select = find(root, "[data-key=choice-beat7]");
select.value = "keyword";
(select.listeners.change || []).forEach((fn) => fn());
await settle();
out.choice = { sent: sent()[0], block: find(root, "[data-key=done-block]"), done: off(find(root, "[data-key=done]")) };
script.next = null;
// a file for the slot: choosing sends nothing; the second button uploads it to the media route with the slot's id
const input = find(root, 'input[data-slot="beat7"]');
input.files = [{ name: "painel.png", size: 2048, type: "image/png" }];
input.listeners.change.forEach((fn) => fn());
await settle();
out.picked = { name: text(find(root, ".wb-hand-chosen")), uploads: calls.filter((c) => c[0] === "upload").length, accept: input.attrs.accept };
const withFile = clone(VIEW); withFile.slots[0].file = { name: "painel.png", type: "png", sha256: "ab", stale: false };
script.view = withFile;
await press(find(root, ".wb-hand-send"));
out.uploaded = { calls: calls.filter((c) => c[0] === "upload"), file: text(find(root, '[data-key="slot-state-beat7"]')), picked: find(root, ".wb-hand-chosen"), reads: calls.filter((c) => c[0] === "read").length, select: find(root, "[data-key=choice-beat7]") };
// a file over the limit and a slot with no id are refused before anything is sent
const big = clone(VIEW); script.view = big;
await view.load({ quiet: true }); await settle();
const input2 = find(root, 'input[data-slot="beat7"]');
input2.files = [{ name: "enorme.png", size: 2 * 1024 * 1024 * 1024, type: "image/png" }];
input2.listeners.change.forEach((fn) => fn());
await settle();
const uploadsBefore = calls.filter((c) => c[0] === "upload").length;
await press(find(root, ".wb-hand-send"));
out.tooBig = { text: text(find(root, ".wb-card-error")), sent: calls.filter((c) => c[0] === "upload").length - uploadsBefore };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_an_empty_slot_gets_a_choice_or_a_file_through_the_media_route_and_done_waits_for_one_of_them(tmp_path):
    got = run(tmp_path, SLOTS)
    assert got["choice"]["sent"] == [{"op": "slot", "slot": "beat7", "choice": "keyword"}] and got["choice"]["block"] is None and got["choice"]["done"] is False
    assert got["picked"] == {"name": "painel.png", "uploads": 0, "accept": "image/png,image/jpeg"}, "choosing a file sends nothing; an image slot offers PNG and JPEG"
    sid = fixture_media()[1]
    assert got["uploaded"]["calls"] == [["upload", RID, sid, "painel.png"]], "the file goes to the recording, bound to the id the media list gave the slot"
    assert "File: painel.png" in got["uploaded"]["file"] and got["uploaded"]["picked"] is None and got["uploaded"]["select"] is None, "after the upload the slot shows its file"
    assert got["uploaded"]["reads"] >= 2, "the review is read again after an upload"
    assert "at most 1 GiB" in got["tooBig"]["text"] and got["tooBig"]["sent"] == 0


FRAME = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
const sent = () => calls.filter((c) => c[0] === "edit").map((c) => c[2]);
const frame = find(root, "[data-key=frame]");
frame.getBoundingClientRect = () => ({ left: 10, top: 20, width: 100, height: 178 });
const placed = clone(VIEW); placed.revision = 1; placed.face_box = { x: 330, y: 750, w: 420, h: 420 };
script.next = () => ({ ...clone(placed), applied: {} });
frame.listeners.click.forEach((fn) => fn({ clientX: 60, clientY: 109 }));
await settle();
out.tap = { sent: sent()[0], line: text(find(root, "[data-key=face-line]")), box: all(root, "[data-key=facebox]").length };
// the size is chosen in words
await press(find(root, "[data-key=size-small]"));
out.size = find(root, "[data-key=size-small]").attrs["aria-pressed"] + find(root, "[data-key=size-medium]").attrs["aria-pressed"];
const frame2 = find(root, "[data-key=frame]");
frame2.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 178 });
const small = clone(placed); small.revision = 2; small.face_box = { x: 0, y: 0, w: 280, h: 280 };
script.next = () => ({ ...clone(small), applied: {} });
frame2.listeners.click.forEach((fn) => fn({ clientX: 0, clientY: 0 }));
await settle();
out.corner = sent()[1];
// numbers: a wrong box is refused on the page, a right one is sent
typeInto(find(root, "[data-key=face-w]"), "2000");
await press(find(root, "[data-key=set-face]"));
out.badBox = { text: text(find(root, ".wb-notice-card")), sent: sent().length };
typeInto(find(root, "[data-key=face-w]"), "300"); typeInto(find(root, "[data-key=face-h]"), "320"); typeInto(find(root, "[data-key=face-x]"), "40"); typeInto(find(root, "[data-key=face-y]"), "60");
script.next = () => ({ ...clone(small), revision: 3, applied: {} });
await press(find(root, "[data-key=set-face]"));
out.numbers = sent()[2];
script.next = () => ({ ...clone(VIEW), revision: 4, applied: {} });
await press(find(root, "[data-key=clear-face]"));
out.clear = sent()[3];
// the cover
typeInto(find(root, "[data-key=cover]"), "abc");
await press(find(root, "[data-key=set-cover]"));
out.badCover = { text: text(find(root, ".wb-notice-card")), sent: sent().length };
typeInto(find(root, "[data-key=cover]"), "2.5");
const covered = clone(VIEW); covered.revision = 5; covered.cover_offset_ms = 2500;
script.next = () => ({ ...clone(covered), applied: {} });
await press(find(root, "[data-key=set-cover]"));
out.cover = { sent: sent()[4], line: text(find(root, "[data-key=cover-line]")) };
script.next = () => ({ ...clone(VIEW), revision: 6, applied: {} });
await press(find(root, "[data-key=cover-first]"));
out.first = sent()[5];
out.all = sent();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_face_box_is_chosen_on_a_schematic_frame_or_in_numbers_and_the_cover_in_seconds_and_the_page_says_what_was_chosen(tmp_path):
    got = run(tmp_path, FRAME)
    assert got["tap"]["sent"] == [{"op": "face_box", "x": 330, "y": 750, "w": 420, "h": 420}] and "420 × 420 px at 330, 750" in got["tap"]["line"] and got["tap"]["box"] == 1
    assert got["size"] == "truefalse" and got["corner"] == [{"op": "face_box", "x": 0, "y": 0, "w": 280, "h": 280}], "a tap in a corner is kept inside the frame"
    assert "inside the frame" in got["badBox"]["text"] and got["badBox"]["sent"] == 2
    assert got["numbers"] == [{"op": "face_box", "x": 40, "y": 60, "w": 300, "h": 320}] and got["clear"] == [{"op": "face_box", "clear": True}]
    assert "inside the recording" in got["badCover"]["text"] and got["badCover"]["sent"] == 4
    assert got["cover"]["sent"] == [{"op": "cover", "offset_ms": 2500}] and "2.5 s" in got["cover"]["line"] and got["first"] == [{"op": "cover", "offset_ms": 0}]
    accepted_by_the_service(got["all"])


# --- the view: done, the pipeline's progress, the Mac, the policy --------------------------------------------------------------------------

DONE = r"""
const done = clone(VIEW);
done.slots[0].choice = "none";
script.view = done;
let changed = 0;
const view = make({ changed: () => { changed += 1; } });
const root = view.el;
await view.load(); await settle();
out.ready = { off: off(find(root, "[data-key=done]")), label: text(find(root, "[data-key=done]")), hint: text(find(root, "[data-part=done]")).includes("sends nothing of your words") };
// the job runs the rest of the pipeline: the steps are shown, read from the media list, until it ends
script.media.pipeline.steps = { transcribe: "done", analyse: "done", retakes: "done", "align-proposal": "done", review: "done", remap: "done", base: "done", align: "pending", check: "pending", render: "pending", cover: "pending", approval: "pending" };
script.media.pipeline.next = "align";
const after = clone(done); after.editable = false; after.steps = clone(script.media.pipeline.steps);
script.view = after;
await press(find(root, "[data-key=done]"));
await settle(); await settle(); await settle();
out.sent = calls.filter((c) => c[0] === "done").map((c) => c[1]);
out.polled = calls.filter((c) => c[0] === "poll").length;
out.after = { chip: text(find(root, ".pui-chip")), editButtons: all(root, "button.wb-rev-word").length, words: all(root, ".wb-rev-word").length, steps: all(root, "[data-step]").length, reopen: find(root, "[data-key=reopen]") !== null, changed };
// the whole call carried the revision and nothing else
out.noText = JSON.stringify(out.sent).includes("text") || JSON.stringify(out.sent).includes("Depois");
await press(find(root, "[data-key=reopen]"));
out.reopen = calls.filter((c) => c[0] === "again").map((c) => c.slice(1));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_done_sends_the_revision_and_nothing_of_the_words_then_the_pipelines_steps_show_and_the_captions_can_be_opened_again(tmp_path):
    got = run(tmp_path, DONE)
    assert got["ready"]["off"] is False and "Done" in got["ready"]["label"] and got["ready"]["hint"] is True
    assert got["sent"] == [{"revision": 0}] and got["noText"] is False, "Done carries the revision and no text"
    assert got["polled"] == 1
    assert got["after"]["chip"] == "Checked" and got["after"]["editButtons"] == 0 and got["after"]["steps"] == 12 and got["after"]["reopen"] is True and got["after"]["changed"] == 1
    assert got["reopen"] == [[RID, "review"]]


RUNNING = r"""
const done = clone(VIEW); done.slots[0].choice = "none"; script.view = done;
const view = make();
const root = view.el;
await view.load(); await settle();
let release; const held = new Promise((r) => { release = r; });
api.pollJob = async (id, every, o) => { calls.push(["poll", id]); o.onUpdate({ state: "running" }); await settle(); out.during = { chip: text(find(root, ".pui-chip")), steps: text(find(root, "[data-key=steps]")), words: all(root, ".wb-rev-word").length, done: find(root, "[data-key=done]") };
  script.media.pipeline.steps.render = "done"; o.onUpdate({ state: "running" }); await settle(); out.later = text(find(root, '[data-step="render"]')); await held; return { state: "done", result: { ok: true } }; };
script.media.pipeline.steps = { transcribe: "done", analyse: "done", retakes: "done", "align-proposal": "done", review: "done", remap: "done", base: "done", align: "done", check: "done", render: "pending", cover: "pending", approval: "pending" };
const after = clone(done); after.editable = false; script.view = after;
const pressing = press(find(root, "[data-key=done]"));
await settle(); await settle();
release();
await pressing; await settle();
out.end = text(find(root, ".pui-chip"));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_while_the_pipeline_goes_on_after_done_the_steps_are_shown_and_updated_from_the_media_list(tmp_path):
    got = run(tmp_path, RUNNING)
    assert got["during"]["chip"] == "Running" and "Render the video" in got["during"]["steps"] and got["during"]["words"] == 0 and got["during"]["done"] is None
    assert "done" in got["later"] and got["end"] == "Checked"


PROGRESS = r"""
script.readError = new ApiError(409, "refused", "the captions are not ready: the pipeline is at align-proposal");
const view = make();
const root = view.el;
await view.load(); await settle();
out.progress = { chip: text(find(root, ".pui-chip")), steps: all(root, "[data-step]").length, statuses: all(root, "[data-step]").map((n) => n.attrs["data-step"] + ":" + n.cls().filter((c) => c.startsWith("is-"))[0]),
  failure: find(root, "[data-part=steps] .wb-notice-card") ? text(find(root, "[data-part=steps] .wb-notice-card")) : null, words: all(root, ".wb-rev-word").length, error: find(root, ".wb-notice-card.is-error") ? text(find(root, ".wb-notice-card.is-error")) : null };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_pipeline_that_is_not_at_the_review_shows_its_steps_and_the_failure_with_the_command_to_run(tmp_path):
    failure = {"step": "align-proposal", "code": "script_refused", "field": "beat3", "provider": "renderer", "next": "fix the post file, then prepare-again", "at": "2026-10-14T10:00:00Z"}
    got = run(tmp_path, PROGRESS, at="align-proposal", failure=failure)
    progress = got["progress"]
    assert progress["chip"] == "Not at the review yet" and progress["steps"] == 12 and progress["words"] == 0
    assert progress["statuses"][3] == "align-proposal:is-waiting" and progress["statuses"][0] == "transcribe:is-done"
    assert "script_refused beat3" in progress["failure"] and "fix the post file, then prepare-again" in progress["failure"]


OFF_MAC = r"""
const view = make({ loopback: false });
const root = view.el;
await view.load(); await settle();
out.mac = { calls: calls.map((c) => c[0]), notice: text(find(root, ".wb-notice-card")), chip: text(find(root, ".pui-chip")), words: all(root, ".wb-rev-word").length, buttons: all(root, "button").map((b) => b.attrs["data-key"]), steps: all(root, "[data-step]").length };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_page_that_is_not_the_mac_reads_nothing_of_the_words_and_says_so(tmp_path):
    got = run(tmp_path, OFF_MAC)["mac"]
    assert got["calls"] == ["media"], "only the pipeline's steps are read: the words never cross the network"
    assert got["notice"].startswith("Check the captions on the Mac") and got["chip"] == "On the Mac" and got["words"] == 0 and got["buttons"] == ["reload"]


POLICY = r"""
const view = make({ can: (op) => !["captions-edit", "captions-done", "prepare-again"].includes(op) });
const root = view.el;
await view.load(); await settle();
out.policy = { buttons: all(root, "button.wb-rev-word").length, words: all(root, ".wb-rev-word").length, actions: all(root, "button").map((b) => b.attrs["data-key"]), line: text(find(root, "[data-key=withheld]")), retakes: all(root, "[data-retake]").length };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_project_that_turns_the_writes_off_for_the_page_leaves_the_words_to_read_and_no_control(tmp_path):
    got = run(tmp_path, POLICY)["policy"]
    assert got["buttons"] == 0 and got["words"] == 85 and got["actions"] == ["reload"] and got["retakes"] == 1
    assert got["line"] == "Turned off for the page: captions-edit, captions-done. Use the terminal."


KEEPS = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
await press(word(root, 3));
const input = find(root, "[data-key=word]");
typeInto(input, "typing");
input.focus();
const transcript = find(root, ".wb-rev-transcript");
const frame = find(root, "[data-key=frame]");
await view.load({ quiet: true }); await settle();
out.same = { transcript: find(root, ".wb-rev-transcript") === transcript, input: find(root, "[data-key=word]") === input, value: input.value, focused: globalThis.document.activeElement === input, frame: find(root, "[data-key=frame]") === frame };
const changed = clone(VIEW); changed.beats = changed.beats.map((b) => (b.beat === 3 ? { ...b, dropped: true } : b));
script.view = changed;
await view.load({ quiet: true }); await settle();
out.partial = { transcript: find(root, ".wb-rev-transcript") === transcript, input: find(root, "[data-key=word]") === input, dropped: find(root, '[data-beat="3"]').cls().includes("is-dropped") };
view.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_read_that_changed_nothing_keeps_the_words_the_typed_text_and_the_focus_and_one_that_changed_a_beat_draws_only_the_beats(tmp_path):
    got = run(tmp_path, KEEPS)
    assert got["same"] == {"transcript": True, "input": True, "value": "typing", "focused": True, "frame": True}
    assert got["partial"] == {"transcript": True, "input": True, "dropped": True}


# --- the row in the Tasks tab ----------------------------------------------------------------------------------------------------------------

TAB = r"""
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
const NOW = new Date("2026-10-14T12:00:00Z");
globalThis.location = { hostname: "127.0.0.1" };
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({ error: "not_found", message: "no" }) });
const cards = [];
const tabApi = { ...api, videoCard: async (p, rid) => { cards.push(rid); return { recording: rid, status: "open", platforms: ["instagram"], platform: "instagram", render: null, cover: null, caption: null, approval: null, sent_back: null, can_download: false, download_name: null, problems: [] }; } };
const task = (id, key) => ({ id, key, title: `Task ${id}`, skill: null, state: "waiting", note: null, agent: "engineering", requestId: 1 });
const tab = createTasksTab({ project: "@PROJECT@", now: () => NOW, refresh: () => {}, api: tabApi, links: { request: () => "#r", inbox: () => "#i", open: () => "#o" } });
const tasks = [task(1, "media:@RID@"), task(2, "plain")];
const data = (extra = {}) => ({ tasks, requests: [{ id: 1, title: "R", state: "ready" }], pending: [], loading: false, reload: 1, ...extra });
tab.update(data()); await settle();
const toggle = (id) => find(tab.el, `[data-key=toggle-${id}]`);
out.closed = { views: all(tab.el, "section.wb-rev").length, reads: calls.length };
toggle(2).click(); await settle();
out.plain = { views: all(tab.el, "section.wb-rev").length, reads: calls.length };
toggle(1).click(); await settle();
out.opened = { views: all(tab.el, "section.wb-rev").length, cards: all(tab.el, "section.wb-video").length, order: find(tab.el, ".wb-media-task").children.map((n) => n.attrs["aria-label"]), reads: calls.filter((c) => c[0] === "read").length };
tab.update(data({ reload: 2 })); await settle();
out.reread = { reads: calls.filter((c) => c[0] === "read").length, card: cards.length };
toggle(1).click(); await settle();
out.collapsed = all(tab.el, "section.wb-rev").length;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_row_of_a_recordings_code_task_shows_the_review_above_the_video_card_and_nothing_for_another_task(tmp_path):
    got = run(tmp_path, TAB)
    assert got["closed"] == {"views": 0, "reads": 0} and got["plain"] == {"views": 0, "reads": 0}
    assert got["opened"]["views"] == 1 and got["opened"]["cards"] == 1 and got["opened"]["order"] == ["Check the captions", "Rendered video"] and got["opened"]["reads"] == 1
    assert got["reread"]["reads"] == 2 and got["reread"]["card"] >= 2, "a store change reads both again"
    assert got["collapsed"] == 0


# --- the client functions ----------------------------------------------------------------------------------------------------------------

CLIENT = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";
setToken("t".repeat(40));
const seen = [];
globalThis.fetch = async (url, init) => { seen.push({ url, init }); return { ok: true, status: 200, json: async () => ({ ok: 1, job: 3 }) }; };
const P = "0123456789ab", R = "0123456789abcdef";
await api.captionsRead(P, R);
await api.captionsEdit(P, R, { revision: 4, edits: [{ op: "edit", index: 1, text: "oi" }] });
await api.captionsDone(P, R, { revision: 4 });
await api.prepareAgain(P, R, "review");
console.log(JSON.stringify(seen.map((s) => ({ url: s.url, method: s.init.method, body: s.init.body ? JSON.parse(s.init.body) : null, auth: s.init.headers.Authorization.startsWith("Bearer "), type: s.init.headers["Content-Type"] || null }))));
"""


@needs_node
def test_the_client_reads_and_writes_the_review_by_its_four_routes_and_sends_the_edits_as_the_json_text_the_operation_takes(tmp_path):
    from test_interface_floor import NODE
    import subprocess
    (tmp_path / "client.mjs").write_text(CLIENT.replace("@JS@", JS.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(tmp_path / "client.mjs")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    base = f"/api/v1/projects/{PROJECT}/media/{RID}"
    assert [(g["method"], g["url"]) for g in got] == [("GET", f"{base}/captions"), ("POST", f"{base}/captions"), ("POST", f"{base}/captions/done"), ("POST", f"{base}/prepare-again")]
    assert got[1]["body"] == {"revision": 4, "text": "[{\"op\":\"edit\",\"index\":1,\"text\":\"oi\"}]"} and got[2]["body"] == {"revision": 4} and got[3]["body"] == {"step": "review"}
    assert all(g["auth"] for g in got) and got[1]["type"] == "application/json"


# --- what the files are allowed to do, and the layout at a phone's width ---------------------------------------------------------------------

def test_the_page_calls_only_its_own_routes_builds_no_markup_and_touches_no_image_model_setting_or_mode():
    code = "\n".join(line for line in VIEW_FILE.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("//"))
    assert set(re.findall(r"\bapi\.(\w+)\(", code)) == {"captionsRead", "captionsEdit", "captionsDone", "prepareAgain", "mediaList", "pollJob"}
    for forbidden in ("setMode", "acceptConfig", "accept-config", "mediaPipeline", "media-pipeline", "innerHTML", "insertAdjacentHTML", "outerHTML", "createContextualFragment", "fetch(", "XMLHttpRequest", "localStorage",
                      "sessionStorage", "window.open", "ev" + "al(", "new Func" + "tion", ".style", "canvas", "toDataURL", "createObjectURL", "setInterval", "models", "build"):
        assert forbidden not in code, forbidden
    assert re.findall(r"uploadRecording\(api, env\.project, file, \{ recording: env\.recording, slot: id", code), "a file goes to the media route by the existing upload function, bound to a slot id"
    model = "\n".join(line for line in MODEL_FILE.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("//"))
    assert "document" not in model and "fetch" not in model, "the model is pure"


def test_the_review_reads_well_at_a_phones_width_and_nothing_scrolls_sideways():
    floor = css_file("floor")
    phone = "\n".join(media_blocks(floor, "max-width: 899px"))
    assert ".wb-rev-word, .wb-rev-matched, .wb-rev-plain, .wb-rev-beat-head, .wb-rev-steps, .wb-rev-heading, .wb-rev-details > summary { font-size: 16px; }" in phone
    assert "button.wb-rev-word { min-height: 40px; }" in phone and ".wb-rev-sizes .pui-btn { flex: 1 1 auto; min-height: 44px; }" in phone
    assert ".wb-card-actions .pui-btn { flex: 1 1 100%; min-height: 44px; }" in phone, "the buttons are full width and tall enough to touch"
    words = re.search(r"^\.wb-rev-words \{([^}]*)\}", floor, re.M).group(1)
    assert "flex-wrap: wrap" in words and "min-width: 0" in words, "the words wrap onto the next line"
    word = re.search(r"^\.wb-rev-word \{([^}]*)\}", floor, re.M).group(1)
    assert "overflow-wrap: anywhere" in word and "max-width: 100%" in word
    assert "minmax(0, 1fr)" in re.search(r"^\.wb-rev-content \{([^}]*)\}", floor, re.M).group(1), "a long unbroken word cannot push the card past the screen"
    assert "display: contents" in re.search(r"^\.wb-rev-part \{([^}]*)\}", floor, re.M).group(1)
    assert "max-width: 200px" in re.search(r"^\.wb-rev-frame \{([^}]*)\}", floor, re.M).group(1)
    assert "overflow-x" not in "\n".join(re.findall(r"[^\n]*wb-cap[^\n]*", floor)), "nothing in the review scrolls sideways"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", "\n".join(re.findall(r"[^\n]*wb-cap[^\n]*", floor))), "tokens only: no colour literal"

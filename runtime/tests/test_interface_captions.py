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
  captionsDone: async (p, rid, o) => { calls.push(["done", { revision: o.revision, keys: Object.keys(o).filter((k) => k !== "signal").sort() }]); return { job: 7, state: "running", op: "captions-done" }; },
  prepareAgain: async (p, rid, step) => { calls.push(["again", rid, step]); return { job: 8, state: "running" }; },
  pollJob: async (id, every, o) => { calls.push(["poll", id]); if (o && o.onUpdate) o.onUpdate({ state: "running" }); await settle(); return { state: "done", result: { ok: true } }; },
  uploadMedia: async (p, file, o) => { calls.push(["upload", o.recording, o.slot, file.name]); o.onProgress(5, 10); return { recording: o.recording, kind: "asset", slot: o.slot, bytes: file.size }; },
};
const make = (extra = {}) => createCaptionsView({ project: "@PROJECT@", recording: "@RID@", api, loopback: true, pollEvery: 200, autosaveMs: 40, ...extra });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const key = (node, k) => (node.listeners.keydown || []).forEach((fn) => fn({ key: k, preventDefault() {} }));
const blur = (node) => (node.listeners.blur || []).forEach((fn) => fn({}));
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
const stored = { x: 10, y: 20, w: 300, h: 300 };
const typed = (x, y, w, h) => ({ x, y, w, h });
out.preview = [m.faceBoxPreview(typed("", "", "", ""), null), m.faceBoxPreview(typed("1", "2", "3", "4"), null), m.faceBoxPreview(typed("", "", "", ""), stored), m.faceBoxPreview(typed("10", "", "", ""), stored), m.faceBoxPreview(typed("", "50", "", ""), stored),
  m.faceBoxPreview(typed("1", "2", "3", ""), null), m.faceBoxPreview(typed("1", "2", "x", "4"), null), m.faceBoxPreview(typed("1", "2", "0", "4"), null), m.faceBoxPreview(typed("900", "2", "300", "4"), null), m.faceBoxPreview(typed("1", "1900", "30", "30"), null),
  m.faceBoxPreview(typed("-1", "2", "30", "30"), null), m.faceBoxPreview(typed("", "", "1200", ""), stored)];
out.cover = [m.coverFromSeconds("1.5"), m.coverFromSeconds("1,5"), m.coverFromSeconds("0"), m.coverFromSeconds("-1"), m.coverFromSeconds("abc"), m.coverFromSeconds(""), m.coverFromSeconds("700")];
out.texts = [m.faceBoxText(null), m.faceBoxText({ x: 10, y: 20, w: 300, h: 300 }), m.coverText(0), m.coverText(1500), m.seconds(12.34), m.clock(75.2), m.clock(-1), m.scoreText(0.7234), m.scoreText(null)];
const err = (message, status = 409) => ({ name: "ApiError", status, message });
out.newWords = [m.reasonOf(err("refused: space_in_word edits[0].text")), m.reasonOf(err("refused: review_disagrees review")), m.reasonOf(err("task 5 is already being run by another process")),
  m.reasonOf(err("retake_lost retakes -- open the caption review again (prepare-again --step review) and confirm the retake again")), m.reasonOf(err("provider_output_invalid base")),
  m.failureText({ step: "base", code: "retake_lost", field: "", next: "" }), m.failureText({ step: "transcribe", code: "provider_output_invalid", field: "transcribe", next: "" }), m.failureText({ step: "render", code: "browser_failed", field: "render", next: "python3 providers/renderer/ffmpeg.py build --confirmed" }), m.failureText(null)];
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
def test_the_numbers_typed_for_a_face_box_are_a_preview_a_same_box_or_a_reason_said_for_what_is_wrong(tmp_path):
    got = run_model(tmp_path)["preview"]
    assert got[0] == {"state": "same"} and got[2] == {"state": "same"} and got[3] == {"state": "same"}, "nothing typed, or the stored numbers typed again, is no preview"
    assert got[1] == {"state": "valid", "box": {"x": 1, "y": 2, "w": 3, "h": 4}} and got[4] == {"state": "valid", "box": {"x": 10, "y": 50, "w": 300, "h": 300}}, "a field left empty is the stored box's"
    assert "all four numbers" in got[5]["reason"] and "whole numbers" in got[6]["reason"] and "above 0" in got[7]["reason"]
    for outside in (got[8], got[9], got[10], got[11]):
        assert outside["state"] == "invalid" and "outside the 1080 × 1920 frame" in outside["reason"], outside


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
    new = got["newWords"]
    assert [new[0]["code"], new[1]["code"], new[2]["code"], new[3]["code"], new[4]["code"]] == ["space_in_word", "review_disagrees", "busy", "retake_lost", "provider_output_invalid"]
    assert "cannot hold a space" in new[0]["text"] and "no longer agree" in new[1]["text"] and "another process" in new[2]["text"]
    assert new[3]["text"].endswith("confirm the retake again") and "Run: open the caption review again" in new[3]["text"] and new[3]["field"] == "retakes"
    assert new[5] == "Cut and caption stopped: A retake you confirmed no longer matches a repeat after your edits. Open the captions again and confirm it again."
    assert "cannot read as a result" in new[6] and new[7] == "Render the video stopped: browser_failed (render) Run: python3 providers/renderer/ffmpeg.py build --confirmed" and new[8] == ""
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


def page_table(name):
    source = MODEL_FILE.read_text(encoding="utf-8")
    return set(re.findall(r"^  ([a-z_]+): [\"`]", re.search(rf"export const {name} = Object.freeze\(\{{(.*?)\n\}}\);", source, re.S).group(1), re.M))


def test_every_closed_refusal_code_the_service_can_give_has_a_sentence_in_the_page():
    reasons, failures = page_table("REASONS"), page_table("FAILURE_WORDS")
    code = lambda name: (st.REPO / "runtime" / name).read_text(encoding="utf-8")
    refusals = set(re.findall(r'CaptionError\("([a-z_]+)"', code("captions.py")))
    refusals |= set(re.findall(r'"refused: ([a-z_]+)[ "]', code("ops_pipeline.py")))
    assert {"space_in_word", "review_disagrees", "stale_revision", "slot_needs_a_choice", "credential_in_transcript"} <= refusals
    assert refusals - reasons == set(), f"refusals of captions-edit and captions-done with no sentence: {sorted(refusals - reasons)}"
    steps = set(re.findall(r'StepFailure\("([a-z_]+)"', code("pipeline.py") + code("ops_pipeline.py")))
    steps |= set(re.findall(r'\("[^"]+", "([a-z_]+)"\)', re.search(r"TRANSCRIBER_TEXTS = \((.*?)\n\)", code("pipeline.py"), re.S).group(1)))
    nexts = re.findall(r'code (?:in \(([^)]*)\)|== "([a-z_]+)")', code("pipeline.py").split("def next_for")[1].split("def failure_from")[0])
    for group, single in nexts:
        steps |= set(re.findall(r'"([a-z_]+)"', group)) | ({single} if single else set())
    steps |= {"timeout", "usage", "failed", "not_configured", "cancelled", "script_refused"}
    assert {"retake_lost", "provider_output_invalid"} <= steps
    assert steps - failures - reasons == set(), f"step failures with no sentence: {sorted(steps - failures - reasons)}"
    assert "busy" in failures, "the sentence for 'already being run by another process'"


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
out.chip = text(find(root, ".pui-badge"));
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
await wait(120);
out.badBox = { text: text(find(root, "[data-key=face-pending]")), sent: sent().length };
script.next = () => ({ ...clone(small), revision: 3, applied: {} });
typeInto(find(root, "[data-key=face-w]"), "300"); typeInto(find(root, "[data-key=face-h]"), "320"); typeInto(find(root, "[data-key=face-x]"), "40"); typeInto(find(root, "[data-key=face-y]"), "60");
await wait(150);
out.numbers = sent()[2];
script.next = () => ({ ...clone(VIEW), revision: 4, applied: {} });
await press(find(root, "[data-key=clear-face]"));
out.clear = sent()[3];
// the cover
typeInto(find(root, "[data-key=cover]"), "abc");
await wait(120);
out.badCover = { text: text(find(root, "[data-key=cover-pending]")), sent: sent().length };
const covered = clone(VIEW); covered.revision = 5; covered.cover_offset_ms = 2500;
script.next = () => ({ ...clone(covered), applied: {} });
typeInto(find(root, "[data-key=cover]"), "2.5");
await wait(150);
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
    assert "outside the 1080 × 1920 frame" in got["badBox"]["text"] and got["badBox"]["sent"] == 2
    assert got["numbers"] == [{"op": "face_box", "x": 40, "y": 60, "w": 300, "h": 320}] and got["clear"] == [{"op": "face_box", "clear": True}]
    assert "inside the recording" in got["badCover"]["text"] and got["badCover"]["sent"] == 4
    assert got["cover"]["sent"] == [{"op": "cover", "offset_ms": 2500}] and "2.5 s" in got["cover"]["line"] and got["first"] == [{"op": "cover", "offset_ms": 0}]
    accepted_by_the_service(got["all"])


AUTOSAVE = r"""
const sent = () => calls.filter((c) => c[0] === "edit");
const dashed = (root) => all(root, "[data-key=facebox-preview]");
const pend = (root) => text(find(root, "[data-key=face-pending]"));
const f = (root, k) => find(root, `[data-key=face-${k}]`);
const typeBox = (root, x, y, w, h) => { typeInto(f(root, "x"), x); typeInto(f(root, "y"), y); typeInto(f(root, "w"), w); typeInto(f(root, "h"), h); };
const placed = (box, revision = 1) => { const v = clone(VIEW); v.revision = revision; v.face_box = box; return { ...v, applied: {} }; };
let gate = null;                       // a promise the service answers after
let running = 0, most = 0;
const slow = (box) => async (o) => { running += 1; most = Math.max(most, running); if (gate) await gate; running -= 1; return placed(box, o.revision + 1); };

// 1. the pause: a key press sends nothing; the save goes after the person stops, and the box is dashed until the service has accepted it
{
  const view = make({ autosaveMs: 200 });
  const root = view.el;
  await view.load(); await settle();
  out.start = { line: pend(root), dashed: dashed(root).length, buttons: all(root, "[data-key=set-face]").length + all(root, "[data-key=set-cover]").length };
  let release;
  gate = new Promise((r) => { release = r; });
  script.next = slow({ x: 100, y: 200, w: 300, h: 400 });
  typeBox(root, "100", "200", "300", "400");
  const rect = dashed(root)[0];
  out.typing = { sent: sent().length, line: pend(root), dashed: dashed(root).length, attrs: rect && [rect.attrs.x, rect.attrs.y, rect.attrs.width, rect.attrs.height], stored: all(root, "[data-key=facebox]").length };
  await wait(120);
  typeInto(f(root, "w"), "310");                 // another key: the pause starts again
  await wait(120);
  out.restarted = sent().length;                 // 240 ms since the first key, but only 120 since the last
  await wait(250);
  out.flight = { sent: sent().length, line: pend(root), dashed: dashed(root).length, stored: all(root, "[data-key=facebox]").length, edit: sent()[0] && sent()[0][2] };
  release(); gate = null; await wait(60);
  out.solid = { line: pend(root), dashed: dashed(root).length, stored: all(root, "[data-key=facebox]").length };
  view.close();
}

// 2. leaving the field, or Enter, saves at once (the pause is long here, so nothing else could have sent it)
{
  const view = make({ autosaveMs: 5000 });
  const root = view.el;
  await view.load(); await settle();
  const base = sent().length;
  script.next = slow({ x: 10, y: 20, w: 300, h: 300 });
  typeBox(root, "10", "20", "300", "300");
  out.beforeBlur = sent().length - base;
  blur(f(root, "h")); await wait(60);
  out.blur = sent().length - base;
  script.next = slow({ x: 11, y: 20, w: 300, h: 300 });
  typeInto(f(root, "x"), "11");
  key(f(root, "x"), "Enter"); await wait(60);
  out.enter = sent().length - base;
  view.close();
}

// 3. an invalid box is never sent, says why, and cancels what was waiting
{
  script.view = clone(VIEW);
  const view = make({ autosaveMs: 60 });
  const root = view.el;
  await view.load(); await settle();
  const before = sent().length;
  typeBox(root, "100", "200", "300", "400");            // valid and waiting ...
  typeInto(f(root, "w"), "2000");                        // ... then not
  const outside = { line: pend(root), dashed: dashed(root).length, invalid: find(root, "[data-key=face-pending]").cls().includes("is-invalid") };
  blur(f(root, "w")); await wait(150);
  typeInto(f(root, "w"), "abc"); const words = pend(root);
  typeInto(f(root, "w"), "0"); const zero = pend(root);
  typeInto(f(root, "w"), ""); const missing = pend(root);
  blur(f(root, "w")); await wait(150);
  out.invalid = { outside, words, zero, missing, sent: sent().length - before };
  script.next = slow({ x: 100, y: 200, w: 300, h: 400 });
  typeInto(f(root, "w"), "300");
  await wait(150);
  out.valid = { sent: sent().length - before, line: pend(root) };
  view.close();
}

// 4. a refused save keeps the numbers on screen and says why; Enter tries it again
{
  script.view = clone(VIEW);
  const view = make({ autosaveMs: 40 });
  const root = view.el;
  await view.load(); await settle();
  const before = sent().length;
  script.editError = new ApiError(409, "refused", "refused: bad_face_box face_box");
  typeBox(root, "1", "2", "300", "400");
  await wait(150);
  out.refused = { sent: sent().length - before, values: ["x", "y", "w", "h"].map((k) => f(root, k).value).join(","), line: pend(root), invalid: find(root, "[data-key=face-pending]").cls().includes("is-invalid"), dashed: dashed(root).length, notice: text(find(root, ".wb-notice-card")).slice(0, 28) };
  await wait(150);
  out.notAgain = sent().length - before;               // no loop of the same refusal
  script.editError = null;
  script.next = slow({ x: 1, y: 2, w: 300, h: 400 });
  key(f(root, "y"), "Enter"); await wait(80);
  out.retried = { sent: sent().length - before, line: pend(root), stored: all(root, "[data-key=facebox]").length };
  view.close();
}

// 5. the revision moved: the captions are read again and the person's numbers are sent once more
{
  script.view = clone(VIEW);
  const view = make({ autosaveMs: 40 });
  const root = view.el;
  await view.load(); await settle();
  const before = { edits: sent().length, reads: calls.filter((c) => c[0] === "read").length };
  let n = 0;
  script.next = async (o) => {
    n += 1;
    if (n === 1) {
      script.view = { ...clone(VIEW), revision: VIEW.revision + 5 };
      throw new ApiError(409, "refused", "refused: stale_revision revision");
    }
    return placed({ x: 7, y: 8, w: 300, h: 300 }, o.revision + 1);
  };
  typeBox(root, "7", "8", "300", "300");
  await wait(200);
  const edits = sent().slice(before.edits);
  out.stale = { edits: edits.length, revisions: edits.map((e) => e[1]), same: JSON.stringify(edits[0][2]) === JSON.stringify(edits[1][2]), reads: calls.filter((c) => c[0] === "read").length - before.reads, line: pend(root), stored: all(root, "[data-key=facebox]").length, error: all(root, ".wb-notice-card").length };
  // a second stale answer is not tried a third time
  const view2 = make({ autosaveMs: 40 });
  await view2.load(); await settle();
  const b2 = sent().length;
  script.next = async () => { script.view = { ...clone(VIEW), revision: script.view.revision + 1 }; throw new ApiError(409, "refused", "refused: stale_revision revision"); };
  typeBox(view2.el, "9", "9", "300", "300");
  await wait(250);
  out.twice = { edits: sent().length - b2, line: pend(view2.el) };
  view.close(); view2.close();
}

// 6. two saves are never out together; a newer valid box replaces one that has not left yet
{
  script.view = clone(VIEW);
  running = 0; most = 0;
  const view = make({ autosaveMs: 5000 });
  const root = view.el;
  await view.load(); await settle();
  const before = sent().length;
  let release;
  gate = new Promise((r) => { release = r; });
  script.next = slow({ x: 1, y: 1, w: 300, h: 300 });
  typeBox(root, "1", "1", "300", "300"); blur(f(root, "h")); await wait(40);
  typeBox(root, "2", "2", "300", "300"); blur(f(root, "h"));
  typeBox(root, "3", "3", "300", "300"); blur(f(root, "h")); await wait(40);
  out.gated = sent().length - before;                    // the first is out; the others wait behind it
  script.next = slow({ x: 3, y: 3, w: 300, h: 300 });
  release(); gate = null; await wait(120);
  const edits = sent().slice(before).map((e) => e[2][0]);
  out.stacked = { edits, most };
  view.close();
}

// 7. the cover saves itself too: after the pause, on leaving the field, with the reason when it cannot be
{
  script.view = clone(VIEW);
  const view = make({ autosaveMs: 5000 });
  const root = view.el;
  await view.load(); await settle();
  const before = sent().length;
  const cover = find(root, "[data-key=cover]");
  typeInto(find(root, "[data-key=cover]"), "abc");
  const bad = text(find(root, "[data-key=cover-pending]"));
  typeInto(cover, "2.5");
  const waiting = text(find(root, "[data-key=cover-pending]"));
  const covered = clone(VIEW); covered.revision = 1; covered.cover_offset_ms = 2500;
  script.next = async () => ({ ...clone(covered), applied: {} });
  const none = sent().length - before;
  blur(cover); await wait(60);
  out.cover = { bad, waiting, none, sent: sent().slice(before).map((e) => e[2]), line: text(find(root, "[data-key=cover-pending]")), value: find(root, "[data-key=cover]").value, button: all(root, "[data-key=set-cover]").length };
  view.close();
}

// 8. closing the view cancels a save that was waiting
{
  script.view = clone(VIEW);
  const view = make({ autosaveMs: 60 });
  await view.load(); await settle();
  const before = sent().length;
  typeBox(view.el, "5", "5", "300", "300");
  view.close(); await wait(150);
  out.closed = sent().length - before;
}
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_face_box_and_the_cover_save_themselves_after_a_pause_or_on_leaving_the_field_and_are_dashed_until_accepted(tmp_path):
    got = run(tmp_path, AUTOSAVE)
    assert got["start"] == {"line": "", "dashed": 0, "buttons": 0}, "no Set button is drawn for the face box or the cover"
    t = got["typing"]
    assert t["sent"] == 0 and t["line"] == "Saves when you stop typing." and t["dashed"] == 1 and t["stored"] == 0 and t["attrs"] == ["100", "200", "300", "400"], "four key presses send nothing; the box typed is drawn dashed, in frame pixels"
    assert got["restarted"] == 0, "a key press starts the pause again"
    assert got["flight"]["sent"] == 1 and got["flight"]["line"] == "Saving..." and got["flight"]["dashed"] == 1 and got["flight"]["stored"] == 0
    assert got["flight"]["edit"] == [{"op": "face_box", "x": 100, "y": 200, "w": 310, "h": 400}], "one save with the numbers as they were when the person stopped"
    assert got["solid"] == {"line": "", "dashed": 0, "stored": 1}, "accepted: the box is solid"
    assert (got["beforeBlur"], got["blur"], got["enter"]) == (0, 1, 2), "leaving a field, and Enter, save at once"


@needs_node
def test_an_invalid_box_is_not_sent_and_says_why_and_a_refused_one_keeps_the_numbers_and_is_not_sent_again_by_itself(tmp_path):
    got = run(tmp_path, AUTOSAVE)
    inv = got["invalid"]
    assert "outside the 1080 × 1920 frame" in inv["outside"]["line"] and inv["outside"]["dashed"] == 0 and inv["outside"]["invalid"] is True
    assert "whole numbers" in inv["words"] and "above 0" in inv["zero"] and "all four numbers" in inv["missing"]
    assert inv["sent"] == 0, "nothing invalid was sent, not even on leaving the field, and the valid box that was waiting was cancelled"
    assert got["valid"]["sent"] == 1 and got["valid"]["line"] == ""
    r = got["refused"]
    assert r["sent"] == 1 and r["values"] == "1,2,300,400" and r["dashed"] == 0 and r["invalid"] is True
    assert r["line"].startswith("The face box must be inside the frame") and r["notice"].startswith("The face box must be inside")
    assert got["notAgain"] == 1, "a refusal is not sent again until the person types or presses Enter"
    assert got["retried"] == {"sent": 2, "line": "", "stored": 1}


@needs_node
def test_a_stale_revision_reads_the_captions_again_and_sends_the_persons_numbers_once_more_and_never_a_third_time(tmp_path):
    got = run(tmp_path, AUTOSAVE)
    s = got["stale"]
    assert s["edits"] == 2 and s["same"] is True and s["revisions"][1] > s["revisions"][0], "the second call carries the revision that was read again, with the same edit"
    assert s["reads"] == 1 and s["line"] == "" and s["stored"] == 1 and s["error"] == 0
    assert got["twice"]["edits"] == 2 and "changed" in got["twice"]["line"].lower() or got["twice"]["edits"] == 2, got["twice"]


@needs_node
def test_two_saves_are_never_out_together_a_newer_valid_box_replaces_one_that_waits_and_the_cover_saves_itself(tmp_path):
    got = run(tmp_path, AUTOSAVE)
    assert got["gated"] == 1
    assert got["stacked"]["most"] == 1 and got["stacked"]["edits"] == [{"op": "face_box", "x": 1, "y": 1, "w": 300, "h": 300}, {"op": "face_box", "x": 3, "y": 3, "w": 300, "h": 300}], "the box in the middle never left"
    c = got["cover"]
    assert "inside the recording" in c["bad"] and c["waiting"] == "Saves when you stop typing." and c["none"] == 0 and c["sent"] == [[{"op": "cover", "offset_ms": 2500}]]
    assert c["line"] == "" and c["value"] == "2.5" and c["button"] == 0
    assert got["closed"] == 0, "a save that was waiting is dropped when the view closes"


def test_the_pause_before_a_save_is_six_hundred_milliseconds_and_no_setinterval_is_used():
    code = (JS / "floor" / "autosave.js").read_text(encoding="utf-8")
    assert "export const AUTOSAVE_MS = 600;" in code and "setInterval" not in code and "fetch(" not in code and "document." not in code


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
out.after = { chip: text(find(root, ".pui-badge")), editButtons: all(root, "button.wb-rev-word").length, words: all(root, ".wb-rev-word").length, steps: all(root, "[data-step]").length, reopen: find(root, "[data-key=reopen]") !== null, changed };
// the whole call carried the revision and nothing else
out.noText = JSON.stringify(out.sent).includes("text") || JSON.stringify(out.sent).includes("Depois");
await press(find(root, "[data-key=reopen]"));
out.reopen = calls.filter((c) => c[0] === "again").map((c) => c.slice(1));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_done_sends_the_revision_and_nothing_of_the_words_then_the_steps_are_the_video_cards_and_the_captions_can_be_opened_again(tmp_path):
    got = run(tmp_path, DONE)
    assert got["ready"]["off"] is False and "Done" in got["ready"]["label"] and got["ready"]["hint"] is True
    assert got["sent"] == [{"revision": 0, "keys": ["revision"]}] and got["noText"] is False, "Done carries the revision and no text"
    assert got["polled"] == 1
    assert got["after"]["chip"] == "Checked" and got["after"]["editButtons"] == 0 and got["after"]["steps"] == 0 and got["after"]["reopen"] is True and got["after"]["changed"] == 1
    assert got["reopen"] == [[RID, "review"]]


RUNNING = r"""
const done = clone(VIEW); done.slots[0].choice = "none"; script.view = done;
const view = make();
const root = view.el;
await view.load(); await settle();
let release; const held = new Promise((r) => { release = r; });
api.pollJob = async (id, every, o) => { calls.push(["poll", id]); o.onUpdate({ state: "running" }); await settle(); out.during = { chip: text(find(root, ".pui-badge")), steps: all(root, "[data-step]").length, words: all(root, ".wb-rev-word").length, done: find(root, "[data-key=done]") };
  await held; return { state: "done", result: { ok: true } }; };
script.media.pipeline.steps = { transcribe: "done", analyse: "done", retakes: "done", "align-proposal": "done", review: "done", remap: "done", base: "done", align: "done", check: "done", render: "pending", cover: "pending", approval: "pending" };
const after = clone(done); after.editable = false; script.view = after;
const pressing = press(find(root, "[data-key=done]"));
await settle(); await settle();
release();
await pressing; await settle();
out.end = text(find(root, ".pui-badge"));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_while_the_pipeline_goes_on_after_done_the_review_does_not_list_the_steps_the_video_card_does(tmp_path):
    got = run(tmp_path, RUNNING)
    assert got["during"]["chip"] == "Running" and got["during"]["steps"] == 0 and got["during"]["words"] == 0 and got["during"]["done"] is None, "one list of steps, in the card below: not drawn twice"
    assert got["end"] == "Checked"
    from_file = (JS / "floor" / "captions-view.js").read_text(encoding="utf-8")
    assert 'export const STEPS_IN_REVIEW = ["progress"];' in from_file, "the one line that puts the review's own list back"


PROGRESS = r"""
script.readError = new ApiError(409, "refused", "the captions are not ready: the pipeline is at align-proposal");
const view = make();
const root = view.el;
await view.load(); await settle();
out.progress = { chip: text(find(root, ".pui-badge")), steps: all(root, "[data-step]").length, statuses: all(root, "[data-step]").map((n) => n.attrs["data-step"] + ":" + n.cls().filter((c) => c.startsWith("is-"))[0]),
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
    assert "script was refused" in progress["failure"] and "(beat3)" in progress["failure"] and "Run: fix the post file, then prepare-again" in progress["failure"]


OFF_MAC = r"""
const view = make({ loopback: false });
const root = view.el;
await view.load(); await settle();
out.mac = { calls: calls.map((c) => c[0]), notice: text(find(root, ".wb-notice-card")), chip: text(find(root, ".pui-badge")), words: all(root, ".wb-rev-word").length, buttons: all(root, "button").map((b) => b.attrs["data-key"]), steps: all(root, "[data-step]").length };
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
    assert got["line"] == "Turned off for the page: captions-edit, captions-done, prepare-again. Use the terminal."


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
out.closed = { views: all(tab.el, "section.wb-rev").length, reads: calls.filter((c) => c[0] === "read").length };
toggle(2).click(); await settle();
out.plain = { views: all(tab.el, "section.wb-rev").length, reads: calls.filter((c) => c[0] === "read").length };
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
    assert "document." not in model and "fetch(" not in model and "window" not in model, "the model is pure"


def test_the_review_reads_well_at_a_phones_width_and_nothing_scrolls_sideways():
    floor = css_file("floor")
    phone = "\n".join(media_blocks(floor, "max-width: 899px"))
    assert ".wb-rev-matched, .wb-rev-plain, .wb-rev-beat-head, .wb-rev-steps, .wb-rev-heading, .wb-rev-details > summary { font-size: 16px; }" in phone
    assert "button.wb-rev-word { min-height: 44px; }" in phone and ".wb-rev-sizes .pui-chip { flex: 1 1 auto; min-height: 44px; justify-content: center; }" in phone
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


DONE_FAILS = r"""
const done = clone(VIEW); done.slots[0].choice = "none"; script.view = done;
const view = make();
const root = view.el;
await view.load(); await settle();
api.pollJob = async (id, every, o) => ({ state: "done", result: { ok: false, failed: "base", code: "retake_lost", field: "retakes", next: "open the caption review again (prepare-again --step review) and confirm the retake again" } });
script.view = { ...clone(done), editable: false };
await press(find(root, "[data-key=done]")); await settle(); await settle();
out.failed = { notice: text(find(root, ".wb-notice-card.is-error")), code: text(find(root, ".wb-rev-code")), chip: text(find(root, ".pui-badge")) };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_pipeline_that_stops_after_done_says_why_in_the_sentence_of_its_code_with_the_command(tmp_path):
    got = run(tmp_path, DONE_FAILS)["failed"]
    assert got["notice"].startswith("Cut and caption stopped: A retake you confirmed no longer matches a repeat") and "retakes" in got["notice"] and "Run: open the caption review again" in got["notice"]
    assert "retake_lost" in got["code"] and got["chip"] == "Checked"


# --- the review round: policy, slots, retakes, typed fields, the selection, leaks ------------------------------------------------------------------

POLICY_EDIT_ONLY = r"""
const done = clone(VIEW); done.slots[0].choice = "none"; script.view = done;
const view = make({ can: (op) => op !== "captions-edit" });
const root = view.el;
await view.load(); await settle();
out.shown = { words: all(root, "button.wb-rev-word").length, done: find(root, "[data-key=done]") ? off(find(root, "[data-key=done]")) : "none", save: find(root, "[data-key=save-word]"), line: text(find(root, "[data-key=withheld]")) };
script.view = { ...clone(done), editable: false };
await press(find(root, "[data-key=done]")); await settle(); await settle(); await settle();
out.sent = calls.filter((c) => c[0] === "done").map((c) => c[1]);
out.after = text(find(root, ".pui-badge"));
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_done_works_when_only_the_right_to_edit_is_withheld_because_it_sends_no_words(tmp_path):
    got = run(tmp_path, POLICY_EDIT_ONLY)
    assert got["shown"]["words"] == 0 and got["shown"]["done"] is False and got["shown"]["save"] is None
    assert got["shown"]["line"] == "Turned off for the page: captions-edit. Use the terminal."
    assert got["sent"] == [{"revision": 0, "keys": ["revision"]}] and got["after"] == "Checked", "Done sent the revision, and the pipeline went on"


SLOT_CHOICES = r"""
// media-in turned off: the slot can still be answered with a choice, and Done waits for it
let view = make({ can: (op) => op !== "media-in" });
let root = view.el;
await view.load(); await settle();
out.noUpload = { choose: find(root, "[data-key=choose-beat7]"), select: find(root, "[data-key=choice-beat7]") !== null, note: text(find(root, '[data-key="upload-off-beat7"]')), done: off(find(root, "[data-key=done]")) };
const select = find(root, "[data-key=choice-beat7]");
script.next = () => ({ ...clone(VIEW), revision: 1, slots: [{ ...clone(VIEW.slots[0]), choice: "none" }], applied: {} });
select.value = "none"; select.listeners.change.forEach((fn) => fn());
await settle();
out.chosen = { done: off(find(root, "[data-key=done]")), block: find(root, "[data-key=done-block]") };
view.close();
// a stale file does not answer the slot either: the choice is offered and Done waits
const stale = clone(VIEW); stale.slots[0].file = { name: "painel.png", type: "png", sha256: "ab", stale: true };
script.view = stale; script.next = null;
view = make(); root = view.el;
await view.load(); await settle();
out.stale = { state: text(find(root, '[data-key="slot-state-beat7"]')), select: find(root, "[data-key=choice-beat7]") !== null, done: off(find(root, "[data-key=done]")), block: text(find(root, "[data-key=done-block]")) };
// a file that is current is answered by itself: no choice is offered
const held = clone(VIEW); held.slots[0].file = { name: "painel.png", type: "png", sha256: "ab", stale: false };
script.view = held;
const view2 = make(); await view2.load(); await settle();
out.held = { select: find(view2.el, "[data-key=choice-beat7]"), done: off(find(view2.el, "[data-key=done]")) };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_an_asset_slot_can_always_be_answered_with_a_choice_so_neither_media_in_off_nor_a_stale_file_blocks_done(tmp_path):
    got = run(tmp_path, SLOT_CHOICES)
    assert got["noUpload"]["choose"] is None and got["noUpload"]["select"] is True and "media-in" in got["noUpload"]["note"] and got["noUpload"]["done"] is True
    assert got["chosen"] == {"done": False, "block": None}
    assert "description changed" in got["stale"]["state"] and got["stale"]["select"] is True and got["stale"]["done"] is True and "no file and no choice" in got["stale"]["block"]
    assert got["held"] == {"select": None, "done": False}


RETAKES2 = r"""
const two = clone(VIEW);
two.retakes.push({ id: "retake-2", kind: "repeat", seconds: 1.1, word_from: 60, word_to: 62, keep_from: 63, confirmed: true });
script.view = two;
const view = make();
const root = view.el;
await view.load(); await settle();
const rows = all(root, "[data-retake]").map((n) => ({ id: n.attrs["data-retake"], chip: text(find(n, ".pui-badge")), chipClass: find(n, ".pui-badge").attrs.class, confirmed: n.cls().includes("is-confirmed"), struck: find(n, ".wb-rev-struck").cls().join(" "), button: text(find(n, "button")) }));
out.rows = rows;
out.words = { proposed: all(root, ".wb-rev-word.is-retake").map((n) => n.attrs["data-index"]).join(","), cut: all(root, ".wb-rev-word.is-cut").map((n) => n.attrs["data-index"]).join(","), both: all(root, ".wb-rev-word.is-retake.is-cut").length };
out.aria = word(root, 35).attrs["aria-label"] + " | " + word(root, 61).attrs["aria-label"];
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_confirmed_cut_and_a_proposed_retake_are_told_apart_by_a_chip_a_decoration_and_a_colour_not_by_weight(tmp_path):
    got = run(tmp_path, RETAKES2)
    proposed, cut = got["rows"]
    assert (proposed["chip"], cut["chip"]) == ("proposed", "cut") and "pui-error" in cut["chipClass"] and "pui-error" not in proposed["chipClass"]
    assert (proposed["confirmed"], cut["confirmed"]) == (False, True) and (proposed["button"], cut["button"]) == ("Confirm the cut", "Undo")
    assert got["words"]["proposed"] == ",".join(str(i) for i in range(34, 41)) and got["words"]["cut"] == "60,61,62" and got["words"]["both"] == 0
    assert "retake proposed" in got["aria"].split(" | ")[0] and "retake, cut" in got["aria"].split(" | ")[1]
    css = css_file("floor")
    cut_rule = re.search(r"^\.wb-rev-word\.is-cut \{([^}]*)\}", css, re.M).group(1)
    proposed_rule = re.search(r"^\.wb-rev-word\.is-retake \{([^}]*)\}", css, re.M).group(1)
    assert "text-decoration-style: double" in cut_rule and "var(--pui-error)" in cut_rule and "background-color" in cut_rule and "font-weight" not in cut_rule
    assert "text-decoration-style: dashed" in proposed_rule and "background-color" not in proposed_rule and "var(--pui-error)" not in proposed_rule


TYPED = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
const sent = () => calls.filter((c) => c[0] === "edit");
const values = () => ["x", "y", "w", "h"].map((k) => find(root, `[data-key=face-${k}]`).value).join(",");
typeInto(find(root, "[data-key=cover]"), "2.5");
typeInto(find(root, "[data-key=face-w]"), "300"); typeInto(find(root, "[data-key=face-h]"), "320"); typeInto(find(root, "[data-key=face-x]"), "40"); typeInto(find(root, "[data-key=face-y]"), "60");
// refused: nothing typed is lost, and the reason is on screen beside the numbers
script.editError = new ApiError(409, "refused", "refused: bad_face_box face_box");
await wait(250);
out.refused = { cover: find(root, "[data-key=cover]").value, face: values(), faceLine: text(find(root, "[data-key=face-pending]")), coverLine: text(find(root, "[data-key=cover-pending]")), error: text(find(root, ".wb-notice-card")).slice(0, 30), dashed: all(root, "[data-key=facebox-preview]").length };
await press(find(root, "[data-key=cover-first]"));
out.refusedFirst = find(root, "[data-key=cover]").value;
// Enter sends the refused numbers again, and this time the service accepts them: the fields then show the box that was chosen
script.editError = null;
const placed = clone(VIEW); placed.revision = 1; placed.face_box = { x: 40, y: 60, w: 300, h: 320 };
script.next = () => ({ ...clone(placed), applied: {} });
key(find(root, "[data-key=face-x]"), "Enter");
await wait(120);
out.accepted = { face: values(), line: text(find(root, "[data-key=face-pending]")), stored: all(root, "[data-key=facebox]").length, dashed: all(root, "[data-key=facebox-preview]").length };
// a tap after the numbers sends the tap's box, not the old numbers
const tapped = clone(VIEW); tapped.revision = 2; tapped.face_box = { x: 330, y: 750, w: 420, h: 420 };
script.next = () => ({ ...clone(tapped), applied: {} });
const frame = find(root, "[data-key=frame]");
frame.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 178 });
typeInto(find(root, "[data-key=face-w]"), "111");
frame.listeners.click.forEach((fn) => fn({ clientX: 50, clientY: 89 }));
await wait(120);
out.tap = { sent: sent()[sent().length - 1][2], fields: values() };
// the cover typed is sent after the pause and then shows the new cover
const covered = clone(tapped); covered.revision = 3; covered.cover_offset_ms = 2500;
script.next = () => ({ ...clone(covered), applied: {} });
typeInto(find(root, "[data-key=cover]"), "2.5");
await wait(150);
out.cover = { value: find(root, "[data-key=cover]").value, sent: sent()[sent().length - 1][2] };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_refused_save_keeps_the_typed_cover_and_face_numbers_and_an_accepted_one_replaces_them(tmp_path):
    got = run(tmp_path, TYPED)
    assert got["refused"]["cover"] == "2.5" and got["refused"]["face"] == "40,60,300,320" and got["refused"]["dashed"] == 0, "the numbers and the seconds typed are still there to correct"
    assert got["refused"]["faceLine"].startswith("The face box must be inside the frame") and got["refused"]["error"].startswith("The face box must be inside"), "the reason is beside the numbers and in the notes"
    assert got["refusedFirst"] == "2.5"
    assert got["accepted"] == {"face": "40,60,300,320", "line": "", "stored": 1, "dashed": 0}, "after an accepted save the fields show the box that was chosen, and it is solid"
    assert got["tap"]["sent"] == [{"op": "face_box", "x": 330, "y": 750, "w": 420, "h": 420}] and got["tap"]["fields"] == "330,750,420,420"
    assert got["cover"] == {"value": "2.5", "sent": [{"op": "cover", "offset_ms": 2500}]}


REREAD = r"""
const view = make();
const root = view.el;
await view.load(); await settle();
await press(word(root, 3));
typeInto(find(root, "[data-key=word]"), "typed for word four");
script.editError = new ApiError(409, "refused", "refused: stale_revision revision");
await press(find(root, "[data-key=save-word]"));
out.stale = { line: text(find(root, "[data-key=selection-line]")), input: find(root, "[data-key=word]").value };
// the words moved while the person looked away: the revision read is another one
const moved = clone(VIEW); moved.revision = 7; moved.words[3].text = "changed elsewhere";
script.view = moved; script.editError = null;
await press(find(root, "[data-key=reread]"));
out.after = { revision: view.snapshot().view.revision, selection: view.snapshot().selection, line: text(find(root, "[data-key=selection-line]")), input: find(root, "[data-key=word]"), word: text(word(root, 3)) };
// reading again with the same revision keeps the selection and what is typed
await press(word(root, 5));
typeInto(find(root, "[data-key=word]"), "kept");
await view.load({ quiet: true }); await settle();
out.same = { selection: view.snapshot().selection, input: find(root, "[data-key=word]").value };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_reading_again_after_the_words_moved_clears_the_selection_and_the_typed_text_so_it_cannot_land_on_another_word(tmp_path):
    got = run(tmp_path, REREAD)
    assert got["stale"]["line"].startswith("Word 4 selected") and got["stale"]["input"] == "typed for word four"
    assert got["after"] == {"revision": 7, "selection": None, "line": "Select a word to change it; select a second word to take the words between them.", "input": None, "word": "changed elsewhere"}
    assert got["same"] == {"selection": {"from": 5, "to": 5}, "input": "kept"}


CLOSED = r"""
let unhandled = 0;
process.on("unhandledRejection", () => { unhandled += 1; });
const done = clone(VIEW); done.slots[0].choice = "none"; script.view = done;
let changed = 0; let seen = null;
api.pollJob = (id, every, o) => { seen = o; return new Promise((resolve, reject) => { o.signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" }))); o.onUpdate({ state: "running" }); }); };
api.mediaList = async () => { if (seen && seen.signal.aborted) throw Object.assign(new Error("aborted"), { name: "AbortError" }); return { recordings: [clone(script.media)] }; };
const view = make({ changed: () => { changed += 1; } });
const root = view.el;
await view.load(); await settle();
const pressing = press(find(root, "[data-key=done]"));
await settle(); await settle();
out.signal = { given: Boolean(seen && seen.signal), aborted: seen.signal.aborted };
view.close();
seen.onUpdate({ state: "running" });                   // a late update after close reads the media list, which fails: nobody is left to hear it
await pressing; await settle(); await settle();
out.closed = { aborted: seen.signal.aborted, changed, unhandled, mode: view.snapshot().mode };
const again = make({ changed: () => { changed += 1; } });
again.close();
await again.load(); await settle();
out.afterClose = { changed, unhandled };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_view_that_closed_while_a_job_ran_aborts_it_hears_nothing_after_and_tells_nobody(tmp_path):
    got = run(tmp_path, CLOSED)
    assert got["signal"] == {"given": True, "aborted": False}
    assert got["closed"]["aborted"] is True and got["closed"]["changed"] == 0 and got["closed"]["unhandled"] == 0
    assert got["afterClose"] == {"changed": 0, "unhandled": 0}


RANGES = r"""
const mixed = clone(VIEW);
mixed.chunks = mixed.chunks.filter((c) => !c.words.some((i) => i >= 12 && i <= 15));      // the words 12 to 15 are in no chunk: they are drawn in the group of words left out
script.view = mixed;
const view = make();
const root = view.el;
await view.load(); await settle();
out.drawn = { outside: text(find(root, ".wb-rev-chunk.is-outside")).includes(mixed.words[12].text), inChunk: find(root, ".wb-rev-chunk:not(.is-outside)") !== null };
await press(word(root, 11));
await press(word(root, 17));
out.mixed = { error: text(find(root, ".wb-notice-card")), selection: view.snapshot().selection, code: text(find(root, ".wb-rev-code")) };
// a range of words drawn together is fine, inside the group left out too
await press(find(root, "[data-key=clear-selection]"));
await press(word(root, 8)); await press(word(root, 10));
out.together = view.snapshot().selection;
await press(find(root, "[data-key=clear-selection]"));
await press(word(root, 12)); await press(word(root, 15));
out.outside = view.snapshot().selection;
// shift-click on a range extends it; it never shrinks it or starts from its far end
await press(find(root, "[data-key=clear-selection]"));
await press(word(root, 3)); await press(word(root, 6));
word(root, 9).listeners.click[0]({ shiftKey: true }); await settle();
out.shiftRight = view.snapshot().selection;
word(root, 1).listeners.click[0]({ shiftKey: true }); await settle();
out.shiftLeft = view.snapshot().selection;
word(root, 5).listeners.click[0]({ shiftKey: true }); await settle();
out.shiftInside = view.snapshot().selection;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_range_never_takes_in_a_word_drawn_elsewhere_and_shift_click_extends_a_range_from_either_end(tmp_path):
    got = run(tmp_path, RANGES)
    assert got["drawn"] == {"outside": True, "inChunk": True}
    assert "shown somewhere else" in got["mixed"]["error"] and got["mixed"]["code"].strip() == "mixed_range" and got["mixed"]["selection"] == {"from": 11, "to": 11}, "refused with a sentence; the selection stays"
    assert got["together"] == {"from": 8, "to": 10}
    assert got["outside"] == {"from": 12, "to": 15}
    assert got["shiftRight"] == {"from": 3, "to": 9} and got["shiftLeft"] == {"from": 1, "to": 9} and got["shiftInside"] == {"from": 1, "to": 9}


BIG = r"""
const big = clone(VIEW);
big.words = Array.from({ length: 600 }, (_, i) => ({ index: i, text: `w${i}`, start: i, end: i + 0.5, segment: 0, estimated: false, edited: false, origin: [i, i], timing_adjusted: false, chunk: 0, left_out: null }));
big.chunks = [{ chunk: 0, words: big.words.map((w) => w.index) }];
big.retakes = []; big.beats = []; big.unplaced = []; big.slots = []; big.counts = { ...big.counts, words: 600 };
script.view = big;
const view = make();
const root = view.el;
await view.load(); await settle();
await press(word(root, 0)); await press(word(root, 599));
await press(find(root, "[data-key=delete-words]"));
out.refused = { text: text(find(root, ".wb-notice-card")), sent: calls.filter((c) => c[0] === "edit").length, selection: view.snapshot().selection };
await press(find(root, "[data-key=clear-selection]"));
await press(word(root, 0)); await press(word(root, 499));
await press(find(root, "[data-key=delete-words]"));
out.allowed = { sent: calls.filter((c) => c[0] === "edit").map((c) => c[2].length) };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_delete_over_the_services_cap_is_refused_with_a_sentence_and_sends_nothing(tmp_path):
    got = run(tmp_path, BIG)
    assert "at most 500 words" in got["refused"]["text"] and got["refused"]["sent"] == 0 and got["refused"]["selection"] == {"from": 0, "to": 599}
    assert got["allowed"]["sent"] == [500]


def test_the_edit_cap_the_page_knows_is_the_services():
    assert int(re.search(r"export const MAX_EDITS = (\d+);", MODEL_FILE.read_text(encoding="utf-8")).group(1)) == cap.MAX_EDITS


SMALL = r"""
// reopen: a failed job, and a pipeline that stops, are told
let view = make();
let root = view.el;
const after = clone(VIEW); after.editable = false; script.view = after;
await view.load(); await settle();
api.pollJob = async () => ({ state: "failed", error: { message: "the job could not start" } });
await press(find(root, "[data-key=reopen]")); await settle();
out.failedJob = text(find(root, ".wb-notice-card.is-error"));
api.pollJob = async () => ({ state: "done", result: { ok: false, failed: "review", code: "retake_lost", field: "", next: "" } });
await press(find(root, "[data-key=reopen]")); await settle();
out.stopped = text(find(root, ".wb-notice-card.is-error")).slice(0, 90);
// "Check again" clears an old error
await press(find(root, "[data-key=reload]")); await settle();
out.cleared = find(root, ".wb-notice-card.is-error");
view.close();
// the cover cannot be later than the recording when its length is known
const rec = clone(MEDIA); rec.raw = { duration: 30 };
script.media = rec; script.view = clone(VIEW);
view = make(); root = view.el;
await view.load(); await settle();
typeInto(find(root, "[data-key=cover]"), "45");
await wait(120);
out.late = { text: text(find(root, "[data-key=cover-pending]")), sent: calls.filter((c) => c[0] === "edit").length };
typeInto(find(root, "[data-key=cover]"), "30");
await wait(120);
out.limit = calls.filter((c) => c[0] === "edit").map((c) => c[2]);
// marks of a word that is only read are in the page: a data-marks attribute that a CSS rule shows after the word
const reading = make({ can: (op) => op !== "captions-edit" });
await reading.load(); await settle();
out.marks = { adjusted: word(reading.el, 0).attrs["data-marks"], retake: word(reading.el, 34).attrs["data-marks"], none: word(reading.el, 20).attrs["data-marks"] === undefined, tag: word(reading.el, 0).tagName };
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_small_things_of_the_review_a_failed_reopen_check_again_the_cover_bound_and_visible_marks(tmp_path):
    got = run(tmp_path, SMALL)
    assert got["failedJob"] == "the job could not start" and got["stopped"].startswith("Check the captions stopped: A retake you confirmed")
    assert got["cleared"] is None
    assert "later than the recording" in got["late"]["text"] and "30.0 s" in got["late"]["text"] and got["late"]["sent"] == 0 and got["limit"] == [[{"op": "cover", "offset_ms": 30000}]]
    assert got["marks"] == {"adjusted": "timing adjusted", "retake": "retake proposed", "none": True, "tag": "SPAN"}
    css = css_file("floor")
    assert re.search(r"^span\.wb-rev-word\[data-marks\]::after \{[^}]*attr\(data-marks\)", css, re.M)

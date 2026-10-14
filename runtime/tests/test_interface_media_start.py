"""The page starts the media pipeline (interface/js/floor/media-start.js and media-start-model.js, `api.mediaPipeline` of js/api.js, its place in the Tasks tab and the Agent tab):
"New short video" (upload a recording that needs no task) and "Edit this recording" (choose the post file and the network, start `media-pipeline`, watch the steps to "Check the
captions"). Run under Node with a fake document and a fake client: no browser, no service, no network. The service half is tested in test_media_pipeline*.py.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_media_start.py
"""
from __future__ import annotations

import json
import os
import re

import standin_tree as st
from interface_css import css_file
from test_interface_floor import INTERFACE, JS, needs_node, run_node
from test_interface_phone_sheet import media_blocks

START = JS / "floor" / "media-start.js"
MODEL = JS / "floor" / "media-start-model.js"
RID = "0123456789abcdef"
RID2 = "fedcba9876543210"
PROJECT = "0123456789ab"

# --- the pure model ----------------------------------------------------------------------------------------------------------------------

PURE = r"""
import * as m from "@JS@/floor/media-start-model.js";
const out = {};
const post = "# Post\n\n- Owner: mkt-social-copy\n- Network: Instagram\n\n```script\nbeat: 1\nline: hi\n```\n";
out.script = [m.hasScript(post), m.hasScript("```post\nx\n```"), m.hasScript(null), m.hasScript("text ```script inline")];
out.network = [m.networkOf(post), m.networkOf("- Network: tiktok-br  \n"), m.networkOf("no line"), m.networkOf("- Network: bad network"), m.networkOf(null)];
out.path = ["docs/marketing/content/a.md", "docs/../x.md", "notes/a.md", "docs/a.txt", " docs/a.md ", "docs//a.md", "", null].map((p) => m.postPath(p));
const arts = [
  { path: "docs/marketing/content/2026-10-01-a.md", owner: "mkt-social-copy", kind: "markdown", modified_at: "2026-10-01T10:00:00Z" },
  { path: "docs/marketing/content/2026-10-03-b.md", owner: "mkt-social-copy", kind: "markdown", modified_at: "2026-10-03T10:00:00Z" },
  { path: "docs/other/c.md", owner: "eng-implement", kind: "markdown", modified_at: "2026-10-04T10:00:00Z" },
  { path: "docs/marketing/content/2026-10-06-d.md", owner: null, kind: "markdown", modified_at: "2026-10-06T10:00:00Z" },
  { path: "docs/other/e.md", owner: "mkt-social-copy", kind: "markdown", modified_at: "2026-10-07T10:00:00Z" },
  { path: "docs/marketing/content/sub/f.md", owner: null, kind: "markdown", modified_at: "2026-10-08T10:00:00Z" },
  { path: "docs/marketing/image.png", owner: "mkt-social-copy", kind: "image", modified_at: "2026-10-05T10:00:00Z" },
  { path: "notes/x.md", owner: "mkt-social-copy", kind: "markdown" },
];
out.candidates = m.postCandidates(arts).map((a) => a.path);
out.many = m.postCandidates(Array.from({ length: 40 }, (_, i) => ({ path: `docs/p${i}.md`, owner: "mkt-social-copy", kind: "markdown", modified_at: `2026-10-${String(10 + (i % 20)).padStart(2, "0")}` }))).length;
out.none = [m.postCandidates(null).length, m.postCandidates([null, 3]).length];
const rec = (id, extra = {}) => ({ id, status: "open", raw: { bytes: 3.4 * 1024 * 1024, duration: 32, name: "take.mp4" }, pipeline: null, created_at: "2026-10-14T10:00:00Z", ...extra });
out.waiting = m.waitingRecordings([rec("a".repeat(16)), rec("b".repeat(16), { pipeline: { steps: {} } }), rec("c".repeat(16), { status: "closed" }), rec("d".repeat(16), { raw: null }), rec("e".repeat(16), { purged_raw: true }), rec("f".repeat(16), { created_at: "2026-10-15T10:00:00Z" }), null]).map((r) => r.id[0]);
out.line = [m.recordingLine({ id: RID, bytes: 3.4 * 1024 * 1024, duration: 32 }), m.recordingLine({ id: RID, bytes: 0, duration: null })];
const err = (message, status = 409) => ({ name: "ApiError", status, message });
out.refusals = m.REFUSALS.map(([pattern]) => m.refusalText(err(`x ${pattern.source.replace(/\\\//g, "/").replace(/\\`/g, "`").split("|")[0].replace(/\\/g, "")} y`)));
out.other = [m.refusalText(err("", 0)), m.refusalText(err("gone", 404)), m.refusalText(err("something new")), m.refusalText(null), m.refusalText(err("the recording has no post file for tiktok: give it with --post"))];
console.log(JSON.stringify(out));
""".replace("RID", json.dumps(RID))


@needs_node
def test_the_model_finds_the_post_files_the_network_and_the_recordings_that_wait_and_never_guesses(tmp_path):
    got = run_node(tmp_path, PURE)
    assert got["script"] == [True, False, False, False]
    assert got["network"] == ["instagram", "tiktok-br", None, None, None]
    assert got["path"] == ["docs/marketing/content/a.md", None, None, None, "docs/a.md", None, None, None]
    assert got["candidates"] == ["docs/other/e.md", "docs/marketing/content/2026-10-06-d.md", "docs/marketing/content/2026-10-03-b.md", "docs/marketing/content/2026-10-01-a.md"], "the post-writing skill's Markdown under docs/ (by owner, or by the folder it writes in), newest first"
    assert got["many"] == 20 and got["none"] == [0, 0]
    assert got["waiting"] == ["f", "a"], "stored, open, not started, with a file; the newest first"
    assert got["line"] == ["Recording 01234567, 32.0 s, 3.4 MiB", "Recording 01234567"]
    assert len(got["refusals"]) == 11 and len(set(got["refusals"])) == 11 and all(not s.startswith("x ") for s in got["refusals"]), got["refusals"]
    assert got["other"][0].startswith("The service could not be reached") and "cannot start the pipeline from here" in got["other"][1] and got["other"][2] == "something new" and got["other"][3] == "The pipeline could not be started."
    assert got["other"][4] == "That network has no post file for this recording: choose the post file.", "the order of the table matters: this one also says `the recording has no post file`"


def test_every_refusal_the_page_tells_in_a_sentence_is_one_the_service_gives():
    """The patterns of REFUSALS are the words of runtime/ops_pipeline.py and runtime/media.py: a reworded refusal there breaks this test, not the page."""
    source = "\n".join((INTERFACE.parent / "runtime" / name).read_text(encoding="utf-8") for name in ("ops_pipeline.py", "media.py", "ops_core.py"))
    table = MODEL.read_text(encoding="utf-8").split("export const REFUSALS", 1)[1].split("]);", 1)[0]
    patterns = re.findall(r"\[/(.+?)/, \"", table)
    assert len(patterns) == 11
    for pattern in patterns:
        for alternative in pattern.split("|"):
            assert alternative.replace("\\", "") in source, f"the service no longer says: {alternative}"


# --- the view -----------------------------------------------------------------------------------------------------------------------------

PRELUDE = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createMediaStart } from "@JS@/floor/media-start.js";
import { ApiError } from "@JS@/api.js";

const RID = "@RID@", RID2 = "@RID2@";
const clone = (v) => JSON.parse(JSON.stringify(v));
const text = (n) => n.textContent;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const calls = [];
const POST = (network) => `# Post\n\n- Owner: mkt-social-copy\n${network ? `- Network: ${network}\n` : ""}\n\`\`\`script\nbeat: 1\nline: hi\n\`\`\`\n`;
const DOCS = {
  "docs/marketing/content/2026-10-03-a.md": POST("instagram"),
  "docs/marketing/content/2026-10-02-b.md": POST(null),
  "docs/marketing/content/2026-10-01-c.md": "# A post with no script\n- Network: instagram\n",
};
const script = {
  recordings: [{ id: RID, status: "open", raw: { bytes: 3 * 1024 * 1024, duration: 32, name: "take <b>one</b>.mp4" }, pipeline: null, created_at: "2026-10-14T10:00:00Z" }],
  artifacts: Object.keys(DOCS).map((path, i) => ({ path, owner: i === 0 ? "mkt-social-copy" : null, kind: "markdown", modified_at: `2026-10-0${3 - i}T10:00:00Z` })),
  platforms: ["instagram", "linkedin", "tiktok"], startError: null, result: { ok: true, task: 2, stopped: "review" }, pollState: "done", pollError: null, jobMessage: "the job could not start",
};
const api = {
  mediaList: async (p, o) => { calls.push(["media-list"]); return { recordings: clone(script.recordings), platforms: clone(script.platforms) }; },
  artifacts: async () => { calls.push(["artifacts"]); return { artifacts: clone(script.artifacts) }; },
  artifact: async (p, path) => { calls.push(["artifact", path]); if (!(path in DOCS)) throw new ApiError(404, "not_found", "no"); return { path, text: DOCS[path] }; },
  mediaPipeline: async (p, rid, o) => { calls.push(["pipeline", rid, { post: o.post, network: o.network, keys: Object.keys(o).filter((k) => k !== "signal").sort() }]); if (script.startError) throw script.startError; return { job: 7, state: "running" }; },
  pollJob: async (id, every, o) => {
    calls.push(["poll", id]);
    script.recordings = script.recordings.map((r) => (r.id === RID ? { ...r, pipeline: { task: 2, steps: { transcribe: "done", analyse: "done", review: "waiting", base: "pending" }, failure: null } } : r));
    if (o && o.onUpdate) o.onUpdate({ state: "running" });
    await settle();
    if (script.pollError) throw script.pollError;
    return { state: script.pollState, result: script.result, error: script.pollState === "failed" ? { error: "refused", message: script.jobMessage, status: 409 } : null };
  },
  uploadMedia: async (p, file, o) => { calls.push(["upload", file.name, o.recording || null]); o.onProgress(5, 10); script.recordings.push({ id: RID2, status: "open", raw: { bytes: file.size, duration: 12, name: file.name }, pipeline: null, created_at: "2026-10-15T10:00:00Z" }); return { recording: RID2, kind: "recording", bytes: file.size }; },
};
const make = (extra = {}) => createMediaStart({ project: "@PROJECT@", api, loopback: true, pollEvery: 20, ...extra });
const typeInto = (node, value) => { node.value = value; (node.listeners.input || []).forEach((fn) => fn()); };
const choose = (node, value) => { node.value = value; (node.listeners.change || []).forEach((fn) => fn()); };
const key = (root, k) => find(root, `[data-key="${k}"]`);
const off = (n) => "disabled" in n.attrs;
const out = {};
"""


def run(tmp_path, body, real=None):
    script = (PRELUDE + body).replace("@PROJECT@", PROJECT).replace("@RID@", RID).replace("@RID2@", RID2).replace("@REAL@", json.dumps(real or {}))
    return run_node(tmp_path, script)


OFFER = r"""
// a stored recording that was never started is offered from media-list, so that a reload strands none; with several post files the page asks and never picks
const view = make();
const root = view.el;
await view.load(); await settle();
out.offer = { rows: all(root, "li.wb-sv-row").length, head: text(find(root, ".wb-sv-head")), name: text(find(root, ".wb-sv-head")).includes("<b>one</b>"), bolds: all(root, "b").length, posts: all(key(root, `sv-post-${RID}`), "option").map((o) => o.textContent),
  readDocs: calls.filter((c) => c[0] === "artifact").map((c) => c[1]).sort(), start: off(key(root, `sv-start-${RID}`)), why: text(key(root, `sv-why-${RID}`)) };
const select = key(root, `sv-post-${RID}`);
choose(select, "docs/marketing/content/2026-10-02-b.md");           // a post that names no network: the person chooses it among the platforms the service knows
out.noNetwork = { start: off(key(root, `sv-start-${RID}`)), why: text(key(root, `sv-why-${RID}`)), options: all(key(root, `sv-net-${RID}`), "option").map(text), tag: key(root, `sv-net-${RID}`).tagName };
choose(key(root, `sv-net-${RID}`), "tiktok");
out.network = { start: off(key(root, `sv-start-${RID}`)), why: text(key(root, `sv-why-${RID}`)) };
choose(key(root, `sv-post-${RID}`), "docs/marketing/content/2026-10-03-a.md");       // a post that names its network: no field, the line says it
out.fromPost = { text: text(key(root, `sv-network-${RID}`)), field: Boolean(key(root, `sv-net-${RID}`)), start: off(key(root, `sv-start-${RID}`)) };
await key(root, `sv-start-${RID}`).click(); await wait(80); await settle();
const piped = calls.filter((c) => c[0] === "pipeline");
out.afterStart = { form: Boolean(key(root, `sv-start-${RID}`)), select: Boolean(key(root, `sv-post-${RID}`)) };
out.started = { piped: piped.map((c) => c.slice(1)), polled: calls.filter((c) => c[0] === "poll").length, result: text(key(root, `sv-result-${RID}`)), steps: all(root, ".wb-sv-step").map((n) => n.attrs["data-step"] + ":" + n.cls().find((c) => c.startsWith("is-"))) };
view.close();
// a reload: a new view over the same store offers the recording again when no pipeline was started
script.recordings = script.recordings.map((r) => ({ ...r, pipeline: null }));
const again = make();
await again.load(); await settle();
out.reload = all(again.el, "li.wb-sv-row").length;
again.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_stored_recording_is_offered_with_the_post_files_found_and_the_network_and_starts_the_pipeline_with_exactly_what_was_chosen(tmp_path):
    got = run(tmp_path, OFFER)
    o = got["offer"]
    assert o["rows"] == 1 and o["head"].startswith("Recording 01234567, 32.0 s, 3.0 MiB") and o["name"] is True and o["bolds"] == 0, "every value is text, never markup"
    assert o["posts"] == ["Choose the post file", "docs/marketing/content/2026-10-03-a.md (instagram)", "docs/marketing/content/2026-10-02-b.md", "another file..."], "only the post files that carry a script, with the network each names, and the way to name another"
    assert o["readDocs"] == ["docs/marketing/content/2026-10-01-c.md", "docs/marketing/content/2026-10-02-b.md", "docs/marketing/content/2026-10-03-a.md"]
    assert o["start"] is True and o["why"] == "Choose the post file.", "several post files: the page asks, it never picks"
    assert got["noNetwork"] == {"start": True, "why": "Choose the network this post is for.", "options": ["Choose the network", "instagram", "linkedin", "tiktok"], "tag": "SELECT"}, "the networks are the ones the service gave: none is written in the page"
    assert got["network"] == {"start": False, "why": ""}
    assert got["fromPost"] == {"text": "Network: instagram (from the post file)", "field": False, "start": False}
    assert got["started"]["piped"] == [[RID, {"post": "docs/marketing/content/2026-10-03-a.md", "network": "instagram", "keys": ["network", "post"]}]], "no model and no request are sent: the post and the network only"
    assert got["afterStart"] == {"form": False, "select": False}, "once the pipeline stopped at the review the form is gone: the sentence says where to go"
    assert got["started"]["polled"] >= 1
    assert got["started"]["result"] == "It stopped at \"Check the captions\" (task #2): open that task in the Tasks tab to check the words."
    assert got["started"]["steps"][:4] == ["transcribe:is-done", "analyse:is-done", "review:is-waiting", "base:is-pending"], "the steps progress as the pipeline runs"
    assert got["reload"] == 1, "a reload does not strand a stored recording"


ONE = r"""
// one post file is still a click, never a pre-selection; none asks for the path; "another file..." types one; a post that names a network with no data file is told
const one = clone(script.artifacts).slice(0, 1);
script.artifacts = one;
let view = make();
await view.load(); await settle();
out.one = { start: off(key(view.el, `sv-start-${RID}`)), selected: key(view.el, `sv-post-${RID}`).value };
choose(key(view.el, `sv-post-${RID}`), "docs/marketing/content/2026-10-03-a.md");
out.clicked = { start: off(key(view.el, `sv-start-${RID}`)), selected: key(view.el, `sv-post-${RID}`).value };
// another file: the select gains a typed path, and the network is chosen (the page did not read that file)
choose(key(view.el, `sv-post-${RID}`), "__other__");
out.other = { path: Boolean(key(view.el, `sv-path-${RID}`)), start: off(key(view.el, `sv-start-${RID}`)), why: text(key(view.el, `sv-why-${RID}`)) };
typeInto(key(view.el, `sv-path-${RID}`), "docs/marketing/content/elsewhere.md");
out.otherNet = { start: off(key(view.el, `sv-start-${RID}`)), why: text(key(view.el, `sv-why-${RID}`)), select: Boolean(key(view.el, `sv-net-${RID}`)) };
choose(key(view.el, `sv-net-${RID}`), "linkedin");
out.otherReady = off(key(view.el, `sv-start-${RID}`));
await key(view.el, `sv-start-${RID}`).click(); await wait(80); await settle();
out.otherSent = calls.filter((c) => c[0] === "pipeline").map((c) => c[2]);
view.close();
script.recordings = script.recordings.map((r) => ({ ...r, pipeline: null }));      // as if it had not started
// a post that names a network the service has no data file for
DOCS["docs/marketing/content/2026-10-03-a.md"] = POST("myspace");
script.artifacts = clone(one);
view = make();
await view.load(); await settle();
choose(key(view.el, `sv-post-${RID}`), "docs/marketing/content/2026-10-03-a.md");
out.unknownNetwork = { start: off(key(view.el, `sv-start-${RID}`)), why: text(key(view.el, `sv-why-${RID}`)) };
view.close();
script.artifacts = [];
view = make();
await view.load(); await settle();
const root = view.el;
out.none = { hint: text(key(root, `sv-noposts-${RID}`)), select: Boolean(key(root, `sv-post-${RID}`)), start: off(key(root, `sv-start-${RID}`)), why: text(key(root, `sv-why-${RID}`)) };
typeInto(key(root, `sv-path-${RID}`), "../secret.md");
out.bad = { start: off(key(root, `sv-start-${RID}`)), why: text(key(root, `sv-why-${RID}`)) };
typeInto(key(root, `sv-path-${RID}`), "docs/marketing/content/x.md");
out.path = { start: off(key(root, `sv-start-${RID}`)), why: text(key(root, `sv-why-${RID}`)) };
choose(key(root, `sv-net-${RID}`), "instagrm");        // a value that is not one of the options is not a network
out.badNet = { start: off(key(root, `sv-start-${RID}`)) };
choose(key(root, `sv-net-${RID}`), "instagram");
out.ready = { start: off(key(root, `sv-start-${RID}`)), kept: key(root, `sv-path-${RID}`).value };
view.close();
// the post files could not be read: its own sentence, not "none found"
api.artifacts = async () => { throw new ApiError(0, "network", "x"); };
view = make();
await view.load(); await settle();
out.unreadable = text(key(view.el, `sv-noposts-${RID}`));
view.close();
// a service that sends no platform list (an older one): the network is typed, and the service decides
script.platforms = [];
api.artifacts = async () => ({ artifacts: [] });
view = make();
await view.load(); await settle();
typeInto(key(view.el, `sv-path-${RID}`), "docs/marketing/content/x.md");
typeInto(key(view.el, `sv-net-${RID}`), "Instagram");
out.typedNet = { tag: key(view.el, `sv-net-${RID}`).tagName, start: off(key(view.el, `sv-start-${RID}`)) };
view.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_one_post_file_is_a_click_none_or_another_asks_for_the_path_and_a_wrong_path_or_network_is_not_sent(tmp_path):
    got = run(tmp_path, ONE)
    assert got["one"] == {"start": True, "selected": ""}, "even a single post file is chosen by a click: the choice is explicit"
    assert got["clicked"] == {"start": False, "selected": "docs/marketing/content/2026-10-03-a.md"}
    assert got["other"] == {"path": True, "start": True, "why": "Type the path of the post file."}
    assert got["otherNet"] == {"start": True, "why": "Choose the network this post is for.", "select": True}
    assert got["otherReady"] is False
    assert got["otherSent"] == [{"post": "docs/marketing/content/elsewhere.md", "network": "linkedin", "keys": ["network", "post"]}]
    assert got["unknownNetwork"] == {"start": True, "why": "The post file names myspace, which has no data file here (instagram, linkedin, tiktok): choose another post file."}
    assert got["none"]["hint"].startswith("No post file with a script was found. Type the path") and got["none"]["select"] is False and got["none"]["start"] is True and got["none"]["why"] == "Type the path of the post file."
    assert got["bad"] == {"start": True, "why": "Type the path of the post file."}
    assert got["path"] == {"start": True, "why": "Choose the network this post is for."}
    assert got["badNet"]["start"] is True
    assert got["ready"] == {"start": False, "kept": "docs/marketing/content/x.md"}, "the button follows what is chosen without drawing the row again"
    assert got["unreadable"].startswith("The post files could not be read (The service could not be reached") and "Type the path" in got["unreadable"] and "No post file with a script" not in got["unreadable"]
    assert got["typedNet"] == {"tag": "INPUT", "start": False}


REFUSED = r"""
// every refusal of media-pipeline reaches the page as a FAILED JOB whose error message is the service's own text: the page tells it in its sentence
const REAL = @REAL@;
const view = make();
const root = view.el;
await view.load(); await settle();
choose(key(root, `sv-post-${RID}`), "docs/marketing/content/2026-10-03-a.md");
out.told = {};
for (const [name, message] of Object.entries(REAL)) {
  script.pollState = "failed"; script.jobMessage = message;
  await key(root, `sv-start-${RID}`).click(); await wait(60); await settle();
  out.told[name] = text(find(root, ".wb-notice-card"));
}
// a request refused before it was a job (the route answered a refusal at once) is told the same way
script.pollState = "done"; script.startError = new ApiError(409, "refused", REAL.no_file);
await key(root, `sv-start-${RID}`).click(); await wait(40); await settle();
out.direct = text(find(root, ".wb-notice-card"));
script.startError = new ApiError(0, "network", "x");
await key(root, `sv-start-${RID}`).click(); await wait(40); await settle();
out.network = text(find(root, ".wb-notice-card"));
script.startError = new ApiError(404, "not_found", "no");
await key(root, `sv-start-${RID}`).click(); await wait(40); await settle();
out.gone = text(find(root, ".wb-notice-card"));
out.stays = off(key(root, `sv-start-${RID}`));
// a pipeline that stopped at a step, and a job with no message
script.startError = null;
script.result = { ok: false, failed: "base", code: "retake_lost", field: "retakes", next: "python3 pipeline.py review" };
await key(root, `sv-start-${RID}`).click(); await wait(60); await settle();
out.stopped = text(find(root, ".wb-notice-card"));
script.result = { ok: true, task: 2 }; script.pollState = "failed"; script.jobMessage = "";
await key(root, `sv-start-${RID}`).click(); await wait(60); await settle();
out.silent = text(find(root, ".wb-notice-card"));
view.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


def real_refusals(tmp_path, monkeypatch):
    """The messages the real operation gives, each made by the real operation over a world with stand-in providers (nothing is typed here from the service's text)."""
    import test_media_pipeline as tm
    kit, ops, media, ops_core = tm.kit, tm.ops, tm.media, tm.ops_core
    w = tm.make_world(tmp_path, monkeypatch)
    said = {}

    def refused(name, call):
        try:
            call()
        except ops.OpsError as e:
            said[name] = str(e)
        else:
            raise AssertionError(f"{name}: the service did not refuse")

    other = "docs/marketing/content/other.md"
    noscript, nonet = "docs/marketing/content/noscript.md", "docs/marketing/content/nonet.md"
    for rel, text in ((noscript, kit.POST.replace("```script", "```text")), (nonet, re.sub(r"^- Network:.*\n", "", kit.POST, flags=re.M)), (other, kit.POST)):
        with open(os.path.join(w.project, *rel.split("/")), "w", encoding="utf-8") as f:
            f.write(text)
    empty = media.create(w.data)["id"]
    refused("no_file", lambda: ops.media_pipeline(w.project, empty))
    refused("typo", lambda: ops.media_pipeline(w.project, w.rid, post=kit.POST_PATH, network="instagrm"))
    refused("bad_path", lambda: ops.media_pipeline(w.project, w.rid, post="notes/x.md", network="instagram"))
    refused("unreadable", lambda: ops.media_pipeline(w.project, w.rid, post="docs/marketing/content/missing.md", network="instagram"))
    refused("no_script", lambda: ops.media_pipeline(w.project, w.rid, post=noscript, network="instagram"))
    refused("no_network", lambda: ops.media_pipeline(w.project, w.rid, post=nonet))
    media.link_posts(w.data, w.rid, {"instagram": kit.POST_PATH, "tiktok": other})
    refused("several", lambda: ops.media_pipeline(w.project, w.rid))
    refused("no_post_for", lambda: ops.media_pipeline(w.project, w.rid, network="linkedin"))
    out = tm.start(w)
    refused("started_for", lambda: ops.media_pipeline(w.project, w.rid, post=kit.POST_PATH, network="tiktok"))
    task = tm.code_task(w)["id"]
    fd = ops_core._try_lock(ops_core._config_of(w.project), f"task-{task}.lock")
    try:
        refused("being_run", lambda: ops.media_pipeline(w.project, w.rid))
    finally:
        os.close(fd)
    ops.cancel(w.project, out["request"])
    refused("cancelled", lambda: ops.captions_edit(w.project, w.rid, 0, json.dumps([{"op": "delete", "index": 3}])))
    return said


@needs_node
def test_every_refusal_of_the_real_service_reaches_the_page_as_a_failed_job_and_is_told_in_the_pages_sentence(tmp_path, monkeypatch):
    real = real_refusals(tmp_path / "service", monkeypatch)
    got = run(tmp_path, REFUSED, real=real)
    assert got["told"] == {
        "no_file": "This recording has no file yet: upload it first.",
        "typo": "That network has no data file here: choose the network from the list.",
        "bad_path": "A post file is a Markdown file under docs/ of the project.",
        "unreadable": "This post file cannot be read: it must be a regular Markdown file under docs/ of the project.",
        "no_script": "This post file has no script block: a short video needs the script of its beats. Choose another post file.",
        "no_network": "The post file names no network: type the network (for example instagram).",
        "several": "Choose the post file this recording is for.",
        "no_post_for": "That network has no post file for this recording: choose the post file.",
        "started_for": "This recording's pipeline was started for another post file: change that post file's text and open the captions again, or start another recording.",
        "being_run": "The pipeline of this recording is being run by another process: wait for it to end.",
        "cancelled": "The request this recording belonged to was cancelled: its pipeline stopped with it.",
    }, "each message is the real one, taken from the operation"
    assert got["direct"] == "This recording has no file yet: upload it first."
    assert got["network"].startswith("The service could not be reached") and "cannot start the pipeline from here" in got["gone"] and got["stays"] is False, "the control stays for another try"
    assert got["stopped"].startswith("Cut and caption stopped:") and "retake" in got["stopped"].lower(), got["stopped"]
    assert got["silent"] == "The pipeline stopped."


DOUBLE = r"""
// a double click in one tab starts one pipeline; two instances of the part (the Tasks tab's and the Agent tab's) offer a recording once, and the one that did not start it stops offering it
const a = make(), b = make({ upload: false, title: "Edit a recording" });
await a.load(); await b.load(); await settle();
choose(key(a.el, `sv-post-${RID}`), "docs/marketing/content/2026-10-03-a.md");
const button = key(a.el, `sv-start-${RID}`);
button.click(); button.click();
await wait(100); await settle();
out.double = calls.filter((c) => c[0] === "pipeline").length;
out.bothOffered = [all(a.el, "li.wb-sv-row").length, all(b.el, "li.wb-sv-row").length];
await b.load(); await settle();                                    // the store changed: the page reads again
out.afterRefresh = [all(a.el, "li.wb-sv-row").length, all(b.el, "li.wb-sv-row").length, text(key(b.el, "sv-none"))];
a.close(); b.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_double_click_starts_one_pipeline_and_a_recording_started_in_one_place_is_no_longer_offered_in_the_other(tmp_path):
    got = run(tmp_path, DOUBLE)
    assert got["double"] == 1, "the second click finds the first one's start under way"
    assert got["bothOffered"] == [1, 1], "until the other part reads again, it still offers it"
    assert got["afterRefresh"] == [1, 0, "No recording is waiting to be edited."], "after the store changed (a reload of the page) the other part no longer offers it; the starter keeps its result line"


def test_the_agent_tab_reads_again_when_the_store_changes_in_both_places_it_lives():
    agent = (JS / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    assert re.search(r"reload\(\) \{\s*if \(startLoaded\) mediaStart\.load\(\);\s*\}", agent)
    assert "tab.reload();" in (JS / "views" / "lobby-agent.js").read_text(encoding="utf-8")
    assert "if (agentTabLive) agentTabLive.reload();" in (JS / "views" / "floor.js").read_text(encoding="utf-8")


POLICY = r"""
// the policy: media-pipeline off withholds the control, media-in off withholds the upload; nothing else changes
let view = make({ can: (op) => op !== "media-pipeline" });
await view.load(); await settle();
out.pipelineOff = { buttons: all(view.el, `[data-key="sv-start-${RID}"]`).length, line: text(find(view.el, "[data-key=withheld]")), upload: Boolean(key(view.el, "sv-choose")) };
view.close();
view = make({ can: (op) => op !== "media-in" });
await view.load(); await settle();
out.uploadOff = { start: Boolean(key(view.el, `sv-start-${RID}`)), choose: Boolean(key(view.el, "sv-choose")), line: text(find(view.el, "[data-key=withheld]")) };
view.close();
// off the Mac: it says so and does nothing, and asks the service for nothing
calls.length = 0;
view = make({ loopback: false });
await view.load(); await settle();
out.lan = { text: text(view.el), buttons: all(view.el, "button").length, calls: calls.length };
view.close();
// no client of the media routes (a page of the Floor that never started one): it draws nothing and asks nothing
view = createMediaStart({ project: "@PROJECT@", api: {}, loopback: true });
await view.load(); await settle();
out.noClient = { children: all(view.el, "button").length };
view.close();
// the heading is the caller's, and an upload step is only drawn when asked for
view = make({ upload: false, title: "Edit a recording" });
await view.load(); await settle();
out.agent = { title: text(find(view.el, ".wb-card-title")), choose: Boolean(key(view.el, "sv-choose")), label: view.el.attrs["aria-label"] };
view.close();
view = make({ title: false });
await view.load(); await settle();
out.untitled = { title: Boolean(find(view.el, ".wb-card-title")), choose: Boolean(key(view.el, "sv-choose")) };
view.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_the_control_is_withheld_when_the_page_may_not_start_the_pipeline_and_off_the_mac_it_says_so_and_asks_nothing(tmp_path):
    got = run(tmp_path, POLICY)
    assert got["pipelineOff"] == {"buttons": 0, "line": "Turned off for the page: media-pipeline. Use the terminal.", "upload": True}
    assert got["uploadOff"]["start"] is True and got["uploadOff"]["choose"] is False and "media-in" in got["uploadOff"]["line"]
    assert "started on the Mac that runs the service" in got["lan"]["text"] and got["lan"]["buttons"] == 0 and got["lan"]["calls"] == 0
    assert got["noClient"] == {"children": 0}
    assert got["agent"] == {"title": "Edit a recording", "choose": False, "label": "Edit a recording"}
    assert got["untitled"] == {"title": False, "choose": True}


UPLOAD = r"""
// a short video needs no agent task: choose a recording, upload it, then it is offered and started
const none = clone(script.recordings);
script.recordings = [];
const view = make();
const root = view.el;
await view.load(); await settle();
out.empty = { line: text(key(root, "sv-none")), choose: Boolean(key(root, "sv-choose")), hint: text(find(root, ".wb-card-hint")) };
view.pick({ name: "notes.pdf", size: 10, type: "application/pdf" });
out.notVideo = { error: text(find(root, ".wb-notice-card")), send: Boolean(find(root, ".wb-hand-send")) };
view.pick({ name: "take.mp4", size: 5 * 1024 * 1024, type: "video/mp4" });
out.picked = { name: text(find(root, ".wb-hand-chosen")), send: text(find(root, ".wb-hand-send")) };
find(root, ".wb-hand-send").click(); await wait(60); await settle();
out.uploaded = { calls: calls.filter((c) => c[0] === "upload"), message: text(key(root, "sv-message")), rows: all(root, "li.wb-sv-row").length, head: text(find(root, ".wb-sv-head")).slice(0, 20), posts: all(key(root, `sv-post-${RID2}`), "option").length };
// a video over the limit and a file of another kind are told, not sent
view.pick({ name: "big.mp4", size: 2 * 1024 * 1024 * 1024, type: "video/mp4" });
out.big = { error: text(find(root, ".wb-notice-card")), send: Boolean(find(root, ".wb-hand-send")) };
view.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_short_video_starts_from_a_recording_chosen_and_uploaded_with_no_agent_task_and_is_then_offered(tmp_path):
    got = run(tmp_path, UPLOAD)
    assert got["empty"]["line"] == "No recording is waiting to be edited." and got["empty"]["choose"] is True and "needs no task" in got["empty"]["hint"]
    assert got["notVideo"] == {"error": "This is not a video: choose a .mov or .mp4 recording.", "send": False}
    assert got["picked"] == {"name": "take.mp4", "send": "Upload the recording"}
    assert got["uploaded"]["calls"] == [["upload", "take.mp4", None]], "to the media route as a new recording: no task, no slot"
    assert got["uploaded"]["message"].startswith("Recording stored (fedcba98)") and got["uploaded"]["rows"] == 1 and got["uploaded"]["head"].startswith("Recording fedcba98") and got["uploaded"]["posts"] == 4
    assert got["big"]["error"] == "A recording is at most 1 GiB."
    assert got["big"]["send"] is False


TAB = r"""
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
globalThis.location = { hostname: "127.0.0.1" };
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({ error: "not_found", message: "no" }) });
const tab = createTasksTab({ project: "@PROJECT@", now: () => new Date("2026-10-14T12:00:00Z"), refresh: () => {}, api: { ...api, retry: async () => ({}) }, links: { request: () => "#r", inbox: () => "#i", open: () => "#o" } });
tab.update({ tasks: [], requests: [], pending: [], loading: false, reload: 1 }); await settle(); await wait(30);
const details = find(tab.el, "[data-key=new-short-video]");
out.noTask = { details: Boolean(details), summary: text(find(details, "summary")), open: details.open, none: text(find(tab.el, ".wb-tasks-list")), offer: all(tab.el, "li.wb-sv-row").length, start: Boolean(find(tab.el, `[data-key="sv-start-${RID}"]`)), upload: Boolean(find(tab.el, '[data-key="sv-choose"]')) };
const before = calls.filter((c) => c[0] === "media-list").length;
tab.update({ tasks: [], requests: [], pending: [], loading: false, reload: 2 }); await settle(); await wait(30);
out.reread = calls.filter((c) => c[0] === "media-list").length - before;
console.log(JSON.stringify(out));
process.exit(0);
"""


@needs_node
def test_a_project_with_no_open_task_still_has_the_place_to_start_a_short_video_in_its_tasks_tab(tmp_path):
    got = run(tmp_path, TAB)
    n = got["noTask"]
    assert n["details"] is True and n["summary"] == "New short video" and n["open"] is True, "it opens by itself when a recording waits"
    assert n["none"] == "This agent has no task yet." and n["offer"] == 1 and n["start"] is True and n["upload"] is True, "the offer and the upload need no task"
    assert got["reread"] >= 1, "a store change reads the recordings again"


CLIENT = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";
setToken("t".repeat(40));
const seen = [];
globalThis.fetch = async (url, init) => { seen.push({ url, init }); return { ok: true, status: 200, json: async () => ({ job: 3 }) }; };
await api.mediaPipeline("@PROJECT@", "@RID@", { post: "docs/a.md", network: "instagram", request: 4 });
await api.mediaPipeline("@PROJECT@", "@RID@", { post: "docs/a.md", network: "instagram" });
console.log(JSON.stringify(seen.map((s) => ({ url: s.url, method: s.init.method, body: JSON.parse(s.init.body), auth: s.init.headers.Authorization.startsWith("Bearer "), type: s.init.headers["Content-Type"] || null }))));
"""


@needs_node
def test_the_client_starts_the_pipeline_by_its_job_route_with_the_post_and_the_network(tmp_path):
    import subprocess

    from test_interface_floor import NODE
    (tmp_path / "client.mjs").write_text(CLIENT.replace("@JS@", JS.as_uri()).replace("@PROJECT@", PROJECT).replace("@RID@", RID), encoding="utf-8")
    done = subprocess.run([NODE, str(tmp_path / "client.mjs")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert [(g["method"], g["url"]) for g in got] == [("POST", f"/api/v1/projects/{PROJECT}/media/{RID}/pipeline")] * 2
    assert got[0]["body"] == {"post": "docs/a.md", "network": "instagram", "request": 4} and got[1]["body"]["post"] == "docs/a.md" and "network" in got[1]["body"]
    assert all(g["auth"] and g["type"] == "application/json" for g in got)


# --- what the files may do, and the phone ----------------------------------------------------------------------------------------------------

def test_the_part_calls_only_its_own_routes_builds_no_markup_and_touches_no_image_model_setting_or_mode():
    code = "\n".join(line for line in START.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("//"))
    assert set(re.findall(r"\bapi\.(\w+)\(", code)) == {"mediaList", "artifacts", "artifact", "mediaPipeline", "pollJob"}
    assert set(re.findall(r"uploadRecording\(api, env\.project, file, \{ bar, signal: closing\.signal \}", code)), "the recording goes by the existing upload function"
    for forbidden in ("setMode", "acceptConfig", "accept-config", "innerHTML", "insertAdjacentHTML", "outerHTML", "createContextualFragment", "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage",
                      "window.open", "ev" + "al(", "new Func" + "tion", ".style", "canvas", "toDataURL", "setInterval", "models", "request:"):
        assert forbidden not in code, forbidden
    model = "\n".join(line for line in MODEL.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("//"))
    assert "document." not in model and "fetch(" not in model and "window" not in model, "the model is pure"


def test_the_agent_tab_and_the_tasks_tab_draw_it_and_the_phone_layout_reads_well():
    tab = (JS / "floor" / "tasks-tab.js").read_text(encoding="utf-8")
    agent = (JS / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    assert "createMediaStart({ project: env.project" in tab and "upload: false" in agent and "createMediaStart" in agent
    floor = css_file("floor")
    phone = "\n".join(media_blocks(floor, "max-width: 899px"))
    assert ".wb-sv-details > summary, .wb-sv-head, .wb-sv-steps { font-size: 16px; }" in phone
    assert ".wb-sv-row .pui-btn { min-height: 44px; }" in phone
    assert "min-width: 0" in re.search(r"\.wb-sv-details \{([^}]*)\}", floor).group(1)
    assert "overflow-wrap: anywhere" in re.search(r"\.wb-sv-button \{([^}]*)\}", floor).group(1), "a long label wraps"
    assert "minmax(0, 1fr)" in re.search(r"\.wb-sv-content \{([^}]*)\}", floor).group(1), "nothing scrolls sideways"

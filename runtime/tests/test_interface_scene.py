"""Tests of the scene engine and the shared frame of the local interface (interface/js/scene/, interface/js/frame/,
interface/js/model.js and the modules beside them). No browser and no model: the pure modules (the render scheduler, the
camera arithmetic, the label culling, the router, the City's model) and the frame's markup run under Node when it is
installed (a fake document stands in for the page's); the rules about rendering, motion and colour that need no run are
read from the files. The page itself was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
SCENE = JS / "scene"
FRAME = JS / "frame"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the pure modules are tested only by their text")


def scene_files():
    return sorted(SCENE.glob("*.js"))


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- the render scheduler: a frame only when something changed ---------------------------------------------------------------

LOOP = r"""
import { createLoop, AMBIENT_FPS } from "@JS@/scene/loop.js";

function harness({ hidden = false, reduced = false } = {}) {
  const queue = [];
  let now = 0;
  const frames = [];
  let rafCalls = 0;
  const loop = createLoop({
    raf: (fn) => { rafCalls += 1; queue.push(fn); return rafCalls; },
    caf: () => { queue.length = 0; },
    render: (ts) => frames.push(ts),
    hidden: () => hidden, reduced: () => reduced,
  });
  // run `ms` milliseconds of 60 Hz browser frames
  const run = (ms) => {
    const end = now + ms;
    while (now < end) {
      now += 1000 / 60;
      const batch = queue.splice(0);
      batch.forEach((fn) => fn(now));
    }
  };
  return { loop, run, frames, raf: () => rafCalls, queued: () => queue.length };
}

const out = {};
let h = harness();
h.run(5000);
out.idleFrames = h.frames.length; out.idleRaf = h.raf();
h.loop.requestRender(); h.loop.requestRender(); h.run(200);
out.afterRequest = h.frames.length; out.afterRequestQueued = h.queued();
h = harness();
h.loop.start("beacon", { ambient: true }); h.run(2000);
out.ambientFpsOver2s = h.frames.length / 2; out.ambientCap = AMBIENT_FPS; out.ambientRunning = h.loop.isRunning();
h.loop.stop("beacon"); const stopped = h.frames.length; h.run(1000);
out.afterStopExtra = h.frames.length - stopped;
h = harness();
h.loop.start("camera", { ambient: false }); h.run(600);
out.transitionFrames = h.frames.length;
h = harness({ hidden: true });
h.loop.requestRender(); h.loop.start("beacon", { ambient: true }); h.run(1000);
out.hiddenFrames = h.frames.length; out.hiddenRaf = h.raf();
h.loop.setHidden(false); h.run(100);
out.visibleFrames = h.frames.length;
h.loop.setHidden(true); const before = h.frames.length; h.run(1000);
out.hiddenAgainFrames = h.frames.length - before;
h = harness({ reduced: true });
out.reducedStarted = h.loop.start("beacon", { ambient: true }); h.run(2000);
out.reducedFrames = h.frames.length; out.reducedRunning = h.loop.isRunning(); out.reducedRaf = h.raf();
h = harness();
h.loop.dispose(); h.loop.requestRender(); h.run(100);
out.disposedFrames = h.frames.length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_scheduler_draws_nothing_while_nothing_changed_and_at_most_thirty_frames_a_second_while_an_ambient_animation_runs(tmp_path):
    got = run_node(tmp_path, LOOP)
    assert got["idleFrames"] == 0 and got["idleRaf"] == 0, "no standing loop: no frame and no request for one while idle"
    assert got["afterRequest"] == 1 and got["afterRequestQueued"] == 0, "two requests in a row make one frame, then the loop stops"
    assert got["ambientCap"] == 30 and 20 <= got["ambientFpsOver2s"] <= 30, "an ambient animation runs at most 30 frames a second"
    assert got["ambientRunning"] is True and got["afterStopExtra"] <= 1, "stopping the animation leaves at most its last frame"
    assert got["transitionFrames"] >= 30, "a transition (the camera) is drawn on the browser's frames while it lasts"
    assert got["hiddenFrames"] == 0 and got["hiddenRaf"] == 0, "a hidden document draws nothing and asks for no frame"
    assert got["visibleFrames"] >= 1, "becoming visible draws again"
    assert got["hiddenAgainFrames"] == 0
    assert got["reducedStarted"] is False and got["reducedRunning"] is False and got["reducedFrames"] == 1 and got["reducedRaf"] == 1, \
        "with reduced motion an ambient animation never starts (one frame for its resting state)"
    assert got["disposedFrames"] == 0


# --- the camera, the culling, the router ------------------------------------------------------------------------------------

PURE = r"""
import { fitFrustum, lerpFrustum, ease, openEase, settleMs, CAMERA_RATE, OPEN_RATE } from "@JS@/scene/fit.js";
import { cull, rankOf, MAX_LABELS } from "@JS@/scene/cull.js";
import * as router from "@JS@/router.js";
import * as format from "@JS@/format.js";

const out = {};
const size = { w: 1280, h: 720 };
const insets = { left: 220, right: 412, top: 64, bottom: 156 };
const bounds = { x0: -10, x1: 12, y0: -4, y1: 14 };
const f = fitFrustum(bounds, size, insets, 1);
// project the subject's corners to pixels with the frustum
const px = (x, y) => [((x - f.left) / (f.right - f.left)) * size.w, ((f.top - y) / (f.top - f.bottom)) * size.h];
const [x0, y1] = px(bounds.x0, bounds.y0); const [x1, y0] = px(bounds.x1, bounds.y1);
out.inside = x0 >= insets.left - 1e-6 && x1 <= size.w - insets.right + 1e-6 && y0 >= insets.top - 1e-6 && y1 <= size.h - insets.bottom + 1e-6;
out.square = Math.abs((f.right - f.left) / size.w - (f.top - f.bottom) / size.h) < 1e-9;
const g = fitFrustum(bounds, size, insets, 1.04);
out.padWider = (g.right - g.left) > (f.right - f.left);
const mid = lerpFrustum(f, g, 0.5); out.lerp = Math.abs(mid.left - (f.left + g.left) / 2) < 1e-9;
out.ease = [ease(0), ease(0.5), ease(1), ease(-1), ease(2)];
out.easeOpen = [openEase(0), openEase(0.05), openEase(1)];
out.easeEarly = ease(0.05);
out.easeMonotone = Array.from({ length: 100 }, (_, i) => i / 99).every((t, i, a) => i === 0 || (ease(t) >= ease(a[i - 1]) && openEase(t) >= openEase(a[i - 1])));
out.settle = [settleMs(CAMERA_RATE), settleMs(OPEN_RATE)];

const r = (id, rank, l, t, w, h) => ({ id, rank, rect: { left: l, top: t, right: l + w, bottom: t + h } });
out.cull = [...cull([r("a", 3, 0, 0, 50, 20), r("b", 0, 40, 5, 50, 20), r("c", 1, 200, 0, 50, 20)])].sort();
out.cullMargin = [...cull([r("a", 0, 0, 0, 50, 20), r("b", 1, 51, 0, 50, 20)])].sort();
out.cullMax = cull(Array.from({ length: 30 }, (_, i) => r(i, 3, i * 100, 0, 50, 20))).size;
out.maxLabels = MAX_LABELS;
out.ranks = [rankOf({ selected: true, decisions: 0, running: false }), rankOf({ selected: false, decisions: 2, running: false }),
  rankOf({ selected: false, decisions: 0, running: true }), rankOf({ selected: false, decisions: 0, running: false })];

const id = "0123456789ab";
out.routes = [
  router.parse("#/"), router.parse(""), router.parse("#/p/zz"), router.parse(`#/p/${id}`), router.parse(`#/p/${id}/`),
  router.parse(`#/p/${id}/floor/marketing/inbox/12`), router.parse(`#/p/${id}/lobby/inbox/3`), router.parse(`#/p/${id}/control/costs`),
  router.parse(`#/p/${id}/floor`), router.parse(`#/p/${id}/floor/../x`),
].map((x) => [x.screen, x.project, x.agent, x.tab, x.pending]);
out.hashes = [router.cityHash(), router.buildingHash(id), router.floorHash(id, "marketing", "inbox", 12), router.lobbyHash(id, "inbox", 3),
  router.controlHash(id, "costs"), router.parentHash(router.parse(`#/p/${id}/floor/x`)), router.parentHash(router.parse(`#/p/${id}`)), router.parentHash(router.parse("#/"))];
out.roundTrip = [router.parse(router.floorHash(id, "marketing", "inbox", 12)).pending, router.parse(router.lobbyHash(id)).screen];

const now = new Date("2026-10-08T12:00:00Z");
out.age = ["2026-10-08T11:59:30Z", "2026-10-08T11:48:00Z", "2026-10-08T07:00:00Z", "2026-10-06T12:00:00Z", "nonsense", null].map((s) => format.age(s, now));
out.words = [format.ageWords("2026-10-06T12:00:00Z", now), format.ageWords("2026-10-08T11:00:00Z", now), format.ageWords("2026-10-08T11:59:59Z", now)];
out.fmt = [format.dollars(3.8249), format.dollars("x"), format.share(5, 0), format.share(7, 5), format.share(1, 4), format.kindWord("your_document"), format.kindWord("mystery"), format.agentWord("planning"), format.agentWord("marketing")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_camera_fits_the_subject_in_the_free_rectangle_and_the_labels_are_culled_by_rank_and_overlap(tmp_path):
    got = run_node(tmp_path, PURE)
    assert got["inside"] and got["square"] and got["padWider"] and got["lerp"], "the subject sits inside the rectangle the panels leave"
    # the prototype's exponential approach, normalised to land on 1: fast at first (nine tenths of the way at half the time), soft at the end
    assert got["ease"][0] == 0 and got["ease"][2] == 1 and got["ease"][3] == 0 and got["ease"][4] == 1, "clamped to 0 and 1"
    assert abs(got["ease"][1] - 0.9090909090909092) < 1e-9 and got["easeOpen"][1] < got["easeEarly"], "the opening starts softer than the camera (the smoothstep on top of the approach)"
    assert got["easeMonotone"], "never goes back"
    assert got["settle"] == [1023, 1439], "ln(100) over the prototype's rates 4.5 and 3.2"
    assert got["cull"] == ["b", "c"], "the lower rank is kept and the label that overlaps it is dropped"
    assert got["cullMargin"] == ["a"], "two labels 1 px apart (inside the 2 px margin) overlap"
    assert got["cullMax"] == got["maxLabels"] == 12, "at most 12 labels are drawn"
    assert got["ranks"] == [0, 1, 2, 3]


@needs_node
def test_the_router_reads_every_hash_form_and_falls_back_to_the_city_and_the_formats_are_the_displays_words(tmp_path):
    got = run_node(tmp_path, PURE)
    i = "0123456789ab"
    assert got["routes"] == [
        ["city", None, None, None, None], ["city", None, None, None, None], ["city", None, None, None, None],
        ["building", i, None, None, None], ["building", i, None, None, None], ["floor", i, "marketing", "inbox", 12],
        ["lobby", i, None, "inbox", 3], ["control", i, None, "costs", None], ["building", i, None, None, None],
        ["building", i, None, None, None]]
    assert got["hashes"] == ["#/city", f"#/p/{i}", f"#/p/{i}/floor/marketing/inbox/12", f"#/p/{i}/lobby/inbox/3", f"#/p/{i}/control/costs",
                             f"#/p/{i}", "#/city", None]      # C-1: the City has its own route
    assert got["roundTrip"] == [12, "lobby"]
    assert got["age"] == ["now", "12 min", "5 h", "2 d", "", ""]
    assert got["words"] == ["2 days", "1 hour", "just now"]
    assert got["fmt"] == ["$3.82", "$0.00", 0, 1, 0.25, "Your document", "mystery", "Lobby", "Marketing"]


# --- what the City shows, from the service's bodies ----------------------------------------------------------------------------

MODEL = r"""
import * as model from "@JS@/model.js";
import { worldModel } from "@JS@/world-model.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const ago = (hours) => new Date(NOW.getTime() - hours * 3600e3).toISOString();
const agents = (names, over = {}) => names.map((name) => ({ name, enabled: true, mode: "supervised", acting_mode: "supervised",
  max_runs_per_day: 10, max_usd_per_day: 2.5, runs_today: 1, usd_today: 0.5, queued: 0, ...(over[name] || {}) }));
const a = "aaaaaaaaaaaa", b = "bbbbbbbbbbbb", c = "cccccccccccc";
const projects = [
  { id: a, name: "shop", config: { accepted: true }, open_pending: 3, running_task: 5 },
  { id: b, name: "docs", config: { accepted: true }, open_pending: 1, running_task: null },
  { id: c, name: "lab", config: { accepted: false }, message: "run: python3 runtime/cli.py accept-config --project /x --sha256 00" },
];
const row = (id, key, state, agent, title) => ({ id, key, skill: "s", state, agent, title });
const statusA = { requests: [{ id: 1, title: "Spring", state: "ready", tasks: [
  row(2, "plan", "done", "marketing", "Content plan"), row(3, "voice", "waiting", "brand", "Voice check"),
  row(4, "copy", "done", "marketing", "Post copy"), row(5, "page", "running", "engineering", "Order page"), row(6, "publish", "waiting", "marketing", "Publish post")] }],
  pending: [
    { id: 11, kind: "plan", title: "Plan: spring", task_id: 1, agent: null, created_at: ago(4) },
    { id: 12, kind: "question", title: "Which tone?", task_id: 3, agent: "brand", created_at: ago(5) },
    { id: 13, kind: "effect", title: "Publish the post", task_id: 6, agent: "marketing", created_at: ago(3) }] };
const statusB = { requests: [], pending: [{ id: 21, kind: "review", title: "Review the guide", task_id: 30, agent: null, created_at: ago(49) }] };
const snapshot = {
  projects, loaded: true,
  details: { [a]: { status: statusA, agents: agents(["engineering", "planning", "marketing", "brand", "design"], { design: { enabled: false }, brand: { acting_mode: "stopped" } }) },
             [b]: { status: statusB, agents: [] } },
  tasks: { [`${a}:5`]: { task: { id: 5, agent: "engineering", title: "Order page", state: "running" }, runs: [{ started_at: "2026-10-08T10:30:00Z" }], pending: [] } },
};
const out = {};
const needed = model.neededTasks(projects, snapshot.details, a);
out.needed = needed.map((n) => `${n.project === a ? "a" : "b"}:${n.id}`).sort();
const city = model.city(snapshot, NOW);
out.floorsOrder = model.floorsOf(snapshot.details[a].agents).map((x) => x.name);
const [shop, docs, lab] = city.buildings;
out.shop = { windows: shop.floors.map((f) => [f.agent, f.window, f.waits]), decisions: shop.decisions, running: shop.runningTask, accepted: shop.accepted };
out.docs = { floors: docs.floors, decisions: docs.decisions, running: docs.runningTask };
out.lab = { accepted: lab.accepted, windows: lab.floors.map((f) => f.window), decisions: lab.decisions, message: lab.message.slice(0, 11) };
out.tips = city.buildings.map(model.tooltipOf);
out.subs = city.buildings.map(model.subOf);
out.linkNames = city.buildings.map(model.linkNameOf);
out.canvasLabel = city.canvasLabel;
out.waiting = city.waiting.map((r) => [r.id, r.kind, r.where, r.age, r.link.replace(a, "A").replace(b, "B"), r.name]);
out.waitingScoped = model.waitingRows(snapshot, NOW, b).map((r) => r.id);
out.kpi = [model.kpiSums(snapshot, null), model.kpiSums(snapshot, b)];
out.tracking = (() => {
  const t = model.tracking(snapshot, a, NOW);
  return { request: t.request, done: t.doneCount, total: t.total, steps: t.steps.map((s) => [s.title, s.state, s.sub, s.link.replace(a, "A"), s.name]), now: t.now && { ...t.now, link: t.now.link.replace(a, "A") } };
})();
out.noRequest = model.tracking(snapshot, b, NOW);
out.subLines = [model.projectSub(snapshot, a), model.projectSub(snapshot, b), model.projectSub(snapshot, c), model.projectSub({ ...snapshot, details: {} }, a)];
const scene = worldModel(snapshot, NOW, { selectedId: a, marked: a });
out.scene = { selected: scene.selectedId, marked: scene.marked, ready: scene.ready, lots: scene.lots.map((l) => [l.id === a ? "a" : l.id === b ? "b" : "c", l.floors.length, l.tip]) };
const six = { ...snapshot, projects: Array.from({ length: 6 }, (_, i) => ({ ...snapshot.projects[0], id: String(i).repeat(12) })), details: Object.fromEntries(Array.from({ length: 6 }, (_, i) => [String(i).repeat(12), snapshot.details[a]])) };
out.maxLots = worldModel(six, NOW, {}).lots.length;
out.openRequest = [model.openRequest({ requests: [{ id: 1, state: "done" }, { id: 4, state: "ready" }, { id: 9, state: "cancelled" }, { id: 7, state: "running" }] }).id, model.openRequest({ requests: [] })];
const bare = { ...snapshot, tasks: {} };
out.noTasks = { windows: model.city(bare, NOW).buildings[0].floors.map((f) => [f.agent, f.window, f.waits]), links: model.city(bare, NOW).waiting.map((r) => r.link.replace(a, "A").replace(b, "B")), now: model.tracking(bare, a, NOW).now.sub };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_city_model_works_out_floors_windows_decisions_links_and_the_tracking_bar_from_the_services_bodies_only(tmp_path):
    got = run_node(tmp_path, MODEL)
    a = "aaaaaaaaaaaa"
    # planning is floor 0, then the agents in the order given
    assert got["floorsOrder"] == ["planning", "engineering", "marketing", "brand", "design"]
    # a floor's windows are lit when its agent is active, a task runs or a decision waits, and grey in every other case (R-21, which supersedes WP-9.8's
    # "lit only while a task runs"; no pale state); a decision's floor waits
    assert got["shop"]["windows"] == [["planning", "lit", True], ["engineering", "lit", False], ["marketing", "lit", True],
                                      ["brand", "grey", True], ["design", "grey", False]]   # brand is stopped: off, whatever it asked
    assert got["shop"]["decisions"] == 3 and got["shop"]["running"] == 5 and got["shop"]["accepted"] is True
    assert got["docs"] == {"floors": [{"agent": None, "window": "grey", "waits": True}], "decisions": 1, "running": None}, \
        "a project with no agents is one floor, which waits when a decision does"
    assert got["lab"] == {"accepted": False, "windows": ["grey"], "decisions": 0, "message": "run: python"}
    assert got["tips"] == ["shop: 3 decisions waiting, task #5 running", "docs: 1 decision waiting, no task running", "lab: not accepted yet"]
    assert got["subs"] == ["task #5 running", "no task running", "not accepted yet"]
    assert got["linkNames"][0] == "shop, 3 decisions waiting, task #5 running"
    assert got["canvasLabel"] == "City with 3 projects, 4 decisions waiting"
    # the waiting rows: oldest first, a plan goes to its request's line, another decision on a request to the lobby's inbox, the others to the agent's floor
    assert [r[0] for r in got["waiting"]] == [21, 12, 11, 13]
    by_id = {r[0]: r for r in got["waiting"]}
    assert by_id[11][1:5] == ["Plan", "shop · Lobby", "4 h", "#/p/A/lobby/conversation/request/1"], "C-2: the row of a plan opens the Conversation at its request's line"
    assert by_id[12][4] == "#/p/A/floor/brand/inbox/12" and by_id[13][4] == "#/p/A/floor/marketing/inbox/13"
    assert by_id[21][4] == "#/p/B/lobby/inbox/21" and by_id[21][3] == "2 d" and by_id[21][2] == "docs · Lobby", \
        "a decision with no agent (a project with no area agents, or a decision on a request) is the lobby's"
    assert by_id[12][5] == "Question, Which tone?, shop, Brand, waiting 5 hours"
    assert got["waitingScoped"] == [21]
    assert got["kpi"][0] == {"decisions": 4, "runs": 5, "runsCap": 50, "usd": 2.5, "usdCap": 12.5, "usdRecorded": 2.5, "usdReserved": 0, "runsTotal": 0,
                             "inUse": {"runs": True, "spend": True}}  # no caps_in_use sent (an older service): both meters
    assert got["kpi"][1] == {"decisions": 1, "runs": 0, "runsCap": 0, "usd": 0, "usdCap": 0, "usdRecorded": 0, "usdReserved": 0, "runsTotal": 0,
                             "inUse": {"runs": True, "spend": True}}  # a project with no agent shows both
    # the tracking bar: titles from the task, the agent from the task, the running run's start, floor numbers from the agents
    tracking = got["tracking"]
    assert tracking["request"] == {"id": 1, "title": "Spring", "state": "ready", "project": "shop", "projectId": "aaaaaaaaaaaa"}
    assert (tracking["done"], tracking["total"]) == (2, 5)
    assert tracking["steps"][3] == ["Order page", "running", "Engineering", "#/p/A/floor/engineering", "Order page, Engineering, running"], \
        "R-8: a step shows its title and its agent, no state word (the name for a screen reader keeps it)"
    assert tracking["now"]["where"] == "Now on floor 1 · engineering" and tracking["now"]["title"] == "Order page"
    assert tracking["now"]["state"] == "Running" and tracking["now"]["sub"].startswith("task #5 · for ") and tracking["now"]["link"] == "#/p/A/floor/engineering"
    assert got["noRequest"] is None
    assert got["subLines"] == ["Request #1 · 2 of 5 steps done", "No request is open", "Not accepted", "..."]
    assert got["scene"]["ready"] is True and got["scene"]["selected"] == a and got["scene"]["marked"] == a, "the chosen project keeps its outline in the City"
    assert got["scene"]["lots"] == [["a", 5, got["tips"][0]], ["b", 1, got["tips"][1]], ["c", 1, got["tips"][2]]]
    assert got["maxLots"] == 4, "at most four lots are drawn"
    assert got["openRequest"] == [7, None]
    # what the page must read besides the status: the one running task of the followed request (its run's start time)
    assert got["needed"] == ["a:5"]
    # the status alone is enough for the windows, the links and the steps (no `task` call): a snapshot with no task bodies gives the same
    assert got["noTasks"] == {"windows": got["shop"]["windows"], "links": [r[4] for r in got["waiting"]], "now": "task #5"}


# --- the shared frame, built under a fake document ---------------------------------------------------------------------------

FAKE_DOM = r"""
class FakeText { constructor(data) { this.data = String(data); this.parent = null; } get textContent() { return this.data; } }
class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; this.parent = null; this.listeners = {};
    this.dataset = {}; this.style = { setProperty: () => {} }; this.title = ""; this.disabled = false; this.value = "";
    const owner = this;
    this.classList = {
      add: (...n) => { const s = new Set(owner.cls()); n.forEach((x) => s.add(x)); owner.attrs.class = [...s].join(" "); },
      remove: (...n) => { const s = new Set(owner.cls()); n.forEach((x) => s.delete(x)); owner.attrs.class = [...s].join(" "); },
      toggle: (n, on) => { const s = new Set(owner.cls()); const want = on === undefined ? !s.has(n) : on; want ? s.add(n) : s.delete(n); owner.attrs.class = [...s].join(" "); return want; },
      contains: (n) => owner.cls().includes(n),
    };
  }
  cls() { return (this.attrs.class || "").split(/\s+/).filter(Boolean); }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get id() { return this.attrs.id || ""; }
  get isConnected() { return true; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  removeAttribute(n) { delete this.attrs[n]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  append(...items) { for (const it of items) { const n = it instanceof FakeNode || it instanceof FakeText ? it : new FakeText(it); if (n.parent) n.parent.children = n.parent.children.filter((c) => c !== n); n.parent = this; this.children.push(n); } }
  replaceChildren(...items) { this.children.forEach((c) => { c.parent = null; }); this.children = []; this.append(...items); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  contains(n) { for (let x = n; x; x = x.parent) if (x === this) return true; return false; }
  focus() { globalThis.__focused = this; }
  set textContent(v) { this.replaceChildren(String(v)); }
  get textContent() { return this.children.map((c) => (c.attrs && c.attrs["aria-hidden"] === "true" ? "" : c.textContent)).join(""); }
  querySelectorAll() { return []; }
  closest() { return null; }
  showModal() {} close() {}
  dispatchEvent() { return true; }
  *walk() { yield this; for (const c of this.children) if (c instanceof FakeNode) yield* c.walk(); }
}
globalThis.Node = FakeNode;
const document = new FakeNode("document");
document.createElement = (tag) => new FakeNode(tag);
document.createTextNode = (t) => new FakeText(t);
document.createElementNS = (ns, tag) => new FakeNode(tag);
document.activeElement = null;
globalThis.document = document;
globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }), location: { hash: "#/" } };

export function accessibleName(node) {
  const label = node.attrs["aria-label"];
  if (label && label.trim()) return label.trim();
  return node.textContent.trim();
}
export { FakeNode };
"""

FRAME_SCRIPT = r"""
import { FakeNode, accessibleName } from "@FAKE@";
import { createFrame } from "@JS@/frame/frame.js";
import * as model from "@JS@/model.js";
import * as router from "@JS@/router.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600e3).toISOString();
const a = "aaaaaaaaaaaa", b = "bbbbbbbbbbbb";
const projects = [{ id: a, name: "northwind-shop", config: { accepted: true } }, { id: b, name: "tinykv-docs", config: { accepted: true } }];
const mk = (id, state, agent, title) => ({ id, key: "k" + id, skill: "s", state, agent, title });
const steps = [mk(2, "done", "marketing", "Content plan"), mk(3, "waiting", "brand", "Voice check"), mk(4, "done", "marketing", "Post copy"),
  mk(5, "running", "engineering", "Order-history page"), mk(6, "ready", "engineering", "Review"), mk(7, "waiting", "marketing", "Publish post")];
const agents = ["planning", "business", "brand", "design", "engineering", "marketing"].map((n) => ({ name: n, enabled: true, acting_mode: "supervised", runs_today: 2, max_runs_per_day: 10, usd_today: 0.8, max_usd_per_day: 3 }));
const snapshot = { projects, loaded: true,
  tasks: { [`${a}:5`]: { task: { id: 5 }, runs: [{ started_at: "2026-10-08T10:02:00Z" }], pending: [] } },
  details: {
    [a]: { agents, status: { requests: [{ id: 14, title: "Spring campaign", state: "ready", tasks: steps }],
      pending: [{ id: 31, kind: "acceptance", title: "Accept: content plan for October", task_id: 2, agent: "marketing", created_at: ago(48) },
                { id: 32, kind: "plan", title: "Plan: spring campaign", task_id: 14, agent: null, created_at: ago(4) }] } },
    [b]: { agents, status: { requests: [], pending: [] } } } };

const root = new FakeNode("div");
const calls = [];
const frame = createFrame(root, { onSelectProject: (id) => calls.push(["select", id]), onForgetToken: () => calls.push(["forget"]), onRetry: () => calls.push(["retry"]) });
frame.main.append(frame.waitingCard.el);   // the City screen puts its card there
const city = router.parse("#/");
const city_data = model.city(snapshot, NOW);
frame.setScreen(city, { projectName: "northwind-shop", projectId: a });
frame.switcher.update({ projects: projects.map((p) => ({ id: p.id, name: p.name, accepted: true, badge: 1, sub: model.projectSub(snapshot, p.id) })), selectedId: a, heading: "Projects · choose the one the tracking bar follows" });
frame.kpis.update({ decisions: 7, runs: 17, runsCap: 70, usd: 4.9, usdCap: 21.5 }, "ready");
frame.waitingCard.set(city_data.waiting, "ready");
frame.waitingMenu.set(city_data.waiting, "ready");
frame.track.set(model.tracking(snapshot, a, NOW), "ready");
frame.notice({ kind: "error", lead: "lab is not accepted yet", text: "run: x", mono: true, retry: true });
frame.announce("New decision: Question, Which tone?");

const nodes = [...root.walk()];
const interactive = nodes.filter((n) => ["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA"].includes(n.tagName) || ["listbox", "option", "tab", "tablist"].includes(n.attrs.role));
const out = {};
out.unnamed = interactive.filter((n) => !accessibleName(n)).map((n) => `${n.tagName}.${n.attrs.class}`);
out.regionsUnnamed = nodes.filter((n) => (n.attrs.role === "region" || n.tagName === "NAV" || n.attrs.role === "group") && !n.attrs["aria-label"] && !n.attrs["aria-labelledby"]).map((n) => n.attrs.class);
out.styleOrEvent = nodes.flatMap((n) => Object.keys(n.attrs).filter((k) => k === "style" || /^on[a-z]+$/i.test(k)));
out.badLinks = nodes.filter((n) => n.tagName === "A" && !/^#/.test(n.attrs.href || "")).map((n) => n.attrs.href);
out.names = {
  kpis: nodes.filter((n) => n.attrs.role === "group").map((n) => n.attrs["aria-label"]),
  back: accessibleName(nodes.find((n) => (n.attrs.class || "").includes("wb-back"))),
  nav: nodes.find((n) => n.tagName === "NAV").attrs["aria-label"],
  crumbs: nodes.filter((n) => (n.attrs.class || "").includes("wb-crumb ")).map((n) => n.textContent),
  chevron: nodes.find((n) => (n.attrs.class || "").includes("wb-switch-chevron")).attrs["aria-label"],
  main: accessibleName(nodes.find((n) => (n.attrs.class || "").includes("wb-switch-main"))),
  listbox: nodes.find((n) => n.attrs.role === "listbox").attrs["aria-label"],
  options: nodes.filter((n) => n.attrs.role === "option").map((n) => n.attrs["aria-selected"]),
  door: accessibleName(nodes.find((n) => (n.attrs.class || "").includes("wb-door"))),
  waitBtn: nodes.find((n) => (n.attrs.class || "").includes("wb-wait-btn")).attrs["aria-label"],
  steps: nodes.find((n) => (n.attrs.class || "").includes("wb-steps")).attrs["aria-label"],
  stepLinks: nodes.filter((n) => (n.attrs.class || "") === "wb-step-text").map((n) => n.attrs["aria-label"]),
  waitRows: nodes.filter((n) => (n.attrs.class || "").startsWith("wb-wait-row")).map((n) => n.attrs["aria-label"]),
  waitingRegion: nodes.find((n) => (n.attrs.class || "").includes("wb-waiting")).attrs["aria-label"],
  skips: nodes.filter((n) => (n.attrs.class || "") === "wb-skip").map((n) => [n.textContent, n.attrs.href]),
  live: nodes.find((n) => n.attrs.role === "status" && (n.attrs.class || "").includes("wb-sr")).attrs["aria-live"],
  heading: nodes.find((n) => n.tagName === "H1").textContent,
  screen: nodes.find((n) => (n.attrs.class || "").includes("wb-frame")).dataset.screen,
  noticeRole: nodes.find((n) => (n.attrs.class || "").includes("wb-notice ")).attrs.role,
};
out.backDisabled = nodes.find((n) => (n.attrs.class || "").includes("wb-back")).disabled;
out.waitingOnCity = [frame.waitingCard.isOpen(), frame.waitingCard.el.cls().includes("is-collapsible"), frame.waitingCard.el.attrs.id];
function frameHidden(ns) { return [frame.waitingCard.isOpen(), frame.waitingCard.el.cls().includes("is-collapsed"), frame.waitingCard.el.attrs.id || null]; }
frame.setScreen(router.parse(`#/p/${a}/floor/marketing`), { projectName: "northwind-shop", projectId: a, leaf: "Marketing" });
const n2 = [...root.walk()];
out.floor = { crumbs: n2.filter((n) => ["wb-crumb", "wb-crumb is-current"].includes(n.attrs.class || "")).map((n) => n.attrs.class.includes("is-current") ? "current:" + n.textContent : n.textContent),
  backDisabled: n2.find((n) => (n.attrs.class || "").includes("wb-back")).disabled, waitingElsewhere: frameHidden(n2), screen: n2.find((n) => (n.attrs.class || "").includes("wb-frame")).dataset.screen };
frame.setScreen(router.parse(`#/p/${a}/control`), { projectName: "northwind-shop", projectId: a });
out.control = { selected: [...root.walk()].find((n) => (n.attrs.class || "").includes("wb-door")).cls().includes("is-selected") };
frame.kpis.update(null, "loading");
frame.waitingCard.set([], "loading");
frame.track.set(null, "loading");
const nodes3 = [...root.walk()];
out.loading = { kpis: nodes3.filter((n) => n.attrs.role === "group").map((n) => n.attrs["aria-label"]), unnamed: nodes3.filter((n) => ["BUTTON", "A"].includes(n.tagName) && !accessibleName(n)).length };
frame.setScreen(city, { projectName: "northwind-shop", projectId: a });     // the City: the card is open (on a project's screen it is closed on its header line, R-7)
frame.waitingCard.set([], "ready");
out.empty = [...root.walk()].filter((n) => (n.attrs.class || "") === "wb-empty").map((n) => n.textContent);
console.log(JSON.stringify(out));
"""


@needs_node
def test_every_control_of_the_frame_has_an_accessible_name_and_the_names_say_what_the_handoff_asks(tmp_path):
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM, encoding="utf-8")
    got = run_node(tmp_path, FRAME_SCRIPT.replace("@FAKE@", fake.as_uri()))
    assert got["unnamed"] == [], "every button, link, listbox and option has a name"
    assert got["regionsUnnamed"] == [], "every region, group and navigation is named"
    assert got["styleOrEvent"] == [] and got["badLinks"] == [], "no style or event attribute; every link is a hash link of this page"
    names = got["names"]
    assert names["kpis"] == ["Runs today 17 of 70", "Spend today $4.90 of $21.50 cap"], "R-5: two cards; the count of open decisions is on \"Waiting for you\""
    assert names["back"] == "Back" and names["nav"] == "Breadcrumbs" and names["chevron"] == "Choose a project"
    assert names["crumbs"] == ["City"]
    assert names["main"] == "northwind-shop, project 1 of 2, go to the next project"
    assert names["listbox"] == "Projects" and names["options"] == ["true", "false"]
    assert names["door"] == "Control room" and names["waitBtn"] == "Waiting for you, 2 decisions"
    assert names["steps"] == "Request 14, Spring campaign, 2 of 6 steps done"
    assert "Order-history page, Engineering, running" in names["stepLinks"]
    assert names["waitRows"][0] == "Acceptance, Accept: content plan for October, northwind-shop, Marketing, waiting 2 days"
    assert names["waitingRegion"] == "Waiting for you, 2 decisions"
    assert names["skips"] == [["Skip to the panel", "#wb-panel"], ["Skip to the scene list", "#wb-scene-list"]]
    assert names["live"] == "polite" and names["heading"] == "City" and names["screen"] == "city" and names["noticeRole"] == "alert"
    assert got["backDisabled"] is True and got["waitingOnCity"] == [False, False, "wb-panel"], \
        "Back is disabled on the City; R-7: there the card is open for good (no toggle: not collapsible) and is the panel the skip link names"
    assert got["floor"] == {"crumbs": ["City", "northwind-shop", "current:Marketing"], "backDisabled": False, "waitingElsewhere": [False, True, None], "screen": "floor"}, \
        "R-7: on a project's screen the card is closed on its header line and gives up the panel's id"
    assert got["control"] == {"selected": True}
    assert got["loading"]["kpis"] == ["Runs today, loading", "Spend today, loading"] and got["loading"]["unnamed"] == 0
    assert "Nothing waits for you." in got["empty"] and "Loading the request..." in got["empty"]


# --- the camera move, the first-read state, the skip links and the notice -------------------------------------------------------

TWEEN = r"""
import { createTween } from "@JS@/scene/tween.js";
import * as model from "@JS@/model.js";

const out = {};
const a = { left: 0, right: 10, top: 10, bottom: 0 }, b = { left: 2, right: 6, top: 8, bottom: 4 };
const settled = [];
const frames = (tween, from, count) => { let f = null; for (let i = 1; i <= count; i++) f = tween.step(from + i * 16) || f; return f; };
let t = createTween();
const move = t.start(a, b, 0); move.then((v) => settled.push(["finished", v]));
out.activeAfterStart = t.active();
const mid = frames(t, 0, 10);
out.midInside = mid.left > 0 && mid.left < 2;
out.stillActive = t.active();
const end = frames(t, 160, 300);   // lands when under a quarter of a pixel is left (WP-9.11), a little after the first one percent
out.endFrustum = [end.left, end.right, end.top, end.bottom]; out.activeAtEnd = t.active();
out.noStepWhenIdle = t.step(9000);
// a move cut by a rebuild settles false, once
t = createTween();
const cut = t.start(a, b, 0); cut.then((v) => settled.push(["cut", v]));
out.cancelReturned = t.cancel(); out.cancelAgain = t.cancel(); out.activeAfterCancel = t.active();
// a second move settles the first false
t = createTween();
const first = t.start(a, b, 0); first.then((v) => settled.push(["first", v]));
const second = t.start(b, a, 0); second.then((v) => settled.push(["second", v]));
frames(t, 0, 300);
await new Promise((r) => setTimeout(r, 10));
out.settled = settled.sort((x, y) => x[0].localeCompare(y[0]));
out.states = [model.screenState({ loaded: false }, null), model.screenState({ loaded: false }, new Error("x")), model.screenState({ loaded: true }, new Error("x")), model.screenState({ loaded: true }, null)];
out.empty = [model.emptyCityVisible("ready", 0), model.emptyCityVisible("ready", 2), model.emptyCityVisible("loading", 0), model.emptyCityVisible("error", 0)];
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_camera_move_is_always_settled_and_the_empty_city_is_never_claimed_before_a_read_answered(tmp_path):
    got = run_node(tmp_path, TWEEN)
    assert got["activeAfterStart"] is True and got["midInside"] is True and got["stillActive"] is True
    assert [round(x, 9) for x in got["endFrustum"]] == [2, 6, 8, 4] and got["activeAtEnd"] is False and got["noStepWhenIdle"] is None
    assert got["cancelReturned"] is True and got["cancelAgain"] is False and got["activeAfterCancel"] is False
    assert got["settled"] == [["cut", False], ["finished", True], ["first", False], ["second", True]], \
        "a move that finishes settles true; one cancelled or replaced settles false, so a click never waits for nothing"
    assert got["states"] == ["loading", "error", "ready", "ready"]
    assert got["empty"] == [True, False, False, False], "no \"no project\" while loading or after a failed first read"


NOTICE = r"""
import { FakeNode } from "@FAKE@";
import { createFrame } from "@JS@/frame/frame.js";
import * as router from "@JS@/router.js";

const root = new FakeNode("div");
const frame = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
document.getElementById = (id) => [...root.walk()].find((n) => n.attrs.id === id) || null;
frame.main.append(frame.waitingCard.el);
const list = new FakeNode("section"); list.setAttribute("id", "wb-scene-list"); frame.main.append(list);   // the City view's list
const out = {};
// skip links: they act by id and never touch the hash
window.location.hash = "#/p/0123456789ab/lobby";
const skip = [...root.walk()].filter((n) => n.attrs.class === "wb-skip");
const clicks = [];
for (const link of skip) {
  globalThis.__focused = null;
  let prevented = false;
  link.listeners.click.forEach((fn) => fn({ preventDefault() { prevented = true; } }));
  clicks.push([link.attrs.href, prevented, globalThis.__focused && globalThis.__focused.attrs.id, window.location.hash]);
}
out.clicks = clicks;
// the notice: a poll with the same spec leaves the band (and a focused button) alone; a different one replaces it
const spec = { kind: "error", text: "could not be reached", retry: true };
frame.notice(spec);
const first = frame.noticeBox.children[0];
frame.notice({ ...spec });
out.sameKept = frame.noticeBox.children[0] === first;
frame.notice({ ...spec, text: "another" });
out.changedReplaced = frame.noticeBox.children[0] !== first && frame.noticeBox.children[0].textContent.includes("another");
frame.notice(null);
out.cleared = frame.noticeBox.hidden && frame.noticeBox.children.length === 0;
frame.notice(null);
out.clearedTwice = frame.noticeBox.hidden;
// destroying the frame takes its document listeners off
let removed = 0;
document.removeEventListener = (type) => { removed += 1; };
frame.destroy();
out.removed = removed;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_skip_links_focus_by_id_without_changing_the_hash_the_notice_is_redrawn_only_when_it_changes_and_the_frame_takes_its_listeners_off(tmp_path):
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM, encoding="utf-8")
    got = run_node(tmp_path, NOTICE.replace("@FAKE@", fake.as_uri()))
    assert got["clicks"] == [["#wb-panel", True, "wb-panel", "#/p/0123456789ab/lobby"],
                             ["#wb-scene-list", True, "wb-scene-list", "#/p/0123456789ab/lobby"]], \
        "a skip link prevents the fragment navigation, focuses its target and leaves the route alone"
    assert got["sameKept"] is True and got["changedReplaced"] is True and got["cleared"] is True and got["clearedTwice"] is True
    assert got["removed"] >= 3, "the frame, the switcher and the waiting menu each take their document listener off"


# --- rules read from the files -------------------------------------------------------------------------------------------------


def test_the_one_animation_frame_request_is_inside_the_scheduler_and_the_scheduler_draws_only_when_asked():
    users = {p.name: p.read_text(encoding="utf-8").count("requestAnimationFrame") for p in JS.rglob("*.js") if "requestAnimationFrame" in p.read_text(encoding="utf-8")}
    assert set(users) <= {"engine.js", "loop.js"}, f"requestAnimationFrame is used outside the scene engine: {sorted(users)}"
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert re.search(r"createLoop\(\{\s*raf: \(fn\) => requestAnimationFrame\(fn\)", engine), "the engine's one request is the scheduler's dependency"
    assert engine.count("requestAnimationFrame(") == 1 and "setInterval" not in engine, "no standing loop in the engine"
    loop = (SCENE / "loop.js").read_text(encoding="utf-8")
    assert "dirty" in loop and "function wanted()" in loop and "AMBIENT_FPS = 30" in loop
    assert re.search(r"function schedule\(\) \{[^}]*!wanted\(\)", loop, re.S), "a frame is requested only when something wants one"
    assert "setInterval" not in " ".join(p.read_text(encoding="utf-8") for p in JS.rglob("*.js")), "nothing polls on an interval timer: a poll is a timeout that the visibility rule can stop"


def test_the_engine_keeps_the_performance_rules_of_the_scene():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "Math.min(window.devicePixelRatio || 1, 2)" in engine, "pixel ratio at most 2"
    assert 'addEventListener("visibilitychange"' in engine and "loop.setHidden(document.hidden || paused)" in engine, "no rendering while the tab is hidden (or while a sheet covers the scene)"
    assert "(prefers-reduced-motion: reduce)" in engine and "reducedQuery.matches" in engine, "reduced motion is read at start and on change"
    assert "shadowMap.autoUpdate = false" in engine, "the shadow map is drawn again only when the geometry changes"
    assert "preserveDrawingBuffer" not in engine and "getContext(\"2d\")" not in engine, "one renderer, no drawing buffer kept, no 2D copy"
    assert "NoWebGL" in engine and "webglcontextlost" in engine and "webglcontextrestored" in engine, "the no-WebGL and lost-context paths"
    assert "forceContextLoss" in engine and "renderer.dispose()" in engine and "contentKit.dispose()" in engine, "the renderer and the geometry are freed on leaving"
    assert "ambient: true" in engine and "AMBIENT_FPS" not in engine, "the cap is the scheduler's, not repeated"
    assert "tween.cancel()" in engine and "createTween()" in engine, "a rebuild settles the camera move in flight (the tween's own test is under Node)"
    assert "light.shadow.dispose()" in engine, "the sun's shadow map is freed when the lights are replaced"
    assert "onRestored" in (JS / "views" / "city.js").read_text(encoding="utf-8"), "the scene host is shown again after a restored context"
    assert "export const CAMERA_MS = 1023" in engine and "export const OPEN_MS = 1439" in engine, "the prototype's durations: ln(100) over 4.5 and 3.2 a second"
    for name in ("palette.js", "kit.js", "props.js", "city.js", "labels.js", "cull.js", "fit.js",
                 "building.js", "world.js", "tower.js", "furniture.js", "plates.js", "owl-build.js", "owl-motion.js", "room-frame.js", "room-words.js", "server-room.js"):   # R-41: the figure is the owl; R-51: the server room
        assert (SCENE / name).is_file()
    # 23 modules before round 4; R-41 and R4D-2 add owl.js and svgpath.js, R-19 and R-20 city-motion.js, R-17 and R-20 marks.js; R4-B2 drops figure.js (R-24, R-41: the agent is the
    # owl) and adds owl-build.js, owl-motion.js (R-41), room-frame.js (R-23) and room-words.js (R-31); R4-B3 adds server-room.js (R-51: the server room's measures)
    assert len(list(SCENE.glob("*.js"))) == 31 and (SCENE / "tween.js").is_file()


def test_the_scene_draws_nothing_decorative_and_holds_no_colour_of_its_own():
    banned = re.compile(r"vehicle|\bcars?\b|\bbirds?\b|cloud|forklift|traffic|particle|weather|\bsway", re.I)
    for path in scene_files():
        text = path.read_text(encoding="utf-8")
        found = banned.search(text)
        assert not found, f"{path.name} mentions {found.group(0)!r}: only a state or a feature animates"
        assert not re.search(r"Math\.random|setInterval", text), f"{path.name}: nothing random, no timer"
        # a hex colour is allowed only for a light's colour (palette.js names them once); everything else is read from tokens
        for literal in re.findall(r"0x[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", text):
            # owl.js: the mark's own palette, the brand's exception (R-41): its six literals are pinned below
            assert path.name in ("palette.js", "engine.js", "owl.js"), f"{path.name} has a colour literal {literal}"
    palette = (SCENE / "palette.js").read_text(encoding="utf-8")
    assert sorted(re.findall(r"0x[0-9a-fA-F]{6}", palette)) == ["0x000000", "0xffffff"], "only the light's white and the shadow's black (DEVIATION-8)"
    owl = (SCENE / "owl.js").read_text(encoding="utf-8")
    assert sorted(re.findall(r"#[0-9a-fA-F]{6}\b", owl)) == sorted(["#1E1B2E", "#6B4429", "#A47551", "#E6D2BC", "#FFFFFF", "#FCD34D"]), "the owl's fixed palette is the mark's six colours and nothing else"
    assert not re.search(r"0x[0-9a-fA-F]{3,}|rgba?\(|hsla?\(|oklch\(|color-mix", owl), "no other way of writing a colour in owl.js"
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert re.findall(r"0x[0-9a-fA-F]{6}", engine) == ["0xffffff"], "the outline's colour is replaced by the theme token at once"
    for token in ("--wb-raised", "--wb-ground", "--pui-theme", "--pui-warn", "--pui-success", "--pui-error", "--pui-border", "--pui-text-muted"):
        assert token in palette, f"the palette reads {token}"


def test_a_script_writes_only_custom_properties_to_an_elements_style():
    for path in sorted(JS.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for call in re.findall(r"\.style\.(\w+)\(([^)]*)", text):
            ok = call[0] == "setProperty" and (re.match(r'\s*"--wb-(x|y|share|drawer-drag|wait-h|cam-top|notice-bottom)"', call[1]) or (path.name == "palette.js" and "color" in call[1]))
            assert ok, \
                f"{path.name}: {call}: a script writes the page's own position and share properties only"
        assert not re.search(r"\.style\.\w+\s*=[^=]", text), f"{path.name} assigns a style property"
        assert "style.cssText" not in text and "setAttribute(\"style\"" not in text


def test_the_stylesheet_derives_the_pages_tokens_from_the_librarys_and_every_icon_it_names_is_a_clean_file():
    css = interface_css()
    root = re.search(r":root \{(.*?)\n\}", css, re.S).group(1)
    for name in ("--wb-raised", "--wb-ground", "--wb-sunken", "--wb-shadow-ink", "--wb-elev", "--wb-ink-theme", "--wb-ink-warn", "--wb-tint-selected"):
        assert re.search(rf"{name}:", root), f"{name} is defined on :root"
    assert "light-dark(var(--pui-bg), var(--pui-bg-muted))" in root and "light-dark(var(--pui-bg-muted), var(--pui-bg))" in root
    # OH-3: the one literal is the brand pair of the primary token (test_interface_files.py keeps that line whole and alone)
    without_brand = re.sub(r"^[ \t]*--pui-theme: light-dark\(#6B4429, #C99A6E\);$", "", css, flags=re.M)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", without_brand), "no colour literal anywhere in the stylesheet but the brand pair"
    named = sorted(set(re.findall(r'url\("\.\./icons/([a-z0-9-]+)\.svg"\)', css)))
    classes = sorted(set(re.findall(r"\.wb-icon-([a-z0-9-]+) \{", css)))
    files = sorted(p.stem for p in (INTERFACE / "icons").glob("*.svg"))
    assert named == classes == files, "one class and one file for each icon"
    listed = re.search(r"ICONS = Object\.freeze\(\[(.*?)\]\)", (FRAME / "icons.js").read_text(encoding="utf-8"), re.S).group(1)
    assert sorted(re.findall(r'"([a-z0-9-]+)"', listed)) == files
    for path in (INTERFACE / "icons").glob("*.svg"):
        text = path.read_text(encoding="utf-8")
        assert "<metadata" not in text and "c2pa" not in text.lower() and len(text) < 1000, f"{path.name}: a clean icon file, no embedded metadata"
        assert 'viewBox="0 0 24 24"' in text and 'stroke="currentColor"' in text
    assert "prefers-reduced-motion" in css and "@keyframes wb-pop" in css


def test_the_page_has_one_scene_container_and_an_html_equivalent_of_every_scene_action():
    city = (JS / "views" / "city.js").read_text(encoding="utf-8")
    assert "wb-building-list" in city and "wb-scene-list" in city and "model.linkNameOf" in city, "a list of the buildings, each a link"
    assert "highlight(" in city and "flyTo(" in city and "NoWebGL" in city, "the list and the scene share one open action; without WebGL the screen keeps its HTML"
    frame = (FRAME / "frame.js").read_text(encoding="utf-8")
    for needle in ("Skip to the panel", "Skip to the scene list", '"aria-live": "polite"', "Your browser cannot draw the 3D scene; the panels have everything."):
        assert needle in frame
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert '"aria-hidden": "true"' in engine and 'role: "img"' in engine, "the canvas is an image with a label; the overlay is hidden from the tree"


# --- WP-9.5b: defects the end-to-end smoke found -------------------------------------------------------------------------------------


def _calls_of(source: str, names) -> list[str]:
    stripped = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.S)
    stripped = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', stripped)
    return [n for n in names if re.search(rf"(?<![\w.]){re.escape(n)}\(", stripped)]


def test_every_name_the_scene_engine_calls_from_a_sibling_module_is_imported():
    """`ease` was called by engine.js and exported by fit.js but never imported: a ReferenceError on every entry to the Building."""
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    imports = {m.group(2): {n.strip().split(" as ")[-1] for n in m.group(1).split(",") if n.strip()}
               for m in re.finditer(r'import \{([^}]*)\} from "\./([a-z-]+)\.js"', engine)}
    checked = 0
    for module in sorted(SCENE.glob("*.js")):
        if module.name == "engine.js":
            continue
        exported = re.findall(r"export (?:function|const|class|let) ([A-Za-z_]\w*)", module.read_text(encoding="utf-8"))
        for name in _calls_of(engine, exported):
            checked += 1
            assert name in imports.get(module.stem, set()), f"engine.js calls {name}() of {module.name} and does not import it"
    assert checked >= 5, "the check found the engine's calls into its siblings"
    assert "ease" in imports["fit"], "the opening animation and the work-order tag use ease"


def test_the_notice_band_and_the_commands_it_shows_have_no_fixed_height_that_clips_them():
    """The `accept-config` command is copied whole: the band's text, the Floor's notice card and its command wrap, never scroll."""
    css = interface_css()
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    seen = set()
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        names = {n for n in (".wb-notice-text", ".wb-notice-card", ".wb-command", ".wb-notice") if re.search(rf"{re.escape(n)}(?![\w-])", selector)}
        if not names:
            continue
        seen |= names
        assert not re.search(r"(?<![\w-])(?:max-)?height\s*:", body), f"{selector.strip()}: no height, so nothing is cut"
        assert not re.search(r"overflow(?:-y)?\s*:\s*(?:auto|scroll|hidden)", body), f"{selector.strip()}: no inner scroll box"
    assert seen == {".wb-notice-text", ".wb-notice-card", ".wb-command", ".wb-notice"}
    assert re.search(r"\.wb-notice-text \{[^}]*overflow-wrap: anywhere", css), "a long hash breaks anywhere"
    assert re.search(r"\.wb-command \{[^}]*overflow-wrap: anywhere", css)


CITY_ARROWS = r"""
import { FakeNode, settle } from "@FAKE@";
import { createCityView } from "@JS@/views/city.js";

globalThis.ResizeObserver = class { observe() {} disconnect() {} };
const el = () => new FakeNode("div");
const frame = {
  main: el(), sceneHost: el(), track: { el: el() }, kpis: { el: el() }, noticeBox: el(),
  waitingCard: { el: el(), set() {} },
  insets: () => ({}), sceneUnavailable() {},
  acquireWorld: () => ({ highlight() {}, show() {}, flyTo: () => Promise.resolve(false), setOptions() {}, stats() { return {}; } }),
};
const view = createCityView(frame);
const b = (id, name) => ({ id, name, accepted: true, decisions: 0, runningTask: null, sub: "" });
view.update({ city: { buildings: [b("aaaaaaaaaaaa", "alpha"), b("bbbbbbbbbbbb", "beta"), b("cccccccccccc", "gamma")], waiting: [], canvasLabel: "City" }, selectedId: null, state: "ready", snapshot: { projects: [], details: {}, tasks: {}, loaded: true }, now: new Date("2026-10-08T12:00:00Z") });
const list = frame.main.querySelectorAll("ul.wb-building-list")[0];
const links = frame.main.querySelectorAll("a.wb-building-link");
const press = (key) => {
  let prevented = false;
  for (const fn of list.listeners.keydown || []) fn({ key, preventDefault() { prevented = true; } });
  return prevented;
};
const out = { links: links.length, handlers: (list.listeners.keydown || []).length };
links[0].focus();
out.down = [press("ArrowDown"), links.indexOf(document.activeElement)];
press("ArrowDown");
out.down2 = links.indexOf(document.activeElement);
press("ArrowDown");
out.stopsAtEnd = links.indexOf(document.activeElement);
press("ArrowUp");
out.up = links.indexOf(document.activeElement);
press("Home");
out.home = links.indexOf(document.activeElement);
press("End");
out.end = links.indexOf(document.activeElement);
out.otherKey = press("a");
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_cities_list_of_buildings_moves_the_focus_with_the_arrow_keys(tmp_path):
    from test_interface_floor import FAKE_DOM as FLOOR_DOM
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FLOOR_DOM + "\nglobalThis.__unused = 0;\n", encoding="utf-8")
    script = tmp_path / "city.mjs"
    script.write_text(CITY_ARROWS.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    got = json.loads(done.stdout.strip().splitlines()[-1])
    assert got["links"] == 3 and got["handlers"] == 1, "one keydown handler on the list"
    assert got["down"] == [True, 1] and got["down2"] == 2 and got["stopsAtEnd"] == 2, "ArrowDown moves down and stops at the last building"
    assert got["up"] == 1 and got["home"] == 0 and got["end"] == 2
    assert got["otherKey"] is False, "other keys are left alone"

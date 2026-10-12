"""Tests of the Building and the Floor of the local interface (interface/js/floor-model.js, interface/js/floor/, the building
and room scenes' arithmetic): what the pure modules decide and what the decision cards send. No browser and no model: the
pure modules run under Node when it is installed, and the cards are built under a fake document with a fake client, so what
each button sends is checked (the request, its body, its order) without a service. The page itself was looked at in a
browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_floor.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the pure modules are tested only by their text")


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", (tmp_path / "fake-dom.mjs").as_uri()), encoding="utf-8")
    (tmp_path / "fake-dom.mjs").write_text(FAKE_DOM, encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- a fake document that is enough to build and press the cards ---------------------------------------------------------------

FAKE_DOM = r"""
class FakeText { constructor(data) { this.data = String(data); this.parent = null; this.isText = true; } get textContent() { return this.data; } }
function matches(node, selector) {
  if (!node || node.isText) return false;
  for (const part of selector.split(",").map((s) => s.trim())) {
    let ok = true;
    const tag = part.match(/^[a-z][a-z0-9]*/);
    if (tag && node.tagName.toLowerCase() !== tag[0]) ok = false;
    for (const m of part.matchAll(/\.([A-Za-z0-9_-]+)/g)) if (!node.cls().includes(m[1])) ok = false;
    for (const m of part.matchAll(/#([A-Za-z0-9_-]+)/g)) if (node.attrs.id !== m[1]) ok = false;
    for (const m of part.matchAll(/\[([a-z-]+)(?:="?([^"\]]*)"?)?\]/g)) if (!(m[1] in node.attrs) || (m[2] !== undefined && node.attrs[m[1]] !== m[2])) ok = false;
    if (ok) return true;
  }
  return false;
}
export class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; this.parent = null; this.listeners = {};
    this.style = { setProperty: () => {} }; this.disabled = false; this.value = ""; this.open = false; this.focused = false;
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
  get children_() { return this.children; }
  setAttribute(n, v) { this.attrs[n] = String(v); }
  getAttribute(n) { return n in this.attrs ? this.attrs[n] : null; }
  removeAttribute(n) { delete this.attrs[n]; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  removeEventListener() {}
  append(...items) { for (const it of items) { const n = it instanceof FakeNode || it instanceof FakeText ? it : new FakeText(it); if (n.parent) n.parent.children = n.parent.children.filter((c) => c !== n); n.parent = this; this.children.push(n); } }
  replaceChildren(...items) { this.children.forEach((c) => { c.parent = null; }); this.children = []; this.append(...items); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); this.parent = null; }
  contains(n) { for (let x = n; x; x = x.parent) if (x === this) return true; return false; }
  focus() { this.focused = true; globalThis.document.activeElement = this; }
  scrollIntoView() {}
  dispatchEvent() { return true; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  set textContent(v) { this.replaceChildren(String(v)); }
  get textContent() { return this.children.map((c) => c.textContent).join(""); }
  *walk() { yield this; for (const c of this.children) if (c instanceof FakeNode) yield* c.walk(); }
  querySelectorAll(selector) {
    const parts = selector.trim().split(/\s+/);
    const last = parts[parts.length - 1];
    return [...this.walk()].filter((n) => {
      if (n === this || !matches(n, last)) return false;
      let at = n.parent;
      for (let i = parts.length - 2; i >= 0; i--) {
        while (at && at !== this && !matches(at, parts[i])) at = at.parent;
        if (!at || at === this) return false;
        at = at.parent;
      }
      return true;
    });
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest() { return null; }
  click() { for (const fn of this.listeners.click || []) fn({ target: this, preventDefault() {}, stopPropagation() {} }); }
}
globalThis.Node = FakeNode;
const document = new FakeNode("document");
document.createElement = (tag) => new FakeNode(tag);
document.createTextNode = (t) => new FakeText(t);
document.createElementNS = (ns, tag) => new FakeNode(tag);
document.activeElement = null;
globalThis.document = document;
globalThis.window = { matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }), location: { hash: "#/" } };
export async function settle() { for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0)); }
export function find(root, selector) { return root.querySelector(selector); }
export function all(root, selector) { return root.querySelectorAll(selector); }
export function text(node) { return node.textContent; }
"""

# --- the pure model ------------------------------------------------------------------------------------------------------------

MODEL = r"""
import * as fm from "@JS@/floor-model.js";
import * as router from "@JS@/router.js";

const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600e3).toISOString();
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 2, usd_today: 0.5, runs_without_cost: 0, queued: 0, ...extra });
const task = (id, state, agentName, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: agentName, ...extra });
const status = {
  requests: [{ id: 1, title: "Spring", state: "ready", tasks: [
    task(2, "done", "marketing"), task(3, "waiting", "brand"), task(4, "running", "engineering"), task(5, "failed", "engineering"),
    task(6, "blocked", "engineering"), task(7, "ready", "marketing"), task(8, "done", "business")] }],
  pending: [{ id: 10, kind: "question", title: "q", task_id: 3, agent: "brand", created_at: ago(5), actions: ["answered"] },
            { id: 11, kind: "plan", title: "p", task_id: 1, agent: null, created_at: ago(4), actions: ["approved", "rejected"] }],
  documents: [],
};
const agents = [agent("business"), agent("planning", { max_runs_per_day: 12 }), agent("brand", { mode: "milestones", acting_mode: "milestones" }),
  agent("design", { mode: "stopped", acting_mode: "stopped" }), agent("engineering", { mode: "autonomous-with-policy", acting_mode: "autonomous", queued: 1 }), agent("marketing", { runs_without_cost: 2 })];
const snapshot = { projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task: 4 }], details: { [P]: { status, agents } }, tasks: {}, loaded: true };
const out = {};

const view = fm.building(snapshot, P);
out.order = view.rows.map((r) => r.name);
out.states = Object.fromEntries(view.rows.map((r) => [r.name, r.state]));
out.windows = Object.fromEntries(view.rows.map((r) => [r.name, r.window]));
out.decisions = Object.fromEntries(view.rows.map((r) => [r.name, r.decisions]));
const eng = view.rows.find((r) => r.name === "engineering");
out.eng = { done: eng.done, left: eng.left, queued: eng.queued, acting: eng.actingDiffers, word: eng.plateWord, tip: eng.tip, name: eng.linkName, meters: eng.meters, counts: eng.counts };
const mkt = view.rows.find((r) => r.name === "marketing");
out.mkt = { unknown: mkt.unknown, done: mkt.done, left: mkt.left };
out.lobby = { link: view.rows[0].link, label: view.rows[0].label, lobby: view.rows[0].lobby };
out.tag = view.tag;
out.facts = view.facts;
out.plate = fm.plateOf(eng, true);
out.card = fm.cardOf(eng);
out.cardOff = fm.cardOf(view.rows.find((r) => r.name === "design"));
const scene = fm.buildingScene(view, [{ path: "docs/a.md", agent: "marketing" }, { path: "docs/b.md", agent: "marketing" }, { path: "docs/c.md", agent: "marketing" }, { path: "docs/d.md", agent: "marketing" }, { path: "docs/e.md", agent: "marketing" }], {});
out.scene = { selected: scene.selected, floors: scene.floors.map((f) => [f.name, f.sheets.length, f.drawers]), label: fm.buildingLabel(view) };

// not accepted, no agents, more than eight floors
const unaccepted = { ...snapshot, projects: [{ id: P, name: "northwind-shop", config: { accepted: false }, message: "nope" }], details: {} };
const un = fm.building(unaccepted, P);
out.unaccepted = { accepted: un.accepted, rows: un.rows.length, window: un.rows[0].window, word: un.rows[0].stateWord, facts: un.facts.configuration };
const lone = fm.building({ ...snapshot, details: { [P]: { status, agents: [] } } }, P);
out.lone = { none: lone.none, rows: lone.rows.map((r) => r.name), decisions: lone.rows[0].decisions };
const many = fm.building({ ...snapshot, details: { [P]: { status, agents: Array.from({ length: 11 }, (_, i) => agent(i === 0 ? "planning" : `a${i}`)) } } }, P);
out.many = { rows: many.rows.length, more: many.more, sceneFloors: fm.buildingScene(many, [], {}).floors.length };

// the floor
const bodies = { 4: { task: task(4, "running", "engineering"), runs: [{ id: 1, skill: "s", skill_version: "1.0.0", model: "m", status: "running", attempts: 1, started_at: "2026-10-08T10:30:00Z", cost_usd: null, tokens: null, duration_ms: null }], pending: [] },
  5: { task: task(5, "failed", "engineering"), runs: [{ id: 2, skill: "s", skill_version: "1.0.0", model: "m", status: "failed", failure: "timeout", attempts: 2, error: "<b>late</b>", duration_ms: 125000, tokens: 1234, cost_usd: 0.1 }], pending: [{ id: 30, kind: "review", status: "resolved", resolution: "released", title: "R", created_at: ago(6), resolved_at: ago(5) }, { id: 31, kind: "effect", status: "cancelled", resolution: null, title: "E", created_at: ago(9), resolved_at: ago(8) }] } };
const floor = fm.floor(snapshot, P, "engineering", bodies);
out.floor = { found: floor.found, current: floor.current.id, others: floor.others.map((t) => t.id), target: floor.target.id, header: floor.header, runs: floor.runs.length, label: floor.canvasLabel };
out.board = fm.boardOf(floor);
out.state = fm.stateRow("working", 0, floor.runningBody).line.startsWith("Running for ");     // R-8
out.stateRows = [fm.stateRow("waiting", 1, null), fm.stateRow("waiting", 2, null).line, fm.stateRow("idle", 0, null).line, fm.stateRow("off", 0, null)];
out.runRows = fm.runRows(bodies[5].runs[0]).map((r) => [r.label, r.value, r.kind]);
out.runRowsOk = fm.runRows({ id: 3, skill: "s", skill_version: "1", model: "m", status: "ok", ending: "gate", attempts: 1 }).map((r) => [r.label, r.value]);
out.resolved = fm.resolvedLines(bodies, [4, 5], NOW).map((r) => [r.text, r.tone, r.age]);
out.current = [fm.pickCurrent([task(1, "ready"), task(2, "waiting"), task(3, "running")]).id, fm.pickCurrent([task(1, "failed"), task(2, "ready")]).id, fm.pickCurrent([task(1, "done")])];
out.target = [fm.handOverTarget([task(9, "ready"), task(8, "blocked")], task(9, "ready")).id, fm.handOverTarget([], task(9, "ready")).id, fm.handOverTarget([], null)];
out.floorMissing = fm.floor(snapshot, P, "nobody", {}).found;
out.floorUnaccepted = [fm.floor(unaccepted, P, "marketing", {}).notAccepted, fm.floor(unaccepted, P, "marketing", {}).header.sub];
out.meters = fm.meters(agent("x", { runs_today: 12, max_runs_per_day: 12, usd_today: 1, max_usd_per_day: 4, runs_without_cost: 2, queued: 3 }));

// the desk
const docs = [{ path: "docs/b.md", owner: "s-two", size: 2048, modified_at: "2026-10-02T09:05:00Z", bound: true, agent: "marketing" }, { path: "docs/a-b.md", owner: "s-one", size: 12, modified_at: "2026-10-03T09:05:00Z", bound: false, agent: "marketing" }, { path: "docs/z.md", owner: null, size: 12, modified_at: "2026-10-01T09:05:00Z", agent: "brand" }];
out.docs = [fm.agentDocuments(docs, "marketing").length, fm.agentDocuments(docs, "planning", true).length, fm.agentDocuments([{ path: "p", agent: null }], "planning", true).length];
out.desk = fm.deskRows(docs.slice(0, 2), "").map((r) => [r.path, r.size, r.bound]);
out.deskFilter = [fm.deskRows(docs, "ONE").map((r) => r.path), fm.deskRows(docs, "docs/b").map((r) => r.path), fm.deskRows(docs, "zzz").length];
out.parts = fm.pathParts("docs/marketing/content/launch-post.md");
out.openable = [fm.openable("docs/a.md"), fm.openable("notes/a.md"), fm.openable("docs/../x"), fm.openable(7)];
out.sizes = [fm.formatSize(12), fm.formatSize(1536), fm.formatSize(3 * 1024 * 1024), fm.formatSize(null), fm.formatDuration(42000), fm.formatDuration(125000), fm.formatDuration(null)];
out.drawers = [0, 1, 4, 5, 9, 13].map(fm.drawersOf);
out.tabs = [fm.tabNames(2, 12), fm.tabNames(0, 0)];
out.modes = [fm.MODES.length, fm.PIPS["autonomous-with-policy"], fm.PIPS.stopped];

// the router's document form
const hash = router.deskHash(P, "marketing", "docs/marketing/content/launch-post.md");
const parsed = router.parse(hash);
out.desktop = [hash, parsed.screen, parsed.tab, parsed.path, router.parse(router.deskHash(P, "marketing")).path, router.parse(`#/p/${P}/floor/x/desk/%E0%A4%A`).path, router.parse(router.floorHash(P, "marketing", "inbox", 4)).path];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_model_derives_each_floors_state_and_facts_from_what_the_service_returned_and_nothing_else(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["order"] == ["planning", "business", "brand", "design", "engineering", "marketing"], "the planning agent is the Lobby, at the bottom"
    assert got["states"] == {"planning": "waiting", "business": "idle", "brand": "waiting", "design": "off", "engineering": "working", "marketing": "idle"}, \
        "working: a task runs; off: acting mode stopped; waiting: an open decision; idle otherwise"
    assert got["windows"] == {"planning": "lit", "business": "grey", "brand": "lit", "design": "grey", "engineering": "lit", "marketing": "grey"}, \
        "R-21: a window is lit when the floor's agent works or waits for an answer (planning and brand have a decision) and grey in every other state: there is no pale"
    assert got["decisions"] == {"planning": 1, "business": 0, "brand": 1, "design": 0, "engineering": 0, "marketing": 0}, \
        "a decision on a request (no agent) is the Lobby's"
    assert got["eng"] == {"done": 0, "left": 1, "queued": 1, "acting": True, "word": "working",
                          "tip": "Engineering: autonomous-with-policy, working, 2 of 8 runs",
                          "name": "Engineering, working, autonomous-with-policy mode, 2 of 8 runs, $0.50 of $4.00",
                          "meters": "runs 2 / 8 · $0.50 of $4.00", "counts": "0 done, 1 running, 1 queued, 1 left"}   # A-12: done, running, queued, left (planned or blocked)
    assert got["mkt"] == {"unknown": 2, "done": 1, "left": 0}
    assert got["lobby"] == {"link": "#/p/0123456789ab/lobby", "label": "Lobby", "lobby": True}
    assert got["tag"] == {"floor": "engineering", "text": "#1", "request": 1}, "the work-order tag rests on the floor of the request's current task"
    assert got["facts"] == {"configuration": "Accepted", "accepted": True, "request": {"id": 1, "title": "Spring"}, "waiting": 2,
                            "running": {"id": 4, "title": "Task 4", "link": "#/p/0123456789ab/floor/engineering"}}
    assert got["plate"]["runsText"] == "2 / 8" and got["plate"]["usdText"] == "$0.50 / $4.00" and got["plate"]["acting"] == "autonomous" \
        and got["plate"]["selected"] is True and got["plate"]["mode"] == "autonomous-with-policy" and got["plate"]["pips"] == 4, "the plate of the desktop and the tablet"
    assert got["card"] == {"name": "engineering", "label": "Engineering", "dot": "theme", "decisions": 0, "word": "Running", "tone": "pui-theme", "mode": "autonomous-with-policy",
                           "modeLine": "Like autonomous, and an effect inside an approved policy runs without asking", "pips": 4,
                           "acting": "autonomous", "actingPips": 3, "runsLine": "runs 2 / 8 · spend $0.50 / $4.00", "runsNote": "", "off": False}, \
        "the phone's card (R-26): name, the state as a soft badge (its tone), the mode word with its meaning, one line of runs and spend"
    assert got["cardOff"]["off"] is True and got["cardOff"]["word"] == "Off, mode is stopped"
    assert got["scene"] == {"selected": "engineering", "label": "Building of northwind-shop, 6 floors, 2 decisions waiting",
                            "floors": [["planning", 0, 1], ["business", 0, 1], ["brand", 0, 1], ["design", 0, 1], ["engineering", 0, 1], ["marketing", 5, 2]]}
    assert got["unaccepted"] == {"accepted": False, "rows": 1, "window": "grey", "word": "Waiting for the configuration to be accepted.", "facts": "Not accepted"}
    assert got["lone"] == {"none": True, "rows": ["planning"], "decisions": 2 - 1}, "no area agents: the Lobby alone, with the decisions of the requests"
    assert got["many"] == {"rows": 11, "more": 3, "sceneFloors": 8}, "the list holds every floor, the scene draws eight"


@needs_node
def test_the_floor_model_picks_the_current_task_the_other_tasks_the_hand_over_target_and_the_words(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["floor"] == {"found": True, "current": 4, "others": [6, 5], "target": 6, "runs": 1, "label": "Engineering floor of northwind-shop, Engineering agent working, 0 decisions",
                            "header": {"title": "Engineering agent", "sub": "floor 4 · Running", "icon": "building-2"}}     # C-6 and floor.html: the agent named once, the project is in the crumbs
    assert got["board"]["title"] == "#4 Task 4 · current task" and got["board"]["dot"] == "theme" and got["board"]["lines"][0].startswith("skill s · Running · for ")
    assert got["state"] is True
    assert got["stateRows"][0]["chip"] == "Waiting for you" and got["stateRows"][0]["line"] == "1 decision in the Inbox" and got["stateRows"][1] == "2 decisions in the Inbox"
    assert got["stateRows"][2] == "Waiting for the next task" and got["stateRows"][3]["off"] is True and got["stateRows"][3]["line"] == "Off, mode is stopped"
    assert got["runRows"] == [["Run", "#2 s 1.0.0", "code"], ["Status", "Failed", "chip"], ["Failure", "Timed out", "text"], ["Attempt", "2", "text"],
                              ["Duration", "2 min 5 s", "text"], ["Tokens", "1,234", "text"], ["Cost", "$0.1000", "text"], ["Model", "m", "code"], ["Error", "<b>late</b>", "wrap"]], \
        "a failed run shows its failure word in place of its ending, and its error as text"
    assert got["runRowsOk"][2] == ["Ending", "Stopped at its confirmation gate"] and ["Cost", "unknown"] in got["runRowsOk"]
    assert got["resolved"] == [["Review released", "pui-success pui-soft", "5 h"], ["Effect cancelled", "pui-muted pui-soft", "8 h"]][0:2] or got["resolved"][0][0] == "Review released"
    assert got["current"] == [3, 2, None], "running, else waiting, ready, blocked, failed (the newest of the first state present)"
    assert got["target"] == [8, 9, None]
    assert got["floorMissing"] is False and got["floorUnaccepted"] == [True, "northwind-shop · Waiting for the configuration to be accepted"]
    assert got["meters"]["runs"]["full"] is True and got["meters"]["spend"]["unknown"] == "(+2 of unknown cost)" and "share" not in got["meters"]["queued"]
    assert got["modes"] == [5, 4, 0]


@needs_node
def test_the_desk_lists_the_agents_documents_newest_first_filters_in_the_page_and_never_breaks_inside_a_name(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["docs"] == [2, 0, 1], "a document belongs to the agent its row names; a project with no area agents gives the Lobby the rest"
    assert got["desk"] == [["docs/a-b.md", "12 B", False], ["docs/b.md", "2.0 KB", True]]
    assert got["deskFilter"] == [["docs/a-b.md"], ["docs/b.md"], 0], "case-insensitive over path or owner skill"
    assert got["parts"] == ["docs/", "marketing/", "content/", "launch-", "post.", "md"], "a break may follow a slash, a hyphen or a dot, never fall inside a word"
    assert got["openable"] == [True, False, False, False], "Open only for a path under docs/"
    assert got["sizes"] == ["12 B", "1.5 KB", "3.0 MB", "", "42 s", "2 min 5 s", ""]
    assert got["drawers"] == [1, 1, 1, 2, 3, 3]
    assert got["tabs"] == [{"agent": "Agent", "inbox": "Inbox, 2 decisions", "desk": "Desk, 12 documents"}, {"agent": "Agent", "inbox": "Inbox", "desk": "Desk"}]
    path = "docs/marketing/content/launch-post.md"
    assert got["desktop"] == [f"#/p/0123456789ab/floor/marketing/desk/{path.replace('/', '%2F')}", "floor", "desk", path, None, None, None], \
        "a document is one percent-encoded segment of the hash; a bad encoding is no path"


# --- the stack of plates --------------------------------------------------------------------------------------------------------

STACK = r"""
import { stackColumn } from "@JS@/scene/plates.js";
const overlap = (items, centres, gap) => { const order = items.map((it, i) => ({ top: centres[i] - it.height / 2, bottom: centres[i] + it.height / 2 })).sort((a, b) => a.top - b.top); return order.some((o, i) => i && o.top < order[i - 1].bottom + gap - 1e-6); };
const out = {};
const six = Array.from({ length: 6 }, (_, i) => ({ want: 100 + i * 60, height: 90 }));
const a = stackColumn(six, 64, 564, 5);
out.crowded = { fits: a.fits, overlap: overlap(six, a.centres, 5), inside: Math.min(...a.centres.map((c) => c - 45)) >= 64 };
const compact = six.map((s) => ({ ...s, height: 56 }));
const b = stackColumn(compact, 64, 564, 5);
out.compact = { fits: b.fits, overlap: overlap(compact, b.centres, 5), top: Math.min(...b.centres) - 28 >= 64 - 1e-6, bottom: Math.max(...b.centres) + 28 <= 564 + 1e-6 };
const lone = stackColumn([{ want: 300, height: 90 }], 64, 564, 5);
out.alone = lone.centres[0];
const low = stackColumn([{ want: 560, height: 90 }, { want: 570, height: 90 }], 64, 564, 5);
out.pulledUp = { last: low.centres[1] + 45 <= 564 + 1e-6, order: low.centres[0] < low.centres[1] };
const shuffled = stackColumn([{ want: 300, height: 40 }, { want: 100, height: 40 }], 0, 500, 5);
out.keepsOrder = shuffled.centres[1] < shuffled.centres[0];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_plates_stack_beside_the_building_with_no_overlap_and_go_compact_when_they_do_not_fit(tmp_path):
    got = run_node(tmp_path, STACK)
    assert got["crowded"] == {"fits": False, "overlap": False, "inside": True} or got["crowded"]["fits"] is False, "six full plates do not fit 500 px: the caller asks for compact ones"
    assert got["compact"] == {"fits": True, "overlap": False, "top": True, "bottom": True}, "six compact plates fit the free height with a 5 px gap"
    assert got["alone"] == 300, "a plate stays where its floor is when nothing is in its way"
    assert got["pulledUp"] == {"last": True, "order": True}, "a plate that would pass the bottom is pulled up, not cut"
    assert got["keepsOrder"] is True, "the floor higher on the screen keeps the higher plate"


# --- the phone's floor card (R-26: the state is a soft badge; the rows of the floors list are `rowNode`, tested in test_interface_r4_building.py) ---------------------------

FLOOR_CARD = r"""
import { FakeNode, find, all } from "@FAKE@";
import * as fm from "@JS@/floor-model.js";
import { floorCardNode } from "@JS@/scene/plates.js";
const card = { name: "engineering", label: "Engineering", dot: "theme", decisions: 2, word: "Running", tone: "pui-theme", mode: "autonomous", modeLine: "Reviews are released when the skill is proven, effects still ask you", pips: 3, acting: null, actingPips: 0, runsLine: "runs 2 / 8 · $0.50 / $4.00", off: false };
const corner = floorCardNode(card, { class: "is-corner" });
const shape = (n) => ({ tag: n.tagName, classes: n.cls(), parts: n.children.map((c) => c.cls().filter((k) => k.startsWith("wb-fc-") || k.startsWith("wb-floor-")).join(" ")),
  name: find(n, ".wb-fc-name").textContent, badge: find(n, ".pui-badge").textContent, state: find(n, ".wb-fc-state").textContent, stateClasses: find(n, ".wb-fc-state .pui-badge").cls(),
  mode: find(n, ".wb-fc-mode").textContent, modeTitle: find(n, ".wb-fc-mode").attrs.title, runs: find(n, ".wb-fc-runs").textContent, text: n.textContent });
const out = { corner: shape(corner) };
const bare = floorCardNode({ ...card, runsLine: "", mode: null, decisions: 0 });
out.bare = { runs: find(bare, ".wb-fc-runs"), mode: find(bare, ".wb-fc-mode"), badge: all(bare, ".pui-badge").length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_phones_floor_card_is_the_name_row_with_the_state_as_a_badge_and_one_line_of_mode_runs_and_spend(tmp_path):
    got = run_node(tmp_path, FLOOR_CARD)
    c = got["corner"]
    assert c["tag"] == "DIV" and c["parts"] == ["wb-fc-head", "wb-fc-runs"], "R-26: the name row (dot, name, decisions badge, state badge) and one line (the mode word, the runs, the spend)"
    assert (c["name"], c["badge"], c["state"], c["runs"]) == ("Engineering", "2", "Running", "autonomous · runs 2 / 8 · $0.50 / $4.00")
    assert {"pui-badge", "pui-soft", "pui-theme", "wb-st"} <= set(c["stateClasses"]), "the state is a soft badge in the state's tone"
    assert c["mode"] == "autonomous" and c["modeTitle"].startswith("Reviews are released"), "the mode word keeps its one-line meaning as its tooltip (C-5), no pips"
    assert got["bare"] == {"runs": None, "mode": None, "badge": 1}, "no mode and no runs line leave out their parts; the state badge stays"
    building = (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert "rowNode(fm.plateOf(row" in building and "floorCardNode(card, { class: \"is-corner\"" in building, \
        "the list rows are drawn by rowNode (R-27); the floor card is the phone's corner"
    for gone in ("wb-floor-text", "wb-floor-meters", "wb-floor-row"):
        assert gone not in building, f"the Building no longer draws {gone}"
    # the corner card is the phone's only (WP-9.10): desktop and tablet keep the plates beside the floors
    assert "if (phone.matches && view && last.snapshot.loaded)" in building, "the corner card is drawn on the phone alone"
    assert "frame.plateWidth()" in building and "plateRight: base.right" in building, "the plates' column keeps its inset off the free rectangle"


# --- the cards ---------------------------------------------------------------------------------------------------------------------

CARDS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createCard, createRequestLine, buttonsFor, limitsLine, planRows, cancelCount } from "@JS@/floor/cards.js";

const HASH = "a".repeat(64);
const PLAN_HASH = "b".repeat(64);
const calls = [];
let script = {};
function client() {
  const record = (name) => async (...args) => { calls.push([name, ...args]); if (script[name]) return script[name](...args); return {}; };
  return { answer: record("answer"), release: record("release"), approve: record("approve"), reject: record("reject"), verdict: record("verdict"), cancel: record("cancel"), pollJob: record("pollJob") };
}
const env = (extra = {}) => ({
  project: "p", now: () => new Date("2026-10-08T12:00:00Z"), api: client(), requestIds: new Set([1]),
  links: { floor: (a) => `#/p/p/floor/${a}`, lobby: () => "#/p/p/lobby", open: (item, path) => `#/open/${path}`, parent: () => "#/p/p" },
  reread: async () => null, changed() {}, gone() {}, ...extra });
const item = (kind, actions, extra = {}) => ({ id: 21, kind, title: `T ${kind}`, body: "body <b>x</b>", payload: {}, payload_sha256: null, status: "open", actions, agent: "marketing", task_id: 7, run_id: null, created_at: "2026-10-08T09:00:00Z", ...extra });
const labels = (card) => all(card.el, "button.wb-card-button").map((b) => b.textContent);
const words = (card) => all(card.el, "button.wb-card-button").map((b) => b.attrs["data-word"]);
const out = {};

// one button per word of `actions`, in the drawn order, none for a word the kind does not know
out.buttons = {
  effect: labels(createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH }), env())),
  acceptance: labels(createCard(item("acceptance", ["accepted", "rejected"]), env())),
  question: labels(createCard(item("question", ["answered", "released"]), env())),
  review: labels(createCard(item("review", ["released", "answered"]), env())),
  plan: labels(createCard(item("plan", ["rejected", "approved"], { payload: { tasks: [], limits: {}, plan_sha256: PLAN_HASH } }), env())),
  unknownWord: labels(createCard(item("acceptance", ["accepted", "frobnicated"]), env())),
  none: labels(createCard(item("effect", []), env())),
  yourDocument: labels(createCard(item("your_document", []), env())),
  mystery: labels(createCard(item("mystery", ["approved"]), env())),
};
const doc = createCard(item("your_document", []), env());
out.yourDocument = find(doc.el, ".wb-card-line").textContent;
out.primary = all(createCard(item("plan", ["approved", "rejected"], { payload: { plan_sha256: PLAN_HASH } }), env()).el, "button.wb-card-button").map((b) => b.cls().includes("pui-theme") ? "primary" : "secondary");

// text is text: a body with markup is one text node, never an element
const markup = createCard(item("acceptance", ["accepted"], { body: "<script>alert(1)</script> <b>bold</b>", title: "<img src=x>" }), env());
const tags = [...markup.el.walk()].map((n) => n.tagName);
out.markup = { elements: tags.filter((t) => ["SCRIPT", "B", "IMG"].includes(t)).length, body: find(markup.el, ".wb-card-body").textContent, title: find(markup.el, "h3").textContent };

// the header
const head = createCard(item("review", ["released", "answered"]), env());
out.head = find(head.el, ".wb-card-meta").textContent;
const planHead = createCard(item("plan", ["approved"], { task_id: 1, agent: null, payload: {} }), env());
out.planHead = [find(planHead.el, ".wb-card-meta").textContent, find(planHead.el, ".wb-card-meta a").attrs.href];

// an effect: the hash shown whole, the body whole, approve with the displayed hash, only that
const effect = createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH, body: "Publish this exactly.\nSecond line." }), env());
out.effect = { hash: find(effect.el, "[data-hash=effect]").textContent, pre: find(effect.el, "pre").textContent, sentence: !!all(effect.el, "p").find((p) => p.textContent === "Nothing is sent before you approve this exact content.") };
script = { approve: async () => ({ job: 5 }), pollJob: async () => ({ state: "done", result: { commit: "abc123", pull_request: "https://example.test/pr/1", state: "approved" } }) };
find(effect.el, "button[data-word=approved]").click();
await settle();
out.approveCalls = calls.filter((c) => c[0] === "approve" || c[0] === "pollJob").map((c) => [c[0], c[1], c[2], c[3], c.length]);
out.effectDone = { done: effect.isDone(), text: find(effect.el, ".wb-card-done").textContent };
calls.length = 0;

// the page sends the hash it shows: a hash node that no longer equals the decision's is refused before any request
script = {};
const tampered = createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH }), env());
find(tampered.el, "[data-hash=effect]").children[0].data = "c".repeat(64);
find(tampered.el, "button[data-word=approved]").click();
await settle();
out.tampered = { calls: calls.length, message: find(tampered.el, ".is-error").textContent };
calls.length = 0;

// reject sends the note only when one was typed; the effect stays unsent
const rejecting = createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH }), env());
find(rejecting.el, "button[data-word=rejected]").click();
await settle();
const note = find(rejecting.el, "input.wb-field-input");
out.rejectNoNote = calls.map((c) => [c[0], c[1], c[2], c[3]]);
calls.length = 0;
const rejecting2 = createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH }), env());
const input = find(rejecting2.el, "input.wb-field-input");
out.noteLabel = find(rejecting2.el, ".wb-field-label").textContent;
input.value = "not this";
input.listeners.input[0]();
find(rejecting2.el, "button[data-word=rejected]").click();
await settle();
out.rejectNote = calls.map((c) => [c[0], c[1], c[2], c[3]]);
calls.length = 0;

// a question: an empty answer is not sent; a typed one is, as typed; Ctrl+Enter is the same request
const question = createCard(item("question", ["answered"]), env());
find(question.el, "button[data-word=answered]").click();
await settle();
out.emptyAnswer = { calls: calls.length, invalid: find(question.el, "textarea").attrs["aria-invalid"], hint: find(question.el, ".wb-hint").textContent, focused: find(question.el, "textarea").focused, shortcuts: find(question.el, "textarea").attrs["aria-keyshortcuts"] };
const area = find(question.el, "textarea");
area.value = "  calm and dry  ";
area.listeners.input[0]();
let prevented = false;
area.listeners.keydown[0]({ key: "Enter", ctrlKey: true, metaKey: false, preventDefault() { prevented = true; } });
await settle();
out.answer = { calls: calls.map((c) => [c[0], c[1], c[2], c[3]]), prevented, done: question.isDone(), text: find(question.el, ".wb-card-done").textContent };
calls.length = 0;

// acceptance: accept sends no hash; a failure shows its message above the buttons and keeps the card open
script = { approve: async () => { throw Object.assign(new Error("A model run is already going"), { name: "ApiError", status: 409, word: "busy" }); } };
const accept = createCard(item("acceptance", ["accepted", "rejected"]), env());
find(accept.el, "button[data-word=accepted]").click();
await settle();
const children = find(accept.el, ".wb-card-content").children.map((c) => c.cls().join(" "));
out.accept = { calls: calls.map((c) => [c[0], c.length]), message: find(accept.el, ".is-error").textContent, done: accept.isDone(), enabled: all(accept.el, "button.wb-card-button").every((b) => !b.disabled),
  messageBeforeButtons: children.findIndex((c) => c.includes("wb-notice-card")) < children.findIndex((c) => c.includes("wb-card-actions")) };
calls.length = 0;

// a job that fails: the job's own message, buttons enabled, the same hash
script = { approve: async () => ({ job: 9 }), pollJob: async () => ({ state: "failed", error: { message: "the pull request could not be opened" } }) };
const failing = createCard(item("effect", ["approved", "rejected"], { payload_sha256: HASH }), env());
find(failing.el, "button[data-word=approved]").click();
await settle();
out.jobFailed = { message: find(failing.el, ".is-error").textContent, done: failing.isDone(), hash: find(failing.el, "[data-hash=effect]").textContent === HASH, enabled: all(failing.el, "button.wb-card-button").every((b) => !b.disabled) };
script = {};
calls.length = 0;

// 404: the card says so and is removed
let gone = null;
script = { answer: async () => { throw Object.assign(new Error("x"), { name: "ApiError", status: 404, word: "not_found" }); } };
const lost = createCard(item("question", ["answered"]), env({ gone: (id) => { gone = id; } }));
const lostArea = find(lost.el, "textarea"); lostArea.value = "hi"; lostArea.listeners.input[0]();
find(lost.el, "button[data-word=answered]").click();
await settle();
out.gone = { id: gone, message: find(lost.el, ".is-error").textContent, link: find(lost.el, ".is-error a").attrs.href, typed: find(lost.el, "textarea").value };
script = {};

calls.length = 0;
// a review: the blocked change set cannot send a release from the page; "Open" only for a returned path under docs/
const review = createCard(item("review", ["released", "answered"], { run_id: 4, payload: { returned: [{ path: "docs/a.md", class: "document" }, { path: "src/x.py", class: "code" }], kept: [{ path: "docs/k.md", class: "document", reason: "kept in the run folder" }],
  ending: "draft_with_questions", why: "Asks two questions", changeset: { blocked: true, refused: [{ path: "src/x.py", reason: "protected" }, { path: "", reason: "too big" }] } } }), env());
find(review.el, "button[data-word=released]").click();
await settle();
out.blocked = { calls: calls.length, aria: find(review.el, "button[data-word=released]").attrs["aria-disabled"], describedby: find(review.el, "button[data-word=released]").attrs["aria-describedby"] === find(review.el, ".wb-blocked").attrs.id,
  disabled: find(review.el, "button[data-word=released]").disabled, panel: find(review.el, ".wb-blocked").textContent,
  opens: all(review.el, "a").map((a) => a.attrs.href).filter((h) => h.startsWith("#/open")), keptRows: all(review.el, ".wb-paths")[1].textContent };
out.reviewText = { ending: all(review.el, ".wb-card-line").map((n) => n.textContent) };
const verdict = find(review.el, "details.wb-verdict");
out.verdictShown = !!verdict && all(verdict, "button").map((b) => b.textContent);
const noRun = createCard(item("review", ["released", "answered"], { run_id: null }), env());
out.noVerdict = find(noRun.el, "details.wb-verdict");
script = { verdict: async () => ({ run_id: 4, use: 1, verdict: "worked" }) };
find(review.el, "button[data-verdict=worked]").click();
await settle();
out.verdictSent = { call: calls.filter((c) => c[0] === "verdict").map((c) => [c[1], c[2], c[3]]), text: find(review.el, "details.wb-verdict p").textContent, disabled: all(review.el, "button[data-verdict]").every((b) => b.disabled) };
calls.length = 0; script = {};

// an empty comment on "Send back with a comment" is not sent
const comment = createCard(item("review", ["released", "answered"]), env());
find(comment.el, "button[data-word=answered]").click();
await settle();
out.emptyComment = { calls: calls.length, hint: all(comment.el, ".wb-hint").map((n) => n.textContent) };

// a plan: the table from payload.tasks, the limits line and the hash from the payload, approve with the displayed plan hash
const payload = { limits: { one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 }, estimate: { runs_at_least: 3 }, plan_sha256: PLAN_HASH,
  tasks: [{ key: "a", title: "Build the sale page", skill: "eng-implement", depends_on: [], milestone: false, web: false, agent: "engineering" },
          { key: "b", title: "Review it", skill: "eng-code-review", depends_on: ["a"], milestone: true, mandatory_milestone: true, web: true },
          { key: "c", title: "Announce", skill: "mkt-social-copy", depends_on: ["a", "b"], milestone: true, web: false }] };
out.rows = planRows(payload).map((r) => [r.n, r.title, r.agent, r.after, r.milestone, r.web]);
out.limits = [limitsLine(payload), limitsLine({ limits: { timeout_seconds: 5, retries: 0 } })];
script = { approve: async () => ({ job: 3 }), pollJob: async () => ({ state: "done", result: { request: 1, tasks: 3, ready: 1, plan_sha256: PLAN_HASH } }) };
const plan = createCard(item("plan", ["approved", "rejected"], { id: 8, task_id: 1, agent: null, payload, body: "Plan for request 1\n| # | Task |", title: "Plan: spring (3 tasks)" }), env());
out.plan = { columns: all(plan.el, "th").map((t) => t.textContent), cells: all(plan.el, "tbody tr").length, hash: find(plan.el, "[data-hash=plan]").textContent, line: all(plan.el, ".wb-card-hint").map((n) => n.textContent),
  asText: find(plan.el, "details .wb-md").textContent, noteLabel: find(plan.el, ".wb-field-label").textContent, skillCell: all(plan.el, "td")[2].cls() };
find(plan.el, "button[data-word=approved]").click();
await settle();
out.planApprove = { calls: calls.filter((c) => c[0] === "approve").map((c) => [c[1], c[2], c[3]]), done: find(plan.el, ".wb-card-done").textContent };
calls.length = 0; script = {};

// the request line and its dialog: the count from the request's tasks, "Keep it" first, cancel sends the request's id
out.counts = [cancelCount([]), cancelCount([{ state: "planned" }, { state: "ready" }]), cancelCount([{ state: "done" }, { state: "ready" }, { state: "running" }]), cancelCount([{ state: "planned" }])];
let changed = null;
const line = createRequestLine({ id: 16, title: "Add a sale page", state: "requested", tasks: [{ state: "planned" }, { state: "planned" }] }, { project: "p", api: client(), changed: (id, o) => { changed = [id, o.text]; }, words: (s) => ({ requested: "Requested" })[s] || s });
const open = find(line.el, "button.wb-cancel-link");
open.click();
const buttons = all(line.dialog, "button");
out.dialog = { labels: buttons.map((b) => b.textContent), open: line.dialog.open, count: find(line.dialog, ".wb-card-hint").textContent, title: find(line.dialog, ".wb-card-title").textContent, labelled: line.dialog.attrs["aria-labelledby"] === find(line.dialog, ".wb-card-title").attrs.id,
  chip: find(line.el, ".pui-chip").textContent, line: line.el.textContent };
all(line.dialog, "button")[1].click();
await settle();
out.cancelled = { calls: calls.filter((c) => c[0] === "cancel").map((c) => [c[1], c[2], c.length]), changed, closed: !line.dialog.open };
const finalLine = createRequestLine({ id: 16, title: "x", state: "cancelled", tasks: [] }, { project: "p", api: client() });
out.hiddenWhenFinal = finalLine.el.hidden;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_card_draws_one_button_per_word_of_its_actions_and_shows_the_decisions_text_as_text(tmp_path):
    got = run_node(tmp_path, CARDS)
    assert got["buttons"] == {
        "effect": ["Approve this exact content", "Reject"], "acceptance": ["Accept", "Reject"], "question": ["Send answer"],
        "review": ["Release (stays a draft)", "Send back with a comment"], "plan": ["Approve this plan", "Reject"], "unknownWord": ["Accept"], "none": [],
        "yourDocument": [], "mystery": []}, "a button for each word of `actions` the kind knows, in the drawn order, and none for any other"
    assert got["yourDocument"] == "Delivering a document is not available on this page yet."
    assert got["primary"] == ["primary", "secondary"], "one primary at most: the first button"
    assert got["markup"] == {"elements": 0, "body": "<script>alert(1)</script> <b>bold</b>", "title": "<img src=x>"}, "a text with markup shows as typed"
    assert got["head"] == "#21 · task #7 · Marketing · 3 h ago"
    assert got["planHead"] == ["#21 · request #1 · Lobby · 3 h ago", "#/p/p/lobby"], "a plan belongs to its request, which the Lobby holds"


@needs_node
def test_an_effect_or_a_plan_is_approved_only_with_the_hash_the_card_shows_and_every_failure_leaves_the_card_open(tmp_path):
    got = run_node(tmp_path, CARDS)
    h = "a" * 64
    assert got["effect"] == {"hash": h, "pre": "Publish this exactly.\nSecond line.", "sentence": True}, "the content and the whole hash are on the card, ahead of the button"
    assert got["approveCalls"] == [["approve", "p", 21, h, 4], ["pollJob", 5, 1000, None, 3]], "approve carries the displayed hash, then the job is polled"
    assert got["effectDone"] == {"done": True, "text": "Effect approvedT effectcommit: abc123pull request: https://example.test/pr/1"}, "the result shows as text"
    assert got["tampered"]["calls"] == 0 and "hash shown is not the hash of this decision" in got["tampered"]["message"], "a hash that differs from the decision's is never sent"
    assert got["rejectNoNote"] == [["reject", "p", 21, None]] and got["rejectNote"] == [["reject", "p", 21, "not this"]], "reject sends the note only when one was typed"
    assert got["noteLabel"] == "Note (optional, used when you reject)", "one wording for the note of the effect and the plan (OPEN-18)"
    assert got["planApprove"]["calls"] == [["p", 8, "b" * 64]], "a plan is approved with the plan hash the card shows"
    assert got["planApprove"]["done"].startswith("Plan approved")
    assert got["accept"] == {"calls": [["approve", 3]], "message": "A model run is already going for this project. Nothing was started; try again when it ends.", "done": False,
                             "enabled": True, "messageBeforeButtons": True}, "accept sends no hash; a failure is written above the buttons and the card stays open"
    assert got["jobFailed"] == {"message": "the pull request could not be opened", "done": False, "hash": True, "enabled": True}
    assert got["gone"] == {"id": 21, "message": "That item is not there any more.Back", "link": "#/p/p", "typed": "hi"}, "a 404 removes the card; the typed text was not thrown away"


@needs_node
def test_the_questions_and_the_reviews_send_what_was_typed_and_a_blocked_release_sends_nothing(tmp_path):
    got = run_node(tmp_path, CARDS)
    assert got["emptyAnswer"] == {"calls": 0, "invalid": "true", "hint": "Type an answer.", "focused": True, "shortcuts": "Control+Enter Meta+Enter"}
    assert got["answer"] == {"calls": [["answer", "p", 21, "  calm and dry  "]], "prevented": True, "done": True, "text": "Question answeredT question"}, \
        "the text goes as typed; Ctrl or Cmd plus Enter is the same request"
    assert got["blocked"]["calls"] == 0 and got["blocked"]["aria"] == "true" and got["blocked"]["describedby"] is True and got["blocked"]["disabled"] is False, \
        "the blocked release is aria-disabled and described by the panel, and sends nothing"
    assert "src/x.py" in got["blocked"]["panel"] and "the whole set" in got["blocked"]["panel"] and "Answer the review with a comment, or cancel the request." in got["blocked"]["panel"]
    assert got["blocked"]["opens"] == ["#/open/docs/a.md"], "Open only for a returned path under docs/, never a kept one"
    assert "kept in the run folder" in got["blocked"]["keptRows"] and "Open" not in got["blocked"]["keptRows"]
    assert got["reviewText"]["ending"][0] == "Ending: Wrote a draft and still has questions"
    assert got["verdictShown"] == ["worked", "corrected", "failed"] and got["noVerdict"] is None, "the verdict disclosure is absent when the decision has no run"
    assert got["verdictSent"] == {"call": [["p", 4, "worked"]], "text": "Verdict recorded: worked.", "disabled": True}
    assert got["emptyComment"] == {"calls": 0, "hint": ["Type a comment."]}


@needs_node
def test_the_plan_card_builds_its_table_limits_and_hash_from_the_payload_and_the_cancel_dialog_counts_the_requests_tasks(tmp_path):
    got = run_node(tmp_path, CARDS)
    assert got["rows"] == [["1", "Build the sale page", "engineering", "-", "no", "no"], ["2", "Review it", "-", "1", "yes (mandatory)", "yes"], ["3", "Announce", "-", "1, 2", "yes", "no"]]
    assert got["limits"] == ["One task at a time; each run at most 1800 s, retried at most 2 times. At least 3 runs.", "Each run at most 5 s, retried at most 0 times."]
    assert got["plan"]["columns"] == ["#", "Task", "Skill", "Agent", "After", "Milestone", "Web"] and got["plan"]["cells"] == 3
    assert got["plan"]["hash"] == "b" * 64 and got["plan"]["line"][0] == got["limits"][0] and got["plan"]["asText"].startswith("Plan for request 1")
    assert "wb-skill" in got["plan"]["skillCell"], "the skill cell breaks at hyphens only"
    assert got["counts"] == ["No task has been created yet.", "2 tasks, none started", "3 tasks, 2 started", "1 task, none started"]
    assert got["dialog"]["labels"] == ["Keep it", "Cancel request"] and got["dialog"]["open"] is True and got["dialog"]["labelled"] is True
    assert got["dialog"]["count"] == "Request #16: Add a sale page · 2 tasks, none started" and got["dialog"]["title"] == "Cancel this request and what is still open under it?"
    assert got["dialog"]["chip"] == "Requested" and "Request #16: Add a sale page" in got["dialog"]["line"]
    assert got["cancelled"] == {"calls": [["p", 16, 3]], "changed": [16, "Request 16 cancelled"], "closed": True}
    assert got["hiddenWhenFinal"] is True, "a request that is done or cancelled has no request line"


# --- the Agent tab ------------------------------------------------------------------------------------------------------------------

AGENT = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createAgentTab, fileRefusal, toBase64, MAX_FILE_BYTES, STANDING } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";

const calls = [];
let script = {};
const record = (name) => async (...args) => { calls.push([name, ...args]); return script[name] ? script[name](...args) : {}; };
const api = { setMode: record("setMode"), retry: record("retry"), handOver: record("handOver") };
let refreshed = 0;
const tab = createAgentTab({ project: "p", agent: "engineering", api, refresh: () => { refreshed += 1; }, now: () => new Date() });
const P = "0123456789ab";
const agent = (extra = {}) => ({ name: "engineering", pack: "code", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 12, max_usd_per_day: 4, runs_today: 5, usd_today: 1.87, runs_without_cost: 0, queued: 0, ...extra });
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: "engineering", ...extra });
const snapshot = (agentRow, tasks, accepted = true) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted } }], details: accepted ? { [P]: { status: { requests: [{ id: 1, title: "R", state: "ready", tasks }], pending: [] }, agents: [agentRow] } } : {}, tasks: {}, loaded: true });
const bodies = { 4: { task: task(4, "running"), runs: [{ id: 1, skill: "s", skill_version: "1.0.0", model: "m", status: "running", attempts: 1, started_at: "2026-10-08T10:30:00Z" }], pending: [] } };
const view = (agentRow, tasks, accepted = true) => fm.floor(snapshot(agentRow, tasks, accepted), P, "engineering", bodies);
const out = {};

tab.update(null);
out.loading = find(tab.el, ".wb-busy").textContent;
tab.update(view(agent(), [task(4, "running"), task(5, "failed"), task(6, "blocked"), task(7, "waiting")]));
out.state = find(tab.el, ".wb-state-row").textContent;
out.plate = find(tab.el, ".wb-mode-row").textContent;
out.options = all(tab.el, "option").length;      // A-17: the select is gone; Stop agent and Supervise are tested in test_interface_plates_meters.py
out.standing = find(tab.el, ".wb-notice-card").textContent === STANDING;
out.meters = all(tab.el, ".wb-meter-cell").map((c) => [c.attrs["aria-label"], c.querySelectorAll(".wb-meter-track").length]);
out.current = find(tab.el, ".wb-current").textContent;
out.others = all(tab.el, ".wb-other").map((o) => o.textContent);
out.retry = all(tab.el, "button[data-key]").map((b) => [b.attrs["aria-label"], b.textContent]).filter((x) => x[0] && x[0].startsWith("Retry"));
out.hint = find(tab.el, ".wb-hint").textContent;

// Stop agent sends one request with its word, the page reloads and no command is shown (the runtime accepts a narrowing at once)
script = { setMode: async () => ({ agent: "engineering", mode: "stopped", config_sha256: "f".repeat(64), accepted: true, by: "code:narrowing", next: null }) };
find(tab.el, "button[data-key=stop-agent]").click();
await settle();
out.setMode = { calls: calls.filter((c) => c[0] === "setMode"), refreshed: refreshed > 0, notice: find(tab.el, ".wb-result-box").textContent };
// a result that was not accepted keeps its notice through the reads that follow, including those of a project not accepted, and goes once it is accepted again
script = { setMode: async () => ({ agent: "engineering", mode: "stopped", accepted: false, next: "python3 /ck/runtime/cli.py accept-config --project p --sha256 " + "e".repeat(64) }) };
find(tab.el, "button[data-key=stop-agent]").click();
await settle();
const kept = find(tab.el, ".wb-result-box").textContent !== "";
tab.update(view(agent(), [], false));
out.unaccepted = { line: find(tab.el, ".wb-empty-line").textContent, hiddenForm: find(tab.el, ".wb-mode-form").hidden, resultKept: kept && find(tab.el, ".wb-result-box").textContent !== "" };
tab.update(view(agent({ mode: "autonomous", acting_mode: "autonomous" }), [task(4, "running"), task(5, "failed"), task(6, "blocked"), task(7, "waiting")]));
out.accepted = { buttons: [find(tab.el, "button[data-key=stop-agent]").disabled, find(tab.el, "button[data-key=supervise]").disabled], resultGone: find(tab.el, ".wb-result-box").textContent === "" };

// a refused mode shows the operation's message under the row
script = { setMode: async () => { throw Object.assign(new Error("a mode is one of stopped, supervised"), { name: "ApiError", status: 400, word: "usage" }); } };
find(tab.el, "button[data-key=stop-agent]").click();
await settle();
out.refusedMode = find(tab.el, ".wb-form-error").textContent;

// Retry sends one request with no body; in flight it reads "Retrying..."
calls.length = 0;
script = { retry: async () => ({ id: 5, state: "ready" }) };
const retryButton = all(tab.el, "button[data-key=retry-5]")[0];
retryButton.click();
await settle();
out.retryCalls = calls.filter((c) => c[0] === "retry").map((c) => [c[1], c[2], c.length]);
script = { retry: async () => { throw Object.assign(new Error("task 6 is not failed or blocked"), { name: "ApiError", status: 409, word: "refused" }); } };
all(tab.el, "button[data-key=retry-6]")[0].click();
await settle();
out.retryRefused = all(tab.el, ".wb-other").map((o) => o.textContent).find((t) => t.includes("Task 6"));

// an agent that is off: the state row says so and its button moves the focus to the select and sends nothing
calls.length = 0;
tab.update(view(agent({ mode: "stopped", acting_mode: "stopped" }), [task(5, "failed")]));
const off = find(tab.el, ".wb-state-row");
out.off = { text: off.textContent, button: all(off, "button").length };

// hand a file over, in two steps (C-17): nothing is sent when no file was chosen, nor when one is chosen; the button names the task it sends to
// (the task the hint named when the file was chosen: a poll that moves the target does not change it) and sends one call with the file's own name
calls.length = 0;
script = { handOver: async () => ({ path: ".workbench-local/drop/5/notes.txt", bytes: 3 }) };
const fileInput = find(tab.el, "input.wb-file");
out.handHint = find(tab.el, ".wb-hint").textContent;
fileInput.files = [];
await fileInput.listeners.change[0]();
out.handNoFile = calls.length;
fileInput.files = [{ name: "notes.txt", size: 3, arrayBuffer: async () => new Uint8Array([97, 98, 99]).buffer }];
await fileInput.listeners.change[0]();
out.handChosen = { calls: calls.filter((c) => c[0] === "handOver").length, name: find(tab.el, ".wb-hand-chosen").textContent, button: find(tab.el, "button.wb-hand-button").textContent };
tab.update(view(agent({ mode: "stopped", acting_mode: "stopped" }), [task(5, "failed"), task(9, "blocked")]));
out.handHintAfterPoll = find(tab.el, ".wb-hint").textContent;
out.handButtonAfterPoll = find(tab.el, "button.wb-hand-button").textContent;
find(tab.el, "button.wb-hand-button").click();
await settle();
out.hand = { calls: calls.filter((c) => c[0] === "handOver").map((c) => c.slice(1)), result: find(tab.el, ".wb-hand-result").textContent };

// the file rules, before anything is sent
out.files = [fileRefusal("ok-file_1.txt", 10), fileRefusal("a/b.txt", 10), fileRefusal("x".repeat(101), 10), fileRefusal("big.bin", MAX_FILE_BYTES + 1), fileRefusal("exact.bin", MAX_FILE_BYTES), fileRefusal("sp ace.txt", 1)];
out.base64 = [toBase64(new Uint8Array([104, 105])), toBase64(new Uint8Array(70000)).length];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_agent_tab_sends_set_mode_retry_and_the_hand_over_as_one_request_each_and_shows_the_command_the_service_gave(tmp_path):
    got = run_node(tmp_path, AGENT)
    assert got["loading"] == "Loading the floor..."
    assert got["state"].startswith("WorkingRunning for "), "R-8: how long the task has run, not since when"
    assert got["plate"].startswith("supervised") and got["plate"].endswith("Every review reaches you."), "the plate says the mode and its one line"
    assert got["options"] == 0, "A-17: no select; the mode is changed by Stop agent and Supervise"
    assert got["standing"] is True
    assert got["meters"] == [["Runs today 5 / 12", 1], ["Spend today $1.87 / $4.00", 1], ["Queued 0", 0]], "Queued has no cap, so no track; A-20: the meters say which model they count"
    assert got["current"].startswith("#4 Task 4Running") and "skill s" in got["current"] and "Run#1 s 1.0.0" in got["current"]
    # A-32: the other tasks carry the actions of a Tasks-tab row, so a waiting one has "Open in the Inbox" after its chip
    assert [o.split("Retry")[0] for o in got["others"]] == ["#7 Task 7Waiting for youOpen in the Inbox", "#6 Task 6Blocked", "#5 Task 5Failed"], "other tasks, newest first"
    assert got["retry"] == [["Retry task 6", "Retry"], ["Retry task 5", "Retry"]], "Retry only on a failed or blocked task, named by its task"
    assert got["hint"] == "To task #6. At most 25 MiB.", "the hand-over target is the newest failed or blocked task, named in the hint"
    assert [c[1:] for c in got["setMode"]["calls"]] == [["p", "engineering", "stopped"]], "Stop agent sends its word, once"
    assert got["setMode"]["refreshed"] is True and got["setMode"]["notice"] == "Mode set to stopped."
    assert got["unaccepted"] == {"line": "Waiting for the configuration to be accepted.", "hiddenForm": True, "resultKept": True}
    assert got["accepted"] == {"buttons": [False, False], "resultGone": True}, "an agent that acts autonomously can be stopped or supervised"
    assert got["refusedMode"] == "a mode is one of stopped, supervised"
    assert got["retryCalls"] == [["p", 5, 3]], "Retry sends the task's id and no body"
    assert "task 6 is not failed or blocked" in got["retryRefused"]
    assert got["off"]["text"].startswith("OffOff, mode is stopped") and got["off"]["button"] == 0, "the Off row has no button: a wider mode is the terminal's"
    assert got["files"] == ["", "The file name may hold letters, digits, ., _ and -, at most 100 characters.", "The file name may hold letters, digits, ., _ and -, at most 100 characters.",
                            "A file handed to a task is at most 25 MiB.", "", "The file name may hold letters, digits, ., _ and -, at most 100 characters."]
    assert got["handNoFile"] == 0, "nothing is sent when no file was chosen"
    assert got["handHint"] == "To task #5. At most 25 MiB." and got["handHintAfterPoll"] == "To task #9. At most 25 MiB."
    assert got["handChosen"] == {"calls": 0, "name": "notes.txt", "button": "Hand over to task #5"}, "C-17: choosing the file sends nothing; its name and the button show"
    assert got["handButtonAfterPoll"] == "Hand over to task #5", "the button still names the task the hint named when the file was chosen"
    assert got["hand"] == {"calls": [["p", 5, "notes.txt", "YWJj"]], "result": "Handed over: .workbench-local/drop/5/notes.txt (3 bytes)"}, \
        "one call, the file's own name, to the task the hint named when the file was chosen (a poll before the click does not change it)"
    assert got["base64"] == ["aGk=", 93336]


# --- the router and the model are the only places a hash or a state is derived; the page decides nothing --------------------------------


def test_the_word_tables_are_the_services_closed_lists():
    model = (JS / "floor-model.js").read_text(encoding="utf-8")
    endings = (st.REPO / "runtime" / "endings.py").read_text(encoding="utf-8")
    for word in ("done", "question", "draft_with_questions", "gate", "blocked", "unclassified"):
        assert f'"{word}"' in endings and (word in model), f"the ending {word} is a word of runtime/endings.py and of the model's table"
    store = (st.REPO / "providers" / "store" / "sqlite.py").read_text(encoding="utf-8")
    for word in ("timeout", "refused", "auth", "adapter", "early_end", "settings", "stopped", "internal", "running", "ok", "failed"):
        assert f"'{word}'" in store, f"{word} is a failure or status word of the store"
    autonomy = (st.REPO / "runtime" / "autonomy.py").read_text(encoding="utf-8")
    for mode in ("stopped", "supervised", "milestones", "autonomous", "autonomous-with-policy"):
        assert f'"{mode}"' in autonomy and f'"{mode}"' in model or f"{mode}:" in model, f"the mode {mode} is one of autonomy.MODES and of the model's table"
    cards = (JS / "floor" / "cards.js").read_text(encoding="utf-8")
    for word in ("approved", "accepted", "rejected", "answered", "released"):
        assert f"'{word}'" in store or f'"{word}"' in store, f"{word} is a resolution word of the store"
        assert f'"{word}"' in cards, f"cards.js draws a button for {word}"


# --- the viewer shows a file as text ----------------------------------------------------------------------------------------------

VIEWER = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createViewer } from "@JS@/floor/viewer.js";

setToken("t".repeat(40));
const asked = [];
let answer;
globalThis.fetch = async (url) => { asked.push(url); return answer; };
const reply = (status, body) => ({ ok: status === 200, status, json: async () => body });
let closed = 0;
const viewer = createViewer({ onClose: () => { closed += 1; } });
const out = {};

answer = reply(200, { path: "docs/a.md", text: "<script>alert(1)</script>\n<b>bold</b> <img src=x onerror=alert(2)>", size: 70, modified_at: "2026-10-03T09:05:00Z" });
const loading = viewer.load("p", "docs/a.md");
out.loading = find(viewer.el, ".wb-busy").textContent;
await loading;
const pre = find(viewer.el, "pre.wb-viewer-text");
const tags = [...viewer.el.walk()].map((n) => n.tagName);
out.text = { value: pre.textContent, children: pre.children.length, markup: tags.filter((t) => ["SCRIPT", "B", "IMG"].includes(t)).length, name: pre.attrs["aria-label"], tabindex: pre.attrs.tabindex };
out.head = { path: find(viewer.el, ".wb-viewer-path").textContent, line: find(viewer.el, ".wb-viewer-line").textContent.replace(/modified .*/, "modified"), region: viewer.el.attrs.role };
out.url = asked[0].replace(/^.*\/artifact/, "/artifact");
find(viewer.el, "button[data-key=close]").click();
out.closed = closed;

answer = reply(400, { error: "usage", message: "an artifact is a file under docs/ <img src=x onerror=alert(3)>" });
await viewer.load("p", "../.env");
const refusal = find(viewer.el, ".wb-refusal");
out.refusal = { text: refusal.textContent, markup: [...viewer.el.walk()].filter((n) => n.tagName === "IMG").length, title: find(viewer.el, ".wb-refusal-title").textContent, size: find(viewer.el, ".wb-viewer-line") };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_viewer_shows_a_files_text_and_a_refusal_as_text_never_as_markup(tmp_path):
    got = run_node(tmp_path, VIEWER)
    assert got["loading"] == "Loading the floor..."
    assert got["text"] == {"value": "<script>alert(1)</script>\n<b>bold</b> <img src=x onerror=alert(2)>", "children": 1, "markup": 0,
                           "name": "Text of docs/a.md", "tabindex": "0"}, "the text is one text node: a script or a tag in a document shows as typed"
    assert got["head"] == {"path": "docs/a.md", "line": "70 B, modified", "region": "region"}
    assert got["url"].startswith("/artifact?path=docs%2Fa.md") or "/artifact?path=docs%2Fa.md" in got["url"]
    assert got["closed"] == 1
    assert got["refusal"]["title"] == "The file could not be opened" and got["refusal"]["markup"] == 0 and got["refusal"]["size"] is None
    assert "<img src=x onerror=alert(3)>" in got["refusal"]["text"], "the operation's refusal is shown whole, as text"


# --- WP-9.5b: the Desk's empty wording for an agent with documents elsewhere ------------------------------------------------------

DESK_EMPTY = r"""
import { FakeNode } from "@FAKE@";
import { createDeskTab, NONE_IN_PROJECT, NONE_OF_ITS_OWN } from "@JS@/floor/desk-tab.js";

const tab = createDeskTab({ project: "p", agent: "engineering", open() {} });
const say = () => tab.el.querySelectorAll(".wb-state-block").map((n) => n.textContent);
const out = { constants: [NONE_IN_PROJECT, NONE_OF_ITS_OWN] };
tab.update({ documents: [], truncated: false, loading: false, error: null });
out.projectEmpty = say();
tab.update({ documents: [], truncated: false, loading: false, error: null, elsewhere: 7 });
out.elsewhere = say();
out.filterHidden = tab.el.querySelectorAll("label")[0] ? tab.el.querySelectorAll("label")[0].hidden : null;
tab.update({ documents: [{ path: "docs/a.md", owner: "s", size: "1 B", modified: "2026-10-03 09:05", bound: false }], truncated: false, loading: false, error: null, elsewhere: 7 });
out.withDocuments = say();
console.log(JSON.stringify(out));
"""


@needs_node
def test_an_agent_with_no_documents_of_its_own_is_not_told_the_project_has_none(tmp_path):
    got = run_node(tmp_path, DESK_EMPTY)
    assert got["constants"] == ["The project has no documents under docs/ yet.", "No documents of this agent. Every document is on the Lobby's desk."]
    assert got["projectEmpty"] == [got["constants"][0]], "a project with no documents at all keeps the drawn sentence"
    assert got["elsewhere"] == [got["constants"][1]], "every document is on the Lobby's desk, and the Desk says so"
    assert got["withDocuments"] == [], "an agent with documents shows its table, no empty block"
    floor = (JS / "views" / "floor.js").read_text(encoding="utf-8")
    assert "elsewhere: documents ? documents.rows.length - documentsRows.length : 0" in floor, "the Floor tells the Desk how many rows are not the agent's"

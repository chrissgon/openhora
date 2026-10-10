"""Tests of the page side of the adjustments A-22 to A-26 and A-29 to A-33 (ADJ-I2): what the cards, the tabs, the composer, the viewer and
the City show and send for the fields the runtime added (waits, `after`, `go_ahead`, `queued`, held commands, `kept`, the drop line, the raw
artifact, `kind`), and the file rules that keep the page's text out of markup. No browser, no model and no service: the modules run under Node with
a fake document and a stand-in for `fetch`. The served page was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_adjustments.py
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import standin_tree as st
from test_interface_floor import FAKE_DOM, INTERFACE, needs_node, NODE
from test_interface_lobby import FAKE_EXTRA as LOBBY_EXTRA
from interface_css import stylesheets

# The Floor's fake document, with what the Lobby's modules use added (insertBefore and the like); its own predicate `find` is `where` here.
FAKE_EXTRA = (LOBBY_EXTRA + """
Object.defineProperty(FakeNode.prototype, "dataset", { get() { return this._dataset || (this._dataset = {}); } });
""").replace("export const find =", "export const where =").replace("=> find(root, (n)", "=> where(root, (n)")

JS = INTERFACE / "js"
CSS = stylesheets()
service = st.load("service")


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM + FAKE_EXTRA, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- A-29: what a task waits for -----------------------------------------------------------------------------------------------------

WAITS = r"""
import * as w from "@JS@/waits.js";
import * as tm from "@JS@/floor/tasks-model.js";
import * as fm from "@JS@/floor-model.js";
import * as model from "@JS@/model.js";
import { chipNodes } from "@JS@/scene/plates.js";
import { FakeNode, all, find } from "@FAKE@";

const input = { task_id: 10, request_id: 3, reason: "docs/brand/identity.md, written by task #10" };
const input2 = { task_id: 12, request_id: 4, reason: "docs/brand/voice.md, written by task #12" };
const after = { task_id: null, request_id: 3, reason: "after request #3" };
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "design-system", state, note: null, agent: "design", requestId: 2, waiting_for: [], ...extra });
const out = {};
out.label = [w.waitingLabel(task(5, "planned", { waiting_for: [input] })), w.waitingLabel(task(5, "planned", { waiting_for: [input, input2, after] })), w.waitingLabel(task(5, "planned")), w.waitingLabel({})];
out.lines = w.waitLines(task(5, "planned", { waiting_for: [input, after] }));
out.kinds = [w.waitKinds(task(5, "planned", { waiting_for: [input] })), w.waitKinds(task(5, "planned", { waiting_for: [after] })), w.waitKinds(task(5, "planned", { waiting_for: [input, after] })), w.waitKinds(task(5, "planned"))];
out.junk = w.waitsOf({ waiting_for: [null, "x", { reason: "" }, { task_id: 1 }, input] }).length;
// the actions a state allows: one source for both tabs
const pending = [{ id: 40, task_id: 9 }];
const kinds = (t) => tm.actionsFor(t, pending).map((a) => a.kind);
out.actions = {
  planned: kinds(task(5, "planned")), waitsInput: kinds(task(5, "planned", { waiting_for: [input] })), waitsAfter: kinds(task(5, "planned", { waiting_for: [after] })),
  waitsBoth: kinds(task(5, "planned", { waiting_for: [input, after] })), ready: kinds(task(5, "ready", { waiting_for: [input] })), running: kinds(task(5, "running", { waiting_for: [input] })),
  blocked: kinds(task(5, "blocked")), failed: kinds(task(5, "failed")), waiting: kinds(task(9, "waiting")), done: kinds(task(5, "done")),
};
out.blockedNote = [tm.blockedNote(task(5, "blocked", { note: "  design-system needs docs/brand/identity.md  " })), tm.blockedNote(task(5, "failed", { note: "x" })), tm.blockedNote(task(5, "blocked"))];
const row = tm.rowOf(task(5, "planned", { waiting_for: [input] }), { requests: [], pending: [], body: null, now: new Date("2026-10-09T12:00:00Z") });
out.row = { waiting: row.waiting, waits: row.waits, actions: row.actions };

// the plate: the waiting tasks are counted under "left" and one chip says what they wait for
const P = "0123456789ab";
const agents = [{ name: "design", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0 }];
const status = (tasks) => ({ requests: [{ id: 2, title: "Design", state: "planned", tasks }], pending: [], documents: [] });
const snapshot = (tasks) => ({ projects: [{ id: P, name: "shop", config: { accepted: true } }], details: { [P]: { status: status(tasks), agents } }, tasks: {}, loaded: true });
const one = fm.building(snapshot([task(5, "planned", { waiting_for: [input] }), task(6, "planned"), task(7, "done")]), P).rows.find((r) => r.name === "design");
out.plate = { left: one.left, done: one.done, waits: one.waits, counts: one.counts, chips: all(new FakeNode("div"), "span").length };
const nodes = chipNodes(fm.plateOf(one));
out.chips = nodes.map((n) => [n.textContent, n.attrs.title || null]);
const two = fm.building(snapshot([task(5, "planned", { waiting_for: [input] }), task(6, "planned", { waiting_for: [after] })]), P).rows.find((r) => r.name === "design");
out.twoWaits = two.waits;
const none = fm.building(snapshot([task(5, "planned"), task(6, "ready")]), P).rows.find((r) => r.name === "design");
out.none = [none.waits, chipNodes(fm.plateOf(none)).map((n) => n.textContent)];
// the tracking bar: the step says what it waits for
const tracking = model.tracking(snapshot([task(5, "planned", { waiting_for: [input, after] }), task(6, "planned")]), P, new Date("2026-10-09T12:00:00Z"));
out.steps = tracking.steps.map((s) => [s.sub, s.name, s.waits || null]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_task_that_waits_says_for_what_on_the_chips_the_bar_and_the_rows_and_has_the_go_ahead_its_state_allows(tmp_path):
    got = run_node(tmp_path, WAITS)
    assert got["label"] == ["waiting for #10", "waiting for #10, #12, request #3", "", ""]
    assert got["lines"] == ["waiting for #10: docs/brand/identity.md, written by task #10", "waiting for request #3"], "the person's own after reads once"
    assert got["kinds"] == [{"goAhead": True, "dropAfter": False}, {"goAhead": False, "dropAfter": True}, {"goAhead": True, "dropAfter": True}, {"goAhead": False, "dropAfter": False}]
    assert got["junk"] == 1, "an entry with no text reason is not a wait"
    actions = got["actions"]
    assert actions["planned"] == [] and actions["waitsInput"] == ["go-ahead"] and actions["waitsAfter"] == ["drop-after"] and actions["waitsBoth"] == ["go-ahead", "drop-after"]
    assert actions["ready"] == ["go-ahead"] and actions["running"] == [], "only a task that has not started can be told to go ahead"
    assert actions["blocked"] == ["retry"] and actions["failed"] == ["retry"] and actions["waiting"] == ["inbox"] and actions["done"] == []
    assert got["blockedNote"] == ["design-system needs docs/brand/identity.md", "", ""], "the sentence stands beside Retry for a blocked task only"
    assert got["row"] == {"waiting": "waiting for #10", "waits": ["waiting for #10: docs/brand/identity.md, written by task #10"], "actions": [{"kind": "go-ahead"}]}
    plate = got["plate"]
    assert plate["left"] == 2 and plate["done"] == 1, "a waiting task is a planned task: counted under left"
    assert plate["waits"] == {"text": "waiting for #10", "title": "task #5 waiting for #10: docs/brand/identity.md, written by task #10"}
    assert plate["counts"] == "1 done, 2 left, waiting for #10"
    assert got["chips"] == [["1 done", None], ["2 left", None], ["waiting for #10", "task #5 waiting for #10: docs/brand/identity.md, written by task #10"]]
    assert got["twoWaits"]["text"] == "2 waiting"
    assert got["none"][0] is None and not any("waiting" in chip for chip in got["none"][1]), "a floor whose tasks wait for nothing shows no waiting chip"
    assert got["steps"][0][0] == "Design · waiting for #10, request #3" and got["steps"][0][1].endswith("waiting for #10, request #3"), \
        "R-8: a step's line is its agent, and what it waits for when it waits: no state word (the icon carries the state)"
    assert got["steps"][1][2] is None


# --- A-29: the plan cards list the waits and send the go-ahead keys ------------------------------------------------------------------

PLAN = r"""
import { FakeNode, settle, find, all, click, where, byClass, textOf } from "@FAKE@";
import { createCard } from "@JS@/floor/cards.js";
import { createPlanCard } from "@JS@/cards/plan.js";
import * as waits from "@JS@/cards/plan-waits.js";

const PLAN_HASH = "b".repeat(64);
const calls = [];
const client = () => {
  const record = (name) => async (...args) => { calls.push([name, ...args]); return name === "approve" ? { job: "j1" } : name === "pollJob" ? { state: "done", result: {} } : {}; };
  return { answer: record("answer"), release: record("release"), approve: record("approve"), reject: record("reject"), cancel: record("cancel"), pollJob: record("pollJob") };
};
const tasks = [{ key: "brand", title: "Brand identity", skill: "brand-identity", agent: "brand" }, { key: "system", title: "Design system", skill: "design-system", agent: "design", depends_on: ["brand"] },
  { key: "voice", title: "Voice", skill: "brand-voice", agent: "brand" }, { key: "later", title: "Landing page", skill: "design-brief", agent: "design" }];
const payload = {
  tasks, limits: { one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 }, estimate: { runs_at_least: 4 }, plan_sha256: PLAN_HASH,
  waits: [{ task_key: "system", task_id: 10, reason: "docs/brand/identity.md, written by task #10" }, { task_key: "system", task_id: 12, reason: "docs/brand/voice.md, written by task #12" },
    { task_key: "later", task_id: null, reason: "after request #3" }],
  missing: [{ task_key: "voice", skill: "brand-voice", path: "docs/brand/profile.md", owner: "brand-profile", sentence: "brand-voice needs docs/brand/profile.md; nothing writes it: run brand-profile first or go ahead and it will stop" }],
  cycles: [{ task_key: "brand", sentence: "brand would wait in a circle" }],
};
const item = { id: 21, kind: "plan", title: "Plan <b>x</b>", body: "body", payload, payload_sha256: null, status: "open", actions: ["approved", "rejected"], agent: null, task_id: 7, run_id: null, created_at: "2026-10-09T09:00:00Z" };
const env = () => ({ project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client(), requestIds: new Set([7]), links: { floor: () => "#", lobby: () => "#/p/p/lobby", open: () => "#" }, reread: async () => null, changed() {}, gone() {} });
const out = {};

out.groups = waits.waitGroups(payload).map((g) => [g.key, g.title, g.reasons, g.derived, g.after]);
out.has = [waits.hasWaits(payload), waits.hasWaits({ tasks }), waits.hasWaits({ waits: [], missing: [], cycles: [] })];

// the Floor's plan card
const card = createCard(item, env());
const block = find(card.el, ".wb-waits");
out.floor = {
  block: Boolean(block), title: textOf(find(block, ".wb-waits-title")), boxes: all(block, "input").map((b) => b.attrs["data-key"]), labels: all(block, "label").map(textOf),
  reasons: all(block, ".wb-waits-reasons").map(textOf), items: all(block, ".wb-waits-item").map(textOf),
  missing: all(block, ".is-missing li").map(textOf), cycles: all(block, ".is-cycles li").map(textOf),
};
const box = (c, key) => all(c.el, "input").find((b) => b.attrs["data-key"] === `go-ahead-${key}`);
const approve = (c) => all(c.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "approved");
// nothing ticked: the plain approve with the hash and no list
approve(card).click();
await settle();
const first = calls.filter((c) => c[0] === "approve").map((c) => c.slice(1));
// a fresh card: tick the box of a task that waits for a task; the key travels with the hash
calls.length = 0;
const card2 = createCard({ ...item, id: 22 }, env());
const tick = box(card2, "system");
tick.checked = true;
tick.listeners.change.forEach((fn) => fn());
approve(card2).click();
await settle();
out.approveCalls = { plain: first, ticked: calls.filter((c) => c[0] === "approve").map((c) => c.slice(1)) };
out.boxAfter = box(card2, "system") ? box(card2, "system").checked : "done";
// a box for a wait on a request does not exist
out.noBoxFor = ["later", "voice", "brand"].map((k) => Boolean(box(createCard({ ...item, id: 23 }, env()), k)));

// a plan that waits for nothing has no block
const quiet = createCard({ ...item, id: 24, payload: { tasks, limits: {}, plan_sha256: PLAN_HASH } }, env());
out.quiet = find(quiet.el, ".wb-waits") === null;

// the Lobby's plan card: the same block, the same call
const lobbyCalls = [];
const api = { approve: async (...a) => { lobbyCalls.push(["approve", ...a]); return { job: "j" }; }, reject: async () => ({}), pollJob: async () => ({ state: "done" }) };
const lobby = createPlanCard({ api, project: "p1", item: { ...item, id: 25 }, now: new Date("2026-10-09T12:00:00Z"), onChanged: async () => {}, signal: undefined });
const lbox = all(lobby.el, "input").find((b) => b.attrs["data-key"] === "go-ahead-system");
out.lobby = { boxes: all(lobby.el, "input").map((b) => b.attrs["data-key"]).filter(Boolean), block: Boolean(find(lobby.el, ".wb-waits")), order: all(lobby.el, "*").map((n) => n.attrs.class || "").filter((c) => /wb-waits |wb-plan-hash-block|wb-card-note/.test(c + " ")).slice(0, 3) };
lbox.checked = true;
lbox.listeners.change.forEach((fn) => fn());
all(lobby.el, "button").find((b) => b.textContent === "Approve this plan").click();
await settle();
out.lobbyApprove = lobbyCalls;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_plan_card_lists_what_the_plan_waits_for_and_sends_the_go_ahead_keys_with_the_hash_it_shows(tmp_path):
    got = run_node(tmp_path, PLAN)
    assert got["groups"] == [["system", "Design system", ["docs/brand/identity.md, written by task #10", "docs/brand/voice.md, written by task #12"], True, False],
                             ["later", "Landing page", ["after request #3"], False, True]]
    assert got["has"] == [True, False, False]
    floor = got["floor"]
    assert floor["block"] and floor["title"] == "Before it starts"
    assert floor["boxes"] == ["go-ahead-system"], "a Go ahead box only for a task that waits for another task, never for the person's own After"
    assert floor["labels"] == ["Go ahead on Design system"]
    assert floor["reasons"][0] == "docs/brand/identity.md, written by task #10; docs/brand/voice.md, written by task #12" and floor["reasons"][1] == "after request #3"
    assert floor["missing"] == ["brand-voice needs docs/brand/profile.md; nothing writes it: run brand-profile first or go ahead and it will stop"], "a required input nothing writes is said before approval"
    assert floor["cycles"] == ["brand would wait in a circle"]
    hash_ = "b" * 64
    assert got["approveCalls"]["plain"] == [["p", 21, hash_]], "nothing ticked: the plain approve with the hash shown"
    assert got["approveCalls"]["ticked"] == [["p", 22, hash_, {"goAhead": ["system"]}]], "the key of the box ticked travels with the same hash"
    assert got["boxAfter"] == "done"
    assert got["noBoxFor"] == [False, False, False]
    assert got["quiet"] is True
    assert got["lobby"]["boxes"] == ["go-ahead-system"] and got["lobby"]["block"]
    assert got["lobbyApprove"] == [["approve", "p1", 25, hash_, {"goAhead": ["system"]}]]


# --- A-29, A-31, A-32: the actions of a task row, in the Tasks tab and the Agent tab ------------------------------------------------

TABS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
import * as fm from "@JS@/floor-model.js";
import { ApiError } from "@JS@/api.js";

setToken("t".repeat(40));
globalThis.fetch = async () => ({ ok: false, status: 404, json: async () => ({ error: "not_found", message: "no" }) });
const P = "0123456789ab";
const NOW = new Date("2026-10-09T12:00:00Z");
const input = { task_id: 10, request_id: 3, reason: "docs/brand/identity.md, written by task #10" };
const after = { task_id: null, request_id: 3, reason: "after request #3" };
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "design-system", state, note: null, agent: "design", requestId: 2, waiting_for: [], ...extra });
const text = (n) => n.textContent;
const sent = [];
let failing = null;
const api = {
  retry: async (p, id) => { sent.push(["retry", p, id]); },
  goAhead: async (p, id, options) => { sent.push(["goAhead", p, id, options || null]); if (failing) throw new ApiError(409, "refused", failing); return { task_id: id }; },
};
let refreshed = 0;
const links = { request: () => "#/r", inbox: (id) => `#/inbox/${id}`, open: (p) => `#/open/${p}` };
const out = {};

// --- the Tasks tab ---
const tab = createTasksTab({ project: P, now: () => NOW, refresh: () => { refreshed += 1; }, api, links });
const list = [task(5, "planned", { waiting_for: [input] }), task(6, "planned", { waiting_for: [after] }), task(7, "planned", { waiting_for: [input, after] }), task(8, "planned"),
  task(9, "blocked", { note: "design-system needs docs/brand/identity.md; nothing writes it" }), task(4, "failed", { note: "Timed out" })];
tab.update({ tasks: list, requests: [{ id: 2, title: "Design", state: "planned" }], pending: [], loading: false });
await settle();
const li = (id) => all(tab.el, "li.wb-task").find((n) => n.attrs["data-task"] === String(id));
const actionsOf = (id) => all(li(id), ".wb-task-actions button").map((b) => [text(b), b.attrs["aria-label"]]);
out.tasks = {
  waits5: all(li(5), ".wb-task-waits").map(text), actions5: actionsOf(5), actions6: actionsOf(6), actions7: actionsOf(7), actions8: all(li(8), ".wb-task-actions").length,
  waits6: all(li(6), ".wb-task-waits").map(text),
  blocked: { buttons: actionsOf(9), beside: text(li(9).querySelector(".wb-task-actions .wb-task-note")), under: li(9).querySelector(".wb-task > .wb-task-note") === null },
  failedNote: text(li(4).querySelector(".wb-task-note")),
};
li(5).querySelector("button.wb-task-go-ahead").click();
await settle();
li(6).querySelector("button.wb-task-drop-after").click();
await settle();
failing = "That task waits for nothing to go ahead of.";
li(7).querySelector("button.wb-task-go-ahead").click();
await settle();
out.tasks.effect = all(li(5), ".wb-task-effect").map(text);
out.tasks.noEffect = all(li(9), ".wb-task-effect").length;
out.tasks.sent = sent.slice();
out.tasks.refused = text(li(7).querySelector(".wb-notice-card"));
out.tasks.refreshed = refreshed > 0;
failing = null;
sent.length = 0;

// --- the Agent tab: the current task carries the actions (A-32) ---
const agent = { name: "design", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 2, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0, wider: [] };
const view = (tasks, pending = []) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "R", state: "planned", tasks }], pending, held: [] }, agents: [agent] } }, tasks: {}, loaded: true }, P, "design", {});
const agentTab = createAgentTab({ project: P, agent: "design", api, refresh: () => { refreshed += 1; }, now: () => NOW, links: { inbox: (id) => `#/p/${P}/floor/design/inbox/${id}` } });
const current = () => find(agentTab.el, ".wb-current");
const buttons = () => all(current(), "button").map((b) => b.attrs["aria-label"]);
// a blocked current task has Retry, with the sentence beside it
agentTab.update(view([task(11, "blocked", { note: "design-system needs docs/brand/identity.md; nothing writes it" })]));
out.blocked = { buttons: buttons(), note: text(current().querySelector(".wb-task-actions .wb-task-note")), head: text(current().querySelector(".wb-current-head")) };
current().querySelector("button[data-key=retry-11]").click();
await settle();
out.blocked.sent = sent.slice();
sent.length = 0;
// a failed one too; a waiting one has "Open in the Inbox"
agentTab.update(view([task(12, "failed", { note: "Timed out" })]));
out.failed = buttons();
agentTab.update(view([task(13, "waiting")], [{ id: 77, kind: "review", title: "r", task_id: 13, agent: "design", actions: ["released"] }]));
out.waiting = { buttons: buttons(), link: current().querySelector("a.wb-task-inbox").attrs.href, text: text(current().querySelector("a.wb-task-inbox")) };
// a planned task is never the current one; it is among the others, with its reasons and Go ahead
agentTab.update(view([task(15, "running"), task(14, "planned", { waiting_for: [input] })]));
const other14 = all(agentTab.el, ".wb-other").find((o) => text(o).startsWith("#14"));
out.planned = { buttons: all(other14, "button").map((b) => b.attrs["aria-label"]), waits: all(other14, ".wb-task-waits").map(text) };
other14.querySelector("button[data-key=go-ahead-14]").click();
await settle();
out.planned.sent = sent.slice();
// a running current task has no action
agentTab.update(view([task(15, "running")]));
out.running = { buttons: buttons(), actions: all(current(), ".wb-task-actions").length };
// the other tasks use the same source
agentTab.update(view([task(16, "running"), task(17, "blocked", { note: "needs a file" }), task(18, "planned", { waiting_for: [after] })]));
const others = all(agentTab.el, ".wb-other");
out.others = others.map((o) => [text(o.querySelector(".wb-other-title")), all(o, "button").map((b) => b.attrs["aria-label"]), all(o, ".wb-task-note").map(text), all(o, ".wb-task-waits").map(text)]);

// the Agent tab's Hand a file over: the line of a web task above the chooser. The current task's body is used as it is (no read of its own); another target is read once
const drops = { 11: { web: true, takes: true, line: "this file will be visible to a run with the open network" }, 12: { web: false, takes: true, line: null }, 13: { web: true, takes: false, line: "x" } };
const reads = [];
const withTask = createAgentTab({ project: P, agent: "design", api, refresh() {}, now: () => NOW, task: async (id) => { reads.push(id); return { task: { id }, drop: drops[id] }; } });
const handOf = () => find(withTask.el, ".wb-hand");
const viewWith = (tasks, bodies) => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "R", state: "planned", tasks }], pending: [], held: [] }, agents: [agent] } }, tasks: {}, loaded: true }, P, "design", bodies);
withTask.update(viewWith([task(11, "blocked", { note: "n" })], { 11: { task: { id: 11 }, runs: [], pending: [], drop: drops[11] } }));
await settle();
out.drop = { line: text(find(handOf(), ".wb-drop-line")), hidden: find(handOf(), ".wb-drop-line").hidden, order: [...handOf().walk()].filter((n) => /wb-drop-line|wb-file/.test(n.attrs.class || "")).map((n) => n.attrs.class.split(" ").pop()), input: find(handOf(), "input.wb-file").disabled, reads: reads.length };
withTask.update(viewWith([task(15, "running"), task(12, "failed")], {}));
await settle();
withTask.update(viewWith([task(15, "running"), task(12, "failed")], {}));
await settle();
out.dropNonWeb = { hidden: find(handOf(), ".wb-drop-line").hidden, input: find(handOf(), "input.wb-file").disabled, reads: reads.slice() };
withTask.update(viewWith([task(15, "running"), task(13, "failed")], {}));
await settle();
out.dropRefuses = [find(handOf(), "input.wb-file").disabled, find(handOf(), ".wb-drop-line").hidden, reads.slice()];
agentTab.update(view([task(11, "blocked", { note: "n" })]));
out.noReader = find(agentTab.el, ".wb-drop-line").hidden;
console.log(JSON.stringify(out));
"""


# --- A-23: the composer, the queued line, the request made during a run -------------------------------------------------------------

COMPOSER = r"""
import { FakeNode, find, all, click, where, byClass, textOf } from "@FAKE@";
import { createComposer } from "@JS@/views/lobby-composer.js";
import { createForm } from "@JS@/views/lobby-form.js";
import { createThread } from "@JS@/views/lobby-thread.js";
import * as m from "@JS@/views/lobby-model.js";
import * as actions from "@JS@/views/lobby-actions.js";
import * as router from "@JS@/router.js";

const NOW = new Date("2026-10-09T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600e3).toISOString();
const out = {};

// the composer says a run is in progress before Send; Send stays on; a plain line is sent as typed
const sent = [];
const composer = createComposer({ onSend: (t) => sent.push(t) });
const runLine = () => byClass(composer.el, "wb-lobby-run")[0];
out.idle = { hidden: runLine().hidden };
composer.set({ sending: false, notice: null, disabled: false, running: { text: "Task #12 Build the page", href: "#/p/x/floor/engineering" } });
const link = byClass(composer.el, "wb-lobby-run-link")[0];
const send = where(composer.el, (n) => n.tagName === "BUTTON")[0];
out.running = { hidden: runLine().hidden, text: textOf(runLine()), link: [textOf(link), link.attrs.href, link.hidden], send: send.disabled, role: runLine().attrs.role };
composer.set({ sending: false, notice: null, disabled: true, running: { text: "Task #12", href: "#/" } });
out.notAccepted = { hidden: runLine().hidden, send: send.disabled };
composer.set({ sending: false, notice: null, disabled: false, running: null });
out.after = { hidden: runLine().hidden };
out.hints = byClass(composer.el, "wb-lobby-hint").map(textOf);

// the model: which line is queued, which message a read asks above, the task that runs
const msgs = [{ id: 3, role: "user", text: "a", queued: false }, { id: 5, role: "user", text: "b", queued: true }, { id: 8, role: "assistant", text: "c", queued: false }];
out.model = {
  meta: [m.metaOf({ role: "user", created_at: ago(1), queued: true }, NOW), m.metaOf({ role: "user", created_at: ago(1), queued: false }, NOW), m.metaOf({ role: "user", queued: true }, NOW)],
  name: m.nameOf({ role: "user", created_at: ago(1), queued: true }, NOW), has: [m.hasQueued(msgs), m.hasQueued([msgs[0]]), m.hasQueued(null)],
  readAfter: [m.readAfter(msgs), m.readAfter([msgs[0], msgs[2]]), m.readAfter([]), m.readAfter([{ id: 5, queued: true }])],
  running: [m.runningTask({ requests: [{ tasks: [{ id: 1, state: "done" }, { id: 2, state: "running", title: "Build", agent: "engineering" }] }] }), m.runningTask({ requests: [{ tasks: [{ id: 1, state: "planned" }] }] }), m.runningTask(null)],
  hash: [router.agentHash("p", "engineering"), router.agentHash("p", "planning"), router.agentHash("p", null)],
};

// the thread: a queued line shows the word until the reply arrives
const api = { approve: async () => ({}), reject: async () => ({}), pollJob: async () => ({ state: "done" }), cancel: async () => ({}) };
const thread = createThread({ api, project: "p1", signal: undefined, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {} });
const state = (messages) => ({ messages, requests: [], pending: [], bodies: {}, now: NOW, loading: false, routing: new Set() });
thread.update(state([{ id: 1, role: "user", text: "Como estamos?", created_at: ago(0.01), queued: true }]));
const first = byClass(thread.el, "wb-msg")[0];
out.queued = { meta: textOf(byClass(thread.el, "wb-msg-meta")[0]), cls: first.attrs.class, name: first.attrs["aria-label"], bubble: textOf(byClass(thread.el, "wb-bubble")[0]) };
thread.update(state([{ id: 1, role: "user", text: "Como estamos?", created_at: ago(0.01), queued: false }, { id: 2, role: "assistant", text: "Two tasks are done.", created_at: ago(0) }]));
out.answered = { meta: textOf(byClass(thread.el, "wb-msg-meta")[0]), cls: byClass(thread.el, "wb-msg")[0].attrs.class, same: byClass(thread.el, "wb-msg")[0] === first, count: byClass(thread.el, "wb-msg").length };

// the form: the "After request #" field, sent only when typed
const form = createForm({ onCreate: () => {} });
const got = [];
const form2 = createForm({ onCreate: (v) => got.push(v) });
const submit = (f) => (f.el.querySelector("form").listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
const fields = (f) => f.el.querySelectorAll("input");
const afterInput = fields(form2).find((i) => i.attrs.id === "wb-new-after");
const textArea = form2.el.querySelectorAll("textarea")[0];
textArea.value = "Landing page";
submit(form2);
afterInput.value = "3";
submit(form2);
out.form = { sent: got, label: textOf(afterInput.parent.querySelector("span")), inputmode: afterInput.attrs.inputmode };
out.afterNumber = ["3", " #4 ", "", "x", "0", "-2", 5, "1.5", "12345678901"].map((v) => actions.afterNumber(v));

// a request made during a run: `request` carries `after`, then `route`; the route answers queued
const calls = [];
const client = {
  request: async (p, text, o) => { calls.push(["request", p, text, o.after === undefined ? null : o.after, o.title === undefined ? null : o.title]); return { request: 9 }; },
  route: async (p, id, o) => { calls.push(["route", p, id, o.flow || null]); return { job: "j" }; },
};
await actions.createRequest(client, "p1", { text: "x", flow: "", title: "", after: "3" });
await actions.createRequest(client, "p1", { text: "y", flow: "design", title: "T" });
out.createCalls = calls;
out.queuedNotice = m.QUEUED_NOTICE;
console.log(JSON.stringify(out));
"""


# --- A-25, A-26, A-30: the unrecognised route, the done card, the review card's hand-over --------------------------------------------

CARDS = r"""
import { FakeNode, settle, find, all, click, where, byClass, textOf } from "@FAKE@";
import { createCard, isUnrecognised } from "@JS@/floor/cards.js";

const calls = [];
let script = {};
const client = () => {
  const record = (name) => async (...args) => { calls.push([name, ...args]); if (script[name]) return script[name](...args); return name === "route" ? { job: "j1" } : name === "pollJob" ? { state: "done", result: { routed: true } } : {}; };
  return { answer: record("answer"), release: record("release"), approve: record("approve"), reject: record("reject"), cancel: record("cancel"), route: record("route"), flows: record("flows"), pollJob: record("pollJob"), handOver: record("handOver") };
};
const env = (extra = {}) => ({ project: "p", now: () => new Date("2026-10-09T12:00:00Z"), api: client(), requestIds: new Set([6]), links: { floor: () => "#", lobby: () => "#/p/p/lobby", open: () => "#" }, reread: async () => null, changed() {}, gone() {}, ...extra });
const RAW = "Route: none (direct)\nWhy: a question\nNext: ask the flow list <b>x</b>";
const lost = { id: 31, kind: "question", title: "The route was not recognised", body: "The planning agent did not name a flow or a skill for request 6", payload: { ending: "unclassified", raw: RAW, actions: ["choose-flow", "cancel"] }, payload_sha256: null,
  status: "open", actions: ["answered"], agent: null, task_id: 6, run_id: 4, created_at: "2026-10-09T09:00:00Z" };
const out = {};

out.is = [isUnrecognised(lost), isUnrecognised({ ...lost, payload: {} }), isUnrecognised({ ...lost, kind: "review" }), isUnrecognised(null)];
const card = createCard(lost, env());
out.card = {
  body: textOf(find(card.el, ".wb-card-body")), words: all(card.el, "button.wb-card-button").map((b) => [b.attrs["data-word"], textOf(b)]),
  disclosure: textOf(find(card.el, ".wb-raw-reply summary")), raw: textOf(find(card.el, ".wb-raw-reply pre")), rawElements: [...find(card.el, ".wb-raw-reply").walk()].filter((n) => ["B", "SCRIPT"].includes(n.tagName)).length,
  answerField: all(card.el, "textarea").length,
};
const plain = createCard({ ...lost, payload: {} }, env());
out.plain = { words: all(plain.el, "button.wb-card-button").map((b) => b.attrs["data-word"]), disclosure: find(plain.el, ".wb-raw-reply") === null };

// Choose a flow: the list is read once, then `route` with the flow
script = { flows: async () => ({ flows: [{ flow: "brand", title: "Brand of a product" }, { flow: "broken", error: "no" }, { flow: "design", title: "Design" }] }) };
const word = (c, w) => all(c.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === w);
word(card, "choose-flow").click();
await settle();
const select = find(card.el, "select");
out.flows = { options: all(select, "option").map((o) => [o.attrs.value, textOf(o)]), calls: calls.filter((c) => c[0] === "flows").map((c) => c.slice(1)) };
word(card, "route").click();                     // nothing chosen: the card says so and sends nothing
await settle();
out.noFlow = { hint: textOf(find(card.el, ".wb-hint.is-error")), routes: calls.filter((c) => c[0] === "route").length };
const select2 = find(card.el, "select");
select2.value = "design";
select2.listeners.change.forEach((fn) => fn());
word(card, "route").click();
await settle();
out.route = { calls: calls.filter((c) => ["route", "pollJob"].includes(c[0])).map((c) => c.slice(0, 4)), done: textOf(find(card.el, ".wb-card-done")) };
// the flow list is not read again when the card opens it a second time
out.flowReads = calls.filter((c) => c[0] === "flows").length;

// Cancel the request: `cancel` with the request id (the decision's task_id)
calls.length = 0;
const card2 = createCard({ ...lost, id: 32 }, env());
word(card2, "cancel-request").click();
await settle();
out.cancel = { calls: calls.map((c) => c.slice(0, 3)), done: textOf(find(card2.el, ".wb-card-done")) };

// a failed list is said on the card, and the card stays open
calls.length = 0;
script = { flows: async () => { throw Object.assign(new Error("The flows could not be read."), { name: "ApiError", status: 409, word: "refused" }); } };
const card3 = createCard({ ...lost, id: 33 }, env());
word(card3, "choose-flow").click();
await settle();
out.flowError = { text: textOf(find(card3.el, ".wb-notice-card")), select: find(card3.el, "select") === null, buttons: all(card3.el, "button.wb-card-button").length };

// a router that could not plan: routed false is an error, not a success
calls.length = 0;
script = { flows: async () => ({ flows: [{ flow: "design", title: "Design" }] }), pollJob: async () => ({ state: "done", result: { routed: false, failure: { reason: "no model" } } }) };
const card4 = createCard({ ...lost, id: 34 }, env());
word(card4, "choose-flow").click();
await settle();
const s4 = find(card4.el, "select");
s4.value = "design";
s4.listeners.change.forEach((fn) => fn());
word(card4, "route").click();
await settle();
out.unrouted = { done: find(card4.el, ".wb-card-done") === null, error: textOf(find(card4.el, ".wb-notice-card")) };

// --- A-26: the done card, a result on its own line, prose for a sentence, mono for an id ---
script = {};
const question = { id: 41, kind: "question", title: "Brand voice <b>question</b>", body: "b", payload: {}, payload_sha256: null, status: "open", actions: ["answered"], agent: "brand", task_id: 5, run_id: null, created_at: "2026-10-09T09:00:00Z" };
script = { answer: async () => ({ state: { written: false, reason: "an answer to the router is given to its next run, not recorded as a decision" } }) };
const asked = createCard(question, env());
find(asked.el, "textarea").value = "go on";
find(asked.el, "textarea").listeners.input.forEach((fn) => fn());
all(asked.el, "button.wb-card-button")[0].click();
await settle();
const done = find(asked.el, ".wb-card-done");
out.doneTitleClass = done.children[1].attrs.class;
out.doneSentence = { classes: done.attrs.class, children: done.children.map((c) => c.attrs.class || c.tagName), result: textOf(find(done, ".wb-card-result")), mono: all(done, ".mono").length, prose: all(done, ".wb-card-result .wb-card-line").map(textOf), title: textOf(done.children[1]) };
script = { release: async () => ({ commit: "abc1234", pull_request: { number: 12 } }) };
const review = { id: 42, kind: "review", title: "R", body: "b", payload: { returned: [], kept: [{ path: "docs/a.woff2", class: "font" }, { path: "docs/b.woff2", class: "font" }], run_dir: "/work/shop/.runs/4" }, payload_sha256: null, status: "open", actions: ["released", "answered"], agent: "brand", task_id: 5, run_id: 4, created_at: "2026-10-09T09:00:00Z" };
const released = createCard(review, env());
all(released.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "released").click();
await settle();
const done2 = find(released.el, ".wb-card-done");
out.doneIds = { mono: all(done2, ".mono").map(textOf), prose: all(done2, ".wb-card-result .wb-card-line").map(textOf), folder: all(done2, ".wb-command-code").map(textOf), copy: all(done2, "button.wb-copy").map((b) => b.attrs["aria-label"]) };
script = {};
const nokept = createCard({ ...review, id: 43, payload: { returned: [], kept: [] } }, env());
all(nokept.el, "button.wb-card-button").find((b) => b.attrs["data-word"] === "released").click();
await settle();
out.doneNoKept = { result: find(find(nokept.el, ".wb-card-done"), ".wb-card-result") !== null, folder: all(nokept.el, ".wb-command-code").length };

// --- A-30: Hand a file over on the review card ---
script = {};
const drop = (extra = {}) => ({ web: true, takes: true, line: "this file will be visible to a run with the open network", ...extra });
const bodyOf = (d) => async (id) => ({ task: { id }, runs: [], pending: [], drop: d });
const rcard = async (d, id) => { const c = createCard({ ...review, id }, env({ task: bodyOf(d) })); await settle(); return c; };
const web = await rcard(drop(), 50);
const control = find(web.el, ".wb-card-hand");
out.hand = { label: textOf(find(control, ".wb-field-label")), line: textOf(find(control, ".wb-drop-line")), order: [...control.walk()].filter((n) => n.attrs && (n.attrs.class || "").match(/wb-drop-line|wb-file/)).map((n) => n.attrs.class.split(" ").pop()), hint: textOf(find(control, ".wb-hint")) };
const input = find(web.el, "input.wb-file");
const file = { name: "logo.png", size: 3, arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
input.files = [file];
input.listeners.change.forEach((fn) => fn());
await settle();
out.handChosen = { calls: calls.filter((c) => c[0] === "handOver").length, name: textOf(find(web.el, ".wb-hand-chosen")) };     // C-17: choosing a file sends nothing
find(web.el, "button.wb-hand-button").click();
await settle();
script = {};
out.handSent = { calls: calls.filter((c) => c[0] === "handOver").map((c) => c.slice(1)), result: textOf(find(web.el, ".wb-card-hand .wb-card-line")) };
// a refusal before sending: a name the service would refuse
const bad = find(web.el, "input.wb-file");
bad.files = [{ name: "bad name.png", size: 3, arrayBuffer: async () => new ArrayBuffer(3) }];
bad.listeners.change.forEach((fn) => fn());
await settle();
out.handBad = textOf(find(web.el, ".wb-card-hand .wb-notice-card"));
const nonweb = await rcard(drop({ web: false, line: "ignored" }), 51);
out.nonWeb = { control: find(nonweb.el, ".wb-card-hand") !== null, line: find(nonweb.el, ".wb-drop-line") === null };
const refuses = await rcard(drop({ takes: false }), 52);
out.refuses = find(refuses.el, ".wb-card-hand") === null;
const unread = createCard({ ...review, id: 53 }, env());                 // no task reader: no control
out.unread = find(unread.el, ".wb-card-hand") === null;
const failing = createCard({ ...review, id: 54 }, env({ task: async () => { throw new Error("no"); } }));
await settle();
out.failedRead = find(failing.el, ".wb-card-hand") === null;
console.log(JSON.stringify(out));
"""


# --- A-33: the viewer shows an image, a type it cannot show gets a sentence, the Desk says the kind ----------------------------------

VIEWER = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createViewer, unshownSentence } from "@JS@/floor/viewer.js";
import { createDeskTab } from "@JS@/floor/desk-tab.js";
import * as fm from "@JS@/floor-model.js";

setToken("t".repeat(40));
const text = (n) => n.textContent;
const requests = [];
let answer = null;
globalThis.fetch = async (url, init) => {
  requests.push({ url: String(url), headers: init.headers, method: init.method });
  return answer(url);
};
const json = (status, body) => ({ ok: status < 300, status, json: async () => body });
const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 1, 2, 3, 4]);
const blobAnswer = () => ({ ok: true, status: 200, blob: async () => new Blob([bytes], { type: "image/png" }), json: async () => { throw new Error("not json"); } });
const made = [];
const revoked = [];
const opened = [];
const object = { create: (blob) => { made.push(blob.size); return `blob:test/${made.length}`; }, revoke: (u) => revoked.push(u) };
let closed = 0;
const rows = { "docs/brand/pieces/banner.png": { kind: "image", size: 8 }, "docs/brand/font.woff2": { kind: "other", size: 4096 }, "docs/a.md": { kind: "markdown", size: 5 } };
const viewer = createViewer({ onClose: () => { closed += 1; }, listed: (p) => rows[p], object, open: (u) => opened.push(u) });
const out = {};

// an image: bytes with the bearer header, an <img> from a blob URL, the path as alt text, the size, "Open in a new tab"
answer = () => blobAnswer();
await viewer.load("p", "docs/brand/pieces/banner.png");
const img = find(viewer.el, "img");
out.image = {
  request: requests[requests.length - 1], src: img.attrs.src, alt: img.attrs.alt, cls: img.attrs.class, srcdoc: "srcdoc" in img.attrs,
  tags: [...viewer.el.walk()].map((n) => n.tagName).filter((t) => ["IMG", "SVG", "OBJECT", "IFRAME", "EMBED"].includes(t)),
  caption: text(find(viewer.el, ".wb-viewer-caption")), head: text(find(viewer.el, ".wb-viewer-line")), button: text(find(viewer.el, "button[data-key=open-tab]")),
  pre: find(viewer.el, "pre") === null, created: made.slice(),
};
// the dimensions arrive when the image has loaded
Object.assign(img, { naturalWidth: 1200, naturalHeight: 630 });
img.listeners.load.forEach((fn) => fn());
out.dims = text(find(viewer.el, ".wb-viewer-caption"));
find(viewer.el, "button[data-key=open-tab]").click();
out.opened = opened.slice();
// another file: the blob URL of the first is revoked; close revokes the last
answer = () => json(200, { path: "docs/a.md", text: "# Hello", size: 7, modified_at: "2026-10-09T09:00:00Z" });
await viewer.load("p", "docs/a.md");
out.afterText = { revoked: revoked.slice(), requestUrl: requests[requests.length - 1].url, img: find(viewer.el, "img") === null };
answer = () => blobAnswer();
await viewer.load("p", "docs/brand/pieces/banner.png");
viewer.close();
out.afterClose = { revoked: revoked.slice(), made: made.length };

// a type the page cannot show: the runtime's sentence, and the path to copy
answer = () => json(400, { error: "usage", message: "docs/brand/font.woff2 is a woff2 font, 4096 bytes: the Desk shows text, Markdown and images" });
await viewer.load("p", "docs/brand/font.woff2");
out.other = { title: text(find(viewer.el, ".wb-refusal-title")), sentence: text(find(viewer.el, ".wb-refusal span")), code: text(find(viewer.el, ".wb-command-code")), copy: find(viewer.el, "button.wb-copy").attrs["aria-label"], img: find(viewer.el, "img") === null,
  url: requests[requests.length - 1].url };
out.sentences = [unshownSentence("given", "other", "4.0 KB"), unshownSentence("", "other", "4.0 KB"), unshownSentence(null, "", "")];
// the raw read failing for another reason is the generic refusal
answer = () => json(404, { error: "not_found", message: "no such file" });
await viewer.load("p", "docs/brand/pieces/banner.png");
out.missing = { title: text(find(viewer.el, ".wb-refusal-title")), message: text(find(viewer.el, ".wb-refusal .mono")) };
// a list that does not say what the file is: the text read first, and an image after it when the text read refuses
let step = 0;
answer = (url) => { step += 1; return step === 1 ? json(400, { error: "usage", message: "docs/x.png is not UTF-8 text" }) : blobAnswer(); };
const blind = createViewer({ onClose() {}, listed: () => undefined, object, open: () => {} });
await blind.load("p", "docs/x.png");
out.blind = { urls: requests.slice(-2).map((r) => r.url.replace("/api/v1/projects/p", "")), img: find(blind.el, "img") !== null };
step = -5;
answer = () => { step += 1; return step < -3 ? json(400, { error: "usage", message: "docs/outside is outside docs/" }) : json(400, { error: "usage", message: "docs/outside is outside docs/" }); };
await blind.load("p", "docs/outside");
out.blindRefused = text(find(blind.el, ".wb-refusal .mono"));

// bytes of a type the page does not show are no image, and a svg has no new-tab button
const typed = (type) => () => ({ ok: true, status: 200, blob: async () => new Blob([bytes], { type }), json: async () => ({}) });
rows["docs/mark.svg"] = { kind: "image", size: 8 };
rows["docs/odd.bin"] = { kind: "image", size: 8 };
rows["docs/p.webp"] = { kind: "image", size: 8 };
answer = typed("image/svg+xml");
await viewer.load("p", "docs/mark.svg");
out.svg = { img: find(viewer.el, "img") !== null, button: find(viewer.el, "button[data-key=open-tab]") === null };
answer = typed("image/webp");
await viewer.load("p", "docs/p.webp");
out.webp = find(viewer.el, "button[data-key=open-tab]") !== null;
const madeBefore = made.length;
answer = typed("application/pdf");
await viewer.load("p", "docs/odd.bin");
out.oddType = { img: find(viewer.el, "img") === null, made: made.length - madeBefore, title: text(find(viewer.el, ".wb-refusal-title")), cls: find(viewer.el, ".wb-refusal").attrs.class, code: text(find(viewer.el, ".wb-command-code")) };
// the blob URL of an image is revoked when the next file is a refusal of the type
answer = () => blobAnswer();
await viewer.load("p", "docs/brand/pieces/banner.png");
const revokedBefore = revoked.length;
answer = () => json(400, { error: "usage", message: "docs/brand/font.woff2 is a woff2 font, 4096 bytes: the Desk shows text, Markdown and images" });
await viewer.load("p", "docs/brand/font.woff2");
out.revokedOnRefusal = revoked.length - revokedBefore;

// the Desk says what each file is
const docs = [{ path: "docs/a.md", owner: "s", size: 5, modified_at: "2026-10-09T09:00:00Z", kind: "markdown" }, { path: "docs/b.png", owner: "s", size: 2048, modified_at: "2026-10-08T09:00:00Z", kind: "image" },
  { path: "docs/c.woff2", owner: null, size: 12, modified_at: "2026-10-07T09:00:00Z", kind: "other" }, { path: "docs/d.txt", owner: null, size: 12, modified_at: "2026-10-06T09:00:00Z", kind: "text" }, { path: "docs/e", owner: null, size: 12, modified_at: "2026-10-05T09:00:00Z" }];
out.rows = fm.deskRows(docs, "").map((r) => [r.path, r.kind]);
const desk = createDeskTab({ project: "p", agent: "x", open() {} });
desk.update({ documents: docs, truncated: false, loading: false, error: null });
out.cells = all(desk.el, "td.wb-nowrap").map(text);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_viewer_shows_an_image_from_a_blob_url_a_type_it_cannot_show_gets_a_sentence_and_the_desk_says_the_kind(tmp_path):
    got = run_node(tmp_path, VIEWER)
    image = got["image"]
    assert image["request"]["url"] == "/api/v1/projects/p/artifact/raw?path=docs%2Fbrand%2Fpieces%2Fbanner.png" and image["request"]["method"] == "GET"
    assert image["request"]["headers"]["Authorization"] == "Bearer " + "t" * 40, "the bytes are fetched with the bearer header: the token is in no address"
    assert image["src"] == "blob:test/1" and image["alt"] == "docs/brand/pieces/banner.png" and image["cls"] == "wb-viewer-image" and image["srcdoc"] is False
    assert image["tags"] == ["IMG"], "an <img> and nothing else: no inline SVG, no object, no frame"
    assert image["caption"] == "8 B" and image["head"] == "8 B" and image["button"] == "Open in a new tab" and image["pre"] is True and image["created"] == [8]
    assert got["dims"] == "8 B · 1200 × 630 px"
    assert got["opened"] == ["blob:test/1"], "Open in a new tab opens the blob URL"
    assert got["afterText"] == {"revoked": ["blob:test/1"], "requestUrl": "/api/v1/projects/p/artifact?path=docs%2Fa.md", "img": True}, "the URL is revoked when another file is shown"
    assert got["afterClose"] == {"revoked": ["blob:test/1", "blob:test/2"], "made": 2}, "and when the viewer closes"
    other = got["other"]
    assert other["title"] == "The Desk cannot show this file" and other["sentence"] == "docs/brand/font.woff2 is a woff2 font, 4096 bytes: the Desk shows text, Markdown and images"
    assert other["code"] == "docs/brand/font.woff2" and other["copy"] == "Copy the path" and other["img"] and other["url"].endswith("/artifact/raw?path=docs%2Fbrand%2Ffont.woff2")
    assert got["sentences"] == ["given", "This file is other, 4.0 KB; the Desk shows text, Markdown and images", "This file is of a type the page cannot show, of unknown size; the Desk shows text, Markdown and images"]
    assert got["missing"] == {"title": "The file could not be opened", "message": "no such file"}
    assert got["blind"]["urls"] == ["/artifact?path=docs%2Fx.png", "/artifact/raw?path=docs%2Fx.png"] and got["blind"]["img"], "a list that does not say: the text first, then the bytes"
    assert got["blindRefused"] == "docs/outside is outside docs/", "the text read's refusal is shown when the bytes do not help"
    assert got["svg"] == {"img": True, "button": True} and got["webp"] is True, "a svg is shown in the page and never opened as a document of its own"
    assert got["oddType"] == {"img": True, "made": 0, "title": "The Desk cannot show this file", "cls": "wb-refusal is-info", "code": "docs/odd.bin"}, "a type outside the closed list gets no <img> and the info tone"
    assert got["revokedOnRefusal"] == 1
    assert got["rows"] == [["docs/a.md", "Markdown"], ["docs/b.png", "image"], ["docs/c.woff2", "other"], ["docs/d.txt", "text"], ["docs/e", ""]]
    assert got["cells"][:4] == ["5 B · Markdown", "2.0 KB · image", "12 B · other", "12 B · text"] and got["cells"][4] == "12 B"


# --- A-24: add a project, leave a project ---------------------------------------------------------------------------------------

PROJECTS = r"""
import { FakeNode, settle, find, all, click, where, byClass, textOf } from "@FAKE@";
import * as m from "@JS@/views/city-projects-model.js";
import { createProjectsPanel } from "@JS@/views/city-projects.js";

const START = "uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py --project /work/shop";
const out = {};
out.words = [m.shellWord("/work/shop"), m.shellWord("/work/my shop"), m.shellWord("/work/it's"), m.shellWord("<folder of shop>"), m.shellWord("a;b")];
out.split = [m.splitWords("python3 '/a b/runtime/service.py' --project /x"), m.splitWords("a \"b c\" 'd e'f")];
out.head = [m.startHead(START), m.startHead("python3 /opt/ck/runtime/service.py"), m.startHead("nothing"), m.startHead(null)];
out.checkout = [m.checkoutOf(m.startHead(START)), m.checkoutOf("python3 '/opt/my ck/runtime/service.py'"), m.checkoutOf("python3 x")];
out.folderOf = [m.folderOf("/work/shop/docs/workbench/runtime.json"), m.folderOf("/x/runtime.json"), m.folderOf(null), m.folderOf("/docs/workbench/runtime.json")];
const snapshot = { projects: [{ id: "a".repeat(12), name: "shop", config: { accepted: true } }, { id: "b".repeat(12), name: "blog", config: { accepted: false } }],
  details: { ["a".repeat(12)]: { status: { config: { path: "/work/shop/docs/workbench/runtime.json" } } } } };
const projects = m.projectsOf(snapshot);
out.projects = projects;
out.readable = [m.readableProject(snapshot), m.readableProject({ projects: [{ id: "x", config: { accepted: false } }] }), m.readableProject(null)];
const head = m.startHead(START);
out.add = m.restartLine({ head, projects: [projects[0]], add: "/work/new shop" });
out.addUnknown = m.restartLine({ head, projects, add: "/work/new" });
out.noHead = m.restartLine({ head: "", projects: [projects[0]], add: "/work/new" }).command;
const evil = [{ id: "e".repeat(12), name: "x $(touch /tmp/pwn) `id` ;rm", folder: null }];
out.evil = m.restartLine({ head, projects: evil, add: "/w" });
out.safe = [m.safeName("shop-1_a.b c"), m.safeName("x$(y)"), m.safeName(null)];
out.leave = m.restartLine({ head, projects, leave: "b".repeat(12) });
out.leaveLast = m.restartLine({ head, projects: [projects[0]], leave: "a".repeat(12) });
out.init = [m.initLine({ head, folder: "/work/new", autonomy: "milestones" }), m.initLine({ head: "", folder: "/work/my new", autonomy: "end" })];
out.refusal = [m.folderRefusal("", projects), m.folderRefusal("relative/dir", projects), m.folderRefusal("/work/shop", projects), m.folderRefusal("/work/other", projects), m.folderRefusal("~/x", projects), m.cleanFolder("  /work/x//  "), m.cleanFolder("/")];

// the panel
let started = 0;
const panel = createProjectsPanel({ readStart: async () => { started += 1; return START; }, copy: { clipboard: null, select: () => false, later: () => {} } });
panel.setProjects(projects);
out.closed = [panel.el.hidden, panel.isOpen()];
panel.openAdd();
await settle();
const codes = () => all(panel.el, ".wb-command-code").map(textOf);
out.opened = { hidden: panel.el.hidden, heading: textOf(find(panel.el, ".wb-add-head strong")), codes: codes(), reads: started, hint: textOf(find(panel.el, ".wb-hint")) };
const folder = () => find(panel.el, "input[data-key=project-folder]");
const type = async (value) => { folder().focus(); folder().value = value; folder().listeners.input.forEach((fn) => fn()); await settle(); };
await type("/work/new");
out.typed = { codes: codes(), sentences: all(panel.el, ".wb-command-sentence").map(textOf), notes: all(panel.el, ".wb-card-note").map(textOf), copies: all(panel.el, "button.wb-copy").length, focus: document.activeElement === folder() };
const none = find(panel.el, "input[data-key=no-configuration]");
none.checked = true;
none.listeners.change.forEach((fn) => fn());
await settle();
out.noConfig = { codes: codes(), sentences: all(panel.el, ".wb-command-sentence").map(textOf), notes: all(panel.el, ".wb-card-note").map(textOf), autonomy: all(find(panel.el, "select[data-key=autonomy]"), "option").map((o) => [o.attrs.value, textOf(o)]) };
const pick = find(panel.el, "select[data-key=autonomy]");
pick.value = "end";
pick.listeners.change.forEach((fn) => fn());
await settle();
out.chosen = codes()[0];
await type("relative");
out.refused = { codes: codes(), hint: textOf(find(panel.el, ".wb-hint.is-error")), invalid: folder().attrs["aria-invalid"] };
await type("/work/shop");
out.same = { codes: codes(), hint: textOf(find(panel.el, ".wb-hint.is-error")) };
// leaving
panel.openLeave("b".repeat(12));
await settle();
out.leaving = { heading: textOf(find(panel.el, ".wb-add-head strong")), codes: codes(), notes: all(panel.el, ".wb-card-note").map(textOf) };
panel.openLeave("a".repeat(12));
panel.setProjects([projects[0]]);
await settle();
out.leaveOnly = { codes: codes(), notes: all(panel.el, ".wb-card-note").map(textOf) };
find(panel.el, "button[data-key=close-add]").click();
out.afterClose = [panel.el.hidden, panel.isOpen()];
// a start line that cannot be read: the known form with the checkout left to fill in
const blind = createProjectsPanel({ readStart: async () => { throw new Error("no"); }, copy: { clipboard: null, select: () => false, later: () => {} } });
blind.setProjects([projects[0]]);
blind.openAdd();
await settle();
const f2 = find(blind.el, "input[data-key=project-folder]");
f2.value = "/work/new";
f2.listeners.input.forEach((fn) => fn());
await settle();
out.blind = { codes: all(blind.el, ".wb-command-code").map(textOf), notes: all(blind.el, ".wb-card-note").map(textOf) };
console.log(JSON.stringify(out));
"""


@needs_node
def test_add_a_project_shows_the_restart_line_with_copy_and_the_init_line_when_there_is_no_configuration_and_never_opens_a_folder(tmp_path):
    got = run_node(tmp_path, PROJECTS)
    assert got["words"] == ["/work/shop", "'/work/my shop'", "'/work/it'\"'\"'s'", "<folder of shop>", "'a;b'"]
    assert got["split"][0] == ["python3", "/a b/runtime/service.py", "--project", "/x"] and got["split"][1] == ["a", "b c", "d ef"]
    head = "uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py"
    assert got["head"] == [head, "python3 /opt/ck/runtime/service.py", "", ""]
    assert got["checkout"] == ["/opt/ck", "/opt/my ck", ""]
    assert got["folderOf"] == ["/work/shop", None, None, None]
    assert got["projects"] == [{"id": "a" * 12, "name": "shop", "folder": "/work/shop"}, {"id": "b" * 12, "name": "blog", "folder": None}]
    assert got["readable"] == ["a" * 12, None, None]
    assert got["add"] == {"command": f"{head} --project /work/shop --project '/work/new shop'", "unknown": [], "empty": False}, "--project repeated: the current ones, then the new folder"
    assert got["addUnknown"]["command"] == f"{head} --project /work/shop --project <folder of blog> --project /work/new" and got["addUnknown"]["unknown"] == ["blog"]
    assert got["noHead"] == "python3 <the workbench folder>/runtime/service.py --project /work/shop --project /work/new"
    assert got["evil"]["command"] == f"{head} --project <folder of x __touch _tmp_pwn_ _id_ _rm> --project /w" and got["evil"]["unknown"] == ["x __touch _tmp_pwn_ _id_ _rm"], "a project name never carries shell text into the line"
    assert "$(" not in got["evil"]["command"] and "`" not in got["evil"]["command"] and ";" not in got["evil"]["command"]
    assert got["safe"] == ["shop-1_a.b c", "x__y_", ""]
    assert got["leave"]["command"] == f"{head} --project /work/shop" and not got["leave"]["empty"]
    assert got["leaveLast"] == {"command": "", "unknown": [], "empty": True}, "the service needs at least one project"
    assert got["init"][0] == "python3 /opt/ck/skills/core-project-init/scripts/init_project.py --root /work/new --apply --autonomy milestones"
    assert got["init"][1] == "python3 <the workbench folder>/skills/core-project-init/scripts/init_project.py --root '/work/my new' --apply --autonomy end"
    assert got["refusal"][:2] == ["", "Type the absolute path of the folder, such as /home/me/shop."] and got["refusal"][2] == "That folder is already one of the service's projects." and got["refusal"][3:5] == ["", "Type the absolute path of the folder, such as /home/me/shop."], "a ~/ path is not absolute: quoted it would name a folder called ~"
    assert got["refusal"][5:] == ["/work/x", "/"]
    assert got["closed"] == [True, False]
    o = got["opened"]
    assert o["hidden"] is False and o["heading"] == "Add a project" and o["codes"] == [] and o["reads"] == 1 and "does not open it" in o["hint"], "nothing is shown until a folder is typed; the service's start line is read once"
    t = got["typed"]
    assert t["codes"] == [f"{head} --project /work/shop --project <folder of blog> --project /work/new"] and t["copies"] == 1 and t["focus"], "the line has Copy; typing keeps the focus in the field"
    assert t["sentences"][0].startswith("Stop the service and start it again with this line") and "Replace <folder of blog>" in t["notes"][0]
    n = got["noConfig"]
    assert len(n["codes"]) == 2 and n["codes"][0].startswith("python3 /opt/ck/skills/core-project-init/scripts/init_project.py --root /work/new --apply --autonomy milestones")
    assert n["sentences"][0].startswith("1. Make the folder a project") and n["sentences"][1].startswith("3. Stop the service")
    assert any(note.startswith("2. Write the project's configuration, docs/workbench/runtime.json, by hand") and "does not start without that file" in note for note in n["notes"]), \
        "the configuration is its own step before the restart line, and says the service does not start without it"
    assert n["autonomy"] == [["milestones", "milestones (recommended)"], ["every-phase", "every phase"], ["end", "at the end"]]
    assert got["chosen"].endswith("--autonomy end")
    assert got["refused"]["codes"] == [] and got["refused"]["hint"].startswith("Type the absolute path") and got["refused"]["invalid"] == "true"
    assert got["same"]["codes"] == [] and got["same"]["hint"] == "That folder is already one of the service's projects."
    assert got["leaving"]["heading"] == "Leave this project" and got["leaving"]["codes"] == [f"{head} --project /work/shop"]
    assert got["leaving"]["notes"][0].startswith("Leaving blog stops showing it here")
    assert got["leaveOnly"]["codes"] == [] and "only project" in got["leaveOnly"]["notes"][0]
    assert got["afterClose"] == [True, False]
    assert got["blind"]["codes"] == ["python3 <the workbench folder>/runtime/service.py --project /work/shop --project /work/new"]
    assert any("could not read the start line" in note for note in got["blind"]["notes"])


# --- A-34: the folder of a project comes from the service, so the restart line holds no placeholder ----------------------------------

PROJECT_FOLDERS = r"""
import * as m from "@JS@/views/city-projects-model.js";

const A = "a".repeat(12), B = "b".repeat(12), C = "c".repeat(12);
const START = "uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py --project /work/shop";
const head = m.startHead(START);
const out = {};
// the entry of GET /projects carries `folder`, accepted or not; the status is not needed to know it
const snapshot = { projects: [{ id: A, name: "shop", folder: "/work/shop", config: { accepted: true } },
                              { id: B, name: "blog", folder: "/work/my blog", config: { accepted: false }, message: "not accepted" }], details: {} };
const projects = m.projectsOf(snapshot);
out.projects = projects;
out.add = m.restartLine({ head, projects, add: "/work/new" });
out.leave = m.restartLine({ head, projects, leave: A });
out.refusal = m.folderRefusal("/work/my blog", projects);
// the service's folder wins over the configuration path of a status, and a status alone still works (an older service)
const both = m.projectsOf({ projects: [{ id: C, name: "docs", folder: "/work/docs", config: { accepted: true } }],
  details: { [C]: { status: { config: { path: "/elsewhere/docs/workbench/runtime.json" } } } } });
out.both = both;
const oldOnly = m.projectsOf({ projects: [{ id: C, name: "docs", config: { accepted: true } }],
  details: { [C]: { status: { config: { path: "/work/docs/docs/workbench/runtime.json" } } } } });
out.oldOnly = oldOnly;
out.nothing = m.projectsOf({ projects: [{ id: C, name: "docs", folder: 7, config: { accepted: false } }], details: {} });
// a folder is a text: a folder with shell text is quoted, never run
out.quoted = m.restartLine({ head, projects: m.projectsOf({ projects: [{ id: C, name: "x", folder: "/w/$(touch pwn) x", config: { accepted: false } }], details: {} }) });
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_add_a_project_model_reads_each_projects_folder_from_the_list_and_writes_no_placeholder(tmp_path):
    got = run_node(tmp_path, PROJECT_FOLDERS)
    head = "uv run --with keyring==25.7.0 python3 /opt/ck/runtime/service.py"
    assert got["projects"] == [{"id": "a" * 12, "name": "shop", "folder": "/work/shop"}, {"id": "b" * 12, "name": "blog", "folder": "/work/my blog"}], \
        "a project that is not accepted has its folder too"
    assert got["add"] == {"command": f"{head} --project /work/shop --project '/work/my blog' --project /work/new", "unknown": [], "empty": False}
    assert "<folder of" not in got["add"]["command"] and "<folder of" not in got["leave"]["command"]
    assert got["leave"] == {"command": f"{head} --project '/work/my blog'", "unknown": [], "empty": False}
    assert got["refusal"] == "That folder is already one of the service's projects.", "the folder of a project that is not accepted counts as held"
    assert got["both"][0]["folder"] == "/work/docs", "the service's own answer first"
    assert got["oldOnly"][0]["folder"] == "/work/docs", "without the key, the status path still gives it"
    assert got["nothing"][0]["folder"] is None, "a folder that is not a text is not one"
    assert got["quoted"]["command"] == f"{head} --project '/w/$(touch pwn) x'" and got["quoted"]["unknown"] == [], "quoted, never run"


# --- the files: nothing deleted that the rows keep, the cards wrap, the page builds no markup --------------------------------------

def _css() -> str:
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


def _rules(css: str):
    return [(sel.strip(), body) for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)]


def test_the_credentials_commands_are_fields_the_service_gives_and_the_page_reads_nothing_out_of_a_sentence():
    command = (JS / "frame" / "command.js").read_text(encoding="utf-8")
    assert "commandsIn" not in command and "STORE" not in command and "keyring" not in command, "A-22: the regular expression and the function that read a command out of a sentence are gone"
    for path in JS.rglob("*.js"):
        assert "commandsIn" not in path.read_text(encoding="utf-8"), f"{path.name} still calls commandsIn"
    assert "held[].commands" in (JS / "floor-model.js").read_text(encoding="utf-8") or "commands" in (JS / "floor-model.js").read_text(encoding="utf-8")


def test_the_image_viewer_builds_no_markup_no_data_url_no_srcdoc_and_the_client_reads_the_bytes_through_its_one_fetch_path():
    viewer = (JS / "floor" / "viewer.js").read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "srcdoc", "data:", "insertAdjacentHTML", "createElementNS", "DOMParser", "<svg", "document.write"):
        assert forbidden not in viewer, f"viewer.js uses {forbidden}"
    assert "createObjectURL" in viewer and "revokeObjectURL" in viewer and 'h("img"' in viewer
    client = (JS / "api.js").read_text(encoding="utf-8")
    assert client.count("fetch(") == 1, "the client has one fetch path"
    assert 'send("GET", `/projects/${enc(p)}/artifact/raw`' in client and "raw: true" in client
    route = next(r for r in service.ROUTES if r["pattern"] == "/projects/{p}/artifact/raw")
    assert route["method"] == "GET" and route["take"] == ("path",) and route["raw"] is True
    assert "img-src 'self' blob:" in service.CSP and "data:" not in service.CSP, "the page may show a blob it built and nothing from `data:`"


def test_every_route_the_adjustments_send_exists_and_the_sends_are_the_shapes_the_service_takes():
    client = (JS / "api.js").read_text(encoding="utf-8")
    routes = {(r["method"], r["pattern"]) for r in service.ROUTES}
    assert ("POST", "/projects/{p}/tasks/{id}/go-ahead") in routes and "/tasks/${enc(id)}/go-ahead" in client
    assert "go_ahead: goAhead" in client and "drop_after: dropAfter ? true : undefined" in client and "{ body: { text, flow, title, after }" in client
    ops = st.load("operations")
    approve = ops.by_name("approve")
    assert {"go_ahead"} <= {a["name"] for a in approve["args"]} and {a["name"]: a["kind"] for a in approve["args"]}["go_ahead"] == "list"
    assert "after" in {a["name"] for a in ops.by_name("request")["args"]}
    assert {"drop_after", "task_id"} == {a["name"] for a in ops.by_name("go-ahead")["args"]}
    assert "page" in ops.by_name("artifact-raw")["channels"]

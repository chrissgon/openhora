"""Tests of the Lobby of the local interface (interface/js/views/lobby*.js, interface/js/cards/plan*.js): the pure modules (the poll
interval, how the conversation and the requests are placed, the plan card's rows and limits line, the order of the calls that make
a request) and the modules' markup under a fake document, with the real client (interface/js/api.js) over a stand-in for `fetch`.
No browser, no model and no service. The Lobby itself was looked at in a browser pane against the real service by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_lobby.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from test_interface_floor import FAKE_DOM as FLOOR_DOM
from test_interface_scene import FAKE_DOM
from interface_css import interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
VIEWS = JS / "views"
CARDS = JS / "cards"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the pure modules are tested only by their text")

# What the fake document of the frame's tests lacks and the Lobby's modules use.
FAKE_EXTRA = r"""
FakeNode.prototype.insertBefore = function (node, ref) {
  if (node.parent) node.parent.children = node.parent.children.filter((c) => c !== node);
  node.parent = this;
  const at = ref ? this.children.indexOf(ref) : -1;
  if (at < 0) this.children.push(node); else this.children.splice(at, 0, node);
};
Object.defineProperty(FakeNode.prototype, "lastElementChild", { get() { return this.children[this.children.length - 1]; } });
Object.defineProperty(FakeNode.prototype, "options", { get() { return this.children; } });
Object.defineProperty(FakeNode.prototype, "tabIndex", { set(v) { this.attrs.tabindex = String(v); }, get() { return Number(this.attrs.tabindex || 0); } });
const setAttr = FakeNode.prototype.setAttribute;
FakeNode.prototype.setAttribute = function (n, v) { setAttr.call(this, n, v); if (n === "value") this.value = String(v); };
globalThis.Node = class { static [Symbol.hasInstance](x) { return x instanceof FakeNode || x instanceof FakeText; } };   // a text node is a Node
FakeNode.prototype.toggleAttribute = function (n, on) { if (on) this.attrs[n] = ""; else delete this.attrs[n]; };
export function click(node) { (node.listeners.click || []).forEach((fn) => fn({ preventDefault() {}, target: node })); }
export function press(node, init) { let stopped = false; (node.listeners.keydown || []).forEach((fn) => fn({ preventDefault() { stopped = true; }, ...init })); return stopped; }
export const textOf = (n) => n.textContent;
export const find = (root, pick) => [...root.walk()].filter(pick);
export const byClass = (root, name) => find(root, (n) => (n.attrs.class || "").split(/\s+/).includes(name));
"""


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FAKE_DOM + FAKE_EXTRA, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- the pure modules --------------------------------------------------------------------------------------------------------

MODEL = r"""
import * as m from "@JS@/views/lobby-model.js";
import * as rows from "@JS@/cards/plan-rows.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const ago = (hours) => new Date(NOW.getTime() - hours * 3600e3).toISOString();
const out = {};

out.poll = [m.pollInterval({ jobRunning: true, hidden: false }), m.pollInterval({ jobRunning: false, hidden: false }),
  m.pollInterval({ jobRunning: true, hidden: true }), m.pollInterval({ jobRunning: false, hidden: true })];
out.tabs = [m.tabOf({ tab: "inbox" }), m.tabOf({ tab: null }), m.tabOf({ tab: "nonsense" }), m.tabOf(null)];

const a = { id: 3, role: "user", text: "one", created_at: ago(4) };
const b = { id: 4, role: "assistant", text: "two", task_id: 14, created_at: ago(4) };
const c = { id: 6, role: "assistant", text: "three", task_id: 14, created_at: ago(1) };
const d = { id: 5, role: "assistant", text: "four", task_id: 9, created_at: ago(2) };
const merged = m.mergeMessages([b, a], [c, b, d]);
out.merged = merged.map((x) => x.id);
out.last = [m.lastId(merged), m.lastId([])];
out.meta = [m.metaOf(a, NOW), m.metaOf(b, NOW), m.nameOf(a, NOW), m.nameOf({ role: "assistant", created_at: ago(0) }, NOW)];

const requests = [{ id: 9, title: "Old", state: "done", tasks: [] }, { id: 14, title: "Spring campaign", state: "requested", tasks: [] },
  { id: 20, title: "Add a sale page", state: "requested", tasks: [] }, { id: 21, title: "Final", state: "cancelled", tasks: [] }, { id: 22, title: "Open", state: "planned", tasks: [{ id: 1, state: "ready" }] }];
const placed = m.placeBlocks(merged, requests);
out.placed = { byMessage: [...placed.byMessage.entries()], trailing: placed.trailing };
out.wanted = m.wantedBodies(placed, requests);
const many = Array.from({ length: 12 }, (_, i) => ({ id: 100 + i, title: "r", state: "planned", tasks: [] }));
const older = Array.from({ length: 12 }, (_, i) => ({ id: 100 + i, title: "r", state: "planned", tasks: [] }));
out.wantedOpen = m.wantedBodies(m.placeBlocks([], older), older, [{ id: 7, task_id: 100 }, { id: 8, task_id: 101 }]);
out.wantedCap = m.wantedBodies(m.placeBlocks([], many), many).length;
out.lobbyDecisions = m.lobbyDecisions({ pending: [{ id: 1, agent: null }, { id: 2, agent: "marketing" }, { id: 3, agent: "planning" }] }).map((p) => p.id);
out.line = [m.requestLine(requests[1], 0), m.requestLine(requests[1], 1).routable, m.requestLine(requests[0], 0).cancellable, m.requestLine(requests[4], 0).routable];
out.cancel = [m.cancelCount({ tasks: [] }), m.cancelCount({ tasks: [{ state: "planned" }, { state: "ready" }] }), m.cancelCount({ tasks: [{ state: "done" }, { state: "ready" }, { state: "running" }] }), m.cancelCount({ tasks: [{ state: "ready" }] })];
out.resolved = [m.resolvedWord({ kind: "plan", status: "resolved", resolution: "approved" }), m.resolvedWord({ kind: "question", status: "cancelled" }), m.resolvedWord({ kind: "review", status: "resolved", resolution: "released" })];
out.flows = m.flowOptions([{ flow: "brand", title: "Brand", tasks: 3 }, { flow: "broken", title: null, tasks: 0, error: "x" }, { flow: "code-change", title: "A code change, to its pull request", tasks: 2 }]);
out.flowsEmpty = m.flowOptions(undefined);
out.notices = [m.noticeFor({ status: 409, word: "busy", message: "job 3 is running for this project: a second one starts when it ends" }), m.noticeFor({ status: 409, word: "refused", message: "nothing was stored" }),
  m.noticeFor({ status: 500, word: "internal", message: "The service had an internal error." }, "job"), m.noticeFor(null, "job")];
out.room = [m.roomModel({ working: true, decisions: 1, hasMessages: true, accepted: true, request: null }).state, m.roomModel({ working: false, decisions: 2, hasMessages: true, accepted: true, request: null }).state,
  m.roomModel({ working: false, decisions: 0, hasMessages: false, accepted: true, request: null }).state, m.roomModel({ working: true, decisions: 0, hasMessages: true, accepted: false, request: null }).state];
out.roomShape = m.roomModel({ working: false, decisions: 2, hasMessages: true, accepted: true, request: { id: 14, title: "Spring campaign", state: "planned" } });
out.label = m.canvasLabel("northwind-shop", m.roomModel({ working: false, decisions: 1, hasMessages: true, accepted: true, request: null }));

const hash = "0123456789abcdef".repeat(4);
const plan = { id: 22, kind: "plan", title: "Plan: x (3 tasks)", body: "stored text", payload: { plan_sha256: hash, limits: { one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 }, estimate: { runs_at_least: 3 },
  tasks: [{ key: "a", title: "Build the page", skill: "eng-implement", depends_on: [], milestone: false, web: false, agent: "engineering" }, { key: "b", title: "Review", skill: "eng-review", depends_on: ["a"], milestone: true, web: true },
    { key: "c", title: "Publish", skill: "mkt-publish", depends_on: ["a", "b", "zz"], milestone: true, mandatory_milestone: true, web: false }] } };
out.planRows = rows.taskRows(plan);
out.limits = [rows.limitsLine(plan), rows.limitsLine({ payload: { limits: { one_task_at_a_time: false, timeout_seconds: 60, retries: 1 }, estimate: { runs_at_least: 1 } } }), rows.limitsLine({ payload: {} }), rows.limitsLine({})];
out.hash = [rows.planHash(plan), rows.planHash({ payload: { plan_sha256: "abc" } }), rows.planHash({}), rows.planText(plan)];
out.columns = rows.COLUMNS;
out.stacked = rows.stackedRow(rows.taskRows(plan)[0]);
out.failures = [rows.failureText({ status: 409, word: "busy", message: "x" }), rows.failureText({ status: 404, word: "not_found", message: "no" }), rows.failureText({ status: 409, word: "refused", message: "hash mismatch" }), rows.failureText(null)];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_lobby_reads_every_two_seconds_while_a_job_runs_and_never_otherwise_nor_while_hidden(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["poll"] == [2000, None, None, None], "WP-9.13: no standing poll; the page reloads when the store changes"
    assert got["tabs"] == ["inbox", "conversation", "conversation", "conversation"]
    source = (VIEWS / "lobby.js").read_text(encoding="utf-8")
    assert re.search(r"pollInterval\(\{ jobRunning: [^}]*hidden: document\.hidden \}\)", source), "the interval is chosen from the document's visibility"
    assert 'addEventListener("visibilitychange", onVisibility)' in source and "setInterval" not in source
    assert re.search(r"function onVisibility\(\) \{\s*if \(document\.hidden\) \{\s*clearTimeout\(timer\)", source), "hiding the document stops the timer; showing it reads at once"


@needs_node
def test_messages_are_merged_by_id_and_each_request_is_placed_under_the_newest_message_that_names_it_or_after_the_last_one(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["merged"] == [3, 4, 5, 6] and got["last"] == [6, 0]
    assert got["meta"] == ["You · 4 h ago", "Planning agent · 4 h ago", "You, 4 hours ago", "Planning agent, just now"]
    # request 14 is named by messages 4 and 6: its block goes under 6; 9 is named by 5 (final, still placed under its message);
    # 20 and 22 are named by none (made from the form): after the last message, oldest first; 21 is final: no trailing block
    assert sorted(got["placed"]["byMessage"]) == [[5, 9], [6, 14]] and got["placed"]["trailing"] == [20, 22]
    assert got["wanted"] == [22, 20, 14, 9], "the bodies read are the newest requests the conversation shows"
    assert got["wantedOpen"][:2] == [101, 100] and len(got["wantedOpen"]) == 8 and got["wantedOpen"][2:] == [111, 110, 109, 108, 107, 106], \
        "a request with an open decision is always read, even when it is older than the newest eight"
    assert got["wantedCap"] == 8
    assert got["lobbyDecisions"] == [1, 3], "a decision on a request (no agent) and the planning agent's own belong to the Lobby"


@needs_node
def test_the_request_line_the_cancel_dialogs_count_and_the_resolved_words_come_from_the_status_alone(tmp_path):
    got = run_node(tmp_path, MODEL)
    line = got["line"][0]
    assert line["title"] == "Spring campaign" and line["state"] == "Requested" and line["cancellable"] is True and line["routable"] is True
    assert line["name"] == "Request 14, Spring campaign, requested"
    assert got["line"][1] is False, "a request that has an open question is not offered a route"
    assert got["line"][2] is False and got["line"][3] is False, "a final request cannot be cancelled; a planned one waits for its plan, not a route"
    assert got["cancel"] == ["No task has been created yet.", "2 tasks, none started", "3 tasks, 2 started", "1 task, none started"]
    assert got["resolved"] == ["Plan approved", "Question cancelled", "Review released"]


@needs_node
def test_the_flow_select_is_the_planning_agents_own_route_then_one_option_per_flow_by_its_title_in_the_services_order(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["flows"] == [{"value": "", "label": "Let the planning agent route it"}, {"value": "brand", "label": "Brand"},
                            {"value": "code-change", "label": "A code change, to its pull request"}], "a flow file that failed its checks is not offered"
    assert got["flowsEmpty"] == [{"value": "", "label": "Let the planning agent route it"}]


@needs_node
def test_a_refused_turn_shows_the_drawings_words_and_any_other_refusal_its_own_message_and_the_room_follows_the_state(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["notices"][0] == {"title": "Not sent", "text": "A run is in progress for this project. Your message was not stored."}
    assert got["notices"][1] == {"title": "Not sent", "text": "nothing was stored"}
    assert got["notices"][2] == {"title": "The turn failed", "text": "The service had an internal error."}
    assert got["notices"][3]["title"] == "The turn failed"
    assert got["room"] == ["working", "waiting", "idle", "off"]
    shape = got["roomShape"]
    assert shape["door"] is True and shape["ready"] is True and shape["window"] == "lit" and shape["decisions"] == 2   # R-21: the room is lit while a decision waits
    assert shape["board"] == {"title": "Spring campaign", "lines": ["request #14 · planned"], "dot": "warn"}
    assert shape["tips"]["tray"] == "Inbox · 2 waiting" and shape["tips"]["agent"] == "Planning agent · waiting for you"
    assert got["label"] == "Lobby of northwind-shop, planning agent waiting, 1 decision, door to the Control room"


@needs_node
def test_the_plan_card_builds_its_table_limits_hash_and_text_from_the_payload_alone(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["columns"] == ["#", "Task", "Skill", "Agent", "After", "Milestone", "Web"]
    assert got["planRows"] == [
        {"n": "1", "task": "Build the page", "skill": "eng-implement", "agent": "engineering", "after": "-", "milestone": "no", "web": "no"},
        {"n": "2", "task": "Review", "skill": "eng-review", "agent": "-", "after": "1", "milestone": "yes", "web": "yes"},
        {"n": "3", "task": "Publish", "skill": "mkt-publish", "agent": "-", "after": "1, 2", "milestone": "yes (mandatory)", "web": "no"}]
    assert got["limits"] == ["One task at a time; each run at most 1800 s, retried at most 2 times. At least 3 runs.", "each run at most 60 s, retried at most 1 time. At least 1 run.", "", ""]
    assert got["hash"] == ["0123456789abcdef" * 4, "", "", "stored text"], "a hash that is not 64 hex characters is not shown as one"
    assert got["stacked"] == {"head": "1  Build the page", "skill": "eng-implement", "agent": "engineering", "tail": "After - · Milestone no · Web no"}
    assert got["failures"] == ["A model run is already going for this project. Nothing was started; try again when it ends.", "That item is not there any more.", "hash mismatch", "The request failed."]


# --- the client, the order of the calls, and what is sent --------------------------------------------------------------------

CALLS = r"""
import { setToken } from "@JS@/token.js";
import * as api from "@JS@/api.js";
import { createRequest, routeRequest, sendTurn, waitFor, worthSending } from "@JS@/views/lobby-actions.js";

setToken("t".repeat(40));
const sent = [];
let script = [];
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url, body: init.body === undefined ? null : JSON.parse(init.body) });
  const next = script.shift();
  const answer = next || { status: 200, body: {} };
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const out = {};

// 1. a request with a flow: `request` first with no flow key, then `route` with the flow
script = [{ status: 200, body: { request: 14, state: "requested", next: "route" } }, { status: 202, body: { job: 7, op: "route", state: "running" } }];
out.withFlow = await createRequest(api, "p1", { text: "Add a sale page", flow: "code-change", title: " Add a sale page " });
out.withFlowSent = sent.splice(0);

// 2. no flow chosen (the first option): `route` with no flow either
script = [{ status: 200, body: { request: 15, state: "requested", next: "route" } }, { status: 202, body: { job: 8, op: "route", state: "running" } }];
out.noFlow = await createRequest(api, "p1", { text: "Plan the launch", flow: "", title: "" });
out.noFlowSent = sent.splice(0);

// 3. empty text: nothing is sent
out.empty = await createRequest(api, "p1", { text: "  \n ", flow: "design", title: "" });
out.emptySent = sent.splice(0).length;

// 4. `route` refused as busy: the request exists, the answer says so
script = [{ status: 200, body: { request: 16, state: "requested", next: "route" } }, { status: 409, body: { error: "busy", message: "job 3 is running for this project: a second one starts when it ends" } }];
const busy = await createRequest(api, "p1", { text: "Another", flow: "brand", title: "" });
out.busy = { request: busy.request, started: busy.started === undefined, word: busy.error.word, status: busy.error.status, isBusy: busy.error.busy };
out.busySent = sent.splice(0).map((s) => s.url);

// 5. `request` itself refused: it throws, `route` is never called
script = [{ status: 400, body: { error: "usage", message: "the request's text is empty" } }];
try { await createRequest(api, "p1", { text: "x", flow: "design", title: "" }); out.requestThrown = false; } catch (e) { out.requestThrown = [e.status, e.word]; }
out.requestFailedSent = sent.splice(0).length;

// 6. "Route it" after a busy answer routes with the flow the person had chosen
script = [{ status: 202, body: { job: 9 } }];
out.again = await routeRequest(api, "p1", 16, "brand");
out.againSent = sent.splice(0);

// 7. a turn: the text exactly as typed, a command unchanged; a 409 busy is an ApiError with the word
script = [{ status: 202, body: { job: 10, op: "say", state: "running" } }];
out.turn = (await sendTurn(api, "p1", "  /help \n and more  ")).job;
out.turnSent = sent.splice(0);
script = [{ status: 409, body: { error: "busy", message: "job 10 is running for this project: a second one starts when it ends" } }];
try { await sendTurn(api, "p1", "second"); out.turnRefused = false; } catch (e) { out.turnRefused = [e.name, e.busy, e.status]; }
out.turnRefusedSent = sent.splice(0).length;

// 8. a job is asked for every second until it is done
let polls = 0;
script = [{ status: 200, body: { job: 10, state: "running" } }, { status: 200, body: { job: 10, state: "done", result: { reply: "ok" } } }];
const t0 = Date.now();
const done = await waitFor(api, { job: 10 });
out.waited = { state: done.state, reply: done.result.reply, seconds: Math.round((Date.now() - t0) / 1000), urls: sent.splice(0).map((s) => s.url) };
out.worth = [worthSending("hello"), worthSending("   "), worthSending(""), worthSending(null), worthSending(" / ")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_request_from_the_form_is_sent_without_a_flow_and_then_routed_with_it(tmp_path):
    got = run_node(tmp_path, CALLS)
    first, second = got["withFlowSent"]
    assert first == {"method": "POST", "url": "/api/v1/projects/p1/requests", "body": {"text": "Add a sale page", "title": "Add a sale page"}}
    assert "flow" not in first["body"], "a request with a flow readies its tasks with no approval of the plan: the form never sends one"
    assert second == {"method": "POST", "url": "/api/v1/projects/p1/requests/14/route", "body": {"flow": "code-change"}}
    assert got["withFlow"]["request"] == 14 and got["withFlow"]["started"]["job"] == 7
    first, second = got["noFlowSent"]
    assert first["body"] == {"text": "Plan the launch"} and "title" not in first["body"], "an empty title is not sent"
    assert second["url"].endswith("/requests/15/route") and second["body"] == {}, "the first option sends no flow to route either: the router plans it"


@needs_node
def test_empty_text_is_not_sent_and_a_busy_route_leaves_the_request_waiting_for_its_route(tmp_path):
    got = run_node(tmp_path, CALLS)
    assert got["empty"] == {"request": None, "empty": True} and got["emptySent"] == 0
    assert got["busy"] == {"request": 16, "started": True, "word": "busy", "status": 409, "isBusy": True}
    assert got["busySent"] == ["/api/v1/projects/p1/requests", "/api/v1/projects/p1/requests/16/route"]
    assert got["requestThrown"] == [400, "usage"] and got["requestFailedSent"] == 1, "a refused request is shown to the person and route is not called"
    assert got["againSent"] == [{"method": "POST", "url": "/api/v1/projects/p1/requests/16/route", "body": {"flow": "brand"}}]


@needs_node
def test_a_turn_sends_the_text_as_typed_and_a_second_turn_while_one_runs_is_a_busy_error_that_stores_nothing(tmp_path):
    got = run_node(tmp_path, CALLS)
    assert got["turnSent"] == [{"method": "POST", "url": "/api/v1/projects/p1/conversation", "body": {"text": "  /help \n and more  "}}], \
        "the page builds no prompt, summary or plan: the text is exactly as typed, a line that starts with / included"
    assert got["turn"] == 10
    assert got["turnRefused"] == ["ApiError", True, 409] and got["turnRefusedSent"] == 1
    assert got["waited"]["state"] == "done" and got["waited"]["reply"] == "ok" and got["waited"]["urls"] == ["/api/v1/jobs/10", "/api/v1/jobs/10"]
    assert got["waited"]["seconds"] >= 1, "a running job is asked for again after its period, not at once"
    assert got["worth"] == [True, False, False, False, True]


# --- the cards and the composer, under a fake document -----------------------------------------------------------------------------

CARD = r"""
import { FakeNode, accessibleName } from "@FAKE@";
import { click, press, find, byClass, textOf } from "@FAKE@";
import { createPlanCard } from "@JS@/cards/plan.js";
import { createBlock, createCancelDialog } from "@JS@/views/lobby-request.js";
import { createComposer } from "@JS@/views/lobby-composer.js";
import { createForm } from "@JS@/views/lobby-form.js";
import { createTabs } from "@JS@/views/lobby-tabs.js";
import { createThread } from "@JS@/views/lobby-thread.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const hash = "ab".repeat(32);
const out = {};
const tasks = [{ key: "a", title: "<b>Build</b> the page", skill: "eng-implement", depends_on: [], milestone: false, web: false }];
const item = (over = {}) => ({ id: 22, kind: "plan", title: "Plan: <i>x</i> (1 task)", body: "Source: <script>alert(1)</script>\nplan text", task_id: 14, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z",
  actions: ["approved", "rejected"], payload: { plan_sha256: hash, tasks, limits: { one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 }, estimate: { runs_at_least: 1 } }, ...over });
const calls = [];
const api = {
  approve: async (...a) => { calls.push(["approve", ...a]); return { job: 5 }; },
  reject: async (...a) => { calls.push(["reject", ...a]); return {}; },
  pollJob: async (id) => { calls.push(["poll", id]); return { state: "done", result: {} }; },
  cancel: async (...a) => { calls.push(["cancel", ...a]); return {}; },
};
const changed = [];
const onChanged = async () => { changed.push(1); };
const buttons = (root) => find(root, (n) => n.tagName === "BUTTON" && n.attrs["data-key"] !== "plain");   // the plan body's "Plain text" toggle (WP-9.17) is a view switch, not a word of `actions`

// the plan card: one button per word of `actions`, the whole hash shown, text as text, the hash sent is the hash shown
let card = createPlanCard({ api, project: "p1", item: item(), now: NOW, onChanged });
const words = buttons(card.el).map(textOf);
const shown = byClass(card.el, "wb-plan-hash")[0].textContent;
out.card = { words, shown, head: byClass(card.el, "wb-card-head")[0].textContent, title: byClass(card.el, "wb-card-title")[0].textContent,
  named: card.el.attrs["aria-labelledby"] === byClass(card.el, "wb-card-title")[0].attrs.id, caption: find(card.el, (n) => n.tagName === "CAPTION").map(textOf),
  headers: find(card.el, (n) => n.tagName === "TH").map(textOf), asText: find(card.el, (n) => (n.attrs.class || "").split(/\s+/).includes("wb-md")).map(textOf),
  elements: [...card.el.walk()].filter((n) => ["B", "I", "SCRIPT", "IMG"].includes(n.tagName)).length,
  taskCell: byClass(card.el, "wb-cell-task")[0].textContent, note: find(card.el, (n) => n.tagName === "SPAN" && textOf(n).startsWith("Note")).map(textOf) };
click(buttons(card.el)[0]);
await new Promise((r) => setTimeout(r, 20));
out.approve = { calls: calls.splice(0), changed: changed.length };
const withNote = createPlanCard({ api, project: "p1", item: item(), now: NOW, onChanged });
find(withNote.el, (n) => n.tagName === "INPUT")[0].value = "Not this week";
click(buttons(withNote.el)[1]);
await new Promise((r) => setTimeout(r, 20));
out.reject = calls.splice(0);
const noNote = createPlanCard({ api, project: "p1", item: item(), now: NOW, onChanged });
click(buttons(noNote.el)[1]);
await new Promise((r) => setTimeout(r, 20));
out.rejectNoNote = calls.splice(0);
out.onlyApprove = buttons(createPlanCard({ api, project: "p1", item: item({ actions: ["approved"] }), now: NOW, onChanged }).el).map(textOf);
out.none = [buttons(createPlanCard({ api, project: "p1", item: item({ actions: [] }), now: NOW, onChanged }).el).length, buttons(createPlanCard({ api, project: "p1", item: item({ actions: ["weird"] }), now: NOW, onChanged }).el).length];
const noHash = createPlanCard({ api, project: "p1", item: item({ payload: { tasks } }), now: NOW, onChanged });
out.noHash = { buttons: buttons(noHash.el).map(textOf), text: byClass(noHash.el, "wb-card-note").map(textOf).filter((t) => t.includes("no hash")) };

// failures: a refused approval shows its message above the buttons, enables them again and asks the host to read again
const refusing = { ...api, approve: async () => { throw Object.assign(new Error("the plan changed: its hash is not the one you approved"), { name: "ApiError", status: 409, word: "refused" }); } };
changed.length = 0;
const refused = createPlanCard({ api: refusing, project: "p1", item: item(), now: NOW, onChanged });
click(buttons(refused.el)[0]);
await new Promise((r) => setTimeout(r, 20));
const err = byClass(refused.el, "wb-card-error")[0];
out.refused = { text: err.textContent, shown: !err.hidden, role: err.attrs.role, enabled: buttons(refused.el).map((b) => !b.disabled), word: buttons(refused.el)[0].textContent, changed: changed.length };
const failing = { ...api, pollJob: async () => ({ state: "failed", error: { error: "refused", message: "the plan could not be approved", status: 409 } }) };
const failed = createPlanCard({ api: failing, project: "p1", item: item(), now: NOW, onChanged });
click(buttons(failed.el)[0]);
await new Promise((r) => setTimeout(r, 20));
out.jobFailed = byClass(failed.el, "wb-card-error")[0].textContent;

// the request line and the blocks
const request = { id: 14, title: "Spring campaign", state: "planned", tasks: [{ id: 30, state: "ready" }] };
const body = { task: request, runs: [], pending: [item(), { id: 21, kind: "question", title: "Which audience?", status: "open", created_at: "2026-10-08T09:00:00Z", actions: ["answered"] },
  { id: 19, kind: "plan", title: "Older plan", status: "resolved", resolution: "rejected", created_at: "2026-10-07T09:00:00Z", resolved_at: "2026-10-07T10:00:00Z" }] };
const cancelled = [];
const block = createBlock({ api, project: "p1", request, body, open: 2, now: NOW, onChanged, onCancel: (r) => cancelled.push(r.id), onRoute: () => {}, routing: false });
const names = (root, name) => byClass(root, name).map(textOf);
out.block = { line: names(block.el, "wb-lobby-request-line")[0], group: byClass(block.el, "wb-lobby-request-line")[0].attrs["aria-label"], plans: byClass(block.el, "wb-plan-card").length,
  resolved: names(block.el, "wb-lobby-resolved"), pointerLink: find(block.el, (n) => n.tagName === "A").map((n) => n.attrs.href).filter((h) => h.includes("inbox")) };
click(find(block.el, (n) => n.tagName === "BUTTON" && textOf(n) === "Cancel request")[0]);
out.cancelClicked = cancelled;
const final = createBlock({ api, project: "p1", request: { id: 9, title: "Old", state: "done", tasks: [] }, body: { pending: [] }, open: 0, now: NOW, onChanged, onCancel: () => {}, onRoute: () => {}, routing: false });
out.finalBlockButtons = buttons(final.el).length;
const waiting = createBlock({ api, project: "p1", request: { id: 20, title: "From the form", state: "requested", tasks: [] }, body: { pending: [] }, open: 0, now: NOW, onChanged, onCancel: () => {}, onRoute: () => {}, routing: false });
out.routeButton = buttons(waiting.el).filter((b) => !b.cls().includes("wb-lobby-request-title")).map(textOf);   // the title is a button too (A-1: it opens the whole text); these are the line's actions
const routingNow = createBlock({ api, project: "p1", request: { id: 20, title: "From the form", state: "requested", tasks: [] }, body: { pending: [] }, open: 0, now: NOW, onChanged, onCancel: () => {}, onRoute: () => {}, routing: true });
out.routing = find(routingNow.el, (n) => n.tagName === "BUTTON" && textOf(n) === "Routing...").map((b) => "disabled" in b.attrs);

// the cancel dialog: opens on "Keep it"; a failure shows its message and keeps the dialog; success closes it and reads again
calls.length = 0;
let closed = 0;
const dialog = createCancelDialog({ api, project: "p1", onChanged });
dialog.el.close = () => { closed += 1; };
dialog.open(request, "1 task, none started");
const dbuttons = buttons(dialog.el);
out.dialog = { heading: byClass(dialog.el, "wb-card-title")[0].textContent, sub: byClass(dialog.el, "wb-card-note")[0].textContent, buttons: dbuttons.map(textOf), labelled: dialog.el.attrs["aria-labelledby"] };
changed.length = 0;
click(dbuttons[1]);
await new Promise((r) => setTimeout(r, 20));
out.dialogCancel = { calls: calls.splice(0), closed, changed: changed.length };
const failingCancel = createCancelDialog({ api: { cancel: async () => { throw Object.assign(new Error("request 14 is done: nothing to cancel"), { name: "ApiError", status: 409, word: "refused" }); } }, project: "p1", onChanged });
failingCancel.el.close = () => { closed += 100; };
failingCancel.open(request, "x");
click(buttons(failingCancel.el)[1]);
await new Promise((r) => setTimeout(r, 20));
out.dialogRefused = { text: byClass(failingCancel.el, "wb-card-error")[0].textContent, closed, enabled: buttons(failingCancel.el).map((b) => !b.disabled) };
click(buttons(failingCancel.el)[0]);
out.keep = closed;

// the composer: Enter sends the text as typed, Shift+Enter makes a new line, the sending state, the refusal notice
const sentTexts = [];
const composer = createComposer({ onSend: (t) => sentTexts.push(t) });
const field = find(composer.el, (n) => n.tagName === "TEXTAREA")[0];
field.value = "  /help me  ";
const stopped = [press(field, { key: "Enter", shiftKey: false }), press(field, { key: "Enter", shiftKey: true }), press(field, { key: "Enter", isComposing: true }), press(field, { key: "a" })];
const submitButton = () => find(composer.el, (n) => n.tagName === "BUTTON")[0];
out.composer = { sent: sentTexts.slice(), stopped, label: find(composer.el, (n) => n.tagName === "SPAN").map(textOf).filter((t) => t.startsWith("Message")), hint: byClass(composer.el, "wb-lobby-hint")[0].textContent,
  button: submitButton().textContent, type: submitButton().attrs.type, placeholder: field.attrs.placeholder, described: field.attrs["aria-describedby"] };
composer.set({ sending: true, notice: null, disabled: false });
out.sending = { field: field.disabled, button: submitButton().disabled, word: submitButton().textContent, busyAttr: submitButton().attrs["aria-busy"], busyLine: byClass(composer.el, "wb-lobby-busy")[0].hidden, busyText: byClass(composer.el, "wb-lobby-busy")[0].textContent,
  busyAria: byClass(composer.el, "wb-lobby-busy")[0].attrs["aria-busy"], iconHidden: byClass(composer.el, "wb-icon")[0].hidden };
press(field, { key: "Enter", shiftKey: false });
out.sendingSentMore = sentTexts.length;
composer.set({ sending: false, notice: { title: "Not sent", text: "A run is in progress for this project. Your message was not stored." }, disabled: false });
const notice = byClass(composer.el, "wb-lobby-notice-card")[0];
out.refusedNotice = { text: notice.textContent, hidden: notice.hidden, role: notice.attrs.role, field: field.disabled, button: submitButton().textContent, kept: field.value };
composer.set({ sending: false, notice: null, disabled: true });
out.notAccepted = { field: field.disabled, button: submitButton().disabled, notice: notice.hidden };

// the form: closed by default, the example fields, the order of the controls, "Creating..."
const created = [];
const form = createForm({ onCreate: (v) => created.push(v) });
form.setFlows([{ flow: "brand", title: "Brand", tasks: 3 }, { flow: "design", title: "Design", tasks: 4 }]);
const labels = find(form.el, (n) => n.tagName === "LABEL").map((n) => n.children[0].textContent);
const select = find(form.el, (n) => n.tagName === "SELECT")[0];
out.form = { open: "open" in form.el.attrs, summary: find(form.el, (n) => n.tagName === "SUMMARY").map(textOf), labels, options: select.children.map((o) => [o.attrs.value, textOf(o)]),
  hint: byClass(form.el, "wb-form-hint")[0].textContent, button: find(form.el, (n) => n.tagName === "BUTTON").map(textOf) };
const textarea = find(form.el, (n) => n.tagName === "TEXTAREA")[0];
textarea.value = "Add a sale page, <b>please</b>";
select.value = "design";
(find(form.el, (n) => n.tagName === "FORM")[0].listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
out.created = created;
form.set({ creating: true });
out.creating = { button: find(form.el, (n) => n.tagName === "BUTTON")[0].textContent, disabled: [textarea.disabled, select.disabled], busy: byClass(form.el, "wb-lobby-busy")[0].hidden };
(find(form.el, (n) => n.tagName === "FORM")[0].listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
out.createdWhileCreating = created.length;
form.set({ creating: false, error: "the request's text is empty" });
out.formError = { text: byClass(form.el, "wb-card-error")[0].textContent, role: byClass(form.el, "wb-card-error")[0].attrs.role, enabled: !textarea.disabled };
form.markEmpty();
out.invalid = textarea.attrs["aria-invalid"];

// the tabs: the URL names the tab; arrows move, Home and End jump
const tabs = createTabs();
tabs.set({ project: "aaaaaaaaaaaa", selected: "conversation", counts: { inbox: 2 } });
const tabButtons = find(tabs.el, (n) => n.attrs.role === "tab");
out.tabs = { names: tabButtons.map((b) => b.attrs["aria-label"]), selected: tabButtons.map((b) => b.attrs["aria-selected"]), controls: tabButtons.map((b) => b.attrs["aria-controls"]), list: tabs.el.attrs.role };
tabButtons[1].listeners.click[0]();
out.clickHash = window.location.hash;
document.activeElement = tabButtons[4];      // the last tab, now that Tasks is the fourth
press(tabs.el, { key: "ArrowRight" });
out.wrap = window.location.hash;
press(tabs.el, { key: "End" });
out.end = window.location.hash;
press(tabs.el, { key: "Home" });
out.home = window.location.hash;
console.log(JSON.stringify(out));
"""

THREAD = r"""
import { FakeNode, find, byClass, textOf } from "@FAKE@";
import { createThread } from "@JS@/views/lobby-thread.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600e3).toISOString();
const api = { approve: async () => ({}), reject: async () => ({}), pollJob: async () => ({ state: "done" }), cancel: async () => ({}) };
const thread = createThread({ api, project: "p1", signal: undefined, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {} });
const out = {};
const hostile = "<img src=x onerror=alert(1)> **not bold** <script>alert(2)</script>";
const messages = [{ id: 1, role: "user", text: hostile, created_at: ago(4) }, { id: 2, role: "assistant", text: "I can plan it.", task_id: 14, created_at: ago(4) }];
const plan = { id: 22, kind: "plan", title: "Plan: x", status: "open", created_at: ago(4), actions: ["approved", "rejected"], payload: { plan_sha256: "cd".repeat(32), tasks: [] } };
const state = (over = {}) => ({ messages, requests: [{ id: 14, title: "Spring campaign", state: "planned", tasks: [] }], pending: [{ id: 22, task_id: 14 }], bodies: { 14: { pending: [plan] } }, now: NOW, loading: false, routing: new Set(), ...over });
thread.update(state({ messages: [], requests: [], pending: [], bodies: {}, loading: true }));
out.loading = thread.el.children.map(textOf);
thread.update(state({ messages: [], requests: [], pending: [], bodies: {} }));
out.empty = thread.el.children.map(textOf);
thread.update(state());
const first = [...thread.el.children];
out.order = thread.el.children.map((n) => n.attrs.class.split(" ")[0]);
out.live = [thread.el.attrs.role, thread.el.attrs["aria-live"], thread.el.attrs["aria-label"]];
out.hostile = { text: byClass(thread.el, "wb-bubble")[0].textContent, elements: [...thread.el.walk()].filter((n) => ["IMG", "SCRIPT"].includes(n.tagName)).length };
out.names = byClass(thread.el, "wb-msg").map((n) => n.attrs["aria-label"]);
out.metas = byClass(thread.el, "wb-msg-meta").map(textOf);
out.sides = byClass(thread.el, "wb-msg").map((n) => n.attrs.class);
// a poll that changed nothing touches no element
thread.update(state());
out.sameNodes = thread.el.children.every((n, i) => n === first[i]) && thread.el.children.length === first.length;
// the plan card is the same element while its decision is unchanged, and goes when the decision is resolved
const card = byClass(thread.el, "wb-plan-card")[0];
thread.update(state());
out.cardKept = byClass(thread.el, "wb-plan-card")[0] === card;
thread.update(state({ pending: [], bodies: { 14: { pending: [{ ...plan, status: "resolved", resolution: "approved", resolved_at: ago(0) }] } } }));
out.afterApprove = { cards: byClass(thread.el, "wb-plan-card").length, resolved: byClass(thread.el, "wb-lobby-resolved").map(textOf) };
// a new message arrives: appended, the earlier nodes stay
const before = [...thread.el.children].slice(0, 2);
thread.update(state({ messages: [...messages, { id: 3, role: "user", text: "And a banner?", created_at: ago(0) }], pending: [], bodies: { 14: { pending: [] } } }));
out.appended = [before[0] === thread.el.children[0], before[1] === thread.el.children[1], thread.el.children.length];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_plan_card_sends_exactly_the_hash_it_shows_one_button_per_word_of_actions_and_every_text_is_text(tmp_path):
    got = run_node(tmp_path, CARD)
    shown = "ab" * 32
    card = got["card"]
    assert card["words"] == ["Approve this plan", "Reject"] and card["shown"] == shown and len(card["shown"]) == 64, "the whole hash, 64 characters"
    assert card["head"].startswith("Plan#22 · request #14 · Lobby · ") and card["named"] is True and card["caption"] == ["Tasks"]
    assert card["headers"] == ["#", "Task", "Skill", "Agent", "After", "Milestone", "Web"]
    assert card["elements"] == 0, "a title or a body with markup is shown as typed, never as markup"
    assert card["title"] == "Plan: <i>x</i> (1 task)" and card["taskCell"] == "<b>Build</b> the page" and card["asText"] == ["Source: <script>alert(1)</script>\nplan text"]
    assert card["note"] == ["Note (optional, used when you reject)"]
    assert got["approve"]["calls"] == [["approve", "p1", 22, shown], ["poll", 5]] and got["approve"]["changed"] == 1, \
        "approve sends the hash displayed (the request body is {sha256: that hash}); the host reads again when the job ends"
    assert got["reject"] == [["reject", "p1", 22, "Not this week"]] and got["rejectNoNote"] == [["reject", "p1", 22, None]]
    assert got["onlyApprove"] == ["Approve this plan"] and got["none"] == [0, 0], "no button for a word the card does not know, none for no words"
    assert got["noHash"]["buttons"] == ["Reject"] and len(got["noHash"]["text"]) == 1, "a plan with no whole hash cannot be approved from the page"


@needs_node
def test_a_refused_approval_shows_its_message_above_the_buttons_enables_them_again_and_the_host_reads_again(tmp_path):
    got = run_node(tmp_path, CARD)
    assert got["refused"] == {"text": "the plan changed: its hash is not the one you approved", "shown": True, "role": "alert",
                              "enabled": [True, True], "word": "Approve this plan", "changed": 1}
    assert got["jobFailed"] == "the plan could not be approved", "a failed job shows its own message"


@needs_node
def test_the_request_line_the_open_card_the_pointer_and_the_resolved_line_and_the_cancel_dialog(tmp_path):
    got = run_node(tmp_path, CARD)
    block = got["block"]
    assert block["group"] == "Request 14, Spring campaign, planned" and block["plans"] == 1
    assert block["line"].startswith("#14Spring campaignPlanned") and block["line"].endswith("Cancel request")
    assert block["resolved"][-1] == "Plan rejected" or any(t.startswith("Plan rejected") for t in block["resolved"])
    assert any(t.startswith("Question") and "Which audience?" in t for t in block["resolved"]), "another open kind is a line that points at the Inbox"
    assert block["pointerLink"] == ["#/p/p1/lobby/inbox/21"]
    assert got["cancelClicked"] == [14] and got["finalBlockButtons"] == 0, "a request in a final state has no line and no button"
    assert got["routeButton"] == ["Cancel request", "Route it"] or got["routeButton"] == ["Route it", "Cancel request"]
    assert got["routing"] == [True], "while its route runs the button reads Routing... and is disabled"
    assert got["dialog"] == {"heading": "Cancel this request and what is still open under it?", "sub": "Request #14: Spring campaign · 1 task, none started",
                             "buttons": ["Keep it", "Cancel request"], "labelled": "wb-cancel-title"}
    assert got["dialogCancel"] == {"calls": [["cancel", "p1", 14]], "closed": 1, "changed": 1}
    assert got["dialogRefused"] == {"text": "request 14 is done: nothing to cancel", "closed": 1, "enabled": [True, True]}, "a refusal shows its message and the dialog stays"
    assert got["keep"] == 101, '"Keep it" closes the dialog and changes nothing'


@needs_node
def test_the_composer_sends_on_enter_not_on_shift_enter_and_draws_sending_refused_and_not_accepted(tmp_path):
    got = run_node(tmp_path, CARD)
    c = got["composer"]
    assert c["sent"] == ["  /help me  "], "Enter sends the text exactly as typed; Shift+Enter, a composing key and any other key do not"
    assert c["stopped"] == [True, False, False, False]
    assert c["label"] == ["Message to the planning agent"] and c["hint"] == "A line that starts with / is a command; /help lists them."
    assert c["button"] == "Send" and c["type"] == "submit" and c["placeholder"] == "Describe what you want done" and c["described"] == "wb-say-hint"
    s = got["sending"]
    assert s["field"] is True and s["button"] is True and s["word"] == "Sending..." and s["busyAttr"] == "true" and s["busyLine"] is False
    assert s["busyText"] == "The planning agent is working on this turn. It can take minutes." and s["busyAria"] == "true" and s["iconHidden"] is True
    assert got["sendingSentMore"] == 1, "nothing is sent while a turn runs"
    n = got["refusedNotice"]
    assert n["text"] == "Not sentA run is in progress for this project. Your message was not stored." and n["hidden"] is False and n["role"] == "alert"
    assert n["field"] is False and n["button"] == "Send" and n["kept"] == "  /help me  ", "the field is enabled and keeps its text"
    assert got["notAccepted"] == {"field": True, "button": True, "notice": True}


@needs_node
def test_the_new_request_form_is_closed_by_default_in_the_drawn_order_and_reports_what_was_typed(tmp_path):
    got = run_node(tmp_path, CARD)
    f = got["form"]
    assert f["open"] is False and f["summary"] == ["New request"]
    assert f["labels"] == ["What do you want done?", "Flow", "Title (optional)", "After request # (optional)"] and f["button"] == ["Create request"]       # A-29: the field after the title
    assert f["options"] == [["", "Let the planning agent route it"], ["brand", "Brand"], ["design", "Design"]]
    assert f["hint"] == "A flow plans the request from a predefined route. Without one, the planning agent routes it."
    assert got["created"] == [{"text": "Add a sale page, <b>please</b>", "flow": "design", "title": ""}], "the form reports the typed text, the chosen flow and the title"
    assert got["creating"] == {"button": "Creating...", "disabled": [True, True], "busy": False} and got["createdWhileCreating"] == 1
    assert got["formError"] == {"text": "the request's text is empty", "role": "alert", "enabled": True} and got["invalid"] == "true"


@needs_node
def test_the_tab_list_names_the_tab_in_the_url_and_moves_with_the_arrows(tmp_path):
    got = run_node(tmp_path, CARD)
    t = got["tabs"]
    assert t["list"] == "tablist" and t["names"] == ["Conversation", "Inbox, 2 waiting", "Desk", "Tasks", "Agent"]
    assert t["selected"] == ["true", "false", "false", "false", "false"] and len(set(t["controls"])) == 5
    assert got["clickHash"] == "#/p/aaaaaaaaaaaa/lobby/inbox" and got["wrap"] == "#/p/aaaaaaaaaaaa/lobby/conversation"
    assert got["end"] == "#/p/aaaaaaaaaaaa/lobby/agent" and got["home"] == "#/p/aaaaaaaaaaaa/lobby/conversation"


@needs_node
def test_the_conversation_log_is_drawn_by_keys_a_poll_that_changed_nothing_touches_no_element_and_a_reply_is_text(tmp_path):
    got = run_node(tmp_path, THREAD)
    assert got["loading"] == ["Loading the conversation..."] and got["empty"] == ["No messages yet. Describe what you want done."]
    assert got["order"] == ["wb-msg", "wb-msg", "wb-request-block"]
    assert got["live"] == ["log", "polite", "Conversation with the planning agent"]
    assert got["hostile"]["text"] == "<img src=x onerror=alert(1)> **not bold** <script>alert(2)</script>" and got["hostile"]["elements"] == 0
    assert got["names"] == ["You, 4 hours ago", "Planning agent, 4 hours ago"] and got["metas"] == ["You · 4 h ago", "Planning agent · 4 h ago"]
    assert got["sides"] == ["wb-msg is-user", "wb-msg is-agent"], "the person's line on one side, the planning agent's on the other"
    assert got["sameNodes"] is True and got["cardKept"] is True
    assert got["afterApprove"] == {"cards": 0, "resolved": ["Plan approved" + "Plan: x · just now"]}
    assert got["appended"] == [True, True, 4]


# --- rules read from the files ---------------------------------------------------------------------------------------------------


def lobby_files():
    return sorted([*VIEWS.glob("lobby*.js"), *CARDS.glob("plan*.js")])


def test_the_lobby_files_exist_and_only_they_call_the_routes_that_write(tmp_path):
    names = {p.name for p in lobby_files()}
    assert names >= {"lobby.js", "lobby-model.js", "lobby-actions.js", "lobby-composer.js", "lobby-form.js", "lobby-request.js", "lobby-tabs.js",
                     "lobby-thread.js", "lobby-scene.js", "plan.js", "plan-rows.js"}
    for icon in ("send", "message-square"):
        assert (INTERFACE / "icons" / f"{icon}.svg").is_file() and f'"{icon}"' in (JS / "frame" / "icons.js").read_text(encoding="utf-8")
        assert f".wb-icon-{icon} " in interface_css()
    source = "\n".join(p.read_text(encoding="utf-8") for p in lobby_files())
    called = set(re.findall(r"\bapi\.(\w+)\(", source))
    assert called >= {"say", "request", "route", "cancel", "approve", "reject", "conversation", "flows", "task", "pollJob"}
    exported = set(re.findall(r"^export (?:async )?function (\w+)", (JS / "api.js").read_text(encoding="utf-8"), re.M))
    assert called <= exported, f"the Lobby calls {sorted(called - exported)}, which api.js does not export"
    assert not re.search(r"\bfetch\(", source), "the client is the one fetch path"


def test_the_form_never_names_a_flow_in_its_request_call_and_the_page_builds_no_prompt():
    actions = (VIEWS / "lobby-actions.js").read_text(encoding="utf-8")
    request_call = re.search(r"api\.request\(([^)]*)\)", actions)
    assert request_call and "flow" not in request_call.group(1), "`request` is never given a flow: it would ready tasks with no approval of the plan"
    assert "api.route(" in actions and actions.index("api.request(") < actions.index("api.route("), "request first, then route"
    lobby = (VIEWS / "lobby.js").read_text(encoding="utf-8")
    assert "sendTurn(api, project, text" in lobby, "a turn is the text as typed"
    assert not re.search(r"sendTurn\([^)]*(trim|replace|\+|`)", lobby), "nothing is added to or taken from the person's line before it is sent"


def test_the_plan_card_sends_the_displayed_hash_and_draws_no_button_for_a_word_it_does_not_know():
    card = (CARDS / "plan.js").read_text(encoding="utf-8")
    assert "const shown = planHash(item);" in card and "api.approve(project, item.id, shown)" in card, "the hash sent is the hash shown"
    assert 'text: shown })' in card, "the hash is displayed whole, as text"
    assert 'actions.includes("approved")' in card and 'actions.includes("rejected")' in card
    assert "innerHTML" not in card


def test_the_lobby_modules_take_no_style_and_no_colour_and_load_nothing_from_another_host():
    css = interface_css()
    section = css[css.index("the Lobby (handoff lobby.md"):]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", section), "the Lobby's rules set no colour of their own"
    for path in lobby_files():
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"https?://|\sstyle\s*[:=]", text) and "innerHTML" not in text, f"{path.name}"


def test_the_room_builder_draws_the_lobbys_door_and_its_label_only_when_the_model_asks_for_one():
    world = (JS / "scene" / "world.js").read_text(encoding="utf-8")
    assert "room.door" in world and 'id: "lobby-door"' in world and 'id: "door-label"' in world and "doorNode" in world
    scene = (VIEWS / "lobby-scene.js").read_text(encoding="utf-8")
    assert 'id === "lobby-door"' in scene, "a click on the door goes to the Control room"


# --- WP-9.4b: the Inbox, Desk and Agent tabs are the Floor's modules with the planning agent ---------------------------------------


def run_floor_node(tmp_path: Path, body: str) -> dict:
    """Like run_node, with the Floor's fake document (it can look nodes up by selector, which the Floor's modules need)."""
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FLOOR_DOM, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


TABS_MODEL = r"""
import * as m from "@JS@/views/lobby-model.js";
import * as fm from "@JS@/floor-model.js";
import * as router from "@JS@/router.js";

const P = "0123456789ab";
const out = {};

// the Desk lists every document of the project (C-2); the agent of each is a column
const rows = [{ path: "a", agent: null }, { path: "b", agent: "planning" }, { path: "c", agent: "marketing" }, { path: "d" }, { path: "e", agent: "brand" }];
out.documents = m.lobbyDocuments(rows).map((d) => d.path);
out.documentsOf = [m.lobbyDocuments(undefined), m.lobbyDocuments(null), m.lobbyDocuments([null, { path: "x", agent: null }]).length];

// the Inbox's split: request 1 is named by a message of the planning agent, request 2 was made from the form, request 3 holds a question
const messages = [{ id: 1, role: "user", text: "x" }, { id: 2, role: "assistant", text: "y", task_id: 1 }];
const status = {
  requests: [{ id: 1, title: "Spring", state: "planned", tasks: [] }, { id: 2, title: "Sale page", state: "requested", tasks: [] }, { id: 3, title: "Refresh", state: "ready", tasks: [{ id: 6, agent: "planning", state: "waiting" }] }],
  pending: [{ id: 10, kind: "plan", task_id: 1, agent: null }, { id: 11, kind: "plan", task_id: 2, agent: null }, { id: 12, kind: "question", task_id: 3, agent: null },
            { id: 13, kind: "review", task_id: 6, agent: "planning" }, { id: 14, kind: "effect", task_id: 7, agent: "marketing" }, { id: 15, kind: "plan", task_id: 1, agent: null }],
};
const parts = m.inboxParts(status, messages);
out.parts = { cards: parts.cards.map((p) => p.id), pointers: parts.pointers.map((p) => p.id) };
out.noMessages = m.inboxParts(status, []).pointers.length;
out.named = [m.isNamed(messages, 1), m.isNamed(messages, 2), m.isNamed([{ role: "user", task_id: 2 }], 2)];
out.partsOfNothing = [m.inboxParts(null, []).cards.length, m.inboxParts({}, messages).pointers.length];

// the room: the Desk's documents are the sheets and the drawers; unread, the cabinet is empty as before
const base = { working: false, decisions: 1, hasMessages: true, accepted: true, request: null };
const none = m.roomModel(base);
const docs = Array.from({ length: 9 }, (_, i) => ({ path: `docs/n${i}.md` }));
const withDocs = m.roomModel({ ...base, documents: docs });
out.room = { none: [none.drawers, none.sheets, none.tips.cabinet], with: [withDocs.drawers, withDocs.sheets.length, withDocs.sheets[0], withDocs.tips.cabinet],
  one: m.roomModel({ ...base, documents: [docs[0]] }).tips.cabinet, zero: [m.roomModel({ ...base, documents: [] }).drawers, m.roomModel({ ...base, documents: [] }).tips.cabinet] };

// the Floor's model finds the planning agent only when the Lobby asks
const task = (id, state, agent) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "core-clarify", state, note: null, agent });
const st = { requests: [{ id: 3, title: "Refresh", state: "ready", tasks: [task(4, "running", "planning"), task(5, "failed", "planning"), task(6, "ready", "engineering")] }],
  pending: [{ id: 12, kind: "question", task_id: 3, agent: null, created_at: "2026-10-08T10:00:00Z", actions: ["answered"] }, { id: 13, kind: "review", task_id: 4, agent: "planning", created_at: "2026-10-08T10:00:00Z", actions: ["released"] },
            { id: 14, kind: "effect", task_id: 6, agent: "engineering", created_at: "2026-10-08T10:00:00Z", actions: ["approved"] }], documents: [] };
const agent = (name, mode = "supervised") => ({ name, pack: "x", enabled: true, mode, acting_mode: mode, max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 2, usd_today: 0.5, runs_without_cost: 0, queued: 0 });
const snapshot = { projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], details: { [P]: { status: st, agents: [agent("planning"), agent("engineering")] } }, tasks: {}, loaded: true };
out.floorDefault = fm.floor(snapshot, P, "planning", {}).found;
const lobby = fm.floor(snapshot, P, "planning", {}, { lobby: true });
out.floorLobby = { found: lobby.found, tasks: lobby.tasks.map((t) => t.id), decisions: lobby.decisions.map((d) => d.id), current: lobby.current.id, target: lobby.target.id, state: lobby.row.state, mode: lobby.agent.mode, none: lobby.view.none };
out.floorOthers = [fm.floor(snapshot, P, "engineering", {}).found, fm.floor(snapshot, P, "engineering", {}, { lobby: true }).decisions.map((d) => d.id), fm.floor(snapshot, P, "nobody", {}, { lobby: true }).found];
const bare = fm.floor({ ...snapshot, details: { [P]: { status: st, agents: [] } } }, P, "planning", {}, { lobby: true });
out.floorNoAgents = [bare.found, bare.view.none, bare.agent.mode];
out.unaccepted = fm.floor({ ...snapshot, projects: [{ id: P, name: "northwind-shop", config: { accepted: false } }], details: {} }, P, "planning", {}, { lobby: true }).notAccepted;

// the hash of a document of the Lobby's Desk
const hash = router.lobbyDeskHash(P, "docs/notes/kickoff.md");
const parsed = router.parse(hash);
out.hash = [hash, parsed.screen, parsed.tab, parsed.path, parsed.pending, router.lobbyDeskHash(P), router.parse(router.lobbyDeskHash(P)).path];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_desk_shows_every_document_of_the_project(tmp_path):
    got = run_node(tmp_path, TABS_MODEL)
    assert got["documents"] == ["a", "b", "c", "d", "e"], "C-2: every document, whoever's it is: the Lobby is the project's room"
    assert got["documentsOf"] == [[], [], 1], "an unread list is empty, and a row that is not an object is dropped"


@needs_node
def test_the_inbox_and_the_conversation_split_the_decisions_so_that_no_plan_card_is_drawn_twice(tmp_path):
    got = run_node(tmp_path, TABS_MODEL)
    # the plan of request 1 is under the message that names it: the Inbox points there (10 and 15); the plan of request 2 (made from the
    # form) has its card in the Inbox, with the question on a request and the planning agent's own review; another agent's effect is not the Lobby's
    assert got["parts"] == {"cards": [11, 12, 13], "pointers": [10, 15]}
    assert got["noMessages"] == 0, "with no message naming a request, every plan has its card in the Inbox"
    assert got["named"] == [True, False, False], "only a message of the planning agent names a request"
    assert got["partsOfNothing"] == [0, 0]


@needs_node
def test_the_room_draws_the_desks_documents_and_the_floors_model_finds_the_planning_agent_only_for_the_lobby(tmp_path):
    got = run_node(tmp_path, TABS_MODEL)
    assert got["room"]["none"] == [None, None, "Documents · open the Desk tab"], "unread: unknown (the world keeps what the table shows, an empty cabinet at first), never an empty list that would clear it"
    assert got["room"]["with"] == [3, 6, {"path": "docs/n0.md", "tip": "docs/n0.md"}, "9 documents · open the Desk tab"]
    assert got["room"]["one"] == "1 document · open the Desk tab" and got["room"]["zero"] == [1, "0 documents · open the Desk tab"]
    assert got["floorDefault"] is False, "the Floor's own call still finds no floor of the planning agent"
    assert got["floorLobby"] == {"found": True, "tasks": [5, 4], "decisions": [12, 13], "current": 4, "target": 5, "state": "waiting", "mode": "supervised", "none": False}, \
        "the planning agent's decisions are those on a request and its own; another agent's tasks are not its tasks"
    assert got["floorOthers"] == [True, [14], False], "an area agent is read as before, with or without the option"
    assert got["floorNoAgents"] == [True, True, None] and got["unaccepted"] is True
    assert got["hash"][:5] == ["#/p/0123456789ab/lobby/desk/docs%2Fnotes%2Fkickoff.md", "lobby", "desk", "docs/notes/kickoff.md", None]
    assert got["hash"][5:] == ["#/p/0123456789ab/lobby/desk", None]


TABS_MARKUP = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createLobbyInbox } from "@JS@/views/lobby-inbox.js";
import { createLobbyDesk } from "@JS@/views/lobby-desk.js";
import { createLobbyAgent, NO_AGENT_TEXT } from "@JS@/views/lobby-agent.js";
import * as fm from "@JS@/floor-model.js";

setToken("t".repeat(40));
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const sent = [];
const answers = new Map();
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url, body: init.body === undefined ? null : JSON.parse(init.body) });
  const key = `${init.method} ${url}`;
  const answer = answers.get(key) || { status: 200, body: {} };
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const out = {};
const hash = "cd".repeat(32);
const plan = (id, task_id, over = {}) => ({ id, kind: "plan", title: `Plan: <i>${id}</i>`, body: "text", task_id, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z", actions: ["approved", "rejected"],
  payload: { plan_sha256: hash, tasks: [{ key: "a", title: "Build", skill: "eng-implement", depends_on: [] }], limits: { one_task_at_a_time: true, timeout_seconds: 60, retries: 1 }, estimate: { runs_at_least: 1 } }, ...over });
const question = { id: 12, kind: "question", title: "Which pages?", body: "Order list or detail?", task_id: 3, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z", actions: ["answered"], payload: {} };
answers.set(`GET /api/v1/projects/${P}/pending/11`, { status: 200, body: plan(11, 2) });
answers.set(`GET /api/v1/projects/${P}/pending/12`, { status: 200, body: question });
answers.set(`POST /api/v1/projects/${P}/pending/11/approve`, { status: 202, body: { job: 9 } });
answers.set(`GET /api/v1/jobs/9`, { status: 200, body: { job: 9, state: "done", result: {} } });

// --- the Inbox: the Floor's cards for the decisions it was given, a line for a plan that lives in the Conversation ---
let refreshed = 0;
const inbox = createLobbyInbox({ project: P, now: () => NOW, refresh: () => { refreshed += 1; } });
const pointer = plan(10, 1);
const data = (over = {}) => ({ cards: [plan(11, 2), question], pointers: [pointer], requests: [{ id: 2 }, { id: 3 }], resolved: [], selected: null, loading: false, ...over });
inbox.update(data());
await settle();
inbox.update(data());
const cards = all(inbox.el, "article");
out.inbox = {
  cards: cards.map((c) => c.querySelector(".wb-card-head").textContent.replace(/ ·.*/, "")), planTables: all(inbox.el, "table.wb-plan-table").length, lobbyPlanCards: all(inbox.el, ".wb-plan-card").length,
  pointer: all(inbox.el, ".wb-pointer").map((n) => n.textContent), pointerLinks: all(inbox.el, ".wb-pointer a").map((a) => a.attrs.href),
  hashShown: find(inbox.el, "[data-hash=plan]").textContent, links: all(inbox.el, ".wb-card-head a").map((a) => a.attrs.href),
  markup: [...inbox.el.walk()].filter((n) => ["I", "B", "SCRIPT"].includes(n.tagName)).length,
};
// the approve button of the Floor's card, pressed in the Lobby, sends exactly the hash the card shows, through the one client
find(inbox.el, "button[data-word=approved]").click();
await new Promise((r) => setTimeout(r, 1300));
out.approve = { sent: sent.filter((s) => s.method === "POST"), refreshed: refreshed > 0 };
sent.length = 0;
// when only the pointer remains, the empty line says so
const lone = createLobbyInbox({ project: P, now: () => NOW, refresh: () => {} });
lone.update(data({ cards: [] }));
out.onlyPointer = [find(lone.el, ".wb-empty-line").textContent, all(lone.el, "article").length, all(lone.el, ".wb-pointer").length];
const empty = createLobbyInbox({ project: P, now: () => NOW, refresh: () => {} });
empty.update(data({ cards: [], pointers: [] }));
out.empty = [find(empty.el, ".wb-empty-line").textContent, all(empty.el, ".wb-pointer").length];

// --- the Desk: the Floor's table over every row `artifacts` returned, with the agent of each as a column (C-2) ---
const doc = (path, agent, owner = null) => ({ path, owner, agent, size: 12, modified_at: "2026-10-08T09:00:00Z", bound: false });
answers.set(`GET /api/v1/projects/${P}/artifacts`, { status: 200, body: { artifacts: [doc("docs/notes/kickoff.md", null), doc("docs/workbench/briefs/a.md", "planning", "core-clarify"), doc("docs/brand/voice.md", "brand", "brand-voice"), doc("docs/marketing/x.md", "marketing", "mkt-x")], truncated: false } });
let read = 0;
const opened = [];
const desk = createLobbyDesk({ project: P, open: (p) => opened.push(p), changed: () => { read += 1; } });
desk.update({ tab: "desk", ready: true });
out.deskBefore = find(desk.el, ".wb-desk-states").textContent;
await settle();
out.desk = { read, rows: all(desk.el, "button.wb-path-button").map((b) => b.attrs["data-path"]), owners: all(desk.el, ".wb-desk-owner").map((n) => n.textContent), agents: all(desk.el, ".wb-desk-agent").map((n) => n.textContent), rowsOf: desk.rows().map((d) => d.path) };
find(desk.el, "button.wb-path-button").click();
out.opened = opened;
desk.update({ tab: "desk", ready: true });
out.askedOnce = sent.filter((s) => s.url.endsWith("/artifacts")).length;
const failing = createLobbyDesk({ project: P, open: () => {}, changed: () => {} });
answers.set(`GET /api/v1/projects/${P}/artifacts`, { status: 500, body: { error: "internal", message: "the documents could not be listed" } });
failing.update({ tab: "desk", ready: true });
await settle();
out.deskError = find(failing.el, ".wb-desk-states").textContent;

// --- the Agent tab: the Floor's, for the planning agent ---
const agentRow = (name, mode = "supervised") => ({ name, pack: "x", enabled: true, mode, acting_mode: mode, max_runs_per_day: 12, max_usd_per_day: 2, runs_today: 3, usd_today: 0.25, runs_without_cost: 0, queued: 1 });
const task = (id, state, agent = "planning", extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "core-clarify", state, note: null, agent, ...extra });
const status = { requests: [{ id: 3, title: "Refresh", state: "ready", tasks: [task(4, "running"), task(5, "failed"), task(6, "ready", "engineering")] }], pending: [{ id: 12, kind: "question", task_id: 3, agent: null }, { id: 13, kind: "review", task_id: 4, agent: "planning" }], documents: [] };
const snapshot = (agents, accepted = true) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted } }], details: accepted ? { [P]: { status, agents } } : {}, tasks: {}, loaded: true });
answers.set(`GET /api/v1/projects/${P}/tasks/4`, { status: 200, body: { task: task(4, "running"), runs: [{ id: 1, skill: "core-clarify", skill_version: "1.0.0", model: "m", status: "running", attempts: 1, started_at: "2026-10-08T10:30:00Z" }], pending: [] } });
answers.set(`GET /api/v1/projects/${P}/tasks/5`, { status: 200, body: { task: task(5, "failed"), runs: [], pending: [] } });
answers.set(`POST /api/v1/projects/${P}/agents/planning/mode`, { status: 200, body: { agent: "planning", mode: "milestones", config_sha256: "f".repeat(64), accepted: false, next: "accept-config --project demo" } });
answers.set(`POST /api/v1/projects/${P}/tasks/5/retry`, { status: 200, body: {} });
let changed = 0;
const agent = createLobbyAgent({ project: P, now: () => NOW, refresh: () => {}, changed: () => { changed += 1; } });
const snap = snapshot([agentRow("planning"), agentRow("engineering")]);
agent.update({ snapshot: { ...snap, loaded: false }, tab: "agent" });
out.agentLoading = find(agent.el, ".wb-busy").textContent;
const model = agent.update({ snapshot: snap, tab: "agent" });
await settle();
agent.update({ snapshot: snap, tab: "agent" });
out.agent = {
  model: [model.found, model.decisions.map((d) => d.id), model.tasks.map((t) => t.id)], state: find(agent.el, ".wb-state-row").textContent, plate: find(agent.el, ".wb-mode-row").textContent,
  meters: all(agent.el, ".wb-meter-cell").map((c) => c.attrs["aria-label"]), current: find(agent.el, ".wb-current").textContent.slice(0, 60), others: all(agent.el, ".wb-other").map((o) => o.textContent),
  reads: sent.filter((s) => s.url.includes("/tasks/")).map((s) => s.url.split("/").pop()), changed: changed > 0, hand: find(agent.el, ".wb-hint").textContent,
  none: find(agent.el, ".wb-lobby-none").hidden, form: find(agent.el, "button.wb-set-mode").textContent,
};
// Stop agent sends one request, for the planning agent, with its word (A-17)
find(agent.el, "button[data-key=stop-agent]").click();
await settle();
out.setMode = sent.filter((s) => s.method === "POST").map((s) => [s.url, s.body]);
sent.length = 0;
find(agent.el, "button[data-key=retry-5]").click();
await settle();
out.retry = sent.filter((s) => s.method === "POST").map((s) => [s.url, s.body]);
// a project with no agent in its configuration, and one that is not accepted
const bare = createLobbyAgent({ project: P, now: () => NOW, refresh: () => {}, changed: () => {} });
bare.update({ snapshot: snapshot([]), tab: "agent" });
out.bare = [find(bare.el, ".wb-lobby-none").hidden, find(bare.el, ".wb-lobby-none").textContent === NO_AGENT_TEXT, find(bare.el, ".wb-agent-tab").hidden];
const unaccepted = createLobbyAgent({ project: P, now: () => NOW, refresh: () => {}, changed: () => {} });
out.unaccepted = [unaccepted.update({ snapshot: snapshot([], false), tab: "agent" }) !== null, all(unaccepted.el, ".wb-empty-line").map((n) => [n.textContent, n.hidden])];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_lobbys_inbox_draws_the_floors_cards_for_its_decisions_and_a_line_for_the_plan_kept_in_the_conversation(tmp_path):
    got = run_floor_node(tmp_path, TABS_MARKUP)
    inbox = got["inbox"]
    assert inbox["cards"] == ["Plan#11", "Question#12"] and inbox["planTables"] == 1 and inbox["lobbyPlanCards"] == 0, "the Floor's cards, one card for each decision it was given: the plan of a request made from the form and the question"
    assert len(inbox["pointer"]) == 1 and inbox["pointer"][0].startswith("PlanPlan: <i>10</i>") and inbox["pointer"][0].endswith("Open in the Conversation")
    assert inbox["pointerLinks"] == ["#/p/0123456789ab/lobby"], "the line points at the Conversation, where that plan's card is"
    assert inbox["hashShown"] == "cd" * 32 and inbox["markup"] == 0, "the whole hash, and a title with markup is text"
    assert inbox["links"][:2] == ["#/p/0123456789ab/lobby", "#/p/0123456789ab/lobby"], "a decision on a request links to the Lobby, not to a floor"
    approve = got["approve"]
    assert approve["sent"] == [{"method": "POST", "url": "/api/v1/projects/0123456789ab/pending/11/approve", "body": {"sha256": "cd" * 32}}], \
        "the Floor's card sends the hash it shows, through the one client"
    assert approve["refreshed"] is True, "the Lobby is asked to read again"
    assert got["onlyPointer"] == ["Nothing else waits for you here.", 0, 1], "a plan kept in the Conversation is not a card here and the empty line does not say that nothing waits"
    assert got["empty"] == ["Nothing waits for you on this floor.", 0]


@needs_node
def test_the_lobbys_desk_is_the_floors_table_over_every_document_with_the_agent_as_a_column(tmp_path):
    got = run_floor_node(tmp_path, TABS_MARKUP)
    assert got["deskBefore"] == "Loading the floor..."
    assert got["desk"]["rows"] == ["docs/brand/voice.md", "docs/marketing/x.md", "docs/notes/kickoff.md", "docs/workbench/briefs/a.md"], "C-2: the brand's and the marketing agent's documents are on this desk too (same time: by path)"
    assert got["desk"]["rowsOf"] == ["docs/notes/kickoff.md", "docs/workbench/briefs/a.md", "docs/brand/voice.md", "docs/marketing/x.md"] and got["desk"]["read"] == 1
    assert got["desk"]["owners"] == ["brand-voice", "mkt-x", "", "core-clarify"]
    assert got["desk"]["agents"] == ["brand", "marketing", "—", "planning"], "the Agent column: the agent of each row, a dash when null"
    assert got["opened"] == ["docs/brand/voice.md"], "a row asks to open its path; the viewer reads the file"
    assert got["askedOnce"] == 1, "a second update inside the period reads nothing"
    assert got["deskError"] == "The documents could not be readthe documents could not be listed"


@needs_node
def test_the_lobbys_agent_tab_is_the_floors_for_the_planning_agent_and_sends_one_request_for_it(tmp_path):
    got = run_floor_node(tmp_path, TABS_MARKUP)
    agent = got["agent"]
    assert got["agentLoading"] == "Loading the floor..."
    assert agent["model"] == [True, [12, 13], [5, 4]], "its decisions are those on a request and its own; the engineering agent's task is not its task"
    assert agent["state"].startswith("Waiting for you") and "2 decisions in the Inbox" in agent["state"]
    assert agent["plate"].startswith("supervised") and "Every review reaches you" in agent["plate"]
    assert agent["meters"] == ["Runs today 3 / 12", "Spend today $0.25 / $2.00", "Queued 1"]
    assert agent["current"].startswith("#4 Task 4Running") and agent["others"] == ["#5 Task 5FailedRetry"]
    assert agent["reads"] == ["4", "5"], "the running task's body is read; the others' only while the Inbox is open, and the task a file would go to (here the failed 5) once, for its file-drop line (A-30)"
    assert agent["changed"] is True and agent["none"] is True and agent["form"] == "Stop agent"
    assert got["setMode"] == [["/api/v1/projects/0123456789ab/agents/planning/mode", {"mode": "stopped"}]]
    assert got["retry"] == [["/api/v1/projects/0123456789ab/tasks/5/retry", {}]]
    assert got["bare"] == [False, True, True], "a project with no agent in its configuration says so and shows no form"
    assert got["unaccepted"] == [True, [["This project has no agents in its configuration.", True], ["Waiting for the configuration to be accepted.", False]]], \
        "a project that is not accepted shows the waiting line and not the line about agents"


BLOCKS = r"""
import { FakeNode, find, byClass, textOf } from "@FAKE@";
import { createBlock } from "@JS@/views/lobby-request.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const hash = "ab".repeat(32);
const plan = { id: 22, kind: "plan", title: "Plan: x", body: "t", task_id: 14, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z", actions: ["approved", "rejected"],
  payload: { plan_sha256: hash, tasks: [{ key: "a", title: "Build", skill: "eng-implement", depends_on: [] }], limits: { timeout_seconds: 60, retries: 1 }, estimate: { runs_at_least: 1 } } };
const api = { approve: async () => ({ job: 1 }), reject: async () => ({}), pollJob: async () => ({ state: "done" }), cancel: async () => ({}) };
const request = { id: 14, title: "Spring", state: "planned", tasks: [] };
const make = (viaMessage) => createBlock({ api, project: "p1", request, body: { pending: [plan] }, open: 1, now: NOW, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {}, routing: false, viaMessage });
const out = {};
const under = make(true);
const form = make(false);
const dflt = createBlock({ api, project: "p1", request, body: { pending: [plan] }, open: 1, now: NOW, onChanged: async () => {}, onCancel: () => {}, onRoute: () => {}, routing: false });
out.underMessage = { cards: byClass(under.el, "wb-plan-card").length, pointers: byClass(under.el, "wb-pointer").length };
out.fromForm = { cards: byClass(form.el, "wb-plan-card").length, pointers: byClass(form.el, "wb-pointer").map(textOf), links: find(form.el, (n) => n.tagName === "A").map((a) => a.attrs.href), line: byClass(form.el, "wb-lobby-request-line").length };
out.default = byClass(dflt.el, "wb-plan-card").length;
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_plan_has_its_card_under_the_message_that_names_its_request_and_in_the_inbox_for_a_request_made_from_the_form(tmp_path):
    got = run_node(tmp_path, BLOCKS)
    assert got["underMessage"] == {"cards": 1, "pointers": 0}
    assert got["fromForm"]["cards"] == 0 and got["fromForm"]["line"] == 1, "the request line stays; the card is in the Inbox"
    assert got["fromForm"]["pointers"] == ["PlanPlan: x · 4 h agoOpen in the Inbox"] and got["fromForm"]["links"] == ["#/p/p1/lobby/inbox/22"]
    assert got["default"] == 1, "a block drawn with no placement is the one under a message, as before"


# --- the Lobby's view itself, under a fake document and a frame of stand-ins: the wiring of the tabs, the route's end, the room's clicks ----

VIEW_EXTRA = r"""
const define = (name, desc) => { if (!(name in FakeNode.prototype)) Object.defineProperty(FakeNode.prototype, name, desc); };
define("dataset", { get() { return this._ds || (this._ds = {}); } });
define("lastElementChild", { get() { return this.children[this.children.length - 1]; } });
define("options", { get() { return this.children; } });
if (!FakeNode.prototype.insertBefore) FakeNode.prototype.insertBefore = function (node, ref) {
  if (node.parent) node.parent.children = node.parent.children.filter((c) => c !== node);
  node.parent = this;
  const at = ref ? this.children.indexOf(ref) : -1;
  if (at < 0) this.children.push(node); else this.children.splice(at, 0, node);
};
if (!FakeNode.prototype.toggleAttribute) FakeNode.prototype.toggleAttribute = function (n, on) { if (on) this.attrs[n] = ""; else delete this.attrs[n]; };
"""

VIEW = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createLobbyView } from "@JS@/views/lobby.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };   // the fake's is empty
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const sent = [];
const answers = new Map();
let conversation = () => ({ messages: [] });
globalThis.fetch = async (url, init) => {
  sent.push({ method: init.method, url, body: init.body === undefined ? null : JSON.parse(init.body) });
  let answer;
  if (url.includes("/conversation")) answer = { status: 200, body: await conversation() };
  else answer = answers.get(`${init.method} ${url.split("?")[0]}`) || { status: 200, body: {} };
  return { ok: answer.status < 400, status: answer.status, json: async () => answer.body };
};
const hash = "cd".repeat(32);
const plan = { id: 5, kind: "plan", title: "Plan: sale page", body: "text", task_id: 2, agent: null, status: "open", created_at: "2026-10-08T08:00:00Z", actions: ["approved", "rejected"],
  payload: { plan_sha256: hash, tasks: [{ key: "a", title: "Build", skill: "eng-implement", depends_on: [] }], limits: { timeout_seconds: 60, retries: 1 }, estimate: { runs_at_least: 1 } } };
const A = (path) => `/api/v1/projects/${P}${path}`;
answers.set(`GET ${A("/flows")}`, { status: 200, body: { flows: [{ flow: "design", title: "Design", tasks: 3 }] } });
answers.set(`GET ${A("/tasks/2")}`, { status: 200, body: { task: { id: 2 }, runs: [], pending: [plan] } });
answers.set(`GET ${A("/pending/5")}`, { status: 200, body: plan });
answers.set(`POST ${A("/requests")}`, { status: 200, body: { request: 2, state: "requested", next: "route" } });
answers.set(`POST ${A("/requests/2/route")}`, { status: 202, body: { job: 7 } });
answers.set(`GET /api/v1/jobs/7`, { status: 200, body: { job: 7, state: "done", result: { routed: true, pending_id: 5 } } });
answers.set(`GET ${A("/artifacts")}`, { status: 200, body: { artifacts: [{ path: "docs/notes/a.md", owner: null, agent: null, size: 4, modified_at: "2026-10-08T09:00:00Z", bound: false }], truncated: false } });
answers.set(`GET ${A("/artifact")}`, { status: 200, body: { path: "docs/notes/a.md", text: "<b>hi</b>", size: 4, modified_at: "2026-10-08T09:00:00Z" } });

const agent = (name) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0 });
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("planning")], status: { requests: [{ id: 2, title: "Sale page", state: "requested", tasks: [] }], pending: [{ id: 5, kind: "plan", title: "Plan: sale page", task_id: 2, agent: null, created_at: "2026-10-08T08:00:00Z" }] } } } };
const makeFrame = () => ({ el: new FakeNode("div"), main: new FakeNode("main"), sceneHost: new FakeNode("div"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), sceneUnavailable() {}, announce(text) { announced.push(text); },
  acquireWorld: () => ({ show() {}, setOptions() {}, flyTo: () => Promise.resolve(false), stats() { return {}; } }), kpis: { el: new FakeNode("div") } });
const announced = [];
const hashOf = () => window.location.hash;
const route = (h) => router.parse(`#/p/${P}/lobby${h}`);
const press = (type, init) => (document.listeners[type] || []).forEach((fn) => fn({ preventDefault() {}, ...init }));
const submit = (root) => (find(root, "form").listeners.submit || []).forEach((fn) => fn({ preventDefault() {} }));
const out = {};

async function create(frame, view, route0) {
  const textarea = frame.main.querySelector(".wb-new-request textarea");
  textarea.value = "Add a sale page, linked from the home page.";
  submit(frame.main.querySelector(".wb-new-request"));
  await new Promise((r) => setTimeout(r, 250));
}
const fresh = () => { announced.length = 0; sent.length = 0; window.location.hash = `#/p/${P}/lobby`; };

// 1. a request made from the form: when its route ends, no message names it, so its plan card is in the Inbox and the page opens it
conversation = () => ({ messages: [] });
fresh();
let frame = makeFrame();
let view = createLobbyView(frame, { project: P, onChanged: async () => {} });
view.update({ snapshot, route: route(""), now: NOW, projectName: "northwind-shop" });
await settle();
await create(frame, view);
out.fromForm = { hash: hashOf(), requestBody: sent.filter((s) => s.method === "POST" && s.url === A("/requests")).map((s) => s.body), routeBody: sent.filter((s) => s.url === A("/requests/2/route")).map((s) => s.body) };
view.dispose();

// 2. the same end while a read of the conversation is running: the router's message is read before the place is chosen, so a named plan stays in the Conversation
let calls = 0;
conversation = async () => {
  calls += 1;
  if (calls === 1) { await new Promise((r) => setTimeout(r, 1200)); return { messages: [] }; }
  return { messages: [{ id: 1, role: "assistant", text: "I can plan it.", task_id: 2, created_at: "2026-10-08T08:00:00Z" }] };
};
fresh();
frame = makeFrame();
view = createLobbyView(frame, { project: P, onChanged: async () => {} });
view.update({ snapshot, route: route(""), now: NOW, projectName: "northwind-shop" });     // the first read starts here and is slow
await create(frame, view);
await new Promise((r) => setTimeout(r, 2500));
out.named = { hash: hashOf(), planCards: all(frame.main, ".wb-plan-card").length, conversationReads: calls };
view.dispose();

// 3. before the conversation was read no plan is drawn as a card in the Inbox; once it was, the plan with no message is the Inbox's card
conversation = async () => { await new Promise((r) => setTimeout(r, 600)); return { messages: [] }; };
fresh();
frame = makeFrame();
view = createLobbyView(frame, { project: P, onChanged: async () => {} });
view.update({ snapshot, route: route("/inbox"), now: NOW, projectName: "northwind-shop" });
await new Promise((r) => setTimeout(r, 150));
out.beforeRead = { cards: all(frame.main, ".wb-lobby-inbox article").length, text: frame.main.querySelector(".wb-lobby-inbox").textContent };
await new Promise((r) => setTimeout(r, 1200));
out.afterRead = { cards: all(frame.main, ".wb-lobby-inbox article").length };

// 4. the room's clicks open the tabs
const opened = [];
for (const id of ["tray", "cabinet", "agent", "board", "desk", "sheet:docs/notes/a.md", "lobby-door", "nonsense"]) {
  window.location.hash = "#/";
  view.open(id);
  opened.push(hashOf());
}
out.scene = opened;

// 5. a document takes the panel's place (Escape is the frame's one handler, tested in test_interface_scene_round3.py)
view.update({ snapshot, route: route("/desk/" + encodeURIComponent("docs/notes/a.md")), now: NOW, projectName: "northwind-shop" });
await new Promise((r) => setTimeout(r, 300));
const panel = frame.main.querySelector(".wb-panel-lobby");
const host = frame.main.querySelector(".wb-viewer-host");
out.viewer = { inline: panel.cls().includes("is-viewing"), hostHidden: host.hidden, head: frame.main.querySelector(".wb-panel-head").hidden, tabsHidden: frame.main.querySelector(".wb-lobby-tabs").hidden, text: host.textContent.includes("<b>hi</b>"), artifactReads: sent.filter((s) => s.url.startsWith(A("/artifact") + "?")).length };
view.update({ snapshot, route: route("/desk"), now: NOW, projectName: "northwind-shop" });
out.closed = { inline: panel.cls().includes("is-viewing"), hostHidden: host.hidden, head: frame.main.querySelector(".wb-panel-head").hidden, tabs: frame.main.querySelector(".wb-lobby-tabs").hidden };
view.dispose();
out.disposed = (document.listeners.keydown || []).length;

// 6. on a phone the document is a dialog and the panel keeps its tabs
window.matchMedia = () => ({ matches: true, addEventListener() {}, removeEventListener() {} });
frame = makeFrame();
view = createLobbyView(frame, { project: P, onChanged: async () => {} });
view.update({ snapshot, route: route("/desk/" + encodeURIComponent("docs/notes/a.md")), now: NOW, projectName: "northwind-shop" });
await new Promise((r) => setTimeout(r, 300));
const dialog = frame.el.querySelector("dialog.wb-viewer-dialog");
out.phone = { dialogOpen: dialog.open, inline: frame.main.querySelector(".wb-panel-lobby").cls().includes("is-viewing"), tabsHidden: frame.main.querySelector(".wb-lobby-tabs").hidden };
view.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


def run_view_node(tmp_path: Path, body: str) -> dict:
    fake = tmp_path / "fake-dom.mjs"
    fake.write_text(FLOOR_DOM + VIEW_EXTRA, encoding="utf-8")
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", fake.as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_the_lobby_view_opens_the_inbox_for_a_plan_from_the_form_and_keeps_a_named_plan_in_the_conversation(tmp_path):
    got = run_view_node(tmp_path, VIEW)
    form = got["fromForm"]
    assert form["requestBody"] == [{"text": "Add a sale page, linked from the home page."}] and form["routeBody"] == [{}], "request without a flow, then route"
    assert form["hash"] == "#/p/0123456789ab/lobby/inbox/5", "no message names the request: its plan card is in the Inbox, which opens on it"
    named = got["named"]
    assert named["hash"] == "#/p/0123456789ab/lobby", "the router's message was read before the place was chosen: the plan stays under it"
    assert named["planCards"] == 1 and named["conversationReads"] >= 2


@needs_node
def test_before_the_conversation_is_read_no_plan_is_drawn_as_a_card_in_the_inbox(tmp_path):
    got = run_view_node(tmp_path, VIEW)
    assert got["beforeRead"]["cards"] == 0 and "Loading" in got["beforeRead"]["text"]
    assert got["afterRead"]["cards"] == 1, "a plan no message names is the Inbox's card once the conversation is known"


@needs_node
def test_a_click_in_the_room_opens_the_tab_the_handoff_names(tmp_path):
    got = run_view_node(tmp_path, VIEW)
    p = "#/p/0123456789ab/lobby"
    # one object per destination (WP-9.8): the tray the Inbox, the figure the Agent tab, the desk the Desk tab, a sheet its document; the cabinet and the board open nothing
    assert got["scene"] == [f"{p}/inbox", "#/", f"{p}/agent", "#/", f"{p}/desk", f"{p}/desk/docs%2Fnotes%2Fa.md", "#/", "#/"]


@needs_node
def test_a_document_takes_the_panels_place_and_gives_it_back_and_on_a_phone_it_is_a_dialog(tmp_path):
    got = run_view_node(tmp_path, VIEW)
    assert got["viewer"] == {"inline": True, "hostHidden": False, "head": True, "tabsHidden": True, "text": True, "artifactReads": 1}, "the file is read once and shown as text"
    assert got["closed"] == {"inline": False, "hostHidden": True, "head": False, "tabs": False}
    assert got["disposed"] == 0, "the view takes its keyboard listener away"
    assert got["phone"] == {"dialogOpen": True, "inline": False, "tabsHidden": False}

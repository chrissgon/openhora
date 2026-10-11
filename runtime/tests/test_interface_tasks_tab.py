"""Tests of the Tasks tab of a floor (WP-9.16; interface/js/floor/tasks-model.js, tasks-tab.js, run-block.js): what the pure model
decides (the groups and their order, the actions each state allows, the paths a done task returned, the age, the failure line,
the Lobby's filter) and what the tab draws and sends under a fake document with the real client over a stand-in for `fetch`
(the expand reads `task` once, Retry goes through the environment's client, a path opens only under docs/, a poll never takes
the focus away). No browser, no model and no service. The page itself was looked at in a browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_tasks_tab.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st
from test_interface_floor import INTERFACE, needs_node, run_node

TAB = INTERFACE / "js" / "floor" / "tasks-tab.js"
MODEL_FILE = INTERFACE / "js" / "floor" / "tasks-model.js"
BLOCK = INTERFACE / "js" / "floor" / "run-block.js"

# --- the pure model ------------------------------------------------------------------------------------------------------------

MODEL = r"""
import * as tm from "@JS@/floor/tasks-model.js";
import * as fm from "@JS@/floor-model.js";
import * as router from "@JS@/router.js";

const NOW = new Date("2026-10-08T12:00:00Z");
const task = (id, state, agent = "engineering", extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "eng-implement", state, note: null, agent, requestId: 1, ...extra });
const out = {};

// the groups: the order of the spec, newest first inside a group, an empty group has a count of 0
const all = [task(1, "done"), task(2, "failed"), task(3, "blocked"), task(4, "planned"), task(5, "ready"), task(6, "running"), task(7, "waiting"),
  task(8, "cancelled"), task(9, "done"), task(10, "ready"), task(11, "requested")];
const groups = tm.groupTasks(all);
out.order = groups.map((g) => g.id);
out.labels = groups.map((g) => g.label);
out.counts = groups.map((g) => g.count);
out.ids = groups.map((g) => g.tasks.map((t) => t.id));
out.empty = tm.groupTasks([]).map((g) => [g.id, g.count]);
out.unknown = tm.groupTasks([task(1, "sleeping")]).map((g) => [g.id, g.count]).filter((p) => p[1] > 0);

// the actions each state allows
const pending = [{ id: 31, kind: "question", task_id: 99, agent: "engineering" }, { id: 32, kind: "review", task_id: 7, agent: "engineering" }, { id: 33, kind: "question", task_id: 7, agent: "engineering" }];
out.actions = Object.fromEntries(["requested", "planned", "ready", "running", "waiting", "blocked", "done", "failed", "cancelled"].map((s) => [s, tm.actionsFor(task(7, s), pending)]));
out.waitingNoDecision = tm.actionsFor(task(8, "waiting"), pending);

// the Lobby's filter and the Floor's, over the model's own rule (a task with no agent is the planning agent's)
const status = { requests: [{ id: 1, title: "R", state: "ready", tasks: [task(2, "ready", null), task(3, "done", "planning"), task(4, "ready", "brand"), task(5, "failed", "engineering")] }, { id: 2, title: "S", state: "ready", tasks: [task(6, "running", null)] }], pending: [] };
out.lobby = fm.agentTasks(status, "planning").map((t) => [t.id, t.requestId]);
out.brand = fm.agentTasks(status, "brand").map((t) => t.id);

// the paths a done task returned: the newest review's, "Open" only for a path under docs/
const review = (id, returned, extra = {}) => ({ id, kind: "review", status: "resolved", payload: { returned }, ...extra });
out.returned = {
  one: tm.returnedPaths({ pending: [review(1, [{ path: "docs/a.md" }, { path: "notes/b.md" }, { path: "docs/../x" }]), { id: 2, kind: "question", payload: {} }] }),
  newest: tm.returnedPaths({ pending: [review(1, [{ path: "docs/a.md" }]), review(3, [{ path: "docs/c.md" }])] }).map((p) => p.path),
  none: [tm.returnedPaths({ pending: [review(1, [])] }), tm.returnedPaths({ pending: [] }), tm.returnedPaths(null), tm.returnedPaths({ pending: [review(1, ["docs/a.md", 7, null])] })],
};

// the age: the newest run's start for a running task, else the task's last change, else its creation; "-" when no time is known
const body = (extra = {}) => ({ task: { created_at: "2026-10-08T08:00:00Z", updated_at: "2026-10-08T11:00:00Z" }, runs: [{ id: 1, started_at: "2026-10-08T11:30:00Z", status: "running" }], pending: [], ...extra });
out.age = [
  tm.ageStamp(task(1, "running"), body()), tm.ageStamp(task(1, "done"), body()), tm.ageStamp(task(1, "done"), body({ task: { created_at: "2026-10-08T08:00:00Z" } })),
  tm.ageStamp(task(1, "running"), body({ runs: [] })), tm.ageStamp(task(1, "done"), null), tm.ageStamp(task(1, "done"), { task: {} }),
];
out.rowAge = [tm.rowOf(task(1, "running"), { requests: [], pending: [], body: body(), now: NOW }).age, tm.rowOf(task(1, "done"), { requests: [], pending: [], body: null, now: NOW }).age];

// the failure line of a failed task: the failure word of its newest run and that run's ending
const failedBody = (run) => ({ task: { updated_at: "2026-10-08T11:00:00Z" }, runs: [{ id: 1, status: "failed", failure: "adapter" }, run], pending: [] });
out.failure = [
  tm.failureLine(failedBody({ id: 2, status: "failed", failure: "timeout", ending: null })),
  tm.failureLine(failedBody({ id: 2, status: "failed", failure: "refused", ending: "question" })),
  tm.failureLine(failedBody({ id: 2, status: "failed", failure: null, ending: null })),
  tm.failureLine({ task: {}, runs: [], pending: [] }), tm.failureLine(null),
];

// a row: every fact, from the status row, the request, the decisions and the body
const requests = [{ id: 1, title: "Spring <b>sale</b>", state: "ready" }];
const row = tm.rowOf(task(5, "failed", "engineering", { note: "The run timed out", title: "Build <i>page</i>" }), { requests, pending, body: failedBody({ id: 2, status: "failed", failure: "timeout" }), now: NOW });
out.row = { number: row.number, title: row.title, skill: row.skill, word: row.word, tone: row.tone, request: row.request, note: row.note, actions: row.actions, failure: row.failure, runs: row.runs.map((r) => r.id), age: row.age };
const lone = tm.rowOf(task(6, "ready", "engineering", { requestId: 77 }), { requests, pending: [], body: null, now: NOW });
out.noRequest = lone.request;
out.bareTitle = tm.rowOf(task(8, "ready", "engineering", { title: "" }), { requests, pending: [], body: null, now: NOW }).title;

// the tab is named by the router
out.route = [router.parse(router.floorHash("0123456789ab", "brand", "tasks")).tab, router.parse(router.lobbyHash("0123456789ab", "tasks")).tab, router.floorHash("0123456789ab", "brand", "tasks"),
  router.lobbyHash("0123456789ab", "inbox", null), router.floorHash("0123456789ab", "brand", "inbox", null)];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_groups_follow_the_specs_order_newest_first_and_an_empty_group_has_a_count_of_zero(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["order"] == ["running", "waiting", "ready", "planned", "done", "failed", "cancelled"]
    assert got["labels"] == ["Running", "Waiting for you", "Ready (queued)", "Planned or blocked", "Done", "Failed", "Cancelled"]
    assert got["counts"] == [1, 1, 2, 3, 2, 1, 1]
    assert got["ids"] == [[6], [7], [10, 5], [11, 4, 3], [9, 1], [2], [8]], "newest first inside a group; blocked, planned and requested share one group"
    assert got["empty"] == [["running", 0], ["waiting", 0], ["ready", 0], ["planned", 0], ["done", 0], ["failed", 0], ["cancelled", 0]]
    assert got["unknown"] == [["other", 1]], "a state the closed list does not know is shown, in a group of its own"


@needs_node
def test_retry_is_offered_on_failed_and_blocked_and_the_inbox_when_a_decision_waits_and_nothing_else(tmp_path):
    got = run_node(tmp_path, MODEL)
    actions = got["actions"]
    assert actions["failed"] == [{"kind": "retry"}] and actions["blocked"] == [{"kind": "retry"}]
    assert actions["waiting"] == [{"kind": "inbox", "pending": 32}], "the task's oldest open decision, not another task's"
    for state in ("requested", "planned", "ready", "running", "done", "cancelled"):
        assert actions[state] == [], f"no action on a {state} task (no cancel here: cancel is the request's)"
    assert got["waitingNoDecision"] == [{"kind": "inbox", "pending": None}], "a task that waits with no decision found still points at the Inbox"


@needs_node
def test_the_lobby_takes_the_tasks_with_no_agent_and_the_planning_agents_and_a_floor_only_its_own(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["lobby"] == [[6, 2], [3, 1], [2, 1]], "agent null and agent planning, newest first, each with its request"
    assert got["brand"] == [4]


@needs_node
def test_a_done_task_shows_the_paths_its_newest_review_returned_and_open_only_under_docs(tmp_path):
    got = run_node(tmp_path, MODEL)["returned"]
    assert got["one"] == [{"path": "docs/a.md", "openable": True}, {"path": "notes/b.md", "openable": False}, {"path": "docs/../x", "openable": False}]
    assert got["newest"] == ["docs/c.md"]
    assert got["none"] == [[], [], [], []], "no review, an empty list, no body and entries that are not a path show no paths"


@needs_node
def test_the_age_comes_from_the_run_or_the_task_and_is_a_dash_when_no_time_is_known(tmp_path):
    got = run_node(tmp_path, MODEL)
    assert got["age"] == ["2026-10-08T11:30:00Z", "2026-10-08T11:00:00Z", "2026-10-08T08:00:00Z", "2026-10-08T11:00:00Z", "", ""]
    assert got["rowAge"] == ["30 min ago", "—"]


@needs_node
def test_a_failed_task_shows_its_failure_word_and_the_last_runs_ending(tmp_path):
    got = run_node(tmp_path, MODEL)["failure"]
    assert got[0] == {"failure": "Timed out", "ending": ""}
    assert got[1] == {"failure": "Refused", "ending": "Asked a question"}
    assert got[2] == {"failure": "Failed", "ending": ""}
    assert got[3] is None and got[4] is None


@needs_node
def test_a_row_carries_the_number_the_title_the_skill_the_request_and_the_actions_as_text(tmp_path):
    got = run_node(tmp_path, MODEL)
    row = got["row"]
    assert row["number"] == "#5" and row["title"] == "Build <i>page</i>" and row["skill"] == "eng-implement"
    assert row["word"] == "Failed" and row["tone"] == "pui-error pui-soft"
    assert row["request"] == {"id": 1, "title": "Spring <b>sale</b>", "label": "Request #1 Spring <b>sale</b>"}
    assert row["note"] == "The run timed out" and row["actions"] == [{"kind": "retry"}]
    assert row["failure"] == {"failure": "Timed out", "ending": ""} and row["runs"] == [2, 1], "the runs are newest first"
    assert got["noRequest"] is None and got["bareTitle"] == "k8", "a task without a title shows its key"
    assert got["route"][:3] == ["tasks", "tasks", "#/p/0123456789ab/floor/brand/tasks"]


# --- the tab under a fake document ------------------------------------------------------------------------------------------------

TAB_MARKUP = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
import { ApiError } from "@JS@/api.js";

setToken("t".repeat(40));
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const calls = [];
const bodies = new Map();
globalThis.fetch = async (url, init) => {
  calls.push(`${init.method} ${url}`);
  const m = String(url).match(/\/tasks\/(\d+)$/);
  const body = m ? bodies.get(Number(m[1])) : null;
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body || { error: "not_found", message: "no" } };
};
const reads = (id) => calls.filter((c) => c === `GET /api/v1/projects/${P}/tasks/${id}`).length;
const text = (n) => n.textContent;
const task = (id, state, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "eng-implement", state, note: null, agent: "engineering", requestId: 1, ...extra });
const run = (id, extra = {}) => ({ id, skill: "eng-implement", skill_version: "1.0.0", model: "model-a", status: "ok", ending: "done", attempts: 1, started_at: "2026-10-08T11:00:00Z", duration_ms: 42000, tokens: 1200, cost_usd: 0.1, ...extra });
const body = (t, runs, pending = []) => ({ task: { id: t.id, state: t.state, created_at: "2026-10-08T08:00:00Z", updated_at: "2026-10-08T10:00:00Z" }, runs, pending });
const out = {};
const sentRetry = [];
let retryFails = false;
let refreshed = 0;
const env = {
  project: P, now: () => NOW, refresh: () => { refreshed += 1; },
  api: { retry: async (p, id) => { sentRetry.push([p, id]); if (retryFails) throw new ApiError(409, "refused", "That task is not failed or blocked."); return {}; } },
  links: { request: (id) => `#/p/${P}/lobby`, inbox: (pending) => `#/p/${P}/floor/engineering/inbox${pending ? "/" + pending : ""}`, open: (path) => `#/p/${P}/floor/engineering/desk/${encodeURIComponent(path)}` },
};
const requests = [{ id: 1, title: "Spring sale", state: "ready" }];
const pending = [{ id: 40, kind: "question", title: "q", task_id: 4, agent: "engineering" }];
const tab = createTasksTab(env);
const rowsOf = (root) => all(root, "li.wb-task");
const idOf = (li) => li.attrs["data-task"];

// --- eleven tasks of every state (no more than the twelve a tab reads at once) ---
const list = [task(1, "done"), task(2, "failed", { note: "Timed out <b>late</b>", title: "Build <script>alert(1)</script>" }), task(3, "blocked", { note: "An input is missing" }), task(4, "waiting"),
  task(5, "running"), task(6, "ready"), task(7, "planned"), task(8, "cancelled"), task(9, "done", { title: "Second done" })];
bodies.set(1, body(list[0], [run(1)], [{ id: 1, kind: "review", status: "resolved", payload: { returned: [{ path: "docs/brand/voice.md" }, { path: "notes/scratch.md" }] } }]));
bodies.set(2, body(list[1], [run(2, { status: "failed", failure: "timeout", ending: null, cost_usd: null, tokens: null, duration_ms: null, started_at: "2026-10-08T09:00:00Z" }), run(3, { status: "failed", failure: "refused", ending: "question", cost_usd: null })]));
bodies.set(5, body(list[4], [run(4, { status: "running", ending: null, cost_usd: null, started_at: "2026-10-08T11:50:00Z" })]));
tab.update({ tasks: list.slice().sort((a, b) => b.id - a.id), requests, pending, loading: false });
await settle();
tab.update({ tasks: list.slice().sort((a, b) => b.id - a.id), requests, pending, loading: false });
const groupsOf = () => all(tab.el, "details.wb-task-group");
out.groups = groupsOf().map((g) => [g.attrs["data-group"], "open" in g.attrs, text(g.querySelector("summary"))]);
out.rows = rowsOf(tab.el).map(idOf);
const li = (id) => rowsOf(tab.el).find((n) => idOf(n) === String(id));
const row2 = li(2);
out.failedRow = {
  text: text(row2.querySelector(".wb-task-title")), number: text(row2.querySelector(".wb-task-num")), skill: text(row2.querySelector(".wb-task-skill")), chip: text(row2.querySelector(".pui-chip")),
  request: row2.querySelector(".wb-task-request a").attrs.href, requestText: text(row2.querySelector(".wb-task-request a")), age: text(row2.querySelector(".wb-task-age")),
  note: text(row2.querySelector(".wb-task-note")), failure: text(row2.querySelector(".wb-task-failure")), retry: row2.querySelector(".wb-task-retry").attrs["aria-label"],
  markup: [...row2.walk()].filter((n) => ["SCRIPT", "B", "I"].includes(n.tagName)).length,
};
const row1 = li(1);
out.doneRow = { paths: all(row1, ".wb-path-row").map((r) => [text(r.querySelector("code")), r.querySelector("a") ? r.querySelector("a").attrs.href : null]), age: text(row1.querySelector(".wb-task-age")) };
const row4 = li(4);
out.waitingRow = { link: row4.querySelector("a.wb-task-inbox").attrs.href, text: text(row4.querySelector("a.wb-task-inbox")), retry: row4.querySelector(".wb-task-retry") === null };
out.noActions = [6, 7, 8, 9, 5].map((id) => [id, all(li(id), ".wb-task-retry").length + all(li(id), "a.wb-task-inbox").length]);
out.blockedRetry = li(3).querySelector(".wb-task-retry").attrs["aria-label"];

// --- the expand: the runs, newest first, from `task`, read once ---
const before2 = reads(2);
const toggle2 = row2.querySelector("button.wb-task-toggle");
out.collapsed = [toggle2.attrs["aria-expanded"], row2.querySelector(".wb-task-detail").hidden];
toggle2.click();
await settle();
tab.update({ tasks: list.slice().sort((a, b) => b.id - a.id), requests, pending, loading: false });
const open2 = li(2);
out.expanded = {
  aria: open2.querySelector("button.wb-task-toggle").attrs["aria-expanded"], hidden: open2.querySelector(".wb-task-detail").hidden,
  runs: all(open2, "dl.wb-run").map((d) => all(d, "dt").map((t, i) => [text(t), text(all(d, "dd")[i])])).map((rows) => Object.fromEntries(rows)),
  readsBefore: before2, readsAfter: reads(2),
};
toggle2.click(); await settle(); li(2).querySelector("button.wb-task-toggle").click(); await settle();
out.readsAfterToggles = reads(2);
// a running task shows its run with no cost: "unknown", never $0
li(5).querySelector("button.wb-task-toggle").click();
await settle();
out.runningRun = Object.fromEntries(all(li(5), "dl.wb-run").map((d) => all(d, "dt").map((t, i) => [text(t), text(all(d, "dd")[i])]))[0]);

// --- Retry goes through the environment's client, once, then the tab is read again ---
const retry = li(2).querySelector(".wb-task-retry");
retry.click();
await settle();
out.retry = { sent: sentRetry.slice(), refreshed: refreshed > 0 };
retryFails = true;
li(3).querySelector(".wb-task-retry").click();
await settle();
out.retryError = { sent: sentRetry.length, notice: text(li(3).querySelector(".wb-notice-card")), button: li(3).querySelector(".wb-task-retry").disabled };

// --- the keyboard: arrows move between the rows' toggles, Home and End jump ---
const press = (key) => (tab.el.querySelector(".wb-tasks-groups").listeners.keydown || []).forEach((fn) => fn({ key, preventDefault() {} }));
const toggles = () => all(tab.el, "button.wb-task-toggle");
toggles()[0].focus();
press("ArrowDown");
const second = document.activeElement === toggles()[1];
press("End");
const last = document.activeElement === toggles()[toggles().length - 1];
press("Home");
const first = document.activeElement === toggles()[0];
out.keys = [second, last, first, toggles().every((b) => b.attrs.tabindex === undefined || b.attrs.tabindex === "0")];

// --- a poll with the same data draws nothing again and keeps the focus on the row (the bodies Retry dropped are read first) ---
tab.update({ tasks: list.slice().sort((a, b) => b.id - a.id), requests, pending, loading: false });
await settle();
toggles()[2].focus();
const focused = document.activeElement.attrs["data-key"];
const nodeBefore = li(6);
tab.update({ tasks: list.slice().sort((a, b) => b.id - a.id), requests, pending, loading: false });
out.poll = [document.activeElement.attrs["data-key"] === focused, li(6) === nodeBefore];
// the data changed: the row is drawn again and the focus returns to the control with the same key
tab.update({ tasks: list.map((t) => (t.id === 6 ? { ...t, title: "Renamed" } : t)).sort((a, b) => b.id - a.id), requests, pending, loading: false });
out.afterChange = [document.activeElement.attrs["data-key"] === focused, text(li(6).querySelector(".wb-task-title"))];

// --- states: loading, no task ---
const fresh = createTasksTab(env);
fresh.update({ tasks: [], requests: [], pending: [], loading: true });
out.loading = [text(fresh.el), all(fresh.el, "details").length];
fresh.update({ tasks: [], requests: [], pending: [], loading: false });
out.none = [text(fresh.el), all(fresh.el, "details").length];
// a task that waits with no decision found (the Lobby's too): the link is the bare Inbox, never an id of another task
const lonely = createTasksTab(env);
lonely.update({ tasks: [task(30, "waiting")], requests, pending: [{ id: 99, kind: "question", task_id: 31, agent: "engineering" }], loading: false });
out.bareInbox = text(all(lonely.el, "a.wb-task-inbox")[0]) + " " + all(lonely.el, "a.wb-task-inbox")[0].attrs.href;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_tab_draws_a_group_for_each_state_with_its_count_and_a_row_with_every_fact_as_text(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    names = [(g[0], g[1]) for g in got["groups"]]
    assert names == [("running", True), ("waiting", True), ("ready", True), ("planned", True), ("done", True), ("failed", True), ("cancelled", True)], \
        "seven groups in the spec's order, each open because each holds a task"
    assert [g[2] for g in got["groups"]][:2] == ["Running1", "Waiting for you1"] and got["groups"][3][2] == "Planned or blocked2"
    assert got["rows"] == ["5", "4", "6", "7", "3", "9", "1", "2", "8"], "rows follow the groups, newest first inside each"
    f = got["failedRow"]
    assert f["number"] == "#2" and f["text"] == "Build <script>alert(1)</script>" and f["skill"] == "eng-implement" and f["chip"] == "Failed"
    assert f["request"] == "#/p/0123456789ab/lobby" and f["requestText"] == "Request #1 Spring sale"
    assert f["age"] == "2 h ago" and f["note"] == "Timed out <b>late</b>" and f["retry"] == "Retry task 2"
    assert f["failure"] == "Refused · Asked a question", "the failure word of the newest run and that run's ending"
    assert f["markup"] == 0, "a title and a note are text, never markup"


@needs_node
def test_a_done_row_opens_a_returned_path_only_under_docs_and_a_waiting_row_opens_its_decision_in_the_inbox(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    assert got["doneRow"]["paths"] == [["docs/brand/voice.md", "#/p/0123456789ab/floor/engineering/desk/docs%2Fbrand%2Fvoice.md"], ["notes/scratch.md", None]]
    assert got["waitingRow"] == {"link": "#/p/0123456789ab/floor/engineering/inbox/40", "text": "Open in the Inbox", "retry": True}
    assert all(n == 0 for _id, n in got["noActions"]), "running, ready, planned, cancelled and done tasks have no action"
    assert got["blockedRetry"] == "Retry task 3"


@needs_node
def test_a_row_expands_into_its_runs_newest_first_and_task_is_read_once_per_row(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    assert got["collapsed"] == ["false", True]
    e = got["expanded"]
    assert e["aria"] == "true" and e["hidden"] is False
    assert [r["Run"] for r in e["runs"]] == ["#3 eng-implement 1.0.0"], "the last run is the only one drawn until the earlier attempts are opened (A-72)"
    assert e["runs"][0]["Failure"] == "Refused" and e["runs"][0]["Model"] == "model-a"
    assert all(r["Cost"] == "unknown" for r in e["runs"]), "an unknown cost is unknown, never $0"
    assert e["readsBefore"] == 1 and e["readsAfter"] == 1, "the tab read the body once; the expand did not read it again"
    assert got["readsAfterToggles"] == 1, "collapsing and expanding again reads nothing"
    assert got["runningRun"]["Status"] == "Running" and got["runningRun"]["Cost"] == "unknown"


@needs_node
def test_retry_sends_through_the_environments_client_once_and_a_refusal_is_shown_on_its_row(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    assert got["retry"] == {"sent": [["0123456789ab", 2]], "refreshed": True}
    assert got["retryError"]["sent"] == 2 and got["retryError"]["notice"] == "That task is not failed or blocked." and got["retryError"]["button"] is False


@needs_node
def test_the_arrow_keys_move_between_the_rows_and_a_poll_never_takes_the_focus_or_redraws_a_row_that_did_not_change(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    assert got["keys"] == [True, True, True, True], "ArrowDown, End and Home move the focus; every toggle is in the tab order"
    assert got["poll"] == [True, True], "the same data draws nothing again"
    assert got["afterChange"] == [True, "Renamed"], "changed data is drawn and the focus goes back to the control with the same key"


@needs_node
def test_a_waiting_task_with_no_decision_of_its_own_links_to_the_bare_inbox(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    assert got["bareInbox"] == "Open in the Inbox #/p/0123456789ab/floor/engineering/inbox"
    model = run_node(tmp_path, MODEL)
    assert model["route"][3:] == ["#/p/0123456789ab/lobby/inbox", "#/p/0123456789ab/floor/brand/inbox"], "the Lobby's and the Floor's link builders give the bare Inbox for a null id"


@needs_node
def test_the_tab_says_loading_and_says_the_agent_has_no_task_yet(tmp_path):
    got = run_node(tmp_path, TAB_MARKUP)
    assert got["loading"] == ["Loading the tasks...", 0]
    assert got["none"] == ["This agent has no task yet.", 0]


READS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createTasksTab } from "@JS@/floor/tasks-tab.js";

setToken("t".repeat(40));
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push(String(url).replace(`/api/v1/projects/${P}/tasks/`, ""));
  const id = Number(String(url).split("/").pop());
  return { ok: true, status: 200, json: async () => ({ task: { id, created_at: "2026-10-08T08:00:00Z", updated_at: "2026-10-08T10:00:00Z" }, runs: [{ id: id * 10, skill: "s", model: "m", status: "ok", ending: "done", attempts: 1 }], pending: [] }) };
};
const task = (id, state) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: "engineering", requestId: 1 });
const env = { project: P, now: () => NOW, refresh() {}, api: { retry: async () => ({}) }, links: { request: () => "#/", inbox: () => "#/", open: () => "#/" } };
const tab = createTasksTab(env);
const tasks = Array.from({ length: 14 }, (_, i) => task(i + 1, "done")).reverse();    // 14 .. 1
const draw = (list) => tab.update({ tasks: list, requests: [], pending: [], loading: false });
draw(tasks);
await settle();
const out = {};
out.first = [...calls].sort((a, b) => Number(a) - Number(b));
draw(tasks);
await settle();
out.again = calls.length;                       // the same data within the stale time: nothing is read again
// the 13th row and the 14th (ids 2 and 1) were not read: expanding one reads it, once
const li = (id) => all(tab.el, "li.wb-task").find((n) => n.attrs["data-task"] === String(id));
li(1).querySelector("button.wb-task-toggle").click();
await settle();
out.expand1 = calls.filter((c) => c === "1").length;
li(1).querySelector("button.wb-task-toggle").click();
li(1).querySelector("button.wb-task-toggle").click();
await settle();
out.expand1Again = calls.filter((c) => c === "1").length;
// a task whose state changed is read again
draw(tasks.map((t) => (t.id === 14 ? { ...t, state: "failed" } : t)));
await settle();
out.stateChange = calls.filter((c) => c === "14").length;
// the page's refresh after an action reads the open rows again
// the twelve are the failed rows, then the done rows, then the rest: thirteen done rows fill them and an old running task waits for its expand
calls.length = 0;
const second = createTasksTab(env);
second.update({ tasks: [task(1, "running"), ...Array.from({ length: 13 }, (_, i) => task(i + 2, "done"))], requests: [], pending: [], loading: false });
await settle();
out.groupOrder = [calls.includes("1"), calls.length, calls.includes("2")];     // the oldest done row (2) is the thirteenth done row, the running one (1) is after them all

// twenty rows where the failed ones come last (the oldest ids): the failed and the done are read first, then the rest, twelve in all
calls.length = 0;
const third = createTasksTab(env);
const mixed = [task(1, "failed"), task(2, "failed"), task(3, "failed"), ...Array.from({ length: 4 }, (_, i) => task(i + 4, "done")), ...Array.from({ length: 13 }, (_, i) => task(i + 8, "ready"))];
third.update({ tasks: mixed, requests: [], pending: [], loading: false });
await settle();
const asked = calls.map(Number);
out.failedFirst = [asked.length, [1, 2, 3].every((id) => asked.includes(id)), [4, 5, 6, 7].every((id) => asked.includes(id)), asked.filter((id) => id >= 8).length];

// the reload stamp: the same stamp reads nothing, a moved stamp reads every shown body again, a read that began before the move is read again
calls.length = 0;
let gate = null;
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, init) => { if (gate) await gate; return realFetch(url, init); };
const stamped = createTasksTab(env);
const rows = Array.from({ length: 3 }, (_, i) => task(i + 1, "done"));
const give = (reload) => stamped.update({ tasks: rows, requests: [], pending: [], loading: false, reload });
give(1);
await settle();
const afterFirst = calls.length;
give(1);
await settle();
const afterSame = calls.length;
give(2);
await settle();
const afterMoved = calls.length;
let release;
gate = new Promise((r) => { release = r; });
give(3);                                  // three reads begin and wait at the gate
give(4);                                  // the stamp moves while they run
release();
gate = null;
await settle();
out.stamp = [afterFirst, afterSame - afterFirst, afterMoved - afterSame, calls.length - afterMoved];
globalThis.fetch = realFetch;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_tab_reads_the_first_twelve_bodies_once_and_a_row_beyond_them_only_when_it_is_expanded(tmp_path):
    got = run_node(tmp_path, READS)
    assert got["first"] == [str(i) for i in range(3, 15)], "the first twelve rows of fourteen"
    assert got["again"] == 12, "the same data within the stale time reads nothing"
    assert got["expand1"] == 1 and got["expand1Again"] == 1, "expanding a row beyond the twelve reads its body once"
    assert got["stateChange"] == 2, "a task whose state changed is read again"
    assert got["groupOrder"] == [False, 12, False], "failed rows are read first, then done rows, then the rest: of thirteen done rows and one running, twelve done rows are read"
    assert got["failedFirst"] == [12, True, True, 5], "twenty rows with the failed ones last: the three failed and the four done are read first, then five of the rest"
    assert got["stamp"] == [3, 0, 3, 6], "a stamp that did not move reads nothing, a moved one reads each shown body again, and the reads that began before a move are read again"


# --- the shared run block and the files ----------------------------------------------------------------------------------------------

RUN_BLOCK = r"""
import { FakeNode } from "@FAKE@";
import { runBlock } from "@JS@/floor/run-block.js";
const dl = runBlock({ id: 9, skill: "s", skill_version: "1", model: "m", status: "failed", failure: "timeout", attempts: 2, error: "<b>late</b>", duration_ms: 125000, tokens: 1234, cost_usd: null });
const rows = dl.querySelectorAll("dt").map((t, i) => [t.textContent, dl.querySelectorAll("dd")[i].textContent]);
console.log(JSON.stringify({ rows, cls: dl.attrs.class, error: dl.querySelectorAll("dd").pop().children.length }));
"""


@needs_node
def test_the_run_block_is_one_component_with_an_unknown_cost_spelled_unknown(tmp_path):
    got = run_node(tmp_path, RUN_BLOCK)
    assert got["cls"] == "wb-run"
    assert ["Cost", "unknown"] in got["rows"] and ["Failure", "Timed out"] in got["rows"] and ["Error", "<b>late</b>"] in got["rows"]
    assert got["error"] == 1, "an error is one text node"


def test_the_tab_files_exist_and_the_agent_tab_and_the_tasks_tab_import_the_same_run_block():
    for path in (TAB, MODEL_FILE, BLOCK):
        assert path.is_file(), f"{path.name} is a file of the page"
    agent = (INTERFACE / "js" / "floor" / "agent-tab.js").read_text(encoding="utf-8")
    tasks = TAB.read_text(encoding="utf-8")
    assert 'import { runsSection } from "./run-block.js";' in agent and 'import { runsSection } from "./run-block.js";' in tasks
    assert "function runBlock" not in agent and "runBlock(" not in agent and "runBlock(" not in tasks, "both tabs draw the runs through the one runsSection (A-72)"


def test_the_tasks_tab_sends_only_retry_and_go_ahead_through_its_environment_and_reads_only_task():
    text = TAB.read_text(encoding="utf-8")
    actions = (TAB.parent / "task-actions.js").read_text(encoding="utf-8")        # A-32: the one source of the actions of the Tasks tab and the Agent tab
    assert not re.search(r'import\s*\{[^}]*\}\s*from\s*"\.\./api\.js"', text + actions), "no operation of the client is imported by name"
    assert "createTaskActions" in text and not set(re.findall(r"\benv\.api\.(\w+)\(", text)), "the tab sends nothing itself: its actions do"
    assert set(re.findall(r"\benv\.api\.(\w+)\(", actions)) == {"retry", "goAhead"}, "the only writes are Retry and Go ahead (A-29), through the client the view hands in"
    assert set(re.findall(r"\bclient\.(\w+)\(", text)) == {"task"}, "the only read is a task's body"
    for forbidden in ("innerHTML", "insertAdjacentHTML", "document.write", "eval(", "fetch("):  # security-scan: allow dynamic-eval -- a pattern that forbids a call; nothing runs it
        assert forbidden not in text and forbidden not in MODEL_FILE.read_text(encoding="utf-8"), forbidden
    for target in re.findall(r"href: ([^,}]+)", text):
        assert target.strip().startswith("env.links."), f"tasks-tab.js links only through the links its view builds with the router: {target}"


# --- A-72: "This run" and "Earlier attempts (n)" ---------------------------------------------------------------------------------

EARLIER = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createTasksTab } from "@JS@/floor/tasks-tab.js";
import { splitRuns } from "@JS@/floor/tasks-model.js";

setToken("t".repeat(40));
const P = "0123456789ab";
const NOW = new Date("2026-10-08T12:00:00Z");
const bodies = new Map();
globalThis.fetch = async (url) => {
  const m = String(url).match(/\/tasks\/(\d+)$/);
  const body = m ? bodies.get(Number(m[1])) : null;
  return { ok: Boolean(body), status: body ? 200 : 404, json: async () => body || { error: "not_found", message: "no" } };
};
const text = (n) => n.textContent;
const task = (id, state) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "eng-implement", state, note: null, agent: "engineering", requestId: 1 });
const run = (id, extra = {}) => ({ id, skill: "eng-implement", skill_version: "1.0.0", model: "model-a", status: "ok", ending: "done", attempts: 1, started_at: "2026-10-08T11:00:00Z", duration_ms: 42000, tokens: 1200, cost_usd: 0.1, ...extra });
const failed = (id, error) => run(id, { status: "failed", failure: "adapter", ending: null, cost_usd: null, error });
const body = (t, runs) => ({ task: { id: t.id, state: t.state, created_at: "2026-10-08T08:00:00Z", updated_at: "2026-10-08T10:00:00Z" }, runs, pending: [] });
const out = {};
const env = { project: P, now: () => NOW, refresh() {}, api: { retry: async () => ({}) }, links: { request: () => "#", inbox: () => "#", open: () => "#" } };
const list = [task(1, "done"), task(2, "running"), task(3, "failed")];
bodies.set(1, body(list[0], [run(1)]));
bodies.set(2, body(list[1], [failed(10, "the adapter said <b>no</b>"), run(11, { status: "running", ending: null, cost_usd: null })]));          // stored oldest first
bodies.set(3, body(list[2], [run(20), failed(21, "first error"), failed(22, "second error")]));
const data = { tasks: list.slice().sort((a, b) => b.id - a.id), requests: [{ id: 1, title: "R", state: "ready" }], pending: [], loading: false };
const tab = createTasksTab(env);
tab.update(data);
await settle();
tab.update(data);
const li = (id) => all(tab.el, "li.wb-task").find((n) => n.attrs["data-task"] === String(id));
const open = async (id) => { li(id).querySelector("button.wb-task-toggle").click(); await settle(); tab.update(data); };
const facts = (d) => Object.fromEntries(all(d, "dt").map((t, i) => [text(t), text(all(d, "dd")[i])]));
const shape = (id) => {
  const row = li(id);
  const toggle = row.querySelector("button.wb-earlier-toggle");
  const listNode = row.querySelector(".wb-earlier-list");
  return {
    heads: all(row, ".wb-runs-head").map(text),
    blocks: all(row, "dl.wb-run").length,
    this: facts(row.querySelector(".wb-task-detail").children.find((c) => c.tagName === "DL")),
    toggle: toggle ? { text: text(toggle), aria: toggle.attrs["aria-expanded"], controls: toggle.attrs["aria-controls"], muted: (toggle.attrs.class || "").includes("wb-muted") } : null,
    list: listNode ? { id: listNode.attrs.id, hidden: listNode.hidden, runs: all(listNode, "dl.wb-run").map((d) => facts(d)) } : null,
  };
};

// one run: the heading and the run, no disclosure
await open(1);
out.one = shape(1);

// a running run with an earlier failed one: closed by default, then opened, then closed again
await open(2);
out.running = { closed: shape(2) };
li(2).querySelector("button.wb-earlier-toggle").click();
await settle();
out.running.opened = shape(2);
out.running.markup = [...li(2).walk()].filter((n) => n.tagName === "B").length;
tab.update(data);                                       // a poll with the same data keeps the choice
out.running.afterPoll = shape(2).toggle.aria;
li(2).querySelector("button.wb-earlier-toggle").click();
await settle();
out.running.closedAgain = shape(2);

// no run in progress: the last run is "This run"; the earlier ones are newest first
await open(3);
li(3).querySelector("button.wb-earlier-toggle").click();
await settle();
out.last = shape(3);

// the pure split
out.split = [splitRuns([]), splitRuns([{ id: 1, status: "ok" }]), splitRuns([{ id: 3, status: "failed" }, { id: 2, status: "running" }, { id: 1, status: "failed" }]), splitRuns(null)]
  .map((s) => [s.thisRun ? s.thisRun.id : null, s.earlier.map((r) => r.id)]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_one_run_is_drawn_under_this_run_with_no_disclosure(tmp_path):
    got = run_node(tmp_path, EARLIER)["one"]
    assert got["heads"] == ["This run"] and got["blocks"] == 1 and got["toggle"] is None and got["list"] is None
    assert got["this"]["Run"] == "#1 eng-implement 1.0.0"


@needs_node
def test_the_running_run_is_this_run_and_the_earlier_failed_one_waits_behind_a_closed_disclosure_that_opens(tmp_path):
    got = run_node(tmp_path, EARLIER)["running"]
    closed = got["closed"]
    assert closed["heads"] == ["This run"] and closed["this"]["Run"] == "#11 eng-implement 1.0.0" and closed["this"]["Status"] == "Running"
    assert closed["blocks"] == 1, "the failed run is not drawn while the disclosure is closed"
    assert closed["toggle"]["text"] == "Earlier attempts (1)" and closed["toggle"]["aria"] == "false" and closed["toggle"]["muted"] is True
    assert closed["toggle"]["controls"] == closed["list"]["id"] and closed["list"]["hidden"] is True and closed["list"]["runs"] == []
    opened = got["opened"]
    assert opened["toggle"]["aria"] == "true" and opened["list"]["hidden"] is False and opened["blocks"] == 2
    [earlier] = opened["list"]["runs"]
    assert earlier["Run"] == "#10 eng-implement 1.0.0" and earlier["Status"] == "Failed" and earlier["Failure"] == "The adapter failed"
    assert earlier["Error"] == "the adapter said <b>no</b>", "the error is text, never markup"
    assert got["markup"] == 0 and got["afterPoll"] == "true", "a poll with the same data keeps the person's choice"
    assert got["closedAgain"]["toggle"]["aria"] == "false" and got["closedAgain"]["blocks"] == 1


@needs_node
def test_with_no_run_in_progress_the_last_run_is_this_run_and_the_earlier_ones_follow_newest_first(tmp_path):
    got = run_node(tmp_path, EARLIER)
    last = got["last"]
    assert last["this"]["Run"] == "#22 eng-implement 1.0.0" and last["toggle"]["text"] == "Earlier attempts (2)"
    assert [r["Run"] for r in last["list"]["runs"]] == ["#21 eng-implement 1.0.0", "#20 eng-implement 1.0.0"]
    assert got["split"] == [[None, []], [1, []], [2, [3, 1]], [None, []]], "a running run wins over a newer one; the rest keep their order"


CURRENT_RUNS = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as fm from "@JS@/floor-model.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";

setToken("t".repeat(40));
const NOW = new Date("2026-10-10T12:00:00Z");
const P = "0123456789ab";
const text = (n) => (n ? n.textContent : null);
const task = (id, state) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "implement-change", state, note: null, agent: "engineering", requestId: 2, waiting_for: [] });
const agent = { name: "engineering", pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 6, max_usd_per_day: 2, runs_today: 3, usd_today: 0, runs_without_cost: 0, queued: 0, held: 0 };
const run = (id, extra = {}) => ({ id, skill: "implement-change", skill_version: "1.4.0", model: "reference", status: "ok", ending: "done", attempts: 1, started_at: "2026-10-10T11:00:00Z", tokens: 10, cost_usd: null, duration_ms: 1000, ...extra });
const view = (runs, state = "running") => fm.floor({ projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: { requests: [{ id: 2, title: "R", state: "running", tasks: [task(52, state)] }], pending: [], held: [] }, agents: [agent] } }, tasks: {}, loaded: true },
  P, "engineering", { 52: { task: { id: 52, updated_at: "2026-10-10T11:50:00Z" }, runs, pending: [] } });
const tab = createAgentTab({ project: P, agent: "engineering", api: { setMode: async () => ({}), retry: async () => ({}), goAhead: async () => ({}), handOver: async () => ({}) }, refresh() {}, now: () => NOW });
const facts = (d) => Object.fromEntries(all(d, "dt").map((t, i) => [text(t), text(all(d, "dd")[i])]));
const shape = () => {
  const card = find(tab.el, ".wb-current");
  const toggle = card.querySelector("button.wb-earlier-toggle");
  const list = card.querySelector(".wb-earlier-list");
  return {
    heads: all(card, ".wb-runs-head").map(text), blocks: all(card, "dl.wb-run").length, thisRun: facts(card.children.find((c) => c.tagName === "DL")),
    toggle: toggle ? [text(toggle), toggle.attrs["aria-expanded"], toggle.attrs["aria-controls"] === list.attrs.id] : null,
    list: list ? { hidden: list.hidden, runs: all(list, "dl.wb-run").map(facts) } : null,
  };
};
const out = {};
// one run: no disclosure
tab.update(view([run(5, { status: "running", ending: null })]));
await settle();
out.one = shape();
// a running run (stored last) and an earlier failed one: closed by default, then open, then closed again, kept across an update
tab.update(view([run(4, { status: "failed", failure: "timeout", ending: null, error: "stopped after 40 minutes" }), run(5, { status: "running", ending: null })]));
await settle();
out.closed = shape();
find(tab.el, ".wb-current").querySelector("button.wb-earlier-toggle").click();
await settle();
out.opened = shape();
tab.update(view([run(4, { status: "failed", failure: "timeout", ending: null, error: "stopped after 40 minutes" }), run(5, { status: "running", ending: null })]));
await settle();
out.afterUpdate = shape().toggle[1];
find(tab.el, ".wb-current").querySelector("button.wb-earlier-toggle").click();
await settle();
out.closedAgain = shape().toggle[1];
// no run in progress: the last run is this run
tab.update(view([run(1), run(2, { status: "failed", failure: "refused", ending: null, error: "no" }), run(3)], "ready"));
await settle();
out.last = shape();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_agent_tabs_current_task_draws_this_run_and_a_closed_earlier_attempts_like_the_tasks_tab(tmp_path):
    got = run_node(tmp_path, CURRENT_RUNS)
    assert got["one"]["heads"] == ["This run"] and got["one"]["blocks"] == 1 and got["one"]["toggle"] is None
    closed = got["closed"]
    assert closed["heads"] == ["This run"] and closed["thisRun"]["Run"] == "#5 implement-change 1.4.0" and closed["thisRun"]["Status"] == "Running"
    assert closed["blocks"] == 1 and closed["toggle"] == ["Earlier attempts (1)", "false", True] and closed["list"]["hidden"] is True and closed["list"]["runs"] == []
    opened = got["opened"]
    assert opened["toggle"][1] == "true" and opened["list"]["hidden"] is False and opened["blocks"] == 2
    [earlier] = opened["list"]["runs"]
    assert earlier["Run"] == "#4 implement-change 1.4.0" and earlier["Status"] == "Failed" and earlier["Error"] == "stopped after 40 minutes"
    assert got["afterUpdate"] == "true" and got["closedAgain"] == "false"
    last = got["last"]
    assert last["thisRun"]["Run"] == "#3 implement-change 1.4.0" and last["toggle"][0] == "Earlier attempts (2)"

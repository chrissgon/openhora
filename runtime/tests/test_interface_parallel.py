"""PAR-5: the page reads several running tasks (SPEC-PAR section 10). The runtime runs tasks of one project at once (slots per floor, a limit per
project); the page draws what the reads say: a floor is working while a task of its agent runs, the Agent tab shows one card for each running task,
the tracking bar and the Building's "Running now" list up to three, a ready task held by one of the five new words is queued, the busy slots of a
floor are the agent's `slots_held` of its `max_parallel`, the composer is busy only while the router answers, and the plan's limits line says how
many tasks run at a time. No browser and no model: the modules run under Node with a fake document, as the other interface tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_parallel.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

from test_interface_floor import FAKE_DOM as FLOOR_DOM, INTERFACE, NODE, needs_node
from test_interface_plates_meters import run_node

JS = INTERFACE / "js"

COMMON = r"""
import * as model from "@JS@/model.js";
import * as fm from "@JS@/floor-model.js";

const P = "0123456789ab";
const NOW = new Date("2026-10-12T12:00:00Z");
const ago = (m) => new Date(NOW.getTime() - m * 60000).toISOString();
const task = (id, state, agent, extra = {}) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "eng-implement", state, note: null, agent, holds_slot: state === "running", waiting_for: [], ...extra });
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0, runs_without_cost: 0,
  queued: 0, held: 0, max_parallel: 1, max_parallel_ceiling: 4, slots_held: 0, holders: [], wider: [], ...extra });
const status = (tasks, held = [], pending = []) => ({ requests: [{ id: 1, title: "Spring", state: "ready", tasks }], pending, held, documents: [] });
const snapshot = (tasks, agents, projectExtra = {}, held = []) => ({ projects: [{ id: P, name: "northwind-shop", config: { accepted: true }, running_task: null, running_tasks: [], ...projectExtra }],
  details: { [P]: { status: status(tasks, held), agents } }, tasks: {}, loaded: true });
const out = {};
"""


# --- two running tasks of two floors light two floors ------------------------------------------------------------------------------------

TWO_FLOORS = COMMON + r"""
const tasks = [task(4, "running", "engineering"), task(5, "running", "design"), task(6, "ready", "marketing")];
const agents = [agent("planning"), agent("engineering", { slots_held: 1, holders: [4] }), agent("design", { slots_held: 1, holders: [5] }), agent("marketing", { queued: 1 })];
const snap = snapshot(tasks, agents, { running_task: 4, running_tasks: [4, 5] });
const view = fm.building(snap, P);
out.states = Object.fromEntries(view.rows.map((r) => [r.name, [r.state, r.window]]));
const city = model.buildingOf(snap.projects[0], snap.details[P]);
out.city = city.floors.map((f) => [f.agent, f.window]);
out.runningTasks = [city.runningTask, city.runningTasks];
out.words = [model.subOf(city), model.tooltipOf(city), model.linkNameOf(city)];
const one = model.buildingOf({ ...snap.projects[0], running_task: 4, running_tasks: [4] }, snap.details[P]);
out.one = [one.runningTask, one.runningTasks, model.subOf(one)];
const none = model.buildingOf({ ...snap.projects[0], running_task: null, running_tasks: [] }, snap.details[P]);
out.none = [none.runningTask, none.runningTasks, model.subOf(none)];
const older = model.buildingOf({ id: P, name: "n", config: { accepted: true }, running_task: 7 }, snap.details[P]);       // a service that lists no running_tasks
out.older = [older.runningTasks, model.subOf(older)];
out.facts = [view.facts.runningCount, view.facts.runningList.map((r) => r.id), view.facts.running.id];
// the followed project's running tasks are read: every one, the oldest first, at most six
const many = Array.from({ length: 8 }, (_, i) => task(20 - i, "running", i % 2 ? "design" : "engineering"));
out.needed = [model.neededTasks(snap.projects, snap.details, P).map((t) => t.id), model.neededTasks(snapshot(many, agents).projects, snapshot(many, agents).details, P).map((t) => t.id),
  model.neededTasks(snap.projects, snap.details, "other")];
console.log(JSON.stringify(out));
"""


@needs_node
def test_two_running_tasks_of_two_floors_light_two_floors(tmp_path):
    got = run_node(tmp_path, TWO_FLOORS)
    assert got["states"]["engineering"] == ["working", "lit"] and got["states"]["design"] == ["working", "lit"], "a task of the agent runs: the floor works"
    assert got["states"]["marketing"][0] == "ready" and got["states"]["planning"][0] == "idle"
    assert dict(got["city"])["engineering"] == "lit" and dict(got["city"])["design"] == "lit" and dict(got["city"])["marketing"] == "lit", "the City lights both floors that run and the queued one"
    assert got["runningTasks"] == [4, [4, 5]], "the building keeps runningTask (the scene reads it) and gains the list"
    assert got["words"][0] == "2 tasks running" and got["words"][1].endswith("2 tasks running") and "2 tasks running" in got["words"][2]
    assert got["one"] == [4, [4], "task #4 running"] and got["none"] == [None, [], "no task running"]
    assert got["older"] == [[7], "task #7 running"], "a project list with running_task alone is read as one running task"
    assert got["facts"] == [2, [4, 5], 4]
    assert got["needed"][0] == [4, 5]
    assert got["needed"][1] == [13, 14, 15, 16, 17, 18], "at most six, the oldest (lowest numbers) first"
    assert got["needed"][2] == []


# --- the Agent tab: Current tasks ---------------------------------------------------------------------------------------------------------

AGENT_TAB = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import { createAgentTab } from "@JS@/floor/agent-tab.js";
""" + COMMON + r"""
setToken("t".repeat(40));
const text = (n) => n.textContent;
const api = { retry: async () => ({}), goAhead: async () => ({}), setMode: async () => ({}), handOver: async () => ({}) };
const tab = createAgentTab({ project: P, agent: "engineering", api, refresh() {}, now: () => NOW });
const bodies = { 4: { task: task(4, "running", "engineering"), runs: [{ id: 1, skill: "eng-implement", status: "running", started_at: ago(12) }], pending: [] },
  5: { task: task(5, "running", "engineering"), runs: [{ id: 2, skill: "eng-implement", status: "running", started_at: ago(3) }], pending: [] } };
const view = (tasks, agentExtra = {}, held = []) => fm.floor(snapshot(tasks, [agent("planning"), agent("engineering", agentExtra)], {}, held), P, "engineering", bodies);
const heads = () => all(tab.el, ".wb-sec-head").map(text);
const cards = () => all(tab.el, ".wb-current");

tab.update(view([task(4, "running", "engineering"), task(5, "running", "engineering"), task(6, "ready", "engineering")], { max_parallel: 2, slots_held: 2, holders: [4, 5] },
  [{ task_id: 6, agent: "engineering", reason: "agent at max_parallel", at: ago(0), next: null, commands: [] }]));
out.two = { heads: heads(), cards: cards().map((c) => text(find(c, ".wb-current-head"))), subs: cards().map((c) => text(find(c, ".wb-current-sub"))), others: all(tab.el, ".wb-other").map((o) => text(find(o, ".wb-other-title"))),
  held: all(tab.el, ".wb-other .wb-held-line").map(text) };
out.twoModel = (() => { const v = view([task(4, "running", "engineering"), task(5, "running", "engineering")], { max_parallel: 2 }); return [v.runningTasks.map((t) => t.id), v.current.id, v.currents.map((c) => c.task.id), v.tasks.length]; })();

tab.update(view([task(4, "running", "engineering"), task(6, "ready", "engineering")]));
out.one = { heads: heads(), cards: cards().length, others: all(tab.el, ".wb-other").length };

tab.update(view([task(6, "ready", "engineering")]));
out.ready = { heads: heads(), cards: cards().map((c) => text(find(c, ".wb-current-head"))) };

tab.update(view([]));
out.empty = { heads: heads(), cards: cards().length };
console.log(JSON.stringify(out));
"""


@needs_node
def test_two_running_tasks_of_one_floor_give_current_tasks_with_two_cards(tmp_path):
    got = run_node(tmp_path, AGENT_TAB, FLOOR_DOM)
    assert got["two"]["heads"][0] == "Current tasks", "several running tasks: the section is plural"
    assert [c.split(" ")[0] for c in got["two"]["cards"]] == ["#4", "#5"], "one card for each running task, the oldest first"
    assert len(got["two"]["subs"]) == 2 and got["two"]["others"] == ["#6 Task 6"], "the ready task is among the others, not a card"
    assert got["two"]["held"] == ["Held: Every slot of this floor is held, by #4, #5; it starts when one ends."], "a ready task of the floor says why it waits, and names the holders"
    assert got["twoModel"] == [[4, 5], 4, [4, 5], 2], "the current task stays the oldest running one; `currents` lists every card"
    assert got["one"]["heads"][0] == "Current task" and got["one"]["cards"] == 1 and got["one"]["others"] == 1
    assert got["ready"]["heads"][0] == "Current task" and len(got["ready"]["cards"]) == 1
    assert got["empty"]["cards"] == 0


# --- the held words and the queued pose ---------------------------------------------------------------------------------------------------

HELD = COMMON + r"""
const words = ["agent at max_parallel", "project at max_running", "artifact in use", "a code task of the request runs", "could not start, tried again shortly"];
out.turn = model.TURN_REASONS.slice();
out.old = [fm.HELD_SENTENCES["job running"] === undefined, model.TURN_REASON === undefined, fm.TURN_REASON === undefined];
out.sentences = words.map((w) => fm.heldSentence(w));
out.holders = [fm.heldSentence("agent at max_parallel", [12, 15]), fm.heldSentence("agent at max_parallel", [9]), fm.heldSentence("agent at max_parallel", [])];
out.note = fm.QUEUED_NOTE;
const held = (w, id) => ({ task_id: id, agent: "design", reason: w, at: ago(1), next: null, commands: [] });
// a ready task held by one of the five words is queued (the ready pose); a hold of its own kind is not
out.pose = words.map((w) => {
  const a = agent("design", { queued: 1, held: 1 });
  return fm.stateOf(a, status([task(7, "ready", "design")], [held(w, 7)]));
});
out.own = ["stopped", "credential", "cap: runs per day"].map((w) => fm.stateOf(agent("design", { queued: 1, held: 1 }), status([task(7, "ready", "design")], [held(w, 7)])));
out.free = model.queuedFree(agent("design", { queued: 2 }), status([task(7, "ready", "design"), task(8, "ready", "design")], [held("agent at max_parallel", 7), held("credential", 8)]));
// the Floor says why the current task waits, naming the holders
const snap = snapshot([task(4, "running", "design"), task(7, "ready", "design")], [agent("planning"), agent("design", { queued: 1, held: 1, max_parallel: 1, slots_held: 1, holders: [4] })], {}, [held("agent at max_parallel", 7)]);
const view = fm.floor(snap, P, "design", {});
out.floor = [view.current.id, view.heldCurrent];
const snap2 = snapshot([task(7, "ready", "design")], [agent("planning"), agent("design", { queued: 1, held: 1, max_parallel: 2, slots_held: 2, holders: [12, 15] })], {}, [held("agent at max_parallel", 7)]);
out.floor2 = fm.floor(snap2, P, "design", {}).heldCurrent.sentence;
out.stateRow = fm.stateRow("ready", 0, null);
console.log(JSON.stringify(out));
"""


@needs_node
def test_each_new_held_word_gives_its_sentence_and_the_ready_pose_and_agent_at_max_parallel_names_the_holders(tmp_path):
    got = run_node(tmp_path, HELD)
    assert got["turn"] == ["agent at max_parallel", "project at max_running", "artifact in use", "a code task of the request runs", "could not start, tried again shortly"]
    assert got["old"] == [True, True, True], "the word `job running` and its constant are gone"
    assert got["sentences"] == [
        "Every slot of this floor is held; it starts when one ends.",
        "The project runs as many tasks as it allows at once; it starts when one ends.",
        "Another running task writes the same document; it starts when that one ends.",
        "Another code task of this request is running; code of one request runs one task at a time.",
        "It could not start just now; the next round tries again.",
    ]
    assert got["holders"][0] == "Every slot of this floor is held, by #12, #15; it starts when one ends."
    assert got["holders"][1] == "Every slot of this floor is held, by #9; it starts when one ends." and got["holders"][2] == got["sentences"][0]
    assert got["note"] == "starts when a slot frees"
    assert got["pose"] == ["ready"] * 5, "a ready task held by any of the five words is queued: the ready pose"
    assert got["own"] == ["idle", "idle", "idle"], "a hold of its own kind (stopped, a credential, a cap) is not queued"
    assert got["free"] == 1, "one ready task is held for a slot, one for a credential"
    assert got["floor"][0] == 4 and got["floor"][1] is None, "the running task is the floor's current one; it is not held"
    assert got["floor2"] == "Every slot of this floor is held, by #12, #15; it starts when one ends.", "the Floor names the agent's holders"
    assert got["stateRow"]["line"] == "Queued, starts when a slot frees"


# --- the slots of a floor ----------------------------------------------------------------------------------------------------------------

SLOTS = COMMON + r"""
const snap = (a) => snapshot([task(4, "running", "engineering")], [agent("planning"), agent("engineering", a)]);
const row = (a) => fm.building(snap(a), P).rows.find((r) => r.name === "engineering");
const two = row({ max_parallel: 2, slots_held: 1, holders: [4] });
out.two = [two.slots, two.counts, two.tip, two.linkName];
out.plate = fm.plateOf(two).slots;
out.one = row({ max_parallel: 1, slots_held: 1, holders: [4] }).slots;
out.older = row({ max_parallel: undefined, slots_held: undefined }).slots;        // an older service: no slots, nothing drawn
const three = row({ max_parallel: 4, slots_held: 3, holders: [4, 5, 6] });
out.three = [three.slots.text, three.slots.held, three.slots.max];
// the numbers are the agent's, never computed from the tasks: three running tasks listed, one slot reported
const view = fm.floor(snap({ max_parallel: 2, slots_held: 2, holders: [4, 9] }), P, "engineering", {});
out.state = fm.stateRow("working", 0, null, NOW, view.row.slots).line;
out.stateNone = fm.stateRow("working", 0, null, NOW, null).line;
out.board = fm.boardOf(view, NOW).lines;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_busy_slots_come_from_slots_held_of_max_parallel_and_the_page_never_writes_the_cap(tmp_path):
    got = run_node(tmp_path, SLOTS)
    assert got["two"][0] == {"held": 1, "max": 2, "text": "1 of 2 slots"}
    assert "1 of 2 slots" in got["two"][1] and "1 of 2 slots" in got["two"][3]
    assert got["plate"] == got["two"][0]
    assert got["one"] is None and got["older"] is None, "a floor with one slot, or an older service, says nothing about slots"
    assert got["three"] == ["3 of 4 slots", 3, 4]
    assert got["state"] == "Running · 2 of 2 slots" and got["stateNone"] == "Running"
    assert any("2 of 2 slots" in line for line in got["board"])
    # the page never writes the number of slots: the files hold no max_parallel in a write
    api = (JS / "api.js").read_text(encoding="utf-8")
    assert "max_parallel" not in api, "the client sends no slot count: the agents read gives it, the configuration holds it"


# --- the tracking bar and the Building: up to three, then +N more -------------------------------------------------------------------------

NOW_CARDS = r"""
import { FakeNode, find, all } from "@FAKE@";
import { createTrack } from "@JS@/frame/track.js";
""" + COMMON + r"""
const text = (n) => (n ? n.textContent : null);
const agents = [agent("planning"), agent("engineering"), agent("design"), agent("marketing")];
const running = (n) => Array.from({ length: n }, (_, i) => task(10 + i, "running", ["engineering", "design", "marketing", "engineering"][i % 4]));
const track = createTrack({ onOpenSteps() {}, onSelectRequest() {} });
const draw = (tasks, projectExtra = {}) => {
  const snap = snapshot(tasks, agents, projectExtra);
  snap.tasks = Object.fromEntries(tasks.filter((t) => t.state === "running").map((t) => [`${P}:${t.id}`, { task: { id: t.id }, runs: [{ started_at: ago(5 + t.id) }], pending: [] }]));
  const t = model.tracking(snap, P, NOW);
  track.set(t, "ready");
  return { t, snap };
};
for (const n of [1, 2, 3, 5]) {
  const { t } = draw(running(n), { running_task: 10, running_tasks: running(n).map((x) => x.id) });
  out[`n${n}`] = { cards: all(track.el, ".wb-now").map((c) => text(find(c, ".wb-now-title"))), more: all(track.el, ".wb-now-more").map(text), nows: t.nows.length, nowMore: t.nowMore, first: t.now.title,
    phone: text(find(track.el, ".wb-track-now-text")) };
}
// a waiting task (no running one) is the one card, as before; nothing running says so
out.waiting = (() => { const { t } = draw([task(3, "waiting", "design")]); return [t.nows.length, t.now.state, all(track.el, ".wb-now").length]; })();
out.nothing = (() => { const { t } = draw([task(3, "done", "design")]); return [t.nows.length, t.now, text(find(track.el, ".wb-now-where"))]; })();
// the router's run on the request comes after the running tasks (they run beside it)
out.routed = (() => {
  const snap = snapshot(running(1), agents, { running_task: 10, running_tasks: [10] });
  snap.details[P].status.requests[0].routing = { run_id: 3, skill: "core-orchestrator", started_at: ago(1) };
  const t = model.tracking(snap, P, NOW);
  return [t.nows.map((c) => c.title), t.now.sub.startsWith("task #10")];
})();
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_tracking_bar_shows_one_now_card_for_each_running_task_up_to_three_then_plus_n_more(tmp_path):
    got = run_node(tmp_path, NOW_CARDS)
    assert len(got["n1"]["cards"]) == 1 and got["n1"]["more"] == [] and got["n1"]["first"] == "Task 10"
    assert got["n2"]["cards"] == ["Task 10", "Task 11"] and got["n2"]["nows"] == 2
    assert got["n3"]["cards"] == ["Task 10", "Task 11", "Task 12"] and got["n3"]["more"] == []
    assert got["n5"]["cards"] == ["Task 10", "Task 11", "Task 12"] and got["n5"]["more"] == ["+2 more"] and got["n5"]["nowMore"] == 2, "at most three cards, then +N more"
    assert got["n5"]["phone"].startswith("5 tasks running"), "the phone's line counts the running tasks instead of naming one"
    assert got["waiting"] == [1, "Waiting for you", 1] and got["nothing"][1] is None and got["nothing"][2] == "Nothing is running"
    assert got["routed"][0] == ["Task 10", "Planning agent · routing request #1"] and got["routed"][1] is True


FACTS = COMMON + r"""
const agents = [agent("planning"), agent("engineering")];
const running = (n) => Array.from({ length: n }, (_, i) => task(10 + i, "running", "engineering"));
const f = (n, extra = {}) => fm.facts({ id: P, running_task: n ? 10 : null, running_tasks: running(n).map((t) => t.id), ...extra }, status(running(n)), true, false, NOW);
out.none = [f(0).running, f(0).runningList, f(0).runningCount, f(0).runningMore];
out.one = [f(1).running.id, f(1).runningList.map((r) => r.id), f(1).runningCount, f(1).runningMore];
out.five = [f(5).running.id, f(5).runningList.map((r) => r.id), f(5).runningCount, f(5).runningMore];
out.link = f(2).runningList.map((r) => r.link);
// a project that is not accepted keeps the last status: its running tasks are read from it
out.kept = fm.facts({ id: P, running_task: null }, status(running(2)), false, true, NOW).runningList.map((r) => r.id);
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_buildings_running_now_lists_up_to_three_tasks_then_plus_n_more(tmp_path):
    got = run_node(tmp_path, FACTS)
    assert got["none"] == [None, [], 0, 0]
    assert got["one"] == [10, [10], 1, 0]
    assert got["five"] == [10, [10, 11, 12], 5, 2]
    assert len(set(got["link"])) == 1 and got["link"][0].endswith("/floor/engineering")
    assert got["kept"] == [10, 11]
    building = (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert "runningMore" in building and "runningList" in building, "the panel draws the list and the +N more"


# --- the Lobby: the composer is free during a task run --------------------------------------------------------------------------------------

LOBBY = COMMON + r"""
import * as lm from "@JS@/views/lobby-model.js";
const tasks = (n) => Array.from({ length: n }, (_, i) => task(10 + i, "running", i % 2 ? "design" : "engineering", { title: `Build ${i}` }));
const routed = status(tasks(0));
routed.requests[0].routing = { run_id: 3, skill: "core-orchestrator", started_at: ago(2) };
const note = (s) => lm.runNote(s, NOW, P);
out.none = note(status([]));
out.one = note(status(tasks(1)));
out.two = note(status(tasks(2)));
out.routing = note(routed);
out.running = [lm.runningTasks(status(tasks(3))).map((t) => t.id), lm.runningTasks(status([])).length];
// a route is queued only behind another request's router run, never behind a task
out.busy = [lm.routerBusy(status(tasks(2)).requests, 1), lm.routerBusy(routed.requests, 1), lm.routerBusy([...routed.requests, { id: 2, state: "requested", tasks: [], routing: null }], 2), lm.routerBusy(routed.requests, 99)];
out.lines = [lm.RUN_LINE, lm.QUEUE_REASON, lm.BUSY_NOTICE.text, lm.TASKS_LINE];
out.old = /one run|run is in progress|current run ends/.test(JSON.stringify([lm.RUN_LINE, lm.QUEUE_REASON, lm.BUSY_NOTICE, lm.TASKS_LINE]));
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_composer_note_names_the_running_tasks_and_the_router_busy_only_while_routing(tmp_path):
    got = run_node(tmp_path, LOBBY)
    assert got["none"] is None
    assert got["one"]["text"] == "Task #10 Build 0" and got["one"]["href"].endswith("/floor/engineering") and got["one"]["line"] == got["lines"][3]
    assert got["two"]["text"] == "2 tasks running" and got["two"]["href"] == "#/p/0123456789ab", "several tasks: the count, linking to the Building"
    assert got["routing"]["text"] == "Planning agent · routing request #1 · for 2 min" and got["routing"]["line"] == got["lines"][0]
    assert got["running"] == [[10, 11, 12], 0]
    assert got["busy"] == [False, False, True, True], "Route it is queued only behind another request's router run (a run on the request itself is its own routing)"
    assert got["old"] is False, "no sentence says one run at a time or that a run is in progress"


COMPOSER = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { createComposer } from "@JS@/views/lobby-composer.js";
const text = (n) => n.textContent;
const sent = [];
const composer = createComposer({ onSend: (t) => sent.push(t) });
const field = find(composer.el, "textarea");
const send = find(composer.el, "button.wb-send");
const out = {};
composer.set({ sending: false, notice: null, disabled: false, running: { text: "2 tasks running", href: "#/p/x/building", line: "Your line is routed at once." } });
out.tasks = { line: text(find(composer.el, ".wb-lobby-run")), hidden: find(composer.el, ".wb-lobby-run").hidden, field: field.disabled, send: send.disabled };
composer.set({ sending: false, notice: null, disabled: false, running: { text: "Planning agent · routing request #2", href: "#/r", line: "The planning agent is answering another request: your line is routed when it ends; a question about the state is answered now." } });
out.routing = { line: text(find(composer.el, ".wb-lobby-run")), field: field.disabled, send: send.disabled };
composer.set({ sending: true, notice: null, disabled: false, running: null });
out.sending = { field: field.disabled, send: send.disabled };
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_composer_stays_on_during_a_task_run_and_during_routing_and_is_busy_only_while_a_turn_is_sent(tmp_path):
    got = run_node(tmp_path, COMPOSER, FLOOR_DOM)
    assert "2 tasks running" in got["tasks"]["line"] and "routed at once" in got["tasks"]["line"] and got["tasks"]["field"] is False and got["tasks"]["send"] is False
    assert "answering another request" in got["routing"]["line"] and got["routing"]["send"] is False, "Send stays on while the router works; the line is stored and routed after"
    assert got["sending"] == {"field": True, "send": True}
    lobby = (JS / "views" / "lobby.js").read_text(encoding="utf-8")
    assert "routerBusy" in (JS / "views" / "lobby-thread.js").read_text(encoding="utf-8"), "the request line asks the model whether the router is busy"
    assert "runNote" in lobby, "the Lobby asks the model for the composer's note"


# --- the plan's limits line --------------------------------------------------------------------------------------------------------------

LIMITS = r"""
import { limitsLine } from "@JS@/cards/plan-rows.js";
import { limitsLine as cardLimits } from "@JS@/floor/cards.js";
const item = (limits, estimate = { runs_at_least: 4 }) => ({ payload: { limits, estimate } });
const out = {};
out.rows = [limitsLine(item({ max_running: 3, timeout_seconds: 1800, retries: 2 })), limitsLine(item({ max_running: 1, timeout_seconds: 1800, retries: 1 })), limitsLine(item({ timeout_seconds: 1800, retries: 2 })),
  limitsLine(item({ one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 }))];
out.cards = [cardLimits({ limits: { max_running: 3, timeout_seconds: 1800, retries: 2 }, estimate: { runs_at_least: 4 } }), cardLimits({ limits: { max_running: 1, timeout_seconds: 60, retries: 0 } }),
  cardLimits({ limits: { timeout_seconds: 1800, retries: 2 } }), cardLimits({ limits: { one_task_at_a_time: true, timeout_seconds: 1800, retries: 2 } })];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_limits_line_says_how_many_tasks_run_at_a_time_from_max_running(tmp_path):
    got = run_node(tmp_path, LIMITS)
    assert got["rows"][0] == "Up to 3 tasks at a time; each run at most 1800 s, retried at most 2 times. At least 4 runs."
    assert got["rows"][1].startswith("Up to 1 task at a time; ") and got["rows"][2] == "each run at most 1800 s, retried at most 2 times. At least 4 runs."
    assert got["rows"][3] == got["rows"][2], "the old key says nothing any more"
    assert got["cards"][0] == "Up to 3 tasks at a time; each run at most 1800 s, retried at most 2 times. At least 4 runs."
    assert got["cards"][1].startswith("Up to 1 task at a time; each run at most 60 s") and got["cards"][2].startswith("Each run at most 1800 s")
    assert got["cards"][3] == got["cards"][2]


# --- no word of the old rule is left in the page ---------------------------------------------------------------------------------------

def test_no_file_of_the_page_keeps_the_old_one_task_at_a_time_rule():
    old = re.compile(r"job running|one_task_at_a_time|one run at a time|One task at a time|current run ends|A run is in progress|Nothing is running")
    found = {}
    for path in sorted((INTERFACE / "js").rglob("*.js")) + sorted((INTERFACE / "demo").glob("*.js")):
        if "scene" in path.relative_to(INTERFACE).parts:
            continue
        hits = [m.group(0) for m in old.finditer(path.read_text(encoding="utf-8"))]
        if hits:
            found[str(path.relative_to(INTERFACE))] = sorted(set(hits))
    # the one phrase that stays is the tracking bar's "Nothing is running": no task runs, which is still true
    found = {k: [h for h in v if h != "Nothing is running"] for k, v in found.items()}
    assert {k: v for k, v in found.items() if v} == {}


# --- the demo ---------------------------------------------------------------------------------------------------------------------------

DEMO = r"""
import { buildState } from "@DEMO@/world-state.js";
import { dispatch } from "@DEMO@/world-writes.js";
import * as reads from "@DEMO@/world-reads.js";

const NOW = Date.UTC(2026, 9, 12, 12, 0, 0);
const ctx = { now: () => NOW };
const state = await buildState(ctx, 0);
const P = state.projects["3f9a1c07d2b4"];
const out = {};
const make = (id, agent, key, skill, state = "ready") => ({ ...P.tasks.find((t) => t.parent_id !== null), id, agent, key, skill, title: key, state, depends_on: [], parent_id: 1, updated_at: "x" });
const reset = () => { P.tasks = P.tasks.filter((t) => t.id < 100); P.runs = P.runs.filter((r) => r.task_id < 100); };
const states = () => Object.fromEntries(P.tasks.filter((t) => t.id >= 100).map((t) => [t.id, t.state]));
const heldOf = () => reads.status(P).held.map((h) => [h.task_id, h.reason]);

// two ready tasks of two agents start in one round
P.tasks.push(make(100, "design", "d", "design-handoff"), make(101, "marketing", "m", "mkt-social-copy"));
out.two = [dispatch(ctx, P), states(), reads.projectsList({ projects: { [P.id]: P }, generation: 0 }).projects.find((p) => p.name === "northwind-shop").running_tasks];
out.statusRows = reads.status(P).requests.flatMap((r) => r.tasks).filter((t) => t.id >= 100).map((t) => [t.id, t.holds_slot]);
reset();

// a floor with max_parallel 1: the second task of the floor waits and says why
P.agents.find((a) => a.name === "design").maxParallel = 1;
P.tasks.push(make(100, "design", "d1", "design-handoff"), make(101, "design", "d2", "design-system"));
out.slot = [dispatch(ctx, P), states(), heldOf()];
out.agent = reads.agents(P).agents.filter((a) => a.name === "design").map((a) => [a.max_parallel, a.max_parallel_ceiling, a.slots_held, a.holders]);
reset();

// a floor with two slots starts two; the third waits; the same skill never runs twice at once
const eng = P.agents.find((a) => a.name === "engineering");
eng.maxParallel = 2;
P.tasks.push(make(100, "engineering", "e1", "eng-implement"), make(101, "engineering", "e2", "eng-docs"), make(102, "engineering", "e3", "eng-unit-tests"));
out.two_slots = [dispatch(ctx, P), states(), heldOf()];
out.engine = reads.agents(P).agents.filter((a) => a.name === "engineering").map((a) => [a.max_parallel, a.slots_held, a.holders]);
reset();
P.tasks.push(make(100, "engineering", "e1", "eng-docs"), make(101, "design", "d1", "eng-docs"));
out.same_skill = [dispatch(ctx, P), states(), heldOf()];
reset();

// the project's limit: four ready tasks of four agents, three start
P.agents.push({ name: "ops", pack: "ops", enabled: true, mode: "supervised", maxRuns: 6, maxUsd: 0, runs: 0, usd: 0 });
P.tasks.push(make(100, "design", "a", "design-handoff"), make(101, "marketing", "b", "mkt-social-copy"), make(102, "engineering", "c", "eng-docs"), make(103, "ops", "d", "ops-pull-request"));
out.limit = [dispatch(ctx, P), states(), heldOf()];
reset();

// a router run holds a request: it takes no slot and stops no task
P.routing = { request: 1, run_id: 99, skill: "core-orchestrator", started_at: "x" };
P.tasks.push(make(100, "design", "a", "design-handoff"));
out.routing = [dispatch(ctx, P), states()];
P.routing = null;
console.log(JSON.stringify(out));
"""


def run_demo(tmp_path):
    script = tmp_path / "demo.mjs"
    script.write_text(DEMO.replace("@DEMO@", (INTERFACE / "demo").as_uri()), encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=90)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
def test_the_demo_dispatch_starts_every_ready_task_its_rule_allows(tmp_path):
    got = run_demo(tmp_path)
    assert got["two"][0] == [100, 101] and got["two"][1] == {"100": "running", "101": "running"} and got["two"][2] == [100, 101]
    assert got["statusRows"] == [[100, True], [101, True]]
    assert got["slot"][0] == [100] and got["slot"][1] == {"100": "running", "101": "ready"} and got["slot"][2] == [[101, "agent at max_parallel"]]
    assert got["agent"] == [[1, 4, 1, [100]]]
    assert got["two_slots"][0] == [100, 101] and got["two_slots"][2] == [[102, "agent at max_parallel"]]
    assert got["engine"] == [[2, 2, [100, 101]]]
    assert got["same_skill"][0] == [100] and got["same_skill"][2] == [[101, "artifact in use"]], "tasks of one skill write the same files: one after the other"
    assert got["limit"][0] == [100, 101, 102] and got["limit"][2] == [[103, "project at max_running"]]
    assert got["routing"][0] == [100], "a router run takes no slot and stops no task"


def test_the_demo_fixtures_show_two_running_tasks_of_two_agents():
    fixtures = INTERFACE / "demo" / "fixtures"
    live = json.loads((fixtures / "status-live.json").read_text(encoding="utf-8"))
    running = [t for r in live["requests"] for t in r["tasks"] if t["state"] == "running"]
    assert len(running) == 2 and len({t["agent"] for t in running}) == 2, "two running tasks of two agents"
    assert all(t["holds_slot"] for t in running)
    projects = json.loads((fixtures / "projects.json").read_text(encoding="utf-8"))
    assert projects["projects"][0]["running_tasks"] == sorted(t["id"] for t in running) and projects["projects"][0]["running_task"] == min(t["id"] for t in running)
    agents = json.loads((fixtures / "agents.json").read_text(encoding="utf-8"))
    assert all({"max_parallel", "max_parallel_ceiling", "slots_held", "holders"} <= set(a) for a in agents["agents"])


def test_the_demo_readers_and_writers_state_the_new_rule():
    reads = (INTERFACE / "demo" / "world-reads.js").read_text(encoding="utf-8")
    for word in ("running_tasks", "holds_slot", "max_parallel", "slots_held", "holders", "max_parallel_ceiling"):
        assert word in reads, f"world-reads.js gives {word}"
    writes = (INTERFACE / "demo" / "world-writes.js").read_text(encoding="utf-8")
    assert "Up to ${MAX_RUNNING} tasks at a time" in writes or "Up to 3 tasks at a time" in writes


ACROSS = COMMON + r"""
const status2 = { requests: [
  { id: 1, title: "A", state: "ready", tasks: [task(4, "running", "engineering"), task(5, "running", "engineering")] },
  { id: 2, title: "B", state: "ready", tasks: [task(8, "running", "engineering"), task(9, "running", "marketing")] }], pending: [], held: [], documents: [] };
const snap = { projects: [{ id: P, name: "n", config: { accepted: true } }], details: { [P]: { status: status2, agents: [agent("planning"), agent("engineering"), agent("marketing")] } }, tasks: {}, loaded: true };
const view = fm.building(snap, P);
const row = (n) => view.rows.find((r) => r.name === n);
out.running = [row("engineering").running, row("marketing").running, row("engineering").counts, row("marketing").counts, fm.plateOf(row("marketing")).running];
console.log(JSON.stringify(out));
"""


@needs_node
def test_running_counts_every_running_task_of_the_agent_whatever_its_request(tmp_path):
    got = run_node(tmp_path, ACROSS)
    assert got["running"][:2] == [3, 1], "engineering runs 3 tasks over two requests, marketing one that is in another request than the followed one"
    assert "3 running" in got["running"][2] and "1 running" in got["running"][3] and got["running"][4] == 1

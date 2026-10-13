"""PAR-7e: each owl of a floor is selected on its own (SPEC-PAR-7 section 12). The pointer, the brackets, the tooltip and the click treat an owl as one thing: an owl that holds a task
names that task and opens it (the Tasks tab with the task open, or its decision in the Inbox when it waits for the person), an owl of a free slot says it is asleep and opens the
Agent tab, and an owl the floor's own state draws (no task holds a slot) keeps the floor's tooltip and click. The words and the destinations are one pure function
(`owl-words.js`) that `world-model.js` calls and the views read; the scene picks one group for each owl; the HTML twin of the owls is a list with one link for each.

No browser and no model: the pure modules and the real views run under Node, the room builders with the real three.js and no WebGL, as the other scene tests do.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_owl_pick.py
"""
from __future__ import annotations

import standin_tree as st
from test_interface_cards_fields import run_node as run_dom_node
from test_interface_parallel import COMMON as MODEL_COMMON
from test_interface_plates_meters import run_node as run_model_node
from test_interface_scene_round3 import WORLD_JS, needs_node, run_node
from interface_css import interface_css

JS = st.REPO / "interface" / "js"

# A project whose engineering agent has `slots` places and the given tasks; `pending` are the open decisions.
SNAP = MODEL_COMMON + r"""
import { worldModel } from "@JS@/world-model.js";
const eng = (id, state, hold = true, extra = {}) => task(id, state, "engineering", { holds_slot: hold, ...extra });
const make = (tasks, slots, { pending = [], agentExtra = {} } = {}) => {
  const snap = snapshot(tasks, [agent("planning"), agent("engineering", { max_parallel: slots, ...agentExtra })], {});
  snap.details[P].status.pending = pending;
  return snap;
};
const owlsOf = (snap, name = "engineering", room = {}) => worldModel(snap, NOW, { focus: P, floor: name, room: { tips: { agent: `${name === "planning" ? "Planning agent" : "Engineering"} · working` }, board: null, door: name === "planning", ...room } }).room.owls;
const brief = (owls) => owls.map((o) => [o.seat, o.id, o.tip, o.route.tab, o.route.id === undefined ? null : o.route.id]);
"""


# --- the words and the destination of each owl ----------------------------------------------------------------------------------------------

@needs_node
def test_an_owl_of_a_task_names_the_task_and_opens_it_and_a_free_owl_is_asleep_and_opens_the_agent_tab(tmp_path):
    got = run_model_node(tmp_path, SNAP + r"""
const decision = { id: 31, kind: "review", task_id: 6, agent: "engineering", title: "Review" };
// three places: task 4 runs, task 6 waits for the person and has a decision, the third place is free
out.mixed = brief(owlsOf(make([eng(4, "running"), eng(6, "waiting")], 3, { pending: [decision] })));
// a waiting task with no decision of its own opens its row; a task about to run again says it is queued
out.plain = brief(owlsOf(make([eng(7, "waiting"), eng(9, "ready")], 2)));
// the task's own title is the words; a task with no title says its key
out.key = brief(owlsOf(make([eng(8, "running", true, { title: "" })], 1)));
console.log(JSON.stringify(out));
""")
    assert got["mixed"] == [
        [0, "owl:0", "#4 Task 4 · working", "tasks", 4],
        [1, "owl:1", "#6 Task 6 · waiting for you · open the Inbox", "inbox", 31],
        [2, "owl:2", "Free slot · asleep", "agent", None],
    ], "a working owl opens its task, a waiting owl its decision in the Inbox, a free owl the Agent tab; the words are '#<id> <title> · <state words>' and 'Free slot · asleep'"
    assert got["plain"] == [
        [0, "owl:0", "#7 Task 7 · waiting for you", "tasks", 7],
        [1, "owl:1", "#9 Task 9 · queued · starts when a slot frees", "tasks", 9],
    ], "a waiting task without a decision opens the Tasks tab; a ready holder says queued as the floor's tooltip does"
    assert got["key"] == [[0, "owl:0", "#8 k8 · working", "tasks", 8]], "a task with no title is named by its key"


@needs_node
def test_a_floor_with_no_holder_keeps_its_floor_tooltip_and_click_on_the_owl_its_state_draws(tmp_path):
    got = run_model_node(tmp_path, SNAP + r"""
const decision = { id: 40, kind: "plan", task_id: 12, agent: "engineering", title: "Plan" };
// no task holds a slot, a decision of the agent waits: seat 0 is the floor's owl and asks, the other place is free
out.asks = brief(owlsOf(make([eng(12, "blocked", false)], 2, { pending: [decision] })));
// the floor is queued (a ready task that holds no slot): seat 0 is awake with the floor's words
out.queued = brief(owlsOf(make([eng(13, "ready", false)], 2, { agentExtra: { queued: 1 } }), "engineering", { tips: { agent: "Engineering · queued · starts when a slot frees" } }));
// nothing at all: the one place of a one-slot floor is free
out.rest = brief(owlsOf(make([], 1)));
out.rest3 = brief(owlsOf(make([], 3)));
// the Lobby while the router runs: its one owl types with the floor's words, a click goes to the Agent tab
out.lobby = brief(owlsOf(make([], 1), "planning", { state: "working", window: "lit" }));
out.lobbyIdle = brief(owlsOf(make([], 1), "planning"));
console.log(JSON.stringify(out));
""")
    assert got["asks"] == [[0, "tray", "Engineering · working · open the Inbox", "inbox", None], [1, "owl:1", "Free slot · asleep", "agent", None]], \
        "the owl the floor's state draws (no holder, a decision open) keeps the floor's tooltip and opens the Inbox as it did"
    assert got["queued"][0] == [0, "agent", "Engineering · queued · starts when a slot frees", "agent", None] and got["queued"][1][2] == "Free slot · asleep"
    assert got["rest"] == [[0, "agent", "Engineering · working", "agent", None]], "a floor at rest with one place: seat 0 is the floor's owl, never a free slot"
    assert got["rest3"] == [[0, "agent", "Engineering · working", "agent", None], [1, "owl:1", "Free slot · asleep", "agent", None], [2, "owl:2", "Free slot · asleep", "agent", None]], "three places, no holder: seat 0 the floor's words, the others free slots"
    assert got["lobbyIdle"] == [[0, "agent", "Planning agent · working", "agent", None]], "the Lobby has no slots: its owl, asleep too, is never a free slot"
    assert got["lobby"] == [[0, "agent", "Planning agent · working", "agent", None]], "the Lobby's routing owl keeps the Lobby's tooltip and the Agent tab"


@needs_node
def test_a_floor_that_is_off_has_no_owl_to_select(tmp_path):
    got = run_model_node(tmp_path, SNAP + r"""
const snap = make([eng(4, "done", false)], 3, { agentExtra: { enabled: false } });
const room = worldModel(snap, NOW, { focus: P, floor: "engineering", room: { tips: { agent: "x" }, board: null, door: false } }).room;
out.owls = room.owls;
out.seats = worldModel(snap, NOW, { focus: P, floor: "engineering", room: { tips: {}, board: null, door: false } }).lots[0].floors.find((f) => f.name === "engineering").seats.map((s) => s.pose);
console.log(JSON.stringify(out));
""")
    assert got["seats"] == [None, None, None] and got["owls"] == [], "a stopped floor keeps its desks and has no owl: nothing to hover, nothing to click"


# --- the scene: one pick target and one set of brackets for each owl ---------------------------------------------------------------

WORLD_OWLS = WORLD_JS + r"""
import { pickList } from "@JS@/scene/pick.js";
const r3 = (v) => Math.round(v * 1000) / 1000;
const seatsOf3 = [{ seat: 0, pose: "working", taskId: 4 }, { seat: 1, pose: "waiting", taskId: 6 }, { seat: 2, pose: "idle", taskId: null }];
const owls3 = [
  { seat: 0, id: "owl:0", tip: "#4 Task 4 · working", kind: "task", route: { tab: "tasks", id: 4 } },
  { seat: 1, id: "owl:1", tip: "#6 Task 6 · waiting for you · open the Inbox", kind: "task", route: { tab: "inbox", id: 31 } },
  { seat: 2, id: "owl:2", tip: "Free slot · asleep", kind: "free", route: { tab: "agent" } },
];
const withSeats = (seats, extra = {}) => lot("a").floors.map((f) => (f.name === "business" ? { ...f, state: "working", window: "lit", seats, ...extra } : f));
const room = (owls) => ({ tips: { agent: "a", desk: "d", tray: "t" }, board: { title: "t", lines: ["x"], dot: "theme" }, door: false, ...(owls ? { owls } : {}) });
function build(seats, owls, extra = {}) {
  const { world, kit, scene } = make();
  const m = model({ lots: [lot("a", { floors: withSeats(seats, extra) }), lot("b"), lot("c")], focus: "a", floor: "business", room: room(owls) });
  world.setFocus("a", true);
  world.update(m);
  world.setFloors("business", null, true);
  scene.updateMatrixWorld(true);
  return { world, kit, scene, m };
}
const centre = (object) => new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3());
const around = (marks, point) => { const b = new THREE.Box3().setFromObject(marks); return b.min.x <= point.x && point.x <= b.max.x && b.min.z <= point.z && point.z <= b.max.z; };
const out = {};
"""


@needs_node
def test_two_owls_of_one_floor_are_two_pick_targets_each_with_its_own_tip(tmp_path):
    got = run_node(tmp_path, WORLD_OWLS + r"""
const { world, scene, m } = build(seatsOf3, owls3);
out.ids = world.hits.map((h) => h.id);
out.tips = world.hits.filter((h) => h.id.startsWith("owl:")).map((h) => h.tip);
const owlHits = world.hits.filter((h) => h.id.startsWith("owl:"));
out.distinct = new Set(owlHits.map((h) => h.object)).size;
const list = pickList(world.hits);
out.owned = owlHits.map((h) => list.meshes.filter((mesh) => list.owner.get(mesh) === h).length > 0);
out.anchors = new Set(owlHits.map((h) => `${r3(h.anchor.x)},${r3(h.anchor.z)}`)).size;
// a poll that changes the words changes the tooltips and builds nothing again
const words = world.text(m).tips;
out.words = [words.get("owl:0"), words.get("owl:1"), words.get("owl:2")];
console.log(JSON.stringify(out));
""")
    assert got["ids"] == ["owl:0", "owl:1", "owl:2", "tasks", "desk"], "one hit for each owl, then the board and the bookcase (the owls are not one group any more)"
    assert got["tips"] == ["#4 Task 4 · working", "#6 Task 6 · waiting for you · open the Inbox", "Free slot · asleep"], "each hit has its own tip"
    assert got["distinct"] == 3 and got["owned"] == [True, True, True], "each hit is its own group and the pick finds meshes of each"
    assert got["anchors"] == 3, "each tooltip stands over its own owl"
    assert got["words"] == got["tips"], "the world's text() gives the tooltip of each owl, so that a poll refreshes them"


@needs_node
def test_the_brackets_of_a_hovered_owl_enclose_that_owl_alone(tmp_path):
    got = run_node(tmp_path, WORLD_OWLS + r"""
const { world } = build(seatsOf3, owls3);
const owlHits = world.hits.filter((h) => h.id.startsWith("owl:"));
out.distinct = new Set(owlHits.map((h) => h.marks)).size;
out.hidden = owlHits.map((h) => h.marks.visible);
out.holders = owlHits.map((h) => h.marks.userData.brackets === true);
out.encloses = owlHits.map((hit) => owlHits.map((other) => around(hit.marks, centre(other.object))));
console.log(JSON.stringify(out));
""")
    assert got["distinct"] == 3 and got["hidden"] == [False, False, False] and got["holders"] == [True, True, True], "three sets of brackets, hidden until the pointer is on their owl, never picked"
    assert got["encloses"] == [[True, False, False], [False, True, False], [False, False, True]], "the brackets of an owl are round that owl and no other"


@needs_node
def test_a_floor_whose_owl_the_state_draws_keeps_the_floors_hit_and_a_caller_with_no_owls_keeps_one_hit(tmp_path):
    got = run_node(tmp_path, WORLD_OWLS + r"""
// no holder, a decision waits: seat 0 is the floor's owl (id tray, the floor's words), seat 1 is a free place
const waiting = [{ seat: 0, pose: "waiting", taskId: null }, { seat: 1, pose: "idle", taskId: null }];
const floorOwls = [{ seat: 0, id: "tray", tip: "business · waiting for you · open the Inbox", kind: "floor", route: { tab: "inbox" } }, { seat: 1, id: "owl:1", tip: "Free slot · asleep", kind: "free", route: { tab: "agent" } }];
const a = build(waiting, floorOwls, { state: "waiting", decisions: 2 });
out.floorOwl = a.world.hits.map((h) => [h.id, h.tip]);
// a caller that gives the world no `owls` (an older test, an older service) gets today's one hit round the owls
const b = build(seatsOf3, null);
out.legacy = b.world.hits.map((h) => h.id);
// a floor that is off has no owl hit
const stopped = build([{ seat: 0, pose: null, taskId: null }, { seat: 1, pose: null, taskId: null }], [], { state: "off" });
out.off = stopped.world.hits.map((h) => h.id);
console.log(JSON.stringify(out));
""")
    assert got["floorOwl"][:2] == [["tray", "business · waiting for you · open the Inbox"], ["owl:1", "Free slot · asleep"]], "the floor's own owl keeps its floor tooltip and the Inbox id"
    assert got["legacy"] == ["agent", "tasks", "desk"], "with no owls given: today's single hit"
    assert got["off"] == ["tasks", "desk"], "a floor that is off: no owl hit"


# --- the click and the keyboard twin ---------------------------------------------------------------------------------------------------------

FLOOR_PAGE = r"""
import { FakeNode, settle, find, all } from "@FAKE@";
import { setToken } from "@JS@/token.js";
import * as router from "@JS@/router.js";
import { createFloorView } from "@JS@/views/floor.js";

setToken("t".repeat(40));
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
document.removeEventListener = (type, fn) => { document.listeners[type] = (document.listeners[type] || []).filter((f) => f !== fn); };
const P = "0123456789ab";
const NOW = new Date("2026-10-12T12:00:00Z");
globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
const agent = (name, extra = {}) => ({ name, pack: "x", enabled: true, mode: "supervised", acting_mode: "supervised", max_runs_per_day: 8, max_usd_per_day: 4, runs_today: 1, usd_today: 0.1, runs_without_cost: 0, queued: 0, max_parallel: 1, ...extra });
const task = (id, state, hold) => ({ id, key: `k${id}`, title: `Task ${id}`, skill: "s", state, note: null, agent: "engineering", holds_slot: hold });
const status = { requests: [{ id: 1, title: "Spring", state: "ready", tasks: [task(4, "running", true), task(6, "waiting", true)] }],
  pending: [{ id: 31, kind: "review", title: "Review", task_id: 6, agent: "engineering", created_at: "2026-10-12T08:00:00Z", actions: ["answered"] }], documents: [] };
const snapshot = { loaded: true, projects: [{ id: P, name: "northwind-shop", config: { accepted: true } }], tasks: {},
  details: { [P]: { agents: [agent("engineering", { max_parallel: 3 }), agent("planning")], status } } };
const lit = [];
const makeFrame = () => ({ el: new FakeNode("div"), main: new FakeNode("main"), track: { el: new FakeNode("div") }, noticeBox: new FakeNode("div"),
  insets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1 }), isPhone: () => false, sceneUnavailable() {}, announce() {},
  acquireWorld: () => ({ show() {}, setOptions() {}, refit() {}, stats() { return {}; }, highlight(id, source) { lit.push([id, source || "pointer"]); } }) });
const walk = (root) => [...root.walk()];
const base = `#/p/${P}/floor/engineering`;
const out = {};
const frame = makeFrame();
window.location.hash = base;
const view = createFloorView(frame, { refresh() {} });
view.update({ snapshot, route: router.parse(base), now: NOW });
await settle();
await settle();
"""


@needs_node
def test_a_click_on_an_owl_opens_that_owls_task_or_decision_or_the_agent_tab(tmp_path):
    got = run_dom_node(tmp_path, FLOOR_PAGE + r"""
const opened = [];
for (const id of ["owl:0", "owl:1", "owl:2", "owl:3", "agent"]) {
  window.location.hash = "#/";
  view.open(id);
  opened.push(window.location.hash);
}
out.opened = opened;
console.log(JSON.stringify(out));
""")
    base = "#/p/0123456789ab/floor/engineering"
    assert got["opened"] == [f"{base}/tasks/4", f"{base}/inbox/31", f"{base}/agent", "#/", f"{base}/agent"], \
        "a working owl opens its task, a waiting one its decision, a free one the Agent tab; an owl that is not there opens nothing; the floor's own owl keeps its tab"


@needs_node
def test_the_owls_have_a_twin_list_in_seat_order_with_the_tooltips_words_and_the_scene_follows_the_focus(tmp_path):
    got = run_dom_node(tmp_path, FLOOR_PAGE + r"""
const links = walk(frame.main).filter((n) => n.tagName === "A" && (n.attrs.class || "").includes("wb-owl-link"));
out.links = links.map((n) => [n.textContent, n.attrs.href]);
const listEl = walk(frame.main).find((n) => (n.attrs.class || "").includes("wb-owls"));
out.list = listEl ? [listEl.attrs["aria-label"], listEl.hidden === true] : null;
(links[1].listeners.focus || []).forEach((fn) => fn({}));
(links[1].listeners.blur || []).forEach((fn) => fn({}));
(links[2].listeners.pointerenter || []).forEach((fn) => fn({}));
(links[2].listeners.pointerleave || []).forEach((fn) => fn({}));
out.lit = lit.slice();
console.log(JSON.stringify(out));
""")
    base = "#/p/0123456789ab/floor/engineering"
    assert got["links"] == [
        ["#4 Task 4 · working", f"{base}/tasks/4"],
        ["#6 Task 6 · waiting for you · open the Inbox", f"{base}/inbox/31"],
        ["Free slot 3 of 3 · asleep", f"{base}/agent"],
    ], "one focusable link for each owl, in seat order, with the tooltip's words and the click's destination"
    assert got["list"] == ["Owls of this floor", False]
    assert got["lit"] == [["owl:1", "keyboard"], [None, "keyboard"], ["owl:2", "pointer"], [None, "pointer"]], \
        "the focus on a link brackets its owl in the scene as the focus on a floor's row does in the Building"


@needs_node
def test_the_tasks_tab_opens_the_task_the_route_names(tmp_path):
    got = run_dom_node(tmp_path, FLOOR_PAGE + r"""
const go = async (hash) => { window.location.hash = hash; view.update({ snapshot, route: router.parse(hash), now: NOW }); await settle(); await settle(); };
const toggles = () => Object.fromEntries(walk(frame.main).filter((n) => n.tagName === "BUTTON" && (n.attrs["data-key"] || "").startsWith("toggle-")).map((n) => [n.attrs["data-key"], n.attrs["aria-expanded"]]));
await go(`${base}/tasks`);
out.plain = toggles();
await go(`${base}/tasks/6`);
out.named = toggles();
out.focus = document.activeElement && document.activeElement.attrs["data-key"];
console.log(JSON.stringify(out));
""")
    assert got["plain"] == {"toggle-4": "false", "toggle-6": "false"}, "the Tasks tab with no task named: every row closed"
    assert got["named"] == {"toggle-4": "false", "toggle-6": "true"} and got["focus"] == "toggle-6", "the task the route names is open and holds the focus"


# --- the files ---------------------------------------------------------------------------------------------------------------------------------

def test_the_views_route_an_owl_through_the_one_function_and_the_lobby_does_too():
    owl_words = (JS / "owl-words.js").read_text(encoding="utf-8")
    assert "export function owlTargets" in owl_words and "Free slot · asleep" in owl_words
    for name in ("floor.js", "lobby.js"):
        text = (JS / "views" / name).read_text(encoding="utf-8")
        assert "openOwl(" in text, f"{name}: a click on an owl goes through openOwl"
        assert "createOwlList(" in text, f"{name}: the owls' twin list"
    world = (JS / "scene" / "world.js").read_text(encoding="utf-8")
    assert "room.owls" in world and "o.marks" in world, "the world makes a hit of each owl from the room's owls"
    building = (JS / "scene" / "building.js").read_text(encoding="utf-8")
    assert "marks" in building and "boxBrackets" in building


def test_the_owl_list_is_styled_and_clipped_until_it_has_the_focus():
    css = interface_css()
    assert ".wb-owls" in css and ".wb-owls:focus-within" in css and ".wb-owl-link" in css
    text = (JS / "floor" / "owl-list.js").read_text(encoding="utf-8")
    assert 'class: "wb-owls' in text and "innerHTML" not in text, "the list is built with the dom helper: text, never markup"


# --- an awake owl lights the floor (SPEC-PAR-7 section 12.1) -----------------------------------------------------------------------------------

@needs_node
def test_a_floor_is_lit_when_any_owl_is_awake_and_the_city_follows(tmp_path):
    got = run_model_node(tmp_path, SNAP + r"""
const lit = (snap) => {
  const row = fm.building(snap, P).rows.find((r) => r.name === "engineering");
  const city = model.buildingOf(snap.projects[0], snap.details[P]).floors.find((f) => f.agent === "engineering");
  const world = worldModel(snap, NOW, { focus: P, floor: "engineering", room: { tips: {}, board: null, door: false } }).lots[0].floors.find((f) => f.name === "engineering");
  return [row.state, row.window, city.window, world.window];
};
// a holder that is ready (answered, about to run again) leaves the floor idle, but its owl is awake: lit
out.ready = lit(make([eng(4, "ready", true)], 2));
// two places, every owl asleep: grey
out.asleep = lit(make([], 2));
// a stopped floor: as today
out.off = lit(make([eng(4, "done", false)], 2, { agentExtra: { enabled: false } }));
// a ready task that holds no slot and nothing else: as today (queued is its own rule)
out.noHolder = lit(make([eng(5, "blocked", false)], 2));
console.log(JSON.stringify(out));
""")
    assert got["ready"] == ["idle", "lit", "lit", "lit"], "an idle floor whose holder is ready has an awake owl: lit in the Floor, the Building and the City"
    assert got["asleep"][1:] == ["grey", "grey", "grey"] and got["off"][1:] == ["grey", "grey", "grey"] and got["noHolder"][1:] == ["grey", "grey", "grey"]


@needs_node
def test_free_places_are_told_apart_in_the_list_and_not_in_the_tooltip(tmp_path):
    got = run_model_node(tmp_path, SNAP + r"""
import { createOwlList } from "@JS@/floor/owl-list.js";
const owls = owlsOf(make([], 3));
out.tips = owls.map((o) => o.tip);
out.list = owls.map((o) => o.listTip);
console.log(JSON.stringify(out));
""")
    assert got["tips"] == ["Engineering · working", "Free slot · asleep", "Free slot · asleep"], "seat 0 is the floor's owl; the free slots' tooltip in the scene stays as the table says"
    assert got["list"][1:] == ["Free slot 2 of 3 · asleep", "Free slot 3 of 3 · asleep"], "the list's links differ (link purpose)"


@needs_node
def test_escape_on_a_task_goes_back_to_the_tasks_list_and_on_a_decision_to_the_inbox(tmp_path):
    got = run_model_node(tmp_path, r"""
import * as router from "@JS@/router.js";
import { escapeStep } from "@JS@/frame/escape.js";
const P = "0123456789ab";
const go = (h) => escapeStep({ route: router.parse(h) }).hash;
console.log(JSON.stringify([go(`#/p/${P}/floor/engineering/tasks/4`), go(`#/p/${P}/floor/engineering/inbox/31`), go(`#/p/${P}/lobby/tasks/4`), go(`#/p/${P}/lobby/inbox/5`), go(`#/p/${P}/lobby/conversation/5`)]));
""")
    p = "#/p/0123456789ab"
    assert got == [f"{p}/floor/engineering/tasks", f"{p}/floor/engineering/inbox", f"{p}/lobby/tasks", f"{p}/lobby/inbox", f"{p}/lobby/inbox"]


@needs_node
def test_a_stopped_floor_with_a_holder_stays_dark_everywhere(tmp_path):
    got = run_model_node(tmp_path, SNAP + r"""
const snap = make([eng(4, "ready", true)], 2, { agentExtra: { enabled: false } });
const row = fm.building(snap, P).rows.find((r) => r.name === "engineering");
const city = model.buildingOf(snap.projects[0], snap.details[P]).floors.find((f) => f.agent === "engineering");
const world = worldModel(snap, NOW, { focus: P, floor: "engineering", room: { tips: {}, board: null, door: false } }).lots[0].floors.find((f) => f.name === "engineering");
console.log(JSON.stringify([row.state, row.window, city.window, world.window]));
""")
    assert got == ["off", "grey", "grey", "grey"], "a stopped agent's ready holder lights nothing"


@needs_node
def test_the_brackets_round_all_the_owls_are_made_only_when_asked_for(tmp_path):
    got = run_node(tmp_path, WORLD_OWLS + r"""
const { world } = build(seatsOf3, owls3);
const count = () => { let n = 0; world.towers.get("a").parts.forEach((p) => { if (p) p.owls.forEach(() => n++); }); return n; };
const parts = world.towers.get("a").parts.find((p) => p && p.owls.length);
let holders = 0; parts.agent.parent.children.forEach((c) => { if (c.userData && c.userData.brackets) holders++; });
out.before = holders;
parts.marks.agent;
let after = 0; parts.agent.parent.children.forEach((c) => { if (c.userData && c.userData.brackets) after++; });
out.after = after;
console.log(JSON.stringify(out));
""")
    assert got["after"] == got["before"] + 1, "the group's brackets are built on the first ask, never for a world that gives each owl its words"

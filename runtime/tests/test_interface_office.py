"""Tests of the office of the local interface, slice 1 (interface/js/views/office.js, interface/js/office/*.js, css/office.css): the router form and
Escape, the number and the agents the office takes from the snapshot, the room, the ported A* (the cases of its source, translated), the walk, the
sprite cache, the zoom, the view under a fake document with a recording 2D context and a manual frame scheduler, and the text rules (no client call,
no 3D, every class styled, the licence notice kept). No browser and no service: the served files are `test_service_office_page.py`'s.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_office.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import standin_tree as st
from interface_css import interface_css
from test_interface_lobby import needs_node, run_node

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
OFFICE = JS / "office"
PROJECT = "0123456789ab"
# The check of scripts/validate.py (PORTUGUESE_RE), written as escapes so that this file passes it too.
PORTUGUESE_RE = re.compile(r"[\u00e3\u00f5\u00e7\u00c3\u00d5\u00c7]|(?<!\w)(?:n\u00e3o|voc\u00ea|is" + "so|p" + r"ra|est\u00e1|tamb\u00e9m)(?!\w)", re.IGNORECASE)

SCRIPT = r"""
import { FakeNode } from "@FAKE@";
import * as router from "@JS@/router.js";
import { escapeStep } from "@JS@/frame/escape.js";
import * as fm from "@JS@/floor-model.js";
import * as model from "@JS@/model.js";
import { officeOf, fnv1a32 } from "@JS@/office/office-model.js";
import { buildRoom, MAX_SEATS } from "@JS@/office/room.js";
import { BLOCKED, FREE, SEAT, WalkGrid, PathFinder } from "@JS@/office/astar.js";
import { createWalkers, placeOf, seeded, WANDER_MS } from "@JS@/office/walk.js";
import { createSprites } from "@JS@/office/sprites.js";
import { paintPlaceholder } from "@JS@/office/placeholder.js";
import { fitScale } from "@JS@/office/scene.js";
import { EN, word } from "@JS@/office/words.js";
import { createOfficeView } from "@JS@/views/office.js";

const out = { errors: [] };
async function section(name, fn) {
  try { out[name] = await fn(); } catch (e) { out.errors.push(`${name}: ${e && e.stack}`); }
}

const P = "0123456789ab";
const NOW = new Date("2026-11-28T12:00:00Z");
const ago = (h) => new Date(NOW.getTime() - h * 3600e3).toISOString();
const agent = (name) => ({ name, enabled: true, acting_mode: "supervised", runs_today: 0, max_runs_per_day: 10, usd_today: 0, max_usd_per_day: 3, queued: 0 });
function snapshotOf(extra = {}) {
  const detail = {
    agents: ["planning", "engineering", "design", "marketing"].map(agent),
    status: {
      requests: [{ id: 14, title: "Spring campaign", state: "ready", routing: true,
        tasks: [{ id: 5, key: "build", skill: "eng-implement", state: "running", agent: "engineering", title: "Build the page" }] }],
      pending: [
        { id: 1, kind: "plan", title: "Plan: spring campaign", task_id: 14, agent: null, created_at: ago(2) },
        { id: 2, kind: "effect", title: "Publish the page", task_id: 5, agent: "engineering", created_at: ago(3) },
        { id: 3, kind: "effect", title: "Send the mailing", task_id: 9, agent: "marketing", created_at: ago(30) },
        { id: 4, kind: "question", title: "Which tone?", task_id: 9, agent: "marketing", created_at: ago(1) },
      ],
    },
    ...extra,
  };
  return { loaded: true, projects: [{ id: P, name: "Larkspur Studio", config: { accepted: true } }], details: { [P]: detail }, tasks: {} };
}

// ---- 1. the router and Escape
await section("router", () => {
  const route = router.parse(`#/p/${P}/office`);
  return { route, hash: router.officeHash(P), parent: router.parentHash(route), escape: escapeStep({ route }),
    withTab: router.parse(`#/p/${P}/office/extra`).screen, building: router.parse(`#/p/${P}`).screen, field: escapeStep({ route, field: true }) };
});

// ---- 2. the number and the agents
await section("model", () => {
  const snap = snapshotOf();
  const found = officeOf(snap, P, NOW);
  return { count: found.count, rows: model.waitingRows(snap, NOW, P).length, ready: found.ready, accepted: found.accepted,
    agents: found.agents.map((a) => ({ name: a.name, display: a.display, state: a.state, decisions: a.decisions, link: a.link, hue: a.look.hue })),
    missing: [officeOf(snap, "ffffffffffff", NOW), officeOf({ projects: snap.projects, details: {} }, P, NOW)],
    fnv: [fnv1a32(""), fnv1a32("a"), fnv1a32("foobar")],
    unaccepted: officeOf({ ...snap, projects: [{ id: P, name: "Larkspur Studio", config: { accepted: false } }] }, P, NOW).agents.map((a) => a.state) };
});

// ---- 3. the room
await section("room", () => {
  const four = buildRoom(["a", "b", "c", "d"]);
  const thirty = buildRoom(Array.from({ length: 30 }, (_, i) => `n${i}`));
  const border = [];
  for (let x = 0; x < four.w; x++) border.push(four.grid.get(x, 0), four.grid.get(x, four.h - 1));
  for (let y = 0; y < four.h; y++) border.push(four.grid.get(0, y), four.grid.get(four.w - 1, y));
  return { w: four.w, h: four.h, seatsX: four.seats.map((s) => s.seat.x), seatsY: four.seats.map((s) => s.seat.y), border: [...new Set(border)],
    desks: four.seats.map((s) => [four.grid.get(s.desk.x, s.desk.y), four.grid.get(s.desk.x + 1, s.desk.y), four.grid.get(s.seat.x, s.seat.y)]),
    board: [four.board[0], four.board[four.board.length - 1], four.board.length], wanderMinY: Math.min(...four.wander.map((t) => t.y)),
    wanderFree: four.wander.every((t) => four.grid.get(t.x, t.y) === FREE),
    seats30: thirty.seats.length, overflow30: thirty.overflow, size30: [thirty.w, thirty.h], max: MAX_SEATS,
    empty: (() => { const r = buildRoom([]); return [r.w, r.h, r.seats.length]; })() };
});

// ---- 4. the A* port: the four cases of its source, translated, and the grid's two searches
function gridFrom(rows) {
  const g = new WalkGrid(rows[0].length, rows.length);
  rows.forEach((r, y) => [...r].forEach((c, x) => g.set(x, y, c === "#" ? BLOCKED : c === "s" ? SEAT : FREE)));
  return g;
}
const pairs = (o) => { const r = []; for (let i = 0; i < o.length; i += 2) r.push([o[i], o[i + 1]]); return r; };
await section("astar", () => {
  const res = {};
  let g = gridFrom(["..... ".trim(), ".###.", "...#.", ".#..."]);
  let pf = new PathFinder(g);
  let o = [];
  res.found = pf.find(0, 0, 4, 3, o);
  let p = pairs(o);
  res.steps = p.length;
  res.last = p[p.length - 1];
  let prev = [0, 0];
  res.adjacent = true;
  for (const [x, y] of p) { if (Math.abs(x - prev[0]) + Math.abs(y - prev[1]) !== 1 || !g.walkable(x, y)) res.adjacent = false; prev = [x, y]; }
  g = gridFrom(["..#..", "..#..", "..#.."]);
  pf = new PathFinder(g);
  o = [1, 2, 3];
  res.noPath = [pf.find(0, 0, 4, 0, o), o.length];
  res.same = [pf.find(1, 1, 1, 1, o), o.length];
  g = gridFrom([".s.", "..."]);
  pf = new PathFinder(g);
  o = [];
  pf.find(0, 0, 2, 0, o);
  res.avoids = !pairs(o).some(([x, y]) => x === 1 && y === 0);
  pf.find(0, 0, 1, 0, o);
  res.endsOnSeat = pairs(o);
  g = gridFrom(["#..", "..."]);
  res.blockedStart = new PathFinder(g).find(0, 0, 2, 1, []);
  g = gridFrom(["......", "......", "......", "......"]);
  o = [];
  new PathFinder(g).find(0, 0, 5, 3, o);
  let turns = 0, last = -1, pv = [0, 0];
  for (const c of pairs(o)) { const d = c[0] !== pv[0] ? 0 : 1; if (last >= 0 && d !== last) turns++; last = d; pv = c; }
  res.turns = turns;
  g = gridFrom([".....", "....."]);
  pf = new PathFinder(g);
  res.reuse = true;
  for (let i = 0; i < 200; i++) { o = []; if (!pf.find(0, 0, 4, 1, o) || o.length / 2 !== 5) res.reuse = false; }
  g = gridFrom(["###", "#.#", "###"]);
  res.nearest = [g.nearestWalkable(0, 0), g.nearestWalkable(1, 1), gridFrom(["###", "###"]).nearestWalkable(0, 0, 3)];
  g = gridFrom(["..#.", "..#.", "...."]);
  const seen = g.reachableFrom(0, 0);
  res.reach = [...seen];
  res.reachBlocked = [...gridFrom(["#."]).reachableFrom(0, 0)];
  return res;
});

// ---- 6. where each state stands, and an unreachable place is reached at once
function walkRoom() { const room = buildRoom(["planning", "engineering", "design", "marketing"]); return { room, finder: new PathFinder(room.grid) }; }
await section("walk", () => {
  const { room, finder } = walkRoom();
  const res = {};
  const place = (state, i, w = 0) => placeOf({ state }, i, room, w);
  res.places = { working: place("working", 1), ready: place("ready", 1), off: place("off", 1), idle: place("idle", 1), waiting: place("waiting", 1, 2), seat1: room.seats[1].seat, board2: room.board[2] };
  const agents = ["planning", "engineering", "design", "marketing"].map((name) => ({ name, state: name === "marketing" ? "idle" : "working" }));
  const walkers = createWalkers(room, finder);
  walkers.retarget(agents, { reduced: false });
  res.start = walkers.positions().map((p) => [p.x, p.y]);
  res.startMoving = walkers.moving();
  agents[3].state = "waiting";
  walkers.retarget(agents, { reduced: false });
  res.walkMoving = walkers.moving();
  res.walkPose = walkers.positions()[3].pose;
  walkers.advance(150, 0, () => 0);
  const mid = walkers.positions()[3];
  res.mid = { moved: mid.x !== room.seats[3].seat.x || mid.y !== room.seats[3].seat.y, dir: mid.dir, frame: mid.frame };
  walkers.advance(10000, 0, () => 0);
  res.arrived = [walkers.positions()[3].x, walkers.positions()[3].y, walkers.moving(), walkers.positions()[3].pose];
  res.board0 = room.board[0];
  // an unreachable place: the finder says no path, the figure is set on its place at once
  const stuck = createWalkers(room, { find: () => false });
  stuck.retarget(agents.map((a) => ({ ...a, state: "idle" })), { reduced: false });
  const moved = agents.map((a) => ({ ...a, state: "waiting" }));
  stuck.retarget(moved, { reduced: false });
  res.unreachable = [stuck.moving(), stuck.positions().map((p) => [p.x, p.y]), moved.map((_, i) => [room.board[i].x, room.board[i].y])];
  // a wander: an idle figure at rest for WANDER_MS gets up, and goes back the next time
  const idle = createWalkers(room, finder);
  const quiet = agents.map((a) => ({ ...a, state: "idle" }));
  idle.retarget(quiet, { reduced: false });
  idle.advance(WANDER_MS - 1, 0, () => 0);
  res.beforeWander = idle.moving();
  idle.advance(1, 0, () => 0);
  res.wandering = idle.moving();
  idle.advance(20000, 0, () => 0);
  res.wandered = idle.positions().map((p) => [p.x, p.y]);
  res.noRepeatOnRetarget = (() => { idle.retarget(quiet, { reduced: false }); return idle.moving(); })();
  idle.advance(WANDER_MS, 0, () => 0);
  idle.advance(20000, 0, () => 0);
  res.backHome = idle.positions().map((p) => [p.x, p.y]);
  res.homes = room.seats.map((s) => [s.seat.x, s.seat.y]);
  const rnd = seeded(7), again = seeded(7);
  res.seeded = [rnd(), rnd(), again(), again()];
  return res;
});

// ---- 7. reduced motion, and a hidden tab
await section("reduced", () => {
  const { room, finder } = walkRoom();
  const agents = ["planning", "engineering", "design", "marketing"].map((name) => ({ name, state: "idle" }));
  const walkers = createWalkers(room, finder);
  walkers.retarget(agents, { reduced: true });
  agents[2].state = "waiting";
  walkers.retarget(agents, { reduced: true });
  const at = walkers.positions()[2];
  walkers.advance(WANDER_MS * 3, 0, () => 0);
  return { moving: walkers.moving(), at: [at.x, at.y], board0: [room.board[0].x, room.board[0].y], after: walkers.positions().map((p) => [p.x, p.y, p.pose]) };
});

// ---- 8. the sprite cache
await section("sprites", () => {
  const calls = [];
  const sprites = createSprites({ paint: (ctx, spec) => calls.push(spec), surface: (w, h) => ({ canvas: { w, h, id: calls.length }, ctx: {} }) });
  const look = { hue: 120 };
  const right = sprites.get(look, "walk", 0, "right");
  const left = sprites.get(look, "walk", 0, "left");
  sprites.get(look, "walk", 0, "right");
  sprites.get(look, "walk", 1, "right");
  sprites.get(look, "stand", 0, "down");
  sprites.get({ hue: 121 }, "stand", 0, "down");
  const log = [];
  const ctx = { fillStyle: "", fillRect: (...a) => log.push([ctx.fillStyle, ...a]) };
  paintPlaceholder(ctx, { look, pose: "walk", frame: 0, dir: "up" });
  const colours = [...new Set(log.map((l) => l[0]))];
  return { paints: calls.length, same: right.image === left.image, mirror: [right.mirror, left.mirror], size: sprites.size(), dirs: calls.map((c) => c.dir),
    surfaceSize: [right.image.w, right.image.h], colours, rects: log.length, body: log.find((l) => l[1] === 4 && l[2] === 10), head: log.find((l) => l[1] === 5 && l[2] === 2),
    stripe: log.filter((l) => l[3] === 1 && l[4] === 12).length };
});

// ---- 9. the zoom
await section("zoom", () => [fitScale({ cssW: 800, cssH: 600, dpr: 2, roomW: 19, roomH: 7 }), fitScale({ cssW: 300, cssH: 200, dpr: 1, roomW: 19, roomH: 7 })]);

// ---- 10, 11, 7b. the view
function recordingContext(log) {
  const ctx = { fillStyle: "", imageSmoothingEnabled: true };
  for (const name of ["fillRect", "clearRect", "drawImage", "save", "restore", "translate", "scale"]) ctx[name] = (...a) => log.push([name, ...a]);
  return ctx;
}
function stubFrame() {
  const patch = document.createElement.bind(document);
  document.createElement = (tag) => { const n = patch(tag); n.style = { props: {}, setProperty(k, v) { this.props[k] = v; } }; return n; };
  return { sceneHost: new FakeNode("div"), main: new FakeNode("main") };
}
const all = (root) => [...root.walk()];
const byClass = (root, cls) => all(root).filter((n) => (n.attrs.class || "").split(/\s+/).includes(cls));
function driver(options = {}) {
  const frame = stubFrame();
  const queue = [];
  const logs = [];
  const timers = [];
  let tick = 0;
  const view = createOfficeView(frame, {
    context: options.context || ((canvas) => { const log = []; logs.push(log); return recordingContext(log); }),
    raf: (fn) => { queue.push(fn); return queue.length; }, caf: () => {}, hidden: () => Boolean(options.hidden), reduced: () => Boolean(options.reduced),
    setTimer: (fn, ms) => { timers.push([fn, ms]); return timers.length; }, clearTimer: () => {}, clock: () => 0,
  });
  const frameRun = () => { const fn = queue.shift(); if (fn) { tick += 16; fn(tick); return true; } return false; };
  return { frame, view, queue, logs, timers, frameRun };
}
const draws = (log, name) => log.filter((e) => e[0] === name).length;
const route = router.parse(`#/p/${P}/office`);

await section("view", () => {
  window.location.hash = "#/";
  const d = driver();
  d.view.update({ snapshot: snapshotOf(), route, now: NOW, reload: 1 });
  const before = { queued: d.queue.length };
  d.frameRun();
  const log = d.logs[0];
  const rows = byClass(d.frame.main, "wb-office-row");
  const count = byClass(d.frame.main, "wb-office-count")[0];
  const fourText = count.textContent;
  const labels = byClass(d.frame.sceneHost, "wb-office-label");
  // a click on marketing's figure: the room is 19 x 7 tiles at zoom 2 in a 640 x 480 host, marketing stands at the board's first tile
  const canvas = all(d.frame.sceneHost).find((n) => n.tagName === "CANVAS");
  const click = (x, y) => { window.location.hash = "#/"; (canvas.listeners.click || []).forEach((fn) => fn({ clientX: x, clientY: y })); return window.location.hash; };
  const picked = { marketing: click(88, 160), planning: click(88, 250), nowhere: click(5, 5) };
  const rowClick = rows.map((r) => r.attrs.href);
  const idleFrames = [];
  for (let i = 0; i < 3; i++) idleFrames.push(d.frameRun());
  const stats = [d.queue.length, d.timers.length];
  const list = byClass(d.frame.main, "wb-office-list")[0];
  const region = byClass(d.frame.main, "wb-office-panel")[0];
  // an update that changes nothing asks for no frame; a changed number is drawn in the text without one
  d.view.update({ snapshot: snapshotOf(), route, now: NOW, reload: 2 });
  const same = d.queue.length;
  const listNodeBefore = list.children[0];
  d.view.update({ snapshot: snapshotOf(), route, now: NOW, reload: 3 });
  const kept = list.children[0] === listNodeBefore;
  const fewer = snapshotOf();
  fewer.details[P].status.pending = fewer.details[P].status.pending.slice(0, 1);
  d.view.update({ snapshot: fewer, route, now: NOW, reload: 4 });
  const one = count.textContent;
  d.view.dispose();
  return {
    queuedAfterUpdate: before.queued, countText: [fourText, one], regionAttrs: [region.attrs.role, region.attrs["aria-labelledby"]], listLabel: list.attrs["aria-label"],
    rows: rows.map((r) => [r.children[0].textContent, r.children[1].textContent, r.attrs.href, r.children.length > 2 ? r.children[2].textContent : null]),
    rowLabels: rows.map((r) => r.attrs["aria-label"]), rowClick, figureDraws: draws(log, "drawImage"), mirrorSaves: draws(log, "save"),
    labels: labels.map((l) => [l.attrs["aria-hidden"], l.hidden, l.children[0].textContent, l.children[1].textContent, Object.keys(l.style.props)]),
    picked, idleFrames, stats, same, kept, left: [byClass(d.frame.main, "wb-office-panel").length, byClass(d.frame.sceneHost, "wb-office-labels").length, all(d.frame.sceneHost).filter((n) => n.tagName === "CANVAS").length],
    warnMarks: log.filter((e) => e[0] === "fillRect" && e[3] !== undefined && e[3] === e[4]).length,
    smoothing: log.length ? true : false,
  };
});

await section("hidden", () => {
  const d = driver({ hidden: true });
  d.view.update({ snapshot: snapshotOf(), route, now: NOW, reload: 1 });
  const ran = d.frameRun();
  const count = byClass(d.frame.main, "wb-office-count")[0].textContent;
  return { queued: d.queue.length, ran, draws: d.logs.map((l) => draws(l, "drawImage")), count, rows: byClass(d.frame.main, "wb-office-row").length };
});

await section("reducedView", () => {
  const d = driver({ reduced: true });
  const snap = snapshotOf();
  d.view.update({ snapshot: snap, route, now: NOW, reload: 1 });
  d.frameRun();
  const changed = snapshotOf();
  changed.details[P].status.pending = [];     // marketing's decisions are answered: it is idle again
  d.view.update({ snapshot: changed, route, now: NOW, reload: 2 });
  let frames = 0;
  while (d.frameRun()) frames += 1;
  return { moving: frames, timers: d.timers.length, draws: draws(d.logs[0], "drawImage") };
});

await section("walkingView", () => {
  const d = driver();
  const snap = snapshotOf();
  snap.details[P].status.pending = [];
  d.view.update({ snapshot: snap, route, now: NOW, reload: 1 });
  while (d.frameRun()) { if (d.queue.length > 5) break; }
  const quiet = [d.queue.length, d.timers.length, d.timers[0] && d.timers[0][1]];
  const waiting = snapshotOf();
  d.view.update({ snapshot: waiting, route, now: NOW, reload: 2 });
  let frames = 0;
  while (d.frameRun() && frames < 400) frames += 1;
  return { quiet, frames, ended: d.queue.length };
});

await section("fallback", () => {
  const d = driver({ context: () => null });
  d.view.update({ snapshot: snapshotOf(), route, now: NOW, reload: 1 });
  const note = byClass(d.frame.main, "wb-office-note")[0];
  const rows = byClass(d.frame.main, "wb-office-row");
  return { note: [note.textContent, note.hidden], rows: rows.map((r) => r.children[0].textContent), canvases: all(d.frame.sceneHost).filter((n) => n.tagName === "CANVAS").length,
    count: byClass(d.frame.main, "wb-office-count")[0].textContent, queue: d.queue.length };
});

await section("overflow", () => {
  const d = driver();
  const snap = snapshotOf();
  snap.details[P].agents = Array.from({ length: 30 }, (_, i) => agent(i === 0 ? "planning" : `area${i}`));
  d.view.update({ snapshot: snap, route, now: NOW, reload: 1 });
  d.frameRun();
  const note = byClass(d.frame.main, "wb-office-note")[0];
  return { note: [note.textContent, note.hidden], rows: byClass(d.frame.main, "wb-office-row").length, figures: draws(d.logs[0], "drawImage"), labels: byClass(d.frame.sceneHost, "wb-office-label").filter((l) => !l.hidden).length };
});

await section("loading", () => {
  const d = driver();
  d.view.update({ snapshot: { loaded: false, projects: [], details: {} }, route, now: NOW, reload: 0 });
  return { count: byClass(d.frame.main, "wb-office-count")[0].textContent, queued: d.queue.length };
});

// ---- 12. the words
await section("words", () => ({
  one: word("office.waiting", { n: 1 }), zero: word("office.waiting", { n: 0 }), many: word("office.waiting", { n: 4 }),
  pt: word("office.waiting", { n: 2, language: "pt-BR" }), missing: word("office.nothing"), figure: word("office.figure", { vars: { name: "Design", state: "Idle" } }),
  decisions: [word("office.decisions", { n: 1 }), word("office.decisions", { n: 3 })], overflow: [word("office.overflow", { n: 1 }), word("office.overflow", { n: 6 })],
  states: ["working", "waiting", "ready", "idle", "off"].map((s) => [EN[`state.${s}`], fm.stateWords(s)]),
  keys: Object.keys(EN), frozen: Object.isFrozen(EN),
}));

console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def got(tmp_path_factory):
    result = run_node(tmp_path_factory.mktemp("office"), SCRIPT)
    assert result["errors"] == [], "\n".join(result["errors"])
    return result


@needs_node
def test_the_router_parses_and_builds_the_office_hash_and_escape_goes_to_the_building(got):
    r = got["router"]
    assert r["route"]["screen"] == "office" and r["route"]["project"] == PROJECT and r["route"]["tab"] is None
    assert r["hash"] == f"#/p/{PROJECT}/office"
    assert r["parent"] == f"#/p/{PROJECT}", "Back and the crumb go to the Building"
    assert r["escape"] == {"step": "up", "hash": f"#/p/{PROJECT}"}
    assert r["field"] == {"step": "none"}, "a typed field keeps the focus first"
    assert r["withTab"] == "office" and r["building"] == "building"


@needs_node
def test_the_office_number_counts_open_decisions_not_agents(got):
    m = got["model"]
    assert m["count"] == 4 == m["rows"], "the first number is the 'Waiting for you' rows of the project"
    assert [a["name"] for a in m["agents"]] == ["planning", "engineering", "design", "marketing"]
    assert [a["state"] for a in m["agents"]] == ["working", "working", "idle", "waiting"]
    assert [a["decisions"] for a in m["agents"]] == [1, 1, 0, 2]
    by = {a["name"]: a for a in m["agents"]}
    assert by["planning"]["display"] == "Lobby" and by["marketing"]["display"] == "Marketing"
    assert by["marketing"]["link"] == f"#/p/{PROJECT}/floor/marketing/inbox/3", "the link of its oldest decision, not its newest"
    assert by["engineering"]["link"] == f"#/p/{PROJECT}/floor/engineering/inbox/2"
    assert by["planning"]["link"] == f"#/p/{PROJECT}/lobby/conversation/request/14", "a plan of a request opens in the conversation"
    assert by["design"]["link"] == f"#/p/{PROJECT}/floor/design", "an agent with no decision links to its floor"
    assert len({a["hue"] for a in m["agents"]}) == 4 and all(0 <= a["hue"] < 360 for a in m["agents"])
    assert m["missing"] == [{"ready": False}, {"ready": False}]
    assert m["fnv"] == [2166136261, 3826002220, 3214735720], "32-bit FNV-1a"
    assert m["unaccepted"] == ["off"] * 4, "a project that is not accepted shows its agents off"


@needs_node
def test_the_room_seats_every_agent_up_to_the_cap_inside_its_walls(got):
    r = got["room"]
    assert (r["w"], r["h"]) == (19, 7) and r["seatsX"] == [2, 6, 10, 14] and r["seatsY"] == [4] * 4
    assert r["border"] == [0], "the border is blocked"
    assert r["desks"] == [[0, 0, 2]] * 4, "a desk is two blocked tiles and the seat in front of it is avoided, not blocked"
    assert r["board"] == [{"x": 2, "y": 1}, {"x": 16, "y": 1}, 15]
    assert r["wanderMinY"] >= 2 and r["wanderFree"]
    assert r["seats30"] == 24 == r["max"] and len(r["overflow30"]) == 6 and r["overflow30"][0] == "n24"
    assert r["size30"] == [19, 4 + 3 * 6]
    assert r["empty"] == [7, 7, 0], "a room with no agent is still a room"


@needs_node
def test_the_astar_port_passes_the_cases_of_its_source(got):
    a = got["astar"]
    assert a["found"] is True and a["steps"] == 7 and a["last"] == [4, 3] and a["adjacent"] is True
    assert a["noPath"] == [False, 0], "no path: false, and `out` is emptied"
    assert a["same"] == [True, 0], "start equals goal: true and nothing to walk"
    assert a["avoids"] is True and a["endsOnSeat"] == [[1, 0]], "a seat is avoided unless it is the goal"
    assert a["blockedStart"] is True, "a figure on a blocked tile may start from it"
    assert a["turns"] <= 1, "paths prefer fewer turns"
    assert a["reuse"] is True, "the buffers are reused between searches without leaking state"
    assert a["nearest"] == [{"x": 1, "y": 1}, {"x": 1, "y": 1}, None]
    assert a["reach"] == [1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1, 1], "everything is reachable through the gap, the blocked column is not"
    assert a["reachBlocked"] == [0, 0], "nothing is reachable from a blocked tile"


PORT = OFFICE / "astar.js"


def test_the_port_keeps_its_licence_notice_and_holds_no_portuguese():
    text = PORT.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0].startswith("// Ported from Habblaud (the repository marmottajr/habblaud on GitHub), files client/src/world/path/grid.ts and")
    assert "faa1a012b5fbf632c66dc6801c5383e53a542406" in lines[1] and "comments translated to English, logic unchanged" in lines[2]
    assert "// MIT License" in lines and "// Copyright (c) 2026 Márcio Junior" in lines
    for needle in ("Permission is hereby granted, free of charge", "The above copyright notice and this permission notice shall be included in all",
                   'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND', "// SOFTWARE."):
        assert any(needle in line for line in lines), needle
    notice = [line for line in lines if line.startswith("//")][:24]
    assert len(notice) == 24 and not any(PORTUGUESE_RE.search(line) for line in lines), "every comment is English"
    assert not re.search(r"https?://", text), "the source is named, never linked"
    for kept in ("const SEAT_COST = 6;", "const TURN_COST = 0.35;", "h * 1.001", "new Int8Array(n)", "0xffffffff", "(pos - 1) >> 1"):
        assert kept in text, f"the logic is the source's: {kept}"
    assert re.search(r"export (class|const) \w+", text) and {m for m in re.findall(r"^export (?:class|const) (\w+)", text, re.M)} == {"BLOCKED", "FREE", "SEAT", "WalkGrid", "PathFinder"}


@needs_node
def test_each_state_has_its_place_and_an_unreachable_place_is_reached_at_once(got):
    w = got["walk"]
    p = w["places"]
    assert p["working"] == p["ready"] == p["off"] == p["idle"] == p["seat1"], "these four states sit at the seat"
    assert p["waiting"] == p["board2"], "one that waits stands at the board, in its turn"
    assert w["startMoving"] is False, "a figure that arrives is placed, not walked in"
    assert w["walkMoving"] is True and w["walkPose"] == "walk", "a change of state walks"
    assert w["mid"]["moved"] is True and w["mid"]["dir"] in ("up", "right", "down", "left") and w["mid"]["frame"] in (0, 1)
    assert w["arrived"] == [w["board0"]["x"], w["board0"]["y"], False, "stand"]
    assert w["unreachable"][0] is False and w["unreachable"][1] == w["unreachable"][2], "no path: on the place at once, nothing to walk"
    assert w["beforeWander"] is False and w["wandering"] is True, "an idle figure at rest for WANDER_MS gets up"
    assert w["noRepeatOnRetarget"] is False, "a reload that changes nothing does not send a figure back"
    assert w["wandered"] != w["homes"] and w["backHome"] == w["homes"], "it goes back to its seat the next time"
    assert w["seeded"][0] == w["seeded"][2] and w["seeded"][1] == w["seeded"][3] and 0 <= w["seeded"][0] < 1 and w["seeded"][0] != w["seeded"][1]


@needs_node
def test_reduced_motion_places_agents_without_a_walk_and_a_hidden_tab_draws_nothing(got):
    r = got["reduced"]
    assert r["moving"] is False and r["at"] == r["board0"], "reduced motion: on the place at once"
    assert all(p[2] == "stand" for p in r["after"]) and r["after"][0][:2] != r["board0"], "and nobody wanders"
    assert got["reducedView"]["moving"] == 1 and got["reducedView"]["timers"] == 0, "one frame for the change, then no walking frames and no wander timer"
    h = got["hidden"]
    assert h["queued"] == 0 and h["ran"] is False and not any(h["draws"]), "a hidden document schedules and draws nothing"
    assert h["count"] == "4 decisions waiting for you" and h["rows"] == 4, "the text is still current"


@needs_node
def test_the_sprite_cache_paints_each_pose_once_and_mirrors_left(got):
    s = got["sprites"]
    assert s["paints"] == 4, "right/walk/0, right/walk/1, down/stand/0 and another hue; the second right/walk/0 and the left one are the cache"
    assert s["same"] is True and s["mirror"] == [False, True], "left is the right image, mirrored when drawn"
    assert "left" not in s["dirs"] and s["size"] == {"w": 16, "h": 24} and s["surfaceSize"] == [16, 24]
    assert all(re.fullmatch(r"hsl\(120 \d+% \d+%\)", c) for c in s["colours"]), "the placeholder writes hsl strings of the agent's hue only"
    assert s["body"][1:] == [4, 10, 8, 12] and s["head"][1:] == [5, 2, 6, 7] and s["body"][0] == "hsl(120 45% 55%)" and s["head"][0] == "hsl(120 30% 75%)"
    assert s["stripe"] == 1, "a figure seen from behind has a 1 px darker stripe down its back"


@needs_node
def test_the_zoom_is_an_integer_number_of_device_pixels(got):
    big, small = got["zoom"]
    assert big["device"] == 5 and big["css"] == 2.5 and big["left"] == (800 - 19 * 16 * 2.5) / 2 and big["top"] == (600 - 7 * 16 * 2.5) / 2
    assert small["device"] == 1 and small["css"] == 1, "a small host gets the smallest whole zoom, never a fraction"


@needs_node
def test_the_view_draws_the_room_lists_every_agent_and_shows_the_count(got):
    v = got["view"]
    assert v["queuedAfterUpdate"] == 1, "one frame is asked for on arrival"
    assert v["countText"] == ["4 decisions waiting for you", "1 decision waiting for you"]
    assert v["regionAttrs"] == ["region", "wb-office-title"] and v["listLabel"] == "Agents in the office"
    assert [r[:2] for r in v["rows"]] == [["Lobby", "Running"], ["Engineering", "Running"], ["Design", "Idle"], ["Marketing", "Waiting for you"]]
    assert [r[3] for r in v["rows"]] == ["1 decision", "1 decision", None, "2 decisions"]
    assert [r[2] for r in v["rows"]] == v["rowClick"] and v["rows"][3][2] == f"#/p/{PROJECT}/floor/marketing/inbox/3"
    assert v["rowLabels"][3] == "Marketing, Waiting for you, 2 decisions"
    assert v["figureDraws"] == 4, "one figure for each agent in the frame"
    assert v["picked"]["marketing"] == f"#/p/{PROJECT}/floor/marketing/inbox/3", "a click on a figure opens its oldest decision"
    assert v["picked"]["planning"] == f"#/p/{PROJECT}/lobby/conversation/request/14" and v["picked"]["nowhere"] == "#/"
    assert len(v["labels"]) == 4 and all(l[0] == "true" for l in v["labels"]), "the labels are decoration: the list is the accessible twin"
    assert all("--wb-x" in l[4] and "--wb-y" in l[4] for l in v["labels"]) and not any(l[1] for l in v["labels"])
    assert v["idleFrames"] == [False, False, False] and v["stats"][0] == 0, "no frame is scheduled while nothing moves"
    assert v["same"] == 0, "an update that changes nothing draws nothing"
    assert v["kept"] is True, "the list is rebuilt only when its text or links changed"
    assert v["left"] == [0, 0, 0], "dispose removes the panel, the labels and the canvas"


@needs_node
def test_a_figure_walks_frame_by_frame_and_the_loop_stops_when_it_arrives(got):
    w = got["walkingView"]
    assert w["quiet"][0] == 0, "nothing runs while everybody sits"
    assert 0 < w["frames"] < 400 and w["ended"] == 0, "a walk is some frames and then none"


@needs_node
def test_without_a_2d_context_the_office_says_why_and_lists_every_agent(got):
    f = got["fallback"]
    assert f["note"] == ["This browser cannot draw the office. Every agent is listed below.", False]
    assert f["rows"] == ["Lobby", "Engineering", "Design", "Marketing"] and f["canvases"] == 0 and f["queue"] == 0
    assert f["count"] == "4 decisions waiting for you", "the number does not need the picture"
    o = got["overflow"]
    assert o["rows"] == 30 and o["figures"] == 24 and o["note"] == ["6 more agents are not drawn; they are listed below.", False]
    assert o["labels"] <= 12, "at most MAX_LABELS labels"
    assert got["loading"]["count"] == "Loading the agents..." and got["loading"]["queued"] == 0


@needs_node
def test_the_words_use_plural_rules_and_fall_back_to_english(got):
    w = got["words"]
    assert (w["one"], w["zero"], w["many"]) == ("1 decision waiting for you", "0 decisions waiting for you", "4 decisions waiting for you")
    assert w["pt"] == "2 decisions waiting for you", "only English exists in slice 1: another language reads English"
    assert w["missing"] == "office.nothing" and w["figure"] == "Design, Idle"
    assert w["decisions"] == ["1 decision", "3 decisions"] and w["overflow"] == ["1 more agent is not drawn; it is listed below.", "6 more agents are not drawn; they are listed below."]
    assert all(a == b for a, b in w["states"]), "the state words are the floors list's"
    assert w["frozen"] is True and len(w["keys"]) == 17


def test_the_office_writes_nothing_loads_no_3d_and_styles_every_class_it_builds():
    files = sorted(OFFICE.glob("*.js")) + [JS / "views" / "office.js"]
    assert {f.name for f in files} >= {"astar.js", "office-model.js", "placeholder.js", "room.js", "scene.js", "sprites.js", "walk.js", "words.js", "office.js"}
    css = interface_css()
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\bapi\.|from \"\.\./api\.js\"|from \"\./api\.js\"|\bfetch\(", text), f"{path.name} reads or writes through the client"
        assert not re.search(r"scene/engine\.js|js/three\.js|from \"[./]*three\.js\"|vendor/three", text), f"{path.name} loads the 3D scene"
        assert not re.search(r"localStorage|sessionStorage|innerHTML|insertAdjacentHTML|setAttribute\(\"style\"", text), path.name
        assert not re.search(r"https?://", text), path.name
        assert not re.search(r"\.hash = router\.|approve|\.post\(", text.replace("window.location.hash = agent.link", "")), f"{path.name} builds a hash or approves"
        for cls in set(re.findall(r"\bwb-office-[a-z0-9-]+", text)) - {"wb-office-title"}:   # the title is an id
            assert re.search(re.escape("." + cls) + r"(?![A-Za-z0-9_-])", css), f"{cls} of {path.name} is not styled"
    office_css = (INTERFACE / "css" / "office.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", office_css), "the stylesheet writes no colour literal"
    assert "image-rendering: pixelated" in office_css and "max-width: 899px" in office_css and "prefers-reduced-motion" in office_css
    assert "createOfficeView" in (JS / "main.js").read_text(encoding="utf-8")
    assert "officeHash" in (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert 'office: "Office"' in (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert not re.search(r"\.hash\s*=", (JS / "office" / "walk.js").read_text(encoding="utf-8"))
    pick = re.findall(r"window\.location\.hash = (.+);", (JS / "views" / "office.js").read_text(encoding="utf-8"))
    assert pick == ["agent.link"], "a pick only moves to the link of a waiting row or an agent's floor"

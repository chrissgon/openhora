"""Tests of the scene's third round (WP-9.11): one world (the clicked building opens where it stands while the camera flies, Back closes it, no
mesh is replaced and none jumps), the in-between layout (the scene is fitted in what the KPI cards, the header, the panel and the plates leave) and the
bounded request list.

No browser and no model: the pure modules run under Node when it is installed (the world with the real three.js, no WebGL); what only a browser can show
was looked at in the browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_round3.py
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from test_interface_floor import FAKE_DOM
from interface_css import css_file, interface_css

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
SCENE = JS / "scene"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed: the pure modules are tested only by their text")


def run_node(tmp_path: Path, body: str) -> dict:
    """Run `body` (an ES module that prints one JSON line) with Node and return what it printed."""
    script = tmp_path / "check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", (tmp_path / "fake-dom.mjs").as_uri()), encoding="utf-8")
    (tmp_path / "fake-dom.mjs").write_text(FAKE_DOM, encoding="utf-8")
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


def run_node_engine(tmp_path: Path, body: str) -> dict:
    """Run `body` with the real engine under Node: a loader hook swaps the one place the 3D library is imported from for a copy with a renderer that
    draws nothing (the engine, its loop, its camera and the world are the real ones; only the GPU is missing), so the camera's frames can be read."""
    real = (JS.parent / "vendor" / "three" / "three.module.js").resolve().as_uri()
    stub = tmp_path / "three-stub.mjs"
    stub.write_text(
        f'export * from "{real}";\n'
        "export class WebGLRenderer {\n"
        "  constructor({ canvas }) { this.domElement = canvas; this.shadowMap = {}; this.draws = 0; }\n"
        "  getContext() { return {}; } setClearColor() {} setPixelRatio() {} getPixelRatio() { return 1; } setSize() {} render(scene) { this.draws += 1; globalThis.__scene = scene; } dispose() {} forceContextLoss() {}\n"  
        "  get info() { return { render: { calls: 0 }, memory: { geometries: 0 } }; }\n"
        "}\n", encoding="utf-8")
    (tmp_path / "hooks.mjs").write_text(
        "export async function resolve(specifier, context, next) {\n"
        "  const r = await next(specifier, context);\n"
        f"  if (r.url === {json.dumps((JS / 'three.js').resolve().as_uri())}) return {{ url: {json.dumps(stub.as_uri())}, shortCircuit: true }};\n"
        "  return r;\n}\n", encoding="utf-8")
    (tmp_path / "register.mjs").write_text('import { register } from "node:module";\nregister("./hooks.mjs", import.meta.url);\n', encoding="utf-8")
    script = tmp_path / "engine-check.mjs"
    script.write_text(body.replace("@JS@", JS.as_uri()).replace("@FAKE@", (tmp_path / "fake-dom.mjs").as_uri()), encoding="utf-8")
    (tmp_path / "fake-dom.mjs").write_text(FAKE_DOM, encoding="utf-8")
    done = subprocess.run([NODE, "--import", str(tmp_path / "register.mjs"), str(script)], capture_output=True, text=True, timeout=120, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# What the tests of the world share: a palette, the models of a City of three lots and the world built from them.
WORLD_JS = r"""
import * as THREE from "@JS@/three.js";
import { createKit } from "@JS@/scene/kit.js";
import { buildWorld } from "@JS@/scene/world.js";
import { cityTones } from "@JS@/scene/palette.js";

const c = (hex) => new THREE.Color(hex);
const T = { border: c(0x101010), theme: c(0x2020f0), success: c(0x10f010), error: c(0xf01010), emphasis: c(0x303030), text: c(0x404040), warn: c(0xf0a010), textMuted: c(0x505050), mutedRole: c(0x707070) };
export const palette = { dark: false, T, mix: (a, b, t) => a.clone().lerp(b, t), bg: c(0xfafafa), shell: c(0xf8f8f8), ink: c(0x202020), metal: c(0x606060), deskTop: c(0xd0d0d0), screenOff: c(0x181818), leafA: c(0x80c080), leafB: c(0x70b070), trunk: c(0x806040),
  lot: c(0xffffff), warm: c(0xf0c040), pale: c(0xd0d8f0), glass: c(0xd0e0f0), wood: c(0xc0a080), drawer: c(0x9090d0), skin: c(0xe0c0b0), windows: { lit: c(0xf0c040), grey: T.border } };
export { THREE, createKit, buildWorld, cityTones };

const floor = (name, extra = {}) => ({ name, label: name, state: "idle", window: "grey", decisions: 0, lobby: name === "planning", notes: ["done", "run"], documents: 2, sheets: [{ path: "docs/a.md", tip: "docs/a.md" }, { path: "docs/b.md", tip: "docs/b.md" }], drawers: 1, tip: `tip ${name}`, interactive: true,
  plate: { name, label: name, dot: "muted", decisions: 0, word: "resting", done: 0, left: 0, queued: 0, runsText: "0 / 4", runsShare: 0, usdText: "$0 / $1", usdShare: 0, unknown: 0, mode: "supervised", pips: 2, acting: null, actingPips: 0, selected: false, off: false }, ...extra });
export const lot = (id, extra = {}) => ({ id, name: id, accepted: true, decisions: 1, runningTask: id === "a" ? 5 : null, tip: `tip ${id}`, sub: "sub", selected: null, tag: null,
  floors: [floor("planning"), floor("business", { state: "working", window: "lit" }), floor("design", { decisions: 2, state: "waiting" }), floor("engineering")], ...extra });
export const model = (extra = {}) => ({ ready: true, selectedId: null, marked: null, outlined: null, focus: null, floor: null, frame: null, room: null, lots: [lot("a"), lot("b"), lot("c")], ...extra });
export function make(extra = {}) {
  const kit = createKit(palette);
  const scene = new THREE.Scene();
  const world = buildWorld(kit, model(extra));
  scene.add(world.group);
  return { kit, scene, world };
}
// every visible mesh of the world (a hidden group hides its subtree), with the world position of its centre
export function visibleMeshes(world) {
  const out = [];
  const walk = (n) => { if (!n.visible) return; if (n.isMesh) out.push(n); n.children.forEach(walk); };
  walk(world.group);
  return out;
}
"""


# The product's own models, through the product's own functions: a snapshot of two projects (the first with a running task, decisions and the five agents
# that make its floors), the models the City, the Building and the Floor hand to the world, and the rows of `artifacts` the views read late. The views
# start with `documents = null` and read them after the screen is shown: that is the order the world must meet.
PRODUCT_JS = r"""
import { worldModel } from "@JS@/world-model.js";

export const NOW = new Date("2026-10-08T12:00:00Z");
const ago = (hours) => new Date(NOW.getTime() - hours * 3600e3).toISOString();
const agents = (names, over = {}) => names.map((name) => ({ name, enabled: true, mode: "supervised", acting_mode: "supervised",
  max_runs_per_day: 10, max_usd_per_day: 2.5, runs_today: 1, usd_today: 0.5, queued: 0, ...(over[name] || {}) }));
export const A = "aaaaaaaaaaaa", B = "bbbbbbbbbbbb", C = "cccccccccccc";
const projects = [
  { id: A, name: "shop", config: { accepted: true }, open_pending: 3, running_task: 5 },
  { id: B, name: "docs", config: { accepted: true }, open_pending: 1, running_task: null },
  { id: C, name: "lab", config: { accepted: true }, open_pending: 0, running_task: null },
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
const names = ["engineering", "planning", "marketing", "brand", "design"];
export const snapshot = {
  projects, loaded: true,
  details: { [A]: { status: statusA, agents: agents(names, { design: { enabled: false }, brand: { acting_mode: "stopped" } }) },
             [B]: { status: statusB, agents: agents(names) }, [C]: { status: { requests: [], pending: [] }, agents: agents(names) } },
  tasks: { [`${A}:5`]: { task: { id: 5, agent: "engineering", title: "Order page", state: "running" }, runs: [{ started_at: "2026-10-08T10:30:00Z" }], pending: [] } },
};
// the rows of `artifacts` of the shop, read late
export const DOCS = [
  { path: "docs/e1.md", agent: "engineering" }, { path: "docs/e2.md", agent: "engineering" }, { path: "docs/e3.md", agent: "engineering" },
  { path: "docs/m1.md", agent: "marketing" }, { path: "docs/b1.md", agent: "brand" }, { path: "docs/p1.md", agent: "planning" },
];
const ROOM = { tips: { agent: "Engineering", desk: "Current task", tray: "Inbox", cabinet: "documents", board: "b" }, board: { title: "t", lines: ["l"], dot: "theme" }, door: false };
// the models, as the views build them
export const models = {
  city: () => worldModel(snapshot, NOW, { selectedId: null, marked: A }),
  building: (documents) => worldModel(snapshot, NOW, { selectedId: A, focus: A, documents }),
  floor: (documents, name = "engineering") => worldModel(snapshot, NOW, { selectedId: A, focus: A, floor: name, room: ROOM, documents }),
};
"""

# every mesh under a group, the world position of each and the scale and position of each floor group
SNAP_JS = r"""
export const meshesOf = (group) => { const out = new Set(); group.traverse((n) => { if (n.isMesh) out.add(n); }); return out; };
export const positions = (meshes) => { const out = new Map(); const v = new THREE.Vector3(); for (const m of meshes) { m.getWorldPosition(v); out.set(m, [v.x, v.y, v.z]); } return out; };
export const matrices = (meshes) => { const out = new Map(); for (const m of meshes) { m.updateWorldMatrix(true, false); out.set(m, m.matrixWorld.elements.slice()); } return out; };
"""


@needs_node
def test_the_product_sequence_city_building_floor_back_replaces_no_mesh_and_every_transform_moves_by_the_prototypes_curve(tmp_path):
    """The reviewer's finding (PR 252): the views start with their documents unread, so the real sequence of models changes the sheets, the drawers
    and (on a floor) the room's words while the building is moving. Nothing of the clicked building may be replaced across the route changes, and each
    transform must follow the curve: the floors rise by the prototype's `explode` approach, the floors that are not chosen shrink by `vis`, the chosen
    floor stays where it is, and the reverse runs the same way."""
    got = run_node(tmp_path, WORLD_JS + PRODUCT_JS + SNAP_JS + r"""
import { approach, EXPLODE_RATE, smooth } from "@JS@/scene/prototype-motion.js";
import { floorY, P, GAP } from "@JS@/scene/building.js";
import { roofY, squash } from "@JS@/scene/tower.js";

const kit = createKit(palette);
const world = buildWorld(kit, models.city());
const scene = new THREE.Scene(); scene.add(world.group);
let a = world.towers.get(A);   // read again after every model: a world that built the tower again would hand a new one
const n = a.floorGroups.length;
const out = { floors: a.lot.floors.map((f) => f.name), frames: [] };
let known = new Set();                  // the meshes of the clicked building once its rooms are in
const lost = [];                        // a mesh that was there and is not (a replaced mesh)
const steps = [];                       // per frame: what moved, to compare with the curve
let last = null;                        // the previous frame's world positions and matrices
let frameNo = 0;
let reference = 0;                      // an independent integration of the prototype's explode
const chosenName = "engineering";
const chosen = a.lot.floors.findIndex((f) => f.name === chosenName);
const floorOf = (mesh) => { for (let o = mesh; o; o = o.parent) { const i = a.floorGroups.indexOf(o); if (i >= 0) return i; } return -1; };
const others = [B, C].map((id) => world.towers.get(id));
// the exclamation outside a floor with a decision waiting shrinks away as the building opens (its own scale, by the same curve): it is checked apart
const shrinking = new Set(); for (const e of a.markers) for (const m of meshesOf(e.group)) shrinking.add(m);
const othersBefore = others.map((t) => positions(meshesOf(t.group)));

// run until settled; `at` is [frame, fn] pairs called before that frame's step (a route change, a read arriving)
function run(label, at, cap = 120) {
  const pending = [...at];
  for (let i = 0; i < cap; i++) {
    for (let k = pending.length - 1; k >= 0; k--) if (pending[k][0] === i) { pending[k][1](); pending.splice(k, 1); }
    a = world.towers.get(A);
    const before = last;
    const moving = world.step(1 / 30);
    frameNo += 1;
    reference = approach(reference, a.target, 1 / 30, EXPLODE_RATE);
    if (Math.abs(reference - a.target) <= 0.004) reference = a.target;
    const now = meshesOf(a.group);
    for (const m of [...known]) if (!now.has(m)) { lost.push([label, frameNo]); known.delete(m); }
    for (const m of now) known.add(m);
    const pos = positions(now), mat = matrices(now);
    const rec = { label, open: a.open, reference, scale: a.floorGroups.map((g) => g.scale.x), y: a.floorGroups.map((g) => g.position.y), roof: null };
    if (before) {
      // x and z of every mesh that was there: unchanged (the floors only rise, the others only shrink about their own centres)
      let maxXZ = 0, maxDy = 0, minDy = 0;
      for (const [m, p] of pos) {
        const q = before.pos.get(m);
        if (!q || shrinking.has(m)) continue;
        if (a.floorGroups.every((g) => g.scale.x === 1) && before.scales.every((s) => s === 1)) {
          maxXZ = Math.max(maxXZ, Math.abs(p[0] - q[0]), Math.abs(p[2] - q[2]));
          const dy = p[1] - q[1];
          maxDy = Math.max(maxDy, dy); minDy = Math.min(minDy, dy);
        }
      }
      rec.maxXZ = maxXZ; rec.maxDy = maxDy; rec.minDy = minDy;
      rec.chosenSame = [...meshesOf(a.floorGroups[chosen])].every((m) => { const e = mat.get(m), f = before.mat.get(m); return !f || e.every((v, k) => v === f[k]); });
      rec.dOpen = a.open - before.open;
      // the highest mesh (the roof, the top floor) moves by this much at most: the floors' rise, and (R-16) the closed City's height growing from its drawing's
      // height to the rooms' as the walls fade (`squash`), over the whole stack
      rec.bound = n * GAP * Math.abs(smooth(a.open) - smooth(before.open)) + (n * (P + GAP) + P) * Math.abs(squash(smooth(a.open)) - squash(smooth(before.open)));
    }
    last = { pos, mat, open: a.open, scales: a.floorGroups.map((g) => g.scale.x) };
    out.frames.push(rec);
    if (!moving) break;
  }
}

// 1. the click on the building: its rooms go in behind the walls, the route changes on frame 4 (the Building with its documents unread), the
//    documents arrive on frame 12
world.setFocus(A);
run("open", [[3, () => world.update(models.building(null))], [11, () => world.update(models.building(DOCS))]]);
out.afterOpen = { open: a.open, cases: a.parts.map((p) => p && p.cases) };
// 2. the click on a floor: the Floor view starts without documents, reads them on frame 8
world.setFloors(chosenName, null);
run("floor", [[2, () => world.update(models.floor(null))], [8, () => world.update(models.floor(DOCS))]]);
out.afterFloor = { visible: a.floorGroups.map((g) => g.visible), scale: a.floorGroups.map((g) => g.scale.x), hits: world.hits.map((h) => h.id) };
// 3. Back to the Building: a new view, its documents unread again, read on frame 9
world.setFloors(null, null);
run("backFloor", [[1, () => world.update(models.building(null))], [9, () => world.update(models.building(DOCS))]]);
// 4. Back to the City
world.setFocus(null);
run("backBuilding", [[2, () => world.update(models.city())]]);
out.end = { open: a.open, hits: world.hits.map((h) => h.id), y: a.floorGroups.map((g) => g.position.y) };
out.lost = lost;
out.others = others.map((t, i) => { const now = positions(meshesOf(t.group)); return [...now].every(([m, p]) => othersBefore[i].get(m) && p.every((v, k) => v === othersBefore[i].get(m)[k])) && t.group.visible; });
out.sheetsKept = true;
out.curve = { P, GAP, n };
console.log(JSON.stringify(out));
""")
    assert got["lost"] == [], f"no mesh of the clicked building is ever replaced across the route changes and the late documents: {got['lost'][:3]}"
    frames = got["frames"]
    opening = [f for f in frames if f["label"] == "open" and "maxXZ" in f]
    assert opening and all(f["maxXZ"] < 1e-9 for f in opening), "while it opens, no mesh moves sideways: only up"
    assert all(f["minDy"] >= -1e-9 for f in opening), "and no mesh moves down on any frame of the opening, across the route change and the documents arriving"
    assert all(abs(f["open"] - f["reference"]) < 1e-12 for f in frames if f["label"] == "open"), "the progress is the prototype's exponential approach, frame by frame, whatever the models do meanwhile"
    step_curve = [abs(b["open"] - a["open"]) for a, b in zip(opening, opening[1:])]
    assert max(step_curve) < 0.15, "no frame advances the opening by more than the exponential approach allows (a jump would)"
    assert all(f["maxDy"] <= f["bound"] + 1e-9 for f in opening), "no mesh rises by more than the highest floor does by that frame's step of the prototype's curve"
    floor = [f for f in frames if f["label"] == "floor" and "chosenSame" in f]
    assert all(f["chosenSame"] for f in floor), "on the floor click every mesh of the chosen floor keeps its transform, on every frame"
    chosen = got["floors"].index("engineering")
    for i in range(len(got["floors"])):
        series = [f["scale"][i] for f in floor]
        if i == chosen:
            assert all(v == 1 for v in series)
        else:
            assert all(b <= a + 1e-12 for a, b in zip(series, series[1:])) and series[-1] <= 0.001, f"floor {i} shrinks monotonically to nothing"
    assert got["afterFloor"]["visible"].count(True) == 1 and got["afterFloor"]["hits"][:3] == ["agent", "tasks", "desk"], "on the floor the room's three ways in are what the pointer meets (R-31)"
    back_floor = [f for f in frames if f["label"] == "backFloor" and "chosenSame" in f]
    assert all(f["chosenSame"] for f in back_floor), "Back from the floor: the chosen floor still keeps its transform"
    for i in range(len(got["floors"])):
        series = [f["scale"][i] for f in back_floor]
        assert all(b >= a - 1e-12 for a, b in zip(series, series[1:])) and series[-1] == 1, f"floor {i} grows back monotonically"
    closing = [f for f in frames if f["label"] == "backBuilding" and "maxDy" in f]
    assert all(f["maxXZ"] < 1e-9 for f in closing) and all(f["maxDy"] <= 1e-9 and -f["minDy"] <= f["bound"] + 1e-9 for f in closing), "Back from the Building: every mesh only comes down, by the same curve"
    assert got["end"]["open"] == 0 and got["end"]["hits"] == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"], "and the City is whole again"
    assert got["others"] == [True, True], "the other buildings never moved and never left"


@needs_node
def test_a_click_on_a_floor_shrinks_the_other_floors_to_nothing_and_keeps_the_chosen_one_where_it_is(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const { world } = make();
world.setFocus("a", true);
const a = world.towers.get("a");
const chosen = a.floorGroups[1];
const snap = (g) => [g.position.x, g.position.y, g.position.z, g.scale.x, g.scale.y, g.scale.z, g.rotation.x, g.rotation.y, g.rotation.z];
const chosenBefore = snap(chosen);
const meshes = new Set();
a.group.traverse((n) => { if (n.isMesh) meshes.add(n); });
world.setFloors("business", null);          // the click on the floor
const scales = [[], [], []];
let frame = 0;
const sameChosen = [];
let routed = false;
while (world.moving() && frame < 80) {
  world.step(1 / 30);
  frame += 1;
  if (frame === 10) { world.update(model({ focus: "a", floor: "business", room: { tips: { agent: "a", desk: "d", tray: "t" }, board: null, door: false } })); routed = true; }
  [0, 2, 3].forEach((i, k) => scales[k].push(a.floorGroups[i].scale.x));
  sameChosen.push(snap(chosen).every((v, i) => v === chosenBefore[i]));
}
const after = new Set();
a.group.traverse((n) => { if (n.isMesh) after.add(n); });
const meshesKept = [...meshes].every((m) => after.has(m));
const entered = { routed, frames: frame, scales: scales.map((s) => ({ monotone: s.every((v, i) => i === 0 || v <= s[i - 1] + 1e-12), last: s[s.length - 1], first: s[0] })), sameChosen: sameChosen.every(Boolean), meshesKept,
  visible: [0, 1, 2, 3].map((i) => a.floorGroups[i].visible), hits: world.hits.map((h) => h.id), others: ["b", "c"].map((id) => world.towers.get(id).group.visible) };
// Back from the floor: the floors grow back by the same approach
world.setFloors(null, null);
const back = [];
while (world.moving()) { world.step(1 / 30); back.push(a.floorGroups[0].scale.x); }
console.log(JSON.stringify({ ...entered, back: { monotone: back.every((v, i) => i === 0 || v >= back[i - 1] - 1e-12), last: back[back.length - 1], steps: back.length } }));
""")
    assert got["routed"] is True and got["frames"] < 40, "the route changes during the motion and the motion ends within a second"
    assert all(s["monotone"] and s["last"] <= 0.001 for s in got["scales"]), "every other floor shrinks, never grows, to nothing"
    assert got["sameChosen"] is True, "the chosen floor's transform is not touched in any frame"
    assert got["meshesKept"] is True, "no mesh is replaced: the floor the person is on is the one they clicked"
    assert got["visible"] == [False, True, False, False], "the others are out of the scene when they have reached nothing"
    assert got["hits"] == ["agent", "tasks", "desk"], "the owl, the board of notes and the bookcase are what the pointer meets (R-31)"
    assert got["others"] == [True, True] or got["others"] == [False, False], "the city furniture goes only when the engine hides it after everything settled (not by the world's own motion)"
    assert got["back"]["monotone"] is True and got["back"]["last"] == 1, "Back: the floors grow back by the same approach"


@needs_node
def test_back_closes_the_building_by_the_same_curve_from_wherever_it_is_and_the_other_buildings_stay(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const { world } = make();
const a = world.towers.get("a");
const tops = () => a.floorGroups.map((g) => g.position.y);
const closedYs = tops();
const closedOpacity = a.group.children[0].children[0].children[1].material.opacity;
world.setFocus("a", true);
const frames = [];
world.setFocus(null);
for (let f = 0; f < 80 && world.moving(); f++) { world.step(1 / 30); frames.push({ open: a.open, y: tops()[3], others: ["b", "c"].every((id) => world.towers.get(id).group.visible) }); }
const out = {
  monotoneDown: frames.every((fr, i) => i === 0 || fr.open <= frames[i - 1].open + 1e-12),
  yMonotone: frames.every((fr, i) => i === 0 || fr.y <= frames[i - 1].y + 1e-12),
  othersAlways: frames.every((fr) => fr.others),
  endsClosed: tops().every((y, i) => Math.abs(y - closedYs[i]) < 1e-9),
  opacityBack: a.group.children[0].children[0].children[1].material.opacity === closedOpacity,
  hitsCity: world.hits.map((h) => h.id),
  firstStep: frames[0].open,
};
// reverse in the middle of the opening: the progress is continuous, it turns round where it was
world.setFocus("a");
for (let f = 0; f < 8; f++) world.step(1 / 30);
const mid = a.open;
world.setFocus(null);
world.step(1 / 30);
out.turn = [mid, a.open];
console.log(JSON.stringify(out));
""")
    assert got["monotoneDown"] and got["yMonotone"], "Back runs the opening backwards: the floors come down, nothing the other way"
    assert got["othersAlways"] is True, "the other buildings never leave"
    assert got["endsClosed"] is True and got["opacityBack"] is True, "and the building ends exactly as it was: the same floors at the same heights, the walls opaque"
    assert got["hitsCity"] == ["a", "b", "c"], "the City is whole again: every building a hit"
    assert got["firstStep"] < 1, "Back starts from where the building is"
    mid, after = got["turn"]
    assert 0 < mid < 1 and after < mid and mid - after < 0.35, "a Back in the middle of the opening turns the motion round where it was, with no jump"


@needs_node
def test_a_poll_changes_the_world_in_place_a_tower_is_made_again_only_when_its_floors_change(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const { world } = make({ focus: "a" });
world.setFocus("a", true);
const groups = () => ["a", "b", "c"].map((id) => world.towers.get(id).group);
const g0 = groups();
const out = {};
const same = (x, y) => x.every((g, i) => g === y[i]);
// the same model: nothing
out.same = world.update(model({ focus: "a" }));
// other words: a tooltip, a name, a plate, the sub line: nothing is built again
const words = model({ focus: "a" });
words.lots[0].tip = "other"; words.lots[1].name = "renamed"; words.lots[0].floors[1].plate.runsText = "9 / 9"; words.lots[2].sub = "x";
out.words = world.update(words);
out.wordsKept = same(g0, groups());
// a floor of b changes state: it changes where it stands, no tower is made again
const changed = model({ focus: "a" });
changed.lots[1].floors[0].state = "working"; changed.lots[1].floors[0].window = "lit";
out.state = world.update(changed);
const g1 = groups();
out.stateKept = [g1[0] === g0[0], g1[1] === g0[1], g1[2] === g0[2]];
// the open building's own floor changes: it is made again, still open, with its rooms
const open = model({ focus: "a" });
open.lots[0].floors[2].state = "working"; open.lots[0].floors[2].window = "lit";
out.openState = world.update(open);
const a = world.towers.get("a");
out.stillOpen = [a.open, a.interior, a.group === g0[0]];
// a floor is added to c: c alone is made again (its floors changed), a and b keep their groups
const g2 = groups();
const added = model({ focus: "a" });
added.lots[2].floors.push({ ...added.lots[2].floors[0], name: "extra" });
out.added = world.update(added);
const g3 = groups();
out.addedKept = [g3[0] === g2[0], g3[1] === g2[1], g3[2] === g2[2]];
// another set of lots builds the world again
out.lots = world.update(model({ lots: [lot("a"), lot("b")] }));
console.log(JSON.stringify(out));
""")
    assert got["same"] == {"rebuild": False, "structure": False, "inPlace": False, "focus": False, "floors": False}
    assert got["words"]["structure"] is False and got["wordsKept"] is True, "other words never build anything"
    assert got["state"]["structure"] is False and got["state"]["inPlace"] is True and got["stateKept"] == [True, True, True], "a floor that changed state changes where it stands: no building is made again"
    assert got["stillOpen"] == [1, True, True], "the open building whose floor changed state stays open, with its rooms, and is the same group"
    assert got["added"]["structure"] is True and got["addedKept"] == [True, True, False], "a building whose floors changed (an agent came) is made again and no other"
    assert got["lots"]["rebuild"] is True, "only another set of lots builds the world again"


def test_the_engine_hands_the_scene_over_between_the_screens_and_the_views_never_take_it_down():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "updateWorld(nextModel)" in engine and "content.update(next)" in engine and "setOptions(next)" in engine, "the world is updated in place; the next screen takes over its handlers"
    assert "else content.setFocus(id, reducedQuery.matches);" in engine and "refocus(true, FLY_SETTLE_AT)" in engine, "a click opens the building (or goes into the floor) and flies the camera together"
    assert "tween.retarget(goal)" in engine, "the camera goes on from where it is when the page's panels appear"
    assert "loop.start(\"world\", { ambient: false })" in engine and "if (!moving) {" in engine, "the opening runs every frame and stops when it is done: nothing draws while still"
    assert "content.finish()" in engine and "reducedQuery.matches" in engine, "reduced motion skips to the end state"
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert "acquireWorld(options)" in frame and "releaseWorld()" in frame and '["city", "building", "floor", "lobby"].includes(route.screen)' in frame
    for name in ("city.js", "building.js"):
        view = (JS / "views" / name).read_text(encoding="utf-8")
        assert "frame.acquireWorld(" in view and "engine.dispose()" not in view, f"{name}: the screen takes the scene over and leaves it to the frame"
        assert 'engine.show("world"' in view
    assert "snapshot, now" in (JS / "main.js").read_text(encoding="utf-8")


@needs_node
def test_the_camera_goes_on_from_where_it_is_when_its_goal_changes(tmp_path):
    got = run_node(tmp_path, r"""
import { createTween } from "@JS@/scene/tween.js";
const a = { left: -20, right: 20, top: 11.25, bottom: -11.25 };
const b = { left: 3, right: 9, top: 4, bottom: -1 };
const b2 = { left: 6, right: 14, top: 5, bottom: -3 };
const t = createTween();
const settled = [];
t.start(a, b, 0, 0.9).then((v) => settled.push(v));
let f = null;
let now = 0;
for (let i = 0; i < 12; i++) { now += 1000 / 60; f = t.step(now); }
const before = f;
t.retarget(b2);
now += 1000 / 60;
const after = t.step(now);
const jump = Math.max(...["left", "right", "top", "bottom"].map((k) => Math.abs(after[k] - before[k])));
const lastStep = Math.max(...["left", "right", "top", "bottom"].map((k) => Math.abs(before[k] - 0)));
let end = after;
for (let i = 0; i < 200 && t.active(); i++) { now += 1000 / 60; end = t.step(now); }
await new Promise((r) => setTimeout(r, 5));
console.log(JSON.stringify({ jump, end: [end.left, end.right, end.top, end.bottom].map((x) => Math.round(x * 1e6) / 1e6), settled, active: t.active(), retargetIdle: createTween().retarget(b) }));
""")
    assert got["jump"] < 3.0, "a goal that changes in flight bends the move: no frame jumps to the new place"
    assert got["end"] == [6, 14, 5, -3], "and the camera lands exactly on the new goal"
    assert got["settled"] == [True] and got["active"] is False and got["retargetIdle"] is False


@needs_node
def test_the_scene_is_fitted_in_what_the_parts_over_it_leave(tmp_path):
    got = run_node(tmp_path, r"""
import { obstacleInset } from "@JS@/frame/frame.js";
const r = (left, top, w, h) => ({ left, top, width: w, height: h, right: left + w, bottom: top + h });
const wide = r(0, 0, 1280, 720);
const out = {};
out.kpiColumn = obstacleInset(r(16, 62, 188, 190), wide);
out.kpiRow = obstacleInset(r(16, 62, 480, 62), r(0, 0, 900, 700));
out.panel = obstacleInset(r(1280 - 16 - 400, 62, 400, 508), wide);
out.waiting = obstacleInset(r(1280 - 16 - 380, 300, 380, 270), wide);
out.header = obstacleInset(r(16, 16, 440, 36), wide);
out.track = obstacleInset(r(16, 570, 1248, 134), wide);
out.dockedPanel = obstacleInset(r(16, 380, 668, 300), r(0, 0, 680, 380));   // below the scene: it does not touch it
out.nothing = obstacleInset(r(0, 0, 0, 0), wide);
console.log(JSON.stringify(out));
""")
    assert got["kpiColumn"] == {"side": "left", "amount": 220}, "a column of cards at the left takes the left"
    assert got["kpiRow"] == {"side": "top", "amount": 136}, "a row of cards takes the top (the tablet layout), below its bottom edge"
    assert got["panel"] == {"side": "right", "amount": 432} and got["waiting"] == {"side": "right", "amount": 412}
    assert got["header"] == {"side": "top", "amount": 64} and got["track"] == {"side": "bottom", "amount": 166}
    assert got["dockedPanel"] is None and got["nothing"] is None, "a part that does not touch the scene (the panel docked below it) takes nothing"
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert "obstacleInset(part.getBoundingClientRect(), scene)" in frame and "kpis.el, header, noticeBox.hidden ? null : noticeBox, dock" in frame, \
        "every part over the scene is measured, none is assumed (R-1, R-2: the top row and the dock are the parts now; the header button of the actions is gone)"


def test_the_in_between_layout_has_the_tablet_rules_of_the_handoff_and_there_is_no_docked_band_below_900_px():
    css = interface_css()
    block = css[css.index("the in-between layout (WP-9.11"):]
    assert "@media (min-width: 900px) and (max-width: 1099px)" in block, "M-3: the in-between band is 900 to 1099 px"
    mid = block[:block.index("\n.wb-add-project")]
    for rule in (".wb-door-label { display: none; }", "--wb-panel-narrow: 340px", "--wb-wait-w: 340px", "--wb-plate-w: 230px", ".wb-track-left .wb-steps { overflow-x: auto; }"):
        assert rule in mid, f"the tablet rule: {rule}"
    assert "wb-plate-chips" not in css, "R-25: a plate has no count chips, so the in-between band has no rule that hides them"
    assert ".wb-kpis { display: flex;" not in mid and ".wb-kpi-short { display: inline; }" not in mid, "R-5: the KPI cards stay a column of two in this band (R4D-6), the labels are the long ones"
    for gone in ('grid-template-areas: "scene" "content" "track"', ".wb-dock { position: static;", ".wb-panel-floor, .wb-panel-building { height: auto; }", "--wb-dock-h"):
        assert gone not in css_file("frame"), f"M-3: the docked panel is gone from the frame's stylesheet, not left dead: {gone}"
    assert ".wb-plate.is-tiny" in css and "is-tiny" in (SCENE / "labels.js").read_text(encoding="utf-8"), "a plate shortens to its name row when the stack still would not fit"
    kpis = (JS / "frame" / "kpis.js").read_text(encoding="utf-8")
    assert all(word in kpis for word in ('"Runs"', '"Spend"', "wb-kpi-short", "wb-kpi-long")) and '"Decisions"' not in kpis, "the two cards carry their short labels (the phone shows them)"
    assert "plateWidth()" in (JS / "views" / "building.js").read_text(encoding="utf-8"), "the fit leaves the width of the plates as the stylesheet has them now"


@needs_node
def test_the_request_list_has_a_height_of_about_six_rows_a_width_and_ellipsised_titles_with_the_whole_title_as_the_tooltip(tmp_path):
    got = run_node(tmp_path, r"""
import { FakeNode, find, all } from "@FAKE@";
import { createTrack } from "@JS@/frame/track.js";
const task = (id) => ({ id, key: `k${id}`, title: `Task ${id}`, state: "ready", agent: "engineering" });
const long = "A very long title that goes on and on and would stretch the list as wide as the page if nothing held it in";
const requests = Array.from({ length: 9 }, (_, i) => ({ id: i + 1, title: i === 3 ? long : `Request ${i + 1}`, state: "ready", running: false, selected: i === 8 }));
const model = { request: { id: 9, title: "Request 9", state: "ready", project: "shop", projectId: "p" }, requests, steps: [], doneCount: 0, total: 0, now: null };
document.activeElement = null;
FakeNode.prototype.getBoundingClientRect = () => ({ left: 10, top: 500 });
const scrolled = [];
FakeNode.prototype.scrollIntoView = function (o) { scrolled.push([this.attrs["data-request"], o && o.block]); };
const track = createTrack({ onOpenSteps() {}, onSelectRequest() {} });
track.set(model, "ready");
const options = all(track.el, ".wb-track-desktop .wb-req-option");
const longOption = options[3];
const list = find(track.el, ".wb-track-desktop .wb-req-menu");
const chip = find(track.el, ".wb-track-desktop .wb-req-chip");
chip.click();
const press = (key) => { for (const fn of list.listeners.keydown || []) fn({ key, preventDefault() {}, stopPropagation() {} }); };
press("ArrowUp"); press("ArrowUp");
console.log(JSON.stringify({ rows: options.length, longTitle: longOption.attrs.title === long, spanTitle: find(longOption, ".wb-req-option-title").attrs.title === long, shortTitle: options[0].attrs.title, scrolled }));
""")
    assert got["rows"] == 9 and got["longTitle"] is True and got["spanTitle"] is True and got["shortTitle"] == "Request 1", "each row carries its whole title as the tooltip"
    assert got["scrolled"] == [["8", "nearest"], ["7", "nearest"]], "the arrows keep the row they reach in view of the bounded list"
    css = interface_css()
    menu = css[css.index(".wb-req-menu {"):css.index(".wb-req-menu[hidden]")]
    assert "max-width: min(28rem, 90vw)" in menu and "max-height: min(calc(6 * var(--wb-req-row) + 5 * 2px + 8px), 60vh)" in menu and "overflow-y: auto" in menu, "about six rows, then it scrolls; 28 rem wide at most"
    assert "grid-template-columns: minmax(0, 1fr)" in menu, "the single column is limited by the box: a long title is cut, it never widens the rows (seen in the pane)"
    assert "--wb-req-row: 2.25rem" in css and "min-height: var(--wb-req-row)" in css
    assert re.search(r"\.wb-req-option-title \{[^}]*text-overflow: ellipsis", css), "a long title is cut with an ellipsis"


# --- the six corrections of the maintainer's last test (2026-10-09) ---------------------------------------------------------------------------------

@needs_node
def test_a_room_is_marked_by_brackets_and_never_outlined_and_the_citys_building_keeps_its_one_body(tmp_path):
    # R-28 and R-31 supersede "the outline is the outer parts only": a floor of the Building and an object of a room (the owl, the board, the bookcase, the door) are marked by
    # corner brackets of their own (a hidden group of one mesh, shown by the engine), and the room is drawn in batches that mark no part of an outline
    got = run_node(tmp_path, WORLD_JS + r"""
import { outlineGeometry, outlineMeshes } from "@JS@/scene/outline.js";
const { world } = make();
world.update(model({ focus: "a", floor: "planning", room: { tips: { agent: "a" }, board: null, door: true } }));
world.setFocus("a", true);
world.setFloors("planning", null, true);
const out = { objects: {} };
for (const hit of world.hits) {
  out.objects[hit.id] = { shell: outlineMeshes(hit.object).length, marks: Boolean(hit.marks), hidden: hit.marks ? hit.marks.visible === false : null, meshes: hit.marks ? hit.marks.children.filter((c) => c.isMesh).length : 0, anchor: Boolean(hit.anchor) };
}
// the Building screen: a floor is marked by the brackets of its room, the door by its own
world.setFloors(null, null, true);
world.update(model({ focus: "a" }));
out.floorHits = {};
for (const hit of world.hits) out.floorHits[hit.id] = { marks: Boolean(hit.marks), hidden: hit.marks ? hit.marks.visible === false : null, shell: outlineMeshes(hit.object).length };
// the City: a building is one enclosing body, its silhouette
world.setFocus(null, true);
world.setFloors(null, null, true);
const tower = world.hits.find((h) => h.id === "a");
const city = outlineMeshes(tower.object);
out.city = { parts: city.length, allShell: city.every((m) => m.userData.shell === true), segments: outlineGeometry(THREE, tower.object, 0.06).getAttribute("position").count / 2 };
// an object with no part marked has no outline at all (no fall back to every mesh)
const bare = new THREE.Group(); bare.add(new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial()));
out.bare = outlineMeshes(bare).length;
console.log(JSON.stringify(out));
""")
    assert got["bare"] == 0, "no shell part, no outline: never every mesh"
    assert sorted(got["objects"]) == ["agent", "desk", "lobby-door", "tasks"], "the Lobby's room: the owl, the board, the bookcase and the door"
    for hit, o in got["objects"].items():
        assert o["marks"] is True and o["hidden"] is True and o["meshes"] == 1 and o["shell"] == 0 and o["anchor"] is True, f"{hit}: brackets of its own, hidden until asked for, one mesh, no outline part, a point for its tooltip"
    assert got["floorHits"] and all(f["marks"] is True and f["hidden"] is True and f["shell"] == 0 for f in got["floorHits"].values()), "a floor of the Building and the door are marked by brackets, never by an outline"
    assert got["city"]["allShell"] is True and got["city"]["parts"] == 1 and got["city"]["segments"] == 12, "a building's outline in the City is one body's twelve edges: no line at any floor boundary, none for the roof's parts or the windows"


@needs_node
def test_every_floor_has_a_board_a_bookcase_and_a_desk_and_the_top_floor_has_no_roof_when_open(tmp_path):
    # R-23 supersedes "the tray is on every floor": no tray, no table of sheets, no cabinet; the board and the bookcase are on every floor, with or without a task or a document
    got = run_node(tmp_path, WORLD_JS + r"""
const states = () => lot("a", { floors: lot("a").floors.map((f, i) => ({ ...f, decisions: [0, 1, 2, 7][i], notes: [[], ["done"], ["done", "run", "left"], ["left", "left", "run", "done", "done", "done", "left"]][i], documents: [0, 3, 16, 17][i] })) });
const { world } = make({ lots: [states(), lot("b"), lot("c")] });
world.setFocus("a", true);
const a = world.towers.get("a");
const out = { board: [0, 1, 2, 3].map((i) => Boolean(a.parts[i].board && a.parts[i].board.children.length === 1)), shelf: [0, 1, 2, 3].map((i) => Boolean(a.parts[i].shelf && a.parts[i].shelf.children.length === 1)),
  cases: [0, 1, 2, 3].map((i) => a.parts[i].cases), notes: [0, 1, 2, 3].map((i) => a.parts[i].notesShown), noTray: [0, 1, 2, 3].every((i) => a.parts[i].tray === undefined && a.parts[i].sheets === undefined) };
// the roof: gone when the building is open, and the top floor has no ceiling slab
out.roof = a.group.children.filter((c) => c.position.y > a.floorGroups[3].position.y + 2).map((c) => c.visible);
out.shells = a.floorGroups.map((g) => g.children[0].visible);
console.log(JSON.stringify(out));
""")
    assert got["board"] == [True] * 4 and got["shelf"] == [True] * 4, "the board of notes and the bookcase stand on every floor, with or without a task or a document"
    assert got["cases"] == [1, 1, 1, 2], "one bookcase holds sixteen binders, a second comes with the seventeenth"
    assert got["notes"] == [0, 1, 3, 6], "one note for each task of the agent, as many as the board holds: a second bookcase (17 documents) leaves it room for six of the seven"
    assert got["noTray"] is True, "no tray and no table of sheets"
    assert got["roof"] == [False] and got["shells"] == [False] * 4, "no roof slab over the top floor and no front wall: the room is open like the others"


def test_escape_has_one_handler_in_the_frame_and_none_in_the_screens():
    frame = (JS / "frame" / "frame.js").read_text(encoding="utf-8")
    assert "escapeStep({" in frame and frame.count('addEventListener("keydown", onKey)') == 1
    for name in ("floor.js", "building.js", "control.js", "lobby.js"):
        assert 'event.key !== "Escape"' not in (JS / "views" / name).read_text(encoding="utf-8"), f"{name} has no Escape handler of its own"


@needs_node
def test_escape_goes_through_its_steps_in_order_and_goes_up_from_every_screen(tmp_path):
    got = run_node(tmp_path, r"""
import { escapeStep } from "@JS@/frame/escape.js";
import * as router from "@JS@/router.js";
const P = "0123456789ab";
const r = (h) => router.parse(`#/p/${P}${h}`);
const out = {};
const step = (route, extra = {}) => escapeStep({ route, ...extra });
out.field = step(r("/floor/marketing"), { field: true, dialog: true, menu: true });
out.dialog = step(r("/floor/marketing/desk/docs%2Fa.md"), { dialog: true, menu: true, selection: true });
out.floorDocument = step(r("/floor/marketing/desk/docs%2Fa.md"), { menu: true, selection: true });
out.floorPending = step(r("/floor/marketing/inbox/4"), {});
out.lobbyDocument = step(r("/lobby/desk/docs%2Fa.md"), {});
out.lobbyPending = step(r("/lobby/inbox/4"), {});
out.menu = step(r("/floor/marketing"), { menu: true, selection: true });
out.selection = step(r("/lobby"), { selection: true });
out.floorUp = step(r("/floor/marketing"));
out.lobbyUp = step(r("/lobby"));
out.lobbyUpWithTab = step(r("/lobby/inbox"));
out.buildingUp = step(r(""));
out.controlUp = step(r("/control"));
out.controlFrom = step(r("/control/costs"), { from: `#/p/${P}/floor/marketing` });
out.cityNothing = step(router.parse("#/"));
console.log(JSON.stringify(out));
""")
    p = "0123456789ab"
    assert got["field"] == {"step": "none"}, "a field has the focus: nothing"
    assert got["dialog"] == {"step": "dialog"}, "a dialog closes before anything else"
    assert got["floorDocument"] == {"step": "document", "hash": f"#/p/{p}/floor/marketing/desk"}, "a document closes back to the Desk"
    assert got["floorPending"] == {"step": "document", "hash": f"#/p/{p}/floor/marketing/inbox"}
    assert got["lobbyDocument"] == {"step": "document", "hash": f"#/p/{p}/lobby/desk"} and got["lobbyPending"] == {"step": "document", "hash": f"#/p/{p}/lobby/inbox"}, "the Lobby too (it did nothing)"
    assert got["menu"] == {"step": "menu"} and got["selection"] == {"step": "selection"}, "a menu closes, then a selection is cleared"
    assert got["floorUp"] == {"step": "up", "hash": f"#/p/{p}"} and got["lobbyUp"] == {"step": "up", "hash": f"#/p/{p}"} and got["lobbyUpWithTab"] == {"step": "up", "hash": f"#/p/{p}"}, "the Floor and the Lobby go up to the Building"
    assert got["buildingUp"] == {"step": "up", "hash": "#/city"}, "the Building goes up to the City (C-1: #/city)"
    assert got["controlUp"] == {"step": "up", "hash": f"#/p/{p}"} and got["controlFrom"] == {"step": "up", "hash": f"#/p/{p}/floor/marketing"}, "the Control room goes back to where it was opened from, else the Building"
    # In the Control room the frame holds no world (the room is its own scene): nothing there is a selection, so Escape goes straight up (the maintainer's
    # complaint was that it did not): `controlUp` and `controlFrom` above are that case.
    assert got["cityNothing"] == {"step": "none"}


@needs_node
def test_a_plate_and_a_row_of_the_list_carry_the_same_name_row_and_the_plate_has_no_chips_and_the_row_has_them(tmp_path):
    got = run_node(tmp_path, r"""
import { FakeNode, find, all } from "@FAKE@";
import { plateNode, rowNode } from "@JS@/scene/plates.js";
const p = { name: "engineering", label: "Engineering", dot: "theme", decisions: 2, word: "working", tone: "pui-theme", modeLine: "Reviews are released", done: 1, left: 2, queued: 0, runsText: "3 / 14", runsShare: 0.2, usdText: "$0 / $5", usdShare: 0, unknown: 0, mode: "autonomous", pips: 3, acting: null, actingPips: 0, selected: false, off: false };
const plate = plateNode(p);
const row = rowNode(p, { href: "#/p/x/floor/engineering", "aria-label": "Engineering, working" });
const shape = (n) => ({ tag: n.tagName, parts: n.children.map((c) => c.cls().join(" ")), text: n.textContent });
console.log(JSON.stringify({ plate: shape(plate), row: shape(row), href: row.attrs.href, classes: row.cls(), chipsOnPlate: all(plate, ".pui-badge").map((n) => n.textContent), chipsOnRow: all(row, ".wb-fl-chips .pui-badge").map((n) => n.textContent) }));
""")
    assert got["plate"]["tag"] == "DIV" and got["row"]["tag"] == "A" and got["href"] == "#/p/x/floor/engineering"
    assert got["plate"]["parts"] == ["wb-plate-row", "wb-plate-meters"], "R-25: the name row and the two meters, nothing else"
    assert got["row"]["parts"] == ["wb-dot is-theme", "wb-fl-title", "wb-fl-state", "wb-fl-chips", "wb-fl-chev"], "R-27: the dot, the name line (name, badge, mode word), the state badge, the chips under, the chevron"
    assert got["chipsOnPlate"] == ["2", "working"], "R-25: no count chips on a plate: the decisions badge and the state badge only"
    assert got["chipsOnRow"] == ["1 done", "2 left"], "the count chips are on the row"
    assert "wb-fl-row" in got["classes"]


def test_the_chosen_building_keeps_a_thin_outline_in_the_city_besides_the_hover():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "function drawMarked()" in engine and "content.marked" in engine and "markedOutline" in engine
    world = (SCENE / "world.js").read_text(encoding="utf-8")
    assert "marked: model.marked || null" in world and "content.marked = m.marked || null" in world
    city = (JS / "views" / "city.js").read_text(encoding="utf-8")
    assert "marked: selectedId" in city, "the project the switcher has chosen (the City's selectedId)"
    wm = (JS / "world-model.js").read_text(encoding="utf-8")
    assert "marked && lots.some((l) => l.id === marked) && !there ? marked : null" in wm, "only in the City, only for a project that is drawn"


def test_the_route_changes_at_the_click_and_never_waits_for_the_scene():
    for name in ("city.js", "building.js"):
        source = (JS / "views" / name).read_text(encoding="utf-8")
        assert "engine.flyTo(id);" in source and ".then(go)" not in source and "flying" not in source, f"{name}: the scene starts and the route changes in the same moment"
    city = (JS / "views" / "city.js").read_text(encoding="utf-8")
    assert city.index("engine.flyTo(id);") < city.index("window.location.hash = router.buildingHash(id);")


@needs_node
def test_each_thing_a_poll_or_the_documents_change_changes_where_it_stands(tmp_path):
    """Root cause of PR 252 finding 1 (the package's plan, outside the repository: tower-rebuilt-on-the-route-path): `towerStructure` held the state, window, decisions,
    documents and the work-order floor, so any of them built the whole tower again. Each is changed in place; a floor whose documents or tasks are unread (`null`) keeps
    what it shows. Round 4 (R-23, R-23b, R-49): the board's notes and the bookcase's binders are made again in the meshes that stand for them (their geometry is swapped)."""
    got = run_node(tmp_path, WORLD_JS + SNAP_JS + r"""
const { world } = make({ focus: "a" });
world.setFocus("a", true);
const a = world.towers.get("a");
const all = meshesOf(a.group);
const out = {};
const cur = model({ focus: "a" });   // each edit goes on from the last one, as the polls do
const edit = (fn) => {
  fn(cur.lots[0]); const m = JSON.parse(JSON.stringify(cur)); const r = world.update(m); const now = meshesOf(a.group);
  const res = { r, lost: [...all].filter((x) => !now.has(x)).length, added: [...now].filter((x) => !all.has(x)).length, same: world.towers.get("a") === a };
  all.clear(); for (const x of now) all.add(x);
  return res;
};
// the decisions of a floor change what the owl opens and the mark, not what is drawn
out.decisionsUp = edit((l) => { l.floors[2].decisions = 4; });
out.decisionsDown = edit((l) => { l.floors[2].decisions = 0; });
// the board's notes: one more task arrives; the board is the same mesh with a new geometry
out.notes = [a.parts[3].notesShown];
out.notesUp = edit((l) => { l.floors[3].notes = ["done", "run", "left"]; });
out.notes.push(a.parts[3].notesShown);
// the bookcase: a second one comes with the seventeenth document, a third with the thirty-fourth
out.cases = [a.parts[3].cases];
out.documentsUp = edit((l) => { l.floors[3].documents = 17; }); out.cases.push(a.parts[3].cases);
out.documentsMore = edit((l) => { l.floors[3].documents = 40; }); out.cases.push(a.parts[3].cases);
// unread documents and tasks: null changes nothing
out.unread = edit((l) => { l.floors[3].documents = null; l.floors[3].notes = null; });
out.unreadCases = a.parts[3].cases;
// the window of a floor: the material of the same meshes
out.window = edit((l) => { l.floors[0].window = "lit"; });
// R-16: the glass of a floor is one batched mesh, and a window's state is a repaint of its vertices (R-18: the lit tone is the warm white)
const glass = a.floorGroups[0].children[0].children[1];
const paint = glass.geometry.getAttribute("color");
out.litGlass = [paint.getX(0), paint.getY(0), paint.getZ(0)].every((v, i) => Math.abs(v - [cityTones(palette).glassLit.r, cityTones(palette).glassLit.g, cityTones(palette).glassLit.b][i]) < 1e-6);
// R-20, R-21: the decision mark stands beside a floor that waits: a decision arrives on a floor that had none and the floor waits
const marks = (i) => a.overlay.children.filter((c) => c.userData.mark && c.userData.floor === i).length;
out.markers = marks(3);
out.marker = edit((l) => { l.floors[3].decisions = 1; l.floors[3].state = "waiting"; l.floors[3].window = "lit"; }); out.markersAfter = marks(3);
// a state change makes that one room again, and only that
const roomMeshes = meshesOf(a.inner[3]);
const other = meshesOf(a.inner[2]);
out.state = edit((l) => { l.floors[3].state = "working"; l.floors[3].window = "lit"; });
const roomNow = meshesOf(a.inner[3]);
out.stateRoom = { replaced: [...roomMeshes].every((m) => !roomNow.has(m)), othersKept: [...other].every((m) => meshesOf(a.inner[2]).has(m)), motions: a.motions.length };
console.log(JSON.stringify(out));
""")
    for key in ("decisionsUp", "decisionsDown", "notesUp", "documentsUp", "documentsMore", "unread", "window", "marker", "state"):
        assert got[key]["same"] is True and got[key]["r"]["structure"] is False, f"{key}: the same tower, nothing built again"
    assert got["decisionsUp"]["lost"] == 0 and got["decisionsDown"]["lost"] == 0, "the decisions of a floor draw nothing: the owl's hit, the mark and the tooltip follow"
    assert got["notes"] == [2, 3] and got["notesUp"]["lost"] == 0 and got["notesUp"]["added"] == 0, "a task that arrives is a note on the board, in the board's own mesh (R-23b)"
    assert got["cases"] == [1, 2, 3] and got["documentsUp"]["lost"] == 0 and got["documentsMore"]["lost"] == 0, "the binders are made again in the bookcase's own mesh; a second bookcase comes at the seventeenth document (R-49)"
    assert got["unread"]["lost"] == 0 and got["unread"]["added"] == 0 and got["unreadCases"] == 3, "documents and tasks not read yet (null) change nothing: the shelves keep their binders"
    assert got["window"]["lost"] == 0 and got["litGlass"] is True, "a window changes its colour, not its meshes (R-16, R-18)"
    assert got["markers"] == 0 and got["markersAfter"] == 1, "a decision that arrives on a floor that waits makes the mark beside it (R-20, R-21)"
    assert got["stateRoom"]["replaced"] is True and got["stateRoom"]["othersKept"] is True, "a state change makes that floor's room again (the owl takes another pose) and no other floor's"


# The page around the engine, as little of it as the engine reads: the document and the window of the fake DOM, a clock and a frame queue the test
# drives, a probe element whose colour is the token it was given, a host of 1280 x 720 and a resize observer that reports it once.
ENGINE_PAGE_JS = r"""
import { FakeNode } from "@FAKE@";
const TOKENS = { "--wb-raised": "rgb(255, 255, 255)", "--wb-ground": "rgb(244, 245, 247)", "--pui-bg-emphasis": "rgb(226, 229, 233)", "--pui-text": "rgb(30, 34, 41)", "--pui-text-muted": "rgb(98, 106, 118)",
  "--pui-border": "rgb(208, 213, 221)", "--pui-theme": "rgb(36, 99, 235)", "--pui-warn": "rgb(217, 119, 6)", "--pui-success": "rgb(22, 163, 74)", "--pui-error": "rgb(220, 38, 38)", "--pui-muted": "rgb(120, 130, 145)", "--pui-bg": "rgb(255, 255, 255)" };
const clock = { t: 1000, queue: [], id: 1 };
performance.now = () => clock.t;
globalThis.requestAnimationFrame = (fn) => { const id = clock.id++; clock.queue.push([id, fn]); return id; };
globalThis.cancelAnimationFrame = (id) => { clock.queue = clock.queue.filter((e) => e[0] !== id); };
export const frame = (ms) => { clock.t += ms; const run = clock.queue; clock.queue = []; for (const [, fn] of run) fn(clock.t); return run.length; };
document.hidden = false;
const create = document.createElement;
document.createElement = (tag) => {
  const n = create(tag);
  const style = {};
  n.style = { setProperty: (k, v) => { style[k] = v; } };
  n._style = style;
  n.dataset = {};
  n.clientWidth = 1280; n.clientHeight = 720; n.offsetWidth = 200; n.offsetHeight = 90;
  n.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1280, height: 720, right: 1280, bottom: 720 });
  n.appendChild = (c) => n.append(c);
  n.setPointerCapture = () => {}; n.releasePointerCapture = () => {};
  return n;
};
globalThis.getComputedStyle = (n) => ({ color: TOKENS[(String((n._style || {}).color || "").match(/var\((--[a-z-]+)\)/) || [])[1]] || "rgb(0, 0, 0)" });
globalThis.ResizeObserver = class { constructor(cb) { this.cb = cb; } observe() { this.cb([]); } disconnect() {} };
globalThis.window.devicePixelRatio = 1;
globalThis.window.addEventListener = () => {};
globalThis.window.removeEventListener = () => {};
"""


@needs_node
def test_the_engines_camera_goes_on_from_where_it_is_across_the_route_change_and_nothing_is_built_again(tmp_path):
    """Finding 2 of the review of PR 252, at the engine: the real engine, loop, camera and world, the product's own models in the product's order (the
    click starts the building and the camera, the route changes a few frames later with the panel's inset appearing, the documents are read later),
    then Back. The camera's frustum is read from the engine every frame."""
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
// `panel` is the room the panel takes from the right once the route has changed (the screen's panels appear then): 0 keeps the goal where it is
async function sequence(panel) {
  const host = document.createElement("div");
  let insets = { left: 0, right: 0, top: 0, bottom: 0, pad: 1.04 };
  const engine = createEngine(host, { label: "City", getInsets: () => insets, onOpen() {}, onHover() {}, onUnavailable() {} });
  const canvas = engine.canvas;
  const view = () => { const v = canvas.wbStats().view; return { cx: (v.left + v.right) / 2, cy: (v.top + v.bottom) / 2, w: v.right - v.left }; };
  const log = [];
  function run(name, at, cap = 150) {
    const pending = [...at];
    for (let i = 0; i < cap; i++) {
      for (let k = pending.length - 1; k >= 0; k--) if (pending[k][0] === i) { pending[k][1](); pending.splice(k, 1); }
      frame(1000 / 30);
      log.push({ name, i, ...view(), builds: canvas.wbStats().builds });
      if (!canvas.wbStats().animations && !pending.length && i > 3) break;
    }
  }
  engine.show("world", models.city(), "City");
  run("start", [], 10);
  const city = view();
  const builds0 = canvas.wbStats().builds;
  // the click on the building: the building and the camera start now; the route changes on frame 4 (the panel appears), the documents arrive on 12
  engine.flyTo(A);
  run("open", [[3, () => { insets = { ...insets, right: panel }; engine.show("world", models.building(null), "Building"); }], [11, () => engine.show("world", models.building(DOCS), "Building")]]);
  const open = view();
  // the click on a floor, the route changes on frame 3, the documents are read on frame 9
  engine.flyTo("floor:engineering");
  run("floor", [[2, () => engine.show("world", models.floor(null), "Floor")], [8, () => engine.show("world", models.floor(DOCS), "Floor")]]);
  // Back to the Building (documents unread again) and to the City, the panel gone
  run("backFloor", [[0, () => engine.show("world", models.building(null), "Building")], [7, () => engine.show("world", models.building(DOCS), "Building")]]);
  insets = { ...insets, right: 0 };
  run("backBuilding", [[0, () => engine.show("world", models.city(), "City")]]);
  return { log, city, open, end: view(), builds0, builds: canvas.wbStats().builds, towers: canvas.wbStats().towers };
}
console.log(JSON.stringify({ same: await sequence(0), panel: await sequence(420) }));
""")
    k = 1 - math.exp(-4.5 / 30)   # one frame's approach at 30 frames a second
    def of(run, name):
        return [f for f in run["log"] if f["name"] == name]
    def steps(frames, key):
        return [abs(b[key] - a[key]) for a, b in zip(frames, frames[1:])]
    for label, run in got.items():
        assert run["builds"] == run["builds0"], f"{label}: the engine builds the world once: the route changes, the documents and Back change it in place"
        opening = of(run, "open")
        widths = [f["w"] for f in opening]
        assert all(b <= a + 1e-9 or label == "panel" for a, b in zip(widths, widths[1:])), f"{label}: zooming in on the building, the camera's width only goes down"
        assert run["open"]["w"] < run["city"]["w"] * 0.8, f"{label}: and it lands close on the building"
        assert abs(run["end"]["w"] - run["city"]["w"]) < 1e-6 and abs(run["end"]["cx"] - run["city"]["cx"]) < 1e-6 and run["towers"][list(run["towers"])[0]] == 0, f"{label}: Back lands the camera where it started, the building closed"
    # the panel does not take room: the goal is one goal, so the camera's speed only ever falls, across the route change and the late documents (no jump)
    same = of(got["same"], "open")
    for key in ("w", "cx", "cy"):
        s = steps(same, key)
        moving_steps = [x for x in s if x > 0]
        landing = moving_steps.pop()   # the frame that snaps onto the goal (under a quarter of a pixel is left there)
        assert all(b <= a * 1.0001 + 1e-9 for a, b in zip(moving_steps, moving_steps[1:])), f"{key}: the camera's step falls frame after frame through the route change at frame 4 and the documents at 12: {[round(x, 4) for x in moving_steps][:14]}"
        assert landing < 0.3 * (opening[-1]["w"] / 1280) + 1e-9 or landing < 0.02, f"{key}: and the last frame lands within a quarter of a pixel ({landing:.4f})"
    # the panel appears at the route change: the goal moves by what it takes. The camera goes on from where it is: on every frame it covers at most one
    # frame's share of the distance to the goal in force (the one before the route changed or the one after it), so it never jumps to the new place
    moving = of(got["panel"], "open")
    for key in ("zoom", "cx", "cy"):   # the camera approaches its centre and its zoom (the reciprocal of the width), each by the same share
        read = (lambda f: 1 / f["w"]) if key == "zoom" else (lambda f, key=key: f[key])
        goals = (read(got["same"]["open"]), read(got["panel"]["open"]))
        last_move = max(i for i, (a, b) in enumerate(zip(moving, moving[1:])) if read(a) != read(b))   # the frame that lands is the one snapped to the goal
        for i, (a, b) in enumerate(zip(moving, moving[1:])):
            if i == last_move:
                continue
            far = max(abs(read(a) - g) for g in goals)
            assert abs(read(b) - read(a)) <= k * far * 1.02 + 1e-9, f"{key}: with the panel appearing mid-flight, frame {b['i']} moved {abs(read(b) - read(a)):.5f} of {far:.5f} left"
    floor = of(got["same"], "floor")
    assert all(b["w"] <= a["w"] + 1e-9 for a, b in zip(floor, floor[1:])), "closing on the chosen floor: only closer"
    fs = [x for x in steps(floor, "w") if x > 0][:-1]   # without the frame that snaps onto the goal
    assert all(b <= a * 1.0001 + 1e-9 for a, b in zip(fs, fs[1:])), "and its step falls frame after frame through the route change and the documents"
    back = of(got["same"], "backFloor") + of(got["same"], "backBuilding")
    assert all(b["w"] >= a["w"] - 1e-9 for a, b in zip(back, back[1:])), "Back opens the camera out, only out"


@needs_node
def test_the_camera_lands_when_what_is_left_is_under_a_quarter_of_a_pixel_never_with_a_visible_jump(tmp_path):
    """Finding 6: the move used to snap within one percent of its first distance, a residual jump of several pixels on the last frame."""
    got = run_node(tmp_path, r"""
import { createTween } from "@JS@/scene/tween.js";
const a = { left: -68.5, right: 68.5, top: 38.5, bottom: -38.5 };      // the City
const b = { left: -33.2, right: 38.0, top: 33.9, bottom: -6.2 };       // a building
const px = 1280;
const t = createTween();
t.start(a, b, 0, 1);
const frames = [];
let now = 0;
for (let i = 0; i < 400 && (i === 0 || t.active()); i++) { now += 1000 / 30; frames.push(t.step(now, px)); }
const scale = (f) => px / (f.right - f.left);
const toPx = (f, g) => Math.max(...["left", "right", "top", "bottom"].map((k) => Math.abs(f[k] - g[k]))) * scale(g);
const last = frames[frames.length - 1];
const steps = frames.slice(1).map((f, i) => toPx(frames[i], f));
console.log(JSON.stringify({ n: frames.length, landed: ["left", "right", "top", "bottom"].every((k) => Math.abs(last[k] - b[k]) < 1e-9), lastStep: steps[steps.length - 1], before: steps[steps.length - 2], falling: steps.slice(0, -1).every((s, i) => i === 0 || s <= steps[i - 1] * 1.0001 + 1e-9) }));
""")
    assert got["landed"] is True, "the move ends exactly on its goal"
    assert got["lastStep"] < 0.3, f"the last frame, which snaps to the goal, moves the camera by about a quarter of a pixel at most ({got['lastStep']:.3f} px)"
    assert got["falling"] is True, "every step before it is smaller than the one before: the approach, no residual jump"


@needs_node
def test_the_frames_escape_handler_acts_on_what_is_open_and_clears_a_keyboard_selection_never_a_pointer_hover(tmp_path):
    """Findings 3 and 4 of the review of PR 252: the handler as wired in the frame (the real frame and the real engine under a fake document). A mouse
    resting over the scene is not a selection: the first Escape goes up. Only the outline the keyboard's focus put on a list row is cleared first."""
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
import { createFrame } from "@JS@/frame/frame.js";
import * as router from "@JS@/router.js";
const root = document.createElement("div");
const fr = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
const out = {};
const press = (init = {}) => {
  const ev = { key: "Escape", defaultPrevented: false, preventDefault() { ev.defaultPrevented = true; }, ...init };
  for (const fn of document.listeners.keydown) fn(ev);
  return ev.defaultPrevented;
};
const at = (hash) => { window.location.hash = hash; fr.setScreen(router.parse(hash), { projectName: "shop", projectId: A }); };
const none = () => [];
document.querySelectorAll = none;
document.querySelector = () => null;
document.activeElement = null;

// a field has the focus: nothing happens
at(`#/p/${A}/floor/marketing`);
document.activeElement = { tagName: "TEXTAREA" };
out.field = [press(), window.location.hash];
document.activeElement = null;
// a handler that already took the key
out.taken = [press({ defaultPrevented: true }), window.location.hash];
// a dialog: its `cancel` is dispatched as the browser does and it closes, unless it refuses; the page does not go up
let events = [], closed = 0, refuse = false;
const dialog = { dispatchEvent(ev) { events.push(ev.type); if (refuse) ev.preventDefault(); }, close() { closed += 1; } };
document.querySelectorAll = (sel) => (String(sel).startsWith("dialog") ? [dialog] : []);
out.dialog = [press(), events.slice(), closed, window.location.hash];
refuse = true;
out.dialogRefused = [press(), events.length, closed, window.location.hash];
document.querySelectorAll = none;
// the request list is open: Escape closes it (the chip is clicked, as a person would), the page stays
let chipClicks = 0;
document.querySelector = (sel) => (sel === ".wb-req-menu:not([hidden])" ? {} : String(sel).startsWith(".wb-req-chip") ? { click() { chipClicks += 1; } } : null);
out.menu = [press(), chipClicks, window.location.hash];
document.querySelector = () => null;
// the Control room returns to the screen it was opened from
at(`#/p/${A}/floor/marketing`);
at(`#/p/${A}/control`);
out.controlFloor = [press(), window.location.hash];
at(`#/p/${A}`);
at(`#/p/${A}/control/costs`);
out.controlBuilding = [press(), window.location.hash];
at(`#/p/${A}/control`);                      // opened with no screen before it of that project: the Building
out.controlDirect = [press(), window.location.hash];
// the Lobby goes up to the Building too
at(`#/p/${A}/lobby`);
out.lobby = [press(), window.location.hash];
// the scene: a pointer hover is not a selection
const engine = fr.acquireWorld({ getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {}, onUnavailable() {} });
engine.show("world", models.city(), "City");
at(`#/p/${A}`);
engine.show("world", models.building(null), "Building");
engine.highlight(`floor:engineering`, "pointer");
out.pointer = [engine.hasHover(), engine.hasSelection(), press(), window.location.hash];
at(`#/p/${A}`);
engine.highlight(`floor:engineering`, "keyboard");
out.keyboardFirst = [engine.hasSelection(), press(), window.location.hash, engine.hasHover()];
out.keyboardSecond = [press(), window.location.hash];
// a keyboard selection that the pointer then left alone: the pointer's outline replaces it, the first Escape goes up
at(`#/p/${A}`);
engine.highlight(`floor:engineering`, "keyboard");
engine.highlight(`floor:design`, "pointer");
out.replaced = [engine.hasSelection(), press(), window.location.hash];
console.log(JSON.stringify(out));
""")
    a = "aaaaaaaaaaaa"
    assert got["field"] == [False, f"#/p/{a}/floor/marketing"], "a field has the focus: Escape does nothing and the key is left to the field"
    assert got["taken"] == [True, f"#/p/{a}/floor/marketing"], "a key another handler already took is not acted on again"
    assert got["dialog"] == [True, ["cancel"], 1, f"#/p/{a}/floor/marketing"], "a dialog gets its cancel event and closes; the page stays"
    assert got["dialogRefused"] == [True, 2, 1, f"#/p/{a}/floor/marketing"], "a dialog that refuses to be cancelled (a request in flight) stays open"
    assert got["menu"] == [True, 1, f"#/p/{a}/floor/marketing"], "an open request list closes by its own chip; the page stays"
    assert got["controlFloor"] == [True, f"#/p/{a}/floor/marketing"], "the Control room goes back to the Floor it was opened from"
    assert got["controlBuilding"] == [True, f"#/p/{a}"], "or to the Building"
    assert got["controlDirect"] == [True, f"#/p/{a}"], "and with nothing before it, to the Building of its project"
    assert got["lobby"] == [True, f"#/p/{a}"], "the Lobby goes up to the Building"
    assert got["pointer"] == [True, False, True, "#/city"], "a pointer hover over the scene is not a selection: the first Escape goes up"
    assert got["keyboardFirst"] == [True, True, f"#/p/{a}", False], "the outline the keyboard's focus put on a row is cleared first, and the page stays"
    assert got["keyboardSecond"] == [True, "#/city"], "the next Escape goes up"
    assert got["replaced"] == [False, True, "#/city"], "a keyboard selection the pointer's outline replaced is no selection: the first Escape goes up"

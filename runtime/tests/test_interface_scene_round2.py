"""Tests of the scene's second round (WP-9.10): the pick, the tooltip and the outline name the same object everywhere (sampled at the
drawn centre of each object with the page's own camera), the outline follows the object's own geometry, the Building has no Control
room button over the floors, the prototype's motion functions, the desktop plates and the phone's card.

No browser and no model: the pure modules run under Node when it is installed (the builders with the real three.js, no WebGL); what
only a browser can show was looked at in the browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_round2.py
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import standin_tree as st
from test_interface_floor import FAKE_DOM
from test_interface_scene_round3 import WORLD_JS
from interface_css import interface_css

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


# --- the pick, the tooltip and the outline name the same object ------------------------------------------------------------------

SAMPLING = WORLD_JS + r"""
import { fitFrustum } from "@JS@/scene/fit.js";
import { createCamera, boundsOfBox, contentBounds } from "@JS@/scene/rig.js";
import { pickHit, pickList, visibleSamples } from "@JS@/scene/pick.js";
import { outlineGeometry } from "@JS@/scene/outline.js";
import { pointerToNdc } from "@JS@/scene/camera.js";
import { buildServer } from "@JS@/views/control-scene.js";
import { sceneModel as serverModel } from "@JS@/views/control-model.js";

// a canvas that is only a box on the page: the pointer is mapped by its CSS box, as the engine does
const canvasBox = (w, h, left, top) => ({ left, top, width: w, height: h });

const states = (state) => lot("a", { floors: lot("a").floors.map((f) => (f.name === "business" ? { ...f, state } : f)) });
const roomWords = { tips: { agent: "tip agent", desk: "tip desk", tray: "tip tray" }, board: { title: "t", lines: ["x"], dot: "theme" }, door: false };
const world = (m, floor = null, instant = true) => (kit) => {
  const w = buildWorld(kit, m);
  w.setFocus(m.focus, instant);
  w.update(m);
  if (floor) w.setFloors(floor, null, instant);
  return w;
};
function scenes() {
  return [
    ["city", world(model())],
    ["building", world(model({ focus: "a", lots: [lot("a", { tag: { floor: "design", text: "#1" } }), lot("b"), lot("c")] }))],
    ["floor-working", world(model({ focus: "a", floor: "business", room: roomWords, lots: [states("working"), lot("b"), lot("c")] }), "business")],
    ["floor-waiting", world(model({ focus: "a", floor: "business", room: roomWords, lots: [states("waiting"), lot("b"), lot("c")] }), "business")],
    ["lobby", world(model({ focus: "a", floor: "planning", room: { ...roomWords, door: true }, lots: [lot("a"), lot("b"), lot("c")] }), "planning")],
    ["floor-off", world(model({ focus: "a", floor: "business", room: roomWords, lots: [states("off"), lot("b"), lot("c")] }), "business")],
    ["control", (kit) => buildServer(kit, serverModel({ accepted: true, connections: null, costs: null }))],
  ];
}

// the engine's own pick: the pointer to NDC by the canvas's CSS box, then pick.js
function enginePick(camera, hits, list, rect, x, y) {
  const ndc = pointerToNdc(rect.left + x, rect.top + y, rect);
  return pickHit(new THREE.Raycaster(), camera, hits, new THREE.Vector2(ndc.x, ndc.y), list);
}
// what the page used before: every child of the pickable groups, lines included, at three.js's default threshold of one unit
function legacyPick(camera, hits, rect, x, y) {
  const ndc = pointerToNdc(rect.left + x, rect.top + y, rect);
  const rc = new THREE.Raycaster();
  rc.setFromCamera(new THREE.Vector2(ndc.x, ndc.y), camera);
  const objects = hits.map((h) => h.object);
  const found = rc.intersectObjects(objects, true);
  if (!found.length) return null;
  let o = found[0].object;
  while (o && !objects.includes(o)) o = o.parent;
  return hits.find((h) => h.object === o) || null;
}

const out = {};
for (const [width, height, left, top] of [[1280, 720, 0, 0], [375, 520, 13, 90]]) {
  for (const [name, build] of scenes()) {
    const kit = createKit(palette);
    const scene = new THREE.Scene();
    const content = build(kit);
    scene.add(content.group);
    const camera = createCamera(THREE);
    const bounds = content.subject ? boundsOfBox(THREE, camera, content.subject()) : contentBounds(THREE, camera, content.group);
    const f = fitFrustum(bounds, { w: width, h: height }, { left: 0, right: 0, top: 0, bottom: 0 }, 1.04);
    Object.assign(camera, { left: f.left, right: f.right, top: f.top, bottom: f.bottom });
    camera.updateProjectionMatrix();
    scene.updateMatrixWorld(true);
    const rect = canvasBox(width, height, left, top);
    const hits = content.hits;
    const list = pickList(hits);
    const samples = visibleSamples(THREE, camera, scene, hits, { w: width, h: height });
    const result = { hits: hits.map((h) => h.id), samples: samples.length, wrongPick: [], wrongLegacy: 0, outlineOff: [], idsWithoutSample: [], tipsMissing: [] };
    for (const hit of hits) {
      if (!samples.some((s) => s.id === hit.id)) result.idsWithoutSample.push(hit.id);
      if (!hit.tip) result.tipsMissing.push(hit.id);
    }
    for (const s of samples) {
      const got = enginePick(camera, hits, list, rect, s.x, s.y);
      if (!got || got.id !== s.id) result.wrongPick.push([s.id, s.kind, got ? got.id : null]);
      const old = legacyPick(camera, hits, rect, s.x, s.y);
      if (!old || old.id !== s.id) result.wrongLegacy += 1;
      // the outline of the picked object stands on that object: it holds the sample point on the screen and stays within the object's own bounds
      const hit = hits.find((h) => h.id === s.id);
      // R-28 and R-31: an object of a room is marked by corner brackets (hit.marks: a hidden group of one mesh, shown by the engine), not by an outline
      if (hit.marks) {
        if (hit.marks.visible !== false || !hit.marks.children.length) result.outlineOff.push([s.id, s.kind, "marks", hit.marks.visible]);
        continue;
      }
      const pad = hit.pad !== undefined ? hit.pad : 0.04;
      const geometry = outlineGeometry(THREE, hit.outline || hit.object, pad);
      geometry.computeBoundingBox();
      const lineBox = geometry.boundingBox;
      const objectBox = new THREE.Box3().setFromObject(hit.object).expandByScalar(pad * 1.5 + 1e-3);
      const inside = objectBox.containsBox(lineBox);
      const corners = [];
      for (const x of [lineBox.min.x, lineBox.max.x]) for (const y of [lineBox.min.y, lineBox.max.y]) for (const z of [lineBox.min.z, lineBox.max.z]) {
        const v = new THREE.Vector3(x, y, z).project(camera);
        corners.push([((v.x + 1) / 2) * width, ((1 - v.y) / 2) * height]);
      }
      const x0 = Math.min(...corners.map((p) => p[0])) - 0.5, x1 = Math.max(...corners.map((p) => p[0])) + 0.5;
      const y0 = Math.min(...corners.map((p) => p[1])) - 0.5, y1 = Math.max(...corners.map((p) => p[1])) + 0.5;
      const covers = s.x >= x0 && s.x <= x1 && s.y >= y0 && s.y <= y1;
      if (!inside || (s.shell && !covers) || geometry.getAttribute("position").count === 0) result.outlineOff.push([s.id, s.kind, inside, covers]);
      geometry.dispose();
    }
    out[`${name}@${width}`] = result;
    kit.dispose();
  }
}
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_pick_the_tooltip_and_the_outline_name_the_object_at_its_drawn_centre_in_every_scene(tmp_path):
    got = run_node(tmp_path, SAMPLING)
    assert len(got) == 14, "seven scenes at two canvas sizes (one of them offset on the page)"
    for name, r in got.items():
        assert r["samples"] >= len(r["hits"]), f"{name}: every object has a point on it that is drawn ({r['samples']} samples for {r['hits']})"
        assert r["idsWithoutSample"] == [], f"{name}: an object that no point of the screen reaches: {r['idsWithoutSample']}"
        assert r["wrongPick"] == [], f"{name}: the pointer on an object's drawn centre picked another one: {r['wrongPick']}"
        assert r["outlineOff"] == [], f"{name}: the outline is not on the object it names: {r['outlineOff']}"
        assert r["tipsMissing"] == [], f"{name}: an object without its tooltip: {r['tipsMissing']}"
    # the page's old pick (every child of the group, the edge lines at a threshold of one unit) was wrong in the Control room while it drew edge lines. The rooms of round 4 draw
    # none (R-23: batches; R-51: the server room too), so the old pick agrees there now; the rule that a line is never pickable is tested on a group that has lines in
    # `test_interface_scene_r4_server.py` (the cause this assertion was written for)
    assert got["control@1280"]["wrongLegacy"] == 0, "R-51: the Control room has no edge line left, so the old pick no longer fails there"


def test_the_engine_picks_meshes_only_through_pick_js_and_the_outline_comes_from_outline_js():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "pickHit(raycaster, camera, content.hits" in engine and "outlineGeometry(THREE, hit.outline || hit.object" in engine
    assert "intersectObjects(objects, true)" not in engine, "no recursive ray over the groups: their edge lines would be hit"
    assert "Box3().setFromObject(hit.object).expandByScalar" not in engine, "no padded bounding box as an outline"
    pick = (SCENE / "pick.js").read_text(encoding="utf-8")
    assert "intersectObjects(list.meshes, false)" in pick and "isMesh" in pick, "meshes only: a line is never pickable"
    rig = (SCENE / "rig.js").read_text(encoding="utf-8")
    assert "createCamera" in engine and "export function createCamera" in rig, "the engine and the test look through the same camera"


# --- the prototype's motion code -----------------------------------------------------------------------------------------------------

PROTOTYPE = r"""
import { approach, createApproach, frameSeconds, smooth, lerp, beaconPulse, CAMERA_RATE, EXPLODE_RATE, MAX_DT } from "@JS@/scene/prototype-motion.js";
import { createTween } from "@JS@/scene/tween.js";
import { moveFrustum } from "@JS@/scene/fit.js";
import { pulseBeacon } from "@JS@/scene/city.js";

const out = {};
// the prototype's own loop for the camera, line for line: k = 1 - exp(-dt * 4.5); cam.zoom = lerp(cam.zoom, goal.zoom, k); the target the same
const centre = (f) => ({ x: (f.left + f.right) / 2, y: (f.top + f.bottom) / 2, zoom: 2 / (f.right - f.left), aspect: (f.top - f.bottom) / (f.right - f.left) });
const a = { left: -20, right: 20, top: 11.25, bottom: -11.25 };
const b = { left: 3, right: 9, top: 4.375, bottom: -0.625 };
const g = centre(b);
const cam = centre(a);
const tween = createTween();
tween.start(a, b, 0);
let now = 0;
let worst = 0;
let frames = 0;
let landed = null;
for (let i = 0; i < 200 && tween.active(); i++) {
  now += 1000 / 60;
  const dt = Math.min(0.05, 1 / 60);
  const k = 1 - Math.exp(-dt * 4.5);
  cam.zoom = lerp(cam.zoom, g.zoom, k); cam.x = lerp(cam.x, g.x, k); cam.y = lerp(cam.y, g.y, k); cam.aspect = lerp(cam.aspect, g.aspect, k);
  const f = tween.step(now);
  const mine = centre(f);
  frames += 1;
  worst = Math.max(worst, Math.abs(mine.zoom - cam.zoom) / Math.abs(g.zoom - centre(a).zoom), Math.abs(mine.x - cam.x) / Math.abs(g.x - centre(a).x), Math.abs(mine.y - cam.y) / Math.abs(g.y - centre(a).y));
  landed = f;
}
out.camera = { worst, seconds: frames / 60, landed: [landed.left, landed.right, landed.top, landed.bottom] };

// the way the camera is interpolated: the zoom moves in a straight line, not the frustum's sides
const mid = moveFrustum(a, b, 0.5);
out.zoomLinear = Math.abs(centre(mid).zoom - (centre(a).zoom + centre(b).zoom) / 2) < 1e-9;
out.sidesNot = Math.abs(mid.right - mid.left - ((a.right - a.left) + (b.right - b.left)) / 2) > 1;

// frame-rate independent: the same progress after the same time at 60 and at 30 frames a second, and a slow frame counts for at most 50 ms
const at = (fps, seconds) => { const m = createApproach(CAMERA_RATE); let p = 0; for (let i = 0; i < Math.round(seconds * fps); i++) p = m.step(1 / fps); return p; };
out.fps = [at(60, 0.5), at(30, 0.5), at(120, 0.5), 1 - Math.exp(-4.5 * 0.5)];
out.clamp = [frameSeconds(1000, 0), frameSeconds(16, 0), frameSeconds(0, 100)];
out.rates = [CAMERA_RATE, EXPLODE_RATE, MAX_DT];
const opening = createApproach(EXPLODE_RATE); let n = 0; while (!opening.done() && n < 1000) { opening.step(1 / 60); n += 1; }
out.openingSeconds = n / 60;
out.smooth = [smooth(0), smooth(0.5), smooth(1), smooth(0.25)];
out.approach = approach(0, 1, 0.1, 4.5);

// the beacon
const ring = { scale: { x: 1, y: 1, z: 1, set(x, y, z) { this.x = x; this.y = y; this.z = z; } } };
const mat = { opacity: 1 };
pulseBeacon({ ring, material: mat }, Math.PI / 6);
out.beacon = [ring.scale.x, ring.scale.z, mat.opacity, beaconPulse(Math.PI / 6).scale, beaconPulse(Math.PI / 6).opacity];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_camera_moves_as_the_prototypes_loop_does_frame_by_frame_and_lands_exactly_on_its_goal(tmp_path):
    got = run_node(tmp_path, PROTOTYPE)
    cam = got["camera"]
    assert cam["worst"] < 0.0105, "the product's camera follows the prototype's per-frame loop within one percent of the move, frame by frame (it only ends sooner or later than the prototype's, which never ends)"
    assert 1.0 < cam["seconds"] < 2.5, "and ends when what is left is under a quarter of a pixel (WP-9.11: a landing at one percent left a jump of several pixels): about 1.7 s in a 1280 px view, the last second of it too small to see"
    assert [round(x, 9) for x in cam["landed"]] == [3, 9, 4.375, -0.625], "it lands exactly on its goal"
    assert got["zoomLinear"] is True and got["sidesNot"] is True, "the zoom (the reciprocal of the half width) is moved in a straight line, as `cam.zoom` was, not the frustum's sides"
    assert abs(got["fps"][0] - got["fps"][3]) < 1e-9 and abs(got["fps"][1] - got["fps"][3]) < 1e-9 and abs(got["fps"][2] - got["fps"][3]) < 1e-9, "the same progress at 30, 60 and 120 frames a second"
    assert got["clamp"] == [0.05, 0.016, 0], "a slow frame counts for at most 50 ms, as the prototype's loop did"
    assert got["rates"] == [4.5, 3.2, 0.05]
    assert 1.4 < got["openingSeconds"] < 1.5, "the building opens in ln(100) / 3.2 = 1.44 s"
    assert got["smooth"] == [0, 0.5, 1, 0.15625] and abs(got["approach"] - (1 - 2.718281828459045 ** -0.45)) < 1e-12


@needs_node
def test_the_beacon_is_the_prototypes_function(tmp_path):
    # R-24 and R-41: the working figure's pose (forearms, bob, turn, the screen's flip) went with the figure; the owl's motions are owl-motion.js
    got = run_node(tmp_path, PROTOTYPE)
    scale, flat, opacity, pulse_scale, pulse_opacity = got["beacon"]
    assert scale == pulse_scale and flat == 1 and opacity == pulse_opacity, "the City's beacon is prototype-motion's `beaconPulse`"


def test_the_product_calls_the_prototypes_functions_and_keeps_the_rules_around_them():
    motion = (SCENE / "prototype-motion.js").read_text(encoding="utf-8")
    for line in ("Math.exp(-dt * rate)", "t * t * (3 - 2 * t)", "CAMERA_RATE = 4.5", "EXPLODE_RATE = 3.2", "MAX_DT = 0.05", "BEACON_RATE = 3"):
        assert line in motion, f"the prototype's line: {line}"
    assert "document" not in motion and "import" not in motion, "pure: no page, no three.js"
    tween = (SCENE / "tween.js").read_text(encoding="utf-8")
    assert "approach(cur[key], goal[key], dt, CAMERA_RATE)" in tween and "frameSeconds(now, current.last)" in tween
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    world = (SCENE / "world.js").read_text(encoding="utf-8")
    assert "approach(tower.open, tower.target, dt, EXPLODE_RATE)" in world and "approach(v, tower.visTarget[i], dt, VIS_RATE)" in world
    assert 'loop.start("beacon", { ambient: true })' in engine and 'loop.start("camera", { ambient: false })' in engine, "the owl and the beacon stay at 30 frames a second, a camera move runs every frame"
    for forbidden in ("Math.random", "spark", "particle"):
        assert forbidden not in motion + (SCENE / "owl-motion.js").read_text(encoding="utf-8")


# --- the Building: no Control room label over the floors; plates on the desktop, the card on the phone ------------------------------

PLATES = WORLD_JS + r"""
import { cornerPosition } from "@JS@/scene/labels.js";

const { world } = make({ focus: "a" });
world.setFocus("a", true);
const open = world.text(model({ focus: "a" })).labels.map((l) => [l.id, l.kind, l.place || null]);
const phone = world.text(model({ focus: "a", frame: "business" })).labels.map((l) => [l.id, l.kind, l.place || null]);
const out = { open, phone };
out.hasDoor = world.hits.some((h) => h.id === "door");
// a plate rides along while the floors separate
const tower = world.towers.get("a");
tower.open = 0; tower.apply(); const closed = tower.plateAnchors[1].y;
tower.open = 1; tower.apply(); out.rides = tower.plateAnchors[1].y > closed;
out.corner = [cornerPosition({ w: 375, h: 300 }, { right: 70, top: 80, cornerRight: 10 }), cornerPosition({ w: 800, h: 600 }, { right: 300, top: 64 })];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_building_has_a_plate_for_each_floor_and_no_control_room_label_and_the_phone_has_the_card_in_the_corner(tmp_path):
    got = run_node(tmp_path, PLATES)
    assert got["open"] == [["floor:planning", "plate", "column"], ["floor:business", "plate", "column"], ["floor:design", "plate", "column"], ["floor:engineering", "plate", "column"]], \
        "the plates stack beside the floors (desktop and tablet); there is no door label over the floors"
    assert got["phone"] == [], "the phone shows one floor and no plate: its card is the page's, in the corner"
    assert got["hasDoor"] is True, "the 3D door is still there and still opens the Control room"
    assert got["rides"] is True, "a plate follows its floor while the floors separate"
    assert got["corner"][0] == {"x": 365, "y": 80} and got["corner"][1] == {"x": 500, "y": 64}, \
        "the phone's card sits 10 px from the scene's right edge whatever the fit leaves for the stepper; without that field the panels' inset is used"
    scene = (SCENE / "world.js").read_text(encoding="utf-8")
    assert scene.count('id: "door-label"') == 1 and "if (room.door)" in scene, "the Control room label is drawn in the Lobby's room only"
    css = interface_css()
    assert ".wb-plate {" in css and ".wb-plate.is-tiny" in css and ".wb-plate.is-compact" not in css and "--wb-plate-w: 276px" in css, \
        "the desktop plates' styles (R-25: one size, 276 px as the page draws it; the name row alone is the only short form, no compact one)"
    assert re.search(r"@media \(max-width: 899px\)[^@]*?\.wb-floor-steps", css, re.S) and ".wb-plate { top: auto" not in css, "the phone has no docked plate"
    view = (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert "cornerRight: 10" in view and "plateRight: base.right" in view and "frame.plateWidth()" in view
    assert "pointerover" in view and '.wb-plate' in view, "hovering a plate outlines its floor, a click opens it (as before WP-9.8)"
    assert 'function highlightRow(name, fromScene = false, source = "pointer")' in view and "if (engine && (!fromScene || hover !== name))" in view and ", true, how" in view, \
        "a hover that came from the scene does not tell the engine what it drew itself: hovering the door (no floor) used to clear the outline the pick had just drawn (R4-A3: it is told only when the focus's floor should come back)"


# --- review fixes: the phone card's room --------------------------------------------------------------------------------------------------

INSETS = r"""
import { fitInsets, cornerPosition } from "@JS@/scene/labels.js";
const out = {};
// the phone's card: the scene is fitted below it
out.insets = [fitInsets({ top: 80, right: 70, cornerRight: 10 }, 78, 8), fitInsets({ top: 80, right: 70, cornerRight: 10 }, 0), fitInsets({ top: 64, right: 300 }, 90), fitInsets(undefined, 50)];
out.corner = cornerPosition({ w: 375, h: 300 }, { top: 80, right: 70, cornerRight: 10 });
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_phone_scene_is_fitted_below_the_corner_card_and_only_there(tmp_path):
    got = run_node(tmp_path, INSETS)
    assert got["insets"][0] == {"top": 166, "right": 70, "cornerRight": 10}, "card height 78 + 8 gap added under the card's top inset"
    assert got["insets"][1] == {"top": 80, "right": 70, "cornerRight": 10}, "no card, nothing added"
    assert got["insets"][2] == {"top": 64, "right": 300} and got["insets"][3] == {}, "desktop and tablet (no corner inset) are fitted as before"
    assert got["corner"] == {"x": 365, "y": 80}
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "fitInsets(insets, corner ? corner.offsetHeight : 0)" in engine and "      fit();   // the scene is fitted below the card" in engine, "the card is measured and the scene refitted when it is put in or taken out"

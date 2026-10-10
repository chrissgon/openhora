"""Tests of the scene after the maintainer's review (WP-9.8): the prototype's motion, outlines only on hover or selection, grey windows
lit when the agent works, the person's zoom and pan with limits, the pointer's hit-test, one object per destination in a room, no
rebuild on a poll that changed only words, the request selector of the tracking bar and the compact floor card.

No browser and no model: the pure modules run under Node when it is installed (the builders with the real three.js, no WebGL), and
what only a browser can show was looked at in the browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_feedback.py
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
    done = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


# --- the person's camera: zoom and pan with limits ------------------------------------------------------------------------------

CAMERA = r"""
import { MIN_ZOOM, MAX_ZOOM, DRAG_PX, IDENTITY, fitView, isDrag, frustumOf, clampView, zoomAt, panBy, panPixels, wheelFactor, keyAction, pointerToNdc } from "@JS@/scene/camera.js";

const fitted = { left: -20, right: 20, top: 11.25, bottom: -11.25 };   // 40 x 22.5
const bounds = { x0: -10, x1: 10, y0: -5, y1: 5 };                      // the diorama: 20 x 10
const out = {};
const size = (f) => [f.right - f.left, f.top - f.bottom];
const inView = (v) => { const f = frustumOf(fitted, v); return { x: Math.min(f.right, bounds.x1) - Math.max(f.left, bounds.x0), y: Math.min(f.top, bounds.y1) - Math.max(f.bottom, bounds.y0) }; };

out.limits = [MIN_ZOOM, MAX_ZOOM];
// the zoom is clamped between the whole diorama fitted and about three times that
let v = fitView();
for (let i = 0; i < 40; i++) v = zoomAt(v, fitted, bounds, 1.3);
out.zoomMax = v.zoom;
for (let i = 0; i < 40; i++) v = zoomAt(v, fitted, bounds, 1 / 1.3);
out.zoomMin = v.zoom;
out.fitSize = size(frustumOf(fitted, IDENTITY));
out.zoomedSize = size(frustumOf(fitted, { zoom: 2, x: 0, y: 0 }));
// zoom around the pointer keeps the point under it where it was
const ndc = { x: 0.5, y: -0.25 };
const before = frustumOf(fitted, IDENTITY);
const pointBefore = [(before.left + before.right) / 2 + ndc.x * (before.right - before.left) / 2, (before.top + before.bottom) / 2 + ndc.y * (before.top - before.bottom) / 2];
const z = zoomAt(IDENTITY, fitted, { x0: -100, x1: 100, y0: -100, y1: 100 }, 2, ndc);
const after = frustumOf(fitted, z);
const pointAfter = [(after.left + after.right) / 2 + ndc.x * (after.right - after.left) / 2, (after.top + after.bottom) / 2 + ndc.y * (after.top - after.bottom) / 2];
out.anchored = [Math.abs(pointBefore[0] - pointAfter[0]) < 1e-9, Math.abs(pointBefore[1] - pointAfter[1]) < 1e-9, z.zoom];
// the pan is clamped: the diorama's box stays at least half visible on each axis, whatever the drag
let p = { zoom: 1.5, x: 0, y: 0 };
for (const [dx, dy] of [[5000, 5000], [-5000, -5000], [5000, -5000], [-5000, 5000]]) {
  const far = panPixels(p, fitted, bounds, dx, dy, { w: 1000, h: 560 });
  const seen = inView(far);
  (out.panClamp ||= []).push([seen.x >= 0.5 * 20 - 1e-9, seen.y >= 0.5 * 10 - 1e-9]);
}
// when the view is narrower than half the box, the whole view stays inside the box
const deep = panPixels({ zoom: 3, x: 0, y: 0 }, fitted, bounds, 9000, 9000, { w: 1000, h: 560 });
const deepFrustum = frustumOf(fitted, deep);
out.deepInside = [deepFrustum.left >= bounds.x0 - 1e-9 || deepFrustum.right <= bounds.x1 + 1e-9, deepFrustum.top <= bounds.y1 + 1e-9 || deepFrustum.bottom >= bounds.y0 - 1e-9];
// a drag moves the scene with the pointer: dragging right moves the view left
const moved = panPixels({ zoom: 2, x: 0, y: 0 }, fitted, bounds, 100, 0, { w: 1000, h: 560 });
out.dragDirection = [moved.x < 0, moved.y === 0];
// keys and the wheel
out.keys = ["+", "=", "-", "_", "0", "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "a"].map((k) => keyAction(k));
out.wheel = [wheelFactor(-100) > 1, wheelFactor(100) < 1, wheelFactor(0) === 1, wheelFactor(-100, 1) > wheelFactor(-100), wheelFactor(-1e6) === wheelFactor(-400)];
// drag or click: a press that moves more than a few pixels is a pan
out.drag = [[0, 0], [3, 3], [DRAG_PX, 0], [4, 4], [6, 0], [0, -6]].map(([dx, dy]) => isDrag(dx, dy));
// fit restores the whole diorama
const wandered = panBy(zoomAt(IDENTITY, fitted, bounds, 2.5), fitted, bounds, 0.4, -0.3);
out.wandered = wandered.zoom > 1 && (wandered.x !== 0 || wandered.y !== 0);
out.fit = [fitView(), clampView(fitView(), fitted, bounds)];
// a resize keeps the person's zoom and offset while they are inside the limits, and brings them back when they no longer are
const kept = { zoom: 2, x: 2, y: 1 };
const resized = { left: -24, right: 24, top: 13.5, bottom: -13.5 };
out.keptOnResize = clampView(kept, resized, bounds);
out.pulledBackOnResize = clampView({ zoom: 2, x: 500, y: 0 }, resized, bounds).x < 500;
out.zoomClamped = [clampView({ zoom: 9, x: 0, y: 0 }, fitted, bounds).zoom, clampView({ zoom: 0.1, x: 0, y: 0 }, fitted, bounds).zoom, clampView({ zoom: NaN, x: 0, y: 0 }, fitted, bounds).zoom];
// pointer to normalised device coordinates: the canvas's CSS box, never its buffer, so a scaled canvas and any pixel ratio map the same
const rect = { left: 100, top: 50, width: 640, height: 360 };
out.ndc = [pointerToNdc(100, 50, rect), pointerToNdc(420, 230, rect), pointerToNdc(740, 410, rect), pointerToNdc(260, 140, rect)];
const doubled = { left: 100, top: 50, width: 640, height: 360, bufferWidth: 1280, bufferHeight: 720 };   // the buffer of a 2x display is not part of the mapping
out.ndcBuffer = pointerToNdc(420, 230, doubled);
console.log(JSON.stringify(out));
"""


@needs_node
def test_zoom_is_clamped_between_the_whole_diorama_and_three_times_that_and_zooms_around_the_pointer(tmp_path):
    got = run_node(tmp_path, CAMERA)
    assert got["limits"] == [1, 3]
    assert got["zoomMax"] == 3 and got["zoomMin"] == 1, "the wheel cannot go past the limits"
    assert got["fitSize"] == [40, 22.5] and got["zoomedSize"] == [20, 11.25], "zoom 2 shows half the width and height"
    assert got["anchored"] == [True, True, 2], "the point under the pointer stays where it was"
    assert got["zoomClamped"] == [3, 1, 1], "a zoom outside the limits (or not a number) is brought back"


@needs_node
def test_the_pan_never_lets_the_diorama_leave_the_view_and_a_drag_moves_the_scene_with_the_pointer(tmp_path):
    got = run_node(tmp_path, CAMERA)
    assert got["panClamp"] == [[True, True]] * 4, "at least half of the box stays visible on each axis, in every direction"
    assert got["deepInside"] == [True, True], "a view narrower than half the box stays inside the box"
    assert got["dragDirection"] == [True, True], "dragging right moves the view left, so the scene follows the pointer"


@needs_node
def test_a_press_that_moves_more_than_a_few_pixels_is_a_pan_not_a_click_and_fit_restores_the_whole_diorama(tmp_path):
    got = run_node(tmp_path, CAMERA)
    assert got["drag"] == [False, False, False, True, True, True], "up to 5 px is a click; beyond it a pan (the threshold is a distance, not an axis)"
    assert got["wandered"] is True and got["fit"] == [{"zoom": 1, "x": 0, "y": 0}, {"zoom": 1, "x": 0, "y": 0}], "fit is the whole diorama, no offset"
    assert got["keptOnResize"] == {"zoom": 2, "x": 2, "y": 1}, "a resize keeps the person's zoom and offset when they are inside the limits"
    assert got["pulledBackOnResize"] is True, "and brings an offset that is no longer inside them back"


@needs_node
def test_the_keys_and_the_wheel_of_the_camera_and_the_pointer_maps_to_the_canvas_by_its_css_box(tmp_path):
    got = run_node(tmp_path, CAMERA)
    assert got["keys"] == [{"zoom": 1.25}, {"zoom": 1.25}, {"zoom": 0.8}, {"zoom": 0.8}, {"fit": True}, {"pan": [0.1, 0]}, {"pan": [-0.1, 0]},
                           {"pan": [0, 0.1]}, {"pan": [0, -0.1]}, None]
    assert got["wheel"] == [True] * 5
    corner, centre, far, inner = got["ndc"]
    assert corner == {"x": -1, "y": 1} and centre == {"x": 0, "y": 0}, "the top left is (-1, 1), the middle is (0, 0)"
    assert far == {"x": 1, "y": -1} and inner == {"x": -0.5, "y": 0.5}, "a canvas scaled by CSS maps by its box"
    assert got["ndcBuffer"] == {"x": 0, "y": 0}, "the drawing buffer of a 2x display does not enter the mapping"


def test_the_engine_moves_the_camera_on_demand_only_and_offers_the_buttons_the_keys_the_wheel_the_pinch_and_the_double_click():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    for needle in ('"wheel", onWheel, { passive: false }', '"dblclick", onDoubleClick', '"keydown", onKeyDown', '"pointerdown", onDown',
                   'aria-label": label', "Zoom in", "Zoom out", "Fit the scene", "setPointerCapture", "createPointer("):
        assert needle in engine, f"engine.js has {needle}"
    pointer = (SCENE / "pointer.js").read_text(encoding="utf-8")
    assert "isDrag(" in pointer and "pinch" in pointer
    set_view = re.search(r"function setView\(next\) \{(.*?)\n  \}", engine, re.S).group(1)
    assert "loop.requestRender()" in set_view and "requestAnimationFrame" not in engine.replace("raf: (fn) => requestAnimationFrame(fn)", ""), \
        "a camera change asks for one frame; there is no loop for it"
    assert 'tabindex: "0"' in engine and 'role: "img"' in engine, "the canvas can have the focus for the keys"
    css = interface_css()
    assert "touch-action: none" in css and ".wb-camera-tools" in css and ".wb-canvas:focus-visible" in css
    for name in ("plus", "maximize", "minus"):
        assert (INTERFACE / "icons" / f"{name}.svg").is_file()
    assert not re.search(r"setInterval|setTimeout\(\s*(?:animate|draw|tick)", engine), "no timer drives the camera"


# --- windows ---------------------------------------------------------------------------------------------------------------------

WINDOWS = r"""
import { windowState, windowColour, windowUnlit } from "@JS@/scene/look.js";
import * as model from "@JS@/model.js";
import * as fm from "@JS@/floor-model.js";
import { roomModel } from "@JS@/views/lobby-model.js";

const palette = { warm: "WARM", windows: { lit: "WARM", grey: "BORDER" } };
const out = {};
out.state = [windowState(true), windowState(false)];
out.colour = [windowColour(palette, "lit"), windowColour(palette, "grey"), windowColour(palette, "pale"), windowColour(palette, "dark"), windowColour(palette, undefined)];
out.unlit = [windowUnlit("lit"), windowUnlit("grey"), windowUnlit("pale")];
// the City: only a floor whose agent has a running task is lit
const project = { id: "aaaaaaaaaaaa", name: "shop", config: { accepted: true }, running_task: 5, open_pending: 0 };
const agents = [{ name: "planning", enabled: true, acting_mode: "supervised" }, { name: "engineering", enabled: true, acting_mode: "autonomous" },
  { name: "design", enabled: false, acting_mode: "stopped" }, { name: "marketing", enabled: true, acting_mode: "milestones" }];
const status = { requests: [{ id: 1, title: "R", state: "ready", tasks: [{ id: 5, key: "a", title: "A", state: "running", agent: "engineering" }, { id: 6, key: "b", title: "B", state: "waiting", agent: "marketing" }] }], pending: [{ id: 9, task_id: 6, agent: "marketing", kind: "question", title: "q" }] };
const b = model.buildingOf(project, { status, agents });
out.city = b.floors.map((f) => [f.agent, f.window]);
const unaccepted = model.buildingOf({ ...project, config: { accepted: false } }, { status, agents });
out.cityUnaccepted = unaccepted.floors.map((f) => f.window);
// the Building and the Lobby's room
const view = fm.building({ projects: [project], details: { [project.id]: { status, agents: agents.map((a) => ({ ...a, mode: a.acting_mode, max_runs_per_day: 5, max_usd_per_day: 5, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0 })) } }, tasks: {}, loaded: true }, project.id);
out.building = view.rows.map((r) => [r.name, r.state, r.window]);
const lobby = (extra) => roomModel({ working: false, decisions: 0, hasMessages: true, accepted: true, request: null, ...extra }).window;
out.lobby = [lobby({ working: true }), lobby({ decisions: 2 }), lobby({}), lobby({ accepted: false })];
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_window_is_warm_when_its_agent_works_and_grey_in_every_other_state_and_there_is_no_pale(tmp_path):
    got = run_node(tmp_path, WINDOWS)
    assert got["state"] == ["lit", "grey"]
    assert got["colour"] == ["WARM", "BORDER", "BORDER", "BORDER", "BORDER"], "working -> the warm recipe; every other state, even an old word, the border tone"
    assert got["unlit"] == [True, False, False], "only a lit window is an unlit (self-lit) material"
    # R-21 (supersedes "lit only while a task runs"): lit means the agent is active, working or waiting for an answer; dark, resting or off
    assert got["city"] == [["planning", "grey"], ["engineering", "lit"], ["design", "grey"], ["marketing", "lit"]], "a waiting floor is lit; a stopped or idle floor is grey"
    assert got["cityUnaccepted"] == ["grey"] * 4
    assert got["building"] == [["planning", "idle", "grey"], ["engineering", "working", "lit"], ["design", "off", "grey"], ["marketing", "waiting", "lit"]]
    assert got["lobby"] == ["lit", "lit", "grey", "grey"], "the Lobby is lit while a turn runs or a decision waits (R-21)"
    palette = (SCENE / "palette.js").read_text(encoding="utf-8")
    assert re.search(r"palette\.windows = \{ lit: palette\.warm, grey: T\.border \};", palette), "the grey is the border token, the same recipe in light and in dark"
    for path in sorted(JS.rglob("*.js")):
        if "vendor" in path.parts or path.name == "three.js":
            continue
        assert not re.search(r"""["']pale["']""", path.read_text(encoding="utf-8")), f"{path.name} has no pale window state"


# --- outlines ----------------------------------------------------------------------------------------------------------------------

OUTLINES = WORLD_JS + r"""
import { outlineVisible, applyOutlineVisibility } from "@JS@/scene/look.js";
import { buildServer } from "@JS@/views/control-scene.js";
import { sceneModel as serverModel } from "@JS@/views/control-model.js";

const out = {};
out.rule = [outlineVisible("a", null), outlineVisible("a", "a"), outlineVisible("a", "b"), outlineVisible(null, null), outlineVisible(undefined, undefined)];
const visible = (built) => built.outlines.flatMap((o) => o.lines.map((l) => [o.id, l.visible]));
const { kit, world } = make();
// the City: no lot line stands; only the object the route selects shows its line
out.cityBuilt = visible(world).filter((x) => ["a", "b", "c"].includes(x[0]));
applyOutlineVisibility(world.outlines, world.selected);
out.cityNothing = visible(world).filter((x) => ["a", "b", "c"].includes(x[0]));
applyOutlineVisibility(world.outlines, "b");
out.cityRoute = visible(world).filter((x) => ["a", "b", "c"].includes(x[0]));
out.citySelected = world.selected;
out.brackets = world.brackets.map((b) => [b.id, b.group.visible]);
// a floor of the open building: its line is drawn only when the route selects the floor (the Floor, the Lobby)
world.setFocus("a", true);
world.setFloors("business", null, true);
applyOutlineVisibility(world.outlines, world.selected);
out.floorsNothing = visible(world).filter((x) => String(x[0]).startsWith("floor:")).every((x) => x[1] === false);
applyOutlineVisibility(world.outlines, "floor:business");
out.floorRoute = visible(world).filter((x) => x[1] === true);
out.floorLines = world.outlines.map((o) => o.id);
const server = buildServer(kit, serverModel({ accepted: true, connections: null, costs: null }));
applyOutlineVisibility(server.outlines, server.selected);
out.server = [visible(server), server.selected];
console.log(JSON.stringify(out));
"""


@needs_node
def test_no_outline_line_is_drawn_without_a_hover_or_a_selection_and_the_route_selects_the_floor(tmp_path):
    got = run_node(tmp_path, OUTLINES)
    assert got["rule"] == [False, True, False, False, False], "a line shows only for the object the route selected: a hovered object has its box, no lot or floor line"
    # R-17 supersedes the lot line: the City marks a building with eight corner brackets (world.brackets, hidden until the engine asks), no line
    assert got["cityBuilt"] == [] and got["cityNothing"] == [] and got["citySelected"] is None, "the City has no lot line and selects nothing by itself"
    assert got["cityRoute"] == [], "no lot line is made for a route to select"
    assert got["brackets"] == [["a", False], ["b", False], ["c", False]], "built hidden: no standing brackets"
    assert got["floorsNothing"] is True, "no floor line stands, not even for the work order's floor"
    # R-28 and R-31: a floor is marked by corner brackets (hit.marks, shown by the engine), and the room as a whole is not picked on the Floor: no floor line at all
    assert got["floorRoute"] == [] and got["floorLines"] == [], "a floor has no outline line, whatever the route selects: its corners are marked by brackets"
    # R-51 supersedes the room's outline in the theme colour: the Control room selects nothing by a line, its open tab's object wears corner brackets
    assert got["server"] == [[], None], "the Control room has no floor line: the object of the open tab is marked by brackets (R-51)"


def test_the_hover_outline_is_the_prototypes_thin_depth_tested_line_that_follows_a_shape_where_the_object_is_not_a_box():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "new THREE.LineBasicMaterial({ color: 0xffffff });" in engine, "a one-pixel line of the theme colour, full opacity, depth-tested (no depthTest: false, no renderOrder)"
    assert "depthTest: false" not in engine and "renderOrder" not in engine
    assert "OUTLINE_PAD = 0.04" in engine and "outlineGeometry(THREE, hit.outline || hit.object" in engine, "every outline is the edges of the object's own meshes (outline.js), OUTLINE_PAD off"
    outline = (SCENE / "outline.js").read_text(encoding="utf-8")
    assert "EdgesGeometry(mesh.geometry" in outline and "userData.shell" in outline, "the edges of the meshes, the shell's when the object marks one"
    assert "Box3().setFromObject(hit.object).expandByScalar" not in engine, "no padded bounding box"
    city = (SCENE / "city.js").read_text(encoding="utf-8")
    tower = (SCENE / "tower.js").read_text(encoding="utf-8")
    marks = (SCENE / "marks.js").read_text(encoding="utf-8")
    assert "group.visible = false" in marks and "brackets" in engine, "R-17: the brackets of a building are built hidden and shown by the engine for the followed or pointed building"
    assert "lot.runningTask !== null && lot.accepted" in tower, "the beacon ring exists only for a running task"
    motion = (SCENE / "prototype-motion.js").read_text(encoding="utf-8")
    assert "beaconPulse(seconds)" in city and "Math.sin(t * BEACON_RATE)" in motion and "BEACON_RATE = 3" in motion and "BEACON_SWING = 0.12" in motion and "0.35 + 0.3" in motion, \
        "the beacon is the prototype's: sin(3 t), scale 1 +- .12, opacity .35 to .65"


# --- one object per destination ------------------------------------------------------------------------------------------------------

HITS = WORLD_JS + r"""
const tips = { agent: "a", desk: "d", tray: "t" };
const out = {};
for (const [state, name, decisions] of [["working", "business", 0], ["waiting", "business", 0], ["waiting", "business", 2], ["idle", "planning", 0], ["off", "business", 0]]) {
  const { world, kit } = make();
  const m = model({ lots: [lot("a", { floors: [floor2("planning"), floor2("business", { state, decisions })] }), lot("b"), lot("c")], focus: "a", floor: name, room: { tips, board: { title: "t", lines: ["x"], dot: "theme" }, door: name === "planning" } });
  world.setFocus("a", true);
  world.update(m);
  world.setFloors(name, null, true);
  out[`${state}${decisions ? "+asks" : ""}@${name}`] = world.hits.map((h) => h.id);
  kit.dispose();
}
console.log(JSON.stringify(out));
function floor2(n, extra = {}) { return lot("a").floors.find((f) => f.name === "planning" && n === "planning") || { ...lot("a").floors[1], name: n, label: n, lobby: false, ...extra }; }
"""


@needs_node
def test_a_room_has_three_ways_in_the_owl_the_board_and_the_bookcase_and_the_lobby_a_door(tmp_path):
    # R-31 and R-23b supersede "one object for each destination": the figure, the tray, the desk and a sheet each are gone; the owl, the board of notes and the bookcase are
    # what the pointer picks on the Floor, and the Lobby's door beside them
    got = run_node(tmp_path, HITS)
    assert got["working@business"] == ["agent", "tasks", "desk"], "owl -> Agent, board -> Tasks, bookcase -> Desk"
    assert got["waiting@business"] == got["working@business"], "an owl that waits and has nothing open still opens the Agent tab"
    assert got["waiting+asks@business"] == ["tray", "tasks", "desk"], "the owl opens the Inbox when it asks something (R-31)"
    assert got["off@business"] == ["tasks", "desk"], "no owl, no agent hit: an agent that is off has the board and the bookcase"
    assert got["idle@planning"] == ["agent", "tasks", "desk", "lobby-door"], "the Lobby adds its door (R-42)"
    for ids in got.values():
        assert not any(i.startswith("sheet:") or i in ("cabinet", "board") for i in ids), "no sheet, no cabinet: a document is a binder of the bookcase, which opens the Desk"
    for name, tab_by_id in (("floor.js", {"tray": "inbox", "desk": "desk", "agent": "agent", "tasks": "tasks"}), ("lobby.js", {"tray": "inbox", "desk": "desk", "agent": "agent", "tasks": "tasks"})):
        text = (JS / "views" / name).read_text(encoding="utf-8")
        for hit, tab in tab_by_id.items():
            assert re.search(rf'id === "{hit}"\) window\.location\.hash = router\.\w+\((?:project, agent|project), "{tab}"\)', text), f"{name}: {hit} opens {tab}"
        assert '"cabinet"' not in text, f"{name} maps no click from the cabinet"


# --- no rebuild on a poll that changed only words -----------------------------------------------------------------------------------

REBUILD = r"""
import { showPlan } from "@JS@/scene/look.js";
import { BUILDERS } from "@JS@/scene/engine.js";
import "@JS@/views/control-scene.js";
import { sceneModel as serverModel } from "@JS@/views/control-model.js";

// a sequence of polls, as the engine's show() sees them: the plan each one gets
function sequence(kind, models) {
  const structureOf = (BUILDERS[kind] || {}).structure;
  let before = { signature: "", structure: "", built: false };
  return models.map((m) => {
    const plan = showPlan(before, kind, m, structureOf);
    if (plan.action !== "none") before = { signature: plan.signature, structure: plan.action === "build" ? plan.structure : before.structure, built: true };
    return plan.action;
  });
}
const out = {};
const conn = (found) => ({ classes: found.map((f, i) => ({ class: `c${i}`, provider: f ? "p" : null, found: f, note: null, skills: [] })), secrets: [], image: { name: "i", present: true, evidence: true }, platform: {} });
const srv = (found, extra = {}) => serverModel({ accepted: true, connections: conn(found), costs: null, ...extra });
out.server = sequence("server", [srv([true, false]), srv([true, false]), srv([true, false], { accepted: true }), srv([true, true]), srv([true, true])]);
out.unknownKind = sequence("nowhere", [{ a: 1 }, { a: 1 }, { a: 2 }]);
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_poll_that_found_the_same_state_does_not_build_the_control_room_again_and_the_world_changes_in_place(tmp_path):
    got = run_node(tmp_path, REBUILD)
    assert got["server"] == ["build", "none", "none", "build", "none"], "the Control room is built again only when an LED or a bar changes"
    assert got["unknownKind"] == ["build", "none", "build"], "a scene with no builder is its own structure"


def test_the_engine_never_restarts_a_motion_when_it_rebuilds_and_every_builder_that_labels_has_a_structure():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "const epoch = clock();" in engine and "(now - epoch) / 1000" in engine and "pulseStart" not in engine, "the ambient clock is the engine's, never reset by a rebuild"
    assert "showPlan(" in engine and "relabel();" in engine and "content.text(model)" in engine
    world = (SCENE / "world.js").read_text(encoding="utf-8")
    assert "buildWorld.structure = " in world and "content.text = (m) =>" in world and "content.update = (m) =>" in world, "world.js: the structure and the words are apart, a poll updates in place"
    for name in ("views/city.js", "views/building.js", "views/floor.js", "views/lobby-scene.js"):
        text = (JS / name).read_text(encoding="utf-8")
        assert "engine.show(" in text or "engine.show" in text, f"{name} shows the scene through the engine"


# --- the motions of the prototype ----------------------------------------------------------------------------------------------------

MOTION = r"""
import { pulseBeacon, restBeacon } from "@JS@/scene/city.js";
import { createTween } from "@JS@/scene/tween.js";

const out = {};
// the beacon: sin(3 t), scale 1 +- .12 in its plane only, opacity .35 to .65
const beacon = { ring: { scale: { x: 1, y: 1, z: 1, set(a, b, c) { this.x = a; this.y = b; this.z = c; } } }, material: { opacity: 1 } };
const samples = [];
for (let t = 0; t < 2.2; t += 0.01) { pulseBeacon(beacon, t); samples.push([beacon.ring.scale.x, beacon.ring.scale.z, beacon.material.opacity]); }
out.beacon = [Math.min(...samples.map((s) => s[0])), Math.max(...samples.map((s) => s[0])), samples.every((s) => s[1] === 1), Math.min(...samples.map((s) => s[2])), Math.max(...samples.map((s) => s[2]))];
out.period = Math.abs(Math.sin(2 * Math.PI / 3 * 3)) < 1e-9;
restBeacon(beacon);
out.beaconRest = [beacon.ring.scale.x, beacon.material.opacity];
// a move may settle early (the screen is opened while the camera is still on its way) and still runs to its end
const t = createTween();
const a = { left: 0, right: 10, top: 10, bottom: 0 }; const b = { left: 2, right: 6, top: 8, bottom: 4 };
const frames = (tween, from, count) => { let f = null; for (let i = 1; i <= count; i++) f = tween.step(from + i * 16) || f; return f; };
const settled = [];
const move = t.start(a, b, 0, 0.9); move.then((v) => settled.push(v));
frames(t, 0, 10); await new Promise((r) => setTimeout(r, 5)); out.early = [settled.slice(), t.active()];
frames(t, 160, 25); await new Promise((r) => setTimeout(r, 5)); out.atNine = [settled.slice(), t.active()];
const last = frames(t, 560, 80); out.end = [last.left, last.right, t.active()];
const cut = t.start(a, b, 0, 0.9); const cutSettled = []; cut.then((v) => cutSettled.push(v)); t.cancel(); await new Promise((r) => setTimeout(r, 5)); out.cut = cutSettled;
const late = t.start(a, b, 0, 0.9); const lateSettled = []; late.then((v) => lateSettled.push(v)); frames(t, 0, 60); t.cancel(); await new Promise((r) => setTimeout(r, 5)); out.lateCancel = lateSettled;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_motions_are_the_prototypes_numbers_the_beacon_is_a_sine_and_a_move_may_hand_over_early(tmp_path):
    # R-24 and R-41: the typing figure and the screen's scan line are gone with the figure (the owl's motions are owl-motion.js, tested in test_interface_scene_r4.py)
    got = run_node(tmp_path, MOTION)
    lo, hi, flat, olo, ohi = got["beacon"]
    assert abs(lo - 0.88) < 1e-3 and abs(hi - 1.12) < 1e-3 and flat is True, "scale 1 +- .12 in the ring's plane, the thickness stays"
    assert abs(olo - 0.35) < 1e-3 and abs(ohi - 0.65) < 1e-3 and got["period"] is True, "opacity .35 to .65, a cycle of 2 pi / 3 s"
    assert got["beaconRest"] == [1, 1]
    assert got["early"] == [[], True] and got["atNine"][0] == [True] and got["atNine"][1] is True, "settled when the move is nine tenths done, still moving"
    assert got["end"] == [2, 6, False], "the move runs to its end, exactly on its goal"
    assert got["cut"] == [False] and got["lateCancel"] == [True], "a cut before the hand-over settles false, after it stays true"


def test_the_state_animations_keep_the_rules_of_the_scene_and_the_owl_does_not_fidget():
    # R-41: the owl moves only with its state: the raised wing waves while it waits, the wings tap while it works, it breathes and the z rise while it is idle
    motion = (SCENE / "owl-motion.js").read_text(encoding="utf-8")
    build = (SCENE / "owl-build.js").read_text(encoding="utf-8")
    for fidget in ("Math.random", "spark", "blink", "nod"):
        assert fidget not in motion + build, f"the owl has no {fidget}: it moves only for the state it is in"
    assert 'if (pose === "waiting") turnOf("wave"' in build and 'if (pose === "working")' in build and 'if (pose === "idle")' in build, "each motion belongs to one pose"
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert re.search(r"export const CAMERA_MS = 1023;", engine) and "OPEN_MS = 1439" in engine and "FLY_SETTLE_AT = 0.9" in engine
    assert "content.step(frameSeconds(now, worldLast))" in engine and "positionLabels();   // the labels ride along with the camera" in engine and "positionLabels();   // the plates, the cards and the tag ride along with the floors" in engine, "the labels follow the camera and the opening instead of vanishing"
    assert 'loop.start("beacon", { ambient: true })' in engine, "typing and the beacon are ambient: held to 30 frames a second"
    assert "pulseStart = clock()" not in engine


# --- the request selector of the tracking bar -----------------------------------------------------------------------------------------

REQUESTS = r"""
import * as model from "@JS@/model.js";
import { FakeNode, find, all } from "@FAKE@";
import { createTrack } from "@JS@/frame/track.js";

const task = (id, state, agent = "engineering") => ({ id, key: `k${id}`, title: `Task ${id}`, state, agent });
const status = { requests: [
  { id: 1, title: "Old and done", state: "done", tasks: [task(1, "done")] },
  { id: 2, title: "Spring", state: "ready", tasks: [task(2, "done"), task(3, "running")] },
  { id: 3, title: "Fix cart", state: "ready", tasks: [task(4, "waiting")] },
  { id: 4, title: "Docs", state: "ready", tasks: [task(5, "ready")] },
  { id: 5, title: "Dropped", state: "cancelled", tasks: [] }], pending: [] };
const idle = { requests: [{ id: 7, title: "A", state: "ready", tasks: [task(8, "ready")] }, { id: 9, title: "B", state: "ready", tasks: [task(10, "waiting")] }], pending: [] };
const none = { requests: [{ id: 1, title: "x", state: "done", tasks: [] }], pending: [] };
const out = {};
model.resetRequestChoices();
out.open = model.openRequests(status).map((r) => r.id);
out.defaultRunning = model.pickRequest(status).id;          // the newest with a running task, not the newest open (4)
out.defaultNewest = model.pickRequest(idle).id;             // no running task: the newest open
out.defaultNone = [model.pickRequest(none), model.pickRequest({ requests: [] }), model.pickRequest(null)];
out.chosen = model.pickRequest(status, 3).id;
out.choiceGone = model.pickRequest(status, 1).id;           // a request that is done is no choice: back to the default
out.cycle = [model.cycleRequest(status, 4, 1).id, model.cycleRequest(status, 3, 1).id, model.cycleRequest(status, 2, 1).id, model.cycleRequest(status, 4, -1).id, model.cycleRequest(status, 2, -1).id, model.cycleRequest(status, 99, 1).id, model.cycleRequest(none, 1, 1)];
// the choice is kept for each project, in memory, and forgotten with a new session
model.chooseRequest("p1", 3);
out.kept = [model.requestChoice("p1"), model.requestChoice("p2")];
model.resetRequestChoices();
out.forgotten = model.requestChoice("p1");

const snapshot = (c) => ({ projects: [{ id: "p1", name: "shop", config: { accepted: true }, running_task: 3 }], details: { p1: { status, agents: [{ name: "engineering", enabled: true }] } }, tasks: {}, loaded: true, ...c });
const bar = (choice) => { model.resetRequestChoices(); if (choice) model.chooseRequest("p1", choice); return model.tracking(snapshot(), "p1", new Date("2026-10-08T12:00:00Z")); };
const def = bar(null); const picked = bar(3);
out.tracking = [def.request.id, def.requests.map((r) => [r.id, r.selected, r.running]), def.now.title, picked.request.id, picked.steps.map((s) => s.title), picked.now.title, picked.now.state];
out.needed = (() => { model.resetRequestChoices(); const a = model.neededTasks(snapshot().projects, snapshot().details, "p1").map((t) => t.id); model.chooseRequest("p1", 3); const b = model.neededTasks(snapshot().projects, snapshot().details, "p1").map((t) => t.id); return [a, b]; })();
model.resetRequestChoices();

// the bar: one open request is a plain badge; several are a chip with a list and the two buttons; none hides the bar
const chosen = [];
const track = createTrack({ onOpenSteps() {}, onSelectRequest: (p, id) => chosen.push([p, id]) });
document.activeElement = null;
FakeNode.prototype.getBoundingClientRect = () => ({ left: 10, top: 500 });
track.set(def, "ready");
out.barShown = !track.el.hidden;
const chip = find(track.el, ".wb-req-chip");
out.selectorParts = [Boolean(chip), all(track.el, ".wb-track-desktop .wb-req-step").map((b) => b.attrs["aria-label"]), all(track.el, ".wb-track-desktop .wb-req-option").map((o) => [o.attrs["data-request"], o.attrs["aria-selected"]]), chip.attrs["aria-expanded"], find(track.el, ".wb-req-menu").hidden];
chip.click();
out.opened = [chip.attrs["aria-expanded"], find(track.el, ".wb-req-menu").hidden];
all(track.el, ".wb-track-desktop .wb-req-option")[1].click();
out.chose = [chosen.slice(), chip.attrs["aria-expanded"]];
const steps = all(track.el, ".wb-track-desktop .wb-req-step");
steps[0].click(); steps[1].click();
out.stepped = chosen.slice(1);
const single = { ...def, requests: [def.requests[0]] };
track.set(single, "ready");
out.single = [Boolean(find(track.el, ".wb-req-chip")), Boolean(find(track.el, ".wb-req-id"))];
track.set(null, "empty");
out.emptyHidden = track.el.hidden;
track.set(null, "loading");
out.loadingShown = !track.el.hidden;
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_bar_shows_the_newest_request_with_a_running_task_else_the_newest_open_one_and_the_choice_is_kept_per_project(tmp_path):
    got = run_node(tmp_path, REQUESTS)
    assert got["open"] == [4, 3, 2], "the open requests, newest first (done and cancelled are not open)"
    assert got["defaultRunning"] == 2, "the newest request that has a running task, even when a newer one is open"
    assert got["defaultNewest"] == 9 and got["defaultNone"] == [None, None, None]
    assert got["chosen"] == 3 and got["choiceGone"] == 2, "a choice holds while that request is open"
    assert got["cycle"] == [3, 2, 4, 2, 3, 4, None], "next goes to the older one, previous to the newer one, and both wrap round"
    assert got["kept"] == [3, None] and got["forgotten"] is None, "in memory, for each project, forgotten with the session"
    track = got["tracking"]
    assert track[:3] == [2, [[4, False, False], [3, False, False], [2, True, True]], "Task 3"], "the bar and Now on follow the default request"
    assert track[3:] == [3, ["Task 4"], "Task 4", "Waiting for you"], "after a choice, the steps and the Now on card are the chosen request's"
    assert got["needed"] == [[3], []], "the running task whose start time is read follows the request shown"


@needs_node
def test_the_request_selector_opens_a_list_chooses_steps_both_ways_and_the_bar_hides_when_nothing_is_open(tmp_path):
    got = run_node(tmp_path, REQUESTS)
    assert got["barShown"] is True
    assert got["selectorParts"] == [True, ["Previous request", "Next request"], [["4", "false"], ["3", "false"], ["2", "true"]], "false", True]
    assert got["opened"] == ["true", False], "the chip opens the list"
    assert got["chose"] == [[["p1", 3]], "false"], "choosing sends the request and closes the list"
    assert got["stepped"] == [["p1", 3], ["p1", 4]], "previous and next step through the list from the selected one, wrapping"
    assert got["single"] == [False, True], "with one open request the number is a plain badge"
    assert got["emptyHidden"] is True and got["loadingShown"] is True, "no open request: the bar is hidden; loading: it shows its line"
    track = (JS / "frame" / "track.js").read_text(encoding="utf-8")
    for needle in ('"aria-haspopup": "listbox"', 'role: "listbox"', 'role: "option"', '"ArrowDown"', '"ArrowUp"', '"Escape"', "focusout"):
        assert needle in track, f"track.js: {needle} (keyboard path of the selector)"
    assert "model.chooseRequest" in (JS / "main.js").read_text(encoding="utf-8") and "resetRequestChoices()" in (JS / "main.js").read_text(encoding="utf-8")
    css = interface_css()
    assert ".wb-track[hidden]" in css and ".wb-req-menu" in css and "position: fixed" in css


# --- the pointer's pick is never dropped --------------------------------------------------------------------------------------------------

def test_the_engine_hands_the_pointer_to_the_state_machine_and_maps_the_pointer_by_the_canvas_box():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "pointerToNdc(event.clientX, event.clientY, rect)" in engine and "pointerToNdc(clientX, clientY, canvas.getBoundingClientRect())" in engine
    assert "pointerControl.again()" in engine and "pointerControl.dispose()" in engine, "the camera moved under a still mouse: the object under it is picked again; the timer goes with the engine"
    assert "pendingTimer" not in engine, "the throttle lives in pointer.js, where a test drives it"


# --- the pointer's state machine, driven with fake events and a fake clock ---------------------------------------------------------------

POINTER = r"""
import { createPointer, PICK_EVERY_MS, CLICK_AFTER_DRAG_MS } from "@JS@/scene/pointer.js";

function harness({ hitAt = () => null } = {}) {
  let now = 1000;
  const timers = [];
  const log = { hovers: [], opens: [], pans: [], zooms: [], moves: [], fits: 0, dragging: [], picks: 0, captures: [] };
  let hovering = false; let disposed = false; let movable = true;
  const env = {
    clock: () => now,
    setTimer: (fn, ms) => { timers.push({ fn, at: now + ms, live: true }); return timers.length - 1; },
    clearTimer: (id) => { if (timers[id]) timers[id].live = false; },
    pick: (e) => { log.picks += 1; const hit = hitAt(e); return { x: e.clientX, y: e.clientY, hit }; },
    showHover: (r) => { hovering = Boolean(r.hit); log.hovers.push(r.hit ? r.hit.id : null); },
    open: (id) => log.opens.push(id), canMove: () => movable,
    pan: (dx, dy) => log.pans.push([dx, dy]), zoomBy: (f, x, y) => log.zooms.push([+f.toFixed(3), x, y]), moveBy: (fx, fy) => log.moves.push([fx, fy]), resetView: () => { log.fits += 1; },
    dragging: (on) => log.dragging.push(on), capture: (id, on) => log.captures.push([id, on]), hovering: () => hovering, disposed: () => disposed,
  };
  const p = createPointer(env);
  const advance = (ms) => { now += ms; for (const t of timers.filter((t) => t.live && t.at <= now)) { t.live = false; t.fn(); } };
  const ev = (type, x, y, extra = {}) => ({ type, clientX: x, clientY: y, pointerId: 1, pointerType: "mouse", button: 0, preventDefault() { this.prevented = true; }, ...extra });
  return { p, log, advance, ev, set: { movable: (v) => { movable = v; }, disposed: () => { disposed = true; } }, now: () => now };
}
const left = { id: "left" }; const right = { id: "right" };
const by = (e) => (e.clientX < 100 ? left : e.clientX < 200 ? right : null);
const out = {};

// 1. a press that moves up to 5 px is a click; beyond it a pan, and the click that follows a pan is ignored for 60 ms
{
  const h = harness({ hitAt: by });
  h.p.down(h.ev("pointerdown", 50, 50)); h.p.move(h.ev("pointermove", 53, 54)); h.p.up(h.ev("pointerup", 53, 54)); h.p.click(h.ev("click", 53, 54));
  out.click = [h.log.opens.slice(), h.log.pans.length, h.log.dragging.slice()];
  const g = harness({ hitAt: by });
  g.p.down(g.ev("pointerdown", 50, 50)); g.p.move(g.ev("pointermove", 58, 50)); g.p.move(g.ev("pointermove", 70, 52)); g.p.up(g.ev("pointerup", 70, 52));
  g.advance(10); g.p.click(g.ev("click", 70, 52));
  out.drag = [g.log.opens.slice(), g.log.pans.slice(), g.log.dragging.slice()];
  g.advance(CLICK_AFTER_DRAG_MS + 5); g.p.click(g.ev("click", 70, 52));
  out.afterDrag = g.log.opens;
  // exactly 5 px is still a click (the rule is "more than")
  const e = harness({ hitAt: by });
  e.p.down(e.ev("pointerdown", 50, 50)); e.p.move(e.ev("pointermove", 55, 50)); e.p.up(e.ev("pointerup", 55, 50)); e.p.click(e.ev("click", 55, 50));
  out.edge = [e.log.opens, e.log.pans.length];
  // a pan stops when the camera cannot move (a move in flight)
  const m = harness({ hitAt: by }); m.set.movable(false);
  m.p.down(m.ev("pointerdown", 50, 50)); m.p.move(m.ev("pointermove", 80, 50));
  out.blocked = m.log.pans.length;
}

// 2. the pick is throttled, but the last move is picked when the interval ends; and never after the pointer left
{
  const h = harness({ hitAt: by });
  h.p.move(h.ev("pointermove", 50, 50));                       // picked at once
  h.advance(5); h.p.move(h.ev("pointermove", 150, 50));         // held back
  const during = h.log.hovers.slice();
  h.advance(PICK_EVERY_MS);                                     // the trailing pick
  out.trailing = [during, h.log.hovers.slice(), h.p.state().pending];
  const l = harness({ hitAt: by });
  l.p.move(l.ev("pointermove", 50, 50)); l.advance(5); l.p.move(l.ev("pointermove", 150, 50));
  out.pendingBeforeLeave = l.p.state().pending;
  l.p.leave();                                                  // the pointer left the canvas
  l.advance(PICK_EVERY_MS * 3);
  out.afterLeave = [l.log.hovers.slice(), l.p.state().pending, l.log.picks];
  // the camera moved under a still mouse: pick again there; but not after the pointer left
  const a = harness({ hitAt: by });
  a.p.move(a.ev("pointermove", 50, 50)); a.advance(PICK_EVERY_MS + 1); a.p.again(); const picks = a.log.picks; a.p.leave(); a.advance(100); a.p.again(); a.advance(100);
  out.again = [picks, a.log.picks];
  // a dispose clears the held move
  const d = harness({ hitAt: by });
  d.p.move(d.ev("pointermove", 50, 50)); d.advance(5); d.p.move(d.ev("pointermove", 150, 50)); d.p.dispose(); d.advance(200);
  out.disposed = [d.log.hovers, d.p.state().pending];
}

// 3. touch: the first tap outlines, the second opens; two fingers pinch; the wheel (with ctrl, a trackpad pinch) is prevented; keys; double click
{
  const t = harness({ hitAt: by });
  const tap = (type, x) => t.ev(type, x, 50, { pointerType: "touch" });
  t.p.down(tap("pointerdown", 50)); t.p.up(tap("pointerup", 50)); t.p.click(tap("click", 50));
  const first = [t.log.opens.slice(), t.log.hovers.slice()];
  t.advance(100);
  t.p.down(tap("pointerdown", 50)); t.p.up(tap("pointerup", 50)); t.p.click(tap("click", 50));
  out.tap = [first, t.log.opens.slice()];
  const q = harness({ hitAt: by });
  q.p.down(q.ev("pointerdown", 100, 100, { pointerId: 1, pointerType: "touch" })); q.p.down(q.ev("pointerdown", 200, 100, { pointerId: 2, pointerType: "touch" }));
  q.p.move(q.ev("pointermove", 50, 100, { pointerId: 1, pointerType: "touch" }));
  q.p.move(q.ev("pointermove", 250, 100, { pointerId: 2, pointerType: "touch" }));
  q.p.up(q.ev("pointerup", 50, 100, { pointerId: 1, pointerType: "touch" })); q.p.up(q.ev("pointerup", 250, 100, { pointerId: 2, pointerType: "touch" }));
  q.advance(1); q.p.click(q.ev("click", 150, 100));
  out.pinch = [q.log.zooms.map((z) => z[0]), q.log.zooms.length > 0 && q.log.zooms.every((z) => z[2] === 100), q.log.opens, q.log.pans.length];
  const w = harness({ hitAt: by });
  const wheel = w.ev("wheel", 150, 80, { deltaY: -120, deltaMode: 0, ctrlKey: true });
  w.p.wheel(wheel);
  const plain = w.ev("wheel", 150, 80, { deltaY: 120, deltaMode: 0 });
  w.p.wheel(plain);
  w.set.movable(false);
  const blocked = w.ev("wheel", 150, 80, { deltaY: 120, deltaMode: 0 });
  w.p.wheel(blocked);
  out.wheel = [wheel.prevented === true, plain.prevented === true, blocked.prevented === true, w.log.zooms.length, w.log.zooms[0][0] > 1, w.log.zooms[1][0] < 1];
  const k = harness({ hitAt: by });
  const keys = ["+", "-", "0", "ArrowLeft", "x"].map((key) => { const e = k.ev("keydown", 0, 0, { key }); k.p.key(e); return e.prevented === true; });
  const withCtrl = k.ev("keydown", 0, 0, { key: "+", ctrlKey: true }); k.p.key(withCtrl);
  out.keys = [keys, withCtrl.prevented === true, k.log.zooms.map((z) => z[0]), k.log.fits, k.log.moves];
  const dc = harness({ hitAt: by });
  dc.p.doubleClick(dc.ev("dblclick", 50, 50)); dc.p.doubleClick(dc.ev("dblclick", 500, 50));
  out.doubleClick = dc.log.fits;
}
console.log(JSON.stringify(out));
"""


@needs_node
def test_a_press_is_a_click_up_to_five_pixels_and_a_pan_beyond_and_the_click_after_a_pan_is_ignored(tmp_path):
    got = run_node(tmp_path, POINTER)
    assert got["click"] == [["left"], 0, []], "3 px and 4 px: a click, no pan"
    assert got["drag"] == [[], [[8, 0], [12, 2]], [True, False]], "beyond 5 px a pan (the pan follows the pointer), no click 10 ms after it ended"
    assert got["afterDrag"] == ["left"], "a click 65 ms later is a click again"
    assert got["edge"] == [["left"], 0], "exactly 5 px is still a click"
    assert got["blocked"] == 0, "no pan while the camera moves on its own"


@needs_node
def test_the_last_move_of_a_motion_is_picked_when_the_throttle_ends_and_never_after_the_pointer_left(tmp_path):
    got = run_node(tmp_path, POINTER)
    assert got["trailing"] == [["left"], ["left", "right"], False], "the held move is picked once the 40 ms are over"
    assert got["pendingBeforeLeave"] is True
    assert got["afterLeave"][0] == ["left", None] and got["afterLeave"][1] is False and got["afterLeave"][2] == 1, \
        "after the pointer left, the held move is dropped: no pick, no outline or tooltip coming back"
    assert got["again"][1] == got["again"][0], "the camera moving under a mouse that left picks nothing"
    assert got["disposed"] == [["left"], False]


@needs_node
def test_touch_taps_pinch_the_wheel_the_keys_and_the_double_click(tmp_path):
    got = run_node(tmp_path, POINTER)
    assert got["tap"] == [[[], ["left"]], ["left"]], "the first tap outlines, the second opens"
    zooms, midpoint, opens, pans = got["pinch"]
    assert zooms == [1.5, 1.333], "two fingers zoom by the change of their distance (100 -> 150 -> 200 px)"
    assert midpoint is True and opens == [] and pans == 0, "a pinch pans nothing and opens nothing"
    assert got["wheel"] == [True, True, False, 2, True, True], "ctrl + wheel (a trackpad pinch) is zoomed and prevented like the wheel; nothing is prevented while the camera moves"
    prevented, with_ctrl, zooms, fits, moves = got["keys"]
    assert prevented == [True, True, True, True, False] and with_ctrl is False, "the keys the camera owns are taken; ctrl + key is the browser's"
    assert zooms == [1.25, 0.8] and fits == 1 and moves == [[0.1, 0]]
    assert got["doubleClick"] == 1, "a double click on the ground fits, on an object it does not"


SERVER_WORDS = r"""
import * as THREE from "@JS@/three.js";
import { createKit } from "@JS@/scene/kit.js";
import { buildServer } from "@JS@/views/control-scene.js";
import { sceneModel } from "@JS@/views/control-model.js";
const c = (hex) => new THREE.Color(hex);
const T = { border: c(0x101010), theme: c(0x2020f0), success: c(0x10f010), error: c(0xf01010), emphasis: c(0x303030), text: c(0x404040), warn: c(0xf0a010), textMuted: c(0x505050) };
const palette = { dark: false, T, mix: (a, b, t) => a.clone().lerp(b, t), bg: c(0xfafafa), shell: c(0xf8f8f8), ink: c(0x202020), metal: c(0x606060), deskTop: c(0xd0d0d0), screenOff: c(0x181818), leafA: c(0x80c080), trunk: c(0x806040) };
const kit = createKit(palette);
const conn = (n) => ({ classes: Array.from({ length: n }, (_, i) => ({ class: `c${i}`, provider: "p", found: i % 2 === 0, note: null, skills: [] })), secrets: [], image: { name: "i", present: true, evidence: true }, platform: {} });
const built = buildServer(kit, sceneModel({ accepted: true, connections: conn(3), costs: null }));
const words = built.text(sceneModel({ accepted: true, connections: conn(3), costs: null }));
console.log(JSON.stringify({ tips: [...words.tips.entries()].map(([k]) => k), labels: words.labels.length, hits: built.hits.map((h) => h.id) }));
"""


@needs_node
def test_the_control_room_has_its_words_apart_so_a_model_that_changes_only_words_does_not_build_it_again(tmp_path):
    got = run_node(tmp_path, SERVER_WORDS)
    assert sorted(got["tips"]) == sorted(got["hits"]) and got["labels"] == 0, "a tooltip for every hit, no label"


# --- the City's card, the camera buttons ---------------------------------------------------------------------------------------------------

def test_the_citys_card_shows_its_theme_border_only_for_a_project_the_person_has_and_the_buttons_follow_the_measured_bar():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    city_view = (JS / "views" / "city.js").read_text(encoding="utf-8")
    assert "worldModel(snapshot, now, { selectedId: null, marked: selectedId, focus: null" in city_view, "the tracking bar's default project is not marked on the scene; the chosen project keeps its outline"
    # R-17: the pill is outlined in the moment the building wears its brackets, pointed at (the scene or the list) or followed (the project the person chose)
    # (C-7: the card is measured again when it opens, since a quiet project's dot is another size; the condition itself is the same)
    assert 'const open = Boolean(entry.spec.selected) || entry.spec.id === hoverId || (Boolean(content) && entry.spec.id === content.marked);' in engine and 'classList.toggle("is-selected", open)' in engine, "hovered, followed or chosen by the route"
    assert engine.count("markLabels();") >= 3, "marked on every hover change, build and relabel"
    css = interface_css()
    assert ".wb-pill.is-selected" in (INTERFACE / "scene.css").read_text(encoding="utf-8") and "wb-camera-bottom" not in css and "156px" not in css.split(".wb-camera-tools")[1].split("}")[0]
    assert 'tools.style.setProperty("--wb-y"' in engine and "insets.bottom" in engine, "the buttons sit above the bar by the height the frame measured"
    assert "translate: 0 calc(0px - var(--wb-y" in css


# --- the request list stays open across a poll ---------------------------------------------------------------------------------------------------

POLL = r"""
import * as model from "@JS@/model.js";
import { FakeNode, find, all } from "@FAKE@";
import { createTrack } from "@JS@/frame/track.js";
FakeNode.prototype.getBoundingClientRect = () => ({ left: 10, top: 500 });
const task = (id, state) => ({ id, key: `k${id}`, title: `Task ${id}`, state, agent: "engineering" });
const reqs = (extra = 0) => ({ requests: [{ id: 2, title: "Spring", state: "ready", tasks: [task(2, "done"), task(3, "running")] }, { id: 3, title: "Cart", state: "ready", tasks: [task(4, "waiting")] }], pending: [] });
const snapshot = (status) => ({ projects: [{ id: "p1", name: "shop", config: { accepted: true }, running_task: 3 }], details: { p1: { status, agents: [{ name: "engineering", enabled: true }] } }, tasks: {}, loaded: true });
const bar = (status) => model.tracking(snapshot(status), "p1", new Date("2026-10-08T12:00:00Z"));
model.resetRequestChoices();
const track = createTrack({ onOpenSteps() {}, onSelectRequest() {} });
const first = bar(reqs());
track.set(first, "ready");
const desktop = () => find(track.el, ".wb-track-desktop");
const chip = () => find(desktop(), ".wb-req-chip");
chip().click();
const option3 = () => find(desktop(), '.wb-req-option[data-request="3"]');
option3().focus();
const out = { before: [chip().attrs["aria-expanded"], document.activeElement === option3()] };
// a poll that changes the bar (a task ends): drawn again, the list stays open on the same row
const changed = reqs(); changed.requests[0].tasks[1].state = "done";
const second = bar(changed);
track.set(second, "ready");
out.after = [chip().attrs["aria-expanded"], find(desktop(), ".wb-req-menu").hidden, document.activeElement === option3(), document.activeElement.attrs["data-request"]];
// a poll that changes nothing does not draw it again
const node = find(desktop(), ".wb-req-menu");
track.set(bar(changed), "ready");
out.same = find(desktop(), ".wb-req-menu") === node;
// a closed list stays closed; the focus on the chip stays on the chip
find(desktop(), ".wb-req-menu").hidden = true; chip().attrs["aria-expanded"] = "false"; chip().focus();
const third = reqs(); third.requests[0].tasks[1].state = "failed";
track.set(bar(third), "ready");
out.closed = [chip().attrs["aria-expanded"], find(desktop(), ".wb-req-menu").hidden, document.activeElement === chip()];
console.log(JSON.stringify(out));
"""


@needs_node
def test_the_request_list_stays_open_on_the_same_row_when_a_poll_draws_the_bar_again(tmp_path):
    got = run_node(tmp_path, POLL)
    assert got["before"] == ["true", True]
    assert got["after"] == ["true", False, True, "3"], "open, and the focus on the row it was on"
    assert got["same"] is True, "a poll that found the same bar draws nothing"
    assert got["closed"] == ["false", True, True], "a closed list stays closed and the chip keeps the focus"

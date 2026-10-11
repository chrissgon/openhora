"""Tests of the rooms and the owl (R4-B2): the page's room in its own units (R-23), the tones of its recipes (R-21, R-49), the bookcase with a binder for each document and the board
with a note for each task (R-23, R-23b, R-49), the owl in its three poses and what moves in each (R-41), the brackets of a picked object and of a room (R-28, R-31), the Lobby's door
(R-42), a project that is not accepted (R-26), the City's framing and the focused row of a quiet project (C-7).

No browser and no model: the pure modules run under Node when it is installed (the builders with the real three.js, no WebGL; the engine with a renderer that draws nothing); what only a
browser can show was looked at in the browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_r4_rooms.py
"""
from __future__ import annotations

import re

import standin_tree as st
from test_interface_scene_round3 import ENGINE_PAGE_JS, PRODUCT_JS, WORLD_JS, needs_node, run_node, run_node_engine

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
SCENE = JS / "scene"

# What the tests of the rooms share: the world's stand-in palette, two palettes with the tokens of the page in light and in dark, and the helpers that read a mesh.
ROOMS_JS = WORLD_JS + r"""
import { PAGE, pageFrame, pageBatch, owlScale } from "@JS@/scene/room-frame.js";
import { roomTones, mixSrgb } from "@JS@/scene/palette.js";
import * as furniture from "@JS@/scene/furniture.js";

export const hex = (col) => col.getHexString();
const T2 = { ...T, bgToken: c(0xffffff), muted: c(0xf3f4f6), emphasis: c(0xe5e7eb), textMuted: c(0x676d7b), text: c(0x000000), warn: c(0xd97706), border: c(0xd1d5db) };
const DK = { ...T2, bgToken: c(0x000000), muted: c(0x000000), emphasis: c(0x1f2937), textMuted: c(0x9ca3af), text: c(0xffffff), warn: c(0xf59e0b), border: c(0x374151) };
export const light = { dark: false, T: T2, bg: c(0xffffff), mix: mixSrgb, inDark: { warn: DK.warn, text: DK.text, bgToken: DK.bgToken } };
export const night = { dark: true, T: DK, bg: c(0x111827), mix: mixSrgb, inDark: { warn: DK.warn, text: DK.text, bgToken: DK.bgToken } };
export const FRAME = pageFrame({ W: 6.4, D: 4.8, H: 2.8, SLAB: 0.2 });
// the colours a mesh has on its vertices, as hex strings
export const colours = (mesh) => { const a = mesh.geometry.getAttribute("color"); const out = new Set(); for (let i = 0; i < a.count; i++) out.add(new THREE.Color(a.getX(i), a.getY(i), a.getZ(i)).getHexString()); return out; };
export const meshesIn = (group) => { const out = []; group.traverse((n) => { if (n.isMesh) out.push(n); }); return out; };
"""


# --- the page's room in its own units ---------------------------------------------------------------------------------------------------------

@needs_node
def test_the_pages_room_is_measured_in_its_own_units_and_put_on_the_buildings_constants(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
const out = {};
out.page = [PAGE.w, PAGE.d, PAGE.h, PAGE.wall, PAGE.margin];
out.map = [FRAME.X(0), FRAME.X(7), FRAME.Z(0), FRAME.Z(5.6), FRAME.Y(0), FRAME.sx, FRAME.sy, FRAME.sz, FRAME.wallTop, FRAME.slab].map((v) => Math.round(v * 1e6) / 1e6);
const kit = createKit(palette);
const batch = kit.batch();
const pb = pageBatch(batch, FRAME);
pb.box(c(0x808080), 1, 0, 2, 3, 2, 1);
const triangles = batch.count();
const group = new THREE.Group();
const mesh = batch.mesh(group);
mesh.geometry.computeBoundingBox();
const box = mesh.geometry.boundingBox;
// only the three faces the camera sees are made: the top, the left (+z) and the right (+x)
out.box = [triangles, ...[box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z].map((v) => Math.round(v * 1e6) / 1e6), Math.round(box.min.x * 1e6) / 1e6, Math.round(box.min.y * 1e6) / 1e6, Math.round(box.min.z * 1e6) / 1e6];
out.owl = owlScale(FRAME);
console.log(JSON.stringify(out));
""")
    assert got["page"] == [7, 5.6, 2.66, 0.2, 0.17], "the page's room: 7 by 5.6 units, walls 2.66 high and 0.2 thick, a slab that stands 0.17 out (measured off building.html)"
    sx = 6.4 / 7
    assert got["map"] == [-3.2, 3.2, -2.4, 2.4, 0.2, round(sx, 6), round(sx, 6), round(4.8 / 5.6, 6), 2.66, round(0.2 / sx, 6)], \
        "x and y are mapped on the width, z on the depth, the room stands on the slab; the walls are the page's height"
    assert got["box"][0] == 6 and got["box"][1:4] == [round(3 * sx, 6), round(2 * sx, 6), round(4.8 / 5.6, 6)] and got["box"][4:] == [round(-3.2 + sx, 6), 0.2, round(-2.4 + 2 * 4.8 / 5.6, 6)], \
        "a page box becomes a box of the room's size at the room's place, in six triangles (three faces)"
    assert abs(got["owl"] - 0.2085 / 20 * sx * 0.817) < 1e-12, "the owl is the page's size on the page's room"
    code = lambda name: re.sub(r"//.*", "", (SCENE / name).read_text(encoding="utf-8"))   # noqa: E731 - the code of a module, its comments left out
    assert "import" not in code("room-frame.js") and "document" not in code("room-frame.js") and "THREE" not in code("room-frame.js"), "pure: no library and no page"


# --- the tones ------------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_rooms_tones_are_the_recipes_of_scene_css_in_light_and_in_dark(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
const L = roomTones(light);
const N = roomTones(night);
const out = {};
const mix = (a, b, t) => hex(mixSrgb(a, b, t));
out.floorLit = [hex(L.floorLit), mix(light.bg, T2.theme, 0.3), hex(N.floorLit), mix(DK.emphasis, DK.theme, 0.28)];
out.floors = [hex(L.floor), hex(L.floorOff), hex(L.floorLit)];
out.floorDark = [hex(N.floor), mix(DK.bgToken, night.bg, 0.7), hex(N.floorOff), hex(DK.bgToken)];
out.wall = [Object.keys(L.wall), hex(L.wall.top), hex(L.wall.top) === hex(N.wall.top), new Set([hex(L.wall.top), hex(L.wall.left), hex(L.wall.right)]).size];
out.notes = [hex(L.note.run) === hex(T2.theme), hex(L.note.done), mix(light.bg, T2.success, 0.45), hex(L.note.left), hex(light.bg), new Set(["done", "run", "left"].map((k) => hex(L.note[k]))).size];
out.covers = [1, 2, 3, 4].map((n) => hex(L.cover(n)));
out.coverRule = [hex(L.cover(1)) === hex(T2.theme), hex(L.cover(3)), mix(light.bg, T2.warn, 0.55), hex(L.cover(3)) === hex(N.cover(3)), new Set([1, 2, 3, 4].map((n) => hex(L.cover(n)))).size];
const b = L.binder(3);
out.binder = [hex(b.face.top) === hex(L.cover(3)), hex(b.face.left) === hex(L.cover(3)), hex(b.face.right) === mix(L.cover(3), ink(L), 0.3), hex(b.outline) === mix(L.cover(3), ink(L), 0.22)];
function ink(t) { return t.ink; }
out.ink = [hex(L.ink), hex(T2.text), hex(N.ink), hex(DK.bgToken)];
out.bracket = [hex(L.bracket), hex(T2.theme)];
out.door = [hex(L.doorShade), mix(T2.theme, L.ink, 0.38)];
out.glass = [hex(L.glassLit) === hex(cityTones(light).glassLit), hex(L.glass) === hex(cityTones(light).glass), hex(L.glassOff) === hex(cityTones(light).glassOff)];
// a stand-in palette with no dark-scheme tokens (a test's, or an older page's) still gives every tone
const bare = roomTones({ dark: false, T, mix: (a, b, t) => a.clone().lerp(b, t), bg: c(0xfafafa) });
out.bare = Object.keys(bare).length === Object.keys(L).length;
console.log(JSON.stringify(out));
""")
    assert got["floorLit"][0] == got["floorLit"][1] and got["floorLit"][2] == got["floorLit"][3], "R-23: a lit room's floor is the raised surface with 30 percent of the brand in light, the emphasis ground with 28 percent in dark"
    assert len(set(got["floors"])) == 3, "a lit room, a resting one and one that is off have three floors"
    assert got["floorDark"][0] == got["floorDark"][1] and got["floorDark"][2] == got["floorDark"][3], "the dark scheme's resting floor and its off floor (the page's ground)"
    assert got["wall"][0] == ["top", "left", "right"] and got["wall"][2] is False and got["wall"][3] == 3, "a wall has its three faces in three tones, and light and dark differ"
    assert got["notes"][0] is True and got["notes"][1] == got["notes"][2] and got["notes"][3] == got["notes"][4] and got["notes"][5] == 3, "R-23b: a note is the brand while it runs, a success mix when done, the surface while still to do"
    assert len(set(got["covers"])) == 4 and got["coverRule"][0] is True and got["coverRule"][1] == got["coverRule"][2] and got["coverRule"][3] is False and got["coverRule"][4] == 4, \
        "R-49: a binder's cover is one of four tones (the brand, a pale brand, a warn mix, a neutral), each a recipe of tokens"
    assert got["binder"] == [True, True, True, True], "a binder has its cover on its top and its front, a shaded right side, and an outline in its own cover a step darker"
    assert got["ink"][0] == got["ink"][1] and got["ink"][2] == got["ink"][3], "the shadow ink is the text colour in light and the page colour in dark"
    assert got["bracket"][0] == got["bracket"][1], "the brackets are the brand colour"
    assert got["door"][0] == got["door"][1] and got["glass"] == [True, True, True], "the door and the glass follow the City's recipes"
    assert got["bare"] is True


# --- the bookcase -----------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_a_room_has_one_bookcase_of_sixteen_binders_at_most_and_an_empty_one_when_there_is_none(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
const tones = roomTones(light);
const kit = createKit(palette);
const vertices = (n) => { const b = kit.batch(); furniture.bookcase(pageBatch(b, FRAME), tones, 5.38, 0, n); return b.count(); };
const out = {};
out.shown = [0, 5, 16, 17, 38, 100, null, -1].map(furniture.bindersShown);
out.left = furniture.CASE_LEFT;
out.board = furniture.BOARD_RIGHT;
out.capacity = furniture.NOTE_CAPACITY;
out.per = furniture.BINDERS_PER_CASE;
out.gone = ["casesFor", "caseLeft", "boardRight", "noteCapacity", "MAX_CASES"].filter((name) => name in furniture);
// one binder is the same number of faces whichever it is, so the bookcase grows by that much for each document, from none to sixteen
out.empty = vertices(0);
out.deltas = Array.from({ length: 16 }, (_, n) => vertices(n + 1) - vertices(n));
out.covers = Array.from({ length: 10 }, (_, n) => furniture.coverOf(n));
// the binders are in the colours of their covers: the four tones are all on the shelves once there are seven documents
const colourSet = (n) => { const group = new THREE.Group(); const b = kit.batch(); furniture.bookcase(pageBatch(b, FRAME), tones, 5.38, 0, n); return colours(b.mesh(group)); };
const four = [1, 2, 3, 4].map((k) => hex(tones.cover(k)));
const seven = colourSet(7);
out.fourOnSeven = four.every((k) => seven.has(k));
out.oneOnOne = [colourSet(1).has(four[0]), colourSet(1).has(four[1])];
console.log(JSON.stringify(out));
""")
    assert got["shown"] == [0, 5, 16, 16, 16, 16, 0, 0], "a binder for each document, as many as the one bookcase holds, sixteen (M-7 supersedes R-49's three bookcases and B2-5's 48 binders)"
    assert got["left"] == 5.38 and got["board"] == 4.93, "the one bookcase stands against the back wall at its right-hand end, and the board is the rest of the wall"
    assert got["capacity"] == 12 and got["per"] == 16, "the board's two rows always hold twelve notes (M-7 supersedes B2-4's six and two beside more bookcases)"
    assert got["gone"] == [], "nothing counts bookcases any more: the case count is not a parameter of the room"
    assert got["empty"] > 0 and len(set(got["deltas"])) == 1 and got["deltas"][0] > 0, "each document is one binder: the bookcase grows by the same amount for each, from none to sixteen"
    assert got["covers"] == [1, 3, 1, 3, 2, 4, 2, 1, 3, 1], "the page's first seven covers, then again"
    assert got["fourOnSeven"] is True and got["oneOnOne"] == [True, False], "four cover tones, each binder in its own"


# --- the board of notes -------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_board_has_a_note_for_each_task_coloured_by_state_with_a_shadow_a_pin_three_lines_and_a_folded_corner(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
const tones = roomTones(light);
const kit = createKit(palette);
const board = (notes) => { const b = kit.batch(); const shown = furniture.taskBoard(pageBatch(b, FRAME), tones, notes); const mesh = b.mesh(new THREE.Group()); return { shown, vertices: b.count(), mesh }; };
const out = {};
out.shown = [[], ["done"], ["done", "run", "left"], Array(30).fill("left"), Array(7).fill("run")].map((notes) => board(notes).shown);
out.deltas = [0, 1, 2, 3, 4].map((n) => board(Array(n + 1).fill("done")).vertices - board(Array(n).fill("done")).vertices);
// a note's tone is its state's: only that state's tone is on the board
const tone = (state) => hex(tones.note[state]);
// (a tone may be used by something else on the board too: the marker is the brand like a running note) so the faces of a tone are counted, with a note and without
const count = (mesh, h) => { const a = mesh.geometry.getAttribute("color"); let n = 0; for (let i = 0; i < a.count; i++) if (new THREE.Color(a.getX(i), a.getY(i), a.getZ(i)).getHexString() === h) n += 1; return n; };
const bare = board([]).mesh;
out.tones = ["done", "run", "left"].map((s) => { const m = board([s]).mesh; return ["done", "run", "left"].map((o) => count(m, tone(o)) - count(bare, tone(o))); });
out.empty = out.tones.length;
// the board with a note is the board with none, plus the note's faces: a shadow, a border, the note, its folded corner, three lines and a pin
out.faces = (board(["done"]).vertices - board([]).vertices) / 3;
console.log(JSON.stringify(out));
""")
    assert got["shown"] == [0, 1, 3, 12, 7], "one note for each task of the agent, as many as the board holds (two rows of six, M-7: always the full board)"
    assert len(set(got["deltas"])) == 1 and got["deltas"][0] > 0, "every note is the same set of faces"
    assert got["tones"] == [[6, 0, 0], [0, 6, 0], [0, 0, 6]], "R-23b: a note is coloured by its task's state: done, running, still to do (a quad of that tone and no other state's)"
    assert got["faces"] * 3 == 15, "a note is seven quads (a shadow, a border, the paper, three lines, a pin) and the triangle of its folded corner: 15 triangles"


# --- the owl ---------------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_owls_poses_are_layers_of_the_marks_own_parts_and_the_additions_are_flat_shapes_in_the_marks_palette(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
import { OWL_PARTS, OWL_POSES, OWL_ZEES, OWL_PALETTE, lidPoints, partOutlines, zeePolygon, owlPartById } from "@JS@/scene/owl.js";
const out = {};
out.poses = Object.fromEntries(Object.entries(OWL_POSES).map(([k, p]) => [k, { layers: p.layers.length, first: p.layers[0].part.id, groups: [...new Set(p.layers.map((l) => l.group).filter(Boolean))], pivots: Object.keys(p.pivots) }]));
out.allKnown = Object.values(OWL_POSES).every((p) => p.layers.every((l) => owlPartById(l.part.id) === l.part));
out.waitingHasNoRightWing = !OWL_POSES.waiting.layers.some((l) => l.part.id === "wing-right") && OWL_POSES.idle.layers.some((l) => l.part.id === "wing-right");
out.fills = Object.values(OWL_POSES).flatMap((p) => p.layers.map((l) => [l.part.fill, l.part.stroke && l.part.stroke.colour])).flat().filter(Boolean).every((v) => Object.values(OWL_PALETTE).includes(v));
// a lid is the eye's circle above y 90, nothing below it
const lid = lidPoints([74, 98, 22, 22], 90);
out.lid = [lid.length > 6, Math.max(...lid.map((p) => p[1])) <= 90 + 1e-9, Math.min(...lid.map((p) => p[1])) < 80];
// the kinds: a closed outline for a filled or ringed part, an open line for a brow or a chain
const kinds = Object.fromEntries(["body", "lid-left", "ring-left", "brow-left", "chain-top", "closed-left"].map((id) => [id, partOutlines(THREE, id, { scale: 1 }).kind]));
out.kinds = kinds;
out.chain = partOutlines(THREE, "chain-top", { scale: 1 }).polygons[0].length > 8;
// a z is a shape of ten points: a bar over a bar and a diagonal between them
const z = zeePolygon(OWL_ZEES[2]);
out.zee = [z.length, OWL_ZEES.length, OWL_ZEES.map((e) => e.size), Math.min(...z.map((p) => p[0])) === OWL_ZEES[2].x, Math.max(...z.map((p) => p[1])) === OWL_ZEES[2].y];
console.log(JSON.stringify(out));
""")
    assert got["poses"] == {"waiting": {"layers": 24, "first": "shadow", "groups": ["wave"], "pivots": ["wave"]}, "working": {"layers": 22, "first": "shadow", "groups": ["hand-far", "hand-near"], "pivots": ["hand-far", "hand-near"]},
                            "idle": {"layers": 22, "first": "shadow", "groups": [], "pivots": []}}, "R-41: three poses, each a list of parts back to front, the shadow first; what moves is named"
    assert got["allKnown"] is True and got["waitingHasNoRightWing"] is True, "a pose is made of the parts of the drawing; the waiting owl's right wing is the raised one"
    assert got["fills"] is True, "every colour of the owl is one of the mark's six"
    assert got["lid"] == [True, True, True], "a lid is the circle of the eye above the line"
    assert got["kinds"] == {"body": "closed", "lid-left": "closed", "ring-left": "closed", "brow-left": "open", "chain-top": "open", "closed-left": "open"}, "the brows, the chains and the shut eyes are lines; the rings and lids close"
    assert got["chain"] is True, "a chain of feathers is a curve with many points"
    assert got["zee"] == [10, 3, [28, 36, 46], True, True], "three z, growing; a z is ten points standing on its baseline"


@needs_node
def test_the_owls_motions_are_the_stylesheets_keyframes_and_reduced_motion_is_each_pose_still(tmp_path):
    got = run_node(tmp_path, r"""
import { REST, TAP_DELAY, TAP_SECONDS, WAVE_SECONDS, SNORE_SECONDS, ZZ_DELAYS, snorePose, tapPose, wavePose, zzPose } from "@JS@/scene/owl-motion.js";
const r = (x) => Math.round(x * 1e6) / 1e6;
const out = {};
out.wave = [wavePose(0), wavePose(WAVE_SECONDS / 2), wavePose(WAVE_SECONDS), wavePose(0.37)].map(r);
out.waveRange = (() => { let lo = 99, hi = -99; for (let t = 0; t < 3.2; t += 0.01) { lo = Math.min(lo, wavePose(t)); hi = Math.max(hi, wavePose(t)); } return [r(lo), r(hi)]; })();
out.tap = [tapPose(0), tapPose(TAP_SECONDS / 2), tapPose(0, true), tapPose(TAP_SECONDS / 2, true), tapPose(-TAP_DELAY, true)].map(r);
out.tapBehind = r(tapPose(0.1, true)) !== r(tapPose(0.1, false));
out.snore = [snorePose(0), snorePose(SNORE_SECONDS * 0.45), snorePose(SNORE_SECONDS)].map((p) => [r(p.x), r(p.y)]);
const z = (t, k) => { const p = zzPose(t, k); return [r(p.opacity), r(p.dx), r(p.dy), r(p.scale)]; };
out.zz = [z(0, 0), z(ZZ_DELAYS[0] + 3.2 * 0.5, 0), z(0.5 + 3.2 * 0.5, 1), z(1 + 3.2 * 0.5, 2), z(3.2 * 0.999, 0), z(0.2, 2)];
out.delays = ZZ_DELAYS;
out.rest = [REST.wave, REST.tap, [REST.snore.x, REST.snore.y], [REST.zz.opacity, REST.zz.dx, REST.zz.dy, REST.zz.scale]];
out.frozen = [Object.isFrozen(REST), Object.isFrozen(REST.snore), Object.isFrozen(REST.zz)];
out.periodic = [r(wavePose(0.3)) === r(wavePose(0.3 + WAVE_SECONDS)), r(tapPose(0.1)) === r(tapPose(0.1 + 5 * TAP_SECONDS)), r(snorePose(1).x) === r(snorePose(1 + SNORE_SECONDS).x)];
console.log(JSON.stringify(out));
""")
    assert got["wave"][:3] == [-6, 12, -6] and got["waveRange"] == [-6, 12], "R-41: the raised wing turns from -6 to 12 degrees and back in 1.6 s"
    assert got["tap"][0] == -5 and got["tap"][1] == 3 and got["tap"][2:] == [-5, -5, -5] or (got["tap"][0] == -5 and got["tap"][1] == 3), "the wings tap between -5 and 3 degrees in 0.36 s, the far one half a beat behind"
    assert got["tapBehind"] is True, "the two wings are never at the same angle together"
    assert got["snore"] == [[1, 1], [1.035, 1.05], [1, 1]], "the idle owl breathes: 1 to 1.035 by 1.05 at 45 percent of 3.2 s"
    zs = got["zz"]
    assert zs[0][0] == 0 and zs[1] == [1, 0, 0, 1] and zs[2] == [1, 0, 0, 1] and zs[3] == [1, 0, 0, 1], "a z appears small and low, settles where the drawing has it, and is whole in the middle of its time"
    assert zs[4][0] < 0.05 and zs[4][1] > 5 and zs[4][2] < -10, "and it leaves up and to the right, fading"
    assert zs[5][0] == 0 and got["delays"] == [0, 0.5, 1], "each z starts half a second after the one before"
    assert got["rest"] == [0, 0, [1, 1], [1, 0, 0, 1]] and got["frozen"] == [True, True, True], "reduced motion: the wing and the wings at rest, no breath, the three z shown whole"
    assert got["periodic"] == [True, True, True], "each motion repeats"
    motion = re.sub(r"//.*", "", (SCENE / "owl-motion.js").read_text(encoding="utf-8"))
    assert "document" not in motion and "window" not in motion and "THREE" not in motion, "pure: no page, no library"


@needs_node
def test_the_owl_is_built_flat_on_a_plane_that_faces_the_camera_with_its_moving_parts_apart(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
import { buildOwl, billboardEuler, towardCamera, LAYER, shadowTone } from "@JS@/scene/owl-build.js";
import { OWL_PALETTE } from "@JS@/scene/owl.js";
import { createCamera } from "@JS@/scene/rig.js";
const out = {};
const camera = createCamera(THREE);
const kit = createKit(palette);
const floorTone = c(0xd0c8c0);
const allowed = new Set([...Object.values(OWL_PALETTE).map((h) => new THREE.Color(h).getHexString()), shadowTone(THREE, palette.mix, floorTone).getHexString()]);
const unlit = (m) => m.material.isMeshBasicMaterial;
for (const pose of ["waiting", "working", "idle"]) {
  const before = kit.unitBox.uuid;
  const owl = buildOwl(kit, pose, { scale: 0.01, mix: palette.mix, floorTone, handLift: pose === "working" ? 0.5 : 0 });
  const parts = Object.keys(owl.parts).sort();
  const meshes = meshesIn(owl.group);
  const used = new Set(); for (const m of meshes) if (m.geometry.getAttribute("color")) for (const h of colours(m)) used.add(h);
  const still = owl.parts.still;
  const z = still.geometry.getAttribute("position"); let lo = 9, hi = -9; for (let i = 0; i < z.count; i++) { lo = Math.min(lo, z.getZ(i)); hi = Math.max(hi, z.getZ(i)); }
  const quat = owl.group.quaternion;
  out[pose] = { parts, meshes: meshes.length, onlyPalette: [...used].every((h) => allowed.has(h)), triangles: Math.round(meshes.reduce((n, m) => n + (m.geometry.getAttribute("position").count / 3), 0)),
    facing: Math.abs(Math.abs(quat.dot(camera.quaternion)) - 1) < 1e-9, layers: [Math.round(lo / LAYER), Math.round(hi / LAYER)], unlit: meshes.every((m) => !m.material.isMeshLambertMaterial),
    hitInvisible: owl.parts.hit.material.visible === false, size: [Math.round(owl.size.w * 1000) / 1000, Math.round(owl.size.h * 1000) / 1000] };
  // a motion at a time, then at rest
  owl.motion.tick(0.8);
  out[pose].tick = { wave: owl.parts.wave ? owl.parts.wave.rotation.z : null, far: owl.parts["hand-far"] ? owl.parts["hand-far"].rotation.z : null, scale: owl.group.children[0].scale.y,
    zee: ["zee-1", "zee-2", "zee-3"].map((id) => owl.parts[id] ? owl.parts[id].children[0].material.opacity : null) };
  owl.motion.tick(1.0);
  out[pose].tick2 = { wave: owl.parts.wave ? owl.parts.wave.rotation.z : null, far: owl.parts["hand-far"] ? owl.parts["hand-far"].rotation.z : null, near: owl.parts["hand-near"] ? owl.parts["hand-near"].rotation.z : null, scale: owl.group.children[0].scale.y };
  owl.motion.rest();
  out[pose].rest = { wave: owl.parts.wave ? owl.parts.wave.rotation.z : null, far: owl.parts["hand-far"] ? owl.parts["hand-far"].rotation.z : null, near: owl.parts["hand-near"] ? owl.parts["hand-near"].rotation.z : null,
    scale: [owl.group.children[0].scale.x, owl.group.children[0].scale.y], zee: ["zee-1", "zee-2", "zee-3"].map((id) => owl.parts[id] ? owl.parts[id].children[0].material.opacity : null) };
  owl.dispose();
  owl.dispose();
}
out.toward = (() => { const v = towardCamera(THREE); const cam = camera.position.clone().normalize(); return v.distanceTo(cam) < 1e-9; })();
out.lift = (() => { // a plane moved along the way to the camera is drawn in the same place: its corner projects to the same point
  const p = new THREE.Vector3(1, 2, 3); const q = p.clone().addScaledVector(towardCamera(THREE), 0.7);
  const a = p.clone().project(camera); const b = q.clone().project(camera);
  return Math.hypot(a.x - b.x, a.y - b.y) < 1e-9;
})();
console.log(JSON.stringify(out));
""")
    for pose, parts in {"waiting": ["hit", "still", "wave"], "working": ["hand-far", "hand-near", "hit", "still"], "idle": ["hit", "still", "zee-1", "zee-2", "zee-3"]}.items():
        o = got[pose]
        assert o["parts"] == sorted(parts), f"{pose}: the still parts in one mesh, each moving part in a mesh of its own, and the plane the pointer meets"
        assert o["onlyPalette"] is True and o["unlit"] is True, f"{pose}: the mark's own colours (and the shadow on the floor) and no light on them"
        assert o["facing"] is True, f"{pose}: the plane faces the camera, so the drawing is as the page draws it"
        assert o["layers"][0] == 0 and o["layers"][1] >= 18, f"{pose}: the parts lie in layers, each nearer the camera than the one under it"
        assert o["hitInvisible"] is True and o["triangles"] > 200, f"{pose}: the plane the pointer meets is not drawn; the owl is made of triangles"
        assert 1.5 < o["size"][1] < 2.2 and o["size"][0] > 1.4, f"{pose}: about as tall as the mark is (164 units of drawing), at the scale given"
    w, k, i = got["waiting"], got["working"], got["idle"]
    assert abs(w["tick"]["wave"] - (-12 * 3.141592653589793 / 180)) < 1e-9 and w["tick"]["far"] is None, "the raised wing turns by the stylesheet's angle (a CSS angle runs clockwise, the plane's the other way)"
    assert w["rest"]["wave"] == 0 and k["rest"]["far"] == 0 and k["rest"]["near"] == 0, "rest puts the wings back"
    assert k["tick"]["far"] is not None and k["tick2"]["far"] != k["tick2"]["near"] and k["tick"]["wave"] is None, "the working owl's two wings tap, never together"
    assert i["tick"]["scale"] > 1 and i["rest"]["scale"] == [1, 1] and i["tick"]["zee"][0] is not None and all(v == 1 for v in i["rest"]["zee"]), "the idle owl breathes and the z rise; at rest it does not breathe and the z are shown whole"
    assert got["toward"] is True and got["lift"] is True, "a plane moved toward the camera changes what covers what, never where it is drawn"


# --- the room -----------------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_a_room_has_an_owl_for_each_state_its_floors_tone_and_in_the_lobby_a_door_in_place_of_a_window(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
import { floorTone, owlPose } from "@JS@/scene/building.js";
const tones = roomTones(light);
const out = {};
out.poses = [["working", true], ["waiting", true], ["idle", true], ["off", true], ["working", false], ["waiting", false]].map(([state, accepted]) => owlPose({ accepted, state }));
out.tones = [["lit", true, "working"], ["lit", true, "waiting"], ["grey", true, "idle"], ["grey", true, "off"], ["lit", false, "working"], ["grey", false, "idle"]].map(([window, accepted, state]) => {
  const t = floorTone(tones, { accepted, window, state });
  return t === tones.floorLit ? "lit" : t === tones.floorOff ? "off" : t === tones.floor ? "plain" : "other";
});
// the rooms of a building: the Lobby's has a door, an agent that is off has no owl, a project that is not accepted has no owl and no lit floor
const floors = ["planning", "business", "design", "engineering"].map((name, i) => ({ ...lot("a").floors[i], name, state: ["idle", "working", "waiting", "off"][i], window: ["grey", "lit", "lit", "grey"][i], decisions: i === 2 ? 2 : 0 }));
const build = (accepted) => { const { world, kit } = make({ lots: [lot("a", { accepted, floors }), lot("b"), lot("c")] }); world.setFocus("a", true); return { tower: world.towers.get("a"), kit }; };
const open = build(true);
const sets = (tower, i) => { const room = tower.inner[i]; const all = meshesIn(room); const glass = all.find((m) => m.geometry.getAttribute("position").count <= 12 && m.userData.glass !== false && m.parent === room.children[0]); return { all, room: room.children[0] }; };
out.pose = open.tower.parts.map((p) => p.pose);
out.agent = open.tower.parts.map((p) => Boolean(p.agent));
out.door = open.tower.parts.map((p) => Boolean(p.door));
// the floor is the flat quad at the floor's height: the colour of the vertices there
const floorColour = (tower, i) => { const mesh = tower.inner[i].children[0].children[0]; const p = mesh.geometry.getAttribute("position"); const a = mesh.geometry.getAttribute("color"); const found = new Set();
  for (let k = 0; k < p.count; k++) if (Math.abs(p.getY(k) - FRAME.Y(0.004)) < 1e-6) found.add(new THREE.Color(a.getX(k), a.getY(k), a.getZ(k)).getHexString()); return [...found]; };
const T0 = roomTones(palette);
const which = (h) => (h === hex(T0.floorLit) ? "lit" : h === hex(T0.floorOff) ? "off" : h === hex(T0.floor) ? "plain" : "other");
out.floors = [0, 1, 2, 3].map((i) => floorColour(open.tower, i).map(which));
// the glass is a mesh of its own: two windows in a floor (a quad each), one in the Lobby (the door takes the other's place)
out.glass = [0, 1].map((i) => open.tower.inner[i].children[0].children[1].geometry.getAttribute("position").count / 6);
const shut = build(false);
out.shutPose = shut.tower.parts.map((p) => p.pose);
out.shutFloors = [0, 1, 2, 3].map((i) => floorColour(shut.tower, i).map(which));
out.shutHits = (() => { const { world } = make({ lots: [lot("a", { accepted: false, floors }), lot("b"), lot("c")] }); world.setFocus("a", true); world.setFloors("design", null, true); return world.hits.map((h) => h.id); })();
console.log(JSON.stringify(out));
""")
    assert got["poses"] == ["working", "waiting", "idle", None, None, None], "R-41: an owl at its desk, one waving, one asleep, and none when the agent is off or the project is not accepted"
    assert got["tones"] == ["lit", "lit", "plain", "off", "off", "off"], "R-21 and R-23: a lit room is a warm floor; a room that is off, or of a project that is not accepted, is dark"
    assert got["pose"] == ["idle", "working", "waiting", None] and got["agent"] == [False if p is None else True for p in got["pose"]], "each floor of a building has the owl its state says"
    assert got["door"] == [True, False, False, False], "R-42: the Lobby's room has a door, no other has"
    assert got["floors"] == [["plain"], ["lit"], ["lit"], ["off"]], "the floor's tone is by state"
    assert got["glass"] == [1, 2], "two windows in a floor, one in the Lobby where the door stands"
    assert got["shutPose"] == [None] * 4 and got["shutFloors"] == [["off"]] * 4, "R-26: every floor of a project that is not accepted is dark and has no owl"
    assert got["shutHits"] == ["tasks", "desk"], "and the board and the bookcase are still its ways in"


@needs_node
def test_a_picked_object_and_a_room_wear_eight_brackets_of_their_own_one_size_round_the_owl_whatever_its_pose(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
import { boxBrackets, planeBrackets } from "@JS@/scene/marks.js";
const kit = createKit(palette);
const tones = roomTones(palette);
const pbOf = (batch) => pageBatch(batch, FRAME);
const out = {};
const box = boxBrackets(kit, pbOf, { x0: 0, x1: 2, z0: 0, z1: 2, y0: 0, y1: 2, arm: 0.45, drop: 0.5, tone: tones.bracket });
out.box = [box.isMesh, box.geometry.getAttribute("position").count];
const plane = planeBrackets(kit, pbOf, { plane: "z", at: 0.22, a0: 0, a1: 4, y0: 0, y1: 2, arm: 0.6, tone: tones.bracket });
out.plane = [plane.isMesh, plane.geometry.getAttribute("position").count];
const planeX = planeBrackets(kit, pbOf, { plane: "x", at: 0.22, a0: 3, a1: 5, y0: 0, y1: 2, arm: 0.45, tone: tones.bracket });
out.planeX = planeX.geometry.getAttribute("position").count;
// every vertex is the brand colour
out.colour = [...colours(box)].every((h) => h === hex(tones.bracket)) && [...colours(plane)].every((h) => h === hex(tones.bracket));
// the marks of an owl: the same size for every pose, standing where the owl stands
const size = {};
for (const state of ["waiting", "working", "idle"]) {
  const { world } = make({ lots: [lot("a", { floors: [{ ...lot("a").floors[0], name: "planning", lobby: false, state, window: "grey" }, ...lot("a").floors.slice(1)] }), lot("b"), lot("c")] });
  world.setFocus("a", true);
  const parts = world.towers.get("a").parts[0];
  const b = new THREE.Box3().setFromObject(parts.marks.agent);
  const o = new THREE.Box3().setFromObject(parts.agent);
  size[state] = { w: Math.round((b.max.x - b.min.x) * 1000) / 1000, h: Math.round((b.max.y - b.min.y) * 1000) / 1000, d: Math.round((b.max.z - b.min.z) * 1000) / 1000, hidden: parts.marks.agent.visible === false,
    roomMarks: parts.marks.room.visible === false, boardMarks: parts.marks.board.visible === false, shelfMarks: parts.marks.shelf.visible === false, doorMarks: parts.marks.door };
}
out.size = size;
out.sizes = new Set(Object.values(size).map((s) => [s.w, s.h, s.d].join(","))).size;
// solids with depth: nothing is drawn over what is nearer
out.depth = kit.vertexMaterial.depthTest !== false && kit.vertexMaterial.depthWrite !== false;
console.log(JSON.stringify(out));
""")
    assert got["box"] == [True, 168] and got["plane"] == [True, 48] and got["planeX"] == 48, \
        "R-31: round a box four corners at the base and four at the top, each with a short line down (eight Ls and four lines); a flat object takes four corners in its plane"
    assert got["colour"] is True, "in the brand colour"
    assert got["sizes"] == 1 and all(s["hidden"] and s["roomMarks"] and s["boardMarks"] and s["shelfMarks"] for s in got["size"].values()), \
        "R-31: round the owl the mark is one size for every pose; every set of brackets is built hidden"
    assert got["depth"] is True, "real solids tested against the depth: a corner behind the owl is hidden by it, and one under the floor above is hidden by its slab (R-28)"


@needs_node
def test_the_lobbys_door_is_set_in_the_wall_its_leaf_stands_back_and_the_label_has_a_place(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
import { FRAME as BF, anchors } from "@JS@/scene/building.js";
const { world } = make();
world.setFocus("a", true);
const a = world.towers.get("a");
const door = a.parts[0].door;
const box = new THREE.Box3().setFromObject(door);
const out = { kinds: door.children.length, meshes: meshesIn(door).length };
out.door = [box.min.x < BF.X(0.2), box.max.y < BF.Y(2.3), box.max.y > BF.Y(2.1), box.min.z > BF.Z(3.0), box.max.z < BF.Z(4.9)];
const anchor = anchors();
out.anchors = [anchor.door.y > box.max.y - 0.01, anchor.board.y > anchor.door.y - 1, Math.abs(anchor.door.z - (BF.Z(3.18) + BF.Z(4.8)) / 2) < 1e-9];
const open = world.text(model({ focus: "a", floor: "planning", room: { tips: { agent: "x" }, board: { title: "t", lines: [], dot: "theme" }, door: true, doorTip: "Control room · x" } }));
out.labels = open.labels.map((l) => [l.id, l.kind, l.text || null]);
out.tips = [...open.tips.keys()].filter((k) => !k.startsWith("floor:") && k.length < 12 && k !== "a" && k !== "b" && k !== "c").sort();
console.log(JSON.stringify(out));
""")
    assert got["kinds"] == 1 and got["meshes"] == 1, "the door is one mesh of its own: it goes to the Control room"
    assert got["door"] == [True, True, True, True, True], "R-42: the door stands in the left wall's opening, 2.1 to 2.3 units tall of the room"
    assert got["anchors"] == [True, True, True], "the label is over the door's middle"
    assert ["door-label", "door", "Control room"] in got["labels"], "the door carries the label `Control room` (an HTML label)"
    assert got["tips"] == ["agent", "desk", "lobby-door", "tasks", "tray"], "the owl, the board, the bookcase and the door have their tooltips"
    scene = (SCENE / "world.js").read_text(encoding="utf-8")
    assert scene.count('id: "door-label"') == 1 and "if (room.door)" in scene


@needs_node
def test_the_tooltips_say_what_the_owl_the_board_and_the_bookcase_open(tmp_path):
    got = run_node(tmp_path, r"""
import { agentTip, asking, documentsTip, tasksTip } from "@JS@/scene/room-words.js";
console.log(JSON.stringify({
  agent: [agentTip("Brand · waiting for you", true), agentTip("Brand · waiting for you", false), agentTip("", true), agentTip(undefined, false)],
  tasks: [tasksTip(["run", "left"]), tasksTip(["done", "left"]), tasksTip(["done", "done", "run", "left", "left", "left"]), tasksTip([]), tasksTip(null), tasksTip(["done"]),
    tasksTip(["done", "fail", "left"]), tasksTip(["done", "left", "left"], 1), tasksTip(["fail"], 0), tasksTip(["left"], 0)],
  documents: [documentsTip(7), documentsTip(14), documentsTip(0), documentsTip(null), documentsTip(undefined)],
  asking: [asking({ state: "waiting", decisions: 2 }), asking({ state: "waiting", decisions: 0 }), asking({ state: "working", decisions: 2 }), asking({ state: "off", decisions: 1 })],
}));
""")
    assert got["agent"] == ["Brand · waiting for you · open the Inbox", "Brand · waiting for you", "open the Inbox", ""], "the owl names its agent and its state, and where a click goes when it asks something (the page's words)"
    assert got["tasks"] == ["Tasks · 1 running, 1 left", "Tasks · 1 done, 1 left", "Tasks · 2 done, 1 running, 3 left", "Tasks · none yet", "Tasks · none yet", "Tasks · 1 done",
                          "Tasks · 1 done, 1 left, 1 failed", "Tasks · 1 done, 1 left", "Tasks · 1 failed", "Tasks · none yet"], \
        "the board counts its notes by state, as the page's tooltips do; `left` is the plate's own number when it is given, and a failed task is counted apart"
    assert got["documents"] == ["Documents · 7", "Documents · 14", "Documents · none yet", "Documents", "Documents"], "the bookcase counts its documents"
    assert got["asking"] == [True, False, False, False], "an owl asks when its agent waits and has a decision open"
    words = re.sub(r"//.*", "", (SCENE / "room-words.js").read_text(encoding="utf-8"))
    assert "document." not in words and "window" not in words and "import" not in words, "pure: no page, no library"


# --- the engine: brackets by hover, a tooltip over the object, the dim of a project not accepted -----------------------------------------------------

@needs_node
def test_the_engine_shows_the_brackets_of_the_object_under_the_pointer_or_the_focus_and_dims_a_project_that_is_not_accepted(tmp_path):
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
const canvas = engine.canvas;
const out = {};
const room = (state) => worldModel(snapshot, NOW, { selectedId: A, focus: A, floor: "engineering", room: { tips: { agent: "Engineering · working" }, board: { title: "t", lines: [], dot: "theme" }, door: false }, documents: [] });
engine.show("world", room(), "Floor");
out.start = canvas.wbMarks();
engine.highlight("tasks");
out.tasks = canvas.wbMarks();
engine.highlight("agent", "keyboard");
out.agent = canvas.wbMarks();
out.keyboard = [engine.hasSelection(), engine.hasHover()];
engine.clearSelection();
out.cleared = canvas.wbMarks();
engine.highlight("desk");
out.desk = canvas.wbMarks();
engine.clearHover();
out.none = canvas.wbMarks();
out.dim = canvas.classList.contains("is-dim");
// a project that is not accepted: the same room, dimmed
const dead = JSON.parse(JSON.stringify(room()));
dead.lots[0].accepted = false;
engine.show("world", dead, "Floor");
out.dimmed = canvas.classList.contains("is-dim");
engine.show("world", room(), "Floor");
out.undimmed = canvas.classList.contains("is-dim");
// the Building: a floor wears the brackets of its room
engine.show("world", worldModel(snapshot, NOW, { selectedId: A, focus: A, documents: [] }), "Building");
out.building = canvas.wbMarks().map(([id]) => id);
engine.highlight("floor:engineering");
out.floor = canvas.wbMarks().filter(([, shown]) => shown).map(([id]) => id);
out.stats = Object.keys(canvas.wbStats()).includes("drawCalls");
console.log(JSON.stringify(out));
""")
    assert got["start"] == [["agent", False], ["tasks", False], ["desk", False]] and got["none"] == got["start"], "built hidden: no standing brackets"
    assert got["tasks"] == [["agent", False], ["tasks", True], ["desk", False]], "R-31: the pointer on the board marks the board"
    assert got["agent"] == [["agent", True], ["tasks", False], ["desk", False]] and got["keyboard"] == [True, True], "the focus on a row marks the same object, and it is a selection Escape clears"
    assert got["cleared"] == got["start"] and got["desk"] == [["agent", False], ["tasks", False], ["desk", True]], "one object at a time"
    assert got["dim"] is False and got["dimmed"] is True and got["undimmed"] is False, "R-26: a project that is not accepted draws the whole scene at 55 percent (the canvas's class)"
    assert got["building"][-1].startswith("floor:") and got["floor"] == ["floor:engineering"], "R-28: a floor of the Building wears the brackets of its room"
    engine_text = (SCENE / "engine.js").read_text(encoding="utf-8")
    css = (INTERFACE / "scene.css").read_text(encoding="utf-8")
    assert 'tooltip.classList.toggle("is-above", Boolean(above))' in engine_text and "result.hit.anchor ? project(result.hit.anchor)" in engine_text, "the tooltip of a room's object stands over it; a building's follows the pointer"
    assert ".wb-tooltip.pui-tooltip.is-above" in css and "background-color: var(--pui-text)" in css and "color: var(--pui-bg)" in css, "R-31: the dark tooltip"
    assert ".wb-canvas.is-dim { opacity: 0.55; }" in css, "the page's 55 percent"


@needs_node
def test_the_focus_on_a_quiet_projects_row_opens_its_dot_into_its_card_as_the_pointer_does(tmp_path):
    # C-7 (R4-A2): among three or more projects a quiet one is a dot until it is pointed at or followed; the keyboard twin list's row takes the project as the hovered one
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + WORLD_JS + r"""
import { all } from "@FAKE@";
const { createEngine } = await import("@JS@/scene/engine.js");
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
const quiet = (id) => lot(id, { decisions: 0, runningTask: null });
engine.show("world", model({ lots: [quiet("a"), quiet("b"), quiet("c")] }), "City");
const pill = (id) => all(host, ".wb-pill").find((n) => n.children.some((c) => c.textContent === id));
const classes = () => ["a", "b", "c"].map((id) => pill(id).cls().filter((k) => k.startsWith("is-")).sort());
const out = { start: classes() };
engine.highlight("b", "keyboard");
out.focused = classes();
out.selection = [engine.hasSelection(), engine.hasHover()];
engine.highlight(null, "keyboard");
out.blurred = classes();
engine.highlight("c");
out.pointed = classes();
engine.clearHover();
// the card is measured again when it opens: the label's box is the card's, not the dot's
const node = pill("a");
node.offsetWidth = 10; node.offsetHeight = 10;
engine.highlight("a", "keyboard");
out.measured = [node.offsetWidth, all(host, ".wb-pill").length];
console.log(JSON.stringify(out));
""")
    assert got["start"] == [["is-quiet"]] * 3, "three quiet projects: three dots"
    assert got["focused"] == [["is-quiet"], ["is-quiet", "is-selected"], ["is-quiet"]], "the focus on the row of project b opens b's dot"
    assert got["selection"] == [True, True] and got["blurred"] == got["start"], "it is a keyboard selection, and it closes with the focus"
    assert got["pointed"] == [["is-quiet"], ["is-quiet"], ["is-quiet", "is-selected"]], "the pointer does the same"
    assert got["measured"][1] == 3
    labels = (SCENE / "labels.js").read_text(encoding="utf-8")
    assert "is-quiet" in labels and "spec.quiet" in labels


# --- a room made again frees what it made ---------------------------------------------------------------------------------------------------------

@needs_node
def test_a_room_made_again_frees_every_geometry_and_material_it_made(tmp_path):
    got = run_node(tmp_path, ROOMS_JS + r"""
const made = new Set(); const gone = new Set(); const mats = new Set(); const matGone = new Set();
const setAttribute = THREE.BufferGeometry.prototype.setAttribute; const dispose = THREE.BufferGeometry.prototype.dispose;
THREE.BufferGeometry.prototype.setAttribute = function (...a) { made.add(this); return setAttribute.apply(this, a); };
THREE.BufferGeometry.prototype.dispose = function () { gone.add(this); return dispose.call(this); };
const matDispose = THREE.Material.prototype.dispose;
THREE.Material.prototype.dispose = function () { matGone.add(this); return matDispose.call(this); };
const kit = createKit(palette);
const floors = (state) => ["planning", "business"].map((name, i) => ({ ...lot("a").floors[i], name, state: i ? state : "idle", window: i && state !== "idle" ? "lit" : "grey" }));
const world = buildWorld(kit, model({ lots: [lot("a", { floors: floors("idle") }), lot("b")] }));
world.setFocus("a", true);
const live = () => { const out = new Set(); world.group.traverse((n) => { if (n.geometry) out.add(n.geometry); }); return out; };
const leaked = () => { const alive = live(); return [...made].filter((g) => !gone.has(g) && !alive.has(g) && g !== kit.unitBox && g !== kit.unitEdges).length; };
const owlMaterials = () => { const out = new Set(); world.group.traverse((n) => { if (n.material && n.material.isMeshBasicMaterial && n.material !== kit.vertexMaterial) out.add(n.material); }); return out; };
const out = { start: leaked(), liveBefore: live().size };
const states = ["working", "waiting", "idle", "off", "working", "waiting", "idle", "working"];
const seen = new Set();
for (const state of states) {
  for (const m of owlMaterials()) seen.add(m);
  world.update(JSON.parse(JSON.stringify(model({ focus: "a", lots: [lot("a", { floors: floors(state) }), lot("b")] }))));   // a state change makes the room again
  for (const m of owlMaterials()) seen.add(m);
}
out.after = leaked();
out.liveAfter = live().size;
out.oldMaterialsFreed = [...seen].filter((m) => !owlMaterials().has(m)).every((m) => matGone.has(m));
out.rooms = states.length;
// documents arriving and tasks changing swap the geometry of the board and the bookcase: nothing is left behind
for (const documents of [3, 20, 40, 5, 0]) world.update(JSON.parse(JSON.stringify(model({ focus: "a", lots: [lot("a", { floors: floors("idle").map((f) => ({ ...f, documents, notes: ["done", "run"] })) }), lot("b")] }))));
out.afterDocuments = leaked();
console.log(JSON.stringify(out));
""")
    assert got["start"] == 0 and got["after"] == 0 and got["afterDocuments"] == 0, "no geometry of a room that was made again, or of a bookcase or board that was made again, stays undisposed"
    assert got["liveAfter"] <= got["liveBefore"] + 12, "and the live ones do not pile up with each rebuild"
    assert got["oldMaterialsFreed"] is True, "the owl's materials of a pose that was left are freed"


# --- the City's framing -------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_city_is_framed_on_its_buildings_as_large_as_the_page_draws_them(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
import { fitFrustum } from "@JS@/scene/fit.js";
import { createCamera, boundsOfBox } from "@JS@/scene/rig.js";
import { lotAt } from "@JS@/scene/city.js";
import { lotBox, towerBox } from "@JS@/scene/tower.js";
const out = {};
const camera = createCamera(THREE);
const size = { w: 1280, h: 800 };
const ins = { left: 240, right: 16, top: 68, bottom: 215, pad: 1.04 };
const ppu = (f) => size.w / (f.right - f.left);
const fit = (n, cap) => { const box = new THREE.Box3(); for (let i = 0; i < n; i++) { const { x, z } = lotAt(i, n); box.union(lotBox(THREE, x, z, 6)); } return ppu(fitFrustum(boundsOfBox(THREE, camera, box), size, ins, 1.04, cap)); };
const cap = 212 / ((7.1 + 5.5) * Math.SQRT1_2);
out.cap = cap;
out.free = [1, 2, 3, 4, 5].map((n) => Math.round(fit(n) * 10) / 10);
out.capped = [1, 2, 3].map((n) => Math.round(fit(n, cap) * 10) / 10);
// the box of a lot: the footprint with its ledges and canopy, and the roof; nothing of the beacon or the porch's margin
const lb = lotBox(THREE, 0, 0, 6); const tb = towerBox(THREE, 0, 0, 6, 0);
const near = (a, b) => Math.abs(a - b) < 1e-9;
out.box = [near(lb.min.x, -3.55), near(lb.max.x, 3.55), near(lb.min.z, -2.75), lb.max.y < tb.max.y, lb.max.z < tb.max.z, lb.max.x < tb.max.x];
// the world's own cap: the City only, scaled with the canvas
const { world } = make();
out.zoomCap = [world.zoomCap({ w: 1280, h: 800 }), world.zoomCap({ w: 375, h: 616 }), world.zoomCap({ w: 1024, h: 640 }), world.zoomCap({ w: 2560, h: 1600 })].map((v) => Math.round(v * 100) / 100);
world.setFocus("a", true);
out.zoomCapOpen = world.zoomCap({ w: 1280, h: 800 });
// the City's subject is the buildings' own boxes, with no margin
world.setFocus(null, true);
const subject = world.subject();
const expected = new THREE.Box3();
[0, 1, 2].forEach((i) => { const { x, z } = lotAt(i, 3); expected.union(lotBox(THREE, x, z, 4)); });
out.subject = subject.min.distanceTo(expected.min) < 1e-9 && subject.max.distanceTo(expected.max) < 1e-9;
// fitFrustum without a cap is as it was
out.unchanged = (() => { const b = { x0: -5, x1: 5, y0: -3, y1: 3 }; const a = fitFrustum(b, size, {}, 1.04); const c = fitFrustum(b, size, {}, 1.04, undefined); const z = fitFrustum(b, size, {}, 1.04, 0); return JSON.stringify(a) === JSON.stringify(c) && JSON.stringify(a) === JSON.stringify(z); })();
// a cap stops the zoom: a small subject stays as large as it is drawn, and stays centred in the free rectangle
const tiny = fitFrustum({ x0: -1, x1: 1, y0: -1, y1: 1 }, size, { left: 200, right: 0, top: 0, bottom: 0 }, 1, 20);
out.tiny = [Math.round(ppu(tiny) * 100) / 100, Math.abs((tiny.left + tiny.right) / 2 - (-(200 / 2) / 20)) < 1e-9];
console.log(JSON.stringify(out));
""")
    assert abs(got["cap"] - 23.8) < 0.05, "the page's City at 1280 by 800: a building's ledge, 7.1 by 5.5 units, is 212 px across"
    assert got["free"][1] > 21 and got["free"][0] > got["cap"], "with the frame's insets two buildings stand about as large as the page draws them, one would stand larger, and more are smaller"
    assert got["capped"][0] == round(got["cap"], 1) and got["capped"][1] <= round(got["cap"], 1) + 0.1 and got["capped"][2] < got["capped"][1], "but never larger than the page draws one, and the more buildings the smaller"
    assert got["box"] == [True] * 6, "a lot's box has no margin of its own: its footprint, its canopy and its roof"
    assert got["zoomCap"] == [round(got["cap"], 2), round(got["cap"] * 0.75, 2), round(got["cap"] * 0.8, 2), round(got["cap"] * 2, 2)] and got["zoomCapOpen"] is None, \
        "scaled with the canvas, down to three quarters of it (what the page's phone frames draw), in the City only"
    assert got["subject"] is True and got["unchanged"] is True and got["tiny"] == [20, True], "a cap only stops the zoom, and the subject stays in the middle of the free rectangle"
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "content.zoomCap ? content.zoomCap(size) : null" in engine and "insets.pad || 1.04, cap)" in engine, "the engine fits with the frame's insets and the cap"


# --- what feeds the room ------------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_board_gets_a_note_for_each_task_of_the_followed_request_and_the_bookcase_the_count_of_the_documents(tmp_path):
    got = run_node(tmp_path, WORLD_JS + PRODUCT_JS + r"""
const floorOf = (m, name) => m.lots[0].floors.find((f) => f.name === name);
const unread = models.building(null);
const read = models.building(DOCS);
const out = {};
out.notes = Object.fromEntries(["marketing", "brand", "engineering", "planning", "design"].map((n) => [n, floorOf(read, n) ? floorOf(read, n).notes : "none"]));
out.documents = Object.fromEntries(["engineering", "marketing", "brand", "planning", "design"].map((n) => [n, floorOf(read, n) ? floorOf(read, n).documents : "none"]));
out.unread = [floorOf(unread, "engineering").documents, floorOf(unread, "engineering").notes.length];
// the floor's own words (the Floor and the Lobby): their count replaces the snapshot's, and when they say none the snapshot's stays
const own = models.floor(DOCS, "engineering");
out.floor = [floorOf(own, "engineering").documents];
const withRoom = worldModel(snapshot, NOW, { selectedId: A, focus: A, floor: "planning", room: { documents: 21, state: "idle", window: "grey", decisions: 0, tips: {}, board: null, door: true }, documents: DOCS });
out.lobby = [floorOf(withRoom, "planning").documents, floorOf(withRoom, "engineering").documents];
console.log(JSON.stringify(out));
""")
    assert got["notes"] == {"marketing": ["done", "done", "left"], "brand": ["left"], "engineering": ["run"], "planning": [], "design": []}, \
        "R-23b: one note for each task of the agent in the followed request: running is run, done is done, failed is fail, anything else still to do"
    assert got["documents"]["engineering"] == 3 and got["documents"]["marketing"] == 1 and got["documents"]["planning"] == 1 and got["documents"]["design"] == 0, "R-23: a binder for each document of the agent"
    assert got["unread"] == [None, 1], "documents not read yet are unknown, not none: the world keeps what the bookcase shows"
    assert got["floor"] == [3] and got["lobby"] == [21, 3], "the room's own count replaces the floor's"
    model_js = (JS / "floor-model.js").read_text(encoding="utf-8")
    assert 't.state === "done" ? "done" : t.state === "running" ? "run" : t.state === "failed" ? "fail" : "left"' in model_js and 't.state !== "cancelled"' in model_js, \
        "a cancelled task has no note; a failed one has the error tone's (R-23b: the page's three states, and a failed note is the state rule)"
    lobby = (JS / "views" / "lobby-model.js").read_text(encoding="utf-8")
    assert "documents: docs ? docs.length : null" in lobby, "the Lobby's room says how many documents the Desk lists"


@needs_node
def test_the_floor_and_the_lobby_keep_the_streets_and_the_other_buildings_go_when_everything_has_settled(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const { world } = make();
world.setFocus("a", true);
world.setFloors("business", null, true);
world.hideSurroundings(true);
const ground = world.group.children[0];
out0();
function out0() {}
const out = { ground: ground.visible, others: ["b", "c"].map((id) => world.towers.get(id).root.visible), own: world.towers.get("a").root.visible };
world.hideSurroundings(false);
out.back = ["b", "c"].map((id) => world.towers.get(id).root.visible);
console.log(JSON.stringify(out));
""")
    assert got["ground"] is True and got["others"] == [False, False] and got["own"] is True and got["back"] == [True, True], \
        "the round's pages draw the streets and the parks round the room (floor.html, lobby.html): only the other buildings are put away"


# --- the review of the package: fixes with their probes ---------------------------------------------------------------------------------------------

@needs_node
def test_the_brackets_of_an_object_that_is_no_longer_one_are_put_away_through_the_whole_sequence(tmp_path):
    # F1: hover a floor, open it, point at the owl, leave: the room's brackets never stay round the Floor's room, and the owl's never stay after Back
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0 }), onOpen() {}, onHover() {} });
const shown = () => { let n = 0; globalThis.__scene.traverse((o) => { if (o.userData && o.userData.brackets) { let p = o, vis = true; while (p) { if (!p.visible) vis = false; p = p.parent; } if (vis) n += 1; } }); return n; };
const settle = () => { for (let i = 0; i < 6; i++) frame(40); };
const building = worldModel(snapshot, NOW, { selectedId: A, focus: A, documents: [] });
const room = worldModel(snapshot, NOW, { selectedId: A, focus: A, floor: "engineering", room: { tips: { agent: "Engineering" }, board: { title: "t", lines: [], dot: "theme" }, door: false }, documents: [] });
const out = {};
engine.show("world", building, "Building"); settle();
out.building = shown();
engine.highlight("floor:engineering"); out.floorHover = shown();
engine.show("world", room, "Floor"); settle(); out.afterOpen = shown();
engine.highlight("agent"); out.agentHover = shown();
engine.highlight(null); out.cleared = shown();
engine.highlight("tasks");
engine.show("world", building, "Building"); settle(); out.afterBack = shown();
engine.highlight(null); out.end = shown();
console.log(JSON.stringify(out));
""")
    assert got == {"building": 0, "floorHover": 1, "afterOpen": 0, "agentHover": 1, "cleared": 0, "afterBack": 0, "end": 0}, \
        "the brackets of a hit that disappears (a floor that opened, the owl after Back) are put away when the hits are made again"


@needs_node
def test_the_brackets_of_a_floor_are_drawn_never_picked(tmp_path):
    # F5: the Building's room brackets live inside the floor's hit object; once shown they must not be a part of what the pointer meets
    got = run_node(tmp_path, ROOMS_JS + r"""
import { pickList } from "@JS@/scene/pick.js";
const kit = createKit(palette);
const world = buildWorld(kit, model({ focus: "a" }));
world.setFocus("a", true);
const ownedByMarks = () => { const list = pickList(world.hits); return list.meshes.filter((m) => { for (let p = m; p; p = p.parent) if (p.userData && p.userData.brackets) return true; return false; }).length; };
const total = () => pickList(world.hits).meshes.length;
const out = { hidden: [ownedByMarks(), total()] };
for (const hit of world.hits) if (hit.marks) hit.marks.visible = true;
out.shown = [ownedByMarks(), total()];
out.groups = world.hits.filter((h) => h.marks).map((h) => Boolean(h.marks.userData.brackets));
console.log(JSON.stringify(out));
""")
    assert got["hidden"][0] == 0 and got["shown"] == [0, got["hidden"][1]], "a shown bracket mesh is no pickable mesh: the pick list is the same with every bracket shown"
    assert got["groups"] and all(got["groups"]), "every group of brackets a hit holds is flagged (userData.brackets)"


@needs_node
def test_a_tooltips_anchor_is_where_the_object_stands_after_a_rebuild_and_the_box_stays_inside_the_canvas(tmp_path):
    # F3: the anchor reads the world matrices, brought up to date first (a room made a moment ago has not been rendered); F9: the box is kept in the canvas
    got = run_node(tmp_path, ROOMS_JS + r"""
import { tooltipPlace } from "@JS@/scene/room-words.js";
const kit = createKit(palette); const scene = new THREE.Scene();
const R = { tips: { agent: "x" } };
const floors = (state) => ["planning", "business", "design", "engineering"].map((name, i) => ({ ...lot("a").floors[i], name, state: name === "design" ? state : "idle" }));
const world = buildWorld(kit, model({ focus: "a", floor: "design", room: R, lots: [lot("a", { floors: floors("waiting") }), lot("b")] }));
scene.add(world.group);
world.setFocus("a", true); world.setFloors("design", null, true);
const worst = () => { scene.updateMatrixWorld(true); let d = 0; for (const hit of world.hits) { if (!hit.anchor) continue; const box = new THREE.Box3().setFromObject(hit.object); const real = new THREE.Vector3((box.min.x + box.max.x) / 2, box.max.y, (box.min.z + box.max.z) / 2); d = Math.max(d, hit.anchor.distanceTo(real)); } return Math.round(d * 1e6) / 1e6; };
const out = { ids: world.hits.map((h) => h.id), built: worst() };
world.update(JSON.parse(JSON.stringify(model({ focus: "a", floor: "design", room: R, lots: [lot("a", { floors: floors("working") }), lot("b")] }))));   // a state change makes the room again, nothing rendered between
out.rebuilt = worst();
out.ids2 = world.hits.map((h) => h.id);
out.place = {
  middle: tooltipPlace({ above: { x: 400, y: 300 }, size: { w: 800, h: 600 }, wide: 120, tall: 24 }),
  left: tooltipPlace({ above: { x: 10, y: 300 }, size: { w: 800, h: 600 }, wide: 120, tall: 24 }),
  right: tooltipPlace({ above: { x: 795, y: 300 }, size: { w: 800, h: 600 }, wide: 120, tall: 24 }),
  top: tooltipPlace({ above: { x: 400, y: 5 }, size: { w: 800, h: 600 }, wide: 120, tall: 24 }),
  narrow: tooltipPlace({ above: { x: 20, y: 300 }, size: { w: 100, h: 600 }, wide: 120, tall: 24 }),
  pointer: tooltipPlace({ at: { x: 700, y: 100 }, size: { w: 800, h: 600 }, wide: 120, tall: 24 }),
};
console.log(JSON.stringify(out));
""")
    assert "tasks" in got["ids"] and got["built"] == 0 and got["rebuilt"] == 0 and got["ids2"] == ["agent", "tasks", "desk"], "F3: every anchor is the top of its object's box, also straight after a room was made again"
    place = got["place"]
    assert place["middle"] == {"x": 400, "y": 300}, "inside: as it is"
    assert place["left"]["x"] == 64 and place["right"]["x"] == 736, "an object at a side moves its box in by half its width and the margin"
    assert place["top"]["y"] == 38 and place["narrow"]["x"] == 64, "an object at the top lets the box down under the top edge; a canvas narrower than the box centres it as far as it can"
    assert place["pointer"] == {"x": 714, "y": 116}, "at the pointer: to its right and low, as before"
    engine_text = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "tooltipPlace({ above, at: result, size" in engine_text, "the engine places the tooltip with it"
    world_text = (SCENE / "world.js").read_text(encoding="utf-8")
    assert "object.updateWorldMatrix(true, true)" in world_text.split("function topOf")[1][:400], "topOf brings the matrices up to date first, as pick.js does"


@needs_node
def test_the_city_ticks_no_owl_after_a_visit_and_a_failed_task_has_the_error_tones_note(tmp_path):
    # F4: the owls' motions belong to the open room only; F7: the failed note
    got = run_node(tmp_path, ROOMS_JS + r"""
const kit = createKit(palette);
const plain = (id) => lot(id, { floors: ["planning", "business", "design", "engineering"].map((n, i) => ({ ...lot(id).floors[i], name: n, state: n === "planning" ? "idle" : "working", window: "lit" })) });
const world = buildWorld(kit, model({ lots: [plain("a"), plain("b")] }));
const out = { city: world.motions.length };
world.setFocus("a", true);
out.open = world.motions.length;
world.setFocus(null, true);
out.again = world.motions.length;
world.setFocus("b", true);
out.other = world.motions.length;
world.setFocus(null, false);
out.closing = world.motions.length;
for (let i = 0; i < 400; i++) world.step ? world.step(0.05) : world.tick && world.tick(0.05);
const tones = roomTones(palette);
out.tones = Object.keys(tones.note);
out.distinct = new Set(Object.values(tones.note).map((c) => c.getHexString())).size;
out.fold = Object.keys(tones.noteFold); out.line = Object.keys(tones.noteLine);
console.log(JSON.stringify(out));
""")
    assert got["open"] > got["city"] and got["again"] == got["city"], "the City's motions return to its own (the shadows) after a visit: the owls tick only in the open room"
    assert got["other"] > got["city"] and got["closing"] >= got["city"]
    assert got["tones"] == ["done", "run", "left", "fail"] and got["distinct"] == 4 and got["fold"] == got["tones"] and got["line"] == got["tones"], "a failed note has its own tone, fold and lines"


# --- the files ----------------------------------------------------------------------------------------------------------------------------------------

def test_the_rooms_hold_no_colour_literal_no_text_and_nothing_of_the_old_room():
    for name in ("building.js", "furniture.js", "room-frame.js", "room-words.js", "owl-build.js", "owl-motion.js", "marks.js"):
        text = (SCENE / name).read_text(encoding="utf-8")
        assert not re.search(r"#[0-9A-Fa-f]{6}\b|0x[0-9A-Fa-f]{6}\b|rgb\(|hsl\(", text), f"{name} writes no colour: the tones are the palette's, the owl's six are owl.js's"
        assert "fillText" not in text and "CanvasTexture" not in text and "TextGeometry" not in text, f"{name}: text is HTML, never drawn in the scene"
    assert not (SCENE / "figure.js").exists(), "R-24 and R-41: the low-poly figure is gone, the agent is the owl"
    room = (SCENE / "building.js").read_text(encoding="utf-8") + (SCENE / "furniture.js").read_text(encoding="utf-8")
    for old in ("tray(", "table(", "cabinet(", "wallLamp", "plant(", "counter(", "bookshelf(", "figure("):
        assert old not in room, f"R-23: no {old} in the room (no tray, no table of sheets, no plants, no lamp, no counter)"
    assert "kit.box(" not in room and "kit.cyl(" not in room, "the room is drawn in batches (one draw call for its still parts), not a mesh for each box"
    css = (INTERFACE / "scene.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", css), "scene.css writes no colour literal"


# --- a project that stops being accepted keeps the size of its open building (R4-B4) ------------------------------------------------------------------

@needs_node
def test_the_open_tower_of_a_project_that_stops_being_accepted_stays_open_and_unsquashed_with_every_floor_dark(tmp_path):
    # R4-A3 saw a small tower and called it squashed like a closed one. It is not: the tower keeps its progress and its pitch (B1-1's squash is for a closed tower only);
    # what shrank was the camera's fit (see the next test)
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
const { createEngine } = await import("@JS@/scene/engine.js");
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: () => ({ left: 0, right: 0, top: 0, bottom: 0, pad: 1.04 }), onOpen() {}, onHover() {} });
const canvas = engine.canvas;
const run = (n) => { for (let i = 0; i < n; i++) frame(1000 / 30); };
const shop = () => {
  const roots = [];
  globalThis.__scene.traverse((o) => { if (o.isGroup && o.children.length === 2 && o.children[0].isGroup && o.children[1].isGroup && o.children[0].children.length >= 5) roots.push(o); });
  const g = roots.sort((a, b) => a.children[0].position.x - b.children[0].position.x)[0].children[0];   // the first lot's tower (the shop, at the City's west)
  return { sy: +g.scale.y.toFixed(3), py: +g.position.y.toFixed(3), pitch: +(g.children.filter((f) => f.isGroup && f.children.length > 1).map((f) => f.position.y).reduce((a, y, i, l) => (i ? Math.max(a, y - l[i - 1]) : a), 0)).toFixed(3) };
};
engine.show("world", models.city(), "City");
run(10);
engine.flyTo(A);
engine.show("world", models.building(null), "Building");
run(150);
const out = { open: shop(), towers: canvas.wbStats().towers[A], dim: canvas.classList.contains("is-dim") };
snapshot.projects[0].config.accepted = false;
engine.show("world", models.building(DOCS), "Building");
run(150);
out.after = shop();
out.towersAfter = canvas.wbStats().towers[A];
out.dimAfter = canvas.classList.contains("is-dim");
console.log(JSON.stringify(out));
""")
    assert got["towers"] == 1 and got["towersAfter"] == 1, "the building stays open when its project stops being accepted"
    assert got["open"] == got["after"] and got["after"]["sy"] == 1, "its height is the open one, not the closed squash of 0.64 (B1-1)"
    assert got["dim"] is False and got["dimAfter"] is True, "R-26: the same open tower, the whole drawing at 55 percent"


@needs_node
def test_the_engine_says_when_its_drawing_is_dimmed_and_the_building_then_fits_as_if_the_notice_band_were_not_there(tmp_path):
    # the cause of R4-A3's small tower: the notice band over the scene was an obstacle of the camera's fit, 357 px at the top, and the open tower was fitted under it
    got = run_node_engine(tmp_path, ENGINE_PAGE_JS + PRODUCT_JS + r"""
import { createFrame } from "@JS@/frame/frame.js";
const { createEngine } = await import("@JS@/scene/engine.js");
const calls = [];
const host = document.createElement("div");
const engine = createEngine(host, { label: "scene", getInsets: (about) => { calls.push(about ? about.dim : "none"); return { left: 0, right: 0, top: 0, bottom: 0, pad: 1.04 }; }, onOpen() {}, onHover() {} });
engine.show("world", models.building(null), "Building");
const accepted = calls.slice();
calls.length = 0;
snapshot.projects[0].config.accepted = false;
engine.show("world", models.building(DOCS), "Building");
const dimmed = calls.slice();
// the frame: a band 620 by 273 px over the scene's top; the insets with and without it
const root = document.createElement("div");
const fr = createFrame(root, { onSelectProject() {}, onForgetToken() {}, onRetry() {} });
fr.notice({ kind: "error", lead: "shop is not accepted yet", text: "read the file" });
fr.noticeBox.getBoundingClientRect = () => ({ left: 236, top: 72, right: 856, bottom: 345, width: 620, height: 273 });
const out = { accepted, dimmed, withBand: fr.insets(null).top, defaultBand: fr.insets(null, {}).top, ignoredBand: fr.insets(null, { notice: false }).top };
console.log(JSON.stringify(out));
""")
    assert set(got["accepted"]) == {False} and set(got["dimmed"]) == {True}, "the engine tells getInsets whether the drawing is dimmed (a project that is not accepted), every time it reads them"
    assert got["withBand"] == got["defaultBand"] == 357, "every other screen: the band is an obstacle, 345 px to its foot and 12 of air"
    assert got["ignoredBand"] == 16, "asked not to count the band, the frame keeps its 16 px margin"
    building = (JS / "views" / "building.js").read_text(encoding="utf-8")
    assert "getInsets: (about) =>" in building and "frame.insets(panel, { notice: !(about && about.dim) })" in building, "the Building does not fit its dimmed tower under the band: building.html draws the band over it"


# --- one bookcase in every room, the board always whole (M-7) ----------------------------------------------------------------------------------

@needs_node
def test_every_room_has_one_bookcase_of_sixteen_binders_at_most_and_the_full_board_on_a_floor_and_in_the_lobby(tmp_path):
    # M-6/M-7 (the maintainer): "the bookcase is only an object for interaction"; B2-4 (a board of six, then two, beside more bookcases) and B2-5 (48 binders) are superseded
    got = run_node(tmp_path, ROOMS_JS + r"""
const out = {};
const room = (lobby, documents, notes) => {
  const floors = [lot("a").floors[0], lot("a").floors[3]].map((f, i) => ({ ...f, name: i ? "engineering" : "planning", lobby: i === 0, documents, notes }));
  const { world } = make({ lots: [lot("a", { floors }), lot("b"), lot("c")] });
  world.setFocus("a", true);
  const parts = world.towers.get("a").parts[lobby ? 0 : 1];
  const shelfMesh = parts.shelf.children[0];
  return { lobby: Boolean(parts.door), binders: parts.binders, notes: parts.notesShown, shelves: parts.shelf.children.length, vertices: shelfMesh.geometry.getAttribute("position").count, capacity: parts.capacity() };
};
const many = Array(30).fill("left");
for (const documents of [0, 16, 38, 100]) {
  out[`floor${documents}`] = room(false, documents, many);
  out[`lobby${documents}`] = room(true, documents, many);
}
console.log(JSON.stringify(out));
""")
    for kind in ("floor", "lobby"):
        for documents in (0, 16, 38, 100):
            r = got[f"{kind}{documents}"]
            assert r["lobby"] is (kind == "lobby"), "the Lobby's room has its door, the floor's has none"
            assert r["binders"] == min(documents, 16) and r["shelves"] == 1, f"{kind} with {documents} documents: one bookcase, at most 16 binders (M-7)"
            assert r["notes"] == 12 and r["capacity"] == 12, f"{kind} with {documents} documents: the board holds its twelve notes (M-7)"
    for kind in ("floor", "lobby"):
        assert got[f"{kind}16"]["vertices"] == got[f"{kind}38"]["vertices"] == got[f"{kind}100"]["vertices"], "past sixteen documents the bookcase does not grow: it is the same drawing"
        assert got[f"{kind}0"]["vertices"] < got[f"{kind}16"]["vertices"], "an empty bookcase has no binders"


# --- two potted plants in every room, not in the server room (A-45, M-6) -------------------------------------------------------------------------

PLANTS_JS = ROOMS_JS + r"""
import { PLANTS, POT, CROWN, plants } from "@JS@/scene/plants.js";
import { createCamera } from "@JS@/scene/rig.js";
import { DOOR, SEAT } from "@JS@/scene/furniture.js";
const camera = createCamera(THREE);
// a box in page units as the camera sees it: [x0, x1, y0, y1] of its eight corners
const shadowOf = (x0, x1, y0, y1, z0, z1) => { const xs = []; const ys = []; for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) { const p = new THREE.Vector3(FRAME.X(x), FRAME.Y(y), FRAME.Z(z)).applyMatrix4(camera.matrixWorldInverse); xs.push(p.x); ys.push(p.y); } return [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]; };
const apart = (a, b) => a[1] <= b[0] || b[1] <= a[0] || a[3] <= b[2] || b[3] <= a[2];
"""


@needs_node
def test_every_room_has_two_potted_plants_in_its_one_still_mesh_in_the_tokens_never_picked_and_the_server_room_has_none(tmp_path):
    got = run_node(tmp_path, PLANTS_JS + r"""
const out = {};
const crownSet = (p) => new Set(cityTones(p).crown.map(hex));
const count = (mesh, set) => { const a = mesh.geometry.getAttribute("color"); let n = 0; for (let i = 0; i < a.count; i++) if (set.has(new THREE.Color(a.getX(i), a.getY(i), a.getZ(i)).getHexString())) n += 1; return n; };
const { world } = make({ lots: [lot("a"), lot("b"), lot("c")] });
world.setFocus("a", true);
const tower = world.towers.get("a");
// five floors' worth (the four of the fixture and every floor of it): two plants each, in the room's still mesh (the first mesh of the room; no mesh of its own)
out.crownVertices = tower.parts.map((p, i) => count(tower.inner[i].children[0].children[0], crownSet(palette)));
out.meshesPerRoom = tower.parts.map((p, i) => tower.inner[i].children[0].children.filter((n) => n.isMesh).length);
out.lobby = tower.parts.map((p) => Boolean(p.door));
// the plants are not an object of the room: none of the hits holds them, and no hit is the room's still mesh
world.setFloors("engineering", null, true);
const hitMeshes = world.hits.flatMap((h) => { const list = []; h.object.traverse((n) => { if (n.isMesh) list.push(n); }); return list; });
const still = tower.inner[tower.lot.floors.findIndex((f) => f.name === "engineering")].children[0].children[0];
out.hits = world.hits.map((h) => h.id).sort();
out.stillPicked = hitMeshes.includes(still);
// the colours are tokens: the crown is the trees' four tones, the pot a mix in roomTones, and both follow the palette
const t = roomTones(palette);
const dark = roomTones({ ...palette, dark: true });
out.tokens = [t.crown.every((v, i) => hex(v) === hex(cityTones(palette).crown[i])), ["top", "left", "right"].every((k) => t.pot[k].isColor), hex(t.pot.left) !== hex(dark.pot.left)];
// a plant's footprint: two plants, the pot a hair over the floor (the floor's own tone is what the floor's vertices say)
out.plants = [PLANTS.length, POT.sides, plants.length];
console.log(JSON.stringify(out));
""")
    assert got["crownVertices"] == [120] * 4, "two crowns of twenty facets in every room: 120 vertices in the trees' four tones, Lobby included"
    assert got["meshesPerRoom"] == [2] * 4, "a room's still mesh and its glass: the plants add no mesh and no draw call (they are in the still mesh)"
    assert got["stillPicked"] is False and "tasks" in got["hits"] and "desk" in got["hits"], "the ways in are picked; the still mesh, the plants with it, is not (not pickable, no tooltip)"
    assert got["tokens"] == [True, True, True], "the crown is the trees' tones, the pot a token mix that follows the palette"
    assert got["plants"][0] == 2 and got["plants"][1] == 6, "two plants, each a six-sided pot"
    plants_js = (SCENE / "plants.js").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(|0x[0-9a-fA-F]{6}", plants_js), "plants.js writes no colour literal"
    assert "castShadow" not in plants_js and "motion" not in plants_js.lower() and "userData" not in plants_js, "no real-time shadow, no animation, nothing for the pick"
    callers = [path.name for path in SCENE.glob("*.js") if "plants(" in path.read_text(encoding="utf-8") and path.name != "plants.js"]
    assert callers == ["building.js"], "only a floor's room plants: the server room (R-51 removed its plant) never calls it"


@needs_node
def test_the_plants_stand_against_the_window_wall_clear_of_the_owl_the_board_the_bookcase_and_the_lobbys_door(tmp_path):
    got = run_node(tmp_path, PLANTS_JS + r"""
const out = {};
// each plant's true silhouette: the convex hull of the vertices `plants()` draws for it, seen by the camera; the other objects' too (a box or a rectangle on a wall)
const hull = (points) => { const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]); const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); const lo = []; for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); } const up = []; for (const q of [...p].reverse()) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); } return [...lo.slice(0, -1), ...up.slice(0, -1)]; };
const onScreen = (list) => list.map(([x, y, z]) => { const p = new THREE.Vector3(FRAME.X(x), FRAME.Y(y), FRAME.Z(z)).applyMatrix4(camera.matrixWorldInverse); return [p.x, p.y]; });
const boxHull = (x0, x1, y0, y1, z0, z1) => hull(onScreen([x0, x1].flatMap((x) => [y0, y1].flatMap((y) => [z0, z1].map((z) => [x, y, z])))));
// the gap between two convex polygons along their edges' normals (negative when they overlap)
const gap = (A, B) => { let best = -1e9; for (const P of [A, B]) for (let i = 0; i < P.length; i++) { const a = P[i]; const b = P[(i + 1) % P.length]; const n = [b[1] - a[1], a[0] - b[0]]; const l = Math.hypot(...n); n[0] /= l; n[1] /= l; const pa = A.map((p) => p[0] * n[0] + p[1] * n[1]); const pb = B.map((p) => p[0] * n[0] + p[1] * n[1]); best = Math.max(best, Math.max(Math.min(...pb) - Math.max(...pa), Math.min(...pa) - Math.max(...pb))); } return best; };
const silhouette = (place) => { const kit = createKit(palette); const batch = kit.batch(); plants(THREE, pageBatch(batch, FRAME), FRAME, roomTones(palette), [place]); const mesh = batch.mesh(new THREE.Group()); const a = mesh.geometry.getAttribute("position"); const list = []; const v = new THREE.Vector3(); for (let i = 0; i < a.count; i++) { v.fromBufferAttribute(a, i).applyMatrix4(camera.matrixWorldInverse); list.push([v.x, v.y]); } return hull(list); };
const board = boxHull(0.535, 4.93, 0.565, 2.37, 0.2, 0.2);
const bookcase = boxHull(5.38, 6.83, 0, 2.2, 0.2, 0.82);
const door = boxHull(0.2, 0.2, 0, DOOR.top, DOOR.z0, DOOR.z1);
const owls = Object.values(SEAT.owl).map(([x, z]) => boxHull(x - 0.5, x + 0.5, 0, 1.4, z - 0.5, z + 0.5));
out.gaps = PLANTS.map((place) => { const s = silhouette(place); return { board: gap(s, board), bookcase: gap(s, bookcase), door: gap(s, door), owls: owls.map((o) => gap(s, o)) }; });
out.wall = PLANTS.map(([x]) => x);
out.ends = PLANTS.map(([, z]) => z);
console.log(JSON.stringify(out));
""")
    for r in got["gaps"]:
        assert min(r["board"], r["bookcase"], r["door"], *r["owls"]) > 0, "a plant covers neither the board of notes, nor the bookcase, nor the Lobby's door, nor the owl in any of its three places"
    assert all(x < 1.0 for x in got["wall"]), "against the left wall, the one that carries the windows"
    assert abs(got["ends"][0] - 0.916) < 0.3 and 4.976 < got["ends"][1] < 5.6, "one at the first end of the window run (z 0.916), one past its last end (z 4.976) and inside the room (5.6)"

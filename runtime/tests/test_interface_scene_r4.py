"""Tests of the City's scene in the style of round 4 (R4-B1): the low-poly City (R-16), the brackets of the followed building (R-17), the lit window (R-18),
the agent's shadow at the windows (R-19), the decision mark (R-20), what a floor's light means (R-21), the parser of path data (`svgpath.js`, R4D-2), the owl
module (`owl.js`, R-41) and the City's motions (`city-motion.js`).

No browser and no model: the pure modules run under Node when it is installed (the builders with the real three.js, no WebGL); what only a browser can show was
looked at in the browser pane by the package's report.

Run: uv run --with pytest==9.1.1 pytest runtime/tests/test_interface_scene_r4.py
"""
from __future__ import annotations

import re

import pytest

import standin_tree as st
from interface_css import css_paths
from test_interface_scene_round3 import WORLD_JS, needs_node, run_node

INTERFACE = st.REPO / "interface"
JS = INTERFACE / "js"
SCENE = JS / "scene"


# --- the parser of path data ----------------------------------------------------------------------------------------------------------

@needs_node
def test_the_path_parser_reads_every_command_the_owl_uses_in_absolute_and_relative_form_and_refuses_an_arc(tmp_path):
    got = run_node(tmp_path, r"""
import { parsePath, subpaths } from "@JS@/scene/svgpath.js";
const flat = (d) => parsePath(d).map((s) => [s.type, ...s.points.flat()]);
const out = {};
out.absolute = flat("M10 20 L30 40 H50 V60 C1 2 3 4 5 6 Q7 8 9 10 Z");
out.relative = flat("m10 20 l5 5 h5 v5 c1 1 2 2 3 3 q1 1 2 0 z");
out.implicit = flat("M0 0 10 10 20 0");                       // the pairs after a moveto are linetos
out.smooth = flat("M0 0 C0 10 10 10 10 0 S20 -10 20 0");      // the first control of S is the reflection of the last one of C
out.quad = flat("M0 0 Q5 10 10 0 T20 0");                      // and of T, for a quadratic
out.chain = flat("M76 156 q6 6 12 0 q6 6 12 0");               // the owl's feathers: relative curves from the point the last one ended on
out.numbers = flat("M-1.5-2.5L.5,.25e1");                      // signs, a leading point, a comma, an exponent
out.closeBack = flat("M5 5 L10 5 L10 10 Z l1 1");              // a relative command after Z starts from the subpath's first point
out.smoothRel = flat("M0 0 c0 10 10 10 10 0 s10 -10 10 0");    // relative S: the reflected first control, the others from the current point
out.quadRel = flat("M0 0 q5 10 10 0 t10 0");                   // relative T
out.afterZ = flat("M5 5 L10 5 L10 10 Z L20 20");               // a drawing command after Z, with no M, starts a new subpath at the start point
out.afterZSubs = subpaths(parsePath("M5 5 L10 5 L10 10 Z L20 20 Z")).map((s) => [s.segments.length, s.closed]);
out.subs = subpaths(parsePath("M0 0 L1 1 Z M5 5 L6 6")).map((s) => [s.segments.length, s.closed]);
const fails = (d) => { try { parsePath(d); return null; } catch (e) { return e.message; } };
out.arc = fails("M0 0 A5 5 0 0 1 10 10");
out.unknown = fails("M0 0 X1 1");
out.short = fails("M0 0 L5");
out.stray = fails("5 5");
console.log(JSON.stringify(out));
""")
    assert got["absolute"] == [["M", 10, 20], ["L", 30, 40], ["L", 50, 40], ["L", 50, 60], ["C", 1, 2, 3, 4, 5, 6], ["Q", 7, 8, 9, 10], ["Z"]]
    assert got["relative"] == [["M", 10, 20], ["L", 15, 25], ["L", 20, 25], ["L", 20, 30], ["C", 21, 31, 22, 32, 23, 33], ["Q", 24, 34, 25, 33], ["Z"]]
    assert got["implicit"] == [["M", 0, 0], ["L", 10, 10], ["L", 20, 0]]
    assert got["smooth"][2] == ["C", 10, -10, 20, -10, 20, 0], "S reflects (10, 10) about (10, 0) to (10, -10)"
    assert got["quad"][2] == ["Q", 15, -10, 20, 0], "T reflects (5, 10) about (10, 0) to (15, -10)"
    assert got["chain"] == [["M", 76, 156], ["Q", 82, 162, 88, 156], ["Q", 94, 162, 100, 156]]
    assert got["numbers"] == [["M", -1.5, -2.5], ["L", 0.5, 2.5]]
    assert got["closeBack"][-1] == ["L", 6, 6], "after Z the current point is the subpath's start (5, 5)"
    assert got["smoothRel"][2] == ["C", 10, -10, 20, -10, 20, 0], "relative s reflects the last control about the current point (10, 0)"
    assert got["quadRel"][2] == ["Q", 15, -10, 20, 0], "relative t reflects (5, 10) about (10, 0)"
    assert got["afterZ"] == [["M", 5, 5], ["L", 10, 5], ["L", 10, 10], ["Z"], ["M", 5, 5], ["L", 20, 20]], "a draw after Z starts a new subpath where the closed one started"
    assert got["afterZSubs"] == [[4, True], [3, True]], "and it is its own subpath, not a tail of the closed one"
    assert got["subs"] == [[3, True], [2, False]]
    assert "arc" in got["arc"] and got["unknown"] and got["short"] and got["stray"], "an arc, a command the grammar lacks, a short group and a stray number all throw"


@needs_node
def test_a_path_becomes_shapes_standing_on_an_origin_with_y_up_and_each_axis_can_be_stretched(tmp_path):
    got = run_node(tmp_path, r"""
import * as THREE from "@JS@/three.js";
import { pathToShapes, ellipseToShape, strokeTriangles } from "@JS@/scene/svgpath.js";
const box = (shape) => { const pts = shape.getPoints(24); return [Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)), Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y))].map((v) => +v.toFixed(3)); };
const out = {};
out.square = box(pathToShapes(THREE, "M10 10 H30 V40 H10Z", { originX: 20, originY: 40 })[0]);   // 20 by 30 on the bottom middle
out.stretched = box(pathToShapes(THREE, "M10 10 H30 V40 H10Z", { originX: 20, originY: 40, scaleX: 0.5, scaleY: 2 })[0]);
out.down = box(pathToShapes(THREE, "M0 0 H10 V10 H0Z", { flipY: false })[0]);
out.two = pathToShapes(THREE, "M0 0 L1 0 L1 1Z M5 5 L6 5 L6 6Z").length;
out.open = pathToShapes(THREE, "M0 0 L4 0 L4 4")[0].getPoints().length >= 3;          // an open subpath is closed as a fill does
out.circle = box(ellipseToShape(THREE, 74, 98, 22, 22, { originX: 100, originY: 186 }));
// a curve really curves: the Q control point pulls the shape out of its chord
out.curve = box(pathToShapes(THREE, "M0 0 Q5 10 10 0Z", { flipY: false })[0])[3];
const tri = strokeTriangles([[0, 0], [10, 0]], 2, false, 4);
out.stroke = [tri.length % 9, Math.max(...tri.filter((_, i) => i % 3 === 1))];
console.log(JSON.stringify(out));
""")
    assert got["square"] == [-10, 10, 0, 30]
    assert got["stretched"] == [-5, 5, 0, 60]
    assert got["down"] == [0, 10, 0, 10]
    assert got["two"] == 2 and got["open"] is True
    assert got["circle"][0] == -48.0 and got["circle"][1] == -4.0 and got["circle"][3] - got["circle"][2] == 44.0, "a circle of radius 22 at (74, 98), seen from the owl's feet"
    assert 4.9 < got["curve"] < 5.1, "a quadratic's apex is half the control's height"
    assert got["stroke"][0] == 0 and got["stroke"][1] >= 1, "a stroke is whole triangles, a width wide"


# --- the owl ----------------------------------------------------------------------------------------------------------------------------

def test_the_owl_module_holds_the_marks_six_colours_and_the_parts_the_shadow_and_the_next_package_start_from():
    owl = (SCENE / "owl.js").read_text(encoding="utf-8")
    assert sorted(re.findall(r"#[0-9A-Fa-f]{6}\b", owl)) == sorted(["#1E1B2E", "#6B4429", "#A47551", "#E6D2BC", "#FFFFFF", "#FCD34D"]), "the mark's palette and nothing else"
    ids = re.findall(r'\{ id: "([a-z-]+)", kind:', owl)
    mark = ["ear-left", "ear-right", "foot-left", "foot-right", "body", "wing-left", "wing-right", "face", "eye-left", "eye-right", "pupil-left", "pupil-right", "glint-left", "glint-right", "beak"]
    # R-41 (R4-B2): the parts the poses add: the lids, the rings round the eyes and the brows over them, the two chains of feathers, the raised wing, the shut eyes, the shadow on the floor;
    # then the working owl's own (turned three-quarters to its desk, with its two wings)
    added = ["lid-left", "lid-right", "ring-left", "ring-right", "brow-left", "brow-right", "chain-top", "chain-low", "wing-wave", "shut-left", "shut-right", "closed-left", "closed-right", "shadow"]
    working = ["w-ear-left", "w-ear-right", "w-foot-left", "w-foot-right", "w-face", "w-eye-left", "w-eye-right", "w-pupil-left", "w-pupil-right", "w-glint-left", "w-glint-right",
               "w-lid-left", "w-lid-right", "w-ring-left", "w-ring-right", "w-brow-left", "w-brow-right", "w-beak", "w-hand-far", "w-hand-near"]
    assert ids == mark + added + working, "the mark's parts, back to front, and what the three poses add to them"
    assert 'from "./svgpath.js"' in owl and "three.js" not in owl and "export function partShapes(THREE," in owl, "the owl takes the library as an argument, as the parser does"


@needs_node
def test_the_owls_parts_are_shapes_on_its_feet_and_its_outline_is_the_body_and_two_ears(tmp_path):
    got = run_node(tmp_path, r"""
import * as THREE from "@JS@/three.js";
import { OWL_PARTS, OWL_PALETTE, owlOutline, owlPart, partShapes, partStroke } from "@JS@/scene/owl.js";
const box = (shape) => { const pts = shape.getPoints(24); return [Math.min(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.x)), Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.y))].map((v) => +v.toFixed(1)); };
const out = {};
out.parts = OWL_PARTS.filter((p) => p.fill).map((p) => [p.id, partShapes(THREE, p).length, new THREE.ShapeGeometry(partShapes(THREE, p)).getAttribute("position").count > 0]);   // a ring, a brow and a chain are ink alone: no fill
const outline = owlOutline(THREE);
out.body = box(outline.body);
out.ears = outline.ears.map(box);
out.fitted = box(owlOutline(THREE, { scaleX: 0.01, scaleY: 0.02 }).body);
out.stroked = [partStroke(THREE, owlPart("body")).length > 0, partStroke(THREE, owlPart("pupil-left"))];
out.fills = OWL_PARTS.map((p) => p.fill).filter(Boolean).every((f) => Object.values(OWL_PALETTE).includes(f));
console.log(JSON.stringify(out));
""")
    assert all(count == 1 and drawn for _, count, drawn in got["parts"]), "every part is one shape with triangles"
    assert got["body"][0] == -80.0 and got["body"][1] == 80.0 and got["body"][2] == 0.0, "the body stands on the feet (y 0) and is 160 wide"
    assert got["ears"][0][3] > 100 and got["ears"][1][3] > 100 and got["ears"][0][1] < 0 < got["ears"][1][0] or got["ears"][0][0] < got["ears"][1][0], "the ears are on both sides, above the body's top"
    assert got["fitted"] == [-0.8, 0.8, 0.0, got["fitted"][3]], "the outline is stretched to a window by each axis"
    assert got["stroked"][0] is True and got["stroked"][1] is None, "a part with an ink outline has stroke triangles; a pupil has none"
    assert got["fills"] is True


# --- the colours of the City ------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_citys_tones_are_the_recipes_of_scene_css_in_light_and_in_dark_and_the_mark_is_the_same_amber_in_both(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
import { mixSrgb } from "@JS@/scene/palette.js";
const hex = (col) => col.getHexString();
const T2 = { ...T, bgToken: c(0xffffff), muted: c(0xf3f4f6), emphasis: c(0xe5e7eb), textMuted: c(0x676d7b), text: c(0x000000), warn: c(0xd97706), border: c(0xd1d5db) };
const dark = { ...T2, bgToken: c(0x000000), muted: c(0x000000), emphasis: c(0x1f2937), textMuted: c(0x9ca3af), text: c(0xffffff), warn: c(0xf59e0b), border: c(0x374151) };
const mix = (a, b, t) => mixSrgb(a, b, t);
const light = { dark: false, T: T2, bg: c(0xffffff), mix, inDark: { warn: dark.warn, text: dark.text, bgToken: dark.bgToken } };
const night = { dark: true, T: dark, bg: c(0x111827), mix, inDark: { warn: dark.warn, text: dark.text, bgToken: dark.bgToken } };
const L = cityTones(light);
const N = cityTones(night);
const out = {};
out.mixHalf = hex(mixSrgb(c(0x000000), c(0xffffff), 0.5));    // half way in the encoded channels, not in the linear working space: 0x808080
out.litLight = [hex(L.glassLit), hex(mixSrgb(light.bg, T2.warn, 0.34))];
out.litDark = [hex(N.glassLit), hex(mixSrgb(dark.text, dark.theme || T.theme, 0.36))];
out.markSame = [L.mark.top.equals(N.mark.top), L.mark.left.equals(N.mark.left), L.mark.right.equals(N.mark.right), hex(L.mark.right) === hex(dark.warn)];
out.roofIsBrand = [hex(L.roofFloor) === hex(T.theme), hex(N.roofFloor) === hex(T.theme), hex(L.bracket) === hex(T.theme)];
out.lightDiffers = [L.road.equals(N.road), L.grass.equals(N.grass), L.glass.equals(N.glass), L.shell.right.equals(N.shell.right)];
out.faces = [Object.keys(L.shell), Object.keys(L.roof), Object.keys(L.ledge), Object.keys(L.unit), Object.keys(L.mark)];
out.crown = [L.crown.length, N.crown.length];
console.log(JSON.stringify(out));
""")
    assert got["mixHalf"] == "808080", "color-mix(in srgb) is a blend of the encoded channels"
    assert got["litLight"][0] == got["litLight"][1] and got["litDark"][0] == got["litDark"][1], "R-18: raised with the warn colour in light, the text with the brand's brown in dark"
    assert got["markSame"] == [True, True, True, True], "R-20: the same amber in light and in dark, from the dark scheme's tokens"
    assert got["roofIsBrand"] == [True, True, True], "the roof and the brackets are the brand colour, the token"
    assert got["lightDiffers"] == [False, False, False, False], "light and dark are different recipes"
    assert all(keys == ["top", "left", "right"] for keys in got["faces"]), "a solid is given its three visible faces, each a tone"
    assert got["crown"] == [4, 4], "a crown has four tones"


def test_palette_reads_the_dark_scheme_for_the_mark_and_mixes_in_the_encoded_space():
    palette = (SCENE / "palette.js").read_text(encoding="utf-8")
    assert 'probe.style.setProperty("color-scheme", "dark")' in palette, "the mark's amber is read from the dark scheme's tokens even in light"
    assert "const mix = mixSrgb;" in palette and "convertLinearToSRGB" in palette, "a mix is the stylesheet's, in the encoded space"
    assert "warm: dark ? mix(T.text, T.theme, 0.36) : mix(bg, T.warn, 0.34)" in palette, "R-18: the lit window's recipe"


# --- the motions ------------------------------------------------------------------------------------------------------------------------

@needs_node
def test_the_agents_shadow_and_the_notification_follow_the_stylesheets_keyframes(tmp_path):
    got = run_node(tmp_path, r"""
import { AGENT_SECONDS, ALERT_SECONDS, ALERT_RISE, COME, COME_Y, LEAVE, LEAVE_UP, agentPose, agentRest, alertPose, cubicBezier, easeInOut, sample, windowOffset, windowSide } from "@JS@/scene/city-motion.js";
const near = (a, b) => Math.abs(a - b) < 1e-6;
const out = {};
out.bezier = [easeInOut(0), easeInOut(1), +easeInOut(0.5).toFixed(6), easeInOut(0.25) < 0.25, easeInOut(0.75) > 0.75, cubicBezier(0, 0, 1, 1)(0.3).toFixed(3)];
let mono = true; let last = 0; for (let i = 0; i <= 100; i++) { const v = easeInOut(i / 100); if (v < last) mono = false; last = v; } out.mono = mono;
out.sample = [sample([[0, 0], [1, 10]], 0), +sample([[0, 0], [1, 10]], 0.5).toFixed(6), sample([[0, [0, 0]], [0.5, [2, 4]], [1, [2, 4]]], 0.25).map((v) => +v.toFixed(6))];
// a window whose phase is 0 at t = 48 - offset
const k = 1; const floor = 0;
const t0 = AGENT_SECONDS - windowOffset(k, floor) + AGENT_SECONDS;      // phase 0
const at = (percent) => agentPose(t0 + (percent / 100) * AGENT_SECONDS, k, floor);
out.start = [at(0).opacity, at(0).scale, at(0).x === windowSide(k, floor) * COME, at(0).y === COME_Y, COME_Y];
out.arrived = [at(7).opacity, at(7).scale, at(7).x, at(7).y];
out.standing = [at(19.5).opacity, at(19.5).scale];
out.leaving = [at(23).opacity > 0.3 && at(23).opacity < 0.4, at(25).opacity, at(25).scale, near(at(25).x, -windowSide(k, floor) * LEAVE), near(at(25).y, LEAVE_UP)];
out.empty = [at(60).opacity, at(99.9).opacity];
out.period = near(agentPose(10, 2, 1).opacity, agentPose(10 + AGENT_SECONDS, 2, 1).opacity) && near(agentPose(10, 2, 1).x, agentPose(10 + AGENT_SECONDS, 2, 1).x);
// the four windows of a floor take their turns: each is up for about a quarter of the cycle, the windows' times do not overlap by much and none is skipped
const seen = [0, 1, 2, 3].map((w) => { let n = 0; for (let s = 0; s < AGENT_SECONDS; s += 0.5) if (agentPose(s, w, 0).opacity > 0.3) n += 1; return n * 0.5; });
const overlap = []; for (let s = 0; s < AGENT_SECONDS; s += 0.5) overlap.push([0, 1, 2, 3].filter((w) => agentPose(s, w, 0).opacity > 0.3).length);
out.turns = [seen.every((v) => v > 7 && v < 13), Math.max(...overlap), Math.min(...overlap)];
out.floorsDiffer = agentPose(5, 0, 0).opacity !== agentPose(5, 0, 1).opacity || agentPose(5, 1, 0).opacity !== agentPose(5, 1, 1).opacity;
out.sides = [0, 1, 2, 3].map((w) => windowSide(w, 0)).concat([0, 1, 2, 3].map((w) => windowSide(w, 2)));
out.rest = [0, 1, 2, 3].map((w) => agentRest(w).opacity);
// the notification: rest, rise, three shakes, settle; 3.4 s
const a = (percent) => alertPose((percent / 100) * ALERT_SECONDS);
out.alert = [a(0), a(58), a(64), a(69), a(74), a(79), a(84), a(89), a(95), a(100)].map((p) => [+p.rise.toFixed(3), +p.roll.toFixed(3)]);
out.alertPeriod = near(alertPose(1.234).rise, alertPose(1.234 + ALERT_SECONDS).rise) && near(alertPose(2.3).roll, alertPose(2.3 + ALERT_SECONDS).roll);
out.alertBetween = alertPose(0.665 * ALERT_SECONDS).roll;
out.constants = [AGENT_SECONDS, ALERT_SECONDS, ALERT_RISE];
console.log(JSON.stringify(out));
""")
    assert got["bezier"][:2] == [0, 1] and got["bezier"][2] == 0.5 and got["bezier"][3] is True and got["bezier"][4] is True and got["bezier"][5] == "0.300", "ease-in-out is cubic-bezier(.42 0 .58 1)"
    assert got["mono"] is True
    assert got["sample"][:2] == [0, 5] and got["sample"][2][0] > 0 and got["sample"][2][1] > 0 and got["sample"][2][1] == 2 * got["sample"][2][0], "values are eased between two keyframes, element by element"
    assert got["start"] == [0, 0.28, True, True, -0.022], "it starts small, faint, to one side and a hair low: x, y and scale arrive together (R-19; the page's --ax -13.2, --ay -7.2)"
    assert got["arrived"] == [0.62, 1, 0, 0], "7 percent: at its window, full size, opacity .62"
    assert got["standing"] == [0.62, 1], "it stands at the glass from 7 to 19.5 percent (about 6 s)"
    assert got["leaving"] == [True, 0, 0.3, True, True], "it fades from 23 percent, is gone at 25 and has walked off the other way, shrunk"
    assert got["empty"] == [0, 0], "the window stays empty for the rest of the cycle"
    assert got["period"] is True, "a 48 s cycle"
    assert got["turns"][0] is True and got["turns"][1] <= 2 and got["turns"][2] >= 0, "each window of a floor has about a quarter of the cycle, and few at once"
    assert got["floorsDiffer"] is True, "the floors are shifted against one another"
    assert got["sides"] == [-1, 1, -1, 1, 1, -1, 1, -1], "the shadow comes from alternate sides along a floor, and from the other side two floors up"
    assert got["rest"] == [0, 0.62, 0, 0], "reduced motion: one still figure"
    assert got["alert"] == [[0, 0], [0, 0], [0.3, 0], [0.3, -13], [0.3, 11], [0.3, -8], [0.3, 5], [0.3, 0], [0, 0], [0, 0]], "rest, rise, shake left, right, left, right, settle"
    assert got["alertPeriod"] is True and -13 < got["alertBetween"] < 0
    assert got["constants"] == [48, 3.4, 0.3]


# --- the batches and the ground ---------------------------------------------------------------------------------------------------------

@needs_node
def test_a_batch_bakes_solids_into_one_mesh_with_a_colour_a_vertex_and_the_ground_is_a_handful_of_draws(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
import { buildGround, lotAt, blockKind, treesOf, hash, PITCH_X, PITCH_Z, BLOCK_W, STREET, KERB, MARGIN_X, ROWS } from "@JS@/scene/city.js";
const kit = createKit(palette);
const out = {};
const group = new THREE.Group();
const b = kit.batch();
b.box(1, 1, 1, 0, 0, 0, palette.T.theme).flat(0, 0, 1, 1, 0, palette.T.warn).front(0, 0, 1, 1, 0, palette.T.warn).side(0, 0, 1, 1, 0, palette.T.warn);
out.triangles = b.count();
const mesh = b.mesh(group);
const colour = mesh.geometry.getAttribute("color");
out.colour = [mesh.geometry.getAttribute("position").count, colour.count, colour.itemSize, mesh.material === kit.vertexMaterial, mesh.castShadow];
out.empty = kit.batch().mesh(group);
const two = kit.batch(); two.box(1, 1, 1, 0, 0, 0, { top: palette.T.theme, left: palette.T.warn, right: palette.T.success });
const m2 = two.mesh(group, { cast: false });
const col = m2.geometry.getAttribute("color");
out.faces = [0, 6, 12].map((i) => [col.getX(i), col.getY(i), col.getZ(i)].map((v) => +v.toFixed(3)).join(",")).length;   // top, left, right: three tones
out.toneOfFirstFace = [col.getX(0) === Math.fround(palette.T.theme.r), col.getX(6) === Math.fround(palette.T.warn.r), col.getX(12) === Math.fround(palette.T.success.r)];
// the ground
const ground = buildGround(kit, 2);
let meshes = 0; let instanced = 0; let triangles = 0;
ground.group.traverse((n) => { if (n.isInstancedMesh) instanced += 1; else if (n.isMesh) meshes += 1; });
out.ground = [meshes, instanced, ground.trees > 100];
out.same = buildGround(createKit(palette), 2).trees === ground.trees;
out.lots = [lotAt(0, 1), lotAt(0, 2).x + lotAt(1, 2).x, +(lotAt(1, 3).x - lotAt(0, 3).x).toFixed(3), PITCH_X.toFixed(3)];
out.kinds = [blockKind(0, 0, 2), blockKind(1, 0, 2), blockKind(2, 0, 2), blockKind(0, 1, 2), blockKind(1, 1, 2), blockKind(-1, 0, 2), blockKind(0, -1, 2)];
out.lot = treesOf("lot", 0, 0).length;
out.hash = [hash(1, 2, 3) === hash(1, 2, 3), hash(1, 2, 3) !== hash(1, 2, 4), hash(7, 7, 7) >= 0 && hash(7, 7, 7) < 1];
out.sizes = [BLOCK_W, STREET, KERB, MARGIN_X, ROWS];
const lotsWorld = buildWorld(kit, model());
let all = 0; lotsWorld.group.traverse((n) => { if (n.isMesh) all += 1; });
out.world = all;
console.log(JSON.stringify(out));
""")
    assert got["triangles"] == 6 + 2 + 2 + 2, "a solid is its three visible faces (six triangles), a flat or a plane two"
    assert got["colour"] == [36, 36, 3, True, True], "one colour for every vertex, drawn with the kit's one vertex-colour material, casting a shadow"
    assert got["empty"] is None
    assert got["toneOfFirstFace"] == [True, True, True], "the top, the left face and the right face each take their own tone"
    assert got["ground"][0] == 3 and got["ground"][1] == 2 and got["ground"][2] is True, "the ground is three batches and two instanced meshes (crowns, trunks), however many blocks"
    assert got["same"] is True, "the same city every time"
    assert got["lots"][0] == {"x": 0, "z": 0} and got["lots"][1] == 0 and got["lots"][2] == float(got["lots"][3]), "the lots stand one block apart, in a row centred on the origin"
    assert got["kinds"] == ["lot", "lot", "plaza", "park", "plaza", "park", "park"], "a lot's block holds a project; the others alternate between a paved square and a park"
    assert got["lot"] == 4, "four trees at the corners of a lot's block"
    assert got["hash"] == [True, True, True]
    assert got["world"] < 120, "three buildings of four floors and the whole ground: fewer than 120 meshes (the budget; before round 4 the same world was about three times that)"


# --- the building ------------------------------------------------------------------------------------------------------------------------

STATES_JS = WORLD_JS + r"""
import { openings } from "@JS@/scene/tower.js";
const kit = createKit(palette);
const meshes = (root) => { const out = []; root.traverse((n) => { if (n.isMesh) out.push(n); }); return out; };
const marksOf = (tower) => tower.overlay.children.filter((c) => c.userData.mark);
const markIn = (tower, i) => marksOf(tower).filter((m) => m.userData.floor === i).length;
const agentIn = (tower, i) => tower.floorGroups[i].children.filter((c) => c.children.length && c.children.every((w) => w.children[0] && w.children[0].isMesh && w.children[0].renderOrder === 2));
"""


@needs_node
def test_a_lit_floor_has_the_agent_at_its_windows_and_only_a_lit_floor_that_waits_has_a_mark(tmp_path):
    got = run_node(tmp_path, STATES_JS + r"""
const waiting = { state: "waiting", window: "lit", decisions: 2 };
const world = buildWorld(kit, model({ lots: [lot("a", { floors: [
  { ...lot("x").floors[0] },                                                    // planning: idle, dark
  { ...lot("x").floors[1], state: "working", window: "lit", decisions: 0 },     // working: lit, no mark (R-21)
  { ...lot("x").floors[2], ...waiting },                                        // waiting: lit, a mark
  { ...lot("x").floors[3], state: "idle", window: "grey", decisions: 1 },       // a decision on a dark floor: no mark
] }), lot("b", { accepted: false, floors: [{ ...lot("x").floors[1], state: "off", window: "grey", decisions: 3 }] })] }));
const a = world.towers.get("a");
const out = {};
out.marks = [0, 1, 2, 3].map((i) => markIn(a, i));
out.agents = [0, 1, 2, 3].map((i) => (a.floorGroups[i].children.some((c) => c.visible && c.children.length === openings(i).front.filter((o) => o.kind === "glass").length && c.children[0].children[0] && c.children[0].children[0].renderOrder === 2) ? 1 : 0));
const windowsOf = (i) => openings(i).front.filter((o) => o.kind === "glass").length;
out.windows = [windowsOf(0), windowsOf(1)];
out.motions = a.motions.length;
out.unaccepted = [markIn(world.towers.get("b"), 0), world.towers.get("b").motions.length];
// the motions: a mark rises and tilts, a shadow comes to its window; both still under reduced motion
const tilt = (t) => { a.motions.forEach((m) => m.tick(t)); const g = marksOf(a).find((c) => c.userData.floor === 2); return [+g.position.y.toFixed(3), +g.quaternion.w.toFixed(4), g.quaternion.x !== 0 || g.quaternion.y !== 0 || g.quaternion.z !== 0]; };
out.tilt = [tilt(0), tilt(0.69 * 3.4), tilt(0.95 * 3.4 + 3.4)];
a.motions.forEach((m) => m.rest());
const still = marksOf(a).find((c) => c.userData.floor === 2);
out.rest = [+still.position.y.toFixed(3), still.quaternion.w];
const holder = a.floorGroups[1].children.find((c) => c.children.length === 4);
out.shadows = holder.children.map((w) => +w.children[0].material.opacity.toFixed(2));
out.depth = [holder.children[0].children[0].material.depthFunc === THREE.LessDepth, holder.children[0].children[0].material.transparent, holder.children[0].children[0].castShadow];
// the brackets are built hidden, apart from the tower, and follow the roof
out.brackets = world.brackets.map((b) => [b.id, b.group.visible, b.tower.brackets.closed, world.group.children.includes(b.group), a.root.children.includes(b.group)]);
console.log(JSON.stringify(out));
""")
    assert got["marks"] == [0, 0, 1, 0], "R-20, R-21: one mark, beside the one floor that is lit and waits; a floor that works has none, nor has a dark floor with a decision"
    assert got["agents"] == [0, 1, 1, 0], "R-19: the agent shows at the windows of the lit floors (the working one and the waiting one), not at the dark ones"
    assert got["windows"] == [3, 4], "four windows on an upper floor, three beside the shop's door on the ground floor"
    assert got["unaccepted"] == [0, 0], "a project that is not accepted has no mark and no figure"
    # the foot of the mark on floor 2 of a closed building: the slab's top (6.4) squashed to 0.64 of its height over the block (0.2), 0.15 above it
    foot = round(0.2 + 0.64 * (6.4 - 0.2) + 0.15, 3)
    assert got["tilt"][0][0] == foot and got["tilt"][0][2] is False, "at rest the mark stands on its foot, beside the floor"
    assert got["tilt"][1][0] == round(foot + 0.3, 3) and got["tilt"][1][2] is True, "R-20: it rises and shakes (a turn about the view axis)"
    assert got["tilt"][2][0] == foot, "and it settles"
    assert got["rest"] == [foot, 1], "reduced motion: the mark is still"
    assert got["shadows"] == [0, 0.62, 0, 0], "reduced motion: one still figure at its window"
    assert got["depth"] == [True, True, False], "the shadow is a transparent figure drawn once where its ears cross its body, and it casts no shadow"
    assert [b[1:] for b in got["brackets"]] == [[False, True, True, False]] * 2, "built hidden, closed, in the world beside the tower and not in it (the pointer picks the building, never its marks)"


@needs_node
def test_a_window_is_lit_glass_dark_glass_or_the_walls_own_tone_and_a_floor_has_the_walls_of_its_openings(tmp_path):
    got = run_node(tmp_path, STATES_JS + r"""
const tones = cityTones(palette);
const world = buildWorld(kit, model({ lots: [lot("a"), lot("b", { accepted: false })] }));
const tower = world.towers.get("a");
const paintOf = (t, i) => { const g = t.floorGroups[i].children[0].children[1].geometry.getAttribute("color"); return [g.getX(0), g.getY(0), g.getZ(0)]; };
const same = (rgb, col) => Math.abs(rgb[0] - col.r) < 1e-6 && Math.abs(rgb[1] - col.g) < 1e-6 && Math.abs(rgb[2] - col.b) < 1e-6;
const out = {};
out.lit = same(paintOf(tower, 1), tones.glassLit);                // the working floor: warm white
out.dark = same(paintOf(tower, 2), tones.glass);                  // an upper floor at rest
out.shop = same(paintOf(tower, 0), tones.store);                  // the ground floor's glass is the shop front's tone
out.off = [0, 1, 2, 3].every((i) => same(paintOf(world.towers.get("b"), i), tones.glassOff));   // not accepted: every window the wall's own tone
out.parts = tower.floorGroups[1].children.filter((c) => c.children.length).length;
out.shell = tower.floorGroups[1].children[0].children.map((m) => m.isMesh);
out.upper = [openings(1).front.length, openings(1).right.length, openings(0).front.map((o) => o.kind), openings(0).right.length];
const tall = (o) => +(o.top - o.bottom).toFixed(6);
out.heights = [tall(openings(1).front[0]), tall(openings(0).front[2]), tall(openings(0).front[1])];
// a window changes colour in place: no mesh is replaced
const before = new Set(); tower.group.traverse((n) => { if (n.isMesh) before.add(n); });
const next = JSON.parse(JSON.stringify(world.update ? model({ lots: [lot("a"), lot("b", { accepted: false })] }) : {}));
next.lots[0].floors[2].window = "lit";
world.update(next);
const after = new Set(); tower.group.traverse((n) => { if (n.isMesh) after.add(n); });
out.inPlace = [[...before].every((m) => after.has(m)), same(paintOf(tower, 2), tones.glassLit)];
// the pitch of a closed floor is the room's: the shell stands on the same floors the rooms do
out.floors = tower.floorGroups.map((g) => +g.position.y.toFixed(3));
console.log(JSON.stringify(out));
""")
    assert got["lit"] is True and got["dark"] is True and got["shop"] is True and got["off"] is True
    assert got["shell"] == [True, True], "a floor's shell is two batched meshes: the walls and the glass"
    assert got["upper"][0] == 4 and got["upper"][1] == 3 and got["upper"][2] == ["glass", "door", "glass", "glass"] and got["upper"][3] == 2
    assert got["heights"][0] == 2.0 and got["heights"][1] == 2.2 and got["heights"][2] == 2.4, "windows nearly the floor's height (2.0 of 2.8), the shop front 2.2, the door 2.4"
    assert got["inPlace"] == [True, True], "a floor that becomes lit is repainted: no mesh is replaced"
    assert got["floors"] == [0.2, 3.2, 6.2, 9.2]


@needs_node
def test_the_roof_is_the_brand_colour_with_a_parapet_and_two_units_and_the_ring_stays_while_a_task_runs(tmp_path):
    got = run_node(tmp_path, STATES_JS + r"""
const world = buildWorld(kit, model());
const a = world.towers.get("a"); const b = world.towers.get("b");
const roofOf = (t) => t.group.children[t.group.children.length - 2];
const out = {};
out.beacon = [Boolean(a.beacon), Boolean(b.beacon), a.beacons === undefined];
out.ring = [a.beacon.ring.geometry.parameters.radius, a.beacon.material.transparent];
const roof = a.group.children.find((c) => c.children.length >= 1 && c.children.some((m) => m.isMesh && m !== a.beacon.ring && m.geometry.getAttribute("color")));
out.roofMeshes = roof.children.filter((m) => m.isMesh).length;       // the body's batch, the ring and its core
out.closed = a.brackets.closed;
// the card above the roof, the camera frames the lots and their blocks
const subject = world.subject();
out.subject = [subject.min.x < 0, subject.max.x > 0, subject.max.y > 8 && subject.max.y < 11];   // squashed: four floors are 12 high open, 7.9 closed
// a roof bracket follows the roof when the building opens
world.setFocus("a", true);
out.opened = [a.brackets.closed, a.brackets.roof.position.y > 12];
console.log(JSON.stringify(out));
""")
    assert got["beacon"][:2] == [True, False], "a ring on the roof of a running project only"
    assert got["ring"] == [0.95, True]
    assert got["roofMeshes"] == 3, "the roof's batch, the ring and its core"
    assert got["closed"] is True and got["opened"][0] is False, "the brackets are drawn only while the building is closed"
    assert got["subject"] == [True, True, True]


# --- the label, the style sheet, the page -----------------------------------------------------------------------------------------------

@needs_node
def test_the_label_of_a_building_is_a_one_line_pill_a_quiet_one_is_a_dot_and_the_chip_says_not_accepted(tmp_path):
    got = run_node(tmp_path, r"""
import { find, all } from "@FAKE@";
import { cityCard } from "@JS@/scene/labels.js";
const text = (n) => n.textContent !== undefined ? n.textContent : "";
const pill = cityCard({ name: "northwind-shop", sub: "task #52 running", running: true, decisions: 2, accepted: true, selected: true, quiet: false });
const quiet = cityCard({ name: "lab", sub: "no task running", running: false, decisions: 0, accepted: true, selected: false, quiet: true });
const off = cityCard({ name: "tinykv-docs", sub: "not accepted yet", running: false, decisions: 0, accepted: false, selected: false, quiet: false });
console.log(JSON.stringify({
  classes: [pill.cls(), quiet.cls(), off.cls()],
  names: [find(pill, ".wb-pill-name") && text(find(pill, ".wb-pill-name")), text(find(pill, ".wb-pill-sub")), find(pill, ".wb-dot").cls()],
  badge: [text(find(pill, ".pui-badge")), find(off, ".pui-chip") && text(find(off, ".pui-chip")), find(quiet, ".pui-badge")],
  order: pill.children.map((c) => c.cls()[0] || c.cls()),
}));
""")
    assert got["classes"][0].count("wb-pill") == 1 and "is-selected" in got["classes"][0] and "wb-label" in got["classes"][0]
    assert "is-quiet" in got["classes"][1] and "is-quiet" not in got["classes"][0] and "is-quiet" not in got["classes"][2]
    assert got["names"][0] == "northwind-shop" and got["names"][1] == "task #52 running" and "is-running" in got["names"][2]
    assert got["badge"] == ["2", "Not accepted", None], "the count of decisions, or the chip of a project that is not accepted"
    assert got["order"] == ["wb-dot", "wb-pill-name", "wb-pill-sub", "pui-badge"], "a dot, the name, what it does, the count: one line"


def test_the_scenes_style_sheet_is_linked_once_after_the_pages_and_holds_no_colour_of_its_own():
    css = (INTERFACE / "scene.css").read_text(encoding="utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|oklch\(|oklab\(", css), "scene.css names tokens only: no colour literal"
    for name in (".wb-pill", ".wb-pill.is-selected", ".wb-pill.is-quiet", ".wb-pill-name", ".wb-pill-sub", ".wb-pill.is-culled"):
        assert name in css, f"scene.css draws {name}"
    assert "var(--pui-theme)" in css and "var(--wb-raised)" in css and "var(--pui-border)" in css
    page = (INTERFACE / "index.html").read_text(encoding="utf-8")
    assert page.count('href="./scene.css"') == 1 and all(page.index(f'href="./css/{path.name}"') < page.index('href="./scene.css"') for path in css_paths()), "scene.css is loaded once, after the page's stylesheets"
    assert "<style" not in page and "style=" not in page, "no inline style: the service's policy forbids it"


def test_the_engine_marks_a_building_with_brackets_never_an_outline_and_the_shade_lies_over_the_blocks():
    engine = (SCENE / "engine.js").read_text(encoding="utf-8")
    assert "b.group.visible = b.tower.brackets.closed && (b.id === hoverId || b.id === content.marked)" in engine, "R-17: pointed at or followed, and closed"
    assert "if (hit && !hit.brackets && !hit.marks)" in engine and "if (!hit || hit.brackets || hit.marks)" in engine, "a building of the City, or an object with brackets of its own (R-28, R-31), has no outline to draw"
    assert "SHADE_Y = 0.22" in engine and "ground.position.y = -0.06" in engine and "shade.position.y = SHADE_Y" in engine, "the shadows land over the paving, the void under the streets"
    world = (SCENE / "world.js").read_text(encoding="utf-8")
    assert "brackets: true" in world and "tower.brackets.group" in world


# --- a tower made again frees what it made, a mark needs a lit floor, and an agent that is off lights nothing ---------------------------------------

@needs_node
def test_a_tower_made_again_frees_every_geometry_it_made_and_keeps_none_but_the_shared_ones(tmp_path):
    got = run_node(tmp_path, WORLD_JS + r"""
const made = new Set(); const gone = new Set();
const setAttribute = THREE.BufferGeometry.prototype.setAttribute; const dispose = THREE.BufferGeometry.prototype.dispose;
THREE.BufferGeometry.prototype.setAttribute = function (...a) { made.add(this); return setAttribute.apply(this, a); };
THREE.BufferGeometry.prototype.dispose = function () { gone.add(this); return dispose.call(this); };
const kit = createKit(palette);
const world = buildWorld(kit, model({ lots: [lot("a", { floors: [
  lot("x").floors[0], { ...lot("x").floors[1], state: "working", window: "lit" }, { ...lot("x").floors[2], state: "waiting", window: "lit", decisions: 2 }, lot("x").floors[3]] }), lot("b")] }));
world.setFocus("a", true);   // its rooms are in: they are freed with it too
const live = () => { const out = new Set(); world.group.traverse((n) => { if (n.geometry) out.add(n.geometry); }); return out; };
const leaked = () => { const alive = live(); return [...made].filter((g) => !gone.has(g) && !alive.has(g) && g !== kit.unitBox && g !== kit.unitEdges).length; };
const out = { start: leaked() };
for (let i = 0; i < 8; i++) {   // the structure changes when a task starts or ends: the tower is made again
  const next = JSON.parse(JSON.stringify(model({ lots: [lot("a", { runningTask: i % 2 ? 5 : null, floors: [lot("x").floors[0], { ...lot("x").floors[1], state: "working", window: "lit" }, { ...lot("x").floors[2], state: "waiting", window: "lit", decisions: 2 }, lot("x").floors[3]] }), lot("b")], focus: "a" })));
  out["r" + i] = world.update(next).structure;
}
out.after = leaked();
out.live = live().size;
out.unitKept = [gone.has(kit.unitBox), gone.has(kit.unitEdges)];
out.shapes = made.size;
console.log(JSON.stringify(out));
""")
    assert all(got[f"r{i}"] is True for i in range(8)), "every update changed the running task, so the tower was made again each time"
    assert got["start"] == 0 and got["after"] == 0, "no geometry of a tower that was made again stays undisposed: only the live ones and the kit's shared unit box and edges remain"
    assert got["unitKept"] == [False, False], "the shared unit box and edges are never disposed"
    assert got["shapes"] > 100, "the test did build many geometries"


@needs_node
def test_a_mark_needs_a_lit_floor_and_an_agent_that_is_off_lights_no_window_in_either_model(tmp_path):
    got = run_node(tmp_path, STATES_JS + r"""
import * as modelJs from "@JS@/model.js";
import * as fm from "@JS@/floor-model.js";
const mk = (extra) => buildWorld(kit, model({ lots: [lot("a", { floors: [lot("x").floors[0], { ...lot("x").floors[1], ...extra }] })] }));
const out = {};
out.dark = markIn(mk({ state: "waiting", window: "grey", decisions: 2 }).towers.get("a"), 1);          // waiting but not lit: no mark
out.lit = markIn(mk({ state: "waiting", window: "lit", decisions: 2 }).towers.get("a"), 1);
out.working = markIn(mk({ state: "working", window: "lit", decisions: 2 }).towers.get("a"), 1);        // working: lit, but a floor that works has no mark
// an agent that is stopped or disabled with a decision: grey in both models (the City's and the Building's), as floor-model.stateOf says
const project = { id: "aaaaaaaaaaaa", name: "shop", config: { accepted: true }, running_task: null, open_pending: 2 };
const agents = [{ name: "planning", enabled: true, acting_mode: "supervised" }, { name: "design", enabled: false, acting_mode: "supervised" },
  { name: "brand", enabled: true, acting_mode: "stopped" }, { name: "marketing", enabled: true, acting_mode: "supervised" }];
const status = { requests: [], pending: [{ id: 1, task_id: 2, agent: "design", kind: "question", title: "q" }, { id: 2, task_id: 3, agent: "brand", kind: "question", title: "q" }, { id: 3, task_id: 4, agent: "marketing", kind: "question", title: "q" }] };
out.city = modelJs.buildingOf(project, { status, agents }).floors.map((f) => [f.agent, f.window]);
const view = fm.building({ projects: [project], details: { [project.id]: { status, agents: agents.map((a) => ({ ...a, mode: a.acting_mode, max_runs_per_day: 5, max_usd_per_day: 5, runs_today: 0, usd_today: 0, runs_without_cost: 0, queued: 0 })) } }, tasks: {}, loaded: true }, project.id);
out.building = view.rows.map((r) => [r.name, r.state, r.window]);
console.log(JSON.stringify(out));
""")
    assert got["dark"] == 0 and got["lit"] == 1 and got["working"] == 0, "R-21: a mark stands only beside a floor that is lit and waits"
    assert got["city"] == [["planning", "grey"], ["design", "grey"], ["brand", "grey"], ["marketing", "lit"]], "the City's model: a disabled or stopped agent with a decision stays dark; one that is active and waits is lit"
    assert got["building"] == [["planning", "idle", "grey"], ["design", "off", "grey"], ["brand", "off", "grey"], ["marketing", "waiting", "lit"]], "the Building's model says the same"
